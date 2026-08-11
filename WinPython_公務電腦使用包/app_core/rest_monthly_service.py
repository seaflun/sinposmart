# -*- coding: utf-8 -*-
"""UI-independent boundary for rest-time and monthly-base automation."""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Callable


LEGACY_MODULE_NAME = "_sinposmart_qt_rest_monthly_automation"
LEGACY_SCRIPT_NAME = "rest_time_automation.py"


class RestMonthlyValidationError(ValueError):
    """A safe request-validation message for the native forms."""


class RestMonthlyExecutionError(RuntimeError):
    """A safe execution failure for the native forms."""

    def __init__(
        self,
        message: str,
        *,
        failure_stage: str = "unknown",
        failure_detail: str = "",
    ) -> None:
        super().__init__(message)
        self.failure_stage = failure_stage
        self.failure_detail = failure_detail


@dataclass(frozen=True)
class RestMonthlyDefaults:
    roc_year: int
    month_options: tuple[str, ...]
    selected_month: str
    workbook_path: str = ""


@dataclass(frozen=True)
class RestTimeRequest:
    user_id: str
    password: str = field(repr=False)
    actor_no: str
    workbook_path: str
    roc_year: int
    month: int
    actor_name: str = ""


@dataclass(frozen=True)
class MonthlyBaseRequest:
    user_id: str
    password: str = field(repr=False)
    actor_no: str
    roc_year: int
    month: int
    actor_name: str = ""


def load_legacy_module(package_root: Path) -> ModuleType:
    script_path = package_root / LEGACY_SCRIPT_NAME
    source_mtime = script_path.stat().st_mtime
    existing = sys.modules.get(LEGACY_MODULE_NAME)
    if (
        existing is not None
        and getattr(existing, "__sinposmart_source_path__", None) == str(script_path)
        and getattr(existing, "__sinposmart_source_mtime__", None) == source_mtime
    ):
        return existing
    sys.modules.pop(LEGACY_MODULE_NAME, None)
    importlib.invalidate_caches()
    spec = importlib.util.spec_from_file_location(LEGACY_MODULE_NAME, script_path)
    if spec is None or spec.loader is None:
        raise RestMonthlyExecutionError("休息時間自動化模組無法載入。")
    module = importlib.util.module_from_spec(spec)
    sys.modules[LEGACY_MODULE_NAME] = module
    sys.path.insert(0, str(package_root))
    try:
        spec.loader.exec_module(module)
    finally:
        try:
            sys.path.remove(str(package_root))
        except ValueError:
            pass
    module.__sinposmart_source_path__ = str(script_path)
    module.__sinposmart_source_mtime__ = source_mtime
    return module


