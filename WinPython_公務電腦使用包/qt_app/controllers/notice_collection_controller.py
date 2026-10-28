"""Independent notice polling; browser and network work stay off the GUI thread."""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable
from uuid import uuid4

from PySide6.QtCore import QObject, Property, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from app_core.notice_collection_service import (
    FIXED_NOTICE_ACCOUNT,
    NOTICE_ERROR_CODES,
    TAIPEI,
    NoticeCollectionError,
    NoticeCollectionResult,
    NoticeLoginRequired,
    current_shift,
    next_check_at,
    notice_responsibility_key,
)
from app_core.login_verifier import OA_LOGIN_FAILURE_MESSAGES
from app_core.schedule_repository import business_roc_date


class _NoticeCollectionJob(QThread):
    collected = Signal(object)
    verified = Signal()
    failed = Signal(str, str)

    def __init__(self, service, password: str, received_at: datetime, parent=None, *, verify_only=False, responsibility=None):
        super().__init__(parent)
        self._service = service
        self._password = password
        self._received_at = received_at
        self.verify_only = bool(verify_only)
        self.failure_code = ""
        self._responsibility = copy.deepcopy(responsibility)
        self.poll_outcome: tuple[str, object] | None = None

    def run(self) -> None:
        try:
            if self.verify_only:
                self._service.verify_login(self._password, cancel=self.isInterruptionRequested)
                self.verified.emit()
            else:
                result = self._service.collect(
                    self._password, self._received_at, cancel=self.isInterruptionRequested,
                    responsibility=self._responsibility,
                )
                self.poll_outcome = ("collected", result)
                self.collected.emit(result)
        except NoticeLoginRequired as exc:
            self._report_failure(self._safe_message(exc), "warning", code=exc.code)
        except NoticeCollectionError as exc:
            self._report_failure(self._safe_message(exc), "error", code=exc.code)
        except Exception:
            message = ("通報帳號登入驗證失敗，請檢查帳號密碼或網站狀態。" if self.verify_only
                       else "通報收取未完成，請確認網站與連線狀態。")
            self._report_failure(message, "error")
        finally:
            self._password = ""

    def _report_failure(self, message: str, tone: str, *, code: str = "") -> None:
        self.failure_code = code if code in NOTICE_ERROR_CODES else ""
        self.poll_outcome = ("failed", (message, tone))
        self.failed.emit(message, tone)

    def _safe_message(self, error: Exception) -> str:
        message = str(error)
        if self._password:
            message = message.replace(self._password, "[已隱藏]")
        return message[:300] or "通報收取未完成。"


class _NoticeSheetLinkJob(QThread):
    resolved = Signal(str)
    failed = Signal()

    def __init__(self, service, now, parent):
        super().__init__(parent)
        self._service, self._now = service, now

    def run(self):
        try:
            self.resolved.emit(self._service.monthly_spreadsheet_url(self._now))
        except Exception:
            self.failed.emit()


