# -*- coding: utf-8 -*-
"""
Read-only rehearsal for the TYFD duty management automation.

This script logs in, reads the duty table and related query pages, then prints
the actions that would be created. It never clicks save/submit.
"""

from __future__ import annotations


import argparse
import base64
import ctypes
import getpass
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


BASE_URL = "https://dutymgt.tyfd.gov.tw/tyfd119"

DUTY_TABLE_AP = "wap119.RPS105020"
ENTRY_LOG_AP = "wap119.RPS04040"
ENTRY_OUTIN_VALUE_MAP = {
    "出": "O",
    "入": "I",
    "值班": "I2",
    "值退": "I3",
}
WORK_LOG_AP = "wap119.RPS04060"
CASE_QUERY_AP = "wap119.RPS04061"
WORK_LOG_DEFAULTS_PATH = Path(__file__).with_name("work_log_defaults.json")

OFF_DUTY_SUMMARY_KEYS = {
    "公假",
    "請休",
    "產假",
    "病假",
    "事假",
    "榮譽假",
    "喪假",
    "差假",
    "婚假",
    "特別註記",
    "補休",
    "其他假別",
    "停休",
    "輪休公假",
}
TRAINING_BY_WEEKDAY = {
    0: ("河川抽水及水源運用", "SCBA訓練", "火災特性"),
    1: ("通風排煙訓練", "人命救助訓練", "火場控制及殘火處理"),
    2: ("個人防護裝備操作", "常訓體技能訓練", "救護訓練"),
    3: ("車輛裝備基礎保養維護", "戰術體能訓練", "救護訓練"),
    4: ("救生艇拆裝組合訓練", "船外機與橡皮艇", "個人水域防護裝備介紹"),
    5: ("破壞器材操作", "入室搜救", "五用氣體檢知器及CO探測器"),
    6: ("車輛駕訓", "環境整理", "器材車、化學(處理)車"),
}
TRAINING_REASON = {
    "河川抽水及水源運用": "搶救訓練",
    "通風排煙訓練": "搶救訓練",
    "個人防護裝備操作": "裝備器材保養",
    "車輛裝備基礎保養維護": "裝備器材保養",
    "救生艇拆裝組合訓練": "裝備器材保養",
    "破壞器材操作": "裝備器材保養",
    "車輛駕訓": "搶救訓練",
    "SCBA訓練": "裝備器材保養",
    "人命救助訓練": "搶救訓練",
    "常訓體技能訓練": "體技能訓練",
    "戰術體能訓練": "體技能訓練",
    "船外機與橡皮艇": "裝備器材保養",
    "入室搜救": "搶救訓練",
    "環境整理": "車輛清洗保養",
    "火災特性": "搶救訓練",
    "火場控制及殘火處理": "搶救訓練",
    "救護訓練": "救護訓練",
    "個人水域防護裝備介紹": "裝備器材保養",
    "五用氣體檢知器及CO探測器": "裝備器材保養",
    "器材車、化學(處理)車": "裝備器材保養",
}


# Data models

@dataclass
class DutyRow:
    slot: str
    columns: dict[str, list[str]]


@dataclass
class DutySheet:
    roc_date: str
    unit: str = ""
    rows: list[DutyRow] = field(default_factory=list)
    summary: dict[str, list[str]] = field(default_factory=dict)
    staff: dict[str, dict[str, str]] = field(default_factory=dict)


@dataclass
class CaseRecord:
    report_time: str
    return_time: str
    category: str
    raw: list[str]
    personnel_count: int = 0


@dataclass
class PlannedAction:
    kind: str
    time: str
    actor: str
    target: str
    fields: dict[str, Any]
    source: str
    duplicate_key: str
    date_offset: int = 0


# Date, roster, and radio helpers

def roc_date(d: date) -> str:
    return f"{d.year - 1911:03d}{d.month:02d}{d.day:02d}"


def parse_roc_date(value: str) -> date:
    value = re.sub(r"\D", "", value)
    if len(value) != 7:
        raise ValueError("ROC date must look like 1150517")
    year = int(value[:3]) + 1911
    return date(year, int(value[3:5]), int(value[5:7]))


def nums(text: str) -> list[str]:
    return re.findall(r"\d+", text or "")


def roster_nums(text: str) -> list[str]:
    return nums((text or "").split("合計", 1)[0])


def normalize_num(n: str) -> str:
    return str(int(n)) if str(n).strip().isdigit() else str(n).strip()


def is_fire_case_category(category: str) -> bool:
    return any(keyword in category for keyword in ("火警", "火災", "救災"))


def case_return_time(value: str) -> str:
    text = str(value or "").strip()
    if re.search(r"(?:^|\D)0001[/-]0?1[/-]0?1(?:\D|$)", text):
        return ""
    times = re.findall(r"\d{1,2}:\d{2}:\d{2}", text)
    return times[-1] if times else ""


def case_personnel_count(button_onclick: str) -> int:
    match = re.search(r"choose\('(?P<payload>.*)'\)", str(button_onclick or ""), re.DOTALL)
    if not match:
        return 0
    fields = match.group("payload").split("(^w^)")
    if len(fields) <= 33:
        return 0
    return len({code.strip() for code in fields[33].split(",") if code.strip()})


DEFAULT_WORK_LOG_DEFAULTS: dict[str, Any] = {
    "radio_count": 34,
    "emergency_vehicles_in_station": 6,
    "emergency_vehicles_repair": 0,
    "ems_case_vehicles": 1,
    "fire_case_vehicles": 2,
    "support_vehicles_in_station": 5,
    "support_vehicles_out": 0,
    "support_vehicles_repair": 0,
    "rescue_equipment_in_station": 2,
    "rescue_equipment_out": 0,
    "important_note": "（比如○○車輛或橡皮艇報修、防颱應變中心成立等事項）。",
    "tic_count": 5,
    "case_vehicle_overrides": {},
}


def int_setting(settings: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        value = int(str(settings.get(key, default)).strip())
    except (TypeError, ValueError):
        return default
    return max(0, value)


def load_work_log_defaults() -> dict[str, Any]:
    settings = dict(DEFAULT_WORK_LOG_DEFAULTS)
    if WORK_LOG_DEFAULTS_PATH.exists():
        try:
            loaded = json.loads(WORK_LOG_DEFAULTS_PATH.read_text(encoding="utf-8-sig"))
            if isinstance(loaded, dict):
                settings.update(loaded)
        except Exception:
            pass
    if not isinstance(settings.get("case_vehicle_overrides"), dict):
        settings["case_vehicle_overrides"] = {}
    return settings


def save_work_log_defaults(settings: dict[str, Any]) -> None:
    merged = dict(DEFAULT_WORK_LOG_DEFAULTS)
    merged.update(settings)
    if not isinstance(merged.get("case_vehicle_overrides"), dict):
        merged["case_vehicle_overrides"] = {}
    WORK_LOG_DEFAULTS_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")


def case_vehicle_key(case: CaseRecord, target_roc_date: str) -> str:
    category = case.category or "案件"
    return f"{target_roc_date}|{case.report_time}|{category}|{' '.join(case.raw[:4])}"


def default_case_vehicle_count(case: CaseRecord, settings: dict[str, Any]) -> int:
    if is_fire_case_category(case.category):
        return 2
    if "緊急救護" in case.category:
        return 2 if case.personnel_count >= 4 else 1
    return 0


def case_report_hour(case: CaseRecord) -> int | None:
    if not case.report_time:
        return None
    match = re.match(r"(\d{1,2}):", case.report_time)
    return int(match.group(1)) if match else None


def is_test_case_row(row: list[str]) -> bool:
    return any("測試" in str(cell).replace("（", "(").replace("）", ")") for cell in row)


def unreturned_case_vehicle_items(
    cases: list[CaseRecord],
    settings: dict[str, Any] | None = None,
    target_roc_date: str = "",
    before_hour: int | None = None,
) -> list[dict[str, Any]]:
    settings = settings or load_work_log_defaults()
    date_overrides = settings.get("case_vehicle_overrides", {}).get(target_roc_date, {})
    if not isinstance(date_overrides, dict):
        date_overrides = {}
    items: list[dict[str, Any]] = []
    for case in cases:
        if case.return_time:
            continue
        report_hour = case_report_hour(case)
        if before_hour is not None and report_hour is not None and report_hour >= before_hour:
            continue
        key = case_vehicle_key(case, target_roc_date)
        default_count = default_case_vehicle_count(case, settings)
        count = date_overrides.get(key, default_count)
        try:
            count = max(0, int(count))
        except (TypeError, ValueError):
            count = default_count
        if count <= 0:
            continue
        items.append(
            {
                "key": key,
                "date": target_roc_date,
                "report_time": case.report_time,
                "category": case.category or "案件",
                "count": count,
                "default_count": default_count,
                "raw": case.raw,
            }
        )
    return items


def handheld_radio(number: str) -> str:
    n = int(number)
    if 1 <= n <= 5:
        return f"手{n:02d}、{n:02d}-1"
    return f"手{n:02d}"


# Browser navigation helpers

def open_ap(driver: webdriver.Chrome, ap_name: str) -> None:
    url = (
        f"{BASE_URL}/ActionControlServlet?id=00&APname={ap_name}"
        f"&pushButton=load&nextAPname={ap_name}&_txtFirstEntry=TRUE"
    )
    driver.get(url)


def ensure_ap(driver: webdriver.Chrome, ap_name: str) -> bool:
    current_url = driver.current_url or ""
    if f"APname={ap_name}" in current_url or f"nextAPname={ap_name}" in current_url:
        return False
    open_ap(driver, ap_name)
    return True


def js_click(driver: webdriver.Chrome, element_id: str) -> bool:
    return bool(
        driver.execute_script(
            """
            const el = document.getElementById(arguments[0]);
            if (!el) return false;
            el.click();
            return true;
            """,
            element_id,
        )
    )


def js_set(
    driver: webdriver.Chrome,
    element_id: str,
    value: str,
    *,
    dispatch_change: bool = True,
) -> bool:
    return bool(
        driver.execute_script(
            """
            const el = document.getElementById(arguments[0]);
            if (!el) return false;
            el.value = arguments[1];
            if (arguments[2]) el.dispatchEvent(new Event('change', {bubbles: true}));
            return true;
            """,
            element_id,
            value,
            dispatch_change,
        )
    )


def native_click(driver: webdriver.Chrome, element_id: str) -> bool:
    """Click with a genuine browser event for legacy pages that read window.event."""

    try:
        driver.find_element(By.ID, element_id).click()
    except (AttributeError, NoSuchElementException, WebDriverException):
        return False
    return True


def suppress_window_open_for_background_query(driver: webdriver.Chrome) -> None:
    try:
        driver.execute_script(
            """
            window.open = function() { return null; };
            """
        )
    except Exception:
        pass


def detect_login_error(driver: webdriver.Chrome) -> str:
    try:
        alert = driver.switch_to.alert
        text = alert.text.strip()
        alert.accept()
        if text:
            return text
    except Exception:
        pass
    return driver.execute_script(
        """
        const text = document.body ? document.body.innerText : '';
        const values = Array.from(document.querySelectorAll('input, textarea, select'))
          .map(el => el.value || el.options?.[el.selectedIndex]?.text || '')
          .join('\\n');
        const pageText = [text, values].join('\\n');
        const known = '帳號密碼有誤或尚未申請帳號權限,請確認後再重新登入';
        if (pageText.includes(known)) return known;
        return '';
        """
    ) or ""


# People picker helpers

def set_people_direct(driver: webdriver.Chrome, people: list[Any]) -> dict[str, Any]:
    """Select form people by writing the same fields as the picker popup.

    Entry-log and work-log insert pages both store selected people in
    ``_hidManId`` and ``_areMan``. Work-log additionally updates ``_txtPcnt``.
    ``people`` can contain names or objects like ``{"id": "...", "name": "..."}``.
    """

    return driver.execute_script(
        """
        const targets = arguments[0].map(item => {
          if (item && typeof item === 'object') {
            return {
              id: String(item.id || item.user_id || '').trim(),
              name: String(item.name || '').trim()
            };
          }
          return {id: '', name: String(item || '').trim()};
        }).filter(x => x.id || x.name);

        function collectPeople() {
          const people = [];
          const seen = new Set();
          function push(id, name, title = '', value = '') {
            id = String(id || '').trim();
            name = String(name || '').trim();
            title = String(title || '').trim();
            value = String(value || '').trim();
            if (!id || !name) return;
            const key = id + ':' + name;
            if (seen.has(key)) return;
            seen.add(key);
            people.push({id, name, title, value});
          }

          const selMan = document.getElementById('_selMan');
          if (selMan) {
            Array.from(selMan.options || []).forEach(opt => {
              const parts = String(opt.value || '').split(',');
              push(parts[0], opt.text, parts[1], opt.value);
            });
          }

          const selManData = document.getElementById('_selManData');
          if (selManData) {
            Array.from(selManData.options || []).forEach(opt => {
              const parts = String(opt.value || '').split(',');
              push(parts[1], opt.text, parts[2], [parts[1], parts[2]].filter(Boolean).join(','));
            });
          }
          return people;
        }

        const available = collectPeople();
        const selected = [];
        const missing = [];
        for (const target of targets) {
          const person = available.find(p =>
            (target.id && p.id === target.id) ||
            (target.name && (p.name === target.name || p.name.includes(target.name) || target.name.includes(p.name)))
          );
          if (person) selected.push({...target, ...person});
          else if (target.id && target.name) selected.push(target);
          else missing.push(target.name || target.id);
        }

        if (missing.length === 0 && selected.length > 0) {
          const ids = selected.map(p => p.id).join(',');
          const names = selected.map(p => p.name).join(',');
          const firstTitle = selected[0]?.title || '';
          const hidManId = document.getElementById('_hidManId');
          const areMan = document.getElementById('_areMan');
          if (hidManId) hidManId.value = ids;
          if (areMan) areMan.value = names;
          const txtMan = document.getElementById('_txtMan');
          if (txtMan) txtMan.value = names;
          const selMan = document.getElementById('_selMan');
          if (selMan) {
            const option = Array.from(selMan.options || []).find(opt =>
              String(opt.value || '').split(',')[0].trim() === selected[0].id ||
              String(opt.text || '').trim() === selected[0].name
            );
            if (option) selMan.value = option.value;
          }
          const selTitle = document.getElementById('_selTitle');
          if (selTitle && firstTitle) selTitle.value = firstTitle;
          const txtTitle = document.getElementById('_txtTitle');
          if (txtTitle && selTitle && selTitle.selectedIndex >= 0) txtTitle.value = selTitle.options[selTitle.selectedIndex].text;
          const pcnt = document.getElementById('_txtPcnt');
          if (pcnt) pcnt.value = String(selected.length);
        }

        return {
          ok: missing.length === 0 && selected.length > 0,
          selected,
          missing,
          hidManId: document.getElementById('_hidManId')?.value || '',
          areMan: document.getElementById('_areMan')?.value || '',
          txtMan: document.getElementById('_txtMan')?.value || '',
          txtTitle: document.getElementById('_txtTitle')?.value || '',
          pcnt: document.getElementById('_txtPcnt')?.value || ''
        };
        """,
        people,
    )


def set_entry_people_direct(driver: webdriver.Chrome, names: list[str]) -> dict[str, Any]:
    return set_people_direct(driver, names)


def select_people_via_popup(driver: webdriver.Chrome, people: list[Any]) -> dict[str, Any]:
    """Select people through the background picker popup."""

    main_window = driver.current_window_handle
    before_handles = set(driver.window_handles)
    WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "_btnOpenWin"))).click()
    WebDriverWait(driver, 10).until(lambda d: len(set(d.window_handles) - before_handles) == 1)
    popup_window = (set(driver.window_handles) - before_handles).pop()
    driver.switch_to.window(popup_window)
    result = driver.execute_script(
        """
        const targets = arguments[0].map(item => {
          if (item && typeof item === 'object') {
            return {
              id: String(item.id || item.user_id || '').trim(),
              name: String(item.name || '').trim(),
              dutyNo: String(item.duty_no || item.dutyNo || item.no || '').trim()
            };
          }
          return {id: '', name: String(item || '').trim(), dutyNo: ''};
        }).filter(x => x.id || x.name || x.dutyNo);
        const checks = Array.from(document.querySelectorAll('input[name="_chkUser"]'));
        const selected = [];
        const missing = [];
        const candidates = checks.map(el => ({
          value: String(el.value || ''),
          rowText: String(el.closest('tr')?.innerText || el.parentElement?.innerText || ''),
          cells: Array.from(el.closest('tr')?.children || []).map(cell => String(cell.innerText || '').trim())
        }));

        for (const target of targets) {
          const box = checks.find(el => {
            const parts = String(el.value || '').split(',');
            const id = parts[0].trim();
            const personName = parts.slice(1).join(',').trim();
            const row = el.closest('tr');
            const rowText = String(row?.innerText || el.parentElement?.innerText || '');
            const cells = Array.from(row?.children || []).map(cell => String(cell.innerText || '').trim());
            return (target.id && id === target.id) ||
                   (target.dutyNo && cells.some(text => text === target.dutyNo)) ||
                   (target.name && personName && (
                     personName === target.name ||
                     personName.includes(target.name) ||
                     target.name.includes(personName) ||
                     rowText.includes(target.name)
                   ));
          });
          if (box) {
            box.scrollIntoView({block: 'center'});
            if (!box.checked) box.click();
            box.dispatchEvent(new Event('change', {bubbles: true}));
            selected.push({
              value: box.value,
              rowText: box.closest('tr')?.innerText || box.parentElement?.innerText || '',
              checked: box.checked
            });
          } else {
            missing.push(target.dutyNo || target.name || target.id);
          }
        }

        return {ok: missing.length === 0 && selected.length > 0, selected, missing, candidates};
        """,
        people,
    )
    if result.get("ok"):
        WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "_btnSure"))).click()
    driver.switch_to.window(main_window)

    try:
        WebDriverWait(driver, 5).until(
            lambda d: d.execute_script(
                """
                return Boolean(
                  document.getElementById('_txtMan')?.value ||
                  document.getElementById('_areMan')?.value ||
                  document.getElementById('_hidManId')?.value
                );
                """
            )
        )
    except TimeoutException:
        pass
    verify = driver.execute_script(
        """
        return {
          hidManId: document.getElementById('_hidManId')?.value || '',
          areMan: document.getElementById('_areMan')?.value || '',
          txtMan: document.getElementById('_txtMan')?.value || '',
          txtTitle: document.getElementById('_txtTitle')?.value || '',
          pcnt: document.getElementById('_txtPcnt')?.value || ''
        };
        """
    )
    result.update(verify)
    result["ok"] = bool(result.get("ok") and ((verify.get("hidManId") and verify.get("areMan")) or verify.get("txtMan")))
    if popup_window in driver.window_handles:
        driver.switch_to.window(popup_window)
        driver.close()
        driver.switch_to.window(main_window)
    return result


