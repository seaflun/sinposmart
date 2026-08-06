# -*- coding: utf-8 -*-
"""Independent PySide6 + QML entrypoint for the migration shell."""

from __future__ import annotations

import os
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Sequence

import PySide6

_QT_DLL_DIRECTORY_HANDLE = (
    os.add_dll_directory(str(Path(PySide6.__file__).resolve().parent))
    if os.name == "nt" and hasattr(os, "add_dll_directory")
    else None
)

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from app_core.credential_repository import CredentialRepository
from app_core.login_verifier import (
    LoginVerifier,
    build_foreground_chrome_options,
)
from app_core.schedule_capture_service import ScheduleCaptureService
from app_core.scheduled_folder_service import ScheduledFolderService
from qt_app.controllers.app_controller import AppController


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
QML_PATH = Path(__file__).with_name("qml") / "Main.qml"
APP_ICON_PATH = PACKAGE_ROOT / "duty_tray_icon.ico"
INSTANCE_SERVER_NAME = "TYFD.SinpoSmart.DutyAutomation.Qt"
READ_ONLY_ACCEPTANCE_ARG = "--read-only-login-acceptance"
STARTUP_SMOKE_ARG = "--startup-smoke-test"


class ReadOnlyOperationalSyncService:
    def enqueue_event(self, _record_type: str, **_fields) -> dict:
        return {}

    def sync_board_async(self, _schedule_data: dict) -> bool:
        return False


def load_package_env(package_root: Path = PACKAGE_ROOT) -> None:
    env_path = Path(package_root) / ".env"
    if not env_path.is_file():
        return
    try:
        lines = env_path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return
    for line in lines:
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def create_instance_server(server_name: str = INSTANCE_SERVER_NAME) -> QLocalServer | None:
    probe = QLocalSocket()
    probe.connectToServer(server_name)
    if probe.waitForConnected(250):
        probe.write(b"show")
        probe.waitForBytesWritten(250)
        probe.disconnectFromServer()
        return None
    QLocalServer.removeServer(server_name)
    server = QLocalServer()
    return server if server.listen(server_name) else None


def show_existing_window_requests(server: QLocalServer, controller: AppController) -> None:
    while server.hasPendingConnections():
        connection = server.nextPendingConnection()
        if connection is not None:
            connection.waitForReadyRead(100)
            command = bytes(connection.readAll()).decode("utf-8", errors="ignore").strip()
            if command == "update_logout":
                response = b"ok\n" if controller.recordUpdateLogout() else b"skipped\n"
            else:
                controller.trayController.showWindow()
                response = b"ok\n"
            connection.write(response)
            connection.waitForBytesWritten(250)
            connection.disconnectFromServer()


def create_engine(controller: AppController) -> QQmlApplicationEngine:
    """Create and load the QML engine with one context facade."""

    configure_application_font(QApplication.instance())
    QQuickStyle.setStyle("Basic")
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("appController", controller)
    engine.load(QUrl.fromLocalFile(str(QML_PATH)))
    engine.app_controller = controller
    return engine


def configure_application_font(application: QApplication | None) -> str:
    """Choose a Windows UI font that includes Traditional Chinese glyphs."""

    if application is None:
        return ""
    families = set(QFontDatabase.families())
    preferred_families = (
        "Microsoft JhengHei UI",
        "Microsoft JhengHei",
        "Noto Sans TC",
        "MingLiU",
    )
    if not any(family in families for family in preferred_families):
        fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("msjh.ttc", "NotoSansTC-VF.ttf", "mingliu.ttc"):
            font_path = fonts_dir / filename
            if not font_path.is_file():
                continue
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            if font_id >= 0:
                families.update(QFontDatabase.applicationFontFamilies(font_id))
            if any(family in families for family in preferred_families):
                break
    for family in (*preferred_families, "Segoe UI"):
        if family in families:
            application.setFont(QFont(family, 10))
            return family
    return application.font().family()


def configure_windows_title_bar(window) -> None:
    """Apply a light native caption to windows that retain one."""

    if os.name != "nt" or window is None:
        return
    if bool(window.property("usesCustomTitleBar")):
        return
    try:
        import ctypes

        hwnd = int(window.winId())
        if not hwnd:
            return
        dwmapi = ctypes.windll.dwmapi
        dark_mode = ctypes.c_int(0)
        dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark_mode), ctypes.sizeof(dark_mode))
        for attribute, color in (
            (35, 0x00FFF5ED),  # #EDF5FF caption
            (36, 0x00653B12),  # #123B65 caption text
            (34, 0x00DCE6D7),  # #D7E6DC border
        ):
            color_ref = ctypes.c_int(color)
            dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(color_ref), ctypes.sizeof(color_ref))
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        pass


def schedule_windows_title_bar(window) -> None:
    """Reapply the native caption after Qt has finished updating a window title."""

    configure_windows_title_bar(window)
    for delay in (0, 75, 250):
        QTimer.singleShot(delay, lambda target=window: configure_windows_title_bar(target))


