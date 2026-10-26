# -*- coding: utf-8 -*-
"""QML-facing state and confirmation flow for rescue-video classification."""

from __future__ import annotations

import time
from datetime import date, timedelta
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


MAX_NAS_CLASSIFICATION_ROWS = 200


class RescueVideoController(QObject):
    stateChanged = Signal()
    copyConfirmationRequested = Signal()
    deleteConfirmationRequested = Signal()
    preflightStarted = Signal()
    preflightSucceeded = Signal(str)
    preflightFailed = Signal(str)
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
        read_only_acceptance: bool = False,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._session_state = session_state
        self._source_path = ""
        self._destination_path = ""
        self._target_date = ""
        self._vehicle_options: list[str] = []
        self._selected_vehicle = ""
        self._source_identity = ""
        self._available_dates: list[str] = []
        self._source_hint = ""
        self._can_preview = False
        self._preflight_details: dict[str, object] = {}
        self._preview_counts: dict[str, int] = {}
        self._offset_text = ""
        self._repair_mismatch = False
        self._check_text = "插入單張記憶卡，再按「讀取記憶卡」。"
        self._check_cards: list[dict[str, str]] = []
        self._is_ready = False
        self._has_preview = False
        self._awaiting_confirmation = False
        self._check_requested = False
        self._preview_after_check = False
        self._status_text = "尚未開始"
        self._summary_text = "插入單張記憶卡，再按「讀取記憶卡」。"
        self._error_text = ""
        self._report_path = ""
        self._confirmation_summary = ""
        self._pending_request: RescueVideoRequest | None = None
        self._request_id = 0
        self._failure_stage = "unknown"
        self._workers: dict[int, tuple[QThread, RescueVideoWorker]] = {}
        self._worker_modes: dict[int, str] = {}
        self._run_started_at: dict[int, float] = {}
        self._shutting_down = False
        self._last_completed_mode = ""
        self._last_completed_run_details: dict[str, object] = {}
        self._result_model = RescueVideoResultModel(self)
        self._read_only_acceptance = bool(read_only_acceptance)

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

    @Property(bool, notify=stateChanged)
    def canPreview(self) -> bool:
        return self._can_preview

    @Property(str, notify=stateChanged)
    def sourceHint(self) -> str:
        return self._source_hint

    @Property("QVariantList", notify=stateChanged)
    def availableDates(self) -> list[str]:
        return self._available_dates

    @Property(str, notify=stateChanged)
    def todayDate(self) -> str:
        return date.today().strftime("%Y-%m-%d")

    @Property(str, notify=stateChanged)
    def yesterdayDate(self) -> str:
        return (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")

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

    def completed_run_details(self) -> dict[str, object]:
        return dict(self._last_completed_run_details)

    def completed_preflight_details(self) -> dict[str, object]:
        return dict(self._preflight_details)

    def _remember_selection(self) -> None:
        remember = getattr(self._service, "remember_selection", None)
        if callable(remember):
            remember(self._source_identity, self._target_date, self._selected_vehicle)

    @Slot()
    def resetForNextSession(self) -> None:
        if self._workers:
            return
        self._remember_selection()
        self._source_path = ""
        self._destination_path = ""
        self._target_date = ""
        self._vehicle_options = []
        self._selected_vehicle = ""
        self._source_identity = ""
        self._available_dates = []
        self._source_hint = ""
        self._can_preview = False
        self._preflight_details = {}
        self._preview_counts = {}
        self._offset_text = ""
        self._repair_mismatch = False
        self._check_text = "插入單張記憶卡，再按「讀取記憶卡」。"
        self._check_cards = []
        self._is_ready = False
        self._has_preview = False
        self._awaiting_confirmation = False
        self._check_requested = False
        self._preview_after_check = False
        self._status_text = "尚未開始"
        self._summary_text = "插入單張記憶卡，再按「讀取記憶卡」。"
        self._error_text = ""
        self._report_path = ""
        self._confirmation_summary = ""
        self._pending_request = None
        self._failure_stage = "unknown"
        self._last_completed_mode = ""
        self._last_completed_run_details = {}
        self._result_model.replace_rows(())
        self.stateChanged.emit()

    @Slot()
    def loadDefaults(self) -> None:
        if self._reject_read_only_execution():
            return
        if self._shutting_down or self._workers:
            return
        self._is_ready = False
        self._can_preview = False
        self._has_preview = False
        self._awaiting_confirmation = False
        self._check_requested = False
        self._preview_after_check = False
        self._status_text = "讀取記憶卡"
        self._check_text = "讀取記憶卡與案件資料。"
        self._error_text = ""
        self._set_check_cards_pending(initial=True)
        self.stateChanged.emit()
        self._start_worker("defaults")

    @Slot(str, str, str)
    def refreshAutomaticState(self, source_path: str, target_date: str, vehicle: str) -> None:
        if self._reject_read_only_execution():
            return
        self._begin_check(source_path, target_date, vehicle, preview_after_check=False)

    @Slot(str, str, str)
    def checkAndPreview(self, source_path: str, target_date: str, vehicle: str) -> None:
        if self._reject_read_only_execution():
            return
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
        self._can_preview = False
        self._has_preview = False
        self._awaiting_confirmation = False
        self._check_requested = True
        self._preview_after_check = preview_after_check
        self._status_text = "讀取中"
        self._error_text = ""
        self._summary_text = "確認資料後預覽。" if preview_after_check else "讀取中。"
        self._result_model.replace_rows(())
        self.stateChanged.emit()
        self._start_worker(
            "defaults",
            defaults_source=source_path,
            defaults_date=target_date,
            defaults_vehicle=vehicle,
        )

    @Slot(str, str)
    def refreshVehicleOptions(self, source_path: str, target_date: str) -> None:
        if self._reject_read_only_execution():
            return
        if self._shutting_down or self._workers or self._awaiting_confirmation:
            return
        self._source_path = source_path
        self._target_date = target_date
        self._selected_vehicle = ""
        self._is_ready = False
        self._can_preview = False
        self._has_preview = False
        self._check_requested = False
        self._preview_after_check = False
        self._status_text = "讀取車號"
        self._check_text = "讀取這個日期的案件。"
        self._summary_text = "讀取這個日期的車號。"
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
        if self._reject_read_only_execution():
            return
        if self._workers or self._awaiting_confirmation:
            return
        source_changed = source_path != self._source_path
        if source_changed:
            self._remember_selection()
            self._source_identity = ""
        self._source_path = source_path
        self._target_date = target_date
        self._selected_vehicle = "" if source_changed else vehicle
        self._is_ready = False
        self._has_preview = False
        self._check_requested = False
        self._preview_after_check = False
        self._can_preview = (
            not source_changed and vehicle in self._vehicle_options
            and all(card.get("level") != "error" for card in self._check_cards if card.get("key") != "vehicle_date")
        )
        self._status_text = "可以預覽" if self._can_preview else "請補齊資料"
        self._check_text = "條件已更新。"
        self._summary_text = "按「預覽」。" if self._can_preview else "請確認記憶卡、日期與車號。"
        self._error_text = ""
        for card in self._check_cards:
            if card.get("key") == "vehicle_date":
                card.update(level="ok" if self._can_preview else "error",
                    detail=f"{target_date}｜車號 {vehicle}" if self._can_preview else "請選車號。")
        self._result_model.replace_rows(())
        if not source_changed:
            self._remember_selection()
        self.stateChanged.emit()
        if source_changed:
            self._can_preview = False
            self._start_worker("defaults", defaults_source=source_path)

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
        if self._reject_read_only_execution():
            return
        if self._shutting_down:
            return
        if not self._is_ready or self._awaiting_confirmation:
            self._set_error("請先讀取記憶卡並選車號。")
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
        if self._reject_read_only_execution():
            return
        if not self._is_ready or not self._has_preview or self._awaiting_confirmation:
            self._set_error("請先完成預覽。")
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
        if self._prepare_confirmation(request, "等待確認備份"):
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
        if self._reject_read_only_execution():
            return
        if not self._is_ready or not self._has_preview or self._awaiting_confirmation:
            self._set_error("請先完成預覽。")
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
        if self._prepare_confirmation(
            request,
            "等待確認備份後清理",
        ):
            self.deleteConfirmationRequested.emit()

    @Slot()
    def confirmCopy(self) -> None:
        self._confirm_pending()

    @Slot()
    def cancelCopy(self) -> None:
        self._pending_request = None
        self._confirmation_summary = ""
        self._awaiting_confirmation = False
        self._status_text = "預覽完成" if self._has_preview else "請補齊資料"
        self.stateChanged.emit()

    @Slot()
    def confirmDelete(self) -> None:
        self._confirm_pending()

    def _confirm_pending(self) -> None:
        if self._reject_read_only_execution():
            return
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
        self._status_text = "預覽完成" if self._has_preview else "請補齊資料"
        self.stateChanged.emit()

    def _reject_read_only_execution(self) -> bool:
        if not self._read_only_acceptance:
            return False
        self._pending_request = None
        self._confirmation_summary = ""
        self._awaiting_confirmation = False
        self._status_text = "唯讀驗收模式，不執行分類、複製或刪除。"
        self.stateChanged.emit()
        return True

    def _prepare_confirmation(self, request: RescueVideoRequest, status_text: str) -> bool:
        try:
            summary = self._service.confirmation_summary(request)
        except RescueVideoValidationError as exc:
            self._set_error(str(exc))
            return False
        self._pending_request = request
        counts = self._preview_counts
        count_text = (
            f"\n可備份 {counts.get('ready_count', 0)} 段；待確認 {counts.get('pending_count', 0)} 段；失敗 {counts.get('failed_count', 0)} 段。"
            if counts else ""
        )
        self._confirmation_summary = summary + count_text
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
            source_identity=self._source_identity,
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
            expected_source_identity=self._source_identity,
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
            self._run_started_at[request_id] = time.monotonic()
        if mode:
            self._status_text = "預覽中，請勿拔卡" if mode == "preview" else "備份中，請勿拔卡"
        self.stateChanged.emit()
        if mode:
            self.runStarted.emit(mode)
        else:
            self.preflightStarted.emit()
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
        self._source_identity = defaults.source_identity
        self._available_dates = list(defaults.available_dates)
        self._source_hint = defaults.source_hint
        self._offset_text = defaults.offset_text
        self._repair_mismatch = defaults.repair_mismatch
        self._check_text = defaults.check_text
        check_cards = [
            {
                "key": card.key,
                "title": card.title,
                "detail": card.detail,
                "level": card.level,
                "code": card.code,
            }
            for card in defaults.check_cards
        ]
        self._check_cards = check_cards
        self._can_preview = defaults.is_ready
        self._is_ready = self._check_requested and defaults.is_ready
        self._has_preview = False
        self._awaiting_confirmation = False
        if self._is_ready:
            if self._preview_after_check:
                self._status_text = "準備預覽"
                self._summary_text = "讀取影片中。"
            else:
                self._status_text = "可以預覽"
                self._summary_text = "按「預覽」。"
        elif not self._can_preview:
            self._preview_after_check = False
            self._status_text = "請補齊資料"
            self._summary_text = next(
                (card.detail for card in defaults.check_cards if card.level == "error"),
                "請確認記憶卡、日期與車號。",
            )
        else:
            self._status_text = "已讀取"
            self._summary_text = "按「預覽」。"
        self._preflight_details = {
            "rescue_video_state": "needs_input" if not self._can_preview else "checked" if self._check_requested else "loaded",
            "target_date": self._target_date,
            "vehicle": self._selected_vehicle,
            "preflight_checks": [
                {"key": card.key, "label": card.title, "level": card.level, "code": card.code, "detail": card.detail}
                for card in defaults.check_cards[:6]
            ],
        }
        self.stateChanged.emit()
        if self._check_requested and not self._is_ready:
            self._failure_stage = "preflight"
            self.preflightFailed.emit(self._summary_text)
        else:
            self.preflightSucceeded.emit(self._summary_text if not self._can_preview else "可以預覽" if self._check_requested else "已讀取")

    def _set_check_cards_pending(
        self,
        cards: list[dict[str, str]] | None = None,
        *,
        initial: bool = False,
    ) -> None:
        current_cards = self._check_cards if cards is None else cards
        initial_details = {
            "source": "讀取記憶卡。",
            "destination": "檢查備份位置。",
            "work_log": "讀取工作／返隊紀錄。",
            "vehicle_date": "讀取當日車號。",
            "report": "檢查報告位置。",
            "videos": "尋找 TS 影片。",
        }
        state_text = "讀取中"
        self._check_cards = [
            {
                "key": card["key"],
                "title": card["title"],
                "detail": initial_details.get(
                    card["key"],
                    "讀取中。",
                )
                if initial
                else "讀取更新資料。",
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
        self._last_completed_run_details = self._build_completed_run_details(request_id, result)
        counts = self._result_counts(result.rows)
        pending = counts["pending_count"]
        failed = counts["failed_count"]
        if mode == "preview":
            self._preview_counts = counts
            self._has_preview = True
            self._is_ready = self._is_ready and counts["ready_count"] > 0
            self._status_text = "預覽完成"
            self._summary_text = (
                f"可備份 {counts['ready_count']} 段；待確認 {pending} 段；失敗 {failed} 段。"
            )
        else:
            self._has_preview = False
            self._is_ready = False
            self._status_text = "部分完成" if pending or failed else "備份完成"
            self._summary_text = f"已備份 {counts['ready_count']} 段；待確認 {pending} 段；失敗 {failed} 段。"
            if pending or failed:
                self._summary_text += " 未完成的影片保留在卡內。"
        self.stateChanged.emit()
        self.runSucceeded.emit(self._summary_text)

    def _build_completed_run_details(
        self,
        request_id: int,
        result: RescueVideoRunResult,
    ) -> dict[str, object]:
        started_at = self._run_started_at.pop(request_id, None)
        usage_seconds = (
            max(0, round(time.monotonic() - started_at))
            if started_at is not None
            else 0
        )
        case_names = {
            str(row.get("caseText") or "").strip()
            for row in result.rows
            if str(row.get("caseText") or "").strip() not in {"", "待確認"}
        }
        classification_rows = [
            self._nas_classification_row(row)
            for row in result.rows[:MAX_NAS_CLASSIFICATION_ROWS]
        ]
        counts = self._result_counts(result.rows)
        return {
            "target_date": self._target_date,
            "vehicle": self._selected_vehicle,
            "mode": self._worker_modes.get(request_id, ""),
            "case_count": len(case_names),
            "total_count": len(result.rows),
            "usage_seconds": usage_seconds,
            "classification_rows": classification_rows,
            **counts,
            "rescue_video_state": (
                "previewed" if self._worker_modes.get(request_id) == "preview"
                else "partial" if counts["pending_count"] or counts["failed_count"] else "backed_up"
            ),
        }

    @staticmethod
    def _result_counts(rows) -> dict[str, int]:
        pending = 0
        failed = 0
        for row in rows:
            status = str(row.get("statusText") or "")
            if status in {"無法讀取", "目的地不一致", "錯誤"} or "失敗" in status or "錯誤" in status:
                failed += 1
            elif status == "待確認" or row.get("caseText") == "待確認":
                pending += 1
        return {"ready_count": max(0, len(rows) - pending - failed), "pending_count": pending, "failed_count": failed}

    @staticmethod
    def _nas_classification_row(row: dict[str, object]) -> dict[str, str]:
        source_file = Path(str(row.get("sourcePath") or row.get("sourceText") or "")).name
        case_text = str(row.get("caseText") or "待確認").strip() or "待確認"
        status_text = str(row.get("statusText") or "").strip()
        note_text = str(row.get("noteText") or "").strip()
        reason = ""
        if "沒有符合工作／返隊時間的案件" in note_text:
            reason = "no_matching_work_or_return_time"
        elif status_text == "目的地不一致":
            reason = "destination_mismatch"
        elif status_text == "無法讀取":
            reason = "source_unreadable"
        elif "錯誤" in status_text or "失敗" in status_text:
            reason = "classification_error"
        return {
            "video_time": str(row.get("timeText") or "").strip()[:40],
            "source_file": source_file[:160],
            "case": case_text[:160],
            "status": status_text[:80],
            "reason": reason,
        }

    @Slot(int, str)
    def _failed(self, request_id: int, message: str) -> None:
        if request_id == self._request_id:
            self._is_ready = False
            self._can_preview = False
            self._has_preview = False
            self._awaiting_confirmation = False
            self._preview_after_check = False
            worker_pair = self._workers.get(request_id)
            worker = worker_pair[1] if worker_pair is not None else None
            self._failure_stage = str(getattr(worker, "failure_stage", "unknown") or "unknown")
            self._preflight_details = {**self._preflight_details, "rescue_video_state": "failed"}
            self._run_started_at.pop(request_id, None)
            mode = self._worker_modes.get(request_id, "")
            if mode:
                self.runFailed.emit(mode, message)
            else:
                self.preflightFailed.emit(message)
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
        self._run_started_at.pop(request_id, None)
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
