from __future__ import annotations

import os
import sys
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PACKAGE = Path(__file__).resolve().parents[1] / "WinPython_公務電腦使用包"
sys.path.insert(0, str(PACKAGE))

from PySide6.QtWidgets import QApplication
from app_core.notice_collection_service import NoticeCollectionError, NoticeCollectionResult, NoticeLoginRequired
from qt_app.controllers.notice_collection_controller import NoticeCollectionController

TAIPEI = timezone(timedelta(hours=8))


class NoticeCollectionControllerTests(unittest.TestCase):
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
        def collect(_password, received_at, cancel):
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
                self.assertIn("檢查帳號密碼或網站狀態", self.controller.verificationStatus)
                self.assertNotIn("test-password", self.controller.verificationStatus)
                self.assertNotIn("private response", self.controller.verificationStatus)
                self.assertNotIn("test-password", self.controller.statusText)
                self.service.collect.assert_not_called()

    def test_shutdown_cancels_verification_and_discards_queued_requests(self):
        self.enable_saved_account()
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
        def collect(_password, received_at, cancel):
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
        def collect(_password, received_at, cancel):
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
