# -*- coding: utf-8 -*-
"""Qt worker adapter for the read-only update check."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from app_core.update_repository import UpdateCheckError, UpdateRepository


class UpdateCheckWorker(QObject):
    succeeded = Signal(int, object)
    failed = Signal(int, str)
    finished = Signal(int)

    def __init__(self, request_id: int, repository: UpdateRepository) -> None:
        super().__init__()
        self.request_id = request_id
        self.repository = repository

    @Slot()
    def run(self) -> None:
        try:
            info = self.repository.check()
        except UpdateCheckError as exc:
            self.failed.emit(self.request_id, str(exc))
        except Exception:
            self.failed.emit(self.request_id, "檢查更新失敗，請稍後重試。")
        else:
            self.succeeded.emit(self.request_id, info)
        finally:
            self.finished.emit(self.request_id)
