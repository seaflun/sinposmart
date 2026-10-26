from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import traceback
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlsplit
from pathlib import Path
from typing import Iterable
from uuid import uuid4

try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv(_path: Path) -> None:
        return None
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException, TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


PACKAGE_DIR = Path(__file__).resolve().parents[2]
if str(PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGE_DIR))

from duty_rehearsal import (
    DEFAULT_BROWSER_RETENTION_SECONDS,
    build_driver,
    quit_driver,
    retry_duty_browser_session_open,
)


ROOT_DIR = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = ROOT_DIR / "artifacts"

BASE_URL = "https://ppe.tyfd.gov.tw"
LOGIN_URL = f"{BASE_URL}/"
MAINTAIN_LIST_URL = f"{BASE_URL}/CarMaintainCheck/Index"
EQUIP_CHECK_LIST_URL = f"{BASE_URL}/CarEquipCheck/Index"
TEXT_LOGOUT = "\u767b\u51fa"
TEXT_MAINTAIN = "\u4fdd\u990a"
TEXT_RETURN_TO_LIST = "\u8fd4\u56de\u5217\u8868"
TEXT_SEARCH = "\u67e5\u8a62"
TEXT_EQUIP_CHECK = "\u6e05\u9ede"
TEXT_REVIEW = "\u6aa2\u8996"
TEXT_FINISH_EQUIP_CHECK = "\u5b8c\u6210\u6e05\u9ede"
EQUIPMENT_BUTTON_XPATH = f".//button[text()='{TEXT_EQUIP_CHECK}' or contains(., '{TEXT_EQUIP_CHECK}')]"
REPORT_PREFIX = "[sinposmart-vehicle-report] "
MAX_REPORT_ITEMS = 200
GRID_STATE_SCRIPT = """
return (() => {
    const grid = window.jQuery && window.jQuery('#grid').data('kendoGrid');
    if (!grid || !grid.dataSource) return null;
    const source = grid.dataSource;
    const filter = source.filter();
    return {total: source.total(), page: source.page() ?? null,
            page_size: source.pageSize() ?? null,
            filtered: !!filter && (!Array.isArray(filter.filters) || filter.filters.length > 0)};
})();
"""
GRID_PAGE_READY_SCRIPT = """
const [pathname, queryName, requireGrid] = arguments;
try {
    if (window.location.pathname !== pathname || document.readyState !== 'complete' ||
        typeof window.jQuery !== 'function' || typeof window[queryName] !== 'function' ||
        window.jQuery.active !== 0) return false;
    const holder = window.jQuery('#grid');
    if (!holder || typeof holder.data !== 'function') return false;
    if (!requireGrid) return true;
    // Maintenance schedules its initial QueryData up to 500 ms after document.ready.
    const initialQueryUrl = window.location.origin + '/CarMaintainCheck/QueryProc';
    if (!window.performance.getEntriesByType('resource').some(entry =>
        entry.name.split(/[?#]/, 1)[0] === initialQueryUrl && entry.responseEnd > 0)) return false;
    const grid = holder.data('kendoGrid');
    return !!grid && typeof grid.setDataSource === 'function' && !!grid.dataSource &&
        typeof grid.dataSource.view === 'function';
} catch (_) { return false; }
"""
GRID_QUERY_OBSERVER_SCRIPT = """
const [action, token, button] = arguments;
const key = '__sinposmartVehicleGridQuery';
const currentGrid = () => window.jQuery && window.jQuery('#grid').data('kendoGrid') || null;
const rendered = (grid, source) => {
    try {
        if (!grid || !source || typeof source.view !== 'function' || !grid.tbody) return null;
        const ids = Array.from(source.view()).map(record => record && record.uid);
        const rows = Array.from(grid.tbody.find('tr[data-uid]'));
        if (ids.some(uid => typeof uid !== 'string' || !uid) || ids.length !== rows.length ||
            ids.some((uid, index) => rows[index].getAttribute('data-uid') !== uid)) return null;
        return ids;
    } catch (_) { return null; }
};
if (action === 'begin') {
    if (window[key]) window[key].cleanup();
    if (typeof window.jQuery !== 'function') return false;
    const grid = currentGrid();
    const source = grid && grid.dataSource;
    const state = {token, armed: false, started: false, bound: false, failed: false,
                   checkedGrid: null, checkedSource: null, checkedIds: null};
    state.onStart = event => {
        if (state.armed && grid && event.type === 'read' && currentGrid() === grid && grid.dataSource === source) {
            if (state.checkedGrid) state.failed = true;
            state.started = true;
            state.bound = false;
        }
    };
    state.onBound = () => {
        if (state.armed && state.started && grid && currentGrid() === grid && grid.dataSource === source) state.bound = true;
    };
    state.onError = () => {
        if (state.armed && grid && currentGrid() === grid && grid.dataSource === source) state.failed = true;
    };
    state.cleanup = () => {
        if (grid && typeof grid.unbind === 'function') grid.unbind('dataBound', state.onBound);
        if (source && typeof source.unbind === 'function') {
            source.unbind('requestStart', state.onStart);
            source.unbind('error', state.onError);
        }
        if (window[key] === state) delete window[key];
    };
    state.oldGrid = grid; state.oldSource = source;
    window[key] = state;
    if (grid && typeof grid.bind === 'function') grid.bind('dataBound', state.onBound);
    if (source && typeof source.bind === 'function') {
        source.bind('requestStart', state.onStart);
        source.bind('error', state.onError);
    }
    return true;
}
const state = window[key];
if (!state || state.token !== token) return action === 'cleanup';
if (action === 'click') {
    if (state.armed || !button || typeof button.click !== 'function') return false;
    state.armed = true;
    button.click();
    return true;
}
if (action === 'state') {
    const grid = currentGrid(), source = grid && grid.dataSource, ids = rendered(grid, source);
    if (state.checkedGrid) {
        if (grid !== state.checkedGrid || source !== state.checkedSource || !ids ||
            ids.length !== state.checkedIds.length || ids.some((uid, i) => uid !== state.checkedIds[i])) state.failed = true;
    } else if (state.armed && window.jQuery.active === 0 && ids && (grid !== state.oldGrid || source !== state.oldSource ||
                                   state.started && state.bound)) {
        state.checkedGrid = grid; state.checkedSource = source; state.checkedIds = ids;
    }
    return {token: state.token, ready: !!state.checkedGrid && !state.failed && window.jQuery.active === 0, failed: state.failed};
}
if (action === 'cleanup') { state.cleanup(); return true; }
return false;
"""


