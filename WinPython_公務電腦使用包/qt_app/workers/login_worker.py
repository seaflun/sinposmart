# -*- coding: utf-8 -*-
"""Qt worker adapter for LoginVerifier."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from app_core.login_verifier import LoginVerificationError, LoginVerifier, capture_login_diagnostic


class LoginWorker(QObject):
    succeeded = Signal(int, object)
    failed = Signal(int, str)
    finished = Signal(int)

    def __init__(
        self,
        *,
        attempt_id: int,
        verifier: LoginVerifier,
        actor_no: str,
        user_id: str,
        password: str,
        actor_no_from_user_id: Callable[[str], str],
        actor_no_from_name: Callable[[str], str],
        staff: dict[str, dict[str, Any]],
    ) -> None:
        super().__init__()
        self.attempt_id = attempt_id
        self.verifier = verifier
        self.actor_no = actor_no
        self.user_id = user_id
        self.password = password
        self.actor_no_from_user_id = actor_no_from_user_id
        self.actor_no_from_name = actor_no_from_name
        self.staff = staff
        self.failure_diagnostic: dict = {}

    @Slot()
    def run(self) -> None:
        self.failure_diagnostic = {}
        try:
            result = self.verifier.verify(
                typed_actor_no=self.actor_no,
                user_id=self.user_id,
                password=self.password,
                actor_no_from_user_id=self.actor_no_from_user_id,
                actor_no_from_name=self.actor_no_from_name,
                staff=self.staff,
            )
        except LoginVerificationError as exc:
            self.failure_diagnostic = dict(exc.login_diagnostic) or capture_login_diagnostic(
                None, str(exc), user_id=self.user_id, password=self.password, reason_code=exc.reason_code,
            )
            message = self.failure_diagnostic['reason']
            if self.failure_diagnostic.get('reason_code') == 'password_change_required':
                message = '密碼須更新：請至勤務網站手動完成密碼變更後，再重新登入。'
            self.failed.emit(self.attempt_id, message)
        except Exception as exc:
            self.failure_diagnostic = dict(getattr(exc, 'login_diagnostic', {}) or {}) or capture_login_diagnostic(
                None, str(exc).splitlines()[0] if str(exc) else '登入失敗。',
                user_id=self.user_id, password=self.password,
                reason_code='browser_start_failed' if getattr(exc, 'diagnostic_category', '') else 'login_failed',
            )
            if getattr(exc, "diagnostic_category", ""):
                self.failed.emit(
                    self.attempt_id,
                    "SinpoSmart 專用瀏覽器啟動失敗，已自動清理暫存資料並重試。"
                    "一般 Chrome 不需關閉；若仍失敗請通知管理人員。",
                )
                return
            self.failed.emit(
                self.attempt_id,
                "登入失敗：請確認帳號密碼、網路與 Chrome 狀態後重試。",
            )
        else:
            self.succeeded.emit(self.attempt_id, result)
        finally:
            self.password = ""
            self.finished.emit(self.attempt_id)
