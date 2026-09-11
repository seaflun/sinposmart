# -*- coding: utf-8 -*-
"""Qt worker adapter for the read-only update check."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from PySide6.QtCore import QObject, Signal, Slot

from app_core.update_repository import UpdateCheckError, UpdateRepository


class UpdateCheckWorker(QObject):
    succeeded = Signal(int, object)
    failed = Signal(int, str)
    finished = Signal(int)

    def __init__(self, request_id: int, repository: UpdateRepository) -> None:
        super().__init__()
        self.request_id = request_id
        self.repository = repository

    @Slot()
    def run(self) -> None:
        try:
            info = self.repository.check()
        except UpdateCheckError as exc:
            self.failed.emit(self.request_id, str(exc))
        except Exception:
            self.failed.emit(self.request_id, "檢查更新失敗，請稍後重試。")
        else:
            self.succeeded.emit(self.request_id, info)
        finally:
            self.finished.emit(self.request_id)


class RemoteUpdateWorker(QObject):
    """Fetch or acknowledge one value-duty GUI update command off the UI thread."""

    succeeded = Signal(int, object)
    failed = Signal(int, str)
    finished = Signal(int)

    def __init__(
        self,
        request_id: int,
        endpoint: str,
        token: str,
        worker_id: str,
        package_version: str,
        *,
        target: str = "duty_gui",
        status_request: dict[str, object] | None = None,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.endpoint = str(endpoint or "").rstrip("/")
        self.token = str(token or "")
        self.worker_id = str(worker_id or "")
        self.package_version = str(package_version or "")
        self.target = str(target or "duty_gui")
        self.status_request = status_request

    @Slot()
    def run(self) -> None:
        try:
            payload = self._request()
        except Exception as exc:
            self.failed.emit(self.request_id, self._safe_error(exc))
        else:
            self.succeeded.emit(self.request_id, payload)
        finally:
            self.finished.emit(self.request_id)

    def _request(self) -> dict[str, object]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "SinpoSmart-Duty-GUI",
            "X-Credential-Sync-Token": self.token,
        }
        if self.status_request is None:
            query = urllib.parse.urlencode(
                {
                    "worker_id": self.worker_id,
                    "package_version": self.package_version,
                }
            )
            url = f"{self.endpoint}?{query}" if query else self.endpoint
            request = urllib.request.Request(url, headers=headers, method="GET")
        else:
            request_id = str(self.status_request.get("request_id") or "").strip()
            url = f"{self.endpoint}/{urllib.parse.quote(request_id, safe='')}/status"
            body = dict(self.status_request)
            body.pop("request_id", None)
            body.setdefault("worker_id", self.worker_id)
            request = urllib.request.Request(
                url,
                data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                headers={**headers, "Content-Type": "application/json"},
                method="POST",
            )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                data = json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"遠端更新伺服器回應 HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("遠端更新伺服器暫時無法連線") from exc
        if not isinstance(data, dict) or not data.get("ok"):
            raise RuntimeError("遠端更新伺服器未回報成功")
        return data

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        message = str(exc).strip()
        return message if message and "token" not in message.lower() else "遠端更新連線失敗"
