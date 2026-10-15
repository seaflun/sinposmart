# -*- coding: utf-8 -*-
"""UI-independent duty-system login verification and driver ownership."""

from __future__ import annotations

import base64
import os
import re
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, quote_plus, urlsplit, urlunsplit


DEFAULT_PAGE_LOAD_TIMEOUT_SECONDS = 45
DEFAULT_SCRIPT_TIMEOUT_SECONDS = 30


class LoginVerificationError(RuntimeError):
    """Safe login error that may be shown to the operator."""

    def __init__(self, message: str, *, login_diagnostic: dict | None = None, reason_code: str = 'login_failed') -> None:
        super().__init__(message)
        self.login_diagnostic = dict(login_diagnostic or {})
        self.reason_code = reason_code


LOGIN_DIAGNOSTIC_PROBE_SCRIPT = r"""
// login-diagnostic-probe: never read form values or raw HTML.
const texts = [];
let passwordFields = 0;
function read(doc) {
  const view = doc.defaultView;
  const visible = el => {
    const style = view.getComputedStyle(el);
    return el.getClientRects().length > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  passwordFields += Array.from(doc.querySelectorAll('input[type="password"]')).filter(visible).length;
  const walker = doc.createTreeWalker(doc.body || doc.documentElement, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    const el = node.parentElement;
    if (!el || el.closest('input,textarea,select,[contenteditable],script,style') || !visible(el)) continue;
    texts.push(node.nodeValue || '');
  }
  for (const frame of doc.querySelectorAll('frame,iframe')) {
    try { if (frame.contentDocument) read(frame.contentDocument); } catch (_) {}
  }
}
read(document);
return {page_text: texts.join('\n').slice(0, 12000), password_fields: passwordFields};
"""


LOGIN_DIAGNOSTIC_REDACT_SCRIPT = r"""
// login-diagnostic-redact: a strict true is required before taking a screenshot.
if (window.top !== window) return false;
const secrets = arguments[0].filter(Boolean).sort((a, b) => b.length - a.length);
function redact(value) {
  let text = String(value || '');
  for (const secret of secrets) {
    const escaped = secret.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    text = text.replace(new RegExp(escaped, 'gi'), '[已遮蔽]');
  }
  text = text.replace(/https?:\/\/[^\s<>"']+/gi, value => {
    try { const url = new URL(value); return url.origin + url.pathname; } catch (_) { return '[已遮蔽網址]'; }
  });
  return text.replace(/((?:password|passwd|pwd|token|secret|cookie|authorization|session[_-]?id|api[_-]?key|密碼|帳號)["']?\s*[:=：]\s*)(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\r\n,;]+)/gi, '$1[已遮蔽]');
}
try {
  const style = document.createElement('style');
  style.textContent = '*::before,*::after { content:none!important; }';
  document.documentElement.appendChild(style);
  for (const el of document.querySelectorAll('*')) {
    const generatedContent = ['::before', '::after'].some(pseudo => {
      const content = window.getComputedStyle(el, pseudo).content;
      return content && !['none', 'normal', '""', "''"].includes(content);
    });
    if (el.matches('input,textarea,select,[contenteditable],frame,iframe,object,embed,canvas,video') ||
        el.shadowRoot || el.localName.includes('-') || generatedContent) {
      el.style.setProperty('display', 'none', 'important');
      if ('value' in el) el.value = '';
    }
    for (const name of ['title', 'alt', 'placeholder', 'aria-label', 'value']) {
      if (el.hasAttribute(name)) el.setAttribute(name, redact(el.getAttribute(name)));
    }
  }
  const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (!node.parentElement?.closest('script,style')) node.nodeValue = redact(node.nodeValue);
  }
  const rendered = document.body?.innerText || '';
  if (redact(rendered) !== rendered) return false;
  return true;
} catch (_) { return false; }
"""


def _safe_login_url(value: str) -> str:
    try:
        parts = urlsplit(str(value or ''))
        if parts.scheme not in {'http', 'https'} or not parts.hostname:
            return ''
        host = parts.hostname
        if ':' in host:
            host = f'[{host}]'
        if parts.port is not None:
            host += f':{parts.port}'
        return urlunsplit((parts.scheme, host, parts.path, '', ''))[:320]
    except (TypeError, ValueError):
        return ''


