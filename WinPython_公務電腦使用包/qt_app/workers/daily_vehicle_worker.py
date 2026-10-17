# -*- coding: utf-8 -*-
"""Qt worker for daily vehicle automation."""

from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import QObject, Signal, Slot

from app_core.daily_vehicle_service import (
    DailyVehicleExecutionError,
    DailyVehicleValidationError,
    DailyVehicleRequest,
    DailyVehicleService,
)


class DailyVehicleWorker(QObject):
    progress = Signal(int, str)
    succeeded = Signal(int, str)
    failed = Signal(int, str)
    finished = Signal(int)

    def __init__(self, request_id: int, service: DailyVehicleService, request: DailyVehicleRequest) -> None:
        super().__init__()
        self.request_id = request_id
        self.service = service
        self.request = request
        self.completion_report: dict = {}

    @Slot()
    def run(self) -> None:
        stage = "preflight"
        self.completion_report = {}

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
        except (DailyVehicleExecutionError, DailyVehicleValidationError) as exc:
            self.failure_stage = getattr(exc, "failure_stage", stage)
            self._copy_completion_report(failure_reason="execution_unconfirmed")
            self.failed.emit(self.request_id, str(exc))
        except Exception:
            self.failure_stage = stage
            self._copy_completion_report(failure_reason="unexpected_error")
            self.failed.emit(self.request_id, "車輛保養清點失敗，請檢查網站狀態。")
        else:
            self._copy_completion_report()
            self.succeeded.emit(self.request_id, result)
        finally:
            self.request = DailyVehicleRequest("", "")
            self.finished.emit(self.request_id)

    def _copy_completion_report(self, *, failure_reason: str = "") -> None:
        report = getattr(self.service, "completion_report", {})
        self.completion_report = deepcopy(report) if isinstance(report, dict) else {}
        if failure_reason and self.completion_report:
            if self.completion_report.get("verified") is True or failure_reason == "unexpected_error":
                self.completion_report["reason_code"] = failure_reason
            self.completion_report["verified"] = False
