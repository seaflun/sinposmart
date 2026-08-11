# -*- coding: utf-8 -*-
"""UI-independent login session state for the Tk and Qt frontends."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LoginSession:
    """Authenticated duty-system identity retained for automation work."""

    actor_no: str
    user_id: str
    password: str = field(repr=False)
    verified: bool = False
    actor_name: str = ""
    remember: bool = False


class SessionState:
    """Own login single-flight and stale-result rejection state."""

    def __init__(self) -> None:
        self._session: LoginSession | None = None
        self._login_running = False
        self._attempt_id = 0
        self._generation = 0

    @property
    def session(self) -> LoginSession | None:
        return self._session

    @session.setter
    def session(self, value: LoginSession | None) -> None:
        if value is self._session:
            return
        self._session = value
        self._generation += 1

    @property
    def login_running(self) -> bool:
        return self._login_running

    @login_running.setter
    def login_running(self, value: bool) -> None:
        self._login_running = bool(value)

    @property
    def attempt_id(self) -> int:
        return self._attempt_id

    @attempt_id.setter
    def attempt_id(self, value: int) -> None:
        self._attempt_id = int(value)

    @property
    def generation(self) -> int:
        """Monotonic identity token used to reject work from older sessions."""

        return self._generation

    def begin_login(self) -> int | None:
        """Start one login attempt, returning None while another is active."""

        if self._login_running:
            return None
        self._login_running = True
        self._attempt_id += 1
        return self._attempt_id

    def complete_login(self, attempt_id: int, session: LoginSession) -> bool:
        """Accept a successful result only for the current attempt."""

        if attempt_id != self._attempt_id:
            return False
        self._login_running = False
        self._session = session
        self._generation += 1
        return True

    def fail_login(self, attempt_id: int) -> bool:
        """Clear a failed current attempt and reject stale failures."""

        if attempt_id != self._attempt_id:
            return False
        self._login_running = False
        if self._session is not None:
            self._generation += 1
        self._session = None
        return True

    def timeout_login(self, attempt_id: int) -> bool:
        """Invalidate an active attempt so its eventual worker result is stale."""

        if attempt_id != self._attempt_id or not self._login_running:
            return False
        self._login_running = False
        self._attempt_id += 1
        if self._session is not None:
            self._generation += 1
        self._session = None
        return True

    def clear_session(self) -> LoginSession | None:
        """Clear and return the authenticated session without changing attempts."""

        previous = self._session
        self._session = None
        if previous is not None:
            self._generation += 1
        return previous
