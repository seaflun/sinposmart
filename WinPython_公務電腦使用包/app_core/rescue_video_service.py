# -*- coding: utf-8 -*-
"""UI-independent boundary for rescue dashcam classification."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from types import ModuleType
from typing import Callable


CORE_MODULE_NAME = "_sinposmart_qt_rescue_video_core"
CORE_SCRIPT_NAME = "救護影片分類GUI.py"


class RescueVideoValidationError(ValueError):
    """A user-facing validation failure for the native QML form."""


class RescueVideoExecutionError(RuntimeError):
    """A safe execution failure for the native QML form."""

    def __init__(self, message: str, *, failure_stage: str = "unknown") -> None:
        super().__init__(message)
        self.failure_stage = failure_stage


@dataclass(frozen=True)
class RescueVideoDefaults:
    source_path: str
    destination_path: str
    target_date: str
    vehicle_options: tuple[str, ...]
    selected_vehicle: str
    offset_text: str = ""
    repair_mismatch: bool = False
    check_text: str = ""
    is_ready: bool = True
    status_text: str = "自動檢查通過"
    check_cards: tuple["RescueVideoCheckCard", ...] = ()


@dataclass(frozen=True)
class RescueVideoCheckCard:
    """One stable, user-visible result from the rescue-video preflight."""

    key: str
    title: str
    detail: str
    level: str


@dataclass(frozen=True)
class RescueVideoRequest:
    source_path: str
    destination_path: str
    target_date: str
    vehicle: str
    offset_text: str
    repair_mismatch: bool
    mode: str


@dataclass(frozen=True)
class RescueVideoRunResult:
    summary_text: str
    warning_text: str
    report_path: str
    rows: tuple[dict[str, str], ...]


def load_rescue_video_core(package_root: Path) -> ModuleType:
    rescue_dir = Path(package_root) / "rescue_video"
    script_path = rescue_dir / CORE_SCRIPT_NAME
    source_mtime = script_path.stat().st_mtime
    existing = sys.modules.get(CORE_MODULE_NAME)
    if (
        existing is not None
        and getattr(existing, "__sinposmart_source_path__", None) == str(script_path)
        and getattr(existing, "__sinposmart_source_mtime__", None) == source_mtime
    ):
        return existing

    sys.modules.pop(CORE_MODULE_NAME, None)
    importlib.invalidate_caches()
    spec = importlib.util.spec_from_file_location(CORE_MODULE_NAME, script_path)
    if spec is None or spec.loader is None:
        raise RescueVideoExecutionError("救護影片分類核心無法載入。")
    module = importlib.util.module_from_spec(spec)
    sys.modules[CORE_MODULE_NAME] = module
    sys.path.insert(0, str(rescue_dir))
    try:
        spec.loader.exec_module(module)
    finally:
        try:
            sys.path.remove(str(rescue_dir))
        except ValueError:
            pass
    module.__sinposmart_source_path__ = str(script_path)
    module.__sinposmart_source_mtime__ = source_mtime
    return module


class RescueVideoService:
    def __init__(
        self,
        package_root: Path,
        *,
        module_loader: Callable[[Path], ModuleType] = load_rescue_video_core,
    ) -> None:
        self.package_root = Path(package_root)
        self.module_loader = module_loader

    def load_defaults(
        self,
        today: date | str | None = None,
        *,
        source_path: str = "",
        vehicle: str = "",
    ) -> RescueVideoDefaults:
        core = self.module_loader(self.package_root)
        if isinstance(today, str):
            date_text = today.strip() or date.today().strftime("%Y-%m-%d")
        else:
            date_text = (today or date.today()).strftime("%Y-%m-%d")
        destination = Path(core.DEFAULT_DESTINATION)
        source = str(source_path or "").strip()
        manual_source_error = ""
        if source and not core.is_memory_card_source(Path(source)):
            source = ""
            manual_source_error = "請選擇記憶卡內的 DCIM\\100CAREC 資料夾。"
        if not source and not manual_source_error:
            try:
                source = str(core.classifier.resolve_source(None))
            except OSError:
                pass
        values: dict[str, object] = {
            "source": source,
            "destination": str(destination),
            "date": date_text,
            "vehicle": str(vehicle or "").strip(),
            "offset_minutes": "6",
            "work_log_root": str(core.DEFAULT_WORK_LOG_ROOT),
            "report": str(core.DEFAULT_REPORT),
            "repair_mismatch": False,
        }
        try:
            state = core.evaluate_preflight(values)
        except (OSError, ValueError):
            state = None
        vehicles = tuple(state.vehicles) if state is not None else ()
        selected_vehicle = str(vehicle or "").strip()
        if selected_vehicle not in vehicles:
            selected_vehicle = vehicles[0] if vehicles else ""
        values["vehicle"] = selected_vehicle
        if selected_vehicle:
            values["report"] = str(core.build_public_duty_report_path(date_text, selected_vehicle))

        offset_text = ""
        is_ready = False
        check_state = None
        check_lines: list[str] = [manual_source_error] if manual_source_error else []
        try:
            check_state = core.evaluate_preflight(values)
            check_lines.extend(str(check.detail) for check in check_state.checks.values())
            if check_state.ready:
                args = core.build_args(values, "preview")
                offset_text = str(core.choose_runtime_offset(args))
                check_lines.append(f"自動採用記憶卡偏移：{offset_text} 分鐘")
                is_ready = True
        except (OSError, ValueError, SystemExit) as exc:
            check_lines.append(f"無法判定記憶卡偏移：{exc}")

        card_titles = (
            ("source", "記憶卡來源"),
            ("destination", "案件目的地"),
            ("work_log", "工作／返隊紀錄"),
            ("vehicle_date", "車號與日期"),
            ("report", "報告輸出"),
            ("videos", "影片檢查"),
        )
        checks = getattr(check_state, "checks", {})
        check_cards: list[RescueVideoCheckCard] = []
        for key, title in card_titles:
            check = checks.get(key)
            detail = str(getattr(check, "detail", "尚未取得檢查結果"))
            level = str(getattr(check, "level", "error"))
            if key == "source" and manual_source_error:
                detail = manual_source_error
                level = "error"
            check_cards.append(RescueVideoCheckCard(key, title, detail, level))

        return RescueVideoDefaults(
            source_path=source,
            destination_path=str(destination),
            target_date=date_text,
            vehicle_options=vehicles,
            selected_vehicle=selected_vehicle,
            offset_text=offset_text,
            check_text="\n".join(check_lines),
            is_ready=is_ready,
            status_text="自動檢查通過" if is_ready else "等待必要資料",
            check_cards=tuple(check_cards),
        )

    def validate(self, request: RescueVideoRequest) -> tuple[RescueVideoRequest, list[str], dict[str, object]]:
        core = self.module_loader(self.package_root)
        mode = str(request.mode or "").strip()
        if mode not in ("preview", "copy", "delete"):
            raise RescueVideoValidationError("救護影片操作模式不正確。")
        try:
            datetime.strptime(str(request.target_date or "").strip(), "%Y-%m-%d")
        except ValueError as exc:
            raise RescueVideoValidationError("日期格式必須是 YYYY-MM-DD。") from exc
        if not str(request.vehicle or "").strip():
            raise RescueVideoValidationError("請選擇救護車號。")

        report = core.build_public_duty_report_path(request.target_date, request.vehicle)
        values: dict[str, object] = {
            "source": str(request.source_path or "").strip(),
            "destination": str(request.destination_path or "").strip(),
            "date": str(request.target_date or "").strip(),
            "vehicle": str(request.vehicle or "").strip(),
            "offset_minutes": str(request.offset_text or "").strip() or "0",
            "work_log_root": str(core.DEFAULT_WORK_LOG_ROOT),
            "report": str(report),
            "repair_mismatch": bool(request.repair_mismatch),
        }
        errors, warnings = core.validate_form(values, mode)
        if errors:
            raise RescueVideoValidationError("\n".join(str(error) for error in errors))
        normalized = RescueVideoRequest(
            source_path=str(values["source"]),
            destination_path=str(values["destination"]),
            target_date=str(values["date"]),
            vehicle=str(values["vehicle"]),
            offset_text=str(request.offset_text or "").strip(),
            repair_mismatch=bool(request.repair_mismatch),
            mode=mode,
        )
        return normalized, [str(warning) for warning in warnings], values

    def confirmation_summary(self, request: RescueVideoRequest) -> str:
        normalized, warnings, _values = self.validate(request)
        if normalized.mode == "delete":
            return "只有複製並完成內容驗證的 .TS 檔案會刪除。\n確定要繼續嗎？"
        warning_text = f"\n注意：{'；'.join(warnings)}" if warnings else ""
        action_text = (
            "確認後會複製影片並核對目的地，不會刪除來源影片。"
            if normalized.mode == "copy"
            else "確認後會先複製並核對檔案，只有核對成功的來源影片才會刪除。"
        )
        return (
            f"日期：{normalized.target_date}\n車號：{normalized.vehicle}\n"
            f"來源：{normalized.source_path or '自動偵測記憶卡'}\n\n"
            f"{action_text}"
            f"{warning_text}"
        )

    def execute(
        self,
        request: RescueVideoRequest,
        *,
        status_callback: Callable[[str], None] | None = None,
        stage_callback: Callable[[str], None] | None = None,
    ) -> RescueVideoRunResult:
        stage = "preflight"

        def report_stage(value: str) -> None:
            nonlocal stage
            stage = value
            if stage_callback is not None:
                stage_callback(value)

        report_stage(stage)
        report_stage("module_load")
        core = self.module_loader(self.package_root)
        normalized, warnings, values = self.validate(request)
        try:
            args = core.build_args(values, normalized.mode)
            if not normalized.offset_text:
                report_stage("offset_detection")
                if status_callback:
                    status_callback("正在自動判定記憶卡時間偏移…")
                args.offset_minutes = core.choose_runtime_offset(args)
            if status_callback:
                status_callback("正在預覽影片分類…" if normalized.mode == "preview" else "正在分類並核對來源影片…")
            report_stage("classification")
            try:
                results = core.run_classification(args, stage_callback=report_stage)
            except TypeError as exc:
                if "stage_callback" not in str(exc):
                    raise
                results = core.run_classification(args)
        except (OSError, ValueError) as exc:
            raise RescueVideoExecutionError(str(exc) or "救護影片分類失敗。") from exc

        rows = tuple(self._result_row(core, result) for result in results)
        summary = core.format_summary(core.summarize_results(results))
        return RescueVideoRunResult(
            summary_text=summary,
            warning_text="；".join(warnings),
            report_path=str(args.report),
            rows=rows,
        )

    @staticmethod
    def _result_row(core: ModuleType, result) -> dict[str, str]:
        case = getattr(result, "case", None)
        destination = getattr(result, "destination", None)
        adjusted_time = getattr(result, "adjusted_time", None)
        status = str(getattr(result, "status", "") or "")
        return {
            "sourceText": Path(getattr(result, "source", "")).name,
            "timeText": adjusted_time.strftime("%m/%d %H:%M:%S") if adjusted_time else "",
            "caseText": str(getattr(case, "name", "") or "待確認"),
            "statusText": status,
            "destinationText": str(destination or ""),
            "noteText": str(getattr(result, "note", "") or ""),
            "tone": str(core.status_tag(status) or "normal"),
        }
