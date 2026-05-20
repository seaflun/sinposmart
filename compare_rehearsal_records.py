# -*- coding: utf-8 -*-
"""Compare planned rehearsal actions with records currently visible in TYFD pages."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def clean(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").replace("\xa0", ""))


def hhmm(value: str) -> str:
    return value.replace(":", "")


def person_label(staff: dict[str, dict[str, str]], number: str) -> str:
    info = staff.get(str(number), {})
    name = info.get("name", "")
    if name:
        return f"{number}番{name}"
    return f"{number}番"


def names_for(staff: dict[str, dict[str, str]], numbers: list[str]) -> list[str]:
    return [staff.get(str(no), {}).get("name", "") for no in numbers]


def flatten_rows(rows: list[list[str]], target_date: str) -> list[str]:
    roc_slash = f"{target_date[:3]}/{target_date[3:5]}/{target_date[5:7]}"
    out = []
    for row in rows:
        text = " | ".join(str(x) for x in row if str(x).strip())
        normalized = text.replace("\xa0", " ").strip()
        if re.match(rf"^(?:{re.escape(target_date)}|{re.escape(roc_slash)})\s+\d{{1,2}}:\d{{2}}", normalized):
            out.append(normalized)
        elif re.match(rf"^{re.escape(target_date)}\s*\n\d{{1,2}}:\d{{2}}", normalized):
            out.append(text.replace("\xa0", " "))
    return out


def roc_date_after(value: str, days: int) -> str:
    year = int(value[:3]) + 1911
    month = int(value[3:5])
    day = int(value[5:7])
    shifted = datetime(year, month, day) + timedelta(days=days)
    return f"{shifted.year - 1911:03d}{shifted.month:02d}{shifted.day:02d}"


def action_target_date(base_target_date: str, action: dict[str, Any]) -> str:
    return roc_date_after(base_target_date, int(action.get("date_offset", 0) or 0))


def row_has_time(row: str, target_date: str, time_value: str, allow_near: bool = False, near_minutes: int = 5) -> bool:
    roc_slash = f"{target_date[:3]}/{target_date[3:5]}/{target_date[5:7]}"
    if f"{roc_slash} {time_value}" in row or f"{target_date}\n{time_value}" in row:
        return True
    if not allow_near:
        return False
    target_min = int(time_value[:2]) * 60 + int(time_value[3:])
    for match in re.finditer(rf"{re.escape(roc_slash)}\s+(\d{{2}}):(\d{{2}})", row):
        actual_min = int(match.group(1)) * 60 + int(match.group(2))
        if abs(actual_min - target_min) <= near_minutes:
            return True
    return False


def is_future_action(target_date: str, action: dict[str, Any]) -> bool:
    now = datetime.now()
    today_roc = f"{now.year - 1911:03d}{now.month:02d}{now.day:02d}"
    target_date = action_target_date(target_date, action)
    if target_date > today_roc:
        return True
    if target_date != today_roc:
        return False
    fields = action.get("fields", {})
    value = fields.get("系統寫入時間") or fields.get("工作時間") or action.get("time", "00:00")
    try:
        hour, minute = [int(part) for part in value.split(":", 1)]
    except ValueError:
        return False
    return hour * 60 + minute > now.hour * 60 + now.minute


def row_has_outin(row: str, outin: str, external_entry: bool = False) -> bool:
    if not outin:
        return True
    if "請選擇" in row:
        return True
    checks = [outin]
    if outin == "出":
        checks.extend(["簽出", "外出"])
    elif outin == "入":
        checks.extend(["簽入", "返隊", "到勤"])
    elif outin == "值班":
        checks.extend(["接班"])
    elif outin == "值退":
        checks.extend(["退班"])
    if external_entry and outin == "出":
        checks.append("簽出")
    if external_entry and outin == "入":
        checks.append("簽入")
    return any(check in row for check in checks)


def is_handoff_entry(action: dict[str, Any]) -> bool:
    return action.get("kind") == "entry_log" and action.get("fields", {}).get("出或入") in ("值班", "值退")


def has_value_rows_at_time(rows: list[str], target_date: str, time_value: str) -> bool:
    return any(row_has_time(row, target_date, time_value) and ("值班" in row or "值退" in row) for row in rows)


def has_same_person_value_record(rows: list[str], target_date: str, staff: dict[str, dict[str, str]], action: dict[str, Any]) -> bool:
    target_name = staff.get(str(action.get("target", "")), {}).get("name", "")
    outin = action.get("fields", {}).get("出或入", "")
    system_time = action.get("fields", {}).get("系統寫入時間", action.get("time", ""))
    if not target_name or outin not in ("值班", "值退"):
        return False
    return any(target_name in row and outin in row and row_has_time(row, target_date, system_time) for row in rows)


def is_possible_handoff_adjustment(
    rows: list[str],
    target_date: str,
    staff: dict[str, dict[str, str]],
    action: dict[str, Any],
) -> bool:
    fields = action.get("fields", {})
    time_value = fields.get("系統寫入時間", action.get("time", ""))
    return is_handoff_entry(action) and has_value_rows_at_time(rows, target_date, time_value)


def find_entry_matches(
    rows: list[str],
    target_date: str,
    staff: dict[str, dict[str, str]],
    action: dict[str, Any],
    allow_near: bool = False,
) -> list[str]:
    fields = action["fields"]
    target_name = staff.get(str(action["target"]), {}).get("name", "")
    outin = fields.get("出或入", "")
    system_time = fields.get("系統寫入時間", action["time"])
    strict_time = outin in ("值班", "值退")
    external_entry = str(action.get("source", "")).startswith("外勤")
    matches = []
    for row in rows:
        if target_name and target_name not in row:
            continue
        if not row_has_outin(row, outin, external_entry=external_entry):
            continue
        if strict_time:
            if not row_has_time(row, target_date, system_time, allow_near=allow_near):
                continue
        if external_entry:
            if row_has_time(row, target_date, system_time, allow_near=True, near_minutes=120):
                matches.append(row)
            continue
        if not row_has_time(row, target_date, system_time, allow_near=allow_near):
            continue
        matches.append(row)
    return matches


def find_work_matches(
    rows: list[str],
    target_date: str,
    staff: dict[str, dict[str, str]],
    action: dict[str, Any],
) -> list[str]:
    fields = action["fields"]
    time_value = fields.get("工作時間", action["time"])
    item = fields.get("勤務項目", "")
    source = action.get("source", "")
    matches = []
    for row in rows:
        c = clean(row)
        if not row_has_time(row, target_date, time_value):
            continue
        if item and item not in row:
            continue
        matches.append(row)
    return matches


def summarize_entry(action: dict[str, Any], staff: dict[str, dict[str, str]]) -> str:
    fields = action["fields"]
    return (
        f"{fields.get('系統寫入時間', action['time'])} "
        f"{person_label(staff, action['target'])} "
        f"{fields.get('出或入')} {fields.get('領用事由及地點')} "
        f"登打人={person_label(staff, action['actor'])}"
    )


def summarize_work(action: dict[str, Any], staff: dict[str, dict[str, str]]) -> str:
    fields = action["fields"]
    people = "、".join(person_label(staff, no) for no in fields.get("服勤人員", [])) or "-"
    extra = fields.get("訓練項目") or action["source"]
    return (
        f"{fields.get('工作時間', action['time'])} "
        f"{fields.get('勤務項目')} {extra} "
        f"登打人={person_label(staff, action['actor'])} 服勤={people}"
    )


def compare(json_path: Path, out_path: Path | None = None) -> Path:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    target_date = data["target_date"]
    staff = {
        **data.get("yesterday", {}).get("staff", {}),
        **data.get("today", {}).get("staff", {}),
    }
    comparison_sources: dict[str, dict[str, Any]] = {}
    for offset in sorted({int(action.get("date_offset", 0) or 0) for action in data.get("actions", [])} | {0}):
        action_date = roc_date_after(target_date, offset)
        comparison_file = json_path.with_name(f"comparison_output_{action_date}.json")
        payload: dict[str, Any] = {}
        if comparison_file.exists():
            payload = json.loads(comparison_file.read_text(encoding="utf-8"))
        comparison_sources[action_date] = {
            "entry_rows": flatten_rows(payload.get("visible_entry_rows", data.get("visible_entry_rows", [])), action_date),
            "work_rows": flatten_rows(payload.get("visible_work_rows", data.get("visible_work_rows", [])), action_date),
        }

    lines = [
        f"{target_date} 預演 vs 系統既有紀錄比對",
        "比對規則：只比對查詢頁可見的時間、人員、出入/勤務項目與主要內容；登打帳號若頁面未顯示則不判定。",
        "判讀原則：到勤、退勤、休息後退勤未找到時列為需補登；外勤人員不一致時列為人工確認，不自動補登。",
        "",
        "===== 出入暨領用無線電機登記簿 =====",
    ]
    entry_missing = 0
    entry_near = 0
    critical_missing: list[str] = []
    external_missing: list[str] = []
    for action in [a for a in data["actions"] if a["kind"] == "entry_log"]:
        action_date = action_target_date(target_date, action)
        entry_rows = comparison_sources.get(action_date, {}).get("entry_rows", [])
        exact = find_entry_matches(entry_rows, action_date, staff, action, allow_near=False)
        if exact:
            lines.append(f"[已存在] {summarize_entry(action, staff)}")
            continue
        if is_future_action(target_date, action):
            lines.append(f"[尚未到點] {summarize_entry(action, staff)}")
            continue
        if is_possible_handoff_adjustment(entry_rows, action_date, staff, action):
            lines.append(f"[可能臨時調整] {summarize_entry(action, staff)}")
            continue
        near = find_entry_matches(entry_rows, action_date, staff, action, allow_near=True)
        if near:
            entry_near += 1
            lines.append(f"[時間不同但近似] {summarize_entry(action, staff)}")
            lines.append(f"  系統例：{near[0]}")
            continue
        entry_missing += 1
        summary = summarize_entry(action, staff)
        reason = action["fields"].get("領用事由及地點", "")
        if reason in ("到勤", "退勤", "休息後退勤"):
            critical_missing.append(summary)
            lines.append(f"[需補登] {summary}")
        elif action["source"].startswith("外勤"):
            external_missing.append(summary)
            lines.append(f"[外勤未匹配] {summary}")
        else:
            lines.append(f"[未找到] {summary}")

    lines.extend(
        [
            "",
            "===== 工作紀錄簿 =====",
        ]
    )
    work_missing = 0
    for action in [a for a in data["actions"] if a["kind"] == "work_log"]:
        action_date = action_target_date(target_date, action)
        work_rows = comparison_sources.get(action_date, {}).get("work_rows", [])
        matches = find_work_matches(work_rows, action_date, staff, action)
        if matches:
            lines.append(f"[已存在] {summarize_work(action, staff)}")
        elif is_future_action(target_date, action):
            lines.append(f"[尚未到點] {summarize_work(action, staff)}")
        else:
            work_missing += 1
            lines.append(f"[未找到] {summarize_work(action, staff)}")

    external_targets: dict[str, set[str]] = {}
    for action in [a for a in data["actions"] if a["kind"] == "entry_log" and a["source"].startswith("外勤")]:
        key = f"{action['fields'].get('系統寫入時間', action['time'])}:{action['fields'].get('出或入')}"
        external_targets.setdefault(key, set()).add(staff.get(str(action["target"]), {}).get("name", ""))
    external_extra = []
    external_extra_seen = set()
    for row in entry_rows:
        if "防溺" not in row and "車巡" not in row:
            continue
        parts = [part.strip() for part in row.split("|")]
        time_match = re.search(r"(\d{2}:\d{2})", parts[0] if parts else "")
        if not time_match or len(parts) < 6:
            continue
        key = f"{time_match.group(1)}:{parts[5]}"
        person_name = parts[3]
        if person_name not in external_targets.get(key, set()) and row not in external_extra_seen:
            external_extra_seen.add(row)
            external_extra.append(row)
    if external_extra:
        lines.extend(["", "===== 系統額外外勤紀錄提示 ====="])
        for row in external_extra:
            lines.append(f"[外勤人員不一致/可能換人] {row}")

    if critical_missing or external_missing or external_extra:
        lines.extend(["", "===== 需處理重點 ====="])
        for item in critical_missing:
            lines.append(f"[需補登到退勤] {item}")
        for item in external_missing:
            lines.append(f"[外勤預演未找到] {item}")
        for row in external_extra:
            lines.append(f"[外勤系統已有不同人] {row}")

    lines.extend(
        [
            "",
            "===== 摘要 =====",
            f"出入：未找到 {entry_missing} 筆，時間近似但不完全相同 {entry_near} 筆。",
            f"工作：未找到 {work_missing} 筆。",
            "注意：既有人工登打可能使用不同時間或不同勤務項目名稱，以上是防重複用的初步比對，不會自動覆蓋人工資料。",
        ]
    )
    out_path = out_path or json_path.with_name(f"{target_date}_compare_report.txt")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare rehearsal actions with visible records.")
    parser.add_argument("json_path", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    path = compare(args.json_path, args.out)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
