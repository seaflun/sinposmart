# -*- coding: utf-8 -*-
"""Single QML context facade for the first Qt migration slice."""

from __future__ import annotations

import json
import re
from collections import deque
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QObject, Property, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication

from app_core.credential_repository import CredentialRepository
from app_core.credential_sync_service import CredentialSyncService
from app_core.daily_vehicle_service import DailyVehicleService
from app_core.diagnostics_service import DiagnosticExportError, DiagnosticsService, DiagnosticSnapshot
from app_core.duty_sheet_service import DutySheetService
from app_core.duty_submission_service import DutySubmissionRequest, DutySubmissionResult, DutySubmissionService
from app_core.duty_task_projection import (
    action_completion_key,
    action_summary,
    compact_action_snapshot,
    target_short_label,
)
from app_core.login_verifier import LoginVerifier
from app_core.operational_sync_service import OperationalSyncService
from app_core.rescue_video_service import RescueVideoService
from app_core.rest_monthly_service import RestMonthlyService
from app_core.schedule_repository import ScheduleRepository
from app_core.schedule_repository import business_roc_date
from app_core.schedule_capture_service import ScheduleCaptureRequest, ScheduleCaptureService
from app_core.scheduled_folder_service import ScheduledFolderService
from app_core.session import SessionState
from app_core.update_repository import UpdateRepository
from app_core.work_log_settings_service import WorkLogSettingsService
from qt_app.controllers.duty_controller import DutyController
from qt_app.controllers.daily_vehicle_controller import DailyVehicleController
from qt_app.controllers.duty_sheet_controller import DutySheetController
from qt_app.controllers.duty_execution_controller import DutyExecutionController
from qt_app.controllers.rest_monthly_controller import RestMonthlyController
from qt_app.controllers.rescue_video_controller import RescueVideoController
from qt_app.controllers.session_controller import SessionController
from qt_app.controllers.tool_controller import ToolController
from qt_app.controllers.tray_controller import TrayController
from qt_app.controllers.update_controller import UpdateController
from qt_app.controllers.work_log_settings_controller import WorkLogSettingsController
from qt_app.workers.operational_sync_worker import OperationalSyncWorker
from qt_app.workers.schedule_capture_worker import ScheduleCaptureWorker
from qt_app.workers.scheduled_folder_worker import ScheduledFolderWorker


