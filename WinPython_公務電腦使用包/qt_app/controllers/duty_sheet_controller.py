# -*- coding: utf-8 -*-
"""QML-facing state and confirmation flow for duty-sheet automation."""

from __future__ import annotations

from PySide6.QtCore import QObject, Property, QThread, QUrl, Signal, Slot

from app_core.duty_sheet_service import (
    DutySheetRequest,
    DutySheetService,
    DutySheetValidationError,
)
from app_core.session import SessionState
from qt_app.workers.duty_sheet_worker import DutySheetWorker


class DutySheetController(QObject):
    stateChanged = Signal()
    confirmationRequested = Signal()
    runStarted = Signal()
    runSucceeded = Signal(str)
    runFailed = Signal(str)
    errorOccurred = Signal(str)

    def __init__(
        self,
        session_state: SessionState,
        service: DutySheetService,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._session_state = session_state
        self._service = service
        self._workbook_path = ""
        self._target_date = ""
        self._attack = ""
        self._stop = ""
        self._amb1 = ""
        self._amb2 = ""
        self._attack_options: list[str] = []
        self._stop_options: list[str] = []
        self._amb_options: list[str] = []
        self._notification_enabled = False
        self._status_text = "尚未載入勤務表設定"
        self._confirmation_summary = ""
        self._pending_request: DutySheetRequest | None = None
        self._request_id = 0
        self._failure_stage = "unknown"
        self._workers: dict[int, tuple[QThread, DutySheetWorker]] = {}

    @Property(str, notify=stateChanged)
    def workbookPath(self) -> str:
        return self._workbook_path

    @Property(str, notify=stateChanged)
    def targetDate(self) -> str:
        return self._target_date

    @Property(str, notify=stateChanged)
    def attack(self) -> str:
        return self._attack

    @Property(str, notify=stateChanged)
    def stop(self) -> str:
        return self._stop

    @Property(str, notify=stateChanged)
    def amb1(self) -> str:
        return self._amb1

    @Property(str, notify=stateChanged)
    def amb2(self) -> str:
        return self._amb2

    @Property("QVariantList", notify=stateChanged)
    def attackOptions(self) -> list[str]:
        return self._attack_options

    @Property("QVariantList", notify=stateChanged)
    def stopOptions(self) -> list[str]:
        return self._stop_options

    @Property("QVariantList", notify=stateChanged)
    def ambOptions(self) -> list[str]:
        return self._amb_options

    @Property(bool, notify=stateChanged)
    def notificationEnabled(self) -> bool:
        return self._notification_enabled

    @Slot(bool)
    def setNotificationEnabled(self, enabled: bool) -> None:
        """Keep the screenshot-notification choice as the QML source of truth."""

        enabled = bool(enabled)
        if enabled == self._notification_enabled:
            return
        self._notification_enabled = enabled
        self.stateChanged.emit()

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
        self._apply_defaults(defaults)
        self._status_text = "準備就緒。"
        self.stateChanged.emit()

    def _apply_defaults(self, defaults) -> None:
        self._workbook_path = defaults.workbook_path
        self._target_date = defaults.target_date
        self._attack = defaults.attack
        self._stop = defaults.stop
        self._amb1 = defaults.amb1
        self._amb2 = defaults.amb2
        self._attack_options = list(defaults.attack_options)
        self._stop_options = list(defaults.stop_options)
        self._amb_options = list(defaults.amb_options)
        self._notification_enabled = defaults.notification_enabled

    @Slot(QUrl, result=str)
    def localPath(self, url: QUrl) -> str:
        return url.toLocalFile() if url.isLocalFile() else ""

    @Slot(str, str, str)
    def addVehicleOption(self, group: str, code: str, plate: str) -> None:
        try:
            value = self._service.add_vehicle_option(group, code, plate)
            defaults = self._service.load_defaults()
        except DutySheetValidationError as exc:
            self._set_error(str(exc))
            return
        self._apply_defaults(defaults)
        vehicle_type = "消防車" if group == "attack" else "救護車"
        self._status_text = f"已新增{vehicle_type}：{value}"
        self.stateChanged.emit()

    @Slot(str, str)
    def removeVehicleOption(self, group: str, value: str) -> None:
        try:
            removed = self._service.remove_vehicle_option(group, value)
            defaults = self._service.load_defaults()
        except DutySheetValidationError as exc:
            self._set_error(str(exc))
            return
        self._apply_defaults(defaults)
        vehicle_type = "消防車" if group == "attack" else "救護車"
        self._status_text = f"已移除{vehicle_type}：{removed}"
        self.stateChanged.emit()

    @Slot(str, str, str, str, str, str, bool)
    def prepareRun(
        self,
        workbook_path: str,
        target_date: str,
        attack: str,
        stop: str,
        amb1: str,
        amb2: str,
        notification_enabled: bool,
    ) -> None:
        session = self._session_state.session
        if session is None or not session.verified:
            self._set_error("請先完成勤務系統登入。")
            return
        request = DutySheetRequest(
            session.user_id,
            session.password,
            workbook_path,
            target_date,
            attack,
            stop,
            amb1,
            amb2,
            notification_enabled,
        )
        try:
            request = self._service.validate(request)
        except DutySheetValidationError as exc:
            self._set_error(str(exc))
            return
        self._pending_request = request
        self._confirmation_summary = self._service.confirmation_summary(request)
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
        self._status_text = "正在執行勤務表登打…"

        worker = DutySheetWorker(request_id, self._service, request)
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
        self._status_text = "已取消勤務表登打。"
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
        if request_id != self._request_id:
            return
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
