from __future__ import annotations

from contextlib import redirect_stderr
from io import StringIO
import os
import sys
import threading
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "WinPython_公務電腦使用包"

class RescueVideoPackageTests(unittest.TestCase):
    @staticmethod
    def _classifier_module():
        source_dir = PACKAGE_ROOT / "rescue_video"
        if str(source_dir) not in sys.path:
            sys.path.insert(0, str(source_dir))
        import classify_rescue_video

        return classify_rescue_video

    @staticmethod
    def _service_module():
        if str(PACKAGE_ROOT) not in sys.path:
            sys.path.insert(0, str(PACKAGE_ROOT))
        from app_core import rescue_video_service

        return rescue_video_service

    @staticmethod
    def _ts_packet(pid: int, pts: int) -> bytes:
        pts_bytes = bytes(
            (
                0x21 | (((pts >> 30) & 0x07) << 1),
                (pts >> 22) & 0xFF,
                0x01 | (((pts >> 15) & 0x7F) << 1),
                (pts >> 7) & 0xFF,
                0x01 | ((pts & 0x7F) << 1),
            )
        )
        payload = b"\x00\x00\x01\xe0\x00\x00\x80\x80\x05" + pts_bytes
        packet = bytearray(188)
        packet[0] = 0x47
        packet[1] = 0x40 | ((pid >> 8) & 0x1F)
        packet[2] = pid & 0xFF
        packet[3] = 0x10
        packet[4 : 4 + len(payload)] = payload
        packet[4 + len(payload) :] = b"\xff" * (188 - 4 - len(payload))
        return bytes(packet)

    def test_package_contains_rescue_video_core_and_qml_boundary(self) -> None:
        for relative_path in (
            "rescue_video/救護影片分類GUI.py",
            "rescue_video/classify_rescue_video.py",
            "app_core/rescue_video_service.py",
            "qt_app/controllers/rescue_video_controller.py",
            "qt_app/workers/rescue_video_worker.py",
            "qt_app/models/rescue_video_result_model.py",
        ):
            self.assertTrue((PACKAGE_ROOT / relative_path).is_file(), relative_path)

    def test_rescue_video_uses_nonmodal_qml_window_contract(self) -> None:
        source = (
            PACKAGE_ROOT / "qt_app" / "qml" / "dialogs" / "RescueVideoWindow.qml"
        ).read_text(encoding="utf-8")
        panel = source.split('id: rescueVideoWindow', 1)[1].split(
            'id: rescueVideoDeleteConfirmation', 1
        )[0]

        self.assertIn("Window {", source.split('id: rescueVideoWindow', 1)[0])
        self.assertIn("modality: Qt.NonModal", panel)
        self.assertIn("width: Design.rescueWindowWidth", panel)
        self.assertNotIn("ToolSidePanel {", panel)
        self.assertNotIn("CTkToplevel", panel)

    def test_rescue_video_qml_combines_date_vehicle_check_and_preview_flow(self) -> None:
        source = (
            PACKAGE_ROOT / "qt_app" / "qml" / "dialogs" / "RescueVideoWindow.qml"
        ).read_text(encoding="utf-8")

        self.assertLess(source.index('FormFieldTitle { text: "日期" }'), source.index('FormFieldTitle { text: "車號" }'))
        self.assertIn("refreshVehicleOptions(", source)
        self.assertIn('text: "檢查及預覽分類"', source)
        self.assertIn("controller.checkAndPreview(", source)
        self.assertNotIn('objectName: "rescueVideoPreviewButton"', source)
        self.assertIn('text: "矯正影片時間"', source)
        self.assertIn('text: rescueVideoResultRow.transferPercent + "%"', source)
        self.assertNotIn('text: rescueVideoResultRow.transferText', source)
        self.assertIn("component ResultColumnResizeHandle", source)
        self.assertIn('objectName: "rescueVideoResultResize_" + leftColumn', source)
        self.assertIn("resizeResultColumns(", source)
        self.assertIn(
            "color: parent.containsMouse || parent.pressed ? Design.blue : Design.border",
            source,
        )
        self.assertIn('column === "case" ? 80', source)
        self.assertIn('column === "status" ? 90', source)
        self.assertIn("columnWidthOverride: rescueVideoWindow.resultColumnWidth", source)
        self.assertIn("status: 160", source)
        self.assertIn('column === "status" ? 90', source)
        self.assertIn('modelData.level === "pending"', source)
        self.assertIn("onClosing: function(closeEvent)", source)
        self.assertIn("controller.resetForNextSession()", source)

        controller_source = (PACKAGE_ROOT / "qt_app" / "controllers" / "rescue_video_controller.py").read_text(encoding="utf-8")
        self.assertIn("本工具只支援單張記憶卡", controller_source)
        self.assertIn("errorText", controller_source)
        self.assertNotIn("請先完成預覽分類", controller_source)
        self.assertIn('text: "複製並刪除記憶卡中資料"', source)
        self.assertIn('objectName: "rescueVideoResultEmptyText"', source)
        self.assertIn('objectName: "rescueVideoCloseButton"', source)

    def test_window_keeps_minimize_and_maximize_available_during_copy(self) -> None:
        source = (
            PACKAGE_ROOT / "qt_app" / "qml" / "dialogs" / "RescueVideoWindow.qml"
        ).read_text(encoding="utf-8")
        minimize_start = source.index('objectName: "rescueVideoTitleMinimizeButton"')
        maximize_start = source.index('objectName: "rescueVideoTitleMaximizeButton"')
        close_start = source.index('objectName: "rescueVideoTitleCloseButton"')

        self.assertIn("enabled: true", source[minimize_start:maximize_start])
        self.assertIn("enabled: true", source[maximize_start:close_start])
        self.assertIn(
            "enabled: !rescueVideoWindow.interactionsLocked",
            source[close_start:],
        )

    def test_daily_tools_include_rescue_video_as_third_action(self) -> None:
        source = (
            PACKAGE_ROOT / "qt_app" / "qml" / "pages" / "DutyQuickToolsPanel.qml"
        ).read_text(encoding="utf-8")
        daily_tools = source.split('text: "每日作業"', 1)[1].split(
            'text: "每月作業"', 1
        )[0]

        self.assertLess(daily_tools.index('text: "勤務表登打"'), daily_tools.index('text: "車輛保養清點"'))
        self.assertLess(
            daily_tools.index('text: "車輛保養清點"'),
            daily_tools.index('text: "救護行車紀錄器"'),
        )
        self.assertIn('tone: "review"', daily_tools)
        self.assertIn("dutyQuickToolsPanel.rescueVideoWindow.open()", daily_tools)

    def test_update_backup_keeps_rescue_video_sources(self) -> None:
        source = (PACKAGE_ROOT / "update_package.ps1").read_text(encoding="utf-8-sig")

        self.assertIn('"rescue_video\\救護影片分類GUI.py"', source)
        self.assertIn('"rescue_video\\classify_rescue_video.py"', source)
        self.assertIn('"app_core"', source)
        self.assertIn('"qt_app"', source)

    def test_ts_duration_uses_embedded_pts_instead_of_a_fixed_segment_length(self) -> None:
        classifier = self._classifier_module()
        with TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "V0000001.TS"
            filler = bytearray(188)
            filler[0] = 0x47
            filler[3] = 0x10
            video.write_bytes(
                b"".join(self._ts_packet(256, seconds * 90_000) for seconds in (0, 1, 2, 3))
                + bytes(filler) * 12_000
                + b"".join(
                    self._ts_packet(256, seconds * 90_000) for seconds in (297, 298, 299, 300)
                )
            )

            duration = classifier.read_ts_duration(video)

        self.assertEqual(duration.total_seconds(), 300)

    def test_ts_duration_rejects_a_file_without_pts(self) -> None:
        classifier = self._classifier_module()
        with TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "V0000001.TS"
            video.write_bytes(b"\x47" * (188 * 4))

            with self.assertRaises(ValueError):
                classifier.read_ts_duration(video)

    def test_card_duration_uses_the_largest_file_as_its_single_representative(self) -> None:
        classifier = self._classifier_module()
        with TemporaryDirectory() as temp_dir:
            partial = Path(temp_dir) / "V0000001.TS"
            complete = Path(temp_dir) / "V0000002.TS"
            partial.write_bytes(b"a")
            complete.write_bytes(b"b" * 2)
            with mock.patch.object(
                classifier,
                "read_ts_duration",
                return_value=timedelta(minutes=5),
            ) as duration_reader:
                sample, duration = classifier.read_card_duration([partial, complete])

        self.assertEqual(sample, complete)
        self.assertEqual(duration, timedelta(minutes=5))
        duration_reader.assert_called_once_with(complete)

    def test_video_after_return_selects_the_following_case(self) -> None:
        classifier = self._classifier_module()
        previous = classifier.CaseFolder(
            Path("08120753-92"),
            "08120753-92",
            "92",
            datetime(2026, 8, 12, 7, 53),
            work_start=datetime(2026, 8, 12, 7, 53),
            return_time=datetime(2026, 8, 12, 9, 39, 44),
        )
        following = classifier.CaseFolder(
            Path("08120942-92"),
            "08120942-92",
            "92",
            datetime(2026, 8, 12, 9, 42),
            work_start=datetime(2026, 8, 12, 9, 42),
        )

        selected = classifier.choose_case(
            datetime(2026, 8, 12, 9, 44, 47),
            datetime(2026, 8, 12, 9, 49, 47),
            [previous, following],
            timedelta(minutes=30),
            timedelta(minutes=120),
            timedelta(minutes=15),
        )

        self.assertIs(selected, following)

    def test_work_log_classification_defaults_to_no_post_return_grace(self) -> None:
        classifier = self._classifier_module()
        with mock.patch.object(sys, "argv", ["classify_rescue_video.py"]):
            self.assertEqual(classifier.parse_args().return_grace_minutes, 0)

        with mock.patch.object(
            sys,
            "argv",
            ["classify_rescue_video.py", "--return-grace-minutes", "1"],
        ), redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            classifier.parse_args()

    def test_copy_reports_byte_progress_for_the_current_video(self) -> None:
        classifier = self._classifier_module()
        with TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "V0000001.TS"
            destination = Path(temp_dir) / "destination" / source.name
            source.write_bytes(b"0123456789")
            updates: list[tuple[int, int]] = []
            with mock.patch.object(classifier, "COPY_CHUNK_BYTES", 4):
                classifier.copy_preserving_time(
                    source,
                    destination,
                    progress_callback=lambda copied, total: updates.append((copied, total)),
                )
            self.assertEqual(destination.read_bytes(), b"0123456789")

        self.assertEqual(updates, [(4, 10), (8, 10), (10, 10)])

    def test_work_log_classification_uses_two_transfer_queues_for_distinct_case_folders(self) -> None:
        classifier = self._classifier_module()
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_root = root / "DCIM" / "100CAREC"
            source_root.mkdir(parents=True)
            destination_root = root / "cases"
            first_case = destination_root / "2026" / "8月" / "08150900-92" / "車"
            second_case = destination_root / "2026" / "8月" / "08151000-92" / "車"
            first_case.mkdir(parents=True)
            second_case.mkdir(parents=True)

            first_source = source_root / "V0000001.TS"
            second_source = source_root / "V0000002.TS"
            first_source.write_bytes(b"first video")
            second_source.write_bytes(b"second video")
            first_source.touch()
            second_source.touch()
            first_source_mtime = datetime(2026, 8, 15, 9, 0).timestamp()
            second_source_mtime = datetime(2026, 8, 15, 10, 0).timestamp()
            first_source.touch()
            second_source.touch()
            os.utime(first_source, (first_source_mtime, first_source_mtime))
            os.utime(second_source, (second_source_mtime, second_source_mtime))

            args = SimpleNamespace(
                date="2026-08-15",
                destination=destination_root,
                vehicle="92",
                source=source_root,
                extension=".TS",
                before_minutes=0,
                after_minutes=0,
                work_log_root=root / "work_logs",
                case_folder_tolerance_minutes=10,
                work_before_minutes=0,
                apply=True,
                repair_mismatch=False,
                delete_source=True,
                report=root / "report.csv",
            )

            active_transfers = 0
            maximum_active_transfers = 0
            transfer_lock = threading.Lock()
            transfer_barrier = threading.Barrier(2)
            transfer_states: list[tuple[str, str]] = []
            original_copy = classifier.copy_preserving_time

            def tracked_copy(source, destination, progress_callback=None):
                nonlocal active_transfers, maximum_active_transfers
                with transfer_lock:
                    active_transfers += 1
                    maximum_active_transfers = max(maximum_active_transfers, active_transfers)
                try:
                    transfer_barrier.wait(timeout=2)
                    return original_copy(source, destination, progress_callback)
                finally:
                    with transfer_lock:
                        active_transfers -= 1

            with (
                mock.patch.object(
                    classifier,
                    "read_card_duration",
                    return_value=(first_source, timedelta(seconds=0)),
                ),
                mock.patch.object(classifier, "discover_case_work", return_value=[]),
                mock.patch.object(classifier, "copy_preserving_time", side_effect=tracked_copy),
            ):
                results = classifier.classify_with_work_logs(
                    args,
                    transfer_workers=2,
                    transfer_callback=lambda source, _copied, _total, state: transfer_states.append(
                        (Path(source).name, state)
                    ),
                )
            first_destination_exists = (first_case / first_source.name).is_file()
            second_destination_exists = (second_case / second_source.name).is_file()

        self.assertEqual(
            [result.status for result in results],
            ["已複製並刪除來源", "已複製並刪除來源"],
        )
        self.assertGreaterEqual(maximum_active_transfers, 2)
        self.assertTrue(first_destination_exists)
        self.assertTrue(second_destination_exists)
        self.assertFalse(first_source.exists())
        self.assertFalse(second_source.exists())
        self.assertEqual(
            {name for name, state in transfer_states if state == "驗證完成"},
            {first_source.name, second_source.name},
        )

    def test_rescue_video_initial_state_explains_single_card_first_step_and_local_error(self) -> None:
        if str(PACKAGE_ROOT) not in sys.path:
            sys.path.insert(0, str(PACKAGE_ROOT))
        from app_core.rescue_video_service import RescueVideoCheckCard, RescueVideoDefaults
        from qt_app.controllers.rescue_video_controller import RescueVideoController

        controller = RescueVideoController(object())
        controller._defaults_loaded(
            0,
            RescueVideoDefaults(
                "",
                "destination",
                "2026-08-15",
                (),
                "",
                check_cards=(
                    RescueVideoCheckCard("source", "記憶卡來源", "來源尚未檢查", "error"),
                    RescueVideoCheckCard("vehicle_date", "車號與日期", "車號尚未檢查", "error"),
                ),
                is_ready=False,
            ),
        )

        self.assertEqual(controller.statusText, "尚未開始")
        self.assertIn("單張記憶卡", controller.summaryText)
        self.assertEqual(controller.checkCards[0]["stateText"], "尚未開始")
        self.assertTrue(controller.checkCards[0]["nextStep"])
        self.assertFalse(controller.checkCards[1]["nextStep"])
        self.assertIn("自動尋找 DCIM", controller.checkCards[0]["detail"])

        controller._set_error("請插入單張記憶卡後再檢查。")
        self.assertEqual(controller.errorText, "請插入單張記憶卡後再檢查。")

    def test_cross_day_video_interval_matches_both_dates(self) -> None:
        classifier = self._classifier_module()
        video_start = datetime(2026, 8, 8, 23, 57)
        video_end = datetime(2026, 8, 9, 0, 3)

        self.assertTrue(classifier.video_overlaps_selected_date(video_start, video_end, date(2026, 8, 8)))
        self.assertTrue(classifier.video_overlaps_selected_date(video_start, video_end, date(2026, 8, 9)))
        self.assertFalse(classifier.video_overlaps_selected_date(video_start, video_end, date(2026, 8, 10)))

    def test_vehicle_lookup_includes_previous_day_for_cross_day_case(self) -> None:
        classifier = self._classifier_module()
        with TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir)
            (destination / "2026" / "8月" / "08082350-93").mkdir(parents=True)

            vehicles = classifier.discover_vehicles(destination, date(2026, 8, 9))

        self.assertEqual(vehicles, ["93"])

    def test_result_table_displays_only_corrected_video_start_time(self) -> None:
        service = self._service_module()
        result = SimpleNamespace(
            source=Path("V0000001.TS"),
            adjusted_time=datetime(2026, 8, 9, 0, 3),
            video_start=datetime(2026, 8, 8, 23, 57),
            case=None,
            destination=None,
            status="預計複製",
            note="",
        )

        row = service.RescueVideoService._result_row(
            SimpleNamespace(status_tag=lambda _status: "normal"),
            result,
        )

        self.assertEqual(row["timeText"], "08/08 23:57:00")

    def test_transfer_status_moves_to_the_status_column(self) -> None:
        from qt_app.models.rescue_video_result_model import RescueVideoResultModel

        model = RescueVideoResultModel()
        model.replace_rows(
            (
                {
                    "sourcePath": "X:/DCIM/V0000001.TS",
                    "statusText": "預計複製",
                    "transferPercent": 0,
                    "transferText": "尚未傳輸",
                },
            )
        )
        index = model.index(0, 0)

        model.prepare_transfer()
        self.assertEqual(model.data(index, model.StatusTextRole), "等待傳輸")
        self.assertEqual(model.data(index, model.TransferPercentRole), 0)

        model.update_transfer("X:/DCIM/V0000001.TS", 51, 100, "傳輸中")
        self.assertEqual(model.data(index, model.StatusTextRole), "傳輸中")
        self.assertEqual(model.data(index, model.TransferPercentRole), 51)

    def test_date_or_vehicle_change_marks_check_cards_pending(self) -> None:
        if str(PACKAGE_ROOT) not in sys.path:
            sys.path.insert(0, str(PACKAGE_ROOT))
        from qt_app.controllers.rescue_video_controller import RescueVideoController

        controller = RescueVideoController(object())
        controller._check_cards = [
            {"key": "source", "title": "記憶卡來源", "detail": "來源可用", "level": "ok"},
            {"key": "vehicle_date", "title": "車號與日期", "detail": "案件可用", "level": "ok"},
        ]

        controller.updateInputs("F:/DCIM/100CAREC", "2026-08-08", "93")

        self.assertEqual([card["level"] for card in controller.checkCards], ["pending", "pending"])
        self.assertTrue(all("重新檢查" in card["detail"] for card in controller.checkCards))

    def test_closing_rescue_video_clears_prior_session(self) -> None:
        if str(PACKAGE_ROOT) not in sys.path:
            sys.path.insert(0, str(PACKAGE_ROOT))
        from qt_app.controllers.rescue_video_controller import RescueVideoController

        controller = RescueVideoController(object())
        controller._source_path = "F:/DCIM/100CAREC"
        controller._target_date = "2026-08-08"
        controller._selected_vehicle = "93"
        controller._check_cards = [
            {"key": "source", "title": "記憶卡來源", "detail": "可用", "level": "ok"},
        ]
        controller._is_ready = True
        controller._has_preview = True
        controller._result_model.replace_rows(
            ({"sourcePath": "F:/DCIM/100CAREC/V0000001.TS", "statusText": "已完成"},)
        )

        controller.resetForNextSession()

        self.assertEqual(controller.sourcePath, "")
        self.assertEqual(controller.targetDate, "")
        self.assertEqual(controller.selectedVehicle, "")
        self.assertEqual(controller.checkCards, [])
        self.assertFalse(controller.hasPreview)
        self.assertEqual(controller.statusText, "尚未開始")
        self.assertEqual(controller.resultModel.rowCount(), 0)

    def test_windows_notification_is_limited_to_completed_rescue_video_copy(self) -> None:
        source = (PACKAGE_ROOT / "qt_app" / "controllers" / "app_controller.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('lastCompletedMode in {"copy", "delete"}', source)
        self.assertIn('mode=mode,\n                notify=False,', source)


if __name__ == "__main__":
    unittest.main()
