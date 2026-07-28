# -*- coding: utf-8 -*-
"""Embedded window for the legacy duty-sheet automation workflow."""

from __future__ import annotations

import importlib.util
import os
import re
import sys
import threading
import traceback
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk
import customtkinter as ctk
from types import ModuleType
from typing import Callable, Iterator

UI_FONT = "Microsoft JhengHei UI"
UI_BG = "#f5f7fb"
UI_PANEL = "#ffffff"
UI_PANEL_TINT = "#eef6ff"
UI_BORDER = "#d7e2f0"
UI_TEXT = "#172033"
UI_MUTED = "#64748b"
UI_BLUE = "#2563eb"
UI_BLUE_HOVER = "#1d4ed8"
FONT_BODY = (UI_FONT, 12)
FONT_TITLE = (UI_FONT, 14, "bold")
FONT_BUTTON = (UI_FONT, 12, "bold")
FONT_CONTROL_EMPHASIS = (UI_FONT, 14, "bold")
FONT_CAPTION = (UI_FONT, 11)
FONT_SECTION_TITLE = (UI_FONT, 15, "bold")
FONT_PANEL_TITLE = (UI_FONT, 18, "bold")
FONT_NAV_ICON = (UI_FONT, 24)
CTK_COMBO_STYLE = {
    "fg_color": UI_PANEL,
    "border_color": UI_BORDER,
    "button_color": "#dbeafe",
    "button_hover_color": "#bfdbfe",
    "dropdown_fg_color": "#ffffff",
    "dropdown_hover_color": "#eff6ff",
    "dropdown_text_color": UI_TEXT,
    "text_color": UI_TEXT,
}
SIDE_STATUS_STYLES = {
    "ready": {"fg_color": "#F2F2F7", "border_color": "#D1D1D6", "text_color": "#636366"},
    "progress": {"fg_color": "#F0F7FF", "border_color": "#B8D8FF", "text_color": "#007AFF"},
    "success": {"fg_color": "#F0FAF2", "border_color": "#BFE8C8", "text_color": "#248A3D"},
    "warning": {"fg_color": "#FFF8E5", "border_color": "#F2D27A", "text_color": "#8A5A00"},
    "error": {"fg_color": "#FFF2F1", "border_color": "#FFC9C5", "text_color": "#C62828"},
}
SIDE_STATUS_ERROR_MARKERS = ("失敗", "錯誤", "中斷", "找不到", "未通過", "異常", "逾時")
SIDE_STATUS_REMOVAL_MARKERS = ("移除", "刪除")
SIDE_STATUS_SUCCESS_MARKERS = ("完成", "完畢", "已填入", "檢查通過", "已送出", "已新增")


def normalize_side_status_message(message: str) -> str:
    return re.sub(r"^\s*狀態\s*[：:]\s*", "", str(message or "")).strip()


def side_status_style(message: str) -> dict[str, str]:
    text = normalize_side_status_message(message)
    if any(marker in text for marker in SIDE_STATUS_ERROR_MARKERS):
        category = "error"
    elif any(marker in text for marker in SIDE_STATUS_REMOVAL_MARKERS):
        category = "warning"
    elif text.startswith(("準備就緒", "尚未選擇")):
        category = "ready"
    elif any(marker in text for marker in SIDE_STATUS_SUCCESS_MARKERS):
        category = "success"
    else:
        category = "progress"
    return SIDE_STATUS_STYLES[category].copy()


def bind_side_status_style(status_var: tk.StringVar, status_card: ctk.CTkFrame, status_bar: ctk.CTkLabel) -> None:
    def refresh_style(*_args) -> None:
        message = normalize_side_status_message(status_var.get())
        if message != status_var.get():
            status_var.set(message)
            return
        style = side_status_style(message)
        status_card.configure(fg_color=style["fg_color"], border_color=style["border_color"])
        status_bar.configure(text_color=style["text_color"])

    status_var.trace_add("write", refresh_style)
    refresh_style()

LEGACY_SCRIPT = "sinposmart_1.py"
PACKAGED_PROJECT_DIR = "duty_sheet_legacy"
LEGACY_PROJECT_DIR = "勤務表自動化"
ENV_PROJECT_DIR = "SINPOSMART_DUTY_SHEET_PROJECT"
FRONTEND_ERROR_MESSAGES = {
    "login_failed": "登入失敗：帳號或密碼可能已變更，請登出後重新登入系統。",
    "timeout": "網頁等待逾時：勤務系統可能登入失敗、網頁變慢，或頁面結構已變更。",
    "no_such_element": "找不到網頁元素：可能勤務系統頁面改版，或尚未成功登入。",
    "unknown_error": "執行失敗：系統發生未預期錯誤，請查看後端日誌。",
}
LOGIN_FAILURE_MARKERS = (
    "登入失敗",
    "登入狀態失效",
    "密碼可能已變更",
    "帳號密碼有誤",
    "尚未申請帳號權限",
    "帳號或密碼",
    "重新登入",
    "login119",
    "_txtusername",
    "_txtpassword",
    "登入後元素",
    "仍停留在登入頁",
)
UNSAFE_ERROR_MARKERS = (
    "stacktrace",
    "stack trace",
    "traceback",
    "chromedriver",
    "selenium.common.exceptions",
    "session token",
    "cookie",
    "password",
)


