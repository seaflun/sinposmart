# -*- coding: utf-8 -*-
"""Qt dispatcher with one queued entry browser and one separate work browser."""

from __future__ import annotations

from PySide6.QtCore import QObject, Property, QThread, QTimer, Signal, Slot

from app_core.duty_task_projection import action_completion_key
from app_core.duty_submission_service import (
    DutySubmissionRequest,
    DutySubmissionResult,
    DutySubmissionService,
    DutySubmissionValidationError,
)
from qt_app.workers.duty_submission_worker import (
    DutyEntryQueueWorker,
)


RequestKey = tuple[int, str, str, str]


class _EntryWorkerThread(QThread):
    """Report the exact finished lane thread without relying on QObject.sender()."""

    stoppedWithThread = Signal(object)

    def run(self) -> None:
        try:
            super().run()
        finally:
            self.stoppedWithThread.emit(self)


class DutyExecutionController(QObject):
    """Keep entry and work submissions in separate persistent browser lanes."""

    ENTRY_LANES = ("entry",)
    WORK_LANE = "work"

    stateChanged = Signal()
    actionStarted = Signal(int)
    actionFinished = Signal(int, str, str, str)
    actionFailed = Signal(int, str, str)
    submissionQueued = Signal(object)
    submissionStarted = Signal(object)
    submissionFinished = Signal(object, object)
    submissionFailed = Signal(object, str, str, str)
    submissionCancelled = Signal(object, str, str)
    allLanesUnavailable = Signal(str)

    def __init__(
        self,
        service: DutySubmissionService,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._request_lanes: dict[int, str] = {}
        self._requests: dict[int, DutySubmissionRequest] = {}
        self._request_keys: dict[int, RequestKey] = {}
        self._pending_keys: set[RequestKey] = set()
        self._entry_thread: QThread | None = None
        self._entry_worker: DutyEntryQueueWorker | None = None
        self._entry_active_request_id: int | None = None
        self._entry_queued_request_ids: set[int] = set()
        self._entry_stopping = False
        self._work_thread: QThread | None = None
        self._work_worker: DutyEntryQueueWorker | None = None
        self._work_active_request_id: int | None = None
        self._work_queued_request_ids: set[int] = set()
        self._work_stopping = False
        self._disabled_lanes: set[str] = set()
        self._request_id = 0
        self._session_generation = 0
        self._session_closing = False
        self._status_text = "勤務登打待命中"
        self._idle_cleanup_timer = QTimer(self)
        self._idle_cleanup_timer.setInterval(60_000)
        self._idle_cleanup_timer.timeout.connect(self._request_idle_browser_cleanup)
        self._idle_cleanup_timer.start()

    @Property(str, notify=stateChanged)
    def statusText(self) -> str:
        return self._status_text

    @Property(int, notify=stateChanged)
    def queuedCount(self) -> int:
        return sum(
            self._is_foreground_request_id(request_id)
            for request_id in self._entry_queued_request_ids | self._work_queued_request_ids
        )

    @Property(int, notify=stateChanged)
    def activeCount(self) -> int:
        return sum(
            self._is_foreground_request_id(request_id)
            for request_id in (self._entry_active_request_id, self._work_active_request_id)
            if request_id is not None
        )

    @Property(bool, notify=stateChanged)
    def isBusy(self) -> bool:
        return self.activeCount > 0 or self.queuedCount > 0

    def enqueue(self, request: DutySubmissionRequest) -> bool:
        """Queue a submission owned by the currently authenticated GUI session."""

        if request.background:
            return False
        return self._enqueue(request, allow_background=False)

    def enqueue_background(self, request: DutySubmissionRequest) -> bool:
        """Queue an app-owned waiting task using its captured login identity."""

        if not request.background:
            return False
        return self._enqueue(request, allow_background=True)

    def _enqueue(self, request: DutySubmissionRequest, *, allow_background: bool) -> bool:
        if not allow_background and (
            self._session_closing or not self._request_matches_current_session(request)
        ):
            return False
        try:
            request = self._service.validate(request)
        except DutySubmissionValidationError as exc:
            if allow_background:
                self.submissionFailed.emit(request, str(exc), "validation_error", "")
            else:
                self._report_validation_failure(request, str(exc))
            return False
        if not allow_background and (
            self._session_closing or not self._request_matches_current_session(request)
        ):
            return False
        key = self._request_key(request)
        if key in self._pending_keys:
            return False

        self._request_id += 1
        request_id = self._request_id
        queue_name = self._queue_name(request)
        self._requests[request_id] = request
        self._request_lanes[request_id] = queue_name
        self._request_keys[request_id] = key
        self._pending_keys.add(key)

        if queue_name == "entry":
            worker = self._ensure_entry_worker()
            self._entry_queued_request_ids.add(request_id)
        else:
            worker = self._ensure_work_worker()
            self._work_queued_request_ids.add(request_id)
        if worker is None or not worker.enqueue(request_id, request):
            if queue_name == "entry":
                self._entry_queued_request_ids.discard(request_id)
            else:
                self._work_queued_request_ids.discard(request_id)
            self._forget_request(request_id)
            message = f"{self._lane_label(queue_name)}登打瀏覽器正在結束，請重新登入後再試。"
            if allow_background:
                self.submissionFailed.emit(request, message, "session_ended", "")
            else:
                self._status_text = message
                self.stateChanged.emit()
                self.actionFailed.emit(request.action_index, message, "session_ended")
                self.submissionFailed.emit(request, message, "session_ended", "")
            return False

        self.submissionQueued.emit(request)
        if not request.background:
            self._status_text = f"準備登打，佇列尚有 {self.queuedCount} 項。"
            self.stateChanged.emit()
        return True

    def prewarm_entry_browser(self, request: DutySubmissionRequest) -> bool:
        """Prepare the persistent entry browser without adding a duty action."""

        return self._prewarm_browser(request, lane="entry", allow_background=False)

    def prewarm_work_browser(self, request: DutySubmissionRequest) -> bool:
        """Prepare the persistent work browser without adding a duty action."""

        return self._prewarm_browser(request, lane="work", allow_background=False)

    def prewarm_background_browser(self, request: DutySubmissionRequest) -> bool:
        """Warm a waiting entry task without replacing a newer user's entry session."""

        if not request.background:
            return False
        return self._prewarm_browser(
            request,
            lane="entry",
            allow_background=True,
            preserve_incompatible_session=True,
        )

    def _prewarm_browser(
        self,
        request: DutySubmissionRequest,
        *,
        lane: str,
        allow_background: bool,
        preserve_incompatible_session: bool = False,
    ) -> bool:
        if not allow_background and (
            self._session_closing or not self._request_matches_current_session(request)
        ):
            return False
        try:
            request = self._service.validate(request)
        except DutySubmissionValidationError:
            return False
        if self._queue_name(request) != lane:
            return False
        worker = self._ensure_entry_worker() if lane == "entry" else self._ensure_work_worker()
        return bool(
            worker
            and worker.prewarm_browser_session(
                request,
                preserve_incompatible_session=preserve_incompatible_session,
            )
        )

    @staticmethod
    def _lane_label(lane: str) -> str:
        return "工作" if lane == "work" else "出入"

    @staticmethod
    def _queue_name(request: DutySubmissionRequest) -> str:
        actions = request.schedule_data.get("actions", [])
        action = actions[request.action_index]
        return (
            "work"
            if action.get("kind") == "work_log"
            else "entry"
        )

    @staticmethod
    def _request_key(request: DutySubmissionRequest) -> RequestKey:
        actions = request.schedule_data.get("actions", [])
        action = actions[request.action_index]
        action_key = str(request.action_key or "").strip()
        if not action_key:
            action_key = f"{action_completion_key(action)}@index:{request.action_index}"
        return (
            request.session_generation,
            str(request.schedule_data.get("target_date", "") or ""),
            action_key,
            str(
                request.schedule_data.get("_unreturned_return_component_key", "")
                or request.schedule_data.get("_unreturned_return_queue_id", "")
                or request.schedule_data.get("_handoff_preflight_group_id", "")
                or ""
            ),
        )

    def _ensure_entry_worker(self) -> DutyEntryQueueWorker | None:
        if self._entry_worker is not None:
            return None if self._entry_stopping else self._entry_worker

        worker = DutyEntryQueueWorker(self._service, lane_label="出入")
        thread = _EntryWorkerThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._progress)
        worker.requestStarted.connect(self._entry_request_started)
        worker.succeeded.connect(self._succeeded)
        worker.failed.connect(self._failed)
        worker.requestCancelled.connect(self._entry_request_cancelled)
        worker.requestFinished.connect(self._entry_request_finished)
        worker.stopped.connect(worker.deleteLater)
        thread.stoppedWithThread.connect(self._entry_thread_finished)
        self._entry_worker = worker
        self._entry_thread = thread
        self._entry_stopping = False
        thread.start()
        return worker

    def _ensure_work_worker(self) -> DutyEntryQueueWorker | None:
        if self._work_worker is not None:
            return None if self._work_stopping else self._work_worker

        worker = DutyEntryQueueWorker(self._service, lane_label="工作")
        thread = _EntryWorkerThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._progress)
        worker.requestStarted.connect(self._work_request_started)
        worker.succeeded.connect(self._succeeded)
        worker.failed.connect(self._failed)
        worker.requestCancelled.connect(self._work_request_cancelled)
        worker.requestFinished.connect(self._work_request_finished)
        worker.stopped.connect(worker.deleteLater)
        thread.stoppedWithThread.connect(self._work_thread_finished)
        self._work_worker = worker
        self._work_thread = thread
        self._work_stopping = False
        thread.start()
        return worker

    @Slot(int, int)
    def _entry_request_started(self, request_id: int, action_index: int) -> None:
        self._lane_request_started("entry", request_id, action_index)

    @Slot(int, int)
    def _work_request_started(self, request_id: int, action_index: int) -> None:
        self._lane_request_started("work", request_id, action_index)

    def _lane_request_started(self, lane: str, request_id: int, action_index: int) -> None:
        request = self._requests.get(request_id)
        if request is None:
            return
        queued_ids = (
            self._entry_queued_request_ids
            if lane == "entry"
            else self._work_queued_request_ids
        )
        queued_ids.discard(request_id)
        if lane == "entry":
            self._entry_active_request_id = request_id
        else:
            self._work_active_request_id = request_id
        if not self._request_matches_current_session(request):
            self.stateChanged.emit()
        else:
            self._status_text = f"{self._lane_label(lane)}登打通道執行中。"
            self.stateChanged.emit()
            self.actionStarted.emit(action_index)
        self.submissionStarted.emit(request)

    @Slot(int, str)
    def _progress(self, request_id: int, message: str) -> None:
        request = self._requests.get(request_id)
        if request is not None and self._request_matches_current_session(request):
            self._status_text = message
            self.stateChanged.emit()

    @Slot(int, object)
    def _succeeded(self, request_id: int, result: DutySubmissionResult) -> None:
        request = self._requests.get(request_id)
        if request is None:
            return
        if not self._request_matches_current_session(request):
            self.submissionFinished.emit(request, result)
            return
        self._status_text = result.message
        self.stateChanged.emit()
        self.actionFinished.emit(
            result.action_index,
            result.status,
            result.message,
            str(result.result_path),
        )
        self.submissionFinished.emit(request, result)

    @Slot(int, int, str, str, str)
    def _failed(
        self,
        request_id: int,
        action_index: int,
        message: str,
        error_code: str,
        result_path: str,
    ) -> None:
        request = self._requests.get(request_id)
        if request is None:
            return
        if not self._request_matches_current_session(request):
            self.submissionFailed.emit(request, message, error_code, result_path)
            return
        self._status_text = message
        self.stateChanged.emit()
        self.actionFailed.emit(action_index, message, error_code)
        self.submissionFailed.emit(request, message, error_code, result_path)

    @Slot(int, int, str, str)
    def _entry_request_cancelled(
        self,
        request_id: int,
        action_index: int,
        message: str,
        error_code: str,
    ) -> None:
        self._lane_request_cancelled(request_id, action_index, message, error_code)

    @Slot(int, int, str, str)
    def _work_request_cancelled(
        self,
        request_id: int,
        action_index: int,
        message: str,
        error_code: str,
    ) -> None:
        self._lane_request_cancelled(request_id, action_index, message, error_code)

    def _lane_request_cancelled(
        self,
        request_id: int,
        action_index: int,
        message: str,
        error_code: str,
    ) -> None:
        request = self._requests.get(request_id)
        if error_code == "session_ended":
            if request is not None:
                self.submissionCancelled.emit(request, message, error_code)
            return
        self._failed(request_id, action_index, message, error_code, "")

    @Slot(int)
    def _entry_request_finished(self, request_id: int) -> None:
        self._lane_request_finished("entry", request_id)

    @Slot(int)
    def _work_request_finished(self, request_id: int) -> None:
        self._lane_request_finished("work", request_id)

    def _lane_request_finished(self, lane: str, request_id: int) -> None:
        was_foreground = self._is_foreground_request_id(request_id)
        queued_ids = (
            self._entry_queued_request_ids
            if lane == "entry"
            else self._work_queued_request_ids
        )
        queued_ids.discard(request_id)
        if lane == "entry" and self._entry_active_request_id == request_id:
            self._entry_active_request_id = None
        if lane == "work" and self._work_active_request_id == request_id:
            self._work_active_request_id = None
        self._forget_request(request_id)
        if was_foreground and not self.isBusy:
            self._status_text = (
                "勤務登打已停止，等待登出。"
                if self._session_closing
                else "勤務登打待命中"
            )
        self.stateChanged.emit()

    @Slot(object)
    def _entry_thread_finished(self, finished_thread: QThread) -> None:
        self._lane_thread_finished("entry", finished_thread)

    @Slot(object)
    def _work_thread_finished(self, finished_thread: QThread) -> None:
        self._lane_thread_finished("work", finished_thread)

    def _lane_thread_finished(self, lane: str, finished_thread: QThread) -> None:
        expected_thread = self._entry_thread if lane == "entry" else self._work_thread
        if finished_thread is not expected_thread:
            return
        thread = finished_thread
        if not thread.wait(5_000):
            self._poll_lane_thread_finished(lane, thread)
            return
        self._finalize_lane_thread(lane, thread)

    def _poll_lane_thread_finished(self, lane: str, thread: QThread) -> None:
        expected_thread = self._entry_thread if lane == "entry" else self._work_thread
        if thread is not expected_thread:
            return
        if not thread.isFinished():
            QTimer.singleShot(
                50,
                lambda: self._poll_lane_thread_finished(lane, thread),
            )
            return
        self._finalize_lane_thread(lane, thread)

    def _finalize_lane_thread(self, lane: str, finished_thread: QThread) -> None:
        expected_thread = self._entry_thread if lane == "entry" else self._work_thread
        if finished_thread is not expected_thread:
            return
        request_ids = {
            request_id
            for request_id, request_lane in self._request_lanes.items()
            if request_lane == lane
        }
        for request_id in request_ids:
            self._forget_request(request_id)
        if lane == "entry":
            self._entry_thread = None
            self._entry_worker = None
            self._entry_stopping = False
            self._entry_queued_request_ids.clear()
            self._entry_active_request_id = None
        else:
            self._work_thread = None
            self._work_worker = None
            self._work_stopping = False
            self._work_queued_request_ids.clear()
            self._work_active_request_id = None
        finished_thread.deleteLater()
        if not self.isBusy:
            self._status_text = (
                "勤務登打已停止，等待登出。"
                if self._session_closing
                else "勤務登打待命中"
            )
        self.stateChanged.emit()

    def _forget_request(self, request_id: int) -> None:
        key = self._request_keys.pop(request_id, None)
        if key is not None:
            self._pending_keys.discard(key)
        self._request_lanes.pop(request_id, None)
        self._requests.pop(request_id, None)

    def _request_matches_current_session(self, request: DutySubmissionRequest) -> bool:
        return request.session_generation == self._session_generation

    def _is_foreground_request_id(self, request_id: int | None) -> bool:
        if request_id is None:
            return False
        request = self._requests.get(request_id)
        return request is None or not request.background

    def _has_background_entry_request(self) -> bool:
        request_ids = set(self._entry_queued_request_ids)
        if self._entry_active_request_id is not None:
            request_ids.add(self._entry_active_request_id)
        return any(
            bool((request := self._requests.get(request_id)) and request.background)
            for request_id in request_ids
        )

    def _cancel_queued_foreground_entry_requests(self) -> None:
        worker = self._entry_worker
        if worker is None:
            return
        request_ids = {
            request_id
            for request_id in self._entry_queued_request_ids
            if (request := self._requests.get(request_id)) is not None and not request.background
        }
        worker.cancel_queued_requests(request_ids)

    def _report_validation_failure(self, request: DutySubmissionRequest, message: str) -> None:
        self._status_text = message
        self.stateChanged.emit()
        self.actionFailed.emit(request.action_index, message, "validation_error")
        self.submissionFailed.emit(request, message, "validation_error", "")

    @Slot()
    def close_entry_session(self, *, force: bool = False) -> None:
        """Close the entry browser unless an app-owned background action is active."""

        if self._entry_worker is None or self._entry_stopping:
            return
        if not force and self._has_background_entry_request():
            return
        self._entry_stopping = True
        self._entry_worker.stop()

    def close_work_session(self) -> None:
        """Close the persistent work browser at logout or when the app exits."""

        if self._work_worker is None or self._work_stopping:
            return
        self._work_stopping = True
        self._work_worker.stop()

    @Slot()
    def _request_idle_browser_cleanup(self) -> None:
        for worker in (self._entry_worker, self._work_worker):
            if worker is not None:
                worker.request_idle_cleanup()

    def prepare_session_end(self) -> bool:
        """Stop admitting work and cancel requests that have not started yet."""

        self._session_closing = True
        self._cancel_queued_foreground_entry_requests()
        self.close_entry_session()
        self.close_work_session()
        self._status_text = (
            "正在等待勤務登打完成…"
            if self.isBusy
            else "勤務登打已停止，等待登出。"
        )
        self.stateChanged.emit()
        return not self.isBusy

    def set_session_generation(self, generation: int) -> None:
        """Move to a new authenticated identity and quarantine older results."""

        generation = max(0, int(generation))
        if generation == self._session_generation:
            return
        self._session_generation = generation
        self._session_closing = False
        self._cancel_queued_foreground_entry_requests()
        self.close_entry_session()
        self.close_work_session()
        self._disabled_lanes.clear()
        if not self.isBusy:
            self._status_text = "勤務登打待命中"
        self.stateChanged.emit()

    def reset_parallel_lanes(self) -> None:
        """Compatibility hook kept for login transitions in the application shell."""

        self._disabled_lanes.clear()
        if not self.isBusy:
            self._status_text = "勤務登打待命中"
        self.stateChanged.emit()

    @Slot()
    def shutdown(self) -> None:
        self._session_closing = True
        self._idle_cleanup_timer.stop()
        self.close_entry_session(force=True)
        self.close_work_session()
        entry_thread = self._entry_thread
        if entry_thread is not None:
            if not entry_thread.wait(120_000):
                entry_thread.wait()
            self._entry_thread_finished(entry_thread)

        work_thread = self._work_thread
        if work_thread is not None:
            if not work_thread.wait(120_000):
                work_thread.wait()
            self._work_thread_finished(work_thread)
        self._entry_queued_request_ids.clear()
        self._work_queued_request_ids.clear()
        self._disabled_lanes.clear()
        self.stateChanged.emit()
