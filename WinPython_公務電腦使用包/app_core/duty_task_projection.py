# -*- coding: utf-8 -*-
"""Framework-neutral projection from duty schedule actions to task-list rows."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

from compare_rehearsal_records import (
    find_arrival_entry_exists,
    find_case_work_matches,
    find_entry_matches,
    find_work_matches,
    flatten_rows,
    is_future_action,
    is_possible_handoff_adjustment,
    row_has_time,
)


AUTO_DUE_CATCH_UP_WINDOW = timedelta(hours=2)
EXTERNAL_REST_ENTRY_SOURCES = frozenset(
    {"外勤簽出", "外勤簽入", "休息簽出", "休息結束"}
)
EXTERNAL_REST_DEPARTURE_SOURCES = frozenset({"外勤簽出", "休息簽出"})
EXTERNAL_REST_RETURN_SOURCES = frozenset({"外勤簽入", "休息結束"})


@dataclass(frozen=True)
class DutyTaskProjectionState:
    actor_no: str
    target_roc_date: str
    staff: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    comparisons: Mapping[int, Mapping[str, Any]] = field(default_factory=dict)
    submitting_indices: frozenset[int] = frozenset()
    comparison_wait_statuses: Mapping[int, str] = field(default_factory=dict)
    paused_indices: frozenset[int] = frozenset()
    executed_indices: frozenset[int] = frozenset()
    manual_completed_indices: frozenset[int] = frozenset()
    selected_indices: frozenset[int] = frozenset()
    forced_visible_indices: frozenset[int] = frozenset()
    task_errors: Mapping[int, str] = field(default_factory=dict)
    auto_return_indices: frozenset[int] = frozenset()
    manual_waiting_indices: frozenset[int] = frozenset()


@dataclass(frozen=True)
class DueTaskSelectionState:
    actor_no: str
    target_roc_date: str
    comparisons: Mapping[int, Mapping[str, Any]] = field(default_factory=dict)
    executed_indices: frozenset[int] = frozenset()
    submitting_indices: frozenset[int] = frozenset()
    blocked_indices: frozenset[int] = frozenset()
    retry_after: Mapping[int, datetime] = field(default_factory=dict)
    auto_return_indices: frozenset[int] = frozenset()


def parse_roc_date(value: str) -> date:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    if len(digits) != 7:
        raise ValueError(f"invalid ROC date: {value!r}")
    return date(int(digits[:3]) + 1911, int(digits[3:5]), int(digits[5:7]))


def action_time_value(action: Mapping[str, Any]) -> str:
    fields = action.get("fields", {})
    if not isinstance(fields, Mapping):
        fields = {}
    return str(
        fields.get("登打時間")
        or fields.get("工作時間")
        or action.get("time", "")
        or ""
    )


def action_datetime(
    action: Mapping[str, Any],
    target_roc_date: str,
    *,
    fallback_date: date | None = None,
) -> datetime:
    value = action_time_value(action) or "00:00"
    try:
        hour, minute = [int(part) for part in value.split(":", 1)]
    except (TypeError, ValueError):
        hour, minute = 0, 0
    extra_days, hour = divmod(hour, 24)
    try:
        base_date = parse_roc_date(target_roc_date)
    except ValueError:
        base_date = fallback_date or date.today()
    offset = int(action.get("date_offset", 0) or 0) + extra_days
    action_date = base_date + timedelta(days=offset)
    return datetime(action_date.year, action_date.month, action_date.day, hour, minute)


def action_target_roc_date(action: Mapping[str, Any], target_roc_date: str) -> str:
    submit_target_date = str(action.get("submit_target_date", "") or "").strip()
    if submit_target_date:
        return submit_target_date
    target_date = action_datetime(action, target_roc_date).date()
    return f"{target_date.year - 1911:03d}{target_date.month:02d}{target_date.day:02d}"


def action_return_pair_key(action: Mapping[str, Any]) -> str:
    return str(action.get("return_pair_key", "") or "").strip()


def is_external_or_rest_entry(action: Mapping[str, Any]) -> bool:
    return bool(
        action.get("kind") == "entry_log"
        and str(action.get("source", "") or "") in EXTERNAL_REST_ENTRY_SOURCES
    )


def is_external_or_rest_departure(action: Mapping[str, Any]) -> bool:
    return bool(
        is_external_or_rest_entry(action)
        and str(action.get("source", "") or "") in EXTERNAL_REST_DEPARTURE_SOURCES
    )


def is_external_or_rest_return(action: Mapping[str, Any]) -> bool:
    return bool(
        is_external_or_rest_entry(action)
        and str(action.get("source", "") or "") in EXTERNAL_REST_RETURN_SOURCES
    )


def action_completion_key(action: Mapping[str, Any]) -> str:
    """Return the stable completion identity used by the legacy duty GUI."""

    duplicate_key = str(action.get("duplicate_key", "") or "").strip()
    if duplicate_key:
        return duplicate_key
    fields = action.get("fields", {})
    if not isinstance(fields, Mapping):
        fields = {}
    return "|".join(
        [
            str(action.get("kind", "")),
            str(action.get("source", "")),
            str(action.get("actor", "")),
            str(action.get("target", "")),
            str(action.get("date_offset", "")),
            str(fields.get("出或入", "")),
            str(fields.get("領用事由及地點", "")),
            str(fields.get("工作項目", "")),
            str(action.get("time", "")),
            action_summary(action),
        ]
    )


def compact_action_snapshot(action: Mapping[str, Any]) -> dict[str, str]:
    """Project one action to the bounded backend snapshot used by the legacy GUI."""

    fields = action.get("fields", {})
    if not isinstance(fields, Mapping):
        fields = {}
    return {
        "kind": str(action.get("kind", "")),
        "time": str(
            fields.get("系統寫入時間")
            or fields.get("登打時間")
            or fields.get("工作時間")
            or action.get("time", "")
        ),
        "source": str(action.get("source", "")),
        "actor": str(action.get("actor", "")),
        "target": str(action.get("target", "")),
        "item": str(fields.get("勤務項目") or fields.get("出或入") or ""),
        "content": str(fields.get("工作內容") or fields.get("領用事由及地點") or "")[:240],
    }


def format_action_time(action: Mapping[str, Any], target_roc_date: str) -> str:
    value = action_time_value(action)
    action_at = action_datetime(action, target_roc_date)
    try:
        base_date = parse_roc_date(target_roc_date)
    except ValueError:
        base_date = date.today()
    display_time = action_at.strftime("%H:%M") if value else ""
    return f"{action_at.day}日 {display_time}" if action_at.date() != base_date else display_time


def person_short_label(number: str, staff: Mapping[str, Mapping[str, Any]]) -> str:
    number = str(number or "").strip()
    if not number:
        return "-"
    info = staff.get(number, {})
    name = str(info.get("name", "") or "").strip()
    display_no = number.zfill(2) if number.isdigit() else number
    return f"{display_no} {name}" if name else display_no


def target_short_label(
    action: Mapping[str, Any],
    staff: Mapping[str, Mapping[str, Any]],
) -> str:
    fields = action.get("fields", {})
    if not isinstance(fields, Mapping):
        fields = {}
    if action.get("kind") == "work_log":
        people = fields.get("服勤人員", [])
        if isinstance(people, list) and people:
            return ",".join(person_short_label(str(number), staff) for number in people)
    return person_short_label(str(action.get("target", "") or ""), staff)


def duty_people_label(
    action: Mapping[str, Any],
    staff: Mapping[str, Mapping[str, Any]],
) -> str:
    if action.get("source") == "在隊訓練":
        return "備勤人員"
    fields = action.get("fields", {})
    if not isinstance(fields, Mapping):
        fields = {}
    people = fields.get("服勤人員", [])
    if isinstance(people, list) and len(people) > 1:
        return f"備勤人員 {len(people)}人"
    if isinstance(people, list) and len(people) == 1:
        return person_short_label(str(people[0]), staff)
    return target_short_label(action, staff)


def duty_task_columns(
    action: Mapping[str, Any],
    staff: Mapping[str, Mapping[str, Any]],
) -> tuple[str, str, str, str]:
    fields = action.get("fields", {})
    if not isinstance(fields, Mapping):
        fields = {}
    if action.get("kind") == "entry_log":
        direction = str(fields.get("出或入", "") or "-")
        reason = str(fields.get("領用事由及地點", "") or "-")
        return "出入", direction, f"{direction} / {reason}", target_short_label(action, staff)
    if action.get("source") in ("無線電試話", "無線電測試"):
        return "工作", "其他", "其他 / 無線電測試", duty_people_label(action, staff)
    duty_type = str(fields.get("勤務項目", "") or action.get("source", "") or "工作")
    detail_parts = [
        str(value).strip()
        for value in (duty_type, fields.get("事由", ""), fields.get("訓練項目", ""))
        if str(value).strip()
    ]
    detail = " / ".join(dict.fromkeys(detail_parts)) or duty_type
    if action.get("source") == "在隊訓練":
        topic = str(fields.get("訓練項目", "") or "").strip()
        detail = f"在隊訓練 / {topic}" if topic else "在隊訓練"
    return "工作", "工作", detail, duty_people_label(action, staff)


def is_auto_duty_action(action: Mapping[str, Any]) -> bool:
    if action.get("kind") == "work_log":
        return action.get("source") in (
            "值班交接",
            "在隊訓練",
            "無線電試話",
            "無線電測試",
        )
    if action.get("kind") != "entry_log":
        return False
    fields = action.get("fields", {})
    if not isinstance(fields, Mapping):
        fields = {}
    direction = fields.get("出或入", "")
    reason = fields.get("領用事由及地點", "")
    return direction in ("值班", "值退") or reason in ("到勤", "退勤", "休息後退勤")


def select_due_task_indices(
    actions: Sequence[Mapping[str, Any]],
    state: DueTaskSelectionState,
    *,
    now: datetime | None = None,
) -> list[int]:
    """Return due, auto-eligible task indexes without causing side effects."""
    current = now or datetime.now()
    due: list[int] = []
    for index, action in enumerate(actions):
        if action.get("kind") not in ("work_log", "entry_log"):
            continue
        if str(action.get("actor", "") or "") != str(state.actor_no or ""):
            continue
        if index in state.executed_indices or index in state.submitting_indices:
            continue
        if index in state.blocked_indices:
            continue
        retry_at = state.retry_after.get(index)
        if retry_at is not None and current < retry_at:
            continue
        comparison = state.comparisons.get(index, {})
        is_auto_return = (
            index in state.auto_return_indices
            and is_external_or_rest_return(action)
        )
        if (
            comparison.get("group") in ("done", "manual", "near", "adjust", "review", "skipped")
            and not is_auto_return
        ):
            continue
        if not (is_auto_duty_action(action) or is_auto_return):
            continue
        action_at = action_datetime(action, state.target_roc_date, fallback_date=current.date())
        if action_at <= current <= action_at + AUTO_DUE_CATCH_UP_WINDOW:
            due.append(index)
    return sorted(due, key=lambda index: (action_datetime(actions[index], state.target_roc_date), index))


def previous_duty_actor_nos(actions: Sequence[Mapping[str, Any]], actor_no: str) -> set[str]:
    previous: set[str] = set()
    for action in actions:
        fields = action.get("fields", {})
        if not isinstance(fields, Mapping):
            fields = {}
        if (
            action.get("kind") == "entry_log"
            and action.get("source") == "值班交接"
            and str(action.get("target", "")) == actor_no
            and fields.get("出或入", "") == "值班"
        ):
            action_actor = str(action.get("actor", "") or "")
            if action_actor and action_actor != actor_no:
                previous.add(action_actor)
    return previous


def previous_duty_handoff_times(
    actions: Sequence[Mapping[str, Any]],
    actor_no: str,
    target_roc_date: str,
) -> dict[str, set[datetime]]:
    handoff_times: dict[str, set[datetime]] = {}
    for action in actions:
        fields = action.get("fields", {})
        if not isinstance(fields, Mapping):
            fields = {}
        if (
            action.get("kind") == "entry_log"
            and action.get("source") == "值班交接"
            and str(action.get("target", "")) == actor_no
            and fields.get("出或入", "") == "值班"
        ):
            action_actor = str(action.get("actor", "") or "")
            if action_actor and action_actor != actor_no:
                handoff_times.setdefault(action_actor, set()).add(
                    action_datetime(action, target_roc_date)
                )
    return handoff_times


def _is_previous_duty_item(
    action: Mapping[str, Any],
    previous_handoff_times: Mapping[str, set[datetime]],
    target_roc_date: str,
) -> bool:
    if action.get("kind") != "entry_log":
        return False
    source = str(action.get("source", "") or "")
    if not (source.startswith("外勤") or source in ("休息簽出", "休息結束")):
        return False
    actor_no = str(action.get("actor", "") or "")
    return action_datetime(action, target_roc_date) in previous_handoff_times.get(actor_no, set())


def _display_status(value: Any) -> str:
    text = str(value or "")
    return {
        "已存在": "已登打",
        "已存在(時間不同)": "已登打",
        "可能臨時調整": "疑似異動",
    }.get(text, text)


_TIME_PATTERN = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)")
_RECORD_TIME_PATTERN = re.compile(
    r"(?<!\d)(?:\d{3}/\d{2}/\d{2}|\d{7})[ \t]*\n?[ \t]+(\d{1,2}:\d{2})(?!\d)"
)


def _format_time_value(value: Any) -> str:
    match = _TIME_PATTERN.search(str(value or ""))
    if not match:
        return ""
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        return ""
    return f"{hour:02d}:{minute:02d}"


def actual_record_time(comparison: Mapping[str, Any]) -> str:
    """Extract the actual time from the first matched duty-system record."""

    matched = comparison.get("matched", [])
    if not isinstance(matched, Sequence) or isinstance(matched, (str, bytes)):
        return ""
    mapping_keys = ("實際登打時間", "登打時間", "系統寫入時間", "工作時間", "時間")
    for row in matched:
        if isinstance(row, Mapping):
            for key in mapping_keys:
                value = _format_time_value(row.get(key))
                if value:
                    return value
            continue
        text = str(row or "")
        record_match = _RECORD_TIME_PATTERN.search(text)
        if record_match:
            return _format_time_value(record_match.group(1))
        value = _format_time_value(text)
        if value:
            return value
    return ""


def _is_external_rest_manual_submission(
    action: Mapping[str, Any],
    comparison: Mapping[str, Any],
) -> bool:
    return bool(
        comparison.get("group") == "done"
        and comparison.get("submission_trigger") == "manual"
        and is_external_or_rest_entry(action)
    )


def audit_status_text(
    action: Mapping[str, Any],
    comparison: Mapping[str, Any],
) -> str:
    if comparison.get("group") == "paused":
        return "未返隊暫停"
    if _is_external_rest_manual_submission(action, comparison):
        return "外勤休息手動"
    return _display_status(comparison.get("compare", "未比對"))


def _task_status(
    index: int,
    action: Mapping[str, Any],
    comparison: Mapping[str, Any],
    state: DutyTaskProjectionState,
    *,
    is_previous_item: bool,
    now: datetime,
) -> tuple[str, str]:
    if index in state.submitting_indices:
        return "正在登打", "running"
    is_auto_return = (
        index in state.auto_return_indices
        and is_external_or_rest_return(action)
        and index not in state.executed_indices
    )
    if is_auto_return:
        action_at = action_datetime(action, state.target_roc_date)
        if action_at + AUTO_DUE_CATCH_UP_WINDOW < now:
            return "逾時未補跑", "manual"
        return ("到點待執行", "ready") if action_at <= now else ("等待", "waiting")
    if comparison.get("group") == "done":
        return _display_status(comparison.get("compare") or "已存在"), "triggered"
    if comparison.get("group") == "skipped":
        return _display_status(comparison.get("compare") or "跨班接續已略過"), "manual"
    if index in state.manual_waiting_indices:
        return "等待", "waiting"
    if index in state.comparison_wait_statuses:
        return state.comparison_wait_statuses[index], "manual"
    if index in state.paused_indices:
        return "未返隊暫停", "manual"
    if index in state.executed_indices:
        return ("已手動登打" if index in state.manual_completed_indices else "已登打"), "triggered"
    if comparison.get("group") in ("near", "adjust", "review"):
        return _display_status(comparison.get("compare") or "人工確認"), "manual"
    if is_previous_item:
        return "前班手動", "waiting"
    if comparison.get("group") == "manual" or not is_auto_duty_action(action):
        return "手動", "waiting"
    action_at = action_datetime(action, state.target_roc_date)
    if action_at + AUTO_DUE_CATCH_UP_WINDOW < now:
        return "逾時未補跑", "manual"
    return ("到點待執行", "ready") if action_at <= now else ("等待", "waiting")


def project_duty_tasks(
    actions: Sequence[Mapping[str, Any]],
    state: DutyTaskProjectionState,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return stable duty-card rows without importing a GUI framework."""

    actor_no = str(state.actor_no or "").strip()
    if not actor_no:
        return []
    now = now or datetime.now()
    previous_handoff_times = previous_duty_handoff_times(
        actions,
        actor_no,
        state.target_roc_date,
    )
    handoff_group_anchors: dict[tuple[datetime, str], int] = {}
    for index, action in enumerate(actions):
        if action.get("source") != "值班交接":
            continue
        handoff_group_anchors.setdefault(
            (action_datetime(action, state.target_roc_date), str(action.get("actor", "") or "")),
            index,
        )

    projected: list[tuple[tuple[datetime, int, int, int, int], dict[str, Any]]] = []
    for index, action in enumerate(actions):
        comparison = state.comparisons.get(index, {})
        is_previous_item = _is_previous_duty_item(
            action,
            previous_handoff_times,
            state.target_roc_date,
        )
        if (
            str(action.get("actor", "") or "") != actor_no
            and not is_previous_item
            and index not in state.forced_visible_indices
        ):
            continue
        if is_previous_item and comparison and comparison.get("group") in ("done", "near", "adjust"):
            continue
        is_external_action = str(action.get("source", "") or "").startswith("外勤")
        if comparison.get("group") == "review" and not is_previous_item and not is_external_action:
            continue
        status_text, status_tone = _task_status(
            index,
            action,
            comparison,
            state,
            is_previous_item=is_previous_item,
            now=now,
        )
        system_text, kind_text, detail_text, people_text = duty_task_columns(action, state.staff)
        action_at = action_datetime(action, state.target_roc_date)
        if action.get("source") == "值班交接":
            fields = action.get("fields", {})
            direction = str(fields.get("出或入", "") or "") if isinstance(fields, Mapping) else ""
            handoff_priority = 0 if direction == "值退" else 1 if direction == "值班" else 2
            sort_key = (
                action_at,
                handoff_group_anchors[(action_at, str(action.get("actor", "") or ""))],
                0,
                handoff_priority,
                index,
            )
        else:
            sort_key = (action_at, index, 1, 0, index)
        projected.append(
            (
                sort_key,
                {
                    "taskIndex": index,
                    "timeText": format_action_time(action, state.target_roc_date),
                    "systemText": system_text,
                    "kindText": kind_text,
                    "detailText": detail_text,
                    "peopleText": people_text,
                    "statusText": status_text,
                    "statusTone": status_tone,
                    "selected": index in state.selected_indices,
                    "errorText": str(state.task_errors.get(index, "") or ""),
                },
            )
        )
    projected.sort(key=lambda item: item[0])
    return [row for _sort_key, row in projected]


