# -*- coding: utf-8 -*-
"""Live, read-only duty schedule and comparison capture boundary."""

from __future__ import annotations

import importlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Mapping

from app_core.duty_task_projection import build_schedule_comparisons, comparison_dates
from app_core.schedule_repository import ScheduleSnapshot, business_roc_date


class ScheduleCaptureValidationError(ValueError):
    """A safe capture-request validation message."""


class ScheduleCaptureError(RuntimeError):
    """A safe live-capture failure message."""

    def __init__(self, message: str, error_code: str = "unknown_error") -> None:
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True)
class ScheduleCaptureRequest:
    user_id: str
    password: str = field(repr=False)
    actor_no: str
    target_roc_date: str
    actor_name: str = ""


def load_automation_module() -> ModuleType:
    return importlib.import_module("duty_rehearsal")


def resolve_authenticated_actor(
    driver: Any,
    staff: Mapping[str, Mapping[str, Any]],
) -> tuple[str, str]:
    from app_core.login_verifier import identify_logged_in_actor

    def actor_no_from_name(actor_name: str) -> str:
        normalized_name = "".join(str(actor_name or "").split())
        matches = [
            str(actor_no or "").strip()
            for actor_no, info in staff.items()
            if "".join(str(info.get("name", "") or "").split()) == normalized_name
        ]
        return matches[0] if len(matches) == 1 else ""

    return identify_logged_in_actor(driver, actor_no_from_name, dict(staff))


def actor_identity_from_name(
    staff: Mapping[str, Mapping[str, Any]],
    actor_name: str,
) -> tuple[str, str]:
    normalized_name = "".join(str(actor_name or "").split())
    if not normalized_name:
        return "", ""
    exact = [
        (str(actor_no or "").strip(), str(info.get("name", "") or "").strip())
        for actor_no, info in staff.items()
        if "".join(str(info.get("name", "") or "").split()) == normalized_name
    ]
    if len(exact) == 1:
        return exact[0]
    contained = [
        (str(actor_no or "").strip(), str(info.get("name", "") or "").strip())
        for actor_no, info in staff.items()
        if (staff_name := "".join(str(info.get("name", "") or "").split()))
        and (staff_name in normalized_name or normalized_name in staff_name)
    ]
    return contained[0] if len(contained) == 1 else ("", "")


