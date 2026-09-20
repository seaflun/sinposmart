# -*- coding: utf-8 -*-
"""Tk fallback dialogs for rest-time and monthly-base entry."""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Callable

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from rest_time_automation import (
    CTK_COMBO_STYLE,
    FONT_BODY,
    FONT_BUTTON,
    FONT_TITLE,
    UI_BG,
    UI_BLUE,
    UI_BLUE_HOVER,
    UI_BORDER,
    UI_MUTED,
    UI_PANEL,
    UI_PANEL_TINT,
    UI_TEXT,
    current_roc_year_month,
    default_workbook_path,
    format_automation_error,
    log_automation_exception,
    nearby_month_options,
    save_last_workbook_path,
    selected_year_month,
    submit_monthly_base_entries,
    submit_rest_entries,
    validate_rest_workbook_path,
    workbook_default_year_month,
)

def open_rest_time_dialog(parent: tk.Tk, user_id: str = "", password: str = "", actor_no: str = "", display_name: str = "", on_start: Callable[[], None] | None = None, on_finish: Callable[[str], None] | None = None, on_error: Callable[[str], None] | None = None, on_stage: Callable[[str], None] | None = None) -> ctk.CTkToplevel | None:
    import tkinter as tk
    from tkinter import filedialog, messagebox

    import customtkinter as ctk

    existing = getattr(parent, "_rest_time_dialog", None)
    if existing is not None:
        try:
            if existing.winfo_exists():
                existing.deiconify()
                existing.lift()
                existing.focus_force()
                return existing
        except Exception:
            pass
        setattr(parent, "_rest_time_dialog", None)

    dialog = ctk.CTkToplevel(parent)
    setattr(parent, "_rest_time_dialog", dialog)
    dialog.title("SinpoSmart - 休息時間登打")
    dialog.geometry("430x350")
    dialog.minsize(430, 350)
    dialog.configure(fg_color=UI_BG)
    dialog.transient(parent)

    def close_dialog() -> None:
        setattr(parent, "_rest_time_dialog", None)
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", close_dialog)

    root = ctk.CTkFrame(dialog, fg_color=UI_BG, corner_radius=0)
    root.pack(fill=tk.BOTH, expand=True)

    header = ctk.CTkFrame(root, fg_color=UI_PANEL_TINT, border_color=UI_BORDER, border_width=1, corner_radius=8)
    header.pack(fill=tk.X, padx=10, pady=(10, 0))
    ctk.CTkLabel(header, text="休息時間登打", text_color="#1e3a8a", font=FONT_TITLE).pack(anchor=tk.W, padx=12, pady=(10, 10))

    body = ctk.CTkFrame(root, fg_color=UI_BG, corner_radius=0)
    body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(8, 10))

    form = ctk.CTkFrame(body, fg_color=UI_PANEL, border_color=UI_BORDER, border_width=1, corner_radius=8)
    form.pack(fill=tk.X, pady=(10, 8))
    ctk.CTkLabel(form, text="勤務表檔案", text_color="#1e3a8a", font=FONT_TITLE).grid(row=0, column=0, columnspan=3, sticky=tk.W, padx=12, pady=(10, 4))
    form.columnconfigure(1, weight=1)

    file_var = tk.StringVar(value=str(default_workbook_path()))
    fixed_roc_year, current_month = current_roc_year_month()
    _default_year, default_month = workbook_default_year_month(Path(file_var.get().strip()))
    allowed_months = nearby_month_options(current_month)
    default_month_text = f"{default_month:02d}"
    month_var = tk.StringVar(value=default_month_text if default_month_text in allowed_months else f"{current_month:02d}")
    status_var = tk.StringVar(value=f"準備就緒。{display_name or actor_no or user_id}")

    ctk.CTkLabel(form, text="Excel", text_color=UI_MUTED, font=FONT_BODY).grid(row=1, column=0, sticky=tk.W, padx=(12, 8), pady=(4, 12))
    file_entry = ctk.CTkEntry(form, textvariable=file_var, height=34, font=FONT_BODY, fg_color=UI_PANEL, border_color=UI_BORDER)
    file_entry.grid(row=1, column=1, sticky=tk.EW, pady=(4, 12))

    def browse_file() -> None:
        current_file = Path(file_var.get().strip())
        initial_dir = current_file.parent if current_file.parent.exists() else PACKAGE_ROOT
        path = filedialog.askopenfilename(parent=dialog, filetypes=[("Excel files", "*.xlsx *.xlsm")], initialdir=str(initial_dir))
        if path:
            file_var.set(path)
            save_last_workbook_path(Path(path))
            _file_year, file_month = workbook_default_year_month(Path(path))
            file_month_text = f"{file_month:02d}"
            if file_month_text in allowed_months:
                month_var.set(file_month_text)
            status_var.set("已選擇勤務表 Excel。")

    browse_button = ctk.CTkButton(
        form,
        text="選擇",
        command=browse_file,
        width=64,
        height=30,
        font=FONT_BUTTON,
        fg_color=UI_BLUE,
        hover_color=UI_BLUE_HOVER,
    )
    browse_button.grid(row=1, column=2, sticky=tk.E, padx=(8, 12), pady=(4, 12))

    ctk.CTkLabel(form, text="年月", text_color=UI_MUTED, font=FONT_BODY).grid(row=2, column=0, sticky=tk.W, padx=(12, 8), pady=(0, 12))
    month_row = ctk.CTkFrame(form, fg_color="transparent")
    month_row.grid(row=2, column=1, columnspan=2, sticky=tk.W, pady=(0, 12))
    ctk.CTkLabel(month_row, text=str(fixed_roc_year), text_color=UI_TEXT, font=FONT_BODY).pack(side=tk.LEFT)
    ctk.CTkLabel(month_row, text="年", text_color=UI_TEXT, font=FONT_BODY).pack(side=tk.LEFT, padx=(6, 10))
    ctk.CTkComboBox(
        month_row,
        variable=month_var,
        values=allowed_months,
        state="readonly",
        width=78,
        height=32,
        font=FONT_BODY,
        dropdown_font=FONT_BODY,
        **CTK_COMBO_STYLE,
    ).pack(side=tk.LEFT)
    ctk.CTkLabel(month_row, text="月", text_color=UI_TEXT, font=FONT_BODY).pack(side=tk.LEFT, padx=(6, 0))

    action_row = ctk.CTkFrame(body, fg_color=UI_BG)
    action_row.pack(fill=tk.X, pady=(8, 8))
    action_row.columnconfigure(0, weight=1)

    status_bar = ctk.CTkLabel(body, textvariable=status_var, fg_color=UI_PANEL, text_color=UI_MUTED, font=FONT_BODY, anchor=tk.W, height=32)
    status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def set_running(running: bool) -> None:
        start_button.configure(state=tk.DISABLED if running else tk.NORMAL, text="登打中..." if running else "啟動登打")

    def run_on_dialog(callback: Callable[[], None]) -> None:
        try:
            if dialog.winfo_exists():
                dialog.after(0, lambda: callback() if dialog.winfo_exists() else None)
        except tk.TclError:
            pass

    def set_status(message: str) -> None:
        run_on_dialog(lambda: status_var.set(message))

    def report_stage(stage: str) -> None:
        if on_stage is not None:
            on_stage(stage)

    def run_automation() -> None:
        report_stage("preflight")
        uid = user_id.strip()
        pwd = password
        workbook_path = Path(file_var.get().strip())
        if not uid or not pwd:
            messagebox.showwarning("缺少帳號密碼", "請先在主視窗登入，再啟動休息時間登打。", parent=dialog)
            return
        try:
            validate_rest_workbook_path(workbook_path)
        except RuntimeError as exc:
            messagebox.showwarning("找不到 Excel", str(exc), parent=dialog)
            return
        try:
            expected_roc_year, expected_month = selected_year_month(str(fixed_roc_year), month_var.get())
        except RuntimeError as exc:
            messagebox.showwarning("年月錯誤", str(exc), parent=dialog)
            return
        save_last_workbook_path(workbook_path)
        if on_start is not None:
            on_start()
        set_running(True)
        set_status("開啟瀏覽器登打休息時間...")

        def worker() -> None:
            try:
                result = submit_rest_entries(uid, pwd, workbook_path, False, set_status, keep_browser_open=True, actor_no=actor_no, expected_roc_year=expected_roc_year, expected_month=expected_month, stage_callback=report_stage)
                if on_finish is not None:
                    on_finish(f"{expected_roc_year}年{expected_month}月 休息時間登打完成：{result}")
                run_on_dialog(lambda: show_complete_and_close(result))
            except Exception as exc:
                log_automation_exception("rest_time", exc)
                error = format_automation_error(exc)
                if on_error is not None:
                    on_error(error)
                run_on_dialog(lambda: messagebox.showerror("休息時間登打失敗", error, parent=dialog))
                set_status(f"失敗：{error}")
            finally:
                run_on_dialog(lambda: set_running(False))

        threading.Thread(target=worker, daemon=True).start()

    def show_complete_and_close(result: str) -> None:
        messagebox.showinfo("完成", result, parent=dialog)
        close_dialog()

    start_button = ctk.CTkButton(
        action_row,
        text="啟動登打",
        command=run_automation,
        fg_color="#16a34a",
        hover_color="#15803d",
        font=FONT_BUTTON,
        height=38,
    )
    start_button.grid(row=0, column=0, sticky=tk.EW, padx=(0, 8))
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
    return dialog


