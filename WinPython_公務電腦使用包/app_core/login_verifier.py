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


LOGIN_PAGE_LOAD_MESSAGES = {
    'website_dns_failed': '勤務網站暫時無法開啟：找不到伺服器 IP 位址（DNS 解析失敗）。請確認網路連線，稍後重新登入。',
    'website_offline': '勤務網站暫時無法開啟：目前網路未連線。請恢復網路後重新登入。',
    'website_timeout': '勤務網站讀取逾時，請確認網路與網站狀態，稍後重新登入。',
    'website_certificate_failed': '勤務網站無法開啟：安全憑證驗證失敗。請確認電腦日期時間或通知管理人員。',
    'website_connection_failed': '勤務網站暫時無法開啟：網站連線失敗或已中斷。請確認網路與網站狀態，稍後重新登入。',
}


CAPTURE_ERROR_MESSAGES = {
    'driver_unavailable': '瀏覽器尚未建立或已無法使用，無法擷取截圖。',
    'frame_context_failed': '無法切回主頁面，未執行截圖。',
    'redaction_rejected': '欄位或文字遮蔽檢查未通過，未執行截圖。',
    'redaction_failed': '遮蔽頁面時發生錯誤，未執行截圖。',
    'screenshot_failed': '瀏覽器擷取截圖時發生錯誤。',
    'invalid_image': '瀏覽器未回傳有效的 PNG 圖片。',
    'image_oversize': '圖片尺寸或容量超過保存限制。',
    'server_image_rejected': '後台圖片安全或格式驗證未通過，未保存截圖。',
}
CAPTURE_ERROR_TYPES = frozenset({
    'Error', 'TypeError', 'ValueError', 'RuntimeError', 'TimeoutError', 'AttributeError',
    'SecurityError', 'InvalidStateError', 'WebDriverException', 'TimeoutException',
    'JavascriptException', 'UnexpectedAlertPresentException', 'NoSuchWindowException',
    'InvalidSessionIdException', 'NoSuchFrameException', 'StaleElementReferenceException',
    'InvalidArgumentException',
})


def _capture_failed(diagnostic: dict, code: str, error_type: object = '') -> dict:
    diagnostic.update(
        capture_error_code=code, capture_error=CAPTURE_ERROR_MESSAGES[code],
        capture_error_type=error_type if isinstance(error_type, str) and error_type in CAPTURE_ERROR_TYPES else '',
    )
    return diagnostic


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
const rejected = {ok:false, error_code:'redaction_rejected', error_type:''};
if (window.top !== window) return rejected;
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
  const clearedControls = new Set();
  for (const el of document.querySelectorAll('*')) {
    const generatedContent = ['::before', '::after'].some(pseudo => {
      const content = window.getComputedStyle(el, pseudo).content;
      return content && !['none', 'normal', '""', "''"].includes(content);
    });
    if (el.matches('input,textarea,select,[contenteditable],frame,iframe,object,embed,canvas,video') ||
        el.shadowRoot || el.localName.includes('-') || generatedContent) {
      el.style.setProperty('display', 'none', 'important');
      if ('value' in el) el.value = '';
      if (el.matches('input,textarea,select')) clearedControls.add(el);
    }
    for (const name of ['title', 'alt', 'placeholder', 'aria-label', 'value']) {
      if (el.hasAttribute(name)) el.setAttribute(name, redact(el.getAttribute(name)));
    }
  }
  const visibleTextNodes = [];
  const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    const el = node.parentElement;
    if (!el || el.closest('script,style')) continue;
    node.nodeValue = redact(node.nodeValue);
    if (el.getClientRects().length && window.getComputedStyle(el).visibility !== 'hidden') visibleTextNodes.push(node);
  }
  const emptyFieldLabels = new Set();
  const isFieldLabel = value => /^(?:(?:帳\s*號|密\s*碼|account|username|password)\s*[:：]\s*)+$/i.test(String(value || '').trim());
  for (const control of clearedControls) {
    const row = control.closest('tr,label') || control.parentElement;
    if (!row || row === document.body || !isFieldLabel(row.innerText)) continue;
    const controls = Array.from(row.querySelectorAll('input,textarea,select'));
    if (!controls.length || !controls.every(el => clearedControls.has(el))) continue;
    for (const node of visibleTextNodes) {
      if (row.contains(node.parentElement) && isFieldLabel(node.nodeValue)) emptyFieldLabels.add(node);
    }
  }
  // Only proven empty form labels are excluded. Unassociated labels/values still
  // undergo both adjacent-node and cross-line checks, including unknown tokens.
  const verificationTexts = visibleTextNodes.filter(node => !emptyFieldLabels.has(node)).map(node => node.nodeValue);
  for (const separator of ['', '\n']) {
    const rendered = verificationTexts.join(separator);
    if (redact(rendered) !== rendered) return rejected;
  }
  return {ok:true};
} catch (error) { return {ok:false, error_code:'redaction_failed', error_type:error.name}; }
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


