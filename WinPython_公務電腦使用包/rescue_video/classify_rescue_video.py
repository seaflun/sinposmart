#!/usr/bin/env python3
"""Classify dashcam TS files into existing rescue case folders.

The program is intentionally dry-run by default.  Add --apply to copy files;
add --delete-source to remove only verified source files after copying.
It matches a memory-card file's last-write time against case-folder names such
as 07151309-92 and preserves the source timestamps.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Mapping


CASE_RE = re.compile(r"^(?P<md>\d{4})(?P<hm>\d{4})-(?P<vehicle>\d+)(?P<suffix>.*)$")
YEAR_RE = re.compile(r"^20\d{2}$")
WORK_TIME_RE = re.compile(r"(?P<roc>\d{7})\s*(?:\r?\n\s*)?(?P<hour>\d{1,2}):(?P<minute>\d{2})")
RETURN_TIME_RE = re.compile(
    r"(?P<year>20\d{2})/(?P<month>\d{1,2})/(?P<day>\d{1,2})\s+"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2}):(?P<second>\d{2})"
)
MONTH_RE = re.compile(r"^(\d{1,2})月?$", re.IGNORECASE)


@dataclass(frozen=True)
class CaseFolder:
    path: Path
    name: str
    vehicle: str
    start: datetime
    work_start: datetime | None = None
    return_time: datetime | None = None


@dataclass(frozen=True)
class CaseWork:
    vehicle: str
    work_start: datetime
    return_time: datetime | None
    category: str = ""


@dataclass
class Result:
    source: Path
    source_time: datetime
    adjusted_time: datetime
    case: CaseFolder | None
    destination: Path | None
    status: str
    note: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="將記憶卡影片依案件資料夾時間分類，保留來源修改時間。"
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help=r"記憶卡影片資料夾；省略時自動尋找各磁碟的 DCIM\100CAREC",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=Path(r"Z:\救護硬碟\救護密錄器及行車紀錄器"),
        help="案件資料夾根目錄",
    )
    parser.add_argument("--vehicle", default="92", help="記憶卡所屬車號，例如 92")
    parser.add_argument(
        "--date",
        help="只處理指定日期，例如 2026-07-15；省略則處理所有可配對影片",
    )
    parser.add_argument(
        "--offset-minutes",
        type=float,
        default=0,
        help="記憶卡時間校正分鐘數，實際時間 = 檔案時間 + 此數值",
    )
    parser.add_argument(
        "--before-minutes",
        type=float,
        default=30,
        help="案件時間前允許的配對範圍",
    )
    parser.add_argument(
        "--after-minutes",
        type=float,
        default=120,
        help="案件時間後允許的配對範圍",
    )
    parser.add_argument("--segment-minutes", type=float, default=6, help="單段影片推估長度，預設 6 分鐘")
    parser.add_argument(
        "--work-log-root",
        type=Path,
        default=Path(r"E:\SINPOSMART\WinPython_公務電腦使用包\runtime_outputs\comparison"),
        help="案件工作／返隊紀錄 JSON 資料夾",
    )
    parser.add_argument("--work-before-minutes", type=float, default=15, help="工作時間前允許分鐘數")
    parser.add_argument("--return-grace-minutes", type=float, default=10, help="返隊時間後允許分鐘數")
    parser.add_argument("--case-folder-tolerance-minutes", type=float, default=10, help="工作時間與案件資料夾時間容許差")
    parser.add_argument(
        "--extension",
        default=".TS",
        help="要處理的副檔名，預設只處理 .TS，不處理 .RSV",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="實際複製；未指定時只顯示預覽，不會寫入 Z 槽",
    )
    parser.add_argument(
        "--repair-mismatch",
        action="store_true",
        help="允許以完整驗證後的新檔案取代目的地大小不一致的檔案",
    )
    parser.add_argument(
        "--delete-source",
        action="store_true",
        help="複製並驗證成功後刪除記憶卡來源 .TS；必須搭配 --apply",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(__file__).resolve().with_name("分類結果.csv"),
        help="分類報告輸出位置",
    )
    args = parser.parse_args()
    if args.delete_source and not args.apply:
        parser.error("--delete-source 必須搭配 --apply")
    return args


def parse_date(value: str | None) -> datetime.date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise SystemExit(f"日期格式錯誤：{value}，請使用 YYYY-MM-DD") from exc


def month_from_name(name: str) -> int | None:
    match = MONTH_RE.match(name)
    if not match:
        return None
    month = int(match.group(1))
    return month if 1 <= month <= 12 else None


def discover_cases(destination: Path, vehicle: str) -> list[CaseFolder]:
    cases: list[CaseFolder] = []
    if not destination.exists():
        raise SystemExit(f"找不到目標資料夾：{destination}")

    for year_dir in destination.iterdir():
        if not year_dir.is_dir() or not YEAR_RE.match(year_dir.name):
            continue
        year = int(year_dir.name)
        for month_dir in year_dir.iterdir():
            if not month_dir.is_dir():
                continue
            folder_month = month_from_name(month_dir.name)
            if folder_month is None:
                continue
            for case_dir in month_dir.iterdir():
                if not case_dir.is_dir():
                    continue
                match = CASE_RE.match(case_dir.name)
                if not match or match.group("vehicle") != vehicle:
                    continue
                md = match.group("md")
                hm = match.group("hm")
                try:
                    # Case folder names are MMDDHHMM-vehicle, e.g. 07151309-92.
                    # The month directory is also checked, but 0715 means
                    # July 15, not July 7.
                    encoded_month = int(md[:2])
                    day = int(md[2:])
                    if encoded_month != folder_month:
                        continue
                    start = datetime(
                        year,
                        encoded_month,
                        day,
                        int(hm[:2]),
                        int(hm[2:]),
                    )
                except ValueError:
                    continue
                cases.append(CaseFolder(case_dir, case_dir.name, vehicle, start))
    return sorted(cases, key=lambda item: item.start)


def discover_vehicles(destination: Path, selected_date: date) -> list[str]:
    if not destination.is_dir():
        return []

    vehicles: set[str] = set()
    date_prefix = selected_date.strftime("%m%d")
    for year_dir in destination.iterdir():
        if not year_dir.is_dir() or year_dir.name != str(selected_date.year):
            continue
        for month_dir in year_dir.iterdir():
            if not month_dir.is_dir() or month_from_name(month_dir.name) != selected_date.month:
                continue
            for case_dir in month_dir.iterdir():
                if not case_dir.is_dir():
                    continue
                match = CASE_RE.match(case_dir.name)
                if match and match.group("md") == date_prefix:
                    vehicles.add(match.group("vehicle"))
    return sorted(vehicles, key=lambda vehicle: (int(vehicle), vehicle))


def choose_offset_minutes(scores: Mapping[int, int]) -> int:
    return max((scores.get(offset, 0), offset == 6, -offset, offset) for offset in (5, 6, 7))[3]


def roc_datetime(roc_date: str, hour: int, minute: int, second: int = 0) -> datetime | None:
    try:
        if len(roc_date) != 7:
            return None
        return datetime(int(roc_date[:3]) + 1911, int(roc_date[3:5]), int(roc_date[5:7]), hour, minute, second)
    except ValueError:
        return None


def discover_case_work(root: Path, vehicle: str) -> list[CaseWork]:
    """Read actual work/return times from comparison_output JSON files."""
    if not root.exists():
        return []
    token = re.compile(rf"(?<!\d){re.escape(vehicle)}\s*[:：;；]")
    found: dict[tuple[str, datetime], CaseWork] = {}
    for path in sorted(root.glob("comparison_output_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for row in payload.get("visible_work_rows", []):
            if not isinstance(row, list) or len(row) < 7:
                continue
            row_text = " | ".join(str(value) for value in row)
            if "119案件" not in row_text or not token.search(str(row[6])):
                continue
            work_match = WORK_TIME_RE.search(str(row[0]))
            if not work_match:
                continue
            work_start = roc_datetime(
                work_match.group("roc"), int(work_match.group("hour")), int(work_match.group("minute"))
            )
            if work_start is None:
                continue
            return_match = RETURN_TIME_RE.search(str(row[5]))
            return_time = None
            if return_match:
                try:
                    return_time = datetime(
                        int(return_match.group("year")),
                        int(return_match.group("month")),
                        int(return_match.group("day")),
                        int(return_match.group("hour")),
                        int(return_match.group("minute")),
                        int(return_match.group("second")),
                    )
                except ValueError:
                    return_time = None
            key = (vehicle, work_start)
            found[key] = CaseWork(vehicle, work_start, return_time, str(row[4]))
    return sorted(found.values(), key=lambda item: item.work_start)


def attach_case_work(cases: list[CaseFolder], work: list[CaseWork], tolerance: timedelta) -> list[CaseFolder]:
    attached: list[CaseFolder] = []
    for case in cases:
        candidates = [item for item in work if item.work_start.date() == case.start.date()]
        if candidates:
            closest = min(candidates, key=lambda item: abs(item.work_start - case.start))
            if abs(closest.work_start - case.start) <= tolerance:
                case = replace(case, work_start=closest.work_start, return_time=closest.return_time)
        attached.append(case)
    return attached


def discover_memory_card_sources(roots: Iterable[Path] | None = None) -> list[Path]:
    if roots is None:
        roots = (
            Path(f"{chr(code)}:\\")
            for code in range(ord("A"), ord("Z") + 1)
        )
    candidates: list[Path] = []
    for root in roots:
        candidate = root / "DCIM" / "100CAREC"
        try:
            if candidate.is_dir():
                candidates.append(candidate)
        except OSError:
            continue
    return candidates


def resolve_source(
    source: Path | None,
    roots: Iterable[Path] | None = None,
) -> Path:
    if source is not None:
        return source
    candidates = discover_memory_card_sources(roots)
    if not candidates:
        raise FileNotFoundError(
            r"找不到記憶卡影片資料夾，請確認插卡或使用 --source 指定 DCIM\100CAREC"
        )
    if len(candidates) > 1:
        locations = "、".join(str(path) for path in candidates)
        raise FileExistsError(f"偵測到多張記憶卡影片資料夾：{locations}；請使用 --source 指定")
    return candidates[0]


def discover_sources(source: Path, extension: str) -> list[Path]:
    if not source.exists():
        raise SystemExit(f"找不到記憶卡資料夾：{source}")
    extension = extension if extension.startswith(".") else f".{extension}"
    files: list[Path] = []
    for path in source.iterdir():
        # Check the suffix before is_file(): some camera-generated RSV files
        # may be damaged and Windows can raise WinError 1392 when stat() is
        # called on them.  RSV files are not video input for this program.
        if path.suffix.upper() != extension.upper():
            continue
        # Keep the path even when stat() fails.  The classification report
        # should show unreadable TS files instead of silently dropping them.
        files.append(path)
    def sort_key(path: Path) -> tuple[int, str]:
        try:
            return (path.stat().st_mtime_ns, path.name)
        except OSError:
            return (2**63 - 1, path.name)

    return sorted(files, key=sort_key)


def choose_case(
    video_start: datetime,
    video_end: datetime,
    cases: Iterable[CaseFolder],
    before: timedelta,
    after: timedelta,
    work_before: timedelta,
    return_grace: timedelta,
) -> CaseFolder | None:
    candidates: list[tuple[CaseFolder, float]] = []
    for case in cases:
        if case.work_start is not None:
            range_start = case.work_start - work_before
            range_end = (case.return_time + return_grace) if case.return_time else case.work_start + after
            if video_end < range_start or video_start > range_end:
                continue
            if video_start > range_end:
                distance = (video_start - range_end).total_seconds()
            elif video_end < range_start:
                distance = (range_start - video_end).total_seconds()
            else:
                distance = 0
        else:
            if video_end < case.start - before or video_start > case.start + after:
                continue
            distance = 0
        candidates.append((case, distance))
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[1])[0]


def same_file_metadata(source: Path, destination: Path) -> bool:
    try:
        source_stat = source.stat()
        destination_stat = destination.stat()
    except OSError:
        return False
    return (
        source_stat.st_size == destination_stat.st_size
        and abs(source_stat.st_mtime_ns - destination_stat.st_mtime_ns) <= 2_000_000_000
    )


def copy_preserving_time(source: Path, destination: Path) -> None:
    """Copy through a temporary file, verify size, then atomically rename."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part")
    source_stat = source.stat()
    try:
        with source.open("rb") as input_file, temporary.open("wb") as output_file:
            shutil.copyfileobj(input_file, output_file, length=8 * 1024 * 1024)
            output_file.flush()
            os.fsync(output_file.fileno())
        if temporary.stat().st_size != source_stat.st_size:
            raise IOError(
                f"大小驗證失敗：來源 {source_stat.st_size}，暫存檔 {temporary.stat().st_size}"
            )
        shutil.copystat(source, temporary, follow_symlinks=False)
        os.utime(temporary, ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns))
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def delete_verified_source(source: Path, destination: Path) -> None:
    """Delete a source only after metadata and byte content both match."""
    if source.resolve() == destination.resolve():
        raise IOError("來源與目的地相同，拒絕刪除")
    if not source.is_file() or not destination.is_file():
        raise IOError("來源或目的地不是檔案，拒絕刪除")
    if not same_file_metadata(source, destination):
        raise IOError("刪除前檔案大小或修改時間驗證失敗")
    if sha256_file(source) != sha256_file(destination):
        raise IOError("刪除前 SHA-256 內容驗證失敗")
    source.unlink()


