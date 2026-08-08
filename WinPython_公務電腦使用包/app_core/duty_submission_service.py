# -*- coding: utf-8 -*-
"""UI-independent single-action boundary for duty-system submission."""

from __future__ import annotations

import importlib
import json
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from time import sleep
from types import ModuleType
from typing import Any, Callable, Mapping

from app_core.duty_task_projection import action_target_roc_date, build_schedule_comparisons
from app_core.schedule_repository import business_roc_date
from compare_rehearsal_records import flatten_rows, has_open_external_assignment


class DutySubmissionValidationError(ValueError):
    """A safe request-validation message for Qt controllers."""


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


@dataclass(frozen=True)
class DutySubmissionRequest:
    user_id: str
    password: str = field(repr=False)
    action_index: int
    schedule_data: Mapping[str, Any]
    trigger_type: str = "due"
    save: bool = True
    visible: bool = False


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
        if request.trigger_type not in ("due", "manual", "recovery"):
            raise DutySubmissionValidationError("登打觸發類型不正確。")
        return DutySubmissionRequest(
            user_id=request.user_id.strip(),
            password=request.password,
            action_index=int(request.action_index),
            schedule_data=data,
            trigger_type=request.trigger_type,
            save=bool(request.save),
            visible=bool(request.visible),
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
        base_target_date = str(data["target_date"])
        action_date = action_target_roc_date(action, base_target_date)
        result_path = self._create_result_path(request, action)
        if self.is_stale_due_request(request):
            return self._finish(
                request,
                action,
                result_path,
                "skipped_stale_schedule",
                "消防日已切換，已略過前一消防日的自動登打。",
                {"group": "stale", "matched": []},
            )
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
            driver = (
                browser_session.driver
                if browser_session is not None
                else automation.build_driver(headless=not request.visible)
            )
            if browser_session is None:
                automation.login(driver, request.user_id, request.password)
            action = self._refresh_action_before_submit(
                automation,
                driver,
                action,
                action_date,
                status_callback=status_callback,
            )
            actions[request.action_index] = action
            comparison_source = dict(data)
            comparison_source["actions"] = actions
            if status_callback:
                status_callback("正在進行送出前防重複檢查…")
            before = self._query_comparison(automation, driver, action, action_date)
            staff = self._staff(comparison_source)
            if self._should_pause_for_open_assignment(action, action_date, before, staff, request):
                return self._finish(
                    request,
                    action,
                    result_path,
                    "paused_external",
                    "人員尚未返隊，已暫停退勤登打。",
                    {"compare": "未返隊，暫停登打", "group": "paused", "matched": []},
                )
            if action.get("kind") == "handoff_preflight":
                return self._finish(
                    request,
                    action,
                    result_path,
                    "handoff_preflight_ready",
                    "接班人員已返隊，可登打值退、值班與交接工作。",
                    {"compare": "接班人員已返隊", "group": "ready", "matched": []},
                )
            comparison = self._comparison_for_action(
                comparison_source,
                actions,
                request.action_index,
                action_date,
                before,
            )
            group = str(comparison.get("group", "") or "")
            allows_manual_submission = request.trigger_type == "manual" and (
                group in ("manual", "adjust")
                or (
                    group == "review"
                    and str(action.get("source", "") or "").startswith("外勤")
                )
            )
            if group == "done":
                return self._finish(
                    request,
                    action,
                    result_path,
                    "skipped_duplicate",
                    "已存在相同紀錄，已略過重複登打。",
                    comparison,
                )
            if group in ("near", "adjust", "review", "manual") and not allows_manual_submission:
                return self._finish(
                    request,
                    action,
                    result_path,
                    "review_required",
                    "查到時間近似或需人工確認的紀錄，未自動送出。",
                    comparison,
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
                )

            if status_callback:
                status_callback("正在填寫勤務系統表單…")
            if action.get("kind") == "entry_log":
                form_result = automation.fill_entry_log_form_for_test(
                    driver,
                    action,
                    staff,
                    action_date,
                    save=request.save,
                )
            else:
                form_result = automation.fill_work_log_form_for_test(
                    driver,
                    action,
                    staff,
                    action_date,
                    save=request.save,
                )
            if not request.save:
                return self._finish(
                    request,
                    action,
                    result_path,
                    "filled",
                    "表單已填寫，未送出。",
                    {"group": "filled", "matched": [], "form_result": form_result},
                )

            if status_callback:
                status_callback("正在回查送出結果…")
            verified = {"group": "todo", "matched": []}
            for attempt in range(3):
                after = self._query_comparison(automation, driver, action, action_date)
                verified = self._comparison_for_action(
                    comparison_source,
                    actions,
                    request.action_index,
                    action_date,
                    after,
                )
                if verified.get("group") == "done":
                    break
                if attempt < 2:
                    if status_callback:
                        status_callback(f"登打後資料尚未顯示，正在第 {attempt + 2} 次確認。")
                    self.sleeper(1.0)
            if verified.get("group") != "done":
                raise DutySubmissionExecutionError("登打後未在勤務系統查到已送出資料。")
            verified = {**verified, "form_result": form_result}
            return self._finish(
                request,
                action,
                result_path,
                "submitted",
                "勤務系統登打完成。",
                verified,
            )
        except DutySubmissionValidationError:
            raise
        except DutySubmissionExecutionError as exc:
            if not result_path.is_file():
                self._write_failure(request, action, result_path)
            exc.result_path = result_path
            raise
        except Exception as exc:
            self._write_failure(request, action, result_path)
            message, error_code = self._safe_error(exc)
            raise DutySubmissionExecutionError(message, error_code, result_path) from exc
        finally:
            if browser_session is None and driver is not None and automation is not None:
                try:
                    automation.quit_driver(driver)
                except Exception:
                    pass

    def is_stale_due_request(self, request: DutySubmissionRequest) -> bool:
        request = self.validate(request)
        return (
            request.trigger_type == "due"
            and str(request.schedule_data["target_date"]) != business_roc_date(self.now_factory())
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
                status_callback("正在建立出入登打瀏覽器連線")
            driver = automation.build_driver(headless=not request.visible)
            automation.login(driver, request.user_id, request.password)
            opened = True
            return DutySubmissionBrowserSession(
                automation=automation,
                driver=driver,
                user_id=request.user_id,
                visible=request.visible,
            )
        except DutySubmissionValidationError:
            raise
        except DutySubmissionExecutionError:
            raise
        except Exception as exc:
            message, error_code = self._safe_error(exc)
            raise DutySubmissionExecutionError(message, error_code) from exc
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
    ) -> dict[str, Any]:
        action = dict(action)
        if not (
            action.get("kind") == "work_log"
            and action.get("source") == "值班交接"
            and action.get("duplicate_key")
            and action_date == self._roc_date(self.now_factory().date())
        ):
            return action
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
                if action.get("submit_target_date"):
                    latest_fields = dict(latest_mapping.get("fields", {}))
                    original_fields = action.get("fields", {})
                    if isinstance(original_fields, Mapping):
                        for key in ("工作時間", "登打時間", "系統寫入時間"):
                            if key in original_fields:
                                latest_fields[key] = original_fields[key]
                    latest_mapping["fields"] = latest_fields
                    latest_mapping["time"] = action.get("time", latest_mapping.get("time", ""))
                    latest_mapping["submit_target_date"] = action["submit_target_date"]
                return latest_mapping
        return action

    def _should_pause_for_open_assignment(
        self,
        action: Mapping[str, Any],
        action_date: str,
        comparison_data: Mapping[str, Any],
        staff: Mapping[str, Mapping[str, Any]],
        request: DutySubmissionRequest,
    ) -> bool:
        if request.trigger_type not in ("due", "recovery"):
            return False
        fields = action.get("fields", {})
        if not isinstance(fields, Mapping):
            return False
        if action.get("kind") == "handoff_preflight":
            pass
        elif action.get("kind") == "entry_log" and fields.get("領用事由及地點", "") in ("退勤", "休息後退勤"):
            pass
        else:
            return False
        now = self.now_factory()
        current_minute = now.hour * 60 + now.minute if action_date == self._roc_date(now.date()) else None
        rows = flatten_rows(comparison_data.get("visible_entry_rows", []) or [], action_date)
        return bool(
            self.open_assignment_checker(
                rows,
                action_date,
                staff,
                action,
                current_minute=current_minute,
            )
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

    @staticmethod
    def _query_comparison(
        automation: ModuleType,
        driver: object,
        action: Mapping[str, Any],
        action_date: str,
    ) -> dict[str, list[Any]]:
        if action.get("kind") in ("entry_log", "handoff_preflight"):
            rows = automation.query_visible_table(driver, automation.ENTRY_LOG_AP, action_date)
            return {"visible_entry_rows": rows, "visible_work_rows": []}
        rows = automation.query_visible_table(driver, automation.WORK_LOG_AP, action_date)
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
    ) -> DutySubmissionResult:
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
    ) -> None:
        self._write_result(
            path,
            {
                "stage": "failed",
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
        if getattr(exc, "diagnostic_category", ""):
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