def select_entry_people_via_popup(driver: webdriver.Chrome, names: list[str]) -> dict[str, Any]:
    return select_people_via_popup(driver, names)


def set_form_people(driver: webdriver.Chrome, people: list[Any], fallback_popup: bool = True) -> dict[str, Any]:
    """Set selected people without visible browser UI.

    First writes the underlying fields directly. If direct selection cannot
    verify all people and ``fallback_popup`` is true, it uses the same picker
    popup flow the website uses, still inside headless Chrome.
    """

    result = set_people_direct(driver, people)
    if result.get("ok"):
        result["method"] = "direct"
        return result
    if not fallback_popup:
        result["method"] = "direct"
        return result

    popup_result = select_people_via_popup(driver, people)
    popup_result["method"] = "popup"
    return popup_result


def set_entry_people(driver: webdriver.Chrome, names: list[str], fallback_popup: bool = True) -> dict[str, Any]:
    result = select_people_via_popup(driver, names)
    result["method"] = "popup"
    return result


def set_work_people(driver: webdriver.Chrome, people: list[Any], fallback_popup: bool = True) -> dict[str, Any]:
    return set_form_people(driver, people, fallback_popup)


# Form controls and submit helpers

def control_snapshot(driver: webdriver.Chrome) -> list[dict[str, Any]]:
    return driver.execute_script(
        """
        return Array.from(document.querySelectorAll('input, select, textarea, button')).map(el => ({
          tag: el.tagName.toLowerCase(),
          type: el.type || '',
          id: el.id || '',
          name: el.name || '',
          value: el.value || '',
          text: el.innerText || el.options?.[el.selectedIndex]?.text || '',
          options: el.tagName.toLowerCase() === 'select'
            ? Array.from(el.options || []).map(opt => ({value: opt.value, text: opt.text}))
            : []
        }));
        """
    )


def click_insert_control(driver: webdriver.Chrome) -> dict[str, Any]:
    return driver.execute_script(
        """
        const controls = Array.from(document.querySelectorAll('input, button, a'));
        const target = controls.find(el => {
          const text = [el.id, el.name, el.value, el.title, el.innerText]
            .map(x => String(x || '')).join(' ');
          return /新增|加入|Add|Insert|New|Create/i.test(text);
        });
        if (!target) return {ok: false, reason: 'insert control not found'};
        const before = location.href;
        target.click();
        return {
          ok: true,
          id: target.id || '',
          name: target.name || '',
          value: target.value || '',
          text: target.innerText || '',
          before
        };
        """
    )


def click_save_control(driver: webdriver.Chrome) -> dict[str, Any]:
    return driver.execute_script(
        """
        const controls = Array.from(document.querySelectorAll('input, button, a'));
        const target = controls.find(el => {
          const text = [el.id, el.name, el.value, el.title, el.innerText]
            .map(x => String(x || '')).join(' ');
          return /儲存|存檔|確定|送出|Save|Submit/i.test(text);
        });
        if (!target) return {ok: false, reason: 'save control not found'};
        target.click();
        return {
          ok: true,
          id: target.id || '',
          name: target.name || '',
          value: target.value || '',
          text: target.innerText || ''
        };
        """
    )


def click_entry_insert_control(driver: webdriver.Chrome) -> dict[str, Any]:
    return driver.execute_script(
        """
        const target = document.getElementById('_btnInsert');
        if (!target) return {ok: false, reason: 'entry insert control not found'};
        target.click();
        return {
          ok: true,
          id: target.id || '',
          name: target.name || '',
          value: target.value || '',
          text: target.innerText || ''
        };
        """
    )


# Work log automation

def accept_pending_alerts(driver: webdriver.Chrome, max_alerts: int = 2) -> list[str]:
    accepted: list[str] = []
    for _ in range(max_alerts):
        try:
            alert = driver.switch_to.alert
            text = alert.text.strip()
            alert.accept()
            accepted.append(text)
            time.sleep(0.5)
        except Exception:
            break
    return accepted


def quit_driver(driver: webdriver.Chrome | None) -> None:
    if not driver:
        return
    service = getattr(driver, "service", None)
    profile_dir = getattr(driver, "_sinposmart_duty_browser_profile", "")
    quit_failed = False
    try:
        driver.quit()
    except Exception:
        quit_failed = True
        raise
    finally:
        if service:
            try:
                service.stop()
            except Exception:
                pass
        if profile_dir:
            cleanup_duty_browser_profile(Path(str(profile_dir)), terminate_processes=quit_failed)


def set_work_log_content_fields(driver: webdriver.Chrome, fields: dict[str, Any]) -> dict[str, Any]:
    return driver.execute_script(
        """
        const values = arguments[0];
        const result = {set: [], missing: []};
        function setControl(el, value) {
          if (!el) return false;
          if (el.tagName.toLowerCase() === 'select') {
            const target = String(value || '').trim();
            const options = Array.from(el.options || []);
            const option = options.find(opt =>
              String(opt.text || '').trim() === target ||
              String(opt.value || '').trim() === target
            ) || options.find(opt => String(opt.text || '').includes(target));
            if (!option) return false;
            el.value = option.value;
          } else {
            el.value = value;
          }
          el.dispatchEvent(new Event('input', {bubbles: true}));
          el.dispatchEvent(new Event('change', {bubbles: true}));
          result.set.push({id: el.id || '', name: el.name || '', value});
          return true;
        }
        function setDirect(id, value) {
          const el = document.getElementById(id);
          return setControl(el, value);
        }
        if (!setDirect('_areDescription', values.description)) result.missing.push('description');
        if (!setDirect('_areStatus', values.status)) result.missing.push('status');
        return result;
        """,
        {
            "description": fields.get("工作概述", ""),
            "status": fields.get("處理情形", ""),
        },
    )


def set_work_log_reason_field(driver: webdriver.Chrome, fields: dict[str, Any]) -> dict[str, Any]:
    reason = fields.get("事由", "")
    if not reason:
        return {"set": [], "missing": [], "skipped": True}
    return driver.execute_script(
        """
        const values = arguments[0];
        const result = {set: [], missing: [], confirms: []};
        function setControl(el, value) {
          if (!el) return false;
          if (el.tagName.toLowerCase() === 'select') {
            const target = String(value || '').trim();
            const options = Array.from(el.options || []);
            const option = options.find(opt =>
              String(opt.text || '').trim() === target ||
              String(opt.value || '').trim() === target
            ) || options.find(opt => String(opt.text || '').includes(target));
            if (!option) return false;
            el.value = option.value;
          } else {
            el.value = value;
          }
          const originalConfirm = window.confirm;
          window.confirm = message => {
            result.confirms.push(String(message || ''));
            return true;
          };
          try {
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
          } finally {
            window.confirm = originalConfirm;
          }
          result.set.push({id: el.id || '', name: el.name || '', value});
          return true;
        }
        function setDirect(id, value) {
          const el = document.getElementById(id);
          return setControl(el, value);
        }
        function byIds(ids, value) {
          for (const id of ids) {
            if (setDirect(id, value)) return true;
          }
          return false;
        }
        function byOptionText(value) {
          const target = String(value || '').trim();
          const el = Array.from(document.querySelectorAll('select')).find(control =>
            Array.from(control.options || []).some(opt =>
              String(opt.text || '').trim() === target ||
              String(opt.value || '').trim() === target ||
              String(opt.text || '').includes(target)
            )
          );
          return setControl(el, value);
        }
        function byNearbyText(label, value) {
          const normalize = text => String(text || '').replace(/\\s+/g, '');
          const controlsOf = root => Array.from(root.querySelectorAll('input, select, textarea'));
          const rows = Array.from(document.querySelectorAll('tr'));
          for (const row of rows) {
            const cells = Array.from(row.children);
            const labelIndex = cells.findIndex(cell => normalize(cell.innerText).includes(label));
            if (labelIndex < 0) continue;
            const controls = cells.slice(labelIndex + 1).flatMap(controlsOf);
            for (const control of controls) {
              if (setControl(control, value)) return true;
            }
          }
          return false;
        }
        if (!byIds(['_selReason', '_selList4', '_selList2', '_txtReason'], values.reason) && !byNearbyText('事由', values.reason) && !byOptionText(values.reason)) result.missing.push('reason');
        return result;
        """,
        {"reason": reason},
    )