class VehicleVerificationError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(f"車輛完成結果未確認（{reason_code}）。")
        self.reason_code = reason_code


def new_vehicle_report(target_date: str) -> dict:
    return {"target_date": target_date, "verified": False,
            "reason_code": "execution_unconfirmed", "items": []}


def safe_vehicle_name(value: str) -> str:
    raw = str(value or "")
    text = " ".join(raw.split())
    if (not text or len(text) > 32 or re.search(r"[\r\n\t]", raw)
            or re.search(r"secret|token|password|cookie|account|username|帳號|密碼", text, re.I)
            or re.fullmatch(r"[A-Za-z0-9\u3400-\u9fff -]+", text) is None):
        return ""
    return text


def record_vehicle_result(report: dict, vehicle: str, operation: str,
                          status: str, reason_code: str) -> None:
    safe_name = safe_vehicle_name(vehicle)
    if vehicle and not safe_name:
        status, reason_code = "unconfirmed", "state_unconfirmed"
    item = {"vehicle": safe_name, "operation": operation,
            "status": status, "reason_code": reason_code}
    for index, previous in enumerate(report["items"]):
        if (previous["vehicle"].casefold(), previous["operation"]) == (safe_name.casefold(), operation):
            report["items"][index] = item
            return
    if len(report["items"]) >= MAX_REPORT_ITEMS:
        report["verified"], report["reason_code"] = False, "row_limit"
        raise VehicleVerificationError("row_limit")
    report["items"].append(item)


def fail_verification(report: dict, operation: str, reason_code: str,
                      vehicle: str = "") -> None:
    report["verified"], report["reason_code"] = False, reason_code
    record_vehicle_result(report, vehicle, operation, "unconfirmed", reason_code)
    raise VehicleVerificationError(reason_code)


def verify_vehicle_report(report: dict) -> bool:
    items = report["items"]
    verified = (report.get("reason_code") not in {"row_limit", "not_required"} and 0 < len(items) <= MAX_REPORT_ITEMS
                and {item["operation"] for item in items} == {"maintenance", "equipment"}
                and all(item["vehicle"] and ((item["status"] in {"completed", "already_done"}
                        and item["reason_code"] in {"verified_today", "saved_verified"})
                        or (item["operation"] == "maintenance" and item["status"] == "not_required"
                            and item["reason_code"] == "not_required"))
                        for item in items))
    report["verified"] = verified
    report["reason_code"] = "" if verified else report.get("reason_code") or "execution_unconfirmed"
    return verified


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run PPE daily vehicle maintenance and equipment Selenium automation."
    )
    return parser.parse_args(argv)


def read_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> dict[str, object]:
    load_dotenv(ROOT_DIR / ".env")
    username = os.getenv("PPE_ACCOUNT", "").strip()
    password = os.getenv("PPE_PASSWORD", "").strip()
    if not username or not password:
        raise RuntimeError("Missing PPE_ACCOUNT or PPE_PASSWORD in environment or .env")

    return {
        "username": username,
        "password": password,
        "headless": read_bool("HEADLESS", True),
        "keep_browser_open": read_bool("KEEP_BROWSER_OPEN", False),
        "timeout_seconds": int(os.getenv("SELENIUM_TIMEOUT_SECONDS", "60")),
        "selenium_remote_url": os.getenv("SELENIUM_REMOTE_URL", "").strip(),
        "selenium_remote_ready_timeout_seconds": int(os.getenv("SELENIUM_REMOTE_READY_TIMEOUT_SECONDS", "180")),
    }


def build_today_strings(today: dt.datetime) -> list[str]:
    roc_year = today.year - 1911
    return [
        f"{roc_year}/{today.month:02d}/{today.day:02d}",
        f"{roc_year}/{today.month}/{today.day}",
        f"{roc_year}-{today.month:02d}-{today.day:02d}",
        f"{roc_year}-{today.month}-{today.day}",
        f"{today.year}/{today.month:02d}/{today.day:02d}",
        f"{today.year}/{today.month}/{today.day}",
        f"{today.year}-{today.month:02d}-{today.day:02d}",
        f"{today.year}-{today.month}-{today.day}",
    ]


