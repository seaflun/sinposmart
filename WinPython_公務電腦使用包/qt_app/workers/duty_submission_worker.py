# -*- coding: utf-8 -*-
"""Qt worker for one duty-system submission request."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from app_core.duty_submission_service import (
    DutySubmissionExecutionError,
    DutySubmissionRequest,
    DutySubmissionResult,
    DutySubmissionService,
)


class DutySubmissionWorker(QObject):
    progress = Signal(int, str)
    succeeded = Signal(int, object)
    failed = Signal(int, int, str, str, str)
    finished = Signal(int)

    def __init__(
        self,
        request_id: int,
        service: DutySubmissionService,
        request: DutySubmissionRequest,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.service = service
        self.request = request

    @Slot()
    def run(self) -> None:
        action_index = self.request.action_index
        try:
            result = self.service.execute(
                self.request,
                status_callback=lambda message: self.progress.emit(self.request_id, message),
            )
        except DutySubmissionExecutionError as exc:
            self.failed.emit(
                self.request_id,
                action_index,
                str(exc),
                exc.error_code,
                str(exc.result_path or ""),
            )
        except Exception:
            self.failed.emit(
                self.request_id,
                action_index,
                "勤務系統登打失敗。",
                "unknown_error",
                "",
            )
        else:
            self.succeeded.emit(self.request_id, result)
        finally:
            self.request = DutySubmissionRequest("", "", 0, {"target_date": "", "actions": []})
            self.finished.emit(self.request_id)