def finalize_source_cleanup(
    source: Path,
    destination: Path,
    status: str,
    delete_source: bool,
) -> tuple[str, str]:
    if not delete_source or status not in {"已完成", "已修復", "已複製"}:
        return status, ""
    try:
        delete_verified_source(source, destination)
    except OSError as exc:
        return "來源刪除失敗", f"{status}完成，但來源未刪除：{exc}"
    return f"{status}並刪除來源", ""


def classify(args: argparse.Namespace) -> list[Result]:
    selected_date = parse_date(args.date)
    cases = discover_cases(args.destination, args.vehicle)
    source_root = resolve_source(args.source)
    sources = discover_sources(source_root, args.extension)
    before = timedelta(minutes=args.before_minutes)
    after = timedelta(minutes=args.after_minutes)
    offset = timedelta(minutes=args.offset_minutes)
    results: list[Result] = []

    for source in sources:
        try:
            source_time = datetime.fromtimestamp(source.stat().st_mtime)
        except OSError as exc:
            results.append(
                Result(
                    source,
                    datetime.min,
                    datetime.min,
                    None,
                    None,
                    "無法讀取",
                    str(exc),
                )
            )
            continue
        adjusted_time = source_time + offset
        if selected_date and adjusted_time.date() != selected_date:
            continue
        case = choose_case(
            adjusted_time,
            adjusted_time,
            cases,
            before,
            after,
            timedelta(0),
            timedelta(0),
        )
        if case is None:
            results.append(
                Result(source, source_time, adjusted_time, None, None, "待確認", "沒有符合時間區間的案件")
            )
            continue

        destination = case.path / "車" / source.name
        note = ""
        if destination.exists():
            if same_file_metadata(source, destination):
                status = "已完成"
            elif args.apply and args.repair_mismatch:
                try:
                    copy_preserving_time(source, destination)
                    status = "已修復"
                except OSError as exc:
                    status = "錯誤"
                    results.append(
                        Result(source, source_time, adjusted_time, case, destination, status, str(exc))
                    )
                    continue
            else:
                status = "目的地不一致"
        elif args.apply:
            try:
                copy_preserving_time(source, destination)
                status = "已複製"
            except OSError as exc:
                status = "錯誤"
                results.append(
                    Result(source, source_time, adjusted_time, case, destination, status, str(exc))
                )
                continue
        else:
            status = "預計複製"
        status, note = finalize_source_cleanup(
            source,
            destination,
            status,
            getattr(args, "delete_source", False),
        )
        results.append(Result(source, source_time, adjusted_time, case, destination, status, note))
    return results


