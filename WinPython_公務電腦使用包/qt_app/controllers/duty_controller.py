# -*- coding: utf-8 -*-
"""QML-facing clock and duty task model shell."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import re
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
    target_short_label,
)
from app_core.schedule_repository import ScheduleRepository, ScheduleSnapshot, business_roc_date
from app_core.duty_submission_service import DutySubmissionRequest
from app_core.unreturned_return_queue import UnreturnedReturnQueue
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
    externalReturnManualSubmissionConfirmationRequested = Signal()
    manualSubmissionRequested = Signal(object)
    externalReturnQueueManualSubmissionRequested = Signal(str)
    externalReturnRecoveryDue = Signal(object)
    unreturnedReturnEvent = Signal(object)
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
        unreturned_return_queue: UnreturnedReturnQueue | None = None,
    ) -> None:
        super().__init__(parent)
        package_root = Path(__file__).resolve().parents[2]
        self._repository = repository or ScheduleRepository(package_root / "runtime_outputs")
        self._capture_service = capture_service or ScheduleCaptureService(package_root)
        self._unreturned_return_queue = unreturned_return_queue or UnreturnedReturnQueue(
            package_root / "runtime_outputs"
        )
        self._current_date_text = ""
        self._current_time_text = ""
        self._observed_fire_day = business_roc_date()
        self._target_date_text = ""
        self._schedule_status = "尚未登入"
        self._preview_loaded = False
        self._actor_no = ""
        self._session_generation = 0
        self._session_user_id = ""
        self._session_closing = False
        self._schedule_generation = 0
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
        self._blocked_indices: set[int] = set()
        self._retry_after: dict[int, datetime] = {}
        self._task_errors: dict[int, str] = {}
        self._selected_indices: set[int] = set()
        self._pending_manual_indices: list[int] = []
        self._pending_manual_action_keys: tuple[str, ...] = ()
        self._pending_manual_schedule_generation = 0
        self._manual_confirmation_summary = ""
        self._pending_external_return_indices: list[int] = []
        self._pending_external_return_action_keys: tuple[str, ...] = ()
        self._pending_external_return_schedule_generation = 0
        self._external_return_confirmation_summary = ""
        self._external_return_queue_ids_by_action_index: dict[int, str] = {}
        self._handoff_preflight_groups: dict[str, dict[str, Any]] = {}
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
        self._capture_contexts: dict[int, tuple[int, str, str]] = {}
        self._capture_lane_owners: dict[int, str] = {}
        self._capture_schedule_ready_ids: set[int] = set()
        self._capture_publish_events: dict[int, bool] = {}
        self._capture_auto_execution: dict[int, bool] = {}
        self._comparison_request_id = 0
        self._comparison_workers: dict[int, tuple[QThread, ScheduleCaptureWorker]] = {}
        self._comparison_targets: dict[int, str] = {}
        self._comparison_contexts: dict[int, tuple[int, str, str]] = {}
        self._comparison_lane_owners: dict[int, str] = {}
        self._capture_lane_owner = ""
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

    def set_refresh_status(self, message: str) -> None:
        """Expose an immediate query rejection in the existing schedule-status area."""

        self._schedule_status = str(message or "").strip()
        self.scheduleChanged.emit()

    @Property(bool, notify=scheduleChanged)
    def isRefreshing(self) -> bool:
        return bool(
            self._schedule_workers
            or self._capture_workers
            or self._comparison_workers
            or self._capture_lane_owner
        )

    @property
    def session_generation(self) -> int:
        return self._session_generation

    @property
    def schedule_generation(self) -> int:
        return self._schedule_generation

    def claim_capture_lane(self, owner: str) -> bool:
        """Atomically reserve the browser-capture lane for any capture producer."""

        owner = str(owner or "").strip()
        if (
            self._session_closing
            or not owner
            or self._capture_lane_owner
            or self._capture_workers
            or self._comparison_workers
        ):
            return False
        self._capture_lane_owner = owner
        self.scheduleChanged.emit()
        return True

    def release_capture_lane(self, owner: str) -> None:
        owner = str(owner or "").strip()
        if not owner or owner != self._capture_lane_owner:
            return
        self._capture_lane_owner = ""
        self.scheduleChanged.emit()

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
    def canManualSubmitSelected(self) -> bool:
        """Whether every selected task can be submitted manually."""

        return self._can_manually_submit_selected()

    @Property(str, notify=scheduleChanged)
    def manualConfirmationSummary(self) -> str:
        return self._manual_confirmation_summary

    @Property(bool, notify=scheduleChanged)
    def hasExternalReturnPauseSelected(self) -> bool:
        return any(
            self._comparisons.get(index, {}).get("group") == "paused"
            for index in self._selected_indices
        )

    @Property(bool, notify=scheduleChanged)
    def canConfirmExternalReturnManualSubmissionSelected(self) -> bool:
        if not self._selected_indices:
            return False
        queue_ids = {
            self._external_return_queue_ids_by_action_index.get(index, "")
            for index in self._selected_indices
        }
        if "" in queue_ids or len(queue_ids) != 1:
            return False
        queue_id = next(iter(queue_ids))
        return self._selected_indices == self._queue_action_indices(queue_id)

    @Property(str, notify=scheduleChanged)
    def externalReturnConfirmationSummary(self) -> str:
        return self._external_return_confirmation_summary

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
        queue_id = self._external_return_queue_ids_by_action_index.get(action_index, "")
        group_indices = set(
            self._queue_action_indices(queue_id)
            if queue_id
            else self._handoff_group_indices(action_index)
        )
        if group_indices:
            if group_indices.issubset(self._selected_indices):
                self._selected_indices.difference_update(group_indices)
            else:
                self._selected_indices.update(group_indices)
        elif action_index in self._selected_indices:
            self._selected_indices.remove(action_index)
        else:
            self._selected_indices.add(action_index)
        self._refresh_projection()

    @Slot()
    def prepareManualSubmission(self) -> None:
        if self._session_closing:
            return
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
        action_keys = tuple(action_completion_key(self._actions[index]) for index in ready)
        if len(set(action_keys)) != len(action_keys):
            self._schedule_status = "選取任務識別重複，請重新更新勤務資料"
            self._refresh_projection()
            return
        self._pending_manual_indices = ready
        self._pending_manual_action_keys = action_keys
        self._pending_manual_schedule_generation = self._schedule_generation
        self._manual_confirmation_summary = (
            f"將登打勤務系統 {len(ready)} 筆：\n{summaries}\n\n"
            "將使用按下確認時的當下時間登打。"
        )
        self.scheduleChanged.emit()
        self.manualSubmissionConfirmationRequested.emit()

    @Slot()
    def confirmManualSubmission(self) -> None:
        if self._session_closing:
            return
        if not self._pending_manual_indices:
            return
        action_keys = self._pending_manual_action_keys or tuple(
            action_completion_key(self._actions[index])
            for index in self._pending_manual_indices
            if 0 <= index < len(self._actions)
        )
        indices = self._resolve_action_keys(action_keys)
        if indices is None or not all(self._is_manual_submission_eligible(index) for index in indices):
            self._pending_manual_indices.clear()
            self._pending_manual_action_keys = ()
            self._manual_confirmation_summary = ""
            self._schedule_status = "勤務資料已變更，請重新選取後再確認"
            self._refresh_projection()
            return
        self._pending_manual_indices.clear()
        self._pending_manual_action_keys = ()
        self._pending_manual_schedule_generation = self._schedule_generation
        self._manual_confirmation_summary = ""
        self._selected_indices.clear()
        self.scheduleChanged.emit()
        self.manualSubmissionRequested.emit(indices)

    @Slot()
    def cancelManualSubmission(self) -> None:
        self._pending_manual_indices.clear()
        self._pending_manual_action_keys = ()
        self._pending_manual_schedule_generation = self._schedule_generation
        self._manual_confirmation_summary = ""
        self._schedule_status = "已取消手動登打"
        self.scheduleChanged.emit()

    @Slot()
    def prepareExternalReturnManualSubmission(self) -> None:
        if self._session_closing:
            return
        if not self.canConfirmExternalReturnManualSubmissionSelected:
            self._schedule_status = "請只選取未返隊暫停的退勤項目。"
            self._refresh_projection()
            return
        indices = sorted(self._selected_indices)
        summaries = "\n".join(
            f"• {action_summary(self._actions[index])} ｜ {target_short_label(self._actions[index], self._staff)}"
            for index in indices
        )
        self._pending_external_return_indices = indices
        self._pending_external_return_action_keys = tuple(
            action_completion_key(self._actions[index]) for index in indices
        )
        self._pending_external_return_schedule_generation = self._schedule_generation
        self._external_return_confirmation_summary = (
            "請確認人員已返隊。確認後將以目前時間手動登打下列暫停項目：\n"
            f"{summaries}"
        )
        self.scheduleChanged.emit()
        self.externalReturnManualSubmissionConfirmationRequested.emit()

    @Slot()
    def confirmExternalReturnManualSubmission(self) -> None:
        if self._session_closing:
            return
        if not self._pending_external_return_indices:
            return
        action_keys = self._pending_external_return_action_keys or tuple(
            action_completion_key(self._actions[index])
            for index in self._pending_external_return_indices
            if 0 <= index < len(self._actions)
        )
        indices = self._resolve_action_keys(action_keys)
        queue_ids = {
            self._external_return_queue_ids_by_action_index.get(index, "")
            for index in (indices or [])
        }
        queue_id = next(iter(queue_ids)) if len(queue_ids) == 1 and "" not in queue_ids else ""
        if indices is None or not queue_id or set(indices) != self._queue_action_indices(queue_id):
            self._pending_external_return_indices.clear()
            self._pending_external_return_action_keys = ()
            self._external_return_confirmation_summary = ""
            self._schedule_status = "勤務資料已變更，請重新選取返隊項目"
            self._refresh_projection()
            return
        self._pending_external_return_indices.clear()
        self._pending_external_return_action_keys = ()
        self._pending_external_return_schedule_generation = self._schedule_generation
        self._external_return_confirmation_summary = ""
        self._selected_indices.clear()
        self.scheduleChanged.emit()
        if queue_id:
            self.externalReturnQueueManualSubmissionRequested.emit(queue_id)

    @Slot()
    def cancelExternalReturnManualSubmission(self) -> None:
        self._pending_external_return_indices.clear()
        self._pending_external_return_action_keys = ()
        self._pending_external_return_schedule_generation = self._schedule_generation
        self._external_return_confirmation_summary = ""
        self._schedule_status = "已取消確認返隊手動登打"
        self.scheduleChanged.emit()

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

    def _is_external_return_pause(self, index: int) -> bool:
        return bool(
            0 <= index < len(self._actions)
            and index in self._external_return_queue_ids_by_action_index
            and self._comparisons.get(index, {}).get("group") == "paused"
        )

    def set_session_context(self, generation: int, user_id: str) -> None:
        """Reset transient duty state when the authenticated identity changes."""

        generation = max(0, int(generation))
        user_id = str(user_id or "").strip()
        if generation == self._session_generation and user_id == self._session_user_id:
            return
        self._session_generation = generation
        self._session_user_id = user_id
        self._session_closing = not bool(user_id)
        self._auto_execution_enabled = False
        self._executed_indices.clear()
        self._submitting_indices.clear()
        self._blocked_indices.clear()
        self._retry_after.clear()
        self._task_errors.clear()
        self._selected_indices.clear()
        self._pending_manual_indices.clear()
        self._pending_manual_action_keys = ()
        self._pending_manual_schedule_generation = self._schedule_generation
        self._manual_confirmation_summary = ""
        self._pending_external_return_indices.clear()
        self._pending_external_return_action_keys = ()
        self._pending_external_return_schedule_generation = self._schedule_generation
        self._external_return_confirmation_summary = ""
        self._handoff_preflight_groups.clear()
        self._login_started_at = datetime.now() if user_id else None
        self._cancel_auto_logout()
        self._refresh_projection()

    def request_matches_current_session(self, request: DutySubmissionRequest) -> bool:
        if request.session_generation != self._session_generation:
            return False
        if self._session_user_id and request.user_id != self._session_user_id:
            return False
        return not request.session_actor_no or request.session_actor_no == self._actor_no

    def _unique_action_indices_by_key(self) -> dict[str, int]:
        grouped: dict[str, list[int]] = {}
        for index, action in enumerate(self._actions):
            grouped.setdefault(action_completion_key(action), []).append(index)
        return {
            key: indices[0]
            for key, indices in grouped.items()
            if key and len(indices) == 1
        }

    def _resolve_action_keys(self, action_keys: tuple[str, ...]) -> list[int] | None:
        indices_by_key = self._unique_action_indices_by_key()
        indices = [indices_by_key.get(key, -1) for key in action_keys]
        if not indices or any(index < 0 for index in indices) or len(set(indices)) != len(indices):
            return None
        return indices

    def _resolve_request_action_index(self, request: DutySubmissionRequest) -> int | None:
        if not self.request_matches_current_session(request):
            return None
        request_target_date = str(request.schedule_data.get("target_date", "") or "").strip()
        if request_target_date != str(self._target_date_text or "").strip():
            return None
        action_key = str(request.action_key or "").strip()
        if not action_key:
            actions = request.schedule_data.get("actions", [])
            if not isinstance(actions, list) or not 0 <= request.action_index < len(actions):
                return None
            action = actions[request.action_index]
            if not isinstance(action, Mapping):
                return None
            action_key = action_completion_key(action)
        if request.schedule_generation == self._schedule_generation:
            action_index = request.action_index
            if (
                0 <= action_index < len(self._actions)
                and action_completion_key(self._actions[action_index]) == action_key
            ):
                return action_index
        return self._unique_action_indices_by_key().get(action_key)

    def _submission_request(
        self,
        user_id: str,
        password: str,
        action_index: int,
        schedule_data: Mapping[str, Any],
        *,
        trigger_type: str,
        action_key: str = "",
    ) -> DutySubmissionRequest:
        actions = schedule_data.get("actions", [])
        action = actions[action_index]
        return DutySubmissionRequest(
            user_id=user_id,
            password=password,
            action_index=action_index,
            schedule_data=schedule_data,
            trigger_type=trigger_type,
            session_generation=self._session_generation,
            schedule_generation=self._schedule_generation,
            action_key=str(action_key or action_completion_key(action)),
            session_actor_no=self._actor_no,
        )

    def set_actor_no(self, actor_no: str) -> None:
        actor_no = str(actor_no or "").strip()
        if actor_no == self._actor_no:
            return
        previous_actor = self._actor_no
        self._actor_no = actor_no
        if actor_no != previous_actor:
            self._handoff_preflight_groups.clear()
        if actor_no and actor_no != previous_actor:
            self._login_started_at = datetime.now()
        if not actor_no:
            self._auto_execution_enabled = False
            self._schedule_status = "尚未登入"
            self._selected_indices.clear()
            self._task_errors.clear()
            self._login_started_at = None
            self._cancel_auto_logout()
        self._refresh_projection()

    def _capture_context_is_current(
        self,
        contexts: Mapping[int, tuple[int, str, str]],
        request_id: int,
    ) -> bool:
        context = contexts.get(request_id)
        if context is None:
            return self._session_generation == 0 and not self._session_user_id
        generation, user_id, actor_no = context
        if generation != self._session_generation:
            return False
        if self._session_generation == 0 and not self._session_user_id:
            return True
        return (
            user_id == self._session_user_id
            and (not actor_no or actor_no == self._actor_no)
        )

    def _invalidate_capture_callbacks(self) -> None:
        self._active_capture_request = 0
        self._capture_contexts.clear()
        self._comparison_contexts.clear()

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
        if not user_id or not password:
            return False
        self._capture_request_id += 1
        request_id = self._capture_request_id
        lane_owner = f"duty-schedule:{request_id}"
        if not self.claim_capture_lane(lane_owner):
            return False
        self.disable_auto_execution()
        self._preview_loaded = False
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
        self._capture_contexts[request_id] = (
            self._session_generation,
            str(user_id).strip(),
            str(actor_no or "").strip(),
        )
        self._capture_lane_owners[request_id] = lane_owner
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

        if not user_id or not password:
            return False
        target = str(target_roc_date or business_roc_date()).strip()
        self._comparison_request_id += 1
        request_id = self._comparison_request_id
        lane_owner = f"duty-comparison:{request_id}"
        if not self.claim_capture_lane(lane_owner):
            return False
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
        self._comparison_contexts[request_id] = (
            self._session_generation,
            str(user_id).strip(),
            str(actor_no or "").strip(),
        )
        self._comparison_lane_owners[request_id] = lane_owner
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
        if self._session_closing or not self._auto_execution_enabled or not user_id or not password:
            return []
        requests: list[DutySubmissionRequest] = []
        handled_group_ids: set[str] = set()
        current = datetime.now()
        handoff_priority_times = self._due_handoff_priority_times(indices, current)
        for index in indices:
            if index not in self._due_task_indices or not 0 <= index < len(self._actions):
                continue
            if action_datetime(self._actions[index], self._target_date_text, fallback_date=current.date()) > current:
                continue
            group_indices = self._handoff_group_indices(index)
            if not group_indices:
                if self._is_handoff_priority_checkout(
                    self._actions[index],
                    current,
                    handoff_priority_times,
                ):
                    continue
                requests.append(
                    self._submission_request(
                        user_id,
                        password,
                        index,
                        self._schedule_data,
                        trigger_type="due",
                    )
                )
                continue
            group_id = self._handoff_group_id(group_indices)
            if group_id in handled_group_ids or group_id in self._handoff_preflight_groups:
                continue
            handled_group_ids.add(group_id)
            preflight_requests = self._handoff_preflight_requests(
                user_id,
                password,
                [self._actions[group_index] for group_index in group_indices],
                group_id=group_id,
                group_indices=group_indices,
                trigger_type="due",
            )
            if preflight_requests:
                requests.extend(preflight_requests)
                continue
            requests.extend(
                self._submission_request(
                    user_id,
                    password,
                    group_index,
                    self._schedule_data,
                    trigger_type="due",
                )
                for group_index in group_indices
            )
        return requests

    @staticmethod
    def is_handoff_preflight_request(request: DutySubmissionRequest) -> bool:
        if request.schedule_data.get("_handoff_preflight_group_id"):
            return True
        actions = request.schedule_data.get("actions", [])
        if not isinstance(actions, list) or not 0 <= request.action_index < len(actions):
            return False
        action = actions[request.action_index]
        return isinstance(action, Mapping) and action.get("kind") == "handoff_preflight"

    def _due_handoff_priority_times(
        self,
        indices: list[int],
        current: datetime,
    ) -> set[datetime]:
        times: set[datetime] = set()
        for state in self._handoff_preflight_groups.values():
            if state.get("paused"):
                continue
            for action in state.get("actions", []):
                if not isinstance(action, Mapping):
                    continue
                action_at = action_datetime(
                    action,
                    self._target_date_text,
                    fallback_date=current.date(),
                )
                if action_at <= current:
                    times.add(action_at.replace(second=0, microsecond=0))
                    break
        for index in indices:
            if index not in self._due_task_indices or not 0 <= index < len(self._actions):
                continue
            group_indices = self._handoff_group_indices(index)
            if not group_indices:
                continue
            group_id = self._handoff_group_id(group_indices)
            state = self._handoff_preflight_groups.get(group_id)
            if state is not None and state.get("paused"):
                continue
            action_at = action_datetime(
                self._actions[index],
                self._target_date_text,
                fallback_date=current.date(),
            )
            if action_at <= current:
                times.add(action_at.replace(second=0, microsecond=0))
        return times

    def _is_handoff_priority_checkout(
        self,
        action: Mapping[str, Any],
        current: datetime,
        handoff_priority_times: set[datetime],
    ) -> bool:
        if not handoff_priority_times or action.get("kind") != "entry_log":
            return False
        fields = action.get("fields", {})
        if not isinstance(fields, Mapping) or fields.get("領用事由及地點", "") != "退勤":
            return False
        start_minutes = self._clock_minutes(fields.get("登打時間") or action.get("time", ""))
        write_minutes = self._clock_minutes(fields.get("系統寫入時間"))
        if (
            start_minutes is None
            or write_minutes is None
            or not start_minutes < write_minutes <= start_minutes + 5
        ):
            return False
        action_at = action_datetime(
            action,
            self._target_date_text,
            fallback_date=current.date(),
        ).replace(second=0, microsecond=0)
        return action_at in handoff_priority_times

    @staticmethod
    def _clock_minutes(value: Any) -> int | None:
        try:
            hour, minute = [int(part) for part in str(value or "").split(":", 1)]
        except (TypeError, ValueError):
            return None
        if not 0 <= hour < 24 or not 0 <= minute < 60:
            return None
        return hour * 60 + minute

    def _handoff_group_indices(self, action_index: int) -> tuple[int, ...]:
        if not 0 <= action_index < len(self._actions):
            return ()
        action = self._actions[action_index]
        if action.get("source") != "值班交接":
            return ()
        action_time = action_datetime(action, self._target_date_text)
        actor = str(action.get("actor", "") or "")
        return tuple(
            index
            for index, candidate in enumerate(self._actions)
            if candidate.get("source") == "值班交接"
            and str(candidate.get("actor", "") or "") == actor
            and action_datetime(candidate, self._target_date_text) == action_time
        )

    def _handoff_group_id(self, indices: tuple[int, ...]) -> str:
        return "handoff:" + "|".join(
            sorted(action_completion_key(self._actions[index]) for index in indices)
        )

    def _handoff_state_indices(self, state: Mapping[str, Any]) -> tuple[int, ...]:
        action_keys = tuple(str(key or "") for key in state.get("action_keys", ()))
        if action_keys:
            indices = self._resolve_action_keys(action_keys)
            return tuple(indices or ())
        return tuple(
            int(index)
            for index in state.get("indices", ())
            if 0 <= int(index) < len(self._actions)
        )

    @staticmethod
    def _handoff_incoming_actions(actions: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
        incoming: list[dict[str, Any]] = []
        for action in actions:
            fields = action.get("fields", {})
            if (
                action.get("kind") == "entry_log"
                and isinstance(fields, Mapping)
                and fields.get("出或入") == "值班"
            ):
                incoming.append(dict(action))
        return incoming

    def _scheduled_bridge_incoming_actions(
        self,
        current: datetime,
    ) -> tuple[datetime, list[dict[str, Any]]] | None:
        """Return the current actor's latest scheduled value-handoff arrival group."""

        if not self._actor_no:
            return None
        candidates: list[tuple[datetime, int]] = []
        for index, action in enumerate(self._actions):
            fields = action.get("fields", {})
            if (
                action.get("kind") != "entry_log"
                or action.get("source") != "值班交接"
                or not isinstance(fields, Mapping)
                or fields.get("出或入") != "值班"
                or str(action.get("target", "") or "") != self._actor_no
            ):
                continue
            action_at = action_datetime(
                action,
                self._target_date_text,
                fallback_date=current.date(),
            )
            if action_at <= current:
                candidates.append((action_at, index))
        if not candidates:
            return None
        handoff_at, anchor_index = max(candidates, key=lambda item: item[0])
        group_indices = self._handoff_group_indices(anchor_index)
        incoming_actions = self._handoff_incoming_actions(
            [self._actions[index] for index in group_indices]
        )
        return (handoff_at, incoming_actions) if incoming_actions else None

    def _recovery_cross_shift_bridge(
        self,
        record: Mapping[str, Any],
        actions: list[Mapping[str, Any]],
        current: datetime,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
        """Replace missed handoff arrivals with the current scheduled duty group."""

        if record.get("completed_keys"):
            return None
        original_incoming = self._handoff_incoming_actions(actions)
        scheduled = self._scheduled_bridge_incoming_actions(current)
        if not original_incoming or scheduled is None:
            return None
        scheduled_at, scheduled_incoming = scheduled
        source_target_date = str(record.get("source_target_date") or self._target_date_text)
        original_at = min(
            action_datetime(action, source_target_date, fallback_date=current.date())
            for action in actions
        )
        if scheduled_at <= original_at:
            return None
        original_targets = {
            str(action.get("target", "") or "") for action in original_incoming
        }
        scheduled_targets = {
            str(action.get("target", "") or "") for action in scheduled_incoming
        }
        if not scheduled_targets or scheduled_targets == original_targets:
            return None

        bridge_actor_no = next(
            (str(action.get("actor", "") or "") for action in actions if action.get("actor")),
            "",
        )
        bridge_incoming = []
        for action in scheduled_incoming:
            bridge_action = dict(action)
            if bridge_actor_no:
                bridge_action["actor"] = bridge_actor_no
            bridge_incoming.append(bridge_action)
        outgoing_actions = [
            dict(action)
            for action in actions
            if action not in original_incoming and action.get("kind") != "work_log"
        ]
        work_actions = [dict(action) for action in actions if action.get("kind") == "work_log"]
        bridge_actions = outgoing_actions + bridge_incoming + work_actions
        bridge_action_keys = {action_completion_key(action) for action in bridge_actions}
        skipped_action_keys = {action_completion_key(action) for action in original_incoming}
        skipped_actor_nos = set(original_targets)
        for action in self._actions:
            if action.get("source") != "值班交接":
                continue
            action_at = action_datetime(
                action,
                self._target_date_text,
                fallback_date=current.date(),
            )
            if not original_at <= action_at <= scheduled_at:
                continue
            completion_key = action_completion_key(action)
            if completion_key in bridge_action_keys:
                continue
            skipped_action_keys.add(completion_key)
            fields = action.get("fields", {})
            if (
                action.get("kind") == "entry_log"
                and isinstance(fields, Mapping)
                and fields.get("出或入") == "值班"
            ):
                skipped_actor_nos.add(str(action.get("target", "") or ""))
        return bridge_actions, {
            "bridge_at": current,
            "skipped_actor_nos": tuple(sorted(actor_no for actor_no in skipped_actor_nos if actor_no)),
            "incoming_actor_nos": tuple(sorted(actor_no for actor_no in scheduled_targets if actor_no)),
            "skipped_action_keys": tuple(sorted(skipped_action_keys)),
        }

    def _handoff_preflight_requests(
        self,
        user_id: str,
        password: str,
        actions: list[Mapping[str, Any]],
        *,
        group_id: str,
        group_indices: tuple[int, ...] = (),
        trigger_type: str,
        queue_id: str = "",
        submit_at: datetime | None = None,
        bridge: Mapping[str, Any] | None = None,
    ) -> list[DutySubmissionRequest]:
        incoming_actions = self._handoff_incoming_actions(actions)
        if not incoming_actions:
            return []
        pending_keys = {action_completion_key(action) for action in incoming_actions}
        if len(pending_keys) != len(incoming_actions):
            return []
        self._handoff_preflight_groups[group_id] = {
            "indices": tuple(group_indices),
            "action_keys": tuple(action_completion_key(action) for action in actions),
            "actions": [dict(action) for action in actions],
            "pending_keys": pending_keys,
            "paused": False,
            "queue_id": queue_id,
            "bridge": dict(bridge or {}),
        }
        current = submit_at or datetime.now()
        target_date = f"{current.year - 1911:03d}{current.month:02d}{current.day:02d}"
        requests: list[DutySubmissionRequest] = []
        for incoming in incoming_actions:
            preflight = dict(incoming)
            preflight["kind"] = "handoff_preflight"
            schedule_data = dict(self._schedule_data if not queue_id or bridge else {})
            if queue_id:
                record = self._unreturned_return_queue.get(queue_id) or {}
                if not bridge:
                    schedule_data.update(record.get("schedule_context", {}))
                schedule_data["target_date"] = target_date
                schedule_data["actions"] = [preflight]
                action_index = 0
            else:
                schedule_actions = [dict(action) for action in self._actions]
                action_index = self._unique_action_indices_by_key().get(
                    action_completion_key(incoming),
                    -1,
                )
                if action_index < 0:
                    self._handoff_preflight_groups.pop(group_id, None)
                    return []
                schedule_actions[action_index] = preflight
                schedule_data["actions"] = schedule_actions
            schedule_data["_handoff_preflight_group_id"] = group_id
            schedule_data["_handoff_preflight_component_key"] = action_completion_key(incoming)
            schedule_data["_handoff_preflight_source_index"] = action_index if not queue_id else -1
            if queue_id:
                schedule_data["_unreturned_return_queue_id"] = queue_id
            requests.append(
                self._submission_request(
                    user_id,
                    password,
                    action_index,
                    schedule_data,
                    trigger_type=trigger_type,
                    action_key=action_completion_key(incoming),
                )
            )
        return requests

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
        requests: list[DutySubmissionRequest] = []
        for index in indices:
            if not 0 <= index < len(self._actions):
                continue
            action = self._stamped_submission_action(self._actions[index], current)
            if action is None:
                continue
            actions = [dict(item) for item in self._actions]
            actions[index] = action
            schedule_data = dict(self._schedule_data)
            schedule_data["actions"] = actions
            requests.append(
                self._submission_request(
                    user_id,
                    password,
                    index,
                    schedule_data,
                    trigger_type="manual",
                )
            )
        return requests

    def queued_external_return_manual_submission_requests(
        self,
        user_id: str,
        password: str,
        queue_id: str,
        *,
        submit_at: datetime | None = None,
    ) -> list[DutySubmissionRequest]:
        current = submit_at or datetime.now()
        record = self._unreturned_return_queue.claim_manual(queue_id, self._actor_no, now=current)
        if record is None:
            return []
        return self._queue_submission_requests(
            user_id,
            password,
            record,
            trigger_type="manual",
            submit_at=current,
        )

    def queued_external_return_manual_submission_request(
        self,
        user_id: str,
        password: str,
        queue_id: str,
        *,
        submit_at: datetime | None = None,
    ) -> DutySubmissionRequest | None:
        requests = self.queued_external_return_manual_submission_requests(
            user_id,
            password,
            queue_id,
            submit_at=submit_at,
        )
        return requests[0] if requests else None

    def recovery_submission_requests(
        self,
        user_id: str,
        password: str,
        record: Mapping[str, Any],
        *,
        submit_at: datetime | None = None,
    ) -> list[DutySubmissionRequest]:
        current = submit_at or datetime.now()
        if record.get("record_type") == "handoff_group":
            actions = self._unreturned_return_queue.incomplete_actions(record)
            bridge = self._recovery_cross_shift_bridge(record, actions, current)
            bridge_actions, bridge_metadata = bridge if bridge is not None else (actions, None)
            group_id = "queue:" + str(record.get("queue_id") or "")
            return self._handoff_preflight_requests(
                user_id,
                password,
                bridge_actions,
                group_id=group_id,
                trigger_type="recovery",
                queue_id=str(record.get("queue_id") or ""),
                submit_at=current,
                bridge=bridge_metadata,
            )
        return self._queue_submission_requests(
            user_id,
            password,
            record,
            trigger_type="recovery",
            submit_at=current,
        )

    def recovery_submission_request(
        self,
        user_id: str,
        password: str,
        record: Mapping[str, Any],
        *,
        submit_at: datetime | None = None,
    ) -> DutySubmissionRequest | None:
        requests = self.recovery_submission_requests(
            user_id,
            password,
            record,
            submit_at=submit_at,
        )
        return requests[0] if requests else None

    def release_external_return_recovery(self, queue_id: str) -> None:
        record = self._unreturned_return_queue.defer(queue_id, self._actor_no)
        if record is not None:
            self._publish_unreturned_return_event("pending", record, trigger_type="recovery")
            self.scheduleChanged.emit()

    def handle_external_return_queue_result(
        self,
        queue_id: str,
        action: Mapping[str, Any],
        status: str,
        completion_key: str = "",
    ) -> None:
        record, resolved = self._unreturned_return_queue.complete_action(
            queue_id,
            action,
            status,
            completion_key=completion_key,
        )
        action_index = self._queue_component_action_index(queue_id, action, completion_key)
        if action_index is not None and status in ("submitted", "skipped_duplicate"):
            self._task_errors.pop(action_index, None)
        if record is not None and resolved:
            self._publish_unreturned_return_event("resolved", record, trigger_type="recovery")
        elif record is not None and status not in ("submitted", "skipped_duplicate"):
            self._publish_unreturned_return_event("pending", record, trigger_type="recovery")
        self._refresh_queue_action_indices()
        self._refresh_projection()

    def handle_external_return_queue_failure(
        self,
        queue_id: str,
        action: Mapping[str, Any] | None = None,
        message: str = "",
        completion_key: str = "",
    ) -> None:
        record = self._unreturned_return_queue.defer(queue_id, self._actor_no)
        action_index = self._queue_component_action_index(queue_id, action, completion_key)
        if action_index is not None and message:
            self._task_errors[action_index] = str(message).strip()
        if record is not None:
            self._publish_unreturned_return_event("pending", record, trigger_type="recovery")
        self._refresh_queue_action_indices()
        self._refresh_projection()

    def mark_submission_enqueued(self, action_index: int) -> None:
        if not 0 <= action_index < len(self._actions):
            return
        self._submitting_indices.add(action_index)
        self._task_errors.pop(action_index, None)
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
        self._task_errors.pop(action_index, None)
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
            record, created = self._unreturned_return_queue.pause(
                self._actions[action_index],
                self._schedule_data,
                owner_actor_no=self._actor_no,
            )
            self._external_return_queue_ids_by_action_index[action_index] = str(record["queue_id"])
            self._retry_after[action_index] = datetime.now() + timedelta(minutes=5)
            self._comparisons[action_index] = {"compare": "未返隊，暫停登打", "group": "paused", "matched": []}
            if created:
                self._publish_unreturned_return_event("pending", record, trigger_type="due")
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
            self._task_errors[action_index] = str(message).strip()
        self._schedule_status = message
        self._refresh_projection()
        self.errorOccurred.emit(message)

    def handle_submission_request_result(
        self,
        request: DutySubmissionRequest,
        status: str,
        message: str,
        result_path: str,
    ) -> bool:
        action_index = self._resolve_request_action_index(request)
        if action_index is None:
            return False
        self.handle_submission_result(action_index, status, message, result_path)
        return True

    def handle_submission_request_failure(
        self,
        request: DutySubmissionRequest,
        message: str,
        error_code: str,
    ) -> bool:
        action_index = self._resolve_request_action_index(request)
        if action_index is None:
            return False
        self.handle_submission_failure(action_index, message, error_code)
        return True

    def load_current_schedule(self) -> None:
        if self._schedule_workers:
            return
        self._start_schedule_load()

    def load_audit_schedule(self, target_roc_date: str) -> None:
        """Load a saved schedule and comparison snapshot without a web login."""

        self.disable_auto_execution()
        self._invalidate_capture_callbacks()
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
        self._invalidate_capture_callbacks()
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
        self._session_closing = True
        for request_id, (thread, _worker) in tuple(self._schedule_workers.items()):
            thread.requestInterruption()
            thread.quit()
            if not thread.wait(10_000):
                thread.wait()
            self._schedule_thread_finished(request_id)
            thread.deleteLater()
        for request_id, (thread, _worker) in tuple(self._capture_workers.items()):
            thread.requestInterruption()
            thread.quit()
            if not thread.wait(120_000):
                thread.wait()
            self._capture_thread_finished(request_id)
            thread.deleteLater()
        for request_id, (thread, _worker) in tuple(self._comparison_workers.items()):
            thread.requestInterruption()
            thread.quit()
            if not thread.wait(120_000):
                thread.wait()
            self._comparison_thread_finished(request_id)
            thread.deleteLater()
        self._capture_lane_owner = ""

    def prepare_session_end(self) -> bool:
        """Stop admitting capture or submission work before logout or update."""

        self._session_closing = True
        self.disable_auto_execution()
        self._pending_manual_indices.clear()
        self._pending_manual_action_keys = ()
        self._manual_confirmation_summary = ""
        self._pending_external_return_indices.clear()
        self._pending_external_return_action_keys = ()
        self._external_return_confirmation_summary = ""
        self.scheduleChanged.emit()
        return not self.isRefreshing

    def replace_schedule_data(
        self,
        data: Mapping[str, Any],
        *,
        comparisons: Mapping[int, Mapping[str, Any]] | None = None,
        comparison_data: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        next_target_date = str(data.get("target_date", "") or "")
        same_schedule_date = bool(next_target_date) and next_target_date == self._target_date_text
        previous_unique_indices = self._unique_action_indices_by_key()
        previous_executed_keys = {
            key for key, index in previous_unique_indices.items() if index in self._executed_indices
        }
        previous_submitting_keys = {
            key for key, index in previous_unique_indices.items() if index in self._submitting_indices
        } if same_schedule_date else set()
        previous_blocked_keys = {
            key for key, index in previous_unique_indices.items() if index in self._blocked_indices
        } if same_schedule_date else set()
        previous_completed_by_key = {
            key: {
                **dict(self._comparisons.get(index, {})),
                "compare": str(self._comparisons.get(index, {}).get("compare", "已登打") or "已登打"),
                "group": "done",
            }
            for key, index in previous_unique_indices.items()
            if key in previous_executed_keys
        }
        previous_retry_by_key = {
            key: self._retry_after[index]
            for key, index in previous_unique_indices.items()
            if index in self._retry_after
        } if same_schedule_date else {}
        previous_errors_by_key = {
            key: self._task_errors[index]
            for key, index in previous_unique_indices.items()
            if index in self._task_errors
        } if same_schedule_date else {}
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
        if not same_schedule_date:
            self._pending_manual_indices.clear()
            self._pending_manual_action_keys = ()
            self._manual_confirmation_summary = ""
            self._pending_external_return_indices.clear()
            self._pending_external_return_action_keys = ()
            self._external_return_confirmation_summary = ""
            self._handoff_preflight_groups.clear()
            self._cancel_auto_logout()
        self._append_active_queue_actions()
        self._schedule_generation += 1
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
        next_unique_indices = self._unique_action_indices_by_key()
        carried_completed_indices = {
            next_unique_indices[key]
            for key in previous_executed_keys
            if key in next_unique_indices
        }
        incoming_comparisons.update(
            {
                next_unique_indices[key]: previous_completed_by_key[key]
                for key in previous_completed_by_key
                if key in next_unique_indices
            }
        )
        self._comparisons = incoming_comparisons
        self._selected_indices.clear()
        self._executed_indices = carried_completed_indices
        self._submitting_indices = {
            next_unique_indices[key]
            for key in previous_submitting_keys
            if key in next_unique_indices
        }
        self._blocked_indices = {
            next_unique_indices[key]
            for key in previous_blocked_keys
            if key in next_unique_indices
        }
        self._retry_after = {
            next_unique_indices[key]: retry_at
            for key, retry_at in previous_retry_by_key.items()
            if key in next_unique_indices
        }
        self._task_errors = {
            next_unique_indices[key]: message
            for key, message in previous_errors_by_key.items()
            if key in next_unique_indices
        }
        self._refresh_queue_action_indices()
        self._remap_pending_confirmations()
        self._refresh_projection()

    def _remap_pending_confirmations(self) -> None:
        if self._pending_manual_action_keys:
            indices = self._resolve_action_keys(self._pending_manual_action_keys)
            if indices is None:
                self._pending_manual_indices.clear()
                self._pending_manual_action_keys = ()
                self._manual_confirmation_summary = ""
            else:
                self._pending_manual_indices = indices
                self._pending_manual_schedule_generation = self._schedule_generation
        if self._pending_external_return_action_keys:
            indices = self._resolve_action_keys(self._pending_external_return_action_keys)
            if indices is None:
                self._pending_external_return_indices.clear()
                self._pending_external_return_action_keys = ()
                self._external_return_confirmation_summary = ""
            else:
                self._pending_external_return_indices = indices
                self._pending_external_return_schedule_generation = self._schedule_generation

    def _projection_state(self) -> DutyTaskProjectionState:
        return DutyTaskProjectionState(
            actor_no=self._actor_no,
            target_roc_date=self._target_date_text,
            staff=self._staff,
            comparisons=self._comparisons,
            submitting_indices=frozenset(self._submitting_indices),
            paused_indices=frozenset(self._blocked_indices),
            executed_indices=frozenset(self._executed_indices),
            selected_indices=frozenset(self._selected_indices),
            forced_visible_indices=frozenset(self._external_return_queue_ids_by_action_index),
            task_errors=self._task_errors,
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
                blocked_indices=frozenset(
                    set(self._blocked_indices)
                    | set(self._external_return_queue_ids_by_action_index)
                    | self._handoff_preflight_blocked_indices()
                ),
                retry_after=self._retry_after,
            ),
        )
        if due != self._due_task_indices or force_emit:
            self._due_task_indices = due
            if emit_signal:
                self.scheduleChanged.emit()
            if self._auto_execution_enabled and due:
                self.dueTasksAvailable.emit(list(due))
        self._refresh_unreturned_return_queue()

    def _refresh_unreturned_return_queue(self) -> None:
        self._unreturned_return_queue.prune_bridge_history()
        expired = self._unreturned_return_queue.expire_due()
        for record in expired:
            self._mark_expired_unreturned_return(record)
            self._publish_unreturned_return_event("expired", record, trigger_type="recovery")
        if expired:
            self._refresh_queue_action_indices()
            self._refresh_projection()
        if not self._auto_execution_enabled or not self._actor_no:
            return
        record = self._unreturned_return_queue.claim_due(self._actor_no)
        if record is None:
            return
        self._publish_unreturned_return_event("retrying", record, trigger_type="recovery")
        self.scheduleChanged.emit()
        self.externalReturnRecoveryDue.emit(record)

    @staticmethod
    def _stamped_submission_action(
        original_action: Mapping[str, Any],
        submit_at: datetime,
    ) -> dict[str, Any] | None:
        action = dict(original_action)
        fields = dict(action.get("fields", {}))
        current_time = submit_at.strftime("%H:%M")
        if action.get("kind") == "work_log":
            fields["工作時間"] = current_time
            if action.get("source") == "值班交接":
                fields["處理情形"] = DutyController._handoff_status_with_actual_end(
                    fields.get("處理情形", ""),
                    current_time,
                )
        elif action.get("kind") == "entry_log":
            fields["登打時間"] = current_time
            fields["系統寫入時間"] = current_time
        else:
            return None
        target_date = f"{submit_at.year - 1911:03d}{submit_at.month:02d}{submit_at.day:02d}"
        action["fields"] = fields
        action["time"] = current_time
        action["date_offset"] = 0
        action["submit_target_date"] = target_date
        return action

    @staticmethod
    def _handoff_status_with_actual_end(value: Any, actual_end: str) -> str:
        lines = str(value or "").splitlines()
        if not lines:
            return str(value or "")
        matched = re.match(r"^(一、時間:)\s*(.+?)\s*-\s*.*$", lines[0])
        if matched is None:
            return str(value or "")
        start = matched.group(2).strip()
        if start.isdigit() and len(start) == 2:
            start = f"{start}:00"
        elif start.isdigit() and len(start) == 4:
            start = f"{start[:2]}:{start[2:]}"
        lines[0] = f"{matched.group(1)}{start}-{actual_end}"
        return "\n".join(lines)

    def _queue_submission_requests(
        self,
        user_id: str,
        password: str,
        record: Mapping[str, Any],
        *,
        trigger_type: str,
        submit_at: datetime,
    ) -> list[DutySubmissionRequest]:
        queue_id = str(record.get("queue_id") or "")
        target_date = f"{submit_at.year - 1911:03d}{submit_at.month:02d}{submit_at.day:02d}"
        requests: list[DutySubmissionRequest] = []
        for original_action in self._unreturned_return_queue.incomplete_actions(record):
            action = self._stamped_submission_action(original_action, submit_at)
            if action is None:
                continue
            schedule_data = dict(record.get("schedule_context", {}))
            schedule_data["target_date"] = target_date
            schedule_data["actions"] = [action]
            schedule_data["_unreturned_return_queue_id"] = queue_id
            schedule_data["_unreturned_return_component_key"] = action_completion_key(original_action)
            requests.append(
                self._submission_request(
                    user_id,
                    password,
                    0,
                    schedule_data,
                    trigger_type=trigger_type,
                    action_key=action_completion_key(original_action),
                )
            )
        return requests

    def handoff_group_submission_requests(
        self,
        user_id: str,
        password: str,
        preflight_request: DutySubmissionRequest,
        *,
        submit_at: datetime | None = None,
    ) -> list[DutySubmissionRequest]:
        if not self.request_matches_current_session(preflight_request):
            return []
        group_id = str(preflight_request.schedule_data.get("_handoff_preflight_group_id") or "")
        state = self._handoff_preflight_groups.get(group_id)
        if state is None or state.get("paused"):
            return []
        current = submit_at or datetime.now()
        queue_id = str(state.get("queue_id") or "")
        if queue_id:
            record = self._unreturned_return_queue.get(queue_id)
            if record is None:
                return []
            return self._queue_submission_requests(
                user_id,
                password,
                record,
                trigger_type=preflight_request.trigger_type,
                submit_at=current,
            )

        actions = [dict(action) for action in self._actions]
        group_indices = self._handoff_state_indices(state)
        if not group_indices:
            return []
        target_date = f"{current.year - 1911:03d}{current.month:02d}{current.day:02d}"
        for index in group_indices:
            if (
                not 0 <= index < len(actions)
                or str(actions[index].get("actor", "") or "") != self._actor_no
                or action_datetime(
                    actions[index],
                    self._target_date_text,
                    fallback_date=current.date(),
                )
                > current
            ):
                return []
            action = self._stamped_submission_action(actions[index], current)
            if action is None:
                return []
            actions[index] = action
        schedule_data = dict(self._schedule_data)
        schedule_data["target_date"] = target_date
        schedule_data["actions"] = actions
        return [
            self._submission_request(
                user_id,
                password,
                index,
                schedule_data,
                trigger_type=preflight_request.trigger_type,
            )
            for index in group_indices
        ]

    def handle_handoff_preflight_ready(self, request: DutySubmissionRequest) -> bool:
        if not self.request_matches_current_session(request):
            return False
        group_id = str(request.schedule_data.get("_handoff_preflight_group_id") or "")
        state = self._handoff_preflight_groups.get(group_id)
        if state is None or state.get("paused"):
            return False
        component_key = str(request.schedule_data.get("_handoff_preflight_component_key") or "")
        source_index = self._unique_action_indices_by_key().get(component_key)
        if source_index is not None:
            self._submitting_indices.discard(source_index)
        pending_keys = set(state.get("pending_keys", set()))
        pending_keys.discard(component_key)
        state["pending_keys"] = pending_keys
        if not pending_keys:
            bridge = state.get("bridge", {})
            queue_id = str(state.get("queue_id") or "")
            if bridge and queue_id:
                record = self._unreturned_return_queue.bridge_handoff_group(
                    queue_id,
                    state.get("actions", []),
                    self._schedule_data,
                    bridge_at=bridge.get("bridge_at", datetime.now()),
                    skipped_actor_nos=bridge.get("skipped_actor_nos", ()),
                    incoming_actor_nos=bridge.get("incoming_actor_nos", ()),
                    skipped_action_keys=bridge.get("skipped_action_keys", ()),
                )
                if record is None:
                    self._handoff_preflight_groups.pop(group_id, None)
                    self._unreturned_return_queue.defer(queue_id, self._actor_no)
                    self._schedule_status = "跨班交接資料已變更，將重新確認。"
                    self._refresh_queue_action_indices()
                    self._refresh_projection()
                    return False
                self._refresh_queue_action_indices()
        self._refresh_projection()
        return not pending_keys

    def finish_handoff_preflight_group(self, request: DutySubmissionRequest) -> None:
        if not self.request_matches_current_session(request):
            return
        group_id = str(request.schedule_data.get("_handoff_preflight_group_id") or "")
        if self._handoff_preflight_groups.pop(group_id, None) is not None:
            self._refresh_due_tasks(force_emit=True)

    def handle_handoff_preflight_paused(self, request: DutySubmissionRequest) -> None:
        if not self.request_matches_current_session(request):
            return
        group_id = str(request.schedule_data.get("_handoff_preflight_group_id") or "")
        state = self._handoff_preflight_groups.get(group_id)
        if state is None:
            return
        component_key = str(request.schedule_data.get("_handoff_preflight_component_key") or "")
        source_index = self._unique_action_indices_by_key().get(component_key)
        if source_index is not None:
            self._submitting_indices.discard(source_index)
        state["paused"] = True
        queue_id = str(state.get("queue_id") or "")
        if queue_id:
            record = self._unreturned_return_queue.defer(queue_id, self._actor_no)
        else:
            record, created = self._unreturned_return_queue.pause_group(
                state.get("actions", []),
                self._schedule_data,
                owner_actor_no=self._actor_no,
            )
            queue_id = str(record.get("queue_id") or "")
            if created:
                self._publish_unreturned_return_event("pending", record, trigger_type="due")
        if record is not None:
            handoff_indices = set(self._handoff_state_indices(state))
            for index in self._queue_action_indices(queue_id) | handoff_indices:
                self._comparisons[index] = {
                    "compare": "未返隊，暫停登打",
                    "group": "paused",
                    "matched": [],
                }
            self._schedule_auto_logout_for_handoff_indices(handoff_indices)
        self._refresh_queue_action_indices()
        self._refresh_projection()
        self._refresh_due_tasks(force_emit=True)

    def handle_handoff_preflight_failure(
        self,
        request: DutySubmissionRequest,
        message: str,
        error_code: str,
    ) -> None:
        if not self.request_matches_current_session(request):
            return
        group_id = str(request.schedule_data.get("_handoff_preflight_group_id") or "")
        state = self._handoff_preflight_groups.pop(group_id, None)
        if state is None:
            return
        queue_id = str(state.get("queue_id") or "")
        if queue_id:
            self.handle_external_return_queue_failure(queue_id)
            return
        for index in self._handoff_state_indices(state):
            self._submitting_indices.discard(index)
            self._retry_after[index] = datetime.now() + timedelta(minutes=1)
        self._schedule_status = message
        self._refresh_projection()
        self._refresh_due_tasks(force_emit=True)
        if error_code == "login_failed":
            self.errorOccurred.emit(message)
            self.reloginRequired.emit(message)

    def _handoff_preflight_blocked_indices(self) -> set[int]:
        return {
            index
            for state in self._handoff_preflight_groups.values()
            for index in self._handoff_state_indices(state)
        }

    def _queue_action_indices(self, queue_id: str) -> set[int]:
        return {
            index
            for index, current_queue_id in self._external_return_queue_ids_by_action_index.items()
            if current_queue_id == queue_id
        }

    def _queue_component_action_index(
        self,
        queue_id: str,
        action: Mapping[str, Any] | None,
        completion_key: str = "",
    ) -> int | None:
        if not action:
            return None
        component_key = str(completion_key or action_completion_key(action))
        for index in self._queue_action_indices(queue_id):
            if action_completion_key(self._actions[index]) == component_key:
                return index
        return None

    def _append_active_queue_actions(self) -> None:
        existing_keys = {action_completion_key(action) for action in self._actions}
        for record in self._unreturned_return_queue.active_records():
            source_target_date = str(record.get("source_target_date") or "")
            if source_target_date and source_target_date > self._target_date_text:
                continue
            for action in self._unreturned_return_queue.record_actions(record):
                completion_key = action_completion_key(action)
                if completion_key in existing_keys:
                    continue
                self._actions.append(action)
                existing_keys.add(completion_key)
        self._schedule_data["actions"] = self._actions

    def _refresh_queue_action_indices(self) -> None:
        queue_ids_by_completion_key: dict[str, str] = {}
        completed_statuses: dict[str, str] = {}
        for record in self._unreturned_return_queue.active_records():
            record_completed = {
                str(key): str(value)
                for key, value in dict(record.get("completed_statuses", {})).items()
            }
            for action in self._unreturned_return_queue.record_actions(record):
                completion_key = action_completion_key(action)
                if completion_key in record_completed:
                    completed_statuses[completion_key] = record_completed[completion_key]
                else:
                    queue_ids_by_completion_key[completion_key] = str(record.get("queue_id") or "")
        self._external_return_queue_ids_by_action_index = {
            index: queue_ids_by_completion_key[action_completion_key(action)]
            for index, action in enumerate(self._actions)
            if action_completion_key(action) in queue_ids_by_completion_key
        }
        for index in self._external_return_queue_ids_by_action_index:
            self._comparisons[index] = {
                "compare": "未返隊，暫停登打",
                "group": "paused",
                "matched": [],
            }
        for index, action in enumerate(self._actions):
            status = completed_statuses.get(action_completion_key(action))
            if not status:
                continue
            self._executed_indices.add(index)
            self._comparisons[index] = {
                "compare": "已登打" if status == "submitted" else "已存在",
                "group": "done",
                "matched": [],
            }
        unique_indices = self._unique_action_indices_by_key()
        for record in self._unreturned_return_queue.bridge_history_records():
            for action in self._unreturned_return_queue.record_actions(record):
                index = unique_indices.get(action_completion_key(action))
                if index is None:
                    continue
                self._executed_indices.add(index)
                self._comparisons[index] = {
                    "compare": "已由跨班接續登打",
                    "group": "done",
                    "matched": [],
                }
            for bridge in record.get("bridge_history", []):
                if not isinstance(bridge, Mapping):
                    continue
                for completion_key in bridge.get("skipped_action_keys", []):
                    index = unique_indices.get(str(completion_key or ""))
                    if index is None:
                        continue
                    self._blocked_indices.add(index)
                    self._comparisons[index] = {
                        "compare": "跨班接續已略過未返隊人員",
                        "group": "skipped",
                        "matched": [],
                    }

    def _mark_expired_unreturned_return(self, record: Mapping[str, Any]) -> None:
        expired_keys = {
            action_completion_key(action)
            for action in self._unreturned_return_queue.record_actions(record)
        }
        for index, action in enumerate(self._actions):
            if action_completion_key(action) not in expired_keys:
                continue
            self._blocked_indices.add(index)
            self._comparisons[index] = {
                "compare": "未返隊暫停已逾 18 小時，請人工確認",
                "group": "review",
                "matched": [],
            }

    def _publish_unreturned_return_event(
        self,
        status: str,
        record: Mapping[str, Any],
        *,
        trigger_type: str,
    ) -> None:
        self.unreturnedReturnEvent.emit(
            {
                "status": status,
                "trigger_type": trigger_type,
                "record": dict(record),
            }
        )

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

    def _schedule_auto_logout_for_handoff_indices(self, indices: set[int]) -> None:
        for index in indices:
            if not 0 <= index < len(self._actions):
                continue
            self._schedule_auto_logout_if_needed(index)

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
            if (
                index not in self._executed_indices
                and self._comparisons.get(index, {}).get("group") != "done"
                and not self._is_paused_handoff_group_index(index)
            )
        ]
        if self._submitting_indices or not group or incomplete:
            self._auto_logout_deadline = datetime.now() + timedelta(minutes=10)
            self._auto_logout_timer.start(10 * 60 * 1000)
            self._schedule_status = f"交接仍有 {len(incomplete)} 筆未完成，10 分鐘後再檢查自動登出"
            self.scheduleChanged.emit()
            return
        actor_no = self._auto_logout_actor_no
        self._cancel_auto_logout()
        self.autoLogoutRequested.emit(actor_no)

    def _is_paused_handoff_group_index(self, index: int) -> bool:
        queue_id = self._external_return_queue_ids_by_action_index.get(index, "")
        record = self._unreturned_return_queue.get(queue_id)
        return bool(record is not None and record.get("record_type") == "handoff_group")

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
            self._poll_owned_thread_finished("schedule", request_id)
            return
        self._schedule_thread_finished(request_id)
        thread.deleteLater()

    def _schedule_thread_finished(self, request_id: int) -> None:
        worker_pair = self._schedule_workers.pop(request_id, None)
        if worker_pair is None:
            return
        self.scheduleChanged.emit()

    @Slot(int, str)
    def _capture_progress(self, request_id: int, message: str) -> None:
        if (
            request_id == self._active_capture_request
            and self._capture_context_is_current(self._capture_contexts, request_id)
        ):
            self._schedule_status = message
            self.scheduleChanged.emit()

    @Slot(int, str, object)
    def _capture_schedule_ready(self, request_id: int, actor_no: str, snapshot: ScheduleSnapshot) -> None:
        if (
            request_id != self._active_capture_request
            or not self._capture_context_is_current(self._capture_contexts, request_id)
        ):
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
        if (
            request_id != self._active_capture_request
            or not self._capture_context_is_current(self._capture_contexts, request_id)
        ):
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
        if not self._capture_context_is_current(self._comparison_contexts, request_id):
            return
        self._schedule_status = message
        self.scheduleChanged.emit()

    @Slot(int, str, object)
    def _comparisons_ready(self, request_id: int, _actor_no: str, comparison_data: object) -> None:
        target = self._comparison_targets.get(request_id, "")
        if (
            not self._capture_context_is_current(self._comparison_contexts, request_id)
            or target != self._target_date_text
        ):
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
        if not self._capture_context_is_current(self._comparison_contexts, request_id):
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
            self._poll_owned_thread_finished("comparison", request_id)
            return
        self._comparison_thread_finished(request_id)
        thread.deleteLater()

    def _comparison_thread_finished(self, request_id: int) -> None:
        worker_pair = self._comparison_workers.pop(request_id, None)
        if worker_pair is None:
            return
        thread, _worker = worker_pair
        self._comparison_targets.pop(request_id, None)
        self._comparison_contexts.pop(request_id, None)
        lane_owner = self._comparison_lane_owners.pop(request_id, "")
        self.release_capture_lane(lane_owner)
        self.scheduleChanged.emit()

    @Slot(int, str, str, str)
    def _capture_failed(
        self,
        request_id: int,
        actor_no: str,
        message: str,
        error_code: str,
    ) -> None:
        if (
            request_id != self._active_capture_request
            or not self._capture_context_is_current(self._capture_contexts, request_id)
        ):
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
            self._poll_owned_thread_finished("capture", request_id)
            return
        self._capture_thread_finished(request_id)
        thread.deleteLater()

    def _poll_owned_thread_finished(self, cleanup_kind: str, request_id: int) -> None:
        workers = {
            "schedule": self._schedule_workers,
            "capture": self._capture_workers,
            "comparison": self._comparison_workers,
        }.get(cleanup_kind)
        if workers is None:
            return
        worker_pair = workers.get(request_id)
        if worker_pair is None:
            return
        thread, _worker = worker_pair
        if not thread.isFinished():
            QTimer.singleShot(
                50,
                lambda: self._poll_owned_thread_finished(cleanup_kind, request_id),
            )
            return
        if cleanup_kind == "schedule":
            self._schedule_thread_finished(request_id)
        elif cleanup_kind == "capture":
            self._capture_thread_finished(request_id)
        else:
            self._comparison_thread_finished(request_id)
        thread.deleteLater()

    def _capture_thread_finished(self, request_id: int) -> None:
        worker_pair = self._capture_workers.pop(request_id, None)
        if worker_pair is None:
            return
        thread, _worker = worker_pair
        self._capture_targets.pop(request_id, None)
        self._capture_contexts.pop(request_id, None)
        lane_owner = self._capture_lane_owners.pop(request_id, "")
        self._capture_schedule_ready_ids.discard(request_id)
        self._capture_publish_events.pop(request_id, None)
        self._capture_auto_execution.pop(request_id, None)
        self.release_capture_lane(lane_owner)
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
