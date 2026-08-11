# -*- coding: utf-8 -*-
"""QML-facing update check and confirmed updater launch coordination."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Property, QThread, QTimer, Signal, Slot

from app_core.update_repository import UpdateCheckError, UpdateRepository, VersionInfo
from qt_app.workers.update_check_worker import UpdateCheckWorker


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
        stop_guard: Callable[[], str] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._repository = repository
        self._process_launcher = process_launcher
        self._stop_guard = stop_guard
        self._current_version = ""
        self._latest_version = ""
        self._status_text = "尚未檢查更新"
        self._update_available = False
        self._request_id = 0
        self._workers: dict[int, tuple[QThread, UpdateCheckWorker]] = {}
        self._shutdown_admission = False
        try:
            self._current_version = repository.current_version()
        except UpdateCheckError as exc:
            self._status_text = str(exc)

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

    def setStopGuard(self, guard: Callable[[], str] | None) -> None:
        self._stop_guard = guard

    @Slot()
    def check(self) -> None:
        if self._shutdown_admission or self._workers:
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
        if not self._update_available:
            self._status_text = "目前沒有可安裝的新版。"
            self.stateChanged.emit()
            return
        block_reason = self._stop_block_reason()
        if block_reason:
            message = f"目前無法更新：{block_reason}"
            self._status_text = message
            self.stateChanged.emit()
            self.errorOccurred.emit(message)
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