def fill_work_log_form_for_test(
    driver: webdriver.Chrome,
    action: dict[str, Any],
    staff: dict[str, dict[str, str]],
    target_roc_date: str,
    save: bool = False,
) -> dict[str, Any]:
    """Fill the work-log form. Save only when explicitly requested."""

    fields = action.get("fields", {})
    time_value = fields.get("工作時間", action.get("time", "00:00"))
    hour, minute = time_value.split(":", 1)
    people = [
        {
            "id": staff.get(str(no), {}).get("user_id", ""),
            "name": staff.get(str(no), {}).get("name", str(no)),
        }
        for no in fields.get("服勤人員", [])
    ]

    navigated = ensure_ap(driver, WORK_LOG_AP)
    if navigated:
        time.sleep(1)
    before_controls = control_snapshot(driver)
    form_ready = driver.execute_script("return Boolean(document.getElementById('_txtDATE') && document.getElementById('_selTIMEH') && document.getElementById('_areDescription'));")
    insert_result = {"ok": True, "skipped": True, "reason": "work form already open"} if form_ready else click_insert_control(driver)
    time.sleep(2)

    fill_result = driver.execute_script(
        """
        const values = arguments[0];
        const result = {set: [], missing: [], confirms: []};
        const used = new Set();

        function visibleControls() {
          return Array.from(document.querySelectorAll('input, select, textarea'));
        }
        function setControl(el, value, confirmOnReplace = false) {
          if (!el) return false;
          const key = el.id || el.name || `${el.tagName}:${result.set.length}`;
          if (used.has(key)) return false;
          const oldValue = String(el.value || '');
          const willReplace = oldValue.trim() !== '' && oldValue !== String(value);
          if (el.tagName.toLowerCase() === 'select') {
            const options = Array.from(el.options || []);
            const exactOption = options.find(opt =>
              String(opt.text || '').trim() === String(value).trim() ||
              String(opt.value || '').trim() === String(value).trim()
            );
            const option = exactOption || options.find(opt =>
              String(opt.text || '').includes(String(value).trim())
            );
            if (!option) return false;
            el.value = option.value;
          } else {
            el.value = value;
          }
          const originalConfirm = window.confirm;
          if (confirmOnReplace && willReplace) {
            window.confirm = message => {
              result.confirms.push(String(message || ''));
              return true;
            };
          }
          try {
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
          } finally {
            window.confirm = originalConfirm;
          }
          used.add(key);
          result.set.push({id: el.id || '', name: el.name || '', value});
          return true;
        }
        function byIds(ids, value) {
          for (const id of ids) {
            const el = document.getElementById(id);
            if (setControl(el, value)) return true;
          }
          return false;
        }
        function optionMatches(opt, value, exactOnly = false) {
          const target = String(value || '').trim();
          const text = String(opt.text || '').trim();
          const optValue = String(opt.value || '').trim();
          if (text === target || optValue === target) return true;
          if (exactOnly) return false;
          return text.includes(target);
        }
        function byOptionText(value) {
          const exactOnly = String(value || '').trim() === '其他';
          const el = visibleControls().find(control =>
            control.tagName.toLowerCase() === 'select' &&
            Array.from(control.options || []).some(opt => optionMatches(opt, value, exactOnly))
          );
          return setControl(el, value, true);
        }
        if (!byIds(['_txtDATE', '_txtDate', '_txtTaskDate', '_txtSDATE', '_txtSdate'], values.date)) result.missing.push('date');
        if (!byIds(['_selTIMEH', '_selSTIMEH', '_selTimeH', '_selHH', '_selHOUR'], values.hour)) result.missing.push('hour');
        if (!byIds(['_selTIMEM', '_selSTIMEM', '_selTimeM', '_selMM', '_selMIN'], values.minute)) result.missing.push('minute');
        byIds(['_selETIMEH', '_selETimeH'], values.hour);
        byIds(['_selETIMEM', '_selETimeM'], values.minute);
        if (!byOptionText(values.item)) result.missing.push('item');
        return result;
        """,
        {
            "date": target_roc_date,
            "hour": hour,
            "minute": minute,
            "item": fields.get("勤務項目", ""),
        },
    )
    fill_result["item_alerts"] = accept_pending_alerts(driver)
    reason_result = set_work_log_reason_field(driver, fields)
    fill_result["reason"] = reason_result
    fill_result["reason_alerts"] = accept_pending_alerts(driver)
    time.sleep(1)
    content_result = set_work_log_content_fields(driver, fields)
    fill_result["content"] = content_result

    people_result = set_work_people(driver, people, fallback_popup=True) if people else {"ok": False, "missing": []}
    save_result = click_save_control(driver) if save else {"ok": False, "skipped": True}
    if save:
        time.sleep(2)
    after_controls = control_snapshot(driver)
    return {
        "ok": True,
        "insert": insert_result,
        "fill": fill_result,
        "people": people_result,
        "save": save_result,
        "before_controls": before_controls,
        "after_controls": after_controls,
    }


# Entry log automation

def fill_entry_log_form_for_test(
    driver: webdriver.Chrome,
    action: dict[str, Any],
    staff: dict[str, dict[str, str]],
    target_roc_date: str,
    save: bool = False,
) -> dict[str, Any]:
    """Fill the entry-log form. Save only when explicitly requested."""

    fields = action.get("fields", {})
    time_value = fields.get("系統寫入時間", fields.get("登打時間", action.get("time", "00:00")))
    hour, minute = time_value.split(":", 1)
    target_no = str(action.get("target", ""))
    person = {
        "id": staff.get(target_no, {}).get("user_id", ""),
        "name": staff.get(target_no, {}).get("name", target_no),
        "duty_no": target_no,
    }

    navigated = ensure_ap(driver, ENTRY_LOG_AP)
    if navigated:
        time.sleep(1)
    before_controls = control_snapshot(driver)
    form_ready = driver.execute_script("return Boolean(document.getElementById('_txtDATE') && document.getElementById('_selTIMEH'));")
    insert_result = {"ok": True, "skipped": True, "reason": "entry form already open"} if form_ready else click_insert_control(driver)
    time.sleep(2)

    fill_result = driver.execute_script(
        """
        const values = arguments[0];
        const result = {set: [], missing: []};
        const used = new Set();

        function controls() {
          return Array.from(document.querySelectorAll('input, select, textarea'));
        }
        function setControl(el, value) {
          if (!el) return false;
          const key = el.id || el.name || `${el.tagName}:${result.set.length}`;
          if (used.has(key)) return false;
          if (el.tagName.toLowerCase() === 'select') {
            const option = Array.from(el.options || []).find(opt =>
              String(opt.text || '').trim() === String(value).trim() ||
              String(opt.value || '').trim() === String(value).trim() ||
              String(opt.text || '').includes(String(value).trim())
            );
            if (!option) return false;
            el.value = option.value;
          } else {
            el.value = value;
          }
          el.dispatchEvent(new Event('input', {bubbles: true}));
          el.dispatchEvent(new Event('change', {bubbles: true}));
          used.add(key);
          result.set.push({id: el.id || '', name: el.name || '', value});
          return true;
        }
        function byIds(ids, value) {
          for (const id of ids) {
            if (setControl(document.getElementById(id), value)) return true;
          }
          return false;
        }
        function byOptionText(value) {
          const el = controls().find(control =>
            control.tagName.toLowerCase() === 'select' &&
            Array.from(control.options || []).some(opt => String(opt.text || '').trim() === String(value).trim())
          );
          return setControl(el, value);
        }
        function byNearbyText(label, value) {
          const normalize = text => String(text || '').replace(/\\s+/g, '');
          const rows = Array.from(document.querySelectorAll('tr'));
          for (const row of rows) {
            const cells = Array.from(row.children);
            const labelIndex = cells.findIndex(cell => normalize(cell.innerText).includes(label));
            if (labelIndex < 0) continue;
            const candidates = cells.slice(labelIndex + 1).flatMap(cell =>
              Array.from(cell.querySelectorAll('input, select, textarea'))
            );
            for (const control of candidates) {
              if (setControl(control, value)) return true;
            }
          }
          return false;
        }

        if (!byIds(['_txtDATE', '_txtDate', '_txtTaskDate', '_txtSDATE', '_txtSdate'], values.date)) result.missing.push('date');
        if (!byIds(['_selTIMEH', '_selSTIMEH', '_selTimeH', '_selHH', '_selHOUR'], values.hour)) result.missing.push('hour');
        if (!byIds(['_selTIMEM', '_selSTIMEM', '_selTimeM', '_selMM', '_selMIN'], values.minute)) result.missing.push('minute');
        if (values.duty_item && !byIds(['_selList3'], values.duty_item)) result.missing.push('duty_item');
        if (typeof changeSelList4 === 'function') changeSelList4();
        return result;
        """,
        {
            "date": target_roc_date,
            "hour": hour,
            "minute": minute,
            "duty_item": fields.get("勤務項目", ""),
        },
    )
    time.sleep(1)
    people_result = set_entry_people(driver, [person], fallback_popup=True)
    if not people_result.get("ok"):
        raise RuntimeError("entry people selection failed: " + json.dumps(people_result, ensure_ascii=False))
    selected_people = people_result.get("selected") or []
    selected_person = selected_people[0] or {} if selected_people else {}
    selected_value = str(selected_person.get("value", ""))
    selected_user_id = str(selected_person.get("id", "")).strip() or selected_value.split(",", 1)[0].strip() or people_result.get("hidManId", "")
    selected_title = str(selected_person.get("title", "")).strip()
    selected_man_value = selected_value or ",".join(part for part in (selected_user_id, selected_title) if part)
    outin_result = driver.execute_script(
        """
        const values = arguments[0];
        const result = {set: [], missing: []};
        const used = new Set();

        function controls() {
          return Array.from(document.querySelectorAll('input, select, textarea'));
        }
        function setControl(el, value) {
          if (!el) return false;
          const key = el.id || el.name || `${el.tagName}:${result.set.length}`;
          if (used.has(key)) return false;
          if (el.tagName.toLowerCase() === 'select') {
            const option = Array.from(el.options || []).find(opt =>
              String(opt.text || '').trim() === String(value).trim() ||
              String(opt.value || '').trim() === String(value).trim() ||
              String(opt.text || '').includes(String(value).trim())
            );
            if (!option) return false;
            el.value = option.value;
          } else {
            el.value = value;
          }
          el.dispatchEvent(new Event('input', {bubbles: true}));
          el.dispatchEvent(new Event('change', {bubbles: true}));
          used.add(key);
          result.set.push({id: el.id || '', name: el.name || '', value});
          return true;
        }
        function byIds(ids, value) {
          for (const id of ids) {
            if (setControl(document.getElementById(id), value)) return true;
          }
          return false;
        }
        function byOptionText(value) {
          const el = controls().find(control =>
            control.tagName.toLowerCase() === 'select' &&
            Array.from(control.options || []).some(opt => String(opt.text || '').trim() === String(value).trim())
          );
          return setControl(el, value);
        }
        function byNearbyText(label, value) {
          const normalize = text => String(text || '').replace(/\\s+/g, '');
          const rows = Array.from(document.querySelectorAll('tr'));
          for (const row of rows) {
            const cells = Array.from(row.children);
            const labelIndex = cells.findIndex(cell => normalize(cell.innerText).includes(label));
            if (labelIndex < 0) continue;
            const candidates = cells.slice(labelIndex + 1).flatMap(cell =>
              Array.from(cell.querySelectorAll('input, select, textarea'))
            );
            for (const control of candidates) {
              if (setControl(control, value)) return true;
            }
          }
          return false;
        }
        function selectedOptionText(el) {
          return String(el?.options?.[el.selectedIndex]?.text || '').trim();
        }
        function setOutinControl(el) {
          if (!el || el.tagName.toLowerCase() !== 'select') return false;
          const key = el.id || el.name || `${el.tagName}:outin`;
          if (used.has(key)) return false;
          const wantedValue = String(values.outin_value || '').trim();
          const wantedText = String(values.outin_text || values.outin || '').trim();
          const options = Array.from(el.options || []);
          const option = options.find(opt => wantedValue && String(opt.value || '').trim() === wantedValue) ||
            options.find(opt => wantedText && String(opt.text || '').trim() === wantedText) ||
            options.find(opt => wantedText && String(opt.text || '').replace(/\\s+/g, '') === wantedText);
          if (!option) return false;
          el.value = option.value;
          el.dispatchEvent(new Event('input', {bubbles: true}));
          el.dispatchEvent(new Event('change', {bubbles: true}));
          used.add(key);
          const actualText = selectedOptionText(el);
          const confirmed = (
            (wantedValue && String(el.value || '').trim() === wantedValue) ||
            (wantedText && actualText === wantedText)
          );
          result.outin = {
            id: el.id || '',
            name: el.name || '',
            value: el.value || '',
            text: actualText,
            confirmed,
          };
          result.set.push({id: el.id || '', name: el.name || '', value: el.value || '', text: actualText, field: 'outin'});
          return confirmed;
        }
        function byOutinIds(ids) {
          for (const id of ids) {
            if (setOutinControl(document.getElementById(id))) return true;
          }
          return false;
        }
        function byNearbyOutin(label) {
          const normalize = text => String(text || '').replace(/\\s+/g, '');
          const rows = Array.from(document.querySelectorAll('tr'));
          for (const row of rows) {
            const cells = Array.from(row.children);
            const labelIndex = cells.findIndex(cell => normalize(cell.innerText).includes(label));
            if (labelIndex < 0) continue;
            const candidates = cells.slice(labelIndex + 1).flatMap(cell =>
              Array.from(cell.querySelectorAll('select'))
            );
            for (const control of candidates) {
              if (setOutinControl(control)) return true;
            }
          }
          return false;
        }
        function byOutinSignature() {
          const candidates = controls().filter(control => {
            if (control.tagName.toLowerCase() !== 'select') return false;
            const signature = String(`${control.id || ''} ${control.name || ''}`).toLowerCase();
            return signature.includes('isout') || signature.includes('outin') ||
              signature.includes('out_in') || signature.includes('inout') || signature === 'io';
          });
          for (const control of candidates) {
            if (setOutinControl(control)) return true;
          }
          return false;
        }

        if (!byIds(['_selMan'], values.man)) result.missing.push('man');
        byIds(['_txtMan'], values.man_name);
        if (values.title) byIds(['_selTitle'], values.title);
        if (values.title_text) byIds(['_txtTitle'], values.title_text);
        if (values.outin || values.outin_value) {
          const outinSet = byOutinIds(['_selIsout', '_selOutIn', '_selIO', '_selOutin', '_selINOUT']) ||
            byNearbyOutin('出或入') || byOutinSignature();
          if (!outinSet) {
            result.missing.push('outin');
          } else if (!result.outin?.confirmed) {
            result.missing.push('outin_confirm');
          }
        }
        if (values.radio && !byIds(['_txtRadiokind', '_txtRadio', '_txtRadioNo', '_txtWireless'], values.radio) && !byNearbyText('手提無線電編號', values.radio) && !byNearbyText('無線電', values.radio)) result.missing.push('radio');
        if (values.returned && !byIds(['_selReturn', '_selIsReturn', '_txtReturn'], values.returned) && !byOptionText(values.returned) && !byNearbyText('是否歸還', values.returned)) result.missing.push('returned');
        return result;
        """,
        {
            "man": selected_man_value,
            "man_name": person["name"],
            "title": selected_title,
            "title_text": "",
            "outin": fields.get("出或入", ""),
            "outin_text": fields.get("出或入", ""),
            "outin_value": ENTRY_OUTIN_VALUE_MAP.get(fields.get("出或入", ""), ""),
            "radio": fields.get("手提無線電編號", ""),
            "returned": fields.get("是否歸還", ""),
        },
    )
    time.sleep(1)
    reason_result = driver.execute_script(
        """
        const values = arguments[0];
        const result = {set: [], missing: []};

        function setControl(el, value) {
          if (!el) return false;
          el.value = value;
          el.dispatchEvent(new Event('input', {bubbles: true}));
          el.dispatchEvent(new Event('change', {bubbles: true}));
          result.set.push({id: el.id || '', name: el.name || '', value});
          return true;
        }
        function byIds(ids, value) {
          for (const id of ids) {
            if (setControl(document.getElementById(id), value)) return true;
          }
          return false;
        }
        function byNearbyText(label, value) {
          const normalize = text => String(text || '').replace(/\\s+/g, '');
          const rows = Array.from(document.querySelectorAll('tr'));
          for (const row of rows) {
            const cells = Array.from(row.children);
            const labelIndex = cells.findIndex(cell => normalize(cell.innerText).includes(label));
            if (labelIndex < 0) continue;
            const candidates = cells.slice(labelIndex + 1).flatMap(cell =>
              Array.from(cell.querySelectorAll('input, textarea'))
            );
            for (const control of candidates) {
              if (setControl(control, value)) return true;
            }
          }
          return false;
        }

        if (values.reason && !byIds(['_areMemo', '_txtPlace', '_txtReason', '_txtMemo', '_txtRemark'], values.reason) && !byNearbyText('領用事由及地點', values.reason) && !byNearbyText('事由及地點', values.reason)) {
          result.missing.push('reason');
        }
        return result;
        """,
        {
            "reason": fields.get("領用事由及地點", ""),
        },
    )
    time.sleep(1)

    save_result = click_entry_insert_control(driver) if save else {"ok": False, "skipped": True}
    if save:
        time.sleep(2)
    after_controls = control_snapshot(driver)
    return {
        "ok": True,
        "insert": insert_result,
        "fill": fill_result,
        "outin": outin_result,
        "reason": reason_result,
        "people": people_result,
        "save": save_result,
        "before_controls": before_controls,
        "after_controls": after_controls,
    }


