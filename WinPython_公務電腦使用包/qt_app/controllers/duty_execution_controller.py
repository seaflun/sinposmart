# -*- coding: utf-8 -*-
"""Two-lane Qt queue for duty-system submission workers."""

from __future__ import annotations

from collections import deque
from PySide6.QtCore import QObject, Property, QThread, Signal, Slot

from app_core.duty_submission_service import (
    DutySubmissionRequest,
    DutySubmissionResult,
    DutySubmissionService,
    DutySubmissionValidationError,
)
from qt_app.workers.duty_submission_worker import DutySubmissionWorker


class DutyExecutionController(QObject):
    stateChanged = Signal()
    actionStarted = Signal(int)
    actionFinished = Signal(int, str, str, str)
    actionFailed = Signal(int, str, str)
    submissionQueued = Signal(object)
    submissionFinished = Signal(object, object)
    submissionFailed = Signal(object, str, str, str)

    def __init__(
        self,
        service: DutySubmissionService,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._queues: dict[str, deque[tuple[int, DutySubmissionRequest, tuple[str, int, str]]]] = {
            "entry": deque(),
            "work": deque(),
        }
        self._active: dict[str, tuple[int, QThread, DutySubmissionWorker, tuple[str, int, str]]] = {}
        self._request_lanes: dict[int, str] = {}
        self._requests: dict[int, DutySubmissionRequest] = {}
        self._pending_keys: set[tuple[str, int, str]] = set()
        self._request_id = 0
        self._status_text = "登打佇列就緒"

    @Property(str, notify=stateChanged)
    def statusText(self) -> str:
        return self._status_text

    @Property(int, notify=stateChanged)
    def queuedCount(self) -> int:
        return sum(len(queue) for queue in self._queues.values())

    @Property(int, notify=stateChanged)
    def activeCount(self) -> int:
        return len(self._active)

    @Property(bool, notify=stateChanged)
    def isBusy(self) -> bool:
        return bool(self._active) or self.queuedCount > 0

    def enqueue(self, request: DutySubmissionRequest) -> bool:
        try:
            request = self._service.validate(request)
        except DutySubmissionValidationError as exc:
            self._status_text = str(exc)
            self.stateChanged.emit()
            self.actionFailed.emit(request.action_index, str(exc), "validation_error")
            self.submissionFailed.emit(request, str(exc), "validation_error", "")
            return False
        key = self._request_key(request)
        if key in self._pending_keys:
            return False
        lane = self._lane(request)
        self._request_id += 1
        request_id = self._request_id
        self._pending_keys.add(key)
        self._queues[lane].append((request_id, request, key))
        self.submissionQueued.emit(request)
        self._status_text = f"已加入登打佇列：{self.queuedCount} 筆"
        self.stateChanged.emit()
        self._start_next(lane)
        return True

    @staticmethod
    def _lane(request: DutySubmissionRequest) -> str:
        actions = request.schedule_data.get("actions", [])
        action = actions[request.action_index]
        if request.trigger_type == "due" and not request.visible and action.get("kind") == "work_log":
            return "work"
        return "entry"

    @staticmethod
    def _request_key(request: DutySubmissionRequest) -> tuple[str, int, str]:
        return (
            str(request.schedule_data.get("target_date", "") or ""),
            request.action_index,
            request.trigger_type,
        )

    def _start_next(self, lane: str) -> None:
        if lane in self._active or not self._queues[lane]:
            return
        request_id, request, key = self._queues[lane].popleft()
        worker = DutySubmissionWorker(request_id, self._service, request)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._progress)
        worker.succeeded.connect(self._succeeded)
        worker.failed.connect(self._failed)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(self._worker_finished)
        self._active[lane] = (request_id, thread, worker, key)
        self._request_lanes[request_id] = lane
        self._requests[request_id] = request
        self._status_text = f"正在執行登打：{self.activeCount} 條佇列"
        self.stateChanged.emit()
        self.actionStarted.emit(request.action_index)
        thread.start()

    @Slot(int, str)
    def _progress(self, request_id: int, message: str) -> None:
        if request_id in self._request_lanes:
            self._status_text = message
            self.stateChanged.emit()

    @Slot(int, object)
    def _succeeded(self, request_id: int, result: DutySubmissionResult) -> None:
        if request_id not in self._request_lanes:
            return
        self._status_text = result.message
        self.stateChanged.emit()
        self.actionFinished.emit(
            result.action_index,
            result.status,
            result.message,
            str(result.result_path),
        )
        self.submissionFinished.emit(self._requests[request_id], result)

    @Slot(int, int, str, str, str)
    def _failed(
        self,
        request_id: int,
        action_index: int,
        message: str,
        error_code: str,
        result_path: str,
    ) -> None:
        if request_id not in self._request_lanes:
            return
        self._status_text = message
        self.stateChanged.emit()
        self.actionFailed.emit(action_index, message, error_code)
        self.submissionFailed.emit(self._requests[request_id], message, error_code, result_path)

    @Slot(int)
    def _worker_finished(self, request_id: int) -> None:
        lane = self._request_lanes.pop(request_id, "")
        active = self._active.get(lane)
        if active is None or active[0] != request_id:
            return
        _active_id, thread, _worker, key = active
        thread.quit()
        if not thread.wait(5_000):
            return
        self._active.pop(lane, None)
        self._pending_keys.discard(key)
        self._requests.pop(request_id, None)
        thread.deleteLater()
        if not self.isBusy:
            self._status_text = "登打佇列已完成"
        self.stateChanged.emit()
        self._start_next(lane)

    @Slot()
    def shutdown(self) -> None:
        for lane, (_request_id, thread, _worker, key) in tuple(self._active.items()):
            thread.requestInterruption()
            thread.quit()
            if thread.wait(120_000):
                self._active.pop(lane, None)
                self._pending_keys.discard(key)
                self._requests.pop(_request_id, None)
                thread.deleteLater()
        for queue in self._queues.values():
            while queue:
                _request_id, _request, key = queue.popleft()
                self._pending_keys.discard(key)
        self.stateChanged.emit()
