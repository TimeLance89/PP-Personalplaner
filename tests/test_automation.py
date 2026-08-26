from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pp.automation_engine import ensure_automation_schema, run_once
from pp.config import Settings
from pp.db import Database, utcnow
from pp.system_settings import set_values


class AutomationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "pp.sqlite3")
        self.db.initialize()
        ensure_automation_schema(self.db)
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
        self.user_id = self.db.execute(
            "INSERT INTO users(username,display_name,password_hash,role,department_id,active,created_at) VALUES (?,?,?,?,?,1,?)",
            ("admin", "Admin", "dummy", "admin", None, utcnow()),
        )
        self.worker_id = self.db.execute(
            """INSERT INTO workers(first_name,last_name,employee_code,agency_id,start_date,status,notes,custom_data,created_at,updated_at)
               VALUES (?,?,?,?,?,'active','','{}',?,?)""",
            ("Max", "Muster", "ZA-1", self.agency_id, "2026-08-01", utcnow(), utcnow()),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_assist_detects_unassigned_without_changing_worker(self) -> None:
        set_values(self.db, {"autonomy_mode": "assist", "automation_watch_unassigned": True}, self.user_id)
        result = run_once(self.db, self.settings, trigger="test")
        self.assertEqual(result["mode"], "assist")
        self.assertEqual(result["unassigned_workers"], 1)
        event = self.db.one("SELECT * FROM automation_events WHERE fingerprint=?", (f"unassigned:{self.worker_id}",))
        self.assertIsNotNone(event)
        self.assertEqual(event["state"], "open")
        worker = self.db.one("SELECT status FROM workers WHERE id=?", (self.worker_id,))
        self.assertEqual(worker["status"], "active")

    def test_event_resolves_after_assignment(self) -> None:
        set_values(self.db, {"autonomy_mode": "assist", "automation_watch_unassigned": True}, self.user_id)
        run_once(self.db, self.settings, trigger="test")
        self.db.execute(
            "INSERT INTO assignments(worker_id,department_id,assigned_from,assigned_until,notes,created_by,created_at) VALUES (?,?,?,NULL,'',?,?)",
            (self.worker_id, self.department_id, "2026-08-01", self.user_id, utcnow()),
        )
        run_once(self.db, self.settings, trigger="test")
        event = self.db.one("SELECT state FROM automation_events WHERE fingerprint=?", (f"unassigned:{self.worker_id}",))
        self.assertEqual(event["state"], "resolved")

    def test_rules_attempt_failed_mail_but_do_not_make_personnel_decision(self) -> None:
        assignment_id = self.db.execute(
            "INSERT INTO assignments(worker_id,department_id,assigned_from,assigned_until,notes,created_by,created_at) VALUES (?,?,?,NULL,'',?,?)",
            (self.worker_id, self.department_id, "2026-08-01", self.user_id, utcnow()),
        )
        offboarding_id = self.db.execute(
            """INSERT INTO offboarding_requests(
                worker_id,assignment_id,department_id,agency_id,requested_by,effective_at,reason_id,reason_text,
                replacement_required,replacement_notes,status,notification_to,notification_subject,notification_body,mail_error,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?, 'mail_failed', ?,?,?,?,?)""",
            (
                self.worker_id, assignment_id, self.department_id, self.agency_id, self.user_id, "2026-09-01", None,
                "Keine Arbeit mehr", 0, "", "dispo@example.test", "Abmeldung Test", "Test", "vorheriger Fehler", utcnow(),
            ),
        )
        set_values(
            self.db,
            {
                "autonomy_mode": "rules",
                "automation_retry_failed_mail": True,
                "automation_retry_after_minutes": 1,
                "automation_retry_max_attempts": 3,
            },
            self.user_id,
        )
        result = run_once(self.db, self.settings, trigger="test")
        self.assertEqual(result["mail_retry_attempted"], 1)
        retry = self.db.one("SELECT * FROM automation_mail_retry WHERE offboarding_id=?", (offboarding_id,))
        self.assertEqual(retry["attempts"], 1)
        worker = self.db.one("SELECT status FROM workers WHERE id=?", (self.worker_id,))
        self.assertEqual(worker["status"], "active")

    def test_emergency_stop_skips_automation(self) -> None:
        set_values(self.db, {"autonomy_mode": "autopilot", "automation_emergency_stop": True}, self.user_id)
        result = run_once(self.db, self.settings, trigger="test")
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "emergency_stop")


if __name__ == "__main__":
    unittest.main()