def is_task_done(cell_text: str, today_strings: Iterable[str]) -> bool:
    text = str(cell_text or "").strip()
    if re.search(r"未完成|尚未|待完成|未清點|待清點|未保養|待保養|not\s+(?:done|completed)", text, re.I):
        return False
    matched = False
    for date_text in today_strings:
        text, count = re.subn(r"(?<!\d)" + re.escape(date_text) + r"(?!\d)", "", text)
        matched = matched or bool(count)
    if not matched:
        return False
    text = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", "", text)
    text = re.sub(r"已完成|已清點|清點完成|保養完成|完成清點|完成保養", "", text)
    return not text.strip(" \t\r\n:：,，;；()（）[]【】.-")


def wait_for_spinner(wait: WebDriverWait) -> None:
    wait.until(EC.invisibility_of_element_located((By.ID, "spinner-container")))


def navigate_vehicle_document(driver: webdriver.Chrome, wait: WebDriverWait, context: str,
                              *, refresh: bool = False) -> None:
    phase = "maintenance" if context == "maintain" else "equipment"
    print(f"[sinposmart-stage] {phase}_page_ready", flush=True)
    previous_document = driver.find_element(By.TAG_NAME, "html")
    if refresh:
        driver.refresh()
    else:
        driver.get(MAINTAIN_LIST_URL if context == "maintain" else EQUIP_CHECK_LIST_URL)
    wait.until(EC.staleness_of(previous_document))


def query_grid_rows(driver: webdriver.Chrome, wait: WebDriverWait, context: str) -> list:
    phase = "maintenance" if context == "maintain" else "equipment"
    print(f"[sinposmart-stage] {phase}_page_ready", flush=True)
    pathname, query_name = (("/CarMaintainCheck/Index", "QueryData") if context == "maintain"
                            else ("/CarEquipCheck/Index", "Query"))
    wait.until(lambda current_driver: current_driver.execute_script(
        GRID_PAGE_READY_SCRIPT, pathname, query_name, context == "maintain") is True)
    wait_for_spinner(wait)
    search_button = wait.until(
        EC.element_to_be_clickable((By.XPATH, f"//button[contains(normalize-space(.), '{TEXT_SEARCH}')]"))
    )
    token = uuid4().hex
    try:
        print(f"[sinposmart-stage] {phase}_query_start", flush=True)
        if driver.execute_script(GRID_QUERY_OBSERVER_SCRIPT, "begin", token) is not True:
            raise VehicleVerificationError("state_unconfirmed")
        if driver.execute_script(GRID_QUERY_OBSERVER_SCRIPT, "click", token, search_button) is not True:
            raise VehicleVerificationError("state_unconfirmed")
        print(f"[sinposmart-stage] {phase}_query_wait", flush=True)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            state = driver.execute_script(GRID_QUERY_OBSERVER_SCRIPT, "state", token)
            if (not isinstance(state, dict) or state.get("token") != token
                    or type(state.get("ready")) is not bool or type(state.get("failed")) is not bool
                    or state["failed"]):
                raise VehicleVerificationError("state_unconfirmed")
            if state["ready"]:
                break
            time.sleep(0.1)
        else:
            raise VehicleVerificationError("state_unconfirmed")
        print(f"[sinposmart-stage] {phase}_query_verify", flush=True)
        try:
            wait_for_spinner(wait)
        except TimeoutException:
            print("[sinposmart-vehicle-diagnostic] query_spinner_timeout", flush=True)
            raise VehicleVerificationError("state_unconfirmed") from None
        except Exception:
            print("[sinposmart-vehicle-diagnostic] query_spinner_driver_error", flush=True)
            raise VehicleVerificationError("state_unconfirmed") from None
        try:
            state = driver.execute_script(GRID_QUERY_OBSERVER_SCRIPT, "state", token)
        except Exception:
            print("[sinposmart-vehicle-diagnostic] query_state_read_failed_before_rows", flush=True)
            raise VehicleVerificationError("state_unconfirmed") from None
        if not isinstance(state, dict) or state.get("token") != token or state.get("ready") is not True or state.get("failed") is not False:
            print("[sinposmart-vehicle-diagnostic] query_source_changed_before_read", flush=True)
            raise VehicleVerificationError("state_unconfirmed")
        try:
            rows = driver.find_elements(By.XPATH, "//div[@id='grid']//tbody/tr")
        except Exception:
            print("[sinposmart-vehicle-diagnostic] query_rows_read_failed", flush=True)
            raise VehicleVerificationError("state_unconfirmed") from None
        try:
            state = driver.execute_script(GRID_QUERY_OBSERVER_SCRIPT, "state", token)
        except Exception:
            print("[sinposmart-vehicle-diagnostic] query_state_read_failed_after_rows", flush=True)
            raise VehicleVerificationError("state_unconfirmed") from None
        if not isinstance(state, dict) or state.get("token") != token or state.get("ready") is not True or state.get("failed") is not False:
            print("[sinposmart-vehicle-diagnostic] query_source_changed_after_read", flush=True)
            raise VehicleVerificationError("state_unconfirmed")
        if not rows:
            raise VehicleVerificationError("empty_list")
        print(f"[{context}] rows loaded: {len(rows)}")
        return rows
    finally:
        try:
            driver.execute_script(GRID_QUERY_OBSERVER_SCRIPT, "cleanup", token)
        except Exception:
            pass


