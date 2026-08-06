# -*- coding: utf-8 -*-
"""QML-facing work-log default settings controller."""

from __future__ import annotations

from typing import Any, Mapping

from PySide6.QtCore import QObject, Property, Signal, Slot

from app_core.work_log_settings_service import (
    NUMERIC_FIELDS,
    WorkLogSettings,
    WorkLogSettingsError,
    WorkLogSettingsService,
    WorkLogSettingsValidationError,
)


_PRIMARY_WORK_LOG_VALUE_KEYS = (
    "radio_count",
    "emergency_vehicles_in_station",
    "emergency_vehicles_repair",
    "support_vehicles_in_station",
    "support_vehicles_out",
    "support_vehicles_repair",
    "rescue_equipment_in_station",
    "rescue_equipment_out",
    "tic_count",
)

_BUILTIN_WORK_LOG_VALUES = {
    "radio_count": 34,
    "emergency_vehicles_in_station": 6,
    "emergency_vehicles_repair": 0,
    "ems_case_vehicles": 1,
    "fire_case_vehicles": 2,
    "support_vehicles_in_station": 5,
    "support_vehicles_out": 0,
    "support_vehicles_repair": 0,
    "rescue_equipment_in_station": 2,
    "rescue_equipment_out": 0,
    "tic_count": 5,
}
_BUILTIN_WORK_LOG_NOTE = "（比如○○車輛或橡皮艇報修、防颱應變中心成立等事項）。"


