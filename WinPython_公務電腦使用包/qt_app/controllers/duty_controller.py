# -*- coding: utf-8 -*-
"""QML-facing clock and duty task model shell."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from PySide6.QtCore import QDateTime, QObject, Property, QThread, QTimer, QUrl, Signal, Slot

from compare_rehearsal_records import build_case_work_audits
from app_core.duty_task_projection import (
    DueTaskSelectionState,
    DutyTaskProjectionState,
    action_completion_key,
    action_summary,
    action_datetime,
    build_schedule_comparisons,
    is_auto_duty_action,
    next_duty_task_text,
    project_audit_tasks,
    project_duty_tasks,
    select_due_task_indices,
)
from app_core.schedule_repository import ScheduleRepository, ScheduleSnapshot, business_roc_date
from app_core.duty_submission_service import DutySubmissionRequest
from app_core.schedule_capture_service import ScheduleCaptureRequest, ScheduleCaptureService
from qt_app.models.duty_task_model import DutyTaskListModel
from qt_app.workers.schedule_load_worker import ScheduleLoadWorker
from qt_app.workers.schedule_capture_worker import ScheduleCaptureWorker


class DutyController(QObject):
    clockChanged = Signal()
    scheduleChanged = Signal()
    dueTasksAvailable = Signal(object)
    autoLogoutRequested = Signal(str)
    reloginRequired = Signal(str)
    manualSubmissionConfirmationRequested = Signal()
    manualSubmissionRequested = Signal(object)
    liveScheduleCaptured = Signal(object)
    liveSnapshotCaptured = Signal(object)
    liveCaptureFailed = Signal(str, str)
    cachedScheduleLoaded = Signal(object)
    fireDayChanged = Signal(str)
    errorOccurred = Signal(str)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        repository: ScheduleRepository | None = None,
        capture_service: ScheduleCaptureService | None = None,
    ) -> None:
        super().__init__(parent)
        package_root = Path(__file__).resolve().parents[2]
        self._repository = repository or ScheduleRepository(package_root / "runtime_outputs")
        self._capture_service = capture_service or ScheduleCaptureService(package_root)
        self._current_date_text = ""
        self._current_time_text = ""
        self._observed_fire_day = business_roc_date()
        self._target_date_text = ""
        self._schedule_status = "尚未登入"
        self._preview_loaded = False
        self._actor_no = ""
        self._actions: list[dict[str, Any]] = []
        self._schedule_data: dict[str, Any] = {}
        self._staff: dict[str, dict[str, Any]] = {}
        self._comparisons: dict[int, dict[str, Any]] = {}
        self._audit_kind_filter = "全部"
        self._audit_status_filter = "需處理"
        self._audit_only_actor = False
        self._audit_summary_counts = {"todo": 0, "review": 0, "ready": 0, "done": 0}
        self._due_task_indices: list[int] = []
        self._executed_indices: set[int] = set()
        self._submitting_indices: set[int] = set()
        self._manual_paused_indices: set[int] = set()
        self._blocked_indices: set[int] = set()
        self._retry_after: dict[int, datetime] = {}
        self._selected_indices: set[int] = set()
        self._pending_manual_indices: list[int] = []
        self._manual_confirmation_summary = ""
        self._auto_execution_enabled = False
        self._login_started_at: datetime | None = None
        self._auto_logout_actor_no = ""
        self._auto_logout_handoff_at: datetime | None = None
        self._auto_logout_deadline: datetime | None = None
        self._auto_logout_timer = QTimer(self)
        self._auto_logout_timer.setSingleShot(True)
        self._auto_logout_timer.timeout.connect(self._check_auto_logout)
        self._schedule_request_id = 0
        self._active_schedule_request = 0
        self._schedule_workers: dict[int, tuple[QThread, ScheduleLoadWorker]] = {}
        self._capture_request_id = 0
        self._active_capture_request = 0
        self._capture_workers: dict[int, tuple[QThread, ScheduleCaptureWorker]] = {}
        self._capture_targets: dict[int, str] = {}
        self._capture_schedule_ready_ids: set[int] = set()
        self._capture_publish_events: dict[int, bool] = {}
        self._capture_auto_execution: dict[int, bool] = {}
        self._comparison_request_id = 0
        self._comparison_workers: dict[int, tuple[QThread, ScheduleCaptureWorker]] = {}
        self._comparison_targets: dict[int, str] = {}
        self._task_model = DutyTaskListModel(self)
        self._audit_model = DutyTaskListModel(self)
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.timeout.connect(self._refresh_due_tasks)
        self._update_clock()
        self._clock_timer.start()

    @Property(str, notify=clockChanged)
    def currentDateText(self) -> str:
        return self._current_date_text

    @Property(str, notify=clockChanged)
    def currentTimeText(self) -> str:
        return self._current_time_text

    @Property(QObject, constant=True)
    def taskModel(self) -> DutyTaskListModel:
        return self._task_model

    @Property(QObject, constant=True)
    def auditModel(self) -> DutyTaskListModel:
        return self._audit_model

    @Property(str, notify=scheduleChanged)
    def targetDateText(self) -> str:
        return self._target_date_text

    @Property("QStringList", notify=scheduleChanged)
    def auditDateOptions(self) -> list[str]:
        available_dates = getattr(self._repository, "available_dates", None)
        values = list(available_dates() if callable(available_dates) else [])
        if self._target_date_text and self._target_date_text not in values:
            values.append(self._target_date_text)
        return sorted(set(values))

    @Property(str, notify=scheduleChanged)
    def scheduleStatus(self) -> str:
        return self._schedule_status

    @Property(bool, notify=scheduleChanged)
    def isRefreshing(self) -> bool:
        return bool(self._schedule_workers or self._capture_workers or self._comparison_workers)

    @Property(bool, notify=scheduleChanged)
    def isPreviewLoaded(self) -> bool:
        return self._preview_loaded

    @Property(str, notify=clockChanged)
    def nextTaskText(self) -> str:
        return next_duty_task_text(self._actions, self._projection_state())

    @Property(str, notify=scheduleChanged)
    def auditKindFilter(self) -> str:
        return self._audit_kind_filter

    @Property(str, notify=scheduleChanged)
    def auditStatusFilter(self) -> str:
        return self._audit_status_filter

    @Property(bool, notify=scheduleChanged)
    def auditOnlyActor(self) -> bool:
        return self._audit_only_actor

    @Property(int, notify=scheduleChanged)
    def auditTodoCount(self) -> int:
        return self._audit_summary_counts["todo"]

    @Property(int, notify=scheduleChanged)
    def auditReviewCount(self) -> int:
        return self._audit_summary_counts["review"]

    @Property(int, notify=scheduleChanged)
    def auditReadyCount(self) -> int:
        return self._audit_summary_counts["ready"]

    @Property(int, notify=scheduleChanged)
    def auditDoneCount(self) -> int:
        return self._audit_summary_counts["done"]

    @Property(int, notify=scheduleChanged)
    def dueTaskCount(self) -> int:
        return len(self._due_task_indices)

    @Property(int, notify=scheduleChanged)
    def selectedTaskCount(self) -> int:
        return len(self._selected_indices)

    @Property(bool, notify=scheduleChanged)
    def canAdjustSelectedSchedule(self) -> bool:
        """Whether every selected task remains eligible for schedule controls."""

        return self._can_adjust_selected_schedule()

    @Property(bool, notify=scheduleChanged)
    def canManualSubmitSelected(self) -> bool:
        """Whether every selected task can be submitted manually."""

        return self._can_manually_submit_selected()

    @Property(str, notify=scheduleChanged)
    def manualConfirmationSummary(self) -> str:
        return self._manual_confirmation_summary

    @Property(str, notify=scheduleChanged)
    def automationStatus(self) -> str:
        if not self._actor_no:
            return "登入後才會監看到點任務"
        if self._capture_workers:
            return "勤務更新中；自動登打暫停"
        if self._schedule_workers:
            return "勤務資料載入中；自動登打暫停"
        if self._preview_loaded:
            return "預演模式；自動登打已停用"
        if self._auto_execution_enabled:
            return f"偵測到 {len(self._due_task_indices)} 筆到點任務；自動登打監看中"
        if self._due_task_indices:
            return f"偵測到 {len(self._due_task_indices)} 筆到點任務；自動登打目前已暫停"
        return "排程監看目前已暫停"

    @Slot(str)
    def setAuditKindFilter(self, value: str) -> None:
        value = value if value in ("全部", "工作", "出入", "案件工作") else "全部"
        if value != self._audit_kind_filter:
            self._audit_kind_filter = value
            self._refresh_projection()

    @Slot(str)
    def setAuditStatusFilter(self, value: str) -> None:
        allowed = (
            "需處理",
            "全部",
            "已登打",
            "手動",
            "尚未到點",
            "疑似異動",
            "時間近似",
            "人工確認",
        )
        value = value if value in allowed else "全部"
        if value != self._audit_status_filter:
            self._audit_status_filter = value
            self._refresh_projection()

    @Slot(bool)
    def setAuditOnlyActor(self, value: bool) -> None:
        value = bool(value)
        if value != self._audit_only_actor:
            self._audit_only_actor = value
            self._refresh_projection()

    @Slot(int)
    def toggleTaskSelection(self, action_index: int) -> None:
        if not 0 <= action_index < len(self._actions):
            return
        if action_index in self._selected_indices:
            self._selected_indices.remove(action_index)
        else:
            self._selected_indices.add(action_index)
        self._refresh_projection()

    @Slot()
    def pauseSelectedTasks(self) -> None:
        if not self._can_adjust_selected_schedule():
            return
        paused = 0
        for index in tuple(self._selected_indices):
            if not 0 <= index < len(self._actions):
                continue
            action = self._actions[index]
            comparison = self._comparisons.get(index, {})
            if (
                str(action.get("actor", "") or "") == self._actor_no
                and action.get("kind") in ("work_log", "entry_log")
                and comparison.get("group") not in ("done", "manual", "near", "adjust", "review")
                and index not in self._executed_indices
                and index not in self._submitting_indices
            ):
                self._manual_paused_indices.add(index)
                paused += 1
        self._selected_indices.clear()
        self._schedule_status = f"已手動暫停 {paused} 筆任務" if paused else "選取任務無法手動暫停"
        self._refresh_projection()

    @Slot()
    def resumeSelectedTasks(self) -> None:
        if not self._can_adjust_selected_schedule():
            return
        resumed = 0
        for index in tuple(self._selected_indices):
            if index in self._manual_paused_indices:
                self._manual_paused_indices.remove(index)
                resumed += 1
        self._selected_indices.clear()
        self._schedule_status = f"已繼續排程 {resumed} 筆任務" if resumed else "選取任務沒有手動暫停狀態"
        self._refresh_projection()

    @Slot()
    def prepareManualSubmission(self) -> None:
        if not self._can_manually_submit_selected():
            self._schedule_status = "選取項目包含已登打或不可手動登打的勤務"
            self._refresh_projection()
            return
        ready: list[int] = []
        for index in sorted(self._selected_indices):
            if not 0 <= index < len(self._actions):
                continue
            action = self._actions[index]
            comparison = self._comparisons.get(index, {})
            is_manual_external_review = (
                comparison.get("group") == "review"
                and str(action.get("source", "") or "").startswith("外勤")
            )
            if (
                action.get("kind") in ("work_log", "entry_log")
                and index not in self._submitting_indices
                and index not in self._executed_indices
                and (
                    comparison.get("group") not in ("done", "near", "review")
                    or is_manual_external_review
                )
            ):
                ready.append(index)
        if not ready:
            self._schedule_status = "選取任務無法手動登打"
            self._refresh_projection()
            return
        summaries = "\n".join(f"• {action_summary(self._actions[index])}" for index in ready[:8])
        if len(ready) > 8:
            summaries += f"\n…另 {len(ready) - 8} 筆"
        self._pending_manual_indices = ready
        self._manual_confirmation_summary = (
            f"將登打勤務系統 {len(ready)} 筆：\n{summaries}\n\n"
            "將使用按下確認時的當下時間登打。"
        )
        self.scheduleChanged.emit()
        self.manualSubmissionConfirmationRequested.emit()

    @Slot()
    def confirmManualSubmission(self) -> None:
        if not self._pending_manual_indices:
            return
        indices = list(self._pending_manual_indices)
        self._pending_manual_indices.clear()
        self._manual_confirmation_summary = ""
        self._selected_indices.clear()
        self.scheduleChanged.emit()
        self.manualSubmissionRequested.emit(indices)

    @Slot()
    def cancelManualSubmission(self) -> None:
        self._pending_manual_indices.clear()
        self._manual_confirmation_summary = ""
        self._schedule_status = "已取消手動登打"
        self.scheduleChanged.emit()

    def _can_adjust_selected_schedule(self) -> bool:
        """Keep manual or external-review tasks out of automatic scheduling controls."""

        if not self._selected_indices:
            return False
        for index in self._selected_indices:
            if not 0 <= index < len(self._actions):
                return False
            action = self._actions[index]
            comparison = self._comparisons.get(index, {})
            if (
                str(action.get("actor", "") or "") != self._actor_no
                or action.get("kind") not in ("work_log", "entry_log")
                or not is_auto_duty_action(action)
                or comparison.get("group") in ("done", "manual", "near", "adjust", "review")
                or index in self._executed_indices
                or index in self._submitting_indices
            ):
                return False
        return True

    def _can_manually_submit_selected(self) -> bool:
        """Require all selected tasks to be manually eligible before enabling the action."""

        return bool(self._selected_indices) and all(
            self._is_manual_submission_eligible(index) for index in self._selected_indices
        )

    def _is_manual_submission_eligible(self, index: int) -> bool:
        if not 0 <= index < len(self._actions):
            return False
        action = self._actions[index]
        comparison = self._comparisons.get(index, {})
        is_manual_external_review = (
            comparison.get("group") == "review"
            and str(action.get("source", "") or "").startswith("外勤")
        )
        return (
            action.get("kind") in ("work_log", "entry_log")
            and index not in self._submitting_indices
            and index not in self._executed_indices
            and (
                comparison.get("group") not in ("done", "near", "review")
                or is_manual_external_review
            )
        )

    def set_actor_no(self, actor_no: str) -> None:
        actor_no = str(actor_no or "").strip()
        if actor_no == self._actor_no:
            return
        previous_actor = self._actor_no
        self._actor_no = actor_no
        if actor_no and actor_no != previous_actor:
            self._login_started_at = datetime.now()
        if not actor_no:
            self._schedule_status = "尚未登入"
            self._selected_indices.clear()
            self._manual_paused_indices.clear()
            self._login_started_at = None
            self._cancel_auto_logout()
        self._refresh_projection()

    def enable_auto_execution(self) -> None:
        if self._auto_execution_enabled:
            return
        self._auto_execution_enabled = True
        self._refresh_due_tasks(force_emit=True)
        self.scheduleChanged.emit()

    def disable_auto_execution(self) -> None:
        if not self._auto_execution_enabled:
            return
        self._auto_execution_enabled = False
        self.scheduleChanged.emit()

    def refresh_live_schedule(
        self,
        user_id: str,
        password: str,
        actor_no: str,
        target_roc_date: str = "",
        actor_name: str = "",
        *,
        publish_events: bool = True,
        allow_auto_execution: bool = True,
    ) -> bool:
        if not user_id or not password or self._capture_workers:
            return False
        self.disable_auto_execution()
        self._preview_loaded = False
        self._capture_request_id += 1
        request_id = self._capture_request_id
        self._active_capture_request = request_id
        request = (
            ScheduleCaptureRequest(user_id, password, actor_no, target_roc_date, actor_name)
            if target_roc_date
            else self._capture_service.current_request(user_id, password, actor_no, actor_name)
        )
        worker = ScheduleCaptureWorker(request_id, self._capture_service, request)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._capture_progress)
        worker.scheduleReady.connect(self._capture_schedule_ready)
        worker.succeeded.connect(self._capture_succeeded)
        worker.failed.connect(self._capture_failed)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(self._capture_worker_finished)
        self._capture_workers[request_id] = (thread, worker)
        self._capture_targets[request_id] = request.target_roc_date
        self._capture_publish_events[request_id] = bool(publish_events)
        self._capture_auto_execution[request_id] = bool(allow_auto_execution)
        self._schedule_status = "正在即時更新勤務與比對資料…"
        self.scheduleChanged.emit()
        thread.start()
        return True

    def refresh_live_comparisons(
        self,
        user_id: str,
        password: str,
        actor_no: str,
        target_roc_date: str = "",
        actor_name: str = "",
    ) -> bool:
        """Refresh saved-record comparisons without replacing the loaded duty schedule."""

        if not user_id or not password or self._comparison_workers:
            return False
        target = str(target_roc_date or business_roc_date()).strip()
        self._comparison_request_id += 1
        request_id = self._comparison_request_id
        request = ScheduleCaptureRequest(user_id, password, actor_no, target, actor_name)
        worker = ScheduleCaptureWorker(
            request_id,
            self._capture_service,
            request,
            include_schedule=False,
            include_comparisons=True,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._comparison_capture_progress)
        worker.comparisonsReady.connect(self._comparisons_ready)
        worker.failed.connect(self._comparisons_failed)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(self._comparison_worker_finished)
        self._comparison_workers[request_id] = (thread, worker)
        self._comparison_targets[request_id] = target
        self._schedule_status = "正在更新已登打比對資料…"
        self.scheduleChanged.emit()
        thread.start()
        return True

    def due_submission_requests(
        self,
        user_id: str,
        password: str,
        indices: list[int],
    ) -> list[DutySubmissionRequest]:
        if not self._auto_execution_enabled or not user_id or not password:
            return []
        return [
            DutySubmissionRequest(user_id, password, index, self._schedule_data, trigger_type="due")
            for index in indices
            if index in self._due_task_indices and 0 <= index < len(self._actions)
        ]

    def manual_submission_requests(
        self,
        user_id: str,
        password: str,
        indices: list[int],
        *,
        submit_at: datetime | None = None,
    ) -> list[DutySubmissionRequest]:
        if not user_id or not password:
            return []
        current = submit_at or datetime.now()
        current_time = current.strftime("%H:%M")
        submit_target_date = f"{current.year - 1911:03d}{current.month:02d}{current.day:02d}"
        requests: list[DutySubmissionRequest] = []
        for index in indices:
            if not 0 <= index < len(self._actions):
                continue
            action = dict(self._actions[index])
            fields = dict(action.get("fields", {}))
            if action.get("kind") == "work_log":
                fields["工作時間"] = current_time
            elif action.get("kind") == "entry_log":
                fields["登打時間"] = current_time
                fields["系統寫入時間"] = current_time
            else:
                continue
            action["fields"] = fields
            action["time"] = current_time
            action["submit_target_date"] = submit_target_date
            actions = [dict(item) for item in self._actions]
            actions[index] = action
            schedule_data = dict(self._schedule_data)
            schedule_data["actions"] = actions
            requests.append(
                DutySubmissionRequest(
                    user_id,
                    password,
                    index,
                    schedule_data,
                    trigger_type="manual",
                )
            )
        return requests

    def mark_submission_enqueued(self, action_index: int) -> None:
        if not 0 <= action_index < len(self._actions):
            return
        self._submitting_indices.add(action_index)
        self._refresh_projection()

    @Slot(int, str, str, str)
    def handle_submission_result(
        self,
        action_index: int,
        status: str,
        message: str,
        _result_path: str,
    ) -> None:
        self._submitting_indices.discard(action_index)
        if not 0 <= action_index < len(self._actions):
            return
        if status in ("submitted", "skipped_duplicate"):
            self._executed_indices.add(action_index)
            self._comparisons[action_index] = {
                "compare": "已登打" if status == "submitted" else "已存在",
                "group": "done",
                "matched": [],
            }
            self._retry_after.pop(action_index, None)
            self._schedule_auto_logout_if_needed(action_index)
        elif status == "review_required":
            self._blocked_indices.add(action_index)
            self._comparisons[action_index] = {"compare": "人工確認", "group": "review", "matched": []}
        elif status == "paused_external":
            self._retry_after[action_index] = datetime.now() + timedelta(minutes=1)
            self._comparisons[action_index] = {"compare": "未返隊，暫停登打", "group": "paused", "matched": []}
        else:
            self._retry_after[action_index] = datetime.now() + timedelta(seconds=30)
        self._schedule_status = message
        self._refresh_projection()

    @Slot(int, str, str)
    def handle_submission_failure(self, action_index: int, message: str, error_code: str) -> None:
        self._submitting_indices.discard(action_index)
        if error_code == "login_failed":
            self._retry_after.clear()
            self._schedule_status = message
            self._refresh_projection()
            self.errorOccurred.emit(message)
            self.reloginRequired.emit(message)
            return
        if 0 <= action_index < len(self._actions):
            self._retry_after[action_index] = datetime.now() + timedelta(minutes=1)
        self._schedule_status = message
        self._refresh_projection()
        self.errorOccurred.emit(message)

    def load_current_schedule(self) -> None:
        if self._schedule_workers:
            return
        self._start_schedule_load()

    def load_audit_schedule(self, target_roc_date: str) -> None:
        """Load a saved schedule and comparison snapshot without a web login."""

        if self._schedule_workers:
            return
        self._start_schedule_load(target_roc_date=target_roc_date)

    @Slot(QUrl)
    def loadPreviewFile(self, selected_file: QUrl) -> None:
        if self._schedule_workers:
            return
        if not selected_file.isLocalFile():
            self._schedule_status = "請選擇本機的 JSON 預演檔。"
            self.scheduleChanged.emit()
            self.errorOccurred.emit(self._schedule_status)
            return
        self._load_preview_path(Path(selected_file.toLocalFile()))

    @Slot(str)
    def loadPreviewPath(self, value: str) -> None:
        if self._schedule_workers:
            return
        preview_value = str(value or "").strip()
        if not preview_value:
            self._schedule_status = "請選擇本機的 JSON 預演檔。"
            self.scheduleChanged.emit()
            self.errorOccurred.emit(self._schedule_status)
            return
        self._load_preview_path(Path(preview_value).expanduser())

    @Slot(QUrl, result=str)
    def localPath(self, selected_file: QUrl) -> str:
        return selected_file.toLocalFile() if selected_file.isLocalFile() else ""

    def _load_preview_path(self, preview_path: Path) -> None:
        self.disable_auto_execution()
        self._start_schedule_load(preview_path)

    def _start_schedule_load(
        self,
        preview_path: Path | None = None,
        target_roc_date: str = "",
    ) -> None:
        self._schedule_request_id += 1
        request_id = self._schedule_request_id
        self._active_schedule_request = request_id

        worker = ScheduleLoadWorker(
            request_id,
            self._repository,
            preview_path,
            target_roc_date,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._schedule_loaded)
        worker.failed.connect(self._schedule_failed)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(self._schedule_worker_finished)
        self._schedule_workers[request_id] = (thread, worker)
        self._schedule_status = (
            "正在載入預演檔…"
            if preview_path is not None
            else f"正在載入 {target_roc_date} 審核資料…"
            if target_roc_date
            else "正在載入今日排程…"
        )
        self.scheduleChanged.emit()
        thread.start()

    @Slot()
    def shutdown(self) -> None:
        for request_id, (thread, _worker) in tuple(self._schedule_workers.items()):
            thread.requestInterruption()
            thread.quit()
            if thread.wait(10_000):
                self._schedule_workers.pop(request_id, None)
                thread.deleteLater()
        for request_id, (thread, _worker) in tuple(self._capture_workers.items()):
            thread.requestInterruption()
            thread.quit()
            if thread.wait(120_000):
                self._capture_workers.pop(request_id, None)
                self._capture_targets.pop(request_id, None)
                self._capture_publish_events.pop(request_id, None)
                self._capture_auto_execution.pop(request_id, None)
                thread.deleteLater()
        for request_id, (thread, _worker) in tuple(self._comparison_workers.items()):
            thread.requestInterruption()
            thread.quit()
            if thread.wait(120_000):
                self._comparison_workers.pop(request_id, None)
                self._comparison_targets.pop(request_id, None)
                thread.deleteLater()

    def replace_schedule_data(
        self,
        data: Mapping[str, Any],
        *,
        comparisons: Mapping[int, Mapping[str, Any]] | None = None,
        comparison_data: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        next_target_date = str(data.get("target_date", "") or "")
        same_schedule_date = bool(next_target_date and next_target_date == self._target_date_text)
        previous_completed_by_key = {
            action_completion_key(self._actions[index]): {
                **dict(self._comparisons.get(index, {})),
                "compare": str(self._comparisons.get(index, {}).get("compare", "已登打") or "已登打"),
                "group": "done",
            }
            for index in self._executed_indices
            if 0 <= index < len(self._actions)
        }
        actions = data.get("actions", [])
        today = data.get("today", {})
        yesterday = data.get("yesterday", {})
        today_staff = today.get("staff", {}) if isinstance(today, Mapping) else {}
        yesterday_staff = yesterday.get("staff", {}) if isinstance(yesterday, Mapping) else {}
        scheduled_actions = [dict(action) for action in actions] if isinstance(actions, list) else []
        existing_duplicate_keys = {
            str(action.get("duplicate_key", "") or "")
            for action in scheduled_actions
        }
        case_work_actions = [
            action
            for action in build_case_work_audits(dict(data))
            if str(action.get("duplicate_key", "") or "") not in existing_duplicate_keys
        ]
        self._actions = scheduled_actions + case_work_actions
        self._schedule_data = dict(data)
        self._schedule_data["actions"] = self._actions
        self._staff = {
            str(number): dict(info)
            for number, info in {**yesterday_staff, **today_staff}.items()
            if isinstance(info, Mapping)
        }
        self._target_date_text = next_target_date
        incoming_comparisons = {
            int(index): dict(comparison)
            for index, comparison in (comparisons or {}).items()
        }
        if comparison_data:
            incoming_comparisons = build_schedule_comparisons(
                self._schedule_data,
                self._actions,
                comparison_data,
            )
        elif case_work_actions:
            case_comparisons = build_schedule_comparisons(
                self._schedule_data,
                case_work_actions,
                {},
            )
            incoming_comparisons.update(
                {
                    len(scheduled_actions) + index: comparison
                    for index, comparison in case_comparisons.items()
                }
            )
        if same_schedule_date:
            incoming_comparisons.update(
                {
                    index: dict(self._comparisons[index])
                    for index in self._executed_indices
                    if index in self._comparisons and index < len(self._actions)
                }
            )
            carried_completed_indices = set(self._executed_indices)
        else:
            carried_completed_indices = {
                index
                for index, action in enumerate(self._actions)
                if action_completion_key(action) in previous_completed_by_key
            }
            incoming_comparisons.update(
                {
                    index: previous_completed_by_key[action_completion_key(action)]
                    for index, action in enumerate(self._actions)
                    if index in carried_completed_indices
                }
            )
        self._comparisons = incoming_comparisons
        self._selected_indices.clear()
        if not same_schedule_date:
            self._executed_indices = carried_completed_indices
            self._submitting_indices.clear()
            self._manual_paused_indices.clear()
            self._blocked_indices.clear()
            self._retry_after.clear()
        self._refresh_projection()

    def _projection_state(self) -> DutyTaskProjectionState:
        return DutyTaskProjectionState(
            actor_no=self._actor_no,
            target_roc_date=self._target_date_text,
            staff=self._staff,
            comparisons=self._comparisons,
            submitting_indices=frozenset(self._submitting_indices),
            manual_paused_indices=frozenset(self._manual_paused_indices),
            paused_indices=frozenset(self._blocked_indices),
            executed_indices=frozenset(self._executed_indices),
            selected_indices=frozenset(self._selected_indices),
        )

    def _refresh_projection(self) -> None:
        rows = project_duty_tasks(self._actions, self._projection_state())
        self._task_model.replace_tasks(rows)
        summary_rows = project_audit_tasks(
            self._actions,
            target_roc_date=self._target_date_text,
            staff=self._staff,
            comparisons=self._comparisons,
            actor_no=self._actor_no if self._audit_only_actor else "",
            kind_filter=self._audit_kind_filter,
            status_filter="全部",
        )
        counts = {"todo": 0, "review": 0, "ready": 0, "done": 0}
        for row in summary_rows:
            group = row.get("group", "")
            if group == "todo":
                counts["todo"] += 1
            elif group in ("review", "adjust", "manual"):
                counts["review"] += 1
            elif group == "future":
                counts["ready"] += 1
            elif group == "done":
                counts["done"] += 1
        self._audit_summary_counts = counts
        audit_rows = project_audit_tasks(
            self._actions,
            target_roc_date=self._target_date_text,
            staff=self._staff,
            comparisons=self._comparisons,
            actor_no=self._actor_no if self._audit_only_actor else "",
            kind_filter=self._audit_kind_filter,
            status_filter=self._audit_status_filter,
        )
        self._audit_model.replace_tasks(audit_rows)
        self._refresh_due_tasks(emit_signal=False)
        self.scheduleChanged.emit()

    def _refresh_due_tasks(self, *, emit_signal: bool = True, force_emit: bool = False) -> None:
        due = select_due_task_indices(
            self._actions,
            DueTaskSelectionState(
                actor_no=self._actor_no,
                target_roc_date=self._target_date_text,
                comparisons=self._comparisons,
                executed_indices=frozenset(self._executed_indices),
                submitting_indices=frozenset(self._submitting_indices),
                manual_paused_indices=frozenset(self._manual_paused_indices),
                blocked_indices=frozenset(self._blocked_indices),
                retry_after=self._retry_after,
            ),
        )
        if due == self._due_task_indices and not force_emit:
            return
        self._due_task_indices = due
        if emit_signal:
            self.scheduleChanged.emit()
        if self._auto_execution_enabled and due:
            self.dueTasksAvailable.emit(list(due))

    def _schedule_auto_logout_if_needed(self, action_index: int) -> None:
        action = self._actions[action_index]
        fields = action.get("fields", {})
        if not (
            action.get("kind") == "entry_log"
            and action.get("source") == "值班交接"
            and isinstance(fields, Mapping)
            and fields.get("出或入", "") == "值退"
        ):
            return
        handoff_at = action_datetime(action, self._target_date_text)
        if self._login_started_at is None or handoff_at < self._login_started_at:
            return
        self._auto_logout_actor_no = self._actor_no
        self._auto_logout_handoff_at = handoff_at
        self._auto_logout_deadline = handoff_at + timedelta(minutes=10)
        delay_ms = max(0, int((self._auto_logout_deadline - datetime.now()).total_seconds() * 1000))
        self._auto_logout_timer.start(delay_ms)

    @Slot()
    def _check_auto_logout(self) -> None:
        if not self._auto_logout_actor_no or self._auto_logout_handoff_at is None:
            return
        if self._actor_no != self._auto_logout_actor_no:
            self._cancel_auto_logout()
            return
        group = [
            index
            for index, action in enumerate(self._actions)
            if action.get("kind") in ("entry_log", "work_log")
            and is_auto_duty_action(action)
            and str(action.get("actor", "") or "") == self._auto_logout_actor_no
            and action_datetime(action, self._target_date_text) == self._auto_logout_handoff_at
        ]
        incomplete = [
            index
            for index in group
            if index not in self._executed_indices and self._comparisons.get(index, {}).get("group") != "done"
        ]
        if self._submitting_indices or self._manual_paused_indices or not group or incomplete:
            self._auto_logout_deadline = datetime.now() + timedelta(minutes=10)
            self._auto_logout_timer.start(10 * 60 * 1000)
            self._schedule_status = f"交接仍有 {len(incomplete)} 筆未完成，10 分鐘後再檢查自動登出"
            self.scheduleChanged.emit()
            return
        actor_no = self._auto_logout_actor_no
        self._cancel_auto_logout()
        self.autoLogoutRequested.emit(actor_no)

    def _cancel_auto_logout(self) -> None:
        self._auto_logout_timer.stop()
        self._auto_logout_actor_no = ""
        self._auto_logout_handoff_at = None
        self._auto_logout_deadline = None

    @Slot(int, object)
    def _schedule_loaded(self, request_id: int, snapshot: ScheduleSnapshot) -> None:
        if request_id != self._active_schedule_request:
            return
        worker_pair = self._schedule_workers.get(request_id)
        is_preview = bool(worker_pair and worker_pair[1].preview_path is not None)
        self._preview_loaded = is_preview
        if not snapshot.found:
            self.replace_schedule_data(
                {"target_date": snapshot.target_roc_date, "actions": []}
            )
            self._schedule_status = f"{snapshot.target_roc_date} 尚無排程資料"
        else:
            self.replace_schedule_data(
                snapshot.data,
                comparisons=snapshot.comparisons,
                comparison_data=snapshot.comparison_data,
            )
            if not is_preview:
                self.cachedScheduleLoaded.emit(dict(snapshot.data))
            self._schedule_status = (
                f"已載入預演檔 {snapshot.path.name}"
                if is_preview
                else f"已載入 {snapshot.path.name}"
            )
        self.scheduleChanged.emit()

    @Slot(int, str)
    def _schedule_failed(self, request_id: int, message: str) -> None:
        if request_id != self._active_schedule_request:
            return
        self._schedule_status = message
        self.scheduleChanged.emit()
        self.errorOccurred.emit(message)

    @Slot(int)
    def _schedule_worker_finished(self, request_id: int) -> None:
        worker_pair = self._schedule_workers.get(request_id)
        if worker_pair is None:
            return
        thread, _worker = worker_pair
        thread.quit()
        if not thread.wait(5_000):
            return
        self._schedule_workers.pop(request_id, None)
        thread.deleteLater()
        self.scheduleChanged.emit()

    @Slot(int, str)
    def _capture_progress(self, request_id: int, message: str) -> None:
        if request_id == self._active_capture_request:
            self._schedule_status = message
            self.scheduleChanged.emit()

    @Slot(int, str, object)
    def _capture_schedule_ready(self, request_id: int, actor_no: str, snapshot: ScheduleSnapshot) -> None:
        if request_id != self._active_capture_request:
            return
        self._capture_schedule_ready_ids.add(request_id)
        self._active_schedule_request = 0
        self._preview_loaded = False
        self.replace_schedule_data(
            snapshot.data,
            comparisons=snapshot.comparisons,
            comparison_data=snapshot.comparison_data,
        )
        captured_data = dict(snapshot.data)
        if snapshot.authenticated_actor_no:
            captured_data["_authenticated_actor"] = {
                "actor_no": snapshot.authenticated_actor_no,
                "actor_name": snapshot.authenticated_actor_name,
            }
        if self._capture_publish_events.get(request_id, True):
            self.liveScheduleCaptured.emit(captured_data)
            self.liveSnapshotCaptured.emit(snapshot)
        self._schedule_status = f"即時勤務資料已更新：{snapshot.path.name}；正在背景比對已登打資料…"
        if (
            self._capture_auto_execution.get(request_id, True)
            and snapshot.target_roc_date == business_roc_date()
            and self._actor_no
        ):
            self.enable_auto_execution()
        else:
            self.disable_auto_execution()
            self.scheduleChanged.emit()

    @Slot(int, str, object)
    def _capture_succeeded(self, request_id: int, actor_no: str, snapshot: ScheduleSnapshot) -> None:
        if request_id != self._active_capture_request:
            return
        schedule_was_ready = request_id in self._capture_schedule_ready_ids
        self._active_schedule_request = 0
        self._preview_loaded = False
        self.replace_schedule_data(
            snapshot.data,
            comparisons=snapshot.comparisons,
            comparison_data=snapshot.comparison_data,
        )
        publish_events = self._capture_publish_events.get(request_id, True)
        if not schedule_was_ready and publish_events:
            captured_data = dict(snapshot.data)
            if snapshot.authenticated_actor_no:
                captured_data["_authenticated_actor"] = {
                    "actor_no": snapshot.authenticated_actor_no,
                    "actor_name": snapshot.authenticated_actor_name,
                }
            self.liveScheduleCaptured.emit(captured_data)
            self.liveSnapshotCaptured.emit(snapshot)
        elif schedule_was_ready and publish_events:
            self.liveSnapshotCaptured.emit(
                ScheduleSnapshot(
                    snapshot.path,
                    snapshot.data,
                    snapshot.target_roc_date,
                    snapshot.comparisons,
                    comparison_data=snapshot.comparison_data,
                    authenticated_actor_no=snapshot.authenticated_actor_no,
                    authenticated_actor_name=snapshot.authenticated_actor_name,
                )
            )
        self._schedule_status = f"即時勤務資料已更新：{snapshot.path.name}"
        if (
            self._capture_auto_execution.get(request_id, True)
            and snapshot.target_roc_date == business_roc_date()
            and self._actor_no
        ):
            self.enable_auto_execution()
        else:
            self.disable_auto_execution()
            self.scheduleChanged.emit()

    @Slot(int, str)
    def _comparison_capture_progress(self, request_id: int, message: str) -> None:
        if request_id not in self._comparison_workers:
            return
        self._schedule_status = message
        self.scheduleChanged.emit()

    @Slot(int, str, object)
    def _comparisons_ready(self, request_id: int, _actor_no: str, comparison_data: object) -> None:
        target = self._comparison_targets.get(request_id, "")
        if request_id not in self._comparison_workers or target != self._target_date_text:
            return
        payload = comparison_data if isinstance(comparison_data, Mapping) else {}
        comparisons = build_schedule_comparisons(self._schedule_data, self._actions, payload)
        comparisons.update(
            {
                index: dict(self._comparisons[index])
                for index in self._executed_indices
                if index in self._comparisons and index < len(self._actions)
            }
        )
        self._comparisons = comparisons
        self._schedule_status = "已更新已登打比對資料。"
        self._refresh_projection()

    @Slot(int, str, str, str)
    def _comparisons_failed(
        self,
        request_id: int,
        _actor_no: str,
        message: str,
        error_code: str,
    ) -> None:
        if request_id not in self._comparison_workers:
            return
        self._schedule_status = message
        self.scheduleChanged.emit()
        self.errorOccurred.emit(message)
        if error_code == "login_failed":
            self.reloginRequired.emit(message)

    @Slot(int)
    def _comparison_worker_finished(self, request_id: int) -> None:
        worker_pair = self._comparison_workers.get(request_id)
        if worker_pair is None:
            return
        thread, _worker = worker_pair
        thread.quit()
        if not thread.wait(5_000):
            return
        self._comparison_workers.pop(request_id, None)
        self._comparison_targets.pop(request_id, None)
        thread.deleteLater()
        self.scheduleChanged.emit()

    @Slot(int, str, str, str)
    def _capture_failed(
        self,
        request_id: int,
        actor_no: str,
        message: str,
        error_code: str,
    ) -> None:
        if request_id != self._active_capture_request:
            return
        comparison_failure = (
            request_id in self._capture_schedule_ready_ids
            and error_code.startswith("comparison_")
        )
        if not comparison_failure:
            self.disable_auto_execution()
        self._schedule_status = message
        self.scheduleChanged.emit()
        self.errorOccurred.emit(message)
        if self._capture_publish_events.get(request_id, True):
            self.liveCaptureFailed.emit(message, error_code)
        if error_code in {"login_failed", "comparison_login_failed"}:
            self.reloginRequired.emit(message)
            return
        if comparison_failure:
            return
        if self._capture_targets.get(request_id) == business_roc_date():
            self.load_current_schedule()

    @Slot(int)
    def _capture_worker_finished(self, request_id: int) -> None:
        worker_pair = self._capture_workers.get(request_id)
        if worker_pair is None:
            return
        thread, _worker = worker_pair
        thread.quit()
        if not thread.wait(5_000):
            return
        self._capture_workers.pop(request_id, None)
        self._capture_targets.pop(request_id, None)
        self._capture_schedule_ready_ids.discard(request_id)
        self._capture_publish_events.pop(request_id, None)
        self._capture_auto_execution.pop(request_id, None)
        thread.deleteLater()
        self.scheduleChanged.emit()

    def _update_clock(self) -> None:
        now = QDateTime.currentDateTime()
        weekdays = "一二三四五六日"
        date_text = f'{now.toString("yyyy/MM/dd")}（{weekdays[now.date().dayOfWeek() - 1]}）'
        time_text = now.toString("HH:mm:ss")
        if date_text == self._current_date_text and time_text == self._current_time_text:
            return
        self._current_date_text = date_text
        self._current_time_text = time_text
        self.clockChanged.emit()
        current_fire_day = business_roc_date()
        if current_fire_day != self._observed_fire_day:
            self._observed_fire_day = current_fire_day
            self.disable_auto_execution()
            self.fireDayChanged.emit(current_fire_day)
