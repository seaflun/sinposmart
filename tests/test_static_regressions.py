import ast
from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_python(relative_path: str) -> ast.AST:
    return ast.parse((PROJECT_ROOT / relative_path).read_text(encoding="utf-8-sig"))


class StaticRegressionTests(unittest.TestCase):
    def test_submit_failure_callbacks_pass_trigger_type(self) -> None:
        for relative_path in self.duty_gui_paths():
            tree = parse_python(relative_path)
            method_arg_counts = self.method_arg_counts(tree, "_save_work_log_item_failed")
            self.assertEqual([5, 5], method_arg_counts, relative_path)

    def test_except_variables_are_not_captured_by_delayed_lambdas(self) -> None:
        for relative_path in self.automation_paths():
            tree = parse_python(relative_path)
            issues = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler) and node.name:
                    for inner in ast.walk(node):
                        if isinstance(inner, ast.Lambda) and self.lambda_uses_name_without_default(inner, node.name):
                            issues.append((inner.lineno, node.name))
            self.assertEqual([], issues, relative_path)

    def test_manual_and_due_completion_statuses_stay_distinct(self) -> None:
        for relative_path in self.duty_gui_paths():
            source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8-sig")
            self.assertIn('status = "已手動登打" if completion_key in self.manual_completed_keys else "已登打"', source)
            self.assertIn('compare_text = "已手動登打" if trigger_type == "manual" else "已登打"', source)
            self.assertIn("def restore_manual_completed_keys", source)
            self.assertIn('self.manual_completed_keys = self.restore_manual_completed_keys(self.duty_data["target_date"], self.duty_actions)', source)
            self.assertIn('self.log_trigger(index, self.duty_actions[index], "manual", status="manual_marked")', source)
            self.assertIn('self.log_trigger(index, action, trigger_type)', source)
            self.assertIn('self.log_trigger(index, self.duty_actions[index], trigger_type, status="submitted", completion_key=completion_key)', source)
            self.assertIn('self.log_trigger(index, self.duty_actions[index], trigger_type, status="skipped_duplicate", completion_key=completion_key)', source)
            self.assertIn('self.log_trigger(index, self.duty_actions[index], trigger_type, status="failed")', source)
            self.assertIn('if record.get("status") not in ("manual_marked", "submitted", "skipped_duplicate"):', source)
            self.assertIn('self.manual_completed_keys = self.restore_manual_completed_keys(data.get("target_date", ""), self.duty_actions)', source)
            self.assertIn('self.manual_completed_keys = self.restore_manual_completed_keys(today_data.get("target_date", ""), self.duty_actions)', source)
            self.assertIn("def should_count_as_next_duty_item", source)
            self.assertIn('elif pending_previous:', source)
            self.assertIn('self.next_task_text.set(f"前一班尚有 {pending_previous} 筆待手動處理")', source)
            self.assertIn("def set_duty_status", source)
            self.assertIn("def active_duty_status_override", source)
            self.assertIn('self.set_duty_status("值班段落結束 5 分鐘，已自動登出。", hold_seconds=10)', source)
            self.assertIn('elif status_override:', source)
            self.assertIn('self.set_duty_status(compare_text, hold_seconds=6)', source)
            self.assertIn('self.set_duty_status(f"登打失敗：{error}，結果：{result_path.name}{package_note}", hold_seconds=12)', source)
            self.assertIn('self.duty_status_text.set(self.active_duty_status_override() or "")', source)

    def test_near_compare_stays_manual_in_duty_mode(self) -> None:
        for relative_path in self.duty_gui_paths():
            source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8-sig")
            self.assertIn("def compare_needs_manual_review", source)
            self.assertIn('return compare.get("group") in ("near", "adjust", "review")', source)
            self.assertIn("def action_compare_sync_key", source)
            self.assertIn("def sync_duty_compare_from_audit", source)
            self.assertIn("def build_comparison(self, data: dict[str, Any], actions: list[dict[str, Any]] | None = None)", source)
            self.assertIn("actions = actions if actions is not None else self.build_audit_actions(data)", source)
            self.assertIn('comparison_staff = {**data.get("yesterday", {}).get("staff", {}), **data.get("today", {}).get("staff", {})}', source)
            self.assertIn("find_entry_matches(entry_rows, action_date, comparison_staff, action", source)
            self.assertIn("find_work_matches(work_rows, action_date, comparison_staff, action)", source)
            self.assertNotIn("dict(self.action_compare), self.duty_actions", source)
            self.assertGreaterEqual(source.count("self.build_comparison(self.duty_data, self.duty_actions)"), 3)
            self.assertIn("audit_compare_by_key", source)
            self.assertIn("self.action_compare_sync_key(action, audit_target_date)", source)
            self.assertIn("self.action_compare_sync_key(action, duty_target_date)", source)
            self.assertNotIn('self.data.get("target_date") != self.duty_data.get("target_date")', source)
            self.assertGreaterEqual(source.count("self.sync_duty_compare_from_audit()"), 2)
            self.assertIn("def resolve_duty_task_display", source)
            self.assertIn("status, tag, is_next_candidate = self.resolve_duty_task_display", source)
            self.assertIn('return ("到點待執行", "ready", True) if action_at <= now else ("等待", "waiting", is_auto_candidate)', source)
            self.assertIn('return compare.get("compare") or "人工確認", "manual", False', source)
            self.assertIn("if self.compare_needs_manual_review(compare):", source)
            self.assertIn('compare.get("group") == "manual" or self.compare_needs_manual_review(compare)', source)

    def test_manual_current_time_entry_uses_submit_date_override(self) -> None:
        for relative_path in self.duty_gui_paths():
            source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8-sig")
            self.assertIn('if action.get("submit_target_date"):', source)
            self.assertIn('return str(action["submit_target_date"])', source)
            self.assertIn("current_now = datetime.now()", source)
            self.assertIn('updated["submit_target_date"] = roc_date(current_now.date())', source)

    def test_due_tasks_catch_up_after_exact_minute(self) -> None:
        for relative_path in self.duty_gui_paths():
            source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8-sig")
            self.assertIn("is_due_now = action_at <= now", source)
            self.assertNotIn("action_at.hour == now.hour and action_at.minute == now.minute", source)

    def test_public_computer_runtime_logs_mirror_to_cloud(self) -> None:
        for relative_path in self.duty_gui_paths():
            source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8-sig")
            self.assertIn('CLOUD_LOG_DIR_NAME = "public_computer_logs"', source)
            self.assertIn("def cloud_runtime_log_root", source)
            self.assertIn("def mirror_runtime_file_to_cloud", source)
            self.assertIn("def append_runtime_jsonl_to_cloud", source)
            self.assertIn('mirror_runtime_file_to_cloud(result_path, "form_tests")', source)
            self.assertIn('append_runtime_jsonl_to_cloud("duty_trigger_log.jsonl", line)', source)

    def test_update_package_rejects_version_mismatch(self) -> None:
        script = (PROJECT_ROOT / "WinPython_公務電腦使用包" / "update_package.ps1").read_text(encoding="utf-8-sig")
        self.assertIn('$packageVersionPath = Join-Path $sourceDir "VERSION.txt"', script)
        self.assertIn("Update version mismatch.", script)
        self.assertIn("$packageVersion | Set-Content", script)

    def test_update_package_does_not_downgrade(self) -> None:
        script = (PROJECT_ROOT / "WinPython_公務電腦使用包" / "update_package.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("[string]::CompareOrdinal($remoteVersion, $localVersion) -le 0", script)

    def test_update_package_validates_version_text(self) -> None:
        script = (PROJECT_ROOT / "WinPython_公務電腦使用包" / "update_package.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("function Test-VersionText", script)
        self.assertIn("^\\d{4}\\.\\d{2}\\.\\d{2}\\.\\d{4}$", script)
        self.assertIn("Remote VERSION.txt has an invalid version", script)
        self.assertIn("Update zip VERSION.txt has an invalid version", script)
        self.assertIn("$localVersionPath -Raw -Encoding UTF8).Trim().TrimStart([char]0xFEFF)", script)

    def test_update_package_verifies_download_sha256(self) -> None:
        script = (PROJECT_ROOT / "WinPython_公務電腦使用包" / "update_package.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("$remoteSha256Url", script)
        self.assertIn("function Get-Sha256FromText", script)
        self.assertIn("[0-9a-fA-F]{64}", script)
        self.assertIn("Get-FileHash -LiteralPath $zipPath -Algorithm SHA256", script)
        self.assertIn("Downloaded package SHA256 mismatch", script)

    def test_update_package_never_copies_sensitive_local_files(self) -> None:
        script = (PROJECT_ROOT / "WinPython_公務電腦使用包" / "update_package.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("$alwaysSkipFiles = @(", script)
        self.assertIn('"duty_sheet_legacy\\config.json"', script)
        self.assertIn('"duty_sheet_legacy\\effortless-leaf-353501-63492cc3ece4.json"', script)
        self.assertIn('"daily_vehicle_legacy\\.env"', script)
        self.assertIn("if ($alwaysSkipFiles -contains $relative)", script)

    def test_update_package_cleans_temporary_downloads(self) -> None:
        script = (PROJECT_ROOT / "WinPython_公務電腦使用包" / "update_package.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("try {", script)
        self.assertIn("} finally {", script)
        self.assertIn("Remove-Item -LiteralPath $tempDir -Recurse -Force", script)
        self.assertIn("Could not remove temporary update folder", script)

    def test_update_package_backups_stay_out_of_synced_project_folder(self) -> None:
        script = (PROJECT_ROOT / "WinPython_公務電腦使用包" / "update_package.ps1").read_text(encoding="utf-8-sig")
        self.assertIn('$backupRoot = Join-Path $env:LOCALAPPDATA "SinpoSmart"', script)
        self.assertIn('$backupDir = Join-Path $backupRoot "update_backups"', script)
        self.assertNotIn('Join-Path $parentDir "_update_backups"', script)

    def test_no_console_launcher_uses_batch_python_detection(self) -> None:
        script = (PROJECT_ROOT / "start_duty_gui_no_console.vbs").read_text(encoding="utf-8-sig")
        self.assertIn("start_duty_gui.bat", script)
        self.assertNotIn("pythonw.exe", script.lower())

    def test_startup_shortcuts_use_no_console_launchers(self) -> None:
        for relative_path in ("install_startup_shortcut.ps1", "WinPython_公務電腦使用包/install_startup_shortcut.ps1"):
            script = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8-sig")
            self.assertIn("System32\\wscript.exe", script)
            self.assertIn("RUN_DUTY_GUI_WINPYTHON.vbs", script)
            self.assertNotIn("C:\\Users\\User", script)
            self.assertNotIn('$shortcut.TargetPath = $pythonw', script)
            self.assertLess(script.index("start_duty_gui_no_console.vbs"), script.index("RUN_DUTY_GUI_WINPYTHON.vbs"))

    def test_duty_sheet_screenshot_fits_summary_cells(self) -> None:
        for relative_path in ("duty_sheet_legacy/sinposmart_1.py", "WinPython_公務電腦使用包/duty_sheet_legacy/sinposmart_1.py"):
            source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8-sig")
            self.assertIn("def fit_summary_cells_for_screenshot", source)
            self.assertIn('"月補"', source)
            self.assertIn("summary_range.ShrinkToFit = True", source)
            self.assertIn('value_cell.NumberFormat = "@"', source)
            self.assertIn("value_cell.Value = str(original_value)", source)
            self.assertIn("fit_summary_cells_for_screenshot(worksheet, sheet_values, min_col, min_row, max_col, max_row)", source)
            self.assertIn("def copy_range_picture_with_retry", source)
            self.assertIn("copy_range_picture_with_retry(export_range)", source)
            self.assertIn("export_range.Width + 8", source)
            self.assertIn("def export_chart_to_png", source)
            self.assertIn("tempfile.gettempdir()", source)
            self.assertIn("export_chart_to_png(chart, output_path)", source)
            self.assertIn('upload_stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")', source)
            self.assertIn('{upload_stamp}_{Path(image_path).name}', source)

    @staticmethod
    def method_arg_counts(tree: ast.AST, method_name: str) -> list[int]:
        counts = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == method_name:
                counts.append(len(node.args))
        return sorted(counts)

    @staticmethod
    def lambda_uses_name_without_default(node: ast.Lambda, name: str) -> bool:
        body_names = {inner.id for inner in ast.walk(node.body) if isinstance(inner, ast.Name)}
        default_names = {
            inner.id
            for default in node.args.defaults
            for inner in ast.walk(default)
            if isinstance(inner, ast.Name)
        }
        return name in body_names and name not in default_names

    @staticmethod
    def duty_gui_paths() -> list[str]:
        paths = ["duty_gui.py"]
        paths.extend(str(path.relative_to(PROJECT_ROOT)) for path in PROJECT_ROOT.glob("WinPython_*/duty_gui.py"))
        return paths

    @classmethod
    def automation_paths(cls) -> list[str]:
        paths = [
            "daily_vehicle_automation.py",
            "duty_sheet_automation.py",
            "rest_time_automation.py",
        ]
        paths.extend(str(path.relative_to(PROJECT_ROOT)) for path in PROJECT_ROOT.glob("WinPython_*/*_automation.py"))
        paths.extend(cls.duty_gui_paths())
        return paths


if __name__ == "__main__":
    unittest.main()
