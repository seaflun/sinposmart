# -*- coding: utf-8 -*-
"""QML-facing confirmation flow for daily vehicle automation."""

from __future__ import annotations

from PySide6.QtCore import QObject, Property, QThread, Signal, Slot

from app_core.daily_vehicle_service import (
    DailyVehicleRequest,
    DailyVehicleService,
    DailyVehicleValidationError,
)
from app_core.session import SessionState
from qt_app.workers.daily_vehicle_worker import DailyVehicleWorker


class DailyVehicleController(QObject):
    stateChanged = Signal()
    confirmationRequested = Signal()
    runStarted = Signal()
    runSucceeded = Signal(str)
    runFailed = Signal(str)
    errorOccurred = Signal(str)

    def __init__(
        self,
        session_state: SessionState,
        service: DailyVehicleService,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._session_state = session_state
        self._service = service
        self._target_date = ""
        self._operations: list[str] = []
        self._status_text = "尚未載入設定"
        self._confirmation_summary = ""
        self._pending_request: DailyVehicleRequest | None = None
        self._request_id = 0
        self._failure_stage = "unknown"
        self._workers: dict[int, tuple[QThread, DailyVehicleWorker]] = {}

    @Property(str, notify=stateChanged)
    def targetDate(self) -> str:
        return self._target_date

    @Property("QVariantList", notify=stateChanged)
    def operations(self) -> list[str]:
        return self._operations

    @Property(str, notify=stateChanged)
    def statusText(self) -> str:
        return self._status_text

    @Property(str, notify=stateChanged)
    def confirmationSummary(self) -> str:
        return self._confirmation_summary

    @Property(str, notify=stateChanged)
    def failureStage(self) -> str:
        return self._failure_stage

    @Property(bool, notify=stateChanged)
    def isRunning(self) -> bool:
        return bool(self._workers)

    @Slot()
    def loadDefaults(self) -> None:
        defaults = self._service.load_defaults()
        self._target_date = defaults.target_date
        self._operations = list(defaults.operations)
        self._status_text = "準備就緒。"
        self.stateChanged.emit()

    @Slot()
    def prepareRun(self) -> None:
        session = self._session_state.session
        if session is None or not session.verified:
            self._set_error("請先完成勤務系統登入。")
            return
        try:
            request = self._service.validate(DailyVehicleRequest(session.user_id, session.password))
            summary = self._service.confirmation_summary(request)
        except DailyVehicleValidationError as exc:
            self._set_error(str(exc))
            return
        self._pending_request = request
        self._confirmation_summary = summary
        self._status_text = "等待使用者確認正式登打。"
        self.stateChanged.emit()
        self.confirmationRequested.emit()

    @Slot()
    def confirmRun(self) -> None:
        if self._pending_request is None or self._workers:
            return
        self._request_id += 1
        request_id = self._request_id
        self._failure_stage = "unknown"
        request = self._pending_request
        self._pending_request = None
        self._confirmation_summary = ""
        self._status_text = "正在執行車輛保養清點…"
        worker = DailyVehicleWorker(request_id, self._service, request)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._progress)
        worker.succeeded.connect(self._succeeded)
        worker.failed.connect(self._failed)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(self._worker_finished)
        self._workers[request_id] = (thread, worker)
        self.stateChanged.emit()
        self.runStarted.emit()
        thread.start()

    @Slot()
    def cancelPendingRun(self) -> None:
        self._pending_request = None
        self._confirmation_summary = ""
        self._status_text = "已取消車輛保養清點。"
        self.stateChanged.emit()

    @Slot(int, str)
    def _progress(self, request_id: int, message: str) -> None:
        if request_id == self._request_id:
            self._status_text = message
            self.stateChanged.emit()

    @Slot(int, str)
    def _succeeded(self, request_id: int, message: str) -> None:
        if request_id != self._request_id:
            return
        self._status_text = message
        self.stateChanged.emit()
        self.runSucceeded.emit(message)

    @Slot(int, str)
    def _failed(self, request_id: int, message: str) -> None:
        if request_id == self._request_id:
            worker_pair = self._workers.get(request_id)
            worker = worker_pair[1] if worker_pair is not None else None
            self._failure_stage = str(getattr(worker, "failure_stage", "unknown") or "unknown")
            self.runFailed.emit(message)
            self._set_error(message)

    @Slot(int)
    def _worker_finished(self, request_id: int) -> None:
        worker_pair = self._workers.get(request_id)
        if worker_pair is None:
            return
        thread, _worker = worker_pair
        thread.quit()
        if not thread.wait(5_000):
            return
        self._workers.pop(request_id, None)
        thread.deleteLater()
        self.stateChanged.emit()

    @Slot()
    def shutdown(self) -> None:
        for request_id, (thread, _worker) in tuple(self._workers.items()):
            thread.requestInterruption()
            thread.quit()
            if thread.wait(120_000):
                self._workers.pop(request_id, None)
                thread.deleteLater()

    def _set_error(self, message: str) -> None:
        self._status_text = message
        self.stateChanged.emit()
        self.errorOccurred.emit(message)
