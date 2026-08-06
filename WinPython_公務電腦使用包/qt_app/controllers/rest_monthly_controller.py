# -*- coding: utf-8 -*-
"""QML-facing state and confirmation flow for rest and monthly tools."""

from __future__ import annotations

from PySide6.QtCore import QObject, Property, QThread, QUrl, Signal, Slot

from app_core.rest_monthly_service import (
    MonthlyBaseRequest,
    RestMonthlyService,
    RestMonthlyValidationError,
    RestTimeRequest,
)
from app_core.session import SessionState
from qt_app.workers.rest_monthly_worker import RestMonthlyWorker


class RestMonthlyController(QObject):
    stateChanged = Signal()
    confirmationRequested = Signal(str)
    runStarted = Signal(str)
    runSucceeded = Signal(str, str)
    runFailed = Signal(str, str)
    errorOccurred = Signal(str)

    def __init__(
        self,
        session_state: SessionState,
        service: RestMonthlyService,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._session_state = session_state
        self._service = service
        self._rest_workbook_path = ""
        self._roc_year = 0
        self._month_options: list[str] = []
        self._rest_month = ""
        self._monthly_month = ""
        self._status_text = "尚未載入設定"
        self._confirmation_summary = ""
        self._pending_request: RestTimeRequest | MonthlyBaseRequest | None = None
        self._pending_tool_id = ""
        self._request_id = 0
        self._failure_stage = "unknown"
        self._failure_detail = ""
        self._workers: dict[int, tuple[QThread, RestMonthlyWorker]] = {}

    @Property(str, notify=stateChanged)
    def restWorkbookPath(self) -> str:
        return self._rest_workbook_path

    @Property(int, notify=stateChanged)
    def rocYear(self) -> int:
        return self._roc_year

    @Property("QVariantList", notify=stateChanged)
    def monthOptions(self) -> list[str]:
        return self._month_options

    @Property(str, notify=stateChanged)
    def restMonth(self) -> str:
        return self._rest_month

    @Property(str, notify=stateChanged)
    def monthlyMonth(self) -> str:
        return self._monthly_month

    @Property(str, notify=stateChanged)
    def statusText(self) -> str:
        return self._status_text

    @Property(str, notify=stateChanged)
    def confirmationSummary(self) -> str:
        return self._confirmation_summary

    @Property(str, notify=stateChanged)
    def failureStage(self) -> str:
        return self._failure_stage

    @Property(str, notify=stateChanged)
    def failureDetail(self) -> str:
        return self._failure_detail

    @Property(bool, notify=stateChanged)
    def isRunning(self) -> bool:
        return bool(self._workers)

    @Slot()
    def loadRestDefaults(self) -> None:
        defaults = self._service.load_rest_defaults()
        self._rest_workbook_path = defaults.workbook_path
        self._roc_year = defaults.roc_year
        self._month_options = list(defaults.month_options)
        self._rest_month = defaults.selected_month
        self._status_text = self._ready_status()
        self.stateChanged.emit()

    @Slot()
    def loadMonthlyDefaults(self) -> None:
        defaults = self._service.load_monthly_defaults()
        self._roc_year = defaults.roc_year
        self._month_options = list(defaults.month_options)
        self._monthly_month = defaults.selected_month
        self._status_text = self._ready_status()
        self.stateChanged.emit()

    @Slot(QUrl, result=str)
    def localPath(self, url: QUrl) -> str:
        return url.toLocalFile() if url.isLocalFile() else ""

    @Slot(QUrl)
    def selectRestWorkbook(self, url: QUrl) -> None:
        path = self.localPath(url)
        try:
            defaults = self._service.select_rest_workbook(path)
        except (RestMonthlyValidationError, OSError, ValueError) as exc:
            self._set_error(str(exc) or "請選擇有效的勤務表 Excel 檔案。")
            return
        self._rest_workbook_path = defaults.workbook_path
        self._roc_year = defaults.roc_year
        self._month_options = list(defaults.month_options)
        self._rest_month = defaults.selected_month
        self._status_text = "已選擇勤務表 Excel。"
        self.stateChanged.emit()

    @Slot(str, str)
    def prepareRestRun(self, workbook_path: str, month: str) -> None:
        session = self._verified_session()
        if session is None:
            return
        try:
            request = self._service.validate_rest(
                RestTimeRequest(
                    session.user_id,
                    session.password,
                    session.actor_no,
                    workbook_path,
                    self._roc_year,
                    int(month),
                    session.actor_name,
                )
            )
        except (RestMonthlyValidationError, ValueError) as exc:
            self._set_error(str(exc) or "請選擇正確的月份。")
            return
        self._rest_month = f"{request.month:02d}"
        self._prepare_confirmation("rest_time", request)

    @Slot(str)
    def prepareMonthlyRun(self, month: str) -> None:
        session = self._verified_session()
        if session is None:
            return
        try:
            request = self._service.validate_monthly(
                MonthlyBaseRequest(
                    session.user_id,
                    session.password,
                    session.actor_no,
                    self._roc_year,
                    int(month),
                    session.actor_name,
                )
            )
        except (RestMonthlyValidationError, ValueError) as exc:
            self._set_error(str(exc) or "請選擇正確的月份。")
            return
        self._monthly_month = f"{request.month:02d}"
        self._prepare_confirmation("monthly_base", request)

    @Slot()
    def confirmRun(self) -> None:
        if self._pending_request is None or not self._pending_tool_id or self._workers:
            return
        self._request_id += 1
        request_id = self._request_id
        self._failure_stage = "unknown"
        self._failure_detail = ""
        request = self._pending_request
        tool_id = self._pending_tool_id
        self._pending_request = None
        self._pending_tool_id = ""
        self._confirmation_summary = ""
        self._status_text = "正在執行登打…"
        worker = RestMonthlyWorker(request_id, tool_id, self._service, request)
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
        self.runStarted.emit(tool_id)
        thread.start()

    @Slot()
    def cancelPendingRun(self) -> None:
        self._pending_request = None
        self._pending_tool_id = ""
        self._confirmation_summary = ""
        self._status_text = "已取消登打。"
        self.stateChanged.emit()

    def _verified_session(self):
        session = self._session_state.session
        if session is None or not session.verified:
            self._set_error("請先完成勤務系統登入。")
            return None
        if not str(session.actor_name or "").strip():
            self._set_error("登入資料缺少人員姓名，無法確認登打對象。")
            return None
        return session

    def _ready_status(self) -> str:
        session = self._session_state.session
        if session is None:
            return "準備就緒。"
        actor_no = str(session.actor_no or "").strip()
        actor_name = str(session.actor_name or "").strip()
        if actor_name:
            display_name = f"{actor_no}番 {actor_name}" if actor_no else actor_name
        else:
            display_name = actor_no or str(session.user_id or "").strip()
        return f"準備就緒。{display_name}"

    def _prepare_confirmation(
        self,
        tool_id: str,
        request: RestTimeRequest | MonthlyBaseRequest,
    ) -> None:
        self._pending_request = request
        self._pending_tool_id = tool_id
        self._confirmation_summary = self._service.confirmation_summary(request)
        self._status_text = "等待使用者確認正式登打。"
        self.stateChanged.emit()
        self.confirmationRequested.emit(tool_id)

    @Slot(int, str, str)
    def _progress(self, request_id: int, _tool_id: str, message: str) -> None:
        if request_id == self._request_id:
            self._status_text = message
            self.stateChanged.emit()

    @Slot(int, str, str)
    def _succeeded(self, request_id: int, tool_id: str, message: str) -> None:
        if request_id != self._request_id:
            return
        self._status_text = message
        self.stateChanged.emit()
        self.runSucceeded.emit(tool_id, message)

    @Slot(int, str, str)
    def _failed(self, request_id: int, tool_id: str, message: str) -> None:
        if request_id == self._request_id:
            worker_pair = self._workers.get(request_id)
            worker = worker_pair[1] if worker_pair is not None else None
            self._failure_stage = str(getattr(worker, "failure_stage", "unknown") or "unknown")
            self._failure_detail = str(getattr(worker, "failure_detail", "") or "")
            self.runFailed.emit(tool_id, message)
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
