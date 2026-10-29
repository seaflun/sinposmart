from __future__ import annotations

import os
import sys
import threading
import time
import unittest
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PACKAGE = Path(__file__).resolve().parents[1] / "WinPython_公務電腦使用包"
sys.path.insert(0, str(PACKAGE))

from PySide6.QtWidgets import QApplication
from app_core.notice_collection_service import NoticeCollectionError, NoticeCollectionResult, NoticeLoginRequired
from qt_app.controllers.notice_collection_controller import NoticeCollectionController

TAIPEI = timezone(timedelta(hours=8))


class NoticeCollectionControllerTests(unittest.TestCase):
    def test_verification_failure_reports_real_safe_code_without_collection_counts(self):
        self.enable_saved_account()
        reports = []
        self.controller.reportReady.connect(reports.append)
        for code in ("oa_credentials_rejected", "oa_account_locked", "oa_password_change_required",
                     "oa_login_guard_unavailable", "oa_password_warning_blocked", "unknown-sensitive-code"):
            with self.subTest(code=code):
                reports.clear()
                self.service.verify_login.side_effect = NoticeLoginRequired(
                    "test-password token=fixture-secret cookie=fixture-session", code=code)
                self.controller.verifyLogin()
                self.wait_for(lambda: not self.controller.isRunning)
                self.assertEqual(len(reports), 1)
                report = reports[0]
                self.assertIs(report["verification_only"], True)
                self.assertEqual((report["state"], report["error_stage"]), ("failed", "login"))
                self.assertEqual(report["error_code"], "" if code.startswith("unknown") else code)
                self.assertEqual(report["started_at"], self.now.isoformat())
                self.assertEqual(report["completed_at"], self.now.isoformat())
                self.assertEqual((report["part_index"], report["part_count"]), (0, 1))
                self.assertEqual((report["records"], report["new_keys"]), ([], []))
                for field in ("unread_count", "new_count", "marked_read_count", "pending_write_count", "pending_read_count"):
                    self.assertIsNone(report[field])
                for value in ("test-password", "fixture-secret", "fixture-session", "unknown-sensitive-code"):
                    self.assertNotIn(value, str(report))
                    self.assertNotIn(value, self.controller.verificationStatus)
                if code.startswith("unknown"):
                    self.assertEqual(report["message"], "驗證未完成，原因待確認。")
                self.now += timedelta(seconds=1)
        self.service.collect.assert_not_called()
        self.service.report_parts.assert_not_called()

    def test_verification_busy_reports_throttled_waiting_and_success_does_not_fake_collection(self):
        self.enable_saved_account()
        reports = []
        self.controller.reportReady.connect(reports.append)
        self.busy.return_value = "勤務登打"
        self.controller.verifyLogin()
        self.controller.check_due()
        self.now += timedelta(seconds=59)
        self.controller.check_due()
        self.assertEqual(len(reports), 1)
        self.now += timedelta(seconds=1)
        self.controller.check_due()
        self.assertEqual(len(reports), 2)
        self.assertEqual(reports[0]["run_id"], reports[1]["run_id"])
        for report in reports:
            self.assertEqual((report["state"], report["error_stage"]), ("waiting", "busy"))
            self.assertEqual((report["started_at"], report["completed_at"]), ("", ""))
            self.assertIs(report["verification_only"], True)
        self.service.verify_login.assert_not_called()
        self.busy.return_value = ""
        self.controller.check_due()
        self.wait_for(lambda: not self.controller.isRunning)
        self.assertEqual(self.controller.verificationState, "verified")
        self.assertEqual(len(reports), 2)
        self.service.collect.assert_not_called()

    def test_paused_closing_and_running_gates_do_not_report_fake_verification_failure(self):
        reports = []
        self.controller.reportReady.connect(reports.append)
        self.service.login_protection.return_value = {"paused": True}
        self.controller.check_due()
        self.controller._job = SimpleNamespace(verify_only=False)
        self.controller.check_due()
        self.controller._job = None
        self.controller.prepare_shutdown_admission()
        self.controller.verifyLogin()
        self.controller.check_due()
        self.assertEqual(reports, [])
        self.service.verify_login.assert_not_called()

    def test_expiry_pauses_scheduler_and_collect_now_but_password_verification_can_resume(self):
        from app_core.notice_collection_service import NoticeLoginGuard
        self.now = datetime(2026, 10, 31, 23, 58, tzinfo=TAIPEI)
        with tempfile.TemporaryDirectory() as temporary:
            guard = NoticeLoginGuard(Path(temporary))
            guard.record_expiry("2026-11-01")
            self.service.login_protection.side_effect = lambda now: guard.status(now)
            self.enable_saved_account()
            self.controller.check_due()
            self.wait_for(lambda: not self.controller.isRunning)
            count = self.service.collect.call_count
            self.now += timedelta(minutes=1)
            self.controller.check_due()
            self.controller.collectNow()
            self.assertEqual(self.service.collect.call_count, count)
            self.assertEqual(self.controller.activityLabel, "已暫停")
            self.assertIn("10/31 23:59", self.controller.statusText)
            def verify(*_args, **_kwargs):
                guard.begin_attempt(self.now, verification=True)
                guard.record_expiry("2027-02-01", pending=True)
                guard.finish_attempt(self.now, verification=True)
            self.service.verify_login.side_effect = verify
            self.controller.verifyLogin()
            self.wait_for(lambda: not self.controller.isRunning)
            self.service.verify_login.assert_called_once()
            self.assertFalse(guard.status(self.now)["paused"])
            self.controller.collectNow()
            self.wait_for(lambda: not self.controller.isRunning)
            self.assertEqual(self.service.collect.call_count, count + 1)

    def test_login_protection_hides_unknown_and_unexpired_routine_information(self):
        from app_core.notice_collection_service import NoticeLoginGuard

        for expiry in ("", "2027-02-01"):
            with self.subTest(expiry=expiry), tempfile.TemporaryDirectory() as temporary:
                guard = NoticeLoginGuard(Path(temporary))
                if expiry:
                    guard.record_expiry(expiry)
                protection = guard.status(self.now)
                self.assertFalse(protection["paused"])
                self.service.login_protection.side_effect = lambda now: guard.status(now)
                self.controller.refreshReminder()
                self.assertEqual(self.controller.loginProtectionText, "")
                self.assertNotIn(protection["message"], self.controller.statusText)
        self.service.collect.assert_not_called()
        self.service.verify_login.assert_not_called()

    def test_login_protection_keeps_expired_locked_and_paused_warnings(self):
        from app_core.notice_collection_service import NoticeLoginGuard

        for code in ("oa_password_expired", "oa_account_locked", "oa_login_unconfirmed"):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as temporary:
                guard = NoticeLoginGuard(Path(temporary))
                if code == "oa_password_expired":
                    guard.record_expiry("2026-10-21")
                else:
                    guard.pause(code)
                protection = guard.status(self.now)
                self.assertTrue(protection["paused"])
                self.service.login_protection.side_effect = lambda now: guard.status(now)
                self.controller.refreshReminder()
                self.assertEqual(self.controller.loginProtectionText, protection["message"])
                self.assertIn(protection["message"], self.controller.statusText)

    def test_login_protection_read_failure_keeps_fail_closed_warning(self):
        self.service.login_protection.side_effect = OSError("fixture")
        self.controller.refreshReminder()
        warning = "通報登入保護狀態無法確認，已停止自動登入。"
        self.assertEqual(self.controller.loginProtectionText, warning)
        self.assertIn(warning, self.controller.statusText)

    def test_verification_success_does_not_repeat_unknown_or_future_expiry(self):
        from app_core.notice_collection_service import NoticeLoginGuard

        self.enable_saved_account()
        for expiry in ("", "2027-02-01"):
            with self.subTest(expiry=expiry), tempfile.TemporaryDirectory() as temporary:
                guard = NoticeLoginGuard(Path(temporary))
                if expiry:
                    guard.record_expiry(expiry)
                self.service.login_protection.side_effect = lambda now: guard.status(now)
                self.controller.verifyLogin()
                self.wait_for(lambda: not self.controller.isRunning)
                self.assertEqual(self.controller.verificationState, "verified")
                self.assertEqual(self.controller.verificationStatus, "通報帳號 tyfd01214 登入驗證成功。")
        self.service.collect.assert_not_called()

    def reminder_controller(self, path=None, actor=None):
        self.controller.shutdown()
        self.service.shift_records.return_value = [{"time": "09:12", "unit": "第三救災救護大隊",
            "name": "測試員", "subject": "測試主旨"}]
        self.actor = actor or Mock(return_value="1")
        self.controller = NoticeCollectionController(self.service, self.lookup, self.busy,
            now_factory=lambda: self.now, timer_start=False, reminder_actor_provider=self.actor,
            reminder_state_path=path)
        self.controller._next_check = self.now + timedelta(hours=3)
        self.controller.set_schedule_data(self.schedule())

    def test_handoff_popup_uses_two_minute_boundary_updates_and_dismisses_once(self):
        self.now = self.now.replace(hour=9, minute=57, second=59)
        self.reminder_controller()
        self.assertFalse(self.controller.handoffReminder["visible"])
        self.now += timedelta(seconds=1)
        self.controller.check_due()
        self.assertTrue(self.controller.handoffReminder["visible"])
        self.assertEqual(self.controller.handoffReminder["count"], 1)
        self.assertEqual(self.controller.handoffReminder["handoffText"], "10:00 交班")
        self.service.shift_records.return_value.append({"time": "09:58", "unit": "救災救護指揮中心",
            "name": "測試乙", "subject": "新增通報"})
        self.controller.check_due()
        self.assertEqual(self.controller.handoffReminder["count"], 2)
        self.controller.dismissHandoffReminder()
        self.controller.check_due()
        self.assertFalse(self.controller.handoffReminder["visible"])

    def test_zero_records_wrong_actor_logout_and_shift_end_never_show_popup(self):
        self.now = self.now.replace(hour=9, minute=58)
        self.reminder_controller(actor=Mock(return_value="2"))
        self.assertFalse(self.controller.handoffReminder["visible"])
        self.actor.return_value = "1"
        self.service.shift_records.return_value = []
        self.controller.check_due()
        self.assertFalse(self.controller.handoffReminder["visible"])
        self.service.shift_records.return_value = [{"time": "09:12", "unit": "救護科", "name": "甲", "subject": "通報"}]
        self.controller.check_due()
        self.assertTrue(self.controller.handoffReminder["visible"])
        self.actor.return_value = ""
        self.controller.check_due()
        self.assertFalse(self.controller.handoffReminder["visible"])
        self.actor.return_value = "1"
        self.now = self.now.replace(hour=10)
        self.controller.check_due()
        self.assertFalse(self.controller.handoffReminder["visible"])

    def test_reminder_checkpoint_prevents_repeat_after_restart_and_corruption(self):
        self.now = self.now.replace(hour=9, minute=58)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "reminder.json"
            self.reminder_controller(path)
            self.assertTrue(self.controller.handoffReminder["visible"])
            self.reminder_controller(path)
            self.assertFalse(self.controller.handoffReminder["visible"])
            path.write_text("{bad", encoding="utf-8")
            self.reminder_controller(path)
            self.assertFalse(self.controller.handoffReminder["visible"])

    def test_popup_uses_true_handoff_across_midnight(self):
        self.now = self.now.replace(hour=23, minute=58)
        self.reminder_controller()
        schedule = self.schedule()
        schedule["today"]["rows"] = [{"slot": "22~0", "columns": {"值班": ["1"]}}]
        self.controller.set_schedule_data(schedule)
        self.assertTrue(self.controller.handoffReminder["visible"])
        self.assertEqual(self.controller.handoffReminder["handoffText"], "00:00 交班")

    def test_popup_is_read_only_during_ledger_failure_and_journal_write_failure(self):
        self.now = self.now.replace(hour=9, minute=58)
        with tempfile.TemporaryDirectory() as temporary:
            self.reminder_controller(Path(temporary) / "reminder.json", actor=Mock(return_value="2"))
            self.actor.return_value = "1"
            with patch.object(Path, "replace", side_effect=OSError("test")):
                self.controller.check_due()
            self.assertFalse(self.controller.handoffReminder["visible"])
            self.service.collect.assert_not_called()

    def test_live_popup_keeps_confirmed_rows_when_refresh_fails(self):
        self.now = self.now.replace(hour=9, minute=58)
        self.reminder_controller()
        self.service.shift_records.side_effect = NoticeCollectionError("暫時失敗")
        self.controller.refreshReminder()
        self.assertTrue(self.controller.handoffReminder["visible"])
        self.assertEqual(self.controller.handoffReminder["count"], 1)
        self.assertIn("上次已確認", self.controller.handoffReminder["warning"])
        self.actor.return_value = ""
        self.controller.refreshReminder()
        self.assertFalse(self.controller.handoffReminder["visible"])

    def test_last_check_checkpoint_survives_restart_without_triggering_collection(self):
        self.now = self.now.replace(hour=9, minute=57)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "reminder.json"
            self.reminder_controller(path)
            self.controller._poll_run_id = "fixture-run"
            self.controller._collected(NoticeCollectionResult(self.now))
            self.now = self.now.replace(minute=58)
            self.reminder_controller(path)
            self.assertIn("09:57:00", self.controller.handoffReminder["lastCheckedText"])
            self.service.collect.assert_not_called()

    def test_refresh_failure_after_sleep_does_not_expose_the_previous_shift(self):
        self.now = self.now.replace(hour=9, minute=58)
        self.reminder_controller()
        self.assertTrue(self.controller.handoffReminder["visible"])
        self.now = self.now.replace(hour=11)
        self.actor.return_value = "2"
        self.service.shift_records.side_effect = NoticeCollectionError("暫時失敗")
        self.controller.refreshReminder()
        self.assertFalse(self.controller.handoffReminder["visible"])

    def test_sheet_link_is_fetched_off_thread_and_untrusted_urls_never_open(self):
        self.service.monthly_spreadsheet_url.return_value = "https://docs.google.com/spreadsheets/d/" + "a" * 30 + "/edit"
        with patch("qt_app.controllers.notice_collection_controller.QDesktopServices.openUrl", return_value=True) as opened:
            self.controller.openNoticeSheet()
            self.wait_for(lambda: not self.controller.sheetLinkBusy)
            opened.assert_called_once()
            self.assertEqual(self.controller.sheetLinkMessage, "")
            self.controller._open_sheet_url("https://private.invalid/")
            opened.assert_called_once()
            self.assertIn("尚未確認", self.controller.sheetLinkMessage)

    def test_real_qml_popup_keeps_unit_above_name_and_scrolls_long_subjects(self):
        from PySide6.QtCore import QObject, QUrl, Qt
        from PySide6.QtQml import QQmlApplicationEngine
        from PySide6.QtQuickControls2 import QQuickStyle
        QQuickStyle.setStyle("Basic")
        self.now = self.now.replace(hour=9, minute=58)
        self.reminder_controller()
        rows = self.service.shift_records.return_value
        rows[0]["subject"] = "長主旨測試" * 30
        rows.extend([{"time": "09:40", "unit": "救災救護指揮中心", "name": "測試乙", "subject": "通報"}] * 20)
        self.controller.refreshReminder()
        engine = QQmlApplicationEngine()
        engine.setInitialProperties({"controller": self.controller})
        errors = []
        engine.warnings.connect(lambda values: errors.extend(str(value) for value in values))
        engine.load(QUrl.fromLocalFile(str(PACKAGE / "qt_app/qml/dialogs/NoticeHandoffWindow.qml")))
        self.assertTrue(engine.rootObjects(), errors)
        root = engine.rootObjects()[0]
        try:
            self.app.processEvents()
            self.assertTrue(root.isVisible())
            self.assertTrue(root.flags() & Qt.WindowStaysOnTopHint)
            self.assertEqual(root.modality(), Qt.NonModal)
            self.assertIsNone(root.transientParent())
            shift, checked = (root.findChild(QObject, name) for name in ("noticeShiftLabel", "noticeLastChecked"))
            self.assertEqual(shift.parent(), checked.parent())
            listing = root.findChild(QObject, "noticeHandoffList")
            self.assertGreater(listing.property("contentHeight"), listing.property("height"))
            def walk(item):
                yield item
                for child in item.childItems():
                    yield from walk(child)
            visible = list(walk(root.contentItem()))
            unit = next(item for item in visible if item.objectName() == "noticePublisherUnit")
            name = next(item for item in visible if item.objectName() == "noticePublisherName")
            self.assertGreaterEqual(name.y(), unit.y() + unit.height())
            self.assertFalse(errors, errors)
            root.findChild(QObject, "noticeDismissButton").clicked.emit()
            self.app.processEvents()
            self.assertFalse(root.isVisible())
        finally:
            root.setVisible(False)
            engine.deleteLater()
            self.app.processEvents()

    def test_shift_reminder_clears_only_after_a_confirmed_handoff(self):
        self.controller.shutdown()
        proof = {"schema_version": 1, "status": "confirmed", "actorNo": "1", "name": "持續值班甲",
                 "role": "隊員", "capturedAt": self.now.isoformat(),
                 "handoffSlotAt": "2026-10-21T08:00:00+08:00", "evidenceKey": "a" * 64}
        provider = Mock(return_value=proof)
        self.service.has_notices_for_responsibility.return_value = False
        self.controller = NoticeCollectionController(self.service, self.lookup, self.busy,
            responsibility_provider=provider, now_factory=lambda: self.now, timer_start=False)
        self.controller.set_schedule_data(self.schedule())
        self.assertFalse(self.controller.hasShiftNotices)
        self.service.has_notices_for_responsibility.return_value = True
        self.controller.check_due()
        self.assertTrue(self.controller.hasShiftNotices)
        self.now = self.now.replace(hour=10, minute=5)
        provider.return_value = {**proof, "capturedAt": self.now.isoformat()}
        self.service.has_notices_for_responsibility.return_value = False
        self.controller._set_notice("檢查失敗", "error")
        self.assertTrue(self.controller.hasShiftNotices)
        provider.side_effect = RuntimeError("暫時無法比對")
        self.controller.check_due()
        self.assertTrue(self.controller.hasShiftNotices)
        provider.side_effect = None
        provider.return_value = {**proof, "status": "unknown"}
        self.controller.check_due()
        self.assertTrue(self.controller.hasShiftNotices)
        provider.return_value = {**proof, "capturedAt": self.now.isoformat(), "actorNo": "2", "evidenceKey": "b" * 64}
        self.controller.check_due()
        self.assertFalse(self.controller.hasShiftNotices)

    def test_activity_capsule_tracks_waiting_running_failure_and_shutdown(self):
        self.assertEqual(self.controller.activityLabel, "等待排程")
        self.busy.return_value = "勤務登打"
        self.controller.check_due()
        self.assertEqual(self.controller.activityLabel, "等待作業")
        self.busy.return_value = ""
        self.enable_saved_account()
        release = threading.Event()
        def collect(*_args, **_kwargs):
            release.wait(2)
            raise NoticeCollectionError("測試讀取失敗")
        self.service.collect.side_effect = collect
        self.controller.check_due()
        self.assertEqual(self.controller.activityLabel, "執行中")
        release.set()
        self.wait_for(lambda: not self.controller.isRunning)
        self.assertEqual(self.controller.activityLabel, "失敗")
        self.controller.shutdown()
        self.assertEqual(self.controller.activityLabel, "已停止")

    def test_job_receives_an_immutable_responsibility_snapshot_from_the_main_thread(self):
        self.controller.shutdown()
        proof = {"status": "confirmed", "actorNo": "1"}
        provider_threads = []
        provider = Mock(side_effect=lambda _now: provider_threads.append(threading.get_ident()) or proof)
        self.controller = NoticeCollectionController(self.service, self.lookup, self.busy,
            responsibility_provider=provider, now_factory=lambda: self.now, timer_start=False)
        self.enable_saved_account()
        self.controller.check_due()
        self.wait_for(lambda: not self.controller.isRunning)
        self.assertTrue(provider.call_args_list)
        self.assertTrue(all(call.args == (self.now,) for call in provider.call_args_list))
        self.assertTrue(all(thread == threading.get_ident() for thread in provider_threads))
        self.assertEqual(self.service.collect.call_args.kwargs["responsibility"], proof)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["notice-controller-tests"])

    def setUp(self):
        self.now = datetime(2026, 10, 21, 9, 0, tzinfo=TAIPEI)
        self.service = Mock()
        self.service.counts.return_value = (0, 0)
        self.lookup = Mock(return_value=None)
        self.busy = Mock(return_value="")
        self.controller = NoticeCollectionController(
            self.service, self.lookup, self.busy,
            now_factory=lambda: self.now, timer_start=False,
        )

    def tearDown(self):
        self.controller.shutdown()
        self.app.processEvents()

    def wait_for(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertTrue(predicate(), "Qt worker did not reach the expected state")

    def enable_saved_account(self):
        self.lookup.return_value = {"user_id": "tyfd01214", "password": "test-password"}
        self.service.collect.return_value = NoticeCollectionResult(self.now)

    def schedule(self):
        return {"target_date": "1151021", "today": {
            "roc_date": "1151021", "staff": {"1": {"name": "測試人員"}, "2": {"name": "接班人員"}},
            "rows": [
                {"slot": "8~9", "columns": {"值班": ["1"]}},
                {"slot": "9~10", "columns": {"值班": ["1"]}},
                {"slot": "10~12", "columns": {"值班": ["2"]}},
            ],
        }}

    def test_missing_fixed_account_waits_without_collecting_or_using_other_accounts(self):
        self.controller.check_due()
        self.lookup.assert_called_once_with("tyfd01214")
        self.service.collect.assert_not_called()
        self.assertFalse(self.controller.isRunning)
        self.assertIn("tyfd01214", self.controller.statusText)
        self.assertEqual(self.controller.statusTone, "warning")
        self.controller.check_due()
        self.lookup.assert_called_once()

    def test_zero_unread_poll_reports_running_then_success_with_the_same_run_id(self):
        from app_core.notice_collection_service import NoticeCollectionService
        from tests.test_notice_collection import FakeBrowser
        self.controller.shutdown()
        with tempfile.TemporaryDirectory() as directory:
            service = NoticeCollectionService(Path(directory), browser=FakeBrowser(),
                                              poster=lambda _payload: self.fail("no Sheets write"))
            self.controller = NoticeCollectionController(service, self.lookup, self.busy,
                now_factory=lambda: self.now, timer_start=False)
            self.lookup.return_value = {"user_id": "tyfd01214", "password": "fixture-password"}
            reports = []
            self.controller.reportReady.connect(reports.append)
            self.controller.collectNow()
            self.wait_for(lambda: not self.controller.isRunning)
            self.assertEqual([report["state"] for report in reports], ["running", "success"])
            self.assertEqual(reports[0]["run_id"], reports[1]["run_id"])
            self.assertIsNone(reports[0]["unread_count"])
            self.assertEqual(reports[1]["unread_count"], 0)
            self.assertEqual(reports[1]["records"], [])
            self.assertNotIn("fixture-password", str(reports))

    def test_shutdown_reports_each_finished_poll_once_without_processing_queued_signals(self):
        for state in ("success", "partial", "failed"):
            with self.subTest(state=state):
                self.controller.shutdown()
                service = Mock()
                service.counts.return_value = (0, 0)
                result = NoticeCollectionResult(self.now, status=state,
                    unread_count=1 if state == "partial" else 0,
                    error_count=int(state != "success"), error_stage="write" if state == "partial" else "")
                service.last_result = result
                service.report_parts.side_effect = lambda run_id, state, *_args, **_kwargs: [
                    {"run_id": run_id, "state": state}]
                def collect(_password, _received_at, cancel, **_kwargs):
                    while not cancel():
                        time.sleep(0.001)
                    if state == "failed":
                        raise NoticeLoginRequired("fixture-password https://example.invalid/private")
                    return result
                service.collect.side_effect = collect
                self.controller = NoticeCollectionController(service, self.lookup, self.busy,
                    now_factory=lambda: self.now, timer_start=False)
                self.lookup.return_value = {"user_id": "tyfd01214", "password": "fixture-password"}
                reports = []
                self.controller.reportReady.connect(reports.append)
                self.controller.collectNow()
                self.assertTrue(self.controller.shutdown())
                self.assertEqual([report["state"] for report in reports], ["running", state])
                self.assertEqual(reports[0]["run_id"], reports[1]["run_id"])
                self.assertIs(service.report_parts.call_args.kwargs["result"], result)
                self.assertNotIn("fixture-password", str(reports))
                self.app.processEvents()
                self.assertEqual(len(reports), 2)
                service.close.assert_called_once()

    def test_waiting_report_is_rate_limited_and_missing_credentials_does_not_claim_a_scan(self):
        from app_core.notice_collection_service import NoticeCollectionService
        from tests.test_notice_collection import FakeBrowser
        self.controller.shutdown()
        with tempfile.TemporaryDirectory() as directory:
            service = NoticeCollectionService(Path(directory), browser=FakeBrowser())
            self.controller = NoticeCollectionController(service, self.lookup, self.busy,
                now_factory=lambda: self.now, timer_start=False)
            reports = []
            self.controller.reportReady.connect(reports.append)
            self.busy.return_value = "fixture private exception https://example.invalid"
            self.controller.check_due()
            self.now += timedelta(seconds=59)
            self.controller.check_due()
            self.assertEqual(len(reports), 1)
            self.now += timedelta(seconds=1)
            self.controller.check_due()
            self.assertEqual(len(reports), 2)
            self.assertEqual(reports[0]["run_id"], reports[1]["run_id"])
            self.assertTrue(all(row["state"] == "waiting" and not row["started_at"] for row in reports))
            self.busy.return_value = ""
            self.controller.check_due()
            missing = reports[-1]
            self.assertEqual(missing["state"], "missing_credentials")
            self.assertEqual(missing["error_stage"], "configuration")
            self.assertIsNone(missing["unread_count"])
            self.assertEqual((missing["started_at"], missing["completed_at"]), ("", ""))
            self.assertNotIn("example.invalid", str(reports))
            self.assertNotIn("fixture private exception", str(reports))

    def test_failed_scan_reports_unknown_counts_without_raw_error_and_verification_is_not_a_poll(self):
        from app_core.notice_collection_service import NoticeCollectionService
        from tests.test_notice_collection import FakeBrowser
        self.controller.shutdown()
        with tempfile.TemporaryDirectory() as directory:
            browser = FakeBrowser()
            service = NoticeCollectionService(Path(directory), browser=browser)
            self.controller = NoticeCollectionController(service, self.lookup, self.busy,
                now_factory=lambda: self.now, timer_start=False)
            self.lookup.return_value = {"user_id": "tyfd01214", "password": "fixture-password"}
            reports = []
            self.controller.reportReady.connect(reports.append)
            self.controller.verifyLogin()
            self.wait_for(lambda: not self.controller.isRunning)
            self.assertEqual(reports, [])
            def fail_scan(_password, cancel=None):
                raise NoticeLoginRequired("fixture-password https://example.invalid/private")
            browser.scan_unread = fail_scan
            self.controller.collectNow()
            self.wait_for(lambda: not self.controller.isRunning)
            self.assertEqual([row["state"] for row in reports], ["running", "failed"])
            self.assertEqual(reports[-1]["error_stage"], "login")
            self.assertIsNone(reports[-1]["unread_count"])
            self.assertIsNone(reports[-1]["marked_read_count"])
            self.assertNotIn("fixture-password", str(reports))
            self.assertNotIn("example.invalid", str(reports))

    def test_login_verification_checks_saved_fixed_password_without_collecting_notices(self):
        self.enable_saved_account()
        self.service.counts.return_value = (5, 10)
        self.controller.set_schedule_data(self.schedule())
        self.controller.verifyLogin()
        self.wait_for(lambda: not self.controller.isRunning)
        self.service.verify_login.assert_called_once()
        self.assertEqual(self.service.verify_login.call_args.args, ("test-password",))
        self.lookup.assert_called_with("tyfd01214")
        self.service.collect.assert_not_called()
        self.assertIn("tyfd01214", self.controller.verificationStatus)
        self.assertIn("驗證成功", self.controller.verificationStatus)
        self.assertIn("已自動收取 5 則通報", self.controller.statusText)
        self.controller.check_due()
        self.service.collect.assert_not_called()

    def test_verification_state_tracks_waiting_running_and_success_for_the_settings_view(self):
        self.enable_saved_account()
        self.assertEqual(self.controller.verificationState, "configured")
        observed = []
        self.controller.verificationStatusChanged.connect(
            lambda: observed.append(self.controller.verificationState))
        self.busy.return_value = "勤務登打"
        self.controller.verifyLogin()
        self.assertEqual(self.controller.verificationState, "waiting")
        release = threading.Event()
        self.addCleanup(release.set)
        self.service.verify_login.side_effect = lambda _password, cancel: release.wait(1)
        self.busy.return_value = ""
        self.controller.check_due()
        self.wait_for(lambda: self.service.verify_login.called)
        self.assertEqual(self.controller.verificationState, "verifying")
        release.set()
        self.wait_for(lambda: not self.controller.isRunning)
        self.assertEqual(self.controller.verificationState, "verified")
        self.assertEqual(observed, ["waiting", "verifying", "verified"])
        self.service.collect.assert_not_called()

    def test_verification_state_is_error_for_missing_credentials_and_backend_failure(self):
        self.controller.verifyLogin()
        self.assertEqual(self.controller.verificationState, "error")
        self.enable_saved_account()
        self.service.verify_login.side_effect = NoticeCollectionError("連線中斷")
        self.controller.verifyLogin()
        self.wait_for(lambda: not self.controller.isRunning)
        self.assertEqual(self.controller.verificationState, "error")
        self.service.collect.assert_not_called()

    def test_verification_state_change_notifies_even_when_status_text_is_unchanged(self):
        notified = []
        self.controller.verificationStatusChanged.connect(
            lambda: notified.append(self.controller.verificationState))
        self.controller._set_verification_status("相同狀態文字", "waiting")
        self.controller._set_verification_status("相同狀態文字", "verifying")
        self.controller._set_verification_status("相同狀態文字", "verifying")
        self.assertEqual(notified, ["waiting", "verifying"])

    def test_verification_missing_fixed_account_never_tries_other_credentials_or_collection(self):
        self.controller.verifyLogin()
        self.lookup.assert_called_once_with("tyfd01214")
        self.assertIn("尚未儲存", self.controller.verificationStatus)
        self.service.verify_login.assert_not_called()
        self.service.collect.assert_not_called()
        self.controller.check_due()
        self.lookup.assert_called_once()

    def test_verification_queued_during_busy_work_uses_latest_saved_password_once(self):
        self.enable_saved_account()
        self.busy.return_value = "勤務登打"
        for _ in range(3):
            self.controller.verifyLogin()
        self.assertIn("等待", self.controller.verificationStatus)
        self.lookup.assert_not_called()
        self.service.verify_login.assert_not_called()
        self.lookup.return_value = {"user_id": "tyfd01214", "password": "latest-test-password"}
        self.busy.return_value = ""
        self.controller.check_due()
        self.wait_for(lambda: not self.controller.isRunning)
        self.service.verify_login.assert_called_once()
        self.assertEqual(self.service.verify_login.call_args.args, ("latest-test-password",))
        self.service.collect.assert_not_called()

    def test_verification_waits_for_collection_and_uses_latest_saved_password(self):
        self.enable_saved_account()
        release = threading.Event()
        def collect(_password, received_at, cancel, **_kwargs):
            while not release.wait(0.01) and not cancel():
                pass
            return NoticeCollectionResult(received_at)
        self.service.collect.side_effect = collect
        self.addCleanup(release.set)
        self.controller.collectNow()
        self.wait_for(lambda: self.service.collect.called)
        for _ in range(3):
            self.controller.verifyLogin()
        self.lookup.return_value = {"user_id": "tyfd01214", "password": "latest-test-password"}
        self.service.verify_login.assert_not_called()
        release.set()
        self.wait_for(lambda: not self.controller.isRunning)
        self.service.verify_login.assert_called_once()
        self.assertEqual(self.service.verify_login.call_args.args, ("latest-test-password",))
        self.assertEqual(self.service.collect.call_count, 1)
        self.assertIn("驗證成功", self.controller.verificationStatus)

    def test_verification_is_single_flight_and_coalesces_repeated_requests(self):
        self.enable_saved_account()
        release = threading.Event()
        def verify(_password, cancel):
            while not release.wait(0.01) and not cancel():
                pass
        self.service.verify_login.side_effect = verify
        self.addCleanup(release.set)
        self.controller.verifyLogin()
        self.wait_for(lambda: self.service.verify_login.called)
        for _ in range(3):
            self.controller.verifyLogin()
        self.lookup.return_value = {"user_id": "tyfd01214", "password": "latest-test-password"}
        self.assertEqual(self.service.verify_login.call_count, 1)
        release.set()
        self.wait_for(lambda: not self.controller.isRunning)
        self.assertEqual(self.service.verify_login.call_count, 2)
        self.assertEqual(self.service.verify_login.call_args.args, ("latest-test-password",))
        self.service.collect.assert_not_called()

    def test_verification_errors_are_explicit_and_do_not_expose_password_or_raw_error(self):
        self.enable_saved_account()
        errors = [NoticeCollectionError("驗證失敗 test-password"), RuntimeError("private response")]
        for error in errors:
            with self.subTest(kind=type(error).__name__):
                self.service.verify_login.side_effect = error
                self.controller.verifyLogin()
                self.wait_for(lambda: not self.controller.isRunning)
                self.assertEqual("驗證未完成，原因待確認。", self.controller.verificationStatus)
                self.assertNotIn("test-password", self.controller.verificationStatus)
                self.assertNotIn("private response", self.controller.verificationStatus)
                self.assertNotIn("test-password", self.controller.statusText)
                self.service.collect.assert_not_called()

    def test_shutdown_cancels_verification_and_discards_queued_requests(self):
        self.enable_saved_account()
        reports = []
        self.controller.reportReady.connect(reports.append)
        def verify(_password, cancel):
            while not cancel():
                time.sleep(0.005)
            raise NoticeCollectionError("登入驗證已停止。")
        self.service.verify_login.side_effect = verify
        self.controller.verifyLogin()
        self.wait_for(lambda: self.service.verify_login.called)
        self.controller.verifyLogin()
        self.assertTrue(self.controller.shutdown())
        self.controller.verifyLogin()
        self.controller.check_due()
        self.app.processEvents()
        self.assertEqual(reports, [])
        self.assertEqual(self.service.verify_login.call_count, 1)
        self.service.collect.assert_not_called()

    def test_blank_password_waits_and_keeps_existing_counts_visible(self):
        self.lookup.return_value = {"user_id": "tyfd01214", "password": ""}
        self.service.counts.return_value = (5, 10)
        self.controller.set_schedule_data(self.schedule())
        self.controller.check_due()
        self.service.collect.assert_not_called()
        self.assertIn("當班時段已自動收取 5 則通報", self.controller.statusText)
        self.assertIn("今日累積 10 則", self.controller.statusText)

    def test_different_account_is_rejected_even_if_lookup_returns_a_password(self):
        self.lookup.return_value = {"user_id": "other-account", "password": "unrelated-password"}
        self.controller.check_due()
        self.service.collect.assert_not_called()
        self.assertEqual(self.controller.statusTone, "warning")

    def test_read_only_acceptance_disables_timer_and_both_collection_entrypoints(self):
        self.controller.shutdown()
        self.controller = NoticeCollectionController(
            self.service, self.lookup, self.busy, now_factory=lambda: self.now,
            read_only_acceptance=True,
        )
        self.controller.check_due()
        self.controller.collectNow()
        self.controller.verifyLogin()
        self.lookup.assert_not_called()
        self.service.collect.assert_not_called()
        self.service.verify_login.assert_not_called()
        self.assertFalse(self.controller.isRunning)

    def test_due_work_waits_for_busy_gate_then_runs_once_without_a_gui_session(self):
        self.enable_saved_account()
        self.busy.return_value = "勤務登打"
        self.controller.check_due()
        self.now += timedelta(hours=2)
        self.controller.check_due()
        self.service.collect.assert_not_called()
        self.lookup.assert_not_called()
        self.busy.return_value = ""
        self.controller.check_due()
        self.wait_for(lambda: not self.controller.isRunning)
        self.assertEqual(self.service.collect.call_count, 1)
        self.assertEqual(self.service.collect.call_args.args, ("test-password", self.now))
        self.controller.check_due()
        self.assertEqual(self.service.collect.call_count, 1)

    def test_running_collection_is_single_flight_even_when_manual_checks_arrive(self):
        self.enable_saved_account()
        release = threading.Event()
        def collect(_password, received_at, cancel, **_kwargs):
            while not release.wait(0.01):
                if cancel():
                    break
            return NoticeCollectionResult(received_at)
        self.service.collect.side_effect = collect
        self.addCleanup(release.set)
        self.controller.collectNow()
        self.wait_for(lambda: self.service.collect.called)
        for _ in range(3):
            self.controller.collectNow()
            self.controller.check_due()
        self.assertEqual(self.service.collect.call_count, 1)
        release.set()
        self.wait_for(lambda: not self.controller.isRunning)

    def test_completed_poll_only_appends_messages_for_incomplete_results(self):
        self.enable_saved_account()
        self.controller.set_schedule_data(self.schedule())
        cases = [
            (NoticeCollectionResult(self.now), (0, 0), "", "success"),
            (NoticeCollectionResult(self.now, written_keys=["new-notice"],
                                    message="已確認收取 1 則通報。"), (1, 2), "", "success"),
            (NoticeCollectionResult(self.now, error_count=1, status="partial",
                                    message="部分通報尚未完成收取。"),
             (1, 2), " 部分通報尚未完成收取。", "warning"),
            (NoticeCollectionResult(self.now, status="uncertain", message="通報寫入收據仍待確認。"),
             (1, 2), " 通報寫入收據仍待確認。", "warning"),
        ]
        for result, counts, suffix, tone in cases:
            with self.subTest(status=result.status, unread=result.unread_count):
                self.service.collect.return_value = result
                self.service.counts.return_value = counts
                self.controller.collectNow()
                self.wait_for(lambda: not self.controller.isRunning)
                self.assertEqual(
                    self.controller.statusText,
                    f"當班時段已自動收取 {counts[0]} 則通報，今日累積 {counts[1]} 則。{suffix}",
                )
                self.assertEqual(self.controller.statusTone, tone)

    def test_polling_rechecks_at_08_and_22_boundaries(self):
        self.now = self.now.replace(hour=7, minute=59)
        self.controller.collectNow()
        self.lookup.reset_mock()
        self.now = self.now.replace(hour=8, minute=0)
        self.controller.check_due()
        self.lookup.assert_called_once_with("tyfd01214")
        self.now = self.now.replace(hour=21, minute=59)
        self.controller.collectNow()
        self.lookup.reset_mock()
        self.now = self.now.replace(hour=22, minute=0)
        self.controller.check_due()
        self.lookup.assert_called_once_with("tyfd01214")

    def test_schedule_uses_whole_station_duty_and_counts_roll_over_when_shift_changes(self):
        self.service.counts.side_effect = lambda now, shift: (5 if now.hour < 10 else 0, 10)
        self.controller.set_schedule_data(self.schedule())
        self.assertEqual(self.controller.currentShiftText, "08-10")
        self.assertIn("當班時段已自動收取 5 則通報", self.controller.statusText)
        self.now = self.now.replace(hour=10)
        self.controller.check_due()
        self.assertEqual(self.controller.currentShiftText, "10-12")
        self.assertIn("當班時段已自動收取 0 則通報", self.controller.statusText)
        self.assertIn("今日累積 10 則", self.controller.statusText)

    def test_historical_audit_snapshot_does_not_replace_current_station_shift(self):
        self.controller.set_schedule_data(self.schedule())
        history = self.schedule()
        history["today"]["roc_date"] = "1151019"
        self.controller.set_schedule_data(history)
        self.assertEqual(self.controller.currentShiftText, "08-10")

    def test_current_schedule_without_valid_duty_does_not_keep_a_stale_shift(self):
        self.controller.set_schedule_data(self.schedule())
        updated = self.schedule()
        updated["today"]["rows"] = []
        self.controller.set_schedule_data(updated)
        self.assertEqual(self.controller.currentShiftText, "值班時段待取得")

    def test_new_fire_day_reloads_saved_schedule_without_a_gui_login(self):
        self.controller.shutdown()
        repository = Mock()
        repository.load_current.return_value = SimpleNamespace(found=True, data=self.schedule())
        self.controller = NoticeCollectionController(
            self.service, self.lookup, self.busy, repository,
            now_factory=lambda: self.now, timer_start=False,
        )
        tomorrow = self.schedule()
        tomorrow["today"]["roc_date"] = "1151022"
        repository.load_current.return_value = SimpleNamespace(found=True, data=tomorrow)
        self.now += timedelta(days=1)
        self.controller.check_due()
        self.assertEqual(repository.load_current.call_count, 2)
        self.assertEqual(self.controller.currentShiftText, "08-10")

    def test_midnight_refresh_keeps_overnight_shift_and_resets_calendar_day_count(self):
        self.now = self.now.replace(hour=23, minute=59)
        schedule = self.schedule()
        schedule["today"]["rows"] = [
            {"slot": "22~0", "columns": {"值班": ["1"]}},
            {"slot": "0~2", "columns": {"值班": ["1"]}},
        ]
        self.service.counts.side_effect = lambda now, shift: (5, 10 if now.day == 21 else 0)
        self.controller.set_schedule_data(schedule)
        self.assertIn("當班時段已自動收取 5 則通報", self.controller.statusText)
        self.assertIn("今日累積 10 則", self.controller.statusText)
        self.now += timedelta(minutes=1)
        self.controller.check_due()
        self.assertEqual(self.controller.currentShiftText, "22-翌日02")
        self.assertIn("已自動收取 5 則通報", self.controller.statusText)
        self.assertIn("今日累積 0 則", self.controller.statusText)

    def test_saved_schedule_is_available_before_any_gui_login(self):
        self.controller.shutdown()
        repository = Mock()
        repository.load_current.return_value = SimpleNamespace(found=True, data=self.schedule())
        self.controller = NoticeCollectionController(
            self.service, self.lookup, self.busy, repository,
            now_factory=lambda: self.now, timer_start=False,
        )
        self.assertEqual(self.controller.currentShiftText, "08-10")
        repository.load_current.assert_called_once_with(self.now)

    def test_login_required_keeps_successful_counts_and_reports_warning(self):
        self.enable_saved_account()
        self.service.counts.return_value = (5, 10)
        self.controller.set_schedule_data(self.schedule())
        self.service.collect.side_effect = NoticeLoginRequired("通報瀏覽器需要重新登入。")
        self.controller.collectNow()
        self.wait_for(lambda: not self.controller.isRunning)
        self.assertEqual(self.controller.statusTone, "warning")
        self.assertIn("重新登入", self.controller.statusText)
        self.assertIn("已自動收取 5 則通報", self.controller.statusText)

    def test_unknown_worker_error_never_exposes_raw_exception_or_password(self):
        self.enable_saved_account()
        self.service.collect.side_effect = RuntimeError("test-password and secret response")
        self.controller.collectNow()
        self.wait_for(lambda: not self.controller.isRunning)
        self.assertEqual(self.controller.statusTone, "error")
        self.assertNotIn("test-password", self.controller.statusText)
        self.assertNotIn("secret response", self.controller.statusText)

    def test_shutdown_cancels_safely_then_closes_browser_and_rejects_further_runs(self):
        self.enable_saved_account()
        def collect(_password, received_at, cancel, **_kwargs):
            while not cancel():
                time.sleep(0.005)
            return NoticeCollectionResult(received_at)
        self.service.collect.side_effect = collect
        self.controller.collectNow()
        self.wait_for(lambda: self.service.collect.called)
        self.assertTrue(self.controller.shutdown())
        self.assertFalse(self.controller.isRunning)
        self.service.close.assert_called_once()
        self.controller.collectNow()
        self.controller.check_due()
        self.assertEqual(self.service.collect.call_count, 1)


if __name__ == "__main__":
    unittest.main()
