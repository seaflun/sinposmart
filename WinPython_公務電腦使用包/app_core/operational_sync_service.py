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
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from app_core.duty_task_projection import action_summary
from app_core.credential_sync_service import SyncTransportError, open_sync_request
from app_core.diagnostics_service import MAX_DIAGNOSTIC_ARCHIVE_BYTES


JsonPoster = Callable[[dict[str, Any]], dict[str, Any]]
SENSITIVE_KEY_PARTS = ("password", "passwd", "token", "secret", "cookie", "authorization")
DEFAULT_SINPOSMART_BACKEND_EVENT_URL = "http://10.30.65.30:8080/api/sinposmart/events"
SYNC_STATUS_FILENAME = "sinposmart_operational_sync_status.json"
GUI_HEARTBEAT_INTERVAL_MS = 10_000
HEARTBEAT_STATES = frozenset({"starting", "idle", "busy", "updating", "failed", "stopping"})
HEARTBEAT_LOGIN_STATES = frozenset({"unknown", "logged_out", "logging_in", "logged_in"})
HEARTBEAT_PHASES = frozenset({
    "startup", "idle", "busy", "preparing", "staged", "waiting_handoff", "waiting_parent",
    "preflight", "waiting_busy", "applying", "installing", "environment_check", "restarting",
    "waiting_gui", "completed", "failed", "stopping", "unknown",
})
HEARTBEAT_RESULTS = frozenset({"", "installer_failed", "gui_start_failed", "gui_ready_timeout", "update_completed", "closed"})


def _heartbeat_uuid(value: Any, *, empty: bool = False) -> bool:
    if not isinstance(value, str):
        return False
    if empty and value == "":
        return True
    try:
        return str(UUID(value)) == value.lower()
    except (ValueError, AttributeError):
        return False


def _valid_heartbeat_payload(payload: Mapping[str, Any]) -> bool:
    fields = {"schema_version", "workstation", "component", "instance_id", "process_started_at",
              "process_id", "sequence", "app_version", "state", "login_state", "phase",
              "update_request_id", "target_version", "result_code", "exit_code", "progress_percent"}
    if set(payload) != fields:
        return False
    if (type(payload["schema_version"]) is not int or payload["schema_version"] != 1
            or not isinstance(payload["workstation"], str)
            or re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", payload["workstation"]) is None
            or payload["component"] not in {"gui", "installer"}
            or not _heartbeat_uuid(payload["instance_id"])
            or not isinstance(payload["process_started_at"], str)):
        return False
    try:
        started = datetime.fromisoformat(payload["process_started_at"])
        if started.utcoffset() is None:
            return False
    except ValueError:
        return False
    if any(type(payload[key]) is not int or payload[key] <= 0 for key in ("process_id", "sequence")):
        return False
    if not isinstance(payload["app_version"], str) or re.fullmatch(r"\d{4}\.\d{2}\.\d{2}\.\d{4}", payload["app_version"]) is None:
        return False
    if (not isinstance(payload["target_version"], str)
            or (payload["target_version"] and re.fullmatch(r"\d{4}\.\d{2}\.\d{2}\.\d{4}", payload["target_version"]) is None)
            or not _heartbeat_uuid(payload["update_request_id"], empty=True)
            or payload["state"] not in HEARTBEAT_STATES
            or payload["login_state"] not in HEARTBEAT_LOGIN_STATES
            or payload["phase"] not in HEARTBEAT_PHASES
            or payload["result_code"] not in HEARTBEAT_RESULTS):
        return False
    if payload["component"] == "installer" and (not payload["update_request_id"] or payload["login_state"] != "unknown"):
        return False
    for key, minimum, maximum in (("exit_code", -1, 65535), ("progress_percent", 0, 100)):
        value = payload[key]
        if value is not None and (type(value) is not int or not minimum <= value <= maximum):
            return False
    return len(json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")) <= 4096


def canonical_workstation_name() -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "-", socket.gethostname())[:64] or "sinposmart-duty-gui"


