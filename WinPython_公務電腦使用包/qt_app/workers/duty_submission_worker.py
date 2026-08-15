# -*- coding: utf-8 -*-
"""Qt worker for one duty-system submission request."""

from __future__ import annotations

from datetime import datetime, timedelta
from itertools import count
from queue import PriorityQueue
from threading import Event, Lock
from typing import Callable
from PySide6.QtCore import QObject, QThread, Signal, Slot

from app_core.duty_submission_service import (
    DutySubmissionExecutionError,
    DutySubmissionBrowserSession,
    DutySubmissionRequest,
    DutySubmissionResult,
    DutySubmissionService,
)


ENTRY_BROWSER_SESSION_IDLE_LIMIT = timedelta(minutes=25)


class DutySubmissionWorker(QObject):
    progress = Signal(int, str)
    succeeded = Signal(int, object)
    failed = Signal(int, int, str, str, str)
    finished = Signal(int)

    def __init__(
        self,
        request_id: int,
        service: DutySubmissionService,
        request: DutySubmissionRequest,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.service = service
        self.request = request

    @Slot()
    def run(self) -> None:
        action_index = self.request.action_index
        try:
            result = self._execute_with_browser_start_retry()
        except DutySubmissionExecutionError as exc:
            self.failed.emit(
                self.request_id,
                action_index,
                str(exc),
                exc.error_code,
                str(exc.result_path or ""),
            )
        except Exception:
            self.failed.emit(
                self.request_id,
                action_index,
                "勤務系統登打失敗。",
                "unknown_error",
                "",
            )
        else:
            self.succeeded.emit(self.request_id, result)
        finally:
            self.request = DutySubmissionRequest("", "", 0, {"target_date": "", "actions": []})
            self.finished.emit(self.request_id)

    def _execute_with_browser_start_retry(self) -> DutySubmissionResult:
        for attempt in range(2):
            try:
                return self.service.execute(
                    self.request,
                    status_callback=lambda message: self.progress.emit(self.request_id, message),
                )
            except DutySubmissionExecutionError as exc:
                if exc.error_code != "browser_startup" or attempt:
                    raise
                self.progress.emit(self.request_id, "工作瀏覽器啟動失敗，正在重新登入後重試一次。")
        raise DutySubmissionExecutionError("工作瀏覽器重試流程未能完成。", "browser_startup")


class DutyEntryQueueWorker(QObject):
    """One persistent browser worker for all entry-log requests in a session."""

    progress = Signal(int, str)
    requestStarted = Signal(int, int)
    succeeded = Signal(int, object)
    failed = Signal(int, int, str, str, str)
    requestFinished = Signal(int)
    requestCancelled = Signal(int, int, str, str)
    stopped = Signal()

    _STOP_PRIORITY = -1
    _MANUAL_PRIORITY = 0
    _NORMAL_PRIORITY = 1

    def __init__(
        self,
        service: DutySubmissionService,
        *,
        now_factory: Callable[[], datetime] = datetime.now,
    ) -> None:
        super().__init__()
        self._service = service
        self._now_factory = now_factory
        self._queue: PriorityQueue[tuple[int, int, int, DutySubmissionRequest | None]] = PriorityQueue()
        self._sequence = count()
        self._sequence_lock = Lock()
        self._stop_requested = Event()
        self._browser_session: DutySubmissionBrowserSession | None = None

    def enqueue(self, request_id: int, request: DutySubmissionRequest) -> bool:
        """Thread-safe; the controller may call it while this worker is running."""

        if self._stop_requested.is_set():
            return False
        priority = self._MANUAL_PRIORITY if request.trigger_type == "manual" else self._NORMAL_PRIORITY
        with self._sequence_lock:
            sequence = next(self._sequence)
        self._queue.put((priority, sequence, request_id, request))
        return True

    def stop(self) -> None:
        """Finish the active action, then cancel all queued entry actions."""

        if self._stop_requested.is_set():
            return
        self._stop_requested.set()
        with self._sequence_lock:
            sequence = next(self._sequence)
        self._queue.put((self._STOP_PRIORITY, sequence, -1, None))

    @Slot()
    def run(self) -> None:
        try:
            while True:
                _priority, _sequence, request_id, request = self._queue.get()
                if request is None:
                    break
                if self._stop_requested.is_set():
                    self.requestCancelled.emit(
                        request_id,
                        request.action_index,
                        "出入登打因登入階段結束而取消。",
                        "session_ended",
                    )
                    self.requestFinished.emit(request_id)
                    continue
                self.requestStarted.emit(request_id, request.action_index)
                try:
                    result = self._execute(request_id, request)
                except DutySubmissionExecutionError as exc:
                    self.failed.emit(
                        request_id,
                        request.action_index,
                        str(exc),
                        exc.error_code,
                        str(exc.result_path or ""),
                    )
                except Exception:
                    self.failed.emit(
                        request_id,
                        request.action_index,
                        "勤務系統登打發生未預期錯誤。",
                        "unknown_error",
                        "",
                    )
                else:
                    self.succeeded.emit(request_id, result)
                finally:
                    request = DutySubmissionRequest("", "", 0, {"target_date": "", "actions": []})
                    self.requestFinished.emit(request_id)
        finally:
            self._cancel_remaining()
            self._close_browser_session()
            self.stopped.emit()
            QThread.currentThread().quit()

    def _execute(self, request_id: int, request: DutySubmissionRequest) -> DutySubmissionResult:
        if not self._supports_browser_sessions():
            return self._service.execute(
                request,
                status_callback=lambda message: self.progress.emit(request_id, message),
            )
        stale_checker = getattr(self._service, "is_stale_due_request", None)
        if callable(stale_checker) and stale_checker(request):
            return self._service.execute(
                request,
                status_callback=lambda message: self.progress.emit(request_id, message),
            )
        had_compatible_session = self._has_compatible_session(request)
        try:
            if not had_compatible_session:
                self._close_browser_session()
                self._browser_session = self._service.open_browser_session(
                    request,
                    status_callback=lambda message: self.progress.emit(request_id, message),
                )
            result = self._service.execute_with_browser_session(
                request,
                self._browser_session,
                status_callback=lambda message: self.progress.emit(request_id, message),
            )
            self._mark_browser_session_active()
            return result
        except DutySubmissionExecutionError as exc:
            session_expired = exc.error_code == "login_failed" and had_compatible_session
            if exc.error_code != "browser_startup" and not session_expired:
                self._close_browser_session()
                raise
            self._close_browser_session()
            retry_message = (
                "出入登入狀態已失效，正在重新登入後重試一次。"
                if session_expired
                else "出入瀏覽器啟動失敗，正在重新登入後重試一次。"
            )
            self.progress.emit(request_id, retry_message)
            self._browser_session = self._service.open_browser_session(
                request,
                status_callback=lambda message: self.progress.emit(request_id, message),
            )
            result = self._service.execute_with_browser_session(
                request,
                self._browser_session,
                status_callback=lambda message: self.progress.emit(request_id, message),
            )
            self._mark_browser_session_active()
            return result

    def _has_compatible_session(self, request: DutySubmissionRequest) -> bool:
        session = self._browser_session
        if not (
            session is not None
            and session.user_id == request.user_id
            and session.visible == request.visible
        ):
            return False
        last_activity_at = getattr(session, "last_activity_at", None)
        if not isinstance(last_activity_at, datetime):
            return True
        return self._now_factory() - last_activity_at < ENTRY_BROWSER_SESSION_IDLE_LIMIT

    def _mark_browser_session_active(self) -> None:
        if self._browser_session is not None:
            self._browser_session.last_activity_at = self._now_factory()

    def _supports_browser_sessions(self) -> bool:
        return all(
            callable(getattr(self._service, name, None))
            for name in (
                "open_browser_session",
                "execute_with_browser_session",
                "close_browser_session",
            )
        )

    def _close_browser_session(self) -> None:
        if self._browser_session is None:
            return
        self._service.close_browser_session(self._browser_session)
        self._browser_session = None

    def _cancel_remaining(self) -> None:
        while not self._queue.empty():
            _priority, _sequence, request_id, request = self._queue.get_nowait()
            if request is None:
                continue
            self.requestCancelled.emit(
                request_id,
                request.action_index,
                "出入登打因登入階段結束而取消。",
                "session_ended",
            )
            self.requestFinished.emit(request_id)