def create_app_controller(arguments: Sequence[str]) -> AppController:
    isolated_startup = (
        READ_ONLY_ACCEPTANCE_ARG in arguments
        or STARTUP_SMOKE_ARG in arguments
    )
    if not isolated_startup:
        return AppController(
            scheduled_folder_service=ScheduledFolderService(PACKAGE_ROOT),
        )

    temporary = tempfile.TemporaryDirectory(prefix="sinposmart-qml-read-only-")
    controller = AppController(
        repository=CredentialRepository(
            Path(temporary.name) / "saved_login.json",
            "SinpoSmart",
            None,
        ),
        verifier=LoginVerifier(
            options_factory=build_foreground_chrome_options,
            allow_post_login_lookup_warning=True,
            defer_actor_resolution=True,
        ),
        credential_sync_service=SimpleNamespace(enabled=False),
        operational_sync_service=ReadOnlyOperationalSyncService(),
        schedule_capture_service=ScheduleCaptureService(Path(temporary.name)),
        read_only_acceptance=True,
    )
    controller.acceptance_temporary_directory = temporary
    return controller


def cleanup_acceptance_directory(controller: AppController) -> None:
    temporary = getattr(controller, "acceptance_temporary_directory", None)
    if temporary is None:
        return
    controller.acceptance_temporary_directory = None
    temporary.cleanup()


def attach_read_only_result(controller: AppController, app: QApplication) -> None:
    result_value = str(os.environ.get("SINPOSMART_ACCEPTANCE_RESULT", "") or "").strip()
    if not controller.readOnlyAcceptance or not result_value:
        return
    result_path = Path(result_value).resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if temp_root not in result_path.parents:
        return

    def write_result(schedule_data: dict) -> None:
        today = schedule_data.get("today") or {}
        payload = {
            "ok": True,
            "target_date_valid": len(str(schedule_data.get("target_date", ""))) == 7,
            "today_staff_count": len(today.get("staff", {})),
            "today_row_count": len(today.get("rows", [])),
            "action_count": len(schedule_data.get("actions", [])),
            "case_count": len(schedule_data.get("cases", [])),
        }
        result_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        QTimer.singleShot(1_500, app.quit)

    def write_cancelled_result() -> None:
        if not result_path.exists():
            result_path.write_text(
                json.dumps({"ok": False, "cancelled": True}),
                encoding="utf-8",
            )

    controller.dutyController.liveScheduleCaptured.connect(write_result)
    app.aboutToQuit.connect(write_cancelled_result)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(argv) if argv is not None else list(sys.argv)
    startup_smoke = STARTUP_SMOKE_ARG in arguments
    if not startup_smoke:
        load_package_env()
    app = QApplication(arguments)
    app.setApplicationName("SinpoSmart")
    app.setApplicationDisplayName("SinpoSmart")
    if APP_ICON_PATH.is_file():
        app.setWindowIcon(QIcon(str(APP_ICON_PATH)))

    read_only_acceptance = READ_ONLY_ACCEPTANCE_ARG in arguments
    isolated_startup = read_only_acceptance or startup_smoke
    if startup_smoke:
        server_name = f"{INSTANCE_SERVER_NAME}.StartupSmoke.{os.getpid()}"
    elif read_only_acceptance:
        server_name = INSTANCE_SERVER_NAME + ".ReadOnlyAcceptance"
    else:
        server_name = INSTANCE_SERVER_NAME
    instance_server = create_instance_server(server_name)
    if instance_server is None:
        return 0

    controller = create_app_controller(arguments)
    controller.nativeTitleBarRequested.connect(schedule_windows_title_bar)
    app.aboutToQuit.connect(controller.shutdown)
    attach_read_only_result(controller, app)
    engine = create_engine(controller)
    if not engine.rootObjects():
        controller.shutdown()
        instance_server.close()
        QLocalServer.removeServer(server_name)
        cleanup_acceptance_directory(controller)
        return 1
    root_window = engine.rootObjects()[0]
    root_window.windowTitleChanged.connect(
        lambda _title: schedule_windows_title_bar(root_window)
    )
    schedule_windows_title_bar(root_window)
    if not isolated_startup:
        controller.trayController.initialize(engine.rootObjects()[0], app.windowIcon())
    instance_server.newConnection.connect(
        lambda: show_existing_window_requests(instance_server, controller)
    )
    app.instance_server = instance_server
    app.setQuitOnLastWindowClosed(isolated_startup or not controller.trayController.available)
    if startup_smoke:
        QTimer.singleShot(250, app.quit)
    try:
        return app.exec()
    finally:
        instance_server.close()
        QLocalServer.removeServer(server_name)
        cleanup_acceptance_directory(controller)


if __name__ == "__main__":
    raise SystemExit(main())
