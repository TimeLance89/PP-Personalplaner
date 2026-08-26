from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from pp.automation_engine import ensure_automation_schema
from pp.config import Settings
from pp.db import Database, utcnow
from pp.workflow_center import (
    ensure_workflow_schema,
    execute_due_actions,
    generate_briefing_for_user,
    inbox_for_user,
    plan_assignment_reviews,
)


class WorkflowCenterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "pp.sqlite3")
        self.db.initialize()
        ensure_automation_schema(self.db)
        ensure_workflow_schema(self.db)
        self.settings = Settings(
            host="127.0.0.1", port=8780, data_dir=Path(self.tmp.name), allowed_hosts=["*"],
            cookie_secure=False, session_hours=12, setup_token="setup-token", company_name="Test GmbH",
            company_contact="Disposition", smtp_host="", smtp_port=587, smtp_user="", smtp_password="",
            smtp_from="", smtp_starttls=True, smtp_ssl=False,
        )
        self.agency_id = self.db.execute(
            "INSERT INTO agencies(name,contact_name,email,phone,active) VALUES (?,?,?,?,1)",
            ("Test Zeitarbeit", "Kontakt", "dispo@example.test", ""),
        )
        self.department_id = self.db.execute(
            "INSERT INTO departments(name,code,active,custom_data) VALUES (?,?,1,'{}')",
            ("Versand", "VS"),
        )
        self.other_department_id = self.db.execute(
            "INSERT INTO departments(name,code,active,custom_data) VALUES (?,?,1,'{}')",
            ("Retouren", "RET"),
        )
        self.admin_id = self.db.execute(
            "INSERT INTO users(username,display_name,password_hash,role,department_id,active,created_at) VALUES (?,?,?,?,NULL,1,?)",
            ("admin", "Admin", "dummy", "admin", utcnow()),
        )
        self.leader_id = self.db.execute(
            "INSERT INTO users(username,display_name,password_hash,role,department_id,active,created_at) VALUES (?,?,?,?,?,1,?)",
            ("leiter", "Leitung Versand", "dummy", "leader", self.department_id, utcnow()),
        )
        self.other_leader_id = self.db.execute(
            "INSERT INTO users(username,display_name,password_hash,role,department_id,active,created_at) VALUES (?,?,?,?,?,1,?)",
            ("retoure", "Leitung Retouren", "dummy", "leader", self.other_department_id, utcnow()),
        )
        self.worker_id = self.db.execute(
            """INSERT INTO workers(first_name,last_name,employee_code,agency_id,start_date,status,notes,custom_data,created_at,updated_at)
               VALUES (?,?,?,?,?,'active','','{}',?,?)""",
            ("Max", "Muster", "ZA-1", self.agency_id, date.today().isoformat(), utcnow(), utcnow()),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _assignment(self, end_in_days: int = 7) -> int:
        return self.db.execute(
            """INSERT INTO assignments(worker_id,department_id,assigned_from,assigned_until,notes,created_by,created_at)
               VALUES (?,?,?,?, '', ?, ?)""",
            (
                self.worker_id,
                self.department_id,
                date.today().isoformat(),
                (date.today() + timedelta(days=end_in_days)).isoformat(),
                self.admin_id,
                utcnow(),
            ),
        )

    def test_assignment_end_creates_prepared_decision(self) -> None:
        assignment_id = self._assignment(7)
        values = {"workflow_assignment_review_enabled": True, "workflow_assignment_review_days": 7}
        created = plan_assignment_reviews(self.db, values, today=date.today())
        self.assertEqual(created, 1)
        scheduled = self.db.one("SELECT * FROM scheduled_actions WHERE entity_id=?", (assignment_id,))
        self.assertEqual(scheduled["state"], "scheduled")
        self.assertEqual(scheduled["scheduled_for"], date.today().isoformat())

        executed = execute_due_actions(self.db, today=date.today())
        self.assertEqual(executed, 1)
        item = self.db.one("SELECT * FROM workflow_inbox WHERE entity_type='assignment' AND entity_id=?", (assignment_id,))
        self.assertIsNotNone(item)
        self.assertEqual(item["state"], "needs_decision")
        self.assertEqual(item["department_id"], self.department_id)

    def test_leader_only_sees_own_department_inbox(self) -> None:
        self._assignment(7)
        plan_assignment_reviews(self.db, {"workflow_assignment_review_enabled": True, "workflow_assignment_review_days": 7}, today=date.today())
        execute_due_actions(self.db, today=date.today())
        leader = {"id": self.leader_id, "role": "leader", "department_id": self.department_id}
        other = {"id": self.other_leader_id, "role": "leader", "department_id": self.other_department_id}
        self.assertEqual(len(inbox_for_user(self.db, leader)), 1)
        self.assertEqual(inbox_for_user(self.db, other), [])

    def test_daily_briefing_is_scoped_to_department(self) -> None:
        self._assignment(7)
        plan_assignment_reviews(self.db, {"workflow_assignment_review_enabled": True, "workflow_assignment_review_days": 7}, today=date.today())
        execute_due_actions(self.db, today=date.today())
        leader = {
            "id": self.leader_id,
            "display_name": "Leitung Versand",
            "role": "leader",
            "department_id": self.department_id,
            "department_name": "Versand",
        }
        other = {
            "id": self.other_leader_id,
            "display_name": "Leitung Retouren",
            "role": "leader",
            "department_id": self.other_department_id,
            "department_name": "Retouren",
        }
        briefing = generate_briefing_for_user(self.db, self.settings, leader, allow_email=False)
        other_briefing = generate_briefing_for_user(self.db, self.settings, other, allow_email=False)
        self.assertEqual(briefing["summary"]["decisions"], 1)
        self.assertEqual(other_briefing["summary"]["decisions"], 0)
        self.assertIn("Versand", briefing["body"])


if __name__ == "__main__":
    unittest.main()
