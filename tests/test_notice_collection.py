# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import tempfile
import unittest
import json
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "WinPython_公務電腦使用包"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))


class FakeBrowser:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.events = []

    def scan_unread(self, password, cancel=None):
        self.events.append("scan")
        return self.rows

    def begin_login_verification(self, password):
        self.events.append("begin_login_verification")

    def read_content(self, record, cancel=None):
        self.events.append("read:" + record["key"])
        return "有效通報內文"

    def mark_read(self, records, cancel=None):
        self.events.append("mark:" + ",".join(row["key"] for row in records))
        return [row["key"] for row in records]

    def close(self):
        self.events.append("close")


def notice(key, date="115-10-21"):
    return {"key": str(key), "noticeId": str(key), "date": date,
            "subject": "測試主旨", "sender": "測試單位", "isUnread": True}


def write_response(payload, written, *, handled=None, errors=0):
    return {"status": "success", "requestId": payload["requestId"],
            "result": {"writtenKeys": list(written), "handledKeys": list(handled or written),
                       "success": len(written), "errors": errors}}


class NoticeCollectionTests(unittest.TestCase):
    def test_report_bootstraps_legacy_counts_without_inventing_subject_or_read_confirmation(self):
        from app_core.notice_collection_service import NoticeCollectionService
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "runtime_outputs/notice_collection/state.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"schema_version": 1, "collected": {
                "1": "2026-10-21T09:00:00+08:00"}, "pending": []}), encoding="utf-8")
            service = NoticeCollectionService(root, browser=FakeBrowser())
            now = datetime(2026, 10, 21, 10, tzinfo=timezone(timedelta(hours=8)))
            parts = service.report_parts("067f3bf8-c404-4431-8607-1f78d2187d80", "running", now,
                                         started_at=now, next_check=now + timedelta(minutes=3))
            self.assertEqual(parts[0]["records"], [{"key": hashlib.sha256(b"1").hexdigest(),
                "subject": "", "received_at": "2026-10-21T09:00:00+08:00", "read_state": "unknown"}])
            self.assertIsNone(parts[0]["unread_count"])
            self.assertEqual(parts[0]["calendar_day"], "2026-10-21")

    def test_report_retains_subject_and_separates_write_confirmation_from_failed_read_marker(self):
        from app_core.notice_collection_service import NoticeCollectionService
        browser = FakeBrowser([notice(1), notice(2)])
        browser.mark_read = lambda _rows, cancel=None: []
        def poster(payload):
            return ({"status": "success", "existingKeys": ["2"]} if payload["action"] == "checkExisting"
                    else write_response(payload, ["1"]))
        with tempfile.TemporaryDirectory() as directory:
            service = NoticeCollectionService(Path(directory), browser=browser, poster=poster)
            started = datetime(2026, 10, 21, 23, 59)
            result = service.collect("fixture-private-password", started)
            parts = service.report_parts("067f3bf8-c404-4431-8607-1f78d2187d80", result.status,
                started, started_at=started, next_check=started + timedelta(minutes=1), result=result)
            self.assertEqual(parts[0]["state"], "partial")
            self.assertEqual((parts[0]["new_count"], parts[0]["marked_read_count"], parts[0]["pending_read_count"]), (1, 0, 2))
            self.assertEqual(parts[0]["records"][0]["subject"], "測試主旨")
            self.assertEqual(parts[0]["records"][0]["read_state"], "pending")
            self.assertEqual(parts[0]["error_stage"], "mark_read")
            saved = service.state_path.read_text(encoding="utf-8")
            self.assertNotIn("fixture-private-password", saved + str(parts))
            self.assertNotIn("有效通報內文", saved + str(parts))
            self.assertEqual(len(parts[0]["records"]), 1)  # Cloud duplicates are not this PC's new receipts.

    def test_reporting_chunks_all_records_and_preserves_confirmed_writes_after_later_failure(self):
        from app_core.notice_collection_service import NoticeCollectionService, NoticeCollectionError
        calls = [0]
        def poster(payload):
            if payload["action"] == "checkExisting":
                calls[0] += 1
                if calls[0] == 2:
                    raise TimeoutError("fixture should never be exported")
                return {"status": "success", "existingKeys": []}
            return write_response(payload, [row["key"] for row in payload["records"]])
        with tempfile.TemporaryDirectory() as directory:
            service = NoticeCollectionService(Path(directory), browser=FakeBrowser([notice(i) for i in range(201)]), poster=poster)
            now = datetime(2026, 10, 21, 23, 59)
            with self.assertRaises(NoticeCollectionError):
                service.collect("fixture-private-password", now)
            result = service.last_result
            self.assertEqual((result.status, len(result.written_keys)), ("partial", 200))
            report = service.report_parts("067f3bf8-c404-4431-8607-1f78d2187d80", result.status,
                now + timedelta(minutes=2), started_at=now, next_check=now + timedelta(minutes=31), result=result)[0]
            self.assertEqual((report["calendar_day"], report["new_count"]), ("2026-10-22", 200))
            self.assertEqual(len(report["records"]), 200)  # Previous-date receipts still appear in this result.
            self.assertTrue(all(row["received_at"].startswith("2026-10-21T23:59") for row in report["records"]))
            self.assertEqual(report["pending_read_count"], 200)
            self.assertNotIn("fixture should never be exported", str(report))
            self.assertEqual(service.counts(datetime(2026, 10, 22, 0, 1)), (0, 0))

    def test_bootstrap_splits_more_than_two_hundred_records_without_truncation(self):
        from app_core.notice_collection_service import NoticeCollectionService
        with tempfile.TemporaryDirectory() as directory:
            service = NoticeCollectionService(Path(directory), browser=FakeBrowser())
            service._state["collected"] = {str(i): "2026-10-21T09:00:00+08:00" for i in range(401)}
            now = datetime(2026, 10, 21, 10)
            parts = service.report_parts("067f3bf8-c404-4431-8607-1f78d2187d80", "running", now,
                started_at=now, next_check=now + timedelta(minutes=3))
            self.assertEqual([len(part["records"]) for part in parts], [200, 200, 1])
            self.assertEqual([part["part_index"] for part in parts], [0, 1, 2])
            self.assertTrue(all(part["part_count"] == 3 for part in parts))
            self.assertEqual(len({row["key"] for part in parts for row in part["records"]}), 401)

    def test_no_unread_finishes_without_content_or_apps_script(self):
        from app_core.notice_collection_service import NoticeCollectionService

        browser = FakeBrowser()
        with tempfile.TemporaryDirectory() as directory:
            service = NoticeCollectionService(Path(directory), browser=browser,
                                              poster=lambda payload: self.fail("不應呼叫 Apps Script"))
            result = service.collect("synthetic-password", datetime(2026, 10, 21, 9))
            self.assertEqual(browser.events, ["scan"])
            self.assertEqual(result.unread_count, 0)
            self.assertEqual(result.written_keys, [])
            self.assertEqual(service.counts(datetime(2026, 10, 21, 9)), (0, 0))

    def test_compare_precedes_content_and_only_confirmed_records_are_marked(self):
        from app_core.notice_collection_service import NoticeCollectionService

        browser = FakeBrowser([notice(1), notice(2), notice(3)])

        def poster(payload):
            browser.events.append("post:" + payload["action"])
            if payload["action"] == "checkExisting":
                return {"status": "success", "existingKeys": ["2"], "retryKeys": []}
            return write_response(payload, ["1"], errors=1)

        with tempfile.TemporaryDirectory() as directory:
            service = NoticeCollectionService(Path(directory), browser=browser, poster=poster)
            result = service.collect("synthetic-password", datetime(2026, 10, 21, 9))
            self.assertEqual(browser.events, ["scan", "post:checkExisting", "read:1", "read:3",
                                              "post:writeRecords", "mark:1,2"])
            self.assertEqual(result.written_keys, ["1"])
            self.assertEqual(result.marked_read_count, 2)
            self.assertGreaterEqual(result.error_count, 1)
            self.assertEqual(service.counts(datetime(2026, 10, 21, 9)), (0, 1))
            saved = (Path(directory) / "runtime_outputs/notice_collection/state.json").read_text(encoding="utf-8")
            self.assertNotIn("synthetic-password", saved)
            self.assertNotIn("有效通報內文", saved)

    def test_midnight_resets_daily_count_while_the_same_shift_continues(self):
        from app_core.notice_collection_service import NoticeCollectionService, NoticeShift, TAIPEI

        with tempfile.TemporaryDirectory() as directory:
            browser = FakeBrowser([notice(1)])
            service = NoticeCollectionService(Path(directory), browser=browser,
                poster=lambda p: {"status": "success", "existingKeys": [], "retryKeys": []}
                if p["action"] == "checkExisting" else write_response(p, [r["key"] for r in p["records"]]))
            shift = NoticeShift("night", "22-翌日02", datetime(2026, 10, 21, 22, tzinfo=TAIPEI),
                                datetime(2026, 10, 22, 2, tzinfo=TAIPEI))
            service.collect("synthetic-password", datetime(2026, 10, 21, 23, 59))
            browser.rows = [notice(2)]
            service.collect("synthetic-password", datetime(2026, 10, 22, 0, 1))
            self.assertEqual(service.counts(datetime(2026, 10, 22, 1), shift), (2, 1))
            restarted = NoticeCollectionService(Path(directory), browser=browser)
            self.assertEqual(restarted.counts(datetime(2026, 10, 22, 1), shift), (2, 1))

    def test_failed_read_marker_does_not_erase_or_duplicate_successful_counts(self):
        from app_core.notice_collection_service import NoticeCollectionService

        browser = FakeBrowser([notice(1)])
        calls = []

        def poster(payload):
            calls.append(payload["action"])
            if payload["action"] == "checkExisting":
                return {"status": "success", "existingKeys": ["1"] if len(calls) > 2 else [], "retryKeys": []}
            return write_response(payload, ["1"])

        with tempfile.TemporaryDirectory() as directory:
            service = NoticeCollectionService(Path(directory), browser=browser, poster=poster)
            with patch.object(browser, "mark_read", side_effect=RuntimeError("synthetic failure")):
                result = service.collect("synthetic-password", datetime(2026, 10, 21, 9))
            self.assertEqual(result.error_count, 1)
            self.assertEqual(service.counts(datetime(2026, 10, 21, 9)), (0, 1))
            service.collect("synthetic-password", datetime(2026, 10, 21, 9, 3))
            self.assertEqual(calls.count("writeRecords"), 1)
            self.assertEqual(service.counts(datetime(2026, 10, 21, 9, 3)), (0, 1))

    def test_cancelled_operation_never_begins_a_write_or_read_marker(self):
        from app_core.notice_collection_service import NoticeCollectionService, NoticeCollectionError

        browser = FakeBrowser([notice(1)])
        with tempfile.TemporaryDirectory() as directory:
            service = NoticeCollectionService(Path(directory), browser=browser,
                                              poster=lambda p: self.fail("取消後不得寫入"))
            with self.assertRaises(NoticeCollectionError):
                service.collect("synthetic-password", datetime(2026, 10, 21, 9), cancel=lambda: True)
            self.assertEqual(browser.events, [])

    def test_uncertain_write_is_resolved_by_receipt_after_restart_without_resend(self):
        from app_core.notice_collection_service import NoticeCollectionService

        requests = []
        request_id = ""

        def unavailable(payload):
            nonlocal request_id
            requests.append(payload)
            if payload["action"] == "checkExisting":
                return {"status": "success", "existingKeys": [], "retryKeys": []}
            if payload["action"] == "writeRecords":
                request_id = payload["requestId"]
            if payload["action"] == "getWriteResult":
                return {"status": "success", "found": False, "requestId": payload["requestId"]}
            raise TimeoutError("synthetic timeout")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = NoticeCollectionService(root, browser=FakeBrowser([notice(1)]), poster=unavailable)
            first.collect("synthetic-password", datetime(2026, 10, 21, 23, 59))

            def recovered(payload):
                requests.append(payload)
                if payload["action"] == "getWriteResult":
                    self.assertEqual(payload["requestId"], request_id)
                    return {"status": "success", "found": True, "requestId": request_id,
                            "result": {"writtenKeys": ["1"], "handledKeys": ["1"]}}
                self.assertEqual(payload["action"], "checkExisting")
                return {"status": "success", "existingKeys": ["1"], "retryKeys": []}

            browser = FakeBrowser([notice(1)])
            second = NoticeCollectionService(root, browser=browser, poster=recovered)
            result = second.collect("synthetic-password", datetime(2026, 10, 22, 0, 1))
            self.assertEqual(second.counts(datetime(2026, 10, 21, 23, 59)), (0, 1))
            self.assertEqual(second.counts(datetime(2026, 10, 22, 0, 1)), (0, 0))
            self.assertEqual(result.marked_read_count, 1)
            self.assertNotIn("read:1", browser.events)

    def test_unresolved_pending_write_is_not_resent_or_marked_after_restart(self):
        from app_core.notice_collection_service import NoticeCollectionService

        def initial(payload):
            if payload["action"] == "checkExisting":
                return {"status": "success", "existingKeys": [], "retryKeys": []}
            if payload["action"] == "getWriteResult":
                return {"status": "success", "found": False, "requestId": payload["requestId"]}
            raise TimeoutError("synthetic timeout")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = NoticeCollectionService(root, browser=FakeBrowser([notice(1)]), poster=initial)
            service.collect("synthetic-password", datetime(2026, 10, 21, 9))
            browser = FakeBrowser([notice(1)])

            def unresolved(payload):
                self.assertNotEqual(payload["action"], "writeRecords")
                return initial(payload)

            restarted = NoticeCollectionService(root, browser=browser, poster=unresolved)
            result = restarted.collect("synthetic-password", datetime(2026, 10, 21, 9, 3))
            self.assertEqual(result.status, "uncertain")
            self.assertEqual(browser.events, ["scan"])
            self.assertEqual(restarted.counts(datetime(2026, 10, 21, 9, 3)), (0, 0))

    def test_mismatched_request_id_never_counts_or_marks_the_attempted_record(self):
        from app_core.notice_collection_service import NoticeCollectionService

        def poster(payload):
            if payload["action"] == "checkExisting":
                return {"status": "success", "existingKeys": [], "retryKeys": []}
            response = write_response({"requestId": "wrong-request-id"}, ["1"])
            return response

        with tempfile.TemporaryDirectory() as directory:
            browser = FakeBrowser([notice(1)])
            service = NoticeCollectionService(Path(directory), browser=browser, poster=poster)
            result = service.collect("synthetic-password", datetime(2026, 10, 21, 9))
            self.assertNotEqual(result.status, "success")
            self.assertEqual(service.counts(datetime(2026, 10, 21, 9)), (0, 0))
            self.assertFalse(any(e.startswith("mark:") for e in browser.events))

    def test_ledger_failure_before_post_prevents_official_write(self):
        from app_core.notice_collection_service import NoticeCollectionService, NoticeCollectionError

        calls = []
        def poster(payload):
            calls.append(payload["action"])
            return {"status": "success", "existingKeys": [], "retryKeys": []}

        with tempfile.TemporaryDirectory() as directory:
            browser = FakeBrowser([notice(1)])
            service = NoticeCollectionService(Path(directory), browser=browser, poster=poster)
            with patch.object(Path, "replace", side_effect=PermissionError("synthetic failure")):
                with self.assertRaises(NoticeCollectionError):
                    service.collect("synthetic-password", datetime(2026, 10, 21, 9))
            self.assertEqual(calls, ["checkExisting"])
            self.assertFalse(any(e.startswith("mark:") for e in browser.events))

    def test_ledger_failure_after_official_write_keeps_intent_and_never_marks(self):
        from app_core.notice_collection_service import NoticeCollectionService, NoticeCollectionError

        browser = FakeBrowser([notice(1)])
        calls = []
        def poster(payload):
            calls.append(payload["action"])
            if payload["action"] == "checkExisting":
                return {"status": "success", "existingKeys": [], "retryKeys": []}
            return write_response(payload, ["1"])
        original_replace = Path.replace
        replace_count = 0
        def replace(source, destination):
            nonlocal replace_count
            replace_count += 1
            if replace_count == 2:
                raise PermissionError("synthetic final ledger failure")
            return original_replace(source, destination)

        with tempfile.TemporaryDirectory() as directory:
            service = NoticeCollectionService(Path(directory), browser=browser, poster=poster)
            with patch.object(Path, "replace", replace):
                with self.assertRaises(NoticeCollectionError):
                    service.collect("synthetic-password", datetime(2026, 10, 21, 9))
            self.assertEqual(calls.count("writeRecords"), 1)
            self.assertFalse(any(e.startswith("mark:") for e in browser.events))
            state = json.loads(service.state_path.read_text(encoding="utf-8"))
            self.assertEqual(len(state["pending"]), 1)
            self.assertEqual(state["collected"], {})

    def test_receipt_for_a_notice_already_read_does_not_report_a_marker_failure(self):
        from app_core.notice_collection_service import NoticeCollectionService

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "runtime_outputs/notice_collection/state.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text(json.dumps({"schema_version": 1, "collected": {}, "pending": [
                {"request_id": "notice-pending-1", "received_at": "2026-10-21T09:00:00+08:00", "records": [notice(1)]}
            ]}), encoding="utf-8")
            browser = FakeBrowser()
            service = NoticeCollectionService(root, browser=browser, poster=lambda payload: {
                "status": "success", "found": True, "requestId": "notice-pending-1",
                "result": {"writtenKeys": ["1"], "handledKeys": ["1"]}})
            result = service.collect("synthetic-password", datetime(2026, 10, 21, 9, 3))
            self.assertEqual(result.status, "success")
            self.assertEqual(result.error_count, 0)
            self.assertEqual(result.marked_read_count, 0)
            self.assertEqual(browser.events, ["scan"])
            parts = service.report_parts("067f3bf8-c404-4431-8607-1f78d2187d80", result.status,
                datetime(2026, 10, 21, 9, 3), next_check=datetime(2026, 10, 21, 9, 6), result=result)
            self.assertEqual(parts[0]["records"][0]["read_state"], "confirmed")
            self.assertEqual(parts[0]["pending_read_count"], 0)
            restarted = NoticeCollectionService(root, browser=FakeBrowser())
            self.assertEqual(restarted._state["confirmed"]["1"]["read_state"], "confirmed")

    def test_requests_are_chunked_to_existing_two_hundred_record_limit(self):
        from app_core.notice_collection_service import NoticeCollectionService

        sizes = []
        def poster(payload):
            sizes.append(len(payload["records"]))
            if payload["action"] == "checkExisting":
                return {"status": "success", "existingKeys": [], "retryKeys": []}
            return write_response(payload, [r["key"] for r in payload["records"]])

        with tempfile.TemporaryDirectory() as directory:
            service = NoticeCollectionService(Path(directory), browser=FakeBrowser([notice(i) for i in range(201)]),
                                              poster=poster)
            result = service.collect("synthetic-password", datetime(2026, 10, 21, 9))
            self.assertEqual(sizes, [200, 200, 1, 1])
            self.assertEqual(len(result.written_keys), 201)
            self.assertEqual(service.counts(datetime(2026, 10, 21, 9)), (0, 201))

    def test_unavailable_content_is_not_written_or_marked(self):
        from app_core.notice_collection_service import NoticeCollectionService

        browser = FakeBrowser([notice(1)])
        calls = []
        def poster(payload):
            calls.append(payload["action"])
            return {"status": "success", "existingKeys": [], "retryKeys": ["1"]}
        with tempfile.TemporaryDirectory() as directory:
            service = NoticeCollectionService(Path(directory), browser=browser, poster=poster)
            with patch.object(browser, "read_content", return_value="權限限制"):
                result = service.collect("synthetic-password", datetime(2026, 10, 21, 9))
            self.assertEqual(calls, ["checkExisting"])
            self.assertEqual(result.error_count, 1)
            self.assertEqual(result.marked_read_count, 0)

    def test_daily_count_does_not_reset_at_fire_day_eight_am(self):
        from app_core.notice_collection_service import NoticeCollectionService

        browser = FakeBrowser([notice(1)])
        with tempfile.TemporaryDirectory() as directory:
            service = NoticeCollectionService(Path(directory), browser=browser, poster=lambda p:
                {"status": "success", "existingKeys": [], "retryKeys": []} if p["action"] == "checkExisting"
                else write_response(p, [r["key"] for r in p["records"]]))
            service.collect("synthetic-password", datetime(2026, 10, 21, 7, 59))
            browser.rows = [notice(2)]
            service.collect("synthetic-password", datetime(2026, 10, 21, 8))
            self.assertEqual(service.counts(datetime(2026, 10, 21, 8)), (0, 2))

    def test_corrupt_ledger_counts_report_unavailable_instead_of_zero(self):
        from app_core.notice_collection_service import NoticeCollectionService, NoticeCollectionError

        cases = ["{", json.dumps({"schema_version": 1, "collected": {"1": "invalid-time"}, "pending": []})]
        for content in cases:
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state_path = root / "runtime_outputs/notice_collection/state.json"
                state_path.parent.mkdir(parents=True)
                state_path.write_text(content, encoding="utf-8")
                browser = FakeBrowser()
                service = NoticeCollectionService(root, browser=browser,
                                                  poster=lambda payload: self.fail("紀錄毀損不得送出"))
                with self.assertRaises(NoticeCollectionError):
                    service.counts(datetime(2026, 10, 21, 9))
                with self.assertRaises(NoticeCollectionError):
                    service.collect("synthetic-password", datetime(2026, 10, 21, 9))
                self.assertEqual(browser.events, [])
                self.assertEqual(state_path.read_text(encoding="utf-8"), content)

    def test_repaired_existing_notices_are_marked_but_only_new_notices_are_counted(self):
        from app_core.notice_collection_service import NoticeCollectionService

        browser = FakeBrowser([notice(1), notice(2), notice(3)])
        def poster(payload):
            if payload["action"] == "checkExisting":
                return {"status": "success", "existingKeys": ["3"], "retryKeys": ["2"]}
            return write_response(payload, ["1", "2"])
        with tempfile.TemporaryDirectory() as directory:
            service = NoticeCollectionService(Path(directory), browser=browser, poster=poster)
            result = service.collect("synthetic-password", datetime(2026, 10, 21, 9))
            self.assertEqual(result.written_keys, ["1"])
            self.assertEqual(result.marked_read_count, 3)
            self.assertEqual(result.error_count, 0)
            self.assertEqual(browser.events, ["scan", "read:1", "read:2", "mark:1,2,3"])
            self.assertEqual(service.counts(datetime(2026, 10, 21, 9)), (0, 1))

    def test_repaired_notice_classification_survives_uncertain_write_and_restart(self):
        from app_core.notice_collection_service import NoticeCollectionService

        request_id = ""
        def unavailable(payload):
            nonlocal request_id
            if payload["action"] == "checkExisting":
                return {"status": "success", "existingKeys": [], "retryKeys": ["2"]}
            if payload["action"] == "getWriteResult":
                return {"status": "success", "found": False, "requestId": payload["requestId"]}
            request_id = payload["requestId"]
            raise TimeoutError("synthetic timeout")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = NoticeCollectionService(root, browser=FakeBrowser([notice(1), notice(2)]), poster=unavailable)
            first.collect("synthetic-password", datetime(2026, 10, 21, 9))
            persisted = json.loads(first.state_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["pending"][0]["repair_keys"], ["2"])
            def recovered(payload):
                if payload["action"] == "getWriteResult":
                    return {"status": "success", "found": True, "requestId": request_id,
                            "result": {"writtenKeys": ["1", "2"], "handledKeys": ["1", "2"]}}
                self.assertEqual(payload["action"], "checkExisting")
                return {"status": "success", "existingKeys": ["1", "2"], "retryKeys": []}
            browser = FakeBrowser([notice(1), notice(2)])
            second = NoticeCollectionService(root, browser=browser, poster=recovered)
            result = second.collect("synthetic-password", datetime(2026, 10, 21, 9, 3))
            self.assertEqual(result.written_keys, ["1"])
            self.assertEqual(result.marked_read_count, 2)
            self.assertEqual(browser.events, ["scan", "mark:1,2"])
            self.assertEqual(second.counts(datetime(2026, 10, 21, 9, 3)), (0, 1))

    def test_invalid_retry_keys_stop_before_content_or_official_changes(self):
        from app_core.notice_collection_service import NoticeCollectionService, NoticeCollectionError

        cases = [([], "1"), ([], ["999"]), (["1"], ["1"])]
        for existing, retry in cases:
            with self.subTest(existing=existing, retry=retry), tempfile.TemporaryDirectory() as directory:
                browser = FakeBrowser([notice(1)])
                calls = []
                def poster(payload):
                    calls.append(payload["action"])
                    return {"status": "success", "existingKeys": existing, "retryKeys": retry}
                service = NoticeCollectionService(Path(directory), browser=browser, poster=poster)
                with self.assertRaises(NoticeCollectionError):
                    service.collect("synthetic-password", datetime(2026, 10, 21, 9))
                self.assertEqual(calls, ["checkExisting"])
                self.assertEqual(browser.events, ["scan"])
                self.assertFalse(service.state_path.exists())

    def test_invalid_pending_repair_keys_do_not_guess_new_counts(self):
        from app_core.notice_collection_service import NoticeCollectionService, NoticeCollectionError

        for repair_keys in ("1", ["999"], [1]):
            with self.subTest(repair_keys=repair_keys), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state_path = root / "runtime_outputs/notice_collection/state.json"
                state_path.parent.mkdir(parents=True)
                content = json.dumps({"schema_version": 1, "collected": {}, "pending": [
                    {"request_id": "notice-pending-1", "received_at": "2026-10-21T09:00:00+08:00",
                     "records": [notice(1)], "repair_keys": repair_keys}]})
                state_path.write_text(content, encoding="utf-8")
                browser = FakeBrowser()
                service = NoticeCollectionService(root, browser=browser,
                    poster=lambda payload: self.fail("分類毀損不得送出"))
                with self.assertRaises(NoticeCollectionError):
                    service.counts(datetime(2026, 10, 21, 9))
                with self.assertRaises(NoticeCollectionError):
                    service.collect("synthetic-password", datetime(2026, 10, 21, 9))
                self.assertEqual(browser.events, [])
                self.assertEqual(state_path.read_text(encoding="utf-8"), content)


