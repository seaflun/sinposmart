# -*- coding: utf-8 -*-
"""QML-facing session state and Qt login-worker coordination."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Property, QThread, QTimer, Signal, Slot

from app_core.credential_repository import (
    CredentialRepository,
    create_default_credential_repository,
)
from app_core.credential_sync_service import CredentialSyncService
from app_core.login_verifier import LoginResult, LoginVerifier
from app_core.session import LoginSession, SessionState
from qt_app.models.saved_account_model import SavedAccountListModel
from qt_app.workers.credential_sync_worker import CredentialSyncWorker
from qt_app.workers.login_worker import LoginWorker


DEFAULT_LOGIN_TIMEOUT_MS = 120_000


class SessionController(QObject):
    sessionChanged = Signal()
    statusChanged = Signal()
    savedAccountSelected = Signal(str, str, str)
    errorOccurred = Signal(str)
    loginAttemptFailed = Signal(str, str, str)
    credentialSyncConfirmationRequested = Signal()

    def __init__(
        self,
        state: SessionState | None = None,
        *,
        repository: CredentialRepository | None = None,
        verifier: LoginVerifier | Any | None = None,
        credential_sync_service: CredentialSyncService | None = None,
        login_timeout_ms: int = DEFAULT_LOGIN_TIMEOUT_MS,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._state = state or SessionState()
        self._repository = repository or create_default_credential_repository()
        self._verifier = verifier or LoginVerifier(defer_actor_resolution=True)
        self._credential_sync_service = credential_sync_service or CredentialSyncService()
        self._login_timeout_ms = max(1, int(login_timeout_ms))
        self._login_status = "未登入"
        self._login_status_tone = "neutral"
        self._display_name = ""
        self._accounts: list[dict[str, str]] = []
        self._last_selected_identity = ""
        self._saved_accounts_model = SavedAccountListModel(self)
        self._pending_credentials: dict[int, tuple[str, str, bool]] = {}
        self._login_workers: dict[int, tuple[QThread, LoginWorker]] = {}
        self._credential_sync_request_id = 0
        self._credential_sync_workers: dict[int, tuple[QThread, CredentialSyncWorker]] = {}
        self._reload_accounts()

    @Property(str, notify=sessionChanged)
    def actorNo(self) -> str:
        return self._state.session.actor_no if self._state.session else ""

    @Property(str, notify=sessionChanged)
    def userId(self) -> str:
        return self._state.session.user_id if self._state.session else ""

    @Property(str, notify=sessionChanged)
    def displayName(self) -> str:
        return self._display_name

    @Property(str, notify=statusChanged)
    def loginStatus(self) -> str:
        return self._login_status

    @Property(str, notify=statusChanged)
    def loginStatusTone(self) -> str:
        """Return the semantic color category for the login-status message."""

        return self._login_status_tone

    @Property(bool, notify=sessionChanged)
    def isLoggedIn(self) -> bool:
        return bool(self._state.session and self._state.session.verified)

    @Property(bool, notify=sessionChanged)
    def isBusy(self) -> bool:
        return self._state.login_running or bool(self._login_workers)

    @Property(QObject, constant=True)
    def savedAccountsModel(self) -> SavedAccountListModel:
        return self._saved_accounts_model

    @Slot(str, str, bool)
    def login(self, user_id: str, password: str, remember: bool = False) -> None:
        if self._state.login_running or self._login_workers:
            return
        user_id = str(user_id or "").strip()
        account = self._account_by_user_id(user_id)
        if not password and account:
            password = str(account.get("password", "") or "")
        if not user_id or not password:
            self._set_status("請輸入帳號、密碼。", error=True)
            return

        attempt_id = self._state.begin_login()
        if attempt_id is None:
            return
        self._pending_credentials[attempt_id] = (user_id, password, bool(remember))
        self._set_status("登入中…", tone="info")

        worker = LoginWorker(
            attempt_id=attempt_id,
            verifier=self._verifier,
            actor_no="",
            user_id=user_id,
            password=password,
            actor_no_from_user_id=self._actor_no_from_user_id,
            actor_no_from_name=self._actor_no_from_name,
            staff={},
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._login_succeeded)
        worker.failed.connect(self._login_failed)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(self._worker_finished)
        self._login_workers[attempt_id] = (thread, worker)
        thread.start()
        QTimer.singleShot(
            self._login_timeout_ms,
            lambda attempt=attempt_id: self._login_timed_out(attempt),
        )

    @Slot()
    def loadSavedAccounts(self) -> None:
        self._reload_accounts()

    @Slot()
    def restoreSavedAccountSelection(self) -> None:
        """Restore the released GUI's last saved account after QML binds signals."""

        account = self._account_by_identity(self._last_selected_identity)
        if account is None and self._accounts:
            account = self._accounts[0]
        if account is not None:
            self.savedAccountSelected.emit(
                str(account.get("actor_no", "") or ""),
                str(account.get("user_id", "") or ""),
                str(account.get("password", "") or ""),
            )

    @Slot(str)
    def selectSavedAccount(self, identity: str) -> None:
        account = self._account_by_identity(identity)
        if account:
            self.savedAccountSelected.emit(
                str(account.get("actor_no", "") or ""),
                str(account.get("user_id", "") or ""),
                str(account.get("password", "") or ""),
            )

    @Slot(str)
    def deleteSavedAccount(self, identity: str) -> None:
        account = self._account_by_identity(identity)
        if not account:
            return
        remaining_accounts = self._sorted_accounts(
            [item for item in self._accounts if item is not account]
        )
        next_account = remaining_accounts[0] if remaining_accounts else None
        next_identity = (
            self._repository.account_identity(next_account)
            if next_account is not None
            else ""
        )
        if not self._repository.save(remaining_accounts, next_identity):
            self._set_status("無法儲存帳號：Windows DPAPI 不可用。", error=True)
            return
        self._accounts = remaining_accounts
        self._saved_accounts_model.replace_accounts(self._accounts)
        if next_account is None:
            self.savedAccountSelected.emit("", "", "")
            return
        self.savedAccountSelected.emit(
            str(next_account.get("actor_no", "") or ""),
            str(next_account.get("user_id", "") or ""),
            str(next_account.get("password", "") or ""),
        )

    @Slot()
    def prepareCredentialSync(self) -> None:
        if not self.isLoggedIn:
            self._set_status("請先登入後再同步帳密。", error=True)
            return
        self.credentialSyncConfirmationRequested.emit()

    @Slot()
    def syncSavedAccounts(self) -> None:
        self._start_credential_sync(notify_user=True)

    def resolve_actor_no(self, actor_no: str, actor_name: str = "") -> bool:
        """Apply the duty number resolved from the existing schedule capture."""

        session = self._state.session
        actor_no = str(actor_no or "").strip()
        actor_name = str(actor_name or session.actor_name if session else actor_name or "").strip()
        if session is None or not session.verified or not actor_no:
            return False
        session.actor_no = actor_no
        session.actor_name = actor_name
        self._display_name = f"{actor_no}番 {actor_name}" if actor_name else f"{actor_no}番"

        account = self._account_by_user_id(session.user_id)
        if session.remember or account:
            self._save_successful_account(
                actor_no=actor_no,
                user_id=session.user_id,
                password=session.password,
                display_name=self._display_name,
                actor_name=actor_name,
            )
        self._start_credential_sync(
            extra_account={
                "actor_no": actor_no,
                "user_id": session.user_id,
                "password": session.password,
                "display_name": self._display_name,
                "name": actor_name,
                "id_number": str(account.get("id_number", "") or "") if account else "",
            },
            notify_user=False,
        )
        self.set_logged_in_status()
        return True

    def set_logged_in_status(self, identity: str = "", shift_label: str = "") -> None:
        """Match the finalized legacy GUI login-status wording."""

        session = self._state.session
        if session is None or not session.verified:
            return
        identity = str(identity or "").strip() or self._login_identity()
        shift_label = str(shift_label or "").strip()
        if not shift_label:
            self._set_status(f"已登入：{identity}，正在查詢今日勤務表。")
        elif shift_label == "今日無值班時段":
            self._set_status(f"已登入：{identity}，今日無值班時段。")
        else:
            self._set_status(f"已登入：{identity}，今日值班時段：{shift_label}。")

    @Slot(str, str)
    def setOperationalStatus(self, message: str, tone: str = "warning") -> None:
        """Show a duty-operation result in the existing logged-in status row."""

        normalized = str(message or "").strip()
        if not self.isLoggedIn or not normalized:
            return
        self._login_status = normalized
        self._login_status_tone = str(tone or "warning")
        self.statusChanged.emit()

    @Slot()
    def logout(self) -> None:
        self._state.clear_session()
        self._display_name = ""
        self._set_status("未登入", tone="neutral")

    def systemLogout(self, message: str = "系統已登出") -> None:
        """End a session initiated by an automatic system condition."""

        self._state.clear_session()
        self._display_name = ""
        self._set_status(str(message or "系統已登出"), tone="warning")

    @Slot()
    def shutdown(self) -> None:
        for attempt_id, (thread, _worker) in tuple(self._login_workers.items()):
            thread.requestInterruption()
            thread.quit()
            if thread.wait(60_000):
                self._login_workers.pop(attempt_id, None)
                self._pending_credentials.pop(attempt_id, None)
                thread.deleteLater()
        for request_id, (thread, _worker) in tuple(self._credential_sync_workers.items()):
            thread.requestInterruption()
            thread.quit()
            if thread.wait(60_000):
                self._credential_sync_workers.pop(request_id, None)
                thread.deleteLater()

    def _reload_accounts(self) -> None:
        snapshot = self._repository.load()
        if snapshot.invalid_file:
            self._accounts = []
            self._saved_accounts_model.replace_accounts([])
            self._set_status("已儲存帳號檔無法讀取，尚未覆寫原檔。", error=True)
            return
        self._accounts = self._sorted_accounts(snapshot.accounts)
        self._last_selected_identity = str(snapshot.last_selected or "")
        self._saved_accounts_model.replace_accounts(self._accounts)
        if snapshot.can_persist and snapshot.needs_rewrite:
            self._repository.save(self._accounts, snapshot.last_selected)

    def _account_by_identity(self, identity: str) -> dict[str, str] | None:
        identity = str(identity or "").strip()
        return next(
            (
                account
                for account in self._accounts
                if self._repository.account_identity(account) == identity
            ),
            None,
        )

    def _sorted_accounts(
        self,
        accounts: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        def account_sort_key(account: dict[str, str]) -> tuple[int, str]:
            actor_no = str(account.get("actor_no", "") or "").strip()
            identity = self._repository.account_identity(account)
            return (int(actor_no), identity) if actor_no.isdigit() else (9999, identity)

        return sorted(accounts, key=account_sort_key)

    def _account_by_user_id(self, user_id: str) -> dict[str, str] | None:
        user_id = str(user_id or "").strip()
        return next(
            (
                account
                for account in self._accounts
                if str(account.get("user_id", "") or "").strip() == user_id
            ),
            None,
        )

    def _actor_no_from_user_id(self, user_id: str) -> str:
        account = self._account_by_user_id(user_id)
        return str(account.get("actor_no", "") or "").strip() if account else ""

    def saved_actor_no(self, user_id: str) -> str:
        """Return a saved duty number for provisional local-cache projection only."""

        return self._actor_no_from_user_id(user_id)

    def _actor_no_from_name(self, name: str) -> str:
        name = str(name or "").strip()
        for account in self._accounts:
            account_name = str(account.get("name", "") or "").strip()
            display_name = str(account.get("display_name", "") or "").strip()
            if name and (account_name == name or name in display_name):
                return str(account.get("actor_no", "") or "").strip()
        return ""

    @Slot(int, object)
    def _login_succeeded(self, attempt_id: int, result: LoginResult) -> None:
        pending = self._pending_credentials.pop(attempt_id, None)
        if pending is None:
            return
        user_id, password, remember = pending
        session = LoginSession(
            actor_no=result.actor_no,
            user_id=result.user_id,
            password=password,
            verified=True,
            actor_name=str(result.actor_name or "").strip(),
            remember=remember,
        )
        if not self._state.complete_login(attempt_id, session):
            return

        account = self._account_by_user_id(user_id)
        actor_name = str(result.actor_name or "").strip()
        if actor_name:
            self._display_name = f"{result.actor_no}番 {actor_name}" if result.actor_no else actor_name
        elif account and account.get("display_name"):
            self._display_name = str(account["display_name"])
        elif result.actor_no:
            self._display_name = f"{result.actor_no}番"
        else:
            self._display_name = user_id

        if result.actor_no and (remember or account):
            self._save_successful_account(
                actor_no=result.actor_no,
                user_id=user_id,
                password=password,
                display_name=self._display_name,
                actor_name=actor_name,
            )
        if result.actor_no:
            self._start_credential_sync(
                extra_account={
                    "actor_no": result.actor_no,
                    "user_id": user_id,
                    "password": password,
                    "display_name": self._display_name,
                    "name": actor_name,
                    "id_number": str(account.get("id_number", "") or "") if account else "",
                },
                notify_user=False,
            )
        self.set_logged_in_status()

    @Slot(int, str)
    def _login_failed(self, attempt_id: int, message: str) -> None:
        pending = self._pending_credentials.pop(attempt_id, None)
        if not self._state.fail_login(attempt_id):
            return
        self._display_name = ""
        self._set_status(message, error=True)
        user_id = pending[0] if pending is not None else ""
        self.loginAttemptFailed.emit(user_id, message, "login_failed")

    def _login_timed_out(self, attempt_id: int) -> None:
        pending = self._pending_credentials.pop(attempt_id, None)
        if not self._state.timeout_login(attempt_id):
            return
        self._display_name = ""
        message = "登入逾時：請確認帳號密碼或勤務系統是否有回應。"
        self._set_status(message, error=True)
        user_id = pending[0] if pending is not None else ""
        self.loginAttemptFailed.emit(user_id, message, "timeout")

    def _save_successful_account(
        self,
        *,
        actor_no: str,
        user_id: str,
        password: str,
        display_name: str,
        actor_name: str,
    ) -> None:
        existing = self._account_by_user_id(user_id) or {}
        updated = {
            "actor_no": actor_no,
            "user_id": user_id,
            "password": password,
            "display_name": display_name,
            "name": actor_name or str(existing.get("name", "") or ""),
            "id_number": str(existing.get("id_number", "") or ""),
        }
        self._accounts = self._sorted_accounts([
            updated if item is existing else item
            for item in self._accounts
        ] if existing else [*self._accounts, updated])
        self._repository.enable_persistence()
        if self._repository.save(self._accounts, user_id):
            self._saved_accounts_model.replace_accounts(self._accounts)

    @Slot(int)
    def _worker_finished(self, attempt_id: int) -> None:
        worker_pair = self._login_workers.get(attempt_id)
        if worker_pair is None:
            return
        thread, _worker = worker_pair
        thread.quit()
        if not thread.wait(5_000):
            return
        self._login_workers.pop(attempt_id, None)
        thread.deleteLater()
        self.sessionChanged.emit()

    def _start_credential_sync(
        self,
        *,
        extra_account: dict[str, str] | None = None,
        notify_user: bool,
    ) -> None:
        if not self._credential_sync_service.enabled:
            if notify_user:
                self._set_status("尚未設定 NAS 帳密同步 URL 或 token。", error=True)
            return
        accounts = [dict(account) for account in self._accounts]
        if extra_account and extra_account.get("user_id") and extra_account.get("password"):
            accounts = [
                account
                for account in accounts
                if str(account.get("user_id", "") or "") != extra_account["user_id"]
            ]
            accounts.insert(0, dict(extra_account))
        if notify_user:
            self._set_status("帳密同步傳送中…")

        self._credential_sync_request_id += 1
        request_id = self._credential_sync_request_id
        worker = CredentialSyncWorker(
            request_id,
            self._credential_sync_service,
            accounts,
            notify_user,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._credential_sync_succeeded)
        worker.failed.connect(self._credential_sync_failed)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(self._credential_sync_worker_finished)
        self._credential_sync_workers[request_id] = (thread, worker)
        thread.start()

    @Slot(int, int, bool)
    def _credential_sync_succeeded(self, _request_id: int, count: int, notify_user: bool) -> None:
        if notify_user:
            self._set_status(f"已同步 {count} 組帳密。")

    @Slot(int, str, bool)
    def _credential_sync_failed(self, _request_id: int, message: str, notify_user: bool) -> None:
        if notify_user:
            self._set_status(message, error=True)

    @Slot(int)
    def _credential_sync_worker_finished(self, request_id: int) -> None:
        worker_pair = self._credential_sync_workers.get(request_id)
        if worker_pair is None:
            return
        thread, _worker = worker_pair
        thread.quit()
        if not thread.wait(5_000):
            return
        self._credential_sync_workers.pop(request_id, None)
        thread.deleteLater()

    def _set_status(
        self,
        message: str,
        *,
        error: bool = False,
        tone: str = "success",
    ) -> None:
        self._login_status = message
        self._login_status_tone = "error" if error else tone
        self.statusChanged.emit()
        self.sessionChanged.emit()
        if error:
            self.errorOccurred.emit(message)

    def _login_identity(self) -> str:
        session = self._state.session
        if session is None:
            return "-"
        actor_name = str(session.actor_name or "").strip()
        if actor_name:
            return actor_name
        display_name = str(self._display_name or "").strip()
        if display_name:
            return display_name
        if session.actor_no:
            return f"{session.actor_no}番"
        return session.user_id