# Manual inspection tools

def open_entry_log_form_for_manual(driver: webdriver.Chrome) -> dict[str, Any]:
    """Open a blank entry-log insert form for manual field inspection."""

    open_ap(driver, ENTRY_LOG_AP)
    time.sleep(1)
    before_controls = control_snapshot(driver)
    form_ready = driver.execute_script("return Boolean(document.getElementById('_txtDATE') && document.getElementById('_selTIMEH'));")
    insert_result = {"ok": True, "skipped": True, "reason": "entry form already open"} if form_ready else click_insert_control(driver)
    time.sleep(2)
    after_controls = control_snapshot(driver)
    return {
        "ok": True,
        "insert": insert_result,
        "before_controls": before_controls,
        "after_controls": after_controls,
        "save": {"ok": False, "skipped": True},
    }


def inspect_entry_log_format(
    driver: webdriver.Chrome,
    action: dict[str, Any],
    staff: dict[str, dict[str, str]],
    target_roc_date: str,
) -> dict[str, Any]:
    """Open entry-log form and capture main/popup control formats."""

    fields = action.get("fields", {})
    time_value = fields.get("系統寫入時間", fields.get("登打時間", action.get("time", "00:00")))
    hour, minute = time_value.split(":", 1)
    target_no = str(action.get("target", ""))
    person = {
        "id": staff.get(target_no, {}).get("user_id", ""),
        "name": staff.get(target_no, {}).get("name", target_no),
        "duty_no": target_no,
    }

    open_ap(driver, ENTRY_LOG_AP)
    time.sleep(1)
    before_controls = control_snapshot(driver)
    form_ready = driver.execute_script("return Boolean(document.getElementById('_txtDATE') && document.getElementById('_selTIMEH'));")
    insert_result = {"ok": True, "skipped": True, "reason": "entry form already open"} if form_ready else click_insert_control(driver)
    time.sleep(2)
    main_before_popup = control_snapshot(driver)
    fill_result = driver.execute_script(
        """
        const values = arguments[0];
        const result = {set: [], missing: []};

        function setById(id, value) {
          const el = document.getElementById(id);
          if (!el) return false;
          if (el.tagName.toLowerCase() === 'select') {
            const option = Array.from(el.options || []).find(opt =>
              String(opt.text || '').trim() === String(value).trim() ||
              String(opt.value || '').trim() === String(value).trim()
            );
            if (!option) return false;
            el.value = option.value;
          } else {
            el.value = value;
          }
          el.dispatchEvent(new Event('input', {bubbles: true}));
          el.dispatchEvent(new Event('change', {bubbles: true}));
          result.set.push({id, value});
          return true;
        }

        if (!setById('_txtDATE', values.date)) result.missing.push('_txtDATE');
        if (!setById('_selTIMEH', values.hour)) result.missing.push('_selTIMEH');
        if (!setById('_selTIMEM', values.minute)) result.missing.push('_selTIMEM');
        if (!setById('_areMemo', values.reason)) result.missing.push('_areMemo');
        return result;
        """,
        {
            "date": target_roc_date,
            "hour": hour,
            "minute": minute,
            "reason": fields.get("領用事由及地點", ""),
        },
    )
    handles_before = set(driver.window_handles)
    WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "_btnOpenWin"))).click()
    WebDriverWait(driver, 10).until(lambda d: len(set(d.window_handles) - handles_before) == 1)
    popup_window = (set(driver.window_handles) - handles_before).pop()
    driver.switch_to.window(popup_window)
    popup_controls = control_snapshot(driver)
    popup_summary = driver.execute_script(
        """
        return {
          title: document.title,
          url: location.href,
          bodyText: document.body ? document.body.innerText.slice(0, 8000) : '',
          checkboxes: Array.from(document.querySelectorAll('input[type="checkbox"], input[name="_chkUser"]')).map(el => ({
            id: el.id || '',
            name: el.name || '',
            value: el.value || '',
            checked: el.checked,
            rowText: el.closest('tr')?.innerText || el.parentElement?.innerText || ''
          })),
          buttons: Array.from(document.querySelectorAll('input, button, a')).map(el => ({
            tag: el.tagName.toLowerCase(),
            type: el.type || '',
            id: el.id || '',
            name: el.name || '',
            value: el.value || '',
            text: el.innerText || ''
          }))
        };
        """
    )
    driver.switch_to.window(driver.window_handles[0])
    return {
        "ok": True,
        "target_person": person,
        "insert": insert_result,
        "fill": fill_result,
        "before_controls": before_controls,
        "main_before_popup": main_before_popup,
        "popup_controls": popup_controls,
        "popup_summary": popup_summary,
        "save": {"ok": False, "skipped": True},
    }


# Login and query readers

def login(driver: webdriver.Chrome, user_id: str, password: str) -> None:
    wait = WebDriverWait(driver, 20)
    driver.get(f"{BASE_URL}/login119")
    wait.until(EC.presence_of_element_located((By.ID, "_txtUsername"))).send_keys(user_id)
    driver.find_element(By.ID, "_txtPassword").send_keys(password)
    driver.execute_script(
        """
        if (document.getElementById('hidFlag')) {
          document.getElementById('hidFlag').value = 'APPLICATION';
        }
        if (typeof Testlogin === 'function') {
          Testlogin();
        } else {
          document.getElementById('ndppc').submit();
        }
        """
    )
    for _ in range(20):
        error = detect_login_error(driver)
        if error:
            raise RuntimeError(error)
        time.sleep(0.25)
    # The legacy app can keep login119 in the address bar after posting. The
    # real proof is whether authenticated AP pages load, so callers verify that.


def query_authenticated_person_name(driver: webdriver.Chrome, user_id: str) -> str:
    """Read the logged-in person's name from the work-log form without saving."""

    user_id = str(user_id or "").strip()
    if not user_id:
        return ""

    def read_matching_names() -> list[str]:
        values = driver.execute_script(
            """
            const normalize = value => String(value || '').trim().toLowerCase();
            const loginId = normalize(arguments[0]);
            const loginAliases = new Set([
              loginId,
              loginId.replace(/^[a-z]+/, ''),
              loginId.replace(/^[a-z]+/, '').replace(/^0+/, '')
            ].filter(Boolean));
            const names = [];
            const pushName = value => {
              for (const part of String(value || '').split(/[,，]/)) {
                const name = part.trim();
                if (name && !/^\\d+$/.test(name) && !names.includes(name)) names.push(name);
              }
            };
            const matchesLogin = value => {
              const parts = String(value || '').split(/[,，|;\\s]+/)
                .map(normalize)
                .flatMap(part => /^\\d+$/.test(part) ? [part, part.replace(/^0+/, '')] : [part])
                .filter(Boolean);
              return parts.some(part => loginAliases.has(part));
            };

            const directIds = ['_hidManId', '_txtUserId', '_hidUserId', '_txtLoginId']
              .map(id => document.getElementById(id)?.value || '')
              .filter(Boolean);
            if (directIds.some(matchesLogin)) {
              for (const id of ['_areMan', '_txtMan', '_txtUserName', '_hidUserName']) {
                pushName(document.getElementById(id)?.value || '');
              }
            }

            for (const id of ['_selMan', '_selManData']) {
              const select = document.getElementById(id);
              for (const option of Array.from(select?.options || [])) {
                if (matchesLogin(option.value)) pushName(option.text);
              }
            }
            for (const checkbox of document.querySelectorAll('input[name="_chkUser"]')) {
              if (!matchesLogin(checkbox.value)) continue;
              const parts = String(checkbox.value || '').split(',');
              if (parts.length > 1) pushName(parts.slice(1).join(','));
            }
            return names;
            """,
            user_id,
        ) or []
        return [str(value or "").strip() for value in values if str(value or "").strip()]

    if ensure_ap(driver, WORK_LOG_AP):
        time.sleep(1)
    names = read_matching_names()
    if len(names) == 1:
        return names[0]

    form_ready = driver.execute_script(
        "return Boolean(document.getElementById('_txtDATE') && document.getElementById('_areDescription'));"
    )
    if not form_ready:
        insert_result = click_insert_control(driver)
        if not insert_result.get("ok"):
            return ""
        time.sleep(2)
        names = read_matching_names()
    return names[0] if len(names) == 1 else ""


def query_duty_sheet(driver: webdriver.Chrome, target_roc_date: str) -> DutySheet:
    open_ap(driver, DUTY_TABLE_AP)
    try:
        WebDriverWait(driver, 15, poll_frequency=0.25).until(
            lambda current_driver: bool(
                current_driver.execute_script(
                    """
                    const dateField = document.getElementById('_txtTaskDate');
                    const queryButton = document.getElementById('_btnQuery') ||
                      document.getElementById('_btnSearch');
                    return Boolean(dateField && queryButton);
                    """
                )
            )
        )
    except TimeoutException as exc:
        raise RuntimeError("勤務表查詢失敗：查詢介面未在 15 秒內完成載入。") from exc
    suppress_window_open_for_background_query(driver)
    if not js_set(driver, "_txtTaskDate", target_roc_date):
        raise RuntimeError("勤務表查詢失敗：找不到查詢日期欄位。")
    if not js_click(driver, "_btnQuery") and not js_click(driver, "_btnSearch"):
        raise RuntimeError("勤務表查詢失敗：找不到查詢按鈕。")
    try:
        WebDriverWait(driver, 15, poll_frequency=0.25).until(
            lambda current_driver: bool(
                current_driver.execute_script(
                    """
                    return Array.from(document.querySelectorAll('table')).some(table => {
                      if (!String(table.className || '').includes('report_list1')) return false;
                      const slots = Array.from(table.querySelectorAll('tr')).map(row =>
                        String(row.children[0]?.innerText || '').replace(/\\s+/g, '')
                      );
                      return slots.some(slot => /^8[~～-]9$/.test(slot)) &&
                        slots.some(slot => /^7[~～-]8$/.test(slot));
                    });
                    """
                )
            )
        )
    except TimeoutException as exc:
        raise RuntimeError("勤務表讀取逾時：等待查詢結果超過 15 秒。") from exc
    data = driver.execute_script(
        """
        function cellText(cell) {
          const text = (cell.innerText || '').trim();
          const controls = Array.from(cell.querySelectorAll('textarea,input,select'));
          const hasTextarea = controls.some(el => el.tagName === 'TEXTAREA');
          const visibleControls = controls.filter(el => {
            const style = window.getComputedStyle(el);
            return el.tagName === 'TEXTAREA' || (el.type !== 'hidden' && style.display !== 'none');
          });
          if (text && !hasTextarea) return text;
          const parts = (visibleControls.length ? visibleControls : controls).map(el => {
            if (el.tagName === 'SELECT') return el.options[el.selectedIndex]?.text || el.value || '';
            return el.value || '';
          }).filter(Boolean);
          return parts.length ? parts.join(' ') : text;
        }
        const tables = Array.from(document.querySelectorAll('table'));
        const result = {unit: '', rows: [], summary: {}, staff: {}, checkNums: []};
        const bodyText = document.body.innerText || '';
        const unitMatch = bodyText.match(/勤務單位\\s*[:：]\\s*([^\\n\\r\\t ]+)/);
        if (unitMatch) result.unit = unitMatch[1];

        for (const table of tables) {
          const trs = Array.from(table.querySelectorAll('tr'));
          const matrix = trs.map(tr => Array.from(tr.children).map(cellText));
          const flat = matrix.flat().join('|');
          const looksLikeDutyTable = table.className.includes('report_list1') &&
            trs.length >= 20 &&
            matrix.some(row => /^8[~～-]9$/.test((row[0] || '').replace(/\\s+/g, ''))) &&
            matrix.some(row => /^7[~～-]8$/.test((row[0] || '').replace(/\\s+/g, '')));
          if (looksLikeDutyTable) {
            let header = [];
            for (const row of matrix) {
              if ((row[0] || '').includes('時段')) {
                header = row.map((value, index) => {
                  const key = (value || '').replace(/\\s+/g, '');
                  return index === 0 ? '時段' : key;
                });
                break;
              }
            }
            if (!header.length) {
              header = ['時段', '值班', '外勤1', '救護', '備勤', '休息', '檢核欄'];
            }
            for (const row of matrix) {
              if (row.length < 3) continue;
              const slot = row[0].replace(/\\s+/g, '');
              if (!/^\\d{1,2}[~～-]\\d{1,2}$/.test(slot)) continue;
              const cols = {};
              for (let i = 1; i < Math.min(header.length, row.length); i++) {
                const key = (header[i] || '').replace(/\\s+/g, '');
                if (key === '檢核欄') {
                  result.checkNums.push(...((row[i] || '').match(/\\d+/g) || []));
                  continue;
                }
                if (key) cols[key] = row[i] || '';
              }
              result.rows.push({slot, columns: cols});
            }
          }
          const looksLikeSummary = table.className.includes('report_list1') &&
            trs.length >= 8 &&
            matrix.some(row => /^\\d+(,\\d+)+/.test((row[1] || '').trim()));
          if (looksLikeSummary) {
            const summaryLabels = ['在勤', '輪休', '請休', '外宿', '公假', '產假', '病假', '事假',
              '榮譽假', '喪假', '差假', '婚假', '特別註記', '補休', '其他假別', '停休', '輪休公假'];
            for (const row of matrix) {
              for (let i = 0; i + 1 < row.length; i += 2) {
                const value = row[i + 1] || '';
                if (/^\\d+(,\\d+)*/.test(value.trim())) {
                  const label = summaryLabels.find(key => (row[i] || '').includes(key)) || (Object.keys(result.summary).length ? '未知' : '在勤');
                  result.summary[label] = value;
                }
              }
            }
          }
          const looksLikeStaffTable = table.className.includes('report_list1') &&
            matrix.some(row => row.some(cell => /^1$/.test(cell))) &&
            matrix.flat().join('|').match(/\\d{1,2}\\|[^|]+\\|[^|]+/);
          if (looksLikeStaffTable) {
            for (const row of matrix) {
              for (let i = 0; i + 2 < row.length; i++) {
                const no = (row[i] || '').trim();
                const role = (row[i + 1] || '').trim();
                const name = (row[i + 2] || '').trim();
                if (/^\\d{1,2}$/.test(no) && name) result.staff[no] = {role, name};
              }
            }
          }
        }
        return result;
        """
    )
    if not data.get("rows"):
        page_text = driver.execute_script(
            """
            const body = document.body ? document.body.innerText : '';
            const controls = Array.from(document.querySelectorAll('input,select,textarea'))
              .map(el => [el.id || '', el.name || '', el.value || ''].join(' '))
              .join('\\n');
            return [location.href || '', document.title || '', body, controls].join('\\n');
            """
        ) or ""
        if "login119" in page_text or "_txtUsername" in page_text or "_txtPassword" in page_text:
            raise RuntimeError("勤務表讀取失敗：登入狀態失效或密碼可能已變更，請登出/清除後重新輸入新密碼登入。")
        raise RuntimeError("勤務表讀取失敗：未讀到勤務表資料，已停止產生空白勤務資料。請確認勤務系統頁面是否正常。")
    sheet = DutySheet(
        roc_date=target_roc_date,
        unit=data.get("unit", ""),
        rows=[
            DutyRow(
                slot=row["slot"],
                columns={key: nums(value) for key, value in row["columns"].items() if key != "檢核欄"},
            )
            for row in data.get("rows", [])
        ],
        summary={key: roster_nums(value) for key, value in data.get("summary", {}).items()},
        staff=data.get("staff", {}),
    )
    off_duty = set()
    for key in OFF_DUTY_SUMMARY_KEYS:
        off_duty.update(sheet.summary.get(key, []))
    duty_column_nums = {
        no
        for row in sheet.rows
        for values in row.columns.values()
        for no in values
    }
    check_only = set(data.get("checkNums", [])) - duty_column_nums
    off_duty.update(check_only)
    if off_duty and "在勤" in sheet.summary:
        sheet.summary["在勤"] = [no for no in sheet.summary["在勤"] if no not in off_duty]
    return sheet


