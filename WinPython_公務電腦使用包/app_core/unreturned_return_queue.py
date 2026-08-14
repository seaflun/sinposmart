# -*- coding: utf-8 -*-
"""Persistent, credential-free queue for paused external-return records."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from app_core.duty_task_projection import action_completion_key


QUEUE_FILENAME = "unreturned_return_queue.json"
RETENTION = timedelta(hours=18)
BRIDGE_HISTORY_RETENTION = timedelta(hours=36)
CURRENT_SHIFT_RETRY = timedelta(minutes=5)
HANDOVER_RETRY = timedelta(minutes=10)


class UnreturnedReturnQueue:
    """Keep unfinished return records across schedule reloads and application restarts."""

    def __init__(
        self,
        runtime_output_dir: Path,
        *,
        now_factory: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.path = Path(runtime_output_dir) / QUEUE_FILENAME
        self.now_factory = now_factory
        self._records = self._load_records()
        self._inflight_ids: set[str] = set()

    def active_records(self) -> list[dict[str, Any]]:
        """Return active records without exposing the queue's mutable backing store."""

        return [
            dict(record)
            for record in self._records.values()
            if record.get("record_type") in ("single", "handoff_group")
        ]

    def bridge_history_records(self) -> list[dict[str, Any]]:
        """Return resolved bridge records that still suppress skipped handoff actions."""

        return [
            dict(record)
            for record in self._records.values()
            if record.get("record_type") == "bridge_history"
        ]

    def get(self, queue_id: str) -> dict[str, Any] | None:
        record = self._records.get(str(queue_id or ""))
        return dict(record) if record is not None else None

    def pause(
        self,
        action: Mapping[str, Any],
        schedule_data: Mapping[str, Any],
        *,
        owner_actor_no: str,
        now: datetime | None = None,
        unreturned_entry_at: str = "",
    ) -> tuple[dict[str, Any], bool]:
        """Store one paused action once and return whether it was newly created."""

        current = now or self.now_factory()
        completion_key = action_completion_key(action)
        source_target_date = str(schedule_data.get("target_date") or "").strip()
        normalized_entry_at = str(unreturned_entry_at or "").strip()
        existing = next(
            (
                record
                for record in self._records.values()
                if record.get("completion_key") == completion_key
                and record.get("source_target_date") == source_target_date
            ),
            None,
        )
        if existing is not None:
            if normalized_entry_at and not existing.get("unreturned_entry_at"):
                existing["unreturned_entry_at"] = normalized_entry_at
                self._write_records()
            return dict(existing), False
        queue_id = uuid4().hex
        record = {
            "queue_id": queue_id,
            "record_type": "single",
            "completion_key": completion_key,
            "source_target_date": source_target_date,
            "unreturned_entry_at": normalized_entry_at,
            "action": self._json_mapping(action),
            "schedule_context": self._schedule_context(schedule_data),
            "origin_actor_no": str(owner_actor_no or "").strip(),
            "last_owner_actor_no": str(owner_actor_no or "").strip(),
            "first_paused_at": self._timestamp(current),
            "last_attempt_at": self._timestamp(current),
            "next_retry_at": self._timestamp(current + CURRENT_SHIFT_RETRY),
            "expires_at": self._timestamp(current + RETENTION),
            "retry_interval_minutes": int(CURRENT_SHIFT_RETRY.total_seconds() // 60),
        }
        self._records[queue_id] = record
        self._write_records()
        return dict(record), True

    def pause_group(
        self,
        actions: Sequence[Mapping[str, Any]],
        schedule_data: Mapping[str, Any],
        *,
        owner_actor_no: str,
        now: datetime | None = None,
        unreturned_entry_at: str = "",
    ) -> tuple[dict[str, Any], bool]:
        """Store one handoff group so every related item pauses and retries together."""

        group_actions = [self._json_mapping(action) for action in actions if isinstance(action, Mapping)]
        if not group_actions:
            raise ValueError("未返隊交接群組沒有可處理的任務。")
        current = now or self.now_factory()
        completion_keys = [action_completion_key(action) for action in group_actions]
        source_target_date = str(schedule_data.get("target_date") or "").strip()
        normalized_entry_at = str(unreturned_entry_at or "").strip()
        existing = next(
            (
                record
                for record in self._records.values()
                if record.get("record_type") == "handoff_group"
                and record.get("source_target_date") == source_target_date
                and list(record.get("completion_keys", [])) == completion_keys
            ),
            None,
        )
        if existing is not None:
            if normalized_entry_at and not existing.get("unreturned_entry_at"):
                existing["unreturned_entry_at"] = normalized_entry_at
                self._write_records()
            return dict(existing), False
        queue_id = uuid4().hex
        record = {
            "queue_id": queue_id,
            "record_type": "handoff_group",
            "completion_keys": completion_keys,
            "completed_keys": [],
            "completed_statuses": {},
            "source_target_date": source_target_date,
            "unreturned_entry_at": normalized_entry_at,
            "actions": group_actions,
            "schedule_context": self._schedule_context(schedule_data),
            "origin_actor_no": str(owner_actor_no or "").strip(),
            "last_owner_actor_no": str(owner_actor_no or "").strip(),
            "first_paused_at": self._timestamp(current),
            "last_attempt_at": self._timestamp(current),
            "next_retry_at": self._timestamp(current + CURRENT_SHIFT_RETRY),
            "expires_at": self._timestamp(current + RETENTION),
            "retry_interval_minutes": int(CURRENT_SHIFT_RETRY.total_seconds() // 60),
        }
        self._records[queue_id] = record
        self._write_records()
        return dict(record), True

    @staticmethod
    def record_actions(record: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Return every action represented by either a legacy or grouped record."""

        actions = record.get("actions", [])
        if isinstance(actions, list) and actions:
            return [dict(action) for action in actions if isinstance(action, Mapping)]
        action = record.get("action")
        return [dict(action)] if isinstance(action, Mapping) else []

    @classmethod
    def incomplete_actions(cls, record: Mapping[str, Any]) -> list[dict[str, Any]]:
        completed = {str(key) for key in record.get("completed_keys", [])}
        return [
            action
            for action in cls.record_actions(record)
            if action_completion_key(action) not in completed
        ]

    def complete_action(
        self,
        queue_id: str,
        action: Mapping[str, Any],
        status: str,
        *,
        completion_key: str = "",
    ) -> tuple[dict[str, Any] | None, bool]:
        """Record one component result and resolve a group only after every component succeeds."""

        queue_id = str(queue_id or "")
        record = self._records.get(queue_id)
        if record is None:
            return None, False
        if status not in ("submitted", "skipped_duplicate"):
            return self.defer(queue_id, str(record.get("last_owner_actor_no") or "")), False
        if record.get("record_type") != "handoff_group":
            return self.resolve(queue_id), True

        completion_key = str(completion_key or action_completion_key(action))
        completed = {str(key) for key in record.get("completed_keys", [])}
        completed.add(completion_key)
        record["completed_keys"] = sorted(completed)
        completed_statuses = dict(record.get("completed_statuses", {}))
        completed_statuses[completion_key] = status
        record["completed_statuses"] = completed_statuses
        expected = {str(key) for key in record.get("completion_keys", [])}
        if expected and expected.issubset(completed):
            if record.get("bridge_history"):
                record["record_type"] = "bridge_history"
                record["resolved_at"] = self._timestamp(self.now_factory())
                self._inflight_ids.discard(queue_id)
                self._write_records()
                return dict(record), True
            return self.resolve(queue_id), True
        self._write_records()
        return dict(record), False

    def bridge_handoff_group(
        self,
        queue_id: str,
        actions: Sequence[Mapping[str, Any]],
        schedule_data: Mapping[str, Any],
        *,
        bridge_at: datetime,
        skipped_actor_nos: Sequence[str],
        incoming_actor_nos: Sequence[str],
        skipped_action_keys: Sequence[str],
    ) -> dict[str, Any] | None:
        """Replace an untouched paused handoff with its scheduled bridge group."""

        record = self._records.get(str(queue_id or ""))
        if (
            record is None
            or record.get("record_type") != "handoff_group"
            or record.get("completed_keys")
        ):
            return None
        bridge_actions = [self._json_mapping(action) for action in actions if isinstance(action, Mapping)]
        if not bridge_actions:
            return None
        history = list(record.get("bridge_history", []))
        history.append(
            {
                "bridged_at": self._timestamp(bridge_at),
                "skipped_actor_nos": [str(actor_no or "").strip() for actor_no in skipped_actor_nos],
                "incoming_actor_nos": [str(actor_no or "").strip() for actor_no in incoming_actor_nos],
                "skipped_action_keys": [str(key or "").strip() for key in skipped_action_keys],
            }
        )
        record["actions"] = bridge_actions
        record["completion_keys"] = [action_completion_key(action) for action in bridge_actions]
        record["completed_keys"] = []
        record["completed_statuses"] = {}
        record["schedule_context"] = self._schedule_context(schedule_data)
        record["bridge_history"] = history
        self._write_records()
        return dict(record)

    def claim_due(self, actor_no: str, *, now: datetime | None = None) -> dict[str, Any] | None:
        """Claim one due record and schedule its next safe retry window."""

        current = now or self.now_factory()
        candidates = [
            record
            for record in self._records.values()
            if record.get("record_type") in ("single", "handoff_group")
            if record.get("queue_id") not in self._inflight_ids
            and self._parse_timestamp(record.get("next_retry_at")) <= current
        ]
        if not candidates:
            return None
        record = min(candidates, key=lambda value: str(value.get("next_retry_at", "")))
        queue_id = str(record["queue_id"])
        interval = self.retry_interval(record, actor_no)
        record["last_owner_actor_no"] = str(actor_no or "").strip()
        record["last_attempt_at"] = self._timestamp(current)
        record["next_retry_at"] = self._timestamp(current + interval)
        record["retry_interval_minutes"] = int(interval.total_seconds() // 60)
        self._inflight_ids.add(queue_id)
        self._write_records()
        return dict(record)

    def claim_manual(self, queue_id: str, actor_no: str, *, now: datetime | None = None) -> dict[str, Any] | None:
        """Claim a human-confirmed record without changing its fixed expiry point."""

        record = self._records.get(str(queue_id or ""))
        if record is None or str(queue_id) in self._inflight_ids:
            return None
        current = now or self.now_factory()
        record["last_owner_actor_no"] = str(actor_no or "").strip()
        record["last_attempt_at"] = self._timestamp(current)
        record["next_retry_at"] = self._timestamp(current + self.retry_interval(record, actor_no))
        record["retry_interval_minutes"] = int(self.retry_interval(record, actor_no).total_seconds() // 60)
        self._inflight_ids.add(str(queue_id))
        self._write_records()
        return dict(record)

    def defer(self, queue_id: str, actor_no: str, *, now: datetime | None = None) -> dict[str, Any] | None:
        """Release a failed attempt and retain the record until its next retry window."""

        record = self._records.get(str(queue_id or ""))
        if record is None:
            return None
        current = now or self.now_factory()
        interval = self.retry_interval(record, actor_no)
        record["last_owner_actor_no"] = str(actor_no or "").strip()
        record["last_attempt_at"] = self._timestamp(current)
        record["next_retry_at"] = self._timestamp(current + interval)
        record["retry_interval_minutes"] = int(interval.total_seconds() // 60)
        self._inflight_ids.discard(str(queue_id))
        self._write_records()
        return dict(record)

    def resolve(self, queue_id: str) -> dict[str, Any] | None:
        """Remove a completed record while returning a final immutable event snapshot."""

        queue_id = str(queue_id or "")
        record = self._records.pop(queue_id, None)
        self._inflight_ids.discard(queue_id)
        if record is not None:
            self._write_records()
        return dict(record) if record is not None else None

    def expire_due(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        """Discard records at the fixed 18-hour boundary and return expiry snapshots."""

        current = now or self.now_factory()
        expired_ids = [
            queue_id
            for queue_id, record in self._records.items()
            if record.get("record_type") in ("single", "handoff_group")
            if self._parse_timestamp(record.get("expires_at")) <= current
        ]
        expired = [dict(self._records.pop(queue_id)) for queue_id in expired_ids]
        for queue_id in expired_ids:
            self._inflight_ids.discard(queue_id)
        if expired:
            self._write_records()
        return expired

    def prune_bridge_history(self, *, now: datetime | None = None) -> None:
        """Discard resolved bridge history after it can no longer affect a fire day."""

        current = now or self.now_factory()
        expired_ids = [
            queue_id
            for queue_id, record in self._records.items()
            if record.get("record_type") == "bridge_history"
            and self._parse_timestamp(record.get("resolved_at")) + BRIDGE_HISTORY_RETENTION <= current
        ]
        if not expired_ids:
            return
        for queue_id in expired_ids:
            self._records.pop(queue_id, None)
            self._inflight_ids.discard(queue_id)
        self._write_records()

    @staticmethod
    def retry_interval(record: Mapping[str, Any], actor_no: str) -> timedelta:
        """Use five minutes for the originating shift, ten minutes after handoff."""

        origin_actor_no = str(record.get("origin_actor_no") or "").strip()
        current_actor_no = str(actor_no or "").strip()
        return CURRENT_SHIFT_RETRY if origin_actor_no and origin_actor_no == current_actor_no else HANDOVER_RETRY

    def _load_records(self) -> dict[str, dict[str, Any]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError):
            return {}
        if not isinstance(raw, list):
            return {}
        records: dict[str, dict[str, Any]] = {}
        for value in raw:
            if not isinstance(value, Mapping):
                continue
            queue_id = str(value.get("queue_id") or "").strip()
            if not queue_id or not self.record_actions(value):
                continue
            records[queue_id] = dict(value)
        return records

    def _write_records(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(list(self._records.values()), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary_path, self.path)

    @staticmethod
    def _json_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
        return json.loads(json.dumps(dict(value), ensure_ascii=False, default=str))

    @classmethod
    def _schedule_context(cls, schedule_data: Mapping[str, Any]) -> dict[str, Any]:
        context: dict[str, Any] = {}
        for key in ("today", "yesterday"):
            day = schedule_data.get(key, {})
            if isinstance(day, Mapping):
                staff = day.get("staff", {})
                if isinstance(staff, Mapping):
                    context[key] = {"staff": cls._json_mapping(staff)}
        return context

    @staticmethod
    def _timestamp(value: datetime) -> str:
        return value.isoformat(timespec="seconds")

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime:
        try:
            return datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return datetime.min
