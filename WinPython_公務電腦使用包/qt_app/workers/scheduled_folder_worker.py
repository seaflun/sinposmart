# -*- coding: utf-8 -*-
"""Qt worker for scheduled Windows folder presentation."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from app_core.scheduled_folder_service import ScheduledFolderService


class ScheduledFolderWorker(QObject):
    failed = Signal(int)
    finished = Signal(int)

    def __init__(
        self,
        request_id: int,
        service: ScheduledFolderService,
        folder: Path,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.service = service
        self.folder = Path(folder)

    @Slot()
    def run(self) -> None:
        try:
            self.service.open(self.folder)
        except Exception:
            self.failed.emit(self.request_id)
        finally:
            self.finished.emit(self.request_id)