def _login_failure_code(error: Exception, *, page_text: str = '') -> str:
    text = str(error or '')
    network_error = re.search(r'\bnet::(ERR_[A-Z0-9_]+)\b', text, re.I)
    if not network_error and re.search(
        r'無法連上這個網站|無法存取這個網站|(?:你|您)的連線不是私人連線|'
        r'this site can.t be reached|your connection is not private', page_text, re.I,
    ):
        network_error = re.search(r'\b(ERR_[A-Z0-9_]+)\b', page_text, re.I)
    if network_error:
        code = network_error.group(1).upper()
        if code == 'ERR_NAME_NOT_RESOLVED' or code.startswith('ERR_DNS_'):
            return 'website_dns_failed'
        if code == 'ERR_INTERNET_DISCONNECTED':
            return 'website_offline'
        if code in {'ERR_TIMED_OUT', 'ERR_CONNECTION_TIMED_OUT'}:
            return 'website_timeout'
        if code.startswith(('ERR_CERT_', 'ERR_SSL_')):
            return 'website_certificate_failed'
        return 'website_connection_failed'
    if isinstance(error, LoginVerificationError) and error.reason_code != 'login_failed':
        return error.reason_code
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
        'capture_error_code': '', 'capture_error': '', 'capture_error_type': '',
    }
    if driver is None:
        return _capture_failed(diagnostic, 'driver_unavailable')
    top_level = False
    try:
        driver.switch_to.default_content()
        top_level = True
    except Exception as exc:
        _capture_failed(diagnostic, 'frame_context_failed', type(exc).__name__)
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
    if not top_level:
        return diagnostic
    try:
        redaction = driver.execute_script(LOGIN_DIAGNOSTIC_REDACT_SCRIPT, list(secrets))
    except Exception as exc:
        return _capture_failed(diagnostic, 'redaction_failed', type(exc).__name__)
    if redaction is not True:
        if not (isinstance(redaction, dict) and redaction.get('ok') is True
                and isinstance(redaction.get('error_code', ''), str) and redaction.get('error_code', '') == ''):
            code, error_type = 'redaction_rejected', ''
            if isinstance(redaction, dict):
                if redaction.get('error_code') == 'redaction_failed':
                    code = 'redaction_failed'
                error_type = redaction.get('error_type', '')
            return _capture_failed(diagnostic, code, error_type)
    try:
        png = driver.get_screenshot_as_png()
    except Exception as exc:
        return _capture_failed(diagnostic, 'screenshot_failed', type(exc).__name__)
    if not isinstance(png, bytes):
        return _capture_failed(diagnostic, 'invalid_image')
    if len(png) > 512 * 1024:
        diagnostic['capture_status'] = 'oversize'
        return _capture_failed(diagnostic, 'image_oversize')
    if len(png) < 33 or png[:8] != b'\x89PNG\r\n\x1a\n' or png[12:16] != b'IHDR':
        return _capture_failed(diagnostic, 'invalid_image')
    width, height = struct.unpack('>II', png[16:24])
    if not (0 < width <= 4096 and 0 < height <= 4096 and width * height <= 4194304):
        diagnostic['capture_status'] = 'oversize'
        return _capture_failed(diagnostic, 'image_oversize')
    diagnostic.update(capture_status='captured', image_redacted=True,
                      image_png=base64.b64encode(png).decode('ascii'),
                      capture_error_code='', capture_error='', capture_error_type='')
    return diagnostic


class OASessionExpiredError(LoginVerificationError):
    """The OA portal returned its session-timeout page after a login attempt."""


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


