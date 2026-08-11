# -*- coding: utf-8 -*-
"""Qt dispatcher with one queued entry browser and one separate work browser."""

from __future__ import annotations

from collections import deque

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
    DutySubmissionWorker,
)


RequestKey = tuple[int, str, str, str]


class _EntryWorkerThread(QThread):
    """Report the exact finished thread without relying on QObject.sender()."""

    stoppedWithThread = Signal(object)

    def run(self) -> None:
        try:
            super().run()
        finally:
            self.stoppedWithThread.emit(self)


class DutyExecutionController(QObject):
    """Keep entry submissions serial in one browser; work uses its own channel."""

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
        self._queues: dict[str, deque[tuple[int, DutySubmissionRequest, RequestKey]]] = {
            "work": deque(),
        }
        self._active: dict[str, tuple[int, QThread, DutySubmissionWorker, RequestKey]] = {}
        self._request_lanes: dict[int, str] = {}
        self._requests: dict[int, DutySubmissionRequest] = {}
        self._request_keys: dict[int, RequestKey] = {}
        self._pending_keys: set[RequestKey] = set()
        self._entry_thread: QThread | None = None
        self._entry_worker: DutyEntryQueueWorker | None = None
        self._entry_active_request_id: int | None = None
        self._entry_queued_request_ids: set[int] = set()
        self._entry_stopping = False
        self._disabled_lanes: set[str] = set()
        self._request_id = 0
        self._session_generation = 0
        self._session_closing = False
        self._status_text = "勤務登打待命中"

    @Property(str, notify=stateChanged)
    def statusText(self) -> str:
        return self._status_text

    @Property(int, notify=stateChanged)
    def queuedCount(self) -> int:
        return len(self._entry_queued_request_ids) + sum(len(queue) for queue in self._queues.values())

    @Property(int, notify=stateChanged)
    def activeCount(self) -> int:
        return len(self._active) + int(self._entry_active_request_id is not None)

    @Property(bool, notify=stateChanged)
    def isBusy(self) -> bool:
        return self.activeCount > 0 or self.queuedCount > 0

    def enqueue(self, request: DutySubmissionRequest) -> bool:
        if self._session_closing or not self._request_matches_current_session(request):
            return False
        try:
            request = self._service.validate(request)
        except DutySubmissionValidationError as exc:
            self._report_validation_failure(request, str(exc))
            return False
        if self._session_closing or not self._request_matches_current_session(request):
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
            if worker is None or not worker.enqueue(request_id, request):
                self._forget_request(request_id)
                message = "出入登打瀏覽器正在結束，請重新登入後再試。"
                self._status_text = message
                self.stateChanged.emit()
                self.actionFailed.emit(request.action_index, message, "session_ended")
                self.submissionFailed.emit(request, message, "session_ended", "")
                return False
            self._entry_queued_request_ids.add(request_id)
        else:
            self._queues["work"].append((request_id, request, key))

        self.submissionQueued.emit(request)
        self._status_text = f"準備登打，佇列尚有 {self.queuedCount} 項。"
        self.stateChanged.emit()
        self._start_available_workers()
        return True

    @staticmethod
    def _queue_name(request: DutySubmissionRequest) -> str:
        actions = request.schedule_data.get("actions", [])
        action = actions[request.action_index]
        return (
            "work"
            if action.get("kind") == "work_log" and action.get("source") != "值班交接"
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

        worker = DutyEntryQueueWorker(self._service)
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

    def _start_available_workers(self) -> None:
        if self._session_closing or self.WORK_LANE in self._active:
            return
        while self._queues["work"]:
            request_id, request, key = self._queues["work"].popleft()
            if self._request_matches_current_session(request):
                self._start_work_job(request_id, request, key)
                return
            self._forget_request(request_id)

    def _start_work_job(
        self,
        request_id: int,
        request: DutySubmissionRequest,
        key: RequestKey,
    ) -> None:
        if self._session_closing or not self._request_matches_current_session(request):
            self._forget_request(request_id)
            return
        worker = DutySubmissionWorker(request_id, self._service, request)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._progress)
        worker.succeeded.connect(self._succeeded)
        worker.failed.connect(self._failed)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(self._work_worker_finished)
        self._active[self.WORK_LANE] = (request_id, thread, worker, key)
        self._status_text = "工作登打通道執行中。"
        self.stateChanged.emit()
        self.actionStarted.emit(request.action_index)
        self.submissionStarted.emit(request)
        thread.start()

    @Slot(int, int)
    def _entry_request_started(self, request_id: int, action_index: int) -> None:
        request = self._requests.get(request_id)
        if request is None:
            return
        self._entry_queued_request_ids.discard(request_id)
        self._entry_active_request_id = request_id
        if not self._request_matches_current_session(request):
            self.stateChanged.emit()
            return
        self._status_text = "出入登打通道執行中。"
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
        request = self._requests.get(request_id)
        if error_code == "session_ended":
            if request is not None:
                self.submissionCancelled.emit(request, message, error_code)
            return
        self._failed(request_id, action_index, message, error_code, "")

    @Slot(int)
    def _entry_request_finished(self, request_id: int) -> None:
        self._entry_queued_request_ids.discard(request_id)
        if self._entry_active_request_id == request_id:
            self._entry_active_request_id = None
        self._forget_request(request_id)
        if not self.isBusy:
            self._status_text = "勤務登打已停止，等待登出。" if self._session_closing else "勤務登打待命中"
        self.stateChanged.emit()

    @Slot(int)
    def _work_worker_finished(self, request_id: int) -> None:
        active = self._active.get(self.WORK_LANE)
        if active is None or active[0] != request_id:
            return
        _active_id, thread, _worker, _key = active
        thread.quit()
        if not thread.wait(5_000):
            self._poll_work_thread_finished(request_id)
            return
        self._work_thread_finished(request_id)
        thread.deleteLater()

    def _poll_work_thread_finished(self, request_id: int) -> None:
        active = self._active.get(self.WORK_LANE)
        if active is None or active[0] != request_id:
            return
        _active_id, thread, _worker, _key = active
        if not thread.isFinished():
            QTimer.singleShot(50, lambda: self._poll_work_thread_finished(request_id))
            return
        self._work_thread_finished(request_id)
        thread.deleteLater()

    def _work_thread_finished(self, request_id: int) -> None:
        active = self._active.get(self.WORK_LANE)
        if active is None or active[0] != request_id:
            return
        _active_id, thread, _worker, _key = active
        self._active.pop(self.WORK_LANE, None)
        self._forget_request(request_id)
        if not self.isBusy:
            self._status_text = "勤務登打已停止，等待登出。" if self._session_closing else "勤務登打待命中"
        self.stateChanged.emit()
        self._start_available_workers()

    @Slot(object)
    def _entry_thread_finished(self, finished_thread: QThread) -> None:
        if finished_thread is not self._entry_thread:
            return
        finished_thread.wait()
        self._entry_thread = None
        self._entry_worker = None
        self._entry_stopping = False
        entry_request_ids = {
            request_id
            for request_id, lane in self._request_lanes.items()
            if lane == "entry"
        }
        for request_id in entry_request_ids:
            self._forget_request(request_id)
        self._entry_queued_request_ids.clear()
        self._entry_active_request_id = None
        finished_thread.deleteLater()
        if not self.isBusy:
            self._status_text = "勤務登打已停止，等待登出。" if self._session_closing else "勤務登打待命中"
        self.stateChanged.emit()

    def _forget_request(self, request_id: int) -> None:
        key = self._request_keys.pop(request_id, None)
        if key is not None:
            self._pending_keys.discard(key)
        self._request_lanes.pop(request_id, None)
        self._requests.pop(request_id, None)

    def _request_matches_current_session(self, request: DutySubmissionRequest) -> bool:
        return request.session_generation == self._session_generation

    def _discard_queued_work(self) -> None:
        while self._queues["work"]:
            request_id, request, _key = self._queues["work"].popleft()
            self.submissionCancelled.emit(
                request,
                "勤務登打因登入階段結束而取消。",
                "session_ended",
            )
            self._forget_request(request_id)

    def _report_validation_failure(self, request: DutySubmissionRequest, message: str) -> None:
        self._status_text = message
        self.stateChanged.emit()
        self.actionFailed.emit(request.action_index, message, "validation_error")
        self.submissionFailed.emit(request, message, "validation_error", "")

    @Slot()
    def close_entry_session(self) -> None:
        """Close the shared browser at logout; queued entry tasks are cancelled safely."""

        if self._entry_worker is None or self._entry_stopping:
            return
        self._entry_stopping = True
        self._entry_worker.stop()

    def prepare_session_end(self) -> bool:
        """Stop admitting work and cancel requests that have not started yet."""

        self._session_closing = True
        self._discard_queued_work()
        self.close_entry_session()
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
        self._discard_queued_work()
        self.close_entry_session()
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
        self.close_entry_session()
        entry_thread = self._entry_thread
        if entry_thread is not None:
            if not entry_thread.wait(120_000):
                entry_thread.wait()
            self._entry_thread_finished(entry_thread)

        for lane, (request_id, thread, _worker, _key) in tuple(self._active.items()):
            thread.requestInterruption()
            thread.quit()
            if not thread.wait(120_000):
                thread.wait()
            self._work_thread_finished(request_id)
            thread.deleteLater()
        self._discard_queued_work()
        self._entry_queued_request_ids.clear()
        self._disabled_lanes.clear()
        self.stateChanged.emit()