def wait_for_query_completion(driver: webdriver.Chrome, expected_page: str = "") -> None:
    """Wait for the duty system to confirm that its asynchronous query finished."""

    expected_page = str(expected_page or "")

    def query_completed(current_driver: webdriver.Chrome) -> bool:
        state = current_driver.execute_script(
            r"""
            const text = document.body?.innerText || '';
            const pageSelect = document.querySelector("select[name='pageSelect']");
            return {
              completed: /QUY-000\s*[:：]\s*查詢完成/.test(text)
                || /QUY-500\s*[:：]\s*查無資料/.test(text),
              page: pageSelect?.value || '',
              hasRows: Array.from(document.querySelectorAll('tr')).some(row => row.children.length >= 3)
            };
            """
        )
        if not isinstance(state, dict):
            return False
        if expected_page:
            return str(state.get("page", "")) == expected_page and bool(state.get("hasRows"))
        return bool(state.get("completed"))

    WebDriverWait(driver, 8, poll_frequency=0.25).until(query_completed)


def query_visible_table(driver: webdriver.Chrome, ap_name: str, target_roc_date: str) -> list[list[str]]:
    open_ap(driver, ap_name)
    time.sleep(1)
    suppress_window_open_for_background_query(driver)
    for field_id in (
        "_txtSDATE",
        "_txtEDATE",
        "_txtDate",
        "_txtTaskDate",
        "_txtSdate",
        "_txtEDate",
        "_txtSDate",
        "_txtEndDate",
    ):
        js_set(driver, field_id, target_roc_date)
    js_set(driver, "_selSTIMEH", "00")
    js_set(driver, "_selSTIMEM", "00")
    js_set(driver, "_selETIMEH", "23")
    js_set(driver, "_selETIMEM", "59")
    js_set(driver, "_selQDept", "033006")
    js_set(driver, "_selDeptno", "033006")
    js_set(driver, "_txtPageNum", "200")
    for button_id in ("_btnQuery", "_btnSearch"):
        if js_click(driver, button_id):
            break
    wait_for_query_completion(driver)
    raw_rows = driver.execute_script(
        """
        return Array.from(document.querySelectorAll('tr')).map(tr =>
          Array.from(tr.children).map(td => (td.innerText || td.value || '').trim()).filter(Boolean)
        ).filter(row => row.length);
        """
    )
    roc_slash = f"{target_roc_date[:3]}/{target_roc_date[3:5]}/{target_roc_date[5:7]}"
    date_pattern = re.compile(rf"^(?:{re.escape(target_roc_date)}|{re.escape(roc_slash)})\s*\n?\d{{1,2}}:\d{{2}}")

    if ap_name == WORK_LOG_AP:
        return [row for row in raw_rows if len(row) >= 8 and date_pattern.match(str(row[0]))]

    rows: list[list[str]] = []
    index = 0
    while index < len(raw_rows):
        row = raw_rows[index]
        if len(row) >= 6 and date_pattern.match(str(row[0])):
            combined = list(row)
            if index + 1 < len(raw_rows):
                next_row = raw_rows[index + 1]
                if next_row and not date_pattern.match(str(next_row[0])):
                    combined.extend(next_row)
                    index += 1
            rows.append(combined)
        index += 1
    return rows


def case_query_pages(driver: webdriver.Chrome) -> list[str]:
    pages = driver.execute_script(
        """
        const pageSelect = document.querySelector("select[name='pageSelect']");
        if (!pageSelect) return [];
        return Array.from(pageSelect.options || [])
          .map(option => String(option.value || '').trim())
          .filter(Boolean);
        """
    )
    return [str(page) for page in pages] if isinstance(pages, list) else []


def select_case_query_page(driver: webdriver.Chrome, page: str) -> None:
    try:
        page_select = driver.find_element(By.CSS_SELECTOR, "select[name='pageSelect']")
        option = page_select.find_element(By.CSS_SELECTOR, f"option[value='{page}']")
        option.click()
        return
    except (AttributeError, NoSuchElementException, WebDriverException) as exc:
        raise RuntimeError(f"案件查詢無法以原生事件切換至第 {page} 頁。") from exc


def capture_case_query_table(driver: webdriver.Chrome) -> dict[str, Any]:
    captured_table = driver.execute_script(
        r"""
        const text = (element) => (element.innerText || element.textContent || element.value || '').trim();
        const tables = Array.from(document.querySelectorAll('table'));
        for (const table of tables) {
          const rows = Array.from(table.querySelectorAll('tr')).map(tr => ({
            cells: Array.from(tr.children).map(text),
            personnel_source: tr.querySelector("input[id^='_btnChoose']")?.getAttribute('onclick') || '',
          }));
          const matrix = rows.map(row => row.cells);
          const headers = matrix.find(row => row.some(cell => /返隊/.test(cell))) || [];
          if (headers.length && matrix.some(row => row.some(cell => /\d{1,2}:\d{2}:\d{2}/.test(cell)))) {
            return {
              headers,
              rows: rows.filter(row => row.cells !== headers && row.cells.filter(Boolean).length >= 3),
            };
          }
        }
        return {headers: [], rows: []};
        """
    )
    return captured_table if isinstance(captured_table, dict) else {"headers": [], "rows": []}


def query_cases(driver: webdriver.Chrome, target_roc_date: str) -> list[CaseRecord]:
    open_ap(driver, CASE_QUERY_AP)
    time.sleep(1)
    suppress_window_open_for_background_query(driver)
    for element_id, value in (
        ("_hidDeptno", "033006"),
        ("_txtSDATE", target_roc_date),
        ("_txtEDATE", target_roc_date),
        ("_selSTIMEH", "00"),
        ("_selSTIMEM", "00"),
        ("_selETIMEH", "23"),
        ("_selETIMEM", "59"),
    ):
        if not js_set(driver, element_id, value, dispatch_change=False):
            raise RuntimeError(f"案件查詢找不到欄位：{element_id}。")
    if not native_click(driver, "_btnQuery") and not js_click(driver, "_btnQuery"):
        raise RuntimeError("案件查詢找不到查詢按鈕。")
    wait_for_query_completion(driver)
    captured_tables = [capture_case_query_table(driver)]
    pages = case_query_pages(driver)
    for page in pages[1:]:
        select_case_query_page(driver, page)
        wait_for_query_completion(driver, expected_page=page)
        captured_tables.append(capture_case_query_table(driver))

    headers: list[str] = []
    rows: list[dict[str, Any]] = []
    for captured_table in captured_tables:
        if not headers:
            table_headers = captured_table.get("headers", [])
            if isinstance(table_headers, list):
                headers = [str(value or "") for value in table_headers]
        table_rows = captured_table.get("rows", [])
        if isinstance(table_rows, list):
            rows.extend(row for row in table_rows if isinstance(row, dict))
    return_column = next(
        (index for index, header in enumerate(headers) if "返隊" in re.sub(r"\s+", "", header)),
        None,
    )
    if return_column is None and (headers or rows):
        raise RuntimeError("案件查詢結果缺少返隊時間欄位。")
    cases: list[CaseRecord] = []
    for captured_row in rows:
        if not isinstance(captured_row, dict):
            continue
        row_values = captured_row.get("cells", [])
        if not isinstance(row_values, list):
            continue
        row = [str(value or "") for value in row_values]
        personnel_count = case_personnel_count(captured_row.get("personnel_source", ""))
        joined = " ".join(row)
        if is_test_case_row(row):
            continue
        if not re.search(r"\d{1,2}:\d{2}:\d{2}", joined):
            continue
        times = re.findall(r"\d{1,2}:\d{2}:\d{2}", joined)
        return_time = case_return_time(row[return_column]) if return_column < len(row) else ""
        category = ""
        for cell in row:
            if "緊急救護" in cell or is_fire_case_category(cell):
                category = cell
                break
        cases.append(
            CaseRecord(
                report_time=times[0] if times else "",
                return_time=return_time,
                category=category,
                raw=row,
                personnel_count=personnel_count,
            )
        )
    return cases


# Duty table interpretation

def slot_start(slot: str) -> int | None:
    m = re.match(r"(\d{1,2})[~～-](\d{1,2})", slot)
    return int(m.group(1)) if m else None


def slot_end(slot: str) -> int | None:
    m = re.match(r"(\d{1,2})[~～-](\d{1,2})", slot)
    return int(m.group(2)) if m else None


def row_for_hour(sheet: DutySheet, hour: int) -> DutyRow | None:
    for row in sheet.rows:
        start = slot_start(row.slot)
        end = slot_end(row.slot)
        if start is None or end is None:
            continue
        if start <= hour < end:
            return row
    return None


def people_at(sheet: DutySheet, hour: int, column: str) -> list[str]:
    row = row_for_hour(sheet, hour)
    return row.columns.get(column, []) if row else []


def fire_day_hour(hour: int) -> int:
    return hour if hour >= 8 else hour + 24


def fire_day_slot_bounds(slot: str) -> tuple[int, int] | None:
    start = slot_start(slot)
    end = slot_end(slot)
    if start is None or end is None:
        return None
    fire_start = fire_day_hour(start)
    fire_end = fire_day_hour(end)
    if end == 24:
        fire_end = 24
    if fire_end <= fire_start:
        fire_end += 24
    return fire_start, fire_end


def duty_segments(sheet: DutySheet) -> list[tuple[int, int, tuple[str, ...]]]:
    rows: list[tuple[int, int, tuple[str, ...]]] = []
    for row in sheet.rows:
        bounds = fire_day_slot_bounds(row.slot)
        people = tuple(row.columns.get("值班", []))
        if not bounds or not people:
            continue
        rows.append((bounds[0], bounds[1], people))
    rows.sort(key=lambda item: item[0])

    segments: list[tuple[int, int, tuple[str, ...]]] = []
    for start, end, people in rows:
        if segments and segments[-1][1] == start and segments[-1][2] == people:
            prev_start, _, _ = segments[-1]
            segments[-1] = (prev_start, end, people)
        else:
            segments.append((start, end, people))
    return segments


def duty_segment_before_fire_hour(sheet: DutySheet, fire_hour: int) -> tuple[int, int, tuple[str, ...]] | None:
    for start, end, people in duty_segments(sheet):
        if start < fire_hour <= end:
            return start, end, people
    return None


def clock_hour(fire_hour: int) -> int:
    return fire_hour % 24


def is_active_checkout_column(column: str) -> bool:
    return column not in OFF_DUTY_SUMMARY_KEYS and column != "檢核欄"


def needs_next_morning_checkout(sheet: DutySheet, no: str) -> bool:
    row = row_for_hour(sheet, 22)
    if not row:
        return False
    return any(no in values for column, values in row.columns.items() if is_active_checkout_column(column))


def rest_starting_at(sheet: DutySheet, hour: int, next_sheet: DutySheet | None = None) -> dict[str, int]:
    starts: dict[str, int] = {}
    ordered_rows = sorted(sheet.rows, key=lambda item: slot_start(item.slot) if slot_start(item.slot) is not None else -1)
    for row in ordered_rows:
        start = slot_start(row.slot)
        end = slot_end(row.slot)
        if start == hour and end is not None:
            previous = row_for_hour(sheet, start - 1) if start > 0 else None
            for no in row.columns.get("休息", []):
                if previous and no in previous.columns.get("休息", []):
                    continue
                block_end = end
                probe = end
                while True:
                    next_row = row_for_hour(sheet, probe)
                    if not next_row or no not in next_row.columns.get("休息", []):
                        break
                    next_end = slot_end(next_row.slot)
                    if next_end is None or next_end <= block_end:
                        break
                    block_end = next_end
                    probe = next_end
                if block_end == 8 and next_sheet and no in people_at(next_sheet, 8, "休息"):
                    probe = 8
                    while True:
                        next_row = row_for_hour(next_sheet, probe)
                        if not next_row or no not in next_row.columns.get("休息", []):
                            break
                        next_end = slot_end(next_row.slot)
                        if next_end is None or next_end <= probe:
                            break
                        block_end = next_end
                        probe = next_end
                starts[no] = block_end
    return starts