def _safe_login_text(value: object, secrets: tuple[str, ...], limit: int) -> str:
    text = str(value or '')
    text = re.sub(r'https?://[^\s<>"\']+', lambda match: _safe_login_url(match.group()), text, flags=re.I)
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret:
            text = re.sub(re.escape(secret), '[已遮蔽]', text, flags=re.I)
    text = re.sub(r'''((?:password|passwd|pwd|token|secret|cookie|authorization|session[_-]?id|api[_-]?key|密碼|帳號)["']?\s*[:=：]\s*)(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\r\n,;]+)''',
                  r'\1[已遮蔽]', text, flags=re.I)
    return text[:limit]


def _password_change_required(text: str, password_fields: int = 0) -> bool:
    compact = re.sub(r'\s+', '', text).lower()
    expired_pattern = r'密碼(?:有效期限?|使用期限)?(?:已經|已)?(?:到期|過期|逾期)|password.{0,20}expired'
    explicit = re.search(
        r'密碼(?:有效期限?|使用期限)?(?:已經|已)?(?:到期|過期|逾期)|'
        r'密碼(?:必須|須|需)(?:更換|變更|修改|更新|重設)|'
        r'(?:必須|請先|須先|需先|強制|請立即|請您|請).{0,12}(?:更換|變更|修改|更新|重設|重新設定)密碼|'
        r'password.{0,20}expired|passwordmustbechanged|(?:must|please|requiredto).{0,20}(?:change|reset|update).{0,10}password',
        compact,
    )
    form = password_fields >= 2 and re.search(r'(?:修改|更換|變更|更新|設定|重設).{0,8}(?:新)?密碼|新密碼|changepassword|newpassword', compact)
    mandatory = re.search(
        r'密碼(?:必須|須|需)(?:更換|變更|修改|更新|重設)|'
        r'(?:必須|請先|須先|需先|強制|請立即).{0,12}(?:更換|變更|修改|更新|重設|重新設定)密碼|'
        r'passwordmustbechanged|(?:must|requiredto).{0,20}(?:change|reset|update).{0,10}password', compact,
    )
    if re.search(r'定期|將於|將在|日後|天後|尚未到期|notexpired|expiresin', compact):
        explicit = re.search(expired_pattern, compact)
        if 'notexpired' in compact:
            explicit = None
    return bool(explicit or mandatory or form)


def _login_page_probe(driver: Any) -> dict:
    try:
        result = driver.execute_script(LOGIN_DIAGNOSTIC_PROBE_SCRIPT)
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


def _login_failure_code(error: Exception) -> str:
    if isinstance(error, LoginVerificationError) and error.reason_code != 'login_failed':
        return error.reason_code
    text = str(error or '')
    if _password_change_required(text):
        return 'password_change_required'
    if getattr(error, 'diagnostic_category', ''):
        return 'browser_start_failed'
    if isinstance(error, TimeoutError) or 'timeout' in type(error).__name__.lower():
        return 'login_timeout'
    if re.search(r'帳號.{0,8}密碼.{0,8}(?:有誤|錯誤|不正確)|invalid.{0,12}(?:credential|password)|incorrect.{0,12}password', text, re.I):
        return 'invalid_credentials'
    return 'login_failed'


def capture_login_diagnostic(
    driver: Any, reason: str, *, user_id: str = '', password: str = '',
    stage: str = 'login', reason_code: str = 'login_failed',
) -> dict:
    """Best-effort, bounded failure evidence; never expose raw HTML or input values."""
    secrets = tuple({variant for secret in (user_id, password) if secret
                     for variant in (secret, quote(secret, safe=''), quote_plus(secret, safe=''))})
    diagnostic = {
        'reason_code': reason_code, 'stage': stage,
        'reason': _safe_login_text(reason, secrets, 600),
        'page_url': '', 'page_title': '', 'page_text': '',
        'captured_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'capture_status': 'unavailable', 'image_redacted': False,
    }
    if driver is None:
        return diagnostic
    top_level = False
    try:
        driver.switch_to.default_content()
        top_level = True
    except Exception:
        pass
    probe = _login_page_probe(driver)
    diagnostic['page_text'] = _safe_login_text(probe.get('page_text'), secrets, 4000)
    for key, attribute, limit in (('page_url', 'current_url', 320), ('page_title', 'title', 160)):
        try:
            value = getattr(driver, attribute, '')
            if key == 'page_url':
                value = _safe_login_url(value)
            diagnostic[key] = _safe_login_text(value, secrets, limit)
        except Exception:
            pass
    try:
        if not top_level:
            return diagnostic
        if driver.execute_script(LOGIN_DIAGNOSTIC_REDACT_SCRIPT, list(secrets)) is not True:
            return diagnostic
        png = driver.get_screenshot_as_png()
        if not isinstance(png, bytes):
            return diagnostic
        if len(png) > 512 * 1024:
            diagnostic['capture_status'] = 'oversize'
            return diagnostic
        if len(png) < 33 or png[:8] != b'\x89PNG\r\n\x1a\n' or png[12:16] != b'IHDR':
            return diagnostic
        width, height = struct.unpack('>II', png[16:24])
        if not (0 < width <= 4096 and 0 < height <= 4096 and width * height <= 4194304):
            diagnostic['capture_status'] = 'oversize'
            return diagnostic
        diagnostic.update(capture_status='captured', image_redacted=True,
                          image_png=base64.b64encode(png).decode('ascii'))
    except Exception:
        pass
    return diagnostic


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


