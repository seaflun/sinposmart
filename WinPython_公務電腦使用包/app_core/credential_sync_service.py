# -*- coding: utf-8 -*-
"""Credential relay client used after verified SinpoSmart login."""

from __future__ import annotations

import json
import os
import ipaddress
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4


CredentialPoster = Callable[[dict[str, Any]], dict[str, Any]]
ACCOUNT_FIELDS = ("actor_no", "user_id", "password", "display_name", "name", "id_number", "duty_pc_save_status")
NAS_OVERLAY_IP = "100.114.126.58"
_OVERLAY_NETWORK = ipaddress.ip_network("100.64.0.0/10")
_NAS_API_PATHS = {"/api/credential-sync", "/api/sinposmart/events", "/api/sinposmart/civilpower-roster",
                  "/api/sinposmart/identity", "/api/sinposmart/heartbeat"}


class CredentialSyncError(RuntimeError):
    """Safe credential-sync failure without secret values."""


class SyncTransportError(RuntimeError):
    """A safe transport-policy failure containing no endpoint or credentials."""


def _tailscale_peer_verified(address: str) -> bool:
    candidates = (
        (Path("C:/Program Files/Tailscale/tailscale.exe"), Path("C:/Program Files (x86)/Tailscale/tailscale.exe"))
        if os.name == "nt" else (Path("/usr/bin/tailscale"), Path("/usr/local/bin/tailscale"))
    )
    executable = next((path for path in candidates if path.is_file()), None)
    if executable is None:
        return False
    try:
        completed = subprocess.run(
            [str(executable), "status", "--json"], capture_output=True, text=True, encoding="utf-8",
            timeout=3, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        state = json.loads(completed.stdout) if completed.returncode == 0 else {}
        own = state.get("Self", {})
        peers = state.get("Peer", {})
        return (
            state.get("BackendState") == "Running" and own.get("Online") is True
            and any(ipaddress.ip_address(ip) in _OVERLAY_NETWORK for ip in own.get("TailscaleIPs", []))
            and isinstance(peers, dict)
            and any(isinstance(peer, dict) and peer.get("Online") is True
                    and address in peer.get("TailscaleIPs", []) for peer in peers.values())
        )
    except (OSError, ValueError, TypeError, AttributeError, subprocess.SubprocessError):
        return False


def _sync_target(url: str) -> tuple[str, bool]:
    try:
        parsed = urlsplit(url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None or parsed.fragment
                or (parsed.port is not None and not 1 <= parsed.port <= 65535)):
            raise ValueError()
        if parsed.scheme == "https":
            return url, False
        if (parsed.hostname == "10.30.65.30" and parsed.port == 8080
                and parsed.path in _NAS_API_PATHS and not parsed.query):
            url = urlunsplit(("http", NAS_OVERLAY_IP + ":8080", parsed.path, "", ""))
            parsed = urlsplit(url)
        address = ipaddress.ip_address(parsed.hostname)
        if address not in _OVERLAY_NETWORK:
            raise ValueError()
    except (ValueError, TypeError):
        raise SyncTransportError("同步位址必須使用 HTTPS 或已驗證的 Tailscale 加密連線。") from None
    if not _tailscale_peer_verified(str(address)):
        raise SyncTransportError("尚未確認 Tailscale 加密連線與 NAS 節點，已停止傳送同步資料。")
    return url, True


class SyncRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, *, allow_google_redirects: bool = False) -> None:
        super().__init__()
        self._allow_google_redirects = allow_google_redirects

    def redirect_request(self, request, fp, code, message, headers, new_url):
        try:
            source, target = urlsplit(request.full_url), urlsplit(new_url)
            same_origin = (source.scheme, source.hostname, source.port or 443) == (
                target.scheme, target.hostname, target.port or 443)
            google_redirect = (source.hostname in {"script.google.com", "script.googleusercontent.com"}
                               and target.hostname == "script.googleusercontent.com")
            allowed = (self._allow_google_redirects and code in {301, 302, 303}
                       and source.scheme == target.scheme == "https"
                       and target.hostname and target.username is None and target.password is None
                       and target.port in (None, 443) and not target.fragment
                       and (same_origin or google_redirect))
        except (ValueError, TypeError):
            allowed = False
        if not allowed:
            raise SyncTransportError("同步服務發生未授權轉址，已停止傳送資料。") from None
        return urllib.request.Request(new_url, headers={"Accept": "application/json"}, method="GET")


def open_sync_request(request: urllib.request.Request, *, timeout: int,
                      allow_google_redirects: bool = False):
    url, overlay = _sync_target(request.full_url)
    if url != request.full_url:
        request = urllib.request.Request(url, data=request.data, headers=dict(request.header_items()),
                                         method=request.get_method())
    handlers = [SyncRedirectHandler(allow_google_redirects=allow_google_redirects)]
    if overlay:
        handlers.append(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(*handlers).open(request, timeout=timeout)


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
            if account["duty_pc_save_status"] not in {"saved", "not_saved", "failed"}:
                account["duty_pc_save_status"] = "unknown"
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
            with open_sync_request(request, timeout=self._timeout_seconds()) as response:
                return json.loads(response.read().decode("utf-8") or "{}")
        except SyncTransportError as exc:
            raise CredentialSyncError(str(exc)) from None
        except urllib.error.HTTPError as exc:
            raise CredentialSyncError(f"NAS 帳密同步被拒絕或失敗：HTTP {exc.code}") from None
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            raise CredentialSyncError("NAS 帳密同步連線失敗。") from None

    @staticmethod
    def _timeout_seconds() -> int:
        try:
            return max(1, int(os.environ.get("SINPOSMART_CREDENTIAL_SYNC_TIMEOUT_SECONDS", "8")))
        except ValueError:
            return 8
