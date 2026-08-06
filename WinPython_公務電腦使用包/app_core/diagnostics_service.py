# -*- coding: utf-8 -*-
"""Create an allowlisted SinpoSmart diagnostic package without credentials."""

from __future__ import annotations

import json
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


class DiagnosticExportError(RuntimeError):
    """Safe diagnostic-export failure suitable for operator display."""


@dataclass(frozen=True)
class DiagnosticSnapshot:
    mode: str = "PySide6/QML"
    login_status: str = ""
    duty_status: str = ""
    target_date: str = ""
    session_actor: str = ""
    session_verified: bool = False


class DiagnosticsService:
    def __init__(self, package_root: Path) -> None:
        self.package_root = Path(package_root)

    def export(self, snapshot: DiagnosticSnapshot) -> Path:
        issue_dir = self.package_root / "issue_reports"
        try:
            issue_dir.mkdir(parents=True, exist_ok=True)
            package_path = issue_dir / f"issue_report_{datetime.now():%Y%m%d_%H%M%S_%f}.zip"
            manifest = {
                "created_at": datetime.now().isoformat(timespec="seconds"),
                **asdict(snapshot),
            }
            with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
                for path in self._candidate_files(snapshot.target_date):
                    archive.write(path, arcname=path.relative_to(self.package_root).as_posix())
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            raise DiagnosticExportError(f"無法建立問題包：{exc}") from exc
        return package_path

    def _candidate_files(self, target_date: str) -> list[Path]:
        candidates = [
            self.package_root / "duty_trigger_log.jsonl",
            self.package_root / "requirements.txt",
            self.package_root / "VERSION.txt",
            self.package_root / "docs" / "CODE_MAP.md",
            self.package_root / "docs" / "HANDOFF.md",
        ]
        normalized_date = "".join(ch for ch in str(target_date or "") if ch.isdigit())
        if len(normalized_date) == 7:
            candidates.extend(
                [
                    self.package_root / "runtime_outputs" / "schedule" / f"schedule_output_{normalized_date}.json",
                    self.package_root / "runtime_outputs" / "comparison" / f"comparison_output_{normalized_date}.json",
                    self.package_root / "duty_sheet_legacy" / "runtime_outputs" / "schedule" / f"schedule_output_{normalized_date}.json",
                    self.package_root / "duty_sheet_legacy" / "runtime_outputs" / "comparison" / f"comparison_output_{normalized_date}.json",
                ]
            )
        candidates.extend(self._recent_files("runtime_outputs/form_tests", ("*.json",), 20))
        candidates.extend(self._recent_files("runtime_outputs/snapshots", ("*.json", "*.txt"), 30))
        candidates.extend(self._recent_files("runtime_outputs/browser", ("*.jsonl",), 5))

        seen: set[Path] = set()
        allowed: list[Path] = []
        package_root = self.package_root.resolve()
        for candidate in candidates:
            if not candidate.is_file():
                continue
            resolved = candidate.resolve()
            if resolved in seen or package_root not in resolved.parents:
                continue
            seen.add(resolved)
            allowed.append(resolved)
        return allowed

    def _recent_files(self, relative_folder: str, patterns: tuple[str, ...], limit: int) -> list[Path]:
        folder = self.package_root / relative_folder
        if not folder.is_dir():
            return []
        files: list[Path] = []
        for pattern in patterns:
            files.extend(folder.glob(pattern))
        return sorted(files, key=lambda path: path.stat().st_mtime)[-limit:]