def action_summary(action: Mapping[str, Any]) -> str:
    fields = action.get("fields", {})
    if not isinstance(fields, Mapping):
        fields = {}
    if action.get("source") in ("無線電試話", "無線電測試"):
        return "其他 / 無線電試話"
    if action.get("source") == "案件工作審核":
        return str(fields.get("事由", "") or "")
    if action.get("kind") == "entry_log":
        return f"{fields.get('出或入', '')} / {fields.get('領用事由及地點', '')}".strip(" / ")
    parts = (fields.get("勤務項目", ""), fields.get("事由", ""), fields.get("訓練項目", ""))
    return " / ".join(str(part).strip() for part in parts if str(part).strip())


def next_duty_task_text(
    actions: Sequence[Mapping[str, Any]],
    state: DutyTaskProjectionState,
    *,
    now: datetime | None = None,
) -> str:
    """Return the legacy next-task summary without causing any submission side effect."""

    actor_no = str(state.actor_no or "").strip()
    if not actor_no:
        return "下一項任務：-"

    current = now or datetime.now()
    pending_previous = 0
    for row in project_duty_tasks(actions, state, now=current):
        index = int(row["taskIndex"])
        action = actions[index]
        if str(action.get("actor", "") or "") != actor_no:
            pending_previous += 1
            continue

        comparison = state.comparisons.get(index, {})
        if index in state.submitting_indices or comparison.get("group") == "done":
            continue
        if index in state.comparison_wait_statuses:
            continue
        if index in state.paused_indices or index in state.executed_indices:
            continue
        if comparison.get("group") in ("near", "adjust", "review", "manual"):
            continue
        if not is_auto_duty_action(action):
            continue

        action_at = action_datetime(action, state.target_roc_date, fallback_date=current.date())
        delta = max(0, int((action_at - current).total_seconds() // 60))
        return f"{format_action_time(action, state.target_roc_date)}  {action_summary(action)}，約 {delta} 分鐘後"

    if pending_previous:
        return f"前一班尚有 {pending_previous} 筆待手動處理"
    return "今日目前沒有未完成的當班任務"


def audit_detail_text(
    action: Mapping[str, Any],
    comparison: Mapping[str, Any],
) -> str:
    detail_status = (
        audit_status_text(action, comparison)
        if comparison.get("group") == "paused"
        or _is_external_rest_manual_submission(action, comparison)
        else str(comparison.get("compare", "未比對") or "未比對")
    )
    lines = [
        f"比對：{detail_status}",
        f"摘要：{action_summary(action) or '-'}",
    ]
    actual_time = actual_record_time(comparison)
    if actual_time:
        lines.append(f"實際登打：{actual_time}")
    lines.append("")
    matched = comparison.get("matched", [])
    if isinstance(matched, Sequence) and not isinstance(matched, (str, bytes)):
        for row in matched:
            row_text = row if isinstance(row, str) else json.dumps(row, ensure_ascii=False, default=str)
            lines.extend(["系統既有紀錄：", row_text, ""])
    lines.extend(
        [
            "原始預演資料：",
            json.dumps(dict(action), ensure_ascii=False, indent=2, default=str),
        ]
    )
    return "\n".join(lines)


def project_audit_tasks(
    actions: Sequence[Mapping[str, Any]],
    *,
    target_roc_date: str,
    staff: Mapping[str, Mapping[str, Any]],
    comparisons: Mapping[int, Mapping[str, Any]],
    actor_no: str = "",
    kind_filter: str = "全部",
    status_filter: str = "全部",
) -> list[dict[str, Any]]:
    """Project all review rows with optional actor, kind and status filters."""

    rows: list[tuple[datetime, dict[str, Any]]] = []
    for index, action in enumerate(actions):
        action_actor = str(action.get("actor", "") or "")
        if actor_no and action_actor != actor_no:
            continue
        system_text, kind_text, detail_text, people_text = duty_task_columns(action, staff)
        audit_kind_text = (
            "案件工作"
            if action.get("source") == "案件工作審核"
            else "出入"
            if action.get("kind") == "entry_log"
            else "工作"
        )
        if kind_filter != "全部" and audit_kind_text != kind_filter:
            continue
        comparison = comparisons.get(index, {"compare": "未比對", "group": "ready"})
        group = str(comparison.get("group", "ready") or "ready")
        is_external_rest_manual = _is_external_rest_manual_submission(action, comparison)
        if status_filter == "需處理" and group in ("done", "future"):
            continue
        if status_filter == "已登打" and group != "done":
            continue
        if status_filter == "未返隊暫停" and group != "paused":
            continue
        if status_filter == "外勤休息手動" and not is_external_rest_manual:
            continue
        if status_filter == "人工確認" and group != "review":
            continue
        if status_filter == "尚未到點" and group != "future":
            continue
        if status_filter == "手動" and group != "manual":
            continue
        if status_filter == "疑似異動" and group != "adjust":
            continue
        if status_filter == "時間近似" and group != "near":
            continue
        comparison_text = audit_status_text(action, comparison)
        tone = "triggered" if group == "done" else "manual" if group in ("paused", "review", "adjust", "near", "manual") else "waiting"
        action_at = action_datetime(action, target_roc_date)
        actual_time = actual_record_time(comparison)
        if actual_time:
            detail_text = f"{detail_text or action_summary(action)}｜實際登打 {actual_time}"
        rows.append(
            (
                action_at,
                {
                    "taskIndex": index,
                    "timeText": format_action_time(action, target_roc_date),
                    "systemText": audit_kind_text,
                    "kindText": kind_text,
                    "detailText": detail_text or action_summary(action),
                    "peopleText": people_text,
                    "statusText": comparison_text,
                    "statusTone": tone,
                    "selected": False,
                    "actorText": person_short_label(action_actor, staff),
                    "targetText": target_short_label(action, staff),
                "comparisonText": comparison_text,
                "group": group,
                "fullDetailText": audit_detail_text(action, comparison),
            },
            )
        )
    rows.sort(key=lambda item: item[0])
    return [row for _action_at, row in rows]


def comparison_dates(
    actions: Sequence[Mapping[str, Any]],
    target_roc_date: str,
) -> set[str]:
    dates = {target_roc_date} if target_roc_date else set()
    dates.update(action_target_roc_date(action, target_roc_date) for action in actions if target_roc_date)
    return dates


def _rest_entry_matches(
    entry_rows: Sequence[str],
    action_date: str,
    action: Mapping[str, Any],
    *,
    allow_near: bool,
    near_minutes: int = 120,
    staff: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    fields = action.get("fields", {})
    if not isinstance(fields, Mapping):
        fields = {}
    reason = str(fields.get("領用事由及地點", "") or "")
    direction = str(fields.get("出或入", "") or "")
    system_time = str(fields.get("系統寫入時間", action.get("time", "")) or "")
    try:
        hour, minute = [int(part) for part in system_time.split(":", 1)]
        if hour >= 24:
            system_time = f"{hour % 24:02d}:{minute:02d}"
    except ValueError:
        pass
    target_name = str(staff.get(str(action.get("target", "")), {}).get("name", "") or "")
    acceptable_reasons = ("休息返隊", "返隊") if reason == "休息返隊" else (reason,)
    return [
        row
        for row in entry_rows
        if (not target_name or target_name in row)
        and (not direction or direction in row)
        and (not reason or any(value in row for value in acceptable_reasons))
        and row_has_time(row, action_date, system_time, allow_near=allow_near, near_minutes=near_minutes)
    ]


def _compare_rest_entry(
    actions: Sequence[Mapping[str, Any]],
    action: Mapping[str, Any],
    action_date: str,
    entry_rows: Sequence[str],
    target_roc_date: str,
    staff: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    fields = action.get("fields", {})
    if not isinstance(fields, Mapping):
        fields = {}
    if fields.get("領用事由及地點", "") == "休息返隊":
        rest_out_exists = False
        for candidate in actions:
            if candidate.get("kind") != "entry_log" or candidate.get("source") != "休息簽出":
                continue
            if str(candidate.get("target", "")) != str(action.get("target", "")):
                continue
            candidate_date = action_target_roc_date(candidate, target_roc_date)
            if candidate_date != action_date or _rest_entry_matches(
                entry_rows,
                action_date,
                candidate,
                allow_near=False,
                staff=staff,
            ) or _rest_entry_matches(
                entry_rows,
                action_date,
                candidate,
                allow_near=True,
                staff=staff,
            ):
                rest_out_exists = True
                break
        if not rest_out_exists:
            return {"compare": "未找到", "group": "todo", "matched": []}
    exact = _rest_entry_matches(entry_rows, action_date, action, allow_near=False, staff=staff)
    near = [] if exact else _rest_entry_matches(entry_rows, action_date, action, allow_near=True, staff=staff)
    if exact:
        return {"compare": "已存在", "group": "done", "matched": exact[:1]}
    if near:
        return {"compare": "時間近似", "group": "near", "matched": near[:1]}
    return {"compare": "未找到", "group": "todo", "matched": []}


def compare_submission_action(
    data: Mapping[str, Any],
    action: Mapping[str, Any],
    action_date: str,
    comparison_data: Mapping[str, Any],
    *,
    verify_saved: bool = False,
) -> dict[str, Any]:
    """Match only the action being submitted, with a short write-time tolerance."""

    today = data.get("today", {})
    yesterday = data.get("yesterday", {})
    today_staff = today.get("staff", {}) if isinstance(today, Mapping) else {}
    yesterday_staff = yesterday.get("staff", {}) if isinstance(yesterday, Mapping) else {}
    staff = {**yesterday_staff, **today_staff}
    current_action = dict(action)

    if is_external_or_rest_entry(current_action) and not verify_saved:
        return {"compare": "略過防重複比對", "group": "todo", "matched": []}

    if current_action.get("kind") == "entry_log":
        entry_source = comparison_data.get("visible_entry_rows", [])
        entry_rows = flatten_rows(entry_source or [], action_date)
        fields = current_action.get("fields", {})
        reason = fields.get("領用事由及地點", "") if isinstance(fields, Mapping) else ""
        if reason in ("休息", "休息返隊"):
            matches = _rest_entry_matches(
                entry_rows,
                action_date,
                current_action,
                allow_near=True,
                near_minutes=2,
                staff=staff,
            )
        else:
            matches = find_entry_matches(
                entry_rows,
                action_date,
                staff,
                current_action,
                allow_near=True,
                near_minutes=2,
            )
    elif current_action.get("kind") == "work_log":
        work_source = comparison_data.get("visible_work_rows", [])
        work_rows = flatten_rows(work_source or [], action_date)
        matches = (
            find_case_work_matches(work_rows, action_date, current_action, near_minutes=2)
            if current_action.get("source") == "案件工作審核"
            else find_work_matches(
                work_rows,
                action_date,
                staff,
                current_action,
                allow_near=True,
                near_minutes=2,
            )
        )
    else:
        matches = []

    if matches:
        return {"compare": "已存在", "group": "done", "matched": matches[:1]}
    return {"compare": "未找到", "group": "todo", "matched": []}


def build_schedule_comparisons(
    data: Mapping[str, Any],
    actions: Sequence[Mapping[str, Any]],
    comparison_data_by_date: Mapping[str, Mapping[str, Any]],
) -> dict[int, dict[str, Any]]:
    """Match planned actions to the already-captured visible duty-system rows."""

    target_date = str(data.get("target_date", "") or "")
    today = data.get("today", {})
    yesterday = data.get("yesterday", {})
    today_staff = today.get("staff", {}) if isinstance(today, Mapping) else {}
    yesterday_staff = yesterday.get("staff", {}) if isinstance(yesterday, Mapping) else {}
    staff = {**yesterday_staff, **today_staff}
    comparison_cache: dict[str, dict[str, list[str]]] = {}
    for action_date in comparison_dates(actions, target_date):
        comparison_data = comparison_data_by_date.get(action_date, {})
        entry_source = comparison_data.get("visible_entry_rows", data.get("visible_entry_rows", []))
        work_source = comparison_data.get("visible_work_rows", data.get("visible_work_rows", []))
        comparison_cache[action_date] = {
            "entry_rows": flatten_rows(entry_source or [], action_date),
            "work_rows": flatten_rows(work_source or [], action_date),
        }

    result: dict[int, dict[str, Any]] = {}
    external_targets: dict[str, set[str]] = {}
    for action in actions:
        if action.get("kind") != "entry_log" or not str(action.get("source", "")).startswith("外勤"):
            continue
        fields = action.get("fields", {})
        action_date = action_target_roc_date(action, target_date)
        key = f"{action_date}:{fields.get('系統寫入時間', action.get('time', ''))}:{fields.get('出或入', '')}"
        external_targets.setdefault(key, set()).add(
            str(staff.get(str(action.get("target", "")), {}).get("name", "") or "")
        )

    for index, action in enumerate(actions):
        fields = action.get("fields", {})
        action_date = action_target_roc_date(action, target_date)
        entry_rows = comparison_cache.get(action_date, {}).get("entry_rows", [])
        work_rows = comparison_cache.get(action_date, {}).get("work_rows", [])
        if action.get("kind") == "entry_log":
            if is_external_or_rest_entry(action):
                future = is_future_action(target_date, dict(action))
                result[index] = {
                    "compare": "尚未到點" if future else "略過防重複比對",
                    "group": "future" if future else "todo",
                    "matched": [],
                }
                continue
            reason = fields.get("領用事由及地點", "")
            if reason in ("休息", "休息返隊"):
                comparison = _compare_rest_entry(actions, action, action_date, entry_rows, target_date, staff)
                result[index] = (
                    comparison
                    if comparison.get("group") == "done" or not is_future_action(target_date, dict(action))
                    else {"compare": "尚未到點", "group": "future", "matched": []}
                )
            else:
                exact = find_entry_matches(entry_rows, action_date, staff, action, allow_near=False)
                arrival_exists = [] if exact else find_arrival_entry_exists(entry_rows, action_date, staff, action)
                near = [] if exact else find_entry_matches(entry_rows, action_date, staff, action, allow_near=True)
                if exact:
                    result[index] = {"compare": "已存在", "group": "done", "matched": exact[:1]}
                elif arrival_exists:
                    result[index] = {"compare": "已存在(時間不同)", "group": "done", "matched": arrival_exists[:1]}
                elif is_future_action(target_date, dict(action)):
                    result[index] = {"compare": "尚未到點", "group": "future", "matched": []}
                elif is_possible_handoff_adjustment(entry_rows, action_date, staff, action):
                    result[index] = {"compare": "可能臨時調整", "group": "adjust", "matched": []}
                elif near:
                    result[index] = {"compare": "時間近似", "group": "near", "matched": near[:1]}
                elif reason in ("到勤", "退勤", "休息後退勤"):
                    result[index] = {"compare": "未找到", "group": "todo", "matched": []}
                elif str(action.get("source", "")).startswith("外勤"):
                    result[index] = {"compare": "人工確認", "group": "review", "matched": []}
                else:
                    result[index] = {"compare": "未找到", "group": "todo", "matched": []}
        else:
            matches = (
                find_case_work_matches(work_rows, action_date, action)
                if action.get("source") == "案件工作審核"
                else find_work_matches(work_rows, action_date, staff, action)
            )
            if matches:
                result[index] = {"compare": "已存在", "group": "done", "matched": matches[:1]}
            elif is_future_action(target_date, dict(action)):
                result[index] = {"compare": "尚未到點", "group": "future", "matched": []}
            else:
                result[index] = {"compare": "未找到", "group": "todo", "matched": []}

    for index, action in enumerate(actions):
        if action.get("kind") != "entry_log" or not str(action.get("source", "")).startswith("外勤"):
            continue
        fields = action.get("fields", {})
        action_date = action_target_roc_date(action, target_date)
        key = f"{action_date}:{fields.get('系統寫入時間', action.get('time', ''))}:{fields.get('出或入', '')}"
        if result.get(index, {}).get("compare") == "人工確認" and external_targets.get(key):
            result[index]["compare"] = "外勤確認"
    return result
