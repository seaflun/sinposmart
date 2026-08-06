# -*- coding: utf-8 -*-
"""UI-independent work-log default settings boundary."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from types import ModuleType
from typing import Any, Callable, Mapping


NUMERIC_FIELDS = (
    "radio_count",
    "emergency_vehicles_in_station",
    "emergency_vehicles_repair",
    "ems_case_vehicles",
    "fire_case_vehicles",
    "support_vehicles_in_station",
    "support_vehicles_out",
    "support_vehicles_repair",
    "rescue_equipment_in_station",
    "rescue_equipment_out",
    "tic_count",
)


class WorkLogSettingsValidationError(ValueError):
    """A safe local-settings validation message."""


class WorkLogSettingsError(RuntimeError):
    """A safe local-settings persistence failure."""


@dataclass(frozen=True)
class WorkLogSettings:
    values: Mapping[str, int]
    important_note: str
    preserved: Mapping[str, Any]


def load_automation_module() -> ModuleType:
    return importlib.import_module("duty_rehearsal")


class WorkLogSettingsService:
    def __init__(self, *, module_loader: Callable[[], ModuleType] = load_automation_module) -> None:
        self.module_loader = module_loader

    def load(self) -> WorkLogSettings:
        automation = self._automation()
        try:
            payload = automation.load_work_log_defaults()
        except Exception as exc:
            raise WorkLogSettingsError("工作紀錄預設內容無法讀取。") from exc
        return self._from_payload(payload)

    def defaults(self) -> WorkLogSettings:
        automation = self._automation()
        return self._from_payload(dict(automation.DEFAULT_WORK_LOG_DEFAULTS))

    def save(
        self,
        values: Mapping[str, Any],
        important_note: str,
        case_vehicle_counts: Mapping[str, Any] | None = None,
    ) -> WorkLogSettings:
        automation = self._automation()
        current = dict(automation.load_work_log_defaults())
        normalized = self._normalize_values(values)
        current.update(normalized)
        current["important_note"] = str(important_note or "").strip()
        existing_overrides = current.get("case_vehicle_overrides", {})
        overrides = {
            str(date_key): dict(date_values)
            for date_key, date_values in existing_overrides.items()
            if isinstance(date_values, Mapping)
        } if isinstance(existing_overrides, Mapping) else {}
        for key, raw_count in (case_vehicle_counts or {}).items():
            normalized_key = str(key or "").strip()
            date_key = normalized_key.split("|", 1)[0]
            if not normalized_key or not date_key:
                continue
            try:
                count = int(str(raw_count).strip())
            except (TypeError, ValueError) as exc:
                raise WorkLogSettingsValidationError("案件車數必須是非負整數。") from exc
            if count < 0:
                raise WorkLogSettingsValidationError("案件車數不能小於 0。")
            overrides.setdefault(date_key, {})[normalized_key] = count
        current["case_vehicle_overrides"] = overrides
        try:
            automation.save_work_log_defaults(current)
        except Exception as exc:
            raise WorkLogSettingsError("工作紀錄預設內容無法儲存。") from exc
        return self._from_payload(current)

    def preview(
        self,
        values: Mapping[str, Any],
        important_note: str,
        *,
        vehicle_out_count: int = 0,
    ) -> str:
        automation = self._automation()
        payload = dict(self.load().preserved)
        payload.update(self._normalize_values(values))
        payload["important_note"] = str(important_note or "").strip()
        try:
            return str(automation.work_handoff_description(payload, max(0, int(vehicle_out_count))))
        except Exception as exc:
            raise WorkLogSettingsError("工作紀錄預覽無法產生。") from exc

    def case_items(
        self,
        schedule_data: Mapping[str, Any],
        settings: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        target_date = str(schedule_data.get("target_date", "") or "").strip()
        if not target_date:
            return []
        automation = self._automation()
        yesterday = self._case_records(automation, schedule_data.get("yesterday_cases", []))
        current = self._case_records(automation, schedule_data.get("cases", []))
        try:
            yesterday_date = automation.roc_date_after(target_date, -1)
            items = automation.unreturned_case_vehicle_items(
                yesterday,
                dict(settings),
                yesterday_date,
            )
            items.extend(
                automation.unreturned_case_vehicle_items(
                    current,
                    dict(settings),
                    target_date,
                )
            )
        except Exception as exc:
            raise WorkLogSettingsError("未返隊案件車數無法載入。") from exc
        return [dict(item) for item in items if isinstance(item, Mapping)]

    def _automation(self) -> ModuleType:
        try:
            return self.module_loader()
        except Exception as exc:
            raise WorkLogSettingsError("工作紀錄設定模組無法載入。") from exc

    def _from_payload(self, payload: Mapping[str, Any]) -> WorkLogSettings:
        return WorkLogSettings(
            values=self._normalize_values(payload),
            important_note=str(payload.get("important_note", "") or ""),
            preserved=dict(payload),
        )

    @staticmethod
    def _case_records(automation: ModuleType, raw_items: Any) -> list[Any]:
        records: list[Any] = []
        case_type = automation.CaseRecord
        for item in raw_items if isinstance(raw_items, (list, tuple)) else ():
            if isinstance(item, case_type):
                records.append(item)
            elif isinstance(item, Mapping):
                records.append(
                    case_type(
                        report_time=str(item.get("report_time", "") or ""),
                        return_time=str(item.get("return_time", "") or ""),
                        category=str(item.get("category", "") or ""),
                        raw=[str(value) for value in item.get("raw", [])],
                    )
                )
        return records

    @staticmethod
    def _normalize_values(values: Mapping[str, Any]) -> dict[str, int]:
        normalized: dict[str, int] = {}
        for key in NUMERIC_FIELDS:
            try:
                value = int(str(values.get(key, 0)).strip())
            except (TypeError, ValueError) as exc:
                raise WorkLogSettingsValidationError("數量欄位必須是非負整數。") from exc
            if value < 0:
                raise WorkLogSettingsValidationError("數量欄位不能小於 0。")
            normalized[key] = value
        return normalized
