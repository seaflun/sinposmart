#!/usr/bin/env python3
"""UI-independent workflow for rescue dashcam classification."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Mapping

import classify_rescue_video as classifier


DEFAULT_DESTINATION = Path(r"Z:\救護硬碟\救護密錄器及行車紀錄器")
DEFAULT_WORK_LOG_ROOT = Path(
    r"E:\SINPOSMART\WinPython_公務電腦使用包\runtime_outputs\comparison"
)
DEFAULT_RUNTIME_OUTPUT_ROOT = Path(r"E:\SINPOSMART\WinPython_公務電腦使用包\runtime_outputs")
DEFAULT_REPORT = Path(__file__).with_name("分類結果.csv")
MODES = {
    "preview": (False, False),
    "copy": (True, False),
    "delete": (True, True),
}


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    level: str
    detail: str


@dataclass(frozen=True)
class PreflightState:
    checks: Mapping[str, PreflightCheck]
    vehicles: list[str]
    offset_minutes: int | None = None

    @property
    def ready(self) -> bool:
        return bool(self.vehicles) and all(check.level != "error" for check in self.checks.values())


def execution_enabled(state: PreflightState) -> bool:
    return state.ready and state.offset_minutes is not None


def is_memory_card_source(path: Path) -> bool:
    return path.is_dir() and path.name.upper() == "100CAREC" and path.parent.name.upper() == "DCIM"


def build_public_duty_report_path(selected_date: str, vehicle: str) -> Path:
    compact_date = datetime.strptime(selected_date, "%Y-%m-%d").strftime("%Y%m%d")
    return DEFAULT_RUNTIME_OUTPUT_ROOT / "rescue_video" / f"分類結果_{compact_date}_{vehicle}.csv"


def evaluate_preflight(values: Mapping[str, object]) -> PreflightState:
    source_text = _text(values, "source")
    source = Path(source_text) if source_text else None
    destination = DEFAULT_DESTINATION
    work_log = DEFAULT_WORK_LOG_ROOT
    date_text = _text(values, "date")
    vehicle = _text(values, "vehicle")
    checks: dict[str, PreflightCheck] = {}

    if source is not None and source.is_dir():
        checks["source"] = PreflightCheck("source", "ok", f"來源：{source}")
    else:
        checks["source"] = PreflightCheck("source", "error", "找不到記憶卡來源")

    if destination.is_dir() and os.access(destination, os.R_OK | os.W_OK):
        checks["destination"] = PreflightCheck("destination", "ok", "案件目的地可存取")
    else:
        checks["destination"] = PreflightCheck("destination", "error", "找不到固定案件目的地 Z 槽")

    if work_log.is_dir():
        checks["work_log"] = PreflightCheck("work_log", "ok", "工作／返隊紀錄可存取")
    else:
        checks["work_log"] = PreflightCheck("work_log", "error", "找不到固定工作／返隊紀錄")

    try:
        selected_date = datetime.strptime(date_text, "%Y-%m-%d").date()
    except ValueError:
        selected_date = None
    vehicles = classifier.discover_vehicles(destination, selected_date) if selected_date else []
    if selected_date and vehicle and vehicle in vehicles:
        checks["vehicle_date"] = PreflightCheck("vehicle_date", "ok", f"車號 {vehicle}／日期 {date_text}")
    else:
        checks["vehicle_date"] = PreflightCheck("vehicle_date", "error", "請從當日案件選擇車號與有效日期")

    if DEFAULT_RUNTIME_OUTPUT_ROOT.is_dir() and os.access(DEFAULT_RUNTIME_OUTPUT_ROOT, os.W_OK):
        report = build_public_duty_report_path(date_text, vehicle) if selected_date and vehicle else None
        detail = f"報告將建立於：{report}" if report else "等待車號與日期後建立固定報告"
        checks["report"] = PreflightCheck("report", "ok", detail)
    else:
        checks["report"] = PreflightCheck("report", "error", "找不到或無法寫入固定報告根目錄")

    videos: list[Path] = []
    if source is not None and source.is_dir():
        videos = classifier.discover_sources(source, ".TS")
    if videos:
        try:
            sample, duration = classifier.read_card_duration(videos)
        except (OSError, ValueError) as exc:
            checks["videos"] = PreflightCheck(
                "videos",
                "error",
                f"無法讀取範例影片 {sample.name} 的實際長度：{exc}",
            )
        else:
            checks["videos"] = PreflightCheck(
                "videos",
                "ok",
                f"已檢查 {sample.name}：{duration.total_seconds():.3f} 秒（同卡影片共用）。",
            )
    else:
        checks["videos"] = PreflightCheck("videos", "error", "找不到可判定實際長度的 .TS 影片")

    return PreflightState(checks=checks, vehicles=vehicles)


def choose_runtime_offset(_args: argparse.Namespace) -> int:
    """Use the file end time and each TS file's measured duration without an offset."""
    return 0


