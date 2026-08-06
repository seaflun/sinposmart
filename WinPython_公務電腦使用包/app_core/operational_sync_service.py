# -*- coding: utf-8 -*-
"""Background Google duty-board sync and SinpoSmart operational events."""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from app_core.duty_task_projection import action_summary


JsonPoster = Callable[[dict[str, Any]], dict[str, Any]]
SENSITIVE_KEY_PARTS = ("password", "passwd", "token", "secret", "cookie", "authorization")
DEFAULT_SINPOSMART_BACKEND_EVENT_URL = "http://10.30.65.30:8080/api/sinposmart/events"
SYNC_STATUS_FILENAME = "sinposmart_operational_sync_status.json"


def sanitize_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): sanitize_payload(item)
            for key, item in value.items()
            if not any(part in str(key).lower() for part in SENSITIVE_KEY_PARTS)
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_payload(item) for item in value]
    return value


def normalize_duty_board_day(raw_day: Mapping[str, Any]) -> dict[str, Any] | None:
    roc_day = str(raw_day.get("roc_date", "")).strip()
    rows = raw_day.get("rows")
    staff = raw_day.get("staff")
    if len(roc_day) != 7 or not isinstance(rows, list) or not isinstance(staff, Mapping):
        return None
    slots: list[dict[str, Any]] = []
    for raw_row in rows:
        if not isinstance(raw_row, Mapping):
            continue
        slot = str(raw_row.get("slot", "")).strip()
        match = re.fullmatch(r"\s*(\d{1,2})\s*[~～-]\s*(\d{1,2})\s*", slot)
        columns = raw_row.get("columns")
        duty_nos = columns.get("值班", []) if isinstance(columns, Mapping) else []
        if match is None or not isinstance(duty_nos, list):
            continue
        numbers = [str(number).strip() for number in duty_nos if str(number).strip()]
        names = [
            str(staff.get(number, {}).get("name", "")).strip()
            for number in numbers
            if isinstance(staff.get(number, {}), Mapping)
        ]
        slots.append(
            {
                "slot": slot,
                "start_hour": int(match.group(1)),
                "end_hour": int(match.group(2)),
                "duty_nos": numbers,
                "names": [name for name in names if name],
            }
        )
    return {"roc_date": roc_day, "slots": slots}