def wait_for_remote_selenium(remote_url: str, timeout_seconds: int) -> None:
    status_url = remote_url.removesuffix("/wd/hub") + "/status"
    deadline = time.time() + timeout_seconds
    last_error = "unknown error"

    while time.time() < deadline:
        try:
            with urllib.request.urlopen(status_url, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("value", {}).get("ready") is True:
                print(f"[driver] selenium ready: {status_url}")
                return
            last_error = f"status not ready: {payload}"
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = str(error)
        time.sleep(2)

    raise RuntimeError(f"Selenium remote was not ready within {timeout_seconds}s: {last_error}")


def wait_for_login_site(url: str, timeout_seconds: int) -> None:
    deadline = time.time() + timeout_seconds
    last_error = "unknown error"

    while time.time() < deadline:
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 PPE-Automation/1.0"},
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                status = getattr(response, "status", 200)
            if 200 <= status < 500:
                print(f"[network] login site reachable: {url} ({status})")
                return
            last_error = f"http status {status}"
        except (urllib.error.URLError, TimeoutError) as error:
            last_error = str(error)
        time.sleep(2)

    raise RuntimeError(f"Login site was not reachable within {timeout_seconds}s: {last_error}")


def login(driver: webdriver.Chrome, wait: WebDriverWait, username: str, password: str) -> None:
    def require_authorized_page(*, login_page: bool = True) -> None:
        try:
            target = urlsplit(str(driver.current_url or ""))
            authorized = (
                target.scheme == "https"
                and target.hostname == "ppe.tyfd.gov.tw"
                and target.port in (None, 443)
                and target.username is None
                and target.password is None
                and (not login_page or target.path == "/")
            )
        except ValueError:
            authorized = False
        if not authorized:
            raise RuntimeError("車輛保養登入已離開授權頁面，已停止操作。")

    print("[login] opening login page")
    driver.get(LOGIN_URL)
    for field_id, value in (("Account", username), ("Password", password)):
        require_authorized_page()
        field = wait.until(EC.presence_of_element_located((By.ID, field_id)))
        require_authorized_page()
        field.send_keys(value)
    require_authorized_page()
    button = wait.until(EC.element_to_be_clickable((By.ID, "btnSubmit")))
    require_authorized_page()
    button.click()

    def logged_in(current_driver):
        require_authorized_page(login_page=False)
        return EC.presence_of_element_located(
            (By.XPATH, f"//*[contains(text(), '{TEXT_LOGOUT}')]"),
        )(current_driver)

    wait.until(logged_in)
    require_authorized_page(login_page=False)
    print("[login] success")


def ensure_requested_date() -> None:
    target = os.environ.get("PPE_TARGET_DATE", "").strip()
    if target and target != dt.date.today().isoformat():
        raise RuntimeError("每日點車已跨日，停止送出，請人工確認。")


def verified_grid_rows(driver: webdriver.Chrome, wait: WebDriverWait, operation: str,
                       report: dict, expected: set[str] | None = None) -> dict:
    context = "maintain" if operation == "maintenance" else "equip"
    phase = "maintenance" if context == "maintain" else "equipment"
    try:
        rows = query_grid_rows(driver, wait, context)
        print(f"[sinposmart-stage] {phase}_inventory_verify", flush=True)
        metadata = driver.execute_script(GRID_STATE_SCRIPT)
    except VehicleVerificationError as error:
        fail_verification(report, operation, error.reason_code)
    except Exception:
        fail_verification(report, operation, "state_unconfirmed")
    if not rows:
        fail_verification(report, operation, "empty_list")
    if len(rows) > MAX_REPORT_ITEMS:
        fail_verification(report, operation, "row_limit")
    if (not isinstance(metadata, dict) or type(metadata.get("total")) is not int
            or metadata.get("filtered") is not False):
        fail_verification(report, operation, "state_unconfirmed")
    total, page, page_size = metadata["total"], metadata.get("page"), metadata.get("page_size")
    if (total != len(rows) or (page is not None and (type(page) is not int or page != 1))
            or (page_size is not None and (type(page_size) is not int or page_size < len(rows)))):
        fail_verification(report, operation, "list_changed")
    result, identities, equipment_groups, equipment_ids = {}, set(), {}, set()
    for index, row in enumerate(rows, 1):
        cells = row.find_elements(By.TAG_NAME, "td")
        column = 8 if operation == "maintenance" else 3
        if len(cells) < (13 if operation == "maintenance" else 4):
            fail_verification(report, operation, "state_unconfirmed")
        vehicle = safe_vehicle_name(cells[column].get_attribute("textContent"))
        if (not vehicle or vehicle.casefold() in identities
                and (operation == "maintenance" or vehicle not in result)):
            fail_verification(report, operation, "state_unconfirmed")
        identities.add(vehicle.casefold())
        result[vehicle] = (index, row)
        if operation == "equipment":
            today_strings = build_today_strings(dt.datetime.combine(dt.date.fromisoformat(report["target_date"]), dt.time()))
            record_id = equipment_record_id(driver, row, vehicle, today_strings)
            if not record_id or record_id in equipment_ids:
                if (not record_id and len(cells) == 10 and row.find_elements(By.CSS_SELECTOR, ".k-grid-view")
                        and not row.find_elements(By.CSS_SELECTOR, ".k-grid-check")
                        and cell_completion_text(cells[8]) in {"", "-", "—", "－"}):
                    print("[sinposmart-vehicle-diagnostic] equipment_end_time_missing", flush=True)
                fail_verification(report, operation, "state_unconfirmed", vehicle)
            equipment_ids.add(record_id)
            equipment_groups.setdefault(vehicle, []).append((record_id, index, row))
    for vehicle, records in equipment_groups.items():
        if len(records) == 1:
            continue
        latest = max(records, key=lambda item: int(item[0]))
        unfinished = [item for item in records if not equipment_done(item[2], today_strings)]
        if len(unfinished) > 1 or unfinished and unfinished[0][0] != latest[0]:
            fail_verification(report, operation, "state_unconfirmed")
        selected = unfinished[0] if unfinished else latest
        result[vehicle] = (selected[1], selected[2])
    if expected is not None and set(result) != expected:
        fail_verification(report, operation, "list_changed")
    print(f"[sinposmart-stage] {phase}_check", flush=True)
    return result


def cell_completion_text(cell) -> str:
    if cell.find_elements(By.XPATH, ".//button|.//a|.//input|.//select|.//textarea"):
        return ""
    return str(cell.get_attribute("textContent") or "").strip()


def maintenance_done(row, today_strings: list[str], today: dt.datetime) -> bool:
    cells = row.find_elements(By.TAG_NAME, "td")
    required = [9]
    if today.weekday() == 6:
        required.append(10)
    if today.day == 28:
        required.append(11)
    if (today.month, today.day) in {(6, 30), (10, 31)}:
        required.append(12)
    return len(cells) >= 13 and all(is_task_done(cell_completion_text(cells[index]), today_strings)
                                   for index in required)


def equipment_done(row, today_strings: list[str]) -> bool:
    cells = row.find_elements(By.TAG_NAME, "td")
    if len(cells) != 10 or not is_task_done(cell_completion_text(cells[4]), today_strings):
        return False
    checker = cell_completion_text(cells[6])
    if checker in {"", "-", "—", "－"} or re.search(r"未完成|尚未|待完成|未清點|待清點", checker):
        return False
    if not all(re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?", cell_completion_text(cells[index]))
               for index in (7, 8)):
        return False
    views = row.find_elements(By.CSS_SELECTOR, ".k-grid-view")
    return bool(views and any(view.is_displayed() and view.is_enabled() for view in views)
                and not row.find_elements(By.CSS_SELECTOR, ".k-grid-check"))


EQUIPMENT_SELECT_ALL_XPATH = "//input[@type='checkbox' and (@aria-label='Select all rows' or @aria-label='Deselect all rows')]"
EQUIPMENT_SELECTION_SCRIPT = """
// __sinposmartEquipmentSelection: do not select or submit an empty/unbound detail grid.
try {
    const box = arguments[0], host = window.jQuery(box).closest('.k-grid, .k-treelist');
    const grid = host.data('kendoGrid') || host.data('kendoTreeList');
    if (!grid || !grid.dataSource || !grid.tbody || window.jQuery.active !== 0) return null;
    const records = Array.from(grid.dataSource.data()), total = grid.dataSource.total();
    const rows = Array.from(grid.tbody.find('tr[data-uid]'));
    const ids = records.map(record => record.uid);
    if (!Number.isInteger(total) || total < 1 || total > 2000 || records.length !== total ||
        rows.length !== total || new Set(ids).size !== total ||
        ids.some(uid => typeof uid !== 'string' || !uid) ||
        rows.some(row => !ids.includes(row.getAttribute('data-uid'))) ||
        new Set(rows.map(row => row.getAttribute('data-uid'))).size !== total) return null;
    const checks = rows.map(row => Array.from(row.querySelectorAll('input[type="checkbox"]')));
    if (checks.some(items => items.length !== 1)) return null;
    return {ready: true, selected: records.every(record => record.Checked === 'Y') && box.checked && !box.indeterminate &&
        checks.every(items => items[0].checked && !items[0].indeterminate)};
} catch (_) { return null; }
"""


def equipment_record_id(driver, row, vehicle: str, today_strings: list[str]) -> str:
    record = driver.execute_script("""
const grid = window.jQuery && window.jQuery('#grid').data('kendoGrid');
const item = grid && grid.dataItem(arguments[0]);
return item ? {id: String(item.ID), vehicle: item.LICENSE, date: item.CHECK_DATE} : null;
""", row)
    if (not isinstance(record, dict) or not isinstance(record.get("id"), str)
            or re.fullmatch(r"[1-9]\d{0,19}", record["id"]) is None
            or record.get("vehicle") != vehicle
            or not is_task_done(str(record.get("date") or ""), today_strings)):
        return ""
    return record["id"]


def wait_equipment_state(wait, condition, report: dict, vehicle: str, diagnostic: str,
                         reason: str = "state_unconfirmed"):
    try:
        return wait.until(condition)
    except TimeoutException:
        print(f"[sinposmart-vehicle-diagnostic] {diagnostic}", flush=True)
        fail_verification(report, "equipment", reason, vehicle)


def process_maintain_checks(driver: webdriver.Chrome, wait: WebDriverWait, today_strings: list[str],
                            today: dt.datetime, report: dict | None = None) -> None:
    report = report if report is not None else new_vehicle_report(today.date().isoformat())
    navigate_vehicle_document(driver, wait, "maintain")
    inventory = set(verified_grid_rows(driver, wait, "maintenance", report))
    not_required = set()
    for vehicle in sorted(inventory):
        ensure_requested_date()
        current = verified_grid_rows(driver, wait, "maintenance", report, inventory)
        index, row = current[vehicle]
        if maintenance_done(row, today_strings, today):
            record_vehicle_result(report, vehicle, "maintenance", "already_done", "verified_today")
            continue
        button = wait.until(EC.element_to_be_clickable((By.XPATH,
            f"//div[@id='grid']//tbody/tr[{index}]//button[contains(., '{TEXT_MAINTAIN}')]")))
        driver.execute_script("arguments[0].click();", button)
        saved = False
        previous = None
        for _ in range(MAX_REPORT_ITEMS):
            wait_for_spinner(wait)
            wait.until(lambda current_driver: current_driver.find_elements(By.CSS_SELECTOR, "#scheduler .k-event"))
            events = [event for event in driver.find_elements(By.CSS_SELECTOR, "#scheduler .k-event")
                      if f"{today.year}年{today.month}月{today.day}日" in (event.get_attribute("aria-label") or "")]
            if not events:
                fail_verification(report, "maintenance", "today_not_found", vehicle)
            disabled = [bool(set((event.get_attribute("class") or "").split()) & {"disable", "disabled"})
                        for event in events]
            if any(disabled):
                if not all(disabled) or any(set((event.get_attribute("class") or "").split()) & {"checked", "unchecked", "reviewed"}
                        or event.find_elements(By.CSS_SELECTOR, ".reviewed") for event in events):
                    fail_verification(report, "maintenance", "state_unconfirmed", vehicle)
                not_required.add(vehicle)
                break
            signature = tuple((event.get_attribute("aria-label"), event.get_attribute("class"),
                               len(event.find_elements(By.CSS_SELECTOR, ".reviewed"))) for event in events)
            if previous == signature:
                fail_verification(report, "maintenance", "save_unconfirmed", vehicle)
            target_event = None
            for event in events:
                classes = set((event.get_attribute("class") or "").split())
                if "checked" in classes or event.find_elements(By.CSS_SELECTOR, ".reviewed"):
                    continue
                if classes & {"disable", "disabled"}:
                    fail_verification(report, "maintenance", "state_unconfirmed", vehicle)
                target_event = event
                break
            if target_event is None:
                break
            previous = signature
            ensure_requested_date()
            driver.execute_script("arguments[0].click();", target_event)
            wait.until(EC.visibility_of_element_located((By.ID, "maintainList")))
            submit = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@onclick='SaveProc()']")))
            ensure_requested_date()
            driver.execute_script("arguments[0].click();", submit)
            wait.until(EC.presence_of_element_located((By.XPATH,
                "//div[contains(@class, 'swal') or contains(@class, 'sweet')]")))
            saved = True
            navigate_vehicle_document(driver, wait, "maintain", refresh=True)
        else:
            fail_verification(report, "maintenance", "save_unconfirmed", vehicle)
        navigate_vehicle_document(driver, wait, "maintain")
        current = verified_grid_rows(driver, wait, "maintenance", report, inventory)
        if vehicle in not_required:
            record_vehicle_result(report, vehicle, "maintenance", "not_required", "not_required")
            continue
        if not maintenance_done(current[vehicle][1], today_strings, today):
            fail_verification(report, "maintenance", "save_unconfirmed" if saved else "state_unconfirmed", vehicle)
        record_vehicle_result(report, vehicle, "maintenance", "completed" if saved else "already_done",
                              "saved_verified" if saved else "verified_today")
    current = verified_grid_rows(driver, wait, "maintenance", report, inventory)
    for vehicle, (_index, row) in current.items():
        if vehicle in not_required:
            continue
        if not maintenance_done(row, today_strings, today):
            fail_verification(report, "maintenance", "save_unconfirmed", vehicle)