def format_automation_error(exc: BaseException | str) -> str:
    text = str(exc or "").strip()
    lowered = text.lower()
    if any(marker in lowered or marker in text for marker in LOGIN_FAILURE_MARKERS):
        return FRONTEND_ERROR_MESSAGES["login_failed"]
    if "timeoutexception" in lowered or "timeout" in lowered or "timed out" in lowered or "逾時" in text:
        return FRONTEND_ERROR_MESSAGES["timeout"]
    if "nosuchelementexception" in lowered or "no such element" in lowered or "unable to locate element" in lowered:
        return FRONTEND_ERROR_MESSAGES["no_such_element"]
    if any(marker in lowered for marker in UNSAFE_ERROR_MARKERS):
        return FRONTEND_ERROR_MESSAGES["unknown_error"]
    if text:
        return text
    return FRONTEND_ERROR_MESSAGES["unknown_error"]


def log_automation_exception(context: str, exc: BaseException) -> None:
    print(f"[automation-error] {context}: {type(exc).__name__}: {exc}", file=sys.stderr)
    traceback.print_exc()


def candidate_project_dirs(base_dir: Path | None = None) -> list[Path]:
    base_dir = (base_dir or Path(__file__).resolve().parent).resolve()
    candidates: list[Path] = []
    env_path = os.environ.get(ENV_PROJECT_DIR, "").strip()
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(base_dir / PACKAGED_PROJECT_DIR)
    candidates.extend(base / LEGACY_PROJECT_DIR for base in [base_dir, *base_dir.parents])
    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        resolved = path.expanduser().resolve()
        key = str(resolved).lower()
        if key not in seen:
            seen.add(key)
            unique.append(resolved)
    return unique


def find_project_dir(base_dir: Path | None = None) -> Path | None:
    for project_dir in candidate_project_dirs(base_dir):
        if (project_dir / LEGACY_SCRIPT).exists():
            return project_dir
    return None


@contextmanager
def legacy_workdir(project_dir: Path) -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(project_dir)
    try:
        yield
    finally:
        os.chdir(previous)


def load_legacy_module(project_dir: Path) -> ModuleType:
    module_name = "_sinposmart_duty_sheet_automation"
    script_path = project_dir / LEGACY_SCRIPT
    source_mtime = script_path.stat().st_mtime
    existing = sys.modules.get(module_name)
    if (
        existing is not None
        and getattr(existing, "__sinposmart_source_path__", None) == str(script_path)
        and getattr(existing, "__sinposmart_source_mtime__", None) == source_mtime
    ):
        return existing
    sys.modules.pop(module_name, None)
    importlib.invalidate_caches()
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"無法載入勤務表自動化腳本：{script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    sys.path.insert(0, str(project_dir))
    try:
        with legacy_workdir(project_dir):
            spec.loader.exec_module(module)
        module.__sinposmart_source_path__ = str(script_path)
        module.__sinposmart_source_mtime__ = source_mtime
    finally:
        try:
            sys.path.remove(str(project_dir))
        except ValueError:
            pass
    return module


