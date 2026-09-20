# -*- coding: utf-8 -*-
"""Independent PySide6 + QML entrypoint for the migration shell."""

from __future__ import annotations

import os
import json
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Sequence

if {
    "--read-only-login-acceptance",
    "--startup-smoke-test",
    "--audit-fixture-acceptance",
} & set(sys.argv[1:]):
    sys.dont_write_bytecode = True
    os.environ["QML_DISABLE_DISK_CACHE"] = "1"
    os.environ.pop("QML_FORCE_DISK_CACHE", None)

import PySide6

_QT_DLL_DIRECTORY_HANDLE = (
    os.add_dll_directory(str(Path(PySide6.__file__).resolve().parent))
    if os.name == "nt" and hasattr(os, "add_dll_directory")
    else None
)

from PySide6.QtCore import QObject, QTimer, QUrl, Qt
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from app_core.diagnostics_service import DiagnosticsService
from app_core.credential_repository import CredentialRepository
from app_core.login_verifier import (
    LoginVerifier,
    build_foreground_chrome_options,
    create_login_webdriver,
)
from app_core.schedule_capture_service import ScheduleCaptureService
from app_core.schedule_repository import ScheduleRepository
from app_core.scheduled_folder_service import ScheduledFolderService
from app_core.session import LoginSession
from app_core.unreturned_return_queue import UnreturnedReturnQueue
from qt_app.controllers.app_controller import AppController
from qt_app.controllers.tray_controller import configure_windows_notification_identity


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
QML_PATH = Path(__file__).with_name("qml") / "Main.qml"
APP_ICON_PATH = PACKAGE_ROOT / "duty_tray_icon.ico"
INSTANCE_SERVER_NAME = "TYFD.SinpoSmart.DutyAutomation.Qt"
READ_ONLY_ACCEPTANCE_ARG = "--read-only-login-acceptance"
STARTUP_SMOKE_ARG = "--startup-smoke-test"
AUDIT_FIXTURE_ACCEPTANCE_ARG = "--audit-fixture-acceptance"


_AUDIT_FIXTURE_TARGET_DATE = "1150729"
_AUDIT_FIXTURE_SCHEDULE = {
    "file_type": "schedule",
    "target_date": _AUDIT_FIXTURE_TARGET_DATE,
    "today": {"staff": {"10": {"name": "離線驗收人員"}}},
    "actions": [
        {
            "kind": "entry_log",
            "time": "09:00",
            "actor": "10",
            "target": "10",
            "source": "外勤離線驗收",
            "fields": {
                "系統寫入時間": "09:00",
                "出或入": "出",
                "領用事由及地點": "離線驗收差異",
            },
        }
    ],
}
_AUDIT_FIXTURE_COMPARISON = {
    "file_type": "comparison",
    "target_date": _AUDIT_FIXTURE_TARGET_DATE,
    "visible_work_rows": [],
    "visible_entry_rows": [],
}


class ReadOnlyOperationalSyncService:
    def enqueue_event(self, _record_type: str, **_fields) -> dict:
        return {}

    def sync_board_async(self, _schedule_data: dict) -> bool:
        return False


def configure_isolated_qt_runtime() -> None:
    """Prevent QML and Qt Quick caches outside the acceptance temporary directory."""

    os.environ["QML_DISABLE_DISK_CACHE"] = "1"
    os.environ.pop("QML_FORCE_DISK_CACHE", None)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DisableShaderDiskCache, True)


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
            quit_after_response = False
            connection.waitForReadyRead(100)
            command = bytes(connection.readAll()).decode("utf-8", errors="ignore").strip()
            if command == "update_prepare":
                prepare = getattr(controller, "prepareUpdateShutdown", None)
                if not callable(prepare):
                    result = "failed"
                else:
                    try:
                        result = str(prepare() or "failed").strip().lower()
                    except Exception:
                        result = "failed"
                if result not in {"ready", "busy", "failed"}:
                    result = "failed"
                response = f"{result}\n".encode("utf-8")
                quit_after_response = result == "ready"
            elif command == "update_logout":
                response = b"ok\n" if controller.recordUpdateLogout() else b"skipped\n"
            elif command in {"update_status", "update_status_handoff"}:
                app = QApplication.instance()
                window = getattr(app, "sinposmart_main_window", None)
                ready = (window is not None and window.isVisible() and window.isExposed()
                         and (command == "update_status_handoff" or not controller.sessionController.isLoggedIn))
                response = f"ready:{os.getpid()}\n".encode("ascii") if ready else b"starting\n"
            else:
                controller.trayController.showWindow()
                response = b"ok\n"
            connection.write(response)
            connection.waitForBytesWritten(250)
            connection.disconnectFromServer()
            if quit_after_response:
                app = QApplication.instance()
                if app is not None:
                    QTimer.singleShot(0, app.quit)