def rest_blocks(sheet: DutySheet, next_sheet: DutySheet | None = None) -> list[tuple[str, int, int | None]]:
    blocks: list[tuple[str, int, int | None]] = []
    active: dict[str, int] = {}
    ordered_rows = sorted(sheet.rows, key=lambda item: slot_start(item.slot) if slot_start(item.slot) is not None else -1)
    for row in ordered_rows:
        start = slot_start(row.slot)
        end = slot_end(row.slot)
        if start is None or end is None:
            continue
        current = set(row.columns.get("休息", []))
        for no in current:
            active.setdefault(no, start)
        for no in list(active.keys()):
            if no in current:
                continue
            block_start = active.pop(no)
            block_end = start
            if block_end == 8 and next_sheet and no in people_at(next_sheet, 8, "休息"):
                probe = 8
                while True:
                    next_row = row_for_hour(next_sheet, probe)
                    if not next_row or no not in next_row.columns.get("休息", []):
                        break
                    next_end = slot_end(next_row.slot)
                    if next_end is None or next_end <= probe:
                        break
                    block_end = next_end
                    probe = next_end
            blocks.append((no, block_start, block_end))
    final_end = slot_end(ordered_rows[-1].slot) if ordered_rows else None
    for no, block_start in active.items():
        blocks.append((no, block_start, final_end))
    midnight_rest_ends = {no: end for no, start, end in blocks if start == 0 and end is not None}
    overnight_rest_nos = {no for no, _start, end in blocks if end == 24 and no in midnight_rest_ends}
    return [
        (no, start, midnight_rest_ends[no] + 24) if no in overnight_rest_nos and end == 24 else (no, start, end)
        for no, start, end in blocks
        if not (no in overnight_rest_nos and start == 0)
    ]


def external_columns(row: DutyRow) -> dict[str, list[str]]:
    ignore = {"值班", "救護", "備勤", "休息", "檢核欄"}
    return {column: values for column, values in row.columns.items() if column not in ignore}


def has_external_duty(row: DutyRow | None, no: str) -> bool:
    if not row:
        return False
    return any(no in values for values in external_columns(row).values())


def adjacent_rest_start(sheet: DutySheet, no: str, start: int) -> int:
    probe = start - 1
    block_start = start
    while probe >= 0:
        row = row_for_hour(sheet, probe)
        if not row or no not in row.columns.get("休息", []):
            break
        row_start = slot_start(row.slot)
        if row_start is None:
            break
        block_start = row_start
        probe = row_start - 1
    return block_start


def rest_is_external_route(sheet: DutySheet, no: str, start: int, end: int | None) -> bool:
    if start == 8:
        return False
    before = row_for_hour(sheet, start - 1) if start > 0 else None
    after = row_for_hour(sheet, clock_hour(end)) if end is not None and end != 24 else None
    return has_external_duty(before, no) or has_external_duty(after, no)


def rest_checkout_targets(sheet: DutySheet | None, next_sheet: DutySheet | None) -> set[str]:
    if not sheet or not next_sheet:
        return set()
    next_on = set(next_sheet.summary.get("在勤", []))
    targets: set[str] = set()
    for no, start, end in rest_blocks(sheet, next_sheet):
        if start < 8 and no not in next_on and (end is None or end >= 8) and not rest_is_external_route(sheet, no, start, end):
            targets.add(no)
    return targets


def external_duty_blocks(sheet: DutySheet, next_sheet: DutySheet | None = None) -> list[tuple[str, str, int, int | None, int]]:
    blocks: list[tuple[str, str, int, int | None, int]] = []
    active: dict[tuple[str, str], int] = {}
    ordered_rows = sorted(sheet.rows, key=lambda item: slot_start(item.slot) if slot_start(item.slot) is not None else -1)
    for row in ordered_rows:
        start = slot_start(row.slot)
        end = slot_end(row.slot)
        if start is None or end is None:
            continue
        current: set[tuple[str, str]] = set()
        for column, values in external_columns(row).items():
            for no in values:
                current.add((column, no))
                route_start = adjacent_rest_start(sheet, no, start)
                if route_start < 8 <= start:
                    route_start = start
                active.setdefault((column, no), start if route_start == 8 else route_start)
        for key in list(active.keys()):
            if key not in current:
                duty_name, no = key
                if no in row.columns.get("休息", []):
                    continue
                block_start = active.pop(key)
                block_end = start
                if block_end == 8 and next_sheet and no in people_at(next_sheet, 8, duty_name):
                    probe = 8
                    while True:
                        next_row = row_for_hour(next_sheet, probe)
                        if not next_row or no not in next_row.columns.get(duty_name, []):
                            break
                        next_end = slot_end(next_row.slot)
                        if next_end is None or next_end <= probe:
                            break
                        block_end = next_end
                        probe = next_end
                elif block_end == 8 and next_sheet and no not in next_sheet.summary.get("在勤", []):
                    block_end = None
                blocks.append((duty_name, no, block_start, block_end, 0))
        # Extend currently active keys through this row by keeping them in active.
    final_end = slot_end(ordered_rows[-1].slot) if ordered_rows else None
    if final_end is not None:
        for (duty_name, no), start in active.items():
            block_end = final_end
            end_offset = 0
            if final_end == 24 and next_sheet:
                block_end = None
                probe = 0
                while probe < 24:
                    next_row = row_for_hour(next_sheet, probe)
                    if not next_row or no not in next_row.columns.get(duty_name, []):
                        break
                    next_end = slot_end(next_row.slot)
                    if next_end is None or next_end <= probe:
                        break
                    block_end = next_end
                    end_offset = 1
                    probe = next_end
            blocks.append((duty_name, no, start, block_end, end_offset))
    return blocks


def prev_slot_duty(today: DutySheet, yesterday: DutySheet | None, handoff_hour: int) -> list[str]:
    source = yesterday if handoff_hour == 8 and yesterday else today
    fire_hour = 32 if source is yesterday and handoff_hour == 8 else fire_day_hour(handoff_hour)
    segment = duty_segment_before_fire_hour(source, fire_hour)
    if segment:
        return list(segment[2])
    if handoff_hour == 8:
        previous_fire_day = (
            people_at(yesterday, 7, "值班")
            or people_at(yesterday, 6, "值班")
            or people_at(yesterday, 22, "值班")
            if yesterday
            else []
        )
        if previous_fire_day:
            return previous_fire_day
        return people_at(today, handoff_hour - 1, "值班")
    if handoff_hour == 0:
        return people_at(today, 23, "值班") or (people_at(yesterday, 23, "值班") if yesterday else [])
    return people_at(today, handoff_hour - 1, "值班")


def handoff_hours_for_sheet(sheet: DutySheet) -> list[int]:
    dynamic_hours: set[int] = set()
    for row in sheet.rows:
        start = slot_start(row.slot)
        if start is None:
            continue
        if row.columns.get("值班"):
            dynamic_hours.add(start)
    return sorted(dynamic_hours)


def handoff_period(today: DutySheet, yesterday: DutySheet | None, hour: int) -> tuple[int, int]:
    source = yesterday if hour == 8 and yesterday else today
    fire_hour = 32 if source is yesterday and hour == 8 else fire_day_hour(hour)
    segment = duty_segment_before_fire_hour(source, fire_hour)
    if segment:
        return clock_hour(segment[0]), clock_hour(segment[1])
    if hour == 0:
        return 22, 0
    if hour == 8:
        return 22, 8
    previous_row = row_for_hour(today, hour - 1)
    previous_start = slot_start(previous_row.slot) if previous_row else None
    return previous_start if previous_start is not None else hour - 2, hour


def case_counts(cases: list[CaseRecord], start_hour: int, end_hour: int) -> dict[str, int]:
    counts = {"救護": 0, "火警": 0}
    for case in cases:
        if not case.report_time:
            continue
        hour = int(case.report_time.split(":")[0])
        if start_hour <= hour < end_hour:
            if is_fire_case_category(case.category):
                counts["火警"] += 1
            elif "緊急救護" in case.category:
                counts["救護"] += 1
    return counts


def case_counts_overnight(yesterday_cases: list[CaseRecord], today_cases: list[CaseRecord]) -> dict[str, int]:
    counts = {"救護": 0, "火警": 0}
    for partial in (case_counts(yesterday_cases, 22, 24), case_counts(today_cases, 0, 8)):
        counts["救護"] += partial["救護"]
        counts["火警"] += partial["火警"]
    return counts


def name_of(sheet: DutySheet, number: str) -> str:
    return sheet.staff.get(normalize_num(number), {}).get("name", "")


def sheet_has_duty_data(sheet: DutySheet | None) -> bool:
    if not sheet:
        return False
    if any(values for values in sheet.summary.values()):
        return True
    return any(any(values for values in row.columns.values()) for row in sheet.rows)


def officer_for_training(sheet: DutySheet) -> str:
    on_duty = set(sheet.summary.get("在勤", []))
    for no in ("2", "3", "4", "5"):
        if no in on_duty and name_of(sheet, no):
            return f"小隊長{name_of(sheet, no)}"
    if "1" in on_duty and name_of(sheet, "1"):
        return f"分隊長{name_of(sheet, '1')}"
    return "小隊長OOO"


# Work log text templates

def work_handoff_description(settings: dict[str, Any] | None = None, vehicle_out_count: int = 0) -> str:
    settings = settings or load_work_log_defaults()
    important_note = str(settings.get("important_note", "")).strip() or "無。"
    emergency_in_station = max(0, int_setting(settings, "emergency_vehicles_in_station", 6) - vehicle_out_count)
    return "\n".join(
        [
            f"（一）無線電：良好{int_setting(settings, 'radio_count', 34)}支。",
            f"（二）消防及救護車【各式消防救災救護車輛】在隊{emergency_in_station}台、出勤{vehicle_out_count}台、報修{int_setting(settings, 'emergency_vehicles_repair', 0)}台。",
            f"（三）後勤車【機車、幫浦車、指揮車、火場鑑識車】在隊{int_setting(settings, 'support_vehicles_in_station', 5)}台、出勤{int_setting(settings, 'support_vehicles_out', 0)}台、報修{int_setting(settings, 'support_vehicles_repair', 0)}台。",
            f"（四）救災器材裝備【橡皮艇、救生艇】在隊{int_setting(settings, 'rescue_equipment_in_station', 2)}台、出勤{int_setting(settings, 'rescue_equipment_out', 0)}台。",
            f"（五）重要記事：{important_note}",
            f"（六）TIC：隊上{int_setting(settings, 'tic_count', 5)}支。",
        ]
    )


def work_handoff_status(start_hour: int, end_hour: int, counts: dict[str, int]) -> str:
    return work_handoff_status_text(f"{start_hour:02d}-{end_hour:02d}", counts)


def work_handoff_status_text(time_range: str, counts: dict[str, int]) -> str:
    case_parts = []
    if counts["救護"]:
        case_parts.append(f"救護{counts['救護']}件")
    if counts["火警"]:
        case_parts.append(f"火警{counts['火警']}件")
    if case_parts:
        middle = f"二、{'、'.join(case_parts)}"
    else:
        middle = "二、無事故"
    return "\n".join(
        [
            f"一、時間:{time_range}",
            middle,
            "三、無線電車輛交接清楚",
        ]
    )


def radio_test_description() -> str:
    return "11時10分與指揮中心試通無線電基地台訊號良好。"


def radio_test_status() -> str:
    return "\n".join(
        [
            "一、時間 : 11時10分",
            "二、地點 : 新坡分隊",
            "三、內容 : 11時10分與指揮中心試通無線電基地台訊號良好",
        ]
    )


def training_template(topic: str, time_range: str, instructor: str) -> tuple[str, str]:
    description = "\n".join(
        [
            topic,
            f"一、時間：{time_range}",
            "二、地點：分隊駐地",
            f"三、教官：{instructor}",
            f"四、訓練情形：由教官實施{topic}，訓練結果由教官抽測，同仁均熟悉。",
        ]
    )
    status = "訓練結果由教官抽測，同仁均熟悉。"
    if topic == "環境整理":
        description = "\n".join(
            [
                topic,
                f"一、時間：{time_range}",
                "二、地點：分隊駐地",
                f"三、教官：{instructor}",
                "四、訓練情形：由教官分配環境清潔區域，由上班同仁負責打掃整理後，由幹部督導並檢查。",
            ]
        )
        status = "由幹部督導並檢查。"
    elif topic == "車輛駕訓":
        status = "人員均熟悉道路路況及駕駛技能。"
    return description, status


# Actor selection and planned actions

def duty_actor_at(today: DutySheet, yesterday: DutySheet | None, hour: int, minute: int = 0) -> str:
    if hour < 8 and yesterday:
        return (people_at(yesterday, hour, "值班") or [""])[0]
    return (people_at(today, hour, "值班") or [""])[0]


def entry_actor_at(today: DutySheet, yesterday: DutySheet | None, hour: int, minute: int = 0) -> str:
    if minute == 0:
        if hour < 8 and yesterday:
            return (people_at(yesterday, 22, "值班") or people_at(yesterday, hour, "值班") or [""])[0]
        previous = prev_slot_duty(today, yesterday, hour)
        if previous:
            return previous[0]
    return duty_actor_at(today, yesterday, hour, minute)


def next_morning_entry_actor(today: DutySheet, hour: int) -> str:
    return (people_at(today, 22, "值班") or people_at(today, hour, "值班") or [""])[0]


def physical_entry_key(base_date: date, action: PlannedAction) -> tuple[str, date, str, str, str, str] | None:
    if action.kind != "entry_log":
        return None
    fields = action.fields
    return (
        action.kind,
        base_date + timedelta(days=action.date_offset),
        action.time,
        action.target,
        str(fields.get("出或入", "")),
        str(fields.get("領用事由及地點", "")),
    )


