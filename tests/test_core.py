from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pp.auth import hash_password, verify_password
from pp.config import Settings
from pp.db import Database
from pp.services import active_assignment_for_worker, offboarding_message


class PersonalplanerCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "pp.sqlite3")
        self.db.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_password_hashing(self) -> None:
        hashed = hash_password("sehr-sicheres-passwort")
        self.assertTrue(verify_password(hashed, "sehr-sicheres-passwort"))
        self.assertFalse(verify_password(hashed, "falsch"))

    def test_one_worker_has_one_current_assignment(self) -> None:
        agency = self.db.execute("INSERT INTO agencies(name,email) VALUES (?,?)", ("Agentur", "a@example.test"))
        dep = self.db.execute("INSERT INTO departments(name,code) VALUES (?,?)", ("Versand", "VS"))
        worker = self.db.execute(
            "INSERT INTO workers(first_name,last_name,agency_id,status,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            ("Max", "Muster", agency, "active", "2026-08-26T10:00:00+00:00", "2026-08-26T10:00:00+00:00"),
        )
        self.db.execute(
            "INSERT INTO assignments(worker_id,department_id,assigned_from,created_at) VALUES (?,?,?,?)",
            (worker, dep, "2026-01-01", "2026-08-26T10:00:00+00:00"),
        )
        assignment = active_assignment_for_worker(self.db, worker, dep)
        self.assertIsNotNone(assignment)
        self.assertEqual(assignment["department_name"], "Versand")

    def test_offboarding_message_contains_required_information(self) -> None:
        settings = Settings(
            host="0.0.0.0", port=8780, data_dir=Path(self.tmp.name), allowed_hosts=["*"],
            cookie_secure=False, session_hours=12, setup_token="x", company_name="Beispiel GmbH",
            company_contact="Disposition", smtp_host="", smtp_port=587, smtp_user="", smtp_password="",
            smtp_from="", smtp_starttls=True, smtp_ssl=False,
        )
        record = {
            "first_name": "Max", "last_name": "Muster", "employee_code": "ZA-42",
            "agency_name": "Agentur", "department_name": "Versand", "effective_at": "2026-09-01",
            "replacement_required": 1, "replacement_notes": "Frühschicht", "reason_text": "Auftragslage",
        }
        subject, body = offboarding_message(settings, record, "Keine Arbeit mehr", "Leitung Versand")
        self.assertIn("Max Muster", subject)
        self.assertIn("Versand", body)
        self.assertIn("Keine Arbeit mehr", body)
        self.assertIn("Ersatz wird benötigt: Ja", body)


if __name__ == "__main__":
    unittest.main()
