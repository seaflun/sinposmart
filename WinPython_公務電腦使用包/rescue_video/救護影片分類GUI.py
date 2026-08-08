# 記憶卡因為是插卡讀取，每次位置可能不同，只有 Z 槽式固定。
#!/usr/bin/env python3
"""Tkinter GUI for the rescue dashcam classification workflow."""

from __future__ import annotations

import argparse
import os
import queue
import threading
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
PUBLIC_GUI_MODES = ("preview", "delete")


def _load_tk_ui() -> None:
    global ctk, filedialog, messagebox, tk, ttk

    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    import customtkinter as ctk


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
        return_grace_minutes=10,
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
    results = classifier.classify_with_work_logs(args, transfer_callback=transfer_callback)
    if stage_callback is not None:
        stage_callback("report_write")
    classifier.write_report(results, args.report)
    return results


class RescueVideoApp:
    def __init__(self, root: ctk.CTk) -> None:
        self.root = root
        ctk.set_appearance_mode("light")
        self.root.title("救護行車影片分類")
        self.root.geometry("1280x720")
        self.root.minsize(980, 560)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.running = False
        self.buttons: list[object] = []
        self.execute_buttons: list[ctk.CTkButton] = []
        self.preflight_ready = False
        self.preflight_signature: tuple[object, ...] | None = None
        self.current_state: PreflightState | None = None
        self.offset_signature: tuple[str, str, str] | None = None

        self.source_var = tk.StringVar()
        self.destination_var = tk.StringVar(value=str(DEFAULT_DESTINATION))
        self.vehicle_var = tk.StringVar()
        self.date_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        self.offset_var = tk.StringVar(value="0")
        self.work_log_var = tk.StringVar(value=str(DEFAULT_WORK_LOG_ROOT))
        self.report_var = tk.StringVar(value=str(DEFAULT_REPORT))
        self.repair_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="就緒")
        self.summary_var = tk.StringVar(value="尚未執行")
        self.source_health_var = tk.StringVar(value="來源：尚未指定，執行時會自動偵測")

        self._build_public_duty_gui()
        self.root.after(100, self._refresh_automatic_state)
        self.root.after(100, self._poll_events)

    def _build_form(self) -> None:
        form = ttk.LabelFrame(self.root, text="分類設定", padding=10)
        form.pack(fill="x", padx=10, pady=(10, 5))
        form.columnconfigure(1, weight=1)

        self._add_path_row(form, 0, "記憶卡來源", self.source_var, self._browse_source)
        self._add_path_row(form, 1, "案件目的地", self.destination_var, None, readonly=True)
        self._add_path_row(form, 2, "工作紀錄", self.work_log_var, self._browse_work_log)
        self._add_path_row(form, 3, "CSV 報告", self.report_var, self._browse_report)

        ttk.Label(form, text="車號").grid(row=0, column=3, padx=(12, 4), sticky="e")
        ttk.Entry(form, textvariable=self.vehicle_var, width=8).grid(row=0, column=4, sticky="w")
        ttk.Label(form, text="日期").grid(row=1, column=3, padx=(12, 4), sticky="e")
        ttk.Entry(form, textvariable=self.date_var, width=12).grid(row=1, column=4, sticky="w")
        ttk.Label(form, text="時間偏移(分)").grid(row=2, column=3, padx=(12, 4), sticky="e")
        ttk.Entry(form, textvariable=self.offset_var, width=8).grid(row=2, column=4, sticky="w")
        ttk.Checkbutton(form, text="修復目的地不一致檔案", variable=self.repair_var).grid(
            row=3, column=3, columnspan=2, padx=(12, 4), sticky="w"
        )

        actions = ttk.Frame(self.root, padding=(10, 5))
        actions.pack(fill="x")
        self._add_button(actions, "自動偵測記憶卡", self._detect_source)
        self._add_button(actions, "預覽分類", lambda: self._start("preview"))
        self._add_button(actions, "執行複製", lambda: self._start("copy"))
        delete_button = self._add_button(
            actions,
            "複製並刪除已驗證來源",
            lambda: self._start("delete"),
        )
        delete_button.configure(width=24)

        info = ttk.Frame(self.root, padding=(10, 0, 10, 5))
        info.pack(fill="x")
        ttk.Label(info, textvariable=self.status_var).pack(side="left")
        ttk.Label(info, textvariable=self.summary_var).pack(side="right")

        table_frame = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        table_frame.pack(fill="both", expand=True)
        columns = ("source", "time", "case", "status", "destination", "note")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings")
        headings = {
            "source": "來源檔案",
            "time": "校正後時間",
            "case": "案件資料夾",
            "status": "狀態",
            "destination": "目的地",
            "note": "備註",
        }
        widths = {"source": 190, "time": 135, "case": 190, "status": 125, "destination": 300, "note": 300}
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor="w")
        self.tree.tag_configure("warning", foreground="#9a5a00")
        self.tree.tag_configure("error", foreground="#a00000")
        self.tree.tag_configure("deleted", foreground="#146b2e")
        y_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        x_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

    def _build_public_duty_gui(self) -> None:
        self.root.configure(fg_color="#eef3f8")
        self.root.geometry("1100x720")

        header = ctk.CTkFrame(self.root, fg_color="#123b65", corner_radius=0)
        header.pack(fill="x")
        ctk.CTkLabel(
            header,
            text="救護行車影片分類",
            font=ctk.CTkFont(family="Microsoft JhengHei UI", size=23, weight="bold"),
            text_color="white",
        ).pack(side="left", padx=24, pady=14)
        self.status_badge = ctk.CTkLabel(
            header,
            text="● 自動檢查中",
            font=ctk.CTkFont(family="Microsoft JhengHei UI", size=12, weight="bold"),
            text_color="#bfdbfe",
        )
        self.status_badge.pack(side="right", padx=24, pady=14)

        settings = ctk.CTkFrame(self.root, fg_color="#ffffff", border_width=1, border_color="#d7e2ee")
        settings.pack(fill="x", padx=24, pady=(16, 8))
        ctk.CTkLabel(settings, text="車號", font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=0, padx=(16, 8), pady=14
        )
        self.vehicle_combo = ctk.CTkComboBox(
            settings,
            values=[],
            variable=self.vehicle_var,
            command=lambda _value: self._refresh_automatic_state(),
            state="disabled",
            width=140,
        )
        self.vehicle_combo.grid(row=0, column=1, padx=(0, 24), pady=14)
        ctk.CTkLabel(settings, text="日期", font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=2, padx=(0, 8), pady=14
        )
        date_entry = ctk.CTkEntry(settings, textvariable=self.date_var, width=150)
        date_entry.grid(row=0, column=3, padx=(0, 24), pady=14)
        self.date_var.trace_add("write", lambda *_args: self._schedule_automatic_refresh())
        settings.grid_columnconfigure(4, weight=1)
        ctk.CTkLabel(
            settings,
            text="車號由當日案件資料夾自動取得；工作紀錄、報告位置與時間偏移均自動處理。",
            text_color="#52627a",
        ).grid(row=0, column=4, sticky="w", padx=(0, 16), pady=14)

        status_card = ctk.CTkFrame(self.root, fg_color="#ffffff", border_width=1, border_color="#d7e2ee")
        status_card.pack(fill="x", padx=24, pady=(0, 8))
        ctk.CTkLabel(status_card, text="自動檢查", font=ctk.CTkFont(size=14, weight="bold")).pack(
            anchor="w", padx=14, pady=(10, 2)
        )
        self.auto_status_var = tk.StringVar(value="正在檢查記憶卡、Z 槽與工作紀錄。")
        ctk.CTkLabel(status_card, textvariable=self.auto_status_var, justify="left", anchor="w", wraplength=980).pack(
            fill="x", padx=14, pady=(0, 10)
        )
        self.manual_source_button = ctk.CTkButton(
            status_card,
            text="手動選取記憶卡資料夾",
            command=self._select_manual_source,
            fg_color="#52627a",
        )

        actions = ctk.CTkFrame(self.root, fg_color="transparent")
        actions.pack(fill="x", padx=24, pady=(0, 8))
        self.preview_button = ctk.CTkButton(
            actions,
            text="預覽分類",
            command=lambda: self._start("preview"),
            state="disabled",
            fg_color="#2563eb",
        )
        self.preview_button.pack(side="left", padx=(0, 8))
        self.delete_button = ctk.CTkButton(
            actions,
            text="複製後刪除已驗證來源",
            command=lambda: self._start("delete"),
            state="disabled",
            fg_color="#b42318",
        )
        self.delete_button.pack(side="left")
        self.buttons = [self.preview_button, self.delete_button]
        self.execute_buttons = [self.preview_button, self.delete_button]
        self.progress = ctk.CTkProgressBar(actions, mode="indeterminate", width=160)
        self.progress.pack(side="right")
        self.progress.set(0)

        results_card = ctk.CTkFrame(self.root, fg_color="#ffffff", border_width=1, border_color="#d7e2ee")
        results_card.pack(fill="both", expand=True, padx=24, pady=(0, 8))
        ctk.CTkLabel(results_card, text="分類結果", font=ctk.CTkFont(size=15, weight="bold")).pack(
            anchor="w", padx=12, pady=(10, 4)
        )
        table_frame = ttk.Frame(results_card)
        table_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        columns = ("source", "time", "case", "status", "destination", "note")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=14)
        headings = {"source": "來源檔案", "time": "校正後時間", "case": "案件資料夾", "status": "狀態", "destination": "目的地", "note": "備註"}
        widths = {"source": 180, "time": 140, "case": 180, "status": 145, "destination": 280, "note": 280}
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor="w", stretch=column in {"source", "case", "destination", "note"})
        self.tree.tag_configure("warning", foreground="#9a5a00")
        self.tree.tag_configure("error", foreground="#a00000")
        self.tree.tag_configure("deleted", foreground="#176b3a")
        y_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=y_scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        y_scroll.pack(side="right", fill="y")
        self.summary_var.set("等待自動檢查完成。")
        ctk.CTkLabel(self.root, textvariable=self.summary_var, text_color="#52627a").pack(
            anchor="w", padx=24, pady=(0, 14)
        )

    def _schedule_automatic_refresh(self) -> None:
        if self.running:
            return
        if getattr(self, "automatic_refresh_id", None) is not None:
            self.root.after_cancel(self.automatic_refresh_id)
        self.automatic_refresh_id = self.root.after(250, self._refresh_automatic_state)

    def _refresh_automatic_state(self) -> None:
        self.automatic_refresh_id = None
        if self.running:
            return

        source = self.source_var.get().strip()
        if not source or not Path(source).is_dir():
            try:
                source = str(classifier.resolve_source(None))
            except OSError:
                source = ""
            self.source_var.set(source)
        if source:
            self.manual_source_button.pack_forget()
        elif not self.manual_source_button.winfo_manager():
            self.manual_source_button.pack(anchor="e", padx=14, pady=(0, 10))

        state = evaluate_preflight(self._values())
        vehicles = state.vehicles
        selected_vehicle = self.vehicle_var.get().strip()
        if vehicles:
            self.vehicle_combo.configure(values=vehicles, state="normal")
            if selected_vehicle not in vehicles:
                selected_vehicle = vehicles[0]
                self.vehicle_var.set(selected_vehicle)
                state = evaluate_preflight(self._values())
        else:
            self.vehicle_combo.configure(values=[], state="disabled")
            if selected_vehicle:
                self.vehicle_var.set("")
                state = evaluate_preflight(self._values())

        offset_minutes: int | None = None
        signature = (self.source_var.get(), self.date_var.get(), self.vehicle_var.get())
        if state.ready:
            try:
                if signature != self.offset_signature:
                    trial_args = self._build_public_args("preview", 6)
                    self.offset_var.set(str(choose_runtime_offset(trial_args)))
                    self.offset_signature = signature
                offset_minutes = int(self.offset_var.get())
            except (OSError, ValueError, SystemExit) as exc:
                checks = dict(state.checks)
                checks["offset"] = PreflightCheck("offset", "error", f"無法判定記憶卡偏移：{exc}")
                state = PreflightState(checks=checks, vehicles=state.vehicles)
        else:
            self.offset_signature = None

        self.current_state = PreflightState(
            checks=state.checks,
            vehicles=state.vehicles,
            offset_minutes=offset_minutes,
        )
        self.preflight_ready = execution_enabled(self.current_state)
        for button in self.execute_buttons:
            button.configure(state="normal" if self.preflight_ready else "disabled")

        details = [check.detail for check in self.current_state.checks.values()]
        if self.preflight_ready:
            details.append(f"自動採用記憶卡偏移：{offset_minutes} 分鐘")
            self._set_status("自動檢查通過", "#166534")
            self.summary_var.set("可以預覽分類，或複製後刪除已驗證來源。")
        else:
            self._set_status("等待必要資料", "#b42318")
            self.summary_var.set("請插入記憶卡並確認 Z 槽與工作紀錄可用。")
        self.auto_status_var.set("\n".join(details))
        self.root.after(5000, self._refresh_automatic_state)

    def _select_manual_source(self) -> None:
        selected = filedialog.askdirectory(title="選擇記憶卡 DCIM\\100CAREC 資料夾")
        if not selected:
            return
        source = Path(selected)
        if not is_memory_card_source(source):
            messagebox.showerror(
                "記憶卡資料夾不正確",
                "請選擇記憶卡內的 DCIM\\100CAREC 資料夾。",
                parent=self.root,
            )
            return
        self.source_var.set(str(source))
        self.offset_signature = None
        self._refresh_automatic_state()

    def _build_public_args(self, mode: str, offset_minutes: int) -> argparse.Namespace:
        values = self._values()
        values["offset_minutes"] = str(offset_minutes)
        values["report"] = str(build_public_duty_report_path(self.date_var.get(), self.vehicle_var.get()))
        return build_args(values, mode)

    def _build_dashboard(self) -> None:
        self.root.configure(fg_color="#eef3f8")
        width = min(1320, max(1040, self.root.winfo_screenwidth() - 100))
        height = min(860, max(680, self.root.winfo_screenheight() - 120))
        self.root.geometry(f"{width}x{height}")

        header = ctk.CTkFrame(self.root, fg_color="#123b65", corner_radius=0)
        header.pack(fill="x")
        ctk.CTkLabel(
            header,
            text="救護行車影片分類",
            font=ctk.CTkFont(family="Microsoft JhengHei UI", size=23, weight="bold"),
            text_color="white",
        ).pack(side="left", padx=24, pady=(15, 2))
        self.status_badge = ctk.CTkLabel(
            header,
            text="● 請先執行自檢",
            font=ctk.CTkFont(family="Microsoft JhengHei UI", size=12, weight="bold"),
            text_color="#bfdbfe",
        )
        self.status_badge.pack(side="right", padx=24, pady=(17, 2))
        ctk.CTkLabel(
            self.root,
            text="依 SINPOSMART 工作／返隊時間，將記憶卡影片歸入案件資料夾。自檢不會寫入、複製或刪除檔案。",
            font=ctk.CTkFont(family="Microsoft JhengHei UI", size=13),
            text_color="#52627a",
        ).pack(anchor="w", padx=24, pady=(8, 8))

        health = ctk.CTkFrame(self.root, fg_color="transparent")
        health.pack(fill="x", padx=24, pady=(0, 8))
        self.health_labels: dict[str, ctk.CTkLabel] = {}
        for index, (name, title) in enumerate(
            (("source", "記憶卡來源"), ("destination", "Z: 案件目的地"), ("work_log", "工作／返隊紀錄"))
        ):
            health.grid_columnconfigure(index, weight=1)
            card = ctk.CTkFrame(health, fg_color="#ffffff", border_width=1, border_color="#d7e2ee")
            card.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 5, 0 if index == 2 else 5))
            ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=12, weight="bold"), text_color="#344054").pack(
                anchor="w", padx=12, pady=(8, 0)
            )
            label = ctk.CTkLabel(card, text="尚未檢查", font=ctk.CTkFont(size=12), text_color="#667085")
            label.pack(anchor="w", padx=12, pady=(0, 8))
            self.health_labels[name] = label

        content = ctk.CTkFrame(self.root, fg_color="transparent")
        content.pack(fill="x", padx=24, pady=(0, 8))
        content.grid_columnconfigure(0, weight=3)
        content.grid_columnconfigure(1, weight=2)

        settings = ctk.CTkFrame(content, fg_color="#ffffff", border_width=1, border_color="#d7e2ee")
        settings.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        settings.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(settings, text="本次分類設定", font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", padx=14, pady=(12, 6)
        )
        self._add_dashboard_path_row(settings, 1, "記憶卡來源", self.source_var, (("自動偵測", self._detect_source), ("瀏覽", self._browse_source)))
        self._add_dashboard_path_row(settings, 2, "案件目的地", self.destination_var, (), readonly=True)
        self._add_dashboard_path_row(settings, 3, "工作紀錄", self.work_log_var, (("瀏覽", self._browse_work_log),))
        self._add_dashboard_path_row(settings, 4, "CSV 報告", self.report_var, (("選擇", self._browse_report),))
        ctk.CTkLabel(settings, text="車號").grid(row=5, column=0, sticky="w", padx=14, pady=5)
        ctk.CTkEntry(settings, textvariable=self.vehicle_var, width=120).grid(row=5, column=1, sticky="w", padx=(0, 8), pady=5)
        ctk.CTkLabel(settings, text="案件日期").grid(row=5, column=2, sticky="e", padx=(4, 8), pady=5)
        ctk.CTkEntry(settings, textvariable=self.date_var, width=135).grid(row=5, column=3, sticky="ew", padx=(0, 14), pady=5)
        ctk.CTkLabel(settings, text="記憶卡時間偏移（分）").grid(row=6, column=0, sticky="w", padx=14, pady=5)
        ctk.CTkEntry(settings, textvariable=self.offset_var, width=120).grid(row=6, column=1, sticky="w", padx=(0, 8), pady=5)
        ctk.CTkCheckBox(settings, text="允許修復目的地不一致檔案", variable=self.repair_var).grid(
            row=6, column=2, columnspan=2, sticky="w", padx=(4, 14), pady=5
        )

        check_card = ctk.CTkFrame(content, fg_color="#ffffff", border_width=1, border_color="#d7e2ee")
        check_card.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        ctk.CTkLabel(check_card, text="執行前自檢", font=ctk.CTkFont(size=15, weight="bold")).pack(
            anchor="w", padx=14, pady=(12, 2)
        )
        ctk.CTkLabel(check_card, text="自檢只讀取狀態，不會建立測試檔。", text_color="#667085").pack(
            anchor="w", padx=14, pady=(0, 6)
        )
        self.check_text = ctk.CTkTextbox(check_card, height=165, fg_color="#f7f9fc", text_color="#344054", wrap="word")
        self.check_text.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.check_text.insert("1.0", "尚未執行自檢。")
        self.check_text.configure(state="disabled")
        self.check_button = ctk.CTkButton(check_card, text="執行前自檢", command=self._run_preflight, fg_color="#1d4ed8")
        self.check_button.pack(anchor="e", padx=12, pady=(0, 12))
        self.buttons.append(self.check_button)

        actions = ctk.CTkFrame(self.root, fg_color="transparent")
        actions.pack(fill="x", padx=24, pady=(0, 8))
        ctk.CTkLabel(actions, text="分類操作", font=ctk.CTkFont(size=14, weight="bold"), text_color="#344054").pack(side="left", padx=(0, 12))
        for text, mode, color in (
            ("1　預覽分類", "preview", "#2563eb"),
            ("2　執行複製", "copy", "#2563eb"),
            ("3　複製並刪除已驗證來源", "delete", "#b42318"),
        ):
            button = ctk.CTkButton(actions, text=text, command=lambda item=mode: self._start(item), fg_color=color, state="disabled")
            button.pack(side="left", padx=(0, 8))
            self.buttons.append(button)
            self.execute_buttons.append(button)
        self.progress = ctk.CTkProgressBar(actions, mode="indeterminate", width=160)
        self.progress.pack(side="right", padx=(8, 0))
        self.progress.set(0)

        results_card = ctk.CTkFrame(self.root, fg_color="#ffffff", border_width=1, border_color="#d7e2ee")
        results_card.pack(fill="both", expand=True, padx=24, pady=(0, 8))
        ctk.CTkLabel(results_card, text="分類結果", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=12, pady=(10, 4))
        table_frame = ttk.Frame(results_card)
        table_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        columns = ("source", "time", "case", "status", "destination", "note")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=10)
        headings = {"source": "來源檔案", "time": "校正後時間", "case": "案件資料夾", "status": "狀態", "destination": "目的地", "note": "備註"}
        widths = {"source": 190, "time": 140, "case": 190, "status": 145, "destination": 320, "note": 300}
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor="w", stretch=column in {"source", "case", "destination", "note"})
        self.tree.tag_configure("warning", foreground="#9a5a00")
        self.tree.tag_configure("error", foreground="#a00000")
        self.tree.tag_configure("deleted", foreground="#176b3a")
        y_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=y_scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        y_scroll.pack(side="right", fill="y")

        self.summary_var.set("請先執行自檢，再選擇分類操作。")
        ctk.CTkLabel(self.root, textvariable=self.summary_var, text_color="#52627a").pack(anchor="w", padx=24, pady=(0, 4))
        self.log_text = ctk.CTkTextbox(self.root, height=85, fg_color="#f7f9fc", text_color="#344054", wrap="word")
        self.log_text.pack(fill="x", padx=24, pady=(0, 16))
        self.log_text.configure(state="disabled")
        self._log("GUI 已啟動；請先執行執行前自檢。")

    def _add_dashboard_path_row(
        self,
        parent: ctk.CTkFrame,
        row: int,
        label: str,
        variable: tk.StringVar,
        buttons: tuple[tuple[str, object], ...],
        readonly: bool = False,
    ) -> None:
        ctk.CTkLabel(parent, text=label).grid(row=row, column=0, sticky="w", padx=14, pady=5)
        entry = ctk.CTkEntry(parent, textvariable=variable)
        if readonly:
            entry.configure(state="disabled")
        entry.grid(row=row, column=1, columnspan=2, sticky="ew", pady=5)
        for index, (text, command) in enumerate(buttons, start=3):
            ctk.CTkButton(parent, text=text, width=74, command=command).grid(row=row, column=index, padx=(6, 14 if index == len(buttons) + 2 else 0), pady=5)

    def _settings_signature(self) -> tuple[object, ...]:
        values = self._values()
        return tuple(values[key] for key in sorted(values))

    def _run_preflight(self) -> bool:
        if not self.source_var.get().strip():
            try:
                self.source_var.set(str(classifier.resolve_source(None)))
            except OSError as exc:
                self._log(f"記憶卡偵測：{exc}")
        checks = run_preflight(self._values())
        colors = {"ok": "#166534", "warning": "#92400e", "error": "#b42318"}
        symbols = {"ok": "✓", "warning": "!", "error": "✕"}
        self.check_text.configure(state="normal")
        self.check_text.delete("1.0", "end")
        for check in checks:
            self.check_text.insert("end", f"{symbols[check.level]} {check.detail}\n")
            if check.name in self.health_labels:
                self.health_labels[check.name].configure(text=check.detail, text_color=colors[check.level])
        self.check_text.configure(state="disabled")
        errors = [check for check in checks if check.level == "error"]
        self.preflight_ready = not errors
        self.preflight_signature = self._settings_signature()
        state = "normal" if self.preflight_ready else "disabled"
        for button in self.execute_buttons:
            button.configure(state=state)
        if errors:
            self._set_status("自檢未通過", "#b42318")
            self.summary_var.set(f"自檢未通過：{len(errors)} 項需修正。")
            self._log("自檢未通過；請修正紅色項目後再執行。")
        else:
            warnings = sum(check.level == "warning" for check in checks)
            self._set_status("自檢通過", "#166534")
            self.summary_var.set("自檢通過。" if not warnings else f"自檢通過，另有 {warnings} 項提醒。")
            self._log("自檢通過；可選擇分類操作。")
        return self.preflight_ready

    def _build_modern_form(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Title.TLabel", font=("Microsoft JhengHei UI", 20, "bold"), foreground="#172033")
        style.configure("Subtitle.TLabel", foreground="#62708a")
        style.configure("Card.TLabelframe", padding=4)
        style.configure("Card.TLabelframe.Label", font=("Microsoft JhengHei UI", 11, "bold"), foreground="#24415f")
        style.configure("Hint.TLabel", foreground="#667085")
        style.configure("Status.TLabel", font=("Microsoft JhengHei UI", 11, "bold"), foreground="#176b3a")
        style.configure("Primary.TButton", padding=(14, 8), font=("Microsoft JhengHei UI", 10, "bold"))
        style.configure("Danger.TButton", padding=(14, 8), foreground="#a51d2d", font=("Microsoft JhengHei UI", 10, "bold"))

        width = min(1320, max(1040, self.root.winfo_screenwidth() - 100))
        height = min(860, max(680, self.root.winfo_screenheight() - 120))
        self.root.geometry(f"{width}x{height}")

        header = ttk.Frame(self.root, padding=(24, 18, 24, 10))
        header.pack(fill="x")
        title_frame = ttk.Frame(header)
        title_frame.pack(side="left", fill="x", expand=True)
        ttk.Label(title_frame, text="救護行車影片分類", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            title_frame,
            text="依 SINPOSMART 工作／返隊時間，將記憶卡影片歸入案件資料夾",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(3, 0))
        self.status_badge = ttk.Label(header, text="● 就緒", style="Status.TLabel")
        self.status_badge.pack(anchor="e", pady=(8, 0))

        settings = ttk.Frame(self.root, padding=(24, 0, 24, 8))
        settings.pack(fill="x")
        settings.columnconfigure(0, weight=3)
        settings.columnconfigure(1, weight=2)

        source_card = ttk.LabelFrame(settings, text="來源與儲存位置", padding=12, style="Card.TLabelframe")
        source_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        source_card.columnconfigure(1, weight=1)
        self._add_modern_path_row(
            source_card,
            0,
            "記憶卡來源",
            self.source_var,
            [("自動偵測", self._detect_source), ("瀏覽", self._browse_source)],
        )
        self._add_modern_path_row(
            source_card,
            2,
            "案件目的地",
            self.destination_var,
            [],
            readonly=True,
        )
        self.destination_health_var = tk.StringVar()
        ttk.Label(source_card, textvariable=self.destination_health_var, style="Hint.TLabel").grid(
            row=3, column=1, sticky="w", pady=(2, 8)
        )
        self._add_modern_path_row(
            source_card,
            4,
            "工作紀錄",
            self.work_log_var,
            [("瀏覽", self._browse_work_log)],
        )
        self._add_modern_path_row(
            source_card,
            5,
            "CSV 報告",
            self.report_var,
            [("選擇", self._browse_report)],
        )

        case_card = ttk.LabelFrame(settings, text="案件設定", padding=12, style="Card.TLabelframe")
        case_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        case_card.columnconfigure(1, weight=1)
        ttk.Label(case_card, text="車號").grid(row=0, column=0, sticky="w", pady=5)
        ttk.Entry(case_card, textvariable=self.vehicle_var, width=16).grid(row=0, column=1, sticky="ew", pady=5)
        ttk.Label(case_card, text="案件日期").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Entry(case_card, textvariable=self.date_var, width=16).grid(row=1, column=1, sticky="ew", pady=5)
        ttk.Label(case_card, text="記憶卡時間偏移（分）").grid(row=2, column=0, sticky="w", pady=5)
        ttk.Entry(case_card, textvariable=self.offset_var, width=16).grid(row=2, column=1, sticky="ew", pady=5)
        ttk.Checkbutton(case_card, text="允許修復目的地不一致檔案", variable=self.repair_var).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(8, 3)
        )
        ttk.Label(
            case_card,
            text="日期必填；刪除來源只會處理驗證成功的 .TS 檔案。",
            style="Hint.TLabel",
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))

        action_card = ttk.Frame(self.root, padding=(24, 4, 24, 8))
        action_card.pack(fill="x")
        ttk.Label(action_card, text="執行操作", font=("Microsoft JhengHei UI", 11, "bold")).pack(side="left", padx=(0, 14))
        self.buttons = []
        preview_button = ttk.Button(action_card, text="1  預覽分類", style="Primary.TButton", command=lambda: self._start("preview"))
        copy_button = ttk.Button(action_card, text="2  執行複製", style="Primary.TButton", command=lambda: self._start("copy"))
        delete_button = ttk.Button(
            action_card,
            text="3  複製並刪除已驗證來源",
            style="Danger.TButton",
            command=lambda: self._start("delete"),
        )
        for button in (preview_button, copy_button, delete_button):
            button.pack(side="left", padx=(0, 8))
            self.buttons.append(button)
        self.progress = ttk.Progressbar(action_card, mode="indeterminate", length=180)
        self.progress.pack(side="right", padx=(12, 0))

        summary_bar = ttk.Frame(self.root, padding=(24, 0, 24, 6))
        summary_bar.pack(fill="x")
        ttk.Label(summary_bar, text="結果摘要", font=("Microsoft JhengHei UI", 11, "bold")).pack(side="left")
        ttk.Label(summary_bar, textvariable=self.summary_var, style="Hint.TLabel").pack(side="left", padx=(12, 0))

        results_card = ttk.LabelFrame(self.root, text="分類結果", padding=8, style="Card.TLabelframe")
        results_card.pack(fill="both", expand=True, padx=24, pady=(0, 6))
        results_card.rowconfigure(0, weight=1)
        results_card.columnconfigure(0, weight=1)
        columns = ("source", "time", "case", "status", "destination", "note")
        self.tree = ttk.Treeview(results_card, columns=columns, show="headings", height=12)
        headings = {"source": "來源檔案", "time": "校正後時間", "case": "案件資料夾", "status": "狀態", "destination": "目的地", "note": "備註"}
        widths = {"source": 210, "time": 140, "case": 210, "status": 145, "destination": 360, "note": 360}
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor="w", stretch=column in {"source", "case", "destination", "note"})
        self.tree.tag_configure("warning", foreground="#9a5a00")
        self.tree.tag_configure("error", foreground="#a00000")
        self.tree.tag_configure("deleted", foreground="#176b3a")
        y_scroll = ttk.Scrollbar(results_card, orient="vertical", command=self.tree.yview)
        x_scroll = ttk.Scrollbar(results_card, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

        log_card = ttk.LabelFrame(self.root, text="執行紀錄", padding=6, style="Card.TLabelframe")
        log_card.pack(fill="x", padx=24, pady=(0, 14))
        self.log_text = tk.Text(log_card, height=5, wrap="word", relief="flat", background="#f7f9fc", foreground="#344054")
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll = ttk.Scrollbar(log_card, orient="vertical", command=self.log_text.yview)
        log_scroll.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=log_scroll.set, state="disabled")
        self._refresh_indicators()
        self._log("GUI 已啟動；請先執行預覽分類。")

    def _add_modern_path_row(
        self,
        parent: ttk.LabelFrame,
        row: int,
        label: str,
        variable: tk.StringVar,
        buttons: list[tuple[str, object]],
        readonly: bool = False,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=5)
        entry = ttk.Entry(parent, textvariable=variable)
        if readonly:
            entry.configure(state="readonly")
        entry.grid(row=row, column=1, sticky="ew", pady=5)
        for index, (text, command) in enumerate(buttons, start=2):
            ttk.Button(parent, text=text, command=command).grid(row=row, column=index, padx=(6, 0), pady=5)

    def _refresh_indicators(self) -> None:
        destination = Path(self.destination_var.get())
        if destination.is_dir():
            self.destination_health_var.set("● Z 槽可用")
        else:
            self.destination_health_var.set("● 找不到 Z 槽，執行前會阻止操作")
        source = self.source_var.get().strip()
        if source and Path(source).is_dir():
            self.source_health_var.set(f"來源：{source}")
        else:
            self.source_health_var.set("來源：尚未指定，執行時會自動偵測")

    def _set_status(self, text: str, color: str = "#176b3a") -> None:
        self.status_var.set(text)
        self.status_badge.configure(text=f"● {text}", text_color=color)

    def _log(self, message: str) -> None:
        if not hasattr(self, "log_text"):
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{stamp}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _add_path_row(
        self,
        parent: ttk.LabelFrame,
        row: int,
        label: str,
        variable: tk.StringVar,
        browse_command: object,
        readonly: bool = False,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, padx=(0, 8), sticky="w")
        entry = ttk.Entry(parent, textvariable=variable)
        if readonly:
            entry.configure(state="readonly")
        entry.grid(row=row, column=1, columnspan=2, sticky="ew")
        if browse_command is not None:
            ttk.Button(parent, text="瀏覽", command=browse_command).grid(row=row, column=5, padx=(6, 0))

    def _add_button(self, parent: ttk.Frame, text: str, command: object) -> ttk.Button:
        button = ttk.Button(parent, text=text, command=command)
        button.pack(side="left", padx=(0, 8))
        self.buttons.append(button)
        return button

    def _browse_source(self) -> None:
        selected = filedialog.askdirectory(title="選擇記憶卡 DCIM\\100CAREC 資料夾")
        if selected:
            self.source_var.set(selected)
            self._invalidate_preflight()

    def _browse_work_log(self) -> None:
        selected = filedialog.askdirectory(title="選擇 SINPOSMART 工作紀錄資料夾")
        if selected:
            self.work_log_var.set(selected)
            self._invalidate_preflight()

    def _browse_report(self) -> None:
        selected = filedialog.asksaveasfilename(
            title="選擇 CSV 報告位置",
            defaultextension=".csv",
            filetypes=[("CSV 檔案", "*.csv"), ("所有檔案", "*.*")],
            initialfile=Path(self.report_var.get()).name,
        )
        if selected:
            self.report_var.set(selected)
            self._invalidate_preflight()

    def _detect_source(self) -> None:
        try:
            source = classifier.resolve_source(None)
        except OSError as exc:
            self._set_status("記憶卡偵測失敗", "#a00000")
            self._log(f"錯誤：{exc}")
            messagebox.showerror("找不到記憶卡", str(exc), parent=self.root)
            return
        self.source_var.set(str(source))
        self._invalidate_preflight()
        self._set_status("已偵測記憶卡；請重新自檢", "#92400e")
        self._log(f"已偵測來源：{source}")

    def _values(self) -> dict[str, object]:
        date_text = self.date_var.get()
        vehicle = self.vehicle_var.get()
        try:
            report = build_public_duty_report_path(date_text, vehicle)
        except ValueError:
            report = DEFAULT_REPORT
        return {
            "source": self.source_var.get(),
            "destination": str(DEFAULT_DESTINATION),
            "vehicle": vehicle,
            "date": date_text,
            "offset_minutes": self.offset_var.get(),
            "work_log_root": str(DEFAULT_WORK_LOG_ROOT),
            "report": str(report),
            "repair_mismatch": False,
        }

    def _invalidate_preflight(self) -> None:
        self.preflight_ready = False
        self.preflight_signature = None
        if not self.running:
            for button in self.execute_buttons:
                button.configure(state="disabled")

    def _start(self, mode: str) -> None:
        if mode not in PUBLIC_GUI_MODES:
            raise ValueError(f"公務電腦 GUI 不支援操作：{mode}")
        signature = (self.source_var.get(), self.date_var.get(), self.vehicle_var.get())
        if not self.current_state or not execution_enabled(self.current_state) or signature != self.offset_signature:
            self._refresh_automatic_state()
            return
        if mode == "delete":
            confirmed = messagebox.askyesno(
                "確認刪除記憶卡來源",
                "只有複製並完成內容驗證的 .TS 檔案會刪除。\n確定要繼續嗎？",
                parent=self.root,
            )
            if not confirmed:
                return
        try:
            args = self._build_public_args(mode, self.current_state.offset_minutes or 6)
        except (OSError, ValueError) as exc:
            self._set_status("設定錯誤", "#a00000")
            self._log(f"錯誤：{exc}")
            messagebox.showerror("設定錯誤", str(exc), parent=self.root)
            return
        self._set_running(True)
        self._set_status("執行中，請勿拔除記憶卡或關閉視窗", "#9a5a00")
        self._log({"preview": "開始預覽分類", "delete": "開始複製並刪除已驗證來源"}[mode])
        worker = threading.Thread(target=self._worker, args=(args,), daemon=True)
        worker.start()

    def _worker(self, args: argparse.Namespace) -> None:
        try:
            results = run_classification(args)
        except Exception as exc:
            self.events.put(("error", exc))
            return
        self.events.put(("done", results))

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "done":
                    self._show_results(payload)
                    self._set_running(False)
                    self._set_status("完成")
                    self._log(f"完成：{format_summary(summarize_results(payload))}")
                else:
                    self._set_running(False)
                    self._set_status("執行失敗", "#a00000")
                    self._log(f"錯誤：{payload}")
                    messagebox.showerror("執行錯誤", str(payload), parent=self.root)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _show_results(self, payload: object) -> None:
        results = list(payload)  # type: ignore[arg-type]
        for item in self.tree.get_children():
            self.tree.delete(item)
        for result in results:
            status = result.status
            tag = status_tag(status)
            self.tree.insert(
                "",
                "end",
                values=(
                    str(result.source),
                    result.adjusted_time.strftime("%Y-%m-%d %H:%M:%S"),
                    result.case.name if result.case else "待確認",
                    status,
                    str(result.destination) if result.destination else "",
                    result.note,
                ),
                tags=(tag,),
            )
        self.summary_var.set(format_summary(summarize_results(results)))

    def _set_running(self, running: bool) -> None:
        self.running = running
        for button in self.buttons:
            button.configure(state="disabled" if running else "normal")
        if not running:
            enabled = self.current_state is not None and execution_enabled(self.current_state)
            for button in self.execute_buttons:
                button.configure(state="normal" if enabled else "disabled")
        if hasattr(self, "progress"):
            if running:
                self.progress.start()
            else:
                self.progress.stop()


def main() -> int:
    _load_tk_ui()
    root = ctk.CTk()
    RescueVideoApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