def run_preflight(values: Mapping[str, object]) -> list[PreflightCheck]:
    source = Path(_text(values, "source"))
    destination = Path(_text(values, "destination", str(DEFAULT_DESTINATION)))
    work_log = Path(_text(values, "work_log_root", str(DEFAULT_WORK_LOG_ROOT)))
    report = Path(_text(values, "report", str(DEFAULT_REPORT)))
    checks: list[PreflightCheck] = []

    if source.is_dir():
        checks.append(PreflightCheck("source", "ok", f"來源：{source}"))
    else:
        checks.append(PreflightCheck("source", "error", "尚未找到可用的記憶卡來源"))

    if destination.is_dir() and os.access(destination, os.R_OK | os.W_OK):
        checks.append(PreflightCheck("destination", "ok", f"目的地可存取：{destination}"))
    else:
        checks.append(PreflightCheck("destination", "error", "找不到或無法存取案件目的地"))

    if work_log.is_dir():
        checks.append(PreflightCheck("work_log", "ok", f"工作紀錄：{work_log}"))
    else:
        checks.append(PreflightCheck("work_log", "warning", "找不到工作紀錄，將使用檔案時間分類"))

    vehicle = _text(values, "vehicle")
    date_text = _text(values, "date")
    try:
        datetime.strptime(date_text, "%Y-%m-%d")
        date_valid = True
    except ValueError:
        date_valid = False
    try:
        float(_text(values, "offset_minutes", "0") or "0")
        offset_valid = True
    except ValueError:
        offset_valid = False
    if vehicle and date_valid and offset_valid:
        checks.append(PreflightCheck("vehicle_date", "ok", f"車號 {vehicle}／日期 {date_text}"))
    else:
        checks.append(PreflightCheck("vehicle_date", "error", "請填寫有效的車號、YYYY-MM-DD 日期與時間偏移"))

    report_parent = report.parent
    writable_parent = report_parent
    while not writable_parent.exists() and writable_parent != writable_parent.parent:
        writable_parent = writable_parent.parent
    if writable_parent.is_dir() and os.access(writable_parent, os.W_OK):
        detail = f"報告將建立於：{report}"
        if writable_parent != report_parent:
            detail += "（執行時才建立報表資料夾）"
        checks.append(PreflightCheck("report", "ok", detail))
    else:
        checks.append(PreflightCheck("report", "error", "CSV 報告資料夾不存在或無法寫入"))

    readable = 0
    unreadable = 0
    if source.is_dir():
        for video in classifier.discover_sources(source, ".TS"):
            try:
                with video.open("rb"):
                    pass
            except OSError:
                unreadable += 1
            else:
                readable += 1
    if unreadable:
        checks.append(PreflightCheck("videos", "warning", f"可讀取 {readable} 部；{unreadable} 部無法讀取"))
    elif readable:
        checks.append(PreflightCheck("videos", "ok", f"可讀取影片：{readable} 部"))
    else:
        checks.append(PreflightCheck("videos", "warning", "尚未找到可讀取的 .TS 影片"))

    return checks


def _text(values: Mapping[str, object], name: str, default: str = "") -> str:
    value = values.get(name, default)
    if value is None:
        return default
    return str(value).strip()


