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

    def test_update_package_rejects_version_mismatch(self) -> None:
        script = (PROJECT_ROOT / "WinPython_公務電腦使用包" / "update_package.ps1").read_text(encoding="utf-8-sig")
        self.assertIn('$packageVersionPath = Join-Path $sourceDir "VERSION.txt"', script)
        self.assertIn("Update version mismatch.", script)
        self.assertIn("$packageVersion | Set-Content", script)

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
