# -*- coding: utf-8 -*-
"""Three-lane Qt dispatcher for duty-system submission workers."""

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
    ENTRY_LANES = ("entry_a", "entry_b")
    WORK_LANE = "work"

    stateChanged = Signal()
    actionStarted = Signal(int)
    actionFinished = Signal(int, str, str, str)
    actionFailed = Signal(int, str, str)
    submissionQueued = Signal(object)
    submissionFinished = Signal(object, object)
    submissionFailed = Signal(object, str, str, str)
    allLanesUnavailable = Signal(str)

    def __init__(
        self,
        service: DutySubmissionService,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._queues: dict[str, deque[tuple[int, DutySubmissionRequest, tuple[str, int]]]] = {
            "entry": deque(),
            "work": deque(),
        }
        self._active: dict[str, tuple[int, QThread, DutySubmissionWorker, tuple[str, int]]] = {}
        self._request_lanes: dict[int, str] = {}
        self._requests: dict[int, DutySubmissionRequest] = {}
        self._pending_keys: set[tuple[str, int]] = set()
        self._lane_fallbacks: dict[int, tuple[str, str, str]] = {}
        self._rerouted_keys: set[tuple[str, int]] = set()
        self._disabled_lanes: set[str] = set()
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
        queue_name = self._queue_name(request)
        self._request_id += 1
        request_id = self._request_id
        self._pending_keys.add(key)
        self._queues[queue_name].append((request_id, request, key))
        self.submissionQueued.emit(request)
        self._status_text = f"已加入登打佇列：{self.queuedCount} 筆"
        self.stateChanged.emit()
        self._start_available_workers()
        return True

    @staticmethod
    def _queue_name(request: DutySubmissionRequest) -> str:
        actions = request.schedule_data.get("actions", [])
        action = actions[request.action_index]
        if action.get("kind") == "work_log":
            return "work"
        return "entry"

    @staticmethod
    def _request_key(request: DutySubmissionRequest) -> tuple[str, int]:
        return (
            str(request.schedule_data.get("target_date", "") or ""),
            request.action_index,
        )

    @staticmethod
    def _entry_serial_key(request: DutySubmissionRequest) -> tuple[str, str, str, str] | None:
        actions = request.schedule_data.get("actions", [])
        action = actions[request.action_index]
        if action.get("kind") != "entry_log" or action.get("source") != "值班交接":
            return None
        return (
            str(request.schedule_data.get("target_date", "") or ""),
            str(action.get("time", "") or ""),
            str(action.get("actor", "") or ""),
            str(action.get("source", "") or ""),
        )

    def _active_entry_serial_keys(self) -> set[tuple[str, str, str, str]]:
        keys: set[tuple[str, str, str, str]] = set()
        for request_id, _thread, _worker, _key in self._active.values():
            request = self._requests.get(request_id)
            if request is None:
                continue
            serial_key = self._entry_serial_key(request)
            if serial_key is not None:
                keys.add(serial_key)
        return keys

    def _pop_next_entry_request(self) -> tuple[int, DutySubmissionRequest, tuple[str, int]] | None:
        active_serial_keys = self._active_entry_serial_keys()
        for job in self._queues["entry"]:
            _request_id, request, _key = job
            serial_key = self._entry_serial_key(request)
            if serial_key is None or serial_key not in active_serial_keys:
                self._queues["entry"].remove(job)
                return job
        return None

    def _has_active_work_request(self) -> bool:
        return any(
            request is not None and self._queue_name(request) == "work"
            for request_id, _thread, _worker, _key in self._active.values()
            for request in (self._requests.get(request_id),)
        )

    def _first_available_entry_lane(self) -> str:
        return next(
            (
                lane
                for lane in self.ENTRY_LANES
                if lane not in self._active and lane not in self._disabled_lanes
            ),
            "",
        )

    def _start_available_workers(self) -> None:
        for lane in self.ENTRY_LANES:
            if lane in self._active or lane in self._disabled_lanes:
                continue
            job = self._pop_next_entry_request()
            if job is not None:
                self._start_job(lane, job)

        if (
            self.WORK_LANE not in self._active
            and self.WORK_LANE not in self._disabled_lanes
            and not self._has_active_work_request()
            and self._queues["work"]
        ):
            self._start_job(self.WORK_LANE, self._queues["work"].popleft())

        if self._queues["work"] and not self._has_active_work_request() and self.WORK_LANE in self._disabled_lanes:
            fallback_lane = self._first_available_entry_lane()
            if fallback_lane:
                self._start_job(fallback_lane, self._queues["work"].popleft())

        if (
            self._queues["entry"]
            and all(lane in self._disabled_lanes for lane in self.ENTRY_LANES)
            and self.WORK_LANE not in self._active
            and self.WORK_LANE not in self._disabled_lanes
            and not self._has_active_work_request()
        ):
            job = self._pop_next_entry_request()
            if job is not None:
                self._start_job(self.WORK_LANE, job)

    def _start_job(
        self,
        lane: str,
        job: tuple[int, DutySubmissionRequest, tuple[str, int]],
    ) -> None:
        if lane in self._active:
            return
        request_id, request, key = job
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
        self._status_text = f"正在執行登打：{self.activeCount} 條工作線"
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
        lane = self._request_lanes[request_id]
        active = self._active.get(lane)
        key = active[3] if active is not None else None
        if error_code == "browser_startup" and key is not None and key not in self._rerouted_keys:
            self._lane_fallbacks[request_id] = (message, error_code, result_path)
            self._status_text = "瀏覽器工作線啟動失敗，正在移交其他工作線。"
            self.stateChanged.emit()
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
        fallback = self._lane_fallbacks.pop(request_id, None)
        request = self._requests.pop(request_id, None)
        self._active.pop(lane, None)
        self._pending_keys.discard(key)
        thread.deleteLater()
        if fallback is not None and request is not None:
            message, _error_code, _result_path = fallback
            self._disabled_lanes.add(lane)
            self._rerouted_keys.add(key)
            self._request_id += 1
            self._pending_keys.add(key)
            self._queues[self._queue_name(request)].appendleft((self._request_id, request, key))
            if all(candidate in self._disabled_lanes for candidate in (*self.ENTRY_LANES, self.WORK_LANE)):
                self._fail_queued_for_unavailable_lanes(message)
                self.allLanesUnavailable.emit("所有瀏覽器工作線均無法啟動，已暫停自動登打。")
                return
            self._status_text = f"{lane} 啟動失敗，已移交其他工作線：{message}"
            self.stateChanged.emit()
            self._start_available_workers()
            return
        if not self.isBusy:
            self._status_text = "登打佇列已完成"
        self.stateChanged.emit()
        self._start_available_workers()

    def _fail_queued_for_unavailable_lanes(self, message: str) -> None:
        for queue in self._queues.values():
            while queue:
                _request_id, request, key = queue.popleft()
                self._pending_keys.discard(key)
                self.actionFailed.emit(request.action_index, message, "browser_startup")
                self.submissionFailed.emit(request, message, "browser_startup", "")
        self._status_text = "所有瀏覽器工作線均無法啟動，已暫停自動登打。"
        self.stateChanged.emit()

    def reset_parallel_lanes(self) -> None:
        if self.isBusy or not self._disabled_lanes:
            return
        self._disabled_lanes.clear()
        self._rerouted_keys.clear()
        self._lane_fallbacks.clear()
        self._status_text = "登打佇列就緒"
        self.stateChanged.emit()

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
        self._lane_fallbacks.clear()
        self._rerouted_keys.clear()
        self._disabled_lanes.clear()
        self.stateChanged.emit()
