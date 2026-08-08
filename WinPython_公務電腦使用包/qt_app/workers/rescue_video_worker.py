# -*- coding: utf-8 -*-
"""Qt worker for rescue-video defaults and classification."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from app_core.rescue_video_service import (
    RescueVideoExecutionError,
    RescueVideoRequest,
    RescueVideoService,
    RescueVideoValidationError,
)


class RescueVideoWorker(QObject):
    progress = Signal(int, str)
    transferProgress = Signal(int, str, int, int, str)
    defaultsLoaded = Signal(int, object)
    runSucceeded = Signal(int, object)
    failed = Signal(int, str)
    finished = Signal(int)

    def __init__(
        self,
        request_id: int,
        service: RescueVideoService,
        operation: str,
        request: RescueVideoRequest | None = None,
        defaults_source: str = "",
        defaults_date: str = "",
        defaults_vehicle: str = "",
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.service = service
        self.operation = operation
        self.request = request
        self.defaults_source = defaults_source
        self.defaults_date = defaults_date
        self.defaults_vehicle = defaults_vehicle

    @Slot()
    def run(self) -> None:
        stage = "preflight"

        def update_stage(value: str) -> None:
            nonlocal stage
            stage = value

        try:
            if self.operation == "defaults":
                if self.defaults_source or self.defaults_date or self.defaults_vehicle:
                    defaults = self.service.load_defaults(
                        self.defaults_date or None,
                        source_path=self.defaults_source,
                        vehicle=self.defaults_vehicle,
                    )
                else:
                    defaults = self.service.load_defaults()
                self.defaultsLoaded.emit(self.request_id, defaults)
            elif self.operation == "execute" and self.request is not None:
                try:
                    result = self.service.execute(
                        self.request,
                        status_callback=lambda message: self.progress.emit(self.request_id, message),
                        stage_callback=update_stage,
                        transfer_callback=lambda source, copied, total, state: self.transferProgress.emit(
                            self.request_id,
                            source,
                            copied,
                            total,
                            state,
                        ),
                    )
                except TypeError as exc:
                    if "unexpected keyword argument" not in str(exc):
                        raise
                    try:
                        result = self.service.execute(
                            self.request,
                            status_callback=lambda message: self.progress.emit(self.request_id, message),
                            stage_callback=update_stage,
                        )
                    except TypeError as fallback_exc:
                        if "unexpected keyword argument" not in str(fallback_exc):
                            raise
                        result = self.service.execute(
                            self.request,
                            status_callback=lambda message: self.progress.emit(self.request_id, message),
                        )
                self.runSucceeded.emit(self.request_id, result)
            else:
                raise RescueVideoExecutionError("救護影片背景工作參數不正確。")
        except (RescueVideoExecutionError, RescueVideoValidationError) as exc:
            self.failure_stage = getattr(exc, "failure_stage", stage)
            self.failed.emit(self.request_id, str(exc))
        except Exception:
            self.failure_stage = stage
            self.failed.emit(self.request_id, "救護影片分類失敗，請檢查記憶卡與目的地。")
        finally:
            self.request = None
            self.finished.emit(self.request_id)