def create_login_webdriver(
    options: Any,
    *,
    profile_root: Path | None = None,
    prune_profiles: bool = True,
    write_diagnostics: bool = True,
) -> Any:
    from duty_rehearsal import build_driver

    arguments = tuple(str(argument) for argument in getattr(options, "arguments", ()) or ())
    headless = any(argument.startswith("--headless") for argument in arguments)
    passthrough_arguments = tuple(
        argument
        for argument in arguments
        if not argument.startswith("--headless") and not argument.startswith("--window-size")
    )
    browser_options: dict[str, Any] = {}
    if profile_root is not None:
        browser_options["profile_root"] = profile_root
    if not prune_profiles:
        browser_options["prune_profiles"] = False
    if not write_diagnostics:
        browser_options["write_diagnostics"] = False
    return build_driver(
        headless=headless,
        option_arguments=passthrough_arguments,
        **browser_options,
    )


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
        session_open_diagnostics: bool = True,
    ) -> None:
        self.options_factory = options_factory
        self.driver_factory = driver_factory
        self.configure_driver = configure_driver
        self.login_function = login_function
        self.actor_no_query = actor_no_query
        self.allow_post_login_lookup_warning = bool(allow_post_login_lookup_warning)
        self.defer_actor_resolution = bool(defer_actor_resolution)
        self.driver_cleanup = driver_cleanup
        self.session_open_diagnostics = bool(session_open_diagnostics)

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
        failure_diagnostic = None
        try:
            from duty_rehearsal import retry_duty_browser_session_open

            def create_browser() -> Any:
                nonlocal failure_diagnostic
                failure_diagnostic = None
                return self.driver_factory(self.options_factory())

            def initialize_browser(candidate: Any) -> None:
                nonlocal failure_diagnostic
                failure_stage = 'login'
                configuring = True
                try:
                    self.configure_driver(candidate)
                    configuring = False
                    self.login_function(candidate, user_id, password)
                    failure_stage = 'post_login'
                    probe = _login_page_probe(candidate)
                    fields = probe.get('password_fields', 0)
                    fields = fields if isinstance(fields, int) else 0
                    if _password_change_required(str(probe.get('page_text', '')), fields):
                        raise LoginVerificationError(
                            '密碼須更新：請至勤務網站手動完成密碼變更後，再重新登入。',
                            reason_code='password_change_required',
                        )
                except Exception as exc:
                    failure_diagnostic = capture_login_diagnostic(
                        candidate, str(exc).splitlines()[0] if str(exc) else '登入失敗。',
                        user_id=user_id, password=password, stage=failure_stage,
                        reason_code='browser_start_failed' if configuring else _login_failure_code(exc),
                    )
                    raise

            driver = retry_duty_browser_session_open(
                create_browser,
                initialize_browser,
                cleanup=self.driver_cleanup,
                write_diagnostics=self.session_open_diagnostics,
            )
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
        except Exception as exc:
            if failure_diagnostic is None:
                reason_code = _login_failure_code(exc)
                if driver is None and reason_code == 'login_failed':
                    reason_code = 'browser_start_failed'
                failure_diagnostic = capture_login_diagnostic(
                    driver, str(exc).splitlines()[0] if str(exc) else '登入失敗。',
                    user_id=user_id, password=password, stage='post_login' if driver is not None else 'login',
                    reason_code=reason_code,
                )
            if getattr(exc, 'diagnostic_category', ''):
                failure_diagnostic['reason_code'] = 'browser_start_failed'
                exc.login_diagnostic = failure_diagnostic
                raise
            raise LoginVerificationError(
                failure_diagnostic['reason'], login_diagnostic=failure_diagnostic,
                reason_code=failure_diagnostic['reason_code'],
            ) from None
        finally:
            if driver is not None:
                self.driver_cleanup(driver)
