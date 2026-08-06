# -*- coding: utf-8 -*-
"""Single QML context facade for the first Qt migration slice."""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QObject, Property, QThread, QTimer, Signal, Slot
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
    nativeTitleBarRequested = Signal(QObject)

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
        self._last_login_actor_no = ""
        self._last_login_user_id = ""
        self._last_login_display_name = ""
        self._provisional_actor_no = ""
        self._actor_identity_pending = False
        self._pending_fire_day_refresh = ""
        self._operational_staff: dict[str, dict] = {}
        self._last_hourly_refresh_key = ""
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
        self._duty_controller.dueTasksAvailable.connect(self._enqueue_due_tasks)
        self._duty_controller.autoLogoutRequested.connect(self._auto_logout)
        self._duty_controller.reloginRequired.connect(self._force_logout)
        self._duty_controller.manualSubmissionRequested.connect(self._enqueue_manual_tasks)
        self._work_log_settings_controller.settingsSaved.connect(self._refresh_after_settings_save)
        self._duty_execution_controller.actionStarted.connect(self._duty_controller.mark_submission_enqueued)
        self._duty_execution_controller.actionFinished.connect(self._duty_controller.handle_submission_result)
        self._duty_execution_controller.actionFailed.connect(self._duty_controller.handle_submission_failure)
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
            lambda mode: self._tool_run_started("rescue_video", "行車紀錄器（BETA）", mode=mode)
        )
        self._rescue_video_controller.runSucceeded.connect(
            lambda message: self._tool_run_finished("rescue_video", "行車紀錄器（BETA）", message)
        )
        self._rescue_video_controller.runFailed.connect(
            lambda mode, message: self._tool_run_failed(
                "rescue_video",
                "行車紀錄器（BETA）",
                message,
                mode=mode,
            )
        )
        self._duty_execution_controller.actionStarted.connect(
            self._notify_duty_action_started
        )
        self._duty_execution_controller.submissionQueued.connect(self._submission_queued)
        self._duty_execution_controller.submissionFinished.connect(self._submission_finished)
        self._duty_execution_controller.submissionFailed.connect(self._submission_failed)

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
            self._tray_controller.notify("SinpoSmart", self._diagnostics_status)
            return
        self._diagnostics_status = f"問題包已匯出：{package_path.name}"
        self.diagnosticsChanged.emit()
        self._tray_controller.notify("SinpoSmart", self._diagnostics_status)

    @Slot(result=bool)
    def recordUpdateLogout(self) -> bool:
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
            immediate=True,
        )
        return True

    @Slot(int)
    def shiftAuditDate(self, days: int) -> None:
        target = shift_roc_date(self._duty_controller.targetDateText or business_roc_date(), int(days))
        self.refreshAuditDate(target)

    @Slot()
    def openAuditMode(self) -> None:
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
            return False
        session = self._session_state.session
        if session is None or not session.verified:
            return False
        try:
            target_roc_date = clamp_audit_roc_date(
                self._duty_controller.targetDateText or business_roc_date()
            )
        except ValueError:
            return False
        return self._duty_controller.refresh_live_schedule(
            session.user_id,
            session.password,
            session.actor_no,
            target_roc_date=target_roc_date,
            actor_name=session.actor_name,
            publish_events=False,
            allow_auto_execution=False,
        )

    @Slot()
    def returnToDutySchedule(self) -> None:
        self._duty_mode_active = True
        if (
            self._duty_controller.isPreviewLoaded
            or self._duty_controller.targetDateText != business_roc_date()
        ):
            self.refreshAuditDate(business_roc_date())

    def _sync_session_actor(self) -> None:
        previous_actor_no = self._synced_actor_no
        previous_user_id = self._synced_user_id
        logged_in = self._session_controller.isLoggedIn
        actor_no = self._session_controller.actorNo if logged_in else ""
        user_id = self._session_controller.userId if logged_in else ""
        if actor_no == self._synced_actor_no and user_id == self._synced_user_id:
            return
        self._synced_actor_no = actor_no
        self._synced_user_id = user_id
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
            self._duty_controller.refresh_live_schedule(
                session.user_id,
                session.password,
                provisional_actor_no,
                actor_name=session.actor_name,
            )
        elif previous_actor_no:
            self._send_operational_event(
                "logout",
                status="ok",
                trigger_type="logout",
                actor_no=previous_actor_no,
                user_id=previous_user_id,
                display_name=self._last_login_display_name,
            )

    @Slot(bool)
    def setDutyModeActive(self, active: bool) -> None:
        self._duty_mode_active = bool(active)

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
            self._send_operational_event(
                "schedule_snapshot",
                status="ok",
                trigger_type="schedule",
                snapshot={
                    "paths": schedule_paths,
                    "days": schedule_days,
                },
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
        if self._read_only_acceptance:
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

        if self._read_only_acceptance or self._tomorrow_schedule_workers:
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
        worker.finished.connect(self._tomorrow_schedule_worker_finished)
        self._tomorrow_schedule_workers[request_id] = (thread, worker)
        thread.start()

    @Slot(int, str, object)
    def _tomorrow_schedule_succeeded(self, request_id: int, _actor_no: str, snapshot) -> None:
        if request_id not in self._tomorrow_schedule_workers:
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
        if request_id not in self._tomorrow_schedule_workers:
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
        if not thread.wait(5_000):
            return
        self._tomorrow_schedule_workers.pop(request_id, None)
        thread.deleteLater()

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

    @staticmethod
    def _format_duty_notification(
        action: Mapping,
        staff: Mapping[str, Mapping],
        outcome: str,
    ) -> str:
        """Keep duty notifications specific enough for parallel submissions."""

        kind = "出入" if action.get("kind") == "entry_log" else "工作"
        summary = action_summary(action) or "勤務登打"
        target = target_short_label(action, staff)
        target_text = f" {target}" if target and target != "-" else ""
        return f"{kind}｜{summary}{target_text}｜{outcome}"

    @Slot(int)
    def _notify_duty_action_started(self, action_index: int) -> None:
        actions = self._duty_controller._actions
        if not 0 <= action_index < len(actions):
            return
        message = self._format_duty_notification(
            actions[action_index],
            self._operational_staff,
            "開始登打",
        )
        self._tray_controller.notify("SinpoSmart", message)

    @Slot(object)
    def _submission_queued(self, request: DutySubmissionRequest) -> None:
        action = self._submission_action(request)
        self._send_operational_event(
            "action_queued",
            status="pending_write_automation",
            trigger_type=request.trigger_type,
            action=action,
            snapshot={
                "action_index": request.action_index,
                "completion_key": action_completion_key(action),
            },
        )

    @Slot(object, object)
    def _submission_finished(
        self,
        request: DutySubmissionRequest,
        result: DutySubmissionResult,
    ) -> None:
        action = self._submission_action(request, result)
        self._send_operational_event(
            "action_result",
            status=result.status,
            trigger_type=request.trigger_type,
            action=action,
            result_ref=Path(result.result_path).name,
            snapshot={
                "action_index": request.action_index,
                "completion_key": action_completion_key(action),
            },
        )
        outcome = "登打完成" if result.status == "submitted" else "已有資料，略過"
        self._tray_controller.notify(
            "SinpoSmart",
            self._format_duty_notification(action, self._operational_staff, outcome),
        )

    @Slot(object, str, str, str)
    def _submission_failed(
        self,
        request: DutySubmissionRequest,
        message: str,
        error_code: str,
        result_path: str,
    ) -> None:
        action = self._submission_action(request)
        self._send_operational_event(
            "action_result",
            status="failed",
            trigger_type=request.trigger_type,
            action=action,
            error=message,
            result_ref=Path(result_path).name if result_path else "",
            snapshot={
                "action_index": request.action_index,
                "completion_key": action_completion_key(action),
                "error_code": error_code,
            },
        )
        detail = str(message or "登打失敗").strip()
        self._tray_controller.notify(
            "SinpoSmart",
            self._format_duty_notification(
                action,
                self._operational_staff,
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
                    session_actor=self._session_controller.actorNo,
                    session_verified=self._session_controller.isLoggedIn,
                )
            )
        except DiagnosticExportError as exc:
            self._diagnostics_status = str(exc)
        else:
            self._diagnostics_status = f"問題包已匯出：{package_path.name}"
            self._tray_controller.notify("SinpoSmart", self._diagnostics_status)
        self.diagnosticsChanged.emit()

    def _tool_run_started(self, tool_name: str, tool_label: str, *, mode: str = "") -> None:
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

    def _tool_run_finished(self, tool_name: str, tool_label: str, message: str) -> None:
        self._tool_controller.record_finished(tool_name, "completed", message)
        self._send_operational_event(
            "tool_action_finished",
            status="completed",
            trigger_type="tool_finish",
            content=message,
            snapshot={"tool_name": tool_name, "tool_label": tool_label},
        )
        self._tray_controller.notify("SinpoSmart", message)

    def _tool_run_failed(
        self,
        tool_name: str,
        tool_label: str,
        message: str,
        *,
        mode: str = "",
    ) -> None:
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
        self._tray_controller.notify("SinpoSmart", message)

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
        self._operational_sync_request_id += 1
        request_id = self._operational_sync_request_id
        request = (
            request_id,
            operation,
            record_type,
            dict(fields or {}),
            dict(schedule_data or {}),
        )
        if operation != "event":
            self._launch_operational_sync(request)
            return
        self._operational_sync_queue.append(request)
        self._start_next_operational_sync()

    def _start_next_operational_sync(self) -> None:
        if (
            self._operational_sync_shutting_down
            or any(
                worker.operation == "event"
                for _thread, worker in self._operational_sync_workers.values()
            )
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
            return
        self._operational_sync_workers.pop(request_id, None)
        thread.deleteLater()
        self._start_next_operational_sync()

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
        if self._read_only_acceptance:
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
                self._duty_controller.mark_submission_enqueued(request.action_index)

    @Slot(str)
    def _auto_logout(self, actor_no: str) -> None:
        session = self._session_state.session
        if session is None or str(session.actor_no) != str(actor_no):
            return
        self._tray_controller.notify("SinpoSmart", f"{actor_no} 值班交接已完成，自動登出")
        self._session_controller.systemLogout("系統已自動登出")

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
        self._session_controller.systemLogout(message)

    @Slot()
    def _refresh_after_settings_save(self) -> None:
        if self._read_only_acceptance:
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
        if self._scheduled_folder_service is None:
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
            return
        self._scheduled_folder_workers.pop(request_id, None)
        thread.deleteLater()

    @Slot()
    def shutdown(self) -> None:
        self._hourly_refresh_timer.stop()
        self._board_retry_timer.stop()
        self._tomorrow_schedule_timer.stop()
        self._operational_sync_shutting_down = True
        if self._scheduled_folder_timer is not None:
            self._scheduled_folder_timer.stop()
        for request_id, (thread, _worker) in tuple(self._scheduled_folder_workers.items()):
            thread.requestInterruption()
            thread.quit()
            if thread.wait(10_000):
                self._scheduled_folder_workers.pop(request_id, None)
                thread.deleteLater()
        for request_id, (thread, _worker) in tuple(self._tomorrow_schedule_workers.items()):
            thread.requestInterruption()
            thread.quit()
            if thread.wait(10_000):
                self._tomorrow_schedule_workers.pop(request_id, None)
                thread.deleteLater()
        for request_id, (thread, _worker) in tuple(self._operational_sync_workers.items()):
            thread.quit()
            if thread.wait(60_000):
                self._operational_sync_workers.pop(request_id, None)
                thread.deleteLater()
        self._drain_queued_operational_sync()
        self._tray_controller.shutdown()
        self._update_controller.shutdown()
        self._duty_sheet_controller.shutdown()
        self._rest_monthly_controller.shutdown()
        self._daily_vehicle_controller.shutdown()
        self._rescue_video_controller.shutdown()
        self._duty_execution_controller.shutdown()
        self._duty_controller.shutdown()
        self._session_controller.shutdown()


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
    """Match the legacy backend event target label without exposing UI widgets."""
    number = str(number or "").strip()
    if not number:
        return ""
    info = staff.get(number, {}) if isinstance(staff, Mapping) else {}
    name = str(info.get("name", "") or "").strip() if isinstance(info, Mapping) else ""
    role = str(info.get("role", "") or "").strip() if isinstance(info, Mapping) else ""
    if name and role:
        return f"{number}番 {name}（{role}）"
    if name:
        return f"{number}番 {name}"
    return f"{number}番"
