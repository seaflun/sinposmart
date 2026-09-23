# -*- coding: utf-8 -*-
"""QML-facing update check and confirmed updater launch coordination."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Property, QThread, QTimer, Signal, Slot

from app_core.operational_sync_service import DEFAULT_SINPOSMART_BACKEND_EVENT_URL
from app_core.update_repository import UpdateCheckError, UpdateRepository, VersionInfo
from qt_app.workers.update_check_worker import RemoteUpdateWorker, UpdateCheckWorker

DEFERRED_UPDATE_RETRY_INTERVAL_MS = 30_000
DEFERRED_UPDATE_TIMEOUT_SECONDS = 300
REMOTE_UPDATE_POLL_INTERVAL_MS = 10_000
REMOTE_UPDATE_ACTIVE_STATUSES = frozenset(
    {"pending", "preparing", "staged", "waiting_handoff", "applying", "updating"}
)
REMOTE_UPDATE_TERMINAL_STATUSES = frozenset(
    {"completed", "up_to_date", "failed", "timed_out"}
)


def create_update_run_directory() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SinpoSmart" / "update_progress"
    directory = root / uuid.uuid4().hex
    directory.mkdir(parents=True, exist_ok=False)
    return directory


def launch_update_process(script_path: Path, *, request_id: str = "") -> Any:
    """The QML host survives the duty GUI; it alone starts the hidden installer."""
    directory = create_update_run_directory()
    python = Path(sys.executable)
    if python.with_name("pythonw.exe").is_file():
        python = python.with_name("pythonw.exe")
    command = [
        str(python), "-m", "qt_app.controllers.update_controller",
        "--install", str(script_path.resolve()), "--state-dir", str(directory),
    ]
    if request_id:
        command.extend(["--request-id", request_id])
    with (directory / "window.log").open("ab") as output:
        process = subprocess.Popen(
            command, cwd=str(script_path.parent),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
        )
    process.update_state_dir = directory
    return process


class UpdateWindowState(QObject):
    viewChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._view = {
            "visible": False, "phase": "idle", "title": "檢查更新",
            "subtitle": "", "detail": "", "progress": -1,
            "busy": False, "canInstall": False,
            "footer": "", "diagnosticPath": "",
        }

    @Property("QVariantMap", notify=viewChanged)
    def updateView(self) -> dict:
        return dict(self._view)

    @Property(bool, constant=True)
    def reducedMotion(self) -> bool:
        if os.name == "nt":
            import ctypes
            enabled = ctypes.c_int(1)
            if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
                return not enabled.value
        return False

    def _show_view(self, **values: Any) -> None:
        self._view.update(values)
        self.viewChanged.emit()

    @Slot()
    def dismissUpdateWindow(self) -> None:
        if not self._view["busy"]:
            self._show_view(visible=False)

    @Slot()
    def openUpdateDiagnostics(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        path = self._view["diagnosticPath"]
        if path and Path(path).is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def launch_remote_update_process(script_path: Path, request_id: str, phase: str) -> Any:
    """Run one remote update phase without a console window or user prompt."""

    if phase == "ApplyStaged":
        return launch_update_process(script_path, request_id=request_id)

    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-WindowStyle",
        "Hidden",
        "-File",
        str(script_path),
        "-AssumeYes",
        f"-{phase}",
        "-RequestId",
        str(request_id),
    ]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(
        command,
        cwd=str(script_path.parent),
        creationflags=creationflags,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _remote_update_endpoint() -> str:
    configured = os.environ.get("SINPOSMART_REMOTE_UPDATE_URL", "").strip()
    if configured:
        return configured.rstrip("/")
    event_url = os.environ.get(
        "SINPOSMART_BACKEND_EVENT_URL",
        DEFAULT_SINPOSMART_BACKEND_EVENT_URL,
    ).strip().rstrip("/")
    suffix = "/api/sinposmart/events"
    if event_url.endswith(suffix):
        return event_url[: -len(suffix)] + "/api/sinposmart/remote-update"
    return ""


def _remote_update_token() -> str:
    return (
        os.environ.get("SINPOSMART_REMOTE_UPDATE_TOKEN", "").strip()
        or os.environ.get("SINPOSMART_CREDENTIAL_SYNC_TOKEN", "").strip()
    )


def _remote_update_worker_id() -> str:
    return (
        os.environ.get("SINPOSMART_REMOTE_UPDATE_WORKER_ID", "").strip()
        or socket.gethostname().strip()
        or "sinposmart-duty-gui"
    )


class UpdateController(UpdateWindowState):
    unreturnedCancellationsReceived = Signal(object)
    stateChanged = Signal()
    errorOccurred = Signal(str)
    updateReady = Signal(str)
    checkCompleted = Signal(str)

    def __init__(
        self,
        repository: UpdateRepository,
        *,
        process_launcher: Callable[[Path], Any] = launch_update_process,
        remote_process_launcher: Callable[[Path, str, str], Any] = launch_remote_update_process,
        remote_update_enabled: bool | None = None,
        stop_guard: Callable[[], str] | None = None,
        read_only_acceptance: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._repository = repository
        self._process_launcher = process_launcher
        self._remote_process_launcher = remote_process_launcher
        self._stop_guard = stop_guard
        self._read_only_acceptance = bool(read_only_acceptance)
        self._current_version = ""
        self._latest_version = ""
        self._status_text = "尚未檢查更新"
        self._update_available = False
        self._update_deferred = False
        self._deferred_since: float | None = None
        self._deferred_reason = ""
        self._deferred_retry_timer = QTimer(self)
        self._deferred_retry_timer.setSingleShot(True)
        self._deferred_retry_timer.setInterval(DEFERRED_UPDATE_RETRY_INTERVAL_MS)
        self._deferred_retry_timer.timeout.connect(self._retry_deferred_update)
        self._request_id = 0
        self._workers: dict[int, tuple[QThread, UpdateCheckWorker]] = {}
        self._remote_workers: dict[int, tuple[QThread, RemoteUpdateWorker]] = {}
        self._remote_worker_request_id = 0
        self._remote_update_endpoint = _remote_update_endpoint()
        self._remote_update_token = _remote_update_token()
        self._remote_update_worker_id = _remote_update_worker_id()
        self._remote_update_enabled = (
            bool(self._remote_update_endpoint and self._remote_update_token)
            if remote_update_enabled is None
            else bool(remote_update_enabled)
        ) and not self._read_only_acceptance
        self._remote_update_command: dict[str, Any] = {}
        self._remote_update_request_id = ""
        self._remote_update_status = ""
        self._remote_update_active = False
        self._remote_update_ready = False
        self._remote_update_apply_requested = False
        self._remote_update_prepare_process: Any | None = None
        self._remote_update_prepare_process_request_id = ""
        self._remote_update_stage_reported = False
        self._remote_update_apply_inflight = False
        self._remote_update_apply_process: Any | None = None
        self._remote_status_actions: dict[int, Callable[[], None]] = {}
        self._remote_update_poll_timer = QTimer(self)
        self._remote_update_poll_timer.setInterval(REMOTE_UPDATE_POLL_INTERVAL_MS)
        self._remote_update_poll_timer.timeout.connect(self._poll_remote_update)
        self._shutdown_admission = False
        self._install_launched = False
        self._update_process = None
        self._update_window_started = False
        self._launch_timer = QTimer(self)
        self._launch_timer.setInterval(150)
        self._launch_timer.timeout.connect(self._check_update_window_started)
        try:
            self._current_version = repository.current_version()
        except UpdateCheckError as exc:
            self._status_text = str(exc)
        if self._remote_update_enabled:
            self._remote_update_poll_timer.start()
            QTimer.singleShot(0, self._poll_remote_update)

    def _show_view(self, **values: Any) -> None:
        super()._show_view(**values)
        self.stateChanged.emit()

    @Property(str, notify=stateChanged)
    def currentVersion(self) -> str:
        return self._current_version

    @Property(str, notify=stateChanged)
    def latestVersion(self) -> str:
        return self._latest_version

    @Property(str, notify=stateChanged)
    def statusText(self) -> str:
        return self._status_text

    @Property(bool, notify=stateChanged)
    def updateAvailable(self) -> bool:
        return self._update_available

    @Property(bool, notify=stateChanged)
    def isChecking(self) -> bool:
        return bool(self._workers)

    @Property(bool, notify=stateChanged)
    def updateDeferred(self) -> bool:
        return self._update_deferred

    @Property(bool, notify=stateChanged)
    def remoteUpdateActive(self) -> bool:
        return self._remote_update_active

    @Property(bool, notify=stateChanged)
    def remoteUpdateReady(self) -> bool:
        return self._remote_update_ready

    @Property(str, notify=stateChanged)
    def remoteUpdateStatus(self) -> str:
        return self._remote_update_status

    @Property(str, notify=stateChanged)
    def remoteUpdateRequestId(self) -> str:
        return self._remote_update_request_id

    @Property(str, notify=stateChanged)
    def logoutActionText(self) -> str:
        return "登出並更新" if self._remote_update_active else "登出"

    def setStopGuard(self, guard: Callable[[], str] | None) -> None:
        self._stop_guard = guard

    def _set_remote_state(
        self,
        *,
        active: bool | None = None,
        ready: bool | None = None,
        status: str | None = None,
    ) -> None:
        if active is not None:
            self._remote_update_active = bool(active)
        if ready is not None:
            self._remote_update_ready = bool(ready)
        if status is not None:
            self._remote_update_status = str(status or "")
        self.stateChanged.emit()

    @Slot()
    def check(self) -> None:
        if self._read_only_acceptance:
            self._status_text = "唯讀驗收模式，不檢查或安裝更新。"
            self.stateChanged.emit()
            return
        if self._shutdown_admission or self._update_deferred or self._workers or self._install_launched:
            return
        self._request_id += 1
        request_id = self._request_id
        self._status_text = "正在檢查更新…"
        self._show_view(
            visible=True, phase="checking", title="正在檢查更新",
            subtitle="正在確認是否有可用的新版本", detail=self._status_text,
            progress=-1, busy=True, canInstall=False, footer="請稍候，檢查完成後會顯示結果。",
            diagnosticPath="",
        )

        worker = UpdateCheckWorker(request_id, self._repository)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._check_succeeded)
        worker.failed.connect(self._check_failed)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(self._worker_finished)
        self._workers[request_id] = (thread, worker)
        thread.start()

    @Slot()
    def launchUpdate(self) -> None:
        if self._read_only_acceptance:
            self._status_text = "唯讀驗收模式，不檢查或安裝更新。"
            self.stateChanged.emit()
            return
        if self._update_deferred or self._install_launched or self._shutdown_admission:
            return
        if not self._update_available:
            self._status_text = "目前沒有可安裝的新版。"
            self.stateChanged.emit()
            return
        block_reason = self._stop_block_reason()
        if block_reason:
            self.deferUpdate(block_reason)
            return
        script_path = self._repository.version_path.with_name("update_package.ps1")
        if not script_path.is_file():
            message = f"找不到更新腳本：{script_path}"
            self._status_text = message
            self.stateChanged.emit()
            self.errorOccurred.emit(message)
            self._show_launch_error(message)
            return
        try:
            self._update_process = self._process_launcher(script_path)
        except OSError as exc:
            message = f"無法啟動更新程式：{exc}"
            self._status_text = message
            self.stateChanged.emit()
            self.errorOccurred.emit(message)
            self._show_launch_error("無法開啟更新視窗，請稍後再試。")
            return
        self._install_launched = True
        self._status_text = "已開啟更新程式，請依更新視窗完成操作。"
        self._show_view(
            visible=True, phase="launching", title="正在準備更新",
            subtitle="即將開啟更新進度視窗", detail="正在啟動更新程式…",
            progress=-1, busy=True, canInstall=False,
            footer="更新期間無法取消或暫停，請勿關閉電腦。",
        )
        if self._update_process is not None:
            self._launch_timer.start()

    def _show_launch_error(self, message: str) -> None:
        self._show_view(
            visible=True, phase="failed", title="無法開始更新",
            subtitle=message, detail="本次更新未開始。", progress=-1,
            busy=False, canInstall=False, footer="關閉此視窗後，可稍後重新檢查。",
        )

    def _check_update_window_started(self) -> None:
        process = self._update_process
        directory = getattr(process, "update_state_dir", None)
        if not self._update_window_started and directory is not None and (directory / "window-ready").is_file():
            self._update_window_started = True
            self._show_view(visible=False)
        code = process.poll()
        if code is not None:
            self._launch_timer.stop()
            self._install_launched = False
            if not self._update_window_started:
                self._show_launch_error("更新視窗未能啟動，請查看紀錄後再試。")
            elif code != 0:
                self._show_view(visible=True, phase="failed", title="更新視窗意外關閉",
                                subtitle="請查看更新紀錄，確認目前安裝狀態。", busy=False,
                                detail="若主程式未開啟，請手動重新開啟。", canInstall=False)
            else:
                self._status_text = "更新視窗已關閉，可重新檢查更新。"
                self.stateChanged.emit()
            self._update_window_started = False
            if directory is not None and self._view["visible"]:
                log = "installer.log" if (directory / "installer.log").is_file() else "window.log"
                self._show_view(diagnosticPath=str(directory / log))

    @Slot(result=bool)
    def applyRemoteUpdate(self) -> bool:
        """Queue or launch the staged remote update from a safe logout boundary."""

        if not self._remote_update_active or self._shutdown_admission:
            return False
        self._remote_update_apply_requested = True
        self._check_remote_stage()
        if not self._remote_update_active:
            return False
        if self._remote_update_ready:
            return self._launch_remote_apply()
        self._status_text = "遠端更新已收到，等待背景準備完成後登出並套用。"
        self._set_remote_state(status="waiting_handoff")
        self._send_remote_status("waiting_handoff", self._status_text)
        return True

    def _poll_remote_update(self) -> None:
        if (
            not self._remote_update_enabled
            or self._shutdown_admission
            or self._remote_workers
        ):
            self._check_remote_stage()
            return
        try:
            package_version = self._repository.current_version()
        except UpdateCheckError:
            package_version = ""
        self._remote_worker_request_id += 1
        request_id = self._remote_worker_request_id
        worker = RemoteUpdateWorker(
            request_id,
            self._remote_update_endpoint,
            self._remote_update_token,
            self._remote_update_worker_id,
            package_version,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._remote_poll_succeeded)
        worker.failed.connect(self._remote_poll_failed)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(self._remote_worker_finished)
        self._remote_workers[request_id] = (thread, worker)
        thread.start()

    @Slot(int, object)
    def _remote_poll_succeeded(self, request_id: int, response: object) -> None:
        if request_id not in self._remote_workers or not isinstance(response, dict):
            return
        cancellations = response.get("unreturned_cancellations")
        if isinstance(cancellations, list) and not self._read_only_acceptance:
            self.unreturnedCancellationsReceived.emit(cancellations)
        command = response.get("command")
        if not isinstance(command, dict):
            self._check_remote_stage()
            return
        command_id = str(command.get("request_id") or "").strip()
        status = str(command.get("status") or "").strip()
        if not command_id:
            return
        previous_request_id = self._remote_update_request_id
        self._remote_update_command = dict(command)
        self._remote_update_request_id = command_id
        if status in REMOTE_UPDATE_TERMINAL_STATUSES:
            if status == "timed_out" and self._check_remote_stage(reconcile_only=True):
                return
            self._finish_remote_update(status, command)
            return
        if status not in REMOTE_UPDATE_ACTIVE_STATUSES:
            return
        was_active = self._remote_update_active
        if previous_request_id and previous_request_id != command_id:
            self._remote_update_prepare_process = None
            self._remote_update_ready = False
            self._remote_update_apply_requested = False
            self._remote_update_stage_reported = False
        self._set_remote_state(active=True, status=status)
        if not was_active:
            self._remote_update_ready = False
            self._remote_update_apply_requested = False
            self._remote_update_stage_reported = False
        if status in {"pending", "preparing"} and self._remote_update_prepare_process is None:
            self._start_remote_prepare()
        self._check_remote_stage()

    @Slot(int, str)
    def _remote_poll_failed(self, request_id: int, message: str) -> None:
        if request_id not in self._remote_workers:
            return
        if not self._remote_update_active:
            return
        self._status_text = f"遠端更新狀態暫時無法取得：{message}"
        self.stateChanged.emit()

    def _start_remote_prepare(self) -> None:
        request_id = self._remote_update_request_id
        script_path = self._repository.version_path.with_name("update_package.ps1")
        if not request_id or not script_path.is_file():
            self._fail_remote_update("找不到遠端更新腳本。")
            return
        process = self._remote_update_prepare_process
        if process is not None:
            poll = getattr(process, "poll", None)
            if not callable(poll) or poll() is None:
                return
        self._remote_update_prepare_process_request_id = request_id
        self._send_remote_status("preparing", "正在背景準備更新套件。")
        try:
            self._remote_update_prepare_process = self._remote_process_launcher(
                script_path,
                request_id,
                "PrepareOnly",
            )
        except OSError as exc:
            self._remote_update_prepare_process = None
            self._fail_remote_update(f"無法啟動背景更新準備：{exc}")
            return
        self._status_text = "遠端更新已收到，正在背景準備套件。"
        self.stateChanged.emit()

    def _check_remote_stage(self, *, reconcile_only: bool = False) -> bool:
        if not self._remote_update_request_id or (not self._remote_update_active and not reconcile_only):
            return False
        manifest_path = self._remote_update_manifest_path(self._remote_update_request_id)
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                manifest = {}
            if isinstance(manifest, dict) and str(manifest.get("request_id") or "") == self._remote_update_request_id:
                stage_status = str(manifest.get("status") or "").strip()
                if stage_status in {"completed", "up_to_date"}:
                    installed_version = str(manifest.get("installed_version") or "").strip()
                    if not installed_version or installed_version != self._current_version:
                        return False
                    self._remote_update_prepare_process = None
                    terminal_detail = str(
                        manifest.get("detail")
                        or (
                            "值班台目前已是最新版本。"
                            if stage_status == "up_to_date"
                            else "遠端更新已完成，值班台已重新啟動。"
                        )
                    )
                    terminal_command = {
                        **self._remote_update_command,
                        "status": stage_status,
                        "detail": terminal_detail,
                        "installed_version": installed_version,
                    }
                    self._finish_remote_update(stage_status, terminal_command)
                    self._send_remote_status(stage_status, terminal_detail)
                    return True
                if reconcile_only:
                    return False
                if stage_status == "failed":
                    self._remote_update_prepare_process = None
                    self._fail_remote_update(str(manifest.get("detail") or "背景更新準備失敗。"))
                    return False
                if stage_status == "staged":
                    self._remote_update_prepare_process = None
                    self._remote_update_ready = True
                    if self._remote_update_apply_inflight:
                        process = self._remote_update_apply_process
                        if process is not None and process.poll() is not None:
                            self._fail_remote_update("更新視窗已結束，但尚未收到安裝完成結果。")
                        return False
                    if self._update_deferred:
                        return False
                    self._status_text = "遠端更新檔已準備，等待交接登出套用。"
                    self._set_remote_state(status="waiting_handoff")
                    if not self._remote_update_stage_reported:
                        self._remote_update_stage_reported = True
                        self._send_remote_status("staged", self._status_text)
                    if self._remote_update_apply_requested:
                        self._launch_remote_apply()
                    return False
        if reconcile_only:
            return False
        process = self._remote_update_prepare_process
        poll = getattr(process, "poll", None) if process is not None else None
        if callable(poll):
            try:
                exit_code = poll()
            except Exception:
                exit_code = None
            if exit_code is not None and exit_code != 0:
                self._fail_remote_update("背景更新準備失敗，尚未套用任何檔案。")
            elif exit_code == 0:
                self._fail_remote_update("背景更新準備未產生可套用的套件。")
        return False

    def _launch_remote_apply(self) -> bool:
        if self._shutdown_admission or not self._remote_update_active or not self._remote_update_ready:
            return False
        if self._remote_update_apply_inflight:
            return True
        block_reason = self._stop_block_reason()
        if block_reason:
            self._remote_update_apply_requested = True
            self.deferUpdate(block_reason)
            return True
        request_id = self._remote_update_request_id
        script_path = self._repository.version_path.with_name("update_package.ps1")
        if not request_id or not script_path.is_file():
            self._fail_remote_update("找不到遠端更新套用腳本。")
            return False
        self._remote_update_apply_requested = False
        self._clear_deferred_update()
        self._status_text = "正在登出並套用遠端更新，完成後會自動重啟。"
        self._set_remote_state(status="applying")
        self._remote_update_apply_inflight = True
        launch_started = False

        def launch_apply() -> None:
            nonlocal launch_started
            if (
                launch_started
                or not self._remote_update_apply_inflight
                or self._shutdown_admission
                or request_id != self._remote_update_request_id
            ):
                return
            launch_started = True
            try:
                self._remote_update_apply_process = self._remote_process_launcher(
                    script_path, request_id, "ApplyStaged"
                )
            except OSError as exc:
                self._fail_remote_update(f"無法啟動遠端更新套用：{exc}")

        if not self._send_remote_status(
            "applying",
            self._status_text,
            after_success=launch_apply,
            after_failure=launch_apply,
        ):
            launch_apply()
        return True

    def _finish_remote_update(self, status: str, command: dict[str, Any]) -> None:
        was_deferred = self._remote_update_active and self._update_deferred
        if self._remote_update_active:
            self._clear_deferred_update()
        self._remote_update_command = dict(command)
        self._remote_update_status = status
        self._remote_update_active = False
        self._remote_update_ready = False
        self._remote_update_apply_requested = False
        self._remote_update_apply_inflight = False
        self._remote_update_apply_process = None
        self._remote_update_stage_reported = False
        detail = str(command.get("detail") or "遠端更新已結束。")
        self._status_text = detail
        if was_deferred and status in {"failed", "timed_out"}:
            self._show_launch_error(detail)
        elif was_deferred:
            self._show_view(visible=False, phase="idle", busy=False)
        else:
            self.stateChanged.emit()

    def _fail_remote_update(self, detail: str) -> None:
        message = str(detail or "遠端更新準備失敗。")
        if self._deferred_reason and self._deferred_reason not in message:
            message += f" 最後等待原因：{self._deferred_reason}。"
        self._clear_deferred_update()
        request_id = self._remote_update_request_id
        if request_id:
            self._send_remote_status("failed", message)
        self._remote_update_status = "failed"
        self._remote_update_active = False
        self._remote_update_ready = False
        self._remote_update_apply_requested = False
        self._remote_update_apply_inflight = False
        self._remote_update_apply_process = None
        self._remote_update_stage_reported = False
        self._remote_update_prepare_process = None
        self._status_text = f"{message} 已恢復一般登出。"
        self._show_launch_error(self._status_text)

    def _send_remote_status(
        self,
        status: str,
        detail: str,
        *,
        after_success: Callable[[], None] | None = None,
        after_failure: Callable[[], None] | None = None,
    ) -> bool:
        if (
            not self._remote_update_enabled
            or not self._remote_update_request_id
            or self._shutdown_admission
        ):
            return False
        self._remote_worker_request_id += 1
        request_id = self._remote_worker_request_id
        worker = RemoteUpdateWorker(
            request_id,
            self._remote_update_endpoint,
            self._remote_update_token,
            self._remote_update_worker_id,
            self._current_version,
            status_request={
                "request_id": self._remote_update_request_id,
                "status": status,
                "detail": str(detail or "")[:500],
                "worker_id": self._remote_update_worker_id,
                **({"installed_version": self._current_version, "exit_code": 0}
                   if status in {"completed", "up_to_date"} else {}),
            },
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(self._remote_worker_finished)
        if after_success is not None:
            self._remote_status_actions[request_id] = after_success
        elif after_failure is not None:
            self._remote_status_actions[request_id] = after_failure
        worker.succeeded.connect(self._remote_status_succeeded)
        worker.failed.connect(self._remote_status_failed)
        self._remote_workers[request_id] = (thread, worker)
        thread.start()
        return True

    @Slot(int, object)
    def _remote_status_succeeded(self, request_id: int, _response: object) -> None:
        action = self._remote_status_actions.pop(request_id, None)
        if action is not None:
            action()

    @Slot(int, str)
    def _remote_status_failed(self, request_id: int, _message: str) -> None:
        action = self._remote_status_actions.pop(request_id, None)
        if action is not None:
            action()

    def _remote_update_manifest_path(self, request_id: str) -> Path:
        safe_request_id = "".join(
            character if character.isalnum() or character in "._-" else "_"
            for character in str(request_id or "")
        )
        state_root = os.environ.get("LOCALAPPDATA", "").strip() or tempfile.gettempdir()
        return Path(state_root) / "SinpoSmart" / "update_staging" / safe_request_id / "manifest.json"

    @Slot(int)
    def _remote_worker_finished(self, request_id: int) -> None:
        worker_pair = self._remote_workers.get(request_id)
        if worker_pair is None:
            return
        thread, _worker = worker_pair
        thread.quit()
        if not thread.wait(5_000):
            self._poll_remote_worker_thread_finished(request_id)
            return
        self._finalize_remote_worker(request_id)
        thread.deleteLater()

    def _poll_remote_worker_thread_finished(self, request_id: int) -> None:
        worker_pair = self._remote_workers.get(request_id)
        if worker_pair is None:
            return
        thread, _worker = worker_pair
        if not thread.isFinished():
            QTimer.singleShot(50, lambda: self._poll_remote_worker_thread_finished(request_id))
            return
        self._finalize_remote_worker(request_id)
        thread.deleteLater()

    def _finalize_remote_worker(self, request_id: int) -> None:
        if self._remote_workers.pop(request_id, None) is not None:
            self.stateChanged.emit()

    @Slot(str)
    def deferUpdate(self, block_reason: str) -> None:
        if self._shutdown_admission:
            return
        reason = str(block_reason or "目前工作尚未結束").strip()
        if self._update_deferred and reason == self._deferred_reason:
            self._schedule_deferred_retry()
            return
        if not self._update_deferred:
            self._deferred_since = time.monotonic()
        self._update_deferred = True
        self._deferred_reason = reason
        self._status_text = (
            f"更新已延後：{reason}；工作完成後會自動重試（最多等待 5 分鐘）"
        )
        if self._remote_update_active:
            status = "applying" if self._remote_update_apply_inflight else "waiting_handoff"
            if self._remote_update_status == "updating":
                status = "updating"
            self._set_remote_state(status=status)
            self._send_remote_status(status, self._status_text)
        self.stateChanged.emit()
        self.errorOccurred.emit(self._status_text)
        self._show_view(
            visible=True, phase="deferred", title="更新已延後",
            subtitle=reason,
            detail="目前工作完成後會自動重試更新；超過 5 分鐘會停止等待並保留目前程式。",
            progress=-1, busy=False, canInstall=False, footer="目前程式會繼續保持開啟。",
        )
        self._schedule_deferred_retry()

    def _schedule_deferred_retry(self) -> None:
        if self._shutdown_admission:
            return
        if not self._deferred_retry_timer.isActive():
            self._deferred_retry_timer.start()

    @Slot()
    def _retry_deferred_update(self) -> None:
        if self._shutdown_admission or not self._update_deferred:
            self._deferred_retry_timer.stop()
            return
        if self._remote_update_active:
            self._check_remote_stage()
            if not self._remote_update_active:
                return
        if self._remote_update_apply_inflight or self._install_launched:
            # The existing installer owns the busy handshake and its timeout.
            # Never spawn another installer while that attempt is still alive.
            self._schedule_deferred_retry()
            return
        remote_pending = self._remote_update_active and self._remote_update_apply_requested
        if not remote_pending and not self._update_available:
            self._clear_deferred_update()
            self.stateChanged.emit()
            return
        block_reason = self._stop_block_reason()
        if block_reason:
            if (
                self._deferred_since is not None
                and time.monotonic() - self._deferred_since >= DEFERRED_UPDATE_TIMEOUT_SECONDS
            ):
                message = f"更新等待超過 5 分鐘：{block_reason}。請待工作結束後重新嘗試。"
                if remote_pending:
                    self._fail_remote_update(message)
                else:
                    self._clear_deferred_update()
                    self._status_text = message
                    self._show_launch_error(message)
                return
            self.deferUpdate(block_reason)
            return
        self._clear_deferred_update()
        self.stateChanged.emit()
        if remote_pending:
            self._launch_remote_apply()
        else:
            self.launchUpdate()

    def _clear_deferred_update(self) -> None:
        self._update_deferred = False
        self._deferred_since = None
        self._deferred_reason = ""
        self._deferred_retry_timer.stop()

    def _stop_block_reason(self) -> str:
        if self._stop_guard is None:
            return ""
        try:
            return str(self._stop_guard() or "").strip()
        except Exception:
            return "無法確認目前工作是否已安全結束"

    @Slot(int, object)
    def _check_succeeded(self, request_id: int, info: VersionInfo) -> None:
        if request_id != self._request_id:
            return
        self._current_version = info.current_version
        self._latest_version = info.latest_version
        self._update_available = info.update_available
        self._status_text = (
            f"有新版可用：{info.latest_version}"
            if info.update_available
            else "目前已是最新版"
        )
        self._show_view(
            visible=True, phase="available" if info.update_available else "current",
            title="有新版本可以更新" if info.update_available else "目前已是最新版",
            subtitle=f"目前版本 {info.current_version}",
            detail=f"最新版本 {info.latest_version}", progress=-1, busy=False,
            canInstall=info.update_available,
            footer="更新會先安全登出，完成後自動開啟登入畫面。" if info.update_available else "你可以繼續使用 SinpoSmart。",
        )
        if info.update_available:
            self.updateReady.emit(info.latest_version)
        else:
            self.checkCompleted.emit(self._status_text)

    @Slot(int, str)
    def _check_failed(self, request_id: int, message: str) -> None:
        if request_id != self._request_id:
            return
        self._latest_version = ""
        self._update_available = False
        self._status_text = message
        diagnostic_path = ""
        try:
            diagnostic = create_update_run_directory() / "check.log"
            diagnostic.write_text(message, encoding="utf-8")
            diagnostic_path = str(diagnostic)
        except OSError:
            pass
        self._show_view(
            visible=True, phase="failed", title="暫時無法檢查更新",
            subtitle="請確認網路連線後再試。", detail="目前程式可以繼續使用。",
            progress=-1, busy=False, canInstall=False,
            footer="關閉此視窗後，可稍後重新檢查。",
            diagnosticPath=diagnostic_path,
        )
        self.errorOccurred.emit(message)

    @Slot(int)
    def _worker_finished(self, request_id: int) -> None:
        worker_pair = self._workers.get(request_id)
        if worker_pair is None:
            return
        thread, _worker = worker_pair
        thread.quit()
        if not thread.wait(5_000):
            self._poll_worker_thread_finished(request_id)
            return
        self._finalize_worker_thread(request_id)
        thread.deleteLater()

    def _poll_worker_thread_finished(self, request_id: int) -> None:
        worker_pair = self._workers.get(request_id)
        if worker_pair is None:
            return
        thread, _worker = worker_pair
        if not thread.isFinished():
            QTimer.singleShot(50, lambda: self._poll_worker_thread_finished(request_id))
            return
        self._finalize_worker_thread(request_id)
        thread.deleteLater()

    def _finalize_worker_thread(self, request_id: int) -> None:
        worker_pair = self._workers.pop(request_id, None)
        if worker_pair is None:
            return
        self.stateChanged.emit()

    @Slot()
    def prepare_shutdown_admission(self) -> None:
        self._shutdown_admission = True
        self._deferred_retry_timer.stop()
        self._remote_update_poll_timer.stop()

    @Slot()
    def shutdown(self) -> None:
        self.prepare_shutdown_admission()
        self._launch_timer.stop()
        for request_id, (thread, _worker) in tuple(self._workers.items()):
            thread.requestInterruption()
            thread.quit()
            if not thread.wait(15_000):
                thread.wait()
            self._finalize_worker_thread(request_id)
            thread.deleteLater()
        for request_id, (thread, _worker) in tuple(self._remote_workers.items()):
            thread.requestInterruption()
            thread.quit()
            if not thread.wait(15_000):
                thread.wait()
            self._finalize_remote_worker(request_id)
            thread.deleteLater()
        self._remote_status_actions.clear()


UPDATE_PHASE_TEXT = {
    "checking": "正在確認更新版本…",
    "downloading": "正在下載更新檔案…",
    "verifying": "正在驗證更新檔案…",
    "backup": "正在備份目前版本…",
    "extracting": "正在解壓縮更新檔案…",
    "closing": "正在安全登出並關閉主程式…",
    "waiting_idle": "目前工作尚未結束，完成後會接續更新（最多等待 5 分鐘）…",
    "installing": "正在安裝更新檔案…",
    "setup": "正在準備執行環境，可能需要一些時間…",
    "environment": "正在檢查執行環境…",
    "restarting": "正在重新開啟登入畫面…",
    "installed": "正在確認登入畫面已開啟…",
    "current": "目前已是最新版",
}
UPDATE_INSTANCE_SERVER = "TYFD.SinpoSmart.DutyAutomation.Qt"


class UpdateProgressController(UpdateWindowState):
    """Read installer progress without tying the window to the duty GUI lifetime."""

    installerFinished = Signal()

    def __init__(self, script_path: Path, state_dir: Path, parent: QObject | None = None, *, request_id: str = "") -> None:
        super().__init__(parent)
        from PySide6.QtNetwork import QLocalSocket

        self._script_path = script_path.resolve()
        self._request_id = request_id
        self._state_dir = state_dir
        self._status_path = state_dir / "progress.json"
        self._process = None
        self._exit_code = None
        self._expected_pid = 0
        self._waiting_since = None
        self._socket = QLocalSocket(self)
        self._socket.connected.connect(lambda: self._socket.write(
            b"update_status_handoff\n" if self._request_id else b"update_status\n"
        ))
        self._socket.readyRead.connect(self._read_ready_response)
        self._socket.errorOccurred.connect(lambda _error: self._socket.abort())
        self._reply = bytearray()
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(200)
        self._poll_timer.timeout.connect(self.poll)
        self._show_view(
            visible=True, phase="checking", title="正在更新，請稍候",
            subtitle="完成後將自動重新開啟值班台" if request_id else "完成後將自動開啟登入畫面",
            detail=UPDATE_PHASE_TEXT["checking"],
            progress=0, busy=True, canInstall=False,
            footer="更新期間無法取消或暫停，請勿關閉電腦。",
            diagnosticPath=str(state_dir / "installer.log"),
        )

    @Slot()
    def start(self) -> None:
        if self._process is not None or self._exit_code is not None:
            return
        command = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                   "-File", str(self._script_path), "-AssumeYes", "-RestartAfterUpdate",
                   "-ProgressPath", str(self._status_path)]
        if self._request_id:
            command.extend(["-ApplyStaged", "-RequestId", self._request_id])
        try:
            with (self._state_dir / "installer.log").open("ab") as output:
                self._process = subprocess.Popen(
                    command,
                    cwd=str(self._script_path.parent),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                )
        except OSError as exc:
            (self._state_dir / "installer.log").write_text(str(exc), encoding="utf-8")
            self.process_finished(1)
            return
        self._poll_timer.start()

    def accept_progress(self, record: Any) -> None:
        if not isinstance(record, dict) or self._exit_code is not None:
            return
        phase = record.get("phase")
        percent = record.get("percent")
        if phase not in UPDATE_PHASE_TEXT or type(percent) is not int or not 0 <= percent <= 100:
            return
        if percent < self._view["progress"]:
            return
        if phase == "installed":
            pid = record.get("pid")
            if type(pid) is not int or pid <= 0:
                return
            self._expected_pid = pid
        detail = UPDATE_PHASE_TEXT[phase]
        elapsed = record.get("elapsed_seconds")
        if phase in ("setup", "environment") and type(elapsed) is int and elapsed > 0:
            detail += f" 已等待 {elapsed // 60} 分 {elapsed % 60} 秒；可開啟更新紀錄查看安裝輸出。"
        self._show_view(phase=phase, progress=min(percent, 98), detail=detail)

    def poll(self) -> None:
        if self._exit_code is None:
            try:
                self.accept_progress(json.loads(self._status_path.read_text(encoding="utf-8-sig")))
            except (OSError, ValueError):
                pass  # A missing/in-flight status never turns into success.
            if self._process is not None:
                code = self._process.poll()
                if code is not None:
                    try:
                        self.accept_progress(json.loads(self._status_path.read_text(encoding="utf-8-sig")))
                    except (OSError, ValueError):
                        pass
                    self.process_finished(code)
        if self._waiting_since is not None:
            if time.monotonic() - self._waiting_since >= 60:
                self._fail("更新檔案已安裝，但尚未確認登入畫面。", "請手動開啟 SinpoSmart，並查看更新紀錄。")
            elif self._socket.state() == self._socket.LocalSocketState.UnconnectedState:
                self._reply.clear()
                self._socket.connectToServer(UPDATE_INSTANCE_SERVER)
                QTimer.singleShot(180, self._socket.abort)

    def process_finished(self, exit_code: int) -> None:
        self._exit_code = exit_code
        self.installerFinished.emit()
        if exit_code != 0:
            self._fail("這次更新未完成。", "請查看更新紀錄；若主程式未開啟，請手動重新開啟。")
        elif self._view["phase"] == "current":
            self._poll_timer.stop()
            self._show_view(title="目前已是最新版", subtitle="不需要安裝更新。", busy=False,
                            progress=-1, footer="你可以繼續使用 SinpoSmart。")
        elif self._view["phase"] == "installed" and self._expected_pid > 0:
            self._waiting_since = time.monotonic()
            self._poll_timer.start()
        else:
            self._fail("未收到完整的更新結果。", "請查看更新紀錄，確認目前安裝狀態。")

    def _read_ready_response(self) -> None:
        self._reply.extend(bytes(self._socket.readAll()))
        if b"\n" in self._reply:
            self.confirm_window_ready(self._reply.decode("utf-8", errors="replace").strip())
            self._socket.abort()

    def confirm_window_ready(self, response: str) -> None:
        if self._waiting_since is None or response != f"ready:{self._expected_pid}":
            return
        self._waiting_since = None
        self._poll_timer.stop()
        self._show_view(phase="completed", title="更新完成",
                        subtitle="值班台已重新開啟。" if self._request_id else "登入畫面已開啟。",
                        detail="可以開始使用 SinpoSmart。", progress=100, busy=False,
                        footer="此視窗將自動關閉。")
        QTimer.singleShot(900, self.dismissUpdateWindow)

    def _fail(self, subtitle: str, detail: str) -> None:
        self._waiting_since = None
        self._poll_timer.stop()
        self._socket.abort()
        self._show_view(phase="failed", title="更新需要處理", subtitle=subtitle, detail=detail,
                        busy=False, footer="更新程序已結束，可以關閉此視窗。")


def run_update_window(arguments: list[str] | None = None) -> int:
    """Independent window mode in the existing module; never imports the duty app."""
    import argparse
    from PySide6.QtCore import QLockFile, QUrl
    from PySide6.QtGui import QCursor, QFont, QFontDatabase, QIcon
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickWindow
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtWidgets import QApplication

    parser = argparse.ArgumentParser()
    parser.add_argument("--install", type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--request-id", default="")
    options = parser.parse_args(arguments)
    package_root = Path(__file__).resolve().parents[2]
    app = QApplication([sys.argv[0]])
    app.setApplicationName("SinpoSmart 更新")
    app.setQuitOnLastWindowClosed(False)
    if (package_root / "duty_tray_icon.ico").is_file():
        app.setWindowIcon(QIcon(str(package_root / "duty_tray_icon.ico")))
    if not any(family in QFontDatabase.families() for family in ("Microsoft JhengHei UI", "Microsoft JhengHei")):
        font_path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "msjh.ttc"
        if font_path.is_file():
            QFontDatabase.addApplicationFont(str(font_path))
    for family in ("SF Pro Text", "Microsoft JhengHei UI", "Microsoft JhengHei"):
        if family in QFontDatabase.families():
            app.setFont(QFont(family))
            break
    QQuickStyle.setStyle("Basic")
    if options.install or options.preview:
        directory = options.state_dir or create_update_run_directory()
        controller = UpdateProgressController(options.install or package_root / "update_package.ps1", directory,
                                              request_id=options.request_id)
    else:
        controller = UpdateController(UpdateRepository(package_root / "VERSION.txt"), remote_update_enabled=False)
        controller._show_view(visible=True)
        app.aboutToQuit.connect(controller.shutdown)
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"controller": controller})
    qml = Path(__file__).resolve().parents[1] / "qml" / "dialogs" / "UpdateProgressWindow.qml"
    engine.load(QUrl.fromLocalFile(str(qml)))
    if not engine.rootObjects():
        return 1
    window: QQuickWindow = engine.rootObjects()[0]
    screen = app.screenAt(QCursor.pos()) or app.primaryScreen()
    available = screen.availableGeometry()
    window.setPosition(available.center().x() - window.width() // 2,
                       available.center().y() - window.height() // 2)
    controller.viewChanged.connect(lambda: app.quit() if not controller.updateView["visible"] else None)
    if options.preview:
        controller.accept_progress({"phase": "installing", "percent": 68})
    elif options.install:
        import hashlib
        lock_key = hashlib.sha256(str(options.install.resolve()).casefold().encode("utf-8")).hexdigest()[:20]
        lock_path = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SinpoSmart" / f"update-{lock_key}.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        app.update_lock = QLockFile(str(lock_path))
        app.update_lock.setStaleLockTime(0)
        if not app.update_lock.tryLock(0):
            controller._fail("另一個更新視窗正在處理更新。", "請等待原本的更新視窗完成。")
            (directory / "window-ready").write_text("ready", encoding="ascii")
            return app.exec()
        controller.installerFinished.connect(app.update_lock.unlock)
        # Start only after the first rendered frame, so the progress window exists
        # before the updater can ask the main GUI to exit.
        def begin_install() -> None:
            window.frameSwapped.disconnect(begin_install)
            (directory / "window-ready").write_text("ready", encoding="ascii")
            controller.start()
        window.frameSwapped.connect(begin_install)
    else:
        QTimer.singleShot(0, controller.check)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run_update_window())
