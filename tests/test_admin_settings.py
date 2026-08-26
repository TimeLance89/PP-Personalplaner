from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pp.admin_settings_api import build_admin_settings_router
from pp.api import build_router
from pp.config import Settings
from pp.db import Database
from pp.system_settings import get_all


class AdminSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        data_dir = Path(self.tmp.name)
        self.db = Database(data_dir / "personalplaner.sqlite3")
        self.db.initialize()
        self.settings = Settings(
            host="127.0.0.1", port=8780, data_dir=data_dir, allowed_hosts=["*"],
            cookie_secure=False, session_hours=12, setup_token="setup-token", company_name="Test GmbH",
            company_contact="Disposition", smtp_host="", smtp_port=587, smtp_user="", smtp_password="",
            smtp_from="", smtp_starttls=True, smtp_ssl=False,
        )
        app = FastAPI()
        app.include_router(build_router(self.db, self.settings))
        app.include_router(build_admin_settings_router(self.db, self.settings))
        self.client = TestClient(app)
        self.client.post("/api/setup", json={
            "token": "setup-token", "username": "admin", "display_name": "Admin", "password": "sicheres-passwort"
        })
        login = self.client.post("/api/auth/login", json={"username": "admin", "password": "sicheres-passwort"})
        self.csrf = login.json()["csrf_token"]
        self.headers = {"X-CSRF-Token": self.csrf}

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_settings_are_persisted_and_secrets_are_masked(self) -> None:
        response = self.client.put(
            "/api/admin/settings",
            headers=self.headers,
            json={"values": {
                "company_name": "Beispiel Logistik GmbH",
                "mail_provider": "smtp",
                "smtp_host": "smtp.example.test",
                "smtp_from": "pp@example.test",
                "smtp_password": "super-secret",
                "offboarding_default_days": 2,
                "offboarding_require_reason_text": True,
            }},
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = self.client.get("/api/admin/settings").json()
        self.assertEqual(payload["company_name"], "Beispiel Logistik GmbH")
        self.assertTrue(payload["smtp_password_configured"])
        self.assertNotIn("smtp_password", payload)
        self.assertEqual(payload["offboarding_default_days"], 2)
        self.assertTrue(payload["offboarding_require_reason_text"])
        stored = get_all(self.db, self.settings)
        self.assertEqual(stored["smtp_password"], "super-secret")

    def test_preferences_expose_only_operational_non_secret_values(self) -> None:
        self.client.put(
            "/api/admin/settings",
            headers=self.headers,
            json={"values": {
                "offboarding_default_replacement": True,
                "offboarding_default_days": 3,
                "mail_provider": "smtp",
                "smtp_host": "smtp.example.test",
                "smtp_from": "pp@example.test",
            }},
        )
        payload = self.client.get("/api/preferences").json()
        self.assertTrue(payload["offboarding_default_replacement"])
        self.assertEqual(payload["offboarding_default_days"], 3)
        self.assertTrue(payload["mail_ready"])
        self.assertNotIn("smtp_host", payload)
        self.assertNotIn("smtp_password", payload)


if __name__ == "__main__":
    unittest.main()
