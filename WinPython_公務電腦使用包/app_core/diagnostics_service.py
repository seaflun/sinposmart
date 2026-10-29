# -*- coding: utf-8 -*-
"""Create an allowlisted SinpoSmart diagnostic package without credentials."""

from __future__ import annotations

import json
import os
import re
import socket
import stat
import time
import tempfile
import traceback
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote, urlsplit, urlunsplit


MAX_DIAGNOSTIC_ARCHIVE_BYTES = 8 * 1024 * 1024
MAX_DIAGNOSTIC_CONTENT_BYTES = 16 * 1024 * 1024
MAX_DIAGNOSTIC_FILE_BYTES = 2 * 1024 * 1024
_SENSITIVE_KEYS = re.compile(r"password|passwd|pwd|token|secret|cookie|authorization|credential|session[ _-]?id|(?:api|sync)[_-]?key|username|user_id|account|csrf|^sid$|密碼|密码|權杖", re.I)
_SENSITIVE_TEXT = re.compile(
    r'''(?i)(password|passwd|pwd|token|secret|cookie|authorization|credential|session[ _-]?id|(?:api|sync)[_-]?key|username|user_id|account|csrf|密碼|密码|權杖)["']?\s*[:=：]\s*(?:(?:Bearer|Basic)\s+)?(?:"[^"\r\n]*"|'[^'\r\n]*'|[^,;\r\n，；]+)'''
)
_URL = re.compile(r'''(?:https?|wss?)://[^\s<>"']+''', re.I)


def redact_diagnostic_text(value: str, secrets: tuple[str, ...] = ()) -> str:
    """Keep actionable errors without saved credentials, headers or URL parameters."""
    text = str(value)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[已遮蔽]").replace(quote(secret, safe=""), "[已遮蔽]")
    text = re.sub(r"(?im)\b(?:set-cookie|cookie|authorization|proxy-authorization)\s*:\s*[^\r\n]+", "[認證標頭已遮蔽]", text)
    text = _SENSITIVE_TEXT.sub(lambda match: match.group(1) + "=[已遮蔽]", text)
    def public_url(match):
        try:
            parts = urlsplit(match.group(0))
            host = parts.hostname or ""
            host = f"[{host}]" if ":" in host else host
            authority = host + (f":{parts.port}" if parts.port is not None else "")
            return urlunsplit((parts.scheme, authority, parts.path, "", ""))
        except ValueError:
            return "[網址已遮蔽]"
    return _URL.sub(public_url, text)


def sanitize_diagnostic_value(value: Any, secrets: tuple[str, ...] = ()) -> Any:
    if isinstance(value, Mapping):
        if "value" in value and any(_SENSITIVE_KEYS.search(str(value.get(key, ""))) for key in ("name", "id", "field", "label", "type")):
            return {"redacted": True}
        return {str(key): sanitize_diagnostic_value(item, secrets) for key, item in value.items()
                if not _SENSITIVE_KEYS.search(str(key))
                and not re.search(r"html|page_source|screenshot|(?:^|_)image(?:_|$)", str(key), re.I)}
    if isinstance(value, (list, tuple)):
        return [sanitize_diagnostic_value(item, secrets) for item in value]
    if isinstance(value, str):
        if re.search(r"<(?:!doctype|html|input|script|form)\b", value, re.I):
            return "[HTML 已略過]"
        return redact_diagnostic_text(value, secrets)
    return value


