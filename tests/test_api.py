from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pp.api import build_router
from pp.config import Settings
from pp.db import Database


class ApiFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "pp.sqlite3")
        self.db.initialize()
        self.settings = Settings(
            host="127.0.0.1", port=8780, data_dir=Path(self.tmp.name), allowed_hosts=["*"],
            cookie_secure=False, session_hours=12, setup_token="setup-token", company_name="Test GmbH",
            company_contact="Disposition", smtp_host="", smtp_port=587, smtp_user="", smtp_password="",
            smtp_from="", smtp_starttls=True, smtp_ssl=False,
        )
        app = FastAPI()
        app.include_router(build_router(self.db, self.settings))
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def login(self, username: str, password: str) -> str:
        res = self.client.post("/api/auth/login", json={"username": username, "password": password})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["csrf_token"]

    def test_admin_and_department_leader_flow(self) -> None:
        self.assertEqual(self.client.post("/api/setup", json={
            "token": "setup-token", "username": "admin", "display_name": "Admin", "password": "sicheres-passwort"
        }).status_code, 200)
        csrf = self.login("admin", "sicheres-passwort")
        headers = {"X-CSRF-Token": csrf}

        dep1 = self.client.post("/api/departments", headers=headers, json={"name":"Versand","code":"VS","active":True,"custom_data":{}}).json()["id"]
        dep2 = self.client.post("/api/departments", headers=headers, json={"name":"Retouren","code":"RET","active":True,"custom_data":{}}).json()["id"]
        agency = self.client.post("/api/agencies", headers=headers, json={"name":"Zeitarbeit Nord","contact_name":"Frau Test","email":"dispo@example.test","phone":"","active":True}).json()["id"]
        worker = self.client.post("/api/workers", headers=headers, json={"first_name":"Max","last_name":"Muster","employee_code":"ZA-7","agency_id":agency,"start_date":"2026-08-01","notes":"","status":"active","custom_data":{}}).json()["id"]
        self.assertEqual(self.client.post("/api/assignments", headers=headers, json={"worker_id":worker,"department_id":dep1,"assigned_from":"2026-08-01","assigned_until":None,"notes":""}).status_code, 200)
        self.assertEqual(self.client.post("/api/users", headers=headers, json={"username":"leiter","display_name":"Leitung Versand","password":"noch-sicherer-pass","role":"leader","department_id":dep1,"active":True}).status_code, 200)
        self.assertEqual(self.client.post("/api/users", headers=headers, json={"username":"retoure","display_name":"Leitung Retouren","password":"noch-sicherer-pass","role":"leader","department_id":dep2,"active":True}).status_code, 200)

        self.client.post("/api/auth/logout", headers=headers)
        csrf = self.login("leiter", "noch-sicherer-pass")
        rows = self.client.get("/api/workers").json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["last_name"], "Muster")
        reasons = self.client.get("/api/offboarding-reasons").json()
        payload = {"worker_id":worker,"effective_at":"2026-09-01","reason_id":reasons[0]["id"],"reason_text":"Auftragslage","replacement_required":True,"replacement_notes":"Frühschicht"}
        preview = self.client.post("/api/offboardings/preview", json=payload)
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertIn("Versand", preview.json()["body"])
        created = self.client.post("/api/offboardings", headers={"X-CSRF-Token":csrf}, json=payload)
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["status"], "mail_failed")

        self.client.post("/api/auth/logout", headers={"X-CSRF-Token":csrf})
        self.login("retoure", "noch-sicherer-pass")
        self.assertEqual(self.client.get("/api/workers").json(), [])


if __name__ == "__main__":
    unittest.main()
