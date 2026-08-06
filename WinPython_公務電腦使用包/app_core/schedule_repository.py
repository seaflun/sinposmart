# -*- coding: utf-8 -*-
"""Read-only access to generated SinpoSmart duty schedule JSON files."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app_core.duty_task_projection import (
    build_schedule_comparisons,
    comparison_dates,
)


class ScheduleLoadError(RuntimeError):
    """Raised when a schedule exists but cannot be safely loaded."""


@dataclass(frozen=True)
class ScheduleSnapshot:
    path: Path | None
    data: dict[str, Any]
    target_roc_date: str
    comparisons: dict[int, dict[str, Any]] = field(default_factory=dict)
    comparison_data: dict[str, dict[str, Any]] = field(default_factory=dict)
    schedule_data_by_date: dict[str, dict[str, Any]] = field(default_factory=dict)
    authenticated_actor_no: str = ""
    authenticated_actor_name: str = ""

    @property
    def found(self) -> bool:
        return self.path is not None


def business_roc_date(now: datetime | None = None) -> str:
    now = now or datetime.now()
    business_date = now.date() if now.hour >= 8 else now.date() - timedelta(days=1)
    return f"{business_date.year - 1911:03d}{business_date.month:02d}{business_date.day:02d}"


class ScheduleRepository:
    def __init__(self, runtime_output_dir: Path) -> None:
        self.runtime_output_dir = Path(runtime_output_dir)
        self.schedule_dir = self.runtime_output_dir / "schedule"
        self.comparison_dir = self.runtime_output_dir / "comparison"
        self.rehearsal_dir = self.runtime_output_dir / "rehearsal"

    def schedule_path(self, target_roc_date: str) -> Path:
        return self.schedule_dir / f"schedule_output_{target_roc_date}.json"

    def rehearsal_path(self, target_roc_date: str) -> Path:
        return self.rehearsal_dir / f"rehearsal_output_{target_roc_date}.json"

    def comparison_path(self, target_roc_date: str) -> Path:
        return self.comparison_dir / f"comparison_output_{target_roc_date}.json"

    def available_dates(self, *, max_roc_date: str = "") -> list[str]:
        """Return legacy audit-date choices from saved schedule artifacts."""

        limit = str(max_roc_date or "").strip()
        values: set[str] = set()
        for directory, pattern in (
            (self.schedule_dir, "schedule_output_*.json"),
            (self.rehearsal_dir, "rehearsal_output_*.json"),
        ):
            if not directory.is_dir():
                continue
            for path in directory.glob(pattern):
                value = path.stem.rsplit("_", 1)[-1]
                if len(value) == 7 and value.isdigit() and (not limit or value <= limit):
                    values.add(value)
        return sorted(values)

    def path_for_date(self, target_roc_date: str) -> Path | None:
        schedule = self.schedule_path(target_roc_date)
        if schedule.is_file():
            return schedule
        rehearsal = self.rehearsal_path(target_roc_date)
        return rehearsal if rehearsal.is_file() else None

    def load_for_date(self, target_roc_date: str) -> ScheduleSnapshot:
        target_roc_date = str(target_roc_date or "").strip()
        path = self.path_for_date(target_roc_date)
        if path is None:
            return ScheduleSnapshot(None, {}, target_roc_date)
        return self._load_path(path, expected_target_date=target_roc_date)

    def load_path(self, path: Path) -> ScheduleSnapshot:
        path = Path(path)
        if not path.is_file():
            raise ScheduleLoadError("選取的預演檔不存在。")
        return self._load_path(path)

    def _load_path(
        self,
        path: Path,
        *,
        expected_target_date: str = "",
    ) -> ScheduleSnapshot:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ScheduleLoadError(f"排程資料無法讀取：{path.name}") from exc
        if not isinstance(payload, dict):
            raise ScheduleLoadError(f"排程資料格式錯誤：{path.name}")
        actions = payload.get("actions", [])
        if not isinstance(actions, list):
            raise ScheduleLoadError(f"排程 actions 格式錯誤：{path.name}")
        normalized_actions: list[dict[str, Any]] = []
        for action in actions:
            if not isinstance(action, dict) or not isinstance(action.get("fields", {}), dict):
                raise ScheduleLoadError(f"排程 action 格式錯誤：{path.name}")
            normalized = dict(action)
            normalized.setdefault("kind", "")
            normalized.setdefault("time", "")
            normalized.setdefault("actor", "")
            normalized.setdefault("target", "")
            normalized.setdefault("fields", {})
            normalized_actions.append(normalized)
        actions = normalized_actions
        payload["actions"] = actions
        payload_target = str(payload.get("target_date", "") or "").strip()
        target_roc_date = payload_target or str(expected_target_date or "").strip()
        if not (len(target_roc_date) == 7 and target_roc_date.isdigit()):
            raise ScheduleLoadError(f"排程資料缺少正確日期：{path.name}")
        if expected_target_date and payload_target and payload_target != expected_target_date:
            raise ScheduleLoadError(f"排程日期不一致：{path.name}")
        payload["target_date"] = target_roc_date
        comparison_data = {
            action_date: self._load_comparison_data(action_date)
            for action_date in comparison_dates(actions, payload["target_date"])
        }
        comparisons = build_schedule_comparisons(payload, actions, comparison_data)
        return ScheduleSnapshot(
            path,
            payload,
            target_roc_date,
            comparisons,
            comparison_data=comparison_data,
            schedule_data_by_date={target_roc_date: payload},
        )

    def load_current(self, now: datetime | None = None) -> ScheduleSnapshot:
        return self.load_for_date(business_roc_date(now))

    def _load_comparison_data(self, target_roc_date: str) -> dict[str, Any]:
        path = self.comparison_path(target_roc_date)
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ScheduleLoadError(f"比對資料無法讀取：{path.name}") from exc
        if not isinstance(payload, dict):
            raise ScheduleLoadError(f"比對資料格式錯誤：{path.name}")
        return payload