def open_duty_sheet_dialog(parent: tk.Tk, user_id: str = "", password: str = "", on_start: Callable[..., None] | None = None, on_finish: Callable[[str], None] | None = None, on_error: Callable[[str], None] | None = None, container: tk.Widget | None = None, on_close: Callable[[], None] | None = None) -> ctk.CTkToplevel | ctk.CTkFrame | None:
    embedded = container is not None
    existing = None if embedded else getattr(parent, "_duty_sheet_dialog", None)
    if existing is not None:
        try:
            if existing.winfo_exists():
                existing.deiconify()
                existing.lift()
                existing.focus_force()
                return existing
        except Exception:
            pass
        setattr(parent, "_duty_sheet_dialog", None)

    base_dir = Path(__file__).resolve().parent
    project_dir = find_project_dir(base_dir)
    if project_dir is None:
        searched = "\n".join(str(path) for path in candidate_project_dirs(base_dir))
        messagebox.showerror("勤務表登打", f"找不到勤務表自動化專案，已搜尋：\n{searched}", parent=parent)
        return None

    try:
        legacy = load_legacy_module(project_dir)
        with legacy_workdir(project_dir):
            current_config = legacy.load_config()
    except Exception as exc:
        messagebox.showerror("勤務表登打", f"載入勤務表自動化失敗：{exc}", parent=parent)
        return None

    login_config = current_config.get("login", {})
    last = current_config.get("last_selection", {})
    opts = current_config.get("car_options", {})
    hidden_opts = current_config.setdefault("hidden_car_options", {})
    if not isinstance(hidden_opts, dict):
        hidden_opts = {}
        current_config["hidden_car_options"] = hidden_opts
    hidden_opts.setdefault("attack", [])
    hidden_opts.setdefault("amb", [])

    if embedded:
        dialog = parent
    else:
        dialog = ctk.CTkToplevel(parent)
        setattr(parent, "_duty_sheet_dialog", dialog)
        dialog.title("SinpoSmart - 勤務表登打")
        dialog.geometry("430x600")
        dialog.minsize(410, 580)
        dialog.configure(fg_color=UI_BG)
        dialog.transient(parent)

    def close_dialog() -> None:
        if embedded:
            if on_close is not None:
                on_close()
            elif root.winfo_exists():
                root.destroy()
            return
        setattr(parent, "_duty_sheet_dialog", None)
        dialog.destroy()

    if not embedded:
        dialog.protocol("WM_DELETE_WINDOW", close_dialog)

    root = ctk.CTkFrame(container if embedded else dialog, fg_color="transparent" if embedded else UI_BG, corner_radius=0)
    root.pack(fill=tk.BOTH if not embedded else tk.X, expand=not embedded)

    if not embedded:
        header = ctk.CTkFrame(root, fg_color=UI_PANEL_TINT, border_color=UI_BORDER, border_width=1, corner_radius=8)
        header.pack(fill=tk.X, padx=10, pady=(10, 0))
        ctk.CTkLabel(header, text="勤務表登打", text_color="#1e3a8a", font=FONT_TITLE).pack(anchor=tk.W, padx=12, pady=(10, 10))

    body = ctk.CTkFrame(root, fg_color="transparent" if embedded else UI_BG, corner_radius=0)
    body.pack(fill=tk.X, padx=0 if embedded else 10, pady=(0, 0) if embedded else (8, 4))

    status_var = tk.StringVar(value="準備就緒。")
    settings_widgets: list[tk.Widget] = []
    settings_widget_states: dict[tk.Widget, str] = {}

    def card(title: str) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(body, fg_color="transparent" if embedded else UI_PANEL, border_color=UI_BORDER, border_width=0 if embedded else 1, corner_radius=0 if embedded else 8)
        frame.pack(fill=tk.X, pady=(0, 8))
        if embedded and title != "勤務表檔案":
            section_header = ctk.CTkFrame(frame, fg_color="transparent", corner_radius=0)
            section_header.grid(row=0, column=0, columnspan=3, sticky=tk.EW, pady=(2, 4))
            ctk.CTkFrame(section_header, width=4, height=20, fg_color="#2563EB", corner_radius=2).pack(side=tk.LEFT)
            ctk.CTkLabel(section_header, text=title, text_color="#1E3A5F", font=FONT_SECTION_TITLE).pack(side=tk.LEFT, padx=(7, 0))
        elif not embedded:
            ctk.CTkLabel(frame, text=title, text_color="#1e3a8a", font=FONT_TITLE).grid(row=0, column=0, columnspan=3, sticky=tk.W, padx=12, pady=(10, 4))
        frame.columnconfigure(1, weight=1)
        return frame

    user_var = tk.StringVar(value=user_id or login_config.get("user_id", ""))
    password_var = tk.StringVar(value=password or login_config.get("user_pwd", ""))

    file_card = card("勤務表檔案")
    file_card.columnconfigure(2, weight=0)
    saved_workbook = Path(str(last.get("workbook_path", "")))
    default_workbook = saved_workbook if saved_workbook.exists() else next(project_dir.glob("*.xlsm"), None)
    file_var = tk.StringVar(value=str(default_workbook) if default_workbook else "")
    if default_workbook is None or not default_workbook.is_file():
        status_var.set("尚未選擇 Excel 檔案。")
    ctk.CTkLabel(file_card, text="Excel", text_color=UI_MUTED, font=FONT_BODY).grid(row=1, column=0, sticky=tk.W, padx=(12, 8), pady=2 if embedded else 4)
    file_row = ctk.CTkFrame(file_card, fg_color="transparent")
    file_row.grid(row=1, column=1, sticky=tk.EW, padx=(0, 12), pady=2 if embedded else 4)
    file_row.columnconfigure(0, weight=1)
    file_entry = ctk.CTkEntry(file_row, textvariable=file_var, height=32 if embedded else 34, font=FONT_BODY, fg_color=UI_PANEL, border_color=UI_BORDER)
    file_entry.grid(row=0, column=0, sticky=tk.EW)
    settings_widgets.append(file_entry)

    def browse_file() -> None:
        current_file = Path(file_var.get().strip())
        initial_dir = current_file.parent if current_file.parent.exists() else project_dir
        path = filedialog.askopenfilename(parent=dialog, filetypes=[("Excel files", "*.xlsx *.xlsm")], initialdir=str(initial_dir))
        if path:
            file_var.set(path)
            set_status("已選擇勤務表檔案。")

    browse_button = ctk.CTkButton(
        file_row,
        text="選擇",
        command=browse_file,
        width=64,
        height=30,
        font=FONT_BUTTON,
        fg_color=UI_BLUE,
        hover_color=UI_BLUE_HOVER,
    )
    browse_button.grid(row=0, column=1, padx=(6, 0))
    settings_widgets.append(browse_button)

    date_var = tk.StringVar(value=(datetime.now() + timedelta(days=1)).strftime("%Y/%m/%d"))
    date_row = ctk.CTkFrame(file_card, fg_color="transparent")
    date_row.grid(row=2, column=1, sticky=tk.W, padx=(0, 12), pady=2 if embedded else 4)
    date_entry = ctk.CTkEntry(date_row, textvariable=date_var, width=112, height=32 if embedded else 34, font=FONT_BODY, fg_color=UI_PANEL, border_color=UI_BORDER)
    date_entry.pack(side=tk.LEFT)

    def get_selected_date() -> datetime:
        return datetime.strptime(date_var.get().strip(), "%Y/%m/%d")

    def shift_selected_date(days: int) -> None:
        try:
            current = get_selected_date()
        except ValueError:
            current = datetime.now() + timedelta(days=1)
        date_var.set((current + timedelta(days=days)).strftime("%Y/%m/%d"))

    previous_date_button = ctk.CTkButton(date_row, text="<", width=32, height=32 if embedded else 34, font=FONT_BUTTON, fg_color="#dbeafe", text_color="#1d4ed8", hover_color="#bfdbfe", command=lambda: shift_selected_date(-1))
    previous_date_button.pack(side=tk.LEFT, padx=(6, 0))
    next_date_button = ctk.CTkButton(date_row, text=">", width=32, height=32 if embedded else 34, font=FONT_BUTTON, fg_color="#dbeafe", text_color="#1d4ed8", hover_color="#bfdbfe", command=lambda: shift_selected_date(1))
    next_date_button.pack(side=tk.LEFT, padx=(4, 0))
    settings_widgets.extend((date_entry, previous_date_button, next_date_button))

    ctk.CTkLabel(file_card, text="日期", text_color=UI_MUTED, font=FONT_BODY).grid(row=2, column=0, sticky=tk.W, padx=(12, 8), pady=2 if embedded else 4)
    send_group_var = tk.BooleanVar(value=bool(current_config.get("notification", {}).get("enabled", True)))
    send_group_checkbox = ctk.CTkCheckBox(
        file_card,
        text="完成後發送勤務表截圖",
        variable=send_group_var,
        font=FONT_BODY,
        text_color=UI_TEXT,
        fg_color=UI_BLUE,
        hover_color=UI_BLUE_HOVER,
        checkbox_width=18,
        checkbox_height=18,
    )
    send_group_checkbox.grid(row=3, column=1, sticky=tk.W, pady=(2, 6) if embedded else (4, 10))
    settings_widgets.append(send_group_checkbox)

    car_card = card("主力車設定")
    attack_var = tk.StringVar(value=last.get("attack", ""))
    stop_var = tk.StringVar(value=last.get("stop", ""))
    amb1_var = tk.StringVar(value=last.get("amb1", ""))
    amb2_var = tk.StringVar(value=last.get("amb2", ""))
    car_rows = [
        ("攻擊車", attack_var, opts.get("attack", [])),
        ("中繼車", stop_var, opts.get("stop", [])),
        ("救護 1 車", amb1_var, opts.get("amb", [])),
        ("救護 2 車", amb2_var, opts.get("amb", [])),
    ]
    car_combos: dict[str, list[ctk.CTkComboBox]] = {"attack": [], "amb": []}
    for row, (label, variable, values) in enumerate(car_rows):
        ctk.CTkLabel(car_card, text=label, text_color=UI_MUTED, font=FONT_BODY).grid(row=row + 1, column=0, sticky=tk.W, padx=(12, 8), pady=2 if embedded else 4)
        combo = ctk.CTkComboBox(
            car_card,
            variable=variable,
            values=values,
            width=128,
            height=30 if embedded else 32,
            font=FONT_BODY,
            dropdown_font=FONT_BODY,
            **CTK_COMBO_STYLE,
        )
        combo.grid(row=row + 1, column=1, sticky=tk.EW, padx=(0, 12), pady=2 if embedded else 4)
        settings_widgets.append(combo)
        if label == "攻擊車":
            car_combos["attack"].append(combo)
        elif label.startswith("救護"):
            car_combos["amb"].append(combo)

    vehicle_groups = {"消防車": "attack", "救護車": "amb"}

    def persist_vehicle_options() -> None:
        cars_config = {
            "attack": attack_var.get(),
            "stop": stop_var.get(),
            "amb1": amb1_var.get(),
            "amb2": amb2_var.get(),
            "workbook_path": file_var.get().strip(),
        }
        login_settings = {"user_id": user_var.get().strip(), "user_pwd": password_var.get()}
        notification_config = current_config.get("notification", legacy.get_default_config()["notification"]).copy()
        notification_config["enabled"] = bool(send_group_var.get())
        with legacy_workdir(project_dir):
            legacy.save_config(
                cars_config,
                login_settings=login_settings,
                notification_settings=notification_config,
                car_options=opts,
                hidden_car_options=hidden_opts,
            )

    def refresh_vehicle_options() -> None:
        for combo in car_combos["attack"]:
            combo.configure(values=opts.get("attack", []))
        amb_values = opts.get("amb", [])
        for combo in car_combos["amb"]:
            combo.configure(values=amb_values)

    def create_embedded_vehicle_page(title: str) -> tuple[ctk.CTkFrame, ctk.CTkFrame, Callable[[], None]]:
        root.pack_forget()
        page = ctk.CTkFrame(container, fg_color="transparent", corner_radius=0)
        page.pack(fill=tk.X)

        def close_page() -> None:
            if page.winfo_exists():
                page.destroy()
            if root.winfo_exists():
                root.pack(fill=tk.X)

        navigation = ctk.CTkFrame(page, fg_color="transparent", corner_radius=0)
        navigation.pack(fill=tk.X, pady=(0, 14))
        ctk.CTkButton(navigation, text="‹", width=34, height=34, corner_radius=17, font=FONT_NAV_ICON, fg_color="#FFFFFF", text_color="#334155", hover_color="#EFF6FF", border_color="#CBD5E1", border_width=1, command=close_page).pack(side=tk.LEFT)
        ctk.CTkLabel(navigation, text=title, text_color="#0F172A", font=FONT_PANEL_TITLE, anchor=tk.W).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0))
        content = ctk.CTkFrame(page, fg_color="#FFFFFF", border_color="#CBD5E1", border_width=1, corner_radius=14)
        content.pack(fill=tk.X)
        content.columnconfigure(0, weight=1)
        return page, content, close_page

    def open_embedded_add_vehicle_page() -> None:
        _page, content, close_page = create_embedded_vehicle_page("新增車輛")
        vehicle_type_var = tk.StringVar(value="救護車")
        code_var = tk.StringVar()
        plate_var = tk.StringVar()

        ctk.CTkLabel(content, text="車輛類型", text_color=UI_MUTED, font=FONT_BODY, anchor=tk.W).grid(row=0, column=0, sticky=tk.EW, padx=14, pady=(14, 4))
        ctk.CTkComboBox(content, variable=vehicle_type_var, values=list(vehicle_groups.keys()), state="readonly", height=36, font=FONT_BODY, dropdown_font=FONT_BODY, **CTK_COMBO_STYLE).grid(row=1, column=0, sticky=tk.EW, padx=14)
        ctk.CTkLabel(content, text="車輛代號", text_color=UI_MUTED, font=FONT_BODY, anchor=tk.W).grid(row=2, column=0, sticky=tk.EW, padx=14, pady=(12, 4))
        code_entry = ctk.CTkEntry(content, textvariable=code_var, height=36, font=FONT_BODY, fg_color="#FFFFFF", border_color="#CBD5E1")
        code_entry.grid(row=3, column=0, sticky=tk.EW, padx=14)
        ctk.CTkLabel(content, text="車牌號碼", text_color=UI_MUTED, font=FONT_BODY, anchor=tk.W).grid(row=4, column=0, sticky=tk.EW, padx=14, pady=(12, 4))
        ctk.CTkEntry(content, textvariable=plate_var, height=36, font=FONT_BODY, fg_color="#FFFFFF", border_color="#CBD5E1").grid(row=5, column=0, sticky=tk.EW, padx=14)
        ctk.CTkLabel(content, text="新增後會立即更新主力車選單。", text_color=UI_MUTED, font=FONT_CAPTION, anchor=tk.W).grid(row=6, column=0, sticky=tk.EW, padx=14, pady=(10, 0))

        def confirm() -> None:
            code = code_var.get().strip()
            plate = plate_var.get().strip()
            if not code or not plate:
                messagebox.showwarning("資料不足", "請輸入車輛代號與車牌號碼。", parent=dialog)
                return
            apply_added_vehicle(vehicle_groups[vehicle_type_var.get()], f"{code}/{plate}")
            close_page()

        buttons = ctk.CTkFrame(content, fg_color="transparent")
        buttons.grid(row=7, column=0, sticky=tk.EW, padx=14, pady=14)
        buttons.columnconfigure((0, 1), weight=1)
        ctk.CTkButton(buttons, text="返回", height=40, corner_radius=8, font=FONT_BUTTON, fg_color="#F1F5F9", text_color="#334155", hover_color="#E2E8F0", border_color="#CBD5E1", border_width=1, command=close_page).grid(row=0, column=0, sticky=tk.EW, padx=(0, 4))
        ctk.CTkButton(buttons, text="新增", height=40, corner_radius=8, font=FONT_BUTTON, fg_color="#2563EB", hover_color="#1D4ED8", command=confirm).grid(row=0, column=1, sticky=tk.EW, padx=(4, 0))
        code_entry.focus_set()

    def open_add_vehicle_dialog() -> tuple[str, str] | None:
        result: dict[str, str] = {}
        add_dialog = ctk.CTkToplevel(dialog)
        add_dialog.title("新增車輛")
        add_dialog.transient(dialog)
        add_dialog.grab_set()
        add_dialog.resizable(False, False)

        vehicle_type_var = tk.StringVar(value="救護車")
        code_var = tk.StringVar()
        plate_var = tk.StringVar()

        ttk.Label(add_dialog, text="車輛類型").grid(row=0, column=0, sticky=tk.W, padx=12, pady=(12, 4))
        ctk.CTkComboBox(
            add_dialog,
            variable=vehicle_type_var,
            values=list(vehicle_groups.keys()),
            state="readonly",
            width=170,
            height=36,
            font=FONT_BODY,
            dropdown_font=FONT_BODY,
            **CTK_COMBO_STYLE,
        ).grid(row=0, column=1, sticky=tk.EW, padx=12, pady=(12, 4))
        ttk.Label(add_dialog, text="車輛代號").grid(row=1, column=0, sticky=tk.W, padx=12, pady=4)
        code_entry = ttk.Entry(add_dialog, textvariable=code_var, width=20)
        code_entry.grid(row=1, column=1, sticky=tk.EW, padx=12, pady=4)
        ttk.Label(add_dialog, text="車牌號碼").grid(row=2, column=0, sticky=tk.W, padx=12, pady=4)
        ttk.Entry(add_dialog, textvariable=plate_var, width=20).grid(row=2, column=1, sticky=tk.EW, padx=12, pady=4)

        button_row = ttk.Frame(add_dialog)
        button_row.grid(row=3, column=0, columnspan=2, sticky=tk.E, padx=12, pady=(8, 12))

        def confirm() -> None:
            code = code_var.get().strip()
            plate = plate_var.get().strip()
            if not code or not plate:
                messagebox.showwarning("資料不足", "請輸入車輛代號與車牌號碼。", parent=add_dialog)
                return
            result["group"] = vehicle_groups[vehicle_type_var.get()]
            result["value"] = f"{code}/{plate}"
            add_dialog.destroy()

        ctk.CTkButton(button_row, text="確定", width=82, height=36, font=FONT_BUTTON, fg_color=UI_BLUE, hover_color=UI_BLUE_HOVER, command=confirm).pack(side=tk.LEFT, padx=(0, 6))
        ctk.CTkButton(button_row, text="取消", width=82, height=36, font=FONT_BUTTON, fg_color="#e2e8f0", text_color=UI_TEXT, hover_color="#cbd5e1", command=add_dialog.destroy).pack(side=tk.LEFT)
        code_entry.focus_set()
        dialog.wait_window(add_dialog)
        if result:
            return result["group"], result["value"]
        return None

    def add_vehicle_option() -> None:
        if embedded:
            open_embedded_add_vehicle_page()
            return
        selected = open_add_vehicle_dialog()
        if selected is None:
            return
        apply_added_vehicle(*selected)

    def apply_added_vehicle(group: str, value: str) -> None:
        values = opts.setdefault(group, [])
        hidden_values = hidden_opts.setdefault(group, [])
        if value in hidden_values:
            hidden_values.remove(value)
        if value not in values:
            values.append(value)
        refresh_vehicle_options()
        persist_vehicle_options()
        set_status(f"已新增車輛：{value}")

    def removable_vehicle_choices() -> tuple[list[str], dict[str, tuple[str, str]]]:
        choices: list[str] = []
        choice_map: dict[str, tuple[str, str]] = {}
        for group in ("attack", "amb"):
            for value in opts.get(group, []):
                if value not in choice_map:
                    choices.append(value)
                    choice_map[value] = (group, value)
        return choices, choice_map

    def open_embedded_remove_vehicle_page(choices: list[str], choice_map: dict[str, tuple[str, str]]) -> None:
        _page, content, close_page = create_embedded_vehicle_page("移除車輛")
        selected_var = tk.StringVar(value=choices[0])
        ctk.CTkLabel(content, text="要移除的車輛", text_color=UI_MUTED, font=FONT_BODY, anchor=tk.W).grid(row=0, column=0, sticky=tk.EW, padx=14, pady=(14, 4))
        ctk.CTkComboBox(content, variable=selected_var, values=choices, state="readonly", height=36, font=FONT_BODY, dropdown_font=FONT_BODY, **CTK_COMBO_STYLE).grid(row=1, column=0, sticky=tk.EW, padx=14)
        ctk.CTkLabel(content, text="只會從主力車選單移除，不會刪除其他勤務資料。", text_color="#B45309", font=FONT_CAPTION, justify=tk.LEFT, anchor=tk.W, wraplength=320).grid(row=2, column=0, sticky=tk.EW, padx=14, pady=(10, 0))

        def confirm() -> None:
            selected = choice_map.get(selected_var.get())
            if selected is None:
                return
            apply_removed_vehicle(*selected)
            close_page()

        buttons = ctk.CTkFrame(content, fg_color="transparent")
        buttons.grid(row=3, column=0, sticky=tk.EW, padx=14, pady=14)
        buttons.columnconfigure((0, 1), weight=1)
        ctk.CTkButton(buttons, text="返回", height=40, corner_radius=8, font=FONT_BUTTON, fg_color="#F1F5F9", text_color="#334155", hover_color="#E2E8F0", border_color="#CBD5E1", border_width=1, command=close_page).grid(row=0, column=0, sticky=tk.EW, padx=(0, 4))
        ctk.CTkButton(buttons, text="移除", height=40, corner_radius=8, font=FONT_BUTTON, fg_color="#DC2626", hover_color="#B91C1C", command=confirm).grid(row=0, column=1, sticky=tk.EW, padx=(4, 0))

    def open_remove_vehicle_dialog() -> tuple[str, str] | None:
        choices, choice_map = removable_vehicle_choices()
        if not choices:
            messagebox.showwarning("沒有車輛", "目前沒有可移除的車輛。", parent=dialog)
            return None

        result: dict[str, tuple[str, str]] = {}
        remove_dialog = ctk.CTkToplevel(dialog)
        remove_dialog.title("移除車輛")
        remove_dialog.transient(dialog)
        remove_dialog.grab_set()
        remove_dialog.resizable(False, False)

        selected_var = tk.StringVar(value=choices[0])
        ttk.Label(remove_dialog, text="車輛代號/車牌號碼").grid(row=0, column=0, sticky=tk.W, padx=12, pady=(12, 4))
        ctk.CTkComboBox(
            remove_dialog,
            variable=selected_var,
            values=choices,
            state="readonly",
            width=220,
            height=36,
            font=FONT_BODY,
            dropdown_font=FONT_BODY,
            **CTK_COMBO_STYLE,
        ).grid(row=0, column=1, sticky=tk.EW, padx=12, pady=(12, 4))

        button_row = ttk.Frame(remove_dialog)
        button_row.grid(row=1, column=0, columnspan=2, sticky=tk.E, padx=12, pady=(8, 12))

        def confirm() -> None:
            selected_value = selected_var.get()
            if selected_value in choice_map:
                result["selected"] = choice_map[selected_value]
            remove_dialog.destroy()

        ctk.CTkButton(button_row, text="確定", width=82, height=36, font=FONT_BUTTON, fg_color=UI_BLUE, hover_color=UI_BLUE_HOVER, command=confirm).pack(side=tk.LEFT, padx=(0, 6))
        ctk.CTkButton(button_row, text="取消", width=82, height=36, font=FONT_BUTTON, fg_color="#e2e8f0", text_color=UI_TEXT, hover_color="#cbd5e1", command=remove_dialog.destroy).pack(side=tk.LEFT)
        dialog.wait_window(remove_dialog)
        return result.get("selected")

    def remove_vehicle_option() -> None:
        if embedded:
            choices, choice_map = removable_vehicle_choices()
            if not choices:
                messagebox.showwarning("沒有車輛", "目前沒有可移除的車輛。", parent=dialog)
                return
            open_embedded_remove_vehicle_page(choices, choice_map)
            return
        selected = open_remove_vehicle_dialog()
        if selected is None:
            return
        apply_removed_vehicle(*selected)

    def apply_removed_vehicle(group: str, value: str) -> None:
        values = opts.setdefault(group, [])
        if value not in values:
            messagebox.showwarning("找不到車輛", f"車輛清單中沒有：{value}", parent=dialog)
            return
        values.remove(value)
        hidden_values = hidden_opts.setdefault(group, [])
        if value not in hidden_values:
            hidden_values.append(value)
        fallback = values[0] if values else ""
        if group == "attack" and attack_var.get().strip() == value:
            attack_var.set(fallback)
        if group == "amb":
            if amb1_var.get().strip() == value:
                amb1_var.set(fallback)
            if amb2_var.get().strip() == value:
                amb2_var.set(fallback)
        refresh_vehicle_options()
        persist_vehicle_options()
        set_status(f"已移除車輛：{value}")

    vehicle_button_row = ctk.CTkFrame(car_card, fg_color="transparent")
    vehicle_button_row.grid(row=5, column=1, sticky=tk.EW, padx=(0, 12), pady=(4, 6) if embedded else (6, 10))
    vehicle_button_row.columnconfigure(0, weight=1)
    vehicle_button_row.columnconfigure(1, weight=1)
    add_vehicle_button = ctk.CTkButton(
        vehicle_button_row,
        text="新增車輛",
        command=add_vehicle_option,
        height=30 if embedded else 32,
        font=FONT_BUTTON,
        fg_color=UI_BLUE,
        hover_color=UI_BLUE_HOVER,
    )
    add_vehicle_button.grid(row=0, column=0, sticky=tk.EW, padx=(0, 4))
    remove_vehicle_button = ctk.CTkButton(
        vehicle_button_row,
        text="移除車輛",
        command=remove_vehicle_option,
        height=30 if embedded else 32,
        font=FONT_BUTTON,
        fg_color="#fff7ed",
        text_color="#9a3412",
        hover_color="#ffedd5",
    )
    remove_vehicle_button.grid(row=0, column=1, sticky=tk.EW, padx=(4, 0))
    settings_widgets.extend((add_vehicle_button, remove_vehicle_button))

    action_row = ctk.CTkFrame(body, fg_color="transparent" if embedded else UI_BG)
    action_row.pack(fill=tk.X, pady=(4, 0) if embedded else (6, 4))
    action_row.columnconfigure(0, weight=1)

    if embedded:
        status_card = ctk.CTkFrame(body, fg_color="#F0FDF4", border_color="#BBF7D0", border_width=1, corner_radius=10)
        status_card.pack(fill=tk.X, pady=(2, 6), before=action_row)
        status_bar = ctk.CTkLabel(status_card, textvariable=status_var, fg_color="transparent", text_color="#166534", font=FONT_BODY, anchor=tk.W, height=38)
        status_bar.pack(fill=tk.X, padx=12, pady=1)
        bind_side_status_style(status_var, status_card, status_bar)
    else:
        status_bar = ctk.CTkLabel(root, textvariable=status_var, fg_color=UI_PANEL, text_color=UI_MUTED, font=FONT_BODY, anchor=tk.W, height=32)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 6))

    def set_settings_running(running: bool) -> None:
        for widget in settings_widgets:
            try:
                if running:
                    settings_widget_states.setdefault(widget, str(widget.cget("state")))
                    widget.configure(state=tk.DISABLED)
                else:
                    widget.configure(state=settings_widget_states.pop(widget, tk.NORMAL))
            except (tk.TclError, ValueError):
                continue
        start_button.configure(state=tk.DISABLED if running else tk.NORMAL, text="啟動中..." if running else "啟動登打")

    def set_status(message: str) -> None:
        status_var.set(normalize_side_status_message(message))

    def run_on_dialog(callback) -> None:
        event_widget = root if embedded else dialog
        try:
            if event_widget.winfo_exists():
                event_widget.after(0, lambda: callback() if event_widget.winfo_exists() else None)
        except tk.TclError:
            pass

    def run_automation() -> None:
        uid = user_var.get().strip()
        pwd = password_var.get()
        excel_path = file_var.get().strip()
        if not uid or not pwd:
            set_status("失敗：請輸入帳號與密碼。")
            messagebox.showwarning("資料不足", "請輸入帳號與密碼。", parent=dialog)
            return
        if not excel_path:
            set_status("失敗：請選擇 Excel 檔案。")
            messagebox.showwarning("資料不足", "請選擇 Excel 檔案。", parent=dialog)
            return
        selected_date = get_selected_date()
        target_date = legacy.convert_to_minguo(selected_date)
        cars_config = {
            "attack": attack_var.get(),
            "stop": stop_var.get(),
            "amb1": amb1_var.get(),
            "amb2": amb2_var.get(),
            "workbook_path": excel_path,
        }
        login_settings = {"user_id": uid, "user_pwd": pwd}
        notification_config = current_config.get("notification", legacy.get_default_config()["notification"]).copy()
        notification_config["enabled"] = bool(send_group_var.get())

        set_settings_running(True)
        if on_start is not None:
            on_start(target_date)
        set_status(f"開始勤務表登打：{target_date}")

        def worker() -> None:
            success = False
            try:
                legacy.root = dialog
                legacy.status_var = status_var
                if hasattr(legacy, "log_text"):
                    delattr(legacy, "log_text")
                with legacy_workdir(project_dir):
                    legacy.save_config(
                        cars_config,
                        login_settings=login_settings,
                        notification_settings=notification_config,
                        car_options=opts,
                        hidden_car_options=hidden_opts,
                    )
                    automation_result = legacy.start_automation(uid, pwd, target_date, excel_path, cars_config)
                if automation_result is False:
                    error = "勤務表檢查未通過，已停止登打。"
                    if on_error is not None:
                        on_error(error)
                    run_on_dialog(lambda: set_status(f"失敗：{error}"))
                    return
                success = True
                if on_finish is not None:
                    on_finish(f"勤務表登打完成：{target_date}")
            except Exception as exc:
                log_automation_exception("duty_sheet", exc)
                error = format_automation_error(exc)
                if on_error is not None:
                    on_error(error)
                run_on_dialog(lambda: messagebox.showerror("勤務表登打失敗", error, parent=dialog))
                run_on_dialog(lambda: set_status(f"失敗：{error}"))
            finally:
                if success:
                    run_on_dialog(close_dialog)
                else:
                    run_on_dialog(lambda: set_settings_running(False))

        threading.Thread(target=worker, daemon=True).start()

    start_button = ctk.CTkButton(
        action_row,
        text="啟動登打",
        command=run_automation,
        fg_color="#2563EB" if embedded else "#16a34a",
        hover_color="#1D4ED8" if embedded else "#15803d",
        font=FONT_CONTROL_EMPHASIS if embedded else FONT_BUTTON,
        height=50 if embedded else 38,
        corner_radius=9 if embedded else 6,
    )
    start_button.grid(row=0, column=0, sticky=tk.EW, padx=(0, 0 if embedded else 8))
    if not embedded:
        close_button = ctk.CTkButton(
            action_row,
            text="關閉",
            command=close_dialog,
            fg_color="#e2e8f0",
            text_color=UI_TEXT,
            hover_color="#cbd5e1",
            font=FONT_BUTTON,
            width=90,
            height=38,
        )
        close_button.grid(row=0, column=1, sticky=tk.E)
    return root if embedded else dialog
