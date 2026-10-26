# -*- coding: utf-8 -*-
"""UI-independent boundary for rescue dashcam classification."""

from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from types import ModuleType
from typing import Callable


CORE_MODULE_NAME = "_sinposmart_qt_rescue_video_core"
CORE_SCRIPT_NAME = "rescue_video_core.py"


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
    status_text: str = "檢查結果通過"
    check_cards: tuple["RescueVideoCheckCard", ...] = ()
    source_identity: str = ""
    available_dates: tuple[str, ...] = ()
    source_hint: str = ""


@dataclass(frozen=True)
class RescueVideoCheckCard:
    """One stable, user-visible result from the rescue-video preflight."""

    key: str
    title: str
    detail: str
    level: str
    code: str = ""


@dataclass(frozen=True)
class RescueVideoRequest:
    source_path: str
    destination_path: str
    target_date: str
    vehicle: str
    offset_text: str
    repair_mismatch: bool
    mode: str
    source_identity: str = ""


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
        self._card_selections: dict[str, tuple[str, str]] = {}

    def remember_selection(self, identity: str, target_date: str, vehicle: str) -> None:
        if not identity:
            return
        try:
            datetime.strptime(target_date, "%Y-%m-%d")
        except ValueError:
            return
        self._card_selections[identity] = (target_date, vehicle)
        while len(self._card_selections) > 16:
            self._card_selections.pop(next(iter(self._card_selections)))

    def load_defaults(
        self,
        today: date | str | None = None,
        *,
        source_path: str = "",
        vehicle: str = "",
        inspect_videos: bool = False,
        expected_source_identity: str = "",
        status_callback: Callable[[str], None] | None = None,
    ) -> RescueVideoDefaults:
        core = self.module_loader(self.package_root)
        if status_callback is not None:
            status_callback("讀取記憶卡")
        destination = Path(core.DEFAULT_DESTINATION)
        source = ""
        source_error = ""
        source_code = ""
        videos: list[Path] = []
        try:
            source = str(core.normalize_memory_card_source(Path(source_path))) if source_path else str(core.classifier.resolve_source(None))
            videos = core.classifier.discover_sources(Path(source), ".TS")
        except FileExistsError:
            source_error = "偵測到多張記憶卡，請按「選擇記憶卡」。"
            source_code = "source_multiple"
        except (OSError, ValueError, SystemExit) as exc:
            source_error = f"記憶卡讀取失敗：{exc}" if source else str(exc) if source_path else "請插入記憶卡，或按「選擇記憶卡」。"
            source_code = "source_unreadable" if source else "source_invalid" if source_path else "source_missing"
        identity = core.card_identity(Path(source)) if source else ""
        counts: Counter[str] = Counter()
        for video in videos:
            try:
                counts[datetime.fromtimestamp(video.stat().st_mtime).strftime("%Y-%m-%d")] += 1
            except OSError:
                continue
        dates = tuple(sorted(counts, reverse=True))
        remembered_date, remembered_vehicle = self._card_selections.get(identity, ("", ""))
        changed_card = bool(expected_source_identity and identity != expected_source_identity)
        provided_date = today.strip() if isinstance(today, str) else today.strftime("%Y-%m-%d") if today else ""
        if changed_card:
            provided_date = ""
        suggested_date = max(counts, key=lambda value: (counts[value], value)) if counts else date.today().strftime("%Y-%m-%d")
        date_text = provided_date or (remembered_date if remembered_date and (not dates or remembered_date in dates) else suggested_date)
        selected_vehicle = "" if changed_card else str(vehicle or "").strip()
        if not selected_vehicle and not changed_card and date_text == remembered_date:
            selected_vehicle = remembered_vehicle
        values: dict[str, object] = {
            "source": source,
            "source_error": source_error,
            "source_error_code": source_code,
            "destination": str(destination),
            "date": date_text,
            "vehicle": selected_vehicle,
            "offset_minutes": "0",
            "work_log_root": str(core.DEFAULT_WORK_LOG_ROOT),
            "report": str(core.DEFAULT_REPORT),
            "repair_mismatch": False,
        }
        try:
            check_state = core.evaluate_preflight(
                values, inspect_videos=inspect_videos, video_sources=videos, stage_callback=status_callback
            )
        except (OSError, ValueError, SystemExit) as exc:
            check_state = core.PreflightState(
                {"destination": core.PreflightCheck("destination", "error", f"案件清單讀取失敗：{exc}", "case_lookup_failed")},
                [],
            )
        vehicles = tuple(check_state.vehicles)
        if selected_vehicle not in vehicles:
            selected_vehicle = ""
        is_ready = check_state.ready and bool(selected_vehicle)
        check_lines = [str(check.detail) for check in check_state.checks.values()]

        card_titles = (
            ("source", "記憶卡"),
            ("destination", "備份位置"),
            ("work_log", "勤務紀錄"),
            ("vehicle_date", "日期／車號"),
            ("report", "備份報告"),
            ("videos", "影片"),
        )
        checks = getattr(check_state, "checks", {})
        check_cards: list[RescueVideoCheckCard] = []
        for key, title in card_titles:
            check = checks.get(key)
            detail = str(getattr(check, "detail", "尚未檢查"))
            level = str(getattr(check, "level", "pending"))
            check_cards.append(RescueVideoCheckCard(key, title, detail, level, str(getattr(check, "code", ""))))
        if identity:
            self.remember_selection(identity, date_text, selected_vehicle)
        date_hint = dates[-1] if len(dates) == 1 else f"{dates[-1]}～{dates[0]}" if dates else ""
        source_hint = f"{len(videos)} 段" + (f"｜{date_hint}" if date_hint else "") if source else "尚未讀到記憶卡"
        if changed_card:
            source_hint = "記憶卡已變更，請確認日期與車號。"

        return RescueVideoDefaults(
            source_path=source,
            destination_path=str(destination),
            target_date=date_text,
            vehicle_options=vehicles,
            selected_vehicle=selected_vehicle,
            offset_text="0",
            check_text="\n".join(check_lines),
            is_ready=is_ready,
            status_text="可以預覽" if is_ready else "請補齊資料",
            check_cards=tuple(check_cards),
            source_identity=identity,
            available_dates=dates,
            source_hint=source_hint,
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
        if request.source_identity and core.card_identity(Path(request.source_path)) != request.source_identity:
            raise RescueVideoValidationError("記憶卡已變更，請重新讀取並預覽。")

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
            source_identity=request.source_identity,
        )
        return normalized, [str(warning) for warning in warnings], values

    def confirmation_summary(self, request: RescueVideoRequest) -> str:
        normalized, warnings, _values = self.validate(request)
        warning_text = f"\n注意：{'；'.join(warnings)}" if warnings else ""
        if normalized.mode == "delete":
            return (
                f"日期：{normalized.target_date}\n車號：{normalized.vehicle}\n"
                f"來源：{normalized.source_path or '自動偵測記憶卡'}\n\n"
                "備份並逐檔驗證後，清理成功的來源影片。\n"
                "待確認及失敗影片會保留。"
                f"{warning_text}"
            )
        action_text = (
            "備份並逐檔驗證，來源影片保留。"
            if normalized.mode == "copy"
            else "僅清理備份及驗證成功的來源影片。"
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
        transfer_callback: Callable[[str, int, int, str], None] | None = None,
    ) -> RescueVideoRunResult:
        stage = "preflight"

        def report_stage(value: str) -> None:
            nonlocal stage
            stage = value
            if stage_callback is not None:
                stage_callback(value)

        def report_transfer(source: Path, copied: int, total: int, state: str) -> None:
            if transfer_callback is not None:
                transfer_callback(str(source), copied, total, state)

        report_stage(stage)
        report_stage("module_load")
        core = self.module_loader(self.package_root)
        normalized, warnings, values = self.validate(request)
        try:
            args = core.build_args(values, normalized.mode)
            if status_callback:
                status_callback(
                    "正在套用記憶卡影片長度並預覽分類…"
                    if normalized.mode == "preview"
                    else "正在套用記憶卡影片長度、分類並核對來源影片…"
                )
            report_stage("classification")
            try:
                results = core.run_classification(
                    args,
                    stage_callback=report_stage,
                    transfer_callback=report_transfer,
                )
            except TypeError as exc:
                if "unexpected keyword argument" not in str(exc):
                    raise
                try:
                    results = core.run_classification(args, stage_callback=report_stage)
                except TypeError as fallback_exc:
                    if "unexpected keyword argument" not in str(fallback_exc):
                        raise
                    results = core.run_classification(args)
        except (OSError, ValueError, SystemExit) as exc:
            raise RescueVideoExecutionError(str(exc) or "影片讀取失敗。", failure_stage=stage) from exc

        rows = tuple(self._result_row(core, result) for result in results)
        summary = core.format_summary(core.summarize_results(results))
        return RescueVideoRunResult(
            summary_text=summary,
            warning_text="；".join(warnings),
            report_path=str(args.report),
            rows=rows,
        )

    @staticmethod
    def _result_row(core: ModuleType, result) -> dict[str, object]:
        case = getattr(result, "case", None)
        destination = getattr(result, "destination", None)
        adjusted_time = getattr(result, "adjusted_time", None)
        video_start = getattr(result, "video_start", None)
        status = str(getattr(result, "status", "") or "")
        corrected_video_time = video_start or adjusted_time
        time_text = corrected_video_time.strftime("%m/%d %H:%M:%S") if corrected_video_time else ""
        transfer_complete = status.startswith(("已完成", "已修復", "已複製")) or status == "來源刪除失敗"
        transfer_text = "驗證完成，來源未刪除" if status == "來源刪除失敗" else "已完成"
        return {
            "sourcePath": str(getattr(result, "source", "")),
            "sourceText": Path(getattr(result, "source", "")).name,
            "timeText": time_text,
            "caseText": str(getattr(case, "name", "") or "待確認"),
            "statusText": status,
            "destinationText": str(destination or ""),
            "noteText": str(getattr(result, "note", "") or ""),
            "tone": str(core.status_tag(status) or "normal"),
            "transferPercent": 100 if transfer_complete else 0,
            "transferText": transfer_text if transfer_complete else "尚未傳輸",
        }
