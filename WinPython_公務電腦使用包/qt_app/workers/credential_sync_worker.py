# -*- coding: utf-8 -*-
"""Qt worker for credential synchronization."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from app_core.credential_sync_service import CredentialSyncError, CredentialSyncService


class CredentialSyncWorker(QObject):
    succeeded = Signal(int, int, bool)
    failed = Signal(int, str, bool)
    finished = Signal(int)

    def __init__(
        self,
        request_id: int,
        service: CredentialSyncService,
        accounts: list[dict[str, str]],
        notify_user: bool,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.service = service
        self.accounts = accounts
        self.notify_user = notify_user

    @Slot()
    def run(self) -> None:
        try:
            count = self.service.sync(self.accounts)
        except CredentialSyncError as exc:
            self.failed.emit(self.request_id, str(exc), self.notify_user)
        except Exception:
            self.failed.emit(self.request_id, "NAS 帳密同步失敗。", self.notify_user)
        else:
            self.succeeded.emit(self.request_id, count, self.notify_user)
        finally:
            self.accounts = []
            self.finished.emit(self.request_id)
