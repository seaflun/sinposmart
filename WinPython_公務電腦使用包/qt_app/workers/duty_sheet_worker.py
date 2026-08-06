# -*- coding: utf-8 -*-
"""Qt worker for the native duty-sheet tool."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from app_core.duty_sheet_service import DutySheetExecutionError, DutySheetRequest, DutySheetService


class DutySheetWorker(QObject):
    progress = Signal(int, str)
    succeeded = Signal(int, str)
    failed = Signal(int, str)
    finished = Signal(int)

    def __init__(self, request_id: int, service: DutySheetService, request: DutySheetRequest) -> None:
        super().__init__()
        self.request_id = request_id
        self.service = service
        self.request = request

    @Slot()
    def run(self) -> None:
        stage = "preflight"

        def update_stage(value: str) -> None:
            nonlocal stage
            stage = value

        try:
            try:
                result = self.service.execute(
                    self.request,
                    status_callback=lambda message: self.progress.emit(self.request_id, message),
                    stage_callback=update_stage,
                )
            except TypeError as exc:
                if "stage_callback" not in str(exc):
                    raise
                result = self.service.execute(
                    self.request,
                    status_callback=lambda message: self.progress.emit(self.request_id, message),
                )
        except DutySheetExecutionError as exc:
            self.failure_stage = getattr(exc, "failure_stage", stage)
            self.failed.emit(self.request_id, str(exc))
        except Exception:
            self.failure_stage = stage
            self.failed.emit(self.request_id, "勤務表登打失敗，請檢查輸入與網站狀態。")
        else:
            self.succeeded.emit(self.request_id, result)
        finally:
            self.request = DutySheetRequest("", "", "", "", "", "", "", "", False)
            self.finished.emit(self.request_id)
