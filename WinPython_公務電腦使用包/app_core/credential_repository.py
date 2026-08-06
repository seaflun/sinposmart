# -*- coding: utf-8 -*-
"""Windows DPAPI-backed saved-account persistence shared by both GUIs."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SavedAccountsSnapshot:
    accounts: list[dict[str, str]]
    last_selected: str
    can_persist: bool
    needs_rewrite: bool = False
    invalid_file: bool = False


class CredentialRepository:
    """Read and write the existing saved_login.json contract without UI state."""

    def __init__(self, path: Path, app_name: str, dpapi: Any | None) -> None:
        self.path = Path(path)
        self.app_name = app_name
        self.dpapi = dpapi
        self.can_persist = dpapi is not None
        self.needs_backup = False

    @staticmethod
    def account_identity(account: dict[str, str]) -> str:
        return str(account.get("user_id", "") or account.get("actor_no", "") or "").strip()

    def protect_password(self, password: str) -> str:
        if not password or self.dpapi is None:
            return ""
        encrypted = self.dpapi.CryptProtectData(
            password.encode("utf-8"),
            self.app_name,
            None,
            None,
            None,
            0,
        )
        return base64.b64encode(encrypted).decode("ascii")

    def unprotect_password(self, encrypted_password: str) -> str:
        if not encrypted_password or self.dpapi is None:
            return ""
        try:
            _, decrypted = self.dpapi.CryptUnprotectData(
                base64.b64decode(encrypted_password),
                None,
                None,
                None,
                0,
            )
            return decrypted.decode("utf-8")
        except Exception:
            return ""

    def password_from_payload(self, account: dict[str, Any]) -> str:
        encrypted_password = str(account.get("password_dpapi", "") or "")
        if encrypted_password:
            password = self.unprotect_password(encrypted_password)
            if not password:
                self.can_persist = False
            return password
        return str(account.get("password", "") or "")

    def account_payload(self, account: dict[str, str]) -> dict[str, str]:
        return {
            "actor_no": str(account.get("actor_no", "") or ""),
            "user_id": str(account.get("user_id", "") or ""),
            "password_dpapi": self.protect_password(str(account.get("password", "") or "")),
            "display_name": str(account.get("display_name", "") or ""),
            "name": str(account.get("name", "") or ""),
            "id_number": str(account.get("id_number", "") or ""),
        }

    def load(self) -> SavedAccountsSnapshot:
        self.can_persist = self.dpapi is not None
        if not self.path.exists():
            return SavedAccountsSnapshot([], "", self.can_persist)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self.needs_backup = True
            return SavedAccountsSnapshot([], "", self.can_persist, invalid_file=True)

        accounts = payload.get("accounts")
        legacy_format = not isinstance(accounts, list)
        if legacy_format:
            legacy_account = {
                "actor_no": str(payload.get("actor_no", "") or ""),
                "user_id": str(payload.get("user_id", "") or ""),
                "password": str(payload.get("password", "") or ""),
                "display_name": "",
            }
            accounts = [legacy_account] if legacy_account["user_id"] or legacy_account["actor_no"] else []
            payload = {
                "last_selected": legacy_account["user_id"] or legacy_account["actor_no"],
                "accounts": accounts,
            }

        normalized: list[dict[str, str]] = []
        for account in accounts:
            if not isinstance(account, dict):
                continue
            actor_no = str(account.get("actor_no", "") or "").strip()
            user_id = str(account.get("user_id", "") or "").strip()
            if not actor_no and not user_id:
                continue
            normalized.append(
                {
                    "actor_no": actor_no,
                    "user_id": user_id,
                    "password": self.password_from_payload(account),
                    "display_name": str(account.get("display_name", "") or ""),
                    "name": str(account.get("name", "") or account.get("person_name", "") or ""),
                    "id_number": str(account.get("id_number", "") or account.get("national_id", "") or ""),
                }
            )

        last_selected = str(payload.get("last_selected", "") or "")
        if not last_selected and normalized:
            last_selected = self.account_identity(normalized[0])
        needs_rewrite = legacy_format or "accounts" not in payload or payload.get("accounts") != normalized
        return SavedAccountsSnapshot(
            accounts=normalized,
            last_selected=last_selected,
            can_persist=self.can_persist,
            needs_rewrite=needs_rewrite,
        )

    def enable_persistence(self) -> None:
        if self.dpapi is not None:
            self.can_persist = True

    def backup_invalid_file(self) -> None:
        if not self.needs_backup or not self.path.exists():
            return
        backup_path = self.path.with_name(f"{self.path.stem}.invalid-{datetime.now():%Y%m%d-%H%M%S}.bak")
        backup_path.write_text(
            self.path.read_text(encoding="utf-8", errors="replace"),
            encoding="utf-8",
        )
        self.needs_backup = False

    def save(self, accounts: list[dict[str, str]], last_selected: str = "") -> bool:
        if self.dpapi is None or not self.can_persist:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.backup_invalid_file()
        payload = {
            "last_selected": last_selected,
            "accounts": [self.account_payload(account) for account in accounts],
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return True


def create_default_credential_repository(app_name: str = "SinpoSmart") -> CredentialRepository:
    try:
        import win32crypt
    except ImportError:
        win32crypt = None
    path = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "DutyAutomation" / "saved_login.json"
    return CredentialRepository(path=path, app_name=app_name, dpapi=win32crypt)
