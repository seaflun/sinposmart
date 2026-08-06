# -*- coding: utf-8 -*-
"""UI-independent duty-system login verification and driver ownership."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Callable


DEFAULT_PAGE_LOAD_TIMEOUT_SECONDS = 45
DEFAULT_SCRIPT_TIMEOUT_SECONDS = 30


class LoginVerificationError(RuntimeError):
    """Safe login error that may be shown to the operator."""


@dataclass(frozen=True)
class LoginResult:
    actor_no: str
    user_id: str
    actor_name: str = ""
    warning: str = ""


def _bounded_timeout(name: str, default: int) -> int:
    try:
        return max(10, int(os.environ.get(name, str(default))))
    except ValueError:
        return default


def build_background_chrome_options() -> Any:
    from selenium.webdriver.chrome.options import Options

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1280,900")
    options.add_argument("--window-position=-32000,-32000")
    return options


def build_foreground_chrome_options() -> Any:
    from selenium.webdriver.chrome.options import Options

    options = Options()
    options.add_argument("--window-size=1280,900")
    options.add_argument("--window-position=80,80")
    return options


def configure_login_webdriver_timeouts(driver: Any) -> None:
    try:
        driver.set_page_load_timeout(
            _bounded_timeout("SELENIUM_PAGE_LOAD_TIMEOUT_SECONDS", DEFAULT_PAGE_LOAD_TIMEOUT_SECONDS)
        )
    except Exception:
        pass
    try:
        driver.set_script_timeout(
            _bounded_timeout("SELENIUM_SCRIPT_TIMEOUT_SECONDS", DEFAULT_SCRIPT_TIMEOUT_SECONDS)
        )
    except Exception:
        pass


def create_login_webdriver(options: Any) -> Any:
    from duty_rehearsal import build_driver

    arguments = tuple(str(argument) for argument in getattr(options, "arguments", ()) or ())
    headless = any(argument.startswith("--headless") for argument in arguments)
    passthrough_arguments = tuple(
        argument
        for argument in arguments
        if not argument.startswith("--headless") and not argument.startswith("--window-size")
    )
    return build_driver(headless=headless, option_arguments=passthrough_arguments)


def run_duty_login(driver: Any, user_id: str, password: str) -> None:
    from duty_rehearsal import login

    login(driver, user_id, password)


def query_current_duty_actor_no(driver: Any, actor_name: str) -> str:
    from app_core.schedule_repository import business_roc_date
    from duty_rehearsal import query_duty_sheet

    normalized_name = re.sub(r"\s+", "", str(actor_name or ""))
    if not normalized_name:
        return ""
    duty_sheet = query_duty_sheet(driver, business_roc_date())
    matches = [
        str(actor_no).strip()
        for actor_no, info in duty_sheet.staff.items()
        if re.sub(r"\s+", "", str(info.get("name", "") or "")) == normalized_name
    ]
    return matches[0] if len(matches) == 1 else ""


def close_login_webdriver(driver: Any) -> None:
    try:
        from duty_rehearsal import quit_driver

        quit_driver(driver)
    except Exception:
        pass


def page_identity_text(driver: Any) -> str:
    return driver.execute_script(
        """
        const body = document.body ? document.body.innerText : '';
        const values = Array.from(document.querySelectorAll('input,select,textarea'))
          .map(el => el.value || el.options?.[el.selectedIndex]?.text || '')
          .filter(Boolean)
          .join('\\n');
        return [document.title || '', body, values].join('\\n');
        """
    ) or ""


def page_identity_hint_text(driver: Any) -> str:
    """Read non-table identity hints without cookies, secrets or page logging."""

    return driver.execute_script(
        """
        const hints = [];
        const push = value => {
          const text = String(value || '').trim();
          if (text && text.length <= 80 && !hints.includes(text)) hints.push(text);
        };
        for (const element of document.querySelectorAll('body *')) {
          if (element.closest('table') || element.children.length) continue;
          const style = window.getComputedStyle(element);
          if (style.display === 'none' || style.visibility === 'hidden') continue;
          push(element.innerText || element.textContent);
        }
        for (const element of document.querySelectorAll('input,select,textarea')) {
          const identity = `${element.id || ''} ${element.name || ''}`.toLowerCase();
          if (element.type === 'password' || /(pass|pwd|token|secret)/.test(identity)) continue;
          push(element.tagName === 'SELECT'
            ? element.options?.[element.selectedIndex]?.text || element.value
            : element.value);
        }
        for (const key of Object.keys(window)) {
          if (!/(user|name|login|employee|staff|actor)/i.test(key) ||
              /(pass|pwd|token|secret)/i.test(key)) continue;
          try {
            if (typeof window[key] === 'string') push(window[key]);
          } catch (_) {}
        }
        return hints.join('\\n');
        """
    ) or ""


def identify_logged_in_actor(
    driver: Any,
    actor_no_from_name: Callable[[str], str],
    staff: dict[str, dict[str, Any]],
) -> tuple[str, str]:
    texts = [page_identity_text(driver)]
    hint_texts = [page_identity_hint_text(driver)]
    frames = driver.find_elements("tag name", "frame") + driver.find_elements("tag name", "iframe")
    for frame in frames:
        try:
            driver.switch_to.default_content()
            driver.switch_to.frame(frame)
            texts.append(page_identity_text(driver))
            hint_texts.append(page_identity_hint_text(driver))
        except Exception:
            continue
    driver.switch_to.default_content()
    page_text = "\n".join(texts)
    greeting_match = re.search(r"([^\s,，]+)\s*[,，]\s*您好", page_text)
    if greeting_match:
        actor_name = greeting_match.group(1).strip()
        actor_no = str(actor_no_from_name(actor_name) or "").strip()
        if actor_no or not staff:
            return actor_no, actor_name

    compact_page_text = re.sub(r"\s+", "", page_text)
    greeting_candidates = []
    for no, info in staff.items():
        name = str(info.get("name", "") or "").strip()
        compact_name = re.sub(r"\s+", "", name)
        if compact_name and any(
            marker in compact_page_text
            for marker in (
                f"{compact_name},您好",
                f"{compact_name}，您好",
                f"{compact_name}您好",
            )
        ):
            greeting_candidates.append((str(no), name))
    if len(greeting_candidates) == 1:
        return greeting_candidates[0]

    compact_hint_text = re.sub(r"\s+", "", "\n".join(hint_texts))
    hint_candidates = []
    for no, info in staff.items():
        name = str(info.get("name", "") or "").strip()
        compact_name = re.sub(r"\s+", "", name)
        if compact_name and compact_name in compact_hint_text:
            hint_candidates.append((str(no), name))
    if len(hint_candidates) == 1:
        return hint_candidates[0]

    candidates = []
    for no, info in staff.items():
        name = str(info.get("name", "") or "")
        if name and name in page_text:
            candidates.append((str(no), name))
    if len(candidates) == 1:
        return candidates[0]
    return "", ""


def resolve_verified_actor_no(
    typed_actor_no: str,
    user_id: str,
    detected_actor_no: str,
    actor_no_from_user_id: Callable[[str], str],
) -> str:
    typed_actor_no = str(typed_actor_no or "").strip()
    detected_actor_no = str(detected_actor_no or "").strip()
    account_actor_no = str(actor_no_from_user_id(user_id) or "").strip()
    resolved_actor_no = detected_actor_no or account_actor_no or typed_actor_no
    if typed_actor_no and resolved_actor_no and typed_actor_no != resolved_actor_no:
        raise LoginVerificationError(
            f"登入帳號辨識為 {resolved_actor_no} 番，與輸入的 {typed_actor_no} 番不一致。請選擇正確番號或帳號。"
        )
    if not resolved_actor_no:
        raise LoginVerificationError("登入後頁面沒有顯示可辨識的姓名。")
    return resolved_actor_no


class LoginVerifier:
    """Create, use and release one WebDriver entirely inside the caller worker."""

    def __init__(
        self,
        *,
        options_factory: Callable[[], Any] = build_background_chrome_options,
        driver_factory: Callable[[Any], Any] = create_login_webdriver,
        configure_driver: Callable[[Any], None] = configure_login_webdriver_timeouts,
        login_function: Callable[[Any, str, str], None] = run_duty_login,
        actor_no_query: Callable[[Any, str], str] | None = None,
        allow_post_login_lookup_warning: bool = False,
        defer_actor_resolution: bool = False,
        driver_cleanup: Callable[[Any], None] = close_login_webdriver,
    ) -> None:
        self.options_factory = options_factory
        self.driver_factory = driver_factory
        self.configure_driver = configure_driver
        self.login_function = login_function
        self.actor_no_query = actor_no_query
        self.allow_post_login_lookup_warning = bool(allow_post_login_lookup_warning)
        self.defer_actor_resolution = bool(defer_actor_resolution)
        self.driver_cleanup = driver_cleanup

    def verify(
        self,
        *,
        typed_actor_no: str,
        user_id: str,
        password: str,
        actor_no_from_user_id: Callable[[str], str],
        actor_no_from_name: Callable[[str], str],
        staff: dict[str, dict[str, Any]],
    ) -> LoginResult:
        driver = None
        try:
            driver = self.driver_factory(self.options_factory())
            self.configure_driver(driver)
            self.login_function(driver, user_id, password)
            try:
                detected_actor_no, actor_name = identify_logged_in_actor(driver, actor_no_from_name, staff)
            except Exception:
                if not self.allow_post_login_lookup_warning:
                    raise
                return LoginResult(
                    actor_no="",
                    user_id=user_id,
                    warning="登入成功，但無法辨識登入人員；勤務番號尚未取得。",
                )
            if self.defer_actor_resolution:
                return LoginResult(
                    actor_no="",
                    user_id=user_id,
                    actor_name=actor_name,
                    warning="登入成功，正在查詢勤務資料…",
                )
            if self.actor_no_query is not None:
                try:
                    actor_no = str(self.actor_no_query(driver, actor_name) or "").strip()
                except Exception as exc:
                    if not self.allow_post_login_lookup_warning:
                        raise LoginVerificationError("登入成功，但勤務番號查詢失敗。") from exc
                    return LoginResult(
                        actor_no="",
                        user_id=user_id,
                        actor_name=actor_name,
                        warning="登入成功，但勤務番號查詢失敗；請稍後重新整理勤務資料。",
                    )
                if not actor_no:
                    if not self.allow_post_login_lookup_warning:
                        raise LoginVerificationError("登入成功，但在當日勤務表查不到登入人員的番號。")
                    return LoginResult(
                        actor_no="",
                        user_id=user_id,
                        actor_name=actor_name,
                        warning="登入成功，但在當日勤務表查不到登入人員的番號。",
                    )
            else:
                actor_no = resolve_verified_actor_no(
                    typed_actor_no,
                    user_id,
                    detected_actor_no,
                    actor_no_from_user_id,
                )
            return LoginResult(actor_no=actor_no, user_id=user_id, actor_name=actor_name)
        finally:
            if driver is not None:
                self.driver_cleanup(driver)