def _boolean(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def validate_form(
    values: Mapping[str, object],
    mode: str,
    *,
    destination_exists: bool | None = None,
    work_log_exists: bool | None = None,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if mode not in MODES:
        errors.append(f"未知的操作模式：{mode}")

    vehicle = _text(values, "vehicle")
    if not vehicle:
        errors.append("車號不可空白")
    date_text = _text(values, "date")
    if not date_text:
        errors.append("日期不可空白")
    else:
        try:
            datetime.strptime(date_text, "%Y-%m-%d")
        except ValueError:
            errors.append("日期格式必須是 YYYY-MM-DD")

    try:
        float(_text(values, "offset_minutes", "0") or "0")
    except ValueError:
        errors.append("時間偏移必須是數字")

    source_text = _text(values, "source")
    if source_text and not Path(source_text).is_dir():
        errors.append(f"找不到記憶卡資料夾：{source_text}")

    destination_text = _text(values, "destination", str(DEFAULT_DESTINATION))
    if destination_exists is None:
        destination_exists = Path(destination_text).is_dir()
    if not destination_exists:
        errors.append(f"找不到固定目的地 Z 槽：{destination_text}")

    work_log_text = _text(values, "work_log_root", str(DEFAULT_WORK_LOG_ROOT))
    if work_log_exists is None:
        work_log_exists = Path(work_log_text).is_dir()
    if not work_log_exists:
        warnings.append("找不到 SINPOSMART 工作紀錄資料夾，將退回使用案件資料夾時間配對")

    return errors, warnings


def status_tag(status: str) -> str:
    if "刪除來源" in status and "失敗" not in status:
        return "deleted"
    if status in {"待確認", "目的地不一致"}:
        return "warning"
    if status in {"錯誤", "來源刪除失敗", "無法讀取"} or "失敗" in status:
        return "error"
    return ""


def build_args(values: Mapping[str, object], mode: str) -> argparse.Namespace:
    if mode not in MODES:
        raise ValueError(f"未知的 GUI 操作模式：{mode}")
    apply, delete_source = MODES[mode]

    offset_text = _text(values, "offset_minutes", "0") or "0"
    try:
        offset_minutes = float(offset_text)
    except ValueError as exc:
        raise ValueError("時間偏移必須是數字，例如 0 或 10") from exc

    source_text = _text(values, "source")
    destination_text = _text(values, "destination", str(DEFAULT_DESTINATION))
    work_log_text = _text(values, "work_log_root", str(DEFAULT_WORK_LOG_ROOT))
    report_text = _text(values, "report", str(DEFAULT_REPORT))
    if not destination_text:
        raise ValueError("目的地不可空白")
    if not work_log_text:
        raise ValueError("SINPOSMART 工作紀錄資料夾不可空白")
    if not report_text:
        raise ValueError("報告路徑不可空白")

    return argparse.Namespace(
        source=Path(source_text) if source_text else None,
        destination=Path(destination_text),
        vehicle=_text(values, "vehicle", "92") or "92",
        date=_text(values, "date") or None,
        offset_minutes=offset_minutes,
        before_minutes=30,
        after_minutes=120,
        segment_minutes=6,
        work_log_root=Path(work_log_text),
        work_before_minutes=15,
        return_grace_minutes=0,
        case_folder_tolerance_minutes=10,
        extension=".TS",
        apply=apply,
        repair_mismatch=_boolean(values.get("repair_mismatch", False)),
        delete_source=delete_source,
        report=Path(report_text),
    )


def summarize_results(results: Iterable[object]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for result in results:
        status = str(getattr(result, "status", "未知"))
        summary[status] = summary.get(status, 0) + 1
    return summary


def format_summary(summary: Mapping[str, int]) -> str:
    if not summary:
        return "沒有結果"
    return "；".join(f"{status}: {count}" for status, count in sorted(summary.items()))


def run_classification(
    args: argparse.Namespace,
    stage_callback: Callable[[str], None] | None = None,
    transfer_callback: Callable[[Path, int, int, str], None] | None = None,
) -> list[classifier.Result]:
    if stage_callback is not None:
        stage_callback("classification")
    results = classifier.classify_with_work_logs(
        args,
        transfer_callback=transfer_callback,
    )
    if stage_callback is not None:
        stage_callback("report_write")
    classifier.write_report(results, args.report)
    return results
