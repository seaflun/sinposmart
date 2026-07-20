# -*- coding: utf-8 -*-
"""Background launcher for the local daily-vehicle automation workflow."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from tkinter import messagebox
import tkinter as tk
from typing import Callable


PACKAGED_PROJECT_DIR = "daily_vehicle_legacy"
LEGACY_PROJECT_DIR = "每日車輛"
ENV_PROJECT_DIR = "SINPOSMART_DAILY_VEHICLE_PROJECT"
AUTOMATION_SCRIPT = Path("automation") / "ppe_selenium_daily.py"
ENV_EXAMPLE = ".env.example"
RUNNING_PID_FILE = ".daily_vehicle_runner.pid"
WINDOW_TITLE = "SinpoSmart - 車輛保養清點"
OUTPUT_TAIL_LIMIT = 3000
DEFAULT_AUTOMATION_TIMEOUT_SECONDS = 15 * 60
BROWSER_CLOSE_DELAY_SECONDS = 10 * 60
AUTOMATION_COMPLETED_MARKER = "[automation] work-complete"
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

_RUNNING_PROJECTS: set[str] = set()
_RUNNING_LOCK = threading.Lock()


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
        if (project_dir / AUTOMATION_SCRIPT).exists():
            return project_dir
    return None


def load_dotenv_like(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def output_tail(output: str, limit: int = OUTPUT_TAIL_LIMIT) -> str:
    output = (output or "").strip()
    if not output:
        return "沒有輸出內容。"
    if len(output) <= limit:
        return output
    return "...\n" + output[-limit:]


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


def automation_timeout_seconds() -> int:
    raw_value = os.environ.get("SINPOSMART_DAILY_VEHICLE_TIMEOUT_SECONDS") or os.environ.get("SINPOSMART_TOOL_TIMEOUT_SECONDS", "")
    try:
        return max(60, int(raw_value or DEFAULT_AUTOMATION_TIMEOUT_SECONDS))
    except ValueError:
        return DEFAULT_AUTOMATION_TIMEOUT_SECONDS


def running_pid_path(project_dir: Path) -> Path:
    return project_dir / RUNNING_PID_FILE


def read_running_pid(project_dir: Path) -> int | None:
    pid_path = running_pid_path(project_dir)
    if not pid_path.exists():
        return None
    try:
        return int(pid_path.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def write_running_pid(project_dir: Path, pid: int) -> None:
    running_pid_path(project_dir).write_text(f"{pid}\n", encoding="utf-8")


def clear_running_pid(project_dir: Path, pid: int | None = None) -> None:
    pid_path = running_pid_path(project_dir)
    if not pid_path.exists():
        return
    if pid is not None:
        current_pid = read_running_pid(project_dir)
        if current_pid is not None and current_pid != pid:
            return
    try:
        pid_path.unlink()
    except OSError:
        pass


def is_process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return False
    return f'"{pid}"' in result.stdout or f",{pid}," in result.stdout


def is_running(project_dir: Path) -> bool:
    with _RUNNING_LOCK:
        if str(project_dir).lower() in _RUNNING_PROJECTS:
            return True
    pid = read_running_pid(project_dir)
    if pid and is_process_running(pid):
        return True
    clear_running_pid(project_dir, pid)
    return False


def set_running(project_dir: Path, running: bool, pid: int | None = None) -> None:
    key = str(project_dir).lower()
    with _RUNNING_LOCK:
        if running:
            _RUNNING_PROJECTS.add(key)
        else:
            _RUNNING_PROJECTS.discard(key)
    if running and pid:
        write_running_pid(project_dir, pid)
    elif not running:
        clear_running_pid(project_dir, pid)


def start_daily_vehicle_automation(parent: tk.Tk, user_id: str = "", password: str = "", on_start: Callable[[], None] | None = None, on_finish: Callable[[str], None] | None = None, on_error: Callable[[str], None] | None = None) -> None:
    base_dir = Path(__file__).resolve().parent
    project_dir = find_project_dir(base_dir)
    if project_dir is None:
        searched = "\n".join(str(path) for path in candidate_project_dirs(base_dir))
        messagebox.showerror(WINDOW_TITLE, f"找不到車輛保養清點專案，已搜尋：\n{searched}", parent=parent)
        return

    script_path = project_dir / AUTOMATION_SCRIPT
    if not script_path.exists():
        messagebox.showerror(WINDOW_TITLE, f"找不到自動化腳本：\n{script_path}", parent=parent)
        return

    account = user_id.strip()
    pwd = password
    if not account or not pwd:
        messagebox.showwarning(WINDOW_TITLE, "請先在外層登入後再執行車輛保養清點。", parent=parent)
        return

    if is_running(project_dir):
        messagebox.showinfo(WINDOW_TITLE, "車輛保養清點目前正在執行。", parent=parent)
        return

    if not messagebox.askyesno(WINDOW_TITLE, "將開啟瀏覽器執行車輛保養清點，是否繼續？", parent=parent):
        return

    if on_start is not None:
        on_start()
    default_env = load_dotenv_like(project_dir / ENV_EXAMPLE)
    current_env = {**default_env, **load_dotenv_like(project_dir / ".env")}
    env_values = {
        **current_env,
        "PPE_ACCOUNT": account,
        "PPE_PASSWORD": pwd,
        "HEADLESS": "false",
        "KEEP_BROWSER_OPEN": "false",
        "BROWSER_CLOSE_DELAY_SECONDS": str(BROWSER_CLOSE_DELAY_SECONDS),
        "SELENIUM_REMOTE_URL": "",
    }

    command = [sys.executable, "-u", str(script_path)]
    set_running(project_dir, True)

    def run_on_parent(callback) -> None:
        try:
            if parent.winfo_exists():
                parent.after(0, lambda: callback() if parent.winfo_exists() else None)
        except tk.TclError:
            pass

    def worker() -> None:
        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                command,
                cwd=project_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env={**os.environ, **env_values},
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            set_running(project_dir, True, process.pid)
            output_lines: list[str] = []
            completion_seen = threading.Event()

            def read_output() -> None:
                if process is None or process.stdout is None:
                    return
                for line in process.stdout:
                    output_lines.append(line)
                    if AUTOMATION_COMPLETED_MARKER in line:
                        completion_seen.set()

            output_reader = threading.Thread(target=read_output, daemon=True)
            output_reader.start()
            completed_notified = False
            deadline = time.monotonic() + automation_timeout_seconds()
            while process.poll() is None:
                if completion_seen.is_set() and not completed_notified:
                    completed_notified = True
                    deadline = time.monotonic() + BROWSER_CLOSE_DELAY_SECONDS + 60
                    if on_finish is not None:
                        on_finish("車輛保養清點已完成。")
                    run_on_parent(lambda: messagebox.showinfo(WINDOW_TITLE, "車輛保養清點已完成，瀏覽器將於 10 分鐘後自動關閉。", parent=parent))
                if time.monotonic() >= deadline:
                    process.kill()
                    process.wait(timeout=10)
                    output_reader.join(timeout=5)
                    raise RuntimeError(f"車輛保養清點逾時未完成，已超過 {automation_timeout_seconds()} 秒。")
                time.sleep(0.1)
            output_reader.join(timeout=5)
            output = "".join(output_lines)
            return_code = process.returncode
            if return_code == 0:
                if not completed_notified:
                    if on_finish is not None:
                        on_finish("車輛保養清點已完成。")
                    run_on_parent(lambda: messagebox.showinfo(WINDOW_TITLE, "車輛保養清點已完成。", parent=parent))
            else:
                detail = output_tail(output)
                raw_error = f"車輛保養清點執行失敗，代碼：{return_code}；{detail}"
                print(f"[automation-error] daily_vehicle: {raw_error}", file=sys.stderr)
                error = format_automation_error(raw_error)
                if on_error is not None:
                    on_error(error)
                run_on_parent(lambda: messagebox.showerror(WINDOW_TITLE, error, parent=parent))
        except Exception as exc:
            log_automation_exception("daily_vehicle", exc)
            error = format_automation_error(exc)
            if on_error is not None:
                on_error(error)
            run_on_parent(lambda: messagebox.showerror(WINDOW_TITLE, error, parent=parent))
        finally:
            set_running(project_dir, False, process.pid if process else None)

    threading.Thread(target=worker, daemon=True).start()
