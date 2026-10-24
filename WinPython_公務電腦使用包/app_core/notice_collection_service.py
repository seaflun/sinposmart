# -*- coding: utf-8 -*-
"""Notice collection protocol and durable counts, independent of the Qt session."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
import copy
import hashlib
import hmac
import json
import os
import re
import urllib.request
from uuid import uuid4

from app_core.operational_sync_service import normalize_duty_board_day


FIXED_NOTICE_ACCOUNT = "tyfd01214"
TAIPEI = timezone(timedelta(hours=8))
APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbw5yM8234CMi67hkox091wgoubwNIuWC8yxtNsQ024SpbpXhAGWVC5hB-HU4UQQavPO1A/exec"
MAX_RECORDS = 200
NOTICE_ERROR_CODES = frozenset({
    "browser_start_failed", "browser_window_closed", "snapshot_failed", "snapshot_invalid",
    "origin_mismatch", "account_mismatch", "login_target_mismatch", "login_page_failed",
    "list_navigation_failed", "list_wait_timeout", "page_limit", "list_changed", "duplicate_notice_id",
    "next_page_ambiguous", "count_mismatch", "notice_url_invalid", "scan_unexpected",
    "session_expired", "login_failed", "credentials_missing", "cancelled",
})


def _safe_notice_error_code(value: object) -> str:
    return value if isinstance(value, str) and value in NOTICE_ERROR_CODES else ""


class NoticeCollectionError(RuntimeError):
    """Collection stopped without assuming an unconfirmed write succeeded."""

    def __init__(self, message: str, *, code: str = "") -> None:
        super().__init__(message)
        self.code = _safe_notice_error_code(code)


class NoticeLoginRequired(NoticeCollectionError):
    """The dedicated notice browser could not confirm automatic login."""


class _NoticeStateError(NoticeCollectionError):
    """A durable checkpoint could not be saved; do not continue official actions."""


@dataclass(frozen=True)
class NoticeShift:
    key: str
    label: str
    start: datetime
    end: datetime


@dataclass
class NoticeCollectionResult:
    checked_at: datetime
    written_keys: list[str] = field(default_factory=list)
    unread_count: int | None = 0
    marked_read_count: int | None = 0
    error_count: int = 0
    status: str = "success"
    message: str = "本次沒有未讀通報。"
    pending_write_count: int | None = None
    pending_read_count: int | None = None
    error_stage: str = ""
    error_code: str = ""


def _local_time(value: datetime) -> datetime:
    return value.replace(tzinfo=TAIPEI) if value.tzinfo is None else value.astimezone(TAIPEI)


def next_check_at(now: datetime) -> datetime:
    """Use clock-aligned periods; never schedule beyond the 08/22 boundary."""
    local = _local_time(now)
    minutes = 3 if 8 <= local.hour < 22 else 30
    floor = local.replace(second=0, microsecond=0, minute=local.minute // minutes * minutes)
    result = floor + timedelta(minutes=minutes)
    return result.replace(tzinfo=None) if now.tzinfo is None else result


def current_shift(schedule_data: dict, now: datetime) -> NoticeShift | None:
    """Find the station's present duty period, independently of the signed-in actor."""
    local = _local_time(now)
    fire_day = local.date() - timedelta(days=int(local.hour < 8))
    roc_date = f"{fire_day.year - 1911:03d}{fire_day:%m%d}"
    periods = set()
    for name in ("today", "tomorrow"):
        raw_day = schedule_data.get(name)
        if not isinstance(raw_day, dict):
            continue
        day = normalize_duty_board_day(raw_day)
        if day is None or day["roc_date"] != roc_date:
            continue
        for slot in day["slots"]:
            start_hour, end_hour = slot["start_hour"], slot["end_hour"]
            actors = tuple(sorted(set(slot["duty_nos"])))
            if not actors or not 0 <= start_hour < 24 or not 0 <= end_hour <= 24:
                continue
            start = datetime.combine(fire_day, datetime.min.time(), TAIPEI) + timedelta(
                hours=start_hour, days=int(start_hour < 8))
            end = datetime.combine(fire_day, datetime.min.time(), TAIPEI) + timedelta(
                hours=end_hour, days=int(end_hour < 8))
            if end <= start:
                end += timedelta(days=1)
            if end - start > timedelta(hours=24):
                continue
            periods.add((start, end, actors))
    merged = []
    for start, end, actors in sorted(periods):
        if merged and merged[-1][1] == start and merged[-1][2] == actors:
            merged[-1] = (merged[-1][0], end, actors)
        else:
            merged.append((start, end, actors))
    candidates = [p for p in merged if p[0] <= local < p[1]]
    if len(candidates) != 1:
        return None
    start, end, _actors = candidates[0]
    label = f"{start:%H}-{end:%H}" if start.date() == end.date() else f"{start:%H}-翌日{end:%H}"
    return NoticeShift(f"{start.isoformat()}/{end.isoformat()}", label, start, end)