class ScheduleCaptureService:
    def __init__(
        self,
        package_root: Path,
        *,
        module_loader: Callable[[], ModuleType] = load_automation_module,
        now_factory: Callable[[], datetime] = datetime.now,
        identity_resolver: Callable[
            [Any, Mapping[str, Mapping[str, Any]]],
            tuple[str, str],
        ] = resolve_authenticated_actor,
    ) -> None:
        self.package_root = Path(package_root)
        self.runtime_dir = self.package_root / "runtime_outputs"
        self.module_loader = module_loader
        self.now_factory = now_factory
        self.identity_resolver = identity_resolver

    def current_request(
        self,
        user_id: str,
        password: str,
        actor_no: str,
        actor_name: str = "",
    ) -> ScheduleCaptureRequest:
        return ScheduleCaptureRequest(
            user_id,
            password,
            actor_no,
            business_roc_date(self.now_factory()),
            actor_name,
        )

    def validate(self, request: ScheduleCaptureRequest) -> ScheduleCaptureRequest:
        if not str(request.user_id or "").strip() or not request.password:
            raise ScheduleCaptureValidationError("請先完成勤務系統登入。")
        target = str(request.target_roc_date or "").strip()
        if len(target) != 7 or not target.isdigit():
            raise ScheduleCaptureValidationError("勤務表日期格式不正確。")
        return ScheduleCaptureRequest(
            request.user_id.strip(),
            request.password,
            str(request.actor_no or "").strip(),
            target,
            str(request.actor_name or "").strip(),
        )

    def capture(
        self,
        request: ScheduleCaptureRequest,
        *,
        status_callback: Callable[[str], None] | None = None,
    ) -> ScheduleSnapshot:
        request = self.validate(request)
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="sinposmart-live") as executor:
            schedule_future = executor.submit(
                self.capture_schedule,
                request,
                status_callback=status_callback,
            )
            comparison_future = executor.submit(
                self.capture_comparisons,
                request,
                status_callback=status_callback,
            )
            schedule_snapshot = schedule_future.result()
            comparison_data = comparison_future.result()
        return self.combine_capture(schedule_snapshot, comparison_data)

    def capture_schedule(
        self,
        request: ScheduleCaptureRequest,
        *,
        status_callback: Callable[[str], None] | None = None,
    ) -> ScheduleSnapshot:
        request = self.validate(request)
        stage = "load_automation"
        automation = None
        driver = None
        try:
            automation = self._load_automation()
            if status_callback:
                status_callback("正在即時查詢勤務表…")
            def initialize_browser(candidate: Any) -> None:
                nonlocal stage
                stage = "login"
                automation.login(candidate, request.user_id, request.password)

            stage = "start_browser"
            session_builder = getattr(automation, "build_initialized_driver", None)
            if callable(session_builder):
                driver = session_builder(headless=True, initialize=initialize_browser)
            else:
                driver = automation.build_driver(headless=True)
                initialize_browser(driver)
            target = automation.parse_roc_date(request.target_roc_date)
            stage = "today_duty_sheet"
            today_sheet = automation.query_duty_sheet(driver, automation.roc_date(target))
            authenticated_actor_no, authenticated_actor_name = actor_identity_from_name(
                today_sheet.staff,
                request.actor_name,
            )
            if not authenticated_actor_no:
                try:
                    authenticated_actor_no, authenticated_actor_name = self.identity_resolver(
                        driver,
                        today_sheet.staff,
                    )
                except Exception:
                    pass
            if not authenticated_actor_no:
                try:
                    site_actor_name = automation.query_authenticated_person_name(
                        driver,
                        request.user_id,
                    )
                    authenticated_actor_no, authenticated_actor_name = actor_identity_from_name(
                        today_sheet.staff,
                        site_actor_name,
                    )
                except Exception:
                    pass
            yesterday = target - timedelta(days=1)
            tomorrow = target + timedelta(days=1)
            stage = "yesterday_duty_sheet"
            yesterday_sheet = automation.query_duty_sheet(driver, automation.roc_date(yesterday))
            try:
                stage = "tomorrow_duty_sheet"
                tomorrow_sheet = automation.query_duty_sheet(driver, automation.roc_date(tomorrow))
            except Exception:
                tomorrow_sheet = None
            if status_callback:
                status_callback("正在查詢未返隊案件…")
            stage = "yesterday_cases"
            yesterday_cases = automation.query_cases(driver, automation.roc_date(yesterday))
            stage = "today_cases"
            cases = automation.query_cases(driver, automation.roc_date(target))
            stage = "planned_actions"
            actions = automation.planned_actions(
                today_sheet,
                yesterday_sheet,
                cases,
                target,
                yesterday_cases,
                tomorrow_sheet,
            )
            payload = {
                "file_type": "schedule",
                "target_date": request.target_roc_date,
                "created_at": self.now_factory().isoformat(timespec="seconds"),
                "today": asdict(today_sheet),
                "yesterday": asdict(yesterday_sheet),
                "tomorrow": asdict(tomorrow_sheet) if tomorrow_sheet is not None else None,
                "cases": [asdict(item) for item in cases],
                "yesterday_cases": [asdict(item) for item in yesterday_cases],
                "actions": [asdict(item) for item in actions],
            }
            schedule_path = self.runtime_dir / "schedule" / f"schedule_output_{request.target_roc_date}.json"
            stage = "write_schedule_snapshot"
            self._write_json(schedule_path, payload)
            stamp = self.now_factory().strftime("%H%M%S")
            self._write_json(
                self.runtime_dir / "snapshots" / f"schedule_output_{request.target_roc_date}_qt-login_{stamp}.json",
                payload,
            )
            cached_comparison_data = {
                action_date: self._read_comparison_data(action_date)
                for action_date in comparison_dates(payload["actions"], request.target_roc_date)
            }
            return ScheduleSnapshot(
                schedule_path,
                payload,
                request.target_roc_date,
                build_schedule_comparisons(payload, payload["actions"], cached_comparison_data),
                schedule_data_by_date={request.target_roc_date: payload},
                authenticated_actor_no=str(authenticated_actor_no or "").strip(),
                authenticated_actor_name=str(authenticated_actor_name or "").strip(),
            )
        except (ScheduleCaptureValidationError, ScheduleCaptureError) as exc:
            self._write_capture_failure_diagnostic(stage, request, exc)
            raise
        except Exception as exc:
            self._write_capture_failure_diagnostic(stage, request, exc)
            message, error_code = self._safe_error(exc)
            raise ScheduleCaptureError(message, error_code) from exc
        finally:
            if driver is not None and automation is not None:
                try:
                    automation.quit_driver(driver)
                except Exception:
                    pass

    def capture_comparisons(
        self,
        request: ScheduleCaptureRequest,
        *,
        status_callback: Callable[[str], None] | None = None,
    ) -> dict[str, dict[str, Any]]:
        request = self.validate(request)
        stage = "load_automation"
        automation = self._load_automation()
        driver = None
        try:
            if status_callback:
                status_callback("正在背景比對已登打資料…")
            def initialize_browser(candidate: Any) -> None:
                nonlocal stage
                stage = "login"
                automation.login(candidate, request.user_id, request.password)

            stage = "start_browser"
            session_builder = getattr(automation, "build_initialized_driver", None)
            if callable(session_builder):
                driver = session_builder(headless=True, initialize=initialize_browser)
            else:
                driver = automation.build_driver(headless=True)
                initialize_browser(driver)
            target = automation.parse_roc_date(request.target_roc_date)
            comparison_data: dict[str, dict[str, Any]] = {}
            for action_date in [target + timedelta(days=offset) for offset in (-1, 0, 1)]:
                target_roc_date = automation.roc_date(action_date)
                stage = f"work_rows_{target_roc_date}"
                payload = {
                    "file_type": "comparison",
                    "target_date": target_roc_date,
                    "created_at": self.now_factory().isoformat(timespec="seconds"),
                    "visible_work_rows": automation.query_visible_table(
                        driver,
                        automation.WORK_LOG_AP,
                        target_roc_date,
                    ),
                    "visible_entry_rows": [],
                }
                stage = f"entry_rows_{target_roc_date}"
                payload["visible_entry_rows"] = automation.query_visible_table(
                    driver,
                    automation.ENTRY_LOG_AP,
                    target_roc_date,
                )
                comparison_data[target_roc_date] = payload
                stage = f"write_output_{target_roc_date}"
                self._write_json(
                    self.runtime_dir / "comparison" / f"comparison_output_{target_roc_date}.json",
                    payload,
                )
            return comparison_data
        except (ScheduleCaptureValidationError, ScheduleCaptureError) as exc:
            self._write_capture_failure_diagnostic(f"comparison_{stage}", request, exc)
            raise
        except Exception as exc:
            self._write_capture_failure_diagnostic(f"comparison_{stage}", request, exc)
            message, error_code = self._safe_error(exc)
            raise ScheduleCaptureError(message, error_code) from exc
        finally:
            if driver is not None:
                try:
                    automation.quit_driver(driver)
                except Exception:
                    pass

    @staticmethod
    def combine_capture(
        schedule_snapshot: ScheduleSnapshot,
        comparison_data: Mapping[str, Mapping[str, Any]],
    ) -> ScheduleSnapshot:
        normalized_comparison_data = {
            str(target_date): dict(payload)
            for target_date, payload in comparison_data.items()
            if isinstance(payload, Mapping)
        }
        payload = dict(schedule_snapshot.data)
        actions = payload.get("actions", [])
        actions = actions if isinstance(actions, list) else []
        return ScheduleSnapshot(
            schedule_snapshot.path,
            payload,
            schedule_snapshot.target_roc_date,
            build_schedule_comparisons(payload, actions, normalized_comparison_data),
            comparison_data=normalized_comparison_data,
            schedule_data_by_date=dict(schedule_snapshot.schedule_data_by_date),
            authenticated_actor_no=schedule_snapshot.authenticated_actor_no,
            authenticated_actor_name=schedule_snapshot.authenticated_actor_name,
        )

    def _read_comparison_data(self, target_roc_date: str) -> dict[str, Any]:
        path = self.runtime_dir / "comparison" / f"comparison_output_{target_roc_date}.json"
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _load_automation(self) -> ModuleType:
        try:
            return self.module_loader()
        except Exception as exc:
            raise ScheduleCaptureError("勤務查詢模組無法載入。", "module_load_failed") from exc

    @staticmethod
    def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def _write_capture_failure_diagnostic(
        self,
        stage: str,
        request: ScheduleCaptureRequest,
        exc: BaseException,
    ) -> None:
        """Keep only the actionable failure point; never persist credentials or page data."""

        message = " ".join(str(exc or "").split())
        if request.password:
            message = message.replace(request.password, "[REDACTED]")
        payload = {
            "captured_at": self.now_factory().isoformat(timespec="seconds"),
            "target_roc_date": request.target_roc_date,
            "stage": str(stage or "unknown"),
            "exception_type": type(exc).__name__,
            "message": message[:500],
        }
        try:
            self._write_json(self.runtime_dir / "browser" / "schedule_capture_failure.json", payload)
        except OSError:
            return

    @staticmethod
    def _safe_error(exc: Exception) -> tuple[str, str]:
        category = str(getattr(exc, "diagnostic_category", "") or "")
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
            return "即時勤務查詢逾時，已停用自動登打。", "timeout"
        return "即時勤務查詢失敗，已停用自動登打。", "unknown_error"
