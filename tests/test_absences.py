from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pp.absence_api import build_absence_router
from pp.absence_service import (
    build_monthly_report,
    ensure_absence_schema,
    ensure_previous_month_reports,
    get_stored_report,
    store_monthly_report,
    working_days,
)
from pp.api import build_router
from pp.config import Settings
from pp.db import Database


class AbsenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "pp.sqlite3")
        self.db.initialize()
        ensure_absence_schema(self.db)
        self.settings = Settings(
            host="127.0.0.1", port=8780, data_dir=Path(self.tmp.name), allowed_hosts=["*"],
            cookie_secure=False, session_hours=12, setup_token="setup-token", company_name="Test GmbH",
            company_contact="Disposition", smtp_host="", smtp_port=587, smtp_user="", smtp_password="",
            smtp_from="", smtp_starttls=True, smtp_ssl=False,
        )
        app = FastAPI()
        app.include_router(build_router(self.db, self.settings))
        app.include_router(build_absence_router(self.db, self.settings))
        self.client = TestClient(app)

        self.client.post("/api/setup", json={
            "token": "setup-token", "username": "admin", "display_name": "Admin", "password": "sicheres-passwort"
        })
        csrf = self.login("admin", "sicheres-passwort")
        headers = {"X-CSRF-Token": csrf}
        self.dep1 = self.client.post("/api/departments", headers=headers, json={"name":"Versand","code":"VS","active":True,"custom_data":{}}).json()["id"]
        self.dep2 = self.client.post("/api/departments", headers=headers, json={"name":"Retouren","code":"RET","active":True,"custom_data":{}}).json()["id"]
        agency = self.client.post("/api/agencies", headers=headers, json={"name":"Test ZA","contact_name":"","email":"za@example.test","phone":"","active":True}).json()["id"]
        self.worker1 = self.client.post("/api/workers", headers=headers, json={"first_name":"Max","last_name":"Muster","employee_code":"ZA-1","agency_id":agency,"start_date":"2026-08-01","notes":"","status":"active","custom_data":{}}).json()["id"]
        self.worker2 = self.client.post("/api/workers", headers=headers, json={"first_name":"Erika","last_name":"Test","employee_code":"ZA-2","agency_id":agency,"start_date":"2026-08-01","notes":"","status":"active","custom_data":{}}).json()["id"]
        self.client.post("/api/assignments", headers=headers, json={"worker_id":self.worker1,"department_id":self.dep1,"assigned_from":"2026-08-01","assigned_until":"2026-08-31","notes":""})
        self.client.post("/api/assignments", headers=headers, json={"worker_id":self.worker2,"department_id":self.dep2,"assigned_from":"2026-08-01","assigned_until":None,"notes":""})
        self.client.post("/api/users", headers=headers, json={"username":"leiter","display_name":"Leitung Versand","password":"noch-sicherer-pass","role":"leader","department_id":self.dep1,"active":True})
        self.client.post("/api/users", headers=headers, json={"username":"retoure","display_name":"Leitung Retouren","password":"noch-sicherer-pass","role":"leader","department_id":self.dep2,"active":True})
        self.client.post("/api/auth/logout", headers=headers)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def login(self, username: str, password: str) -> str:
        res = self.client.post("/api/auth/login", json={"username": username, "password": password})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["csrf_token"]

    def test_working_days_skip_weekend_and_support_half_day(self) -> None:
        self.assertEqual(working_days(date(2026, 8, 24), date(2026, 8, 30)), 5.0)
        self.assertEqual(working_days(date(2026, 8, 24), date(2026, 8, 24), "morning"), 0.5)

    def test_leader_records_only_own_department_and_report_is_scoped(self) -> None:
        csrf = self.login("leiter", "noch-sicherer-pass")
        sick = next(x for x in self.client.get("/api/absence-types").json() if x["code"] == "sick")
        payload = {
            "worker_id": self.worker1, "absence_type_id": sick["id"],
            "starts_on": "2026-08-24", "ends_on": "2026-08-28", "day_part": "full", "note": ""
        }
        created = self.client.post("/api/absences", headers={"X-CSRF-Token": csrf}, json=payload)
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["working_days"], 5.0)

        forbidden = self.client.post("/api/absences", headers={"X-CSRF-Token": csrf}, json={**payload, "worker_id": self.worker2})
        self.assertEqual(forbidden.status_code, 403)

        beyond_assignment = self.client.post("/api/absences", headers={"X-CSRF-Token": csrf}, json={
            **payload, "starts_on": "2026-08-31", "ends_on": "2026-09-01"
        })
        self.assertEqual(beyond_assignment.status_code, 403)

        rows = self.client.get("/api/absences?month=2026-08").json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["department_id"], self.dep1)
        report = self.client.get("/api/reports/absences/monthly?month=2026-08&live=true").json()
        self.assertEqual(report["summary"]["sick_days"], 5.0)
        self.assertEqual(report["summary"]["affected_workers"], 1)

        self.client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
        self.login("retoure", "noch-sicherer-pass")
        self.assertEqual(self.client.get("/api/absences?month=2026-08").json(), [])
        other_report = self.client.get("/api/reports/absences/monthly?month=2026-08&live=true").json()
        self.assertEqual(other_report["summary"]["sick_days"], 0.0)

    def test_quick_sick_runs_until_return_and_remains_department_scoped(self) -> None:
        csrf = self.login("leiter", "noch-sicherer-pass")
        forbidden = self.client.post(
            "/api/absences/quick-sick",
            headers={"X-CSRF-Token": csrf},
            json={"worker_id": self.worker2},
        )
        self.assertEqual(forbidden.status_code, 403)
        self.client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})

        csrf = self.login("retoure", "noch-sicherer-pass")
        created = self.client.post(
            "/api/absences/quick-sick",
            headers={"X-CSRF-Token": csrf},
            json={"worker_id": self.worker2},
        )
        self.assertEqual(created.status_code, 200, created.text)
        absence_id = created.json()["id"]
        self.assertTrue(created.json()["open_ended"])

        month = date.today().strftime("%Y-%m")
        rows = self.client.get(f"/api/absences?month={month}").json()
        row = next(x for x in rows if x["id"] == absence_id)
        self.assertEqual(row["absence_code"], "sick")
        self.assertTrue(row["open_ended"])
        self.assertGreaterEqual(row["working_days"], 0.0)

        returned = self.client.post(
            f"/api/absences/{absence_id}/return",
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(returned.status_code, 200, returned.text)
        closed = self.db.one("SELECT open_ended,ends_on FROM absences WHERE id=?", (absence_id,))
        self.assertEqual(closed["open_ended"], 0)
        self.assertTrue(closed["ends_on"])

    def test_cross_month_report_counts_only_days_in_selected_month(self) -> None:
        sick = self.db.one("SELECT id FROM absence_types WHERE code='sick'")
        user = self.db.one("SELECT id FROM users WHERE username='leiter'")
        self.db.execute(
            """INSERT INTO absences(worker_id,department_id,absence_type_id,starts_on,ends_on,day_part,note,recorded_by,created_at,updated_at)
               VALUES (?,?,?,?,?,'full','',?,?,?)""",
            (self.worker1, self.dep1, sick["id"], "2026-07-30", "2026-08-03", user["id"], "2026-08-03T08:00:00+00:00", "2026-08-03T08:00:00+00:00"),
        )
        july = build_monthly_report(self.db, "2026-07", self.dep1)
        august = build_monthly_report(self.db, "2026-08", self.dep1)
        self.assertEqual(july["summary"]["sick_days"], 2.0)
        self.assertEqual(august["summary"]["sick_days"], 1.0)

    def test_finalized_monthly_report_is_snapshot(self) -> None:
        report = store_monthly_report(self.db, "2026-07", self.dep1)
        self.assertTrue(report["finalized"])
        self.assertEqual(report["month"], "2026-07")

    def test_previous_month_reports_are_generated_idempotently(self) -> None:
        generated_first = ensure_previous_month_reports(self.db)
        generated_second = ensure_previous_month_reports(self.db)
        self.assertGreaterEqual(generated_first, 1)
        self.assertEqual(generated_second, 0)
        previous = date.today().replace(day=1)
        previous = (previous.replace(day=1) - __import__('datetime').timedelta(days=1)).strftime("%Y-%m")
        self.assertIsNotNone(get_stored_report(self.db, previous, self.dep1))
        self.assertIsNotNone(get_stored_report(self.db, previous, None))


if __name__ == "__main__":
    unittest.main()
