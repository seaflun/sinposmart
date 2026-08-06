from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "WinPython_公務電腦使用包"

class RescueVideoPackageTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
