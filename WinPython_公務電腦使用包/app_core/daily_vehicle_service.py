# -*- coding: utf-8 -*-
"""UI-independent process boundary for daily vehicle automation."""

from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable


AUTOMATION_SCRIPT = Path("automation") / "ppe_selenium_daily.py"
RUNNING_PID_FILE = ".daily_vehicle_runner.pid"
DEFAULT_TIMEOUT_SECONDS = 15 * 60


class DailyVehicleValidationError(ValueError):
    """A safe request-validation message for the native form."""


class DailyVehicleExecutionError(RuntimeError):
    """A safe execution failure for the native form."""

    def __init__(self, message: str, *, failure_stage: str = "unknown") -> None:
        super().__init__(message)
        self.failure_stage = failure_stage


@dataclass(frozen=True)
class DailyVehicleDefaults:
    target_date: str
    operations: tuple[str, ...]


@dataclass(frozen=True)
class DailyVehicleRequest:
    user_id: str
    password: str = field(repr=False)


class DailyVehicleService:
    def __init__(
        self,
        package_root: Path,
        *,
        process_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
        process_checker: Callable[[int], bool] | None = None,
    ) -> None:
        self.package_root = Path(package_root)
        self.process_factory = process_factory
        self.process_checker = process_checker or self._is_process_running

    def load_defaults(self, today: date | None = None) -> DailyVehicleDefaults:
        current = today or date.today()
        return DailyVehicleDefaults(
            target_date=current.strftime("%Y/%m/%d"),
            operations=("車輛保養檢查", "車輛器材清點"),
        )

    def validate(self, request: DailyVehicleRequest) -> DailyVehicleRequest:
        if not str(request.user_id or "").strip() or not request.password:
            raise DailyVehicleValidationError("請先完成勤務系統登入。")
        project_dir = self._project_dir()
        if project_dir is None:
            raise DailyVehicleValidationError("找不到車輛保養清點自動化專案。")
        running_pid = self._read_running_pid(project_dir)
        if running_pid and self.process_checker(running_pid):
            raise DailyVehicleValidationError("車輛保養清點目前正在執行。")
        if running_pid:
            self._clear_running_pid(project_dir, running_pid)
        return DailyVehicleRequest(request.user_id.strip(), request.password)

    def confirmation_summary(self, request: DailyVehicleRequest) -> str:
        self.validate(request)
        return "將開啟瀏覽器執行車輛保養清點，是否繼續？"

    def execute(
        self,
        request: DailyVehicleRequest,
        *,
        status_callback: Callable[[str], None] | None = None,
        stage_callback: Callable[[str], None] | None = None,
    ) -> str:
        stage = "preflight"

        def report_stage(value: str) -> None:
            nonlocal stage
            stage = value
            if stage_callback is not None:
                stage_callback(value)

        report_stage(stage)
        request = self.validate(request)
        project_dir = self._project_dir()
        if project_dir is None:
            raise DailyVehicleExecutionError("找不到車輛保養清點自動化專案。")
        script_path = project_dir / AUTOMATION_SCRIPT
        environment = dict(os.environ)
        environment.update(
            {
                "PPE_ACCOUNT": request.user_id,
                "PPE_PASSWORD": request.password,
                "HEADLESS": "false",
                "KEEP_BROWSER_OPEN": "true",
                "SELENIUM_REMOTE_URL": "",
            }
        )
        if status_callback:
            status_callback("正在開啟瀏覽器執行車輛保養與器材清點…")
        process = None
        try:
            report_stage("process_start")
            process = self.process_factory(
                [sys.executable, "-u", str(script_path)],
                cwd=str(project_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=environment,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._write_running_pid(project_dir, process.pid)
            try:
                report_stage("process_running")
                output = self._wait_for_process_exit(process, status_callback)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                self._close_process_stdout(process)
                raise DailyVehicleExecutionError(
                    "車輛保養清點執行逾時。",
                    failure_stage=stage,
                ) from exc
            if process.returncode != 0:
                stage = self._failure_stage_from_output(output, stage)
                message = self._browser_startup_safe_error(output) or self._safe_error(output)
                raise DailyVehicleExecutionError(message, failure_stage=stage)
            report_stage("result_evaluation")
            return "車輛保養清點已完成。"
        except DailyVehicleExecutionError:
            raise
        except OSError as exc:
            raise DailyVehicleExecutionError(
                "無法啟動車輛保養清點程式。",
                failure_stage=stage,
            ) from exc
        finally:
            if process is not None:
                self._clear_running_pid(project_dir, process.pid)

    def _project_dir(self) -> Path | None:
        configured = str(os.environ.get("SINPOSMART_DAILY_VEHICLE_PROJECT", "") or "").strip()
        candidates = [Path(configured).expanduser()] if configured else []
        candidates.append(self.package_root / "daily_vehicle_legacy")
        for candidate in candidates:
            resolved = candidate.resolve()
            if (resolved / AUTOMATION_SCRIPT).is_file():
                return resolved
        return None

    @staticmethod
    def _safe_error(output: str) -> str:
        text = str(output or "")[-3000:]
        lowered = text.lower()
        if any(marker in text for marker in ("登入失敗", "帳號或密碼", "重新登入")):
            return "登入失敗：帳號或密碼可能已變更，請登出後重新登入系統。"
        if "timeout" in lowered or "timed out" in lowered or "逾時" in text:
            return "網頁等待逾時：網站可能變慢或頁面結構已變更。"
        if "nosuchelement" in lowered or "no such element" in lowered:
            return "找不到網頁元素：網站可能已改版。"
        return "車輛保養清點執行失敗，請檢查網站狀態。"

    @staticmethod
    def _browser_startup_safe_error(output: str) -> str:
        if "SinpoSmart 專用瀏覽器啟動失敗" in str(output or ""):
            return (
                "SinpoSmart 專用瀏覽器啟動失敗，已自動清理暫存資料並重試。"
                "一般 Chrome 不需關閉；若仍失敗，請先在 NAS 值班後台查看工具卡片的錯誤詳情。"
            )
        return ""

    @staticmethod
    def _failure_stage_from_output(output: str, fallback: str) -> str:
        stages = re.findall(
            r"^\[sinposmart-stage\]\s+([a-z0-9_]+)\s*$",
            str(output or ""),
            re.MULTILINE,
        )
        return stages[-1] if stages else fallback

    def _wait_for_process_exit(
        self,
        process: subprocess.Popen,
        status_callback: Callable[[str], None] | None,
    ) -> str:
        """Return when the automation Python process exits, not when retained Chrome closes stdout."""
        stdout = getattr(process, "stdout", None)
        if stdout is None:
            output, _ = process.communicate(timeout=self._timeout_seconds())
            return str(output or "")

        output_lines: list[str] = []
        output_queue: queue.Queue[str | None] = queue.Queue()

        def read_stdout() -> None:
            try:
                for line in iter(stdout.readline, ""):
                    output_queue.put(str(line))
            except (OSError, ValueError):
                pass
            finally:
                output_queue.put(None)

        reader = threading.Thread(target=read_stdout, name="daily-vehicle-output", daemon=True)
        reader.start()
        timeout_seconds = self._timeout_seconds()
        deadline = time.monotonic() + timeout_seconds
        while process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired("daily_vehicle", timeout_seconds)
            try:
                line = output_queue.get(timeout=min(0.2, remaining))
            except queue.Empty:
                continue
            if line is not None:
                self._record_output_line(output_lines, line, status_callback)

        while True:
            try:
                line = output_queue.get_nowait()
            except queue.Empty:
                break
            if line is not None:
                self._record_output_line(output_lines, line, status_callback)
        self._close_process_stdout(process)
        return "".join(output_lines)

    @staticmethod
    def _close_process_stdout(process: subprocess.Popen) -> None:
        try:
            stdout = getattr(process, "stdout", None)
            if stdout is not None:
                stdout.close()
        except (OSError, ValueError):
            pass

    @staticmethod
    def _record_output_line(
        output_lines: list[str],
        line: str,
        status_callback: Callable[[str], None] | None,
    ) -> None:
        output_lines.append(line)
        if len(output_lines) > 500:
            del output_lines[:-500]
        if status_callback is None:
            return
        stage = re.search(r"^\[sinposmart-stage\]\s+([a-z0-9_]+)\s*$", line.strip())
        messages = {
            "browser_start": "正在啟動專用瀏覽器…",
            "login": "正在登入車輛保養系統…",
            "maintenance_check": "正在執行車輛保養檢查…",
            "equipment_check": "正在執行隨車器材清點…",
        }
        if stage is not None and stage.group(1) in messages:
            status_callback(messages[stage.group(1)])

    @staticmethod
    def _timeout_seconds() -> int:
        raw = os.environ.get("SINPOSMART_DAILY_VEHICLE_TIMEOUT_SECONDS") or os.environ.get(
            "SINPOSMART_TOOL_TIMEOUT_SECONDS", ""
        )
        try:
            return max(60, int(raw or DEFAULT_TIMEOUT_SECONDS))
        except ValueError:
            return DEFAULT_TIMEOUT_SECONDS

    @staticmethod
    def _pid_path(project_dir: Path) -> Path:
        return project_dir / RUNNING_PID_FILE

    def _read_running_pid(self, project_dir: Path) -> int | None:
        try:
            return int(self._pid_path(project_dir).read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    def _write_running_pid(self, project_dir: Path, pid: int) -> None:
        self._pid_path(project_dir).write_text(f"{pid}\n", encoding="utf-8")

    def _clear_running_pid(self, project_dir: Path, pid: int) -> None:
        path = self._pid_path(project_dir)
        try:
            current = int(path.read_text(encoding="utf-8").strip())
            if current == pid:
                path.unlink()
        except (OSError, ValueError):
            pass

    @staticmethod
    def _is_process_running(pid: int) -> bool:
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
        except OSError:
            return False
        return f'"{pid}"' in result.stdout or f",{pid}," in result.stdout
