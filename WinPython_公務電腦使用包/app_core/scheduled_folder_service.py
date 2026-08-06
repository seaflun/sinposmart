# -*- coding: utf-8 -*-
"""Scheduled Windows screenshot-folder boundary for the Qt application."""

from __future__ import annotations

import ctypes
import os
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable


SCREENSHOT_FOLDER_SCHEDULE = {
    "1630": "每日勤務表",
    "2155": "夜間勤務",
}


class ScheduledFolderService:
    def __init__(
        self,
        package_root: Path,
        *,
        show_desktop: Callable[[], None] | None = None,
        open_folder: Callable[[Path], None] | None = None,
    ) -> None:
        self.package_root = Path(package_root)
        self._show_desktop = show_desktop or show_windows_desktop
        self._open_folder = open_folder or open_folder_topmost
        self._opened_slots: set[str] = set()
        self._lock = threading.Lock()

    def check_and_open(self, now: datetime) -> Path | None:
        folder = self.claim_due_folder(now)
        if folder is None:
            return None
        self.open(folder)
        return folder

    def claim_due_folder(self, now: datetime) -> Path | None:
        folder_name = SCREENSHOT_FOLDER_SCHEDULE.get(now.strftime("%H%M"))
        if not folder_name:
            return None
        slot_key = now.strftime("%Y%m%d-%H%M")
        with self._lock:
            if slot_key in self._opened_slots:
                return None
            self._opened_slots.add(slot_key)
        folder = self.package_root / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def open(self, folder: Path) -> None:
        self._show_desktop()
        self._open_folder(folder)


def show_windows_desktop() -> None:
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
        return


def open_folder_topmost(folder: Path) -> None:
    folder = Path(folder).resolve()
    try:
        os.startfile(str(folder))
    except OSError:
        subprocess.Popen(["explorer", str(folder)], shell=False)

    deadline = datetime.now() + timedelta(seconds=5)
    while datetime.now() < deadline:
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
