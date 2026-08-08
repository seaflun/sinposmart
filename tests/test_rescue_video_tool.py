from __future__ import annotations

import sys
import unittest
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
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

    def test_daily_tools_include_rescue_video_as_third_action(self) -> None:
        source = (
            PACKAGE_ROOT / "qt_app" / "qml" / "pages" / "DutyQuickToolsPanel.qml"
        ).read_text(encoding="utf-8")
        daily_tools = source.split('text: "每日作業"', 1)[1].split(
            'text: "每月作業"', 1
        )[0]

        self.assertLess(daily_tools.index('text: "勤務表登打"'), daily_tools.index('text: "車輛保養清點"'))
        self.assertLess(daily_tools.index('text: "車輛保養清點"'), daily_tools.index('text: "行車紀錄器"'))
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


if __name__ == "__main__":
    unittest.main()
