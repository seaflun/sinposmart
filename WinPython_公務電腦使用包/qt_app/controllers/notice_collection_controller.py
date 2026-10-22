"""Independent notice polling; browser and network work stay off the GUI thread."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable
from uuid import uuid4

from PySide6.QtCore import QObject, Property, QThread, QTimer, Signal, Slot

from app_core.notice_collection_service import (
    FIXED_NOTICE_ACCOUNT,
    TAIPEI,
    NoticeCollectionError,
    NoticeCollectionResult,
    NoticeLoginRequired,
    current_shift,
    next_check_at,
)
from app_core.schedule_repository import business_roc_date


class _NoticeCollectionJob(QThread):
    collected = Signal(object)
    verified = Signal()
    failed = Signal(str, str)

    def __init__(self, service, password: str, received_at: datetime, parent=None, *, verify_only=False):
        super().__init__(parent)
        self._service = service
        self._password = password
        self._received_at = received_at
        self.verify_only = bool(verify_only)
        self.poll_outcome: tuple[str, object] | None = None

    def run(self) -> None:
        try:
            if self.verify_only:
                self._service.verify_login(self._password, cancel=self.isInterruptionRequested)
                self.verified.emit()
            else:
                result = self._service.collect(
                    self._password, self._received_at, cancel=self.isInterruptionRequested,
                )
                self.poll_outcome = ("collected", result)
                self.collected.emit(result)
        except NoticeLoginRequired as exc:
            self._report_failure(self._safe_message(exc), "warning")
        except NoticeCollectionError as exc:
            self._report_failure(self._safe_message(exc), "error")
        except Exception:
            message = ("通報帳號登入驗證失敗，請檢查帳號密碼或網站狀態。" if self.verify_only
                       else "通報收取未完成，請確認網站與連線狀態。")
            self._report_failure(message, "error")
        finally:
            self._password = ""

    def _report_failure(self, message: str, tone: str) -> None:
        self.poll_outcome = ("failed", (message, tone))
        self.failed.emit(message, tone)

    def _safe_message(self, error: Exception) -> str:
        message = str(error)
        if self._password:
            message = message.replace(self._password, "[已隱藏]")
        return message[:300] or "通報收取未完成。"


class NoticeCollectionController(QObject):
    stateChanged = Signal()
    verificationStatusChanged = Signal()
    reportReady = Signal(object)

    def __init__(
        self, service, saved_account_lookup: Callable, busy_reason: Callable,
        schedule_repository=None, parent=None, *, now_factory=None,
        read_only_acceptance=False, timer_start=True,
    ):
        super().__init__(parent)
        self._service = service
        self._lookup = saved_account_lookup
        self._busy_reason = busy_reason
        self._schedule_repository = schedule_repository
        self._now_factory = now_factory or (lambda: datetime.now(TAIPEI))
        self._read_only = bool(read_only_acceptance)
        self._closing = False
        self._closed = False
        self._job = None
        self._schedule_data = {}
        self._status_text = ""
        self._status_tone = "muted"
        self._shift_text = "值班時段待取得"
        self._notice = ""
        self._verification_status = "尚未驗證通報帳號。"
        self._verification_state = "configured"
        self._verification_pending = False
        self._poll_run_id = ""
        self._poll_started_at = None
        self._last_wait_report_at = None
        self._next_check = self._now()
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

    @Property(bool, notify=stateChanged)
    def isRunning(self) -> bool:
        return self._job is not None

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
        if self._notice and self._status_tone in {"warning", "error"}:
            text += f" {self._notice}"
        changed = text != self._status_text or shift_text != self._shift_text
        self._status_text, self._shift_text = text, shift_text
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
        if self._read_only or self._closing or self.isRunning:
            return
        now = self._now()
        verify_only = self._verification_pending
        if not verify_only and now < self._next_check:
            return
        reason = self._busy_reason()
        if reason:
            if verify_only:
                self._set_verification_status(f"等待{reason}完成後驗證通報帳號。", "waiting")
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
                self._set_verification_status(f"尚未儲存通報帳號 {FIXED_NOTICE_ACCOUNT} 的密碼，無法驗證登入。", "error")
                return
            self._set_notice(f"請先儲存通報帳號 {FIXED_NOTICE_ACCOUNT} 的密碼。", "warning")
            self._ensure_poll_run()
            self._emit_report("missing_credentials", error_stage="configuration")
            self._clear_poll_run()
            return
        if verify_only:
            self._verification_pending = False
            self._set_verification_status(f"正在驗證通報帳號 {FIXED_NOTICE_ACCOUNT}…", "verifying")
        self._notice = ""
        self._status_tone = "muted"
        job = _NoticeCollectionJob(self._service, password, now, self, verify_only=verify_only)
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
        self._set_verification_status(f"通報帳號 {FIXED_NOTICE_ACCOUNT} 登入驗證成功。", "verified")

    @Slot(str, str)
    def _verification_failed(self, message: str, tone: str) -> None:
        self._set_verification_status(f"登入驗證失敗，請檢查帳號密碼或網站狀態。 {message}", "error")
        self._notice, self._status_tone = message, tone

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
        if self._job is not None:
            self._job.requestInterruption()

    def shutdown(self) -> bool:
        self.prepare_shutdown_admission()
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
