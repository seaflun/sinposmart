# -*- coding: utf-8 -*-
"""Qt worker for operational events and duty-board synchronization."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from app_core.operational_sync_service import OperationalSyncService


class OperationalSyncWorker(QObject):
    finished = Signal(int)

    def __init__(
        self,
        request_id: int,
        service: OperationalSyncService,
        operation: str,
        *,
        record_type: str = "",
        fields: dict | None = None,
        schedule_data: dict | None = None,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.service = service
        self.operation = operation
        self.record_type = record_type
        self.fields = dict(fields or {})
        self.schedule_data = dict(schedule_data or {})

    @Slot()
    def run(self) -> None:
        try:
            if self.operation == "event":
                self._send_event()
            elif self.operation == "board":
                self._sync_board()
        except Exception:
            pass
        finally:
            self.fields = {}
            self.schedule_data = {}
            self.finished.emit(self.request_id)

    def _send_event(self) -> None:
        build_payload = getattr(self.service, "build_event_payload", None)
        send_payload = getattr(self.service, "send_event_payload", None)
        if callable(build_payload) and callable(send_payload):
            send_payload(build_payload(self.record_type, **self.fields))
            return
        self.service.enqueue_event(self.record_type, **self.fields)

    def _sync_board(self) -> None:
        sync_board = getattr(self.service, "sync_board", None)
        if callable(sync_board):
            sync_board(self.schedule_data)
            return
        self.service.sync_board_async(self.schedule_data)
