# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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

    def test_non_object_json_is_preserved_as_invalid_account_file(self) -> None:
        for payload in ([], None, "invalid account file", 123):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / "saved_login.json"
                original = json.dumps(payload)
                path.write_text(original, encoding="utf-8")
                repository = self.repository(path)

                snapshot = repository.load()

                self.assertTrue(snapshot.invalid_file)
                self.assertEqual(snapshot.accounts, [])
                self.assertEqual(path.read_text(encoding="utf-8"), original)
                self.assertTrue(repository.needs_backup)

    def test_missing_dpapi_refuses_to_persist(self) -> None:
        from app_core.credential_repository import CredentialRepository

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "saved_login.json"
            repository = CredentialRepository(path=path, app_name="SinpoSmart", dpapi=None)

            self.assertFalse(repository.save([], ""))
            self.assertFalse(path.exists())
            self.assertIn("DPAPI", repository.last_error)

    def test_encryption_failure_preserves_original_file_and_hides_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "saved_login.json"
            repository = self.repository(path)
            self.assertTrue(repository.save([], ""))
            original = path.read_bytes()
            with patch.object(FakeDpapi, "CryptProtectData", side_effect=RuntimeError("secret-value")):
                saved = repository.save([{"user_id": "new-user", "password": "secret-value"}], "new-user")
            self.assertFalse(saved)
            self.assertEqual(path.read_bytes(), original)
            self.assertIn("加密", repository.last_error)
            self.assertNotIn("secret-value", repository.last_error)

    def test_replace_failure_preserves_original_file_and_cleans_owned_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "saved_login.json"
            repository = self.repository(path)
            self.assertTrue(repository.save([], ""))
            original = path.read_bytes()
            with patch.object(Path, "replace", side_effect=PermissionError("secret-value")):
                saved = repository.save([{"user_id": "new-user", "password": "secret-value"}], "new-user")
            self.assertFalse(saved)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.iterdir()), [path])
            self.assertIn("權限", repository.last_error)
            self.assertNotIn("secret-value", repository.last_error)

    def test_partial_write_failure_preserves_original_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "saved_login.json"
            repository = self.repository(path)
            self.assertTrue(repository.save([], ""))
            original = path.read_bytes()

            def interrupted_dump(_payload, stream, **_kwargs):
                stream.write("{partial")
                raise OSError("synthetic disk full")

            with patch("app_core.credential_repository.json.dump", side_effect=interrupted_dump):
                self.assertFalse(repository.save([], ""))
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_unreadable_saved_password_cannot_be_overwritten_by_enabling_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "saved_login.json"
            repository = self.repository(path)
            self.assertTrue(repository.save([{"user_id": "old-user", "password": "old-secret"}], "old-user"))
            original = path.read_bytes()
            with patch.object(FakeDpapi, "CryptUnprotectData", side_effect=RuntimeError("synthetic decrypt failure")):
                snapshot = repository.load()
            self.assertFalse(snapshot.can_persist)
            repository.enable_persistence()
            self.assertFalse(repository.save([{"user_id": "new-user", "password": "new-secret"}], "new-user"))
            self.assertEqual(path.read_bytes(), original)
            self.assertIn("無法解密", repository.last_error)

    def test_successful_retry_clears_previous_save_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "saved_login.json"
            repository = self.repository(path)
            with patch.object(Path, "replace", side_effect=PermissionError("synthetic denied")):
                self.assertFalse(repository.save([], ""))
            self.assertTrue(repository.save([], ""))
            self.assertEqual(repository.last_error, "")

    def test_notice_repository_reuses_encryption_and_keeps_duty_accounts_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "saved_login.json"
            duty = self.repository(path)
            self.assertTrue(duty.save([{"user_id": "duty-user", "password": "duty-test-secret"}], "duty-user"))
            original = path.read_bytes()
            notice = duty.notice_repository()
            self.assertEqual(notice.path, path.with_name("notice_login.json"))
            self.assertEqual(notice.app_name, duty.app_name)
            self.assertIs(notice.dpapi, duty.dpapi)
            self.assertFalse(notice.path.exists())
            self.assertTrue(notice.save([{"user_id": "tyfd01214", "password": "notice-test-secret"}], "tyfd01214"))
            raw = notice.path.read_text(encoding="utf-8")
            self.assertNotIn("notice-test-secret", raw)
            self.assertIn("password_dpapi", raw)
            loaded = duty.notice_repository().load()
            self.assertEqual(loaded.accounts[0]["user_id"], "tyfd01214")
            self.assertEqual(loaded.accounts[0]["password"], "notice-test-secret")
            self.assertEqual(loaded.accounts[0]["actor_no"], "")
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(duty.load().accounts[0]["user_id"], "duty-user")

    def test_notice_repository_without_dpapi_does_not_create_either_credential_file(self) -> None:
        from app_core.credential_repository import CredentialRepository

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "saved_login.json"
            duty = CredentialRepository(path=path, app_name="SinpoSmart", dpapi=None)
            notice = duty.notice_repository()
            self.assertFalse(notice.save([{"user_id": "tyfd01214", "password": "notice-test-secret"}]))
            self.assertIn("DPAPI", notice.last_error)
            self.assertFalse(notice.path.exists())
            self.assertFalse(path.exists())

    def test_notice_repository_with_unreadable_password_preserves_original_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "saved_login.json"
            duty = self.repository(path)
            self.assertTrue(duty.save([], ""))
            duty_original = path.read_bytes()
            notice = duty.notice_repository()
            self.assertTrue(notice.save([{"user_id": "tyfd01214", "password": "notice-test-secret"}], "tyfd01214"))
            notice_original = notice.path.read_bytes()
            with patch.object(FakeDpapi, "CryptUnprotectData", side_effect=RuntimeError("synthetic decrypt failure")):
                snapshot = notice.load()
            self.assertFalse(snapshot.can_persist)
            notice.enable_persistence()
            self.assertFalse(notice.save([{"user_id": "tyfd01214", "password": "replacement-test-secret"}]))
            self.assertIn("無法解密", notice.last_error)
            self.assertEqual(notice.path.read_bytes(), notice_original)
            self.assertEqual(path.read_bytes(), duty_original)


if __name__ == "__main__":
    unittest.main()
