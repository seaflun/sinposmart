from __future__ import annotations

import ast
import importlib
import json
import subprocess
import sys
import tempfile
import unittest
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def package_dir() -> Path:
    candidates = [path for path in PROJECT_ROOT.iterdir() if path.is_dir() and path.name.startswith("WinPython_")]
    if len(candidates) != 1:
        raise AssertionError(f"expected one WinPython package directory, found {len(candidates)}")
    return candidates[0]


def rest_time_module():
    root = package_dir()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return importlib.import_module("rest_time_automation")


def duty_rehearsal_module():
    root = package_dir()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return importlib.import_module("duty_rehearsal")


def duty_gui_module():
    root = package_dir()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return importlib.import_module("duty_gui")


def package_module(name: str):
    root = package_dir()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return importlib.import_module(name)


class PackageSmokeTests(unittest.TestCase):
    def test_package_entry_files_exist(self) -> None:
        root = package_dir()

        for relative in (
            "requirements.txt",
            "duty_gui.pyw",
            "duty_gui.py",
            "RUN_DUTY_GUI_WINPYTHON.bat",
            "update_package.ps1",
        ):
            with self.subTest(relative=relative):
                self.assertTrue((root / relative).is_file())

    def test_python_sources_compile(self) -> None:
        root = package_dir()
        sources = sorted(list(root.rglob("*.py")) + list(root.rglob("*.pyw")))

        self.assertGreaterEqual(len(sources), 8)
        for path in sources:
            if "__pycache__" in path.parts:
                continue
            with self.subTest(path=str(path.relative_to(PROJECT_ROOT))):
                source = path.read_text(encoding="utf-8-sig")
                compile(source, str(path), "exec")

    def test_update_package_excludes_sensitive_and_runtime_files(self) -> None:
        script = (package_dir() / "update_package.ps1").read_text(encoding="utf-8-sig")

        for expected in (
            '".env"',
            '".jsonl"',
            '"logs"',
            '"runtime_outputs"',
            '".zip"',
            '".token"',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, script)

    def test_sinposmart_events_include_installed_version(self) -> None:
        source = (package_dir() / "duty_gui.py").read_text(encoding="utf-8-sig")

        self.assertIn("def current_app_version(", source)
        self.assertIn("snapshot_data = sanitize_frontend_json(dict(snapshot or {}))", source)
        self.assertIn('snapshot_data.setdefault("app_version", current_app_version())', source)
        self.assertIn('"snapshot": snapshot_data', source)

    def test_sinposmart_backend_event_call_keywords_match_signature(self) -> None:
        source = (package_dir() / "duty_gui.py").read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        signature_keywords: set[str] = set()
        call_keywords: set[str] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "send_sinposmart_backend_event":
                signature_keywords = {arg.arg for arg in node.args.args[2:]}
                signature_keywords.update(arg.arg for arg in node.args.kwonlyargs)
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "send_sinposmart_backend_event":
                call_keywords.update(keyword.arg for keyword in node.keywords if keyword.arg)

        self.assertIn("send_sinposmart_backend_event", source)
        self.assertFalse(call_keywords - signature_keywords)

    def test_frontend_error_payload_sanitizes_selenium_and_sensitive_details(self) -> None:
        module = duty_gui_module()
        from selenium.common.exceptions import NoSuchElementException, TimeoutException

        cases = (
            (
                TimeoutException("Timed out receiving message from renderer\nStacktrace:\nChromeDriver"),
                "timeout",
                "網頁等待逾時：勤務系統可能登入失敗、網頁變慢，或頁面結構已變更。",
            ),
            (
                NoSuchElementException("no such element: Unable to locate element\nStacktrace:\nChromeDriver"),
                "no_such_element",
                "找不到網頁元素：可能勤務系統頁面改版，或尚未成功登入。",
            ),
            (
                RuntimeError("仍停留在 login119，找不到 _txtUsername 以外的登入後元素"),
                "login_failed",
                "登入失敗：帳號或密碼可能已變更，請登出後重新登入系統。",
            ),
            (
                RuntimeError("帳號密碼有誤或尚未申請帳號權限,請確認後再重新登入"),
                "login_failed",
                "登入失敗：帳號或密碼可能已變更，請登出後重新登入系統。",
            ),
            (
                RuntimeError("unexpected failure\ntraceback\nsession token abc\ncookie xyz\npassword secret\nChromeDriver"),
                "unknown_error",
                "執行失敗：系統發生未預期錯誤，請查看後端日誌。",
            ),
        )

        for exc, error_code, message in cases:
            with self.subTest(error_code=error_code):
                payload = module.frontend_error_payload(exc)
                self.assertEqual(payload["error_code"], error_code)
                self.assertEqual(payload["message"], message)
                self.assertRegex(payload["timestamp"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
                rendered = json.dumps(payload, ensure_ascii=False).lower()
                for forbidden in ("stacktrace", "traceback", "chromedriver", "cookie", "session token", "password secret"):
                    self.assertNotIn(forbidden, rendered)

    def test_automation_failure_result_uses_safe_error_fields(self) -> None:
        module = duty_gui_module()
        error = RuntimeError("raw traceback\nChromeDriver\ncookie=abc\nsession token=def\npassword secret")
        result = module.automation_failure_result(
            error,
            action_index=3,
            action={"kind": "work_log", "password": "secret", "headers": {"Cookie": "abc"}},
            save=True,
            visible=False,
        )

        self.assertEqual(result["stage"], "failed")
        self.assertEqual(result["error_code"], "unknown_error")
        self.assertEqual(result["message"], "執行失敗：系統發生未預期錯誤，請查看後端日誌。")
        self.assertIn("timestamp", result)
        rendered = json.dumps(result, ensure_ascii=False).lower()
        for forbidden in ("stacktrace", "traceback", "chromedriver", "cookie", "session token", "password secret"):
            self.assertNotIn(forbidden, rendered)

    def test_tool_dialog_error_formatters_hide_selenium_details(self) -> None:
        expected = {
            "TimeoutException: timed out receiving message from renderer\nStacktrace:\nChromeDriver": "網頁等待逾時：勤務系統可能登入失敗、網頁變慢，或頁面結構已變更。",
            "NoSuchElementException: no such element: Unable to locate element\nStacktrace:\nChromeDriver": "找不到網頁元素：可能勤務系統頁面改版，或尚未成功登入。",
            "仍停留在 login119，找不到 _txtUsername 以外的登入後元素": "登入失敗：帳號或密碼可能已變更，請登出後重新登入系統。",
            "帳號密碼有誤或尚未申請帳號權限,請確認後再重新登入": "登入失敗：帳號或密碼可能已變更，請登出後重新登入系統。",
            "Traceback\nChromeDriver\ncookie=abc\nsession token=def\npassword secret": "執行失敗：系統發生未預期錯誤，請查看後端日誌。",
        }

        for module_name in ("duty_sheet_automation", "rest_time_automation", "daily_vehicle_automation"):
            module = package_module(module_name)
            for raw, safe in expected.items():
                with self.subTest(module=module_name, safe=safe):
                    self.assertEqual(module.format_automation_error(RuntimeError(raw)), safe)

    def test_four_tool_entries_register_sinposmart_callbacks(self) -> None:
        source = (package_dir() / "duty_gui.py").read_text(encoding="utf-8-sig")

        for tool_name in ("duty_sheet", "rest_time", "monthly_base", "daily_vehicle"):
            with self.subTest(tool_name=tool_name):
                self.assertIn(f'self.sinposmart_tool_event_callbacks("{tool_name}"', source)
        for callback_name in ("on_start=on_start", "on_finish=on_finish", "on_error=on_error"):
            with self.subTest(callback_name=callback_name):
                self.assertGreaterEqual(source.count(callback_name), 4)

    def test_rest_and_monthly_base_dialogs_use_fixed_year_and_three_month_combo(self) -> None:
        source = (package_dir() / "rest_time_automation.py").read_text(encoding="utf-8-sig")

        self.assertIn("month_var", source)
        self.assertIn("nearby_month_options", source)
        self.assertIn("CTK_COMBO_STYLE", source)
        self.assertIn("ctk.CTkComboBox", source)
        self.assertNotIn("ctk.CTkOptionMenu", source)
        self.assertNotIn("year_var", source)
        self.assertIn("selected_year_month", source)
        self.assertIn("expected_roc_year", source)
        self.assertIn("expected_month", source)

        module = rest_time_module()
        self.assertEqual(module.nearby_month_options(6), ["05", "06", "07"])
        self.assertEqual(module.nearby_month_options(12), ["11", "12", "01"])

    def test_rest_time_rejects_workbook_month_mismatch(self) -> None:
        module = rest_time_module()
        workbook = module.openpyxl.Workbook()
        sheet = workbook.active
        sheet.cell(row=2, column=4).value = 115
        sheet.cell(row=2, column=5).value = 7
        sheet.cell(row=2, column=7).value = 31

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "rest.xlsx"
            workbook.save(path)

            with self.assertRaisesRegex(RuntimeError, "Excel.*115年07月"):
                module.validate_workbook_year_month(path, 115, 6)

    def test_monthly_base_rejects_selected_month_mismatch(self) -> None:
        module = rest_time_module()

        with self.assertRaisesRegex(RuntimeError, "勤務基準表.*115年07月"):
            module.validate_selected_year_month("勤務基準表", 115, 6, 115, 7)

    def test_base_month_text_can_detect_site_month_mismatch(self) -> None:
        module = rest_time_module()

        self.assertEqual(module.extract_base_month_from_text("目前編輯月份為: 115年07月"), (115, 7))
        with self.assertRaisesRegex(RuntimeError, "網站.*115年07月"):
            module.validate_selected_year_month("網站", 115, 6, 115, 7)

    def test_monthly_base_fill_clears_existing_values_before_rewrite(self) -> None:
        source = (package_dir() / "rest_time_automation.py").read_text(encoding="utf-8-sig")

        self.assertIn("function clearRowValues(row, days)", source)
        self.assertIn("function dayPlanControls(row, days)", source)
        self.assertIn("Number(match[2]) >= 1", source)
        self.assertIn("el.value = ''", source)
        self.assertLess(source.index("clearRowValues(row, Object.keys(data).length)"), source.index("return setRowValues(row, data)"))

    def test_update_logout_command_reports_logout_synchronously(self) -> None:
        source = (package_dir() / "duty_gui.py").read_text(encoding="utf-8-sig")

        self.assertIn('elif message == "update_logout":', source)
        self.assertIn("def report_update_logout(self) -> bool:", source)
        self.assertIn("def update_logout_identity(self)", source)
        self.assertIn("last_update_logout_identity", source)
        self.assertIn('"logout"', source)
        self.assertIn('trigger_type="update"', source)
        self.assertIn("immediate=True", source)

    def test_sinposmart_event_worker_persists_pending_before_posting(self) -> None:
        source = (package_dir() / "duty_gui.py").read_text(encoding="utf-8-sig")

        self.assertLess(
            source.index("write_pending_sinposmart_backend_events(pending)"),
            source.index("response = post_sinposmart_backend_event(entry)"),
        )

    def test_next_morning_0600_rest_includes_manual_return_at_0800(self) -> None:
        module = duty_rehearsal_module()
        today = module.DutySheet(
            roc_date="1150621",
            rows=[
                module.DutyRow("06-08", {"值班": ["28"], "休息": ["16"]}),
                module.DutyRow("08-10", {"值班": ["12"], "休息": []}),
                module.DutyRow("22-24", {"值班": ["28"], "休息": []}),
            ],
            summary={"在勤": ["16", "28"]},
        )
        yesterday = module.DutySheet(roc_date="1150620", summary={"在勤": ["28"]})
        tomorrow = module.DutySheet(roc_date="1150622", summary={"在勤": ["16", "28"]})

        actions = module.planned_actions(today, yesterday, [], module.parse_roc_date("1150621"), [], tomorrow)
        rest_actions = [
            action
            for action in actions
            if action.kind == "entry_log" and action.target == "16" and action.fields.get("領用事由及地點") in ("休息", "休息返隊")
        ]

        self.assertEqual(
            [(action.time, action.actor, action.fields["出或入"], action.fields["領用事由及地點"], action.date_offset) for action in rest_actions],
            [("06:00", "28", "出", "休息", 1), ("08:00", "28", "入", "休息返隊", 1)],
        )

    def test_update_package_requests_logout_before_stopping_gui(self) -> None:
        script = (package_dir() / "update_package.ps1").read_text(encoding="utf-8-sig")

        self.assertIn("function Send-UpdateLogoutEvent", script)
        self.assertIn("update_logout", script)
        self.assertLess(script.index("Send-UpdateLogoutEvent"), script.index("$wasRunning = Stop-RunningDutyGui"))

    def test_powershell_scripts_parse(self) -> None:
        root = package_dir()
        scripts = [
            root / "find_winpython.ps1",
            root / "install_startup_shortcut.ps1",
            root / "remove_startup_shortcut.ps1",
            root / "update_package.ps1",
        ]
        parser = (
            "$path = $env:PS_PARSE_PATH; "
            "$tokens = $null; $errors = $null; "
            "[System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors) | Out-Null; "
            "if ($errors.Count) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
        )

        for script in scripts:
            with self.subTest(script=str(script.relative_to(PROJECT_ROOT))):
                env = os.environ.copy()
                env["PS_PARSE_PATH"] = str(script)
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", parser],
                    cwd=PROJECT_ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