def diagnostic_exception(error: BaseException, secrets: tuple[str, ...] = ()) -> dict[str, Any]:
    result = {"type": type(error).__name__, "message": redact_diagnostic_text(str(error), secrets)[:2000],
              "frames": [{"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                         for frame in traceback.extract_tb(error.__traceback__)[-12:]]}
    cause = error.__cause__
    if type(getattr(error, "code", None)) is int:
        result["http_status"] = error.code
    if cause is not None and cause is not error:
        result["cause"] = {"type": type(cause).__name__, "message": redact_diagnostic_text(str(cause), secrets)[:2000]}
    return result


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
    action_key: str = ""
    action_kind: str = ""
    trigger_type: str = ""
    error_code: str = ""
    result_ref: str = ""


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

    def export(self, snapshot: DiagnosticSnapshot, *, secrets: tuple[str, ...] = ()) -> Path:
        issue_dir = self.package_root / "issue_reports"
        secrets = tuple(value for value in (*secrets,
            os.environ.get("SINPOSMART_CREDENTIAL_SYNC_TOKEN", ""),
            os.environ.get("SINPOSMART_DUTY_BOARD_SYNC_KEY", "")) if value)
        try:
            issue_dir.mkdir(parents=True, exist_ok=True)
            package_path = issue_dir / f"issue_report_{datetime.now():%Y%m%d_%H%M%S_%f}.zip"
            manifest = {
                "schema_version": 1,
                "sanitized": True,
                "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "workstation": re.sub(r"[^A-Za-z0-9_.-]", "-", socket.gethostname())[:64],
                **asdict(snapshot),
            }
            omitted = []
            total = 0
            with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                candidates = self._candidate_files(snapshot.target_date)
                if snapshot.result_ref and Path(snapshot.result_ref).name == snapshot.result_ref:
                    primary = self.package_root / "runtime_outputs" / "form_tests" / snapshot.result_ref
                    if primary.is_file() and primary.resolve().is_relative_to(self.package_root.resolve()):
                        candidates = [primary.resolve(), *candidates]
                seen = set()
                for path in candidates:
                    name = path.relative_to(self.package_root.resolve()).as_posix()
                    if name in seen:
                        continue
                    seen.add(name)
                    try:
                        if path.stat().st_size > MAX_DIAGNOSTIC_FILE_BYTES:
                            raise ValueError("file_too_large")
                        text = path.read_text(encoding="utf-8-sig")
                        if path.suffix == ".json":
                            text = json.dumps(sanitize_diagnostic_value(json.loads(text), secrets), ensure_ascii=False, indent=2)
                        elif path.suffix == ".jsonl":
                            text = "".join(json.dumps(sanitize_diagnostic_value(json.loads(line), secrets), ensure_ascii=False) + "\n"
                                           for line in text.splitlines() if line.strip())
                        else:
                            text = sanitize_diagnostic_value(text, secrets)
                        body = text.encode("utf-8")
                        budget = min(MAX_DIAGNOSTIC_CONTENT_BYTES - 65536, MAX_DIAGNOSTIC_ARCHIVE_BYTES - 128 * 1024)
                        if total + len(body) > budget or len(seen) > 79:
                            raise ValueError("package_limit")
                    except (OSError, ValueError, UnicodeError):
                        omitted.append(name)
                        continue
                    archive.writestr(name, body)
                    total += len(body)
                manifest["omitted_files"] = omitted
                archive.writestr("manifest.json", json.dumps(sanitize_diagnostic_value(manifest, secrets), ensure_ascii=False, indent=2))
            if package_path.stat().st_size > MAX_DIAGNOSTIC_ARCHIVE_BYTES:
                raise DiagnosticExportError("問題包超過上傳容量限制，已保留本機檔案。")
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            raise DiagnosticExportError(f"無法建立問題包：{exc}") from exc
        return package_path

    def _candidate_files(self, target_date: str) -> list[Path]:
        candidates = [
            self.package_root / "duty_trigger_log.jsonl",
            self.package_root / "runtime_outputs" / "sinposmart_operational_sync_status.json",
            self.package_root / "runtime_outputs" / "duty_annotation_request.json",
            self.package_root / "runtime_outputs" / "duty_personnel_deductions.json",
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
        candidates.extend(self._recent_files("runtime_outputs/browser", ("*.jsonl", "*.json"), 5))

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