class RestMonthlyService:
    def __init__(
        self,
        package_root: Path,
        *,
        module_loader: Callable[[Path], ModuleType] = load_legacy_module,
    ) -> None:
        self.package_root = Path(package_root)
        self.config_path = self.package_root / "rest_time_automation_config.json"
        self.module_loader = module_loader

    def load_rest_defaults(self, today: date | None = None) -> RestMonthlyDefaults:
        return self._rest_defaults(
            self._default_workbook(),
            today,
            use_saved_month=False,
            use_workbook_month=False,
        )

    def select_rest_workbook(
        self,
        workbook_path: str | Path,
        today: date | None = None,
    ) -> RestMonthlyDefaults:
        workbook = Path(str(workbook_path or "").strip()).expanduser()
        if not workbook.is_absolute():
            workbook = self.package_root / workbook
        workbook = workbook.resolve()
        if not workbook.is_file() or workbook.suffix.lower() not in (".xlsx", ".xlsm"):
            raise RestMonthlyValidationError("請選擇有效的勤務表 Excel 檔案（.xlsx 或 .xlsm）。")
        self._save_workbook_path(workbook)
        return self._rest_defaults(workbook, today, use_saved_month=False)

    def _rest_defaults(
        self,
        workbook: Path | None,
        today: date | None,
        *,
        use_saved_month: bool = True,
        use_workbook_month: bool = True,
    ) -> RestMonthlyDefaults:
        roc_year, current_month = self._current_roc_year_month(today)
        selected_month = current_month
        month_options = self._nearby_months(current_month)
        if use_workbook_month and workbook is not None:
            try:
                import openpyxl

                book = openpyxl.load_workbook(workbook, data_only=True, read_only=True)
                try:
                    workbook_month = int(book.worksheets[0].cell(row=2, column=5).value)
                finally:
                    book.close()
                if workbook_month in self._nearby_months(current_month):
                    selected_month = workbook_month
            except Exception:
                pass
        if use_saved_month:
            selected_month = self._saved_month("rest_month", month_options, selected_month)
        return RestMonthlyDefaults(
            roc_year=roc_year,
            month_options=tuple(f"{month:02d}" for month in month_options),
            selected_month=f"{selected_month:02d}",
            workbook_path=str(workbook) if workbook else "",
        )

    def load_monthly_defaults(self, today: date | None = None) -> RestMonthlyDefaults:
        roc_year, current_month = self._current_roc_year_month(today)
        month_options = self._nearby_months(current_month)
        return RestMonthlyDefaults(
            roc_year=roc_year,
            month_options=tuple(f"{month:02d}" for month in month_options),
            selected_month=f"{current_month:02d}",
        )

    def validate_rest(self, request: RestTimeRequest) -> RestTimeRequest:
        self._validate_identity(request.user_id, request.password, request.actor_no, request.actor_name)
        workbook = Path(str(request.workbook_path or "").strip()).expanduser()
        if not workbook.is_absolute():
            workbook = self.package_root / workbook
        workbook = workbook.resolve()
        if not workbook.is_file() or workbook.suffix.lower() not in (".xlsx", ".xlsm"):
            raise RestMonthlyValidationError("請選擇有效的勤務表 Excel 檔案（.xlsx 或 .xlsm）。")
        self._validate_year_month(request.roc_year, request.month)
        return RestTimeRequest(
            request.user_id.strip(),
            request.password,
            request.actor_no.strip(),
            str(workbook),
            int(request.roc_year),
            int(request.month),
            request.actor_name.strip(),
        )

    def validate_monthly(self, request: MonthlyBaseRequest) -> MonthlyBaseRequest:
        self._validate_identity(request.user_id, request.password, request.actor_no, request.actor_name)
        self._validate_year_month(request.roc_year, request.month)
        return MonthlyBaseRequest(
            request.user_id.strip(),
            request.password,
            request.actor_no.strip(),
            int(request.roc_year),
            int(request.month),
            request.actor_name.strip(),
        )

    @staticmethod
    def confirmation_summary(request: RestTimeRequest | MonthlyBaseRequest) -> str:
        action = "休息時間登打" if isinstance(request, RestTimeRequest) else "勤務基準表登打"
        workbook = f"\nExcel：{Path(request.workbook_path).name}" if isinstance(request, RestTimeRequest) else ""
        return (
            f"作業：{action}\n年月：{request.roc_year}年{request.month:02d}月{workbook}\n\n"
            "確認後將登入正式勤務系統並送出資料。"
        )

    def execute_rest(
        self,
        request: RestTimeRequest,
        *,
        status_callback: Callable[[str], None] | None = None,
        stage_callback: Callable[[str], None] | None = None,
    ) -> str:
        stage = "preflight"

        def report_stage(value: str) -> None:
            nonlocal stage
            stage = value
            if stage_callback is not None:
                stage_callback(value)

        report_stage(stage)
        request = self.validate_rest(request)
        self._save_settings(
            workbook_path=request.workbook_path,
            rest_month=request.month,
        )
        legacy = self._legacy()
        try:
            result = legacy.submit_rest_entries(
                request.user_id,
                request.password,
                Path(request.workbook_path),
                False,
                status_callback,
                keep_browser_open=False,
                actor_no="" if request.actor_name else request.actor_no,
                actor_name=request.actor_name,
                expected_roc_year=request.roc_year,
                expected_month=request.month,
                stage_callback=report_stage,
            )
            return str(result)
        except Exception as exc:
            raise RestMonthlyExecutionError(
                self._format_error(legacy, exc, "休息時間登打失敗。"),
                failure_stage=stage,
                failure_detail=self._failure_detail(exc),
            ) from exc

    def execute_monthly(
        self,
        request: MonthlyBaseRequest,
        *,
        status_callback: Callable[[str], None] | None = None,
        stage_callback: Callable[[str], None] | None = None,
    ) -> str:
        stage = "preflight"

        def report_stage(value: str) -> None:
            nonlocal stage
            stage = value
            if stage_callback is not None:
                stage_callback(value)

        report_stage(stage)
        request = self.validate_monthly(request)
        self._save_settings(monthly_base_month=request.month)
        legacy = self._legacy()
        try:
            result = legacy.submit_monthly_base_entries(
                request.user_id,
                request.password,
                "" if request.actor_name else request.actor_no,
                False,
                status_callback,
                keep_browser_open=False,
                expected_roc_year=request.roc_year,
                expected_month=request.month,
                actor_name=request.actor_name,
                stage_callback=report_stage,
            )
            return str(result)
        except Exception as exc:
            raise RestMonthlyExecutionError(
                self._format_error(legacy, exc, "勤務基準表登打失敗。"),
                failure_stage=stage,
                failure_detail=self._failure_detail(exc),
            ) from exc

    def _legacy(self) -> ModuleType:
        if not (self.package_root / LEGACY_SCRIPT_NAME).is_file():
            raise RestMonthlyExecutionError("找不到休息時間自動化模組。")
        try:
            return self.module_loader(self.package_root)
        except RestMonthlyExecutionError:
            raise
        except Exception as exc:
            raise RestMonthlyExecutionError("休息時間自動化模組無法載入。") from exc

    def _default_workbook(self) -> Path | None:
        saved = self._load_saved_workbook_path()
        if saved is not None and saved.is_file():
            return saved
        candidates = sorted(
            self.package_root.glob("*.xlsm"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        return candidates[0].resolve() if candidates else None

    def _load_saved_workbook_path(self) -> Path | None:
        value = str(self._load_settings().get("workbook_path", "") or "").strip()
        if not value:
            return None
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = self.package_root / path
        return path.resolve()

    def _save_workbook_path(self, path: Path) -> None:
        self._save_settings(workbook_path=path)

    def _saved_month(self, key: str, month_options: tuple[int, ...], fallback: int) -> int:
        try:
            saved_month = int(str(self._load_settings().get(key, "") or "").strip())
        except ValueError:
            return fallback
        return saved_month if saved_month in month_options else fallback

    def _load_settings(self) -> dict[str, object]:
        if not self.config_path.is_file():
            return {}
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        return dict(payload) if isinstance(payload, dict) else {}

    def _save_settings(
        self,
        *,
        workbook_path: str | Path | None = None,
        rest_month: int | None = None,
        monthly_base_month: int | None = None,
    ) -> None:
        payload = self._load_settings()
        if workbook_path is not None:
            payload["workbook_path"] = str(workbook_path)
        if rest_month is not None:
            payload["rest_month"] = f"{int(rest_month):02d}"
        if monthly_base_month is not None:
            payload["monthly_base_month"] = f"{int(monthly_base_month):02d}"
        try:
            self.config_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    @staticmethod
    def _format_error(legacy: ModuleType, exc: Exception, fallback: str) -> str:
        failure_detail = RestMonthlyService._failure_detail(exc)
        if failure_detail == "browser_session_open":
            return (
                "SinpoSmart 專用瀏覽器在登入或開啟勤務頁面時中斷，已使用新的工作階段重試。"
                "若仍失敗，請重新登入後再試或匯出問題包。"
            )
        if failure_detail == "browser_startup":
            return (
                "SinpoSmart 專用瀏覽器啟動失敗，已自動清理暫存資料並重試。"
                "一般 Chrome 不需關閉；若仍失敗，請先在 NAS 值班後台查看工具卡片的錯誤詳情。"
            )
        formatter = getattr(legacy, "format_automation_error", None)
        if callable(formatter):
            message = str(formatter(exc) or "").strip()
            if message:
                return message
        return str(exc).strip() or fallback

    @staticmethod
    def _failure_detail(exc: Exception) -> str:
        category = str(getattr(exc, "diagnostic_category", "") or "")
        if category == "browser_session_open":
            return category
        return "browser_startup" if category else ""

    @staticmethod
    def _validate_identity(user_id: str, password: str, actor_no: str, actor_name: str = "") -> None:
        if not str(user_id or "").strip() or not password:
            raise RestMonthlyValidationError("請先完成勤務系統登入。")
        if not str(actor_name or "").strip() and not str(actor_no or "").strip():
            raise RestMonthlyValidationError("登入資料缺少人員姓名。")

    @staticmethod
    def _validate_year_month(roc_year: int, month: int) -> None:
        if int(roc_year) < 1 or not 1 <= int(month) <= 12:
            raise RestMonthlyValidationError("請選擇正確的民國年月。")

    @staticmethod
    def _current_roc_year_month(today: date | None = None) -> tuple[int, int]:
        current = today or date.today()
        return current.year - 1911, current.month

    @staticmethod
    def _nearby_months(center: int) -> tuple[int, int, int]:
        return tuple(((center + offset - 1) % 12) + 1 for offset in (-1, 0, 1))
