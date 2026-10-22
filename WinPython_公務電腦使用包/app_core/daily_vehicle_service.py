# -*- coding: utf-8 -*-
"""UI-independent process boundary for daily vehicle automation."""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Callable
from app_core.duty_task_projection import parse_roc_date


AUTOMATION_SCRIPT = Path("automation") / "ppe_selenium_daily.py"
RUNNING_PID_FILE = ".daily_vehicle_runner.pid"
DEFAULT_TIMEOUT_SECONDS = 15 * 60
VEHICLE_REPORT_PREFIX = "[sinposmart-vehicle-report] "
VEHICLE_REPORT_REASONS = frozenset({
    "verified_today", "saved_verified", "empty_list", "today_not_found", "state_unconfirmed",
    "save_unconfirmed", "list_changed", "execution_unconfirmed", "report_missing",
    "report_invalid", "unexpected_error", "row_limit",
})
POSITIVE_REPORT_REASONS = frozenset({"verified_today", "saved_verified"})


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
    target_date: str = ""


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
        self._completion_report: dict = {}

    @property
    def completion_report(self) -> dict:
        return deepcopy(self._completion_report)

    @staticmethod
    def _unconfirmed_report(target_date: str, reason_code: str = "report_missing") -> dict:
        return {"target_date": target_date, "verified": False, "reason_code": reason_code, "items": []}

    def load_defaults(self, today: date | None = None) -> DailyVehicleDefaults:
        current = today or date.today()
        return DailyVehicleDefaults(
            target_date=current.strftime("%Y/%m/%d"),
            operations=("車輛保養檢查", "車輛器材清點"),
        )

    def validate(self, request: DailyVehicleRequest) -> DailyVehicleRequest:
        if not str(request.user_id or "").strip() or not request.password:
            raise DailyVehicleValidationError("請先完成勤務系統登入。")
        try:
            raw_date = str(request.target_date or "").strip()
            target_date = (date.fromisoformat(raw_date.replace("/", "-")) if len(raw_date) == 10
                           else parse_roc_date(raw_date)) if raw_date else date.today()
        except (ValueError, TypeError):
            raise DailyVehicleValidationError("車輛保養清點日期格式不正確。") from None
        if target_date != date.today():
            raise DailyVehicleValidationError("每日點車已跨日，未執行，請人工確認。")
        project_dir = self._project_dir()
        if project_dir is None:
            raise DailyVehicleValidationError("找不到車輛保養清點自動化專案。")
        running_pid = self._read_running_pid(project_dir)
        if running_pid and self.process_checker(running_pid):
            raise DailyVehicleValidationError("車輛保養清點目前正在執行。")
        if running_pid:
            self._clear_running_pid(project_dir, running_pid)
        return DailyVehicleRequest(request.user_id.strip(), request.password, target_date.isoformat())

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
        self._completion_report = self._unconfirmed_report(date.today().isoformat())

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
                "PPE_RUNNER_PID_FILE": str(self._pid_path(project_dir)),
                "SELENIUM_REMOTE_URL": "",
                "PYTHONIOENCODING": "utf-8",
                "PPE_TARGET_DATE": request.target_date,
            }
        )
        if status_callback:
            status_callback("正在開啟瀏覽器執行車輛保養與器材清點…")
        process = None
        retaining_runner = False
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
                self._completion_report = self._read_completion_report(
                    str(exc.output or ""), request.target_date, (request.user_id, request.password)
                )
                self._completion_report.update(verified=False, reason_code="execution_unconfirmed")
                raise DailyVehicleExecutionError(
                    "車輛保養清點執行逾時。",
                    failure_stage=stage,
                ) from exc
            process_exited = process.poll() is not None
            self._completion_report = self._read_completion_report(
                output, request.target_date, (request.user_id, request.password)
            )
            completion_verified = (self._completion_report["verified"] is True
                                   and "[done] automation finished" in output.splitlines())
            if not completion_verified or (process_exited and process.returncode != 0):
                if self._completion_report["verified"] is True:
                    self._completion_report.update(verified=False, reason_code="execution_unconfirmed")
                stage = self._failure_stage_from_output(output, stage)
                message = self._browser_startup_safe_error(output) or self._safe_error(output)
                raise DailyVehicleExecutionError(message, failure_stage=stage)
            retaining_runner = not process_exited
            report_stage("result_evaluation")
            if status_callback and retaining_runner:
                status_callback("已完成；瀏覽器將保留 10 分鐘後自動關閉。")
            if any(item["status"] == "not_required" for item in self._completion_report["items"]):
                return f"車輛保養清點已確認全部作業結果：{request.target_date}"
            return f"車輛保養清點已完成：{request.target_date}"
        except DailyVehicleExecutionError:
            raise
        except OSError as exc:
            self._completion_report.update(verified=False, reason_code="unexpected_error")
            raise DailyVehicleExecutionError(
                "無法啟動車輛保養清點程式。",
                failure_stage=stage,
            ) from exc
        finally:
            if process is not None and not retaining_runner:
                try:
                    if process.poll() is None:
                        process.kill()
                except OSError:
                    pass
                else:
                    self._clear_running_pid(project_dir, process.pid)

    @classmethod
    def _read_completion_report(cls, output: str, target_date: str, credentials: tuple[str, ...]) -> dict:
        report = cls._unconfirmed_report(target_date)
        lines = [line[len(VEHICLE_REPORT_PREFIX):] for line in output.splitlines()
                 if line.startswith(VEHICLE_REPORT_PREFIX)]
        if not lines:
            return report
        report["reason_code"] = "report_invalid"
        if len(lines) != 1 or len(lines[0]) > 65536:
            return report

        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate report field")
                result[key] = value
            return result

        try:
            value = json.loads(lines[0], object_pairs_hook=unique_object)
        except (ValueError, TypeError, RecursionError):
            return report
        if not isinstance(value, dict) or value.get("target_date") != target_date:
            return report
        items = value.get("items")
        if not isinstance(items, list):
            return report
        verified = value.get("verified")
        reason = value.get("reason_code")
        valid = type(verified) is bool and isinstance(reason, str)
        if valid:
            valid = (reason in POSITIVE_REPORT_REASONS or reason == "") if verified else (
                reason in VEHICLE_REPORT_REASONS - POSITIVE_REPORT_REASONS
            )
        seen = set()
        for item in items[:200]:
            if not isinstance(item, dict):
                valid = False
                continue
            vehicle, operation = item.get("vehicle"), item.get("operation")
            status, item_reason = item.get("status"), item.get("reason_code")
            if (not isinstance(vehicle, str) or len(vehicle) > 32
                    or re.fullmatch(r"[A-Za-z0-9\u3400-\u9fff -]*", vehicle) is None
                    or re.search(r"secret|token|password|cookie|account|username|帳號|密碼", vehicle, re.I)
                    or operation not in ("maintenance", "equipment")
                    or status not in ("completed", "already_done", "unconfirmed", "not_required")
                    or not isinstance(item_reason, str)
                    or (item_reason not in VEHICLE_REPORT_REASONS and item_reason != "not_required")
                    or (status in ("completed", "already_done")
                        and (not vehicle.strip() or item_reason not in POSITIVE_REPORT_REASONS))
                    or (status == "not_required"
                        and (operation != "maintenance" or item_reason != "not_required" or not vehicle.strip()))
                    or (status == "unconfirmed"
                        and (item_reason in POSITIVE_REPORT_REASONS or item_reason == "not_required"))):
                valid = False
                continue
            vehicle = " ".join(vehicle.split())
            if any(secret and (vehicle.casefold() == secret.casefold()
                               or len(secret) >= 4 and secret.casefold() in vehicle.casefold())
                   for secret in credentials):
                valid = False
                continue
            key = (vehicle.casefold(), operation)
            if key in seen:
                valid = False
                continue
            seen.add(key)
            report["items"].append({"vehicle": vehicle, "operation": operation,
                                    "status": status, "reason_code": item_reason})
        if len(items) > 200:
            report["reason_code"] = "row_limit"
        elif not valid:
            pass
        elif verified is not True:
            report["reason_code"] = reason
        elif ({item["operation"] for item in report["items"]} != {"maintenance", "equipment"}
              or any(item["status"] == "unconfirmed" for item in report["items"])):
            report["reason_code"] = "report_invalid"
        else:
            report.update(verified=True, reason_code=reason)
        return report

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
        diagnostics = {
            "equipment_end_time_missing": "器材清點尚未結束，無法核對原始紀錄，請至公務網站檢查。",
            "equipment_detail_unconfirmed": "器材清點明細尚未完整載入或紀錄不符，已停止送出。",
            "equipment_continue_unavailable": "器材清點頁面未提供可用的「繼續清點」，已停止後續操作。",
            "equipment_selection_unconfirmed": "器材清點未能確認所有項目已勾選，已停止送出。",
            "equipment_confirmation_unconfirmed": "器材清點尚未確認儲存結果，請至公務網站檢查。",
            "query_spinner_timeout": "保養清點查詢的載入遮罩未結束，已停止後續操作。",
            "query_spinner_driver_error": "保養清點查詢無法確認載入遮罩狀態，已停止後續操作。",
            "query_source_changed_before_read": "保養清點查詢在讀取前的清單驗證未通過，已停止後續操作。",
            "query_source_changed_after_read": "保養清點查詢在讀取後的清單驗證未通過，已停止後續操作。",
            "query_rows_read_failed": "保養清點查詢無法讀取網頁資料列，已停止後續操作。",
            "query_state_read_failed_before_rows": "保養清點查詢在讀取前無法核對清單狀態，已停止後續操作。",
            "query_state_read_failed_after_rows": "保養清點查詢在讀取後無法核對清單狀態，已停止後續操作。",
        }
        prefix = "[sinposmart-vehicle-diagnostic] "
        for line in reversed(str(output or "").splitlines()):
            if line.startswith(prefix) and line[len(prefix):] in diagnostics:
                return diagnostics[line[len(prefix):]]
        text = str(output or "")[-3000:]
        lowered = text.lower()
        if "每日點車已跨日" in text:
            return "每日點車已跨日，已停止送出，請人工確認。"
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
        """Return on verified completion or process exit without waiting on retained Chrome."""
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
                raise subprocess.TimeoutExpired("daily_vehicle", timeout_seconds, output="".join(output_lines))
            try:
                line = output_queue.get(timeout=min(0.2, remaining))
            except queue.Empty:
                continue
            if line is not None:
                self._record_output_line(output_lines, line, status_callback)
                if line.strip() == "[done] automation finished":
                    return "".join(output_lines)

        reader.join(timeout=0.1)
        while True:
            try:
                line = output_queue.get_nowait()
            except queue.Empty:
                break
            if line is not None:
                self._record_output_line(output_lines, line, status_callback)
        return "".join(output_lines)

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
