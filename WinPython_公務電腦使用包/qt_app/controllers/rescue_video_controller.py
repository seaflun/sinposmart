# -*- coding: utf-8 -*-
"""QML-facing state and confirmation flow for rescue-video classification."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Property, QThread, QTimer, QUrl, Signal, Slot

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
        self._check_text = "尚未開始。插入單張記憶卡後會自動尋找 DCIM\\100CAREC，再確認日期與車號。"
        self._check_cards: list[dict[str, str]] = []
        self._is_ready = False
        self._has_preview = False
        self._awaiting_confirmation = False
        self._check_requested = False
        self._preview_after_check = False
        self._status_text = "尚未開始"
        self._summary_text = "本工具只支援單張記憶卡；插卡後會自動尋找 DCIM\\100CAREC。"
        self._error_text = ""
        self._report_path = ""
        self._confirmation_summary = ""
        self._pending_request: RescueVideoRequest | None = None
        self._request_id = 0
        self._failure_stage = "unknown"
        self._workers: dict[int, tuple[QThread, RescueVideoWorker]] = {}
        self._worker_modes: dict[int, str] = {}
        self._shutting_down = False
        self._last_completed_mode = ""
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

    @Property(bool, notify=stateChanged)
    def hasPreview(self) -> bool:
        return self._has_preview

    @Property(bool, notify=stateChanged)
    def isAwaitingConfirmation(self) -> bool:
        return self._awaiting_confirmation

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

    @Property(str, notify=stateChanged)
    def errorText(self) -> str:
        return self._error_text

    @Property(str, notify=stateChanged)
    def lastCompletedMode(self) -> str:
        return self._last_completed_mode

    @Property(bool, notify=stateChanged)
    def isRunning(self) -> bool:
        return bool(self._workers)

    @Property(QObject, constant=True)
    def resultModel(self) -> RescueVideoResultModel:
        return self._result_model

    @Slot()
    def resetForNextSession(self) -> None:
        if self._workers:
            return
        self._source_path = ""
        self._destination_path = ""
        self._target_date = ""
        self._vehicle_options = []
        self._selected_vehicle = ""
        self._offset_text = ""
        self._repair_mismatch = False
        self._check_text = "尚未開始。插入單張記憶卡後會自動尋找 DCIM\\100CAREC，再確認日期與車號。"
        self._check_cards = []
        self._is_ready = False
        self._has_preview = False
        self._awaiting_confirmation = False
        self._check_requested = False
        self._preview_after_check = False
        self._status_text = "尚未開始"
        self._summary_text = "本工具只支援單張記憶卡；插卡後會自動尋找 DCIM\\100CAREC。"
        self._error_text = ""
        self._report_path = ""
        self._confirmation_summary = ""
        self._pending_request = None
        self._failure_stage = "unknown"
        self._last_completed_mode = ""
        self._result_model.replace_rows(())
        self.stateChanged.emit()

    @Slot()
    def loadDefaults(self) -> None:
        if self._shutting_down or self._workers:
            return
        self._is_ready = False
        self._has_preview = False
        self._awaiting_confirmation = False
        self._check_requested = False
        self._preview_after_check = False
        self._status_text = "讀取工具設定中"
        self._check_text = "尚未開始。插入單張記憶卡後會自動尋找 DCIM\\100CAREC，再確認日期與車號。"
        self._error_text = ""
        self._set_check_cards_pending(initial=True)
        self.stateChanged.emit()
        self._start_worker("defaults")

    @Slot(str, str, str)
    def refreshAutomaticState(self, source_path: str, target_date: str, vehicle: str) -> None:
        self._begin_check(source_path, target_date, vehicle, preview_after_check=False)

    @Slot(str, str, str)
    def checkAndPreview(self, source_path: str, target_date: str, vehicle: str) -> None:
        self._begin_check(source_path, target_date, vehicle, preview_after_check=True)

    def _begin_check(
        self,
        source_path: str,
        target_date: str,
        vehicle: str,
        *,
        preview_after_check: bool,
    ) -> None:
        if self._shutting_down or self._workers:
            return
        self._is_ready = False
        self._has_preview = False
        self._awaiting_confirmation = False
        self._check_requested = True
        self._preview_after_check = preview_after_check
        self._status_text = "檢查中"
        self._error_text = ""
        self._summary_text = "正在檢查資料；通過後會自動預覽分類結果。" if preview_after_check else "正在檢查資料。"
        self.stateChanged.emit()
        self._start_worker(
            "defaults",
            defaults_source=source_path,
            defaults_date=target_date,
            defaults_vehicle=vehicle,
        )

    @Slot(str, str)
    def refreshVehicleOptions(self, source_path: str, target_date: str) -> None:
        if self._shutting_down or self._workers or self._awaiting_confirmation:
            return
        self._source_path = source_path
        self._target_date = target_date
        self._selected_vehicle = ""
        self._is_ready = False
        self._has_preview = False
        self._check_requested = False
        self._preview_after_check = False
        self._status_text = "正在依日期尋找車號"
        self._check_text = "日期已變更，正在更新可用車號。"
        self._summary_text = "已依日期重新尋找案件車號；請按「檢查及預覽分類」開始。"
        self._error_text = ""
        self._set_check_cards_pending(initial=False)
        self._result_model.replace_rows(())
        self.stateChanged.emit()
        self._start_worker(
            "defaults",
            defaults_source=source_path,
            defaults_date=target_date,
            defaults_vehicle="",
        )

    @Slot(str, str, str)
    def updateInputs(self, source_path: str, target_date: str, vehicle: str) -> None:
        if self._workers or self._awaiting_confirmation:
            return
        self._source_path = source_path
        self._target_date = target_date
        self._selected_vehicle = vehicle
        self._is_ready = False
        self._has_preview = False
        self._check_requested = False
        self._preview_after_check = False
        self._status_text = "尚未開始"
        self._check_text = "資料已變更，請按「檢查及預覽分類」重新確認。"
        self._summary_text = "資料已變更。請按「檢查及預覽分類」重新確認。"
        self._error_text = ""
        self._set_check_cards_pending(initial=False)
        self._result_model.replace_rows(())
        self.stateChanged.emit()

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
        if self._shutting_down:
            return
        if not self._is_ready or self._awaiting_confirmation:
            self._set_error("請先按「檢查及預覽分類」並確認結果通過。")
            return
        self._has_preview = False
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
        if not self._is_ready or not self._has_preview or self._awaiting_confirmation:
            self._set_error("請先按「檢查及預覽分類」並等待完成，才能啟動複製。")
            return
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
        if not self._is_ready or not self._has_preview or self._awaiting_confirmation:
            self._set_error("請先按「檢查及預覽分類」並等待完成，才能啟動複製。")
            return
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
        if self._prepare_confirmation(request, "等待確認複製並刪除記憶卡中資料"):
            self.deleteConfirmationRequested.emit()

    @Slot()
    def confirmCopy(self) -> None:
        self.confirmDelete()

    @Slot()
    def cancelCopy(self) -> None:
        self._pending_request = None
        self._confirmation_summary = ""
        self._awaiting_confirmation = False
        self._status_text = "已完成預覽，等待複製並刪除記憶卡中資料。"
        self.stateChanged.emit()

    @Slot()
    def confirmDelete(self) -> None:
        if self._shutting_down or self._pending_request is None or self._workers:
            return
        request = self._pending_request
        self._pending_request = None
        self._confirmation_summary = ""
        self._awaiting_confirmation = False
        self._has_preview = False
        self._result_model.prepare_transfer()
        self._start_worker("execute", request)

    @Slot()
    def cancelDelete(self) -> None:
        self._pending_request = None
        self._confirmation_summary = ""
        self._awaiting_confirmation = False
        self._status_text = "已完成預覽，等待複製並刪除記憶卡中資料。" if self._has_preview else "等待必要資料"
        self.stateChanged.emit()

    def _prepare_confirmation(self, request: RescueVideoRequest, status_text: str) -> bool:
        try:
            summary = self._service.confirmation_summary(request)
        except RescueVideoValidationError as exc:
            self._set_error(str(exc))
            return False
        self._pending_request = request
        self._confirmation_summary = summary
        self._awaiting_confirmation = True
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
        if self._shutting_down:
            return
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
        worker.transferProgress.connect(self._transfer_progress)
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

    @Slot(int, str, int, int, str)
    def _transfer_progress(
        self,
        request_id: int,
        source_path: str,
        copied: int,
        total: int,
        state: str,
    ) -> None:
        if request_id != self._request_id:
            return
        self._result_model.update_transfer(source_path, copied, total, state)
        self._status_text = f"{Path(source_path).name}：{state}"
        self.stateChanged.emit()

    @Slot(int, object)
    def _defaults_loaded(self, request_id: int, defaults: RescueVideoDefaults) -> None:
        if request_id != self._request_id:
            return
        self._error_text = ""
        self._source_path = defaults.source_path
        self._destination_path = defaults.destination_path
        self._target_date = defaults.target_date
        self._vehicle_options = list(defaults.vehicle_options)
        self._selected_vehicle = defaults.selected_vehicle
        self._offset_text = defaults.offset_text
        self._repair_mismatch = defaults.repair_mismatch
        self._check_text = defaults.check_text
        check_cards = [
            {
                "key": card.key,
                "title": card.title,
                "detail": card.detail,
                "level": card.level,
            }
            for card in defaults.check_cards
        ]
        if self._check_requested:
            self._check_cards = check_cards
        else:
            self._set_check_cards_pending(check_cards, initial=True)
        self._is_ready = self._check_requested and defaults.is_ready
        self._has_preview = False
        self._awaiting_confirmation = False
        if self._is_ready:
            if self._preview_after_check:
                self._status_text = "檢查完成，準備預覽分類"
                self._summary_text = "檢查通過，正在預覽分類結果。"
            else:
                self._status_text = "檢查完成"
                self._summary_text = "檢查完成。可按「檢查及預覽分類」開始預覽。"
        elif self._check_requested:
            self._preview_after_check = False
            failed_titles = [
                card.title for card in defaults.check_cards if card.level == "error"
            ]
            if failed_titles == ["車號與日期"]:
                self._status_text = "尚未選擇車號或日期"
                self._summary_text = "請先選擇日期與車號，再按「檢查及預覽分類」。"
            else:
                failed_text = "、".join(failed_titles) or "必要資料"
                self._status_text = f"檢查未通過：{failed_text}"
                self._summary_text = f"請先處理：{failed_text}，再按「檢查及預覽分類」。"
        else:
            self._status_text = "尚未開始"
            self._summary_text = "插入單張記憶卡後會自動尋找 DCIM\\100CAREC；再確認日期與車號。"
        self.stateChanged.emit()

    def _set_check_cards_pending(
        self,
        cards: list[dict[str, str]] | None = None,
        *,
        initial: bool = False,
    ) -> None:
        current_cards = self._check_cards if cards is None else cards
        initial_details = {
            "source": "尚未開始；插入單張記憶卡後會自動尋找 DCIM\\100CAREC。",
            "destination": "尚未開始；檢查固定案件目的地是否可存取。",
            "work_log": "尚未開始；檢查工作／返隊紀錄是否可讀取。",
            "vehicle_date": "尚未開始；確認日期後從當日案件選擇車號。",
            "report": "尚未開始；確認分類報告輸出位置可寫入。",
            "videos": "尚未開始；確認記憶卡內有可讀取的 .TS 影片。",
        }
        state_text = "尚未開始" if initial else "待重新檢查"
        self._check_cards = [
            {
                "key": card["key"],
                "title": card["title"],
                "detail": initial_details.get(
                    card["key"],
                    "尚未開始；完成前置檢查後才會顯示結果。",
                )
                if initial
                else "資料已變更，請按「檢查及預覽分類」重新檢查。",
                "level": "pending",
                "stateText": state_text,
                "nextStep": initial and card["key"] == "source",
            }
            for card in current_cards
        ]

    @Slot(int, object)
    def _run_succeeded(self, request_id: int, result: RescueVideoRunResult) -> None:
        if request_id != self._request_id:
            return
        self._error_text = ""
        self._result_model.replace_rows(result.rows)
        self._report_path = result.report_path
        mode = self._worker_modes.get(request_id, "")
        self._last_completed_mode = mode
        if mode == "preview":
            self._has_preview = True
            self._status_text = result.warning_text or "預覽完成"
            self._summary_text = f"{result.summary_text}。下一步：確認分類結果，無誤後按「複製並刪除記憶卡中資料」。"
        else:
            self._has_preview = False
            self._status_text = result.warning_text or "複製與驗證完成"
            self._summary_text = result.summary_text
        self.stateChanged.emit()
        self.runSucceeded.emit(result.summary_text)

    @Slot(int, str)
    def _failed(self, request_id: int, message: str) -> None:
        if request_id == self._request_id:
            self._is_ready = False
            self._has_preview = False
            self._awaiting_confirmation = False
            self._preview_after_check = False
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
            self._poll_worker_thread_finished(request_id)
            return
        self._finalize_worker_thread(request_id)

    def _poll_worker_thread_finished(self, request_id: int) -> None:
        worker_pair = self._workers.get(request_id)
        if worker_pair is None:
            return
        thread, _worker = worker_pair
        if not thread.isFinished():
            QTimer.singleShot(50, lambda: self._poll_worker_thread_finished(request_id))
            return
        self._finalize_worker_thread(request_id)

    def _finalize_worker_thread(self, request_id: int) -> None:
        worker_pair = self._workers.pop(request_id, None)
        if worker_pair is None:
            return
        thread, _worker = worker_pair
        mode = self._worker_modes.pop(request_id, "")
        thread.deleteLater()
        if (
            not self._shutting_down
            and mode == ""
            and self._preview_after_check
            and self._is_ready
        ):
            self._preview_after_check = False
            request = self._request(
                self._source_path,
                self._destination_path,
                self._target_date,
                self._selected_vehicle,
                self._offset_text,
                self._repair_mismatch,
                "preview",
            )
            if request is not None:
                self._start_worker("execute", request)
                return
        self.stateChanged.emit()

    @Slot()
    def prepare_shutdown_admission(self) -> None:
        self._shutting_down = True

    @Slot()
    def shutdown(self) -> None:
        self.prepare_shutdown_admission()
        for request_id, (thread, _worker) in tuple(self._workers.items()):
            thread.requestInterruption()
            thread.quit()
            if not thread.wait(120_000):
                thread.wait()
            self._finalize_worker_thread(request_id)

    def _set_error(self, message: str) -> None:
        self._status_text = message
        self._error_text = message
        self.stateChanged.emit()
        self.errorOccurred.emit(message)
