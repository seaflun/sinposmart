# -*- coding: utf-8 -*-
"""Credential relay client used after verified SinpoSmart login."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import uuid4


CredentialPoster = Callable[[dict[str, Any]], dict[str, Any]]
ACCOUNT_FIELDS = ("actor_no", "user_id", "password", "display_name", "name", "id_number")


class CredentialSyncError(RuntimeError):
    """Safe credential-sync failure without secret values."""


class CredentialSyncService:
    def __init__(self, *, poster: CredentialPoster | None = None) -> None:
        self._poster = poster

    @property
    def enabled(self) -> bool:
        return self._poster is not None or bool(
            self._sync_url and os.environ.get("SINPOSMART_CREDENTIAL_SYNC_TOKEN", "").strip()
        )

    @property
    def _sync_url(self) -> str:
        return os.environ.get(
            "SINPOSMART_CREDENTIAL_SYNC_URL",
            "http://100.114.126.58:8080/api/credential-sync",
        ).strip()

    def build_payload(
        self,
        accounts: Sequence[Mapping[str, Any]],
        *,
        sync_code: str = "",
    ) -> dict[str, Any]:
        normalized = []
        seen = set()
        for raw in accounts:
            account = {field: str(raw.get(field, "") or "") for field in ACCOUNT_FIELDS}
            identity = account["user_id"] or account["actor_no"]
            if not identity or identity in seen or not account["user_id"] or not account["password"]:
                continue
            seen.add(identity)
            normalized.append(account)
        if not normalized:
            raise CredentialSyncError("目前沒有可同步的已儲存帳號密碼。")
        first = normalized[0]
        return {
            "sync_code": sync_code or f"sinposmart-{datetime.now():%Y%m%d%H%M%S}-{uuid4().hex}",
            "accounts": normalized,
            **first,
        }

    def sync(self, accounts: Sequence[Mapping[str, Any]], *, sync_code: str = "") -> int:
        if not self.enabled:
            raise CredentialSyncError("尚未設定 NAS 帳密同步 URL 或 token。")
        payload = self.build_payload(accounts, sync_code=sync_code)
        result = self._post(payload)
        if not isinstance(result, dict) or not result.get("ok"):
            raise CredentialSyncError("NAS 帳密同步未回報成功。")
        return len(payload["accounts"])

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._poster is not None:
            return self._poster(payload)
        request = urllib.request.Request(
            self._sync_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Credential-Sync-Token": os.environ.get("SINPOSMART_CREDENTIAL_SYNC_TOKEN", "").strip(),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds()) as response:
                return json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            raise CredentialSyncError(f"NAS 帳密同步被拒絕或失敗：HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            raise CredentialSyncError("NAS 帳密同步連線失敗。") from exc

    @staticmethod
    def _timeout_seconds() -> int:
        try:
            return max(1, int(os.environ.get("SINPOSMART_CREDENTIAL_SYNC_TIMEOUT_SECONDS", "8")))
        except ValueError:
            return 8