def run_oa_login(driver: Any, user_id: str, password: str, recognizer: Any = None,
                 *, attempts: int = 3) -> None:
    """Log into the OA portal with the existing in-memory CAPTCHA recognizer."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    if not user_id or not password:
        raise LoginVerificationError("請先設定入口網帳號密碼。")
    if recognizer is None:
        try:
            import ddddocr

            recognizer = ddddocr.DdddOcr(show_ad=False)
        except Exception:
            raise LoginVerificationError("入口網自動登入所需 OCR 未就緒，請確認使用包依賴。") from None

    def assert_login_target() -> None:
        target = urlsplit(str(driver.current_url or ""))
        if (target.scheme != "https" or target.netloc != "oa.tyfd.gov.tw"
                or target.path not in {"/login.php", "/login_main.php"}):
            raise LoginVerificationError("入口網登入頁來源或路徑不符，已停止填入帳密。")

    def set_input(wait, selector: str, value: str) -> None:
        assert_login_target()
        field = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, selector)))
        assert_login_target()
        field.clear()
        assert_login_target()
        field.send_keys(value)

    def logged_in(current) -> bool:
        target = urlsplit(str(current.current_url or ""))
        if target.scheme != "https" or target.netloc != "oa.tyfd.gov.tw":
            raise LoginVerificationError("入口網登入後來源不符，已停止操作。")
        if target.path == "/sess_exceed.php":
            raise OASessionExpiredError("入口網作業逾時，請重新登入。")
        return (target.path not in {"/login.php", "/login_main.php"}
                and not current.find_elements(By.CSS_SELECTOR, "#login_name, #verify_code, #loginBtn"))

    for _attempt in range(max(1, min(int(attempts), 3))):
        try:
            driver.get("https://oa.tyfd.gov.tw/login.php")
            assert_login_target()
            wait = WebDriverWait(driver, 15)
            set_input(wait, "#login_name", user_id)
            set_input(wait, "#password", password)
            captcha = wait.until(EC.visibility_of_element_located((By.ID, "checkcodeImg")))
            wait.until(lambda current: captcha.get_attribute("src") and captcha.size.get("width", 0) > 0)
            assert_login_target()
            # CAPTCHA pixels stay in memory; never persist a login screenshot.
            text = "".join(c for c in str(recognizer.classification(captcha.screenshot_as_png)) if c.isalnum())
            if not text:
                continue
            set_input(wait, "#verify_code", text)
            button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#loginBtn")))
            assert_login_target()
            button.click()
            wait.until(logged_in)
            return
        except LoginVerificationError:
            raise
        except Exception:
            continue
    raise LoginVerificationError("入口網自動登入未成功，請確認已儲存的帳密與網站狀態。") from None


AUTHENTICATED_DUTY_PAGE_SCRIPT = """
// duty-authenticated-page: read protected controls only; never submit or read credentials.
return Boolean(
    document.getElementById('_txtTaskDate') &&
    (document.getElementById('_btnQuery') || document.getElementById('_btnSearch')) &&
    !document.querySelector('input[type="password"]')
);
"""


def verify_duty_authentication(driver: Any) -> None:
    """Require a server-protected page before trusting saved identity or lookup warnings."""
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.support.ui import WebDriverWait
    from duty_rehearsal import DUTY_TABLE_AP, open_ap

    open_ap(driver, DUTY_TABLE_AP)
    try:
        WebDriverWait(driver, 15, poll_frequency=0.25).until(
            lambda current: current.execute_script(AUTHENTICATED_DUTY_PAGE_SCRIPT) is True
        )
    except TimeoutException:
        raise LoginVerificationError(
            '登入未通過勤務網站驗證，請確認帳號密碼後重新登入。',
            reason_code='authentication_unverified',
        ) from None


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
        detected_actor_no, actor_name = "", ""
        identity_error = None
        try:
            from duty_rehearsal import retry_duty_browser_session_open

            def create_browser() -> Any:
                nonlocal failure_diagnostic
                failure_diagnostic = None
                return self.driver_factory(self.options_factory())

            def initialize_browser(candidate: Any) -> None:
                nonlocal failure_diagnostic, detected_actor_no, actor_name, identity_error
                detected_actor_no, actor_name, identity_error = "", "", None
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
                    try:
                        detected_actor_no, actor_name = identify_logged_in_actor(candidate, actor_no_from_name, staff)
                    except Exception as exc:
                        identity_error = exc
                    # The protected-page probe navigates away from the login greeting.
                    # Preserve its identity first, but authorize no result before the probe passes.
                    verify_duty_authentication(candidate)
                except Exception as exc:
                    failure_diagnostic = capture_login_diagnostic(
                        candidate, str(exc).splitlines()[0] if str(exc) else '登入失敗。',
                        user_id=user_id, password=password, stage=failure_stage,
                        reason_code='browser_start_failed' if configuring else _login_failure_code(exc),
                    )
                    if not configuring:
                        failure_diagnostic['reason_code'] = _login_failure_code(
                            exc, page_text=failure_diagnostic.get('page_text', ''),
                        )
                    raise

            driver = retry_duty_browser_session_open(
                create_browser,
                initialize_browser,
                cleanup=self.driver_cleanup,
                write_diagnostics=self.session_open_diagnostics,
            )
            if identity_error is not None:
                if not self.allow_post_login_lookup_warning:
                    raise identity_error
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
            if (getattr(exc, 'diagnostic_category', '')
                    and failure_diagnostic['reason_code'] not in LOGIN_PAGE_LOAD_MESSAGES):
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
