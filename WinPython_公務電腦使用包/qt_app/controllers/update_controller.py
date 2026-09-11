# -*- coding: utf-8 -*-
"""QML-facing update check and confirmed updater launch coordination."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Property, QThread, QTimer, Signal, Slot

from app_core.operational_sync_service import DEFAULT_SINPOSMART_BACKEND_EVENT_URL
from app_core.update_repository import UpdateCheckError, UpdateRepository, VersionInfo
from qt_app.workers.update_check_worker import RemoteUpdateWorker, UpdateCheckWorker

DEFERRED_UPDATE_RETRY_INTERVAL_MS = 30_000
REMOTE_UPDATE_POLL_INTERVAL_MS = 10_000
REMOTE_UPDATE_ACTIVE_STATUSES = frozenset(
    {"pending", "preparing", "staged", "waiting_handoff", "applying", "updating"}
)
REMOTE_UPDATE_TERMINAL_STATUSES = frozenset(
    {"completed", "up_to_date", "failed", "timed_out"}
)


def launch_update_process(script_path: Path) -> Any:
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
        "-AssumeYes",
    ]
    creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    return subprocess.Popen(command, cwd=str(script_path.parent), creationflags=creationflags)


def launch_remote_update_process(script_path: Path, request_id: str, phase: str) -> Any:
    """Run one remote update phase without a console window or user prompt."""

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


class UpdateController(QObject):
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
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._repository = repository
        self._process_launcher = process_launcher
        self._remote_process_launcher = remote_process_launcher
        self._stop_guard = stop_guard
        self._current_version = ""
        self._latest_version = ""
        self._status_text = "尚未檢查更新"
        self._update_available = False
        self._update_deferred = False
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
        )
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
        self._remote_status_actions: dict[int, Callable[[], None]] = {}
        self._remote_update_poll_timer = QTimer(self)
        self._remote_update_poll_timer.setInterval(REMOTE_UPDATE_POLL_INTERVAL_MS)
        self._remote_update_poll_timer.timeout.connect(self._poll_remote_update)
        self._shutdown_admission = False
        try:
            self._current_version = repository.current_version()
        except UpdateCheckError as exc:
            self._status_text = str(exc)
        if self._remote_update_enabled:
            self._remote_update_poll_timer.start()
            QTimer.singleShot(0, self._poll_remote_update)

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
        if self._shutdown_admission or self._update_deferred or self._workers:
            return
        self._request_id += 1
        request_id = self._request_id
        self._status_text = "正在檢查更新…"
        self.stateChanged.emit()

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
        if self._update_deferred:
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
            return
        try:
            self._process_launcher(script_path)
        except OSError as exc:
            message = f"無法啟動更新程式：{exc}"
            self._status_text = message
            self.stateChanged.emit()
            self.errorOccurred.emit(message)
            return
        self._status_text = "已開啟更新程式，請依更新視窗完成操作。"
        self.stateChanged.emit()

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

    def _check_remote_stage(self) -> None:
        if not self._remote_update_active or not self._remote_update_request_id:
            return
        manifest_path = self._remote_update_manifest_path(self._remote_update_request_id)
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                manifest = {}
            if isinstance(manifest, dict) and str(manifest.get("request_id") or "") == self._remote_update_request_id:
                stage_status = str(manifest.get("status") or "").strip()
                if stage_status in {"completed", "up_to_date"}:
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
                        "installed_version": str(
                            manifest.get("installed_version") or self._current_version
                        ),
                    }
                    self._finish_remote_update(stage_status, terminal_command)
                    self._send_remote_status(stage_status, terminal_detail)
                    return
                if stage_status == "failed":
                    self._remote_update_prepare_process = None
                    self._fail_remote_update(str(manifest.get("detail") or "背景更新準備失敗。"))
                    return
                if stage_status == "staged":
                    self._remote_update_prepare_process = None
                    self._remote_update_ready = True
                    self._status_text = "遠端更新檔已準備，等待交接登出套用。"
                    self._set_remote_state(status="waiting_handoff")
                    if not self._remote_update_stage_reported:
                        self._remote_update_stage_reported = True
                        self._send_remote_status("staged", self._status_text)
                    if self._remote_update_apply_requested:
                        self._launch_remote_apply()
                    return
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

    def _launch_remote_apply(self) -> bool:
        if not self._remote_update_active or not self._remote_update_ready:
            return False
        if self._remote_update_apply_inflight:
            return True
        request_id = self._remote_update_request_id
        script_path = self._repository.version_path.with_name("update_package.ps1")
        if not request_id or not script_path.is_file():
            self._fail_remote_update("找不到遠端更新套用腳本。")
            return False
        self._remote_update_apply_requested = False
        self._status_text = "正在登出並套用遠端更新，完成後會自動重啟。"
        self._set_remote_state(status="applying")
        self._remote_update_apply_inflight = True

        def launch_apply() -> None:
            if not self._remote_update_apply_inflight:
                return
            self._remote_update_apply_inflight = False
            try:
                self._remote_process_launcher(script_path, request_id, "ApplyStaged")
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
        self._remote_update_command = dict(command)
        self._remote_update_status = status
        self._remote_update_active = False
        self._remote_update_ready = False
        self._remote_update_apply_requested = False
        self._remote_update_apply_inflight = False
        self._remote_update_stage_reported = False
        detail = str(command.get("detail") or "遠端更新已結束。")
        self._status_text = detail
        self.stateChanged.emit()

    def _fail_remote_update(self, detail: str) -> None:
        message = str(detail or "遠端更新準備失敗。")
        request_id = self._remote_update_request_id
        if request_id:
            self._send_remote_status("failed", message)
        self._remote_update_status = "failed"
        self._remote_update_active = False
        self._remote_update_ready = False
        self._remote_update_apply_requested = False
        self._remote_update_apply_inflight = False
        self._remote_update_stage_reported = False
        self._remote_update_prepare_process = None
        self._status_text = f"{message} 已恢復一般登出。"
        self.stateChanged.emit()

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
        if self._update_deferred:
            self._schedule_deferred_retry()
            return
        self._update_deferred = True
        self._status_text = (
            f"更新已延後：{str(block_reason or '').strip()}；"
            "工作完成後會自動重試"
        )
        self.stateChanged.emit()
        self.errorOccurred.emit(self._status_text)
        self._schedule_deferred_retry()

    def _schedule_deferred_retry(self) -> None:
        if self._shutdown_admission or not self._update_available:
            return
        if not self._deferred_retry_timer.isActive():
            self._deferred_retry_timer.start()

    @Slot()
    def _retry_deferred_update(self) -> None:
        if self._shutdown_admission or not self._update_deferred:
            self._deferred_retry_timer.stop()
            return
        if not self._update_available:
            self._update_deferred = False
            self._deferred_retry_timer.stop()
            self.stateChanged.emit()
            return
        block_reason = self._stop_block_reason()
        if block_reason:
            self._status_text = (
                f"更新已延後：{block_reason}；工作完成後會自動重試"
            )
            self.stateChanged.emit()
            self._deferred_retry_timer.start()
            return
        self._update_deferred = False
        self._deferred_retry_timer.stop()
        self.stateChanged.emit()
        self.launchUpdate()

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
        self.stateChanged.emit()
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
        self.stateChanged.emit()
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