def planned_actions(
    today: DutySheet,
    yesterday: DutySheet | None,
    today_cases: list[CaseRecord],
    target: date,
    yesterday_cases: list[CaseRecord] | None = None,
    tomorrow: DutySheet | None = None,
) -> list[PlannedAction]:
    actions: list[PlannedAction] = []
    yesterday_cases = yesterday_cases or []
    work_log_defaults = load_work_log_defaults()

    # 08 boundary, including rest-start exceptions.
    today_on = set(today.summary.get("在勤", []))
    yesterday_on = set(yesterday.summary.get("在勤", [])) if yesterday else set()
    tomorrow_on = set(tomorrow.summary.get("在勤", [])) if tomorrow else set()
    today_rest_start_08 = rest_starting_at(today, 8, tomorrow)
    yesterday_rest_start_06 = rest_starting_at(yesterday, 6, today) if yesterday else {}
    today_rest_checkouts = rest_checkout_targets(today, tomorrow)
    yesterday_rest_checkouts = rest_checkout_targets(yesterday, today)

    for no in sorted(today_on - yesterday_on, key=int):
        if no in today_rest_start_08:
            at = today_rest_start_08[no]
            reason = "到勤"
        else:
            at = 7
            reason = "到勤"
        minute = 0 if no in today_rest_start_08 else 55
        actor = entry_actor_at(today, yesterday, at, minute)
        actions.append(
            PlannedAction(
                kind="entry_log",
                time=f"{at:02d}:{minute:02d}",
                actor=actor,
                target=no,
                fields={
                    "登打時間": f"{at:02d}:{minute:02d}",
                    "系統寫入時間": f"{at:02d}:{minute:02d}",
                    "出或入": "入",
                    "領用事由及地點": reason,
                    "手提無線電編號": handheld_radio(no),
                    "是否歸還": "",
                },
                source="今日在勤且昨日未在勤",
                duplicate_key=f"entry:{target}:{at}{minute:02d}:in:{no}:到勤",
            )
        )

    for no in sorted(yesterday_on - today_on, key=int):
        if yesterday and not needs_next_morning_checkout(yesterday, no):
            continue
        if no in yesterday_rest_start_06:
            at = 6
            minute = 0
            reason = "休息後退勤"
            actor = entry_actor_at(today, yesterday, at, minute)
        elif no in yesterday_rest_checkouts:
            continue
        else:
            at = 8
            minute = 0
            reason = "退勤"
            actor = (people_at(yesterday, 22, "值班") or prev_slot_duty(today, yesterday, 8) or [""])[0]
        actions.append(
            PlannedAction(
                kind="entry_log",
                time=f"{at:02d}:00",
                actor=actor,
                target=no,
                fields={
                    "登打時間": f"{at:02d}:00",
                    "系統寫入時間": f"{at:02d}:{minute + 5:02d}" if reason == "退勤" else f"{at:02d}:{minute:02d}",
                    "出或入": "出",
                    "領用事由及地點": reason,
                    "手提無線電編號": handheld_radio(no),
                    "是否歸還": "是",
                },
                source="昨日在勤且今日未在勤",
                duplicate_key=f"entry:{target}:{at}{(minute + 5) if reason == '退勤' else minute:02d}:out:{no}:{reason}",
            )
        )

    for no, start, end in rest_blocks(today, tomorrow):
        if no not in today_on or (start == 8 and no not in yesterday_on):
            continue
        if rest_is_external_route(today, no, start, end):
            continue
        start_offset = 1 if start < 8 else 0
        end_offset = 1 if end is not None and (end <= 8 or end >= 24) else 0
        rest_checkout = start_offset == 1 and tomorrow and no not in tomorrow_on and (end is None or end >= 8)
        start_actor = next_morning_entry_actor(today, start) if start_offset else entry_actor_at(today, yesterday, start, 0)
        start_reason = "休息後退勤" if rest_checkout else "休息"
        actions.append(
            PlannedAction(
                kind="entry_log",
                time=f"{start:02d}:00",
                actor=start_actor,
                target=no,
                fields={
                    "登打時間": f"{start:02d}:00",
                    "系統寫入時間": f"{start:02d}:00",
                    "出或入": "出",
                    "領用事由及地點": start_reason,
                    "手提無線電編號": handheld_radio(no) if rest_checkout else "",
                    "是否歸還": "是" if rest_checkout else "",
                },
                source="休息後退勤" if rest_checkout else "休息簽出",
                duplicate_key=f"entry:{target}:{start}:out:{no}:{start_reason}",
                date_offset=start_offset,
            )
        )
        if rest_checkout:
            continue
        if end is None:
            continue
        end_hour = clock_hour(end)
        end_time = f"{end_hour:02d}:00"
        end_actor = next_morning_entry_actor(today, end_hour) if end_offset else entry_actor_at(today, yesterday, end_hour, 0)
        actions.append(
            PlannedAction(
                kind="entry_log",
                time=end_time,
                actor=end_actor,
                target=no,
                fields={
                    "登打時間": end_time,
                    "系統寫入時間": end_time,
                    "出或入": "入",
                    "領用事由及地點": "休息返隊",
                    "手提無線電編號": "",
                    "是否歸還": "",
                },
                source="休息結束",
                duplicate_key=f"entry:{target}:{end_hour}:in:{no}:休息返隊",
                date_offset=end_offset,
            )
        )

    # External duty sign-out/sign-in. Sign-out at an exact handoff hour is
    # entered by the previous duty desk, same as value handoff records.
    for duty_name, no, start, end, end_offset in external_duty_blocks(today, tomorrow):
        start_offset = 1 if start < 8 else 0
        start_actor = next_morning_entry_actor(today, start) if start_offset else entry_actor_at(today, yesterday, start, 0)
        actions.append(
            PlannedAction(
                kind="entry_log",
                time=f"{start:02d}:00",
                actor=start_actor,
                target=no,
                fields={
                    "登打時間": f"{start:02d}:00",
                    "系統寫入時間": f"{start:02d}:00",
                    "出或入": "出",
                    "領用事由及地點": duty_name,
                    "手提無線電編號": "",
                    "是否歸還": "",
                },
                source="外勤簽出",
                duplicate_key=f"entry:{target}:{start}:out:{no}:{duty_name}",
                date_offset=start_offset,
            )
        )
        if end is None:
            continue
        if end_offset == 0 and end is not None and end <= 8:
            end_offset = 1
        end_actor = next_morning_entry_actor(today, end) if end_offset else duty_actor_at(today, yesterday, max(end - 1, 0), 0)
        actions.append(
            PlannedAction(
                kind="entry_log",
                time=f"{end:02d}:00",
                actor=end_actor,
                target=no,
                fields={
                    "登打時間": f"{end:02d}:00",
                    "系統寫入時間": f"{end:02d}:00",
                    "出或入": "入",
                    "領用事由及地點": "返隊",
                    "手提無線電編號": "",
                    "是否歸還": "",
                },
                source="外勤簽入",
                duplicate_key=f"entry:{target}:{end}:in:{no}:返隊:{duty_name}",
                date_offset=end_offset,
            )
        )

    # Duty handoff entry log and work log.
    for hour in handoff_hours_for_sheet(today):
        outgoing = prev_slot_duty(today, yesterday, hour)
        incoming = people_at(today, hour, "值班")
        suppressed_outgoing = yesterday_rest_checkouts if hour == 8 else set()
        outgoing_entries = [no for no in outgoing if no not in set(incoming) and no not in suppressed_outgoing]
        incoming_entries = [no for no in incoming if no not in set(outgoing)]
        if not outgoing_entries and not incoming_entries:
            continue
        actor = outgoing[0] if outgoing else duty_actor_at(today, yesterday, hour)
        start_hour, end_hour = handoff_period(today, yesterday, hour)
        time_range = f"{start_hour:02d}-{end_hour:02d}"
        if hour == 8 and start_hour > end_hour:
            counts = case_counts_overnight(yesterday_cases, today_cases)
            vehicle_items = unreturned_case_vehicle_items(yesterday_cases, work_log_defaults, roc_date(target - timedelta(days=1)))
            vehicle_items.extend(unreturned_case_vehicle_items(today_cases, work_log_defaults, roc_date(target), before_hour=8))
        else:
            counts = case_counts(today_cases, start_hour, end_hour) if start_hour < end_hour else {"救護": 0, "火警": 0}
            vehicle_items = unreturned_case_vehicle_items(today_cases, work_log_defaults, roc_date(target), before_hour=hour)
        vehicle_out_count = sum(int(item.get("count", 0)) for item in vehicle_items)
        for no in outgoing_entries:
            actions.append(
                PlannedAction(
                    kind="entry_log",
                    time=f"{hour:02d}:00",
                    actor=actor,
                    target=no,
                    fields={
                        "登打時間": f"{hour:02d}:00",
                        "系統寫入時間": f"{hour:02d}:00",
                        "勤務項目": "值班(宿)",
                        "出或入": "值退",
                        "領用事由及地點": "值退",
                        "手提無線電編號": "",
                        "是否歸還": "",
                    },
                    source="值班交接",
                    duplicate_key=f"entry:{target}:{hour}:值退:{no}",
                )
            )
        for no in incoming_entries:
            actions.append(
                PlannedAction(
                    kind="entry_log",
                    time=f"{hour:02d}:00",
                    actor=actor,
                    target=no,
                    fields={
                        "登打時間": f"{hour:02d}:00",
                        "系統寫入時間": f"{hour:02d}:00",
                        "勤務項目": "值班(宿)",
                        "出或入": "值班",
                        "領用事由及地點": "值班",
                        "手提無線電編號": "",
                        "是否歸還": "",
                    },
                    source="值班交接",
                    duplicate_key=f"entry:{target}:{hour}:值班:{no}",
                )
            )
        if actor:
            actions.append(
                PlannedAction(
                    kind="work_log",
                    time=f"{hour:02d}:00",
                    actor=actor,
                    target=actor,
                    fields={
                        "工作時間": f"{hour:02d}:00",
                        "勤務項目": "值班(宿)",
                        "工作概述": work_handoff_description(work_log_defaults, vehicle_out_count),
                        "處理情形": work_handoff_status_text(time_range, counts),
                        "服勤人員": [actor],
                    },
                    source="值班交接",
                    duplicate_key=f"work:{target}:{hour}:值班交接:{actor}",
                )
            )

    if sheet_has_duty_data(tomorrow):
        next_target = target + timedelta(days=1)
        next_morning_sources = {"今日在勤且昨日未在勤", "昨日在勤且今日未在勤", "值班交接"}
        existing_entry_keys = {key for action in actions if (key := physical_entry_key(target, action)) is not None}
        existing_work_keys = {action.duplicate_key for action in actions if action.kind == "work_log" and action.duplicate_key}
        for action in planned_actions(tomorrow, today, [], next_target, today_cases, None):
            if action.source not in next_morning_sources:
                continue
            if action.time not in ("06:00", "07:00", "07:55", "08:00", "08:05"):
                continue
            if action.kind == "entry_log" and action.target in today_rest_checkouts and action.fields.get("出或入") in ("出", "值退"):
                continue
            action.date_offset = 1
            if action.kind == "entry_log":
                entry_key = physical_entry_key(target, action)
                if entry_key is not None and entry_key in existing_entry_keys:
                    continue
                if entry_key is not None:
                    existing_entry_keys.add(entry_key)
            elif action.kind == "work_log" and action.duplicate_key:
                if action.duplicate_key in existing_work_keys:
                    continue
                existing_work_keys.add(action.duplicate_key)
            actions.append(action)

    # Radio test at 11:10, entered by 10-12 duty.
    radio_actor = duty_actor_at(today, yesterday, 11, 10)
    if radio_actor:
        actions.append(
            PlannedAction(
                kind="work_log",
                time="11:10",
                actor=radio_actor,
                target=radio_actor,
                fields={
                    "工作時間": "11:10",
                    "勤務項目": "其他",
                    "工作概述": radio_test_description(),
                    "處理情形": radio_test_status(),
                    "服勤人員": [radio_actor],
                },
                source="無線電試話",
                duplicate_key=f"work:{target}:1110:無線電試話:{radio_actor}",
            )
        )

    # In-station training records.
    topics = TRAINING_BY_WEEKDAY[target.weekday()]
    training_slots = [
        ("12:00", "09-12", 10, topics[0]),
        ("17:00", "14-17", 16, topics[1]),
        ("21:00", "19-21", 20, topics[2]),
    ]
    instructor = officer_for_training(today)
    for work_time, time_range, actor_hour, topic in training_slots:
        actor = duty_actor_at(today, yesterday, actor_hour)
        end_hour = int(work_time[:2])
        probe_hour = end_hour - 1 if end_hour != 12 else 11
        attendees = set(people_at(today, probe_hour, "救護")) | set(people_at(today, probe_hour, "備勤"))
        attendees -= set(people_at(today, probe_hour, "值班"))
        attendees -= set(people_at(today, probe_hour, "休息"))
        for key in today.rows[0].columns.keys() if today.rows else []:
            if key not in ("值班", "救護", "備勤", "休息", "檢核欄") and key:
                attendees -= set(people_at(today, probe_hour, key))
        description, status = training_template(topic, time_range, instructor)
        if actor:
            actions.append(
                PlannedAction(
                    kind="work_log",
                    time=work_time,
                    actor=actor,
                    target=",".join(sorted(attendees, key=int)),
                    fields={
                        "工作時間": work_time,
                        "勤務項目": "在隊訓練",
                        "事由": TRAINING_REASON.get(topic, ""),
                        "訓練項目": topic,
                        "工作概述": description,
                        "處理情形": status,
                        "服勤人員": sorted(attendees, key=int),
                    },
                    source="在隊訓練",
                    duplicate_key=f"work:{target}:{work_time}:在隊訓練:{topic}",
                )
            )

    def entry_priority(action: PlannedAction) -> int:
        if action.kind != "entry_log":
            return 50
        fields = action.fields
        outin = fields.get("出或入", "")
        reason = fields.get("領用事由及地點", "")
        source = action.source
        if source == "外勤簽入" and outin == "入":
            return 0
        if source == "休息結束" and reason == "休息返隊":
            return 1
        if outin == "值退":
            return 2
        if outin == "值班":
            return 3
        if source == "外勤簽出" and outin == "出":
            return 4
        if source == "休息簽出" and reason == "休息":
            return 5
        return 50

    def sort_key(index_and_action: tuple[int, PlannedAction]) -> tuple[int, int, int]:
        index, action = index_and_action
        hour, minute = [int(part) for part in action.time.split(":")]
        return action.date_offset * 1440 + hour * 60 + minute, entry_priority(action), index

    # Keep insertion order inside the same minute after applying the required
    # entry sequence: 外勤入, 休息入, 值退, 值班, 外勤出, 休息出.
    return [action for _, action in sorted(enumerate(actions), key=sort_key)]