class WorkLogSettingsController(QObject):
    stateChanged = Signal()
    settingsSaved = Signal()
    errorOccurred = Signal(str)

    def __init__(self, service: WorkLogSettingsService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._values: dict[str, int] = dict(_BUILTIN_WORK_LOG_VALUES)
        self._important_note = _BUILTIN_WORK_LOG_NOTE
        self._schedule_data: dict = {}
        self._case_items: list[dict] = []
        self._case_values: dict[str, int] = {}
        self._preview_text = ""
        self._status_text = "尚未載入設定"

    @Property("QVariantMap", notify=stateChanged)
    def values(self) -> dict[str, int]:
        return dict(self._values)

    @Property(str, notify=stateChanged)
    def importantNote(self) -> str:
        return self._important_note

    @Property("QVariantList", notify=stateChanged)
    def caseItems(self) -> list[dict]:
        return [dict(item) for item in self._case_items]

    @Property(str, notify=stateChanged)
    def previewText(self) -> str:
        return self._preview_text

    @Property(str, notify=stateChanged)
    def statusText(self) -> str:
        return self._status_text

    @Slot()
    def load(self) -> None:
        try:
            settings = self._service.load()
            status = "已載入工作紀錄預設內容"
        except WorkLogSettingsError:
            settings = self._source_defaults_or_builtin()
            status = "原工作紀錄設定無法讀取，已回填預設內容"
        if self._has_empty_primary_values(settings.values):
            settings = self._source_defaults_or_builtin(
                important_note=settings.important_note,
                preserved=settings.preserved,
            )
            status = "已回填工作紀錄預設內容"
        try:
            case_items = self._service.case_items(self._schedule_data, settings.preserved)
        except WorkLogSettingsError:
            case_items = []
            status += "；未返隊案件暫時無法載入"
        self._apply(
            settings.values,
            settings.important_note,
            status,
            case_items,
        )

    @Slot()
    def resetDefaults(self) -> None:
        settings = self._source_defaults_or_builtin()
        status = "已還原預設值，尚未儲存"
        try:
            case_items = self._service.case_items(self._schedule_data, settings.preserved)
        except WorkLogSettingsError:
            case_items = []
            status += "；未返隊案件暫時無法載入"
        self._apply(
            settings.values,
            settings.important_note,
            status,
            case_items,
        )

    @Slot(str, str)
    def setValue(self, key: str, value: str) -> None:
        if key not in self._values:
            return
        try:
            parsed = int(str(value).strip())
            if parsed < 0:
                raise ValueError
        except ValueError:
            self._set_error("數量欄位必須是非負整數。")
            return
        self._values[key] = parsed
        self._refresh_preview()

    @Slot(str)
    def setImportantNote(self, value: str) -> None:
        self._important_note = str(value or "")
        self._refresh_preview()

    @Slot(str, str)
    def setCaseVehicleCount(self, key: str, value: str) -> None:
        normalized_key = str(key or "").strip()
        if normalized_key not in self._case_values:
            return
        try:
            parsed = int(str(value).strip())
            if parsed < 0:
                raise ValueError
        except ValueError:
            self._set_error("案件車數必須是非負整數。")
            return
        self._case_values[normalized_key] = parsed
        for item in self._case_items:
            if item.get("key") == normalized_key:
                item["count"] = parsed
                break
        self._refresh_preview()

    @Slot(result=bool)
    def save(self) -> bool:
        try:
            settings = self._service.save(self._values, self._important_note, self._case_values)
            case_items = self._service.case_items(self._schedule_data, settings.preserved)
        except (WorkLogSettingsValidationError, WorkLogSettingsError) as exc:
            self._set_error(str(exc))
            return False
        self._apply(
            settings.values,
            settings.important_note,
            "已儲存工作紀錄預設內容",
            case_items,
        )
        self.settingsSaved.emit()
        return True

    def set_schedule_data(self, schedule_data: dict) -> None:
        self._schedule_data = dict(schedule_data or {})

    def _apply(self, values, important_note: str, status: str, case_items: list[dict]) -> None:
        self._values = {key: int(values.get(key, 0)) for key in NUMERIC_FIELDS}
        self._important_note = important_note
        self._case_items = [self._present_case_item(item) for item in case_items]
        self._case_values = {
            str(item["key"]): int(item["count"])
            for item in self._case_items
        }
        self._status_text = status
        self._refresh_preview(emit_signal=False)
        self.stateChanged.emit()

    def _refresh_preview(self, *, emit_signal: bool = True) -> None:
        try:
            self._preview_text = self._service.preview(
                self._values,
                self._important_note,
                vehicle_out_count=sum(self._case_values.values()),
            )
            if self._status_text.startswith("數量欄位"):
                self._status_text = "設定已變更，尚未儲存"
        except (WorkLogSettingsValidationError, WorkLogSettingsError) as exc:
            self._preview_text = ""
            self._status_text = str(exc)
        if emit_signal:
            self.stateChanged.emit()

    def _set_error(self, message: str) -> None:
        self._status_text = message
        self.stateChanged.emit()
        self.errorOccurred.emit(message)

    def _source_defaults_or_builtin(
        self,
        *,
        important_note: str = "",
        preserved: Mapping[str, Any] | None = None,
    ) -> WorkLogSettings:
        try:
            defaults = self._service.defaults()
        except WorkLogSettingsError:
            return WorkLogSettings(
                dict(_BUILTIN_WORK_LOG_VALUES),
                important_note or _BUILTIN_WORK_LOG_NOTE,
                dict(preserved or {}),
            )
        return WorkLogSettings(
            defaults.values,
            important_note or defaults.important_note,
            dict(preserved) if preserved is not None else defaults.preserved,
        )

    @staticmethod
    def _has_empty_primary_values(values: dict[str, int]) -> bool:
        return all(int(values.get(key, 0)) == 0 for key in _PRIMARY_WORK_LOG_VALUE_KEYS)

    @staticmethod
    def _present_case_item(item: dict) -> dict:
        date_text = str(item.get("date", "") or "")
        if len(date_text) == 7 and date_text.isdigit():
            date_text = f"{date_text[:3]}/{date_text[3:5]}/{date_text[5:7]}"
        report_time = str(item.get("report_time", "") or "")
        category = str(item.get("category", "案件") or "案件")
        count = max(0, int(item.get("count", item.get("default_count", 0)) or 0))
        return {
            "key": str(item.get("key", "") or ""),
            "label": " ".join(part for part in (date_text, report_time, category) if part),
            "count": count,
            "defaultCount": max(0, int(item.get("default_count", count) or 0)),
        }