def classify_with_work_logs(args: argparse.Namespace) -> list[Result]:
    """Classify by video interval against actual work and return times."""
    selected_date = parse_date(args.date)
    cases = discover_cases(args.destination, args.vehicle)
    work = discover_case_work(args.work_log_root, args.vehicle)
    cases = attach_case_work(
        cases,
        work,
        timedelta(minutes=args.case_folder_tolerance_minutes),
    )
    source_root = resolve_source(args.source)
    sources = discover_sources(source_root, args.extension)
    before = timedelta(minutes=args.before_minutes)
    after = timedelta(minutes=args.after_minutes)
    work_before = timedelta(minutes=args.work_before_minutes)
    return_grace = timedelta(minutes=args.return_grace_minutes)
    segment = timedelta(minutes=args.segment_minutes)
    offset = timedelta(minutes=args.offset_minutes)
    results: list[Result] = []

    for source in sources:
        try:
            source_time = datetime.fromtimestamp(source.stat().st_mtime)
        except OSError as exc:
            results.append(Result(source, datetime.min, datetime.min, None, None, "無法讀取", str(exc)))
            continue

        video_end = source_time + offset
        video_start = video_end - segment
        if selected_date and video_end.date() != selected_date:
            continue

        case = choose_case(video_start, video_end, cases, before, after, work_before, return_grace)
        if case is None:
            results.append(Result(source, source_time, video_end, None, None, "待確認", "沒有符合工作／返隊時間的案件"))
            continue

        destination = case.path / "車" / source.name
        work_note = ""
        if case.work_start:
            work_note = f"案件工作={case.work_start:%Y-%m-%d %H:%M}; 返隊={case.return_time:%Y-%m-%d %H:%M:%S}" if case.return_time else f"案件工作={case.work_start:%Y-%m-%d %H:%M}; 無返隊時間"

        if destination.exists():
            if same_file_metadata(source, destination):
                status = "已完成"
            elif args.apply and args.repair_mismatch:
                try:
                    copy_preserving_time(source, destination)
                    status = "已修復"
                except OSError as exc:
                    status = "錯誤"
                    work_note = f"{work_note}; {exc}"
            else:
                status = "目的地不一致"
        elif args.apply:
            try:
                copy_preserving_time(source, destination)
                status = "已複製"
            except OSError as exc:
                status = "錯誤"
                work_note = f"{work_note}; {exc}"
        else:
            status = "預計複製"
        status, cleanup_note = finalize_source_cleanup(
            source,
            destination,
            status,
            getattr(args, "delete_source", False),
        )
        if cleanup_note:
            work_note = f"{work_note}; {cleanup_note}" if work_note else cleanup_note
        results.append(Result(source, source_time, video_end, case, destination, status, work_note))
    return results


