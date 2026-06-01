# -*- coding: utf-8 -*-
"""Background launcher for the local daily-vehicle automation workflow."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import messagebox
import tkinter as tk


PACKAGED_PROJECT_DIR = "daily_vehicle_legacy"
LEGACY_PROJECT_DIR = "每日車輛"
ENV_PROJECT_DIR = "SINPOSMART_DAILY_VEHICLE_PROJECT"
AUTOMATION_SCRIPT = Path("automation") / "ppe_selenium_daily.py"
ENV_EXAMPLE = ".env.example"
RUNNING_PID_FILE = ".daily_vehicle_runner.pid"
WINDOW_TITLE = "SinpoSmart - 車輛保養清點"

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


def write_env_file(path: Path, values: dict[str, str]) -> None:
    lines = [f"{key}={value}" for key, value in values.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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


def start_daily_vehicle_automation(parent: tk.Tk, user_id: str = "", password: str = "") -> None:
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

    env_path = project_dir / ".env"
    default_env = load_dotenv_like(project_dir / ENV_EXAMPLE)
    current_env = {**default_env, **load_dotenv_like(env_path)}
    env_values = {
        **current_env,
        "PPE_ACCOUNT": account,
        "PPE_PASSWORD": pwd,
        "HEADLESS": "false",
        "KEEP_BROWSER_OPEN": "true",
        "SELENIUM_REMOTE_URL": "",
    }
    write_env_file(env_path, env_values)

    command = [sys.executable, "-u", str(script_path)]
    set_running(project_dir, True)

    def worker() -> None:
        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                command,
                cwd=project_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env={**os.environ, **env_values},
            )
            set_running(project_dir, True, process.pid)
            return_code = process.wait()
            if return_code == 0:
                parent.after(0, lambda: messagebox.showinfo(WINDOW_TITLE, "車輛保養清點已完成。", parent=parent))
            else:
                parent.after(0, lambda: messagebox.showerror(WINDOW_TITLE, f"車輛保養清點執行失敗，代碼：{return_code}", parent=parent))
        except Exception as exc:
            parent.after(0, lambda: messagebox.showerror(WINDOW_TITLE, f"車輛保養清點啟動失敗：{exc}", parent=parent))
        finally:
            set_running(project_dir, False, process.pid if process else None)

    threading.Thread(target=worker, daemon=True).start()