class NoticeCollectionController(QObject):
    stateChanged = Signal()
    verificationStatusChanged = Signal()
    reportReady = Signal(object)
    reminderChanged = Signal()

    def __init__(
        self, service, saved_account_lookup: Callable, busy_reason: Callable,
        schedule_repository=None, parent=None, *, now_factory=None,
        read_only_acceptance=False, timer_start=True, responsibility_provider=None,
        reminder_actor_provider=None, reminder_state_path=None,
    ):
        super().__init__(parent)
        self._service = service
        self._lookup = saved_account_lookup
        self._busy_reason = busy_reason
        self._responsibility_provider = responsibility_provider
        self._reminder_actor_provider = reminder_actor_provider
        self._reminder_state_path = Path(reminder_state_path) if reminder_state_path is not None else None
        self._shown_reminders = set()
        self._reminder_journal_error = False
        self._active_reminder = ""
        self._handoff_view = {"visible": False, "rows": []}
        self._last_checked = ""
        self._sheet_job = None
        self._sheet_message = ""
        self._schedule_repository = schedule_repository
        self._now_factory = now_factory or (lambda: datetime.now(TAIPEI))
        self._read_only = bool(read_only_acceptance)
        self._closing = False
        self._closed = False
        self._job = None
        self._schedule_data = {}
        self._status_text = ""
        self._status_tone = "muted"
        self._login_paused = False
        self._login_expired = False
        self._protection_text = ""
        self._shift_text = "值班時段待取得"
        self._reminder_duty_key = ""
        self._has_shift_notices = False
        self._notice = ""
        self._verification_status = "尚未驗證通報帳號。"
        self._verification_state = "configured"
        self._verification_pending = False
        self._verification_run_id = ""
        self._verification_started_at = None
        self._last_verification_wait_at = None
        self._poll_run_id = ""
        self._poll_started_at = None
        self._last_wait_report_at = None
        self._next_check = self._now()
        self._load_reminder_state()
        self._timer = QTimer(self)
        self._timer.setInterval(1_000)
        self._timer.timeout.connect(self.check_due)
        self._load_saved_schedule()
        self._refresh_status()
        if timer_start and not self._read_only:
            self._timer.start()

    @Property(str, notify=stateChanged)
    def statusText(self) -> str:
        return self._status_text

    @Property(str, notify=stateChanged)
    def statusTone(self) -> str:
        return self._status_tone

    @Property(str, notify=stateChanged)
    def loginProtectionText(self) -> str:
        return self._protection_text

    @Property(bool, notify=stateChanged)
    def isRunning(self) -> bool:
        return self._job is not None

    @Property(bool, notify=stateChanged)
    def hasShiftNotices(self) -> bool:
        return self._has_shift_notices

    @Property("QVariantMap", notify=reminderChanged)
    def handoffReminder(self) -> dict:
        return copy.deepcopy(self._handoff_view)

    @Property(bool, notify=reminderChanged)
    def sheetLinkBusy(self) -> bool:
        return self._sheet_job is not None

    @Property(str, notify=reminderChanged)
    def sheetLinkMessage(self) -> str:
        return self._sheet_message

    def _load_reminder_state(self) -> None:
        if self._reminder_state_path is None or not self._reminder_state_path.exists():
            return
        try:
            value = json.loads(self._reminder_state_path.read_text(encoding="utf-8"))
            shown = value["shown"]
            checked = value.get("last_checked", "")
            if (value.get("schema_version") != 1 or not isinstance(shown, list) or len(shown) > 96
                    or any(not isinstance(key, str) or len(key) > 300 for key in shown)
                    or not isinstance(checked, str)):
                raise ValueError("invalid reminder journal")
            if checked:
                at = datetime.fromisoformat(checked)
                checked = (at.replace(tzinfo=TAIPEI) if at.tzinfo is None else at.astimezone(TAIPEI)).isoformat()
            self._shown_reminders, self._last_checked = set(shown), checked
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            self._reminder_journal_error = True

    def _save_reminder_state(self) -> bool:
        if self._reminder_state_path is None:
            return True
        if self._reminder_journal_error:
            return False
        try:
            self._reminder_state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._reminder_state_path.with_name("reminder-" + uuid4().hex + ".tmp")
            temporary.write_text(json.dumps({"schema_version": 1, "shown": sorted(
                self._shown_reminders, key=lambda key: key.split("/", 1)[-1])[-96:],
                "last_checked": self._last_checked}, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self._reminder_state_path)
            return True
        except OSError:
            self._reminder_journal_error = True
            return False

    @Slot()
    def refreshReminder(self) -> None:
        self._refresh_status()

    def _refresh_reminder(self, shift, now) -> None:
        view = {"visible": False, "rows": []}
        eligible = False
        key = ""
        try:
            actor = str(self._reminder_actor_provider() or "").strip() if self._reminder_actor_provider else ""
            actor = actor.lstrip("0") or actor
            eligible = (not self._read_only and not self._closing and shift is not None
                and actor in {number.lstrip("0") or number for number in shift.duty_nos}
                and shift.end - timedelta(minutes=2) <= now < shift.end)
            if eligible:
                key = actor + "/" + shift.key
                rows = self._service.shift_records(shift)
                if isinstance(rows, list) and rows and not self._reminder_journal_error:
                    if key not in self._shown_reminders:
                        self._shown_reminders.add(key)
                        if self._save_reminder_state():
                            self._active_reminder = key
                    if self._active_reminder == key:
                        checked = datetime.fromisoformat(self._last_checked).astimezone(TAIPEI).strftime("%H:%M:%S") if self._last_checked else "尚未檢查"
                        view = {"visible": True, "rows": rows, "count": len(rows),
                            "shiftText": f"{shift.start.year - 1911:03d}/{shift.start:%m/%d}　值班時段 {shift.start:%H:%M}–"
                                         + ("翌日" if shift.end.date() != shift.start.date() else "") + f"{shift.end:%H:%M}",
                            "lastCheckedText": "最後檢查 " + checked,
                            "handoffText": f"{shift.end:%H:%M} 交班",
                            "warning": self._protection_text if self._login_paused else
                                self._notice if self._status_tone in {"warning", "error"} else ""}
        except Exception:
            if eligible and self._active_reminder == key and self._handoff_view.get("visible"):
                view = {**self._handoff_view, "warning": "通報資料暫時無法更新，顯示上次已確認的紀錄。"}
        if not view["visible"]:
            self._active_reminder = ""
        if view != self._handoff_view:
            self._handoff_view = view
            self.reminderChanged.emit()

    @Slot()
    def dismissHandoffReminder(self) -> None:
        self._active_reminder = ""
        self._refresh_status()

    @Slot()
    def openNoticeSheet(self) -> None:
        if self._read_only or self._closing or self._sheet_job is not None:
            return
        self._sheet_message = "正在取得當月通報試算表…"
        job = _NoticeSheetLinkJob(self._service, self._now(), self)
        self._sheet_job = job
        job.resolved.connect(self._open_sheet_url)
        job.failed.connect(self._sheet_failed)
        job.finished.connect(self._sheet_finished)
        self.reminderChanged.emit()
        job.start()

    @Slot(str)
    def _open_sheet_url(self, url: str) -> None:
        if self._closing or (self._reminder_actor_provider and not self._reminder_actor_provider()):
            return
        if (not re.fullmatch(r"https://docs\.google\.com/spreadsheets/d/[A-Za-z0-9_-]{20,128}/edit", url)
                or not QDesktopServices.openUrl(QUrl(url))):
            self._sheet_failed()
            return
        self._sheet_message = ""
        self.reminderChanged.emit()

    @Slot()
    def _sheet_failed(self) -> None:
        self._sheet_message = "通報試算表連結尚未確認，請稍後重試。"
        self.reminderChanged.emit()

    @Slot()
    def _sheet_finished(self) -> None:
        job, self._sheet_job = self._sheet_job, None
        if job is not None:
            job.deleteLater()
        self.reminderChanged.emit()

    @Property(str, notify=stateChanged)
    def activityLabel(self) -> str:
        if self._closing:
            return "停止中" if self.isRunning else "已停止"
        if self._read_only:
            return "已停止"
        if self.isRunning:
            return "登入驗證中" if self._job.verify_only else "執行中"
        if self._login_paused:
            return "已暫停"
        if self._status_tone == "error":
            return "失敗"
        if self._status_tone == "warning":
            return "待確認"
        if self._last_wait_report_at is not None:
            return "等待作業"
        return "等待排程"

    @Property(str, notify=stateChanged)
    def activityTone(self) -> str:
        return ("ready" if self._closing else "running" if self.isRunning else "manual" if self.activityLabel in {"失敗", "待確認", "已暫停"}
                else "triggered" if self._status_tone == "success" and not self._closing else "ready")

    @Property(str, notify=stateChanged)
    def currentShiftText(self) -> str:
        return self._shift_text

    @Property(str, notify=verificationStatusChanged)
    def verificationStatus(self) -> str:
        return self._verification_status

    @Property(str, notify=verificationStatusChanged)
    def verificationState(self) -> str:
        return self._verification_state

    def _now(self) -> datetime:
        value = self._now_factory()
        return value.replace(tzinfo=TAIPEI) if value.tzinfo is None else value.astimezone(TAIPEI)

    def _load_saved_schedule(self) -> None:
        self._last_schedule_day = business_roc_date(self._now())
        if self._schedule_repository is None:
            return
        try:
            snapshot = self._schedule_repository.load_current(self._now())
            if snapshot.found:
                self._schedule_data = dict(snapshot.data)
        except Exception:
            self._notice = "已保存班表無法讀取，值班時段待取得。"

    @Slot(object)
    def set_schedule_data(self, schedule_data: dict) -> None:
        if not isinstance(schedule_data, dict):
            return
        day = business_roc_date(self._now())
        matches_current_day = any(
            isinstance(schedule_data.get(key), dict)
            and str(schedule_data[key].get("roc_date", "")) == day
            for key in ("today", "tomorrow")
        )
        if not any(isinstance(schedule_data.get(key), dict) for key in ("today", "tomorrow")):
            matches_current_day = str(schedule_data.get("target_date", "")) == day
        if matches_current_day:
            self._schedule_data = dict(schedule_data)
        self._refresh_status()

    def _refresh_status(self) -> None:
        now = self._now()
        old_protection = (self._login_paused, self._protection_text)
        try:
            protection = self._service.login_protection(now)
        except Exception:
            protection = {"paused": True, "message": "通報登入保護狀態無法確認，已停止自動登入。"}
        protection = protection if isinstance(protection, dict) else {}
        self._login_paused = protection.get("paused") is True
        self._login_expired = protection.get("expired") is True
        self._protection_text = str(protection.get("message") or "")
        had_notices = self._has_shift_notices
        try:
            responsibility = self._responsibility_provider(now) if self._responsibility_provider else None
        except Exception:
            responsibility = None
        duty_key = notice_responsibility_key(responsibility)
        if duty_key:
            if duty_key != self._reminder_duty_key:
                self._reminder_duty_key = duty_key
                self._has_shift_notices = False
            try:
                if self._service.has_notices_for_responsibility(responsibility) is True:
                    self._has_shift_notices = True
            except NoticeCollectionError:
                pass  # A read failure cannot clear a reminder within the same confirmed duty.
        shift = current_shift(self._schedule_data, now)
        shift_text = shift.label if shift is not None else "值班時段待取得"
        try:
            shift_count, today_count = self._service.counts(now, shift=shift)
            if shift is not None:
                text = f"當班時段已自動收取 {shift_count} 則通報，今日累積 {today_count} 則。"
            else:
                text = f"當班時段待取得，今日累積 {today_count} 則。"
        except NoticeCollectionError:
            text = "當班時段通報收取紀錄暫時無法讀取。"
        if self._reminder_journal_error:
            text += " 交班通報提醒紀錄無法確認，請人工查看通報。"
            if self._status_tone != "error":
                self._status_tone = "warning"
        if self._login_paused and not self.isRunning:
            text += " " + self._protection_text
            self._status_tone = "warning"
        elif self._notice and self._status_tone in {"warning", "error"}:
            text += f" {self._notice}"
        changed = (text != self._status_text or shift_text != self._shift_text
                   or had_notices != self._has_shift_notices
                   or old_protection != (self._login_paused, self._protection_text))
        self._status_text, self._shift_text = text, shift_text
        self._refresh_reminder(shift, now)
        if changed:
            self.stateChanged.emit()

    @Slot()
    def collectNow(self) -> None:
        if self._read_only or self._closing or self.isRunning:
            return
        self._next_check = self._now()
        self.check_due()

    @Slot()
    def verifyLogin(self) -> None:
        if self._read_only or self._closing:
            return
        self._verification_pending = True
        if self.isRunning:
            self._set_verification_status("等待目前作業完成後驗證通報帳號。", "waiting")
            return
        self.check_due()

    @Slot()
    def check_due(self) -> None:
        if business_roc_date(self._now()) != self._last_schedule_day:
            self._load_saved_schedule()
        self._refresh_status()
        if self._login_expired and self.isRunning and not self._job.verify_only:
            self._job.requestInterruption()
        if self._read_only or self._closing or self.isRunning:
            return
        now = self._now()
        verify_only = self._verification_pending
        if verify_only and not self._verification_run_id:
            self._verification_run_id = str(uuid4())
        if self._login_expired and not verify_only:
            try:
                self._service.pause_expired_login(now)
            except NoticeCollectionError:
                self._refresh_status()
        if self._login_paused and not verify_only:
            return
        if not verify_only and now < self._next_check:
            return
        reason = self._busy_reason()
        if reason:
            if verify_only:
                self._set_verification_status(f"等待{reason}完成後驗證通報帳號。", "waiting")
                if (self._last_verification_wait_at is None
                        or now - self._last_verification_wait_at >= timedelta(seconds=60)):
                    self._emit_verification_report("waiting")
                    self._last_verification_wait_at = now
                return
            self._set_notice(f"等待{reason}完成後檢查通報。", "muted")
            if self._last_wait_report_at is None or now - self._last_wait_report_at >= timedelta(seconds=60):
                self._ensure_poll_run()
                self._emit_report("waiting", error_stage="busy", next_check=now + timedelta(seconds=60))
                self._last_wait_report_at = now
            return
        try:
            account = self._lookup(FIXED_NOTICE_ACCOUNT)
            correct_account = (
                isinstance(account, dict)
                and str(account.get("user_id", "")).strip() == FIXED_NOTICE_ACCOUNT
            )
            password = str(account.get("password", "") or "") if correct_account else ""
        except Exception:
            password = ""
        if not password:
            self._next_check = next_check_at(now)
            if verify_only:
                self._verification_pending = False
                self._clear_verification_report()
                self._set_verification_status(f"尚未儲存通報帳號 {FIXED_NOTICE_ACCOUNT} 的密碼，無法驗證登入。", "error")
                return
            self._set_notice(f"請先儲存通報帳號 {FIXED_NOTICE_ACCOUNT} 的密碼。", "warning")
            self._ensure_poll_run()
            self._emit_report("missing_credentials", error_stage="configuration")
            self._clear_poll_run()
            return
        if verify_only:
            self._verification_pending = False
            self._verification_started_at = now
            self._set_verification_status(f"正在驗證通報帳號 {FIXED_NOTICE_ACCOUNT}…", "verifying")
        self._notice = ""
        self._status_tone = "muted"
        try:
            responsibility = self._responsibility_provider(now) if self._responsibility_provider else None
        except Exception:
            responsibility = None
        job = _NoticeCollectionJob(self._service, password, now, self, verify_only=verify_only,
                                   responsibility=responsibility)
        job.collected.connect(self._collected)
        job.verified.connect(self._verified)
        job.failed.connect(self._verification_failed if verify_only else self._failed)
        job.finished.connect(self._job_finished)
        self._job = job
        if not verify_only:
            self._ensure_poll_run()
            self._poll_started_at = now
            self._emit_report("running")
        self._refresh_status()
        self.stateChanged.emit()
        job.start()

    @Slot(object)
    def _collected(self, result) -> None:
        if not self._poll_run_id:
            return
        self._notice = str(result.message or "")
        self._last_checked = result.checked_at.replace(tzinfo=TAIPEI).isoformat() if result.checked_at.tzinfo is None else result.checked_at.astimezone(TAIPEI).isoformat()
        self._save_reminder_state()
        self._status_tone = (
            "success" if result.status == "success" and not result.error_count else "warning"
        )
        state = result.status if result.status in {"success", "partial", "uncertain"} else "failed"
        self._emit_report(state, result=result)
        self._clear_poll_run()

    @Slot(str, str)
    def _failed(self, message: str, tone: str) -> None:
        if not self._poll_run_id:
            return
        self._notice, self._status_tone = message, tone
        self._last_checked = self._now().isoformat()
        self._save_reminder_state()
        result = getattr(self._service, "last_result", None)
        if not isinstance(result, NoticeCollectionResult) or result.checked_at != self._poll_started_at:
            result = None
        state = result.status if result is not None and result.status in {"partial", "uncertain"} else "failed"
        self._emit_report(state, result=result,
                          error_stage=(result.error_stage if result is not None else "login" if tone == "warning" else "unknown"))
        self._clear_poll_run()

    def _ensure_poll_run(self) -> None:
        if not self._poll_run_id:
            self._poll_run_id = str(uuid4())

    def _clear_poll_run(self) -> None:
        self._poll_run_id = ""
        self._poll_started_at = None
        self._last_wait_report_at = None

    def _emit_report(self, state: str, *, result=None, error_stage="", next_check=None) -> None:
        if self._read_only or not self._poll_run_id:
            return
        now = self._now()
        try:
            parts = self._service.report_parts(self._poll_run_id, state, now,
                started_at=self._poll_started_at, next_check=next_check or next_check_at(now),
                shift=current_shift(self._schedule_data, now), result=result, error_stage=error_stage)
        except Exception:
            return  # Reporting cannot repeat or interrupt an official collection action.
        if isinstance(parts, list):
            for report in parts:
                self.reportReady.emit(report)

    @Slot()
    def _verified(self) -> None:
        self._clear_verification_report()
        self._notice, self._status_tone = "", "success"
        self._refresh_status()
        self._set_verification_status(f"通報帳號 {FIXED_NOTICE_ACCOUNT} 登入驗證成功。" + self._protection_text, "verified")

    @Slot(str, str)
    def _verification_failed(self, message: str, tone: str) -> None:
        code = getattr(self._job, "failure_code", "")
        code = code if isinstance(code, str) and code in NOTICE_ERROR_CODES else ""
        safe_message = OA_LOGIN_FAILURE_MESSAGES.get(code, "驗證未完成，原因待確認。")
        self._set_verification_status(safe_message, "error")
        self._notice, self._status_tone = safe_message, tone
        if self._verification_started_at is not None:
            self._emit_verification_report("failed", code=code)
        self._clear_verification_report()

    def _clear_verification_report(self) -> None:
        self._verification_run_id = ""
        self._verification_started_at = None
        self._last_verification_wait_at = None

    def _emit_verification_report(self, state: str, *, code: str = "") -> None:
        if self._read_only or self._closing or not self._verification_run_id:
            return
        now = self._now()
        waiting = state == "waiting"
        self.reportReady.emit({
            "schema_version": 1, "verification_only": True, "run_id": self._verification_run_id,
            "part_index": 0, "part_count": 1, "state": state,
            "started_at": self._verification_started_at.isoformat() if self._verification_started_at else "",
            "completed_at": "" if waiting else now.isoformat(), "reported_at": now.isoformat(),
            "next_check_at": (now + timedelta(seconds=60) if waiting else now).isoformat(),
            "calendar_day": now.date().isoformat(), "shift_start": "", "shift_end": "",
            "unread_count": None, "new_count": None, "marked_read_count": None,
            "pending_write_count": None, "pending_read_count": None, "records": [], "new_keys": [],
            "error_stage": "busy" if waiting else "login", "error_code": code,
            "message": ("通報登入驗證尚未開始，等待公務作業完成。" if waiting else
                        OA_LOGIN_FAILURE_MESSAGES.get(code, "驗證未完成，原因待確認。")),
        })

    def _set_verification_status(self, message: str, state: str = "configured") -> None:
        if self._verification_status != message or self._verification_state != state:
            self._verification_status = message
            self._verification_state = state
            self.verificationStatusChanged.emit()

    @Slot()
    def _job_finished(self) -> None:
        job, self._job = self._job, None
        if job is not None:
            self._next_check = next_check_at(self._now())
            job.deleteLater()
        self._refresh_status()
        self.stateChanged.emit()
        if self._verification_pending and not self._closing:
            self.check_due()

    def _set_notice(self, message: str, tone: str) -> None:
        changed = self._notice != message or self._status_tone != tone
        self._notice, self._status_tone = message, tone
        self._refresh_status()
        if changed:
            self.stateChanged.emit()

    def prepare_shutdown_admission(self) -> None:
        self._closing = True
        self._verification_pending = False
        self._timer.stop()
        self._refresh_status()
        if self._job is not None:
            self._job.requestInterruption()
        self.stateChanged.emit()

    def shutdown(self) -> bool:
        self.prepare_shutdown_admission()
        if self._sheet_job is not None:
            self._sheet_job.wait()
            self._sheet_finished()
        if self._job is not None:
            if not self._job.wait(15_000):
                self._job.wait()
            if self._poll_run_id and not self._job.verify_only and self._job.poll_outcome is not None:
                kind, outcome = self._job.poll_outcome
                if kind == "collected":
                    self._collected(outcome)
                else:
                    self._failed(*outcome)
            self._job_finished()
        if not self._closed:
            self._service.close()
            self._closed = True
        return True
