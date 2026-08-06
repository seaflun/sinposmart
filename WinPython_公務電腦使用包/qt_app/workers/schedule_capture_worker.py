# -*- coding: utf-8 -*-
"""Qt worker for live duty schedule capture."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Signal, Slot

from app_core.schedule_capture_service import (
    ScheduleCaptureError,
    ScheduleCaptureRequest,
    ScheduleCaptureService,
)


class ScheduleCaptureWorker(QObject):
    progress = Signal(int, str)
    scheduleReady = Signal(int, str, object)
    comparisonsReady = Signal(int, str, object)
    succeeded = Signal(int, str, object)
    failed = Signal(int, str, str, str)
    finished = Signal(int)

    def __init__(
        self,
        request_id: int,
        service: ScheduleCaptureService,
        request: ScheduleCaptureRequest,
        *,
        include_schedule: bool = True,
        include_comparisons: bool = True,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.service = service
        self.request = request
        self.include_schedule = bool(include_schedule)
        self.include_comparisons = bool(include_comparisons)

    @Slot()
    def run(self) -> None:
        actor_no = self.request.actor_no
        try:
            if not self.include_schedule:
                if not self.include_comparisons:
                    raise ScheduleCaptureError("未指定任何勤務查詢工作。", "invalid_request")
                comparison_data = self.service.capture_comparisons(
                    self.request,
                    status_callback=lambda message: self.progress.emit(self.request_id, message),
                )
                self.comparisonsReady.emit(self.request_id, actor_no, comparison_data)
                return
            if not self.include_comparisons:
                snapshot = self.service.capture_schedule(
                    self.request,
                    status_callback=lambda message: self.progress.emit(self.request_id, message),
                )
                self.succeeded.emit(self.request_id, actor_no, snapshot)
                return
            capture_schedule = getattr(self.service, "capture_schedule", None)
            capture_comparisons = getattr(self.service, "capture_comparisons", None)
            combine_capture = getattr(self.service, "combine_capture", None)
            if all(callable(value) for value in (capture_schedule, capture_comparisons, combine_capture)):
                callback = lambda message: self.progress.emit(self.request_id, message)
                with ThreadPoolExecutor(max_workers=2, thread_name_prefix="sinposmart-qt-live") as executor:
                    schedule_future = executor.submit(
                        capture_schedule,
                        self.request,
                        status_callback=callback,
                    )
                    comparison_future = executor.submit(
                        capture_comparisons,
                        self.request,
                        status_callback=callback,
                    )
                    schedule_snapshot = schedule_future.result()
                    self.scheduleReady.emit(self.request_id, actor_no, schedule_snapshot)
                    try:
                        comparison_data = comparison_future.result()
                    except ScheduleCaptureError as exc:
                        message = (
                            "已登打資料比對逾時，勤務資料仍可使用。"
                            if exc.error_code == "timeout"
                            else "已登打資料比對失敗，勤務資料仍可使用。"
                        )
                        self.failed.emit(
                            self.request_id,
                            actor_no,
                            message,
                            f"comparison_{exc.error_code}",
                        )
                        return
                snapshot = combine_capture(schedule_snapshot, comparison_data)
            else:
                snapshot = self.service.capture(
                    self.request,
                    status_callback=lambda message: self.progress.emit(self.request_id, message),
                )
        except ScheduleCaptureError as exc:
            self.failed.emit(self.request_id, actor_no, str(exc), exc.error_code)
        except Exception:
            self.failed.emit(
                self.request_id,
                actor_no,
                "即時勤務查詢失敗，已停用自動登打。",
                "unknown_error",
            )
        else:
            self.succeeded.emit(self.request_id, actor_no, snapshot)
        finally:
            self.request = ScheduleCaptureRequest("", "", "", "", "")
            self.finished.emit(self.request_id)