class NoticeCollectionService:
    def __init__(self, package_root: Path, *, browser=None, poster=None, now_factory=None, sync_key_lookup=None):
        self.package_root = Path(package_root)
        self._browser = browser
        self._poster = poster
        self._sync_key_lookup = sync_key_lookup if sync_key_lookup is not None else self._default_sync_key
        self._now = now_factory or (lambda: datetime.now(TAIPEI))
        self.state_path = self.package_root / "runtime_outputs" / "notice_collection" / "state.json"
        self._state_error = False
        self.last_result: NoticeCollectionResult | None = None
        self._collection_stage = "scan"
        self._confirmed_for_read: set[str] = set()
        self._marked_for_read: set[str] = set()
        self._state = {"schema_version": 1, "collected": {}, "pending": [], "confirmed": {}}
        if self.state_path.exists():
            try:
                state = json.loads(self.state_path.read_text(encoding="utf-8"))
                if (state.get("schema_version") != 1 or not isinstance(state["collected"], dict)
                        or not isinstance(state["pending"], list)):
                    raise ValueError("invalid ledger")
                for key, timestamp in state["collected"].items():
                    if not isinstance(key, str) or not isinstance(timestamp, str):
                        raise ValueError("invalid ledger entry")
                    _local_time(datetime.fromisoformat(timestamp))
                for intent in state["pending"]:
                    if (not isinstance(intent, dict) or not isinstance(intent.get("records"), list)
                            or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", intent.get("request_id", ""))):
                        raise ValueError("invalid pending request")
                    _local_time(datetime.fromisoformat(intent["received_at"]))
                    for row in intent["records"]:
                        self._record_key(row)
                    repair_keys = intent.get("repair_keys", [])
                    if (not isinstance(repair_keys, list)
                            or not all(isinstance(key, str) for key in repair_keys)
                            or not set(repair_keys) <= {row["key"] for row in intent["records"]}):
                        raise ValueError("invalid pending repair classification")
                metadata = state.setdefault("confirmed", {})
                if not isinstance(metadata, dict):
                    raise ValueError("invalid confirmed metadata")
                for key, record in metadata.items():
                    if (key not in state["collected"] or not isinstance(record, dict)
                            or not isinstance(record.get("subject", ""), str)
                            or record.get("read_state", "unknown") not in {"confirmed", "pending", "unknown"}):
                        raise ValueError("invalid confirmed record")
                self._state = state
            except (OSError, ValueError, KeyError, TypeError, AttributeError, NoticeCollectionError):
                self._state_error = True

    def verify_login(self, password: str, cancel=None) -> NoticeCollectionResult:
        """Verify a fresh fixed-account login without collecting or changing counts."""
        self._check_cancel(cancel)
        if not isinstance(password, str) or not password:
            raise NoticeLoginRequired("請先設定通報帳號 tyfd01214 的密碼。")
        try:
            if self._browser is None:
                from app_core.notice_collection_browser import NoticeBrowser
                self._browser = NoticeBrowser(self.package_root)
            self._check_cancel(cancel)
            self._browser.begin_login_verification(password)
            self._check_cancel(cancel)
            rows = self._browser.scan_unread(password, cancel=cancel)
            self._check_cancel(cancel)
            if not isinstance(rows, list):
                raise NoticeCollectionError("通報登入驗證未取得完整的未讀列表。")
            keys = {self._record_key(row) for row in rows}
        except NoticeCollectionError:
            raise
        except Exception:
            raise NoticeCollectionError("通報登入驗證未完成，請確認帳密、網站與網路狀態。") from None
        return NoticeCollectionResult(
            _local_time(self._now()), unread_count=len(keys), status="login_verified",
            message="通報帳號 tyfd01214 登入驗證成功。",
        )

    def collect(self, password: str, received_at: datetime, cancel=None) -> NoticeCollectionResult:
        received_at = _local_time(received_at)
        before = set(self._state["collected"])
        self.last_result = NoticeCollectionResult(received_at, unread_count=None, marked_read_count=None)
        self._confirmed_for_read, self._marked_for_read = set(), set()
        self._collection_stage = "scan"
        try:
            return self._collect(password, received_at, cancel)
        except Exception as exc:
            result = self.last_result
            result.written_keys = sorted(set(result.written_keys) | (set(self._state["collected"]) - before))
            result.status = ("uncertain" if self._state["pending"] else
                             "partial" if result.written_keys else "failed")
            result.error_stage = ("state" if isinstance(exc, _NoticeStateError) or self._state_error
                                  else "login" if isinstance(exc, NoticeLoginRequired)
                                  else self._collection_stage if isinstance(exc, NoticeCollectionError) else "unknown")
            result.error_code = _safe_notice_error_code(getattr(exc, "code", ""))
            if result.unread_count is not None:
                result.pending_write_count = self._pending_write_count()
                result.pending_read_count = len((self._confirmed_for_read | set(result.written_keys)) - self._marked_for_read)
            raise

    def _collect(self, password: str, received_at: datetime, cancel=None) -> NoticeCollectionResult:
        self._check_cancel(cancel)
        if self._state_error:
            raise NoticeCollectionError("通報收取紀錄無法讀取，請先確認本機紀錄；未送出通報。")
        if self._browser is None:
            from app_core.notice_collection_browser import NoticeBrowser
            self._browser = NoticeBrowser(self.package_root)
        scanned = self._browser.scan_unread(password, cancel=cancel)
        rows = list({self._record_key(row): dict(row) for row in scanned}.values())
        received_at = _local_time(received_at)
        result = self.last_result
        result.unread_count, result.marked_read_count = len(rows), 0
        result.pending_write_count, result.pending_read_count = 0, 0
        if not rows and not self._state["pending"]:
            return result
        self._collection_stage = "write"
        confirmed, recovered = self._recover_pending(cancel, rows)
        self._confirmed_for_read = confirmed
        result.written_keys.extend(recovered)
        blocked = {row["key"] for intent in self._state["pending"] for row in intent["records"]}
        for offset in range(0, len(rows), MAX_RECORDS):
            batch = [row for row in rows[offset:offset + MAX_RECORDS]
                     if row["key"] not in blocked and row["key"] not in confirmed]
            if not batch:
                continue
            self._check_cancel(cancel)
            self._collection_stage = "write"
            existing, repairs = self._check_existing(batch)
            confirmed.update(existing)
            records = []
            for row in batch:
                if row["key"] in existing:
                    continue
                self._check_cancel(cancel)
                self._collection_stage = "scan"
                try:
                    content = str(self._browser.read_content(row, cancel=cancel)).strip()
                except NoticeLoginRequired:
                    raise
                except Exception:
                    result.error_count += 1
                    result.error_stage = "scan"
                    continue
                if content in ("", "內文抓取失敗", "讀取失敗", "權限限制"):
                    result.error_count += 1
                    result.error_stage = "scan"
                    continue
                records.append({**self._metadata(row), "content": content,
                                "receivedAt": received_at.strftime("%Y.%m.%d.%H%M")})
            if records:
                self._check_cancel(cancel)
                self._collection_stage = "state"
                intent = {"request_id": "notice-" + uuid4().hex,
                          "received_at": received_at.isoformat(),
                          "records": [self._metadata(row) for row in records],
                          "repair_keys": sorted(repairs & {row["key"] for row in records})}
                state = copy.deepcopy(self._state)
                state["pending"].append(intent)
                self._persist(state)
                self._collection_stage = "write"
                payload = {"action": "writeRecords", "requestId": intent["request_id"], "records": records}
                try:
                    handled, written = self._write_with_recovery(intent, payload, cancel)
                except _NoticeStateError:
                    raise
                except NoticeCollectionError:
                    handled, written = set(), []
                confirmed.update(handled)
                result.written_keys.extend(written)
                result.error_count += len(records) - len(handled)
        to_mark = [row for row in rows if row["key"] in confirmed]
        if to_mark:
            self._check_cancel(cancel)
            self._collection_stage = "mark_read"
            try:
                marked = set(self._browser.mark_read(to_mark, cancel=cancel))
                expected = {row["key"] for row in to_mark}
                result.marked_read_count = len(marked & expected)
                result.error_count += len(expected - marked)
                self._marked_for_read = marked & expected
            except Exception:
                result.error_count += len(to_mark)
            result.pending_read_count = len({row["key"] for row in to_mark} - self._marked_for_read)
            if result.pending_read_count:
                result.error_stage = "mark_read"
        # A complete unread scan also confirms recovered receipts already absent
        # from that list, without claiming we marked them during this attempt.
        confirmed_read = self._marked_for_read | (confirmed - {row["key"] for row in rows})
        state = copy.deepcopy(self._state)
        changed = False
        for key in confirmed_read:
            if key in state["collected"]:
                record = state.setdefault("confirmed", {}).setdefault(key, {})
                if record.get("read_state") != "confirmed":
                    record["read_state"] = "confirmed"
                    changed = True
        if changed:
            self._collection_stage = "state"
            self._persist(state)
        pending_keys = {row["key"] for intent in self._state["pending"] for row in intent["records"]}
        result.error_count += len({row["key"] for row in rows} & (blocked - confirmed))
        result.pending_write_count = len(pending_keys)
        if pending_keys:
            result.error_stage = "write"
        result.status = "uncertain" if pending_keys else "partial" if result.error_count else "success"
        result.message = (f"已確認收取 {len(result.written_keys)} 則通報。" if not result.error_count
                          else "部分通報尚未完成收取或已讀確認，將保留未完成狀態。")
        if pending_keys:
            result.message = "通報寫入收據仍待確認；未確認的通報保留未讀，待下輪安全重試。"
        return result

    def _receipt(self, intent: dict) -> dict | None:
        try:
            response = self._post({"action": "getWriteResult", "requestId": intent["request_id"]})
            if (response.get("status") == "success" and isinstance(response.get("found"), bool)
                    and response.get("requestId") == intent["request_id"]):
                return {"status": "success", "requestId": intent["request_id"],
                        "found": response["found"], "result": response.get("result")}
        except NoticeCollectionError:
            pass
        return None

    def _recover_pending(self, cancel, rows: list[dict]) -> tuple[set[str], list[str]]:
        confirmed, written = set(), []
        for intent in list(self._state["pending"]):
            self._check_cancel(cancel)
            receipt = self._receipt(intent)
            if receipt is not None and receipt["found"]:
                try:
                    handled, recovered = self._finish_write(intent, receipt)
                    confirmed.update(handled)
                    written.extend(recovered)
                    continue
                except _NoticeStateError:
                    raise
                except NoticeCollectionError:
                    pass
            try:
                existing, _repairs = self._check_existing(intent["records"])
                confirmed.update(existing)
            except NoticeCollectionError:
                continue
            # Receipts expire after ten minutes. Complete durable rows settle an
            # old intent without guessing who wrote them or adding new counts.
            if existing == {row["key"] for row in intent["records"]}:
                state = copy.deepcopy(self._state)
                state["pending"] = [p for p in state["pending"] if p["request_id"] != intent["request_id"]]
                self._persist(state)
                continue
            if receipt is None or receipt["found"] is not False:
                continue
            records = self._rehydrate_pending(intent, rows, cancel)
            if records is None:
                continue
            self._check_cancel(cancel)
            self._collection_stage = "write"
            payload = {"action": "writeRecords", "requestId": intent["request_id"], "records": records}
            try:
                handled, recovered = self._write_with_recovery(intent, payload, cancel)
                confirmed.update(handled)
                written.extend(recovered)
            except _NoticeStateError:
                raise
            except NoticeCollectionError:
                pass
        return confirmed, written

    def _rehydrate_pending(self, intent: dict, rows: list[dict], cancel) -> list[dict] | None:
        """Re-read the same live notices; never persist their full content locally."""
        originals = intent["records"]
        current = {row["key"]: row for row in rows}
        if (not 0 < len(originals) <= MAX_RECORDS
                or len({row["key"] for row in originals}) != len(originals)):
            return None
        for row in originals:
            notice_id = str(row.get("noticeId", ""))
            if (not re.fullmatch(r"\d+", notice_id) or row["key"] != notice_id
                    or row["key"] not in current
                    or self._metadata(current[row["key"]]) != self._metadata(row)):
                return None
        received_at = _local_time(datetime.fromisoformat(intent["received_at"]))
        records = []
        for row in originals:
            self._check_cancel(cancel)
            self._collection_stage = "scan"
            try:
                content = str(self._browser.read_content(current[row["key"]], cancel=cancel)).strip()
            except NoticeLoginRequired:
                raise
            except Exception:
                return None
            if content in ("", "內文抓取失敗", "讀取失敗", "權限限制"):
                return None
            records.append({**self._metadata(row), "content": content,
                            "receivedAt": received_at.strftime("%Y.%m.%d.%H%M")})
        return records

    def _write_with_recovery(self, intent: dict, payload: dict, cancel) -> tuple[set[str], list[str]]:
        for attempt in range(2):
            self._check_cancel(cancel)
            response = None
            try:
                response = self._post(payload)
                return self._finish_write(intent, response)
            except _NoticeStateError:
                raise
            except NoticeCollectionError:
                if not any(p["request_id"] == intent["request_id"] for p in self._state["pending"]):
                    return set(), []
            self._check_cancel(cancel)
            receipt = self._receipt(intent)
            if receipt is not None and receipt["found"]:
                try:
                    return self._finish_write(intent, receipt)
                except _NoticeStateError:
                    raise
                except NoticeCollectionError:
                    pass
            try:
                existing, _repairs = self._check_existing(intent["records"])
            except NoticeCollectionError:
                existing = set()
            if existing == {row["key"] for row in intent["records"]}:
                return existing, []
            # A malformed/mismatched response is not a reason to issue a new write.
            # Transport/explicitly retryable failures get one receipt-checked retry,
            # using exactly the original request ID and records.
            if response is not None and not response.get("uncertain") and not response.get("retryable"):
                return existing, []
            if attempt == 1:
                return existing, []
        return set(), []

    def _check_existing(self, rows: list[dict]) -> tuple[set[str], set[str]]:
        response = self._post({"action": "checkExisting", "records": [self._metadata(row) for row in rows]})
        values = response.get("existingKeys")
        retry_values = response.get("retryKeys", [])
        if (response.get("status") != "success" or not isinstance(values, list)
                or not isinstance(retry_values, list)):
            raise NoticeCollectionError("試算表比對未完成，未擷取內文或標記已讀。")
        keys = {self._record_key(row) for row in rows}
        existing = {str(key) for key in values}
        repairs = {str(key) for key in retry_values}
        if not (existing | repairs) <= keys or existing & repairs:
            raise NoticeCollectionError("試算表比對的通報識別碼不符，已停止收取。")
        return existing, repairs

    def _finish_write(self, intent: dict, response: dict) -> tuple[set[str], list[str]]:
        if response.get("requestId") != intent["request_id"]:
            raise NoticeCollectionError("試算表寫入收據識別碼不符，保留待確認紀錄。")
        if response.get("status") != "success":
            if not response.get("uncertain") and not response.get("retryable"):
                state = copy.deepcopy(self._state)
                state["pending"] = [p for p in state["pending"] if p["request_id"] != intent["request_id"]]
                self._persist(state)
            raise NoticeCollectionError("試算表未確認寫入成功。")
        outcome = response.get("result")
        if (not isinstance(outcome, dict) or not isinstance(outcome.get("handledKeys"), list)
                or not isinstance(outcome.get("writtenKeys"), list)):
            raise NoticeCollectionError("試算表寫入收據不完整，保留待確認紀錄。")
        keys = {row["key"] for row in intent["records"]}
        handled = {str(key) for key in outcome["handledKeys"]}
        written = {str(key) for key in outcome["writtenKeys"]}
        if not written <= handled <= keys:
            raise NoticeCollectionError("試算表寫入收據通報識別碼不符，保留待確認紀錄。")
        state = copy.deepcopy(self._state)
        newly_written = sorted(written - set(intent.get("repair_keys", [])) - state["collected"].keys())
        for key in newly_written:
            state["collected"][key] = intent["received_at"]
            row = next(row for row in intent["records"] if row["key"] == key)
            state.setdefault("confirmed", {})[key] = {
                "subject": str(row.get("subject", ""))[:240], "read_state": "pending",
            }
        state["pending"] = [p for p in state["pending"] if p["request_id"] != intent["request_id"]]
        self._persist(state)
        return handled, newly_written

    def _pending_write_count(self) -> int:
        return len({row["key"] for intent in self._state["pending"] for row in intent["records"]})

    def report_parts(self, run_id: str, state: str, reported_at: datetime, *, started_at=None,
                     next_check: datetime, shift: NoticeShift | None = None,
                     result: NoticeCollectionResult | None = None, error_stage: str = "") -> list[dict]:
        """Export only confirmed metadata, keeping original receipt times and typed unknowns."""
        now = _local_time(reported_at)
        terminal = state not in {"running", "waiting", "missing_credentials"}
        if self._state_error:
            error_stage, result = "state", None
        raw_new = set(result.written_keys) if result is not None else set()
        records = []
        for key, received in self._state["collected"].items() if not self._state_error else ():
            received_at = _local_time(datetime.fromisoformat(received))
            if (received_at.date() != now.date() and key not in raw_new
                    and not (shift is not None and _local_time(shift.start) <= received_at < _local_time(shift.end))):
                continue
            metadata = self._state.get("confirmed", {}).get(key, {})
            records.append({"key": hashlib.sha256(key.encode("utf-8")).hexdigest(),
                "subject": str(metadata.get("subject", ""))[:240], "received_at": received_at.isoformat(),
                "read_state": metadata.get("read_state", "unknown")})
        records.sort(key=lambda row: (row["received_at"], row["key"]))
        new_keys = {hashlib.sha256(key.encode("utf-8")).hexdigest() for key in raw_new}
        messages = {
            "running": "正在檢查未讀通報。", "waiting": "等待公務作業完成後檢查通報。",
            "missing_credentials": "通報專用帳號尚未完成密碼設定。",
            "success": "本輪通報檢查已完成。", "partial": "部分通報尚未完成入表或已讀確認。",
            "uncertain": "通報寫入收據仍待確認，未確認的通報保留未讀。",
            "failed": "通報檢查未完成，請確認網站、登入或本機紀錄狀態。",
        }
        count = max(1, (len(records) + MAX_RECORDS - 1) // MAX_RECORDS)
        report = {"schema_version": 1, "run_id": run_id, "part_count": count, "state": state,
            "started_at": _local_time(started_at).isoformat() if started_at is not None else "",
            "completed_at": now.isoformat() if terminal else "", "reported_at": now.isoformat(),
            "next_check_at": _local_time(next_check).isoformat(), "calendar_day": now.date().isoformat(),
            "shift_start": _local_time(shift.start).isoformat() if shift is not None else "",
            "shift_end": _local_time(shift.end).isoformat() if shift is not None else "",
            "unread_count": result.unread_count if result is not None else None,
            "new_count": len(raw_new) if result is not None else None,
            "marked_read_count": result.marked_read_count if result is not None else None,
            "pending_write_count": result.pending_write_count if result is not None else None,
            "pending_read_count": result.pending_read_count if result is not None else None,
            "error_stage": error_stage or (result.error_stage if result is not None else ""),
            "message": messages[state]}
        error_code = _safe_notice_error_code(getattr(result, "error_code", ""))
        if state in {"failed", "partial", "uncertain"} and error_code:
            report["error_code"] = error_code
        return [{**report, "part_index": index,
                 "records": records[index * MAX_RECORDS:(index + 1) * MAX_RECORDS],
                 "new_keys": sorted(new_keys & {row["key"] for row in records[index * MAX_RECORDS:(index + 1) * MAX_RECORDS]})}
                for index in range(count)]

    def _persist(self, state: dict) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.state_path.with_name("state-" + uuid4().hex + ".tmp")
            temporary.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            temporary.replace(self.state_path)
        except OSError:
            raise _NoticeStateError("通報收取紀錄無法安全儲存，已停止寫入及已讀操作。") from None
        self._state = state

    @staticmethod
    def _default_sync_key() -> str:
        explicit = os.environ.get("SINPOSMART_NOTICE_COLLECTION_SYNC_KEY", "").strip()
        if explicit:
            return explicit
        token = os.environ.get("SINPOSMART_CREDENTIAL_SYNC_TOKEN", "").strip()
        return (hmac.new(token.encode("utf-8"), b"SinpoSmartNoticeCollection:v1", hashlib.sha256).hexdigest()
                if token else "")

    def _post(self, payload: dict) -> dict:
        try:
            if self._poster is not None:
                response = self._poster(payload)
            else:
                sync_key = self._sync_key_lookup()
                if not isinstance(sync_key, str) or not sync_key.strip():
                    raise ValueError("notice authorization is not configured")
                body = {**payload, "sync_key": sync_key.strip()}
                request = urllib.request.Request(
                    APPS_SCRIPT_URL, json.dumps(body, ensure_ascii=False).encode("utf-8"),
                    {"Content-Type": "text/plain;charset=utf-8"}, method="POST")
                with urllib.request.urlopen(request, timeout=45) as opened:
                    response = json.loads(opened.read(5 * 1024 * 1024))
            if not isinstance(response, dict):
                raise ValueError("invalid response")
            return response
        except Exception:
            raise NoticeCollectionError("通報試算表連線或回覆未確認，請稍後再檢查。") from None

    @staticmethod
    def _record_key(row: dict) -> str:
        if not isinstance(row, dict):
            raise NoticeCollectionError("通報識別資料不完整，已停止收取。")
        key = str(row.get("key") or row.get("noticeId") or "").strip()
        if not key or not re.fullmatch(r"\d{3}-\d{2}-\d{2}", str(row.get("date", ""))):
            raise NoticeCollectionError("通報識別資料不完整，已停止收取。")
        row["key"] = key
        return key

    @staticmethod
    def _metadata(row: dict) -> dict:
        return {name: str(row.get(name, "") or "") for name in ("key", "date", "noticeId", "subject", "sender")}

    @staticmethod
    def _check_cancel(cancel) -> None:
        if cancel is not None and cancel():
            raise NoticeCollectionError("通報收取已停止，未開始新的寫入或已讀操作。", code="cancelled")

    def counts(self, now: datetime, shift: NoticeShift | None = None) -> tuple[int, int]:
        if self._state_error:
            raise NoticeCollectionError("通報收取紀錄無法讀取，統計暫時無法確認。")
        local = _local_time(now)
        timestamps = [_local_time(datetime.fromisoformat(value)) for value in self._state["collected"].values()]
        today = sum(value.date() == local.date() for value in timestamps)
        shift_count = (sum(_local_time(shift.start) <= value < _local_time(shift.end) for value in timestamps)
                       if shift is not None else 0)
        return shift_count, today

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