def process_equip_checks(driver: webdriver.Chrome, wait: WebDriverWait,
                         report: dict | None = None) -> None:
    target_date = report["target_date"] if report is not None else dt.date.today().isoformat()
    report = report if report is not None else new_vehicle_report(target_date)
    today_strings = build_today_strings(dt.datetime.combine(dt.date.fromisoformat(target_date), dt.time()))
    ensure_requested_date()
    navigate_vehicle_document(driver, wait, "equip")
    inventory = set(verified_grid_rows(driver, wait, "equipment", report))
    for vehicle in sorted(inventory):
        current = verified_grid_rows(driver, wait, "equipment", report, inventory)
        _index, row = current[vehicle]
        buttons = row.find_elements(By.CSS_SELECTOR, ".k-grid-check")
        if buttons and row.find_elements(By.CSS_SELECTOR, ".k-grid-view"):
            fail_verification(report, "equipment", "state_unconfirmed", vehicle)
        if equipment_done(row, today_strings):
            if buttons:
                fail_verification(report, "equipment", "state_unconfirmed", vehicle)
            record_vehicle_result(report, vehicle, "equipment", "already_done", "verified_today")
            continue
        cells = row.find_elements(By.TAG_NAME, "td")
        views = row.find_elements(By.CSS_SELECTOR, ".k-grid-view")
        pending = (not buttons and len(views) == 1 and views[0].is_displayed() and views[0].is_enabled()
                   and len(cells) == 10 and is_task_done(cell_completion_text(cells[4]), today_strings)
                   and re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?", cell_completion_text(cells[7]))
                   and cell_completion_text(cells[8]) in {"", "-", "—", "－"})
        record_id = equipment_record_id(driver, row, vehicle, today_strings)
        if (not record_id or not pending and (len(buttons) != 1
                or not buttons[0].is_displayed() or not buttons[0].is_enabled())):
            if pending:
                print("[sinposmart-vehicle-diagnostic] equipment_end_time_missing", flush=True)
            fail_verification(report, "equipment", "state_unconfirmed", vehicle)
        ensure_requested_date()

        def record_page_ready(current_driver, pathname):
            if current_driver.execute_script(
                    "return document.readyState === 'complete' && !!window.jQuery && window.jQuery.active === 0;") is not True:
                return False
            location = urlsplit(current_driver.current_url)
            return (location.scheme == "https" and location.netloc == urlsplit(BASE_URL).netloc
                    and ((location.path == pathname and parse_qs(location.query).get("id") == [record_id])
                         or location.path == f"{pathname}/{record_id}"))

        previous_document = driver.find_element(By.TAG_NAME, "html")
        if pending:
            driver.execute_script("arguments[0].click();", views[0])
            wait_equipment_state(wait, EC.staleness_of(previous_document), report, vehicle,
                                 "equipment_detail_unconfirmed")
            wait_equipment_state(wait, lambda current_driver: record_page_ready(current_driver, "/CarEquipCheck/View"),
                                 report, vehicle, "equipment_detail_unconfirmed")
            resume = wait_equipment_state(wait, EC.element_to_be_clickable((By.XPATH,
                "//button[contains(normalize-space(.), '繼續清點')]|//a[contains(normalize-space(.), '繼續清點')]|"
                "//input[(@type='button' or @type='submit') and contains(@value, '繼續清點')]")),
                report, vehicle, "equipment_continue_unavailable")
            previous_document = driver.find_element(By.TAG_NAME, "html")
            ensure_requested_date()
            driver.execute_script("arguments[0].click();", resume)
        else:
            driver.execute_script("arguments[0].click();", buttons[0])
        wait_equipment_state(wait, EC.staleness_of(previous_document), report, vehicle,
                             "equipment_detail_unconfirmed")

        wait_equipment_state(wait, lambda current_driver: record_page_ready(current_driver, "/CarEquipCheck/Take"),
                             report, vehicle, "equipment_detail_unconfirmed")
        wait_for_spinner(wait)

        def selection_state(current_driver):
            try:
                header = current_driver.find_element(By.XPATH, EQUIPMENT_SELECT_ALL_XPATH)
                state = current_driver.execute_script(EQUIPMENT_SELECTION_SCRIPT, header)
            except (NoSuchElementException, StaleElementReferenceException):
                return False
            return state if isinstance(state, dict) and state.get("ready") is True else False

        selection = wait_equipment_state(wait, selection_state, report, vehicle, "equipment_detail_unconfirmed")
        if not selection.get("selected"):
            checkbox = wait_equipment_state(wait, EC.element_to_be_clickable((By.XPATH, EQUIPMENT_SELECT_ALL_XPATH)),
                                            report, vehicle, "equipment_selection_unconfirmed")
            if checkbox.is_selected():
                print("[sinposmart-vehicle-diagnostic] equipment_selection_unconfirmed", flush=True)
                fail_verification(report, "equipment", "state_unconfirmed", vehicle)
            ensure_requested_date()
            driver.execute_script("arguments[0].click();", checkbox)
        wait_equipment_state(wait, lambda current_driver: bool((selection_state(current_driver) or {}).get("selected")),
                             report, vehicle, "equipment_selection_unconfirmed")
        submit = wait.until(EC.element_to_be_clickable((By.XPATH, f"//button[contains(., '{TEXT_FINISH_EQUIP_CHECK}')]")))
        if not (selection_state(driver) or {}).get("selected"):
            fail_verification(report, "equipment", "state_unconfirmed", vehicle)
        ensure_requested_date()
        submitted_document = driver.find_element(By.TAG_NAME, "html")
        driver.execute_script("arguments[0].click();", submit)
        acknowledged = set()

        def submission_ready(current_driver):
            if not EC.staleness_of(submitted_document)(current_driver):
                return False
            # EndTake performs the final write and redirects to View; do not interrupt it with Index.
            if record_page_ready(current_driver, "/CarEquipCheck/View"):
                return True
            location = urlsplit(current_driver.current_url)
            return (location.scheme == "https" and location.netloc == urlsplit(BASE_URL).netloc
                    and location.path == "/CarEquipCheck/Index"
                    and current_driver.execute_script("return document.readyState === 'complete';") is True)

        def visible_confirmation(current_driver):
            if submission_ready(current_driver):
                return True
            if urlsplit(current_driver.current_url).path != "/CarEquipCheck/Take":
                return False
            for button in current_driver.find_elements(By.CSS_SELECTOR, ".swal-button--confirm, .swal2-confirm"):
                if not button.is_displayed() or not button.is_enabled():
                    continue
                message = current_driver.execute_script("""
// __sinposmartEquipmentDialog: acknowledge each prompt once, including the saved notice.
const modal = arguments[0].closest('.swal-modal, .swal2-popup');
return modal ? modal.textContent.trim() : null;
""", button)
                if isinstance(message, str) and message and message not in acknowledged:
                    return button, message
            return False

        for _ in range(3):
            confirmation = wait_equipment_state(wait, visible_confirmation, report, vehicle,
                                                "equipment_confirmation_unconfirmed", "save_unconfirmed")
            if confirmation is True:
                break
            confirm, message = confirmation
            ensure_requested_date()
            acknowledged.add(message)
            driver.execute_script("arguments[0].click();", confirm)
        wait_equipment_state(wait, submission_ready,
                             report, vehicle, "equipment_confirmation_unconfirmed", "save_unconfirmed")
        navigate_vehicle_document(driver, wait, "equip")
        current = verified_grid_rows(driver, wait, "equipment", report, inventory)
        row = current[vehicle][1]
        if (equipment_record_id(driver, row, vehicle, today_strings) != record_id
                or not equipment_done(row, today_strings)):
            fail_verification(report, "equipment", "save_unconfirmed", vehicle)
        record_vehicle_result(report, vehicle, "equipment", "completed", "saved_verified")
    current = verified_grid_rows(driver, wait, "equipment", report, inventory)
    for vehicle, (_index, row) in current.items():
        if not equipment_done(row, today_strings):
            fail_verification(report, "equipment", "save_unconfirmed", vehicle)


