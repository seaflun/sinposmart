from __future__ import annotations

import sys
import os
import json
import hashlib
from contextlib import ExitStack
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

PACKAGE = Path(__file__).resolve().parents[1] / "WinPython_公務電腦使用包"
sys.path.insert(0, str(PACKAGE))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app_core.civilpower_service import AttendanceRequest, CivilpowerService, CivilpowerError


MEMBER = {"member_id": "m1", "name": "測試義消", "title": "隊員", "unit": "大園救護分隊"}


class AttendanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["civilpower-tests"])

    def tearDown(self):
        from PySide6.QtCore import QCoreApplication, QEvent
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.processEvents()

    def request(self, action="到勤", **changes):
        values = dict(user_id="duty1", password="not-a-real-password", actor_no="1",
                      actor_name="測試值班員", member=MEMBER, date_text="2026-09-23",
                      time_text="09:05", action=action)
        values.update(changes)
        return AttendanceRequest(**values)

    def test_arrival_departure_and_calendar_dates(self):
        service = CivilpowerService(PACKAGE)
        for action, status in (("到勤", "服勤"), ("退勤", "退勤")):
            plan = service.validate(self.request(action))
            self.assertEqual((plan.home_unit, plan.status, plan.reason, plan.date_text, plan.time_text),
                             ("大園救護分隊", status, action, "2026/09/23", "0905"))
        self.assertEqual(service.validate(self.request("退勤", date_text="2026-09-24")).date_text,
                         "2026/09/24")

    def test_rejects_invalid_inputs_before_browser(self):
        service = CivilpowerService(PACKAGE)
        for changes in ({"date_text": "2026-02-30"}, {"time_text": "24:00"},
                        {"action": "救護出勤"}, {"user_id": ""},
                        {"member": {**MEMBER, "unit": "其他單位"}}):
            with self.subTest(changes=changes), self.assertRaises(CivilpowerError):
                service.validate(self.request(**changes))
        self.assertNotIn("not-a-real-password", repr(self.request()))

    def test_roster_groups_and_offline_cache(self):
        with TemporaryDirectory() as root:
            fetch = Mock(return_value={"ok": True, "members": [MEMBER,
                {**MEMBER, "member_id": "m2", "name": "另一位"}],
                "frequent_member_ids": ["m1"], "last_success_at": "2026-09-23T08:00:00"})
            service = CivilpowerService(Path(root), roster_fetcher=fetch)
            roster = service.load_roster()
            self.assertEqual(roster["members"][0]["member_id"], "m1")
            self.assertTrue(roster["members"][0]["frequent"])
            fetch.side_effect = OSError("unreachable")
            cached = service.load_roster()
            self.assertTrue(cached["cached"])
            self.assertEqual(cached["last_success_at"], "2026-09-23T08:00:00")

    def test_no_roster_never_invents_members(self):
        with TemporaryDirectory() as root:
            service = CivilpowerService(Path(root), roster_fetcher=Mock(side_effect=OSError()))
            with self.assertRaises(CivilpowerError):
                service.load_roster()

    def test_login_retries_only_the_supplied_actor(self):
        from app_core import civilpower_automation as automation
        request = self.request()
        with patch.object(automation, "_login_once", side_effect=[RuntimeError(), None]) as login:
            automation.login_attendance(Mock(), request, Mock(), Mock())
        self.assertEqual(login.call_count, 2)
        self.assertTrue(all(call.args[1] is request for call in login.call_args_list))

    def test_failed_login_masks_raw_errors_and_does_not_fallback(self):
        from app_core import civilpower_automation as automation
        with patch.object(automation, "_login_once", side_effect=RuntimeError("password=secret")) as login:
            with self.assertRaises(CivilpowerError) as result:
                automation.login_attendance(Mock(), self.request(), Mock(), Mock())
        self.assertEqual(login.call_count, 3)
        self.assertNotIn("secret", str(result.exception))

    def test_existing_record_never_saves(self):
        from app_core import civilpower_automation as automation
        plan = CivilpowerService(PACKAGE).validate(self.request())
        with patch.object(automation, "_find_io_record", return_value=True), \
                patch.object(automation, "_click") as click:
            created = automation._ensure_io_record(Mock(), plan, plan.status, {}, cancel_check=None,
                                                    require_lookup_confirmation=True)
        self.assertFalse(created)
        click.assert_not_called()

    def test_ambiguous_query_never_saves(self):
        from app_core import civilpower_automation as automation
        plan = CivilpowerService(PACKAGE).validate(self.request())
        with patch.object(automation, "_find_io_record", side_effect=RuntimeError("query incomplete")), \
                patch.object(automation, "_click") as click:
            with self.assertRaises(RuntimeError):
                automation._ensure_io_record(Mock(), plan, plan.status, {}, cancel_check=None,
                                              require_lookup_confirmation=True)
        click.assert_not_called()

    def test_new_record_writes_correct_fields_and_requires_readback(self):
        from app_core import civilpower_automation as automation
        for action, status in (("到勤", "服勤"), ("退勤", "退勤")):
            plan = CivilpowerService(PACKAGE).validate(self.request(action))
            checkpoint = {}
            with self.subTest(action=action), ExitStack() as stack:
                mocked = {name: stack.enter_context(patch.object(automation, name)) for name in (
                    "WebDriverWait", "_click", "_wait_visible", "_select_jqx_combobox",
                    "_wait_for_io_form_dependencies", "_select_io_person", "_set_input",
                    "_select_option_containing", "_wait_for_io_record_form_values", "_wait_after_save")}
                query = stack.enter_context(patch.object(automation, "_find_io_record", side_effect=[False, True]))
                before = Mock()
                self.assertTrue(automation._ensure_io_record(Mock(), plan, status, checkpoint,
                    cancel_check=None, require_lookup_confirmation=True, before_save=before))
                inputs = {call.args[1]: call.args[2] for call in mocked["_set_input"].call_args_list}
                self.assertEqual(inputs, {"#txt_AddLogDate": "2026/09/23", "#txt_AddLogHour": "09",
                                          "#txt_AddLogMin": "05", "#txt_AddReason": action})
                self.assertEqual(mocked["_select_option_containing"].call_args.args[2], status)
                self.assertTrue(query.call_args.kwargs["raise_on_timeout"])
                before.assert_called_once()

    def test_failed_readback_remains_pending(self):
        from app_core import civilpower_automation as automation
        plan = CivilpowerService(PACKAGE).validate(self.request())
        checkpoint = {}
        with ExitStack() as stack:
            for name in ("WebDriverWait", "_click", "_wait_visible", "_select_jqx_combobox",
                         "_wait_for_io_form_dependencies", "_select_io_person", "_set_input",
                         "_select_option_containing", "_wait_for_io_record_form_values", "_wait_after_save"):
                stack.enter_context(patch.object(automation, name))
            stack.enter_context(patch.object(automation, "_find_io_record", side_effect=[False, False]))
            with self.assertRaises(RuntimeError):
                automation._ensure_io_record(Mock(), plan, plan.status, checkpoint, cancel_check=None,
                                             require_lookup_confirmation=True)
        self.assertEqual(checkpoint["in_save_state"], "pending_verification")

    def test_pending_record_rejects_different_actor_before_browser(self):
        from app_core import civilpower_automation as automation
        with TemporaryDirectory() as root:
            request = self.request()
            plan = CivilpowerService(PACKAGE).validate(request)
            identity = json.dumps([plan.member_id, plan.date_text, plan.time_text, plan.status, plan.reason], ensure_ascii=False)
            ledger = Path(root) / "runtime_outputs" / "civilpower" / (hashlib.sha256(identity.encode()).hexdigest() + ".json")
            ledger.parent.mkdir(parents=True)
            ledger.write_text(json.dumps({"state": "pending_verification", "user_id": "other-duty"}))
            with patch("app_core.login_verifier.create_login_webdriver") as browser:
                with self.assertRaisesRegex(CivilpowerError, "原登打帳號"):
                    automation.run_attendance(Path(root), request, plan, Mock())
                browser.assert_not_called()

    def test_standalone_execution_logs_in_verifies_closes_and_remembers_success(self):
        from app_core import civilpower_automation as automation
        with TemporaryDirectory() as root, ExitStack() as stack:
            driver = Mock()
            browser = stack.enter_context(patch("app_core.login_verifier.create_login_webdriver", return_value=driver))
            stack.enter_context(patch("app_core.login_verifier.configure_login_webdriver_timeouts"))
            stack.enter_context(patch.dict(sys.modules, {"ddddocr": Mock()}))
            login = stack.enter_context(patch.object(automation, "login_attendance"))
            def verify(_driver, _plan, _status, checkpoint, **kwargs):
                kwargs["before_save"]()
                checkpoint["in_save_state"] = "verified"
                return True
            save = stack.enter_context(patch.object(automation, "_ensure_io_record", side_effect=verify))
            request = self.request()
            plan = CivilpowerService(PACKAGE).validate(request)
            message = automation.run_attendance(Path(root), request, plan, Mock())
            self.assertIn("已儲存並回查確認", message)
            self.assertIs(login.call_args.args[1], request)
            driver.quit.assert_called_once()
            ledger = next((Path(root) / "runtime_outputs" / "civilpower").glob("*.json"))
            self.assertEqual(json.loads(ledger.read_text())["state"], "verified")
            self.assertNotIn(request.password, ledger.read_text())
            self.assertIn("未重複新增", automation.run_attendance(Path(root), request, plan, Mock()))
            browser.assert_called_once()
            save.assert_called_once()

    def test_incomplete_and_ambiguous_lookup_fail_closed(self):
        from app_core import civilpower_automation as automation
        plan = CivilpowerService(PACKAGE).validate(self.request())
        for ready, rows in ((False, []), (True, [Mock(), Mock()])):
            with self.subTest(ready=ready), ExitStack() as stack:
                for name in ("_open_io_work_log", "_set_if_present", "_select_option_containing_if_present",
                             "_io_result_grid_signature", "_io_result_grid_sentinel", "_click_if_present"):
                    stack.enter_context(patch.object(automation, name))
                stack.enter_context(patch.object(automation, "_wait_for_io_query_result_grid", return_value=ready))
                stack.enter_context(patch.object(automation, "_find_paginated_table_rows", return_value=rows))
                with self.assertRaises(RuntimeError):
                    automation._find_io_record_row(Mock(), plan, "服勤", require_query_confirmation=True)

    def test_localized_times_are_exact_to_minute(self):
        from app_core.civilpower_automation import _token_matches
        self.assertTrue(_token_matches("2026/09/23 上午 12:05:10", "2026/09/23 00:05"))
        self.assertTrue(_token_matches("2026/09/23 下午 12:05:10", "2026/09/23 12:05"))
        self.assertFalse(_token_matches("2026/09/23 下午 01:05:10", "2026/09/23 01:05"))
        self.assertTrue(_token_matches("測試義消 服勤 到勤", "服勤"))
        self.assertTrue(_token_matches("測試義消 退勤 退勤", "退勤"))
        self.assertFalse(_token_matches("測試義消 服勤 到勤", "退勤"))

    def test_controller_runs_in_background_and_rejects_double_submit(self):
        from PySide6.QtWidgets import QApplication
        from PySide6.QtTest import QTest
        from app_core.session import LoginSession, SessionState
        from qt_app.controllers.civilpower_controller import CivilpowerController
        app = QApplication.instance() or QApplication([])
        state = SessionState()
        state.session = LoginSession("1", "duty1", "fake", verified=True, actor_name="測試")
        runner = Mock(return_value="已儲存並回查確認。")
        controller = CivilpowerController(state, CivilpowerService(PACKAGE, runner=runner))
        controller._members = [MEMBER]
        controller.prepareRun("2026-09-23", "09:05", "m1", "到勤")
        controller.confirmRun()
        controller.confirmRun()
        for _ in range(100):
            QTest.qWait(10)
            if not controller.isRunning:
                break
        self.assertFalse(controller.isRunning)
        runner.assert_called_once()
        self.assertIn("已儲存", controller.statusText)
        controller.shutdown()

    def test_controller_freezes_actor_and_rejects_changed_confirmation(self):
        from PySide6.QtWidgets import QApplication
        from app_core.session import LoginSession, SessionState
        from qt_app.controllers.civilpower_controller import CivilpowerController
        app = QApplication.instance() or QApplication([])
        state = SessionState()
        state.session = LoginSession("1", "duty1", "secret1", verified=True, actor_name="甲")
        controller = CivilpowerController(state, CivilpowerService(PACKAGE))
        controller._members = [MEMBER]
        controller.prepareRun("2026-09-23", "09:05", "m1", "到勤")
        self.assertIn("甲", controller.confirmationSummary)
        state.session = LoginSession("2", "duty2", "secret2", verified=True, actor_name="乙")
        with patch.object(controller, "_start_job") as start:
            controller.confirmRun()
            start.assert_not_called()
        self.assertIn("已變更", controller.statusText)
        controller.prepareRun("2026-09-23", "09:05", "m1", "退勤")
        with patch.object(controller, "_start_job") as start:
            controller.confirmRun()
            request = start.call_args.args[0]
        state.clear_session()
        self.assertEqual(request.user_id, "duty2")
        self.assertEqual(request.action, "退勤")

    def test_read_only_controller_never_starts_network_or_browser(self):
        from PySide6.QtWidgets import QApplication
        from app_core.session import SessionState
        from qt_app.controllers.civilpower_controller import CivilpowerController
        app = QApplication.instance() or QApplication([])
        controller = CivilpowerController(SessionState(), Mock(), read_only_acceptance=True)
        with patch.object(controller, "_start_job") as start:
            controller.loadDefaults()
            controller.refreshRoster()
            controller.prepareRun("2026-09-23", "09:05", "m1", "到勤")
            controller.confirmRun()
            start.assert_not_called()

    def test_logout_requires_confirmation_and_cancel_preserves_session(self):
        from PySide6.QtCore import QObject, QPointF, Qt, QMetaObject
        from PySide6.QtTest import QTest
        from app_core.session import LoginSession
        from app_core.credential_repository import CredentialRepository
        from app_core.schedule_repository import ScheduleRepository
        from qt_app.controllers.app_controller import AppController
        from qt_app.main import create_engine

        with TemporaryDirectory() as root_dir:
            controller = AppController(
                repository=CredentialRepository(Path(root_dir) / "accounts.json", "test", None),
                schedule_repository=ScheduleRepository(Path(root_dir)),
                read_only_acceptance=True)
            controller._session_state.session = LoginSession("1", "fixture", "fake", verified=True)
            engine = create_engine(controller)
            root = engine.rootObjects()[0]
            root.show()
            try:
                QTest.qWait(100)
                button = root.findChild(QObject, "logoutButton")
                dialog = root.findChild(QObject, "logoutConfirmation")
                self.assertIsNotNone(dialog)
                point = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
                with patch.object(controller, "_begin_session_logout") as logout:
                    QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, point)
                    QTest.qWait(100)
                    self.assertTrue(dialog.property("visible"))
                    logout.assert_not_called()
                    QMetaObject.invokeMethod(dialog, "reject")
                    QTest.qWait(100)
                    self.assertTrue(controller.sessionController.isLoggedIn)
                    logout.assert_not_called()
                    QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, point)
                    QTest.qWait(100)
                    QMetaObject.invokeMethod(dialog, "accept")
                    logout.assert_called_once()
                    self.assertEqual(logout.call_args.args, ("",))
            finally:
                root.hide()
                controller.shutdown()
                engine.deleteLater()

    def test_native_cards_and_attendance_panel_render_at_existing_width(self):
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtTest import QTest
        from app_core.session import LoginSession
        from app_core.credential_repository import CredentialRepository
        from app_core.schedule_repository import ScheduleRepository
        from qt_app.controllers.app_controller import AppController
        from qt_app.main import create_engine
        app = QApplication.instance() or QApplication([])
        with TemporaryDirectory() as root_dir:
            controller = AppController(
                repository=CredentialRepository(Path(root_dir) / "accounts.json", "test", None),
                schedule_repository=ScheduleRepository(Path(root_dir)),
                read_only_acceptance=True)
            controller._session_state.session = LoginSession("1", "fixture", "fake", verified=True, actor_name="測試值班員")
            engine = create_engine(controller)
            self.assertTrue(engine.rootObjects())
            root = engine.rootObjects()[0]
            root.show()
            QTest.qWait(150)
            def find(name):
                stack = [root.contentItem()]
                while stack:
                    item = stack.pop()
                    if item.objectName() == name:
                        return item
                    stack.extend(item.childItems())
                self.fail("Missing visual: " + name)
            left, right = find("dailyMonthlyOperationCard"), find("otherToolsCard")
            self.assertEqual(root.width(), 550)
            self.assertAlmostEqual(left.height(), right.height(), delta=1)
            self.assertGreater(right.x(), left.x() + left.width())
            self.assertLessEqual(right.x() + right.width(), left.parentItem().width() + 1)
            for name in ("quickDutySheetToolButton", "quickDailyVehicleToolButton", "quickRestTimeToolButton",
                         "quickMonthlyBaseToolButton", "quickRescueVideoToolButton", "quickCivilpowerToolButton"):
                button = find(name)
                self.assertGreater(button.width(), 75)
                self.assertTrue(button.isVisible())
            panel = find("civilpowerDialog")
            button = find("quickCivilpowerToolButton")
            # Enable only the fixture's entry button; the controller remains read-only.
            button.setProperty("enabled", True)
            point = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
            QTest.mouseClick(root, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
            button.setProperty("enabled", False)
            QTest.qWait(250)
            self.assertTrue(panel.property("opened"))
            self.assertGreater(root.width(), 550)
            self.assertFalse(find("civilpowerSubmitButton").isEnabled())
            self.assertEqual(find("civilpowerHomeUnitField").property("text"), "大園救護分隊")
            self.assertTrue(find("civilpowerDateCalendarButton").isVisible())
            self.assertTrue(find("civilpowerTimeClockButton").isVisible())
            controller.civilpowerController._roster_loaded({"members": [{**MEMBER, "label": "★ 測試義消"}],
                                                           "cached": False, "last_success_at": "2026-09-23T09:00:00"})
            QTest.qWait(20)
            self.assertEqual(find("civilpowerMemberCombo").property("currentIndex"), -1)
            preview = os.environ.get("CIVILPOWER_PREVIEW_PATH")
            if preview:
                target = Path(preview)
                target.parent.mkdir(parents=True, exist_ok=True)
                self.assertTrue(root.grabWindow().save(str(target)))
            root.hide()
            controller.shutdown()
            engine.deleteLater()
            app.processEvents()


if __name__ == "__main__":
    unittest.main()
