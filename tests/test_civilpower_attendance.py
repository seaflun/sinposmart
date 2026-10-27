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


class OALoginTests(unittest.TestCase):
    def test_password_expiry_parser_accepts_only_explicit_valid_unambiguous_dates(self):
        from app_core.login_verifier import oa_password_expiry_date
        cases = {
            "此帳號的密碼即將在2026-11-01到期": "2026-11-01",
            "密碼到期日：115/11/01": "2026-11-01",
            "上次變更密碼2026/08/01，密碼有效期限2026年11月01日": "2026-11-01",
            "密碼到期日2026-11-01；密碼到期日2026-12-01": "",
            "密碼即將在2026-02-30到期": "",
            "更新日期2026/11/01": "",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(oa_password_expiry_date(text), expected)

    def test_notice_can_retry_ocr_before_submitting_and_gate_can_stop_the_submit(self):
        from app_core.login_verifier import run_oa_login, LoginVerificationError
        driver, elements, wait = self.make_login()
        recognizer = Mock()
        recognizer.classification.side_effect = ["", "", "abcd"]
        gate = Mock()
        with patch("selenium.webdriver.support.ui.WebDriverWait", wait):
            run_oa_login(driver, "tyfd01214", "synthetic-password", recognizer,
                         attempts=3, submit_limit=1, before_submit=gate)
        self.assertEqual(recognizer.classification.call_count, 3)
        elements["loginBtn"].click.assert_called_once()
        driver, elements, wait = self.make_login()
        recognizer.classification.side_effect = None
        recognizer.classification.return_value = "abcd"
        gate.side_effect = LoginVerificationError("已到停用時間", reason_code="oa_password_expired")
        with patch("selenium.webdriver.support.ui.WebDriverWait", wait), self.assertRaises(LoginVerificationError):
            run_oa_login(driver, "tyfd01214", "synthetic-password", recognizer,
                         attempts=3, submit_limit=1, before_submit=gate)
        elements["loginBtn"].click.assert_not_called()

    def test_guarded_notice_login_captures_expiry_and_calls_gate_before_only_submission(self):
        from app_core.login_verifier import run_oa_login
        driver, elements, wait = self.make_password_warning_login()
        gate, expiry = Mock(), Mock()
        recognizer = Mock()
        recognizer.classification.return_value = "abcd"
        with patch("selenium.webdriver.support.ui.WebDriverWait", wait):
            run_oa_login(driver, "tyfd01214", "synthetic-password", recognizer,
                         attempts=3, submit_limit=1, before_submit=gate, password_expiry_callback=expiry)
        gate.assert_called_once()
        self.assertIn(unittest.mock.call("2026-11-01"), expiry.call_args_list)
        elements["loginBtn"].click.assert_called_once()

    def test_guarded_login_never_resubmits_after_captcha_rejection_or_unknown_result(self):
        from app_core.login_verifier import run_oa_login, LoginVerificationError
        for captcha_rejected in (True, False):
            driver, elements, wait = self.make_login()
            driver.execute_script.side_effect = lambda script, *args: (
                "oa_captcha_rejected" if "const text = Array.from" in script and captcha_rejected
                else {"page_text": "", "password_fields": 0} if "login-diagnostic-probe" in script else True)
            elements["loginBtn"].click.side_effect = None
            recognizer = Mock()
            recognizer.classification.return_value = "abcd"
            with self.subTest(captcha_rejected=captcha_rejected), patch("selenium.webdriver.support.ui.WebDriverWait", wait):
                with self.assertRaises(LoginVerificationError):
                    run_oa_login(driver, "tyfd01214", "synthetic-password", recognizer,
                                 attempts=3, submit_limit=1, before_submit=Mock())
                elements["loginBtn"].click.assert_called_once()

    def make_password_warning_login(self, *, state="oa_password_expiring", dismisses=True, visible=True):
        driver, elements, wait = self.make_login()
        original_find = driver.find_elements.side_effect
        warning = {"active": False}
        skip = Mock()
        skip.is_displayed.return_value = visible
        skip.is_enabled.return_value = True
        elements["skip_password_change"] = skip

        def submit():
            warning["active"] = True
            driver.current_url = "https://oa.tyfd.gov.tw/password_expiry.php"

        def dismiss():
            if dismisses:
                warning["active"] = False
                driver.current_url = "https://oa.tyfd.gov.tw/index.php"

        elements["loginBtn"].click.side_effect = submit
        skip.click.side_effect = dismiss
        driver.execute_script.side_effect = lambda script, *args: (
            {"page_text": ("此帳號的密碼即將在 2026-11-01 到期，是否前往變更密碼？暫不變更 前往變更"
                           if state == "oa_password_expiring" else "密碼已到期，必須變更密碼"),
             "password_fields": 0} if warning["active"] else {"page_text": "入口網首頁", "password_fields": 0}
        ) if "login-diagnostic-probe" in script else True
        driver.find_elements.side_effect = lambda by, selector: (
            [skip] if "暫不變更" in selector else [] if warning["active"] else original_find(by, selector)
        )

        class PollingWait(wait):
            def until(self, predicate):
                from selenium.common.exceptions import TimeoutException
                for _ in range(4):
                    result = predicate(self.driver)
                    if result:
                        return result
                raise TimeoutException("synthetic warning did not close")

        return driver, elements, PollingWait

    def test_shared_oa_login_defers_optional_password_warning_before_success(self):
        from app_core.login_verifier import run_oa_login
        driver, elements, wait = self.make_password_warning_login()
        recognizer = Mock()
        recognizer.classification.return_value = "abcd"
        with patch("selenium.webdriver.support.ui.WebDriverWait", wait):
            run_oa_login(driver, "tyfd01214", "synthetic-password", recognizer, attempts=1)
        elements["skip_password_change"].click.assert_called_once()
        elements["loginBtn"].click.assert_called_once()
        self.assertEqual(driver.current_url, "https://oa.tyfd.gov.tw/index.php")

    def test_optional_warning_must_close_and_never_clicks_hidden_skip(self):
        from app_core.login_verifier import LoginVerificationError, run_oa_login
        for visible in (True, False):
            driver, elements, wait = self.make_password_warning_login(dismisses=False, visible=visible)
            recognizer = Mock()
            recognizer.classification.return_value = "abcd"
            with self.subTest(visible=visible):
                with patch("selenium.webdriver.support.ui.WebDriverWait", wait), \
                        self.assertRaises(LoginVerificationError) as caught:
                    run_oa_login(driver, "tyfd01214", "synthetic-password", recognizer, attempts=1)
                self.assertEqual(caught.exception.reason_code, "oa_password_warning_blocked")
                self.assertEqual(elements["skip_password_change"].click.call_count, int(visible))

    def test_shared_oa_login_never_skips_mandatory_password_change(self):
        from app_core.login_verifier import LoginVerificationError, run_oa_login
        driver, elements, wait = self.make_password_warning_login(state="oa_password_change_required")
        recognizer = Mock()
        recognizer.classification.return_value = "abcd"
        with patch("selenium.webdriver.support.ui.WebDriverWait", wait), \
                self.assertRaises(LoginVerificationError) as caught:
            run_oa_login(driver, "tyfd01214", "synthetic-password", recognizer, attempts=1)
        self.assertEqual(caught.exception.reason_code, "oa_password_change_required")
        elements["skip_password_change"].click.assert_not_called()

    def test_civilpower_waits_for_password_warning_before_opening_module(self):
        from app_core.civilpower_automation import _login_once
        driver, elements, wait = self.make_password_warning_login()
        recognizer = Mock()
        recognizer.classification.return_value = "abcd"

        def verify_navigation(*_args):
            elements["skip_password_change"].click.assert_called_once()
            self.assertEqual(driver.current_url, "https://oa.tyfd.gov.tw/index.php")

        with patch("selenium.webdriver.support.ui.WebDriverWait", wait), \
                patch("app_core.civilpower_automation.open_civilpower_from_oa_dashboard", side_effect=verify_navigation) as opened:
            _login_once(driver, Mock(user_id="tyfd01214", password="synthetic-password"), recognizer)
        opened.assert_called_once()

    def test_civilpower_preserves_required_password_change_message_without_retry(self):
        from app_core.civilpower_automation import login_attendance
        driver, elements, wait = self.make_password_warning_login(state="oa_password_change_required")
        recognizer = Mock()
        recognizer.classification.return_value = "abcd"
        with patch("selenium.webdriver.support.ui.WebDriverWait", wait), self.assertRaisesRegex(CivilpowerError, "手動變更密碼"):
            login_attendance(driver, Mock(user_id="tyfd01214", password="synthetic-password"), recognizer, lambda _: None)
        elements["loginBtn"].click.assert_called_once()

    def test_oa_login_waits_for_captcha_pixels_before_ocr_and_preserves_failure_stage(self):
        from app_core.login_verifier import LoginVerificationError, run_oa_login
        driver, elements, wait = self.make_login()
        driver.execute_script.return_value = False
        recognizer = Mock()
        with patch("selenium.webdriver.support.ui.WebDriverWait", wait), self.assertRaises(LoginVerificationError) as caught:
            run_oa_login(driver, "tyfd01214", "synthetic-password", recognizer, attempts=1)
        self.assertEqual(caught.exception.reason_code, "oa_captcha_not_ready")
        recognizer.classification.assert_not_called()
        elements["loginBtn"].click.assert_not_called()

    def test_oa_empty_ocr_is_reported_as_captcha_failure_instead_of_unknown_login(self):
        from app_core.login_verifier import LoginVerificationError, run_oa_login
        driver, _elements, wait = self.make_login()
        recognizer = Mock()
        recognizer.classification.return_value = ""
        with patch("selenium.webdriver.support.ui.WebDriverWait", wait), self.assertRaises(LoginVerificationError) as caught:
            run_oa_login(driver, "tyfd01214", "synthetic-password", recognizer, attempts=1)
        self.assertEqual(caught.exception.reason_code, "oa_captcha_unrecognized")

    def make_login(self):
        from selenium.common.exceptions import TimeoutException

        driver = Mock(current_url="https://oa.tyfd.gov.tw/login.php")
        driver.execute_script.return_value = True
        elements = {key: Mock() for key in
                    ("login_name", "password", "checkcodeImg", "verify_code", "loginBtn")}
        for element in elements.values():
            element.is_displayed.return_value = True
            element.is_enabled.return_value = True
        elements["checkcodeImg"].size = {"width": 100}
        elements["checkcodeImg"].get_attribute.return_value = "captcha.php"
        elements["checkcodeImg"].screenshot_as_png = b"synthetic-captcha"
        driver.find_element.side_effect = lambda by, selector: elements[selector.lstrip("#")]
        driver.find_elements.side_effect = lambda *args: (
            [] if driver.current_url.endswith("/index.php") else [elements["login_name"]])
        driver.get.side_effect = lambda url: setattr(driver, "current_url", url)
        elements["loginBtn"].click.side_effect = lambda: setattr(
            driver, "current_url", "https://oa.tyfd.gov.tw/index.php")

        class ImmediateWait:
            def __init__(self, current, timeout):
                self.driver = current

            def until(self, predicate):
                result = predicate(self.driver)
                if not result:
                    raise TimeoutException("synthetic wait")
                return result

        return driver, elements, ImmediateWait

    def test_shared_oa_login_uses_ocr_and_replaces_saved_fields(self):
        from app_core.login_verifier import run_oa_login
        driver, elements, wait = self.make_login()
        recognizer = Mock()
        recognizer.classification.return_value = "a 2-B3"
        with patch("selenium.webdriver.support.ui.WebDriverWait", wait):
            run_oa_login(driver, "tyfd01214", "synthetic-password", recognizer)
        elements["password"].clear.assert_called_once()
        elements["password"].send_keys.assert_called_once_with("synthetic-password")
        elements["verify_code"].send_keys.assert_called_once_with("a2B3")
        recognizer.classification.assert_called_once_with(b"synthetic-captcha")
        elements["loginBtn"].click.assert_called_once()

    def test_shared_oa_login_retries_ocr_boundedly_and_hides_raw_error(self):
        from app_core.login_verifier import LoginVerificationError, run_oa_login
        driver, elements, wait = self.make_login()
        recognizer = Mock()
        recognizer.classification.side_effect = RuntimeError("synthetic-password")
        with patch("selenium.webdriver.support.ui.WebDriverWait", wait):
            with self.assertRaises(LoginVerificationError) as caught:
                run_oa_login(driver, "tyfd01214", "synthetic-password", recognizer, attempts=99)
        self.assertEqual(driver.get.call_count, 3)
        self.assertNotIn("synthetic-password", str(caught.exception))
        elements["loginBtn"].click.assert_not_called()

    def test_shared_oa_login_never_fills_redirected_foreign_or_wrong_path(self):
        from app_core.login_verifier import LoginVerificationError, run_oa_login
        for destination in ("https://example.invalid/login.php",
                            "http://oa.tyfd.gov.tw/login.php",
                            "https://oa.tyfd.gov.tw/not-login.php"):
            driver, elements, wait = self.make_login()
            driver.get.side_effect = lambda url: setattr(driver, "current_url", destination)
            with self.subTest(destination=destination), \
                    patch("selenium.webdriver.support.ui.WebDriverWait", wait), \
                    self.assertRaises(LoginVerificationError):
                run_oa_login(driver, "tyfd01214", "synthetic-password", Mock(), attempts=1)
            elements["login_name"].send_keys.assert_not_called()
            elements["password"].send_keys.assert_not_called()

    def test_shared_oa_login_rechecks_origin_before_each_field(self):
        from app_core.login_verifier import LoginVerificationError, run_oa_login
        driver, elements, wait = self.make_login()
        elements["login_name"].send_keys.side_effect = lambda value: setattr(
            driver, "current_url", "https://example.invalid/login.php")
        with patch("selenium.webdriver.support.ui.WebDriverWait", wait), \
                self.assertRaises(LoginVerificationError):
            run_oa_login(driver, "tyfd01214", "synthetic-password", Mock(), attempts=1)
        elements["password"].send_keys.assert_not_called()

    def test_civilpower_uses_same_oa_login_without_multiplying_retries(self):
        from app_core import civilpower_automation as automation
        driver, recognizer = Mock(), Mock()
        request = Mock(user_id="duty1", password="synthetic-password")
        with patch("app_core.login_verifier.run_oa_login") as login, \
                patch.object(automation, "open_civilpower_from_oa_dashboard") as open_module:
            automation._login_once(driver, request, recognizer)
        login.assert_called_once_with(driver, "duty1", "synthetic-password", recognizer, attempts=1)
        open_module.assert_called_once()


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

    def test_person_lookup_waits_for_replaced_dialog(self):
        from selenium.common.exceptions import StaleElementReferenceException
        from selenium.webdriver.support.ui import WebDriverWait
        from app_core import civilpower_automation as automation

        driver, old_dialog, dialog, row = Mock(), Mock(), Mock(), Mock()
        driver.find_elements.side_effect = [[old_dialog], [dialog]]
        old_dialog.is_displayed.side_effect = StaleElementReferenceException("replaced")
        dialog.is_displayed.return_value = True
        with patch.object(automation, "_find_paginated_table_rows", return_value=[row]):
            result = automation._wait_for_io_person_dialog_row(
                driver, WebDriverWait(driver, 0.1, poll_frequency=0.001), ["測試義消"])
        self.assertEqual(result, (dialog, row))
        self.assertEqual(driver.find_elements.call_count, 2)

    def test_person_lookup_never_restarts_partial_page_scan(self):
        from selenium.common.exceptions import StaleElementReferenceException
        from selenium.webdriver.support.ui import WebDriverWait
        from app_core import civilpower_automation as automation

        driver, dialog = Mock(), Mock()
        driver.find_elements.return_value = [dialog]
        with patch.object(automation, "_find_paginated_table_rows",
                          side_effect=StaleElementReferenceException("page replaced")) as query:
            with self.assertRaises(StaleElementReferenceException):
                automation._wait_for_io_person_dialog_row(
                    driver, WebDriverWait(driver, 0.1, poll_frequency=0.001), ["測試義消"])
        query.assert_called_once()

    def test_unit_readback_waits_for_replaced_field(self):
        from selenium.common.exceptions import StaleElementReferenceException
        from selenium.webdriver.support.ui import WebDriverWait
        from app_core import civilpower_automation as automation

        driver, element = Mock(), Mock()
        driver.find_element.return_value = element
        driver.execute_script.return_value = True
        element.get_attribute.side_effect = [StaleElementReferenceException("replaced"), "新坡分隊"]
        with patch.object(automation, "_wait_for_jqx_combobox_option"):
            automation._select_jqx_combobox(
                driver, WebDriverWait(driver, 0.1, poll_frequency=0.001), "#txt_AddServeUnit", "新坡分隊")
        self.assertEqual(element.get_attribute.call_count, 2)

    def test_slow_unit_options_can_become_ready_after_twenty_seconds(self):
        from selenium.webdriver.support.ui import WebDriverWait
        from app_core import civilpower_automation as automation

        elapsed = [0.0]
        clock = Mock()
        clock.monotonic.side_effect = lambda: elapsed[0]
        clock.sleep.side_effect = lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds)
        driver, element = Mock(), Mock()
        driver.find_element.return_value = element
        element.is_displayed.return_value = element.is_enabled.return_value = True
        driver.execute_script.side_effect = lambda *_args: elapsed[0] >= 20
        plan = CivilpowerService(PACKAGE).validate(self.request())
        with patch("selenium.webdriver.support.wait.time", clock):
            automation._wait_for_io_form_dependencies(
                driver, WebDriverWait(driver, automation.DEFAULT_WAIT_SECONDS), plan)
        self.assertEqual(elapsed[0], 20)

    def test_persistently_replaced_person_dialog_never_saves(self):
        from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
        from selenium.webdriver.support.ui import WebDriverWait
        from app_core import civilpower_automation as automation

        driver, dialog, before_save = Mock(), Mock(), Mock()
        driver.find_elements.return_value = [dialog]
        dialog.is_displayed.side_effect = StaleElementReferenceException("replaced")
        plan = CivilpowerService(PACKAGE).validate(self.request())
        with ExitStack() as stack:
            for name in ("_wait_visible", "_select_jqx_combobox", "_wait_for_io_form_dependencies"):
                stack.enter_context(patch.object(automation, name))
            click = stack.enter_context(patch.object(automation, "_click"))
            stack.enter_context(patch.object(automation, "_find_io_record", return_value=False))
            stack.enter_context(patch.object(automation, "WebDriverWait", side_effect=lambda d, _t:
                                            WebDriverWait(d, 0.01, poll_frequency=0.001)))
            with self.assertRaises(TimeoutException):
                automation._ensure_io_record(driver, plan, plan.status, {}, cancel_check=None,
                                             require_lookup_confirmation=True, before_save=before_save)
        before_save.assert_not_called()
        self.assertNotIn("#btn_IOWorkLogAdd", [call.args[1] for call in click.call_args_list])

    def test_failure_preserves_stage_without_raw_browser_details(self):
        from selenium.common.exceptions import TimeoutException, StaleElementReferenceException
        from app_core import civilpower_automation as automation

        for exception_type in (TimeoutException, StaleElementReferenceException, RuntimeError):
            with self.subTest(exception_type=exception_type), TemporaryDirectory() as root, ExitStack() as stack:
                driver = Mock()
                stack.enter_context(patch("app_core.login_verifier.create_login_webdriver", return_value=driver))
                stack.enter_context(patch("app_core.login_verifier.configure_login_webdriver_timeouts"))
                stack.enter_context(patch.dict(sys.modules, {"ddddocr": Mock()}))
                stack.enter_context(patch.object(automation, "login_attendance"))
                def fail(_driver, _plan, _status, _checkpoint, **kwargs):
                    kwargs["progress"](automation.CIVILPOWER_STAGE_LABELS["io_person"])
                    raise exception_type("password=secret token=private")
                stack.enter_context(patch.object(automation, "_ensure_io_record", side_effect=fail))
                request = self.request()
                plan = CivilpowerService(PACKAGE).validate(request)
                with self.assertRaises(CivilpowerError) as result:
                    automation.run_attendance(Path(root), request, plan, Mock())
                self.assertEqual(result.exception.failure_stage, "io_person")
                self.assertIn("選擇義消", str(result.exception))
                self.assertNotIn("secret", str(result.exception))
                self.assertNotIn("private", str(result.exception))
                self.assertNotIn(request.password, str(result.exception))
                self.assertFalse((Path(root) / "runtime_outputs" / "civilpower").exists())
                driver.quit.assert_called_once()

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

    def test_standalone_execution_logs_in_verifies_keeps_browser_and_remembers_success(self):
        from app_core import civilpower_automation as automation
        with TemporaryDirectory() as root, ExitStack() as stack:
            automation.RETAINED_DRIVERS.clear()
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
            driver.quit.assert_not_called()
            self.assertIn(driver, automation.RETAINED_DRIVERS)
            ledger = next((Path(root) / "runtime_outputs" / "civilpower").glob("*.json"))
            self.assertEqual(json.loads(ledger.read_text())["state"], "verified")
            self.assertNotIn(request.password, ledger.read_text())
            self.assertIn("未重複新增", automation.run_attendance(Path(root), request, plan, Mock()))
            browser.assert_called_once()
            save.assert_called_once()
            automation.RETAINED_DRIVERS.remove(driver)

    def test_failed_civilpower_readback_closes_browser(self):
        from app_core import civilpower_automation as automation
        with TemporaryDirectory() as root, ExitStack() as stack:
            automation.RETAINED_DRIVERS.clear()
            driver = Mock()
            stack.enter_context(patch("app_core.login_verifier.create_login_webdriver", return_value=driver))
            stack.enter_context(patch("app_core.login_verifier.configure_login_webdriver_timeouts"))
            stack.enter_context(patch.dict(sys.modules, {"ddddocr": Mock()}))
            stack.enter_context(patch.object(automation, "login_attendance"))
            stack.enter_context(patch.object(automation, "_ensure_io_record", side_effect=RuntimeError("查詢未確認")))
            request = self.request()
            plan = CivilpowerService(PACKAGE).validate(request)
            with self.assertRaises(CivilpowerError):
                automation.run_attendance(Path(root), request, plan, Mock())
            driver.quit.assert_called_once()
            self.assertNotIn(driver, automation.RETAINED_DRIVERS)

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