class AppController(QObject):
    diagnosticsChanged = Signal()
    diagnosticsStatusRequested = Signal(str)
    nativeTitleBarRequested = Signal(QObject)
    dutyActionFailed = Signal(str, str)
    dutyActionRecovered = Signal(str)

    def __init__(
        self,
        *,
        repository: CredentialRepository | None = None,
        verifier: LoginVerifier | None = None,
        credential_sync_service: CredentialSyncService | None = None,
        schedule_repository: ScheduleRepository | None = None,
        tool_controller: ToolController | None = None,
        tray_controller: TrayController | None = None,
        update_repository: UpdateRepository | None = None,
        duty_sheet_service: DutySheetService | None = None,
        rest_monthly_service: RestMonthlyService | None = None,
        daily_vehicle_service: DailyVehicleService | None = None,
        rescue_video_service: RescueVideoService | None = None,
        diagnostics_service: DiagnosticsService | None = None,
        operational_sync_service: OperationalSyncService | None = None,
        duty_submission_service: DutySubmissionService | None = None,
        schedule_capture_service: ScheduleCaptureService | None = None,
        work_log_settings_service: WorkLogSettingsService | None = None,
        scheduled_folder_service: ScheduledFolderService | None = None,
        read_only_acceptance: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._read_only_acceptance = bool(read_only_acceptance)
        self._session_state = SessionState()
        self._session_controller = SessionController(
            self._session_state,
            repository=repository,
            verifier=verifier,
            credential_sync_service=credential_sync_service,
            parent=self,
        )
        package_root = Path(__file__).resolve().parents[2]
        self._diagnostics_service = diagnostics_service or DiagnosticsService(package_root)
        self._diagnostics_status = ""
        self._operational_sync_service = operational_sync_service or OperationalSyncService(package_root)
        self._operational_sync_request_id = 0
        self._operational_sync_workers: dict[int, tuple[QThread, OperationalSyncWorker]] = {}
        self._operational_sync_queue: deque[tuple[int, str, str, dict, dict]] = deque()
        self._operational_sync_shutting_down = False
        self._active_tool_runs: dict[str, tuple[str, str]] = {}
        self._shutdown_terminal_tool_runs: set[str] = set()
        self._schedule_capture_service = schedule_capture_service or ScheduleCaptureService(package_root)
        self._duty_controller = DutyController(
            self,
            repository=schedule_repository,
            capture_service=self._schedule_capture_service,
        )
        self._tool_controller = tool_controller or ToolController(package_root, parent=self)
        if self._tool_controller.parent() is None:
            self._tool_controller.setParent(self)
        self._tray_controller = tray_controller or TrayController(
            QApplication.instance(),
            parent=self,
        )
        if self._tray_controller.parent() is None:
            self._tray_controller.setParent(self)
        self._update_controller = UpdateController(
            update_repository or UpdateRepository(package_root / "VERSION.txt"),
            parent=self,
        )
        self._duty_sheet_controller = DutySheetController(
            self._session_state,
            duty_sheet_service or DutySheetService(package_root),
            self,
        )
        self._rest_monthly_controller = RestMonthlyController(
            self._session_state,
            rest_monthly_service or RestMonthlyService(package_root),
            self,
        )
        self._daily_vehicle_controller = DailyVehicleController(
            self._session_state,
            daily_vehicle_service or DailyVehicleService(package_root),
            self,
        )
        self._rescue_video_controller = RescueVideoController(
            rescue_video_service or RescueVideoService(package_root),
            self,
            session_state=self._session_state,
        )
        self._duty_execution_controller = DutyExecutionController(
            duty_submission_service or DutySubmissionService(package_root),
            self,
        )
        self._work_log_settings_controller = WorkLogSettingsController(
            work_log_settings_service or WorkLogSettingsService(),
            self,
        )
        self._scheduled_folder_service = scheduled_folder_service
        self._scheduled_folder_timer: QTimer | None = None
        self._scheduled_folder_request_id = 0
        self._scheduled_folder_workers: dict[int, tuple[QThread, ScheduledFolderWorker]] = {}
        if self._scheduled_folder_service is not None:
            self._scheduled_folder_timer = QTimer(self)
            self._scheduled_folder_timer.setInterval(1_000)
            self._scheduled_folder_timer.timeout.connect(self._check_scheduled_folders)
            self._scheduled_folder_timer.start()
        self._synced_actor_no = ""
        self._synced_user_id = ""
        self._synced_session_generation = -1
        self._last_login_actor_no = ""
        self._last_login_user_id = ""
        self._last_login_display_name = ""
        self._provisional_actor_no = ""
        self._actor_identity_pending = False
        self._logout_pending = False
        self._pending_logout_message = ""
        self._update_shutdown_prepared = False
        self._worker_admissions_closed = False
        self._allow_shutdown_operational_sync = False
        self._pending_live_refresh_generation: int | None = None
        self._pending_fire_day_refresh = ""
        self._operational_staff: dict[str, dict] = {}
        self._last_hourly_refresh_key = ""
        self._last_schedule_snapshot_signature = ""
        self._duty_mode_active = True
        self._hourly_refresh_timer = QTimer(self)
        self._hourly_refresh_timer.setInterval(60_000)
        self._hourly_refresh_timer.timeout.connect(self._refresh_hourly_live_schedule)
        self._hourly_refresh_timer.start()
        self._board_retry_timer = QTimer(self)
        self._board_retry_timer.setInterval(60_000)
        self._board_retry_timer.timeout.connect(self._retry_current_duty_board)
        self._board_retry_timer.start()
        self._tomorrow_schedule_request_id = 0
        self._tomorrow_schedule_workers: dict[int, tuple[QThread, ScheduleCaptureWorker]] = {}
        self._tomorrow_schedule_contexts: dict[int, tuple[int, str, str, str]] = {}
        self._tomorrow_schedule_timer = QTimer(self)
        self._tomorrow_schedule_timer.setInterval(30_000)
        self._tomorrow_schedule_timer.timeout.connect(self._capture_evening_tomorrow_schedule)
        self._tomorrow_schedule_timer.start()
        QTimer.singleShot(15_000, self._capture_evening_tomorrow_schedule)
        self._session_controller.sessionChanged.connect(self._sync_session_actor)
        self._session_controller.loginAttemptFailed.connect(self._login_attempt_failed)
        self._duty_controller.liveScheduleCaptured.connect(self._live_schedule_captured)
        self._duty_controller.liveSnapshotCaptured.connect(self._live_snapshot_captured)
        self._duty_controller.liveCaptureFailed.connect(self._live_capture_failed)
        self._duty_controller.cachedScheduleLoaded.connect(self._cached_schedule_loaded)
        self._duty_controller.fireDayChanged.connect(self._refresh_after_fire_day_change)
        self._duty_controller.fireDayChanged.connect(self._tool_controller.refreshDailyCompletion)
        self._duty_controller.dueTasksAvailable.connect(self._enqueue_due_tasks)
        self._duty_controller.handoffPrewarmRequested.connect(self._prewarm_handoff_entry_browser)
        self._duty_controller.autoLogoutRequested.connect(self._auto_logout)
        self._duty_controller.reloginRequired.connect(self._force_logout)
        self._duty_controller.manualSubmissionRequested.connect(self._enqueue_manual_tasks)
        self._duty_controller.externalReturnQueueManualSubmissionRequested.connect(
            self._enqueue_queued_external_return_manual_submission
        )
        self._duty_controller.externalReturnRecoveryDue.connect(
            self._enqueue_external_return_recovery
        )
        self._duty_controller.unreturnedReturnEvent.connect(self._publish_unreturned_return_event)
        self._duty_controller.scheduleChanged.connect(self._retry_pending_live_refresh)
        self._work_log_settings_controller.settingsSaved.connect(self._refresh_after_settings_save)
        self._duty_execution_controller.allLanesUnavailable.connect(self._handle_execution_unavailable)
        self._duty_sheet_controller.runStarted.connect(
            lambda: self._tool_run_started("duty_sheet", "勤務表登打")
        )
        self._duty_sheet_controller.runSucceeded.connect(
            lambda message: self._tool_run_finished("duty_sheet", "勤務表登打", message)
        )
        self._duty_sheet_controller.runFailed.connect(
            lambda message: self._tool_run_failed("duty_sheet", "勤務表登打", message)
        )
        self._rest_monthly_controller.runStarted.connect(
            lambda tool_id: self._tool_run_started(tool_id, self._tool_label(tool_id))
        )
        self._rest_monthly_controller.runSucceeded.connect(
            lambda tool_id, message: self._tool_run_finished(tool_id, self._tool_label(tool_id), message)
        )
        self._rest_monthly_controller.runFailed.connect(
            lambda tool_id, message: self._tool_run_failed(tool_id, self._tool_label(tool_id), message)
        )
        self._daily_vehicle_controller.runStarted.connect(
            lambda: self._tool_run_started("daily_vehicle", "車輛保養清點")
        )
        self._daily_vehicle_controller.runSucceeded.connect(
            lambda message: self._tool_run_finished("daily_vehicle", "車輛保養清點", message)
        )
        self._daily_vehicle_controller.runFailed.connect(
            lambda message: self._tool_run_failed("daily_vehicle", "車輛保養清點", message)
        )
        self._rescue_video_controller.runStarted.connect(
            lambda mode: self._tool_run_started("rescue_video", "救護行車紀錄器", mode=mode)
        )
        self._rescue_video_controller.runSucceeded.connect(
            lambda message: self._tool_run_finished(
                "rescue_video",
                "救護行車紀錄器",
                message,
                notify=self._rescue_video_controller.lastCompletedMode in {"copy", "delete"},
            )
        )
        self._rescue_video_controller.runFailed.connect(
            lambda mode, message: self._tool_run_failed(
                "rescue_video",
                "救護行車紀錄器",
                message,
                mode=mode,
                notify=False,
            )
        )
        self._duty_execution_controller.submissionQueued.connect(self._submission_queued)
        self._duty_execution_controller.submissionStarted.connect(self._submission_started)
        self._duty_execution_controller.submissionFinished.connect(self._submission_finished)
        self._duty_execution_controller.submissionFailed.connect(self._submission_failed)
        self._duty_execution_controller.submissionCancelled.connect(self._submission_cancelled)
        self._duty_execution_controller.stateChanged.connect(self._finish_pending_logout)
        self._tray_controller.setStopGuard(self._stop_block_reason)
        self._update_controller.setStopGuard(self._stop_block_reason)

    @Property(QObject, constant=True)
    def sessionController(self) -> SessionController:
        return self._session_controller

    @Property(QObject, constant=True)
    def dutyController(self) -> DutyController:
        return self._duty_controller

    @Property(QObject, constant=True)
    def toolController(self) -> ToolController:
        return self._tool_controller

    @Property(QObject, constant=True)
    def trayController(self) -> TrayController:
        return self._tray_controller

    @Property(QObject, constant=True)
    def updateController(self) -> UpdateController:
        return self._update_controller

    @Property(QObject, constant=True)
    def dutySheetController(self) -> DutySheetController:
        return self._duty_sheet_controller

    @Property(QObject, constant=True)
    def restMonthlyController(self) -> RestMonthlyController:
        return self._rest_monthly_controller

    @Property(QObject, constant=True)
    def dailyVehicleController(self) -> DailyVehicleController:
        return self._daily_vehicle_controller

    @Property(QObject, constant=True)
    def rescueVideoController(self) -> RescueVideoController:
        return self._rescue_video_controller

    @Property(QObject, constant=True)
    def dutyExecutionController(self) -> DutyExecutionController:
        return self._duty_execution_controller

    @Property(QObject, constant=True)
    def workLogSettingsController(self) -> WorkLogSettingsController:
        return self._work_log_settings_controller

    @Property(bool, constant=True)
    def readOnlyAcceptance(self) -> bool:
        return self._read_only_acceptance

    @Property(str, notify=diagnosticsChanged)
    def diagnosticsStatus(self) -> str:
        return self._diagnostics_status

    @Slot(QObject)
    def configureNativeTitleBar(self, window: QObject) -> None:
        """Request the platform shell to style one QML-owned native window."""

        if window is not None:
            self.nativeTitleBarRequested.emit(window)

    @Slot()
    def exportIssuePackage(self) -> None:
        try:
            package_path = self._diagnostics_service.export(
                DiagnosticSnapshot(
                    login_status=self._session_controller.loginStatus,
                    duty_status=self._duty_controller.scheduleStatus,
                    target_date=self._duty_controller.targetDateText,
                    session_actor=self._session_controller.actorNo,
                    session_verified=self._session_controller.isLoggedIn,
                )
            )
        except DiagnosticExportError as exc:
            self._diagnostics_status = str(exc)
            self.diagnosticsChanged.emit()
            self.diagnosticsStatusRequested.emit(self._diagnostics_status)
            return
        self._diagnostics_status = f"問題包已匯出：{package_path.name}"
        self.diagnosticsChanged.emit()
        self.diagnosticsStatusRequested.emit(self._diagnostics_status)

    @Slot(result=bool)
    def recordUpdateLogout(self) -> bool:
        """Durably queue the update logout before the updater may stop this process."""

        session = self._session_state.session
        actor_no = (
            str(session.actor_no or "").strip()
            if session is not None and session.verified
            else ""
        ) or self._last_login_actor_no
        user_id = (
            str(session.user_id or "").strip()
            if session is not None and session.verified
            else ""
        ) or self._last_login_user_id
        display_name = (
            self._session_controller.displayName
            if session is not None and session.verified
            else self._last_login_display_name
        )
        if not actor_no and not user_id:
            return False
        self._operational_sync_service.enqueue_event(
            "logout",
            status="ok",
            trigger_type="update",
            actor_no=actor_no,
            user_id=user_id,
            display_name=self._operational_display_name(actor_no, display_name),
            content="更新前登出",
            durable_only=True,
        )
        return True

    @Slot(result=str)
    def prepareUpdateShutdown(self) -> str:
        """Return the updater handshake result without risking an in-flight task."""

        if self._update_shutdown_prepared:
            return "ready"
        block_reason = self._stop_block_reason()
        if block_reason:
            self._update_controller.deferUpdate(block_reason)
            return "busy"
        session = self._session_state.session
        has_identity = bool(
            (session is not None and session.verified)
            or self._last_login_actor_no
            or self._last_login_user_id
        )
        if has_identity:
            try:
                if not self.recordUpdateLogout():
                    return "failed"
            except Exception:
                return "failed"
        self._pending_live_refresh_generation = None
        if not self._close_worker_admissions():
            return "busy"
        self._update_shutdown_prepared = True
        return "ready"

    def _close_worker_admissions(self) -> bool:
        """Stop every timer and controller entry point before process exit."""

        self._worker_admissions_closed = True
        self._hourly_refresh_timer.stop()
        self._board_retry_timer.stop()
        self._tomorrow_schedule_timer.stop()
        if self._scheduled_folder_timer is not None:
            self._scheduled_folder_timer.stop()
        for controller in (
            self._session_controller,
            self._update_controller,
            self._duty_sheet_controller,
            self._rest_monthly_controller,
            self._daily_vehicle_controller,
            self._rescue_video_controller,
        ):
            prepare = getattr(controller, "prepare_shutdown_admission", None)
            if callable(prepare):
                prepare()
        duty_ready = self._duty_controller.prepare_session_end()
        execution_ready = self._duty_execution_controller.prepare_session_end()
        return duty_ready and execution_ready

    def _stop_block_reason(self) -> str:
        """Describe the first activity that makes quit or update unsafe."""

        if self._update_shutdown_prepared or self._worker_admissions_closed:
            return "程式正在關閉"
        if self._duty_execution_controller.isBusy or self._logout_pending:
            return "勤務登打尚未完成"
        if self._session_controller.isBusy or self._session_controller.hasRunningWorkers:
            return "登入驗證尚未完成"
        if self._duty_controller.isRefreshing or self._tomorrow_schedule_workers:
            return "勤務資料正在更新"
        running_tools = (
            (self._duty_sheet_controller.isRunning, "勤務表登打"),
            (self._rest_monthly_controller.isRunning, "休息時間或勤務基準表登打"),
            (self._daily_vehicle_controller.isRunning, "車輛保養清點"),
            (self._rescue_video_controller.isRunning, "救護行車紀錄器處理"),
        )
        for is_running, label in running_tools:
            if is_running:
                return f"{label}尚未完成"
        if self._scheduled_folder_workers:
            return "排程資料夾作業尚未完成"
        if self._operational_sync_workers or self._operational_sync_queue:
            return "後台狀態正在同步"
        if self._update_controller.isChecking:
            return "更新檢查尚未完成"
        return ""

    @Slot(int)
    def shiftAuditDate(self, days: int) -> None:
        target = shift_roc_date(self._duty_controller.targetDateText or business_roc_date(), int(days))
        self.refreshAuditDate(target)

    @Slot()
    def openAuditMode(self) -> None:
        self._duty_controller.disable_auto_execution()
        self._duty_mode_active = False
        self._duty_controller.setAuditStatusFilter("需處理")
        self._duty_controller.setAuditKindFilter("全部")
        self.refreshAuditDate(self._duty_controller.targetDateText or business_roc_date())

    @Slot(str)
    def refreshAuditDate(self, target_roc_date: str) -> None:
        try:
            normalized = clamp_audit_roc_date(target_roc_date)
        except ValueError:
            return
        self._duty_controller.load_audit_schedule(normalized)

    @Slot(result=bool)
    def refreshAuditLiveData(self) -> bool:
        """Refresh the selected audit date without publishing a NAS event."""

        if self._read_only_acceptance:
            self._duty_controller.set_refresh_status("測試驗收模式不會執行即時勤務查詢。")
            return False
        session = self._session_state.session
        if session is None or not session.verified:
            self._duty_controller.set_refresh_status("請先完成勤務系統登入驗證後再重新查詢。")
            return False
        try:
            target_roc_date = clamp_audit_roc_date(
                self._duty_controller.targetDateText or business_roc_date()
            )
        except ValueError:
            self._duty_controller.set_refresh_status("審核日期格式錯誤，請重新選擇日期。")
            return False
        accepted = self._duty_controller.refresh_live_schedule(
            session.user_id,
            session.password,
            session.actor_no,
            target_roc_date=target_roc_date,
            actor_name=session.actor_name,
            publish_events=False,
            allow_auto_execution=False,
        )
        if not accepted:
            if self._duty_controller.isRefreshing:
                self._duty_controller.set_refresh_status("勤務資料正在更新，請稍候再重新查詢。")
            else:
                self._duty_controller.set_refresh_status("登入資料不完整，請重新登入後再重新查詢。")
        return accepted

    @Slot()
    def returnToDutySchedule(self) -> None:
        self._duty_mode_active = True
        self._duty_controller.disable_auto_execution()
        if self._read_only_acceptance:
            self.refreshAuditDate(business_roc_date())
            return
        session = self._session_state.session
        if session is None or not session.verified:
            self._duty_controller.set_refresh_status("請先完成登入驗證。")
            return
        accepted = self._duty_controller.refresh_live_schedule(
            session.user_id,
            session.password,
            session.actor_no,
            target_roc_date=business_roc_date(),
            actor_name=session.actor_name,
        )
        if not accepted:
            self._duty_controller.set_refresh_status("勤務資料正在更新，完成後才會恢復自動登打。")

    @Slot()
    def requestLogout(self) -> None:
        """Cancel queued work and wait for an irreversible active request."""

        self._begin_session_logout("")

    def _begin_session_logout(self, message: str) -> None:
        if self._logout_pending:
            return
        self._pending_live_refresh_generation = None
        self._duty_controller.prepare_session_end()
        if self._duty_execution_controller.prepare_session_end():
            if message:
                self._session_controller.systemLogout(message)
            else:
                self._session_controller.logout()
            return
        self._logout_pending = True
        self._pending_logout_message = str(message or "")
        self._session_controller.setOperationalStatus(
            "正在完成目前登打，完成後會自動登出。",
            "warning",
        )

    @Slot()
    def _finish_pending_logout(self) -> None:
        if not self._logout_pending or self._duty_execution_controller.isBusy:
            return
        message = self._pending_logout_message
        self._logout_pending = False
        self._pending_logout_message = ""
        if message:
            self._session_controller.systemLogout(message)
        else:
            self._session_controller.logout()

    def _sync_session_actor(self) -> None:
        previous_actor_no = self._synced_actor_no
        previous_user_id = self._synced_user_id
        previous_generation = self._synced_session_generation
        session_generation = self._session_state.generation
        logged_in = self._session_controller.isLoggedIn
        actor_no = self._session_controller.actorNo if logged_in else ""
        user_id = self._session_controller.userId if logged_in else ""
        if (
            actor_no == self._synced_actor_no
            and user_id == self._synced_user_id
            and session_generation == self._synced_session_generation
        ):
            return
        if previous_actor_no or previous_user_id:
            self._duty_execution_controller.close_entry_session()
        self._duty_controller.disable_auto_execution()
        self._synced_actor_no = actor_no
        self._synced_user_id = user_id
        self._synced_session_generation = session_generation
        if session_generation != previous_generation:
            self._actor_identity_pending = False
        self._duty_execution_controller.set_session_generation(session_generation)
        self._duty_controller.set_session_context(session_generation, user_id)
        if logged_in and self._session_controller.displayName:
            self._last_login_display_name = self._session_controller.displayName
        if logged_in and user_id:
            self._duty_execution_controller.reset_parallel_lanes()
            if user_id != self._last_login_user_id:
                self._last_login_actor_no = actor_no
            elif actor_no:
                self._last_login_actor_no = actor_no
            self._last_login_user_id = user_id
        elif logged_in and actor_no:
            self._last_login_actor_no = actor_no
        provisional_actor_no = "" if self._actor_identity_pending else (
            actor_no
            or (self._session_controller.saved_actor_no(user_id) if logged_in and user_id else "")
        )
        self._provisional_actor_no = provisional_actor_no
        self._duty_controller.set_actor_no(provisional_actor_no)
        session = self._session_state.session
        if session is not None and session.verified:
            if actor_no and not self._actor_identity_pending:
                self._send_operational_event("login", status="ok", trigger_type="login")
            self._duty_controller.load_current_schedule()
            accepted = self._duty_controller.refresh_live_schedule(
                session.user_id,
                session.password,
                provisional_actor_no,
                actor_name=session.actor_name,
            )
            self._pending_live_refresh_generation = (
                None if accepted else session_generation
            )
        elif previous_actor_no:
            self._pending_live_refresh_generation = None
            self._send_operational_event(
                "logout",
                status="ok",
                trigger_type="logout",
                actor_no=previous_actor_no,
                user_id=previous_user_id,
                display_name=self._last_login_display_name,
            )

    @Slot()
    def _retry_pending_live_refresh(self) -> None:
        generation = self._pending_live_refresh_generation
        if generation is None or self._duty_controller.isRefreshing:
            return
        session = self._session_state.session
        if (
            session is None
            or not session.verified
            or generation != self._session_state.generation
        ):
            self._pending_live_refresh_generation = None
            return
        self._pending_live_refresh_generation = None
        accepted = self._duty_controller.refresh_live_schedule(
            session.user_id,
            session.password,
            self._provisional_actor_no,
            actor_name=session.actor_name,
        )
        if not accepted and generation == self._session_state.generation:
            self._pending_live_refresh_generation = generation

    @Slot(bool)
    def setDutyModeActive(self, active: bool) -> None:
        self._duty_mode_active = bool(active)
        if not self._duty_mode_active:
            self._duty_controller.disable_auto_execution()

    @Slot(object)
    def _cached_schedule_loaded(self, schedule_data: dict) -> None:
        session = self._session_state.session
        actor_no = session.actor_no if session is not None else ""
        actor_no = str(actor_no or self._provisional_actor_no or "").strip()
        if session is None or not session.verified:
            return
        if not actor_no and session.actor_name:
            actor_no = actor_no_from_schedule(schedule_data, session.actor_name)
            if actor_no:
                self._duty_controller.set_actor_no(actor_no)
                self._session_controller.resolve_actor_no(actor_no, session.actor_name)
        if not actor_no:
            return
        self._session_controller.set_logged_in_status(
            duty_identity_label(
                schedule_data,
                actor_no,
                self._session_controller.displayName,
            ),
            duty_shift_label(schedule_data, actor_no),
        )
        self._work_log_settings_controller.set_schedule_data(schedule_data)

    @Slot(object)
    def _live_schedule_captured(self, schedule_data: dict) -> None:
        schedule_data = dict(schedule_data)
        authenticated_actor = schedule_data.pop("_authenticated_actor", {})
        self._operational_staff = operational_staff_from_schedule(schedule_data)
        session = self._session_state.session
        if str(schedule_data.get("target_date") or "") != business_roc_date():
            self._duty_controller.disable_auto_execution()
            return
        resolved_actor_no = ""
        actor_identity_unresolved = False
        actor_was_unresolved = False
        if session is not None and session.verified:
            actor_was_unresolved = not session.actor_no
            candidate_actor_no = str(authenticated_actor.get("actor_no", "") or "").strip()
            resolved_actor_name = str(authenticated_actor.get("actor_name", "") or "").strip()
            if not candidate_actor_no:
                candidate_actor_no = actor_no_from_schedule(schedule_data, session.actor_name)
                resolved_actor_name = session.actor_name
            if not candidate_actor_no:
                actor_identity_unresolved = True
                self._actor_identity_pending = True
                self._synced_actor_no = ""
                self._duty_controller.disable_auto_execution()
                self._duty_controller.set_actor_no("")
            elif candidate_actor_no != session.actor_no:
                resolved_actor_no = candidate_actor_no
                self._actor_identity_pending = False
                self._duty_controller.disable_auto_execution()
                self._synced_actor_no = resolved_actor_no
                self._synced_user_id = session.user_id
                self._last_login_actor_no = resolved_actor_no
                self._last_login_user_id = session.user_id
                self._duty_controller.set_actor_no(resolved_actor_no)
                self._session_controller.resolve_actor_no(
                    resolved_actor_no,
                    resolved_actor_name,
                )
            else:
                self._actor_identity_pending = False
                self._duty_controller.set_actor_no(candidate_actor_no)
        if session is not None and session.verified and session.actor_no and not actor_identity_unresolved:
            self._session_controller.set_logged_in_status(
                duty_identity_label(
                    schedule_data,
                    session.actor_no,
                    self._session_controller.displayName,
                ),
                duty_shift_label(schedule_data, session.actor_no),
            )
        elif actor_identity_unresolved:
            self._session_controller.setOperationalStatus(
                "已登入：登入身分待確認，已暫停自動登打。",
                "warning",
            )
        self._work_log_settings_controller.set_schedule_data(schedule_data)
        if self._read_only_acceptance:
            QTimer.singleShot(0, self._duty_controller.disable_auto_execution)
            return
        if resolved_actor_no and actor_was_unresolved:
            self._send_operational_event("login", status="ok", trigger_type="login")
        if str(schedule_data.get("target_date") or "") == business_roc_date():
            self._start_operational_sync("board", schedule_data=schedule_data)

    @Slot()
    def _retry_current_duty_board(self) -> None:
        """Retry a failed Google duty-board post without repeating a successful hash."""

        if self._read_only_acceptance or not self._duty_mode_active:
            return
        session = self._session_state.session
        if session is None or not session.verified:
            return
        if not bool(getattr(self._operational_sync_service, "board_enabled", True)):
            return
        schedule_data = dict(self._duty_controller._schedule_data)
        if str(schedule_data.get("target_date") or "") != business_roc_date():
            return
        self._start_operational_sync("board", schedule_data=schedule_data)

    @Slot(str)
    def _refresh_after_fire_day_change(self, target_roc_date: str) -> None:
        """Pause automatic work at 08:00 until the new fire-day capture succeeds."""

        target = str(target_roc_date or "").strip()
        if self._read_only_acceptance or not self._duty_mode_active:
            return
        session = self._session_state.session
        if session is None or not session.verified or not target:
            return
        self._duty_controller.disable_auto_execution()
        if self._duty_controller.refresh_live_schedule(
            session.user_id,
            session.password,
            session.actor_no,
            target_roc_date=target,
            actor_name=session.actor_name,
        ):
            self._pending_fire_day_refresh = ""
            return
        self._pending_fire_day_refresh = target
        QTimer.singleShot(1_000, self._retry_pending_fire_day_refresh)

    @Slot()
    def _retry_pending_fire_day_refresh(self) -> None:
        target = self._pending_fire_day_refresh
        if not target:
            return
        if target != business_roc_date():
            self._pending_fire_day_refresh = ""
            return
        self._refresh_after_fire_day_change(target)

    @Slot(str, str, str)
    def _login_attempt_failed(self, user_id: str, message: str, error_code: str) -> None:
        if self._read_only_acceptance:
            return
        self._send_operational_event(
            "login_failed",
            status="failed",
            trigger_type="login",
            user_id=str(user_id or "").strip(),
            error=message,
            snapshot={"error_code": error_code},
        )

    @Slot(str, str)
    def _live_capture_failed(self, message: str, error_code: str) -> None:
        trigger_type = "comparison" if error_code.startswith("comparison_") else "schedule"
        self._send_operational_event(
            "error",
            status="failed",
            trigger_type=trigger_type,
            error=message,
            snapshot={"error_code": error_code},
        )

    @Slot(object)
    def _live_snapshot_captured(self, snapshot) -> None:
        if self._read_only_acceptance:
            return
        schedule_data = snapshot.data if isinstance(snapshot.data, Mapping) else {}
        schedule_data_by_date = (
            snapshot.schedule_data_by_date
            if isinstance(snapshot.schedule_data_by_date, Mapping) and snapshot.schedule_data_by_date
            else {}
        )
        schedule_days = []
        schedule_paths = []
        for target_date, payload in sorted(schedule_data_by_date.items()):
            if not isinstance(payload, Mapping):
                continue
            actions = payload.get("actions", [])
            actions = actions if isinstance(actions, list) else []
            target_date = str(target_date or payload.get("target_date", ""))
            schedule_paths.append(f"schedule_output_{target_date}.json")
            schedule_days.append(
                {
                    "target_date": target_date,
                    "action_count": len(actions),
                    "actions": [
                        compact_action_snapshot(action)
                        for action in actions[:80]
                        if isinstance(action, Mapping)
                    ],
                }
            )
        if schedule_days:
            schedule_snapshot = {
                "paths": schedule_paths,
                "days": schedule_days,
            }
            signature = json.dumps(
                schedule_snapshot,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            if signature != self._last_schedule_snapshot_signature:
                self._last_schedule_snapshot_signature = signature
                self._send_operational_event(
                    "schedule_snapshot",
                    status="ok",
                    trigger_type="schedule",
                    snapshot=schedule_snapshot,
                )
        comparison_days = []
        for target_date, payload in sorted(snapshot.comparison_data.items()):
            if not isinstance(payload, Mapping):
                continue
            work_rows = payload.get("visible_work_rows", [])
            entry_rows = payload.get("visible_entry_rows", [])
            work_rows = work_rows if isinstance(work_rows, list) else []
            entry_rows = entry_rows if isinstance(entry_rows, list) else []
            comparison_days.append(
                {
                    "target_date": str(target_date),
                    "work_count": len(work_rows),
                    "entry_count": len(entry_rows),
                    "work_rows": [str(row)[:260] for row in work_rows[:50]],
                    "entry_rows": [str(row)[:260] for row in entry_rows[:50]],
                }
            )
        if comparison_days:
            self._send_operational_event(
                "comparison_snapshot",
                status="ok",
                trigger_type="comparison",
                snapshot={
                    "paths": [
                        f"comparison_output_{day['target_date']}.json"
                        for day in comparison_days
                    ],
                    "days": comparison_days,
                },
            )

    @Slot()
    def _refresh_hourly_live_schedule(self) -> None:
        if self._read_only_acceptance or self._worker_admissions_closed:
            return
        now = datetime.now()
        session = self._session_state.session
        if session is None or not session.verified or now.minute >= 5:
            return
        key = f"{now:%Y%m%d%H}"
        if key == self._last_hourly_refresh_key:
            return
        if self._duty_mode_active:
            accepted = self._duty_controller.refresh_live_schedule(
                session.user_id,
                session.password,
                session.actor_no,
                actor_name=session.actor_name,
            )
        else:
            accepted = self._duty_controller.refresh_live_comparisons(
                session.user_id,
                session.password,
                session.actor_no,
                target_roc_date=business_roc_date(now),
                actor_name=session.actor_name,
            )
        if accepted:
            self._last_hourly_refresh_key = key

    @Slot()
    def _capture_evening_tomorrow_schedule(self) -> None:
        """Match the legacy 18:00-24:00 missing-tomorrow snapshot prefetch."""

        if (
            self._read_only_acceptance
            or self._worker_admissions_closed
            or self._tomorrow_schedule_workers
        ):
            return
        now = datetime.now()
        session = self._session_state.session
        if session is None or not session.verified or not 18 <= now.hour < 24:
            return
        if self._duty_controller.isRefreshing:
            return
        target_roc_date = shift_roc_date(business_roc_date(now), 1)
        runtime_dir = getattr(self._schedule_capture_service, "runtime_dir", None)
        if runtime_dir is None:
            return
        schedule_path = (
            Path(runtime_dir)
            / "schedule"
            / f"schedule_output_{target_roc_date}.json"
        )
        if schedule_path.is_file():
            return
        self._tomorrow_schedule_request_id += 1
        request_id = self._tomorrow_schedule_request_id
        lane_owner = f"tomorrow-schedule:{request_id}"
        if not self._duty_controller.claim_capture_lane(lane_owner):
            return
        request = ScheduleCaptureRequest(
            session.user_id,
            session.password,
            session.actor_no,
            target_roc_date,
            session.actor_name,
        )
        worker = ScheduleCaptureWorker(
            request_id,
            self._schedule_capture_service,
            request,
            include_comparisons=False,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._tomorrow_schedule_succeeded)
        worker.failed.connect(self._tomorrow_schedule_failed)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(
            self._tomorrow_schedule_worker_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        self._tomorrow_schedule_workers[request_id] = (thread, worker)
        self._tomorrow_schedule_contexts[request_id] = (
            self._session_state.generation,
            session.user_id,
            session.actor_no,
            lane_owner,
        )
        thread.start()

    def _tomorrow_schedule_request_is_current(self, request_id: int) -> bool:
        context = self._tomorrow_schedule_contexts.get(request_id)
        session = self._session_state.session
        if context is None or session is None or not session.verified:
            return False
        generation, user_id, actor_no, _lane_owner = context
        return (
            generation == self._session_state.generation
            and user_id == session.user_id
            and actor_no == session.actor_no
        )

    @Slot(int, str, object)
    def _tomorrow_schedule_succeeded(self, request_id: int, _actor_no: str, snapshot) -> None:
        if not self._tomorrow_schedule_request_is_current(request_id):
            return
        # NAS schedule-snapshot events remain on hold until the backend update is approved.
        del snapshot

    @Slot(int, str, str, str)
    def _tomorrow_schedule_failed(
        self,
        request_id: int,
        _actor_no: str,
        message: str,
        error_code: str,
    ) -> None:
        if not self._tomorrow_schedule_request_is_current(request_id):
            return
        if error_code == "login_failed":
            self._force_logout(message)

    @Slot(int)
    def _tomorrow_schedule_worker_finished(self, request_id: int) -> None:
        worker_pair = self._tomorrow_schedule_workers.get(request_id)
        if worker_pair is None:
            return
        thread, _worker = worker_pair
        thread.quit()
        self._poll_tomorrow_schedule_thread(request_id)

    def _poll_tomorrow_schedule_thread(self, request_id: int) -> None:
        worker_pair = self._tomorrow_schedule_workers.get(request_id)
        if worker_pair is None:
            return
        if worker_pair[0].isFinished():
            self._tomorrow_schedule_thread_finished(request_id)
            return
        QTimer.singleShot(
            10,
            lambda request_id=request_id: self._poll_tomorrow_schedule_thread(request_id),
        )

    @Slot(int)
    def _tomorrow_schedule_thread_finished(self, request_id: int) -> None:
        worker_pair = self._tomorrow_schedule_workers.pop(request_id, None)
        context = self._tomorrow_schedule_contexts.pop(request_id, None)
        if worker_pair is None:
            return
        thread, _worker = worker_pair
        thread.deleteLater()
        if context is not None:
            self._duty_controller.release_capture_lane(context[3])

    @staticmethod
    def _tool_label(tool_id: str) -> str:
        return {
            "rest_time": "休息時間登打",
            "monthly_base": "勤務基準表登打",
        }.get(str(tool_id or ""), str(tool_id or ""))

    @staticmethod
    def _submission_action(
        request: DutySubmissionRequest,
        result: DutySubmissionResult | None = None,
    ) -> dict:
        if result is not None and result.action:
            return dict(result.action)
        actions = request.schedule_data.get("actions", [])
        if 0 <= request.action_index < len(actions) and isinstance(actions[request.action_index], Mapping):
            return dict(actions[request.action_index])
        return {}

    def _submission_ui_action_key(self, request: DutySubmissionRequest) -> str:
        """Return a key only when it still names one current task in the UI."""

        return self._duty_controller.ui_action_key_for_request(request)

    @staticmethod
    def _submission_staff(request: DutySubmissionRequest) -> dict[str, dict]:
        return operational_staff_from_schedule(request.schedule_data)

    def _submission_event_fields(
        self,
        request: DutySubmissionRequest,
        action: Mapping,
    ) -> dict[str, str]:
        actor_no = str(request.session_actor_no or "").strip()
        staff = self._submission_staff(request)
        actor_name = str(staff.get(actor_no, {}).get("name", "") or "").strip()
        return {
            "actor_no": actor_no,
            "user_id": str(request.user_id or "").strip(),
            "display_name": self._operational_display_name(actor_no, actor_name),
            "target": operational_person_label(str(action.get("target") or ""), staff),
        }

    @staticmethod
    def _external_return_queue_id(request: DutySubmissionRequest) -> str:
        return str(request.schedule_data.get("_unreturned_return_queue_id", "") or "").strip()

    def _is_unreturned_recovery_request(self, request: DutySubmissionRequest) -> bool:
        return request.trigger_type == "recovery" and bool(self._external_return_queue_id(request))

    def _should_send_operational_submission_event(
        self,
        request: DutySubmissionRequest,
        *,
        status: str = "",
    ) -> bool:
        if not self._is_unreturned_recovery_request(request):
            return True
        return status in {"submitted", "skipped_duplicate"}

    @Slot(object)
    def _publish_unreturned_return_event(self, event: Mapping) -> None:
        record = event.get("record", {}) if isinstance(event, Mapping) else {}
        if not isinstance(record, Mapping):
            return
        trigger_type = str(event.get("trigger_type") or "recovery")
        status = str(event.get("status") or "pending")
        if (
            trigger_type == "recovery"
            and status in {"retrying", "pending"}
            and str(record.get("queue_id") or "").strip()
        ):
            return
        actions = [
            dict(item)
            for item in record.get("actions", [])
            if isinstance(item, Mapping)
        ]
        if not actions and isinstance(record.get("action"), Mapping):
            actions = [dict(record["action"])]
        if not actions:
            return
        context = record.get("schedule_context", {}) if isinstance(record, Mapping) else {}
        staff = operational_staff_from_schedule(context) if isinstance(context, Mapping) else {}
        outgoing = next(
            (
                action
                for action in actions
                if action.get("kind") == "entry_log"
                and isinstance(action.get("fields"), Mapping)
                and action["fields"].get("出或入") == "值退"
            ),
            actions[0],
        )
        incoming = next(
            (
                action
                for action in actions
                if action.get("kind") == "entry_log"
                and isinstance(action.get("fields"), Mapping)
                and action["fields"].get("出或入") == "值班"
            ),
            None,
        )
        snapshot = {
            key: str(record.get(key) or "")
            for key in (
                "queue_id",
                "completion_key",
                "source_target_date",
                "origin_actor_no",
                "last_owner_actor_no",
                "first_paused_at",
                "last_attempt_at",
                "next_retry_at",
                "expires_at",
            )
        }
        snapshot["retry_interval_minutes"] = int(record.get("retry_interval_minutes") or 0)
        if record.get("record_type") in {"handoff_group", "bridge_history"}:
            bridge_history = [
                bridge
                for bridge in record.get("bridge_history", [])
                if isinstance(bridge, Mapping)
            ]
            latest_bridge = bridge_history[-1] if bridge_history else {}
            snapshot["handoff"] = {
                "original_handoff_time": str(outgoing.get("time") or ""),
                "outgoing_person": operational_person_label(
                    str(outgoing.get("target") or outgoing.get("actor") or ""),
                    staff or self._operational_staff,
                ),
                "scheduled_incoming_person": operational_person_label(
                    str(incoming.get("target") or "") if incoming else "",
                    staff or self._operational_staff,
                ),
                "actual_incoming_person": operational_person_label(
                    str(incoming.get("target") or "") if incoming else "",
                    staff or self._operational_staff,
                ),
                "bridge_at": str(latest_bridge.get("bridged_at") or ""),
                "skipped_scheduled_people": "、".join(
                    operational_person_label(
                        str(actor_no or ""), staff or self._operational_staff
                    )
                    for actor_no in latest_bridge.get("skipped_actor_nos", [])
                ),
                "actual_incoming_people": "、".join(
                    operational_person_label(
                        str(actor_no or ""), staff or self._operational_staff
                    )
                    for actor_no in latest_bridge.get("incoming_actor_nos", [])
                ),
            }
        self._send_operational_event(
            "unreturned_return",
            status=status,
            trigger_type=trigger_type,
            action=outgoing,
            target=operational_person_label(
                str(outgoing.get("target") or ""),
                staff or self._operational_staff,
            ),
            snapshot=snapshot,
        )

    @staticmethod
    def _format_duty_notification(
        action: Mapping,
        staff: Mapping[str, Mapping],
        outcome: str,
    ) -> str:
        """Keep duty notifications specific enough for parallel submissions."""

        if action.get("kind") == "handoff_preflight":
            kind = "交接預檢"
        elif action.get("kind") == "entry_log":
            kind = "出入"
        else:
            kind = "工作"
        summary = action_summary(action) or "勤務登打"
        target = target_short_label(action, staff)
        target_text = f" {target}" if target and target != "-" else ""
        return f"{kind}｜{summary}{target_text}｜{outcome}"

    def _should_notify_duty_submission(
        self,
        request: DutySubmissionRequest,
        result: DutySubmissionResult | None = None,
    ) -> bool:
        if self._duty_controller.is_handoff_preflight_request(request):
            return False
        if self._is_unreturned_return_check_request(request):
            if request.trigger_type == "manual":
                return True
            return bool(
                result is not None
                and result.status in ("submitted", "skipped_duplicate", "review_required")
            )
        if not self._external_return_queue_id(request):
            return True
        if request.trigger_type != "recovery":
            return True
        return bool(result is not None and result.status in ("submitted", "skipped_duplicate"))

    def _is_unreturned_return_check_request(self, request: DutySubmissionRequest) -> bool:
        if request.trigger_type not in ("due", "recovery", "manual"):
            return False
        action = self._submission_action(request)
        fields = action.get("fields", {})
        return bool(
            action.get("kind") == "entry_log"
            and isinstance(fields, Mapping)
            and fields.get("領用事由及地點", "") in ("退勤", "休息後退勤")
        )

    @Slot(object)
    def _submission_started(self, request: DutySubmissionRequest) -> None:
        if not self._should_notify_duty_submission(request):
            return
        action = self._submission_action(request)
        self._tray_controller.notify(
            "SinpoSmart",
            self._format_duty_notification(
                action,
                self._submission_staff(request),
                "開始登打",
            ),
        )

    @Slot(object)
    def _submission_queued(self, request: DutySubmissionRequest) -> None:
        action = self._submission_action(request)
        is_handoff_preflight = self._duty_controller.is_handoff_preflight_request(request)
        if (
            not is_handoff_preflight
            and self._should_send_operational_submission_event(request)
        ):
            self._send_operational_event(
                "action_queued",
                status="pending_write_automation",
                trigger_type=request.trigger_type,
                action=action,
                snapshot={
                    "action_index": request.action_index,
                    "completion_key": request.action_key or action_completion_key(action),
                },
                **self._submission_event_fields(request, action),
            )

    @Slot(object, str, str)
    def _submission_cancelled(
        self,
        request: DutySubmissionRequest,
        message: str,
        error_code: str,
    ) -> None:
        if self._duty_controller.is_handoff_preflight_request(request):
            return
        if not self._should_send_operational_submission_event(request):
            return
        action = self._submission_action(request)
        self._send_operational_event(
            "action_result",
            status="cancelled",
            trigger_type=request.trigger_type,
            action=action,
            error=message,
            snapshot={
                "action_index": request.action_index,
                "completion_key": request.action_key or action_completion_key(action),
                "error_code": error_code,
            },
            **self._submission_event_fields(request, action),
        )

    @Slot(object, object)
    def _submission_finished(
        self,
        request: DutySubmissionRequest,
        result: DutySubmissionResult,
    ) -> None:
        queue_id = self._external_return_queue_id(request)
        is_handoff_preflight = self._duty_controller.is_handoff_preflight_request(request)
        request_is_current = self._duty_controller.request_matches_current_session(request)
        result_applied = False
        if is_handoff_preflight and request_is_current:
            if result.status == "paused_external":
                self._duty_controller.handle_handoff_preflight_paused(
                    request,
                    result.comparison,
                )
            elif result.status == "handoff_preflight_ready":
                if self._duty_controller.handle_handoff_preflight_ready(request):
                    self._enqueue_handoff_group_after_preflight(request)
            else:
                self._duty_controller.handle_handoff_preflight_failure(
                    request,
                    result.message,
                    "preflight_incomplete",
                )
        elif queue_id and request_is_current:
            action = self._submission_action(request, result)
            component_key = str(
                request.schedule_data.get("_unreturned_return_component_key", "") or ""
            )
            result_applied = self._duty_controller.handle_external_return_queue_result(
                queue_id,
                action,
                result.status,
                component_key,
                trigger_type=request.trigger_type,
            )
        elif not is_handoff_preflight and not queue_id:
            result_applied = self._duty_controller.handle_submission_request_result(
                request,
                result.status,
                result.message,
                str(result.result_path),
                result.comparison,
            )
        action = self._submission_action(request, result)
        if (
            not is_handoff_preflight
            and result_applied
            and result.status in {"submitted", "skipped_duplicate"}
        ):
            action_key = self._submission_ui_action_key(request)
            if action_key:
                self.dutyActionRecovered.emit(action_key)
        if (
            not is_handoff_preflight
            and self._should_send_operational_submission_event(request, status=result.status)
        ):
            self._send_operational_event(
                "action_result",
                status=result.status,
                trigger_type=request.trigger_type,
                action=action,
                result_ref=Path(result.result_path).name,
                snapshot={
                    "action_index": request.action_index,
                    "completion_key": request.action_key or action_completion_key(action),
                },
                **self._submission_event_fields(request, action),
            )
            if result.status == "submitted":
                outcome = "登打完成"
            elif result.status == "skipped_duplicate":
                outcome = "已有資料，略過"
            else:
                outcome = str(result.message or "登打未完成").strip()
            if self._should_notify_duty_submission(request, result):
                self._tray_controller.notify(
                    "SinpoSmart",
                    self._format_duty_notification(action, self._submission_staff(request), outcome),
                )

    @Slot(object, str, str, str)
    def _submission_failed(
        self,
        request: DutySubmissionRequest,
        message: str,
        error_code: str,
        result_path: str,
    ) -> None:
        queue_id = self._external_return_queue_id(request)
        action = self._submission_action(request)
        is_handoff_preflight = self._duty_controller.is_handoff_preflight_request(request)
        request_is_current = self._duty_controller.request_matches_current_session(request)
        failure_applied = False
        if is_handoff_preflight and request_is_current:
            self._duty_controller.handle_handoff_preflight_failure(request, message, error_code)
        elif queue_id and request_is_current:
            component_key = str(
                request.schedule_data.get("_unreturned_return_component_key", "") or ""
            )
            failure_applied = self._duty_controller.handle_external_return_queue_failure(
                queue_id,
                action,
                message,
                component_key,
                trigger_type=request.trigger_type,
            )
            if error_code == "login_failed":
                self._duty_controller.disable_auto_execution()
                self._force_logout(message)
        elif not is_handoff_preflight and not queue_id:
            failure_applied = self._duty_controller.handle_submission_request_failure(
                request,
                message,
                error_code,
            )
            if not failure_applied and request_is_current and error_code == "login_failed":
                self._duty_controller.disable_auto_execution()
                self._force_logout(message)
        if not is_handoff_preflight and failure_applied:
            action_key = self._submission_ui_action_key(request)
            if action_key:
                self.dutyActionFailed.emit(action_key, str(message or "").strip())
        if (
            not is_handoff_preflight
            and self._should_send_operational_submission_event(request)
        ):
            self._send_operational_event(
                "action_result",
                status="failed",
                trigger_type=request.trigger_type,
                action=action,
                error=message,
                result_ref=Path(result_path).name if result_path else "",
                snapshot={
                    "action_index": request.action_index,
                    "completion_key": request.action_key or action_completion_key(action),
                    "error_code": error_code,
                },
                **self._submission_event_fields(request, action),
            )
            detail = str(message or "登打失敗").strip()
            if self._should_notify_duty_submission(request):
                self._tray_controller.notify(
                    "SinpoSmart",
                    self._format_duty_notification(
                        action,
                        self._submission_staff(request),
                        f"登打失敗：{detail}",
                    ),
                )
        if not result_path or error_code == "validation_error":
            return
        try:
            package_path = self._diagnostics_service.export(
                DiagnosticSnapshot(
                    login_status=self._session_controller.loginStatus,
                    duty_status=message,
                    target_date=str(request.schedule_data.get("target_date", "")),
                    session_actor=request.session_actor_no,
                    session_verified=request_is_current,
                )
            )
        except DiagnosticExportError as exc:
            self._diagnostics_status = str(exc)
        else:
            self._diagnostics_status = f"問題包已匯出：{package_path.name}"
        self.diagnosticsChanged.emit()

    def _tool_run_started(self, tool_name: str, tool_label: str, *, mode: str = "") -> None:
        self._active_tool_runs[tool_name] = (tool_label, mode)
        self._shutdown_terminal_tool_runs.discard(tool_name)
        session = self._session_state.session
        actor_no = self._session_controller.actorNo
        actor_name = str(session.actor_name or "").strip() if session is not None else ""
        operator = (
            f"{actor_no}番 {actor_name}"
            if actor_no and actor_name
            else actor_name
            or self._session_controller.displayName
            or self._session_controller.userId
            or "目前登入人員"
        )
        self._tool_controller.record_started(
            tool_name,
            tool_label,
            operator,
            self._tool_usage_period(tool_name),
            actor_no=self._session_controller.actorNo,
            user_id=self._session_controller.userId,
        )
        snapshot = {"tool_name": tool_name, "tool_label": tool_label}
        if mode:
            snapshot["mode"] = mode
        self._send_operational_event(
            "tool_action_started",
            status="started",
            trigger_type="tool_start",
            snapshot=snapshot,
        )

    def _tool_run_finished(
        self,
        tool_name: str,
        tool_label: str,
        message: str,
        *,
        notify: bool = True,
        allow_during_shutdown: bool = False,
    ) -> None:
        if self._operational_sync_shutting_down and not allow_during_shutdown:
            return
        if tool_name in self._shutdown_terminal_tool_runs:
            return
        self._active_tool_runs.pop(tool_name, None)
        self._tool_controller.record_finished(tool_name, "completed", message)
        self._send_operational_event(
            "tool_action_finished",
            status="completed",
            trigger_type="tool_finish",
            content=message,
            snapshot={"tool_name": tool_name, "tool_label": tool_label},
        )
        if notify:
            self._tray_controller.notify("SinpoSmart", message)

    def _tool_run_failed(
        self,
        tool_name: str,
        tool_label: str,
        message: str,
        *,
        mode: str = "",
        notify: bool = True,
        force: bool = False,
        allow_during_shutdown: bool = False,
    ) -> None:
        if self._operational_sync_shutting_down and not allow_during_shutdown:
            return
        if tool_name in self._shutdown_terminal_tool_runs and not force:
            return
        self._active_tool_runs.pop(tool_name, None)
        self._tool_controller.record_finished(tool_name, "failed", message)
        snapshot = {"tool_name": tool_name, "tool_label": tool_label}
        failure_stage = self._failure_stage_for_tool(tool_name)
        if failure_stage:
            snapshot["failure_stage"] = failure_stage
        failure_detail = self._failure_detail_for_tool(tool_name)
        if failure_detail:
            snapshot["failure_detail"] = failure_detail
        if mode:
            snapshot["mode"] = mode
        self._send_operational_event(
            "tool_action_finished",
            status="failed",
            trigger_type="tool_finish",
            error=message,
            snapshot=snapshot,
        )
        if notify:
            self._tray_controller.notify("SinpoSmart", message)

    def _finalize_active_tool_runs_for_shutdown(self) -> None:
        for tool_name, (tool_label, mode) in tuple(self._active_tool_runs.items()):
            self._shutdown_terminal_tool_runs.add(tool_name)
            self._tool_run_failed(
                tool_name,
                tool_label,
                "主程式關閉，未取得工具完成結果。",
                mode=mode,
                notify=False,
                force=True,
                allow_during_shutdown=True,
            )

    def _failure_stage_for_tool(self, tool_name: str) -> str:
        controllers = {
            "duty_sheet": self._duty_sheet_controller,
            "rest_time": self._rest_monthly_controller,
            "monthly_base": self._rest_monthly_controller,
            "daily_vehicle": self._daily_vehicle_controller,
            "rescue_video": self._rescue_video_controller,
        }
        controller = controllers.get(tool_name)
        return str(getattr(controller, "failureStage", "unknown") or "unknown")

    def _failure_detail_for_tool(self, tool_name: str) -> str:
        controllers = {
            "rest_time": self._rest_monthly_controller,
            "monthly_base": self._rest_monthly_controller,
        }
        controller = controllers.get(tool_name)
        return str(getattr(controller, "failureDetail", "") or "")

    def _tool_usage_period(self, tool_name: str) -> str:
        if tool_name == "rest_time":
            month = self._rest_monthly_controller.restMonth
        elif tool_name == "monthly_base":
            month = self._rest_monthly_controller.monthlyMonth
        else:
            return ""
        month_digits = "".join(character for character in str(month) if character.isdigit())
        return f"{self._rest_monthly_controller.rocYear:03d}{int(month_digits or '0'):02d}"

    def _send_operational_event(self, record_type: str, **fields) -> None:
        if self._read_only_acceptance:
            return
        session = self._session_state.session
        action = fields.get("action") if isinstance(fields.get("action"), Mapping) else {}
        if action and "target" not in fields:
            fields["target"] = operational_person_label(
                str(action.get("target") or ""),
                self._operational_staff,
            )
        event_fields = {
            "actor_no": session.actor_no if session else self._synced_actor_no,
            "user_id": session.user_id if session else self._synced_user_id,
            "display_name": self._session_controller.displayName,
        }
        event_fields.update(fields)
        event_fields["display_name"] = self._operational_display_name(
            str(event_fields.get("actor_no") or ""),
            str(event_fields.get("display_name") or ""),
        )
        self._start_operational_sync(
            "event",
            record_type=record_type,
            fields=event_fields,
        )

    @staticmethod
    def _operational_display_name(actor_no: str, display_name: str) -> str:
        """Keep NAS login records in the single ``番號 姓名`` display format."""

        actor = str(actor_no or "").strip().removesuffix("番").strip()
        raw = str(display_name or "").strip()
        if not actor:
            match = re.match(r"^(\d+)\s*番(?:\s+|$)", raw)
            if match is not None:
                actor = match.group(1)
        name = re.sub(r"^\s*\d+\s*番\s*", "", raw)
        name = re.sub(
            r"^(?:(?:副小隊長|小隊長|分隊長|副中隊長|中隊長|大隊長|隊員)\s+)+",
            "",
            name,
        ).strip()
        name = re.sub(r"\s+", " ", name)
        return f"{actor}番 {name}".strip() if actor else name

    def _start_operational_sync(
        self,
        operation: str,
        *,
        record_type: str = "",
        fields: dict | None = None,
        schedule_data: dict | None = None,
    ) -> None:
        if self._worker_admissions_closed and not self._allow_shutdown_operational_sync:
            return
        self._operational_sync_request_id += 1
        request_id = self._operational_sync_request_id
        request = (
            request_id,
            operation,
            record_type,
            dict(fields or {}),
            dict(schedule_data or {}),
        )
        self._operational_sync_queue.append(request)
        self._start_next_operational_sync()

    def _start_next_operational_sync(self) -> None:
        if (
            self._operational_sync_shutting_down
            or self._operational_sync_workers
            or not self._operational_sync_queue
        ):
            return
        self._launch_operational_sync(self._operational_sync_queue.popleft())

    def _launch_operational_sync(
        self,
        request: tuple[int, str, str, dict, dict],
    ) -> None:
        request_id, operation, record_type, fields, schedule_data = request
        worker = OperationalSyncWorker(
            request_id,
            self._operational_sync_service,
            operation,
            record_type=record_type,
            fields=fields,
            schedule_data=schedule_data,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(self._operational_sync_worker_finished)
        self._operational_sync_workers[request_id] = (thread, worker)
        thread.start()

    @Slot(int)
    def _operational_sync_worker_finished(self, request_id: int) -> None:
        worker_pair = self._operational_sync_workers.get(request_id)
        if worker_pair is None:
            return
        thread, _worker = worker_pair
        thread.quit()
        if not thread.wait(5_000):
            self._poll_operational_sync_thread_finished(request_id)
            return
        self._operational_sync_thread_finished(request_id)
        thread.deleteLater()

    def _poll_operational_sync_thread_finished(self, request_id: int) -> None:
        worker_pair = self._operational_sync_workers.get(request_id)
        if worker_pair is None:
            return
        thread, _worker = worker_pair
        if not thread.isFinished():
            QTimer.singleShot(
                50,
                lambda: self._poll_operational_sync_thread_finished(request_id),
            )
            return
        self._operational_sync_thread_finished(request_id)
        thread.deleteLater()

    @Slot(int)
    def _operational_sync_thread_finished(self, request_id: int) -> None:
        worker_pair = self._operational_sync_workers.pop(request_id, None)
        if worker_pair is None:
            return
        QTimer.singleShot(0, self._start_next_operational_sync)

    def _drain_queued_operational_sync(self) -> None:
        while self._operational_sync_queue:
            _request_id, operation, record_type, fields, schedule_data = (
                self._operational_sync_queue.popleft()
            )
            try:
                if operation == "event":
                    self._operational_sync_service.enqueue_event(
                        record_type,
                        **fields,
                        immediate=True,
                    )
                elif operation == "board":
                    sync_board = getattr(self._operational_sync_service, "sync_board", None)
                    if callable(sync_board):
                        sync_board(schedule_data)
                    else:
                        sync_board_async = getattr(
                            self._operational_sync_service,
                            "sync_board_async",
                            None,
                        )
                        if callable(sync_board_async):
                            sync_board_async(schedule_data)
            except Exception as exc:
                self._operational_sync_service.record_unhandled_failure(operation, exc)

    @Slot(object)
    def _enqueue_due_tasks(self, indices: list[int]) -> None:
        if self._read_only_acceptance or not self._duty_mode_active:
            return
        session = self._session_state.session
        if session is None or not session.verified:
            return
        for request in self._duty_controller.due_submission_requests(
            session.user_id,
            session.password,
            list(indices),
        ):
            if self._duty_execution_controller.enqueue(request):
                self._duty_controller.mark_submission_enqueued(request.action_index)

    @Slot(int)
    def _prewarm_handoff_entry_browser(self, action_index: int) -> None:
        if self._read_only_acceptance or not self._duty_mode_active:
            return
        session = self._session_state.session
        if session is None or not session.verified:
            return
        request = self._duty_controller.handoff_prewarm_request(
            session.user_id,
            session.password,
            action_index,
        )
        if request is not None:
            self._duty_execution_controller.prewarm_entry_browser(request)

    @Slot(str)
    def _handle_execution_unavailable(self, message: str) -> None:
        self._duty_controller.disable_auto_execution()
        self._tray_controller.notify("SinpoSmart", message)

    @Slot(object)
    def _enqueue_manual_tasks(self, indices: list[int]) -> None:
        if self._read_only_acceptance:
            return
        session = self._session_state.session
        if session is None or not session.verified:
            return
        for request in self._duty_controller.manual_submission_requests(
            session.user_id,
            session.password,
            list(indices),
        ):
            if self._duty_execution_controller.enqueue(request):
                if not self._external_return_queue_id(request):
                    self._duty_controller.mark_submission_enqueued(request.action_index)

    @Slot(str)
    def _enqueue_queued_external_return_manual_submission(self, queue_id: str) -> None:
        if self._read_only_acceptance:
            return
        session = self._session_state.session
        if session is None or not session.verified:
            return
        requests = self._duty_controller.queued_external_return_manual_submission_requests(
            session.user_id,
            session.password,
            queue_id,
        )
        for request in requests:
            self._duty_execution_controller.enqueue(request)

    @Slot(object)
    def _enqueue_external_return_recovery(self, record: Mapping) -> None:
        queue_id = str(record.get("queue_id") or "") if isinstance(record, Mapping) else ""
        if self._read_only_acceptance:
            self._duty_controller.release_external_return_recovery(queue_id)
            return
        session = self._session_state.session
        if session is None or not session.verified:
            self._duty_controller.release_external_return_recovery(queue_id)
            return
        requests = self._duty_controller.recovery_submission_requests(
            session.user_id,
            session.password,
            record,
        )
        if not requests:
            self._duty_controller.handle_external_return_queue_failure(queue_id)
            return
        for request in requests:
            self._duty_execution_controller.enqueue(request)

    def _enqueue_handoff_group_after_preflight(self, request: DutySubmissionRequest) -> None:
        session = self._session_state.session
        if session is None or not session.verified:
            self._duty_controller.handle_handoff_preflight_failure(
                request,
                "登入狀態已失效，未執行值班交接登打。",
                "login_failed",
            )
            return
        group_requests = self._duty_controller.handoff_group_submission_requests(
            session.user_id,
            session.password,
            request,
        )
        for group_request in group_requests:
            if self._duty_execution_controller.enqueue(group_request):
                if not self._external_return_queue_id(group_request):
                    self._duty_controller.mark_submission_enqueued(group_request.action_index)
        self._duty_controller.finish_handoff_preflight_group(request)

    @Slot(str)
    def _auto_logout(self, actor_no: str) -> None:
        session = self._session_state.session
        if session is None or str(session.actor_no) != str(actor_no):
            return
        self._tray_controller.notify("SinpoSmart", f"{actor_no} 值班交接已完成，自動登出")
        self._begin_session_logout("系統已自動登出")

    @Slot(str)
    def _force_logout(self, message: str) -> None:
        session = self._session_state.session
        if session is None or not session.verified:
            return
        self._send_operational_event(
            "login_expired",
            status="failed",
            trigger_type="login",
            error=message,
        )
        self._tray_controller.notify("SinpoSmart", message)
        self._begin_session_logout(message)

    @Slot()
    def _refresh_after_settings_save(self) -> None:
        if self._read_only_acceptance or self._worker_admissions_closed:
            return
        session = self._session_state.session
        if session is not None and session.verified:
            self._duty_controller.refresh_live_schedule(
                session.user_id,
                session.password,
                session.actor_no,
                actor_name=session.actor_name,
            )

    @Slot()
    def _check_scheduled_folders(self) -> None:
        if self._worker_admissions_closed or self._scheduled_folder_service is None:
            return
        folder = self._scheduled_folder_service.claim_due_folder(datetime.now())
        if folder is None:
            return
        self._scheduled_folder_request_id += 1
        request_id = self._scheduled_folder_request_id
        worker = ScheduledFolderWorker(
            request_id,
            self._scheduled_folder_service,
            folder,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(self._scheduled_folder_worker_finished)
        self._scheduled_folder_workers[request_id] = (thread, worker)
        thread.start()

    @Slot(int)
    def _scheduled_folder_worker_finished(self, request_id: int) -> None:
        worker_pair = self._scheduled_folder_workers.get(request_id)
        if worker_pair is None:
            return
        thread, _worker = worker_pair
        thread.quit()
        if not thread.wait(5_000):
            self._poll_scheduled_folder_thread_finished(request_id)
            return
        self._scheduled_folder_thread_finished(request_id)
        thread.deleteLater()

    def _poll_scheduled_folder_thread_finished(self, request_id: int) -> None:
        worker_pair = self._scheduled_folder_workers.get(request_id)
        if worker_pair is None:
            return
        thread, _worker = worker_pair
        if not thread.isFinished():
            QTimer.singleShot(
                50,
                lambda: self._poll_scheduled_folder_thread_finished(request_id),
            )
            return
        self._scheduled_folder_thread_finished(request_id)
        thread.deleteLater()

    @Slot(int)
    def _scheduled_folder_thread_finished(self, request_id: int) -> None:
        worker_pair = self._scheduled_folder_workers.pop(request_id, None)
        if worker_pair is None:
            return

    @Slot()
    def shutdown(self) -> None:
        self._close_worker_admissions()
        for request_id, (thread, _worker) in tuple(self._scheduled_folder_workers.items()):
            thread.requestInterruption()
            thread.quit()
            if not thread.wait(10_000):
                thread.wait()
            self._scheduled_folder_thread_finished(request_id)
            thread.deleteLater()
        for request_id, (thread, _worker) in tuple(self._tomorrow_schedule_workers.items()):
            thread.requestInterruption()
            thread.quit()
            if not thread.wait(10_000):
                thread.wait()
            self._tomorrow_schedule_thread_finished(request_id)
            thread.deleteLater()
        self._allow_shutdown_operational_sync = True
        self._finalize_active_tool_runs_for_shutdown()
        self._allow_shutdown_operational_sync = False
        self._duty_execution_controller.shutdown()
        self._duty_controller.shutdown()
        self._duty_sheet_controller.shutdown()
        self._rest_monthly_controller.shutdown()
        self._daily_vehicle_controller.shutdown()
        self._rescue_video_controller.shutdown()
        self._session_controller.shutdown()
        self._update_controller.shutdown()
        self._operational_sync_shutting_down = True
        for request_id, (thread, _worker) in tuple(self._operational_sync_workers.items()):
            thread.quit()
            if not thread.wait(60_000):
                thread.wait()
            self._operational_sync_thread_finished(request_id)
            thread.deleteLater()
        self._drain_queued_operational_sync()
        self._tray_controller.shutdown()


def shift_roc_date(target_roc_date: str, days: int) -> str:
    value = "".join(ch for ch in str(target_roc_date or "") if ch.isdigit())
    if len(value) != 7:
        raise ValueError("民國日期格式錯誤")
    year = int(value[:3]) + 1911
    shifted = date(year, int(value[3:5]), int(value[5:7])) + timedelta(days=int(days))
    return f"{shifted.year - 1911:03d}{shifted.month:02d}{shifted.day:02d}"


def clamp_audit_roc_date(target_roc_date: str, today: date | None = None) -> str:
    """Keep audit lookup within the legacy upper bound of tomorrow."""
    normalized = shift_roc_date(target_roc_date, 0)
    calendar_day = today or date.today()
    today_roc_date = f"{calendar_day.year - 1911:03d}{calendar_day.month:02d}{calendar_day.day:02d}"
    return min(normalized, shift_roc_date(today_roc_date, 1))


def actor_no_from_schedule(schedule_data: Mapping, actor_name: str) -> str:
    """Resolve one authenticated name against the existing duty-sheet staff map."""

    normalized_name = "".join(str(actor_name or "").split())
    today = schedule_data.get("today", {}) if isinstance(schedule_data, Mapping) else {}
    staff = today.get("staff", {}) if isinstance(today, Mapping) else {}
    if not normalized_name or not isinstance(staff, Mapping):
        return ""
    matches = [
        str(actor_no or "").strip()
        for actor_no, info in staff.items()
        if isinstance(info, Mapping)
        and "".join(str(info.get("name", "") or "").split()) == normalized_name
    ]
    return matches[0] if len(matches) == 1 else ""


def duty_identity_label(schedule_data: Mapping, actor_no: str, fallback: str = "") -> str:
    """Return the finalized legacy GUI identity label for the login status row."""

    actor_no = str(actor_no or "").strip()
    for day_name in ("today", "yesterday"):
        day = schedule_data.get(day_name, {}) if isinstance(schedule_data, Mapping) else {}
        staff = day.get("staff", {}) if isinstance(day, Mapping) else {}
        info = staff.get(actor_no, {}) if isinstance(staff, Mapping) else {}
        if not isinstance(info, Mapping):
            continue
        name = str(info.get("name", "") or "").strip()
        role = str(info.get("role", "") or "").strip()
        if role and name:
            return f"{role} {name}"
        if name:
            return name
    return str(fallback or "").strip() or (f"{actor_no}番" if actor_no else "-")


def duty_shift_label(schedule_data: Mapping, actor_no: str) -> str:
    """Mirror the finalized legacy GUI duty-span label."""

    actor_no = str(actor_no or "").strip()
    today = schedule_data.get("today", {}) if isinstance(schedule_data, Mapping) else {}
    rows = today.get("rows", []) if isinstance(today, Mapping) else []
    spans: list[tuple[int, int]] = []
    overnight_start: int | None = None
    overnight_end: int | None = None
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        columns = row.get("columns", {})
        duty_people = columns.get("值班", []) if isinstance(columns, Mapping) else []
        if actor_no not in [str(value) for value in duty_people]:
            continue
        match = re.match(r"(\d{1,2})[~～-](\d{1,2})", str(row.get("slot", "")))
        if not match:
            continue
        start, end = int(match.group(1)), int(match.group(2))
        if end <= start:
            return f"{start:02d} - {end:02d}"
        if start >= 22:
            overnight_start = start if overnight_start is None else min(overnight_start, start)
            continue
        if end <= 8:
            overnight_end = end if overnight_end is None else max(overnight_end, end)
            continue
        spans.append((start, end))
    if overnight_start is not None and overnight_end is not None:
        return f"{overnight_start:02d} - {overnight_end:02d}"
    if not spans:
        return "今日無值班時段"
    return f"{min(item[0] for item in spans):02d} - {max(item[1] for item in spans):02d}"


def operational_staff_from_schedule(schedule_data: Mapping) -> dict[str, dict]:
    """Combine the legacy yesterday/today staff maps used by event labels."""
    today = schedule_data.get("today", {}) if isinstance(schedule_data, Mapping) else {}
    yesterday = schedule_data.get("yesterday", {}) if isinstance(schedule_data, Mapping) else {}
    today_staff = today.get("staff", {}) if isinstance(today, Mapping) else {}
    yesterday_staff = yesterday.get("staff", {}) if isinstance(yesterday, Mapping) else {}
    return {
        str(number): dict(info)
        for number, info in {**yesterday_staff, **today_staff}.items()
        if isinstance(info, Mapping)
    }


def operational_person_label(number: str, staff: Mapping[str, Mapping]) -> str:
    """Build NAS target labels as number-plus-name without role titles."""
    targets = [
        target.strip()
        for target in str(number or "").replace("，", ",").split(",")
        if target.strip()
    ]
    labels = []
    for target in targets:
        info = staff.get(target, {}) if isinstance(staff, Mapping) else {}
        name = str(info.get("name", "") or "").strip() if isinstance(info, Mapping) else ""
        labels.append(f"{target}番 {name}" if name else f"{target}番")
    return "、".join(labels)
