# -*- coding: utf-8 -*-
"""Notice collection protocol and durable counts, independent of the Qt session."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
import copy
import json
import re
import urllib.request
from uuid import uuid4

from app_core.operational_sync_service import normalize_duty_board_day


FIXED_NOTICE_ACCOUNT = "tyfd01214"
TAIPEI = timezone(timedelta(hours=8))
APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbw5yM8234CMi67hkox091wgoubwNIuWC8yxtNsQ024SpbpXhAGWVC5hB-HU4UQQavPO1A/exec"
MAX_RECORDS = 200


class NoticeCollectionError(RuntimeError):
    """Collection stopped without assuming an unconfirmed write succeeded."""


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
    unread_count: int = 0
    marked_read_count: int = 0
    error_count: int = 0
    status: str = "success"
    message: str = "本次沒有未讀通報。"


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
    def __init__(self, package_root: Path, *, browser=None, poster=None, now_factory=None):
        self.package_root = Path(package_root)
        self._browser = browser
        self._poster = poster
        self._now = now_factory or (lambda: datetime.now(TAIPEI))
        self.state_path = self.package_root / "runtime_outputs" / "notice_collection" / "state.json"
        self._state_error = False
        self._state = {"schema_version": 1, "collected": {}, "pending": []}
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
        self._check_cancel(cancel)
        if self._state_error:
            raise NoticeCollectionError("通報收取紀錄無法讀取，請先確認本機紀錄；未送出通報。")
        if self._browser is None:
            from app_core.notice_collection_browser import NoticeBrowser
            self._browser = NoticeBrowser(self.package_root)
        scanned = self._browser.scan_unread(password, cancel=cancel)
        rows = list({self._record_key(row): dict(row) for row in scanned}.values())
        received_at = _local_time(received_at)
        result = NoticeCollectionResult(received_at, unread_count=len(rows))
        if not rows and not self._state["pending"]:
            return result
        confirmed, recovered = self._recover_pending(cancel)
        result.written_keys.extend(recovered)
        blocked = {row["key"] for intent in self._state["pending"] for row in intent["records"]}
        for offset in range(0, len(rows), MAX_RECORDS):
            batch = [row for row in rows[offset:offset + MAX_RECORDS] if row["key"] not in blocked]
            if not batch:
                continue
            self._check_cancel(cancel)
            existing, repairs = self._check_existing(batch)
            confirmed.update(existing)
            records = []
            for row in batch:
                if row["key"] in existing:
                    continue
                self._check_cancel(cancel)
                try:
                    content = str(self._browser.read_content(row, cancel=cancel)).strip()
                except NoticeLoginRequired:
                    raise
                except Exception:
                    result.error_count += 1
                    continue
                if content in ("", "內文抓取失敗", "讀取失敗", "權限限制"):
                    result.error_count += 1
                    continue
                records.append({**self._metadata(row), "content": content,
                                "receivedAt": received_at.strftime("%Y.%m.%d.%H%M")})
            if records:
                self._check_cancel(cancel)
                intent = {"request_id": "notice-" + uuid4().hex,
                          "received_at": received_at.isoformat(),
                          "records": [self._metadata(row) for row in records],
                          "repair_keys": sorted(repairs & {row["key"] for row in records})}
                state = copy.deepcopy(self._state)
                state["pending"].append(intent)
                self._persist(state)
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
            try:
                marked = set(self._browser.mark_read(to_mark, cancel=cancel))
                expected = {row["key"] for row in to_mark}
                result.marked_read_count = len(marked & expected)
                result.error_count += len(expected - marked)
            except Exception:
                result.error_count += len(to_mark)
        pending_keys = {row["key"] for intent in self._state["pending"] for row in intent["records"]}
        result.error_count += len({row["key"] for row in rows} & (blocked - confirmed))
        result.status = "uncertain" if pending_keys else "partial" if result.error_count else "success"
        result.message = (f"已確認收取 {len(result.written_keys)} 則通報。" if not result.error_count
                          else "部分通報尚未完成收取或已讀確認，將保留未完成狀態。")
        if pending_keys:
            result.message = "通報寫入收據仍待確認；不重複送出，未確認的通報保留未讀。"
        return result

    def _receipt(self, intent: dict) -> dict | None:
        try:
            response = self._post({"action": "getWriteResult", "requestId": intent["request_id"]})
            if (response.get("status") == "success" and response.get("found") is True
                    and response.get("requestId") == intent["request_id"]):
                return {"status": "success", "requestId": intent["request_id"], "result": response.get("result")}
        except NoticeCollectionError:
            pass
        return None

    def _recover_pending(self, cancel) -> tuple[set[str], list[str]]:
        confirmed, written = set(), []
        for intent in list(self._state["pending"]):
            self._check_cancel(cancel)
            receipt = self._receipt(intent)
            if receipt is not None:
                try:
                    handled, recovered = self._finish_write(intent, receipt)
                    confirmed.update(handled)
                    written.extend(recovered)
                    continue
                except _NoticeStateError:
                    raise
                except NoticeCollectionError:
                    pass
            # Existence permits marking, but cannot prove who added the row.
            # Keep the receipt intent and do not inflate the GUI's new count.
            try:
                existing, _repairs = self._check_existing(intent["records"])
                confirmed.update(existing)
            except NoticeCollectionError:
                pass
        return confirmed, written

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
            if receipt is not None:
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
        state["pending"] = [p for p in state["pending"] if p["request_id"] != intent["request_id"]]
        self._persist(state)
        return handled, newly_written

    def _persist(self, state: dict) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.state_path.with_name("state-" + uuid4().hex + ".tmp")
            temporary.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            temporary.replace(self.state_path)
        except OSError:
            raise _NoticeStateError("通報收取紀錄無法安全儲存，已停止寫入及已讀操作。") from None
        self._state = state

    def _post(self, payload: dict) -> dict:
        try:
            if self._poster is not None:
                response = self._poster(payload)
            else:
                request = urllib.request.Request(
                    APPS_SCRIPT_URL, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
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
            raise NoticeCollectionError("通報收取已停止，未開始新的寫入或已讀操作。")

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
