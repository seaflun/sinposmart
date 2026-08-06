# -*- coding: utf-8 -*-
"""PySide6 system-tray and top-level-window lifecycle controller."""

from __future__ import annotations

import ctypes
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Property, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon


try:
    import pythoncom
    from win32com.propsys import propsys, pscon
    from win32com.shell import shell
except Exception:
    pythoncom = None
    propsys = None
    pscon = None
    shell = None

try:
    from win11toast import toast as win11_toast
except Exception:
    win11_toast = None


APP_DISPLAY_NAME = "SinpoSmart"
APP_USER_MODEL_ID = "TYFD.DutyAutomation"
PACKAGE_ROOT = Path(__file__).resolve().parents[2]
APP_ICON_PATH = PACKAGE_ROOT / "duty_tray_icon.ico"


class _WindowsToastRunnable(QRunnable):
    """Run the blocking Windows Toast callback loop off the Qt UI thread."""

    def __init__(self, title: str, message: str) -> None:
        super().__init__()
        self._title = title
        self._message = message

    def run(self) -> None:
        if win11_toast is None:
            return
        try:
            win11_toast(
                self._title,
                self._message,
                app_id=APP_USER_MODEL_ID,
                on_click=lambda _args=None: None,
                on_dismissed=lambda _reason=None: None,
                on_failed=lambda _error=None: None,
            )
        except Exception:
            pass


def configure_windows_notification_identity() -> None:
    """Associate native notifications with SinpoSmart instead of pythonw.exe."""

    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except (AttributeError, OSError, RuntimeError, TypeError):
        pass


def ensure_windows_notification_shortcut() -> bool:
    """Create the Start-menu shortcut Windows uses to name the toast source."""

    if os.name != "nt" or not all((pythoncom, propsys, pscon, shell)):
        return False
    app_data = os.environ.get("APPDATA", "").strip()
    if not app_data:
        return False
    try:
        shortcut_dir = Path(app_data) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        shortcut_dir.mkdir(parents=True, exist_ok=True)
        shortcut_path = shortcut_dir / f"{APP_DISPLAY_NAME}.lnk"
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        target = pythonw if pythonw.exists() else Path(sys.executable)
        entrypoint = PACKAGE_ROOT / "duty_gui.pyw"

        pythoncom.CoInitialize()
        shortcut = pythoncom.CoCreateInstance(
            shell.CLSID_ShellLink,
            None,
            pythoncom.CLSCTX_INPROC_SERVER,
            shell.IID_IShellLink,
        )
        shortcut.SetPath(str(target))
        shortcut.SetArguments(f'"{entrypoint}"')
        shortcut.SetWorkingDirectory(str(PACKAGE_ROOT))
        if APP_ICON_PATH.is_file():
            shortcut.SetIconLocation(str(APP_ICON_PATH), 0)
        property_store = shortcut.QueryInterface(propsys.IID_IPropertyStore)
        property_store.SetValue(
            pscon.PKEY_AppUserModel_ID,
            propsys.PROPVARIANTType(APP_USER_MODEL_ID, pythoncom.VT_LPWSTR),
        )
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


def show_windows_notification(title: str, message: str) -> bool:
    """Use the same Windows Toast path as the legacy duty GUI when available."""

    if os.name != "nt" or win11_toast is None or os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return False
    try:
        configure_windows_notification_identity()
        ensure_windows_notification_shortcut()
        QThreadPool.globalInstance().start(_WindowsToastRunnable(str(title), str(message)))
        return True
    except Exception:
        return False


class TrayController(QObject):
    stateChanged = Signal()

    def __init__(
        self,
        app: QApplication | None,
        *,
        tray_available: bool | None = None,
        native_notifier: Callable[[str, str], bool] = show_windows_notification,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._app = app
        self._availability_override = tray_available
        self._native_notifier = native_notifier
        self._available = bool(tray_available) if tray_available is not None else False
        self._quit_requested = False
        self._window: Any | None = None
        self._tray: QSystemTrayIcon | None = None
        self._menu: QMenu | None = None

    @Property(bool, notify=stateChanged)
    def available(self) -> bool:
        return self._available

    @Property(bool, notify=stateChanged)
    def quitRequested(self) -> bool:
        return self._quit_requested

    def initialize(self, window: Any, icon: QIcon | None = None) -> None:
        self._window = window
        if self._tray is not None:
            return
        configure_windows_notification_identity()
        ensure_windows_notification_shortcut()
        available = (
            bool(self._availability_override)
            if self._availability_override is not None
            else QSystemTrayIcon.isSystemTrayAvailable()
        )
        self._available = available
        if not available:
            self.stateChanged.emit()
            return

        tray = QSystemTrayIcon(icon or QIcon(), self)
        menu = QMenu()
        show_action = QAction("顯示 SinpoSmart", menu)
        show_action.triggered.connect(self.showWindow)
        hide_action = QAction("縮小到背景", menu)
        hide_action.triggered.connect(self.hideWindow)
        quit_action = QAction("結束程式", menu)
        quit_action.triggered.connect(self.requestQuit)
        menu.addAction(show_action)
        menu.addAction(hide_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        tray.setContextMenu(menu)
        tray.setToolTip("SinpoSmart")
        tray.activated.connect(self._tray_activated)
        tray.show()
        self._tray = tray
        self._menu = menu
        self.stateChanged.emit()

    def attach_window(self, window: Any) -> None:
        self._window = window

    @Slot(result=bool)
    def interceptClose(self) -> bool:
        if not self._available or self._quit_requested:
            return False
        self.hideWindow()
        return True

    @Slot()
    def showWindow(self) -> None:
        if self._window is None:
            return
        self._window.show()
        if hasattr(self._window, "raise_"):
            self._window.raise_()
        if hasattr(self._window, "requestActivate"):
            self._window.requestActivate()

    @Slot()
    def hideWindow(self) -> None:
        if self._window is not None:
            self._window.hide()

    @Slot(str, str)
    def notify(self, title: str, message: str) -> None:
        notification_title = str(title or APP_DISPLAY_NAME).strip() or APP_DISPLAY_NAME
        notification_message = str(message)
        if self._native_notifier(notification_title, notification_message):
            return
        if self._tray is not None and self._available:
            self._tray.showMessage(APP_DISPLAY_NAME, notification_message, QSystemTrayIcon.Information, 5000)

    @Slot()
    def requestQuit(self) -> None:
        self._quit_requested = True
        if self._tray is not None:
            self._tray.hide()
        self.stateChanged.emit()
        if self._app is not None:
            self._app.quit()

    @Slot()
    def shutdown(self) -> None:
        if self._tray is not None:
            self._tray.hide()

    @Slot(QSystemTrayIcon.ActivationReason)
    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.showWindow()