def build_duty_board_payload(schedule_data: Mapping[str, Any]) -> dict[str, Any]:
    days = []
    for raw_day in (schedule_data.get("today"), schedule_data.get("tomorrow")):
        if isinstance(raw_day, Mapping):
            normalized = normalize_duty_board_day(raw_day)
            if normalized is not None:
                days.append(normalized)
    if not days:
        raise RuntimeError("找不到可同步的今日或下一勤務日看板資料。")
    canonical = json.dumps(
        {"schema_version": 1, "days": days},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "schema_version": 1,
        "days": days,
        "content_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


class OperationalSyncService:
    def __init__(
        self,
        package_root: Path,
        *,
        event_poster: JsonPoster | None = None,
        board_poster: JsonPoster | None = None,
    ) -> None:
        self.package_root = Path(package_root)
        self.pending_path = self.package_root / "runtime_outputs" / "sinposmart_backend_events_pending.jsonl"
        self.status_path = self.package_root / "runtime_outputs" / SYNC_STATUS_FILENAME
        self._event_poster = event_poster
        self._board_poster = board_poster
        self._event_lock = threading.Lock()
        self._board_lock = threading.Lock()
        self._last_board_hash = ""
        self._board_inflight_hashes: set[str] = set()

    @property
    def event_enabled(self) -> bool:
        return self._event_poster is not None or bool(
            self.event_url
            and os.environ.get("SINPOSMART_CREDENTIAL_SYNC_TOKEN", "").strip()
        )

    @property
    def event_url(self) -> str:
        """Keep the released Tk runtime's NAS event endpoint fallback."""

        return os.environ.get(
            "SINPOSMART_BACKEND_EVENT_URL",
            DEFAULT_SINPOSMART_BACKEND_EVENT_URL,
        ).strip()

    @property
    def board_enabled(self) -> bool:
        return self._board_poster is not None or bool(
            os.environ.get("SINPOSMART_DUTY_BOARD_SYNC_URL", "").strip()
            and os.environ.get("SINPOSMART_DUTY_BOARD_SYNC_KEY", "").strip()
        )

    def enqueue_event(
        self,
        record_type: str,
        *,
        status: str = "",
        trigger_type: str = "",
        actor_no: str = "",
        user_id: str = "",
        display_name: str = "",
        action: Mapping[str, Any] | None = None,
        target: str = "",
        error: str = "",
        result_ref: str = "",
        content: str = "",
        snapshot: Mapping[str, Any] | None = None,
        immediate: bool = False,
    ) -> dict[str, Any] | None:
        if not self.event_enabled:
            self._record_sync_status(
                "event",
                "disabled",
                "尚未設定 NAS 後台事件 token。",
            )
            return None
        payload = self.build_event_payload(
            record_type,
            status=status,
            trigger_type=trigger_type,
            actor_no=actor_no,
            user_id=user_id,
            display_name=display_name,
            action=action,
            target=target,
            error=error,
            result_ref=result_ref,
            content=content,
            snapshot=snapshot,
        )
        if immediate:
            self.send_event_payload(payload)
        else:
            threading.Thread(target=self.send_event_payload, args=(payload,), daemon=True).start()
        return payload

    def build_event_payload(self, record_type: str, **fields: Any) -> dict[str, Any]:
        now = datetime.now()
        business_day = now.date() if now.hour >= 8 else (now - timedelta(days=1)).date()
        action = fields.get("action") if isinstance(fields.get("action"), Mapping) else {}
        action_fields = action.get("fields") if isinstance(action.get("fields"), Mapping) else {}
        item_kind = "出入" if action.get("kind") == "entry_log" else "工作" if action.get("kind") == "work_log" else str(action.get("kind", ""))
        payload = {
            "event_id": f"sinposmart-{now:%Y%m%d%H%M%S%f}-{uuid4().hex}",
            "occurred_at": now.isoformat(timespec="seconds"),
            "fire_day": business_day.isoformat(),
            "record_type": str(record_type or ""),
            "trigger_type": str(fields.get("trigger_type") or ""),
            "status": str(fields.get("status") or ""),
            "source": "SinpoSmart",
            "error": str(fields.get("error") or "")[:1000],
            "result_ref": str(fields.get("result_ref") or ""),
            "snapshot": sanitize_payload(dict(fields.get("snapshot") or {})),
            "actor_no": str(fields.get("actor_no") or ""),
            "user_id": str(fields.get("user_id") or ""),
            "display_name": str(fields.get("display_name") or ""),
            "item_kind": item_kind,
            "item_title": action_summary(action) if action else "",
            "content": str(
                fields.get("content")
                or action_fields.get("工作內容")
                or action_fields.get("領用事由及地點")
                or action.get("source")
                or ""
            )[:2000],
            "target": str(fields.get("target") or action.get("target") or ""),
            "target_time": str(action_fields.get("系統寫入時間") or action_fields.get("登打時間") or action_fields.get("工作時間") or action.get("time") or ""),
        }
        version_path = self.package_root / "VERSION.txt"
        try:
            payload["snapshot"].setdefault("app_version", version_path.read_text(encoding="utf-8-sig").strip())
        except OSError:
            payload["snapshot"].setdefault("app_version", "")
        payload["snapshot"].setdefault("workstation", socket.gethostname())
        return sanitize_payload(payload)

    def send_event_payload(self, payload: dict[str, Any]) -> None:
        with self._event_lock:
            pending = [*self._load_pending_events(), sanitize_payload(payload)]
            self._write_pending_events(pending)
            sent_count = 0
            try:
                for index, entry in enumerate(pending, start=1):
                    response = self._post_event(entry)
                    if str(response.get("ack_id") or "") != str(entry.get("event_id") or ""):
                        break
                    sent_count = index
            except Exception as exc:
                remaining = pending[sent_count:]
                self._write_pending_events(remaining)
                self._record_sync_status(
                    "event",
                    "failed",
                    self._safe_failure_detail(exc, "NAS 後台事件"),
                    pending_count=len(remaining),
                )
                return
            remaining = pending[sent_count:]
            self._write_pending_events(remaining)
            if remaining:
                self._record_sync_status(
                    "event",
                    "failed",
                    "NAS 後台事件同步失敗：未收到正確確認。",
                    pending_count=len(remaining),
                )
                return
            self._record_sync_status("event", "ok", "NAS 後台事件已同步。", pending_count=0)

    def sync_board_async(self, schedule_data: Mapping[str, Any]) -> bool:
        if not self.board_enabled:
            self._record_sync_status(
                "board",
                "disabled",
                "尚未設定 Google 值班名牌同步 URL 或同步密鑰。",
            )
            return False
        payload = build_duty_board_payload(schedule_data)
        content_hash = payload["content_hash"]
        with self._board_lock:
            if content_hash == self._last_board_hash or content_hash in self._board_inflight_hashes:
                return False
            self._board_inflight_hashes.add(content_hash)
        threading.Thread(target=self._sync_board_worker, args=(payload,), daemon=True).start()
        return True

    def sync_board(self, schedule_data: Mapping[str, Any]) -> bool:
        """Synchronize one board snapshot in the caller's managed worker."""

        if not self.board_enabled:
            self._record_sync_status(
                "board",
                "disabled",
                "尚未設定 Google 值班名牌同步 URL 或同步密鑰。",
            )
            return False
        payload = build_duty_board_payload(schedule_data)
        content_hash = payload["content_hash"]
        with self._board_lock:
            if content_hash == self._last_board_hash or content_hash in self._board_inflight_hashes:
                return False
            self._board_inflight_hashes.add(content_hash)
        try:
            return self.sync_board_payload(payload)
        finally:
            with self._board_lock:
                self._board_inflight_hashes.discard(content_hash)

    def sync_board_payload(self, payload: dict[str, Any]) -> bool:
        content_hash = str(payload.get("content_hash") or "")
        try:
            self._post_board(payload)
        except Exception as exc:
            self._record_sync_status(
                "board",
                "failed",
                self._safe_failure_detail(exc, "Google 值班名牌"),
            )
            return False
        with self._board_lock:
            self._last_board_hash = content_hash
        self._record_sync_status("board", "ok", "Google 值班名牌已同步。")
        return True

    def _sync_board_worker(self, payload: dict[str, Any]) -> None:
        content_hash = str(payload.get("content_hash") or "")
        try:
            self.sync_board_payload(payload)
        finally:
            with self._board_lock:
                self._board_inflight_hashes.discard(content_hash)

    def _post_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._event_poster is not None:
            return self._event_poster(payload)
        url = self.event_url
        token = os.environ.get("SINPOSMART_CREDENTIAL_SYNC_TOKEN", "").strip()
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Credential-Sync-Token": token},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self._timeout("SINPOSMART_BACKEND_EVENT_TIMEOUT_SECONDS", 5)) as response:
            result = json.loads(response.read().decode("utf-8") or "{}")
        if not isinstance(result, dict) or not result.get("ok"):
            raise RuntimeError("SinpoSmart 後台事件未回報成功。")
        return result

    def _post_board(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._board_poster is not None:
            return self._board_poster(payload)
        url = os.environ.get("SINPOSMART_DUTY_BOARD_SYNC_URL", "").strip()
        sync_key = os.environ.get("SINPOSMART_DUTY_BOARD_SYNC_KEY", "").strip()
        body = {"sync_key": sync_key, "payload": payload}
        request = urllib.request.Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self._timeout("SINPOSMART_DUTY_BOARD_SYNC_TIMEOUT_SECONDS", 8)) as response:
            result = json.loads(response.read().decode("utf-8") or "{}")
        if not isinstance(result, dict) or not result.get("ok"):
            raise RuntimeError("Google Site 看板同步未回報成功。")
        return result

    def _load_pending_events(self) -> list[dict[str, Any]]:
        try:
            lines = self.pending_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        entries = []
        for line in lines:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                entries.append(entry)
        return entries

    def _write_pending_events(self, entries: list[dict[str, Any]]) -> None:
        self.pending_path.parent.mkdir(parents=True, exist_ok=True)
        body = "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries)
        self.pending_path.write_text(body, encoding="utf-8")

    def record_unhandled_failure(self, operation: str, error: BaseException) -> None:
        """Persist a safe status when a Qt worker exits unexpectedly."""

        channel = "board" if operation == "board" else "event"
        label = "Google 值班名牌" if channel == "board" else "NAS 後台事件"
        self._record_sync_status(channel, "failed", self._safe_failure_detail(error, label))

    def _record_sync_status(
        self,
        channel: str,
        state: str,
        detail: str,
        *,
        pending_count: int | None = None,
    ) -> None:
        try:
            current = self._load_sync_status()
            status = {
                "state": str(state or "unknown"),
                "detail": str(detail or "")[:300],
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }
            if pending_count is not None:
                status["pending_count"] = max(0, int(pending_count))
            current[str(channel)] = status
            current["updated_at"] = status["updated_at"]
            self.status_path.parent.mkdir(parents=True, exist_ok=True)
            self.status_path.write_text(
                json.dumps(sanitize_payload(current), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            return

    def _load_sync_status(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return dict(payload) if isinstance(payload, Mapping) else {}

    @staticmethod
    def _safe_failure_detail(error: BaseException, label: str) -> str:
        if isinstance(error, urllib.error.HTTPError):
            return f"{label}同步失敗：HTTP {error.code}。"
        if isinstance(error, (urllib.error.URLError, TimeoutError, OSError)):
            return f"{label}同步失敗：連線或逾時。"
        return f"{label}同步失敗，請匯出問題包。"

    @staticmethod
    def _timeout(name: str, default: int) -> int:
        try:
            return max(1, int(os.environ.get(name, str(default))))
        except ValueError:
            return default