class NoticeLoginVerificationTests(unittest.TestCase):
    def test_fresh_login_verification_does_not_collect_or_modify_existing_ledger(self):
        from app_core.notice_collection_service import NoticeCollectionService

        browser = FakeBrowser([notice(1), notice(2)])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "runtime_outputs/notice_collection/state.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text(json.dumps({"schema_version": 1,
                "collected": {"9": "2026-10-21T08:30:00+08:00"}, "pending": []}), encoding="utf-8")
            original = state_path.read_bytes()
            service = NoticeCollectionService(root, browser=browser,
                poster=lambda payload: self.fail("登入驗證不得呼叫 Apps Script"),
                now_factory=lambda: datetime(2026, 10, 21, 9))
            result = service.verify_login("synthetic-login-secret")
            self.assertEqual(result.status, "login_verified")
            self.assertEqual(result.message, "通報帳號 tyfd01214 登入驗證成功。")
            self.assertEqual(result.unread_count, 2)
            self.assertEqual(result.written_keys, [])
            self.assertEqual(result.marked_read_count, 0)
            self.assertNotIn("synthetic-login-secret", repr(result))
            self.assertEqual(browser.events, ["begin_login_verification", "scan"])
            self.assertEqual(state_path.read_bytes(), original)
            self.assertEqual(service.counts(datetime(2026, 10, 21, 9)), (0, 1))
            service.verify_login("synthetic-login-secret")
            self.assertEqual(browser.events, ["begin_login_verification", "scan"] * 2)

    def test_success_with_no_unread_does_not_create_a_collection_ledger(self):
        from app_core.notice_collection_service import NoticeCollectionService

        with tempfile.TemporaryDirectory() as directory:
            browser = FakeBrowser()
            service = NoticeCollectionService(Path(directory), browser=browser,
                poster=lambda payload: self.fail("登入驗證不得呼叫 Apps Script"))
            self.assertEqual(service.verify_login("synthetic-login-secret").status, "login_verified")
            self.assertFalse(service.state_path.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_empty_password_or_pre_cancel_stops_before_browser_actions(self):
        from app_core.notice_collection_service import NoticeCollectionService, NoticeCollectionError

        with tempfile.TemporaryDirectory() as directory:
            browser = FakeBrowser()
            service = NoticeCollectionService(Path(directory), browser=browser)
            for password in ("", None):
                with self.subTest(password=password), self.assertRaises(NoticeCollectionError):
                    service.verify_login(password)
            with self.assertRaises(NoticeCollectionError):
                service.verify_login("synthetic-login-secret", cancel=lambda: True)
            self.assertEqual(browser.events, [])
            self.assertFalse(service.state_path.exists())

    def test_cancel_after_profile_reset_does_not_begin_login(self):
        from app_core.notice_collection_service import NoticeCollectionService, NoticeCollectionError

        cancelled = False
        def begin(_password):
            nonlocal cancelled
            cancelled = True
        with tempfile.TemporaryDirectory() as directory:
            browser = FakeBrowser()
            service = NoticeCollectionService(Path(directory), browser=browser)
            with patch.object(browser, "begin_login_verification", side_effect=begin):
                with self.assertRaises(NoticeCollectionError):
                    service.verify_login("synthetic-login-secret", cancel=lambda: cancelled)
            self.assertEqual(browser.events, [])

    def test_login_failure_and_invalid_source_never_report_verified_or_leak_secret(self):
        from app_core.notice_collection_service import NoticeCollectionService, NoticeCollectionError, NoticeLoginRequired

        with tempfile.TemporaryDirectory() as directory:
            browser = FakeBrowser()
            service = NoticeCollectionService(Path(directory), browser=browser,
                poster=lambda payload: self.fail("登入驗證不得呼叫 Apps Script"))
            with patch.object(browser, "scan_unread", side_effect=NoticeLoginRequired("通報登入未完成。")):
                with self.assertRaises(NoticeLoginRequired):
                    service.verify_login("synthetic-login-secret")
            for method in ("begin_login_verification", "scan_unread"):
                with self.subTest(method=method), patch.object(browser, method,
                        side_effect=RuntimeError("synthetic-login-secret")):
                    with self.assertRaises(NoticeCollectionError) as failed:
                        service.verify_login("synthetic-login-secret")
                    self.assertNotIn("synthetic-login-secret", str(failed.exception))
            with patch.object(browser, "scan_unread", return_value=None):
                with self.assertRaises(NoticeCollectionError):
                    service.verify_login("synthetic-login-secret")
            self.assertFalse(service.state_path.exists())


class NoticeScheduleTests(unittest.TestCase):
    def test_cadence_uses_wall_clock_and_changes_at_eight_and_twenty_two(self):
        from app_core.notice_collection_service import next_check_at

        cases = [
            (datetime(2026, 10, 21, 7, 59, 59), datetime(2026, 10, 21, 8)),
            (datetime(2026, 10, 21, 8), datetime(2026, 10, 21, 8, 3)),
            (datetime(2026, 10, 21, 9, 4, 15), datetime(2026, 10, 21, 9, 6)),
            (datetime(2026, 10, 21, 21, 59, 59), datetime(2026, 10, 21, 22)),
            (datetime(2026, 10, 21, 22), datetime(2026, 10, 21, 22, 30)),
            (datetime(2026, 10, 21, 23, 59), datetime(2026, 10, 22)),
        ]
        for now, expected in cases:
            with self.subTest(now=now):
                self.assertEqual(next_check_at(now), expected)
        utc = timezone.utc
        self.assertEqual(next_check_at(datetime(2026, 10, 21, 0, tzinfo=utc)).hour, 8)

    def test_shift_merges_adjacent_same_staff_and_uses_business_day_only_for_roster(self):
        from app_core.notice_collection_service import current_shift

        schedule = {"today": {"roc_date": "1151021", "staff": {}, "rows": [
            {"slot": "8~9", "columns": {"值班": ["3"]}},
            {"slot": "9~10", "columns": {"值班": ["3"]}},
            {"slot": "10~12", "columns": {"值班": ["4"]}},
        ]}}
        shift = current_shift(schedule, datetime(2026, 10, 21, 9))
        self.assertEqual(shift.label, "08-10")
        self.assertEqual(shift.start.hour, 8)
        self.assertEqual(shift.end.hour, 10)
        self.assertEqual(current_shift(schedule, datetime(2026, 10, 21, 10)).label, "10-12")
        self.assertIsNone(current_shift(schedule, datetime(2026, 10, 22, 9)))

    def test_shift_spans_midnight_without_changing_its_key(self):
        from app_core.notice_collection_service import current_shift

        schedule = {"today": {"roc_date": "1151021", "staff": {}, "rows": [
            {"slot": "22~0", "columns": {"值班": ["3"]}},
            {"slot": "0~2", "columns": {"值班": ["3"]}},
            {"slot": "2~4", "columns": {"值班": ["4"]}},
        ]}}
        before = current_shift(schedule, datetime(2026, 10, 21, 23))
        after = current_shift(schedule, datetime(2026, 10, 22, 1))
        self.assertEqual(before.key, after.key)
        self.assertEqual(after.start.day, 21)
        self.assertEqual(after.end.day, 22)

    def test_ambiguous_or_empty_duty_period_does_not_guess(self):
        from app_core.notice_collection_service import current_shift

        day = {"roc_date": "1151021", "staff": {}, "rows": [
            {"slot": "8~10", "columns": {"值班": ["3"]}},
            {"slot": "9~11", "columns": {"值班": ["4"]}},
        ]}
        self.assertIsNone(current_shift({"today": day}, datetime(2026, 10, 21, 9)))


if __name__ == "__main__":
    unittest.main()