def save_artifacts(driver: webdriver.Chrome, suffix: str) -> None:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    screenshot_path = ARTIFACTS_DIR / f"selenium-{suffix}.png"
    html_path = ARTIFACTS_DIR / f"selenium-{suffix}.html"
    try:
        driver.save_screenshot(str(screenshot_path))
        html_path.write_text(driver.page_source, encoding="utf-8")
    except WebDriverException as error:
        fallback_path = ARTIFACTS_DIR / f"selenium-{suffix}.txt"
        fallback_path.write_text(f"artifact capture skipped: {error}\n", encoding="utf-8")
        print(f"[artifacts] skipped screenshot/html capture: {error}")


def main(argv: list[str] | None = None) -> None:
    parse_args(argv)
    driver = None
    today = dt.datetime.now()
    report = new_vehicle_report(today.date().isoformat())
    operation = "maintenance"
    try:
        target_date = os.environ.get("PPE_TARGET_DATE", "").strip()
        if target_date:
            if dt.date.fromisoformat(target_date).isoformat() != target_date:
                raise VehicleVerificationError("report_invalid")
            report["target_date"] = target_date
        else:
            os.environ["PPE_TARGET_DATE"] = report["target_date"]
        ensure_requested_date()
        config = load_config()
        options = webdriver.ChromeOptions()
        if config["headless"]:
            options.add_argument("--headless=new")
        options.add_argument("--window-size=1440,1200")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-features=Translate,BackForwardCache")
        options.add_argument("--dns-prefetch-disable")
        options.page_load_strategy = "none"
        remote_url = str(config["selenium_remote_url"])

        def create_driver() -> webdriver.Chrome:
            if remote_url:
                wait_for_remote_selenium(remote_url, int(config["selenium_remote_ready_timeout_seconds"]))
                wait_for_login_site(LOGIN_URL, int(config["selenium_remote_ready_timeout_seconds"]))
                return webdriver.Remote(command_executor=remote_url, options=options)
            return build_driver(
                headless=bool(config["headless"]),
                option_arguments=(
                    "--window-size=1440,1200",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-features=Translate,BackForwardCache",
                    "--dns-prefetch-disable",
                ),
                page_load_strategy="none",
            )

        def initialize_browser(candidate: webdriver.Chrome) -> None:
            candidate.set_page_load_timeout(max(15, int(config["timeout_seconds"])))
            candidate.set_script_timeout(max(15, int(config["timeout_seconds"])))
            login(candidate, WebDriverWait(candidate, int(config["timeout_seconds"])),
                  str(config["username"]), str(config["password"]))

        print("[sinposmart-stage] browser_start", flush=True)
        print("[sinposmart-stage] login", flush=True)
        driver = retry_duty_browser_session_open(create_driver, initialize_browser, cleanup=quit_driver)
        wait = WebDriverWait(driver, int(config["timeout_seconds"]))
        today = dt.datetime.combine(dt.date.fromisoformat(report["target_date"]), dt.time())
        print("[sinposmart-stage] maintenance_check", flush=True)
        process_maintain_checks(driver, wait, build_today_strings(today), today, report=report)
        operation = "equipment"
        print("[sinposmart-stage] equipment_check", flush=True)
        process_equip_checks(driver, wait, report=report)
        ensure_requested_date()
        if not verify_vehicle_report(report):
            fail_verification(report, operation, "execution_unconfirmed")
        print(REPORT_PREFIX + json.dumps(report, ensure_ascii=False), flush=True)
        print("[done] automation finished", flush=True)
        if config["keep_browser_open"]:
            time.sleep(DEFAULT_BROWSER_RETENTION_SECONDS)
    except Exception as error:
        reason = error.reason_code if isinstance(error, VehicleVerificationError) else "unexpected_error"
        report["verified"], report["reason_code"] = False, reason
        if not any(item["status"] == "unconfirmed" for item in report["items"]) and len(report["items"]) < MAX_REPORT_ITEMS:
            record_vehicle_result(report, "", operation, "unconfirmed", reason)
        print(REPORT_PREFIX + json.dumps(report, ensure_ascii=False), flush=True)
        raise VehicleVerificationError(reason) from None
    finally:
        if driver is not None:
            try:
                quit_driver(driver)
            except Exception:
                pass
        runner_pid_path = str(os.environ.get("PPE_RUNNER_PID_FILE", "") or "").strip()
        if runner_pid_path:
            try:
                path = Path(runner_pid_path)
                if int(path.read_text(encoding="utf-8").strip()) == os.getpid():
                    path.unlink()
            except (OSError, ValueError):
                pass


if __name__ == "__main__":
    main()
