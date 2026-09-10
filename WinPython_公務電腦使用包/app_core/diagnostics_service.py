# -*- coding: utf-8 -*-
"""Create an allowlisted SinpoSmart diagnostic package without credentials."""

from __future__ import annotations

import json
import os
import stat
import time
import tempfile
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

    def cleanup_retained_files(self, *, now: float | None = None, backup_dir: Path | None = None) -> None:
        """Remove only expired output files; preserve references in live state."""
        cutoff = (time.time() if now is None else now) - 30 * 86400
        root = self.package_root.resolve()

        def owned(path: Path, boundary: Path) -> bool:
            try:
                if not path.resolve().is_relative_to(boundary.resolve()):
                    return False
                for part in (path, *path.parents):
                    info = part.lstat()
                    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 1024:
                        return False
                    if part == boundary:
                        break
                return path.is_file()
            except OSError:
                return False

        references: set[str] = set()
        def collect(value):
            if isinstance(value, dict):
                for item in value.values():
                    collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)
            elif isinstance(value, str):
                references.add(value.replace('\\', '/').rsplit('/', 1)[-1])

        runtime_roots = [root / 'runtime_outputs', root / 'duty_sheet_legacy/runtime_outputs']
        try:
            for runtime in runtime_roots:
                for path in runtime.glob('*.json*'):
                    if not owned(path, root):
                        continue
                    if path.suffix == '.jsonl':
                        with path.open(encoding='utf-8-sig') as handle:
                            for line in handle:
                                if line.strip():
                                    collect(json.loads(line))
                    elif path.suffix == '.json':
                        collect(json.loads(path.read_text(encoding='utf-8-sig')))
        except (OSError, ValueError):
            # Unreadable live state must never cause loss of referenced output.
            return

        folders = [(runtime / name, extensions) for runtime in runtime_roots
                   for name, extensions in [('form_tests', {'.json'}), ('snapshots', {'.json', '.txt'}),
                                             ('schedule', {'.json'}), ('comparison', {'.json'}),
                                             ('browser', {'.json', '.jsonl'})]]
        folders += [(base / name, {'.png'}) for base in (root, root / 'duty_sheet_legacy')
                    for name in ('screenshots', '每日勤務表', '夜間勤務', '夜間勤務表')]
        for runtime in runtime_roots:
            legacy_log = runtime / 'browser/browser_startup.jsonl'
            if not owned(legacy_log, root):
                continue
            temporary = None
            try:
                before = legacy_log.stat()
                changed = False
                with legacy_log.open(encoding='utf-8') as source, tempfile.NamedTemporaryFile(
                    mode='w', encoding='utf-8', dir=legacy_log.parent, suffix='.tmp', delete=False
                ) as output:
                    temporary = Path(output.name)
                    for line in source:
                        try:
                            stamp = datetime.fromisoformat(json.loads(line)['timestamp']).timestamp()
                        except (ValueError, KeyError, TypeError):
                            stamp = cutoff  # Preserve entries whose age cannot be established.
                        if stamp < cutoff:
                            changed = True
                        else:
                            output.write(line)
                after = legacy_log.stat()
                if changed and (before.st_mtime_ns, before.st_size) == (after.st_mtime_ns, after.st_size):
                    temporary.replace(legacy_log)
            except (OSError, UnicodeError):
                pass
            finally:
                if temporary is not None:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        pass

        for folder, extensions in folders:
            for current, directories, files in os.walk(folder, followlinks=False):
                safe_directories = []
                for name in directories:
                    try:
                        child = Path(current) / name
                        if not child.is_symlink() and not getattr(child.lstat(), 'st_file_attributes', 0) & 1024:
                            safe_directories.append(name)
                    except OSError:
                        pass
                directories[:] = safe_directories
                for name in files:
                    path = Path(current) / name
                    if name == 'browser_startup.jsonl' or path.suffix.lower() not in extensions or not owned(path, root):
                        continue
                    if name in references or any(ref and ref in name for ref in references if len(ref) == 7 and ref.isdigit()):
                        continue
                    try:
                        if path.stat().st_mtime < cutoff:
                            path.unlink()
                    except OSError:
                        pass  # Locked files can be retried on the next run.

        backups = backup_dir or Path(os.environ.get('LOCALAPPDATA') or '') / 'SinpoSmart/update_backups'
        if backup_dir is None and not os.environ.get('LOCALAPPDATA'):
            return
        candidates = [path for path in backups.glob('SinpoSmart-package-backup-*.zip') if owned(path, backups)]
        try:
            candidates.sort(key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
            for path in candidates[1:]:
                try:
                    path.unlink()
                except OSError:
                    pass
        except OSError:
            pass

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
            self.package_root / "runtime_outputs" / "sinposmart_operational_sync_status.json",
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
