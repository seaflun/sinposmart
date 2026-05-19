# -*- coding: utf-8 -*-
"""
Tkinter GUI draft for the duty automation workflow.

This GUI is intentionally conservative:
- it can load a rehearsal JSON and show planned work/entry actions;
- each duty member can test-login with their own credentials;
- credentials stay in memory only;

- no duty record is submitted from this GUI yet.
"""

from __future__ import annotations

import json
import threading
import tkinter as tk
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from compare_rehearsal_records import (
    find_entry_matches,
    find_work_matches,
    flatten_rows,
    is_future_action,
    is_possible_handoff_adjustment,
    summarize_entry,
    summarize_work,
)
from duty_rehearsal import (
    ENTRY_LOG_AP,
    WORK_LOG_AP,
    login,
    parse_roc_date,
    planned_actions,
    query_cases,
    query_duty_sheet,
    query_visible_table,
    roc_date,
)


def latest_preview_file() -> Path:
    now = datetime.now()
    today_roc = f"{now.year - 1911:03d}{now.month:02d}{now.day:02d}"
    today_file = schedule_path(today_roc)
    if today_file.exists():
        return today_file
    legacy_today = legacy_rehearsal_path(today_roc)
    if legacy_today.exists():
        return legacy_today
    candidates = sorted(
        list(Path.cwd().glob("schedule_output_*.json")) + list(Path.cwd().glob("rehearsal_output_*.json")),
        key=lambda path: path.stat().st_mtime,
    )
    return candidates[-1] if candidates else Path("rehearsal_output_1150517.json")


def today_roc_date() -> str:
    now = datetime.now()
    return f"{now.year - 1911:03d}{now.month:02d}{now.day:02d}"


def roc_date_after(value: str, days: int) -> str:
    return roc_date(parse_roc_date(value) + timedelta(days=days))


def schedule_path(target_roc_date: str) -> Path:
    return Path(f"schedule_output_{target_roc_date}.json")


def comparison_path(target_roc_date: str) -> Path:
    return Path(f"comparison_output_{target_roc_date}.json")


def legacy_rehearsal_path(target_roc_date: str) -> Path:
    return Path(f"rehearsal_output_{target_roc_date}.json")


DEFAULT_PREVIEW = latest_preview_file()


@dataclass
class LoginSession:
    actor_no: str
    user_id: str
    password: str
    verified: bool = False


class DutyGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("勤務自動化控制台")
        self.geometry("420x620")
        self.minsize(380, 540)

        self.preview_path = tk.StringVar(value=str(DEFAULT_PREVIEW))
        self.audit_date = tk.StringVar(value=today_roc_date())
        self.actor_no = tk.StringVar()
        self.user_id = tk.StringVar()
        self.password = tk.StringVar()
        self.mode = tk.StringVar(value="值班模式")
        self.login_status = tk.StringVar(value="未登入")
        self.filter_actor = tk.BooleanVar(value=False)
        self.simple_mode = tk.BooleanVar(value=True)
        self.status_filter = tk.StringVar(value="需處理")
        self.kind_filter = tk.StringVar(value="全部")
        self.status_text = tk.StringVar(value="請先載入預演 JSON。")
        self.date_text = tk.StringVar(value="")
        self.time_text = tk.StringVar(value="")
        self.next_task_text = tk.StringVar(value="下一項任務：-")
        self.duty_status_text = tk.StringVar(value="請先登入。")
        self.summary_vars = {
            "todo": tk.StringVar(value="需處理 0"),
            "review": tk.StringVar(value="人工確認 0"),
            "ready": tk.StringVar(value="可執行 0"),
            "done": tk.StringVar(value="已存在 0"),
        }

        self.staff: dict[str, dict[str, str]] = {}
        self.actions: list[dict[str, Any]] = []
        self.data: dict[str, Any] = {}
        self.action_compare: dict[int, dict[str, Any]] = {}
        self.session: LoginSession | None = None
        self.executed_due: set[int] = set()
        self.review_widgets: list[tk.Widget] = []
        self.duty_widgets: list[tk.Widget] = []
        self.login_form_widgets: list[tk.Widget] = []
        self.logout_widgets: list[tk.Widget] = []
        self.audit_bottom_frame: ttk.Frame | None = None
        self.snapshot_running = False
        self.snapshot_completed_slots: set[str] = set()
        self.comparison_running = False
        self.comparison_completed_hours: set[str] = set()
        self.logout_cleared = False

        self._build_layout()
        if DEFAULT_PREVIEW.exists():
            self.load_preview(DEFAULT_PREVIEW)
        self.after(1000, self.tick_clock)
        self.after(15000, self.check_scheduled_snapshot)
        self.after(60000, self.check_hourly_comparison)

    def _build_layout(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#f4f7fb")
        style.configure("TLabelframe", background="#f4f7fb", bordercolor="#d5dde8")
        style.configure("TLabelframe.Label", background="#f4f7fb", foreground="#22324a", font=("Microsoft JhengHei UI", 10, "bold"))
        style.configure("TLabel", background="#f4f7fb", foreground="#233044", font=("Microsoft JhengHei UI", 10))
        style.configure("Login.TFrame", background="#ffffff")
        style.configure("Login.TRadiobutton", background="#ffffff", foreground="#334155", font=("Microsoft JhengHei UI", 10))
        style.configure("TButton", font=("Microsoft JhengHei UI", 10), padding=(10, 5))
        style.configure("Accent.TButton", background="#2563eb", foreground="#ffffff")
        style.map("Accent.TButton", background=[("active", "#1d4ed8")])
        style.configure("Soft.TButton", background="#eef2ff", foreground="#243b75")
        style.configure("Treeview", rowheight=30, font=("Microsoft JhengHei UI", 10), background="#ffffff", fieldbackground="#ffffff")
        style.configure("Treeview.Heading", font=("Microsoft JhengHei UI", 10, "bold"), background="#e8eef7", foreground="#1e2b3f")

        root = ttk.Frame(self, padding=14)
        root.pack(fill=tk.BOTH, expand=True)

        top = ttk.LabelFrame(root, text="預演資料", padding=10)
        top.pack(fill=tk.X)
        self.top_frame = top
        self.review_widgets.append(top)
        ttk.Label(top, text="預演 JSON").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(top, textvariable=self.preview_path, width=80).grid(row=0, column=1, sticky=tk.EW, padx=8)
        ttk.Button(top, text="選擇", command=self.choose_preview).grid(row=0, column=2, padx=4)
        ttk.Button(top, text="載入", command=lambda: self.load_preview(Path(self.preview_path.get()))).grid(row=0, column=3)
        top.columnconfigure(1, weight=1)

        login_box = ttk.LabelFrame(root, text="目前值班人員登入", padding=10)
        login_box.pack(fill=tk.X, pady=(10, 0))
        self.login_box = login_box
        self.review_widgets.append(login_box)
        ttk.Label(login_box, text="番號").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(login_box, textvariable=self.actor_no, width=8).grid(row=0, column=1, sticky=tk.W, padx=(6, 16))
        ttk.Label(login_box, text="帳號").grid(row=0, column=2, sticky=tk.W)
        ttk.Entry(login_box, textvariable=self.user_id, width=24).grid(row=0, column=3, sticky=tk.W, padx=(6, 16))
        ttk.Label(login_box, text="密碼").grid(row=0, column=4, sticky=tk.W)
        ttk.Entry(login_box, textvariable=self.password, width=28, show="*").grid(row=0, column=5, sticky=tk.W, padx=(6, 16))
        ttk.Button(login_box, text="測試登入", style="Accent.TButton", command=self.verify_login).grid(row=0, column=6, padx=4)
        ttk.Button(login_box, text="縮小", command=self.iconify).grid(row=0, column=7, padx=4)
        ttk.Button(login_box, text="登出/清除", command=self.clear_login).grid(row=0, column=8, padx=4)
        ttk.Button(login_box, text="查看此人任務", command=self.show_actor_tasks).grid(row=0, column=9, padx=4)
        ttk.Label(login_box, textvariable=self.login_status, foreground="#1f5f3f").grid(row=1, column=0, columnspan=9, sticky=tk.W, pady=(8, 0))

        summary = ttk.Frame(root)
        summary.pack(fill=tk.X, pady=(10, 0))
        self.summary_frame = summary
        self.review_widgets.append(summary)
        for idx, key in enumerate(("todo", "review", "ready", "done")):
            colors = {
                "todo": ("#fff1f2", "#991b1b"),
                "review": ("#fff7ed", "#9a3412"),
                "ready": ("#eff6ff", "#1d4ed8"),
                "done": ("#ecfdf5", "#166534"),
            }
            bg, fg = colors[key]
            card = tk.Frame(summary, bg=bg, highlightbackground="#d8e0ec", highlightthickness=1)
            card.grid(row=0, column=idx, sticky=tk.EW, padx=(0 if idx == 0 else 8, 0))
            tk.Label(card, textvariable=self.summary_vars[key], bg=bg, fg=fg, font=("Microsoft JhengHei UI", 13, "bold"), pady=10).pack(fill=tk.X)
            summary.columnconfigure(idx, weight=1)

        tools = ttk.Frame(root)
        tools.pack(fill=tk.X, pady=(10, 0))
        self.tools_frame = tools
        self.review_widgets.append(tools)
        ttk.Label(tools, text="勤務日期").pack(side=tk.LEFT)
        self.audit_date_combo = ttk.Combobox(tools, textvariable=self.audit_date, values=self.available_audit_dates(), width=10, state="readonly")
        self.audit_date_combo.pack(side=tk.LEFT, padx=(6, 4))
        self.audit_date_combo.bind("<<ComboboxSelected>>", lambda _event: self.load_audit_date())
        ttk.Button(tools, text="◀", width=3, command=lambda: self.shift_audit_date(-1)).pack(side=tk.LEFT)
        ttk.Button(tools, text="▶", width=3, command=lambda: self.shift_audit_date(1)).pack(side=tk.LEFT, padx=(2, 8))
        ttk.Label(tools, text="狀態").pack(side=tk.LEFT, padx=(16, 4))
        ttk.Combobox(
            tools,
            textvariable=self.status_filter,
            values=("需處理", "全部", "可執行", "已存在", "尚未到點", "可能臨時調整", "時間近似", "人工確認", "等待本人登入"),
            width=14,
            state="readonly",
        ).pack(side=tk.LEFT)
        ttk.Label(tools, text="類型").pack(side=tk.LEFT, padx=(12, 4))
        ttk.Combobox(
            tools,
            textvariable=self.kind_filter,
            values=("全部", "工作", "出入"),
            width=8,
            state="readonly",
        ).pack(side=tk.LEFT)
        self.status_filter.trace_add("write", lambda *_: self.refresh_tasks())
        self.kind_filter.trace_add("write", lambda *_: self.refresh_tasks())

        self.audit_bottom_frame = ttk.Frame(root)
        ttk.Button(self.audit_bottom_frame, text="值班模式", command=lambda: self.switch_mode("值班模式")).pack(side=tk.RIGHT)

        columns = (
            "status",
            "compare",
            "execute_time",
            "actor",
            "target",
            "kind",
            "summary",
        )
        self.tree = ttk.Treeview(root, columns=columns, show="headings", height=22)
        headings = {
            "status": "狀態",
            "compare": "比對",
            "execute_time": "登打時間",
            "actor": "登打人",
            "target": "對象/服勤",
            "kind": "類型",
            "summary": "內容",
        }
        widths = {
            "status": 110,
            "compare": 120,
            "execute_time": 80,
            "actor": 70,
            "target": 110,
            "kind": 80,
            "summary": 240,
        }
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor=tk.W)
        self.tree.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.review_widgets.append(self.tree)
        self.tree.tag_configure("todo", background="#fff1f2", foreground="#7f1d1d")
        self.tree.tag_configure("review", background="#fff7ed", foreground="#7c2d12")
        self.tree.tag_configure("near", background="#fefce8", foreground="#713f12")
        self.tree.tag_configure("done", background="#ecfdf5", foreground="#14532d")
        self.tree.tag_configure("ready", background="#eff6ff", foreground="#1e3a8a")
        self.tree.tag_configure("future", background="#f8fafc", foreground="#475569")
        self.tree.tag_configure("adjust", background="#eef2ff", foreground="#3730a3")

        scrollbar = ttk.Scrollbar(self.tree, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        bottom = ttk.LabelFrame(root, text="選取項目明細", padding=10)
        bottom.pack(fill=tk.BOTH, pady=(10, 0))
        self.bottom_frame = bottom
        self.review_widgets.append(bottom)
        self.detail = tk.Text(bottom, height=8, wrap=tk.WORD)
        self.detail.configure(font=("Microsoft JhengHei UI", 10), bg="#ffffff", relief=tk.FLAT, padx=10, pady=8)
        self.detail.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.show_selected_detail)
        self.build_duty_panel(root)
        self.apply_mode()

    def build_duty_panel(self, root: ttk.Frame) -> None:
        panel = ttk.Frame(root)
        self.duty_widgets.append(panel)

        time_panel = tk.Frame(panel, bg="#0f172a", highlightbackground="#0f172a", highlightthickness=1)
        time_panel.pack(fill=tk.X)
        tk.Label(time_panel, textvariable=self.date_text, bg="#0f172a", fg="#cbd5e1", font=("Microsoft JhengHei UI", 12, "bold")).pack(anchor=tk.CENTER, pady=(10, 0))
        tk.Label(time_panel, textvariable=self.time_text, bg="#0f172a", fg="#ffffff", font=("Microsoft JhengHei UI", 28, "bold")).pack(anchor=tk.CENTER, pady=(0, 10))

        login_card = tk.Frame(panel, bg="#eff6ff", highlightbackground="#bfdbfe", highlightthickness=1)
        login_card.pack(fill=tk.X, pady=(10, 0))
        login_panel = tk.Frame(login_card, bg="#eff6ff")
        login_panel.pack(fill=tk.BOTH, expand=True, padx=14, pady=12)
        tk.Label(login_panel, text="消防勤務管理系統登入", bg="#eff6ff", fg="#1e3a8a", font=("Microsoft JhengHei UI", 12, "bold")).pack(anchor=tk.W)
        self.user_label = tk.Label(login_panel, text="帳號", bg="#eff6ff", fg="#64748b", font=("Microsoft JhengHei UI", 9))
        self.user_label.pack(anchor=tk.W, pady=(8, 2))
        self.user_entry = ttk.Entry(login_panel, textvariable=self.user_id, width=28)
        self.user_entry.pack(fill=tk.X)
        self.password_label = tk.Label(login_panel, text="密碼", bg="#eff6ff", fg="#64748b", font=("Microsoft JhengHei UI", 9))
        self.password_label.pack(anchor=tk.W, pady=(6, 2))
        self.password_entry = ttk.Entry(login_panel, textvariable=self.password, width=28, show="*")
        self.password_entry.pack(fill=tk.X)
        self.login_form_widgets.extend([self.user_label, self.user_entry, self.password_label, self.password_entry])

        self.button_row = tk.Frame(login_panel, bg="#eff6ff")
        self.button_row.pack(fill=tk.X, pady=(12, 0))
        self.login_button = ttk.Button(self.button_row, text="登入", style="Accent.TButton", command=self.verify_login)
        self.login_button.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.logout_button = ttk.Button(self.button_row, text="登出", style="Soft.TButton", command=self.clear_login)
        self.logout_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))
        self.login_form_widgets.append(self.login_button)
        self.logout_widgets.append(self.logout_button)
        self.login_status_label = tk.Label(login_panel, textvariable=self.login_status, bg="#eff6ff", fg="#166534", font=("Microsoft JhengHei UI", 9), wraplength=360, justify=tk.LEFT)
        self.login_status_label.pack(anchor=tk.W, pady=(8, 0))

        controls = ttk.Frame(panel)
        controls.pack(fill=tk.X, pady=(10, 0), side=tk.BOTTOM)
        ttk.Button(controls, text="審核模式", style="Soft.TButton", command=lambda: self.switch_mode("審核模式")).pack(side=tk.RIGHT)
        ttk.Button(controls, text="提前記錄", style="Accent.TButton", command=self.early_execute_selected).pack(side=tk.RIGHT, padx=(0, 8))

        columns = ("time", "summary", "status")
        self.duty_tree = ttk.Treeview(panel, columns=columns, show="headings", height=12)
        headings = {
            "time": "時間",
            "summary": "當班任務",
            "status": "狀態",
        }
        widths = {"time": 72, "summary": 230, "status": 82}
        for col in columns:
            self.duty_tree.heading(col, text=headings[col])
            self.duty_tree.column(col, width=widths[col], anchor=tk.W)
        self.duty_tree.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        self.duty_tree.tag_configure("ready", background="#eff6ff", foreground="#1e3a8a")
        self.duty_tree.tag_configure("waiting", background="#ffffff", foreground="#334155")
        self.duty_tree.tag_configure("triggered", background="#ecfdf5", foreground="#14532d")

        self.update_login_panel()

    def choose_preview(self) -> None:
        path = filedialog.askopenfilename(
            title="選擇預演 JSON",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if path:
            self.preview_path.set(path)
            self.load_preview(Path(path))

    def available_audit_dates(self) -> list[str]:
        values = set()
        paths = list(Path.cwd().glob("schedule_output_*.json")) + list(Path.cwd().glob("rehearsal_output_*.json"))
        for path in sorted(paths):
            value = path.stem.rsplit("_", 1)[-1]
            if len(value) == 7 and value.isdigit():
                values.add(value)
        return sorted(values) or [today_roc_date()]

    def shift_audit_date(self, days: int) -> None:
        value = "".join(ch for ch in self.audit_date.get() if ch.isdigit())
        if len(value) != 7:
            value = today_roc_date()
        year = int(value[:3]) + 1911
        month = int(value[3:5])
        day = int(value[5:7])

        shifted = date(year, month, day) + timedelta(days=days)
        self.audit_date.set(f"{shifted.year - 1911:03d}{shifted.month:02d}{shifted.day:02d}")
        self.load_audit_date()

    def show_audit_calendar(self) -> None:
        value = "".join(ch for ch in self.audit_date.get() if ch.isdigit())
        if len(value) != 7:
            value = today_roc_date()
        year = int(value[:3]) + 1911
        month = int(value[3:5])
        selected = date(year, month, 1)

        popup = tk.Toplevel(self)
        popup.title("選擇勤務日期")
        popup.resizable(False, False)
        popup.transient(self)

        container = ttk.Frame(popup, padding=10)
        container.pack(fill=tk.BOTH, expand=True)

        def render(month_date: date) -> None:
            for child in container.winfo_children():
                child.destroy()
            header = ttk.Frame(container)
            header.grid(row=0, column=0, columnspan=7, sticky=tk.EW, pady=(0, 8))

            def move(delta: int) -> None:
                y = month_date.year + ((month_date.month - 1 + delta) // 12)
                m = ((month_date.month - 1 + delta) % 12) + 1
                render(date(y, m, 1))

            ttk.Button(header, text="◀", width=3, command=lambda: move(-1)).pack(side=tk.LEFT)
            ttk.Label(header, text=f"{month_date.year}/{month_date.month:02d}", font=("Microsoft JhengHei UI", 11, "bold")).pack(side=tk.LEFT, expand=True)
            ttk.Button(header, text="▶", width=3, command=lambda: move(1)).pack(side=tk.RIGHT)

            for col, label in enumerate(("一", "二", "三", "四", "五", "六", "日")):
                ttk.Label(container, text=label, anchor=tk.CENTER).grid(row=1, column=col, sticky=tk.EW, padx=2, pady=2)

            first_weekday = month_date.weekday()
            if month_date.month == 12:
                next_month = date(month_date.year + 1, 1, 1)
            else:
                next_month = date(month_date.year, month_date.month + 1, 1)
            days = (next_month - month_date).days
            for day_no in range(1, days + 1):
                offset = first_weekday + day_no - 1
                row = 2 + offset // 7
                col = offset % 7
                d = date(month_date.year, month_date.month, day_no)
                roc = f"{d.year - 1911:03d}{d.month:02d}{d.day:02d}"
                ttk.Button(container, text=str(day_no), width=4, command=lambda value=roc: choose(value)).grid(row=row, column=col, padx=2, pady=2)

        def choose(value: str) -> None:
            self.audit_date.set(value)
            popup.destroy()
            self.load_audit_date()

        render(selected)

    def show_login_dialog(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("勤務系統登入")
        dialog.geometry("420x310")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="登入勤務自動化", font=("Microsoft JhengHei UI", 15, "bold")).pack(anchor=tk.W)

        form = ttk.Frame(frame)
        form.pack(fill=tk.X, pady=(16, 0))
        ttk.Label(form, text="帳號").grid(row=0, column=0, sticky=tk.W, pady=6)
        ttk.Entry(form, textvariable=self.user_id, width=28).grid(row=0, column=1, sticky=tk.EW, pady=6)
        ttk.Label(form, text="密碼").grid(row=1, column=0, sticky=tk.W, pady=6)
        ttk.Entry(form, textvariable=self.password, width=28, show="*").grid(row=1, column=1, sticky=tk.EW, pady=6)
        form.columnconfigure(1, weight=1)

        modes = ttk.LabelFrame(frame, text="模式", padding=8)
        modes.pack(fill=tk.X, pady=(14, 0))
        ttk.Radiobutton(modes, text="值班模式", variable=self.mode, value="值班模式").pack(side=tk.LEFT, padx=(0, 20))
        ttk.Radiobutton(modes, text="審核模式", variable=self.mode, value="審核模式").pack(side=tk.LEFT)

        buttons = ttk.Frame(frame)
        buttons.pack(fill=tk.X, pady=(18, 0))

        def submit() -> None:
            if not self.user_id.get().strip() or not self.password.get():
                messagebox.showwarning("資料不足", "請輸入帳號、密碼。", parent=dialog)
                return
            self.simple_mode.set(self.mode.get() == "值班模式")
            self.apply_mode()
            dialog.destroy()
            self.verify_login()

        ttk.Button(buttons, text="登入", style="Accent.TButton", command=submit).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="取消", command=dialog.destroy).pack(side=tk.RIGHT, padx=(0, 8))
        dialog.bind("<Return>", lambda _event: submit())
        dialog.wait_window()

    def set_mode_from_radio(self) -> None:
        self.switch_mode(self.mode.get())

    def switch_mode(self, mode: str) -> None:
        self.mode.set(mode)
        self.simple_mode.set(mode == "值班模式")
        self.apply_mode()

    def load_preview(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            messagebox.showerror("載入失敗", str(exc))
            return

        today_staff = data.get("today", {}).get("staff", {})
        yesterday_staff = data.get("yesterday", {}).get("staff", {})
        self.data = data
        self.staff = {**yesterday_staff, **today_staff}
        self.actions = data.get("actions", [])
        self.action_compare = self.build_comparison(data)
        compare_note = "，已套用比對檔" if comparison_path(data.get("target_date", "")).exists() else ""
        self.status_text.set(f"已載入 {path.name}，任務 {len(self.actions)} 筆{compare_note}。")
        if hasattr(self, "audit_date_combo"):
            self.audit_date_combo.configure(values=self.available_audit_dates())
        self.refresh_tasks()
        self.refresh_duty_tasks()

    def load_audit_date(self) -> None:
        value = "".join(ch for ch in self.audit_date.get() if ch.isdigit())
        if len(value) != 7:
            messagebox.showwarning("日期格式錯誤", "請輸入民國日期，例如 1150518。")
            return
        path = schedule_path(value)
        if not path.exists():
            path = legacy_rehearsal_path(value)
        if not path.exists():
            messagebox.showwarning("找不到資料", f"找不到 {schedule_path(value).name}，請先產生該日排程資料。")
            return
        self.preview_path.set(str(path))
        self.load_preview(path)

    def load_today_preview_if_available(self) -> bool:
        target_roc_date = today_roc_date()
        path = schedule_path(target_roc_date)
        if not path.exists():
            path = legacy_rehearsal_path(target_roc_date)
        if not path.exists():
            return False
        self.audit_date.set(target_roc_date)
        self.preview_path.set(str(path))
        self.load_preview(path)
        return True

    def build_comparison(self, data: dict[str, Any]) -> dict[int, dict[str, Any]]:
        target_date = data.get("target_date", "")
        comparison_data = self.load_comparison_data(target_date) if target_date else {}
        entry_source = comparison_data.get("visible_entry_rows", data.get("visible_entry_rows", []))
        work_source = comparison_data.get("visible_work_rows", data.get("visible_work_rows", []))
        entry_rows = flatten_rows(entry_source, target_date) if target_date else []
        work_rows = flatten_rows(work_source, target_date) if target_date else []
        result: dict[int, dict[str, Any]] = {}
        external_targets: dict[str, set[str]] = {}
        for action in [a for a in data.get("actions", []) if a.get("kind") == "entry_log" and a.get("source", "").startswith("外勤")]:
            fields = action.get("fields", {})
            key = f"{fields.get('系統寫入時間', action.get('time', ''))}:{fields.get('出或入', '')}"
            external_targets.setdefault(key, set()).add(self.staff.get(str(action.get("target", "")), {}).get("name", ""))

        for index, action in enumerate(data.get("actions", [])):
            fields = action.get("fields", {})
            if action.get("kind") == "entry_log":
                reason = fields.get("領用事由及地點", "")
                if is_future_action(target_date, action):
                    result[index] = {"compare": "尚未到點", "group": "future", "matched": []}
                else:
                    exact = find_entry_matches(entry_rows, target_date, self.staff, action, allow_near=False)
                    near = [] if exact else find_entry_matches(entry_rows, target_date, self.staff, action, allow_near=True)
                    if exact:
                        result[index] = {"compare": "已存在", "group": "done", "matched": exact[:1]}
                    elif is_possible_handoff_adjustment(entry_rows, target_date, self.staff, action):
                        result[index] = {"compare": "可能臨時調整", "group": "adjust", "matched": []}
                    elif near:
                        result[index] = {"compare": "時間近似", "group": "near", "matched": near[:1]}
                    elif reason in ("到勤", "退勤", "休息後退勤"):
                        result[index] = {"compare": "需補登", "group": "todo", "matched": []}
                    elif action.get("source", "").startswith("外勤"):
                        result[index] = {"compare": "人工確認", "group": "review", "matched": []}
                    else:
                        result[index] = {"compare": "未找到", "group": "todo", "matched": []}
            else:
                if is_future_action(target_date, action):
                    result[index] = {"compare": "尚未到點", "group": "future", "matched": []}
                else:
                    matches = find_work_matches(work_rows, target_date, self.staff, action)
                    if matches:
                        result[index] = {"compare": "已存在", "group": "done", "matched": matches[:1]}
                    else:
                        result[index] = {"compare": "未找到", "group": "todo", "matched": []}

        for index, action in enumerate(data.get("actions", [])):
            # A matching external record under a different name means the planned
            # row needs human confirmation, not automatic補登.
            if action.get("kind") != "entry_log" or not action.get("source", "").startswith("外勤"):
                continue
            fields = action.get("fields", {})
            key = f"{fields.get('系統寫入時間', action.get('time', ''))}:{fields.get('出或入', '')}"
            if result.get(index, {}).get("compare") == "人工確認" and external_targets.get(key):
                result[index]["compare"] = "外勤確認"
        return result

    def load_comparison_data(self, target_roc_date: str) -> dict[str, Any]:
        path = comparison_path(target_roc_date)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def verify_login(self) -> None:
        user_id = self.user_id.get().strip()
        password = self.password.get()
        if not user_id or not password:
            messagebox.showwarning("資料不足", "請輸入帳號、密碼。")
            return

        self.login_status.set("測試登入中...")
        thread = threading.Thread(target=self._verify_login_worker, args=(user_id, password), daemon=True)
        thread.start()

    def _verify_login_worker(self, user_id: str, password: str) -> None:
        driver = None
        try:
            options = Options()
            options.add_argument("--headless=new")
            options.add_argument("--disable-popup-blocking")
            driver = webdriver.Chrome(options=options)
            login(driver, user_id, password)
            actor_no, actor_name = self.identify_logged_in_actor(driver)
            if not actor_no:
                raise RuntimeError("登入成功，但頁面未顯示可辨識的登入者姓名，暫時無法自動反查番號。")
        except Exception as exc:
            self.after(0, lambda: self._login_failed(str(exc)))
            return
        finally:
            if driver:
                driver.quit()
        self.after(0, lambda: self._login_succeeded(actor_no, user_id, password))

    def write_schedule_snapshot(self, driver: webdriver.Chrome, target_roc_date: str, slot_label: str = "") -> Path:
        target_date = parse_roc_date(target_roc_date)
        yesterday_date = target_date - timedelta(days=1)
        tomorrow_date = target_date + timedelta(days=1)

        today_sheet = query_duty_sheet(driver, roc_date(target_date))
        yesterday_sheet = query_duty_sheet(driver, roc_date(yesterday_date))
        try:
            tomorrow_sheet = query_duty_sheet(driver, roc_date(tomorrow_date))
        except Exception:
            tomorrow_sheet = None
        yesterday_cases = query_cases(driver, roc_date(yesterday_date))
        cases = query_cases(driver, roc_date(target_date))
        actions = planned_actions(today_sheet, yesterday_sheet, cases, target_date, yesterday_cases, tomorrow_sheet)

        payload = {
            "file_type": "schedule",
            "target_date": roc_date(target_date),
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "today": asdict(today_sheet),
            "yesterday": asdict(yesterday_sheet),
            "tomorrow": asdict(tomorrow_sheet) if tomorrow_sheet else None,
            "cases": [asdict(c) for c in cases],
            "yesterday_cases": [asdict(c) for c in yesterday_cases],
            "actions": [asdict(a) for a in actions],
        }

        canonical_path = schedule_path(target_roc_date)
        canonical_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        snapshots_dir = Path("snapshots")
        snapshots_dir.mkdir(exist_ok=True)
        slot_part = f"_{slot_label}" if slot_label else ""
        snapshot_path = snapshots_dir / f"schedule_output_{target_roc_date}{slot_part}_{datetime.now():%H%M%S}.json"
        snapshot_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return canonical_path

    def write_comparison_snapshot(self, driver: webdriver.Chrome, target_roc_date: str, slot_label: str = "") -> Path:
        work_rows = query_visible_table(driver, WORK_LOG_AP, target_roc_date)
        entry_rows = query_visible_table(driver, ENTRY_LOG_AP, target_roc_date)
        payload = {
            "file_type": "comparison",
            "target_date": target_roc_date,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "visible_work_rows": work_rows,
            "visible_entry_rows": entry_rows,
        }

        canonical_path = comparison_path(target_roc_date)
        canonical_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        snapshots_dir = Path("snapshots")
        snapshots_dir.mkdir(exist_ok=True)
        slot_part = f"_{slot_label}" if slot_label else ""
        snapshot_path = snapshots_dir / f"comparison_output_{target_roc_date}{slot_part}_{datetime.now():%H%M%S}.json"
        snapshot_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return canonical_path

    def check_scheduled_snapshot(self) -> None:
        try:
            now = datetime.now()
            if now.hour == 22 and now.minute < 10:
                target_roc_date = roc_date_after(today_roc_date(), 1)
                key = f"schedule-{target_roc_date}-2200"
                if schedule_path(target_roc_date).exists():
                    self.snapshot_completed_slots.add(key)
                elif key not in self.snapshot_completed_slots:
                    self.refresh_schedule_background(target_roc_date, "2200")
        finally:
            self.after(30000, self.check_scheduled_snapshot)

    def refresh_schedule_background(self, target_roc_date: str, slot_label: str) -> None:
        if self.snapshot_running or not (self.session and self.session.verified):
            return
        session = self.session
        key = f"schedule-{target_roc_date}-{slot_label}"
        self.snapshot_running = True
        self.login_status.set(f"已登入：{self.person_label(session.actor_no)}，正在建立 {target_roc_date} 排程...")

        def worker() -> None:
            driver = None
            try:
                options = Options()
                options.add_argument("--headless=new")
                options.add_argument("--disable-popup-blocking")
                driver = webdriver.Chrome(options=options)
                login(driver, session.user_id, session.password)
                path = self.write_schedule_snapshot(driver, target_roc_date, slot_label)
            except Exception as exc:
                error = str(exc)
                self.after(0, lambda: self._schedule_failed(session.actor_no, error))
                return
            finally:
                if driver:
                    driver.quit()
            self.after(0, lambda: self._schedule_succeeded(session.actor_no, key, path))

        threading.Thread(target=worker, daemon=True).start()

    def _schedule_succeeded(self, actor_no: str, key: str, path: Path) -> None:
        self.snapshot_running = False
        self.snapshot_completed_slots.add(key)
        if path.exists():
            self.preview_path.set(str(path))
            self.load_preview(path)
        self.login_status.set(f"已登入：{self.person_label(actor_no)}，已建立排程資料。")

    def _schedule_failed(self, actor_no: str, error: str) -> None:
        self.snapshot_running = False
        self.login_status.set(f"已登入：{self.person_label(actor_no)}，建立排程失敗：{error}")

    def check_hourly_comparison(self) -> None:
        try:
            now = datetime.now()
            if now.minute < 5 and self.session and self.session.verified:
                target_roc_date = self.data.get("target_date") or today_roc_date()
                key = f"comparison-{target_roc_date}-{now:%Y%m%d%H}"
                if key not in self.comparison_completed_hours:
                    self.refresh_comparison_background(target_roc_date, f"{now:%H}00")
        finally:
            self.after(60000, self.check_hourly_comparison)

    def refresh_comparison_background(self, target_roc_date: str, slot_label: str) -> None:
        if self.comparison_running or not (self.session and self.session.verified):
            return
        session = self.session
        key = f"comparison-{target_roc_date}-{datetime.now():%Y%m%d%H}"
        self.comparison_running = True
        self.login_status.set(f"已登入：{self.person_label(session.actor_no)}，背景比對 {target_roc_date}...")

        def worker() -> None:
            driver = None
            try:
                options = Options()
                options.add_argument("--headless=new")
                options.add_argument("--disable-popup-blocking")
                driver = webdriver.Chrome(options=options)
                login(driver, session.user_id, session.password)
                path = self.write_comparison_snapshot(driver, target_roc_date, slot_label)
            except Exception as exc:
                error = str(exc)
                self.after(0, lambda: self._comparison_failed(session.actor_no, error))
                return
            finally:
                if driver:
                    driver.quit()
            self.after(0, lambda: self._comparison_succeeded(session.actor_no, key, target_roc_date, path))

        threading.Thread(target=worker, daemon=True).start()

    def _comparison_succeeded(self, actor_no: str, key: str, target_roc_date: str, path: Path) -> None:
        self.comparison_running = False
        self.comparison_completed_hours.add(key)
        if path.exists() and self.data.get("target_date") == target_roc_date:
            self.action_compare = self.build_comparison(self.data)
            self.refresh_tasks()
            self.refresh_duty_tasks()
        self.login_status.set(f"已登入：{self.person_label(actor_no)}，背景比對已更新。")

    def _comparison_failed(self, actor_no: str, error: str) -> None:
        self.comparison_running = False
        self.login_status.set(f"已登入：{self.person_label(actor_no)}，背景比對失敗：{error}")

    def identify_logged_in_actor(self, driver: webdriver.Chrome) -> tuple[str, str]:
        texts = [self.page_identity_text(driver)]
        frames = driver.find_elements("tag name", "frame") + driver.find_elements("tag name", "iframe")
        for frame in frames:
            try:
                driver.switch_to.default_content()
                driver.switch_to.frame(frame)
                texts.append(self.page_identity_text(driver))
            except Exception:
                continue
        driver.switch_to.default_content()
        page_text = "\n".join(texts)
        candidates = []
        for no, info in self.staff.items():
            name = info.get("name", "")
            if name and name in page_text:
                candidates.append((str(no), name))
        if len(candidates) == 1:
            return candidates[0]
        return "", ""

    def page_identity_text(self, driver: webdriver.Chrome) -> str:
        return driver.execute_script(
            """
            const body = document.body ? document.body.innerText : '';
            const values = Array.from(document.querySelectorAll('input,select,textarea'))
              .map(el => el.value || el.options?.[el.selectedIndex]?.text || '')
              .filter(Boolean)
              .join('\\n');
            return [document.title || '', body, values].join('\\n');
            """
        ) or ""

    def _login_succeeded(self, actor_no: str, user_id: str, password: str) -> None:
        self.session = LoginSession(actor_no=actor_no, user_id=user_id, password=password, verified=True)
        self.login_status.set(f"已登入：{self.person_label(actor_no)}")
        self.actor_no.set(actor_no)
        self.password.set("")
        self.logout_cleared = False
        self.audit_date.set(today_roc_date())
        if self.simple_mode.get():
            self.filter_actor.set(True)
            self.status_filter.set("可執行")
        self.update_login_panel()
        if self.load_today_preview_if_available():
            self.login_status.set(f"已登入：{self.person_label(actor_no)}，已載入今日資料。")
        else:
            self.refresh_tasks()
            self.refresh_duty_tasks()
            self.login_status.set(f"已登入：{self.person_label(actor_no)}，找不到今日排程檔，登入未執行系統查詢。")

    def _login_failed(self, error: str) -> None:
        self.session = None
        self.login_status.set(f"登入失敗：{error}")
        self.update_login_panel()
        self.refresh_tasks()

    def clear_login(self) -> None:
        self.session = None
        self.password.set("")
        self.logout_cleared = True
        self.login_status.set("已清除登入狀態。")
        self.update_login_panel()
        self.refresh_tasks()
        self.refresh_duty_tasks()
        self.next_task_text.set("下一項任務：-")
        self.duty_status_text.set("")

    def update_login_panel(self) -> None:
        if not hasattr(self, "login_button"):
            return
        if self.session and self.session.verified:
            for widget in self.login_form_widgets:
                widget.pack_forget()
            if not self.logout_button.winfo_manager():
                self.logout_button.pack(side=tk.LEFT, fill=tk.X, expand=True)
        else:
            if not self.user_label.winfo_manager():
                self.user_label.pack(anchor=tk.W, pady=(12, 2), before=self.button_row)
            if not self.user_entry.winfo_manager():
                self.user_entry.pack(fill=tk.X, before=self.button_row)
            if not self.password_label.winfo_manager():
                self.password_label.pack(anchor=tk.W, pady=(8, 2), before=self.button_row)
            if not self.password_entry.winfo_manager():
                self.password_entry.pack(fill=tk.X, before=self.button_row)
            if not self.login_button.winfo_manager():
                self.login_button.pack(side=tk.LEFT, fill=tk.X, expand=True, before=self.logout_button)
            self.logout_button.pack_forget()

    def show_actor_tasks(self) -> None:
        actor_no = self.actor_no.get().strip()
        if not actor_no:
            messagebox.showwarning("缺少番號", "請先輸入番號。")
            return
        if self.session and self.session.verified and self.session.actor_no != actor_no:
            self.session = None
            self.login_status.set("番號已變更，請重新測試登入。")
        self.filter_actor.set(True)
        self.refresh_tasks()

    def tick_clock(self) -> None:
        now = datetime.now()
        self.date_text.set(f"{now.year}/{now.month:02d}/{now.day:02d}")
        self.time_text.set(now.strftime("%H:%M:%S"))
        if self.simple_mode.get():
            self.refresh_duty_tasks()
            self.trigger_due_tasks(now)
        self.after(1000, self.tick_clock)

    def duty_task_indices(self) -> list[int]:
        actor_no = self.session.actor_no if self.session and self.session.verified else self.actor_no.get().strip()
        if not actor_no:
            return []
        indices = []
        for index, action in enumerate(self.actions):
            if str(action.get("actor", "")) != actor_no:
                continue
            compare = self.action_compare.get(index, {})
            if compare.get("group") == "review":
                continue
            indices.append(index)
        return sorted(indices, key=lambda idx: self.action_minutes(self.actions[idx]))

    def action_minutes(self, action: dict[str, Any]) -> int:
        value = action.get("fields", {}).get("登打時間") or action.get("fields", {}).get("工作時間") or action.get("time", "00:00")
        try:
            hour, minute = [int(part) for part in value.split(":", 1)]
        except ValueError:
            return 0
        return hour * 60 + minute

    def refresh_duty_tasks(self) -> None:
        if not hasattr(self, "duty_tree"):
            return
        self.duty_tree.delete(*self.duty_tree.get_children())
        if self.logout_cleared and not (self.session and self.session.verified):
            self.next_task_text.set("下一項任務：-")
            self.duty_status_text.set("")
            return
        now = datetime.now()
        now_min = now.hour * 60 + now.minute
        next_item = None
        for index in self.duty_task_indices():
            action = self.actions[index]
            minutes = self.action_minutes(action)
            if next_item is None and minutes >= now_min:
                next_item = action
            compare = self.action_compare.get(index, {})
            if compare.get("group") == "done":
                status = "已存在"
                tag = "triggered"
            elif index in self.executed_due:
                status = "已記錄"
                tag = "triggered"
            else:
                status = "到點待執行" if minutes <= now_min else "等待"
                tag = "ready" if minutes <= now_min else "waiting"
            fields = action.get("fields", {})
            task_time = fields.get("登打時間") or fields.get("工作時間") or action.get("time", "")
            self.duty_tree.insert(
                "",
                tk.END,
                iid=f"duty-{index}",
                values=(
                    task_time,
                    f"{'出入' if action.get('kind') == 'entry_log' else '工作'}｜{self.duty_action_summary(action)}",
                    status,
                ),
                tags=(tag,),
            )
        if next_item:
            next_min = self.action_minutes(next_item)
            delta = max(0, next_min - now_min)
            self.next_task_text.set(f"{next_min // 60:02d}:{next_min % 60:02d}  {self.action_summary(next_item)}，約 {delta} 分鐘後")
        else:
            self.next_task_text.set("今日目前沒有未完成的當班任務")
        if self.session and self.session.verified:
            self.duty_status_text.set("登入有效；到點後會記錄待接線任務。")
        elif self.logout_cleared:
            self.duty_status_text.set("")
        else:
            self.duty_status_text.set("尚未登入，所有任務不執行。")

    def trigger_due_tasks(self, now: datetime) -> None:
        if not self.session or not self.session.verified:
            return
        now_min = now.hour * 60 + now.minute
        for index in self.duty_task_indices():
            if index in self.executed_due:
                continue
            action = self.actions[index]
            if self.action_minutes(action) <= now_min:
                self.log_trigger(index, action, "due")
                self.executed_due.add(index)
                self.duty_status_text.set(f"已記錄待接線：{self.action_summary(action)}")

    def early_execute_selected(self) -> None:
        selection = self.duty_tree.selection()
        if not selection:
            messagebox.showinfo("提前記錄", "請先選擇一筆當班任務。")
            return
        iid = selection[0]
        if not str(iid).startswith("duty-"):
            return
        index = int(str(iid).split("-", 1)[1])
        if not self.session or not self.session.verified:
            messagebox.showwarning("尚未登入", "請先登入後再提前記錄。")
            return
        self.log_trigger(index, self.actions[index], "manual")
        self.executed_due.add(index)
        self.duty_status_text.set(f"已記錄待接線：{self.duty_action_summary(self.actions[index])}")
        self.refresh_duty_tasks()

    def log_trigger(self, index: int, action: dict[str, Any], trigger_type: str) -> None:
        session = self.session
        record = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "trigger_type": trigger_type,
            "action_index": index,
            "actor_no": session.actor_no if session else "",
            "user_id": session.user_id if session else "",
            "target_date": self.data.get("target_date", ""),
            "kind": action.get("kind", ""),
            "time": action.get("time", ""),
            "source": action.get("source", ""),
            "target": action.get("target", ""),
            "fields": action.get("fields", {}),
            "status": "pending_write_automation",
        }
        with Path("duty_trigger_log.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def apply_mode(self) -> None:
        for widget in (self.top_frame, self.login_box, self.summary_frame, self.tools_frame, self.tree, self.bottom_frame):
            widget.pack_forget()
        if self.audit_bottom_frame is not None:
            self.audit_bottom_frame.pack_forget()
        for widget in self.duty_widgets:
            widget.pack_forget()

        self.mode.set("值班模式" if self.simple_mode.get() else "審核模式")
        if self.simple_mode.get():
            self.geometry("420x620")
            self.minsize(380, 540)
            self.filter_actor.set(True)
            if self.status_filter.get() in ("需處理", "全部", "已存在", "時間近似", "人工確認", "等待本人登入"):
                self.status_filter.set("可執行")
            self.title("勤務自動化控制台 - 值班人員")
            self.duty_widgets[0].pack(fill=tk.BOTH, expand=True)
        else:
            self.geometry("1040x650")
            self.minsize(900, 560)
            self.filter_actor.set(False)
            self.status_filter.set("需處理")
            self.title("勤務自動化控制台 - 幹部審查")
            if self.data.get("target_date"):
                self.audit_date.set(self.data["target_date"])
            self.tools_frame.pack(fill=tk.X, pady=(0, 10))
            self.summary_frame.pack(fill=tk.X, pady=(0, 10))
            self.tree.pack(fill=tk.BOTH, expand=True, pady=(0, 0))
            if self.audit_bottom_frame is not None:
                self.audit_bottom_frame.pack(fill=tk.X, pady=(10, 0), side=tk.BOTTOM)
        self.refresh_tasks()
        self.refresh_duty_tasks()

    def refresh_tasks(self) -> None:
        self.tree.delete(*self.tree.get_children())
        current_actor = self.session.actor_no if self.session and self.session.verified else self.actor_no.get().strip()
        visible = 0
        counts = {"todo": 0, "review": 0, "ready": 0, "done": 0}
        for index, action in enumerate(self.actions):
            actor = str(action.get("actor", ""))
            if self.filter_actor.get() and current_actor and actor != current_actor:
                continue
            if not self.kind_matches_filter(action):
                continue
            compare = self.action_compare.get(index, {"compare": "未比對", "group": "ready"})
            run_status = self.action_status(actor, compare)
            group = compare.get("group", "ready")
            if group == "todo":
                counts["todo"] += 1
            elif group in ("review", "adjust"):
                counts["review"] += 1
            elif group == "done":
                counts["done"] += 1
            elif run_status == "可執行":
                counts["ready"] += 1
            if not self.status_matches_filter(run_status, compare):
                continue
            visible += 1
            fields = action.get("fields", {})
            execute_time = fields.get("登打時間", action.get("time", ""))
            tag = self.tree_tag(run_status, compare)
            self.tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(
                    run_status,
                    compare.get("compare", ""),
                    execute_time,
                    self.person_short_label(actor),
                    self.target_short_label(action),
                    "出入" if action.get("kind") == "entry_log" else "工作",
                    self.action_summary(action),
                ),
                tags=(tag,),
            )
        self.status_text.set(f"顯示 {visible} / {len(self.actions)} 筆。")
        self.summary_vars["todo"].set(f"需補登 {counts['todo']}")
        self.summary_vars["review"].set(f"人工確認 {counts['review']}")
        self.summary_vars["ready"].set(f"可執行 {counts['ready']}")
        self.summary_vars["done"].set(f"已存在 {counts['done']}")

    def kind_matches_filter(self, action: dict[str, Any]) -> bool:
        value = self.kind_filter.get()
        if value == "全部":
            return True
        if value == "出入":
            return action.get("kind") == "entry_log"
        if value == "工作":
            return action.get("kind") == "work_log"
        return True

    def action_status(self, actor: str, compare: dict[str, Any]) -> str:
        if compare.get("group") == "done":
            return "略過"
        if compare.get("group") == "review":
            return "人工確認"
        if compare.get("group") == "adjust":
            return "人工確認"
        if not self.session or not self.session.verified:
            return "未登入不執行"
        if actor == self.session.actor_no:
            return "可執行"
        return "等待本人登入"

    def status_matches_filter(self, run_status: str, compare: dict[str, Any]) -> bool:
        value = self.status_filter.get()
        if value == "全部":
            return True
        if value == "需處理":
            return compare.get("group") in ("todo", "review", "adjust")
        if value == "可執行" and (not self.session or not self.session.verified):
            return run_status == "未登入不執行" and compare.get("group") != "done"
        if value == "已存在":
            return compare.get("group") == "done"
        if value == "時間近似":
            return compare.get("group") == "near"
        if value == "人工確認":
            return compare.get("group") == "review"
        if value == "尚未到點":
            return compare.get("group") == "future"
        if value == "可能臨時調整":
            return compare.get("group") == "adjust"
        return run_status == value

    def tree_tag(self, run_status: str, compare: dict[str, Any]) -> str:
        group = compare.get("group")
        if group in ("todo", "review", "near", "done", "future", "adjust"):
            return group
        if run_status == "可執行":
            return "ready"
        return ""

    def person_label(self, number: str) -> str:
        if not number:
            return "-"
        info = self.staff.get(str(number), {})
        name = info.get("name", "")
        role = info.get("role", "")
        if name and role:
            return f"{number}番 {name}（{role}）"
        if name:
            return f"{number}番 {name}"
        return f"{number}番"

    def person_short_label(self, number: str) -> str:
        if not number:
            return "-"
        info = self.staff.get(str(number), {})
        name = info.get("name", "")
        return f"{number}{name}" if name else str(number)

    def target_label(self, action: dict[str, Any]) -> str:
        fields = action.get("fields", {})
        if action.get("kind") == "work_log":
            people = fields.get("服勤人員", [])
            return "、".join(self.person_label(no) for no in people) if people else self.person_label(action.get("target", ""))
        return self.person_label(action.get("target", ""))

    def target_numbers(self, action: dict[str, Any]) -> str:
        fields = action.get("fields", {})
        if action.get("kind") == "work_log":
            people = fields.get("服勤人員", [])
            return ",".join(str(no) for no in people) if people else str(action.get("target", "") or "-")
        return str(action.get("target", "") or "-")

    def target_short_label(self, action: dict[str, Any]) -> str:
        fields = action.get("fields", {})
        if action.get("kind") == "work_log":
            people = fields.get("服勤人員", [])
            return ",".join(self.person_short_label(str(no)) for no in people) if people else self.person_short_label(str(action.get("target", "") or ""))
        return self.person_short_label(str(action.get("target", "") or ""))

    def action_summary(self, action: dict[str, Any]) -> str:
        fields = action.get("fields", {})
        if action.get("kind") == "entry_log":
            return f"{fields.get('出或入', '')} / {fields.get('領用事由及地點', '')}"
        item = fields.get("勤務項目", "")
        reason = fields.get("事由", "")
        topic = fields.get("訓練項目", "")
        return " / ".join(part for part in (item, reason, topic) if part)

    def duty_action_summary(self, action: dict[str, Any]) -> str:
        fields = action.get("fields", {})
        if action.get("source") == "在隊訓練":
            return fields.get("訓練項目") or self.action_summary(action)
        if action.get("kind") == "entry_log":
            return f"{self.action_summary(action)}｜{self.target_short_label(action)}"
        return f"{self.action_summary(action)}｜{self.target_short_label(action)}"

    def show_selected_detail(self, _event: tk.Event) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        action = self.actions[int(selection[0])]
        compare = self.action_compare.get(int(selection[0]), {})
        self.detail.delete("1.0", tk.END)
        if action.get("kind") == "entry_log":
            headline = summarize_entry(action, self.staff)
        else:
            headline = summarize_work(action, self.staff)
        detail = [
            f"比對：{compare.get('compare', '未比對')}",
            f"摘要：{headline}",
            "",
        ]
        for row in compare.get("matched", []):
            detail.extend(["系統既有紀錄：", row, ""])
        detail.extend(["原始預演資料：", json.dumps(action, ensure_ascii=False, indent=2)])
        self.detail.insert(tk.END, "\n".join(detail))


def main() -> None:
    app = DutyGui()
    app.mainloop()


if __name__ == "__main__":
    main()
