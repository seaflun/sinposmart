"""Duty-PC civil-power attendance automation.

IO selectors, pagination and confirmation helpers extracted from rescue civilpower.py.
No ambulance task, Worker, NAS execution or sibling runtime imports.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from app_core.civilpower_service import AttendancePlan, AttendanceRequest, CivilpowerError, _write_json

OA_LOGIN_URL = "https://oa.tyfd.gov.tw/login.php"
CIVILPOWER_SSO_LOGIN_URL = "https://civilpower.tyfd.gov.tw/TYCC/Home/SSOLogin"
IO_WORK_LOG_URL = "https://civilpower.tyfd.gov.tw/TYCC/Home/IOWorkLog"
OUT_STATUS = "出"
DEFAULT_WAIT_SECONDS = 15
IO_QUERY_SETTLE_SECONDS = 5
CIVILPOWER_STAGE_LABELS = {
    "io_query": "查詢既有出入紀錄…", "io_add": "填寫出入登記…",
    "io_unit": "確認所屬及服勤單位…", "io_person": "選擇義消…",
    "io_save_verify": "儲存並回查出入紀錄…",
}
_DATE_PATTERN = re.compile(r"(?<!\d)\d{1,4}[/-]\d{1,2}[/-]\d{1,2}(?!\d)")
_DATETIME_PATTERN = re.compile(r"(?<!\d)(\d{1,4})[/-](\d{1,2})[/-](\d{1,2})[ T]+(?:(上午|下午)[ T]*)?(\d{1,2})[:：](\d{1,2})(?!\d)")


def _login_once(driver, request: AttendanceRequest, recognizer) -> None:
    driver.get(OA_LOGIN_URL)
    wait = WebDriverWait(driver, DEFAULT_WAIT_SECONDS)
    _set_input(wait, "#login_name", request.user_id)
    _set_input(wait, "#password", request.password)
    captcha = wait.until(EC.visibility_of_element_located((By.ID, "checkcodeImg")))
    wait.until(lambda _driver: captcha.get_attribute("src") and captcha.size.get("width", 0) > 0)
    # Keep CAPTCHA bytes in memory; never save a credential-bearing screenshot.
    text = "".join(c for c in recognizer.classification(captcha.screenshot_as_png) if c.isalnum())
    if not text:
        raise CivilpowerError("入口網驗證碼無法辨識。")
    _set_input(wait, "#verify_code", text)
    _click(wait, "#loginBtn")
    wait.until(lambda current: not _is_oa_login_page(current))
    open_civilpower_from_oa_dashboard(driver, wait)


def login_attendance(driver, request: AttendanceRequest, recognizer, progress) -> None:
    for attempt in range(1, 4):
        progress(f"使用本次值班人員帳號登入民力系統（{attempt}/3）…")
        try:
            _login_once(driver, request, recognizer)
            return
        except Exception:
            if attempt == 3:
                raise CivilpowerError("民力登入失敗，已使用同一值班帳號重試三次；請確認帳號與網站狀態。") from None


def run_attendance(package_root: Path, request: AttendanceRequest, plan: AttendancePlan, progress) -> str:
    from app_core.login_verifier import create_login_webdriver, configure_login_webdriver_timeouts
    from selenium.webdriver.chrome.options import Options

    # Persist only record identity and original actor, never the password.
    identity = json.dumps([plan.member_id, plan.date_text, plan.time_text, plan.status, plan.reason], ensure_ascii=False)
    ledger = Path(package_root) / "runtime_outputs" / "civilpower" / (hashlib.sha256(identity.encode()).hexdigest() + ".json")
    try:
        previous = json.loads(ledger.read_text(encoding="utf-8")) if ledger.exists() else {}
    except (OSError, ValueError):
        raise CivilpowerError("此筆登打查核紀錄無法讀取，請先人工確認網站紀錄。") from None
    if previous.get("state") == "pending_verification" and previous.get("user_id") != request.user_id:
        raise CivilpowerError("此筆曾送出但尚未確認，請由原登打帳號登入後回查，勿換帳號重送。")
    if previous.get("state") == "verified":
        return f"{plan.member_name} {plan.date_text} {plan.time_text[:2]}:{plan.time_text[2:]} {plan.reason}：此筆已確認完成，未重複新增。"
    try:
        import ddddocr
        recognizer = ddddocr.DdddOcr(show_ad=False)
    except Exception:
        raise CivilpowerError("民力自動登入所需 OCR 未就緒，請確認公務電腦使用包依賴已安裝。") from None
    driver = None
    checkpoint = {}
    try:
        options = Options()
        options.add_argument("--window-size=1280,900")
        driver = create_login_webdriver(options, profile_root=Path(package_root) / "runtime_outputs" / "civilpower_profiles",
                                        prune_profiles=False, write_diagnostics=False)
        configure_login_webdriver_timeouts(driver)
        login_attendance(driver, request, recognizer, progress)

        def before_save():
            _write_json(ledger, {"state": "pending_verification", "user_id": request.user_id,
                                 "updated_at": datetime.now().isoformat(timespec="seconds")})

        created = _ensure_io_record(driver, plan, plan.status, checkpoint, cancel_check=None,
                                    require_lookup_confirmation=True, progress=progress, before_save=before_save)
        _write_json(ledger, {"state": "verified", "user_id": request.user_id,
                            "updated_at": datetime.now().isoformat(timespec="seconds")})
        return f"{plan.member_name} {plan.date_text} {plan.time_text[:2]}:{plan.time_text[2:]} {plan.reason}：" + ("已儲存並回查確認。" if created else "網站已有相同紀錄，未重複新增。")
    except CivilpowerError:
        raise
    except Exception:
        if checkpoint.get("out_save_state") == "pending_verification" or checkpoint.get("in_save_state") == "pending_verification":
            raise CivilpowerError("已進入儲存階段，但結果尚未確認；請使用原值班帳號重試回查，勿另建不同時間的紀錄。") from None
        raise CivilpowerError("民力登打未完成；請確認網站及人員資料。查詢不明時不會新增紀錄。") from None
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


class _AmbiguousSelectionError(RuntimeError):
    pass


class _IncompleteQueryError(RuntimeError):
    pass


def open_civilpower_from_oa_dashboard(driver, wait: WebDriverWait) -> None:
    _click(wait, "#moduleBox_other")
    sso_entry = wait.until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, ".custom_icon[onclick*='SSOLogin']"))
    )
    existing_handles = set(driver.window_handles)
    sso_entry.click()
    wait.until(
        lambda current: any(handle not in existing_handles for handle in current.window_handles)
        or CIVILPOWER_SSO_LOGIN_URL in str(current.current_url or "")
    )
    new_handles = [handle for handle in driver.window_handles if handle not in existing_handles]
    if new_handles:
        driver.switch_to.window(new_handles[-1])
    _wait_for_civilpower_page(driver, wait)


def _is_oa_login_page(driver) -> bool:
    return bool(driver.find_elements(By.CSS_SELECTOR, "#login_name, #verify_code, #loginBtn"))


def _wait_for_civilpower_page(driver, wait: WebDriverWait) -> None:
    def ready(current) -> bool:
        if _is_oa_login_page(current) or _is_civilpower_login_page(current):
            return False
        body_text = _clean_text(current.find_element(By.TAG_NAME, "body").text)
        return "民力運用" in body_text or "/TYCC/" in str(current.current_url or "")

    wait.until(ready)


def _is_civilpower_login_page(driver) -> bool:
    return _clean_text(getattr(driver, "title", "")).lower() == "login"


def _ensure_io_record(
    driver,
    plan: AttendancePlan,
    status: str,
    checkpoint: dict[str, object],
    *,
    cancel_check: Callable[[], None] | None,
    require_lookup_confirmation: bool = False,
    progress: Callable[[str], None] | None = None,
    before_save: Callable[[], None] | None = None,
) -> bool:
    marker = "out" if status == OUT_STATUS else "in"
    lookup_kwargs = {"raise_on_timeout": True} if require_lookup_confirmation else {}
    _raise_if_cancelled(cancel_check)
    _report_progress(progress, CIVILPOWER_STAGE_LABELS["io_query"])
    if _find_io_record(
        driver,
        plan,
        status,
        wait_for_match=False,
        require_query_confirmation=True,
        **lookup_kwargs,
    ):
        checkpoint[f"{marker}_verified"] = True
        checkpoint[f"{marker}_save_state"] = "verified"
        return False
    wait = WebDriverWait(driver, DEFAULT_WAIT_SECONDS)
    _report_progress(progress, CIVILPOWER_STAGE_LABELS["io_add"])
    _click(wait, "#btn_Add")
    _wait_visible(wait, "#jqxAddWindow")
    _select_jqx_combobox(driver, wait, "#txt_AddUnit", plan.home_unit)
    _report_progress(progress, CIVILPOWER_STAGE_LABELS["io_unit"])
    _wait_for_io_form_dependencies(driver, wait, plan)
    _select_jqx_combobox(driver, wait, "#txt_AddServeUnit", plan.serve_unit)
    _report_progress(progress, CIVILPOWER_STAGE_LABELS["io_person"])
    _select_io_person(driver, wait, plan)
    date_text = plan.date_text
    time_text = plan.time_text
    _set_input(wait, "#txt_AddLogDate", date_text)
    _set_input(wait, "#txt_AddLogHour", time_text[:2])
    _set_input(wait, "#txt_AddLogMin", time_text[2:])
    _select_jqx_combobox(driver, wait, "#txt_AddServeUnit", plan.serve_unit)
    _select_option_containing(wait, "#ddl_AddIO", status)
    _set_input(wait, "#txt_AddReason", plan.reason)
    _wait_for_io_record_form_values(driver, wait, plan, status)
    _raise_if_cancelled(cancel_check)
    _report_progress(progress, CIVILPOWER_STAGE_LABELS["io_save_verify"])
    checkpoint[f"{marker}_save_state"] = "pending_verification"
    if before_save is not None:
        before_save()
    _click(wait, "#btn_IOWorkLogAdd")
    _wait_after_save(driver, wait, "#jqxAddWindow")
    _raise_if_cancelled(cancel_check)
    if not _find_io_record(
        driver,
        plan,
        status,
        wait_for_match=True,
        reload_page=False,
        **lookup_kwargs,
    ):
        raise RuntimeError(f"出入登記簿儲存後回查不到{status}／{plan.reason}紀錄。")
    checkpoint[f"{marker}_verified"] = True
    checkpoint[f"{marker}_save_state"] = "verified"
    return True


def _open_io_work_log(driver) -> None:
    driver.get(IO_WORK_LOG_URL)
    _wait_for_civilpower_page(driver, WebDriverWait(driver, DEFAULT_WAIT_SECONDS))


def _find_io_record(
    driver,
    plan: AttendancePlan,
    status: str,
    *,
    wait_for_match: bool = False,
    reload_page: bool = True,
    raise_on_timeout: bool = False,
    require_query_confirmation: bool = False,
) -> bool:
    return _find_io_record_row(
        driver,
        plan,
        status,
        wait_for_match=wait_for_match,
        reload_page=reload_page,
        raise_on_timeout=raise_on_timeout,
        require_query_confirmation=require_query_confirmation,
    ) is not None


def _find_io_record_row(
    driver,
    plan: AttendancePlan,
    status: str,
    *,
    wait_for_match: bool = False,
    reload_page: bool = True,
    raise_on_timeout: bool = False,
    require_query_confirmation: bool = False,
):
    if reload_page:
        _open_io_work_log(driver)
    wait = WebDriverWait(driver, DEFAULT_WAIT_SECONDS)
    date_text = plan.date_text
    time_text = plan.time_text
    _set_if_present(driver, wait, "#txt_Name", plan.member_name)
    _set_if_present(driver, wait, "#txt_Date_S", date_text)
    _set_if_present(driver, wait, "#txt_Date_E", date_text)
    _select_option_containing_if_present(driver, wait, "#ddl_IO", status)
    previous_result_signature = _io_result_grid_signature(driver)
    previous_result_sentinel = _io_result_grid_sentinel(driver)
    _click_if_present(driver, wait, "#btn_Query")
    tokens = [
        status,
        plan.member_name,
        plan.home_unit,
        plan.serve_unit,
        plan.reason,
        _datetime_token(date_text, time_text),
    ]
    query_result_confirmed = _wait_for_io_query_result_grid(
        driver,
        tokens,
        previous_result_signature,
        previous_result_sentinel,
    )
    if not query_result_confirmed:
        if require_query_confirmation or raise_on_timeout:
            raise RuntimeError("出入登記簿查詢結果未完成更新，為避免重複新增，請保持原登入帳號後重試。")
        return None
    rows = _find_paginated_table_rows(driver, wait, tokens)
    if not rows and wait_for_match:
        try:
            rows = wait.until(lambda current: _find_paginated_table_rows(current, wait, tokens) or False)
        except TimeoutException:
            if raise_on_timeout:
                raise RuntimeError(f"出入登記簿查詢逾時，無法確認{status}紀錄；請保持原登入帳號後重試。")
            return None
    if len(rows) > 1:
        raise RuntimeError(f"出入登記簿找到多筆相同{status}紀錄，無法安全判定。")
    return rows[0] if rows else None


def _io_result_grid_signature(driver) -> str | None:
    find_element = getattr(driver, "find_element", None)
    if not callable(find_element):
        return None
    try:
        result_grid = find_element(By.CSS_SELECTOR, "#tableresult")
        return str(result_grid.get_attribute("innerHTML") or "")
    except (NoSuchElementException, StaleElementReferenceException):
        return None


def _io_result_grid_sentinel(driver):
    find_elements = getattr(driver, "find_elements", None)
    if not callable(find_elements):
        return None
    try:
        children = find_elements(By.CSS_SELECTOR, "#tableresult > *")
    except (NoSuchElementException, StaleElementReferenceException):
        return None
    if not isinstance(children, (list, tuple)) or not children:
        return None
    return children[0]


def _wait_for_io_query_result_grid(
    driver,
    tokens: list[str],
    previous_signature: str | None,
    previous_sentinel=None,
) -> bool:
    # Existing rows are not evidence that the latest query has finished.
    if previous_signature is None and previous_sentinel is None:
        return False

    def sentinel_replaced() -> bool:
        if previous_sentinel is None:
            return False
        try:
            return bool(EC.staleness_of(previous_sentinel)(driver))
        except (NoSuchElementException, StaleElementReferenceException):
            return True

    def query_result_ready(current) -> bool:
        execute_script = getattr(current, "execute_script", None)
        if callable(execute_script) and execute_script("return Boolean(window.jQuery && window.jQuery.active);") is True:
            return False
        if sentinel_replaced():
            return True
        current_signature = _io_result_grid_signature(current)
        return previous_signature is not None and current_signature is not None and current_signature != previous_signature

    try:
        WebDriverWait(driver, IO_QUERY_SETTLE_SECONDS, poll_frequency=0.2).until(query_result_ready)
        return True
    except TimeoutException:
        return False


def _select_io_person(driver, wait: WebDriverWait, plan: AttendancePlan) -> None:
    _click(wait, "#btn_AddSltMan")
    tokens = [plan.home_unit, plan.member_name]
    if plan.member_title:
        tokens.append(plan.member_title)
    dialog, row = _wait_for_io_person_dialog_row(driver, wait, tokens)
    _click_dialog_row(driver, row)
    _confirm_dialog(driver, wait, dialog)
    _wait_for_io_person_value(driver, wait, plan.member_name)


def _wait_for_io_person_dialog_row(driver, wait: WebDriverWait, tokens: list[str]):
    def find_row(current):
        dialogs = [
            dialog
            for dialog in current.find_elements(By.CSS_SELECTOR, "#jqxSltWindow")
            if dialog.is_displayed()
        ]
        if not dialogs:
            return False
        dialog = dialogs[-1]
        rows = _find_paginated_table_rows(dialog, wait, tokens)
        if len(rows) > 1:
            raise RuntimeError("人員選取視窗找到多筆符合條件的紀錄，無法安全選取：" + "、".join(tokens))
        if not rows:
            return False
        return dialog, rows[0]

    return wait.until(find_row)


def _wait_for_io_person_value(driver, wait: WebDriverWait, member_name: str) -> None:
    wait.until(lambda current: member_name in _control_value(current, "#txt_AddVolFMan"))


def _click_dialog_row_action(driver, row, action_text: str) -> bool:
    expected_text = _clean_text(action_text).replace(" ", "")
    try:
        candidates = row.find_elements(
            By.CSS_SELECTOR,
            "input[type='button'], input[type='submit'], button, a, [role='button'], .jqx-button",
        )
    except (NoSuchElementException, StaleElementReferenceException):
        return False
    for candidate in candidates:
        try:
            candidate_texts = [
                str(candidate.get_attribute(attribute) or "")
                for attribute in ("value", "title", "aria-label", "innerText", "textContent")
            ]
            candidate_texts.append(str(candidate.text or ""))
            selectable = candidate.is_displayed() and candidate.is_enabled()
        except Exception:
            continue
        if not selectable or not any(
            _clean_text(candidate_text).replace(" ", "") == expected_text
            for candidate_text in candidate_texts
        ):
            continue
        try:
            candidate.click()
        except Exception:
            try:
                clicked = driver.execute_script("arguments[0].click(); return true;", candidate)
            except Exception as exc:
                raise RuntimeError(f"選取視窗的「{action_text}」按鈕無法點選。") from exc
            if not clicked:
                raise RuntimeError(f"選取視窗的「{action_text}」按鈕無法點選。")
        return True
    return False


def _click_dialog_row(driver, row) -> None:
    controls = row.find_elements(By.CSS_SELECTOR, "input[type='checkbox'], input[type='radio'], button, input[type='button']")
    for control in controls:
        try:
            if control.is_displayed() and control.is_enabled():
                control.click()
                return
        except Exception:
            continue
    try:
        row.click()
        return
    except Exception:
        pass
    try:
        dispatched = driver.execute_script(
            """
            const row = arguments[0];
            const cells = Array.from(row.querySelectorAll("[role='gridcell'], .jqx-grid-cell"));
            const target = cells.find((cell) => cell.getClientRects().length) || row;
            if (!target || !target.isConnected) return false;
            target.scrollIntoView({block: 'center', inline: 'nearest'});
            for (const type of ['mousedown', 'mouseup', 'click']) {
              target.dispatchEvent(new MouseEvent(type, {
                bubbles: true,
                cancelable: true,
                view: window,
                button: 0,
                buttons: type === 'mousedown' ? 1 : 0,
              }));
            }
            return true;
            """,
            row,
        )
        if dispatched:
            return
    except Exception as exc:
        raise RuntimeError("選取視窗的符合紀錄無法選取。") from exc
    raise RuntimeError("選取視窗的符合紀錄無法選取。")


def _confirm_dialog(driver, wait: WebDriverWait, dialog) -> None:
    if _is_stale(dialog) or not dialog.is_displayed():
        return
    candidates = driver.find_elements(
        By.CSS_SELECTOR,
        "input[type='button'], input[type='submit'], button, a, [role='button'], .jqx-button",
    )
    for candidate in candidates:
        try:
            text = _clean_text(
                " ".join(
                    str(candidate.get_attribute(attribute) or "")
                    for attribute in ("value", "title", "aria-label")
                )
                + " "
                + str(candidate.text or "")
            )
            selectable = candidate.is_displayed() and candidate.is_enabled()
        except Exception:
            continue
        if selectable and "確認選取" in text.replace(" ", ""):
            try:
                candidate.click()
            except Exception:
                try:
                    clicked = driver.execute_script("arguments[0].click(); return true;", candidate)
                except Exception as exc:
                    raise RuntimeError("選取視窗的確認按鈕無法點選。") from exc
                if not clicked:
                    raise RuntimeError("選取視窗的確認按鈕無法點選。")
            _wait_for_dialog_close(wait, dialog)
            return
    raise RuntimeError("選取視窗找不到「確認選取」按鈕。")


def _wait_for_dialog_close(wait: WebDriverWait, dialog) -> None:
    wait.until(lambda _current: _is_stale(dialog) or not dialog.is_displayed())


def _wait_after_save(driver, wait: WebDriverWait, modal_selector: str) -> None:
    try:
        wait.until(lambda current: not _element_displayed(current, modal_selector))
    except TimeoutException:
        body_text = _clean_text(driver.find_element(By.TAG_NAME, "body").text)
        if any(token in body_text for token in ("失敗", "錯誤", "請輸入", "必填")):
            raise RuntimeError("民力運用系統未接受儲存：" + body_text[-300:])
    _dismiss_save_success_dialog(driver, wait)


def _dismiss_save_success_dialog(driver, wait: WebDriverWait) -> None:
    dialog = _visible_save_success_dialog(driver)
    if dialog is None:
        try:
            short_wait = WebDriverWait(driver, min(3, DEFAULT_WAIT_SECONDS))
            dialog = short_wait.until(lambda current: _visible_save_success_dialog(current) or False)
        except TimeoutException:
            return
    try:
        clicked = _click_dialog_row_action(driver, dialog, "確定")
    except RuntimeError as exc:
        raise RuntimeError("民力系統新增成功提示的「確定」按鈕無法點選。") from exc
    if not clicked:
        raise RuntimeError("民力系統顯示新增成功，但找不到「確定」按鈕。")
    _wait_for_dialog_close(wait, dialog)


def _visible_save_success_dialog(driver):
    candidates = driver.find_elements(By.CSS_SELECTOR, ".swal2-popup, .sweet-alert, [role='dialog']")
    for candidate in candidates:
        try:
            text = _clean_text(candidate.text)
            if candidate.is_displayed() and any(
                marker in text for marker in ("新增成功", "編輯成功", "儲存成功", "存檔成功", "操作成功")
            ):
                return candidate
        except Exception:
            continue
    return None


def _pagination_links(root, direction: str) -> list[object]:
    finder = getattr(root, "find_elements", None)
    if not callable(finder):
        return []
    links = finder(By.CSS_SELECTOR, f".pagination li:not(.disabled) a[rel='{direction}']")
    return [link for link in links if link.is_displayed()] if isinstance(links, (list, tuple)) else []


def _pagination_signature(root) -> tuple:
    pages = root.find_elements(By.CSS_SELECTOR, ".pagination .active")
    return tuple(row.text for row in _table_rows(root)), tuple(page.text for page in pages)


def _change_result_page(root, wait: WebDriverWait, direction: str) -> None:
    links = _pagination_links(root, direction)
    if len(links) != 1:
        raise _IncompleteQueryError("民力查詢翻頁按鈕無法唯一定位，已停止避免漏查或重複新增。")
    previous = _pagination_signature(root)
    links[0].click()

    def ready(driver):
        try:
            if driver.execute_script("return Boolean(window.jQuery && window.jQuery.active);") is True:
                return False
            return _pagination_signature(root) != previous
        except (NoSuchElementException, StaleElementReferenceException):
            return False

    try:
        wait.until(ready)
    except TimeoutException as exc:
        raise _IncompleteQueryError("民力查詢翻頁後資料未完成更新，已停止避免漏查或重複新增。") from exc


def _find_paginated_table_rows(
    root, wait: WebDriverWait, required_tokens: list[str], *, row_filter=None
) -> list[object]:
    def matching_rows():
        rows = _matching_table_rows(root, required_tokens)
        return [row for row in rows if row_filter(row)] if row_filter is not None else rows

    rows = matching_rows()
    if not _pagination_links(root, "next"):
        return rows
    matched_count = len(rows)
    matched_page = 0 if rows else None
    page = 0
    signatures = [_pagination_signature(root)]
    seen = {signatures[0]}
    while _pagination_links(root, "next"):
        if page >= 99:
            raise _IncompleteQueryError("民力查詢超過 100 頁，請縮小日期範圍後重試；尚未確認紀錄不存在。")
        _change_result_page(root, wait, "next")
        page += 1
        signature = _pagination_signature(root)
        if signature in seen:
            raise _IncompleteQueryError("民力查詢翻頁重複回到已讀頁面，已停止避免漏查。")
        seen.add(signature)
        signatures.append(signature)
        rows = matching_rows()
        if rows:
            matched_count += len(rows)
            matched_page = page
        if matched_count > 1:
            raise _AmbiguousSelectionError("民力查詢找到多筆符合條件的紀錄，無法安全選取：" + "、".join(required_tokens))
    # Selenium rows from earlier pages are stale. Return to the match and acquire it again.
    # A miss returns to the starting page so a different lookup criterion can scan all pages.
    target_page = matched_page if matched_page is not None else 0
    while page > target_page:
        _change_result_page(root, wait, "prev")
        page -= 1
        if _pagination_signature(root) != signatures[page]:
            raise _IncompleteQueryError("民力查詢翻頁期間資料已變動，請重新查詢；尚未確認紀錄不存在。")
    if not matched_count:
        return []
    rows = matching_rows()
    if len(rows) != 1:
        raise _IncompleteQueryError("民力查詢返回符合頁面後資料已變動，請重新查詢；尚未確認紀錄不存在。")
    return rows


def _matching_table_rows(driver, required_tokens: list[str]) -> list[object]:
    matches: list[object] = []
    for _ in range(2):
        matches = []
        refreshed = False
        try:
            table_rows = _table_rows(driver)
        except StaleElementReferenceException:
            continue
        for row in table_rows:
            try:
                row_text = _clean_text(row.text)
            except StaleElementReferenceException:
                refreshed = True
                continue
            if all(_token_matches(row_text, token) for token in required_tokens if token):
                matches.append(row)
        if not refreshed:
            return matches
    return matches


def _table_rows(driver) -> list[object]:
    rows: list[object] = []
    selectors = "table tbody tr, table tr, [role='row'], .jqx-grid-row"
    seen_ids: set[str] = set()
    for row in driver.find_elements(By.CSS_SELECTOR, selectors):
        try:
            row_id = str(getattr(row, "id", "") or "")
            if row_id and row_id in seen_ids:
                continue
            if row_id:
                seen_ids.add(row_id)
            if row.is_displayed() and _row_cells(row):
                rows.append(row)
        except StaleElementReferenceException:
            raise
        except Exception:
            continue
    return rows


def _row_cells(row) -> list[object]:
    return row.find_elements(By.CSS_SELECTOR, "td, [role='gridcell'], .jqx-grid-cell")


def _wait_for_io_form_dependencies(
    driver,
    wait: WebDriverWait,
    plan: AttendancePlan,
) -> None:
    _wait_for_jqx_combobox_option(driver, wait, "#txt_AddServeUnit", plan.serve_unit)
    wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#btn_AddSltMan")))


def _wait_for_jqx_combobox_option(driver, wait: WebDriverWait, selector: str, text: str) -> None:
    wait.until(lambda current: _jqx_combobox_option_ready(current, selector, text))


def _jqx_combobox_option_ready(driver, selector: str, text: str) -> bool:
    try:
        element = driver.find_element(By.CSS_SELECTOR, selector)
    except NoSuchElementException:
        return False
    try:
        return bool(
            driver.execute_script(
                """
                const outer = arguments[0];
                const expected = arguments[1].replace(/\\s+/g, ' ').trim();
                const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
                if (!window.jQuery || !window.jQuery.fn || !window.jQuery.fn.jqxComboBox) return true;
                try {
                  const widget = window.jQuery(outer);
                  if (widget.jqxComboBox('disabled')) return false;
                  const items = widget.jqxComboBox('getItems') || [];
                  return items.some((item) => clean(item.label) === expected || clean(item.value) === expected);
                } catch (_) {
                  return false;
                }
                """,
                element,
                text,
            )
        )
    except StaleElementReferenceException:
        return False


def _select_jqx_combobox(driver, wait: WebDriverWait, selector: str, text: str) -> None:
    _wait_for_jqx_combobox_option(driver, wait, selector, text)
    def select_option(current) -> bool:
        try:
            element = current.find_element(By.CSS_SELECTOR, selector)
            return bool(
                current.execute_script(
                    """
                    const outer = arguments[0];
                    const expected = arguments[1].replace(/\\s+/g, ' ').trim();
                    const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
                    const input = outer.matches('input') ? outer : outer.querySelector('input');
                    if (window.jQuery && window.jQuery.fn && window.jQuery.fn.jqxComboBox) {
                      const widget = window.jQuery(outer);
                      try {
                        if (widget.jqxComboBox('disabled')) return false;
                        const items = widget.jqxComboBox('getItems') || [];
                        const item = items.find((candidate) => clean(candidate.label) === expected || clean(candidate.value) === expected);
                        if (!item) return false;
                        widget.jqxComboBox('selectItem', item);
                        widget.jqxComboBox('val', item.value);
                        if (input) input.dispatchEvent(new Event('change', {bubbles: true}));
                        return true;
                      } catch (_) {
                        return false;
                      }
                    }
                    if (input) {
                      input.focus();
                      input.value = expected;
                      input.dispatchEvent(new Event('input', {bubbles: true}));
                      input.dispatchEvent(new Event('change', {bubbles: true}));
                      input.blur();
                      return true;
                    }
                    return false;
                    """,
                    element,
                    text,
                )
            )
        except (NoSuchElementException, StaleElementReferenceException):
            return False

    wait.until(select_option)
    wait.until(lambda current: _token_matches(_control_value(current, selector), text))


def _wait_for_io_record_form_values(
    driver,
    wait: WebDriverWait,
    plan: AttendancePlan,
    status: str,
) -> None:
    expected_values = {
        "#txt_AddLogDate": plan.date_text,
        "#txt_AddLogHour": plan.time_text[:2],
        "#txt_AddLogMin": plan.time_text[2:],
        "#txt_AddUnit": plan.home_unit,
        "#txt_AddServeUnit": plan.serve_unit,
        "#txt_AddReason": plan.reason,
    }
    for selector, expected_value in expected_values.items():
        wait.until(
            lambda current, selector=selector, expected_value=expected_value: _same_value(
                _control_value(current, selector),
                expected_value,
            )
        )
    wait.until(lambda current: plan.member_name in _control_value(current, "#txt_AddVolFMan"))
    wait.until(lambda current: _selected_option_text(current, "#ddl_AddIO") == status)


def _selected_option_text(driver, selector: str) -> str:
    try:
        return _clean_text(Select(driver.find_element(By.CSS_SELECTOR, selector)).first_selected_option.text)
    except NoSuchElementException:
        return ""


def _select_option_containing(wait: WebDriverWait, selector: str, text: str, *, clear_others: bool = False) -> None:
    element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
    select = Select(element)
    if clear_others and select.is_multiple:
        select.deselect_all()
    matches = [option for option in select.options if _token_matches(_clean_text(option.text), text)]
    if len(matches) != 1:
        raise RuntimeError(f"下拉選單找不到唯一選項：{selector}={text}")
    select.select_by_visible_text(matches[0].text)


def _select_option_containing_if_present(driver, wait: WebDriverWait, selector: str, text: str) -> None:
    if driver.find_elements(By.CSS_SELECTOR, selector):
        _select_option_containing(wait, selector, text)


def _set_input(wait: WebDriverWait, selector: str, value: str) -> None:
    element = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
    element.clear()
    element.send_keys(value)
    element.send_keys("\t")


def _set_if_present(driver, wait: WebDriverWait, selector: str, value: str) -> None:
    if driver.find_elements(By.CSS_SELECTOR, selector):
        _set_input(wait, selector, value)


def _click(wait: WebDriverWait, selector: str) -> None:
    wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector))).click()


def _click_if_present(driver, wait: WebDriverWait, selector: str) -> None:
    if driver.find_elements(By.CSS_SELECTOR, selector):
        _click(wait, selector)


def _wait_visible(wait: WebDriverWait, selector: str):
    return wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, selector)))


def _control_value(driver, selector: str) -> str:
    try:
        element = driver.find_element(By.CSS_SELECTOR, selector)
    except NoSuchElementException:
        return ""
    value = element.get_attribute("value")
    if value:
        return _clean_text(value)
    if selector.startswith("#txt_"):
        nested = element.find_elements(By.CSS_SELECTOR, "input")
        if nested:
            return _clean_text(nested[0].get_attribute("value"))
    return _clean_text(element.text)


def _element_displayed(driver, selector: str) -> bool:
    elements = driver.find_elements(By.CSS_SELECTOR, selector)
    return any(element.is_displayed() for element in elements)


def _same_value(actual: str, expected: str) -> bool:
    actual_date = _date_parts(actual)
    expected_date = _date_parts(expected)
    if actual_date is not None and expected_date is not None:
        return actual_date == expected_date
    clean_actual = _clean_text(actual)
    clean_expected = _clean_text(expected)
    if clean_actual.isdigit() and clean_expected.isdigit():
        return int(clean_actual) == int(clean_expected)
    return clean_actual == clean_expected


def _date_parts(value: object) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"(\d{1,4})\D+(\d{1,2})\D+(\d{1,2})", _clean_text(value))
    if match is None:
        return None
    year, month, day = map(int, match.groups())
    if year == 0:
        return None
    # List rows use ROC years; query controls and imported fields use Gregorian years.
    if len(match.group(1)) < 4:
        year += 1911
    try:
        parsed = datetime(year, month, day)
    except ValueError:
        return None
    return parsed.year, parsed.month, parsed.day


def _datetime_parts(match) -> tuple[int, int, int, int, int] | None:
    parts = _date_parts("/".join(match.groups()[:3]))
    meridiem = match.group(4) or ""
    hour, minute = map(int, match.groups()[4:])
    if meridiem:
        if not 1 <= hour <= 12:
            return None
        if meridiem == "上午":
            hour = 0 if hour == 12 else hour
        else:
            hour = 12 if hour == 12 else hour + 12
    if parts is None or not (0 <= hour < 24 and 0 <= minute < 60):
        return None
    return (*parts, hour, minute)


def _token_matches(text: str, token: str) -> bool:
    actual = _clean_text(text)
    expected = _clean_text(token)
    if not expected:
        return True
    if expected in {"入", "出", "到勤", "退勤"}:
        return expected in actual.split()
    expected_datetime = _DATETIME_PATTERN.fullmatch(expected)
    if expected_datetime:
        parts = _datetime_parts(expected_datetime)
        return parts is not None and any(
            _datetime_parts(match) == parts for match in _DATETIME_PATTERN.finditer(actual)
        )
    expected_date = _date_parts(expected)
    if expected_date:
        return any(_date_parts(match.group()) == expected_date for match in _DATE_PATTERN.finditer(actual))
    if _valid_hhmm(expected):
        times = re.findall(r"(?<![\d:/])([01]?\d|2[0-3])[:：]([0-5]?\d)(?!\d)", actual)
        return any(_time_from_parts(hour, minute) == expected for hour, minute in times) or expected in actual.split()
    if expected.isdigit():
        return re.search(r"(?<!\d)" + re.escape(expected) + r"(?!\d)", actual) is not None
    return expected in actual


def _datetime_token(date_text: str, hhmm: str) -> str:
    return f"{date_text} {hhmm[:2]}:{hhmm[2:]}"


def _time_from_parts(hour: str, minute: str) -> str:
    hour, minute = _clean_text(hour), _clean_text(minute)
    if not re.fullmatch(r"\d{1,2}", hour) or not re.fullmatch(r"\d{1,2}", minute):
        return ""
    if int(hour) > 23 or int(minute) > 59:
        return ""
    return f"{int(hour):02d}{int(minute):02d}"


def _valid_hhmm(value: str) -> bool:
    return bool(re.fullmatch(r"([01]\d|2[0-3])[0-5]\d", value))


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").split())


def _raise_if_cancelled(cancel_check: Callable[[], None] | None) -> None:
    if cancel_check is not None:
        cancel_check()


def _report_progress(progress: Callable[[str], None] | None, stage: str) -> None:
    if progress is not None:
        progress(stage)


def _is_stale(element) -> bool:
    try:
        _ = element.is_displayed()
        return False
    except Exception:
        return True