def write_report(results: list[Result], report: Path) -> None:
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.writer(output)
        writer.writerow(
            [
                "來源檔案",
                "來源修改時間",
                "校正後時間",
                "案件資料夾",
                "目的地",
                "狀態",
                "備註",
            ]
        )
        for result in results:
            writer.writerow(
                [
                    str(result.source),
                    result.source_time.strftime("%Y-%m-%d %H:%M:%S"),
                    result.adjusted_time.strftime("%Y-%m-%d %H:%M:%S"),
                    result.case.name if result.case else "",
                    str(result.destination) if result.destination else "",
                    result.status,
                    result.note,
                ]
            )


def print_summary(results: list[Result], apply: bool) -> None:
    print("模式：" + ("實際複製" if apply else "預覽，不寫入檔案"))
    print(f"處理檔案：{len(results)}")
    counts: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    for status, count in sorted(counts.items()):
        print(f"  {status}: {count}")
    print("\n分類明細：")
    for result in results:
        case_name = result.case.name if result.case else "待確認"
        print(
            f"  {result.source.name}  {result.adjusted_time:%m/%d %H:%M:%S}"
            f" -> {case_name} [{result.status}]"
        )


def main() -> int:
    args = parse_args()
    try:
        results = classify_with_work_logs(args)
        write_report(results, args.report)
        print_summary(results, args.apply)
        print(f"\n報告：{args.report.resolve()}")
        return 0
    except (OSError, ValueError) as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