def create_engine(controller: AppController) -> QQmlApplicationEngine:
    """Create and load the QML engine with one context facade."""

    configure_application_font(QApplication.instance())
    QQuickStyle.setStyle("Basic")
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("appController", controller)
    engine.load(QUrl.fromLocalFile(str(QML_PATH)))
    engine.app_controller = controller
    return engine


def configure_audit_fixture(controller: AppController) -> None:
    """Populate an isolated controller with one non-mutating audit scenario."""

    if not controller.offlineFixtureAcceptance:
        raise ValueError("離線審核 fixture 只能在專用離線驗收模式使用。")
    temporary = getattr(controller, "acceptance_temporary_directory", None)
    if not isinstance(temporary, tempfile.TemporaryDirectory) or not temporary.name:
        raise ValueError("離線審核 fixture 只能寫入專用暫存目錄。")
    temporary_root = Path(temporary.name).resolve()
    repository = controller.dutyController._repository
    fixture_path = repository.schedule_path(_AUDIT_FIXTURE_TARGET_DATE)
    comparison_path = repository.comparison_path(_AUDIT_FIXTURE_TARGET_DATE)
    for path in (fixture_path, comparison_path):
        try:
            Path(path).resolve().relative_to(temporary_root)
        except ValueError as exc:
            raise ValueError("離線審核 fixture 輸出必須位於專用暫存目錄。") from exc
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text(
        json.dumps(_AUDIT_FIXTURE_SCHEDULE, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    comparison_path.parent.mkdir(parents=True, exist_ok=True)
    comparison_path.write_text(
        json.dumps(_AUDIT_FIXTURE_COMPARISON, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    attempt_id = controller._session_state.begin_login()
    if attempt_id is None:
        raise RuntimeError("離線審核 fixture 無法建立暫時登入狀態。")
    controller._session_state.complete_login(
        attempt_id,
        LoginSession(
            "10",
            "audit-fixture",
            "",
            verified=True,
            actor_name="離線驗收人員",
        ),
    )
    controller.sessionController.sessionChanged.emit()
    controller.dutyController.set_actor_no("10")
    controller.dutyController.replace_schedule_data(
        {"target_date": _AUDIT_FIXTURE_TARGET_DATE, "actions": []},
    )
    controller.sessionController.setOperationalStatus(
        "離線審核 fixture：僅顯示本次暫存資料。",
        "info",
    )


def show_audit_fixture(engine: QQmlApplicationEngine) -> None:
    """Switch the loaded QML shell into the isolated audit fixture."""

    if not engine.rootObjects():
        return
    mode_tabs = engine.rootObjects()[0].findChild(QObject, "modeTabs")
    if mode_tabs is not None:
        mode_tabs.setProperty("currentIndex", 1)


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
        or AUDIT_FIXTURE_ACCEPTANCE_ARG in arguments
    )
    if not isolated_startup:
        return AppController(
            scheduled_folder_service=ScheduledFolderService(PACKAGE_ROOT),
            automatic_tools_enabled=True,
        )

    temporary = tempfile.TemporaryDirectory(prefix="sinposmart-qml-read-only-")
    temporary_root = Path(temporary.name)
    runtime_output_dir = Path(temporary.name) / "runtime_outputs"
    browser_profile_root = temporary_root / "browser_profiles"
    acceptance_environment = {
        "SE_CACHE_PATH": os.environ.get("SE_CACHE_PATH"),
        "SE_AVOID_STATS": os.environ.get("SE_AVOID_STATS"),
    }
    os.environ["SE_CACHE_PATH"] = str(temporary_root / "selenium_cache")
    os.environ["SE_AVOID_STATS"] = "true"

    def create_read_only_login_webdriver(options: object) -> object:
        return create_login_webdriver(
            options,
            profile_root=browser_profile_root,
            prune_profiles=False,
            write_diagnostics=False,
        )

    try:
        controller = AppController(
            repository=CredentialRepository(
                temporary_root / "saved_login.json",
                "SinpoSmart",
                None,
            ),
            verifier=LoginVerifier(
                options_factory=build_foreground_chrome_options,
                driver_factory=create_read_only_login_webdriver,
                allow_post_login_lookup_warning=True,
                defer_actor_resolution=True,
                session_open_diagnostics=False,
            ),
            credential_sync_service=SimpleNamespace(enabled=False),
            operational_sync_service=ReadOnlyOperationalSyncService(),
            schedule_capture_service=ScheduleCaptureService(
                temporary_root,
                browser_profile_root=browser_profile_root,
                browser_prune_profiles=False,
                browser_write_diagnostics=False,
            ),
            schedule_repository=ScheduleRepository(runtime_output_dir),
            unreturned_return_queue=UnreturnedReturnQueue(runtime_output_dir),
            read_only_acceptance=True,
            offline_fixture_acceptance=AUDIT_FIXTURE_ACCEPTANCE_ARG in arguments,
        )
    except Exception:
        for name, previous_value in acceptance_environment.items():
            if previous_value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous_value
        temporary.cleanup()
        raise
    controller.acceptance_temporary_directory = temporary
    controller.acceptance_temporary_environment = acceptance_environment
    return controller


def cleanup_acceptance_directory(controller: AppController) -> None:
    temporary = getattr(controller, "acceptance_temporary_directory", None)
    acceptance_environment = getattr(controller, "acceptance_temporary_environment", None)
    controller.acceptance_temporary_environment = None
    if isinstance(acceptance_environment, dict):
        for name, previous_value in acceptance_environment.items():
            if previous_value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = str(previous_value)
    if temporary is None:
        return
    controller.acceptance_temporary_directory = None
    temporary.cleanup()


def attach_read_only_result(controller: AppController, app: QApplication) -> None:
    result_value = str(os.environ.get("SINPOSMART_ACCEPTANCE_RESULT", "") or "").strip()
    if not controller.readOnlyAcceptance or not result_value:
        return
    result_reported = False

    def report_result(payload: dict) -> None:
        nonlocal result_reported
        if result_reported:
            return
        result_reported = True
        try:
            print(json.dumps(payload, ensure_ascii=False), flush=True)
        except (AttributeError, OSError):
            pass

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
        report_result(payload)
        QTimer.singleShot(1_500, app.quit)

    def write_cancelled_result() -> None:
        report_result({"ok": False, "cancelled": True})

    controller.dutyController.liveScheduleCaptured.connect(write_result)
    app.aboutToQuit.connect(write_cancelled_result)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(argv) if argv is not None else list(sys.argv)
    startup_smoke = STARTUP_SMOKE_ARG in arguments
    read_only_acceptance = READ_ONLY_ACCEPTANCE_ARG in arguments
    audit_fixture_acceptance = AUDIT_FIXTURE_ACCEPTANCE_ARG in arguments
    if audit_fixture_acceptance and (startup_smoke or read_only_acceptance):
        return 2
    isolated_startup = read_only_acceptance or startup_smoke or audit_fixture_acceptance
    if isolated_startup:
        configure_isolated_qt_runtime()
    if not startup_smoke and not audit_fixture_acceptance:
        load_package_env()
    if isolated_startup:
        configure_isolated_qt_runtime()
    configure_windows_notification_identity()
    app = QApplication(arguments)
    app.setApplicationName("SinpoSmart")
    app.setApplicationDisplayName("SinpoSmart")
    if APP_ICON_PATH.is_file():
        app.setWindowIcon(QIcon(str(APP_ICON_PATH)))

    if startup_smoke:
        server_name = f"{INSTANCE_SERVER_NAME}.StartupSmoke.{os.getpid()}"
    elif audit_fixture_acceptance:
        server_name = f"{INSTANCE_SERVER_NAME}.AuditFixture.{os.getpid()}"
    elif read_only_acceptance:
        server_name = INSTANCE_SERVER_NAME + ".ReadOnlyAcceptance"
    else:
        server_name = INSTANCE_SERVER_NAME
    instance_server = create_instance_server(server_name)
    if instance_server is None:
        return 0

    if not isolated_startup:
        retention = DiagnosticsService(PACKAGE_ROOT)
        retention_worker = None

        def cleanup_retention() -> None:
            nonlocal retention_worker
            if retention_worker is None or not retention_worker.is_alive():
                retention_worker = threading.Thread(target=retention.cleanup_retained_files, daemon=True)
                retention_worker.start()

        cleanup_retention()
        retention_timer = QTimer(app)
        retention_timer.setInterval(24 * 60 * 60 * 1000)
        retention_timer.timeout.connect(cleanup_retention)
        retention_timer.start()

    controller = create_app_controller(arguments)
    controller.nativeTitleBarRequested.connect(schedule_windows_title_bar)
    app.aboutToQuit.connect(controller.shutdown)
    attach_read_only_result(controller, app)
    if audit_fixture_acceptance:
        configure_audit_fixture(controller)
    engine = create_engine(controller)
    if not engine.rootObjects():
        controller.shutdown()
        instance_server.close()
        QLocalServer.removeServer(server_name)
        cleanup_acceptance_directory(controller)
        return 1
    root_window = engine.rootObjects()[0]
    app.sinposmart_main_window = root_window
    if not isolated_startup:
        QTimer.singleShot(0, controller.resumePendingAutoLogin)
    root_window.windowTitleChanged.connect(
        lambda _title: schedule_windows_title_bar(root_window)
    )
    schedule_windows_title_bar(root_window)
    if audit_fixture_acceptance:
        show_audit_fixture(engine)
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
