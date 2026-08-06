# -*- coding: utf-8 -*-
"""Qt worker adapter for read-only duty schedule loading."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from app_core.schedule_repository import ScheduleLoadError, ScheduleRepository


class ScheduleLoadWorker(QObject):
    succeeded = Signal(int, object)
    failed = Signal(int, str)
    finished = Signal(int)

    def __init__(
        self,
        request_id: int,
        repository: ScheduleRepository,
        preview_path: Path | None = None,
        target_roc_date: str = "",
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.repository = repository
        self.preview_path = Path(preview_path) if preview_path is not None else None
        self.target_roc_date = str(target_roc_date or "").strip()

    @Slot()
    def run(self) -> None:
        try:
            snapshot = (
                self.repository.load_path(self.preview_path)
                if self.preview_path is not None
                else self.repository.load_for_date(self.target_roc_date)
                if self.target_roc_date
                else self.repository.load_current()
            )
        except ScheduleLoadError as exc:
            self.failed.emit(self.request_id, str(exc))
        except Exception:
            self.failed.emit(self.request_id, "排程資料載入失敗，請稍後重試。")
        else:
            self.succeeded.emit(self.request_id, snapshot)
        finally:
            self.finished.emit(self.request_id)
