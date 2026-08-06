# -*- coding: utf-8 -*-
"""PySide6 system-tray and top-level-window lifecycle controller."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Property, Signal, Slot
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon


class TrayController(QObject):
    stateChanged = Signal()

    def __init__(
        self,
        app: QApplication | None,
        *,
        tray_available: bool | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._app = app
        self._availability_override = tray_available
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
        if self._tray is not None and self._available:
            self._tray.showMessage(str(title), str(message), QSystemTrayIcon.Information, 5000)

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
