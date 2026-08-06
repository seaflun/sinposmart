# -*- coding: utf-8 -*-
"""QML-facing catalog and safe launcher for SinpoSmart tools."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Callable
from uuid import uuid4

from PySide6.QtCore import QObject, Property, Signal, Slot

from app_core.schedule_repository import business_roc_date
from qt_app.models.tool_model import ToolListModel, ToolUsageListModel


TOOL_CATALOG = (
    {
        "toolId": "duty_sheet",
        "label": "勤務表登打",
        "description": "每日勤務表登打與送出前確認",
        "statusText": "原生表單可用",
        "tone": "ready",
        "available": True,
    },
    {
        "toolId": "daily_vehicle",
        "label": "車輛保養清點",
        "description": "車輛、器材與保養資料清點",
        "statusText": "原生確認流程可用",
        "tone": "ready",
        "available": True,
    },
    {
        "toolId": "rest_time",
        "label": "休息時間登打",
        "description": "依勤務表登打休息時間",
        "statusText": "原生表單可用",
        "tone": "ready",
        "available": True,
    },
    {
        "toolId": "monthly_base",
        "label": "勤務基準表登打",
        "description": "每月勤務基準資料登打",
        "statusText": "原生表單可用",
        "tone": "ready",
        "available": True,
    },
    {
        "toolId": "rescue_video",
        "label": "行車紀錄器（BETA）",
        "description": "預覽分類結果，核對後複製並清理記憶卡",
        "statusText": "原生表單可用",
        "tone": "ready",
        "available": True,
    },
)
MONTHLY_TOOL_IDS = {"rest_time", "monthly_base"}
TOOL_USAGE_RESULT_LABELS = {
    "duty_sheet": "勤務表",
    "daily_vehicle": "車輛保養清點",
    "rest_time": "休息時間",
    "monthly_base": "勤務基準表",
}


class ToolController(QObject):
    statusChanged = Signal()
    errorOccurred = Signal(str)
    usageChanged = Signal(str)

    def __init__(
        self,
        package_root: Path,
        *,
        now_factory: Callable[[], datetime] = datetime.now,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._package_root = Path(package_root)
        self._now_factory = now_factory
        self._usage_path = self._package_root / "runtime_outputs" / "tool_usage_history.json"
        self._usage_history = self._load_usage_history()
        self._active_usage_ids: dict[str, str] = {}
        self._usage_models: dict[str, ToolUsageListModel] = {}
        self._usage_filters: dict[str, tuple[str, str, str, bool]] = {}
        self._status_text = "工具中心就緒"
        self._model = ToolListModel(TOOL_CATALOG, self)
        self._refresh_availability()

    @Property(QObject, constant=True)
    def model(self) -> ToolListModel:
        return self._model

    @Property(str, notify=statusChanged)
    def statusText(self) -> str:
        return self._status_text

    @Slot(str)
    def launch(self, tool_id: str) -> None:
        tool_id = str(tool_id or "").strip()
        tool = self._model.tool(tool_id)
        if tool is None:
            self._set_error("找不到指定工具。")
            return
        if not tool.get("available"):
            self._set_error(f"{tool['label']}仍在 PySide6 原生表單遷移中。")
            return
        self._set_error(f"{tool['label']}請由工具中心的原生 QML 流程開啟。")

    @Slot(str, result="QVariantMap")
    def usage(self, tool_id: str) -> dict[str, str]:
        tool_id = str(tool_id or "").strip()
        latest = next(
            (
                entry
                for entry in reversed(self._usage_history)
                if entry.get("tool_name") == tool_id and entry.get("report") in ("已完成", "失敗")
            ),
            {},
        )
        if not latest:
            return {
                "time": "尚無紀錄",
                "people": "尚無紀錄",
                "report": "尚無執行紀錄",
                "tone": "neutral",
            }
        report = str(latest.get("report", "") or "").strip()
        people = str(latest.get("operator", "") or latest.get("people", "") or "").strip()
        return {
            "time": str(latest.get("time", "尚無紀錄") or "尚無紀錄"),
            "people": people or "舊紀錄未保存操作人員",
            "report": self._result_text(tool_id, latest, report, include_failure_context=True),
            "tone": "error" if report == "失敗" else "success",
        }

    @Slot(str, str, str, str, bool, result=QObject)
    def usageModel(
        self,
        tool_id: str,
        actor_no: str,
        user_id: str,
        display_name: str,
        current_operator_only: bool,
    ) -> ToolUsageListModel:
        """Return the filtered last-use rows shown in one tool side panel."""

        normalized_tool_id = str(tool_id or "").strip()
        model = self._usage_models.get(normalized_tool_id)
        if model is None:
            model = ToolUsageListModel(self)
            self._usage_models[normalized_tool_id] = model
        usage_filter = (
            str(actor_no or "").strip(),
            str(user_id or "").strip(),
            str(display_name or "").strip(),
            bool(current_operator_only),
        )
        self._usage_filters[normalized_tool_id] = usage_filter
        model.replace_rows(self._usage_rows(normalized_tool_id, *usage_filter))
        return model

    def record_started(
        self,
        tool_id: str,
        tool_label: str,
        operator: str,
        usage_period: str = "",
        *,
        actor_no: str = "",
        user_id: str = "",
    ) -> None:
        tool_id = str(tool_id or "").strip()
        if not tool_id:
            return
        now = self._now_factory()
        current_business_date = business_roc_date(now)
        period_digits = "".join(character for character in str(usage_period) if character.isdigit())
        normalized_period = (
            period_digits[:5]
            if tool_id in MONTHLY_TOOL_IDS and len(period_digits) >= 5
            else current_business_date[:5]
            if tool_id in MONTHLY_TOOL_IDS
            else period_digits[:7]
            if len(period_digits) == 7
            else current_business_date
        )
        entry_id = uuid4().hex
        self._active_usage_ids[tool_id] = entry_id
        operator = str(operator or "").strip() or "目前登入人員"
        self._usage_history.append(
            {
                "id": entry_id,
                "time": now.strftime("%Y-%m-%d %H:%M"),
                "business_roc_date": current_business_date,
                "usage_period": normalized_period,
                "tool_name": tool_id,
                "tool_label": str(tool_label or "工具"),
                "people": operator,
                "operator": operator,
                "report": "",
            }
        )
        normalized_actor_no = str(actor_no or "").strip()
        normalized_user_id = str(user_id or "").strip()
        if normalized_actor_no:
            self._usage_history[-1]["actor_no"] = normalized_actor_no
        if normalized_user_id:
            self._usage_history[-1]["user_id"] = normalized_user_id
        self._save_usage_history()
        self._refresh_usage_model(tool_id)
        self.usageChanged.emit(tool_id)

    def record_finished(self, tool_id: str, status: str, result: str = "") -> None:
        tool_id = str(tool_id or "").strip()
        entry_id = self._active_usage_ids.pop(tool_id, "")
        report = {"completed": "已完成", "failed": "失敗"}.get(str(status or ""), str(status or ""))
        for entry in reversed(self._usage_history):
            if entry.get("id") != entry_id:
                continue
            entry["report"] = report
            date_match = re.search(r"(?<!\d)(\d{7})(?!\d)", str(result or ""))
            month_match = re.search(r"(?<!\d)(\d{3})年0?(\d{1,2})月", str(result or ""))
            if date_match is not None:
                entry["usage_period"] = date_match.group(1)
            elif month_match is not None:
                entry["usage_period"] = f"{month_match.group(1)}{int(month_match.group(2)):02d}"
            break
        self._save_usage_history()
        self._refresh_usage_model(tool_id)
        self.usageChanged.emit(tool_id)

    def _usage_rows(
        self,
        tool_id: str,
        actor_no: str,
        user_id: str,
        display_name: str,
        current_operator_only: bool,
    ) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        seen_people: set[str] = set()
        for entry in reversed(self._usage_history):
            if entry.get("tool_name") != tool_id:
                continue
            report = str(entry.get("report", "") or "").strip()
            if report not in ("已完成", "失敗"):
                continue
            if current_operator_only and not self._matches_operator(
                entry,
                actor_no,
                user_id,
                display_name,
            ):
                continue
            person_key = self._person_key(entry)
            if person_key in seen_people:
                continue
            seen_people.add(person_key)
            rows.append(
                {
                    "timeText": str(entry.get("time", "") or "—"),
                    "peopleText": str(
                        entry.get("operator", "") or entry.get("people", "") or "目前登入人員"
                    ),
                    "resultText": self._result_text(tool_id, entry, report),
                    "tone": "error" if report == "失敗" else "success",
                }
            )
            break
        return rows

    def _result_text(
        self,
        tool_id: str,
        entry: dict[str, str],
        report: str,
        *,
        include_failure_context: bool = False,
    ) -> str:
        usage_period = str(
            entry.get("usage_period", "") or entry.get("business_roc_date", "") or ""
        ).strip()
        if not usage_period:
            try:
                recorded_at = datetime.strptime(str(entry.get("time", "")), "%Y-%m-%d %H:%M")
                usage_period = business_roc_date(recorded_at)
            except ValueError:
                usage_period = business_roc_date(self._now_factory())
        period = usage_period[:5] if tool_id in MONTHLY_TOOL_IDS else usage_period[:7]
        tool_label = TOOL_USAGE_RESULT_LABELS.get(
            tool_id,
            str(entry.get("tool_label", "") or "工具"),
        )
        if report == "已完成":
            return f"{period} {tool_label}已登打完成"
        return f"{period} {tool_label}{report}" if include_failure_context else report

    def _refresh_usage_model(self, tool_id: str) -> None:
        normalized_tool_id = str(tool_id or "").strip()
        usage_filter = self._usage_filters.get(normalized_tool_id)
        model = self._usage_models.get(normalized_tool_id)
        if usage_filter is not None and model is not None:
            model.replace_rows(self._usage_rows(normalized_tool_id, *usage_filter))

    @staticmethod
    def _person_key(entry: dict[str, str]) -> str:
        entry_actor_no = ToolController._actor_key(str(entry.get("actor_no", "") or ""))
        display_name = str(entry.get("operator", "") or entry.get("people", "") or "").strip()
        return (
            entry_actor_no
            or ToolController._actor_key(display_name)
            or str(entry.get("user_id", "") or "").strip().casefold()
            or display_name
            or "目前登入人員"
        )

    @staticmethod
    def _matches_operator(
        entry: dict[str, str],
        actor_no: str,
        user_id: str,
        display_name: str,
    ) -> bool:
        entry_actor_no = str(entry.get("actor_no", "") or "").strip()
        entry_user_id = str(entry.get("user_id", "") or "").strip().casefold()
        entry_display_name = str(entry.get("operator", "") or entry.get("people", "") or "").strip()
        target_actor_key = ToolController._actor_key(actor_no)
        return bool(
            (target_actor_key and ToolController._actor_key(entry_actor_no) == target_actor_key)
            or (target_actor_key and ToolController._actor_key(entry_display_name) == target_actor_key)
            or (user_id and entry_user_id == user_id.casefold())
            or (display_name and entry_display_name == display_name)
        )

    @staticmethod
    def _actor_key(value: str) -> str:
        text = str(value or "").strip()
        if text.isdigit():
            return str(int(text))
        match = re.search(r"(?<!\d)(\d+)\s*番", text)
        if match is not None:
            return str(int(match.group(1)))
        return ""

    def _rescue_video_path(self) -> Path:
        return self._package_root / "rescue_video" / "救護影片分類GUI.py"

    def _refresh_availability(self) -> None:
        if not self._rescue_video_path().is_file():
            self._model.update_tool(
                "rescue_video",
                available=False,
                statusText="找不到工具檔案",
                tone="error",
            )

    def _load_usage_history(self) -> list[dict[str, str]]:
        try:
            payload = json.loads(self._usage_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return []
        if not isinstance(payload, list):
            return []
        return [dict(item) for item in payload if isinstance(item, dict)][-100:]

    def _save_usage_history(self) -> None:
        try:
            self._usage_path.parent.mkdir(parents=True, exist_ok=True)
            self._usage_path.write_text(
                json.dumps(self._usage_history[-100:], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            return

    def _set_error(self, message: str) -> None:
        self._status_text = message
        self.statusChanged.emit()
        self.errorOccurred.emit(message)