def open_monthly_base_dialog(parent: tk.Tk, user_id: str = "", password: str = "", actor_no: str = "", display_name: str = "", on_start: Callable[[], None] | None = None, on_finish: Callable[[str], None] | None = None, on_error: Callable[[str], None] | None = None, on_stage: Callable[[str], None] | None = None) -> ctk.CTkToplevel | None:
    import tkinter as tk
    from tkinter import messagebox

    import customtkinter as ctk

    existing = getattr(parent, "_monthly_base_dialog", None)
    if existing is not None:
        try:
            if existing.winfo_exists():
                existing.deiconify()
                existing.lift()
                existing.focus_force()
                return existing
        except Exception:
            pass
        setattr(parent, "_monthly_base_dialog", None)

    dialog = ctk.CTkToplevel(parent)
    setattr(parent, "_monthly_base_dialog", dialog)
    dialog.title("SinpoSmart - 勤務基準表登打")
    dialog.geometry("430x330")
    dialog.minsize(430, 330)
    dialog.configure(fg_color=UI_BG)
    dialog.transient(parent)

    def close_dialog() -> None:
        setattr(parent, "_monthly_base_dialog", None)
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", close_dialog)

    root = ctk.CTkFrame(dialog, fg_color=UI_BG, corner_radius=0)
    root.pack(fill=tk.BOTH, expand=True)

    header = ctk.CTkFrame(root, fg_color=UI_PANEL_TINT, border_color=UI_BORDER, border_width=1, corner_radius=8)
    header.pack(fill=tk.X, padx=10, pady=(10, 0))
    ctk.CTkLabel(header, text="勤務基準表登打", text_color="#1e3a8a", font=FONT_TITLE).pack(anchor=tk.W, padx=12, pady=(10, 10))

    body = ctk.CTkFrame(root, fg_color=UI_BG, corner_radius=0)
    body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(8, 10))

    info = ctk.CTkFrame(body, fg_color=UI_PANEL, border_color=UI_BORDER, border_width=1, corner_radius=8)
    info.pack(fill=tk.X, pady=(10, 8))
    ctk.CTkLabel(info, text="固定來源", text_color="#1e3a8a", font=FONT_TITLE).grid(row=0, column=0, sticky=tk.W, padx=12, pady=(10, 4))
    info.columnconfigure(0, weight=1)
    ctk.CTkLabel(info, text=f"Google 試算表 / 輪休基準表  {display_name or actor_no or user_id}", text_color=UI_TEXT, font=FONT_BODY, justify=tk.LEFT, anchor=tk.W).grid(row=1, column=0, sticky=tk.EW, padx=12, pady=(0, 12))

    fixed_roc_year, current_month = current_roc_year_month()
    allowed_months = nearby_month_options(current_month)
    month_var = tk.StringVar(value=f"{current_month:02d}")
    month_row = ctk.CTkFrame(info, fg_color="transparent")
    month_row.grid(row=2, column=0, sticky=tk.W, padx=12, pady=(0, 12))
    ctk.CTkLabel(month_row, text="年月", text_color=UI_MUTED, font=FONT_BODY).pack(side=tk.LEFT, padx=(0, 8))
    ctk.CTkLabel(month_row, text=str(fixed_roc_year), text_color=UI_TEXT, font=FONT_BODY).pack(side=tk.LEFT)
    ctk.CTkLabel(month_row, text="年", text_color=UI_TEXT, font=FONT_BODY).pack(side=tk.LEFT, padx=(6, 10))
    ctk.CTkComboBox(
        month_row,
        variable=month_var,
        values=allowed_months,
        state="readonly",
        width=78,
        height=32,
        font=FONT_BODY,
        dropdown_font=FONT_BODY,
        **CTK_COMBO_STYLE,
    ).pack(side=tk.LEFT)
    ctk.CTkLabel(month_row, text="月", text_color=UI_TEXT, font=FONT_BODY).pack(side=tk.LEFT, padx=(6, 0))

    action_row = ctk.CTkFrame(body, fg_color=UI_BG)
    action_row.pack(fill=tk.X, pady=(8, 8))
    action_row.columnconfigure(0, weight=1)

    status_var = tk.StringVar(value=f"準備就緒。{display_name or actor_no or user_id}")
    status_bar = ctk.CTkLabel(body, textvariable=status_var, fg_color=UI_PANEL, text_color=UI_MUTED, font=FONT_BODY, anchor=tk.W, height=32)
    status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def set_running(running: bool) -> None:
        start_button.configure(state=tk.DISABLED if running else tk.NORMAL, text="登打中..." if running else "啟動登打")

    def run_on_dialog(callback: Callable[[], None]) -> None:
        try:
            if dialog.winfo_exists():
                dialog.after(0, lambda: callback() if dialog.winfo_exists() else None)
        except tk.TclError:
            pass

    def set_status(message: str) -> None:
        run_on_dialog(lambda: status_var.set(message))

    def show_complete_and_close(result: str) -> None:
        messagebox.showinfo("完成", result, parent=dialog)
        close_dialog()

    def report_stage(stage: str) -> None:
        if on_stage is not None:
            on_stage(stage)

    def run_automation() -> None:
        report_stage("preflight")
        uid = user_id.strip()
        pwd = password
        actor = actor_no.strip()
        if not uid or not pwd:
            messagebox.showwarning("缺少帳號密碼", "請先在主視窗登入，再啟動每月基準表登打。", parent=dialog)
            return
        if not actor:
            messagebox.showwarning("缺少番號", "請先在主視窗確認番號，再啟動每月基準表登打。", parent=dialog)
            return
        try:
            expected_roc_year, expected_month = selected_year_month(str(fixed_roc_year), month_var.get())
        except RuntimeError as exc:
            messagebox.showwarning("年月錯誤", str(exc), parent=dialog)
            return
        set_running(True)
        set_status("讀取輪休基準表並開啟勤務基準表...")

        def worker() -> None:
            try:
                if on_start is not None:
                    on_start()
                result = submit_monthly_base_entries(uid, pwd, actor, False, set_status, keep_browser_open=True, expected_roc_year=expected_roc_year, expected_month=expected_month, stage_callback=report_stage)
                if on_finish is not None:
                    on_finish(f"{expected_roc_year}年{expected_month}月 勤務基準表登打完成：{result}")
                run_on_dialog(lambda: show_complete_and_close(result))
            except Exception as exc:
                log_automation_exception("monthly_base", exc)
                error = format_automation_error(exc)
                if on_error is not None:
                    on_error(error)
                run_on_dialog(lambda: messagebox.showerror("每月基準表登打失敗", error, parent=dialog))
                set_status(f"失敗：{error}")
            finally:
                run_on_dialog(lambda: set_running(False))

        threading.Thread(target=worker, daemon=True).start()

    start_button = ctk.CTkButton(
        action_row,
        text="啟動登打",
        command=run_automation,
        fg_color="#16a34a",
        hover_color="#15803d",
        font=FONT_BUTTON,
        height=38,
    )
    start_button.grid(row=0, column=0, sticky=tk.EW, padx=(0, 8))
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
    return dialog
