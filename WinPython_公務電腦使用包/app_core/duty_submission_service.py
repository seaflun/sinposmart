# -*- coding: utf-8 -*-
"""UI-independent single-action boundary for duty-system submission."""

from __future__ import annotations

import importlib
import json
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from datetime import date, datetime, timedelta
from hashlib import sha256
from inspect import signature
from pathlib import Path
from time import sleep
from types import ModuleType
from typing import Any, Callable, Mapping

from app_core.diagnostics_service import diagnostic_exception
from app_core.duty_task_projection import (
    action_completion_key,
    action_staff,
    action_target_roc_date,
    is_fire_day_closing_action,
    build_schedule_comparisons,
    compare_submission_action,
)
from app_core.schedule_repository import business_roc_date
from compare_rehearsal_records import (
    EXTERNAL_ASSIGNMENT_KEYWORDS,
    clean,
    entry_row_fields,
    find_open_external_assignment,
    flatten_rows,
    has_open_external_assignment,
)


class DutySubmissionValidationError(ValueError):
    """A safe request-validation message for Qt controllers."""


class _StaleDutyScheduleError(RuntimeError):
    """Stop a due request before its form can be saved."""


class DutySubmissionExecutionError(RuntimeError):
    """A safe execution failure for Qt controllers."""

    def __init__(
        self,
        message: str,
        error_code: str = "unknown_error",
        result_path: Path | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.result_path = result_path


RECENT_HANDOFF_SCHEDULE_SNAPSHOT_MAX_AGE = timedelta(minutes=2)
ROUTINE_WORK_LOG_QUERY_WINDOW = timedelta(minutes=2)
UNRETURNED_RETURN_QUERY_STARTED_STATUS = "正在確認未返隊人員是否已返隊…"


@dataclass(frozen=True)
class DutySubmissionRequest:
    user_id: str
    password: str = field(repr=False)
    action_index: int
    schedule_data: Mapping[str, Any]
    trigger_type: str = "due"
    save: bool = True
    visible: bool = False
    session_generation: int = 0
    schedule_generation: int = 0
    action_key: str = ""
    session_actor_no: str = ""
    background: bool = False


@dataclass(frozen=True)
class DutySubmissionResult:
    action_index: int
    status: str
    message: str
    result_path: Path
    comparison: Mapping[str, Any]
    action: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class DutySubmissionBrowserSession:
    """A logged-in browser that may execute consecutive entry submissions."""

    automation: ModuleType
    driver: object
    user_id: str
    visible: bool
    last_activity_at: datetime
    known_open_departures: dict[str, str] = field(default_factory=dict)


def load_automation_module() -> ModuleType:
    return importlib.import_module("duty_rehearsal")


class DutySubmissionService:
    def __init__(
        self,
        package_root: Path,
        *,
        module_loader: Callable[[], ModuleType] = load_automation_module,
        now_factory: Callable[[], datetime] = datetime.now,
        comparison_builder: Callable[..., dict[int, dict[str, Any]]] = build_schedule_comparisons,
        open_assignment_checker: Callable[..., bool] = has_open_external_assignment,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        self.package_root = Path(package_root)
        self.output_dir = self.package_root / "runtime_outputs" / "form_tests"
        self.module_loader = module_loader
        self.now_factory = now_factory
        self.comparison_builder = comparison_builder
        self.open_assignment_checker = open_assignment_checker
        self.sleeper = sleeper

    def validate(self, request: DutySubmissionRequest) -> DutySubmissionRequest:
        if not str(request.user_id or "").strip() or not request.password:
            raise DutySubmissionValidationError("請先完成勤務系統登入。")
        data = request.schedule_data
        if not isinstance(data, Mapping):
            raise DutySubmissionValidationError("勤務排程資料格式不正確。")
        target_date = str(data.get("target_date", "") or "").strip()
        if len(target_date) != 7 or not target_date.isdigit():
            raise DutySubmissionValidationError("勤務排程缺少正確的民國日期。")
        actions = data.get("actions", [])
        if not isinstance(actions, list) or not 0 <= int(request.action_index) < len(actions):
            raise DutySubmissionValidationError("找不到指定的勤務任務。")
        action = actions[int(request.action_index)]
        if not isinstance(action, Mapping) or action.get("kind") not in (
            "work_log",
            "entry_log",
            "handoff_preflight",
        ):
            raise DutySubmissionValidationError("這筆任務不支援勤務系統登打。")
        if action.get("staff_roc_date") and not action_staff(data, action).get(
            str(action.get("target", "")), {},
        ).get("name"):
            raise DutySubmissionValidationError("下一消防日人員名冊不完整，請重新更新勤務資料後再安排登打。")
        if request.trigger_type not in ("due", "manual", "recovery"):
            raise DutySubmissionValidationError("登打觸發類型不正確。")
        try:
            session_generation = int(request.session_generation)
            schedule_generation = int(request.schedule_generation)
        except (TypeError, ValueError) as exc:
            raise DutySubmissionValidationError("登打工作階段識別不正確。") from exc
        if session_generation < 0 or schedule_generation < 0:
            raise DutySubmissionValidationError("登打工作階段識別不正確。")
        return DutySubmissionRequest(
            user_id=request.user_id.strip(),
            password=request.password,
            action_index=int(request.action_index),
            schedule_data=data,
            trigger_type=request.trigger_type,
            save=bool(request.save),
            visible=bool(request.visible),
            session_generation=session_generation,
            schedule_generation=schedule_generation,
            action_key=(
                str(request.action_key or "").strip()
                or action_completion_key(action)
            ),
            session_actor_no=str(request.session_actor_no or "").strip(),
            background=bool(request.background),
        )

    def execute(
        self,
        request: DutySubmissionRequest,
        *,
        status_callback: Callable[[str], None] | None = None,
        browser_session: DutySubmissionBrowserSession | None = None,
    ) -> DutySubmissionResult:
        request = self.validate(request)
        if browser_session is not None and (
            request.user_id != browser_session.user_id
            or request.visible != browser_session.visible
        ):
            raise DutySubmissionValidationError("出入登打瀏覽器登入身分與任務不一致。")
        data = request.schedule_data
        actions = [dict(item) for item in data["actions"]]
        action = dict(actions[request.action_index])
        session_departures = getattr(browser_session, "known_open_departures", {})
        if self._checks_open_assignment(action, request):
            request = self._with_session_departures(request, browser_session, [str(action.get("target", ""))])
            data = request.schedule_data
        base_target_date = str(data["target_date"])
        action_date = action_target_roc_date(action, base_target_date)
        result_path = self._create_result_path(request, action)
        if self.is_stale_due_request(request):
            return self._finish_stale_request(request, action, result_path)
        automation = None
        driver = None
        try:
            automation = (
                browser_session.automation
                if browser_session is not None
                else self._load_automation()
            )
            if status_callback:
                status_callback("正在登入勤務系統…")
            if browser_session is not None:
                driver = browser_session.driver
            else:
                def initialize_browser(candidate: Any) -> None:
                    automation.login(candidate, request.user_id, request.password)

                session_builder = getattr(automation, "build_initialized_driver", None)
                if callable(session_builder):
                    driver = session_builder(
                        headless=not request.visible,
                        initialize=initialize_browser,
                    )
                else:
                    driver = automation.build_driver(headless=not request.visible)
                    initialize_browser(driver)
            action = self._refresh_action_before_submit(
                automation,
                driver,
                action,
                action_date,
                status_callback=status_callback,
                prefer_recent_schedule_snapshot=request.trigger_type == "due",
            )
            actions[request.action_index] = action
            comparison_source = dict(data)
            comparison_source["actions"] = actions
            query_range = self._query_range(request, action, action_date)
            if status_callback:
                status_callback("正在進行送出前防重複檢查…")
            query_started_callback = None
            if (
                status_callback
                and request.trigger_type in ("recovery", "manual")
                and request.schedule_data.get("_unreturned_return_queue_id")
            ):
                query_started_callback = lambda: status_callback(
                    UNRETURNED_RETURN_QUERY_STARTED_STATUS
                )
            before = self._query_comparison(
                automation,
                driver,
                action,
                action_date,
                query_range=query_range,
                query_started_callback=query_started_callback,
            )
            staff = action_staff(comparison_source, action)
            time_order_warnings: list[str] = []
            pause_details = self._open_assignment_pause_details(
                action,
                action_date,
                before,
                staff,
                request,
                query_range=query_range,
                time_order_warnings=time_order_warnings,
            )
            if self._checks_open_assignment(action, request) and isinstance(session_departures, dict):
                target = str(action.get("target", ""))
                if pause_details is None:
                    session_departures.pop(target, None)
                elif pause_details.get("unreturned_entry_at"):
                    session_departures[target] = pause_details["unreturned_entry_at"]
            if status_callback:
                for warning in time_order_warnings:
                    status_callback(warning)
            if pause_details is not None:
                pause_comparison = {
                    "compare": "未返隊，暫停登打",
                    "group": "paused",
                    "matched": [],
                    **pause_details,
                }
                return self._finish(
                    request,
                    action,
                    result_path,
                    "paused_external",
                    "尚未取得明確返隊確認，已暫停自動登打。",
                    pause_comparison,
                    time_order_warnings=time_order_warnings,
                )
            if action.get("kind") == "handoff_preflight":
                return self._finish(
                    request,
                    action,
                    result_path,
                    "handoff_preflight_ready",
                    "返隊檢查通過，可登打值退、值班與交接工作。",
                    {"compare": "返隊檢查通過", "group": "ready", "matched": []},
                    time_order_warnings=time_order_warnings,
                )
            comparison = self._comparison_for_action(
                comparison_source,
                actions,
                request.action_index,
                action_date,
                before,
            )
            submission_comparison = self._submission_comparison_for_action(
                comparison_source,
                actions,
                request.action_index,
                action_date,
                before,
                verify_saved=False,
            )
            group = str(comparison.get("group", "") or "")
            is_manual_unreturned_return_recovery = request.trigger_type == "manual" and bool(
                str(request.schedule_data.get("_unreturned_return_queue_id", "") or "").strip()
            )
            allows_manual_submission = request.trigger_type == "manual" and (
                group in ("manual", "adjust")
                or (
                    group == "review"
                    and (
                        str(action.get("source", "") or "").startswith("外勤")
                        or is_manual_unreturned_return_recovery
                    )
                )
            )
            if submission_comparison.get("group") == "done":
                if self._work_save_state(action, action_date) == "pending":
                    self._work_save_state(action, action_date, "confirmed")
                return self._finish(
                    request,
                    action,
                    result_path,
                    "skipped_duplicate",
                    "已存在相同紀錄，已略過重複登打。",
                    submission_comparison,
                    time_order_warnings=time_order_warnings,
                )
            if submission_comparison.get("group") == "review" or self._work_save_state(action, action_date) == "pending":
                return self._finish(
                    request, action, result_path, "review_required",
                    "已存在相同訓練但事由缺漏，或先前送出尚待確認；已停止重複送出。",
                    {**submission_comparison, "group": "review",
                     "confirmation_state": submission_comparison.get("confirmation_state") or "saved_not_verified"},
                    time_order_warnings=time_order_warnings,
                )
            if group in ("near", "adjust", "review", "manual") and not allows_manual_submission:
                return self._finish(
                    request,
                    action,
                    result_path,
                    "review_required",
                    "查到時間近似或需人工確認的紀錄，未自動送出。",
                    comparison,
                    time_order_warnings=time_order_warnings,
                )
            if (
                group == "future"
                and request.trigger_type == "due"
                and not self._allows_scheduled_checkout_preflight(action, action_date)
            ):
                return self._finish(
                    request,
                    action,
                    result_path,
                    "not_due",
                    "任務尚未到點，未送出。",
                    comparison,
                    time_order_warnings=time_order_warnings,
                )

            if status_callback:
                status_callback("正在填寫勤務系統表單…")
            def before_save() -> None:
                if self.is_stale_due_request(request):
                    raise _StaleDutyScheduleError()
                if request.save and action.get("kind") == "work_log":
                    self._work_save_state(action, action_date, "pending")

            if self.is_stale_due_request(request):
                raise _StaleDutyScheduleError()
            fill_form = (
                automation.fill_entry_log_form_for_test
                if action.get("kind") == "entry_log"
                else automation.fill_work_log_form_for_test
            )
            fill_kwargs = {"save": request.save}
            if "before_save" in signature(fill_form).parameters:
                fill_kwargs["before_save"] = before_save
            form_result = fill_form(driver, action, staff, action_date, **fill_kwargs)
            if not request.save:
                return self._finish(
                    request,
                    action,
                    result_path,
                    "filled",
                    "表單已填寫，未送出。",
                    {"group": "filled", "matched": [], "form_result": form_result},
                    time_order_warnings=time_order_warnings,
                )
            if action.get("kind") == "work_log":
                self._work_save_state(action, action_date, "pending")

            try:
                if status_callback:
                    status_callback("正在回查送出結果…")
                verified = {"group": "todo", "matched": []}
                for attempt in range(3):
                    after = self._query_comparison(
                        automation,
                        driver,
                        action,
                        action_date,
                        query_range=query_range,
                    )
                    verified = self._submission_comparison_for_action(
                        comparison_source,
                        actions,
                        request.action_index,
                        action_date,
                        after,
                        verify_saved=True,
                    )
                    if verified.get("group") == "done":
                        break
                    if attempt < 2:
                        if status_callback:
                            status_callback(f"登打後資料尚未顯示，正在第 {attempt + 2} 次確認。")
                        self.sleeper(1.0)
                if verified.get("group") != "done":
                    if action.get("kind") == "work_log":
                        return self._finish(
                            request, action, result_path, "review_required",
                            "已嘗試送出，但回查尚未確認；已停止自動重送，請核對勤務系統紀錄。",
                            {**verified, "group": "review", "confirmation_state": "saved_not_verified",
                             "form_result": {key: form_result[key] for key in ("save", "fill", "people") if key in form_result}},
                            time_order_warnings=time_order_warnings,
                        )
                    raise DutySubmissionExecutionError("登打後未在勤務系統查到已送出資料。")
                if action.get("kind") == "work_log":
                    self._work_save_state(action, action_date, "confirmed")
                verified = {**verified, "form_result": form_result}
                return self._finish(
                    request,
                    action,
                    result_path,
                    "submitted",
                    "勤務系統登打完成。",
                    verified,
                    time_order_warnings=time_order_warnings,
                )
            except DutySubmissionExecutionError:
                raise
            except Exception as exc:
                if status_callback:
                    status_callback("送出流程異常，正在以只讀查詢確認結果…")
                reconciled = self._reconcile_after_submit_error(
                    automation,
                    driver,
                    comparison_source,
                    actions,
                    request.action_index,
                    action_date,
                    query_range,
                    exc,
                )
                if reconciled is None:
                    raise
                if action.get("kind") == "work_log":
                    self._work_save_state(action, action_date, "confirmed")
                reconciled = {**reconciled, "form_result": form_result}
                return self._finish(
                    request,
                    action,
                    result_path,
                    "submitted",
                    "勤務系統登打完成；送出流程異常後已重新查詢確認資料存在。",
                    reconciled,
                    time_order_warnings=time_order_warnings,
                )
        except _StaleDutyScheduleError:
            return self._finish_stale_request(request, action, result_path)
        except DutySubmissionValidationError:
            raise
        except DutySubmissionExecutionError as exc:
            if self._work_save_state(action, action_date) == "pending":
                return self._finish_work_review(request, action, action_date, result_path, exc)
            self._write_failure(request, action, result_path, exc)
            exc.result_path = result_path
            raise
        except Exception as exc:
            if (
                getattr(exc, "diagnostic_category", "") == "work_form_incomplete"
                or self._work_save_state(action, action_date) == "pending"
            ):
                return self._finish_work_review(request, action, action_date, result_path, exc)
            self._write_failure(request, action, result_path, exc)
            message, error_code = self._safe_error(exc)
            raise DutySubmissionExecutionError(message, error_code, result_path) from exc
        finally:
            if browser_session is None and driver is not None and automation is not None:
                try:
                    automation.quit_driver(driver)
                except Exception:
                    pass

    def _work_save_state(
        self, action: Mapping[str, Any], action_date: str, stage: str | None = None,
    ) -> str:
        if action.get("kind") != "work_log":
            return ""
        key = f"{action_date}:{action_completion_key(action)}"
        digest = sha256(key.encode("utf-8")).hexdigest()
        path = self.package_root / "runtime_outputs" / "work_submission_holds" / f"{digest}.json"
        if stage is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            pending = path.with_suffix(".tmp")
            pending.write_text(json.dumps({"completion_key": key, "stage": stage}, ensure_ascii=False), encoding="utf-8")
            pending.replace(path)
            return stage
        if not path.exists():
            return ""
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return "confirmed" if value.get("completion_key") == key and value.get("stage") == "confirmed" else "pending"
        except (OSError, ValueError, AttributeError):
            return "pending"

    def _finish_work_review(
        self, request: DutySubmissionRequest, action: Mapping[str, Any], action_date: str,
        result_path: Path, exc: Exception,
    ) -> DutySubmissionResult:
        pending = self._work_save_state(action, action_date) == "pending"
        return self._finish(
            request, action, result_path, "review_required",
            "送出狀態尚待確認，已停止自動重送。" if pending else "工作表單事由或必填欄位未填妥，已停止送出。",
            {"group": "review", "matched": [],
             "confirmation_state": "saved_not_verified" if pending else "form_not_submitted",
             "confirmation_error_code": str(getattr(exc, "diagnostic_category", "") or self._safe_error(exc)[1])},
        )

    def _finish_stale_request(
        self,
        request: DutySubmissionRequest,
        action: Mapping[str, Any],
        result_path: Path,
    ) -> DutySubmissionResult:
        return self._finish(
            request, action, result_path, "skipped_stale_schedule",
            "消防日已切換，已略過前一消防日的自動登打。",
            {"group": "stale", "matched": []},
        )

    def is_stale_due_request(self, request: DutySubmissionRequest) -> bool:
        request = self.validate(request)
        current = self.now_factory()
        target_date = str(request.schedule_data["target_date"])
        action = request.schedule_data["actions"][request.action_index]
        return (
            request.trigger_type == "due"
            and target_date != business_roc_date(current)
            and not is_fire_day_closing_action(action, target_date, current)
        )

    def open_browser_session(
        self,
        request: DutySubmissionRequest,
        *,
        status_callback: Callable[[str], None] | None = None,
    ) -> DutySubmissionBrowserSession:
        """Create one authenticated browser without retaining the password."""

        request = self.validate(request)
        automation = None
        driver = None
        opened = False
        try:
            automation = self._load_automation()
            if status_callback:
                status_callback("正在建立勤務登打瀏覽器連線")
            def initialize_browser(candidate: Any) -> None:
                automation.login(candidate, request.user_id, request.password)

            session_builder = getattr(automation, "build_initialized_driver", None)
            if callable(session_builder):
                driver = session_builder(
                    headless=not request.visible,
                    initialize=initialize_browser,
                )
            else:
                driver = automation.build_driver(headless=not request.visible)
                initialize_browser(driver)
            session = DutySubmissionBrowserSession(
                automation=automation,
                driver=driver,
                user_id=request.user_id,
                visible=request.visible,
                last_activity_at=self.now_factory(),
            )
            if request.schedule_data.get("_handoff_entry_prewarm") is True:
                self.precheck_browser_session(request, session, status_callback=status_callback)
            opened = True
            return session
        except DutySubmissionValidationError:
            raise
        except DutySubmissionExecutionError:
            raise
        except Exception as exc:
            message, error_code = self._safe_error(exc)
            action = dict(request.schedule_data["actions"][request.action_index])
            result_path = self._create_result_path(request, action)
            self._write_failure(request, action, result_path, exc)
            raise DutySubmissionExecutionError(message, error_code, result_path) from exc
        finally:
            if not opened and driver is not None and automation is not None:
                try:
                    automation.quit_driver(driver)
                except Exception:
                    pass

    def close_browser_session(self, session: DutySubmissionBrowserSession | None) -> None:
        if session is None:
            return
        try:
            session.automation.quit_driver(session.driver)
        except Exception:
            pass

    def precheck_browser_session(
        self,
        request: DutySubmissionRequest,
        session: DutySubmissionBrowserSession,
        *,
        status_callback: Callable[[str], None] | None = None,
    ) -> None:
        """Refresh handoff evidence in an existing browser without logging in or saving."""
        request = self.validate(request)
        if request.user_id != session.user_id or request.visible != session.visible:
            raise DutySubmissionValidationError("交接預查瀏覽器登入身分與任務不一致。")
        if request.schedule_data.get("_handoff_entry_prewarm") is True:
            self._prewarm_return_check(request, session, status_callback=status_callback)

    def _prewarm_return_check(
        self,
        request: DutySubmissionRequest,
        session: DutySubmissionBrowserSession,
        *,
        status_callback: Callable[[str], None] | None = None,
    ) -> None:
        data = request.schedule_data
        anchor = data["actions"][request.action_index]
        incoming_actions = data.get("_handoff_entry_prewarm_actions")
        if isinstance(incoming_actions, list) and incoming_actions:
            checks = [
                {**item, "kind": "handoff_preflight"}
                for item in incoming_actions
                if isinstance(item, Mapping)
                and item.get("kind") == "entry_log"
                and isinstance(item.get("fields"), Mapping)
                and item["fields"].get("出或入") == "值班"
                and str(item.get("target", "")).isdigit()
            ]
            if len(checks) != len(incoming_actions):
                raise DutySubmissionExecutionError("交接預查接班資料不完整，未執行登打。", "unreturned_evidence_invalid")
        else:
            targets = data.get("_handoff_entry_prewarm_targets")
            if not isinstance(targets, (list, tuple)) or not targets:
                targets = [str(anchor.get("target", ""))]
            targets = list(dict.fromkeys(str(target) for target in targets if str(target).isdigit()))
            checks = [{**anchor, "kind": "handoff_preflight", "target": target} for target in targets]
        if not checks:
            raise DutySubmissionExecutionError("交接預查無法確認接班人員，未執行登打。", "unreturned_evidence_invalid")
        request = self._with_session_departures(request, session, [str(action["target"]) for action in checks])
        data = request.schedule_data
        for action in checks:
            self._validate_return_identity(action_staff(data, action), action, self._known_open_at(request, action))
        action_date = action_target_roc_date(checks[0], str(data["target_date"]))
        ranges = [
            self._query_range(request, action, action_target_roc_date(action, str(data["target_date"])))
            for action in checks
        ]
        if any(window is None for window in ranges):
            raise DutySubmissionExecutionError("交接預查日期範圍無法確認，未執行登打。", "unreturned_evidence_invalid")
        query_range = min(ranges, key=lambda window: window["start_at"])
        if status_callback:
            status_callback("正在預查前一日與當日的接班人員出入紀錄…")
        before = self._query_comparison(
            session.automation, session.driver, checks[0], action_date, query_range=query_range,
        )
        for action in checks:
            details = self._open_assignment_pause_details(
                action, action_target_roc_date(action, str(data["target_date"])), before,
                action_staff(data, action), request, query_range=query_range,
            )
            if details and details.get("unreturned_entry_at"):
                session.known_open_departures[str(action["target"])] = details["unreturned_entry_at"]

    def execute_with_browser_session(
        self,
        request: DutySubmissionRequest,
        session: DutySubmissionBrowserSession,
        *,
        status_callback: Callable[[str], None] | None = None,
    ) -> DutySubmissionResult:
        """Execute a request while keeping all pre-checks and verification enabled."""

        return self.execute(
            request,
            status_callback=status_callback,
            browser_session=session,
        )

    def _load_automation(self) -> ModuleType:
        try:
            return self.module_loader()
        except Exception as exc:
            raise DutySubmissionExecutionError("勤務登打模組無法載入。") from exc

    def _refresh_action_before_submit(
        self,
        automation: ModuleType,
        driver: object,
        action: Mapping[str, Any],
        action_date: str,
        *,
        status_callback: Callable[[str], None] | None,
        prefer_recent_schedule_snapshot: bool = False,
    ) -> dict[str, Any]:
        action = dict(action)
        if not (
            action.get("kind") == "work_log"
            and action.get("source") == "值班交接"
            and action.get("duplicate_key")
            and action_date == self._roc_date(self.now_factory().date())
        ):
            return action
        if prefer_recent_schedule_snapshot:
            recent_action = self._recent_handoff_action_from_schedule_snapshot(
                action,
                action_date,
            )
            if recent_action is not None:
                if status_callback:
                    status_callback("正在套用剛更新的值班交接資料…")
                return recent_action
        if status_callback:
            status_callback("正在重新查詢值班交接資料…")
        target = automation.parse_roc_date(action_date)
        yesterday = target - timedelta(days=1)
        tomorrow = target + timedelta(days=1)
        today_sheet = automation.query_duty_sheet(driver, automation.roc_date(target))
        yesterday_sheet = automation.query_duty_sheet(driver, automation.roc_date(yesterday))
        try:
            tomorrow_sheet = automation.query_duty_sheet(driver, automation.roc_date(tomorrow))
        except Exception:
            tomorrow_sheet = None
        yesterday_cases = automation.query_cases(driver, automation.roc_date(yesterday))
        cases = automation.query_cases(driver, automation.roc_date(target))
        latest_actions = automation.planned_actions(
            today_sheet,
            yesterday_sheet,
            cases,
            target,
            yesterday_cases,
            tomorrow_sheet,
        )
        duplicate_key = str(action.get("duplicate_key", "") or "")
        for latest in latest_actions:
            latest_mapping = self._mapping(latest)
            if str(latest_mapping.get("duplicate_key", "") or "") == duplicate_key:
                return self._merge_refreshed_handoff_action(action, latest_mapping)
        return action

    def _recent_handoff_action_from_schedule_snapshot(
        self,
        action: Mapping[str, Any],
        action_date: str,
    ) -> dict[str, Any] | None:
        duplicate_key = str(action.get("duplicate_key", "") or "").strip()
        if not duplicate_key:
            return None
        snapshot_path = (
            self.package_root
            / "runtime_outputs"
            / "schedule"
            / f"schedule_output_{action_date}.json"
        )
        try:
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        if (
            not isinstance(snapshot, Mapping)
            or str(snapshot.get("target_date", "") or "") != action_date
        ):
            return None
        try:
            created_at = datetime.fromisoformat(str(snapshot.get("created_at", "") or ""))
        except ValueError:
            return None
        if created_at.tzinfo is not None:
            created_at = created_at.replace(tzinfo=None)
        age = self.now_factory() - created_at
        if age < timedelta() or age > RECENT_HANDOFF_SCHEDULE_SNAPSHOT_MAX_AGE:
            return None
        latest_actions = snapshot.get("actions", [])
        if not isinstance(latest_actions, list):
            return None
        for latest in latest_actions:
            if not isinstance(latest, Mapping):
                continue
            latest_mapping = self._mapping(latest)
            if str(latest_mapping.get("duplicate_key", "") or "") == duplicate_key:
                return self._merge_refreshed_handoff_action(action, latest_mapping)
        return None

    @staticmethod
    def _merge_refreshed_handoff_action(
        action: Mapping[str, Any],
        latest_mapping: Mapping[str, Any],
    ) -> dict[str, Any]:
        merged = dict(latest_mapping)
        if not (action.get("submit_target_date") or action.get("_actual_handoff_adjusted")):
            return merged
        latest_fields = dict(merged.get("fields", {}))
        original_fields = action.get("fields", {})
        if action.get("submit_target_date"):
            if isinstance(original_fields, Mapping):
                for key in ("工作時間", "登打時間", "系統寫入時間"):
                    if key in original_fields:
                        latest_fields[key] = original_fields[key]
            merged["time"] = action.get("time", merged.get("time", ""))
            merged["submit_target_date"] = action["submit_target_date"]
        if isinstance(original_fields, Mapping):
            original_status = str(original_fields.get("處理情形", "") or "").splitlines()
            latest_status = str(latest_fields.get("處理情形", "") or "").splitlines()
            if (
                original_status and latest_status
                and original_status[0].startswith("一、時間:")
                and latest_status[0].startswith("一、時間:")
            ):
                # Keep actual handoff bounds without restoring stale case counts.
                latest_status[0] = original_status[0]
                latest_fields["處理情形"] = "\n".join(latest_status)
        merged["fields"] = latest_fields
        return merged

    def _open_assignment_pause_details(
        self,
        action: Mapping[str, Any],
        action_date: str,
        comparison_data: Mapping[str, Any],
        staff: Mapping[str, Mapping[str, Any]],
        request: DutySubmissionRequest,
        *,
        query_range: Mapping[str, Any] | None = None,
        time_order_warnings: list[str] | None = None,
    ) -> dict[str, str] | None:
        if not self._checks_open_assignment(action, request):
            return None
        known_open_at = self._known_open_at(request, action)
        self._validate_return_identity(staff, action, known_open_at)
        if self.open_assignment_checker is has_open_external_assignment:
            issues = self._return_evidence_issues(comparison_data, staff, action, self.now_factory())
            if issues:
                if known_open_at is not None:
                    return {
                        "unreturned_entry_at": known_open_at.isoformat(timespec="minutes"),
                        "evidence_state": "incomplete",
                        "evidence_issues": ",".join(issues),
                    }
                raise DutySubmissionExecutionError(
                    "返隊查核資料不足，出入方向或原因明細尚未確認，已停止自動登打。",
                    "unreturned_evidence_invalid",
                )
        now = self.now_factory()
        current_minute = now.hour * 60 + now.minute if action_date == self._roc_date(now.date()) else None
        query_start_date = (
            str(query_range.get("start_roc_date") or "") or None
            if query_range
            else None
        )
        query_end_date = (
            str(query_range.get("end_roc_date") or "") or None
            if query_range
            else None
        )
        rows = flatten_rows(
            comparison_data.get("visible_entry_rows", []) or [],
            action_date,
            start_date=query_start_date,
            end_date=query_end_date,
            entry_metadata=comparison_data.get("visible_entry_metadata"),
        )
        checker_kwargs: dict[str, Any] = {"current_minute": current_minute}
        if self.open_assignment_checker is has_open_external_assignment:
            checker_kwargs.update(
                {
                    "current_at": now if query_range else None,
                    "start_at": query_range.get("start_at") if query_range else None,
                    "end_at": query_range.get("end_at") if query_range else None,
                    "time_order_warnings": time_order_warnings,
                    "known_open_at": known_open_at,
                }
            )
        if not self.open_assignment_checker(
            rows,
            action_date,
            staff,
            action,
            **checker_kwargs,
        ):
            return None
        entry_at = find_open_external_assignment(
            rows,
            action_date,
            staff,
            action,
            current_minute=current_minute,
            current_at=now if query_range or current_minute is not None else None,
            start_at=query_range.get("start_at") if query_range else None,
            end_at=query_range.get("end_at") if query_range else None,
            known_open_at=known_open_at,
        )
        return {"unreturned_entry_at": entry_at} if entry_at else {}

    @staticmethod
    def _return_evidence_issues(
        comparison_data: Mapping[str, Any],
        staff: Mapping[str, Mapping[str, Any]],
        action: Mapping[str, Any],
        current_at: datetime,
    ) -> list[str]:
        target_name = clean(str(staff.get(str(action.get("target", "")), {}).get("name", "") or ""))
        if not target_name:
            return []  # A known departure remains open even if its roster is unavailable.
        metadata_rows = comparison_data.get("visible_entry_metadata")
        issues: list[tuple[datetime, str]] = []
        returns: list[datetime] = []
        for index, raw in enumerate(comparison_data.get("visible_entry_rows", []) or []):
            text = raw if isinstance(raw, str) else " | ".join(str(value) for value in raw)
            normalized = flatten_rows([raw], "", start_date="0000000", end_date="9999999")
            metadata = None
            if metadata_rows is not None:
                metadata = (
                    metadata_rows[index]
                    if isinstance(metadata_rows, list) and index < len(metadata_rows)
                    and isinstance(metadata_rows[index], Mapping) else {"_invalid": True}
                )
            fields = entry_row_fields(normalized[0] if normalized else text, metadata=metadata)
            if target_name not in (fields["primary_name"], fields["claimed_primary_name"]):
                continue
            row_at = datetime.fromisoformat(fields["record_at"]) if fields["record_at"] else current_at
            if row_at > current_at:
                continue
            direction = fields["direction"]
            if fields["evidence_conflict"] or not fields["record_at"]:
                issues.append((row_at, "entry_metadata_invalid"))
            elif direction in ("值班", "值退", "接班", "退班"):
                continue
            elif direction not in ("出", "入", "簽出", "外出", "簽入", "返隊", "到勤"):
                issues.append((row_at, "entry_direction_unknown"))
            elif fields["reason_state"] != "present" and not (
                direction in ("入", "簽入", "到勤") and fields["category"] == "到勤"
            ):
                issues.append((row_at, "entry_reason_missing"))
            elif direction in ("入", "簽入", "返隊", "到勤") and (
                clean(str(fields["reason"] or "")) == "返隊"
                or any(keyword in str(fields["reason"] or "") for keyword in EXTERNAL_ASSIGNMENT_KEYWORDS)
            ):
                returns.append(row_at)
        last_return = max(returns, default=datetime.min)
        return sorted({code for row_at, code in issues if row_at >= last_return})

    @staticmethod
    def _with_session_departures(
        request: DutySubmissionRequest,
        session: DutySubmissionBrowserSession | None,
        targets: list[str],
    ) -> DutySubmissionRequest:
        known = request.schedule_data.get("_unreturned_return_known_departures", {})
        observed = getattr(session, "known_open_departures", {})
        if not isinstance(observed, Mapping):
            raise DutySubmissionExecutionError("預查出勤證據格式不正確，已停止自動登打。", "unreturned_evidence_invalid")
        if not isinstance(known, Mapping):
            return request  # Do not turn malformed stored evidence into an empty map.
        merged = dict(known)
        for target in targets:
            if target not in observed:
                continue
            cached = observed.get(target)
            if not isinstance(cached, str) or not cached.strip():
                raise DutySubmissionExecutionError("預查出勤時間格式不正確，已停止自動登打。", "unreturned_evidence_invalid")
            stored = merged.get(target)
            if stored not in (None, "") and not isinstance(stored, str):
                continue
            if stored in (None, "") or cached > stored:
                merged[target] = cached
        if merged == dict(known):
            return request
        return replace(request, schedule_data={**request.schedule_data, "_unreturned_return_known_departures": merged})

    @staticmethod
    def _checks_open_assignment(action: Mapping[str, Any], request: DutySubmissionRequest) -> bool:
        fields = action.get("fields", {})
        return request.trigger_type in ("due", "recovery") and isinstance(fields, Mapping) and (
            action.get("kind") == "handoff_preflight" or (
                action.get("kind") == "entry_log"
                and fields.get("領用事由及地點", "") in ("退勤", "休息後退勤")
            )
        )

    def _validate_return_identity(
        self,
        staff: Mapping[str, Mapping[str, Any]],
        action: Mapping[str, Any],
        known_open_at: datetime | None,
    ) -> None:
        name = staff.get(str(action.get("target", "")), {}).get("name", "")
        if self.open_assignment_checker is has_open_external_assignment and known_open_at is None and not (
            isinstance(name, str) and name.strip()
        ):
            raise DutySubmissionExecutionError(
                "返隊檢查無法確認人員名冊，已停止自動登打。", "unreturned_evidence_invalid",
            )

    def _known_open_at(self, request: DutySubmissionRequest, action: Mapping[str, Any]) -> datetime | None:
        known = request.schedule_data.get("_unreturned_return_known_departures", {})
        if not isinstance(known, Mapping):
            raise DutySubmissionExecutionError("未返隊出勤資料格式不正確，已停止自動登打。", "unreturned_evidence_invalid")
        raw = known.get(str(action.get("target", "")))
        if raw in (None, ""):
            return None
        try:
            if not isinstance(raw, str):
                raise ValueError()
            known_at = datetime.fromisoformat(raw)
            if known_at > self.now_factory():
                raise ValueError()
            return known_at.replace(second=0, microsecond=0)
        except (TypeError, ValueError):
            raise DutySubmissionExecutionError("未返隊出勤時間無法確認，已停止自動登打。", "unreturned_evidence_invalid") from None

    def _should_pause_for_open_assignment(
        self,
        action: Mapping[str, Any],
        action_date: str,
        comparison_data: Mapping[str, Any],
        staff: Mapping[str, Mapping[str, Any]],
        request: DutySubmissionRequest,
        *,
        query_range: Mapping[str, Any] | None = None,
    ) -> bool:
        return (
            self._open_assignment_pause_details(
                action,
                action_date,
                comparison_data,
                staff,
                request,
                query_range=query_range,
            )
            is not None
        )

    @staticmethod
    def _mapping(value: Any) -> dict[str, Any]:
        if isinstance(value, Mapping):
            return dict(value)
        if is_dataclass(value):
            return asdict(value)
        return dict(vars(value))

    @staticmethod
    def _clock_minutes(value: Any) -> int | None:
        try:
            hour, minute = [int(part) for part in str(value or "").split(":", 1)]
        except (TypeError, ValueError):
            return None
        if not 0 <= hour < 24 or not 0 <= minute < 60:
            return None
        return hour * 60 + minute

    def _allows_scheduled_checkout_preflight(
        self,
        action: Mapping[str, Any],
        action_date: str,
    ) -> bool:
        if action.get("kind") != "entry_log":
            return False
        fields = action.get("fields", {})
        if not isinstance(fields, Mapping) or fields.get("領用事由及地點", "") != "退勤":
            return False
        now = self.now_factory()
        if action_date != self._roc_date(now.date()):
            return False
        start_minutes = self._clock_minutes(fields.get("登打時間") or action.get("time", ""))
        system_minutes = self._clock_minutes(fields.get("系統寫入時間"))
        if start_minutes is None or system_minutes is None:
            return False
        current_minutes = now.hour * 60 + now.minute
        return start_minutes <= current_minutes < system_minutes <= start_minutes + 5

    @staticmethod
    def _roc_date(value: date) -> str:
        return f"{value.year - 1911:03d}{value.month:02d}{value.day:02d}"

    def _query_range(
        self,
        request: DutySubmissionRequest,
        action: Mapping[str, Any],
        action_date: str,
    ) -> dict[str, Any] | None:
        raw_start = str(request.schedule_data.get("_unreturned_return_query_start_at", "") or "").strip()
        if self._checks_open_assignment(action, request):
            now = self.now_factory()
            try:
                start_at = datetime(
                    int(action_date[:3]) + 1911, int(action_date[3:5]), int(action_date[5:7]),
                ) - timedelta(days=1)
                earlier = [self._known_open_at(request, action)]
                if raw_start:
                    try:
                        earlier.append(datetime.fromisoformat(raw_start))
                    except ValueError:
                        pass
                for candidate in earlier:
                    if candidate is not None and candidate <= now:
                        start_at = min(start_at, candidate.replace(hour=0, minute=0, second=0, microsecond=0))
                if start_at > now:
                    raise ValueError()
            except (TypeError, ValueError):
                raise DutySubmissionExecutionError("返隊查詢日期範圍無法確認，已停止自動登打。", "unreturned_evidence_invalid") from None
            return {
                "start_at": start_at,
                "start_roc_date": self._roc_date(start_at.date()),
                "start_time": "00:00",
                "end_at": now,
                "end_roc_date": self._roc_date(now.date()),
                "end_time": now.strftime("%H:%M"),
            }
        if raw_start:
            try:
                start_at = datetime.fromisoformat(raw_start)
            except ValueError:
                return None
            now = self.now_factory()
            if start_at > now:
                return None
            # Include an earlier return for the same case when source times are reversed.
            start_at = start_at.replace(hour=0, minute=0, second=0, microsecond=0)
            return {
                "start_at": start_at,
                "start_roc_date": self._roc_date(start_at.date()),
                "start_time": start_at.strftime("%H:%M"),
                "end_at": now,
                "end_roc_date": self._roc_date(now.date()),
                "end_time": now.strftime("%H:%M"),
            }
        if (
            action.get("kind") != "work_log"
            or action.get("source") == "案件工作審核"
        ):
            return None
        fields = action.get("fields", {})
        work_time = (
            fields.get("工作時間") if isinstance(fields, Mapping) else ""
        ) or action.get("time", "")
        work_minutes = self._clock_minutes(work_time)
        if work_minutes is None:
            return None
        try:
            work_at = datetime(
                int(action_date[:3]) + 1911,
                int(action_date[3:5]),
                int(action_date[5:7]),
            ) + timedelta(minutes=work_minutes)
        except ValueError:
            return None
        start_at = work_at - ROUTINE_WORK_LOG_QUERY_WINDOW
        end_at = work_at + ROUTINE_WORK_LOG_QUERY_WINDOW
        return {
            "start_at": start_at,
            "start_roc_date": self._roc_date(start_at.date()),
            "start_time": start_at.strftime("%H:%M"),
            "end_at": end_at,
            "end_roc_date": self._roc_date(end_at.date()),
            "end_time": end_at.strftime("%H:%M"),
        }

    @staticmethod
    def _query_visible_rows(
        automation: ModuleType,
        driver: object,
        ap_name: str,
        action_date: str,
        query_kwargs: Mapping[str, str],
        *,
        query_started_callback: Callable[[], None] | None = None,
    ) -> list[Any]:
        query_options = dict(query_kwargs)
        if query_started_callback is not None:
            query_options["query_started_callback"] = query_started_callback
        try:
            return automation.query_visible_table(
                driver,
                ap_name,
                action_date,
                **query_options,
            )
        except TypeError as exc:
            if not query_options or "unexpected keyword argument" not in str(exc):
                raise
            return automation.query_visible_table(driver, ap_name, action_date)

    @staticmethod
    def _query_comparison(
        automation: ModuleType,
        driver: object,
        action: Mapping[str, Any],
        action_date: str,
        *,
        query_range: Mapping[str, Any] | None = None,
        query_started_callback: Callable[[], None] | None = None,
    ) -> dict[str, list[Any]]:
        query_kwargs = (
            {
                "start_roc_date": query_range["start_roc_date"],
                "start_time": query_range["start_time"],
                "end_roc_date": query_range["end_roc_date"],
                "end_time": query_range["end_time"],
            }
            if query_range
            else {}
        )
        if action.get("kind") in ("entry_log", "handoff_preflight"):
            rows = DutySubmissionService._query_visible_rows(
                automation,
                driver,
                automation.ENTRY_LOG_AP,
                action_date,
                query_kwargs,
                query_started_callback=query_started_callback,
            )
            result = {"visible_entry_rows": rows, "visible_work_rows": []}
            if getattr(rows, "entry_metadata", None) is not None:
                result["visible_entry_metadata"] = rows.entry_metadata
            return result
        rows = DutySubmissionService._query_visible_rows(
            automation,
            driver,
            automation.WORK_LOG_AP,
            action_date,
            query_kwargs,
        )
        return {"visible_entry_rows": [], "visible_work_rows": rows}

    def _comparison_for_action(
        self,
        data: Mapping[str, Any],
        actions: list[Mapping[str, Any]],
        index: int,
        action_date: str,
        comparison_data: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        comparisons = self.comparison_builder(data, actions, {action_date: comparison_data})
        return comparisons.get(index, {"compare": "未找到", "group": "todo", "matched": []})

    def _submission_comparison_for_action(
        self,
        data: Mapping[str, Any],
        actions: list[Mapping[str, Any]],
        index: int,
        action_date: str,
        comparison_data: Mapping[str, Any],
        *,
        verify_saved: bool = False,
    ) -> Mapping[str, Any]:
        if not 0 <= index < len(actions):
            return {"compare": "未找到", "group": "todo", "matched": []}
        action = actions[index]
        if action.get("kind") in ("entry_log", "work_log"):
            return compare_submission_action(
                data,
                action,
                action_date,
                comparison_data,
                verify_saved=verify_saved,
            )
        return self._comparison_for_action(data, actions, index, action_date, comparison_data)

    def _reconcile_after_submit_error(
        self,
        automation: ModuleType,
        driver: object,
        data: Mapping[str, Any],
        actions: list[Mapping[str, Any]],
        index: int,
        action_date: str,
        query_range: Mapping[str, Any] | None,
        exc: Exception,
    ) -> Mapping[str, Any] | None:
        """Do one read-only lookup after an unexpected submission-side error."""

        try:
            after = self._query_comparison(
                automation,
                driver,
                actions[index],
                action_date,
                query_range=query_range,
            )
            verified = self._submission_comparison_for_action(
                data,
                actions,
                index,
                action_date,
                after,
                verify_saved=True,
            )
        except Exception:
            return None
        if verified.get("group") != "done":
            return None
        _message, error_code = self._safe_error(exc)
        return {
            **verified,
            "confirmation_state": "reconciled_after_submission_error",
            "confirmation_error_code": error_code,
        }

    @staticmethod
    def _staff(data: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        today = data.get("today", {})
        yesterday = data.get("yesterday", {})
        today_staff = today.get("staff", {}) if isinstance(today, Mapping) else {}
        yesterday_staff = yesterday.get("staff", {}) if isinstance(yesterday, Mapping) else {}
        return {
            str(number): dict(info)
            for number, info in {**yesterday_staff, **today_staff}.items()
            if isinstance(info, Mapping)
        }

    def _create_result_path(
        self,
        request: DutySubmissionRequest,
        action: Mapping[str, Any],
    ) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        kind = "entry_log" if action.get("kind") == "entry_log" else "work_log"
        path = self.output_dir / (
            f"{kind}_qt_{self.now_factory():%Y%m%d_%H%M%S_%f}_{request.action_index}.json"
        )
        self._write_result(
            path,
            {
                "stage": "started",
                "action_index": request.action_index,
                "action": dict(action),
                "trigger_type": request.trigger_type,
                "save": request.save,
                "visible": request.visible,
            },
        )
        return path

    def _finish(
        self,
        request: DutySubmissionRequest,
        action: Mapping[str, Any],
        path: Path,
        status: str,
        message: str,
        comparison: Mapping[str, Any],
        *,
        time_order_warnings: list[str] | None = None,
    ) -> DutySubmissionResult:
        if time_order_warnings:
            comparison = {
                **comparison,
                "external_time_order_warnings": list(time_order_warnings),
            }
        self._write_result(
            path,
            {
                "stage": status,
                "action_index": request.action_index,
                "action": dict(action),
                "trigger_type": request.trigger_type,
                "save": request.save,
                "visible": request.visible,
                "comparison": dict(comparison),
                "updated_at": self.now_factory().isoformat(timespec="seconds"),
            },
        )
        return DutySubmissionResult(request.action_index, status, message, path, comparison, dict(action))

    def _write_failure(
        self,
        request: DutySubmissionRequest,
        action: Mapping[str, Any],
        path: Path,
        error: BaseException,
    ) -> None:
        self._write_result(
            path,
            {
                "stage": "failed",
                "exception": diagnostic_exception(error, (request.password,)),
                "action_index": request.action_index,
                "action": dict(action),
                "trigger_type": request.trigger_type,
                "save": request.save,
                "visible": request.visible,
                "updated_at": self.now_factory().isoformat(timespec="seconds"),
            },
        )

    @staticmethod
    def _write_result(path: Path, payload: Mapping[str, Any]) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _safe_error(exc: Exception) -> tuple[str, str]:
        if getattr(exc, "error_code", "") == "invalid_credentials":
            return "帳號或密碼錯誤，已停止登入。", "invalid_credentials"
        category = str(getattr(exc, "diagnostic_category", "") or "")
        if category == "entry_form_incomplete":
            return "出入方向或表單欄位尚未確認，未送出；請檢查勤務系統表單。", "entry_form_incomplete"
        if category == "browser_session_open":
            return (
                "SinpoSmart 專用瀏覽器在登入或開啟勤務頁面時中斷，已使用新的工作階段重試。"
                "若仍失敗，請重新登入後再試或匯出問題包。",
                "browser_session_open",
            )
        if category:
            return (
                "SinpoSmart 專用瀏覽器啟動失敗，已自動清理暫存資料並重試。"
                "一般 Chrome 不需關閉；若仍失敗請通知管理人員。",
                "browser_startup",
            )
        text = str(exc or "")
        lowered = text.lower()
        if any(marker in text for marker in ("登入失敗", "帳號或密碼", "重新登入")):
            return "登入失敗：請登出後重新登入系統。", "login_failed"
        if "timeout" in lowered or "timed out" in lowered or "逾時" in text:
            return "網頁等待逾時，請檢查網站狀態。", "timeout"
        if "nosuchelement" in lowered or "no such element" in lowered:
            return "找不到網頁元素，網站可能已改版。", "no_such_element"
        return "勤務系統登打失敗，請查看結果檔案。", "unknown_error"
