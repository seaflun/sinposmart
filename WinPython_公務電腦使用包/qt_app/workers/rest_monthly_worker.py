# -*- coding: utf-8 -*-
"""Qt worker for rest-time and monthly-base automation."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from app_core.rest_monthly_service import (
    MonthlyBaseRequest,
    RestMonthlyExecutionError,
    RestMonthlyService,
    RestTimeRequest,
)


class MonthlyBaseSourceWorker(QObject):
    succeeded = Signal(int, int, str)
    failed = Signal(int, str)
    finished = Signal(int)

    def __init__(self, request_id: int, service: RestMonthlyService) -> None:
        super().__init__()
        self.request_id = request_id
        self.service = service

    @Slot()
    def run(self) -> None:
        try:
            defaults = self.service.load_monthly_defaults()
        except RestMonthlyExecutionError as exc:
            self.failed.emit(self.request_id, str(exc))
        except Exception:
            self.failed.emit(
                self.request_id,
                "無法讀取 Google 試算表月份，請確認網路與試算表後重試。",
            )
        else:
            self.succeeded.emit(
                self.request_id,
                int(defaults.roc_year),
                str(defaults.selected_month),
            )
        finally:
            self.finished.emit(self.request_id)


class RestMonthlyWorker(QObject):
    progress = Signal(int, str, str)
    succeeded = Signal(int, str, str)
    failed = Signal(int, str, str)
    finished = Signal(int)

    def __init__(
        self,
        request_id: int,
        tool_id: str,
        service: RestMonthlyService,
        request: RestTimeRequest | MonthlyBaseRequest,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.tool_id = tool_id
        self.service = service
        self.request = request
        self.failure_stage = "unknown"
        self.failure_detail = ""

    @Slot()
    def run(self) -> None:
        stage = "preflight"

        def update_stage(value: str) -> None:
            nonlocal stage
            stage = value

        try:
            callback = lambda message: self.progress.emit(self.request_id, self.tool_id, message)
            if self.tool_id == "rest_time":
                try:
                    result = self.service.execute_rest(
                        self.request,
                        status_callback=callback,
                        stage_callback=update_stage,
                    )
                except TypeError as exc:
                    if "stage_callback" not in str(exc):
                        raise
                    result = self.service.execute_rest(self.request, status_callback=callback)
            else:
                try:
                    result = self.service.execute_monthly(
                        self.request,
                        status_callback=callback,
                        stage_callback=update_stage,
                    )
                except TypeError as exc:
                    if "stage_callback" not in str(exc):
                        raise
                    result = self.service.execute_monthly(self.request, status_callback=callback)
        except RestMonthlyExecutionError as exc:
            self.failure_stage = getattr(exc, "failure_stage", stage)
            self.failure_detail = str(getattr(exc, "failure_detail", "") or "")
            self.failed.emit(self.request_id, self.tool_id, str(exc))
        except Exception:
            self.failure_stage = stage
            self.failure_detail = ""
            self.failed.emit(self.request_id, self.tool_id, "登打失敗，請檢查輸入與網站狀態。")
        else:
            self.succeeded.emit(self.request_id, self.tool_id, result)
        finally:
            self.request = MonthlyBaseRequest("", "", "", 1, 1)
            self.finished.emit(self.request_id)
