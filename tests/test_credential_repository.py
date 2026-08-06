# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "WinPython_公務電腦使用包"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))


class FakeDpapi:
    @staticmethod
    def CryptProtectData(data: bytes, *_args) -> bytes:
        return b"protected:" + data[::-1]

    @staticmethod
    def CryptUnprotectData(data: bytes, *_args) -> tuple[None, bytes]:
        prefix = b"protected:"
        if not data.startswith(prefix):
            raise ValueError("invalid protected payload")
        return None, data[len(prefix) :][::-1]


class CredentialRepositoryTests(unittest.TestCase):
    def repository(self, path: Path):
        from app_core.credential_repository import CredentialRepository

        return CredentialRepository(path=path, app_name="SinpoSmart", dpapi=FakeDpapi)

    def test_round_trip_preserves_fields_and_never_writes_plaintext_password(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "saved_login.json"
            repository = self.repository(path)
            accounts = [
                {
                    "actor_no": "10",
                    "user_id": "user10",
                    "password": "top-secret-password",
                    "display_name": "10番 測試員",
                    "name": "測試員",
                    "id_number": "A123456789",
                }
            ]

            self.assertTrue(repository.save(accounts, "user10"))
            raw = path.read_text(encoding="utf-8")
            snapshot = repository.load()

            self.assertNotIn("top-secret-password", raw)
            self.assertEqual(snapshot.last_selected, "user10")
            self.assertEqual(snapshot.accounts, accounts)
            self.assertTrue(snapshot.can_persist)

    def test_load_accepts_legacy_single_account_plaintext_format(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "saved_login.json"
            path.write_text(
                json.dumps({"actor_no": "7", "user_id": "legacy7", "password": "legacy-password"}),
                encoding="utf-8",
            )
            repository = self.repository(path)

            snapshot = repository.load()

            self.assertEqual(snapshot.last_selected, "legacy7")
            self.assertEqual(snapshot.accounts[0]["actor_no"], "7")
            self.assertEqual(snapshot.accounts[0]["user_id"], "legacy7")
            self.assertEqual(snapshot.accounts[0]["password"], "legacy-password")
            self.assertTrue(snapshot.needs_rewrite)

    def test_invalid_file_is_backed_up_before_next_successful_save(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "saved_login.json"
            path.write_text("{invalid-json", encoding="utf-8")
            repository = self.repository(path)

            snapshot = repository.load()
            self.assertTrue(snapshot.invalid_file)
            self.assertTrue(repository.needs_backup)

            self.assertTrue(repository.save([], ""))

            backups = list(path.parent.glob("saved_login.invalid-*.bak"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "{invalid-json")
            self.assertFalse(repository.needs_backup)

    def test_missing_dpapi_refuses_to_persist(self) -> None:
        from app_core.credential_repository import CredentialRepository

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "saved_login.json"
            repository = CredentialRepository(path=path, app_name="SinpoSmart", dpapi=None)

            self.assertFalse(repository.save([], ""))
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
