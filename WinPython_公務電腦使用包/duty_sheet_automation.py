# -*- coding: utf-8 -*-
"""Embedded window for the legacy duty-sheet automation workflow."""

from __future__ import annotations

import importlib.util
import os
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk
from types import ModuleType
from typing import Iterator


LEGACY_SCRIPT = "sinposmart_1.py"
PACKAGED_PROJECT_DIR = "duty_sheet_legacy"
LEGACY_PROJECT_DIR = "勤務表自動化"
ENV_PROJECT_DIR = "SINPOSMART_DUTY_SHEET_PROJECT"


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
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    script_path = project_dir / LEGACY_SCRIPT
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"無法載入勤務表自動化腳本：{script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    sys.path.insert(0, str(project_dir))
    try:
        with legacy_workdir(project_dir):
            spec.loader.exec_module(module)
    finally:
        try:
            sys.path.remove(str(project_dir))
        except ValueError:
            pass
    return module


def open_duty_sheet_dialog(parent: tk.Tk, user_id: str = "", password: str = "") -> tk.Toplevel | None:
    existing = getattr(parent, "_duty_sheet_dialog", None)
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

    dialog = tk.Toplevel(parent)
    setattr(parent, "_duty_sheet_dialog", dialog)
    dialog.title("SinpoSmart - 勤務表登打")
    dialog.geometry("350x500")
    dialog.minsize(350, 480)
    dialog.configure(bg="#f8fafc")
    dialog.transient(parent)

    def close_dialog() -> None:
        setattr(parent, "_duty_sheet_dialog", None)
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", close_dialog)

    root = tk.Frame(dialog, bg="#f8fafc")
    root.pack(fill=tk.BOTH, expand=True)

    header = tk.Frame(root, bg="#eff6ff", highlightbackground="#bfdbfe", highlightthickness=1)
    header.pack(fill=tk.X, padx=10, pady=(10, 0))
    tk.Label(header, text="勤務表登打", bg="#eff6ff", fg="#1e3a8a", font=("Microsoft JhengHei", 11, "bold")).pack(anchor=tk.W, padx=12, pady=(10, 10))

    body = tk.Frame(root, bg="#f8fafc")
    body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(8, 10))

    status_var = tk.StringVar(value="準備就緒。")

    def card(title: str) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(body, text=title, padding=8)
        frame.pack(fill=tk.X, pady=(0, 8))
        frame.columnconfigure(1, weight=1)
        return frame

    user_var = tk.StringVar(value=user_id or login_config.get("user_id", ""))
    password_var = tk.StringVar(value=password or login_config.get("user_pwd", ""))

    file_card = card("勤務表檔案")
    file_card.columnconfigure(2, weight=0)
    saved_workbook = Path(str(last.get("workbook_path", "")))
    default_workbook = saved_workbook if saved_workbook.exists() else next(project_dir.glob("*.xlsm"), None)
    file_var = tk.StringVar(value=str(default_workbook) if default_workbook else "")
    ttk.Label(file_card, text="Excel").grid(row=0, column=0, sticky=tk.W, padx=(0, 6), pady=3)
    file_row = ttk.Frame(file_card)
    file_row.grid(row=0, column=1, sticky=tk.EW, pady=3)
    file_row.columnconfigure(0, weight=1)
    ttk.Entry(file_row, textvariable=file_var, width=12).grid(row=0, column=0, sticky=tk.EW)

    def browse_file() -> None:
        current_file = Path(file_var.get().strip())
        initial_dir = current_file.parent if current_file.parent.exists() else project_dir
        path = filedialog.askopenfilename(parent=dialog, filetypes=[("Excel files", "*.xlsx *.xlsm")], initialdir=str(initial_dir))
        if path:
            file_var.set(path)
            set_status("已選擇勤務表檔案。")

    def bind_button_hover(button: tk.Button, normal_bg: str, hover_bg: str) -> None:
        button.bind("<Enter>", lambda _event: button.configure(bg=hover_bg))
        button.bind("<Leave>", lambda _event: button.configure(bg=normal_bg))

    browse_button = tk.Button(
        file_row,
        text="選擇",
        command=browse_file,
        bg="#2563eb",
        fg="#ffffff",
        activebackground="#1d4ed8",
        activeforeground="#ffffff",
        relief=tk.FLAT,
        width=5,
    )
    bind_button_hover(browse_button, "#2563eb", "#1d4ed8")
    browse_button.grid(row=0, column=1, padx=(6, 0))

    try:
        from tkcalendar import DateEntry

        default_date = datetime.now() + timedelta(days=1)
        date_widget = DateEntry(file_card, width=12, date_pattern="yyyy/mm/dd", year=default_date.year, month=default_date.month, day=default_date.day)
        date_widget.grid(row=1, column=1, sticky=tk.W, pady=3)
        get_selected_date = date_widget.get_date
    except Exception:
        date_var = tk.StringVar(value=(datetime.now() + timedelta(days=1)).strftime("%Y/%m/%d"))
        ttk.Entry(file_card, textvariable=date_var, width=14).grid(row=1, column=1, sticky=tk.W, pady=3)

        def get_selected_date() -> datetime:
            return datetime.strptime(date_var.get().strip(), "%Y/%m/%d")

    ttk.Label(file_card, text="日期").grid(row=1, column=0, sticky=tk.W, padx=(0, 6), pady=3)
    send_group_var = tk.BooleanVar(value=bool(current_config.get("notification", {}).get("enabled", True)))
    tk.Checkbutton(
        file_card,
        text="完成後發送勤務表截圖",
        variable=send_group_var,
        bg="#f8fafc",
        activebackground="#f8fafc",
        fg="#334155",
        activeforeground="#334155",
        selectcolor="#ffffff",
        indicatoron=True,
        font=("Microsoft JhengHei", 9),
    ).grid(row=2, column=1, sticky=tk.W, pady=(2, 3))

    car_card = card("主力車設定")
    combo_width = 14
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
    for row, (label, variable, values) in enumerate(car_rows):
        ttk.Label(car_card, text=label).grid(row=row, column=0, sticky=tk.W, padx=(0, 6), pady=3)
        ttk.Combobox(car_card, textvariable=variable, values=values, width=combo_width).grid(row=row, column=1, sticky=tk.EW, pady=3)

    action_row = tk.Frame(body, bg="#f8fafc")
    action_row.pack(fill=tk.X, pady=(6, 8))
    action_row.columnconfigure(0, weight=1)

    status_bar = ttk.Label(root, textvariable=status_var, relief=tk.SUNKEN, anchor=tk.W, padding=5)
    status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def set_status(message: str) -> None:
        status_var.set(message)

    def run_automation() -> None:
        uid = user_var.get().strip()
        pwd = password_var.get()
        excel_path = file_var.get().strip()
        if not uid or not pwd:
            messagebox.showwarning("資料不足", "請輸入帳號與密碼。", parent=dialog)
            return
        if not excel_path:
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

        start_button.configure(state=tk.DISABLED, text="執行中...")
        set_status(f"開始勤務表登打：{target_date}")

        def worker() -> None:
            success = False
            try:
                legacy.root = dialog
                legacy.status_var = status_var
                if hasattr(legacy, "log_text"):
                    delattr(legacy, "log_text")
                with legacy_workdir(project_dir):
                    legacy.save_config(cars_config, login_settings=login_settings, notification_settings=notification_config)
                    legacy.start_automation(uid, pwd, target_date, excel_path, cars_config)
                success = True
            except Exception as exc:
                error = str(exc)
                dialog.after(0, lambda: messagebox.showerror("勤務表登打失敗", error, parent=dialog))
                dialog.after(0, lambda: set_status(f"失敗：{error}"))
            finally:
                if success:
                    dialog.after(0, close_dialog)
                else:
                    dialog.after(0, lambda: start_button.configure(state=tk.NORMAL, text="啟動登打"))

        threading.Thread(target=worker, daemon=True).start()

    start_button = tk.Button(
        action_row,
        text="啟動登打",
        command=run_automation,
        bg="#16a34a",
        fg="#ffffff",
        activebackground="#15803d",
        activeforeground="#ffffff",
        relief=tk.FLAT,
        font=("Microsoft JhengHei", 11, "bold"),
        height=2,
    )
    bind_button_hover(start_button, "#16a34a", "#15803d")
    start_button.grid(row=0, column=0, sticky=tk.EW, padx=(0, 6))
    close_button = tk.Button(
        action_row,
        text="關閉",
        command=close_dialog,
        bg="#e2e8f0",
        fg="#0f172a",
        activebackground="#cbd5e1",
        activeforeground="#0f172a",
        relief=tk.FLAT,
        font=("Microsoft JhengHei", 11, "bold"),
        width=8,
        height=2,
    )
    bind_button_hover(close_button, "#e2e8f0", "#cbd5e1")
    close_button.grid(row=0, column=1, sticky=tk.NSEW)
    return dialog