# CLI helpers

def print_summary(today: DutySheet, yesterday: DutySheet | None, cases: list[CaseRecord], actions: list[PlannedAction]) -> None:
    print("\n=== 勤務表讀取 ===")
    print(f"今日: {today.roc_date} 單位={today.unit or '(未讀到)'} 在勤={','.join(today.summary.get('在勤', []))}")
    if yesterday:
        print(f"昨日班: {yesterday.roc_date} 在勤={','.join(yesterday.summary.get('在勤', []))}")
    print(f"表格時段數: 今日 {len(today.rows)} / 昨日 {len(yesterday.rows) if yesterday else 0}")

    print("\n=== 案件查詢 ===")
    print(f"讀到案件 {len(cases)} 件")
    for case in cases[:20]:
        print(f"- {case.report_time} {case.return_time} {case.category}")
    if len(cases) > 20:
        print(f"... 還有 {len(cases) - 20} 件")

    print("\n=== 預演計畫 ===")
    for action in actions:
        if action.kind == "entry_log":
            print(
                f"[出入] 登打{action.fields.get('登打時間', action.time)} "
                f"系統{action.fields.get('系統寫入時間', action.time)} "
                f"登打人={action.actor} 對象={action.target} "
                f"{action.fields.get('出或入')} / {action.fields.get('領用事由及地點')} "
                f"無線電={action.fields.get('手提無線電編號') or '-'} "
                f"歸還={action.fields.get('是否歸還') or '-'} ({action.source})"
            )
        else:
            people = action.fields.get("服勤人員", [])
            print(
                f"[工作] {action.time} 登打={action.actor} 項目={action.fields.get('勤務項目')} "
                f"事由={action.fields.get('事由', '-')} 服勤={','.join(people) if people else '-'} ({action.source})"
            )


_DUTY_BROWSER_PROFILE_PREFIX = "duty_gui_"
_DUTY_BROWSER_PROFILE_ATTRIBUTE = "_sinposmart_duty_browser_profile"
_DUTY_BROWSER_DIAGNOSTIC_RELATIVE_PATH = Path("runtime_outputs") / "browser" / "browser_startup.jsonl"
_DUTY_BROWSER_STARTUP_MESSAGE = (
    "SinpoSmart 專用瀏覽器啟動失敗，已自動清理暫存資料並重試。"
    "一般 Chrome 不需關閉；若仍失敗請匯出問題包。"
)


class DutyBrowserStartupError(WebDriverException):
    """Safe browser-start failure that carries no profile or credential details."""

    def __init__(self, *, category: str, attempts: int, profiles_pruned: int) -> None:
        super().__init__(_DUTY_BROWSER_STARTUP_MESSAGE)
        self.diagnostic_category = category
        self.attempts = attempts
        self.profiles_pruned = profiles_pruned


def duty_browser_profile_root() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "SinpoSmart" / "duty_browser_profiles"
    root.mkdir(parents=True, exist_ok=True)
    return root


def duty_browser_profile_dir() -> Path:
    profile_dir = duty_browser_profile_root() / f"{_DUTY_BROWSER_PROFILE_PREFIX}{uuid4().hex}"
    profile_dir.mkdir()
    return profile_dir


def _is_owned_duty_browser_profile(profile_dir: Path, *, root: Path | None = None) -> bool:
    try:
        profile_root = (Path(root) if root is not None else duty_browser_profile_root()).resolve()
        candidate = Path(profile_dir).resolve()
    except OSError:
        return False
    return candidate.parent == profile_root and candidate.name.startswith(_DUTY_BROWSER_PROFILE_PREFIX)


def _active_duty_browser_profiles(root: Path, candidates: list[Path]) -> set[Path]:
    """Return only owned profiles currently referenced by a Chrome process.

    If Windows process inspection fails, return all candidates so cleanup fails
    closed instead of risking a live browser profile.
    """

    if not candidates:
        return set()
    root_token = base64.b64encode(str(root).encode("utf-8")).decode("ascii")
    script = (
        "$target = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('"
        + root_token
        + "')); Get-CimInstance Win32_Process | Where-Object { $_.Name -ieq 'chrome.exe' -and $_.CommandLine -like \"*$target*\" } | "
        "ForEach-Object { $_.CommandLine }"
    )
    encoded_script = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded_script],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return set(candidates)
    if result.returncode:
        return set(candidates)
    command_lines = str(result.stdout or "").casefold()
    return {candidate for candidate in candidates if str(candidate).casefold() in command_lines}


def prune_stale_duty_browser_profiles(
    *,
    root: Path | None = None,
    active_profiles: set[Path] | None = None,
    now: float | None = None,
    minimum_age_seconds: int = 600,
    maximum_profiles: int = 12,
) -> int:
    """Bounded cleanup for old private profiles; never touches regular Chrome data."""

    profile_root = Path(root) if root is not None else duty_browser_profile_root()
    if not profile_root.is_dir() or maximum_profiles < 1:
        return 0
    current_time = time.time() if now is None else now
    try:
        candidates = [
            item
            for item in profile_root.iterdir()
            if item.is_dir() and not item.is_symlink() and item.name.startswith(_DUTY_BROWSER_PROFILE_PREFIX)
        ]
    except OSError:
        return 0
    try:
        candidates.sort(key=lambda item: item.stat().st_mtime)
    except OSError:
        return 0
    active = active_profiles if active_profiles is not None else _active_duty_browser_profiles(profile_root, candidates)
    removed = 0
    for profile_dir in candidates:
        if removed >= maximum_profiles or profile_dir in active:
            continue
        try:
            age = current_time - profile_dir.stat().st_mtime
        except OSError:
            continue
        if age < minimum_age_seconds or not _is_owned_duty_browser_profile(profile_dir, root=profile_root):
            continue
        try:
            shutil.rmtree(profile_dir)
        except OSError:
            continue
        removed += 1
    return removed


def _write_duty_browser_startup_diagnostic(
    event: str,
    *,
    category: str,
    attempts: int,
    profiles_pruned: int,
) -> None:
    """Persist a credential-free startup record for the QML issue package."""

    payload = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "event": event,
        "category": category,
        "attempts": attempts,
        "profiles_pruned": profiles_pruned,
    }
    output_path = Path(__file__).resolve().parent / _DUTY_BROWSER_DIAGNOSTIC_RELATIVE_PATH
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        pass


def chrome_start_attempts() -> int:
    try:
        return max(1, min(int(os.environ.get("SELENIUM_CHROME_START_ATTEMPTS", "2")), 3))
    except ValueError:
        return 2


def chrome_start_timeout_seconds() -> float:
    try:
        return max(float(os.environ.get("SELENIUM_CHROME_START_TIMEOUT_SECONDS", "20")), 1)
    except ValueError:
        return 20


def create_webdriver_chrome_with_timeout(options: Options) -> webdriver.Chrome:
    result_queue: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=1)
    timed_out = threading.Event()

    def start() -> None:
        try:
            service = ChromeService(
                popen_kw={"creation_flags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
            )
            driver = webdriver.Chrome(service=service, options=options)
        except BaseException as exc:
            if not timed_out.is_set():
                result_queue.put(("error", exc))
            return
        if timed_out.is_set():
            with suppress(Exception):
                driver.quit()
            return
        result_queue.put(("driver", driver))

    thread = threading.Thread(target=start, name="sinposmart-chrome-startup", daemon=True)
    thread.start()
    thread.join(chrome_start_timeout_seconds())
    if thread.is_alive():
        timed_out.set()
        raise TimeoutError(f"Chrome 啟動逾時，已超過 {chrome_start_timeout_seconds():g} 秒。")
    kind, value = result_queue.get_nowait()
    if kind == "error":
        raise value
    return value


def cleanup_duty_browser_profile(profile_dir: Path, *, terminate_processes: bool = False) -> None:
    """Remove exactly one program-owned profile, optionally ending its Chrome process."""

    if not _is_owned_duty_browser_profile(profile_dir):
        return
    if terminate_processes:
        profile_token = base64.b64encode(str(profile_dir).encode("utf-8")).decode("ascii")
        script = (
            "$target = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('"
            + profile_token
            + "')); Get-CimInstance Win32_Process | Where-Object { $_.Name -ieq 'chrome.exe' -and $_.CommandLine -like \"*$target*\" } | "
            "Sort-Object ProcessId -Descending | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
        )
        encoded_script = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        with suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded_script],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
    with suppress(OSError):
        shutil.rmtree(profile_dir)


def cleanup_duty_browser_startup_failure(profile_dir: Path) -> None:
    cleanup_duty_browser_profile(profile_dir, terminate_processes=True)


def _browser_startup_failure_category(error: BaseException) -> str:
    if isinstance(error, TimeoutError):
        return "startup_timeout"
    if isinstance(error, OSError):
        return "os_startup"
    return "webdriver_startup"


def position_duty_browser_at_top_right(driver: webdriver.Chrome) -> None:
    """Place a visible tool browser at the upper right of the primary display."""

    if os.name != "nt":
        return
    try:
        screen_width = int(ctypes.windll.user32.GetSystemMetrics(0))
        browser_width = int(driver.get_window_size().get("width", 1280))
        driver.set_window_position(max(0, screen_width - browser_width), 0)
    except (AttributeError, OSError, TypeError, ValueError, WebDriverException):
        return


def build_driver(
    headless: bool,
    option_arguments: tuple[str, ...] = (),
    page_load_strategy: str = "",
) -> webdriver.Chrome:
    attempts = chrome_start_attempts()
    profiles_pruned = prune_stale_duty_browser_profiles()
    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        profile_dir = duty_browser_profile_dir()
        options = Options()
        options.add_argument(f"--user-data-dir={profile_dir}")
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--window-size=1280,900")
        for argument in option_arguments:
            options.add_argument(argument)
        if page_load_strategy:
            options.page_load_strategy = page_load_strategy
        try:
            driver = create_webdriver_chrome_with_timeout(options)
        except (OSError, TimeoutError, WebDriverException) as exc:
            last_error = exc
            cleanup_duty_browser_startup_failure(profile_dir)
            if attempt < attempts:
                time.sleep(1)
                continue
            category = _browser_startup_failure_category(exc)
            _write_duty_browser_startup_diagnostic(
                "startup_failed",
                category=category,
                attempts=attempts,
                profiles_pruned=profiles_pruned,
            )
            raise DutyBrowserStartupError(
                category=category,
                attempts=attempts,
                profiles_pruned=profiles_pruned,
            ) from exc
        break
    else:
        category = _browser_startup_failure_category(last_error or WebDriverException())
        _write_duty_browser_startup_diagnostic(
            "startup_failed",
            category=category,
            attempts=attempts,
            profiles_pruned=profiles_pruned,
        )
        raise DutyBrowserStartupError(
            category=category,
            attempts=attempts,
            profiles_pruned=profiles_pruned,
        ) from last_error
    try:
        driver.set_page_load_timeout(max(10, int(os.environ.get("SELENIUM_PAGE_LOAD_TIMEOUT_SECONDS", "45"))))
    except Exception:
        pass
    try:
        driver.set_script_timeout(max(10, int(os.environ.get("SELENIUM_SCRIPT_TIMEOUT_SECONDS", "45"))))
    except Exception:
        pass
    if not headless and not any(argument.startswith("--window-position=") for argument in option_arguments):
        position_duty_browser_at_top_right(driver)
    setattr(driver, _DUTY_BROWSER_PROFILE_ATTRIBUTE, str(profile_dir))
    if profiles_pruned or attempt > 1:
        _write_duty_browser_startup_diagnostic(
            "startup_recovered",
            category="recovered",
            attempts=attempt,
            profiles_pruned=profiles_pruned,
        )
    return driver


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only duty automation rehearsal.")
    parser.add_argument("--date", default=roc_date(datetime.now().date()), help="ROC date, e.g. 1150517")
    parser.add_argument("--headless", action="store_true", help="Run Chrome headless.")
    parser.add_argument("--json-out", default="", help="Optional JSON output path.")
    args = parser.parse_args()

    target_date = parse_roc_date(args.date)
    yesterday_date = target_date - timedelta(days=1)
    tomorrow_date = target_date + timedelta(days=1)
    user_id = os.environ.get("DUTY_USER") or input("勤務管理系統帳號: ").strip()
    password = os.environ.get("DUTY_PASSWORD") or getpass.getpass("勤務管理系統密碼: ")

    driver = build_driver(args.headless)
    try:
        login(driver, user_id, password)
        today_sheet = query_duty_sheet(driver, roc_date(target_date))
        yesterday_sheet = query_duty_sheet(driver, roc_date(yesterday_date))
        tomorrow_sheet = query_duty_sheet(driver, roc_date(tomorrow_date))
        yesterday_cases = query_cases(driver, roc_date(yesterday_date))
        cases = query_cases(driver, roc_date(target_date))

        # Query pages are still useful as a smoke test for duplicate-check plumbing.
        work_rows = query_visible_table(driver, WORK_LOG_AP, roc_date(target_date))
        entry_rows = query_visible_table(driver, ENTRY_LOG_AP, roc_date(target_date))

        actions = planned_actions(today_sheet, yesterday_sheet, cases, target_date, yesterday_cases, tomorrow_sheet)
        print_summary(today_sheet, yesterday_sheet, cases, actions)
        print("\n=== 既有紀錄查詢 smoke test ===")
        print(f"工作紀錄簿可見列數: {len(work_rows)}")
        print(f"出入登記簿可見列數: {len(entry_rows)}")
        print("注意: 目前只做讀取與預演，沒有新增或儲存。")

        if args.json_out:
            payload = {
                "target_date": roc_date(target_date),
                "today": asdict(today_sheet),
                "yesterday": asdict(yesterday_sheet),
                "tomorrow": asdict(tomorrow_sheet),
                "cases": [asdict(c) for c in cases],
                "yesterday_cases": [asdict(c) for c in yesterday_cases],
                "actions": [asdict(a) for a in actions],
                "visible_work_rows": work_rows,
                "visible_entry_rows": entry_rows,
            }
            with open(args.json_out, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            print(f"JSON 輸出: {args.json_out}")
    finally:
        quit_driver(driver)
    return 0


if __name__ == "__main__":
    sys.exit(main())