class GuiHeartbeatReporter:
    """Coalesce producer pulses; network work never creates proof of UI liveness."""

    def __init__(self, service: OperationalSyncService, *, component: str, app_version: str,
                 request_id: str = "", target_version: str = "", instance_id: str | None = None,
                 process_started_at: str | None = None, process_id: int | None = None) -> None:
        self._service = service
        self._base = {
            "schema_version": 1,
            "workstation": canonical_workstation_name(),
            "component": component,
            "instance_id": instance_id if instance_id is not None else str(uuid4()),
            "process_started_at": process_started_at if process_started_at is not None else datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            "process_id": process_id if process_id is not None else os.getpid(),
            "app_version": app_version,
            "update_request_id": request_id,
            "target_version": target_version,
        }
        self._condition = threading.Condition()
        self._pending: dict[str, Any] | None = None
        self._sequence = 0
        self._closed = False
        self._thread: threading.Thread | None = None

    def pulse(self, *, state: str, login_state: str = "unknown", phase: str = "unknown",
              update_request_id: str | None = None, target_version: str | None = None,
              result_code: str = "", exit_code: int | None = None,
              progress_percent: int | None = None) -> bool:
        if getattr(self._service, "heartbeat_enabled", False) is not True:
            return False
        with self._condition:
            if self._closed:
                return False
            request_id = self._base["update_request_id"] if update_request_id is None else update_request_id
            if self._base["component"] == "installer" and request_id != self._base["update_request_id"]:
                return False
            if self._base["component"] == "installer" and target_version not in (None, self._base["target_version"]):
                return False
            payload = {**self._base, "sequence": self._sequence + 1, "state": state,
                       "login_state": login_state, "phase": phase, "update_request_id": request_id,
                       "target_version": self._base["target_version"] if target_version is None else target_version,
                       "result_code": result_code, "exit_code": exit_code, "progress_percent": progress_percent}
            try:
                valid = _valid_heartbeat_payload(payload)
            except (TypeError, ValueError):
                valid = False
            if not valid:
                return False
            self._sequence += 1
            self._pending = payload
            if self._thread is None:
                self._thread = threading.Thread(target=self._send_pending, name="SinpoSmart-heartbeat", daemon=True)
                self._thread.start()
            self._condition.notify()
            return True

    def _send_pending(self) -> None:
        while True:
            with self._condition:
                while self._pending is None and not self._closed:
                    self._condition.wait()
                if self._pending is None:
                    return
                payload, self._pending = self._pending, None
            try:
                self._service.send_heartbeat(payload)
            except Exception:
                pass  # No replay: only a subsequent real producer pulse may recover liveness.

    def stop(self, *, timeout: float = 1.0) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(max(0.0, min(float(timeout), 1.0)))


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
        members = [
            (str(info.get("name", "")).strip(), info.get("role", ""))
            for number in numbers
            if isinstance(info := staff.get(number, {}), Mapping)
        ]
        slots.append(
            {
                "slot": slot,
                "start_hour": int(match.group(1)),
                "end_hour": int(match.group(2)),
                "duty_nos": numbers,
                "names": [name for name, _role in members if name],
                "roles": [role.strip() if isinstance(role, str) else "" for name, role in members if name],
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
        diagnostic_poster: Callable[[Path, str], dict[str, Any]] | None = None,
    ) -> None:
        self.package_root = Path(package_root)
        self.pending_path = self.package_root / "runtime_outputs" / "sinposmart_backend_events_pending.jsonl"
        self.status_path = self.package_root / "runtime_outputs" / SYNC_STATUS_FILENAME
        self._event_poster = event_poster
        self._board_poster = board_poster
        self._diagnostic_poster = diagnostic_poster
        self._diagnostic_path = self.package_root / "runtime_outputs" / "sinposmart_diagnostics_outbox.json"
        self._diagnostic_lock = threading.Lock()
        self._diagnostic_send_lock = threading.Lock()
        self._event_lock = threading.Lock()
        self._event_send_lock = threading.Lock()
        self._board_lock = threading.Lock()
        self._status_lock = threading.Lock()
        self._last_board_hash = ""
        self._board_inflight_hashes: set[str] = set()
        self._heartbeat_lock = threading.Lock()
        self._heartbeat_server_id = ""
        self._heartbeat_endpoint = self._heartbeat_base_url()
        self._heartbeat_token = os.environ.get("SINPOSMART_CREDENTIAL_SYNC_TOKEN", "").strip()

    def _heartbeat_base_url(self) -> str:
        try:
            endpoint = urllib.parse.urlsplit(self.event_url)
            if (endpoint.scheme not in {"http", "https"} or not endpoint.hostname
                    or endpoint.username is not None or endpoint.password is not None
                    or endpoint.path != "/api/sinposmart/events"):
                return ""
            endpoint.port  # Reject malformed ports before starting any network request.
            return urllib.parse.urlunsplit((endpoint.scheme, endpoint.netloc, "/api/sinposmart", "", ""))
        except ValueError:
            return ""

    @property
    def heartbeat_enabled(self) -> bool:
        return bool(self._heartbeat_endpoint and self._heartbeat_token)

    def _heartbeat_request(self, suffix: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Accept": "application/json", "X-Credential-Sync-Token": self._heartbeat_token}
        body = None
        if payload is not None:
            body = json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")
            if len(body) > 4096:
                raise ValueError("心跳格式不符。")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self._heartbeat_endpoint + suffix, data=body, headers=headers,
                                         method="GET" if body is None else "POST")
        try:
            with open_sync_request(request, timeout=3) as response:
                raw = response.read(8193)
        except urllib.error.HTTPError as error:
            error.close()
            raise RuntimeError("心跳連線未獲確認。") from None
        if len(raw) > 8192:
            raise ValueError("心跳回應格式不符。")
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict) or value.get("ok") is not True:
            raise ValueError("心跳回應格式不符。")
        server = value.get("server")
        if (not isinstance(server, dict) or not _heartbeat_uuid(server.get("instance_id"))
                or not isinstance(server.get("version"), str) or len(server["version"]) > 64
                or not isinstance(server.get("deployment"), str) or len(server["deployment"]) > 64):
            raise ValueError("心跳伺服器身分無法確認。")
        if payload is not None:
            received_at = value.get("received_at")
            if (not isinstance(received_at, str) or len(received_at) > 64
                    or datetime.fromisoformat(received_at).utcoffset() is None):
                raise ValueError("心跳確認時間不符。")
        return value

    def send_heartbeat(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Send only the current technical pulse; never touch the event outbox."""
        try:
            if not self.heartbeat_enabled or not _valid_heartbeat_payload(payload):
                raise ValueError("心跳格式或設定不符。")
            with self._heartbeat_lock:
                if not self._heartbeat_server_id:
                    identity = self._heartbeat_request("/identity")
                    self._heartbeat_server_id = identity["server"]["instance_id"]
                outgoing = {**payload, "route": {"name": "configured", "identity_status": "verified",
                                                "instance_id": self._heartbeat_server_id}}
                response = self._heartbeat_request("/heartbeat", outgoing)
                if (response["server"]["instance_id"] != self._heartbeat_server_id
                        or type(response.get("accepted")) is not bool
                        or not isinstance(response.get("received_at"), str)):
                    raise ValueError("心跳伺服器身分或確認不符。")
            self._record_sync_status("heartbeat", "ok" if response["accepted"] else "failed",
                                     "值班台心跳已同步。" if response["accepted"] else "值班台心跳未被採用。")
            return response
        except SyncTransportError as error:
            self._record_sync_status("heartbeat", "failed", str(error))
            raise RuntimeError(str(error)) from None
        except Exception:
            self._record_sync_status("heartbeat", "failed", "值班台心跳無法確認連線。")
            raise RuntimeError("值班台心跳無法確認連線。") from None

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
        durable_only: bool = False,
    ) -> dict[str, Any] | None:
        if not self.event_enabled and not durable_only:
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
        if durable_only:
            self.persist_event_payload(payload)
        elif immediate:
            self.send_event_payload(payload)
        else:
            threading.Thread(target=self.send_event_payload, args=(payload,), daemon=True).start()
        return payload

    def build_event_payload(self, record_type: str, **fields: Any) -> dict[str, Any]:
        now = datetime.now()
        if record_type == "notice_collection":
            snapshot = fields.get("snapshot") or {}
            report = snapshot.get("notice_collection") or {}
            now = datetime.fromisoformat(report.get("reported_at", ""))
            if now.tzinfo is None:
                raise ValueError("Notice reports require an aware reported_at timestamp")
            now = now.astimezone(timezone(timedelta(hours=8)))
        business_day = now.date() if now.hour >= 8 else (now - timedelta(days=1)).date()
        action = fields.get("action") if isinstance(fields.get("action"), Mapping) else {}
        action_fields = action.get("fields") if isinstance(action.get("fields"), Mapping) else {}
        item_kind = "出入" if action.get("kind") == "entry_log" else "工作" if action.get("kind") == "work_log" else str(action.get("kind", ""))
        target = str(fields.get("target") or action.get("target") or "")
        item_title = action_summary(action) if action else ""
        if action_fields.get("領用事由及地點") == "到勤" and target:
            item_title = f"{item_title} ｜ {target}"
        payload = {
            "event_id": f"sinposmart-{now:%Y%m%d%H%M%S%f}-{uuid4().hex}",
            "occurred_at": now.isoformat() if record_type == "notice_collection" else now.isoformat(timespec="seconds"),
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
            "item_title": item_title,
            "content": str(
                fields.get("content")
                or action_fields.get("工作內容")
                or action_fields.get("領用事由及地點")
                or action.get("source")
                or ""
            )[:2000],
            "target": target,
            "target_time": str(action_fields.get("系統寫入時間") or action_fields.get("登打時間") or action_fields.get("工作時間") or action.get("time") or ""),
        }
        version_path = self.package_root / "VERSION.txt"
        try:
            payload["snapshot"].setdefault("app_version", version_path.read_text(encoding="utf-8-sig").strip())
        except OSError:
            payload["snapshot"].setdefault("app_version", "")
        if record_type == "notice_collection":
            payload["snapshot"]["workstation"] = canonical_workstation_name()
        else:
            payload["snapshot"].setdefault("workstation", socket.gethostname())
        return sanitize_payload(payload)

    def send_event_payload(self, payload: dict[str, Any]) -> None:
        self.persist_event_payload(payload)
        self.drain_event_queue()

    def drain_event_queue(self) -> None:
        """Deliver existing IDs without holding the local admission lock during HTTP."""
        with self._event_send_lock:
            with self._event_lock:
                pending = self._load_pending_events()
            for entry in pending:
                try:
                    response = self._post_event(entry)
                    if str(response.get("ack_id") or "") != str(entry.get("event_id") or ""):
                        raise RuntimeError("NAS 後台事件同步失敗：未收到正確確認。")
                except Exception as exc:
                    with self._event_lock:
                        remaining = self._load_pending_events()
                    self._record_sync_status("event", "failed", self._safe_failure_detail(exc, "NAS 後台事件"),
                                             pending_count=len(remaining))
                    return
                with self._event_lock:
                    # Admission may have added more parts while this HTTP request was in flight.
                    remaining = [item for item in self._load_pending_events()
                                 if str(item.get("event_id") or "") != str(entry.get("event_id") or "")]
                    self._write_pending_events(remaining)
            with self._event_lock:
                remaining = self._load_pending_events()
            self._record_sync_status("event", "pending" if remaining else "ok",
                "NAS 後台事件已安全排入本機佇列。" if remaining else "NAS 後台事件已同步。", pending_count=len(remaining))

    def persist_event_payload(self, payload: Mapping[str, Any]) -> None:
        """Durably queue one event without waiting for NAS HTTP delivery."""

        sanitized = sanitize_payload(dict(payload))
        event_id = str(sanitized.get("event_id") or "")
        with self._event_lock:
            pending = self._load_pending_events()
            if not event_id or all(str(entry.get("event_id") or "") != event_id for entry in pending):
                pending.append(sanitized)
            self._write_pending_events(pending)
            self._record_sync_status(
                "event",
                "pending",
                "NAS 後台事件已安全排入本機佇列。",
                pending_count=len(pending),
            )

    def queue_diagnostic_package(self, package_path: Path) -> str:
        """Persist only a reference to a newly sanitized, immutable local report."""
        path = Path(package_path).resolve()
        if path.parent != (self.package_root / "issue_reports").resolve() or path.suffix != ".zip":
            raise ValueError("問題包不在允許的目錄。")
        if not 0 < path.stat().st_size <= MAX_DIAGNOSTIC_ARCHIVE_BYTES:
            raise ValueError("問題包超過容量限制。")
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo("manifest.json")
            if info.file_size > 65536:
                raise ValueError("問題包資訊超過限制。")
            manifest = json.loads(archive.read(info))
        if not isinstance(manifest, dict) or manifest.get("schema_version") != 1 or manifest.get("sanitized") is not True:
            raise ValueError("舊問題包尚未通過內容遮蔽，不自動上傳。")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        with self._diagnostic_lock:
            records = self._load_diagnostic_records()
            records.setdefault(digest, {"package_name": path.name, "state": "pending"})
            self._write_diagnostic_records(records)
        self._record_sync_status("diagnostic", "pending" if records[digest]["state"] != "uploaded" else "ok",
                                 "問題包已保存本機，等待 NAS 確認。" if records[digest]["state"] != "uploaded" else "問題包已由 NAS 確認。")
        return digest

    def _load_diagnostic_records(self) -> dict[str, dict[str, Any]]:
        if not self._diagnostic_path.exists():
            return {}
        records = json.loads(self._diagnostic_path.read_text(encoding="utf-8"))
        if not isinstance(records, dict) or any(
            re.fullmatch(r"[0-9a-f]{64}", key) is None or not isinstance(item, dict)
            or item.get("state") not in {"pending", "uploaded"}
            or not isinstance(item.get("package_name"), str)
            or Path(item["package_name"]).name != item["package_name"]
            for key, item in records.items()
        ):
            raise ValueError("問題包上傳佇列格式不符，已保留原檔。")
        return records

    def _write_diagnostic_records(self, records: dict[str, dict[str, Any]]) -> None:
        self._diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_text_atomically(self._diagnostic_path, json.dumps(records, ensure_ascii=False, indent=2))

    @property
    def has_pending_diagnostics(self) -> bool:
        try:
            with self._diagnostic_lock:
                return any(item["state"] == "pending" for item in self._load_diagnostic_records().values())
        except (OSError, ValueError):
            return True

    def drain_diagnostic_queue(self) -> None:
        """Upload outside the admission lock; a matching durable NAS receipt is required."""
        if self._diagnostic_poster is None and not (
            self._heartbeat_base_url() and os.environ.get("SINPOSMART_CREDENTIAL_SYNC_TOKEN", "").strip()
        ):
            self._record_sync_status("diagnostic", "disabled", "問題包已保留本機，等待 NAS 同步設定。")
            return
        with self._diagnostic_send_lock:
            try:
                with self._diagnostic_lock:
                    records = self._load_diagnostic_records()
            except (OSError, ValueError):
                self._record_sync_status("diagnostic", "failed", "無法讀取問題包上傳佇列，已保留原檔。")
                return
            pending = [(digest, item) for digest, item in records.items() if item["state"] == "pending"]
            attempts = 0
            for digest, item in pending:
                try:
                    path = (self.package_root / "issue_reports" / item["package_name"]).resolve()
                    if path.parent != (self.package_root / "issue_reports").resolve():
                        raise ValueError("問題包目錄不符。")
                    if not 0 < path.stat().st_size <= MAX_DIAGNOSTIC_ARCHIVE_BYTES or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                        raise ValueError("本機問題包已變更，無法確認上傳內容。")
                    if attempts >= 3:
                        break
                    attempts += 1
                    response = self._post_diagnostic(path, digest)
                    if response.get("ok") is not True or response.get("ack_id") != digest:
                        raise ValueError("未收到正確的問題包確認。")
                    with self._diagnostic_lock:
                        current = self._load_diagnostic_records()
                        current[digest]["state"] = "uploaded"
                        self._write_diagnostic_records(current)
                except Exception as exc:
                    self._record_sync_status("diagnostic", "failed", self._safe_failure_detail(exc, "NAS 問題包"))
                    continue
            if not self.has_pending_diagnostics:
                self._record_sync_status("diagnostic", "ok", "問題包已由 NAS 確認。", pending_count=0)

    def _post_diagnostic(self, path: Path, digest: str) -> dict[str, Any]:
        if self._diagnostic_poster is not None:
            return self._diagnostic_poster(path, digest)
        endpoint = self._heartbeat_base_url()
        if not endpoint:
            raise ValueError("NAS 問題包端點不符。")
        body = path.read_bytes()
        if len(body) > MAX_DIAGNOSTIC_ARCHIVE_BYTES or hashlib.sha256(body).hexdigest() != digest:
            raise ValueError("問題包內容已變更。")
        request = urllib.request.Request(endpoint + "/diagnostics/" + digest, data=body,
            headers={"Content-Type": "application/zip", "X-Credential-Sync-Token": os.environ.get("SINPOSMART_CREDENTIAL_SYNC_TOKEN", "").strip()},
            method="POST")
        with open_sync_request(request, timeout=self._timeout("SINPOSMART_BACKEND_EVENT_TIMEOUT_SECONDS", 5)) as response:
            raw = response.read(8193)
        if len(raw) > 8192:
            raise ValueError("問題包確認格式不符。")
        result = json.loads(raw.decode("utf-8"))
        if not isinstance(result, dict):
            raise ValueError("問題包確認格式不符。")
        return result

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
        with open_sync_request(request, timeout=self._timeout("SINPOSMART_BACKEND_EVENT_TIMEOUT_SECONDS", 5)) as response:
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
        with open_sync_request(request, timeout=self._timeout("SINPOSMART_DUTY_BOARD_SYNC_TIMEOUT_SECONDS", 8),
                               allow_google_redirects=True) as response:
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
        self._write_text_atomically(self.pending_path, body)

    def record_unhandled_failure(self, operation: str, error: BaseException) -> None:
        """Persist a safe status when a Qt worker exits unexpectedly."""

        channel = "board" if operation == "board" else "diagnostic" if operation == "diagnostic_drain" else "event"
        label = "Google 值班名牌" if channel == "board" else "NAS 問題包" if channel == "diagnostic" else "NAS 後台事件"
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
            with self._status_lock:
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
                self._write_text_atomically(
                    self.status_path,
                    json.dumps(sanitize_payload(current), ensure_ascii=False, indent=2),
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
    def _write_text_atomically(path: Path, body: str) -> None:
        temp_path = path.with_name(
            f".{path.name}.{os.getpid()}.{threading.get_ident()}.{uuid4().hex}.tmp"
        )
        try:
            temp_path.write_text(body, encoding="utf-8")
            temp_path.replace(path)
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _safe_failure_detail(error: BaseException, label: str) -> str:
        if isinstance(error, SyncTransportError):
            return f"{label}同步失敗：{error}"
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
