# -*- coding: utf-8 -*-
"""QML-facing state and confirmation flow for rescue-video classification."""

from __future__ import annotations

from PySide6.QtCore import QObject, Property, QThread, QUrl, Signal, Slot

from app_core.rescue_video_service import (
    RescueVideoDefaults,
    RescueVideoRequest,
    RescueVideoRunResult,
    RescueVideoService,
    RescueVideoValidationError,
)
from app_core.session import SessionState
from qt_app.models.rescue_video_result_model import RescueVideoResultModel
from qt_app.workers.rescue_video_worker import RescueVideoWorker


class RescueVideoController(QObject):
    stateChanged = Signal()
    copyConfirmationRequested = Signal()
    deleteConfirmationRequested = Signal()
    runStarted = Signal(str)
    runSucceeded = Signal(str)
    runFailed = Signal(str, str)
    errorOccurred = Signal(str)

    def __init__(
        self,
        service: RescueVideoService,
        parent: QObject | None = None,
        *,
        session_state: SessionState | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._session_state = session_state
        self._source_path = ""
        self._destination_path = ""
        self._target_date = ""
        self._vehicle_options: list[str] = []
        self._selected_vehicle = ""
        self._offset_text = ""
        self._repair_mismatch = False
        self._check_text = "正在檢查記憶卡、Z 槽與工作紀錄。"
        self._check_cards: list[dict[str, str]] = []
        self._is_ready = False
        self._status_text = "自動檢查中"
        self._summary_text = "等待自動檢查完成。"
        self._report_path = ""
        self._confirmation_summary = ""
        self._pending_request: RescueVideoRequest | None = None
        self._request_id = 0
        self._failure_stage = "unknown"
        self._workers: dict[int, tuple[QThread, RescueVideoWorker]] = {}
        self._worker_modes: dict[int, str] = {}
        self._result_model = RescueVideoResultModel(self)

    @Property(str, notify=stateChanged)
    def sourcePath(self) -> str:
        return self._source_path

    @Property(str, notify=stateChanged)
    def destinationPath(self) -> str:
        return self._destination_path

    @Property(str, notify=stateChanged)
    def targetDate(self) -> str:
        return self._target_date

    @Property("QVariantList", notify=stateChanged)
    def vehicleOptions(self) -> list[str]:
        return self._vehicle_options

    @Property(str, notify=stateChanged)
    def selectedVehicle(self) -> str:
        return self._selected_vehicle

    @Property(str, notify=stateChanged)
    def offsetText(self) -> str:
        return self._offset_text

    @Property(bool, notify=stateChanged)
    def repairMismatch(self) -> bool:
        return self._repair_mismatch

    @Property(str, notify=stateChanged)
    def checkText(self) -> str:
        return self._check_text

    @Property("QVariantList", notify=stateChanged)
    def checkCards(self) -> list[dict[str, str]]:
        return self._check_cards

    @Property(bool, notify=stateChanged)
    def isReady(self) -> bool:
        return self._is_ready

    @Property(str, notify=stateChanged)
    def statusText(self) -> str:
        return self._status_text

    @Property(str, notify=stateChanged)
    def summaryText(self) -> str:
        return self._summary_text

    @Property(str, notify=stateChanged)
    def reportPath(self) -> str:
        return self._report_path

    @Property(str, notify=stateChanged)
    def confirmationSummary(self) -> str:
        return self._confirmation_summary

    @Property(str, notify=stateChanged)
    def failureStage(self) -> str:
        return self._failure_stage

    @Property(bool, notify=stateChanged)
    def isRunning(self) -> bool:
        return bool(self._workers)

    @Property(QObject, constant=True)
    def resultModel(self) -> RescueVideoResultModel:
        return self._result_model

    @Slot()
    def loadDefaults(self) -> None:
        if self._workers:
            return
        self._is_ready = False
        self._status_text = "自動檢查中"
        self._check_text = "正在檢查記憶卡、Z 槽與工作紀錄。"
        self.stateChanged.emit()
        self._start_worker("defaults")

    @Slot(str, str, str)
    def refreshAutomaticState(self, source_path: str, target_date: str, vehicle: str) -> None:
        if self._workers:
            return
        self._is_ready = False
        self._status_text = "自動檢查中"
        self.stateChanged.emit()
        self._start_worker(
            "defaults",
            defaults_source=source_path,
            defaults_date=target_date,
            defaults_vehicle=vehicle,
        )

    @Slot(QUrl, result=str)
    def localPath(self, url: QUrl) -> str:
        return url.toLocalFile() if url.isLocalFile() else ""

    @Slot(str, str, str, str, str, bool)
    def preparePreview(
        self,
        source_path: str,
        destination_path: str,
        target_date: str,
        vehicle: str,
        offset_text: str,
        repair_mismatch: bool,
    ) -> None:
        request = self._request(
            source_path,
            destination_path,
            target_date,
            vehicle,
            offset_text,
            repair_mismatch,
            "preview",
        )
        if request is not None:
            self._start_worker("execute", request)

    @Slot(str, str, str, str, str, bool)
    def prepareCopy(
        self,
        source_path: str,
        destination_path: str,
        target_date: str,
        vehicle: str,
        offset_text: str,
        repair_mismatch: bool,
    ) -> None:
        request = self._request(
            source_path,
            destination_path,
            target_date,
            vehicle,
            offset_text,
            repair_mismatch,
            "copy",
        )
        if request is None:
            return
        if self._prepare_confirmation(request, "等待確認執行影片複製。"):
            self.copyConfirmationRequested.emit()

    @Slot(str, str, str, str, str, bool)
    def prepareDelete(
        self,
        source_path: str,
        destination_path: str,
        target_date: str,
        vehicle: str,
        offset_text: str,
        repair_mismatch: bool,
    ) -> None:
        request = self._request(
            source_path,
            destination_path,
            target_date,
            vehicle,
            offset_text,
            repair_mismatch,
            "delete",
        )
        if request is None:
            return
        if self._prepare_confirmation(request, "自動檢查通過"):
            self.deleteConfirmationRequested.emit()

    @Slot()
    def confirmCopy(self) -> None:
        self.confirmDelete()

    @Slot()
    def cancelCopy(self) -> None:
        self._pending_request = None
        self._confirmation_summary = ""
        self._status_text = "已取消影片複製。"
        self.stateChanged.emit()

    @Slot()
    def confirmDelete(self) -> None:
        if self._pending_request is None or self._workers:
            return
        request = self._pending_request
        self._pending_request = None
        self._confirmation_summary = ""
        self._start_worker("execute", request)

    @Slot()
    def cancelDelete(self) -> None:
        self._pending_request = None
        self._confirmation_summary = ""
        self._status_text = "自動檢查通過" if self._is_ready else "等待必要資料"
        self.stateChanged.emit()

    def _prepare_confirmation(self, request: RescueVideoRequest, status_text: str) -> bool:
        try:
            summary = self._service.confirmation_summary(request)
        except RescueVideoValidationError as exc:
            self._set_error(str(exc))
            return False
        self._pending_request = request
        self._confirmation_summary = summary
        self._status_text = status_text
        self.stateChanged.emit()
        return True

    def _request(
        self,
        source_path: str,
        destination_path: str,
        target_date: str,
        vehicle: str,
        offset_text: str,
        repair_mismatch: bool,
        mode: str,
    ) -> RescueVideoRequest | None:
        if self._workers:
            return None
        request = RescueVideoRequest(
            source_path,
            destination_path,
            target_date,
            vehicle,
            offset_text,
            repair_mismatch,
            mode,
        )
        try:
            normalized, _warnings, _values = self._service.validate(request)
        except RescueVideoValidationError as exc:
            self._set_error(str(exc))
            return None
        return normalized

    def _start_worker(
        self,
        operation: str,
        request: RescueVideoRequest | None = None,
        *,
        defaults_source: str = "",
        defaults_date: str = "",
        defaults_vehicle: str = "",
    ) -> None:
        if operation == "execute" and self._session_state is not None:
            session = self._session_state.session
            if session is None or not session.verified or not str(session.actor_no or "").strip():
                self._set_error("登入身分尚未完成番號確認，請稍候勤務表查詢完成。")
                return
        self._request_id += 1
        request_id = self._request_id
        self._failure_stage = "unknown"
        worker = RescueVideoWorker(
            request_id,
            self._service,
            operation,
            request,
            defaults_source,
            defaults_date,
            defaults_vehicle,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._progress)
        worker.defaultsLoaded.connect(self._defaults_loaded)
        worker.runSucceeded.connect(self._run_succeeded)
        worker.failed.connect(self._failed)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(self._worker_finished)
        self._workers[request_id] = (thread, worker)
        mode = request.mode if operation == "execute" and request is not None else ""
        self._worker_modes[request_id] = mode
        if mode:
            self._status_text = "執行中，請勿拔除記憶卡或關閉視窗"
        self.stateChanged.emit()
        if mode:
            self.runStarted.emit(mode)
        thread.start()

    @Slot(int, str)
    def _progress(self, request_id: int, message: str) -> None:
        if request_id == self._request_id:
            self._status_text = message
            self.stateChanged.emit()

    @Slot(int, object)
    def _defaults_loaded(self, request_id: int, defaults: RescueVideoDefaults) -> None:
        if request_id != self._request_id:
            return
        self._source_path = defaults.source_path
        self._destination_path = defaults.destination_path
        self._target_date = defaults.target_date
        self._vehicle_options = list(defaults.vehicle_options)
        self._selected_vehicle = defaults.selected_vehicle
        self._offset_text = defaults.offset_text
        self._repair_mismatch = defaults.repair_mismatch
        self._check_text = defaults.check_text
        self._check_cards = [
            {
                "key": card.key,
                "title": card.title,
                "detail": card.detail,
                "level": card.level,
            }
            for card in defaults.check_cards
        ]
        self._is_ready = defaults.is_ready
        self._status_text = defaults.status_text
        self._summary_text = (
            "可以預覽分類，或複製後刪除已驗證來源。"
            if defaults.is_ready
            else "請插入記憶卡並確認 Z 槽與工作紀錄可用。"
        )
        self.stateChanged.emit()

    @Slot(int, object)
    def _run_succeeded(self, request_id: int, result: RescueVideoRunResult) -> None:
        if request_id != self._request_id:
            return
        self._result_model.replace_rows(result.rows)
        self._summary_text = result.summary_text
        self._report_path = result.report_path
        self._status_text = result.warning_text or "完成"
        self.stateChanged.emit()
        self.runSucceeded.emit(result.summary_text)

    @Slot(int, str)
    def _failed(self, request_id: int, message: str) -> None:
        if request_id == self._request_id:
            self._is_ready = False
            worker_pair = self._workers.get(request_id)
            worker = worker_pair[1] if worker_pair is not None else None
            self._failure_stage = str(getattr(worker, "failure_stage", "unknown") or "unknown")
            mode = self._worker_modes.get(request_id, "")
            if mode:
                self.runFailed.emit(mode, message)
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
        self._worker_modes.pop(request_id, None)
        thread.deleteLater()
        self.stateChanged.emit()

    @Slot()
    def shutdown(self) -> None:
        for request_id, (thread, _worker) in tuple(self._workers.items()):
            thread.requestInterruption()
            thread.quit()
            if thread.wait(120_000):
                self._workers.pop(request_id, None)
                self._worker_modes.pop(request_id, None)
                thread.deleteLater()

    def _set_error(self, message: str) -> None:
        self._status_text = message
        self.stateChanged.emit()
        self.errorOccurred.emit(message)
