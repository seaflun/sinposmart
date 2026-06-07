# -*- coding: utf-8 -*-
"""
Tkinter GUI draft for the duty automation workflow.

This GUI is intentionally conservative:
- it can load a rehearsal JSON and show planned work/entry actions;
- each duty member can test-login with their own credentials;
- saved credentials are protected with Windows DPAPI;

- duty records can be submitted manually or when a logged-in task reaches its time.
"""

from __future__ import annotations

import base64
import copy
import json
import os
import re
import ctypes
import msvcrt
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

DAILY_SCREENSHOT_DIR = "每日勤務表"
NIGHT_SCREENSHOT_DIR = "夜間勤務"
RUNTIME_OUTPUT_DIR = Path("runtime_outputs")
SCHEDULE_OUTPUT_DIR = RUNTIME_OUTPUT_DIR / "schedule"
COMPARISON_OUTPUT_DIR = RUNTIME_OUTPUT_DIR / "comparison"
REHEARSAL_OUTPUT_DIR = RUNTIME_OUTPUT_DIR / "rehearsal"
FORM_TEST_OUTPUT_DIR = RUNTIME_OUTPUT_DIR / "form_tests"
SNAPSHOT_OUTPUT_DIR = RUNTIME_OUTPUT_DIR / "snapshots"
CLOUD_LOG_DIR_NAME = "public_computer_logs"
CLOUD_PROJECT_CANDIDATES = (
    Path(os.environ["SINPOSMART_CLOUD_PROJECT_DIR"])
    if os.environ.get("SINPOSMART_CLOUD_PROJECT_DIR")
    else None,
    Path("G:/我的雲端硬碟/專案/值班勤務系統自動化"),
    Path("I:/我的雲端硬碟/專案/值班勤務系統自動化"),
)
AUTO_CLEAN_RULES = (
    (SCHEDULE_OUTPUT_DIR, "*.json", 45),
    (COMPARISON_OUTPUT_DIR, "*.json", 45),
    (REHEARSAL_OUTPUT_DIR, "*.json", 14),
    (FORM_TEST_OUTPUT_DIR, "*.json", 7),
    (SNAPSHOT_OUTPUT_DIR, "*.json", 14),
)

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from daily_vehicle_automation import start_daily_vehicle_automation
from duty_sheet_automation import open_duty_sheet_dialog
from rest_time_automation import open_monthly_base_dialog, open_rest_time_dialog

try:
    import pystray
    from PIL import Image, ImageDraw
except Exception:
    pystray = None
    Image = None
    ImageDraw = None

try:
    from win11toast import toast as win11_toast
except Exception:
    win11_toast = None

try:
    import pythoncom
    import win32crypt
    from win32com.propsys import propsys, pscon
    from win32com.shell import shell
except Exception:
    pythoncom = None
    win32crypt = None
    propsys = None
    pscon = None
    shell = None

from compare_rehearsal_records import (
    build_case_work_audits,
    find_arrival_entry_exists,
    find_entry_matches,
    find_case_work_matches,
    find_work_matches,
    flatten_rows,
    has_open_external_assignment,
    is_future_action,
    is_possible_handoff_adjustment,
    row_has_primary_person,
    row_has_outin,
    row_has_time,
    row_minutes,
    summarize_entry,
    summarize_work,
)
from duty_rehearsal import (
    CaseRecord,
    DEFAULT_WORK_LOG_DEFAULTS,
    ENTRY_LOG_AP,
    OFF_DUTY_SUMMARY_KEYS,
    WORK_LOG_AP,
    fill_entry_log_form_for_test,
    fill_work_log_form_for_test,
    int_setting,
    load_work_log_defaults,
    login,
    parse_roc_date,
    planned_actions,
    query_cases,
    query_duty_sheet,
    query_visible_table,
    roc_date,
    save_work_log_defaults,
    slot_end,
    slot_start,
    unreturned_case_vehicle_items,
    work_handoff_description,
)


APP_USER_MODEL_ID = "TYFD.DutyAutomation"
APP_DISPLAY_NAME = "SinpoSmart"
APP_ICON_PNG = Path(__file__).with_name("duty_tray_icon.png")
APP_ICON_ICO = Path(__file__).with_name("duty_tray_icon.ico")
APP_ICON_GIF = Path(__file__).with_name("duty_tray_icon.gif")
APP_INSTANCE_MUTEX = "Global\\TYFD.SinpoSmart.DutyAutomation"
APP_INSTANCE_LOCK_FILE = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SinpoSmart" / "duty_gui.lock"
APP_COMMAND_HOST = "127.0.0.1"
APP_COMMAND_PORT = 47631
_APP_INSTANCE_MUTEX_HANDLE: int | None = None
_APP_INSTANCE_LOCK_FILE_HANDLE: Any | None = None


# Paths and date helpers

def acquire_single_instance_lock() -> bool:
    global _APP_INSTANCE_MUTEX_HANDLE, _APP_INSTANCE_LOCK_FILE_HANDLE
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.CreateMutexW(None, False, APP_INSTANCE_MUTEX)
        if not handle:
            raise OSError("CreateMutexW returned null")
        last_error = ctypes.get_last_error()
        if last_error == 183:
            kernel32.CloseHandle(handle)
            return False
        _APP_INSTANCE_MUTEX_HANDLE = handle
        return True
    except Exception:
        pass
    try:
        APP_INSTANCE_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        lock_file = APP_INSTANCE_LOCK_FILE.open("a+b")
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        _APP_INSTANCE_LOCK_FILE_HANDLE = lock_file
        return True
    except OSError:
        return False


def signal_existing_instance() -> bool:
    try:
        with socket.create_connection((APP_COMMAND_HOST, APP_COMMAND_PORT), timeout=0.5) as client:
            client.sendall(b"show\n")
        return True
    except OSError:
        return False


def start_single_instance_command_server(app: "DutyGui") -> None:
    def worker() -> None:
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((APP_COMMAND_HOST, APP_COMMAND_PORT))
            server.listen(5)
        except OSError:
            return
        with server:
            while True:
                try:
                    conn, _addr = server.accept()
                except OSError:
                    return
                with conn:
                    try:
                        message = conn.recv(64).decode("utf-8", errors="ignore").strip().lower()
                    except OSError:
                        message = ""
                if message == "show":
                    app.after(0, app.show_from_tray)

    threading.Thread(target=worker, daemon=True).start()


def set_windows_app_user_model_id() -> None:
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass


def ensure_windows_notification_shortcut() -> bool:
    if not all((pythoncom, propsys, pscon, shell)):
        return False
    try:
        shortcut_dir = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        shortcut_dir.mkdir(parents=True, exist_ok=True)
        shortcut_path = shortcut_dir / f"{APP_DISPLAY_NAME}.lnk"
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        target = pythonw if pythonw.exists() else Path(sys.executable)
        entrypoint = Path(__file__).with_name("duty_gui.pyw")
        if not entrypoint.exists():
            entrypoint = Path(__file__)

        pythoncom.CoInitialize()
        shortcut = pythoncom.CoCreateInstance(
            shell.CLSID_ShellLink,
            None,
            pythoncom.CLSCTX_INPROC_SERVER,
            shell.IID_IShellLink,
        )
        shortcut.SetPath(str(target))
        shortcut.SetArguments(f'"{entrypoint}"')
        shortcut.SetWorkingDirectory(str(Path(__file__).parent))
        if APP_ICON_ICO.exists():
            shortcut.SetIconLocation(str(APP_ICON_ICO), 0)
        property_store = shortcut.QueryInterface(propsys.IID_IPropertyStore)
        property_store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(APP_USER_MODEL_ID, pythoncom.VT_LPWSTR))
        property_store.Commit()
        persist_file = shortcut.QueryInterface(pythoncom.IID_IPersistFile)
        persist_file.Save(str(shortcut_path), 0)
        return True
    except Exception:
        return False
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def cloud_runtime_log_root() -> Path | None:
    for candidate in CLOUD_PROJECT_CANDIDATES:
        if candidate and candidate.exists():
            machine = re.sub(r"[^A-Za-z0-9_.-]+", "_", socket.gethostname()) or "unknown"
            return candidate / RUNTIME_OUTPUT_DIR / CLOUD_LOG_DIR_NAME / machine
    return None


def mirror_runtime_file_to_cloud(path: Path, relative_folder: str = "") -> None:
    try:
        cloud_root = cloud_runtime_log_root()
        if not cloud_root or not path.exists():
            return
        target_dir = cloud_root / relative_folder if relative_folder else cloud_root
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / path.name
        target.write_bytes(path.read_bytes())
    except Exception:
        pass


def append_runtime_jsonl_to_cloud(filename: str, line: str) -> None:
    try:
        cloud_root = cloud_runtime_log_root()
        if not cloud_root:
            return
        cloud_root.mkdir(parents=True, exist_ok=True)
        with (cloud_root / filename).open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


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
        list(SCHEDULE_OUTPUT_DIR.glob("schedule_output_*.json"))
        + list(REHEARSAL_OUTPUT_DIR.glob("rehearsal_output_*.json"))
        + list(Path.cwd().glob("schedule_output_*.json"))
        + list(Path.cwd().glob("rehearsal_output_*.json")),
        key=lambda path: path.stat().st_mtime,
    )
    return candidates[-1] if candidates else Path("rehearsal_output_1150517.json")


def today_roc_date() -> str:
    now = datetime.now()
    return f"{now.year - 1911:03d}{now.month:02d}{now.day:02d}"


def duty_business_roc_date(now: datetime | None = None) -> str:
    now = now or datetime.now()
    business_date = now.date() if now.hour >= 8 else now.date() - timedelta(days=1)
    return roc_date(business_date)


def roc_date_after(value: str, days: int) -> str:
    return roc_date(parse_roc_date(value) + timedelta(days=days))


def schedule_path(target_roc_date: str) -> Path:
    return SCHEDULE_OUTPUT_DIR / f"schedule_output_{target_roc_date}.json"


def comparison_path(target_roc_date: str) -> Path:
    return COMPARISON_OUTPUT_DIR / f"comparison_output_{target_roc_date}.json"


def legacy_rehearsal_path(target_roc_date: str) -> Path:
    return REHEARSAL_OUTPUT_DIR / f"rehearsal_output_{target_roc_date}.json"


def cleanup_old_json_files() -> None:
    now = datetime.now()
    for folder, pattern, keep_days in AUTO_CLEAN_RULES:
        if not folder.exists():
            continue
        for old_path in folder.glob(pattern):
            try:
                age = now - datetime.fromtimestamp(old_path.stat().st_mtime)
                if age > timedelta(days=keep_days):
                    old_path.unlink()
            except Exception:
                continue


DEFAULT_PREVIEW = latest_preview_file()
SAVED_LOGIN_PATH = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "DutyAutomation" / "saved_login.json"


def credential_sync_endpoint(value: str) -> str:
    endpoint = str(value or "").strip().rstrip("/")
    if endpoint.endswith("/credential-sync"):
        return endpoint
    return f"{endpoint}/credential-sync"


def duty_window_dates(base_roc_date: str) -> list[str]:
    return [roc_date_after(base_roc_date, -1), base_roc_date, roc_date_after(base_roc_date, 1)]


# Session model

@dataclass
class LoginSession:
    actor_no: str
    user_id: str
    password: str
    verified: bool = False


# Main GUI controller

class DutyGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_DISPLAY_NAME} - 值班模式")
        self.apply_window_icon(self)
        self.geometry("440x720")
        self.minsize(420, 700)

        self.preview_path = tk.StringVar(value=str(DEFAULT_PREVIEW))
        self.audit_date = tk.StringVar(value=today_roc_date())
        self.actor_no = tk.StringVar()
        self.user_id = tk.StringVar()
        self.password = tk.StringVar()
        self.saved_account_choice = tk.StringVar()
        self.remember_login = tk.BooleanVar(value=True)
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
        self.duty_status_override_text = ""
        self.duty_status_override_until: datetime | None = None
        self.summary_vars = {
            "todo": tk.StringVar(value="未找到 0"),
            "review": tk.StringVar(value="人工確認 0"),
            "ready": tk.StringVar(value="尚未到點 0"),
            "done": tk.StringVar(value="已存在 0"),
        }

        self.staff: dict[str, dict[str, str]] = {}
        self.actions: list[dict[str, Any]] = []
        self.data: dict[str, Any] = {}
        self.action_compare: dict[int, dict[str, Any]] = {}
        self.duty_staff: dict[str, dict[str, str]] = {}
        self.duty_actions: list[dict[str, Any]] = []
        self.duty_data: dict[str, Any] = {}
        self.duty_action_compare: dict[int, dict[str, Any]] = {}
        self.session: LoginSession | None = None
        self.executed_due: set[int] = set()
        self.manual_completed_keys: set[str] = set()
        self.paused_due_indices: dict[int, str] = {}
        self.failed_due_retry_after: dict[int, datetime] = {}
        self.submitting_indices: set[int] = set()
        self.submit_queues: dict[str, list[tuple[int, dict[str, Any], bool, bool, bool, str]]] = {"entry": [], "work": []}
        self.submit_worker_running: dict[str, bool] = {"entry": False, "work": False}
        self.work_submit_parallel_enabled = True
        self.submit_needs_comparison_refresh = False
        self.submit_comparison_refresh_dates: set[str] = set()
        self.submit_comparison_refresh_scheduled = False
        self.duty_selection_anchor = ""
        self.saved_accounts: list[dict[str, str]] = []
        self.work_log_defaults = load_work_log_defaults()
        self.review_widgets: list[tk.Widget] = []
        self.duty_widgets: list[tk.Widget] = []
        self.login_form_widgets: list[tk.Widget] = []
        self.logout_widgets: list[tk.Widget] = []
        self.audit_bottom_frame: ttk.Frame | None = None
        self.snapshot_running = False
        self.snapshot_completed_slots: set[str] = set()
        self.comparison_running = False
        self.comparison_completed_hours: set[str] = set()
        self.pending_hourly_comparison: tuple[str, str, list[str], str, str] | None = None
        self.logout_cleared = False
        self.auto_logout_after_id: str | None = None
        self.auto_logout_deadline: datetime | None = None
        self.auto_logout_actor_no = ""
        self.saved_login_needs_backup = False
        self.login_running = False
        self.login_attempt_id = 0
        self.tray_icon: Any | None = None
        self.tray_available = bool(pystray and Image and ImageDraw)
        self.notification_id = 9100
        self.last_notification_signature = ""
        self.last_notification_at: datetime | None = None
        self.opened_screenshot_folder_slots: set[str] = set()

        cleanup_old_json_files()
        self.load_saved_login()
        self._build_layout()
        self.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        self.refresh_saved_account_choices()
        self.after(500, self.ensure_startup_tray_icon)
        self.after(1000, self.tick_clock)
        self.after(15000, self.check_scheduled_snapshot)
        self.after(60000, self.check_hourly_comparison)

    # Layout construction

    def _build_layout(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#f4f7fb")
        style.configure("TLabelframe", background="#f4f7fb", bordercolor="#d5dde8")
        style.configure("TLabelframe.Label", background="#f4f7fb", foreground="#22324a", font=("Microsoft JhengHei", 10, "bold"))
        style.configure("TLabel", background="#f4f7fb", foreground="#233044", font=("Microsoft JhengHei", 10))
        style.configure("Login.TFrame", background="#ffffff")
        style.configure("Login.TRadiobutton", background="#ffffff", foreground="#334155", font=("Microsoft JhengHei", 10))
        style.configure("TButton", font=("Microsoft JhengHei", 10), padding=(10, 5))
        style.configure("Accent.TButton", background="#2563eb", foreground="#ffffff")
        style.map("Accent.TButton", background=[("active", "#1d4ed8")])
        style.configure("Soft.TButton", background="#eef2ff", foreground="#243b75")
        style.configure("AuditNav.TButton", background="#dbeafe", foreground="#1d4ed8", padding=(8, 2), bordercolor="#bfdbfe")
        style.map("AuditNav.TButton", background=[("active", "#bfdbfe")], foreground=[("active", "#1e3a8a")])
        style.configure("AuditAction.TButton", background="#2563eb", foreground="#ffffff", padding=(10, 2), bordercolor="#1d4ed8")
        style.map("AuditAction.TButton", background=[("active", "#1d4ed8")], foreground=[("active", "#ffffff")])
        style.configure("AuditMode.TButton", background="#e2e8f0", foreground="#334155", padding=(10, 3), bordercolor="#cbd5e1")
        style.map("AuditMode.TButton", background=[("active", "#cbd5e1")], foreground=[("active", "#0f172a")])
        style.configure("DailyTool.TButton", background="#dbeafe", foreground="#1e3a8a", padding=(10, 5), bordercolor="#93c5fd")
        style.map("DailyTool.TButton", background=[("active", "#bfdbfe")], foreground=[("active", "#1e40af")])
        style.configure("MonthlyTool.TButton", background="#fee2e2", foreground="#991b1b", padding=(10, 5), bordercolor="#fca5a5")
        style.map("MonthlyTool.TButton", background=[("active", "#fecaca")], foreground=[("active", "#7f1d1d")])
        style.configure("AuditDate.TCombobox", padding=(6, 2), fieldbackground="#ffffff", background="#ffffff", foreground="#1e3a8a", arrowcolor="#1d4ed8", bordercolor="#bfdbfe")
        style.map("AuditDate.TCombobox", fieldbackground=[("readonly", "#ffffff")], foreground=[("readonly", "#1e3a8a")], selectbackground=[("readonly", "#ffffff")], selectforeground=[("readonly", "#1e3a8a")], background=[("readonly", "#ffffff")], arrowcolor=[("readonly", "#1d4ed8")])
        style.configure("LoginCombo.TCombobox", padding=(4, 4), fieldbackground="#ffffff", background="#ffffff", foreground="#0f172a", arrowcolor="#334155", bordercolor="#cbd5e1")
        style.map("LoginCombo.TCombobox", fieldbackground=[("readonly", "#ffffff")], foreground=[("readonly", "#0f172a")], selectbackground=[("readonly", "#ffffff")], selectforeground=[("readonly", "#0f172a")], background=[("readonly", "#ffffff")], arrowcolor=[("readonly", "#334155")])
        style.configure("Login.TEntry", padding=(4, 3))
        style.configure("PanelTool.TButton", background="#ffffff", foreground="#334155", padding=(10, 4), bordercolor="#cbd5e1")
        style.map("PanelTool.TButton", background=[("active", "#f8fafc")], foreground=[("active", "#0f172a")])
        style.configure("DangerTool.TButton", background="#ffffff", foreground="#b91c1c", padding=(8, 3), bordercolor="#fecaca")
        style.map("DangerTool.TButton", background=[("active", "#fef2f2")], foreground=[("active", "#991b1b")])
        style.configure("AuditValue.TLabel", background="#f4f7fb", foreground="#1e3a8a", font=("Microsoft JhengHei", 10, "bold"))
        style.configure("AuditCaption.TLabel", background="#f4f7fb", foreground="#64748b", font=("Microsoft JhengHei", 9))
        style.configure("Treeview", rowheight=30, font=("Microsoft JhengHei", 10), background="#ffffff", fieldbackground="#ffffff")
        style.configure("Treeview.Heading", font=("Microsoft JhengHei", 10, "bold"), background="#e8eef7", foreground="#1e2b3f")

        root = ttk.Frame(self, padding=14)
        root.pack(fill=tk.BOTH, expand=True)

        top = ttk.LabelFrame(root, text="預演資料", padding=10)
        top.pack(fill=tk.X)
        self.top_frame = top
        self.review_widgets.append(top)
        ttk.Label(top, text="預演 JSON").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(top, textvariable=self.preview_path, width=36).grid(row=0, column=1, sticky=tk.W, padx=8)
        ttk.Button(top, text="選擇", command=self.choose_preview).grid(row=0, column=2, padx=4)
        ttk.Button(top, text="載入", command=lambda: self.load_preview(Path(self.preview_path.get()))).grid(row=0, column=3)
        top.columnconfigure(1, weight=0)

        login_box = ttk.LabelFrame(root, text="目前值班人員登入", padding=10)
        login_box.pack(fill=tk.X, pady=(10, 0))
        self.login_box = login_box
        self.review_widgets.append(login_box)
        ttk.Label(login_box, text="番號").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(login_box, textvariable=self.actor_no, width=8).grid(row=0, column=1, sticky=tk.W, padx=(6, 12))
        ttk.Label(login_box, text="帳號").grid(row=0, column=2, sticky=tk.W)
        self.review_user_entry = ttk.Entry(login_box, textvariable=self.user_id, width=22, style="Login.TEntry")
        self.review_user_entry.grid(row=0, column=3, sticky=tk.W, padx=(6, 8))
        self.review_user_entry.bind("<Tab>", self.focus_review_password_from_user)
        self.review_user_entry.bind("<Return>", self.submit_login_from_entry)
        self.review_manage_account_button = ttk.Button(login_box, text="帳號選擇", width=11, style="PanelTool.TButton", command=self.manage_saved_accounts, takefocus=False)
        self.review_manage_account_button.grid(row=0, column=4, padx=(0, 12))
        ttk.Label(login_box, text="密碼").grid(row=0, column=5, sticky=tk.W)
        self.review_password_entry = ttk.Entry(login_box, textvariable=self.password, width=22, show="*", style="Login.TEntry")
        self.review_password_entry.grid(row=0, column=6, sticky=tk.W, padx=(6, 0))
        self.review_password_entry.bind("<Return>", self.submit_login_from_entry)
        tk.Checkbutton(
            login_box,
            text="記住帳號密碼",
            variable=self.remember_login,
            bg="#f4f7fb",
            activebackground="#f4f7fb",
            fg="#1e3a8a",
            activeforeground="#1e3a8a",
            selectcolor="#ffffff",
            font=("Microsoft JhengHei", 9, "bold"),
            width=11,
        ).grid(row=0, column=7, sticky=tk.W, padx=(12, 0))
        self.review_login_button = ttk.Button(login_box, text="測試登入", style="Accent.TButton", command=self.verify_login)
        self.review_login_button.grid(row=0, column=8, padx=(12, 0))
        self.review_secondary_row = ttk.Frame(login_box)
        self.review_secondary_row.grid(row=1, column=0, columnspan=9, sticky=tk.W, pady=(8, 0))
        ttk.Button(self.review_secondary_row, text="縮小", command=self.iconify).pack(side=tk.LEFT)
        ttk.Button(self.review_secondary_row, text="登出/清除", command=self.clear_login).pack(side=tk.LEFT, padx=(8, 0))
        self.review_tertiary_row = ttk.Frame(login_box)
        self.review_tertiary_row.grid(row=2, column=0, columnspan=9, sticky=tk.W, pady=(6, 0))
        ttk.Button(self.review_tertiary_row, text="查看此人任務", command=self.show_actor_tasks).pack(side=tk.LEFT)
        ttk.Label(login_box, textvariable=self.login_status, foreground="#1f5f3f").grid(row=3, column=0, columnspan=9, sticky=tk.W, pady=(8, 0))

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
            card.grid(row=0, column=idx, sticky=tk.EW, padx=(0 if idx == 0 else 6, 0))
            tk.Label(card, textvariable=self.summary_vars[key], bg=bg, fg=fg, font=("Microsoft JhengHei", 12, "bold"), pady=8).pack(fill=tk.X)
            summary.columnconfigure(idx, weight=1)

        tools = ttk.Frame(root)
        tools.pack(fill=tk.X, pady=(10, 0))
        self.tools_frame = tools
        self.review_widgets.append(tools)
        tools.columnconfigure(0, weight=1)
        tools.columnconfigure(1, weight=1)

        date_card = tk.Frame(tools, bg="#eff6ff", highlightbackground="#bfdbfe", highlightthickness=1)
        date_card.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 5))
        tk.Label(date_card, text="日期切換", bg="#eff6ff", fg="#1e3a8a", font=("Microsoft JhengHei", 10, "bold")).grid(row=0, column=0, columnspan=4, sticky=tk.W, padx=12, pady=(10, 2))
        tk.Label(date_card, text="勤務日期", bg="#eff6ff", fg="#475569", font=("Microsoft JhengHei", 9)).grid(row=1, column=0, sticky=tk.W, padx=12, pady=(0, 2))
        self.audit_date_combo = ttk.Combobox(date_card, textvariable=self.audit_date, values=self.available_audit_dates(), width=8, state="readonly", style="AuditDate.TCombobox")
        self.audit_date_combo.grid(row=2, column=0, sticky=tk.W, padx=12, pady=(0, 10))
        self.audit_date_combo.bind("<<ComboboxSelected>>", lambda _event: self.load_audit_date())
        ttk.Button(date_card, text="◀", width=3, style="AuditNav.TButton", command=lambda: self.shift_audit_date(-1)).grid(row=2, column=1, padx=(4, 2), pady=(0, 10))
        ttk.Button(date_card, text="▶", width=3, style="AuditNav.TButton", command=lambda: self.shift_audit_date(1)).grid(row=2, column=2, padx=2, pady=(0, 10))
        self.refresh_compare_button = ttk.Button(date_card, text="重新查詢", style="AuditAction.TButton", command=self.refresh_current_comparison)
        self.refresh_compare_button.grid(row=2, column=3, sticky=tk.E, padx=(8, 12), pady=(0, 10))
        date_card.columnconfigure(3, weight=1)

        filter_card = tk.Frame(tools, bg="#eff6ff", highlightbackground="#bfdbfe", highlightthickness=1)
        filter_card.grid(row=0, column=1, sticky=tk.NSEW, padx=(5, 0))
        tk.Label(filter_card, text="篩選條件", bg="#eff6ff", fg="#1e3a8a", font=("Microsoft JhengHei", 10, "bold")).grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=12, pady=(10, 2))
        ttk.Label(filter_card, text="狀態", style="AuditCaption.TLabel").grid(row=1, column=0, sticky=tk.W, padx=12, pady=(0, 2))
        ttk.Label(filter_card, text="類型", style="AuditCaption.TLabel").grid(row=1, column=1, sticky=tk.W, padx=(8, 12), pady=(0, 2))
        ttk.Combobox(
            filter_card,
            textvariable=self.status_filter,
            values=("需處理", "全部", "已存在", "手動", "尚未到點", "可能臨時調整", "時間近似", "人工確認"),
            width=13,
            state="readonly",
            style="AuditDate.TCombobox",
        ).grid(row=2, column=0, sticky=tk.EW, padx=12, pady=(0, 10))
        ttk.Combobox(
            filter_card,
            textvariable=self.kind_filter,
            values=("全部", "工作", "出入", "案件工作"),
            width=10,
            state="readonly",
            style="AuditDate.TCombobox",
        ).grid(row=2, column=1, sticky=tk.EW, padx=(8, 12), pady=(0, 10))
        filter_card.columnconfigure(0, weight=1)
        filter_card.columnconfigure(1, weight=1)
        self.status_filter.trace_add("write", lambda *_: self.refresh_tasks())
        self.kind_filter.trace_add("write", lambda *_: self.refresh_tasks())

        self.audit_bottom_frame = ttk.Frame(root)
        audit_bottom_left = ttk.Frame(self.audit_bottom_frame)
        audit_bottom_left.pack(side=tk.LEFT)
        audit_bottom_right = ttk.Frame(self.audit_bottom_frame)
        audit_bottom_right.pack(side=tk.RIGHT, fill=tk.X, expand=True)
        ttk.Button(audit_bottom_left, text="值班模式", style="AuditMode.TButton", command=lambda: self.switch_mode("值班模式")).pack(side=tk.LEFT)
        ttk.Button(audit_bottom_left, text="檢查更新", style="AuditMode.TButton", command=self.check_for_update).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(audit_bottom_left, text="匯出問題包", style="AuditMode.TButton", command=self.export_issue_package).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(audit_bottom_left, text="同步到另一台", style="AuditMode.TButton", command=self.sync_current_account_dialog).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(audit_bottom_right, textvariable=self.status_text, style="AuditValue.TLabel", anchor="e", justify=tk.RIGHT).pack(side=tk.RIGHT)

        columns = (
            "compare",
            "execute_time",
            "actor",
            "target",
            "kind",
            "summary",
        )
        self.tree = ttk.Treeview(root, columns=columns, show="headings", height=22)
        headings = {
            "compare": "比對",
            "execute_time": "登打時間",
            "actor": "登打人",
            "target": "對象/服勤",
            "kind": "類型",
            "summary": "內容",
        }
        widths = {
            "compare": 84,
            "execute_time": 92,
            "actor": 64,
            "target": 120,
            "kind": 90,
            "summary": 288,
        }
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], minwidth=widths[col], stretch=col in ("compare", "target", "summary"), anchor=tk.W)
        self.tree.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.review_widgets.append(self.tree)
        self.tree.tag_configure("todo", background="#fff1f2", foreground="#7f1d1d")
        self.tree.tag_configure("review", background="#fff7ed", foreground="#7c2d12")
        self.tree.tag_configure("near", background="#fefce8", foreground="#713f12")
        self.tree.tag_configure("done", background="#ecfdf5", foreground="#14532d")
        self.tree.tag_configure("ready", background="#eff6ff", foreground="#1e3a8a")
        self.tree.tag_configure("future", background="#f8fafc", foreground="#475569")
        self.tree.tag_configure("adjust", background="#eef2ff", foreground="#3730a3")
        self.tree.tag_configure("manual", background="#fff7ed", foreground="#7c2d12")

        scrollbar = ttk.Scrollbar(self.tree, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        bottom = ttk.LabelFrame(root, text="選取項目明細", padding=10)
        bottom.pack(fill=tk.BOTH, pady=(10, 0))
        self.bottom_frame = bottom
        self.review_widgets.append(bottom)
        self.detail = tk.Text(bottom, height=8, wrap=tk.WORD)
        self.detail.configure(font=("Microsoft JhengHei", 10), bg="#ffffff", relief=tk.FLAT, padx=10, pady=8)
        self.detail.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.show_selected_detail)
        self.build_duty_panel(root)
        self.apply_mode()

    def build_duty_panel(self, root: ttk.Frame) -> None:
        panel = ttk.Frame(root)
        self.duty_widgets.append(panel)

        time_panel = tk.Frame(panel, bg="#0f172a", highlightbackground="#bfdbfe", highlightthickness=1)
        time_panel.pack(fill=tk.X)
        tk.Label(time_panel, textvariable=self.date_text, bg="#0f172a", fg="#cbd5e1", font=("Microsoft JhengHei", 12, "bold")).pack(anchor=tk.CENTER, pady=(6, 0))
        tk.Label(time_panel, textvariable=self.time_text, bg="#0f172a", fg="#ffffff", font=("Microsoft JhengHei", 26, "bold")).pack(anchor=tk.CENTER, pady=(0, 6))

        login_card = tk.Frame(panel, bg="#eff6ff", highlightbackground="#bfdbfe", highlightthickness=1)
        login_card.pack(fill=tk.X, pady=(10, 0))
        login_panel = tk.Frame(login_card, bg="#eff6ff")
        login_panel.pack(fill=tk.BOTH, expand=True, padx=14, pady=12)
        duty_header = tk.Frame(login_panel, bg="#eff6ff")
        duty_header.pack(fill=tk.X)
        tk.Label(duty_header, text="消防勤務管理系統", bg="#eff6ff", fg="#1e3a8a", font=("Microsoft JhengHei", 12, "bold")).pack(side=tk.LEFT)
        self.work_log_settings_button = ttk.Button(duty_header, text="⚙", width=3, style="PanelTool.TButton", command=self.open_work_log_defaults_dialog, takefocus=False)
        self.work_log_settings_button.pack(side=tk.RIGHT)
        self.work_log_settings_button.pack_forget()
        self.credentials_grid = tk.Frame(login_panel, bg="#eff6ff")
        self.credentials_grid.pack(fill=tk.X, pady=(8, 0))
        self.credentials_grid.columnconfigure(0, weight=1)
        self.credentials_grid.columnconfigure(1, minsize=156)
        self.user_label = tk.Label(self.credentials_grid, text="帳號", bg="#eff6ff", fg="#64748b", font=("Microsoft JhengHei", 9))
        self.user_label.grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 2))
        self.account_row = self.credentials_grid
        self.user_entry = ttk.Entry(self.credentials_grid, textvariable=self.user_id, width=20, style="Login.TEntry")
        self.user_entry.grid(row=1, column=0, sticky=tk.EW)
        self.account_action_frame = tk.Frame(self.credentials_grid, bg="#eff6ff", width=156)
        self.account_action_frame.grid(row=1, column=1, padx=(8, 0), sticky=tk.EW)
        self.account_action_frame.grid_propagate(False)
        self.manage_account_button = ttk.Button(self.account_action_frame, text="帳號選擇", width=11, style="PanelTool.TButton", command=self.manage_saved_accounts, takefocus=False)
        self.manage_account_button.pack(fill=tk.X)
        self.password_label = tk.Label(self.credentials_grid, text="密碼", bg="#eff6ff", fg="#64748b", font=("Microsoft JhengHei", 9))
        self.password_label.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(8, 2))
        self.password_row = self.credentials_grid
        self.password_entry = ttk.Entry(self.credentials_grid, textvariable=self.password, width=20, show="*", style="Login.TEntry")
        self.password_entry.grid(row=3, column=0, sticky=tk.EW)
        self.user_entry.bind("<Tab>", self.focus_password_from_user)
        self.user_entry.bind("<Return>", self.submit_login_from_entry)
        self.password_entry.bind("<Return>", self.submit_login_from_entry)
        self.password_action_frame = tk.Frame(self.credentials_grid, bg="#eff6ff", width=156)
        self.password_action_frame.grid(row=3, column=1, padx=(8, 0), sticky=tk.EW)
        self.password_action_frame.grid_propagate(False)
        self.remember_login_check = tk.Checkbutton(
            self.password_action_frame,
            text="記住帳號密碼",
            variable=self.remember_login,
            bg="#eff6ff",
            activebackground="#eff6ff",
            fg="#1e3a8a",
            activeforeground="#1e3a8a",
            selectcolor="#ffffff",
            font=("Microsoft JhengHei", 9, "bold"),
        )
        self.remember_login_check.pack(anchor=tk.W)
        self.login_form_widgets.extend([
            self.credentials_grid,
        ])

        self.button_row = tk.Frame(login_panel, bg="#eff6ff")
        self.button_row.pack(fill=tk.X, pady=(12, 0))
        self.login_button = ttk.Button(self.button_row, text="登入", style="Accent.TButton", command=self.verify_login)
        self.login_button.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.logout_button = ttk.Button(self.button_row, text="登出", style="Soft.TButton", command=self.clear_login)
        self.logout_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))
        self.login_form_widgets.append(self.login_button)
        self.logout_widgets.append(self.logout_button)
        self.login_status_label = tk.Label(login_panel, textvariable=self.login_status, bg="#eff6ff", fg="#166534", font=("Microsoft JhengHei", 9), wraplength=360, justify=tk.LEFT)
        self.login_status_label.pack(anchor=tk.W, pady=(8, 0))

        tools_card = tk.Frame(panel, bg="#eff6ff", highlightbackground="#bfdbfe", highlightthickness=1)
        tools_card.pack(fill=tk.X, pady=(10, 0))
        self.duty_sheet_tools_card = tools_card
        tools_panel = tk.Frame(tools_card, bg="#eff6ff")
        tools_panel.pack(fill=tk.X, padx=10, pady=10)
        tools_panel.columnconfigure(0, minsize=64)
        tools_panel.columnconfigure(1, weight=1, uniform="duty_tools")
        tools_panel.columnconfigure(2, weight=1, uniform="duty_tools")
        tk.Label(tools_panel, text="每日作業", bg="#eff6ff", fg="#1e3a8a", font=("Microsoft JhengHei", 9, "bold")).grid(row=0, column=0, sticky=tk.W, padx=(0, 8))
        self.duty_sheet_button = ttk.Button(tools_panel, text="勤務表登打", style="DailyTool.TButton", command=self.open_duty_sheet_automation)
        self.duty_sheet_button.grid(row=0, column=1, sticky=tk.EW, pady=(0, 8), padx=(0, 4))
        self.daily_vehicle_button = ttk.Button(tools_panel, text="車輛保養清點", style="DailyTool.TButton", command=self.open_daily_vehicle_automation)
        self.daily_vehicle_button.grid(row=0, column=2, sticky=tk.EW, pady=(0, 8), padx=(4, 0))
        tk.Label(tools_panel, text="每月作業", bg="#eff6ff", fg="#991b1b", font=("Microsoft JhengHei", 9, "bold")).grid(row=1, column=0, sticky=tk.W, padx=(0, 8))
        self.rest_time_button = ttk.Button(tools_panel, text="休息時間登打", style="MonthlyTool.TButton", command=self.open_rest_time_automation)
        self.rest_time_button.grid(row=1, column=1, sticky=tk.EW, padx=(0, 4))
        self.monthly_base_button = ttk.Button(tools_panel, text="勤務基準表登打", style="MonthlyTool.TButton", command=self.open_monthly_base_automation)
        self.monthly_base_button.grid(row=1, column=2, sticky=tk.EW, padx=(4, 0))

        controls = ttk.Frame(panel)
        controls.pack(fill=tk.X, pady=(10, 0), side=tk.BOTTOM)
        self.duty_controls = controls
        controls_left = ttk.Frame(controls)
        controls_left.pack(side=tk.LEFT)
        controls_right = ttk.Frame(controls)
        controls_right.pack(side=tk.RIGHT, fill=tk.X, expand=True)
        self.audit_mode_button = ttk.Button(controls_left, text="審核模式", style="AuditMode.TButton", command=lambda: self.switch_mode("審核模式"))
        self.audit_mode_button.pack(side=tk.LEFT)
        self.early_submit_button = ttk.Button(controls_right, text="手動登打", style="Accent.TButton", command=self.save_selected_work_log_test)
        self.early_submit_button.pack(side=tk.RIGHT)

        columns = ("time", "summary", "status")
        self.duty_tree = ttk.Treeview(panel, columns=columns, show="headings", height=12, selectmode="extended")
        headings = {
            "time": "時間",
            "summary": "當班任務",
            "status": "狀態",
        }
        widths = {"time": 96, "summary": 216, "status": 82}
        for col in columns:
            self.duty_tree.heading(col, text=headings[col])
            self.duty_tree.column(col, width=widths[col], anchor=tk.W)
        self.duty_tree.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        self.duty_tree.tag_configure("ready", background="#eff6ff", foreground="#1e3a8a")
        self.duty_tree.tag_configure("waiting", background="#ffffff", foreground="#334155")
        self.duty_tree.tag_configure("triggered", background="#ecfdf5", foreground="#14532d")
        self.duty_tree.tag_configure("manual", background="#fff7ed", foreground="#9a3412")
        self.duty_tree.bind("<Button-1>", self.handle_duty_tree_click, add="+")

        self.update_login_panel()

    # Review data loading and date controls

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
        max_value = roc_date_after(today_roc_date(), 1)
        paths = list(Path.cwd().glob("schedule_output_*.json")) + list(Path.cwd().glob("rehearsal_output_*.json"))
        for path in sorted(paths):
            value = path.stem.rsplit("_", 1)[-1]
            if len(value) == 7 and value.isdigit() and value <= max_value:
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
        shifted_value = f"{shifted.year - 1911:03d}{shifted.month:02d}{shifted.day:02d}"
        self.audit_date.set(min(shifted_value, roc_date_after(today_roc_date(), 1)))
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
            ttk.Label(header, text=f"{month_date.year}/{month_date.month:02d}", font=("Microsoft JhengHei", 11, "bold")).pack(side=tk.LEFT, expand=True)
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
                state = tk.NORMAL if roc <= roc_date_after(today_roc_date(), 1) else tk.DISABLED
                ttk.Button(container, text=str(day_no), width=4, state=state, command=lambda value=roc: choose(value)).grid(row=row, column=col, padx=2, pady=2)

        def choose(value: str) -> None:
            if value > roc_date_after(today_roc_date(), 1):
                return
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
        ttk.Label(frame, text="登入勤務自動化", font=("Microsoft JhengHei", 15, "bold")).pack(anchor=tk.W)

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

    def focus_password_from_user(self, _event: tk.Event) -> str:
        self.password_entry.focus_set()
        self.password_entry.icursor(tk.END)
        return "break"

    def focus_review_password_from_user(self, _event: tk.Event) -> str:
        self.review_password_entry.focus_set()
        self.review_password_entry.icursor(tk.END)
        return "break"

    def submit_login_from_entry(self, _event: tk.Event) -> str:
        self.verify_login()
        return "break"

    def apply_window_icon(self, window: tk.Tk | tk.Toplevel) -> None:
        try:
            if APP_ICON_ICO.exists():
                window.iconbitmap(default=str(APP_ICON_ICO))
        except Exception:
            pass
        for icon_path in (APP_ICON_PNG, APP_ICON_GIF):
            if not icon_path.exists():
                continue
            try:
                photo = tk.PhotoImage(file=str(icon_path))
                window.iconphoto(True, photo)
                window._duty_icon_photo = photo
                return
            except Exception:
                continue

    def hide_to_tray(self) -> None:
        try:
            has_tray = self.ensure_tray_icon()
        except Exception:
            has_tray = False
        if has_tray:
            self.withdraw()
            return
        self.iconify()

    def ensure_startup_tray_icon(self) -> None:
        self.ensure_tray_icon()

    def ensure_tray_icon(self) -> bool:
        if not self.tray_available:
            return False
        if self.tray_icon:
            try:
                if hasattr(self.tray_icon, "visible") and not self.tray_icon.visible:
                    self.tray_icon.visible = True
            except Exception:
                pass
            return True
        image = self.build_tray_image()
        self.tray_icon = pystray.Icon(
            "duty_automation",
            image,
            APP_DISPLAY_NAME,
            pystray.Menu(
                pystray.MenuItem(APP_DISPLAY_NAME, lambda _icon, _item: None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("顯示控制台", lambda _icon, _item: self.after(0, self.show_from_tray), default=True),
                pystray.MenuItem("縮小到背景", lambda _icon, _item: self.after(0, self.hide_to_tray)),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("結束程式", lambda _icon, _item: self.after(0, self.quit_from_tray)),
            ),
        )
        self.tray_icon.run_detached()
        return True

    def build_tray_image(self) -> Any:
        for icon_path in (APP_ICON_PNG, APP_ICON_GIF, APP_ICON_ICO):
            if icon_path.exists():
                return Image.open(icon_path).convert("RGBA")
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((6, 6, 58, 58), radius=14, fill="#0f172a")
        draw.rounded_rectangle((13, 13, 51, 51), radius=10, fill="#2563eb")
        draw.ellipse((43, 7, 59, 23), fill="#22c55e")
        draw.text((23, 18), "勤", fill="#ffffff")
        return image

    def show_from_tray(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()

    def quit_from_tray(self) -> None:
        if self.tray_icon:
            self.tray_icon.stop()
            self.tray_icon = None
        self.destroy()

    def show_toast(self, title: str, message: str, duration_ms: int = 4500) -> None:
        toast = tk.Toplevel(self)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        toast.configure(bg="#dbeafe")
        frame = ttk.Frame(toast, style="Panel.TFrame", padding=(14, 10, 14, 10))
        frame.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        ttk.Label(frame, text=title, style="CardTitle.TLabel").pack(anchor=tk.W)
        ttk.Label(frame, text=message, style="Muted.TLabel", wraplength=300, justify=tk.LEFT).pack(anchor=tk.W, pady=(4, 0))
        toast.update_idletasks()
        width = max(280, toast.winfo_width())
        height = toast.winfo_height()
        if self.state() == "withdrawn":
            x = self.winfo_screenwidth() - width - 24
            y = 64
        else:
            x = self.winfo_rootx() + max(16, self.winfo_width() - width - 16)
            y = self.winfo_rooty() + 16
        toast.geometry(f"{width}x{height}+{x}+{y}")
        toast.lift()
        toast.after(50, lambda: toast.attributes("-topmost", True))
        toast.after(80, toast.lift)
        toast.after(duration_ms, toast.destroy)

    def show_windows_notification(self, title: str, message: str) -> bool:
        if win11_toast is None:
            return False
        try:
            set_windows_app_user_model_id()
            ensure_windows_notification_shortcut()
            threading.Thread(
                target=lambda: win11_toast(
                    title,
                    message,
                    app_id=APP_USER_MODEL_ID,
                    on_click=lambda _args=None: None,
                    on_dismissed=lambda _reason=None: None,
                    on_failed=lambda _error=None: None,
                ),
                daemon=True,
            ).start()
            return True
        except Exception:
            return False

    def notify_user(self, title: str, message: str, duration_ms: int = 4500) -> None:
        signature = f"{title}\n{message}"
        now = datetime.now()
        if (
            signature == self.last_notification_signature
            and self.last_notification_at is not None
            and (now - self.last_notification_at).total_seconds() <= 8
        ):
            return
        self.last_notification_signature = signature
        self.last_notification_at = now
        if self.show_windows_notification(title, message):
            return
        self.show_toast(title, message, duration_ms=duration_ms)

    def switch_mode(self, mode: str) -> None:
        self.mode.set(mode)
        self.simple_mode.set(mode == "值班模式")
        self.apply_mode()

    def load_preview(self, path: Path, update_duty: bool = True) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            messagebox.showerror("載入失敗", str(exc))
            return

        self.sanitize_schedule_data(data)
        today_staff = data.get("today", {}).get("staff", {})
        yesterday_staff = data.get("yesterday", {}).get("staff", {})
        self.data = data
        self.staff = {**yesterday_staff, **today_staff}
        self.actions = self.build_audit_actions(data)
        self.action_compare = self.build_comparison(data)
        if update_duty:
            self.duty_data = data
            self.duty_staff = self.staff
            self.duty_actions = data.get("actions", [])
            self.manual_completed_keys = self.restore_manual_completed_keys(data.get("target_date", ""), self.duty_actions)
            self.duty_action_compare = self.apply_manual_completed_overrides(self.build_comparison(data, self.duty_actions), self.duty_actions)
            self.sync_session_actor_from_user_id()
        compare_note = "，已套用比對檔" if comparison_path(data.get("target_date", "")).exists() else ""
        self.status_text.set(f"已載入 {path.name}，任務 {len(self.actions)} 筆{compare_note}。")
        if hasattr(self, "audit_date_combo"):
            self.audit_date_combo.configure(values=self.available_audit_dates())
        self.refresh_tasks()
        self.refresh_duty_tasks()

    def sanitize_schedule_data(self, data: dict[str, Any]) -> None:
        for sheet_key in ("yesterday", "today", "tomorrow"):
            sheet = data.get(sheet_key, {})
            for row in sheet.get("rows", []):
                row.get("columns", {}).pop("檢核欄", None)
            summary = sheet.get("summary", {})
            off_duty = set()
            for key in OFF_DUTY_SUMMARY_KEYS:
                off_duty.update(str(no) for no in summary.get(key, []))
            if off_duty and "在勤" in summary:
                summary["在勤"] = [str(no) for no in summary["在勤"] if str(no) not in off_duty]
        for action in data.get("actions", []):
            fields = action.get("fields", {})
            if action.get("kind") == "entry_log" and action.get("source") == "休息結束":
                if fields.get("領用事由及地點") == "返隊":
                    fields["領用事由及地點"] = "休息返隊"
                duplicate_key = str(action.get("duplicate_key", ""))
                if duplicate_key.endswith(":返隊"):
                    action["duplicate_key"] = duplicate_key[:-3] + "休息返隊"

    def build_audit_actions(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        return data.get("actions", []) + build_case_work_audits(data)

    def rest_entry_matches(
        self,
        entry_rows: list[str],
        action_date: str,
        action: dict[str, Any],
        allow_near: bool,
        staff: dict[str, dict[str, str]] | None = None,
    ) -> list[str]:
        fields = action.get("fields", {})
        reason = fields.get("領用事由及地點", "")
        outin = fields.get("出或入", "")
        system_time = fields.get("系統寫入時間", action.get("time", ""))
        try:
            hour, minute = [int(part) for part in system_time.split(":", 1)]
            if hour >= 24:
                system_time = f"{hour % 24:02d}:{minute:02d}"
        except ValueError:
            pass
        staff = staff if staff is not None else self.staff
        target_name = staff.get(str(action.get("target", "")), {}).get("name", "")
        acceptable_reasons = ("休息返隊", "返隊") if reason == "休息返隊" else (reason,)
        matches = []
        for row in entry_rows:
            if target_name and target_name not in row:
                continue
            if outin and outin not in row:
                continue
            if reason and not any(value in row for value in acceptable_reasons):
                continue
            if not row_has_time(row, action_date, system_time, allow_near=allow_near, near_minutes=120):
                continue
            matches.append(row)
        return matches

    def compare_rest_entry(
        self,
        actions: list[dict[str, Any]],
        action: dict[str, Any],
        action_date: str,
        entry_rows: list[str],
        target_date: str,
        staff: dict[str, dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        reason = action.get("fields", {}).get("領用事由及地點", "")
        if reason == "休息返隊":
            rest_out_exists = False
            for candidate in actions:
                if candidate.get("kind") != "entry_log" or candidate.get("source") != "休息簽出":
                    continue
                if str(candidate.get("target", "")) != str(action.get("target", "")):
                    continue
                candidate_date = self.action_target_roc_date(candidate, target_date)
                if candidate_date != action_date:
                    rest_out_exists = True
                    break
                if self.rest_entry_matches(entry_rows, action_date, candidate, allow_near=False, staff=staff) or self.rest_entry_matches(entry_rows, action_date, candidate, allow_near=True, staff=staff):
                    rest_out_exists = True
                    break
            if not rest_out_exists:
                return {"compare": "未找到", "group": "todo", "matched": []}
        exact = self.rest_entry_matches(entry_rows, action_date, action, allow_near=False, staff=staff)
        near = [] if exact else self.rest_entry_matches(entry_rows, action_date, action, allow_near=True, staff=staff)
        if exact:
            return {"compare": "已存在", "group": "done", "matched": exact[:1]}
        if near:
            return {"compare": "時間近似", "group": "near", "matched": near[:1]}
        return {"compare": "未找到", "group": "todo", "matched": []}

    def duplicate_query_cache_key(self, action: dict[str, Any], target_roc_date: str) -> tuple[str, str, str]:
        fields = action.get("fields", {})
        if action.get("kind") == "entry_log":
            time_value = fields.get("系統寫入時間", fields.get("登打時間", action.get("time", "")))
            return target_roc_date, "entry", str(time_value)
        time_value = fields.get("工作時間", action.get("time", ""))
        return target_roc_date, "work", str(time_value)

    def duplicate_rows_before_submit(
        self,
        driver: webdriver.Chrome,
        action: dict[str, Any],
        target_roc_date: str,
        duplicate_cache: dict[tuple[str, str, str], list[str]] | None,
    ) -> list[str]:
        cache_key = self.duplicate_query_cache_key(action, target_roc_date)
        if duplicate_cache is not None and cache_key in duplicate_cache:
            return duplicate_cache[cache_key]
        ap_name = ENTRY_LOG_AP if action.get("kind") == "entry_log" else WORK_LOG_AP
        rows = flatten_rows(query_visible_table(driver, ap_name, target_roc_date), target_roc_date)
        if duplicate_cache is not None:
            duplicate_cache[cache_key] = rows
        return rows

    def duplicate_matches_before_submit(
        self,
        driver: webdriver.Chrome,
        action: dict[str, Any],
        target_roc_date: str,
        duplicate_cache: dict[tuple[str, str, str], list[str]] | None = None,
    ) -> list[str]:
        rows = self.duplicate_rows_before_submit(driver, action, target_roc_date, duplicate_cache)
        if action.get("kind") == "entry_log":
            reason = action.get("fields", {}).get("領用事由及地點", "")
            if reason in ("休息", "休息返隊"):
                return self.rest_entry_matches(rows, target_roc_date, action, allow_near=False) or self.rest_entry_matches(rows, target_roc_date, action, allow_near=True)
            return find_entry_matches(rows, target_roc_date, self.duty_staff, action, allow_near=False)
        if action.get("source") == "案件工作審核":
            return find_case_work_matches(rows, target_roc_date, action)
        return find_work_matches(rows, target_roc_date, self.duty_staff, action)

    def load_audit_date(self) -> None:
        value = "".join(ch for ch in self.audit_date.get() if ch.isdigit())
        if len(value) != 7:
            messagebox.showwarning("日期格式錯誤", "請輸入民國日期，例如 1150518。")
            return
        max_value = roc_date_after(today_roc_date(), 1)
        if value > max_value:
            self.audit_date.set(max_value)
            messagebox.showwarning("日期超出範圍", f"最多只能選到 {max_value}。")
            return
        path = schedule_path(value)
        if not path.exists():
            path = legacy_rehearsal_path(value)
        if not path.exists():
            messagebox.showwarning("找不到資料", f"找不到 {schedule_path(value).name}，請先產生該日排程資料。")
            return
        self.preview_path.set(str(path))
        self.load_preview(path, update_duty=False)

    def load_today_preview_if_available(self) -> bool:
        target_roc_date = duty_business_roc_date()
        path = schedule_path(target_roc_date)
        if not path.exists():
            path = legacy_rehearsal_path(target_roc_date)
        if not path.exists():
            return False
        self.audit_date.set(target_roc_date)
        self.preview_path.set(str(path))
        self.load_preview(path, update_duty=True)
        return True

    def build_comparison(self, data: dict[str, Any], actions: list[dict[str, Any]] | None = None) -> dict[int, dict[str, Any]]:
        target_date = data.get("target_date", "")
        actions = actions if actions is not None else self.build_audit_actions(data)
        comparison_staff = {**data.get("yesterday", {}).get("staff", {}), **data.get("today", {}).get("staff", {})}
        comparison_cache: dict[str, dict[str, Any]] = {}
        for offset in sorted({int(action.get("date_offset", 0) or 0) for action in actions} | {0}):
            action_date = roc_date_after(target_date, offset) if target_date else ""
            comparison_data = self.load_comparison_data(action_date) if action_date else {}
            entry_source = comparison_data.get("visible_entry_rows", data.get("visible_entry_rows", []))
            work_source = comparison_data.get("visible_work_rows", data.get("visible_work_rows", []))
            comparison_cache[action_date] = {
                "entry_rows": flatten_rows(entry_source, action_date) if action_date else [],
                "work_rows": flatten_rows(work_source, action_date) if action_date else [],
            }
        result: dict[int, dict[str, Any]] = {}
        external_targets: dict[str, set[str]] = {}
        for action in [a for a in actions if a.get("kind") == "entry_log" and a.get("source", "").startswith("外勤")]:
            fields = action.get("fields", {})
            action_date = self.action_target_roc_date(action, target_date)
            key = f"{action_date}:{fields.get('系統寫入時間', action.get('time', ''))}:{fields.get('出或入', '')}"
            external_targets.setdefault(key, set()).add(comparison_staff.get(str(action.get("target", "")), {}).get("name", ""))

        for index, action in enumerate(actions):
            fields = action.get("fields", {})
            action_date = self.action_target_roc_date(action, target_date)
            entry_rows = comparison_cache.get(action_date, {}).get("entry_rows", [])
            work_rows = comparison_cache.get(action_date, {}).get("work_rows", [])
            if action.get("kind") == "entry_log":
                reason = fields.get("領用事由及地點", "")
                if is_future_action(target_date, action):
                    result[index] = {"compare": "尚未到點", "group": "future", "matched": []}
                    continue
                if reason in ("休息", "休息返隊"):
                    result[index] = self.compare_rest_entry(actions, action, action_date, entry_rows, target_date, comparison_staff)
                    continue
                exact = find_entry_matches(entry_rows, action_date, comparison_staff, action, allow_near=False)
                arrival_exists = [] if exact else find_arrival_entry_exists(entry_rows, action_date, comparison_staff, action)
                near = [] if exact else find_entry_matches(entry_rows, action_date, comparison_staff, action, allow_near=True)
                if exact:
                    result[index] = {"compare": "已存在", "group": "done", "matched": exact[:1]}
                elif arrival_exists:
                    result[index] = {"compare": "已存在(時間不同)", "group": "done", "matched": arrival_exists[:1]}
                elif is_possible_handoff_adjustment(entry_rows, action_date, comparison_staff, action):
                    result[index] = {"compare": "可能臨時調整", "group": "adjust", "matched": []}
                elif near:
                    result[index] = {"compare": "時間近似", "group": "near", "matched": near[:1]}
                elif reason in ("到勤", "退勤", "休息後退勤"):
                    result[index] = {"compare": "未找到", "group": "todo", "matched": []}
                elif action.get("source", "").startswith("外勤"):
                    result[index] = {"compare": "人工確認", "group": "review", "matched": []}
                else:
                    result[index] = {"compare": "未找到", "group": "todo", "matched": []}
            else:
                if is_future_action(target_date, action):
                    result[index] = {"compare": "尚未到點", "group": "future", "matched": []}
                    continue
                matches = find_case_work_matches(work_rows, action_date, action) if action.get("source") == "案件工作審核" else find_work_matches(work_rows, action_date, comparison_staff, action)
                if matches:
                    result[index] = {"compare": "已存在", "group": "done", "matched": matches[:1]}
                else:
                    result[index] = {"compare": "未找到", "group": "todo", "matched": []}

        for index, action in enumerate(actions):
            # A matching external record under a different name means the planned
            # row needs human confirmation, not automatic補登.
            if action.get("kind") != "entry_log" or not action.get("source", "").startswith("外勤"):
                continue
            fields = action.get("fields", {})
            action_date = self.action_target_roc_date(action, target_date)
            key = f"{action_date}:{fields.get('系統寫入時間', action.get('time', ''))}:{fields.get('出或入', '')}"
            if result.get(index, {}).get("compare") == "人工確認" and external_targets.get(key):
                result[index]["compare"] = "外勤確認"
        return result

    def action_completion_key(self, action: dict[str, Any]) -> str:
        duplicate_key = str(action.get("duplicate_key", "") or "").strip()
        if duplicate_key:
            return duplicate_key
        fields = action.get("fields", {})
        parts = [
            str(action.get("kind", "")),
            str(action.get("source", "")),
            str(action.get("actor", "")),
            str(action.get("target", "")),
            str(action.get("date_offset", "")),
            str(fields.get("出或入", "")),
            str(fields.get("領用事由及地點", "")),
            str(fields.get("工作項目", "")),
            str(action.get("time", "")),
            self.action_summary(action),
        ]
        return "|".join(parts)

    def apply_manual_completed_overrides(self, compare: dict[int, dict[str, Any]], actions: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
        if not self.manual_completed_keys:
            return compare
        for index, action in enumerate(actions):
            if self.action_completion_key(action) in self.manual_completed_keys:
                compare[index] = {"compare": "已手動登打", "group": "done", "matched": []}
        return compare

    def clear_duty_status_override(self) -> None:
        self.duty_status_override_text = ""
        self.duty_status_override_until = None

    def set_duty_status(self, text: str, hold_seconds: int = 0) -> None:
        self.duty_status_text.set(text)
        if hold_seconds > 0:
            self.duty_status_override_text = text
            self.duty_status_override_until = datetime.now() + timedelta(seconds=hold_seconds)
        else:
            self.clear_duty_status_override()

    def active_duty_status_override(self) -> str:
        if not self.duty_status_override_text or self.duty_status_override_until is None:
            return ""
        if datetime.now() >= self.duty_status_override_until:
            self.clear_duty_status_override()
            return ""
        return self.duty_status_override_text

    def restore_manual_completed_keys(self, target_roc_date: str, actions: list[dict[str, Any]]) -> set[str]:
        log_path = Path("duty_trigger_log.jsonl")
        if not target_roc_date or not log_path.exists():
            return set()
        valid_keys = {self.action_completion_key(action) for action in actions}
        restored: set[str] = set()
        try:
            with log_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except Exception:
                        continue
                    if record.get("trigger_type") != "manual":
                        continue
                    if record.get("target_date") != target_roc_date:
                        continue
                    if record.get("status") not in ("manual_marked", "submitted", "skipped_duplicate"):
                        continue
                    completion_key = str(record.get("completion_key", "") or "").strip()
                    if completion_key and completion_key in valid_keys:
                        restored.add(completion_key)
        except Exception:
            return set()
        return restored

    def load_comparison_data(self, target_roc_date: str) -> dict[str, Any]:
        path = comparison_path(target_roc_date)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    # Saved account management

    def protect_password(self, password: str) -> str:
        if not password or win32crypt is None:
            return ""
        encrypted = win32crypt.CryptProtectData(password.encode("utf-8"), APP_DISPLAY_NAME, None, None, None, 0)
        return base64.b64encode(encrypted).decode("ascii")

    def unprotect_password(self, encrypted_password: str) -> str:
        if not encrypted_password or win32crypt is None:
            return ""
        try:
            _, decrypted = win32crypt.CryptUnprotectData(base64.b64decode(encrypted_password), None, None, None, 0)
        except Exception:
            return ""
        return decrypted.decode("utf-8")

    def account_password_from_payload(self, account: dict[str, Any]) -> str:
        encrypted_password = str(account.get("password_dpapi", "") or "")
        if encrypted_password:
            return self.unprotect_password(encrypted_password)
        return str(account.get("password", "") or "")

    def backup_invalid_saved_login(self) -> None:
        if not self.saved_login_needs_backup or not SAVED_LOGIN_PATH.exists():
            return
        backup_path = SAVED_LOGIN_PATH.with_name(f"{SAVED_LOGIN_PATH.stem}.invalid-{datetime.now():%Y%m%d-%H%M%S}.bak")
        backup_path.write_text(SAVED_LOGIN_PATH.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        self.saved_login_needs_backup = False

    def saved_account_payload(self, account: dict[str, str]) -> dict[str, str]:
        return {
            "actor_no": str(account.get("actor_no", "") or ""),
            "user_id": str(account.get("user_id", "") or ""),
            "password_dpapi": self.protect_password(str(account.get("password", "") or "")),
            "display_name": str(account.get("display_name", "") or ""),
        }

    def load_saved_login(self) -> None:
        if not SAVED_LOGIN_PATH.exists():
            return
        try:
            payload = json.loads(SAVED_LOGIN_PATH.read_text(encoding="utf-8"))
        except Exception:
            self.saved_login_needs_backup = True
            return
        accounts = payload.get("accounts")
        if not isinstance(accounts, list):
            legacy_account = {
                "actor_no": str(payload.get("actor_no", "") or ""),
                "user_id": str(payload.get("user_id", "") or ""),
                "password": str(payload.get("password", "") or ""),
                "display_name": "",
            }
            accounts = [legacy_account] if legacy_account["user_id"] or legacy_account["actor_no"] else []
            payload = {
                "last_selected": legacy_account["user_id"] or legacy_account["actor_no"],
                "accounts": accounts,
            }
        normalized: list[dict[str, str]] = []
        for account in accounts:
            if not isinstance(account, dict):
                continue
            actor_no = str(account.get("actor_no", "") or "").strip()
            user_id = str(account.get("user_id", "") or "").strip()
            if not actor_no and not user_id:
                continue
            normalized.append(
                {
                    "actor_no": actor_no,
                    "user_id": user_id,
                    "password": self.account_password_from_payload(account),
                    "display_name": str(account.get("display_name", "") or ""),
                }
            )
        self.saved_accounts = normalized
        last_selected = str(payload.get("last_selected", "") or "")
        if not last_selected and self.saved_accounts:
            last_selected = self.account_identity(self.saved_accounts[0])
        self.refresh_saved_account_choices()
        if last_selected:
            self.select_saved_account(last_selected, persist=False)
        if payload.get("accounts") != normalized or "accounts" not in payload:
            self.persist_saved_accounts(last_selected)

    def save_login_locally(self, actor_no: str, user_id: str, password: str, display_name: str = "") -> None:
        identity = user_id or actor_no
        if not identity:
            return
        updated = {
            "actor_no": actor_no,
            "user_id": user_id,
            "password": password,
            "display_name": display_name,
        }
        replaced = False
        for index, account in enumerate(self.saved_accounts):
            if self.account_identity(account) == identity:
                self.saved_accounts[index] = updated
                replaced = True
                break
        if not replaced:
            self.saved_accounts.append(updated)
        self.persist_saved_accounts(identity)
        self.select_saved_account(identity, persist=False)

    def persist_saved_accounts(self, last_selected: str = "") -> None:
        SAVED_LOGIN_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.backup_invalid_saved_login()
        payload = {
            "last_selected": last_selected,
            "accounts": [self.saved_account_payload(account) for account in self.saved_accounts],
        }
        SAVED_LOGIN_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def account_identity(self, account: dict[str, str]) -> str:
        return str(account.get("user_id", "") or account.get("actor_no", "") or "").strip()

    def account_sort_key(self, account: dict[str, str]) -> tuple[int, str]:
        actor_no = str(account.get("actor_no", "") or "").strip()
        if actor_no.isdigit():
            return (int(actor_no), self.account_identity(account))
        return (9999, self.account_identity(account))

    def account_display_name(self, account: dict[str, str]) -> str:
        actor_no = str(account.get("actor_no", "") or "").strip()
        user_id = str(account.get("user_id", "") or "").strip()
        if user_id and actor_no:
            return f"{user_id} / {actor_no}番"
        if user_id:
            return user_id
        if actor_no:
            return f"{actor_no}番"
        return ""

    def refresh_saved_account_choices(self) -> None:
        self.saved_accounts.sort(key=self.account_sort_key)
        values = [str(account.get("user_id", "") or "").strip() for account in self.saved_accounts if str(account.get("user_id", "") or "").strip()]
        if self.user_id.get().strip() and self.user_id.get().strip() not in values:
            self.user_id.set(values[0] if values else "")

    def selected_saved_account(self) -> dict[str, str] | None:
        label = self.user_id.get().strip()
        for account in self.saved_accounts:
            account_user_id = str(account.get("user_id", "") or "").strip()
            if account_user_id == label or self.account_display_name(account) == label:
                return account
        return None

    def select_saved_account(self, identity: str, persist: bool = True) -> None:
        for account in self.saved_accounts:
            if self.account_identity(account) != identity:
                continue
            self.user_id.set(str(account.get("user_id", "") or ""))
            self.apply_saved_account(persist=persist)
            return

    def apply_saved_account(self, persist: bool = True) -> None:
        account = self.selected_saved_account()
        if not account:
            return
        self.actor_no.set(str(account.get("actor_no", "") or ""))
        self.user_id.set(str(account.get("user_id", "") or ""))
        self.password.set(str(account.get("password", "") or ""))
        if persist:
            self.persist_saved_accounts(self.account_identity(account))

    def current_account_display_name(self, actor_no: str, user_id: str) -> str:
        actor_no = str(actor_no or "").strip()
        user_id = str(user_id or "").strip()
        if actor_no:
            resolved = self.logged_in_identity_label(actor_no)
            if resolved and resolved != f"{actor_no}番":
                return f"{actor_no}番 {resolved}"
            return f"{actor_no}番 {user_id}" if user_id else f"{actor_no}番"
        return user_id

    def save_or_update_current_account(self) -> None:
        actor_no = self.actor_no.get().strip()
        user_id = self.user_id.get().strip()
        password = self.password.get()
        if not user_id:
            messagebox.showwarning("資料不足", "請先輸入帳號。")
            return
        self.save_login_locally(actor_no, user_id, password, self.current_account_display_name(actor_no, user_id))
        self.login_status.set("已儲存帳號清單。")

    def saved_accounts_for_credential_sync(self) -> list[dict[str, str]]:
        accounts: list[dict[str, str]] = []
        seen: set[str] = set()
        for account in self.saved_accounts:
            actor_no = str(account.get("actor_no", "") or "").strip()
            user_id = str(account.get("user_id", "") or "").strip()
            password = str(account.get("password", "") or "")
            identity = user_id or actor_no
            if not identity or not user_id or not password or identity in seen:
                continue
            seen.add(identity)
            display_name = str(account.get("display_name", "") or self.current_account_display_name(actor_no, user_id)).strip()
            accounts.append(
                {
                    "actor_no": actor_no,
                    "user_id": user_id,
                    "password": password,
                    "display_name": display_name,
                }
            )
        return accounts

    def sync_current_account_dialog(self) -> None:
        accounts = self.saved_accounts_for_credential_sync()
        if not accounts:
            messagebox.showwarning("資料不足", "目前沒有可同步的已儲存帳號密碼。")
            return

        dialog = tk.Toplevel(self)
        dialog.title("同步帳密到另一台")
        dialog.geometry("460x240")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        target_url = tk.StringVar(value=os.environ.get("CREDENTIAL_SYNC_TARGET_URL", "http://另一台電腦IP:8765/credential-sync"))
        sync_code = tk.StringVar()
        account_names = "、".join(account["user_id"] for account in accounts[:5])
        if len(accounts) > 5:
            account_names += f" 等 {len(accounts)} 組"
        status_text = tk.StringVar(value=f"將同步 {len(accounts)} 組已儲存帳號：{account_names}。不會同步 LINE、GCS 或其他設定。")

        frame = ttk.Frame(dialog, padding=14)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="接收網址").grid(row=0, column=0, sticky=tk.W, pady=5)
        ttk.Entry(frame, textvariable=target_url, width=48).grid(row=0, column=1, sticky=tk.EW, pady=5)
        ttk.Label(frame, text="同步碼").grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Entry(frame, textvariable=sync_code, width=18).grid(row=1, column=1, sticky=tk.W, pady=5)
        ttk.Label(frame, textvariable=status_text, wraplength=410).grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(8, 12))
        frame.columnconfigure(1, weight=1)

        def send() -> None:
            url = target_url.get().strip()
            code = sync_code.get().strip()
            if not url or not code:
                messagebox.showwarning("資料不足", "請輸入第二台接收網址與同步碼。", parent=dialog)
                return
            if not messagebox.askyesno(
                "確認同步",
                f"只會同步 {len(accounts)} 組已儲存的勤務系統帳號與密碼到另一台。\n\n不會同步 LINE token、GCS 金鑰或其他設定。確定送出？",
                parent=dialog,
            ):
                return
            status_text.set("同步中...")
            threading.Thread(
                target=self._send_credential_sync,
                args=(dialog, status_text, url, code, accounts),
                daemon=True,
            ).start()

        buttons = ttk.Frame(frame)
        buttons.grid(row=3, column=0, columnspan=2, sticky=tk.E, pady=(8, 0))
        ttk.Button(buttons, text="取消", command=dialog.destroy).pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(buttons, text="送出同步", style="Accent.TButton", command=send).pack(side=tk.RIGHT)

    def _send_credential_sync(
        self,
        dialog: tk.Toplevel,
        status_text: tk.StringVar,
        target_url: str,
        sync_code: str,
        accounts: list[dict[str, str]],
    ) -> None:
        first_account = accounts[0]
        payload = {
            "sync_code": sync_code,
            "accounts": accounts,
            "actor_no": first_account["actor_no"],
            "user_id": first_account["user_id"],
            "password": first_account["password"],
            "display_name": first_account["display_name"],
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            credential_sync_endpoint(target_url),
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            self.after(0, lambda: status_text.set(f"同步失敗：HTTP {exc.code} {detail}"))
            return
        except Exception as exc:
            self.after(0, lambda: status_text.set(f"同步失敗：{exc}"))
            return
        self.after(0, lambda: status_text.set(f"同步完成：{len(accounts)} 組帳號已送到另一台。"))
        self.after(1200, dialog.destroy)

    def delete_selected_account(self) -> None:
        account = self.selected_saved_account()
        if not account:
            messagebox.showwarning("尚未選取", "請先選擇要刪除的記憶帳號。")
            return
        label = self.account_display_name(account)
        if not messagebox.askyesno("確認刪除", f"確定刪除 {label}？"):
            return
        identity = self.account_identity(account)
        self.saved_accounts = [item for item in self.saved_accounts if self.account_identity(item) != identity]
        self.refresh_saved_account_choices()
        next_identity = self.account_identity(self.saved_accounts[0]) if self.saved_accounts else ""
        if next_identity:
            self.select_saved_account(next_identity, persist=False)
        else:
            self.saved_account_choice.set("")
            self.actor_no.set("")
            self.user_id.set("")
            self.password.set("")
        self.persist_saved_accounts(next_identity)

    def manage_saved_accounts(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("帳號管理")
        dialog.geometry("392x404")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        header = tk.Frame(frame, bg="#eff6ff", highlightbackground="#bfdbfe", highlightthickness=1)
        header.pack(fill=tk.X)
        tk.Label(header, text="帳號選擇", bg="#eff6ff", fg="#1e3a8a", font=("Microsoft JhengHei", 11, "bold")).pack(anchor=tk.W, padx=12, pady=(10, 2))
        tk.Label(header, text="登入成功後會依目前設定自動更新。", bg="#eff6ff", fg="#64748b", font=("Microsoft JhengHei", 9)).pack(anchor=tk.W, padx=12, pady=(0, 10))

        list_shell = tk.Frame(frame, bg="#f4f7fb", height=254)
        list_shell.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        list_shell.pack_propagate(False)
        canvas = tk.Canvas(list_shell, bg="#f4f7fb", highlightthickness=0, bd=0)
        list_body = ttk.Frame(canvas)
        list_body.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        window_id = canvas.create_window((0, 0), window=list_body, anchor="nw")
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window_id, width=event.width))
        canvas.pack(fill=tk.BOTH, expand=True)

        def on_mousewheel(event: tk.Event) -> str:
            bbox = canvas.bbox("all")
            if not bbox:
                return "break"
            content_height = bbox[3] - bbox[1]
            viewport_height = max(canvas.winfo_height(), 1)
            if content_height <= viewport_height:
                return "break"
            first, last = canvas.yview()
            step = int(-event.delta / 120)
            if step < 0 and first <= 0:
                return "break"
            if step > 0 and last >= 1:
                return "break"
            canvas.yview_scroll(step, "units")
            return "break"

        canvas.bind("<MouseWheel>", on_mousewheel)
        list_body.bind("<MouseWheel>", on_mousewheel)
        dialog.bind("<MouseWheel>", on_mousewheel)

        for account in self.saved_accounts:
            row = tk.Frame(list_body, bg="#ffffff", highlightbackground="#d8e0ec", highlightthickness=1)
            row.pack(fill=tk.X, pady=(0, 6))
            def choose_account(target: str = self.account_identity(account)) -> None:
                self.select_saved_account(target, persist=True)
                dialog.destroy()

            def delete_account(target: str = self.account_identity(account)) -> None:
                self.user_id.set(target)
                self.delete_selected_account()
                dialog.destroy()
                self.manage_saved_accounts()

            ttk.Button(row, text="✕", width=3, style="DangerTool.TButton", command=delete_account).pack(side=tk.LEFT, padx=(8, 6), pady=5)
            tk.Label(
                row,
                text=self.account_display_name(account),
                bg="#ffffff",
                fg="#0f172a",
                font=("Microsoft JhengHei", 9),
                anchor="w",
                padx=8,
                pady=6,
            ).pack(side=tk.LEFT, fill=tk.X, expand=True)
            ttk.Button(row, text="選擇", width=6, style="PanelTool.TButton", command=choose_account).pack(side=tk.RIGHT, padx=8, pady=5)

        if not self.saved_accounts:
            empty = tk.Frame(list_body, bg="#ffffff", highlightbackground="#d8e0ec", highlightthickness=1)
            empty.pack(fill=tk.X)
            tk.Label(empty, text="目前沒有已儲存帳號。", bg="#ffffff", fg="#64748b", font=("Microsoft JhengHei", 9), padx=12, pady=12).pack(anchor=tk.W)

        footer = tk.Frame(frame, bg="#f4f7fb", height=38)
        footer.pack(fill=tk.X, pady=(10, 0), side=tk.BOTTOM)
        footer.pack_propagate(False)
        ttk.Button(footer, text="關閉", width=8, style="PanelTool.TButton", command=dialog.destroy).pack(side=tk.RIGHT)

    # Login, snapshots, and background refresh

    def actor_no_from_user_id(self, user_id: str) -> str:
        user_id = str(user_id or "").strip()
        if not user_id:
            return ""
        for account in self.saved_accounts:
            if str(account.get("user_id", "") or "").strip() == user_id:
                actor_no = str(account.get("actor_no", "") or "").strip()
                if actor_no:
                    return actor_no
                display_name = str(account.get("display_name", "") or "").strip()
                display_match = re.match(r"^\s*(\d+)\s*番?", display_name)
                if display_match:
                    return display_match.group(1)
        for source in (self.duty_staff, self.staff):
            for no, info in source.items():
                if str(info.get("user_id", "") or "").strip() == user_id:
                    return str(no)
        for dataset in (self.duty_data, self.data):
            for sheet_key in ("today", "yesterday", "tomorrow"):
                for no, info in dataset.get(sheet_key, {}).get("staff", {}).items():
                    if str(info.get("user_id", "") or "").strip() == user_id:
                        return str(no)
        return ""

    def actor_no_from_name(self, name: str) -> str:
        name = str(name or "").strip()
        if not name:
            return ""
        for source in (self.duty_staff, self.staff):
            for no, info in source.items():
                if str(info.get("name", "") or "").strip() == name:
                    return str(no)
        for dataset in (self.duty_data, self.data):
            for sheet_key in ("today", "yesterday", "tomorrow"):
                for no, info in dataset.get(sheet_key, {}).get("staff", {}).items():
                    if str(info.get("name", "") or "").strip() == name:
                        return str(no)
        for value in duty_window_dates(today_roc_date()):
            path = schedule_path(value)
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for sheet_key in ("today", "yesterday", "tomorrow"):
                for no, info in data.get(sheet_key, {}).get("staff", {}).items():
                    if str(info.get("name", "") or "").strip() == name:
                        return str(no)
        return ""

    def verify_login(self) -> None:
        if self.login_running:
            return
        actor_no = self.actor_no.get().strip()
        user_id = self.user_id.get().strip()
        password = self.password.get()
        if not user_id or not password:
            messagebox.showwarning("資料不足", "請輸入帳號、密碼。")
            return

        self.login_running = True
        self.login_attempt_id += 1
        attempt_id = self.login_attempt_id
        self.set_login_buttons_enabled(False)
        self.login_status.set("登入中...")
        self.after(45000, lambda value=attempt_id: self._login_timed_out(value))
        thread = threading.Thread(target=self._verify_login_worker, args=(attempt_id, actor_no, user_id, password), daemon=True)
        thread.start()

    def _verify_login_worker(self, attempt_id: int, actor_no: str, user_id: str, password: str) -> None:
        driver = None
        try:
            options = Options()
            options.add_argument("--headless=new")
            options.add_argument("--disable-popup-blocking")
            driver = webdriver.Chrome(options=options)
            driver.set_page_load_timeout(30)
            driver.set_script_timeout(30)
            login(driver, user_id, password)
            detected_actor_no, actor_name = self.identify_logged_in_actor(driver)
            actor_no = detected_actor_no or self.actor_no_from_user_id(user_id) or actor_no
            if not actor_no:
                raise RuntimeError("帳號或密碼可能錯誤，或登入後頁面沒有顯示可辨識的姓名。")
        except Exception as exc:
            self.after(0, lambda value=attempt_id, error=str(exc): self._login_failed(value, error))
            return
        finally:
            if driver:
                driver.quit()
        self.after(0, lambda value=attempt_id: self._login_succeeded(value, actor_no, user_id, password))

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
        canonical_path.parent.mkdir(parents=True, exist_ok=True)
        canonical_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        SNAPSHOT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        slot_part = f"_{slot_label}" if slot_label else ""
        snapshot_path = SNAPSHOT_OUTPUT_DIR / f"schedule_output_{target_roc_date}{slot_part}_{datetime.now():%H%M%S}.json"
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
        canonical_path.parent.mkdir(parents=True, exist_ok=True)
        canonical_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        SNAPSHOT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        slot_part = f"_{slot_label}" if slot_label else ""
        snapshot_path = SNAPSHOT_OUTPUT_DIR / f"comparison_output_{target_roc_date}{slot_part}_{datetime.now():%H%M%S}.json"
        snapshot_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return canonical_path

    def check_scheduled_snapshot(self) -> None:
        try:
            now = datetime.now()
            if 18 <= now.hour < 24:
                self.ensure_tomorrow_schedule_background(f"{now.hour:02d}{now.minute:02d}")
        finally:
            self.after(30000, self.check_scheduled_snapshot)

    def ensure_tomorrow_schedule_background(self, slot_label: str) -> None:
        target_roc_date = roc_date_after(today_roc_date(), 1)
        key = f"schedule-{target_roc_date}-{slot_label}"
        if schedule_path(target_roc_date).exists():
            self.snapshot_completed_slots.add(key)
        elif key not in self.snapshot_completed_slots:
            self.refresh_schedule_background(target_roc_date, slot_label)

    def ensure_duty_window_background(self, base_roc_date: str, slot_label: str) -> None:
        target_dates = [value for value in duty_window_dates(base_roc_date) if not schedule_path(value).exists()]
        if target_dates:
            self.refresh_schedule_background(base_roc_date, slot_label, target_dates=target_dates)

    def refresh_schedule_background(self, target_roc_date: str, slot_label: str, target_dates: list[str] | None = None) -> None:
        if self.snapshot_running or not (self.session and self.session.verified):
            return
        session = self.session
        key = f"schedule-{target_roc_date}-{slot_label}"
        target_dates = target_dates or [target_roc_date]
        self.snapshot_running = True
        self.set_logged_in_status(session.actor_no)

        def worker() -> None:
            driver = None
            try:
                options = Options()
                options.add_argument("--headless=new")
                options.add_argument("--disable-popup-blocking")
                driver = webdriver.Chrome(options=options)
                login(driver, session.user_id, session.password)
                paths = [self.write_schedule_snapshot(driver, value, slot_label) for value in target_dates]
            except Exception as exc:
                error = str(exc)
                self.after(0, lambda: self._schedule_failed(session.actor_no, session.user_id, error))
                return
            finally:
                if driver:
                    driver.quit()
            self.after(0, lambda: self._schedule_succeeded(session.actor_no, session.user_id, key, target_roc_date, paths))

        threading.Thread(target=worker, daemon=True).start()

    def _schedule_succeeded(self, actor_no: str, user_id: str, key: str, target_roc_date: str, paths: list[Path]) -> None:
        self.snapshot_running = False
        if not self.current_session_matches(user_id):
            return
        self.snapshot_completed_slots.add(key)
        today_path = next((path for path in paths if path.exists() and path.name == schedule_path(duty_business_roc_date()).name), None)
        if today_path:
            if not self.data.get("target_date"):
                self.preview_path.set(str(today_path))
                self.load_preview(today_path, update_duty=True)
            else:
                try:
                    today_data = json.loads(today_path.read_text(encoding="utf-8"))
                    self.sanitize_schedule_data(today_data)
                    if self.data.get("target_date") == today_data.get("target_date"):
                        self.data = today_data
                        self.staff = {
                            **today_data.get("yesterday", {}).get("staff", {}),
                            **today_data.get("today", {}).get("staff", {}),
                        }
                        self.actions = self.build_audit_actions(today_data)
                        self.action_compare = self.build_comparison(today_data)
                        self.refresh_tasks()
                        self.duty_data = today_data
                        self.duty_staff = {**today_data.get("yesterday", {}).get("staff", {}), **today_data.get("today", {}).get("staff", {})}
                        self.duty_actions = today_data.get("actions", [])
                        self.manual_completed_keys = self.restore_manual_completed_keys(today_data.get("target_date", ""), self.duty_actions)
                        self.duty_action_compare = self.apply_manual_completed_overrides(self.build_comparison(today_data, self.duty_actions), self.duty_actions)
                        self.sync_session_actor_from_user_id()
                        self.refresh_duty_tasks()
                except Exception:
                    pass
        if self.current_session_matches(user_id):
            self.set_logged_in_status(self.session.actor_no)
        selected_date = "".join(ch for ch in self.audit_date.get() if ch.isdigit())
        selected_path = next((path for path in paths if path.exists() and path.name == schedule_path(selected_date).name), None)
        if selected_path and selected_date != self.duty_data.get("target_date"):
            self.preview_path.set(str(selected_path))
            self.load_preview(selected_path, update_duty=False)

    def _schedule_failed(self, actor_no: str, user_id: str, error: str) -> None:
        self.snapshot_running = False
        if self.current_session_matches(user_id):
            self.set_logged_in_status(self.session.actor_no)

    def check_hourly_comparison(self) -> None:
        try:
            now = datetime.now()
            if now.minute < 5 and self.session and self.session.verified:
                target_roc_date = duty_business_roc_date()
                key = f"comparison-{target_roc_date}-{now:%Y%m%d%H}"
                if key not in self.comparison_completed_hours:
                    comparison_dates = duty_window_dates(target_roc_date)
                    if self.comparison_running:
                        self.pending_hourly_comparison = (target_roc_date, f"{now:%H}00", comparison_dates, self.session.user_id, key)
                    else:
                        self.refresh_comparison_background(target_roc_date, f"{now:%H}00", comparison_dates=comparison_dates, completion_key=key)
        finally:
            self.after(60000, self.check_hourly_comparison)

    def refresh_current_comparison(self) -> None:
        target_roc_date = "".join(ch for ch in self.audit_date.get() if ch.isdigit())
        if len(target_roc_date) != 7:
            target_roc_date = self.data.get("target_date", "")
        if not (self.session and self.session.verified):
            messagebox.showwarning("尚未登入", "請先登入後再重新查詢。")
            return
        if self.comparison_running:
            messagebox.showinfo("查詢中", "目前已在背景查詢，請稍候。")
            return
        if len(target_roc_date) != 7:
            messagebox.showwarning("缺少日期", "請先選擇要查詢的勤務日期。")
            return
        self.status_text.set(f"正在重新查詢 {target_roc_date} 的勤務表、工作、出入資料。")
        self.refresh_schedule_background(target_roc_date, "manual-refresh", target_dates=[target_roc_date])
        self.refresh_comparison_background(target_roc_date, "manual-refresh", comparison_dates=duty_window_dates(target_roc_date))

    def current_session_matches(self, user_id: str) -> bool:
        return bool(self.session and self.session.verified and self.session.user_id == user_id)

    def run_pending_hourly_comparison(self) -> None:
        pending = self.pending_hourly_comparison
        if not pending or self.comparison_running:
            return
        target_roc_date, slot_label, comparison_dates, user_id, key = pending
        self.pending_hourly_comparison = None
        if not self.current_session_matches(user_id) or key in self.comparison_completed_hours:
            return
        self.refresh_comparison_background(target_roc_date, slot_label, comparison_dates=comparison_dates, completion_key=key)

    def refresh_comparison_background(self, target_roc_date: str, slot_label: str, comparison_dates: list[str] | None = None, completion_key: str | None = None) -> None:
        if self.comparison_running or not (self.session and self.session.verified):
            return
        session = self.session
        key = completion_key or f"comparison-{target_roc_date}-{datetime.now():%Y%m%d%H}"
        comparison_dates = comparison_dates or self.comparison_target_dates(target_roc_date)
        self.comparison_running = True
        self.set_logged_in_status(session.actor_no)

        def worker() -> None:
            driver = None
            try:
                options = Options()
                options.add_argument("--headless=new")
                options.add_argument("--disable-popup-blocking")
                driver = webdriver.Chrome(options=options)
                login(driver, session.user_id, session.password)
                paths = [self.write_comparison_snapshot(driver, comparison_date, slot_label) for comparison_date in comparison_dates]
            except Exception as exc:
                error = str(exc)
                self.after(0, lambda: self._comparison_failed(session.actor_no, session.user_id, error))
                return
            finally:
                if driver:
                    driver.quit()
            self.after(0, lambda: self._comparison_succeeded(session.actor_no, session.user_id, key, target_roc_date, paths))

        threading.Thread(target=worker, daemon=True).start()

    def comparison_target_dates(self, target_roc_date: str) -> list[str]:
        dates = {target_roc_date}
        for dataset in (self.data, self.duty_data):
            if dataset.get("target_date") != target_roc_date:
                continue
            for action in dataset.get("actions", []):
                dates.add(roc_date_after(target_roc_date, int(action.get("date_offset", 0) or 0)))
        return sorted(dates)

    def _comparison_succeeded(self, actor_no: str, user_id: str, key: str, target_roc_date: str, paths: list[Path]) -> None:
        self.comparison_running = False
        if not self.current_session_matches(user_id):
            self.run_pending_hourly_comparison()
            return
        self.comparison_completed_hours.add(key)
        if any(path.exists() for path in paths) and self.data.get("target_date") == target_roc_date:
            self.action_compare = self.build_comparison(self.data)
            self.refresh_tasks()
        if any(path.exists() for path in paths) and self.duty_data.get("target_date") == target_roc_date:
            self.duty_action_compare = self.apply_manual_completed_overrides(self.build_comparison(self.duty_data, self.duty_actions), self.duty_actions)
            self.refresh_duty_tasks()
        if self.current_session_matches(user_id):
            self.set_logged_in_status(self.session.actor_no)
        self.run_pending_hourly_comparison()

    def _comparison_failed(self, actor_no: str, user_id: str, error: str) -> None:
        self.comparison_running = False
        if self.current_session_matches(user_id):
            self.set_logged_in_status(self.session.actor_no)
        self.run_pending_hourly_comparison()

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
        greeting_match = re.search(r"([^\s,，]+)\s*[,，]\s*您好", page_text)
        if greeting_match:
            actor_name = greeting_match.group(1).strip()
            actor_no = self.actor_no_from_name(actor_name)
            if actor_no:
                return actor_no, actor_name
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

    def _login_succeeded(self, attempt_id: int, actor_no: str, user_id: str, password: str) -> None:
        if attempt_id != self.login_attempt_id:
            return
        self.login_running = False
        self.set_login_buttons_enabled(True)
        self.clear_duty_status_override()
        self.executed_due.clear()
        self.manual_completed_keys.clear()
        self.submitting_indices.clear()
        self.failed_due_retry_after.clear()
        self.submit_queues = {"entry": [], "work": []}
        self.submit_worker_running = {"entry": False, "work": False}
        self.work_submit_parallel_enabled = True
        self.pending_hourly_comparison = None
        self.submit_needs_comparison_refresh = False
        self.submit_comparison_refresh_dates.clear()
        self.submit_comparison_refresh_scheduled = False
        self.cancel_auto_logout()
        self.session = LoginSession(actor_no=actor_no, user_id=user_id, password=password, verified=True)
        if self.remember_login.get():
            self.save_login_locally(actor_no, user_id, password, self.current_account_display_name(actor_no, user_id))
        if self.data.get("target_date"):
            self.action_compare = self.build_comparison(self.data)
        if self.duty_data.get("target_date"):
            self.manual_completed_keys = self.restore_manual_completed_keys(self.duty_data["target_date"], self.duty_actions)
        if self.duty_data.get("target_date"):
            self.duty_action_compare = self.apply_manual_completed_overrides(self.build_comparison(self.duty_data, self.duty_actions), self.duty_actions)
        self.set_logged_in_status(actor_no)
        self.actor_no.set(actor_no)
        self.logout_cleared = False
        self.audit_date.set(duty_business_roc_date())
        if self.simple_mode.get():
            self.filter_actor.set(True)
            self.status_filter.set("需處理")
        self.update_login_panel()
        login_target_date = duty_business_roc_date()
        self.refresh_schedule_background(login_target_date, "login-today", target_dates=[login_target_date])
        self.ensure_duty_window_background(login_target_date, "login")
        if self.load_today_preview_if_available():
            self.set_logged_in_status(actor_no)
            self.refresh_comparison_background(login_target_date, "login", comparison_dates=duty_window_dates(login_target_date))
        else:
            self.refresh_tasks()
            self.refresh_duty_tasks()
            self.set_logged_in_status(actor_no)
            self.refresh_comparison_background(login_target_date, "login", comparison_dates=duty_window_dates(login_target_date))

    def _login_failed(self, attempt_id: int, error: str) -> None:
        if attempt_id != self.login_attempt_id:
            return
        self.login_running = False
        self.set_login_buttons_enabled(True)
        self.session = None
        self.login_status.set(f"登入失敗：{error}")
        messagebox.showerror("登入失敗", error)
        self.update_login_panel()
        self.refresh_tasks()

    def _login_timed_out(self, attempt_id: int) -> None:
        if attempt_id != self.login_attempt_id or not self.login_running:
            return
        self.login_running = False
        self.login_attempt_id += 1
        self.set_login_buttons_enabled(True)
        self.session = None
        self.login_status.set("登入逾時：請確認帳號密碼或勤務系統是否有回應。")
        messagebox.showerror("登入逾時", "登入超過 45 秒沒有完成，已恢復登入按鈕。")
        self.update_login_panel()
        self.refresh_tasks()

    # Login state and duty identity

    def login_person_label(self, number: str) -> str:
        info = self.duty_staff.get(str(number), {}) or self.staff.get(str(number), {})
        name = info.get("name", "")
        role = info.get("role", "")
        if name and role:
            return f"{name}({role})"
        return name or self.person_label(number)

    def logged_in_identity_label(self, number: str) -> str:
        info = self.duty_staff.get(str(number), {}) or self.staff.get(str(number), {})
        name = info.get("name", "")
        role = info.get("role", "")
        if role and name:
            return f"{role} {name}"
        return name or self.person_label(number)

    def duty_shift_label(self, actor_no: str) -> str:
        rows = self.duty_data.get("today", {}).get("rows", [])
        spans: list[tuple[int, int]] = []
        overnight_start: int | None = None
        overnight_end: int | None = None
        for row in rows:
            columns = row.get("columns", {})
            duty_people = [str(value) for value in columns.get("值班", [])]
            if str(actor_no) not in duty_people:
                continue
            start = slot_start(str(row.get("slot", "")))
            end = slot_end(str(row.get("slot", "")))
            if start is None or end is None:
                continue
            if end <= start:
                return f"{start:02d} - {end:02d}"
            if start >= 22:
                overnight_start = start if overnight_start is None else min(overnight_start, start)
                continue
            if end <= 8:
                overnight_end = end if overnight_end is None else max(overnight_end, end)
                continue
            spans.append((start, end))
        if overnight_start is not None and overnight_end is not None:
            return f"{overnight_start:02d} - {overnight_end:02d}"
        if not spans:
            return "今日無值班時段"
        start = min(item[0] for item in spans)
        end = max(item[1] for item in spans)
        return f"{start:02d} - {end:02d}"

    def cancel_auto_logout(self) -> None:
        if self.auto_logout_after_id:
            try:
                self.after_cancel(self.auto_logout_after_id)
            except Exception:
                pass
        self.auto_logout_after_id = None
        self.auto_logout_deadline = None
        self.auto_logout_actor_no = ""

    def should_schedule_auto_logout(self, action: dict[str, Any], trigger_type: str) -> bool:
        if trigger_type != "due" or action.get("kind") != "entry_log":
            return False
        fields = action.get("fields", {})
        outin = str(fields.get("出或入", "")).strip()
        reason = str(fields.get("領用事由及地點", "")).strip()
        return outin == "值退" or reason in ("退勤", "休息後退勤")

    def schedule_auto_logout(self, actor_no: str, action: dict[str, Any]) -> None:
        self.cancel_auto_logout()
        action_at = self.action_datetime(action)
        deadline = action_at + timedelta(minutes=10)
        delay_ms = max(0, int((deadline - datetime.now()).total_seconds() * 1000))
        self.auto_logout_deadline = deadline
        self.auto_logout_actor_no = str(actor_no)
        self.auto_logout_after_id = self.after(
            delay_ms,
            lambda expected_actor=str(actor_no), expected_deadline=deadline: self.run_auto_logout(expected_actor, expected_deadline),
        )
        self.duty_status_text.set(f"已排定 {deadline:%H:%M} 自動登出。")

    def run_auto_logout(self, expected_actor: str, expected_deadline: datetime) -> None:
        self.auto_logout_after_id = None
        if self.auto_logout_deadline != expected_deadline or self.auto_logout_actor_no != str(expected_actor):
            return
        if not (self.session and self.session.verified) or str(self.session.actor_no) != str(expected_actor):
            self.cancel_auto_logout()
            return
        label = self.logged_in_identity_label(expected_actor)
        self.clear_login()
        self.login_status.set(f"已自動登出：{label}")
        self.set_duty_status("值班段落結束 10 分鐘，已自動登出。", hold_seconds=10)
        self.notify_user(APP_DISPLAY_NAME, f"{label} 已自動登出")

    def set_logged_in_status(self, actor_no: str) -> None:
        if self.snapshot_running and self.duty_data.get("target_date") != duty_business_roc_date():
            self.login_status.set(f"已登入：{self.logged_in_identity_label(actor_no)}，正在查詢今日勤務表。")
            return
        shift_label = self.duty_shift_label(actor_no)
        if shift_label == "今日無值班時段":
            self.login_status.set(f"已登入：{self.logged_in_identity_label(actor_no)}，今日無值班時段。")
            return
        self.login_status.set(f"已登入：{self.logged_in_identity_label(actor_no)}，今日值班時段：{shift_label}。")

    def sync_session_actor_from_user_id(self) -> None:
        if not (self.session and self.session.verified):
            return
        resolved = self.actor_no_from_user_id(self.session.user_id)
        if not resolved or resolved == self.session.actor_no:
            return
        self.session.actor_no = resolved
        self.actor_no.set(resolved)

    def clear_login(self) -> None:
        self.cancel_auto_logout()
        self.clear_duty_status_override()
        self.session = None
        self.executed_due.clear()
        self.manual_completed_keys.clear()
        self.submitting_indices.clear()
        self.failed_due_retry_after.clear()
        self.submit_queues = {"entry": [], "work": []}
        self.submit_worker_running = {"entry": False, "work": False}
        self.work_submit_parallel_enabled = True
        self.pending_hourly_comparison = None
        self.submit_needs_comparison_refresh = False
        self.submit_comparison_refresh_dates.clear()
        self.submit_comparison_refresh_scheduled = False
        self.load_saved_login()
        self.saved_account_choice.set("")
        self.actor_no.set("")
        self.user_id.set("")
        self.password.set("")
        self.logout_cleared = True
        self.login_status.set("已清除登入狀態。")
        if self.data.get("target_date"):
            self.action_compare = self.build_comparison(self.data)
        if self.duty_data.get("target_date"):
            self.manual_completed_keys = self.restore_manual_completed_keys(self.duty_data["target_date"], self.duty_actions)
        if self.duty_data.get("target_date"):
            self.duty_action_compare = self.apply_manual_completed_overrides(self.build_comparison(self.duty_data, self.duty_actions), self.duty_actions)
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
            if hasattr(self, "work_log_settings_button") and not self.work_log_settings_button.winfo_manager():
                self.work_log_settings_button.pack(side=tk.RIGHT)
            self.set_duty_action_buttons_visible(True)
        else:
            self.credentials_grid.pack_forget()
            self.credentials_grid.pack(fill=tk.X, before=self.button_row)
            if not self.login_button.winfo_manager():
                self.login_button.pack(side=tk.LEFT, fill=tk.X, expand=True, before=self.logout_button)
            self.logout_button.pack_forget()
            if hasattr(self, "work_log_settings_button"):
                self.work_log_settings_button.pack_forget()
            self.set_duty_action_buttons_visible(False)
        self.set_login_buttons_enabled(not self.login_running)

    def set_duty_action_buttons_visible(self, visible: bool) -> None:
        if not hasattr(self, "audit_mode_button") or not hasattr(self, "early_submit_button"):
            return
        if visible:
            if hasattr(self, "duty_sheet_tools_card") and not self.duty_sheet_tools_card.winfo_manager():
                self.duty_sheet_tools_card.pack(fill=tk.X, pady=(10, 0), before=self.duty_controls)
            if not self.audit_mode_button.winfo_manager():
                self.audit_mode_button.pack(side=tk.RIGHT)
            if not self.early_submit_button.winfo_manager():
                self.early_submit_button.pack(side=tk.RIGHT, padx=(0, 8))
        else:
            if hasattr(self, "duty_sheet_tools_card"):
                self.duty_sheet_tools_card.pack_forget()
            self.audit_mode_button.pack_forget()
            self.early_submit_button.pack_forget()

    def work_log_case_records(self, key: str) -> list[CaseRecord]:
        records: list[CaseRecord] = []
        for item in self.duty_data.get(key, []) or []:
            if isinstance(item, CaseRecord):
                records.append(item)
            elif isinstance(item, dict):
                records.append(
                    CaseRecord(
                        report_time=str(item.get("report_time", "")),
                        return_time=str(item.get("return_time", "")),
                        category=str(item.get("category", "")),
                        raw=[str(value) for value in item.get("raw", [])],
                    )
                )
        return records

    def work_log_case_items(self) -> list[dict[str, Any]]:
        target_date = self.duty_data.get("target_date", "") or duty_business_roc_date()
        items = unreturned_case_vehicle_items(self.work_log_case_records("yesterday_cases"), self.work_log_defaults, roc_date_after(target_date, -1))
        items.extend(unreturned_case_vehicle_items(self.work_log_case_records("cases"), self.work_log_defaults, target_date))
        return items

    def handoff_vehicle_out_count(self, hour: int) -> int:
        target_date = self.duty_data.get("target_date", "") or duty_business_roc_date()
        if hour == 8:
            items = unreturned_case_vehicle_items(self.work_log_case_records("yesterday_cases"), self.work_log_defaults, roc_date_after(target_date, -1))
            items.extend(unreturned_case_vehicle_items(self.work_log_case_records("cases"), self.work_log_defaults, target_date, before_hour=8))
        else:
            items = unreturned_case_vehicle_items(self.work_log_case_records("cases"), self.work_log_defaults, target_date, before_hour=hour)
        return sum(int(item.get("count", 0)) for item in items)

    def refresh_work_log_handoff_descriptions(self) -> None:
        for action in self.duty_actions:
            if action.get("kind") != "work_log" or action.get("source") != "值班交接":
                continue
            try:
                hour = int(str(action.get("time", "00:00")).split(":", 1)[0])
            except ValueError:
                hour = 0
            action.setdefault("fields", {})["工作概述"] = work_handoff_description(self.work_log_defaults, self.handoff_vehicle_out_count(hour))
        for action in self.duty_data.get("actions", []) or []:
            if action.get("kind") != "work_log" or action.get("source") != "值班交接":
                continue
            try:
                hour = int(str(action.get("time", "00:00")).split(":", 1)[0])
            except ValueError:
                hour = 0
            action.setdefault("fields", {})["工作概述"] = work_handoff_description(self.work_log_defaults, self.handoff_vehicle_out_count(hour))

    def open_work_log_defaults_dialog(self) -> None:
        self.work_log_defaults = load_work_log_defaults()
        dialog = tk.Toplevel(self)
        dialog.title("工作紀錄預設內容")
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(bg="#f4f7fb")
        dialog.geometry("520x660")
        dialog.minsize(500, 620)
        self.apply_window_icon(dialog)

        container = tk.Frame(dialog, bg="#f4f7fb")
        container.pack(fill=tk.BOTH, expand=True, padx=14, pady=14)

        header = tk.Frame(container, bg="#e0f2fe", highlightbackground="#bae6fd", highlightthickness=1)
        header.pack(fill=tk.X)
        tk.Label(header, text="工作紀錄預設內容", bg="#e0f2fe", fg="#0f172a", font=("Microsoft JhengHei", 13, "bold")).pack(anchor=tk.W, padx=12, pady=(10, 2))
        tk.Label(header, text="消防救護車出勤由未返隊案件帶入，例外可調整單筆案件台數。", bg="#e0f2fe", fg="#0369a1", font=("Microsoft JhengHei", 9)).pack(anchor=tk.W, padx=12, pady=(0, 10))

        form = tk.Frame(container, bg="#ffffff", highlightbackground="#dbeafe", highlightthickness=1)
        form.pack(fill=tk.X, pady=(10, 0))
        vars_by_key: dict[str, tk.StringVar] = {}

        def add_setting_spin(parent: tk.Widget, row: int, col: int, key: str, label: str, unit: str) -> None:
            tk.Label(parent, text=label, bg="#ffffff", fg="#475569", font=("Microsoft JhengHei", 9)).grid(row=row, column=col, sticky=tk.W, padx=(8, 3), pady=6)
            var = tk.StringVar(value=str(int_setting(self.work_log_defaults, key, int_setting(DEFAULT_WORK_LOG_DEFAULTS, key, 0))))
            vars_by_key[key] = var
            tk.Spinbox(parent, from_=0, to=99, width=4, textvariable=var, font=("Microsoft JhengHei", 9), justify=tk.CENTER).grid(row=row, column=col + 1, sticky=tk.W, pady=6)
            tk.Label(parent, text=unit, bg="#ffffff", fg="#64748b", font=("Microsoft JhengHei", 9)).grid(row=row, column=col + 2, sticky=tk.W, padx=(2, 8), pady=6)

        def add_item_label(row: int, text: str) -> None:
            tk.Label(form, text=text, bg="#ffffff", fg="#0f172a", font=("Microsoft JhengHei", 9, "bold"), width=12, anchor=tk.W).grid(row=row, column=0, sticky=tk.W, padx=(12, 2), pady=6)

        add_item_label(0, "無線電")
        add_setting_spin(form, 0, 1, "radio_count", "良好", "支")
        add_item_label(1, "消防及救護車")
        add_setting_spin(form, 1, 1, "emergency_vehicles_in_station", "在隊", "台")
        add_setting_spin(form, 1, 4, "emergency_vehicles_repair", "報修", "台")
        add_item_label(2, "後勤車")
        add_setting_spin(form, 2, 1, "support_vehicles_in_station", "在隊", "台")
        add_setting_spin(form, 2, 4, "support_vehicles_out", "出勤", "台")
        add_setting_spin(form, 2, 7, "support_vehicles_repair", "報修", "台")
        add_item_label(3, "救災器材")
        add_setting_spin(form, 3, 1, "rescue_equipment_in_station", "在隊", "台")
        add_setting_spin(form, 3, 4, "rescue_equipment_out", "出勤", "台")
        add_item_label(4, "TIC")
        add_setting_spin(form, 4, 1, "tic_count", "隊上", "支")

        note_card = tk.Frame(container, bg="#ffffff", highlightbackground="#dbeafe", highlightthickness=1)
        note_card.pack(fill=tk.X, pady=(10, 0))
        tk.Label(note_card, text="重要記事", bg="#ffffff", fg="#334155", font=("Microsoft JhengHei", 9, "bold")).pack(anchor=tk.W, padx=12, pady=(8, 2))
        note_text = tk.Text(note_card, height=3, wrap=tk.WORD, font=("Microsoft JhengHei", 9), relief=tk.FLAT, highlightbackground="#cbd5e1", highlightthickness=1)
        note_text.pack(fill=tk.X, padx=12, pady=(0, 10))
        note_text.insert("1.0", str(self.work_log_defaults.get("important_note", "")))

        case_card = tk.Frame(container, bg="#ffffff", highlightbackground="#dbeafe", highlightthickness=1)
        case_card.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        tk.Label(case_card, text="未返隊案件出勤估算", bg="#ffffff", fg="#334155", font=("Microsoft JhengHei", 9, "bold")).pack(anchor=tk.W, padx=12, pady=(8, 4))
        case_rows = tk.Frame(case_card, bg="#ffffff")
        case_rows.pack(fill=tk.X, padx=12)
        case_vars: dict[str, tk.StringVar] = {}
        items = self.work_log_case_items()
        if not items:
            tk.Label(case_rows, text="目前沒有查到未返隊案件；登入查詢後會由案件帶入。", bg="#ffffff", fg="#64748b", font=("Microsoft JhengHei", 9)).pack(anchor=tk.W, pady=(0, 8))
        for item in items:
            row = tk.Frame(case_rows, bg="#ffffff")
            row.pack(fill=tk.X, pady=2)
            date_text = str(item.get("date", ""))
            if len(date_text) == 7 and date_text.isdigit():
                date_text = f"{date_text[:3]}/{date_text[3:5]}/{date_text[5:7]}"
            label = f"{date_text} {item.get('report_time', '')} {item.get('category', '案件')}"
            tk.Label(row, text=label, bg="#ffffff", fg="#0f172a", font=("Microsoft JhengHei", 9), width=40, anchor=tk.W).pack(side=tk.LEFT)
            var = tk.StringVar(value=str(item.get("count", item.get("default_count", 0))))
            case_vars[str(item["key"])] = var
            tk.Spinbox(row, from_=0, to=9, width=3, textvariable=var, font=("Microsoft JhengHei", 9), justify=tk.CENTER).pack(side=tk.LEFT)
            tk.Label(row, text="台", bg="#ffffff", fg="#64748b", font=("Microsoft JhengHei", 9)).pack(side=tk.LEFT, padx=(3, 0))

        preview = tk.Label(case_card, text="", bg="#f8fafc", fg="#1e3a8a", font=("Microsoft JhengHei", 9), justify=tk.LEFT, anchor=tk.W, wraplength=460)
        preview.pack(fill=tk.X, padx=12, pady=(8, 10))

        def collect_settings() -> dict[str, Any]:
            settings = dict(self.work_log_defaults)
            for key, var in vars_by_key.items():
                try:
                    settings[key] = max(0, int(var.get()))
                except ValueError:
                    settings[key] = 0
            settings["important_note"] = note_text.get("1.0", tk.END).strip()
            overrides = dict(settings.get("case_vehicle_overrides", {})) if isinstance(settings.get("case_vehicle_overrides"), dict) else {}
            for key, var in case_vars.items():
                date_key = key.split("|", 1)[0]
                overrides.setdefault(date_key, {})
                try:
                    overrides[date_key][key] = max(0, int(var.get()))
                except ValueError:
                    overrides[date_key][key] = 0
            settings["case_vehicle_overrides"] = overrides
            return settings

        def refresh_preview(*_args: object) -> None:
            settings = collect_settings()
            total = 0
            for var in case_vars.values():
                try:
                    total += max(0, int(var.get()))
                except ValueError:
                    pass
            preview.config(text=work_handoff_description(settings, total))

        for var in list(vars_by_key.values()) + list(case_vars.values()):
            var.trace_add("write", refresh_preview)
        note_text.bind("<KeyRelease>", refresh_preview)
        refresh_preview()

        buttons = tk.Frame(container, bg="#f4f7fb")
        buttons.pack(fill=tk.X, pady=(10, 0))

        def reset_defaults() -> None:
            for key, var in vars_by_key.items():
                var.set(str(DEFAULT_WORK_LOG_DEFAULTS.get(key, 0)))
            note_text.delete("1.0", tk.END)
            note_text.insert("1.0", str(DEFAULT_WORK_LOG_DEFAULTS.get("important_note", "")))
            for item in items:
                key = str(item["key"])
                if key in case_vars:
                    case_vars[key].set(str(item.get("default_count", 0)))
            refresh_preview()

        def save_settings() -> None:
            self.work_log_defaults = collect_settings()
            save_work_log_defaults(self.work_log_defaults)
            self.refresh_work_log_handoff_descriptions()
            self.refresh_duty_tasks()
            self.set_duty_status("已儲存工作紀錄預設內容。", hold_seconds=6)
            dialog.destroy()

        ttk.Button(buttons, text="還原預設", style="PanelTool.TButton", command=reset_defaults).pack(side=tk.LEFT)
        ttk.Button(buttons, text="取消", style="PanelTool.TButton", command=dialog.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="儲存", style="Accent.TButton", command=save_settings).pack(side=tk.RIGHT, padx=(0, 8))

    def open_duty_sheet_automation(self) -> None:
        user_id = self.session.user_id if self.session and self.session.verified else self.user_id.get().strip()
        password = self.session.password if self.session and self.session.verified else self.password.get()
        open_duty_sheet_dialog(self, user_id=user_id, password=password)

    def open_rest_time_automation(self) -> None:
        user_id = self.session.user_id if self.session and self.session.verified else self.user_id.get().strip()
        password = self.session.password if self.session and self.session.verified else self.password.get()
        actor_no = self.session.actor_no if self.session and self.session.verified else self.actor_no.get().strip()
        display_name = self.current_account_display_name(actor_no, user_id) if user_id or actor_no else ""
        open_rest_time_dialog(self, user_id=user_id, password=password, actor_no=actor_no, display_name=display_name)

    def open_monthly_base_automation(self) -> None:
        user_id = self.session.user_id if self.session and self.session.verified else self.user_id.get().strip()
        password = self.session.password if self.session and self.session.verified else self.password.get()
        actor_no = self.session.actor_no if self.session and self.session.verified else self.actor_no.get().strip()
        display_name = self.current_account_display_name(actor_no, user_id) if user_id or actor_no else ""
        open_monthly_base_dialog(self, user_id=user_id, password=password, actor_no=actor_no, display_name=display_name)

    def open_daily_vehicle_automation(self) -> None:
        user_id = self.session.user_id if self.session and self.session.verified else self.user_id.get().strip()
        password = self.session.password if self.session and self.session.verified else self.password.get()
        start_daily_vehicle_automation(self, user_id=user_id, password=password)

    def set_login_buttons_enabled(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        for attr in ("login_button", "review_login_button"):
            button = getattr(self, attr, None)
            if button is not None:
                button.configure(state=state)

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

    # Duty-mode task rendering and selection

    def tick_clock(self) -> None:
        now = datetime.now()
        weekdays = "一二三四五六日"
        self.date_text.set(f"{now.year}/{now.month:02d}/{now.day:02d} ({weekdays[now.weekday()]})")
        self.time_text.set(now.strftime("%H:%M:%S"))
        if self.simple_mode.get():
            self.refresh_duty_tasks()
            self.trigger_due_tasks(now)
        self.check_scheduled_screenshot_folders(now)
        self.after(1000, self.tick_clock)

    def screenshot_folder_path(self, folder_name: str) -> Path:
        folder = Path(__file__).resolve().parent / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def show_desktop(self) -> None:
        try:
            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            try:
                shell_app = win32com.client.Dispatch("Shell.Application")
                try:
                    shell_app.MinimizeAll()
                except Exception:
                    shell_app.ToggleDesktop()
            finally:
                pythoncom.CoUninitialize()
            time.sleep(0.5)
        except Exception:
            pass

    def open_folder_topmost(self, folder: Path) -> None:
        folder = folder.resolve()
        try:
            os.startfile(str(folder))
        except Exception:
            subprocess.Popen(["explorer", str(folder)], shell=False)

        def focus_worker() -> None:
            time_limit = datetime.now() + timedelta(seconds=5)
            while datetime.now() < time_limit:
                try:
                    import pythoncom
                    import win32com.client

                    pythoncom.CoInitialize()
                    try:
                        shell_app = win32com.client.Dispatch("Shell.Application")
                        for window in shell_app.Windows():
                            try:
                                path = Path(window.Document.Folder.Self.Path).resolve()
                                if path == folder:
                                    hwnd = int(window.HWND)
                                    ctypes.windll.user32.ShowWindow(hwnd, 9)
                                    ctypes.windll.user32.SetForegroundWindow(hwnd)
                                    return
                            except Exception:
                                continue
                    finally:
                        pythoncom.CoUninitialize()
                except Exception:
                    return
                time.sleep(0.25)

        threading.Thread(target=focus_worker, daemon=True).start()

    def check_scheduled_screenshot_folders(self, now: datetime) -> None:
        schedule = {
            "1630": DAILY_SCREENSHOT_DIR,
            "2155": NIGHT_SCREENSHOT_DIR,
        }
        folder_name = schedule.get(now.strftime("%H%M"))
        if not folder_name:
            return
        slot_key = f"{now:%Y%m%d-%H%M}"
        if slot_key in self.opened_screenshot_folder_slots:
            return
        self.opened_screenshot_folder_slots.add(slot_key)
        self.show_desktop()
        self.open_folder_topmost(self.screenshot_folder_path(folder_name))

    def duty_task_indices(self) -> list[int]:
        actor_no = self.session.actor_no if self.session and self.session.verified else self.actor_no.get().strip()
        if not actor_no:
            return []
        previous_actor_nos = self.previous_duty_actor_nos(actor_no)
        indices = []
        for index, action in enumerate(self.duty_actions):
            action_actor = str(action.get("actor", ""))
            is_previous_actor_item = action_actor in previous_actor_nos and action.get("kind") == "entry_log"
            if action_actor != actor_no and not is_previous_actor_item:
                continue
            compare = self.duty_action_compare.get(index, {})
            if is_previous_actor_item and not self.should_show_previous_duty_item(compare):
                continue
            if compare.get("group") == "review" and not is_previous_actor_item:
                continue
            indices.append(index)
        return sorted(indices, key=lambda idx: self.action_datetime(self.duty_actions[idx]))

    def should_show_previous_duty_item(self, compare: dict[str, Any]) -> bool:
        if not compare:
            return True
        return compare.get("group") not in ("done", "near", "adjust", "future")

    def previous_duty_actor_nos(self, actor_no: str) -> set[str]:
        previous: set[str] = set()
        for action in self.duty_actions:
            if action.get("kind") != "entry_log":
                continue
            fields = action.get("fields", {})
            if action.get("source") != "值班交接":
                continue
            if str(action.get("target", "")) != str(actor_no):
                continue
            if fields.get("出或入", "") != "值班":
                continue
            action_actor = str(action.get("actor", ""))
            if action_actor and action_actor != str(actor_no):
                previous.add(action_actor)
        return previous

    def action_minutes(self, action: dict[str, Any]) -> int:
        value = action.get("fields", {}).get("登打時間") or action.get("fields", {}).get("工作時間") or action.get("time", "00:00")
        try:
            hour, minute = [int(part) for part in value.split(":", 1)]
        except ValueError:
            return 0
        return int(action.get("date_offset", 0) or 0) * 1440 + hour * 60 + minute

    def action_datetime(self, action: dict[str, Any]) -> datetime:
        value = action.get("fields", {}).get("登打時間") or action.get("fields", {}).get("工作時間") or action.get("time", "00:00")
        try:
            hour, minute = [int(part) for part in value.split(":", 1)]
        except ValueError:
            hour, minute = 0, 0
        extra_days, hour = divmod(hour, 24)
        try:
            base_date = parse_roc_date(self.duty_data.get("target_date") or today_roc_date())
        except ValueError:
            base_date = date.today()
        offset = int(action.get("date_offset", 0) or 0) + extra_days
        target_date = base_date + timedelta(days=offset)
        return datetime(target_date.year, target_date.month, target_date.day, hour, minute)

    def action_display_time(self, action: dict[str, Any]) -> str:
        fields = action.get("fields", {})
        value = fields.get("登打時間") or fields.get("工作時間") or action.get("time", "")
        return self.format_action_time(action, value, self.duty_data.get("target_date") or today_roc_date())

    def format_action_time(self, action: dict[str, Any], value: str, base_target_date: str) -> str:
        try:
            base_date = parse_roc_date(base_target_date)
        except ValueError:
            base_date = date.today()
        try:
            hour = int(value.split(":", 1)[0])
        except ValueError:
            hour = 0
        action_date = base_date + timedelta(days=int(action.get("date_offset", 0) or 0) + hour // 24)
        if hour >= 24:
            value = f"{hour % 24:02d}:{value.split(':', 1)[1]}"
        return f"{action_date.day}日 {value}" if action_date != base_date else value

    def action_target_roc_date(self, action: dict[str, Any], base_target_date: str | None = None) -> str:
        if action.get("submit_target_date"):
            return str(action["submit_target_date"])
        try:
            base_date = parse_roc_date(base_target_date or self.duty_data.get("target_date") or today_roc_date())
        except ValueError:
            base_date = date.today()
        value = action.get("fields", {}).get("登打時間") or action.get("fields", {}).get("工作時間") or action.get("time", "00:00")
        try:
            extra_days = int(value.split(":", 1)[0]) // 24
        except ValueError:
            extra_days = 0
        offset = int(action.get("date_offset", 0) or 0) + extra_days
        return roc_date(base_date + timedelta(days=offset))

    def submit_order_key(self, index: int, action: dict[str, Any]) -> tuple[datetime, int]:
        return self.action_datetime(action), index

    def is_auto_duty_action(self, action: dict[str, Any]) -> bool:
        if action.get("kind") == "work_log":
            return True
        if action.get("kind") != "entry_log":
            return False
        fields = action.get("fields", {})
        outin = fields.get("出或入", "")
        reason = fields.get("領用事由及地點", "")
        return outin in ("值班", "值退") or reason in ("到勤", "退勤", "休息後退勤")

    def compare_needs_manual_review(self, compare: dict[str, Any]) -> bool:
        return compare.get("group") in ("near", "adjust", "review")

    def action_compare_sync_key(self, action: dict[str, Any], base_target_date: str) -> str:
        fields = action.get("fields", {})
        scheduled_time = fields.get("系統寫入時間") or fields.get("登打時間") or fields.get("工作時間") or action.get("time", "")
        return "|".join(
            [
                self.action_target_roc_date(action, base_target_date),
                str(action.get("kind", "")),
                str(action.get("source", "")),
                str(action.get("actor", "")),
                str(action.get("target", "")),
                str(fields.get("出或入", "")),
                str(fields.get("領用事由及地點", "")),
                str(scheduled_time),
                self.action_summary(action),
            ]
        )

    def sync_duty_compare_from_audit(self) -> None:
        audit_target_date = self.data.get("target_date", "")
        duty_target_date = self.duty_data.get("target_date", "")
        if not audit_target_date or not duty_target_date:
            return
        if not self.action_compare or not self.actions or not self.duty_actions:
            return
        audit_compare_by_key = {
            self.action_compare_sync_key(action, audit_target_date): self.action_compare[index]
            for index, action in enumerate(self.actions)
            if index in self.action_compare
        }
        for index, action in enumerate(self.duty_actions):
            current = self.duty_action_compare.get(index, {})
            if current.get("group") in ("done", "manual"):
                continue
            compare = audit_compare_by_key.get(self.action_compare_sync_key(action, duty_target_date))
            if compare:
                self.duty_action_compare[index] = dict(compare)

    def manual_entry_uses_current_time(self, action: dict[str, Any]) -> bool:
        if action.get("kind") != "entry_log":
            return False
        fields = action.get("fields", {})
        outin = fields.get("出或入", "")
        reason = fields.get("領用事由及地點", "")
        if outin in ("值班", "值退") or reason in ("值班", "值退", "到勤"):
            return True
        return str(action.get("source", "")).startswith("外勤") or reason in ("休息", "休息返隊", "休息後退勤")

    def action_for_manual_submit(self, action: dict[str, Any]) -> dict[str, Any]:
        if not self.manual_entry_uses_current_time(action):
            return action
        current_now = datetime.now()
        current_time = current_now.strftime("%H:%M")
        updated = copy.deepcopy(action)
        fields = updated.setdefault("fields", {})
        fields["登打時間"] = current_time
        fields["系統寫入時間"] = current_time
        updated["time"] = current_time
        updated["submit_target_date"] = roc_date(current_now.date())
        return updated

    def pending_previous_duty_count(self, actor_no: str) -> int:
        if not actor_no:
            return 0
        return sum(
            1
            for index in self.duty_task_indices()
            if str(self.duty_actions[index].get("actor", "")) != str(actor_no)
        )

    def comparison_external_rows(self, target_roc_date: str) -> list[str]:
        comparison_data = self.load_comparison_data(target_roc_date)
        entry_source = comparison_data.get("visible_entry_rows")
        if self.duty_data.get("target_date") == target_roc_date:
            if entry_source is None:
                entry_source = self.duty_data.get("visible_entry_rows", [])
        return flatten_rows(entry_source or [], target_roc_date)

    def handoff_group_actions(self, action: dict[str, Any], target_roc_date: str) -> list[dict[str, Any]]:
        fields = action.get("fields", {})
        outin = fields.get("出或入", "")
        if action.get("kind") != "entry_log" or action.get("source") != "值班交接" or outin not in ("值班", "值退"):
            return []
        handoff_time = fields.get("系統寫入時間", action.get("time", ""))
        group = []
        for candidate in self.duty_actions:
            candidate_fields = candidate.get("fields", {})
            if candidate.get("kind") != "entry_log" or candidate.get("source") != "值班交接":
                continue
            if self.action_target_roc_date(candidate) != target_roc_date:
                continue
            if candidate_fields.get("出或入", "") not in ("值班", "值退"):
                continue
            if candidate_fields.get("系統寫入時間", candidate.get("time", "")) != handoff_time:
                continue
            group.append(candidate)
        return group

    def handoff_group_has_open_external_assignment(
        self,
        rows: list[str],
        target_roc_date: str,
        group: list[dict[str, Any]],
        current_minute: int | None,
    ) -> bool:
        if not group:
            return False
        handoff_minute = self.action_minutes(group[0])
        effective_minute = current_minute if current_minute is not None else handoff_minute
        for group_action in group:
            target_name = self.duty_staff.get(str(group_action.get("target", "")), {}).get("name", "")
            if not target_name:
                continue
            active_at_handoff = False
            returned_after_handoff = False
            events: list[tuple[int, bool]] = []
            for row in rows:
                if not row_has_primary_person(row, target_name):
                    continue
                if not any(keyword in row for keyword in ("救護", "救災", "火警", "火災", "外勤")):
                    continue
                row_minute = row_minutes(row, target_roc_date)
                if row_minute is None or row_minute > effective_minute:
                    continue
                if row_has_outin(row, "出", external_entry=True):
                    events.append((row_minute, True))
                elif row_has_outin(row, "入", external_entry=True):
                    events.append((row_minute, False))
            for row_minute, is_active in sorted(events, key=lambda item: item[0]):
                if row_minute <= handoff_minute:
                    active_at_handoff = is_active
                elif active_at_handoff and not is_active:
                    returned_after_handoff = True
                    break
            if active_at_handoff and not returned_after_handoff:
                return True
        return False

    def should_pause_due_action(self, action: dict[str, Any], target_roc_date: str, now: datetime | None = None) -> str:
        if action.get("kind") != "entry_log":
            return ""
        fields = action.get("fields", {})
        reason = fields.get("領用事由及地點", "")
        outin = fields.get("出或入", "")
        current_minute = None
        now = now or datetime.now()
        if target_roc_date == roc_date(now.date()):
            current_minute = now.hour * 60 + now.minute
        if reason not in ("退勤", "休息後退勤"):
            return ""
        external_rows = self.comparison_external_rows(target_roc_date)
        if has_open_external_assignment(external_rows, target_roc_date, self.duty_staff, action, current_minute=current_minute):
            return "未返隊，暫停登打"
        return ""

    def should_count_as_next_duty_item(
        self,
        index: int,
        action: dict[str, Any],
        compare: dict[str, Any],
        actor_no: str,
    ) -> bool:
        _, _, is_next_candidate = self.resolve_duty_task_display(index, action, compare, actor_no, datetime.now())
        return is_next_candidate

    def resolve_duty_task_display(
        self,
        index: int,
        action: dict[str, Any],
        compare: dict[str, Any],
        actor_no: str,
        now: datetime,
    ) -> tuple[str, str, bool]:
        is_previous_actor_item = actor_no and str(action.get("actor", "")) != str(actor_no)
        action_at = self.action_datetime(action)
        is_auto_candidate = bool(actor_no and str(action.get("actor", "")) == str(actor_no) and self.is_auto_duty_action(action))
        if index in self.submitting_indices:
            return "正在登打", "ready", False
        if compare.get("group") == "done":
            return compare.get("compare") or "已存在", "triggered", False
        if index in self.paused_due_indices:
            return "暫停", "manual", False
        if index in self.executed_due:
            completion_key = self.action_completion_key(action)
            status = "已手動登打" if completion_key in self.manual_completed_keys else "已登打"
            return status, "triggered", False
        if self.compare_needs_manual_review(compare):
            return compare.get("compare") or "人工確認", "manual", False
        if is_previous_actor_item:
            return "前班手動", "waiting", False
        if compare.get("group") == "manual" or not self.is_auto_duty_action(action):
            return "手動", "waiting", False
        return ("到點待執行", "ready", True) if action_at <= now else ("等待", "waiting", is_auto_candidate)

    def refresh_duty_tasks(self) -> None:
        if not hasattr(self, "duty_tree"):
            return
        self.sync_duty_compare_from_audit()
        selected = set(self.duty_tree.selection())
        self.duty_tree.delete(*self.duty_tree.get_children())
        if self.logout_cleared and not (self.session and self.session.verified):
            self.next_task_text.set("下一項任務：-")
            self.duty_status_text.set(self.active_duty_status_override() or "")
            return
        now = datetime.now()
        actor_no = self.session.actor_no if self.session and self.session.verified else self.actor_no.get().strip()
        next_item = None
        pending_previous = self.pending_previous_duty_count(actor_no) if actor_no else 0
        for index in self.duty_task_indices():
            action = self.duty_actions[index]
            compare = self.duty_action_compare.get(index, {})
            status, tag, is_next_candidate = self.resolve_duty_task_display(index, action, compare, actor_no, now)
            if next_item is None and is_next_candidate:
                next_item = action
            task_time = self.action_display_time(action)
            self.duty_tree.insert(
                "",
                tk.END,
                iid=f"duty-{index}",
                values=(
                    task_time,
                    f"{'出入' if action.get('kind') == 'entry_log' else '工作'}｜{self.duty_action_summary(action)}"
                    + (f"（{self.paused_due_indices[index]}）" if index in self.paused_due_indices else ""),
                    status,
                ),
                tags=(tag,),
            )
        kept_selection = [iid for iid in selected if self.duty_tree.exists(iid)]
        if kept_selection:
            self.duty_tree.selection_set(kept_selection)
            self.duty_tree.focus(kept_selection[0])
        if next_item:
            next_at = self.action_datetime(next_item)
            delta = max(0, int((next_at - now).total_seconds() // 60))
            self.next_task_text.set(f"{self.action_display_time(next_item)}  {self.action_summary(next_item)}，約 {delta} 分鐘後")
        elif pending_previous:
            self.next_task_text.set(f"前一班尚有 {pending_previous} 筆待手動處理")
        else:
            self.next_task_text.set("今日目前沒有未完成的當班任務")
        status_override = self.active_duty_status_override()
        if self.session and self.session.verified:
            if self.submitting_indices:
                self.duty_status_text.set("正在登打")
            elif self.paused_due_indices:
                self.duty_status_text.set(f"未返隊，暫停登打 {len(self.paused_due_indices)} 筆；返隊後請手動簽入/登打。")
            elif self.auto_logout_deadline and self.auto_logout_actor_no == str(self.session.actor_no):
                self.duty_status_text.set(f"本段已完成，預計 {self.auto_logout_deadline:%H:%M} 自動登出。")
            elif pending_previous:
                self.duty_status_text.set(f"前一班未登打 {pending_previous} 筆，請先處理；其餘工作與自動出入會到點執行。")
            elif status_override:
                self.duty_status_text.set(status_override)
            else:
                self.duty_status_text.set("登入有效；工作、值班、值退、到勤、退勤、休息後退勤會自動執行。")
        elif self.logout_cleared:
            self.duty_status_text.set(status_override or "")
        else:
            self.duty_status_text.set("尚未登入，所有任務不執行。")

    def handle_duty_tree_click(self, event: tk.Event) -> str | None:
        if not hasattr(self, "duty_tree"):
            return None
        region = self.duty_tree.identify("region", event.x, event.y)
        if region not in ("cell", "tree"):
            return None
        item = self.duty_tree.identify_row(event.y)
        if not item:
            return None
        items = list(self.duty_tree.get_children())
        current = list(self.duty_tree.selection())
        if event.state & 0x0001 and self.duty_selection_anchor in items:
            anchor_index = items.index(self.duty_selection_anchor)
            item_index = items.index(item)
            start = min(anchor_index, item_index)
            end = max(anchor_index, item_index)
            merged = list(dict.fromkeys(current + items[start : end + 1]))
            self.duty_tree.selection_set(merged)
            self.duty_tree.focus(item)
            return "break"
        if item in current:
            current.remove(item)
        else:
            current.append(item)
            self.duty_selection_anchor = item
        if current:
            self.duty_tree.selection_set(current)
            self.duty_tree.focus(item)
        else:
            self.duty_tree.selection_remove(item)
            if self.duty_selection_anchor == item:
                self.duty_selection_anchor = current[-1] if current else ""
        return "break"

    def trigger_due_tasks(self, now: datetime) -> None:
        if not self.session or not self.session.verified:
            return
        self.sync_duty_compare_from_audit()
        for index in self.duty_task_indices():
            if index in self.executed_due or index in self.submitting_indices:
                continue
            retry_after = self.failed_due_retry_after.get(index)
            if retry_after and now < retry_after:
                continue
            if retry_after and now >= retry_after:
                self.failed_due_retry_after.pop(index, None)
            action = self.duty_actions[index]
            if action.get("kind") not in ("work_log", "entry_log"):
                continue
            if str(action.get("actor", "")) != str(self.session.actor_no):
                continue
            compare = self.duty_action_compare.get(index, {})
            if compare.get("group") == "done":
                self.executed_due.add(index)
                continue
            if compare.get("group") == "manual" or self.compare_needs_manual_review(compare) or not self.is_auto_duty_action(action):
                continue
            action_at = self.action_datetime(action)
            is_paused_retry = index in self.paused_due_indices and action_at <= now
            is_due_now = action_at <= now
            if is_due_now or is_paused_retry:
                target_roc_date = self.action_target_roc_date(action)
                pause_reason = self.should_pause_due_action(action, target_roc_date, now=now)
                if pause_reason:
                    self.paused_due_indices[index] = pause_reason
                    self.refresh_duty_tasks()
                    continue
                self.paused_due_indices.pop(index, None)
                self.log_trigger(index, action, "due")
                self.submit_duty_action(index, action, save=True, visible=False, confirm=False, notify=False, trigger_type="due")

    def early_execute_selected(self) -> None:
        selection = self.duty_tree.selection()
        if not selection:
            messagebox.showinfo("手動登打", "請先選擇一筆當班任務。")
            return
        iid = selection[0]
        if not str(iid).startswith("duty-"):
            return
        index = int(str(iid).split("-", 1)[1])
        if not self.session or not self.session.verified:
            messagebox.showwarning("尚未登入", "請先登入後再手動登打。")
            return
        self.log_trigger(index, self.duty_actions[index], "manual", status="manual_marked")
        self.executed_due.add(index)
        self.manual_completed_keys.add(self.action_completion_key(self.duty_actions[index]))
        self.set_duty_status(f"已記錄待接線：{self.duty_action_summary(self.duty_actions[index])}", hold_seconds=8)
        self.refresh_duty_tasks()

    # Submit pipeline

    def save_selected_work_log_test(self) -> None:
        self.start_submit_selected(save=True, visible=False)

    def start_submit_selected(self, save: bool, visible: bool) -> None:
        selection = self.duty_tree.selection()
        if not selection:
            messagebox.showinfo("手動登打", "請先選擇一筆或多筆工作紀錄任務。")
            return
        selected_actions: list[tuple[int, dict[str, Any]]] = []
        for iid in selection:
            if not str(iid).startswith("duty-"):
                continue
            index = int(str(iid).split("-", 1)[1])
            action = self.duty_actions[index]
            if action.get("kind") in ("work_log", "entry_log"):
                selected_actions.append((index, action))
        if not selected_actions:
            messagebox.showwarning("類型不符", "目前只支援工作紀錄簿與出入登記手動登打。")
            return
        if not self.session or not self.session.verified:
            messagebox.showwarning("尚未登入", "請先登入後再手動登打。")
            return
        summaries = "\n".join(f"- {self.duty_action_summary(action)}" for _, action in selected_actions[:8])
        if len(selected_actions) > 8:
            summaries += f"\n...另 {len(selected_actions) - 8} 筆"
        if save and not messagebox.askyesno("確認手動登打", f"將登打勤務系統 {len(selected_actions)} 筆：\n{summaries}\n\n確定要繼續？"):
            return
        for index, action in sorted(selected_actions, key=lambda item: self.submit_order_key(item[0], item[1])):
            self.submit_duty_action(index, action, save=save, visible=visible, confirm=False, notify=False, trigger_type="manual")
        self.set_duty_status(f"已加入手動登打佇列：{len(selected_actions)} 筆", hold_seconds=6)

    def submit_duty_action(self, index: int, action: dict[str, Any], save: bool, visible: bool, confirm: bool, notify: bool, trigger_type: str = "manual") -> None:
        if not self.session or not self.session.verified:
            return
        if action.get("kind") not in ("work_log", "entry_log"):
            return
        if index in self.submitting_indices:
            return
        submit_kind = "出入" if action.get("kind") == "entry_log" else "工作"
        if confirm and save and not messagebox.askyesno("確認手動登打", f"將登打勤務系統{submit_kind}：\n{self.duty_action_summary(action)}\n\n確定要繼續？"):
            return
        if trigger_type == "manual":
            self.log_trigger(index, action, trigger_type)
            action = self.action_for_manual_submit(action)
        lane = self.submit_lane_for_action(action, visible, trigger_type)
        self.submitting_indices.add(index)
        self.submit_queues[lane].append((index, action, save, visible, notify, trigger_type))
        summary = self.duty_action_summary(action)
        self.duty_status_text.set(f"正在登打：{summary}")
        if trigger_type != "manual":
            self.notify_user(APP_DISPLAY_NAME, f"開始：{self.notification_action_summary(action)}")
        self.refresh_duty_tasks()
        self.start_next_submit_job(lane)

    def submit_lane_for_action(self, action: dict[str, Any], visible: bool, trigger_type: str) -> str:
        if trigger_type == "due" and not visible and action.get("kind") == "work_log" and self.work_submit_parallel_enabled:
            return "work"
        return "entry"

    def submit_queue_has_items(self) -> bool:
        return any(self.submit_queues.get(lane) for lane in ("entry", "work"))

    def start_next_submit_job(self, lane: str = "entry") -> None:
        if lane not in self.submit_queues:
            lane = "entry"
        if self.submit_worker_running.get(lane) or not self.submit_queues.get(lane) or not self.session:
            return
        index, action, save, visible, notify, trigger_type = self.submit_queues[lane].pop(0)
        self.submit_worker_running[lane] = True
        result_path = self.create_submit_result_path(index, action, save, visible)
        self.duty_status_text.set(f"正在登打：{self.duty_action_summary(action)}")
        self.refresh_duty_tasks()
        threading.Thread(target=self._save_work_log_worker, args=((index, action, result_path, save, visible, notify, trigger_type), self.session, visible, lane), daemon=True).start()

    def create_submit_result_path(self, index: int, action: dict[str, Any], save: bool, visible: bool) -> Path:
        prefix = "entry_log_form_test" if action.get("kind") == "entry_log" else "work_log_form_test"
        FORM_TEST_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        result_path = FORM_TEST_OUTPUT_DIR / f"{prefix}_{datetime.now():%Y%m%d_%H%M%S_%f}_{index}.json"
        started_result = {
            "stage": "started",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "action_index": index,
            "action": action,
            "user_id": self.session.user_id,
            "process_id": os.getpid(),
            "executable": sys.executable,
            "cwd": str(Path.cwd()),
            "summary": self.duty_action_summary(action),
            "save": save,
            "visible": visible,
        }
        result_path.write_text(json.dumps(started_result, ensure_ascii=False, indent=2), encoding="utf-8")
        mirror_runtime_file_to_cloud(result_path, "form_tests")
        return result_path

    def next_queued_submit_job(self, lane: str) -> tuple[int, dict[str, Any], Path, bool, bool, bool, str] | None:
        if not self.submit_queues.get(lane):
            return None
        index, action, save, visible, notify, trigger_type = self.submit_queues[lane].pop(0)
        return index, action, self.create_submit_result_path(index, action, save, visible), save, visible, notify, trigger_type

    def check_for_update(self) -> None:
        updater = Path(__file__).with_name("update_package.ps1")
        if not updater.exists():
            messagebox.showerror("檢查更新", f"找不到更新腳本：{updater}")
            return
        if not messagebox.askyesno(
            "檢查更新",
            "將開啟更新視窗檢查 GitHub 是否有新版。\n\n若有更新，確認後會關閉背景程式、更新並重新啟動。是否繼續？",
        ):
            return
        command = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-NoExit",
            "-File",
            str(updater),
        ]
        creationflags = subprocess.CREATE_NEW_CONSOLE if hasattr(subprocess, "CREATE_NEW_CONSOLE") else 0
        try:
            subprocess.Popen(command, cwd=str(updater.parent), creationflags=creationflags)
        except Exception as exc:
            messagebox.showerror("檢查更新", f"無法啟動更新程式：{exc}")

    def export_issue_package(self, result_path: Path | None = None, error: str | None = None, show_dialog: bool = True) -> Path:
        issue_dir = Path("issue_reports")
        issue_dir.mkdir(exist_ok=True)
        package_path = issue_dir / f"issue_report_{datetime.now():%Y%m%d_%H%M%S}.zip"
        target_dates = set()
        for data in (self.data, self.duty_data):
            if data.get("target_date"):
                target_dates.add(str(data["target_date"]))
        target_dates.add(today_roc_date())

        manifest = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "error": error or "",
            "result_path": str(result_path or ""),
            "mode": self.mode.get(),
            "login_status": self.login_status.get(),
            "duty_status": self.duty_status_text.get(),
            "target_dates": sorted(target_dates),
            "session_actor": self.session.actor_no if self.session else "",
            "session_verified": bool(self.session and self.session.verified),
        }
        with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            candidates: list[Path] = []
            for target_date in target_dates:
                candidates.extend([schedule_path(target_date), comparison_path(target_date), legacy_rehearsal_path(target_date)])
            candidates.extend([Path("duty_trigger_log.jsonl"), Path("requirements.txt"), Path("CODE_MAP.md"), Path("HANDOFF.md")])
            if result_path:
                candidates.append(result_path)
            if FORM_TEST_OUTPUT_DIR.exists():
                candidates.extend(sorted(FORM_TEST_OUTPUT_DIR.glob("*.json"), key=lambda path: path.stat().st_mtime)[-20:])
            if SNAPSHOT_OUTPUT_DIR.exists():
                candidates.extend(sorted(SNAPSHOT_OUTPUT_DIR.glob("*.json"), key=lambda path: path.stat().st_mtime)[-20:])
                candidates.extend(sorted(SNAPSHOT_OUTPUT_DIR.glob("*.txt"), key=lambda path: path.stat().st_mtime)[-10:])
            seen: set[Path] = set()
            for path in candidates:
                if not path.exists() or not path.is_file():
                    continue
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                try:
                    archive.write(path, arcname=str(path))
                except Exception:
                    continue
        if show_dialog:
            self.status_text.set(f"問題包已匯出：{package_path.name}")
            messagebox.showinfo("匯出問題包", f"已產生：{package_path}")
        return package_path

    def should_refresh_action_before_submit(self, action: dict[str, Any], target_roc_date: str) -> bool:
        return (
            target_roc_date == today_roc_date()
            and action.get("kind") == "work_log"
            and action.get("source") == "值班交接"
            and bool(action.get("duplicate_key"))
        )

    def refreshed_action_for_submit(self, driver: webdriver.Chrome, action: dict[str, Any], target_roc_date: str) -> dict[str, Any]:
        if not self.should_refresh_action_before_submit(action, target_roc_date):
            return action
        snapshot_path = self.write_schedule_snapshot(driver, target_roc_date, "pre-submit")
        try:
            data = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except Exception:
            return action
        duplicate_key = action.get("duplicate_key", "")
        for latest_action in data.get("actions", []):
            if latest_action.get("duplicate_key") == duplicate_key:
                return latest_action
        return action

    def _save_work_log_worker(self, first_job: tuple[int, dict[str, Any], Path, bool, bool, bool, str], session: LoginSession, visible: bool, lane: str = "entry") -> None:
        driver = None
        try:
            options = Options()
            if visible:
                options.add_argument("--start-maximized")
            else:
                options.add_argument("--headless=new")
            options.add_argument("--disable-popup-blocking")
            driver = webdriver.Chrome(options=options)
            login(driver, session.user_id, session.password)
            job = first_job
            duplicate_cache: dict[tuple[str, str, str], list[str]] = {}
            while job:
                index, action, result_path, save, job_visible, notify, trigger_type = job
                try:
                    target_date = self.action_target_roc_date(action)
                    action = self.refreshed_action_for_submit(driver, action, target_date)
                    duplicate_matches = self.duplicate_matches_before_submit(driver, action, target_date, duplicate_cache) if save else []
                    if duplicate_matches:
                        result = {
                            "stage": "skipped_duplicate",
                            "action_index": index,
                            "action": action,
                            "updated_at": datetime.now().isoformat(timespec="seconds"),
                            "save": save,
                            "visible": job_visible,
                            "matched": duplicate_matches[:3],
                        }
                        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                        mirror_runtime_file_to_cloud(result_path, "form_tests")
                        self.after(0, lambda idx=index, path=result_path, note=notify, origin=trigger_type: self._save_work_log_item_skipped_duplicate(idx, path, note, origin))
                        job = self.next_queued_submit_job(lane)
                        continue
                    if action.get("kind") == "entry_log":
                        result = fill_entry_log_form_for_test(driver, action, self.duty_staff, target_date, save=save)
                    else:
                        result = fill_work_log_form_for_test(driver, action, self.duty_staff, target_date, save=save)
                    result["stage"] = "submitted" if save else "filled"
                    result["action_index"] = index
                    result["action"] = action
                    result["updated_at"] = datetime.now().isoformat(timespec="seconds")
                    result["save"] = save
                    result["visible"] = job_visible
                    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                    mirror_runtime_file_to_cloud(result_path, "form_tests")
                    self.after(0, lambda idx=index, path=result_path, note=notify, origin=trigger_type: self._save_work_log_item_succeeded(idx, path, note, origin))
                except Exception as exc:
                    error = str(exc)
                    failure_result = {
                        "stage": "failed",
                        "updated_at": datetime.now().isoformat(timespec="seconds"),
                        "action_index": index,
                        "action": action,
                        "error": error,
                        "save": save,
                        "visible": job_visible,
                    }
                    result_path.write_text(json.dumps(failure_result, ensure_ascii=False, indent=2), encoding="utf-8")
                    mirror_runtime_file_to_cloud(result_path, "form_tests")
                    self.after(0, lambda idx=index, err=error, path=result_path, note=notify, origin=trigger_type: self._save_work_log_item_failed(idx, err, path, note, origin))
                job = self.next_queued_submit_job(lane)
        except Exception as exc:
            error = str(exc)
            index, action, result_path, save, job_visible, notify, trigger_type = first_job
            if lane == "work":
                self.after(0, lambda raw=(index, action, save, job_visible, notify, trigger_type), err=error: self.fallback_work_submit_to_entry(raw, err))
                return
            failure_result = {
                "stage": "failed",
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "action_index": index,
                "action": action,
                "error": error,
                "save": save,
                "visible": job_visible,
            }
            result_path.write_text(json.dumps(failure_result, ensure_ascii=False, indent=2), encoding="utf-8")
            mirror_runtime_file_to_cloud(result_path, "form_tests")
            self.after(0, lambda: self._save_work_log_item_failed(index, error, result_path, notify, trigger_type))
        finally:
            if driver:
                driver.quit()
            self.after(0, lambda value=lane: self._submit_worker_finished(value))

    def _save_work_log_item_succeeded(self, index: int, result_path: Path, notify: bool, trigger_type: str) -> None:
        self.submitting_indices.discard(index)
        compare_text = "已手動登打" if trigger_type == "manual" else "已登打"
        completion_key = self.action_completion_key(self.duty_actions[index])
        if trigger_type == "manual":
            self.executed_due.add(index)
            self.manual_completed_keys.add(completion_key)
        elif trigger_type == "due":
            self.executed_due.add(index)
        self.log_trigger(index, self.duty_actions[index], trigger_type, status="submitted", completion_key=completion_key)
        self.failed_due_retry_after.pop(index, None)
        if self.should_schedule_auto_logout(self.duty_actions[index], trigger_type) and self.session and self.session.verified:
            self.schedule_auto_logout(self.session.actor_no, self.duty_actions[index])
        self.duty_action_compare[index] = {"compare": compare_text, "group": "done", "matched": []}
        self.set_duty_status(compare_text, hold_seconds=6)
        if trigger_type != "manual":
            self.notify_user(APP_DISPLAY_NAME, f"完成：{self.notification_action_summary(self.duty_actions[index])}")
        if notify:
            messagebox.showinfo("手動登打", f"{compare_text}。")
        if self.duty_data.get("target_date"):
            self.submit_needs_comparison_refresh = True
            self.submit_comparison_refresh_dates.add(self.action_target_roc_date(self.duty_actions[index]))
        self.refresh_duty_tasks()
        self.refresh_tasks()

    def _save_work_log_item_skipped_duplicate(self, index: int, result_path: Path, notify: bool, trigger_type: str) -> None:
        self.submitting_indices.discard(index)
        self.executed_due.add(index)
        completion_key = self.action_completion_key(self.duty_actions[index])
        if trigger_type == "manual":
            self.manual_completed_keys.add(completion_key)
        self.log_trigger(index, self.duty_actions[index], trigger_type, status="skipped_duplicate", completion_key=completion_key)
        self.failed_due_retry_after.pop(index, None)
        if self.should_schedule_auto_logout(self.duty_actions[index], trigger_type) and self.session and self.session.verified:
            self.schedule_auto_logout(self.session.actor_no, self.duty_actions[index])
        self.duty_action_compare[index] = {"compare": "已存在", "group": "done", "matched": []}
        self.set_duty_status(f"已存在，略過登打：{result_path.name}", hold_seconds=8)
        self.notify_user(APP_DISPLAY_NAME, f"已存在略過：{self.notification_action_summary(self.duty_actions[index])}")
        if notify:
            messagebox.showinfo("防重複", f"查詢到既有紀錄，已略過登打。\n\n結果檔：{result_path.name}")
        if self.duty_data.get("target_date"):
            self.submit_needs_comparison_refresh = True
            self.submit_comparison_refresh_dates.add(self.action_target_roc_date(self.duty_actions[index]))
        self.refresh_duty_tasks()
        self.refresh_tasks()

    def _save_work_log_item_failed(self, index: int, error: str, result_path: Path, notify: bool, trigger_type: str) -> None:
        self.submitting_indices.discard(index)
        self.log_trigger(index, self.duty_actions[index], trigger_type, status="failed")
        if trigger_type == "due":
            self.failed_due_retry_after[index] = datetime.now() + timedelta(minutes=1)
        try:
            package_path = self.export_issue_package(result_path=result_path, error=error, show_dialog=False)
            package_note = f"，問題包：{package_path.name}"
        except Exception:
            package_note = ""
        self.set_duty_status(f"登打失敗：{error}，結果：{result_path.name}{package_note}", hold_seconds=12)
        self.notify_user(APP_DISPLAY_NAME, f"登打失敗：{error}\n結果：{result_path.name}{package_note}", duration_ms=6500)
        if notify:
            messagebox.showerror("登打失敗", f"{error}\n\n結果檔：{result_path.name}{package_note}")
        self.refresh_duty_tasks()

    def fallback_work_submit_to_entry(self, first_job: tuple[int, dict[str, Any], bool, bool, bool, str], error: str) -> None:
        self.work_submit_parallel_enabled = False
        remaining_work = self.submit_queues.get("work", [])
        self.submit_queues["work"] = []
        self.submit_queues["entry"] = [first_job, *remaining_work, *self.submit_queues.get("entry", [])]
        self.set_duty_status(f"工作背景登入失敗，改用單佇列順序登打：{error}", hold_seconds=10)
        self.start_next_submit_job("entry")

    def _submit_worker_finished(self, lane: str = "entry") -> None:
        self.submit_worker_running[lane] = False
        if self.submit_needs_comparison_refresh and not self.submit_queue_has_items() and self.duty_data.get("target_date"):
            self.submit_needs_comparison_refresh = False
            self.schedule_submit_comparison_refresh()
        self.refresh_duty_tasks()
        self.start_next_submit_job(lane)

    def schedule_submit_comparison_refresh(self) -> None:
        if self.submit_comparison_refresh_scheduled:
            return
        self.submit_comparison_refresh_scheduled = True
        self.after(30000, self.run_submit_comparison_refresh)

    def run_submit_comparison_refresh(self) -> None:
        self.submit_comparison_refresh_scheduled = False
        if not self.submit_comparison_refresh_dates or not (self.session and self.session.verified):
            return
        if self.comparison_running:
            self.schedule_submit_comparison_refresh()
            return
        comparison_dates = sorted(self.submit_comparison_refresh_dates)
        self.submit_comparison_refresh_dates.clear()
        target_roc_date = self.duty_data.get("target_date") or comparison_dates[0]
        self.refresh_comparison_background(target_roc_date, "early-submit", comparison_dates=comparison_dates)

    def log_trigger(self, index: int, action: dict[str, Any], trigger_type: str, status: str = "pending_write_automation", completion_key: str = "") -> None:
        session = self.session
        record = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "trigger_type": trigger_type,
            "action_index": index,
            "actor_no": session.actor_no if session else "",
            "user_id": session.user_id if session else "",
            "target_date": self.duty_data.get("target_date", ""),
            "kind": action.get("kind", ""),
            "time": action.get("time", ""),
            "source": action.get("source", ""),
            "target": action.get("target", ""),
            "fields": action.get("fields", {}),
            "process_id": os.getpid(),
            "executable": sys.executable,
            "cwd": str(Path.cwd()),
            "status": status,
            "completion_key": completion_key or self.action_completion_key(action),
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with Path("duty_trigger_log.jsonl").open("a", encoding="utf-8") as f:
            f.write(line)
        append_runtime_jsonl_to_cloud("duty_trigger_log.jsonl", line)

    # Mode switching and audit table rendering

    def apply_mode(self) -> None:
        for widget in (self.top_frame, self.login_box, self.summary_frame, self.tools_frame, self.tree, self.bottom_frame):
            widget.pack_forget()
        if self.audit_bottom_frame is not None:
            self.audit_bottom_frame.pack_forget()
        for widget in self.duty_widgets:
            widget.pack_forget()

        self.mode.set("值班模式" if self.simple_mode.get() else "審核模式")
        if self.simple_mode.get():
            self.geometry("440x720")
            self.minsize(420, 700)
            self.filter_actor.set(True)
            if self.status_filter.get() not in ("需處理", "全部", "已存在", "手動", "尚未到點", "可能臨時調整", "時間近似", "人工確認"):
                self.status_filter.set("需處理")
            self.title(f"{APP_DISPLAY_NAME} - 值班模式")
            self.duty_widgets[0].pack(fill=tk.BOTH, expand=True)
        else:
            self.geometry("780x650")
            self.minsize(720, 560)
            self.filter_actor.set(False)
            self.status_filter.set("需處理")
            self.title(f"{APP_DISPLAY_NAME} - 審核模式")
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
            elif group in ("review", "adjust", "manual"):
                counts["review"] += 1
            elif group == "done":
                counts["done"] += 1
            elif group == "future":
                counts["ready"] += 1
            if not self.status_matches_filter(run_status, compare):
                continue
            visible += 1
            fields = action.get("fields", {})
            execute_value = fields.get("登打時間") or fields.get("工作時間") or action.get("time", "")
            execute_time = self.format_action_time(action, execute_value, self.data.get("target_date") or today_roc_date())
            tag = self.tree_tag(run_status, compare)
            kind_label = "案件工作" if action.get("source") == "案件工作審核" else ("出入" if action.get("kind") == "entry_log" else "工作")
            self.tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(
                    compare.get("compare", ""),
                    execute_time,
                    self.person_short_label(actor),
                    self.target_short_label(action),
                    kind_label,
                    self.action_summary(action),
                ),
                tags=(tag,),
            )
        self.status_text.set(f"顯示 {visible} / {len(self.actions)} 筆。")
        self.summary_vars["todo"].set(f"未找到 {counts['todo']}")
        self.summary_vars["review"].set(f"人工確認 {counts['review']}")
        self.summary_vars["ready"].set(f"尚未到點 {counts['ready']}")
        self.summary_vars["done"].set(f"已存在 {counts['done']}")

    def kind_matches_filter(self, action: dict[str, Any]) -> bool:
        value = self.kind_filter.get()
        if value == "全部":
            return True
        if value == "案件工作":
            return action.get("source") == "案件工作審核"
        if value == "出入":
            return action.get("kind") == "entry_log"
        if value == "工作":
            return action.get("kind") == "work_log" and action.get("source") != "案件工作審核"
        return True

    def action_status(self, actor: str, compare: dict[str, Any]) -> str:
        if compare.get("group") == "done":
            return "略過"
        if compare.get("group") == "review":
            return "人工確認"
        if compare.get("group") == "manual":
            return "手動"
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
            return compare.get("group") in ("todo", "review", "adjust", "manual")
        if value == "已存在":
            return compare.get("group") == "done"
        if value == "時間近似":
            return compare.get("group") == "near"
        if value == "人工確認":
            return compare.get("group") == "review"
        if value == "手動":
            return compare.get("group") == "manual"
        if value == "尚未到點":
            return compare.get("group") == "future"
        if value == "可能臨時調整":
            return compare.get("group") == "adjust"
        return run_status == value

    def tree_tag(self, run_status: str, compare: dict[str, Any]) -> str:
        group = compare.get("group")
        if group in ("todo", "review", "near", "done", "future", "adjust", "manual"):
            return group
        if run_status == "可執行":
            return "ready"
        return ""

    # Labels, summaries, and detail rendering

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
        if action.get("source") in ("無線電試話", "無線電測試"):
            return "其他/無線電試話"
        if action.get("source") == "案件工作審核":
            return fields.get("事由", "")
        if action.get("kind") == "entry_log":
            return f"{fields.get('出或入', '')} / {fields.get('領用事由及地點', '')}"
        item = fields.get("勤務項目", "")
        reason = fields.get("事由", "")
        topic = fields.get("訓練項目", "")
        return " / ".join(part for part in (item, reason, topic) if part)

    def duty_action_summary(self, action: dict[str, Any]) -> str:
        fields = action.get("fields", {})
        if action.get("source") == "在隊訓練":
            topic = fields.get("訓練項目") or self.action_summary(action)
            return f"在隊訓練｜{topic}"
        if action.get("kind") == "entry_log":
            return f"{self.action_summary(action)}｜{self.target_short_label(action)}"
        return f"{self.action_summary(action)}｜{self.target_short_label(action)}"

    def notification_action_summary(self, action: dict[str, Any]) -> str:
        fields = action.get("fields", {})
        action_time = self.action_display_time(action)
        targets = self.target_short_label(action)
        if action.get("kind") == "entry_log":
            reason = fields.get("領用事由及地點", "") or fields.get("出或入", "")
            return f"{action_time} {reason}：{targets}"
        if action.get("source") == "在隊訓練":
            topic = fields.get("訓練項目") or "在隊訓練"
            return f"{action_time} 在隊訓練：{topic}"
        summary = self.action_summary(action)
        return f"{action_time} {summary}：{targets}" if targets else f"{action_time} {summary}"

    def show_selected_detail(self, _event: tk.Event | None = None) -> None:
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
    if not acquire_single_instance_lock():
        signal_existing_instance()
        return
    set_windows_app_user_model_id()
    ensure_windows_notification_shortcut()
    app = DutyGui()
    start_single_instance_command_server(app)
    app.mainloop()


if __name__ == "__main__":
    main()
