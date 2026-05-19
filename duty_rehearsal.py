# -*- coding: utf-8 -*-
"""
Read-only rehearsal for the TYFD duty management automation.

This script logs in, reads the duty table and related query pages, then prints
the actions that would be created. It never clicks save/submit.
"""

from __future__ import annotations


import argparse
import getpass
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


BASE_URL = "https://dutymgt.tyfd.gov.tw/tyfd119"

DUTY_TABLE_AP = "wap119.RPS105020"
ENTRY_LOG_AP = "wap119.RPS04040"
WORK_LOG_AP = "wap119.RPS04060"
CASE_QUERY_AP = "wap119.RPS04061"

HANDOFF_HOURS = [8, 10, 12, 14, 16, 18, 20, 22]
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


@dataclass
class PlannedAction:
    kind: str
    time: str
    actor: str
    target: str
    fields: dict[str, Any]
    source: str
    duplicate_key: str


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


def handheld_radio(number: str) -> str:
    n = int(number)
    if 1 <= n <= 5:
        return f"手{n:02d}、{n:02d}-1"
    return f"手{n:02d}"


def open_ap(driver: webdriver.Chrome, ap_name: str) -> None:
    url = (
        f"{BASE_URL}/ActionControlServlet?id=00&APname={ap_name}"
        f"&pushButton=load&nextAPname={ap_name}&_txtFirstEntry=TRUE"
    )
    driver.get(url)


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


def js_set(driver: webdriver.Chrome, element_id: str, value: str) -> bool:
    return bool(
        driver.execute_script(
            """
            const el = document.getElementById(arguments[0]);
            if (!el) return false;
            el.value = arguments[1];
            el.dispatchEvent(new Event('change', {bubbles: true}));
            return true;
            """,
            element_id,
            value,
        )
    )


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
          function push(id, name) {
            id = String(id || '').trim();
            name = String(name || '').trim();
            if (!id || !name) return;
            const key = id + ':' + name;
            if (seen.has(key)) return;
            seen.add(key);
            people.push({id, name});
          }

          const selMan = document.getElementById('_selMan');
          if (selMan) {
            Array.from(selMan.options || []).forEach(opt => {
              const id = String(opt.value || '').split(',')[0].trim();
              push(id, opt.text);
            });
          }

          const selManData = document.getElementById('_selManData');
          if (selManData) {
            Array.from(selManData.options || []).forEach(opt => {
              const parts = String(opt.value || '').split(',');
              push(parts[1], opt.text);
            });
          }
          return people;
        }

        const available = collectPeople();
        const selected = [];
        const missing = [];
        for (const target of targets) {
          if (target.id && target.name) {
            selected.push(target);
            continue;
          }
          const person = available.find(p =>
            (target.id && p.id === target.id) ||
            (target.name && (p.name === target.name || p.name.includes(target.name) || target.name.includes(p.name)))
          );
          if (person) selected.push(person);
          else missing.push(target.name || target.id);
        }

        if (missing.length === 0 && selected.length > 0) {
          document.getElementById('_hidManId').value = selected.map(p => p.id).join(',');
          document.getElementById('_areMan').value = selected.map(p => p.name).join(',');
          const pcnt = document.getElementById('_txtPcnt');
          if (pcnt) pcnt.value = String(selected.length);
        }

        return {
          ok: missing.length === 0 && selected.length > 0,
          selected,
          missing,
          hidManId: document.getElementById('_hidManId')?.value || '',
          areMan: document.getElementById('_areMan')?.value || '',
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
    js_click(driver, "_btnOpenWin")
    WebDriverWait(driver, 10).until(lambda d: len(set(d.window_handles) - before_handles) == 1)
    popup_window = (set(driver.window_handles) - before_handles).pop()
    driver.switch_to.window(popup_window)
    try:
        result = driver.execute_script(
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
            const checks = Array.from(document.querySelectorAll('input[name="_chkUser"]'));
            const selected = [];
            const missing = [];

            for (const target of targets) {
              const box = checks.find(el => {
                const parts = String(el.value || '').split(',');
                const id = parts[0].trim();
                const personName = parts.slice(1).join(',').trim();
                return (target.id && id === target.id) ||
                       (target.name && (personName === target.name || personName.includes(target.name) || target.name.includes(personName)));
              });
              if (box) {
                box.checked = true;
                selected.push(box.value);
              } else {
                missing.push(target.name || target.id);
              }
            }

            if (missing.length === 0 && selected.length > 0) {
              if (typeof sureOK === 'function') sureOK();
              else document.getElementById('_btnSure').click();
            }
            return {ok: missing.length === 0 && selected.length > 0, selected, missing};
            """,
            people,
        )
    finally:
        if popup_window in driver.window_handles:
            driver.close()
        driver.switch_to.window(main_window)

    time.sleep(1)
    verify = driver.execute_script(
        """
        return {
          hidManId: document.getElementById('_hidManId')?.value || '',
          areMan: document.getElementById('_areMan')?.value || '',
          pcnt: document.getElementById('_txtPcnt')?.value || ''
        };
        """
    )
    result.update(verify)
    result["ok"] = bool(result.get("ok") and verify.get("hidManId") and verify.get("areMan"))
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
    return set_form_people(driver, names, fallback_popup)


def set_work_people(driver: webdriver.Chrome, people: list[Any], fallback_popup: bool = True) -> dict[str, Any]:
    return set_form_people(driver, people, fallback_popup)


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

    open_ap(driver, WORK_LOG_AP)
    time.sleep(1)
    before_controls = control_snapshot(driver)
    insert_result = click_insert_control(driver)
    time.sleep(2)

    fill_result = driver.execute_script(
        """
        const values = arguments[0];
        const result = {set: [], missing: []};

        function visibleControls() {
          return Array.from(document.querySelectorAll('input, select, textarea'));
        }
        function setControl(el, value) {
          if (!el) return false;
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
        function byOptionText(value) {
          const el = visibleControls().find(control =>
            control.tagName.toLowerCase() === 'select' &&
            Array.from(control.options || []).some(opt => String(opt.text || '').includes(value))
          );
          return setControl(el, value);
        }
        function byNearbyText(label, value, preferTextarea = false) {
          const labels = Array.from(document.querySelectorAll('td, th, label, span, div'));
          const node = labels.find(el => String(el.innerText || '').replace(/\\s+/g, '').includes(label));
          if (!node) return false;
          let cursor = node;
          for (let depth = 0; depth < 4 && cursor; depth += 1, cursor = cursor.parentElement) {
            const controls = Array.from(cursor.querySelectorAll('input, select, textarea'));
            const candidates = preferTextarea ? controls.filter(el => el.tagName.toLowerCase() === 'textarea') : controls;
            for (const control of candidates) {
              if (setControl(control, value)) return true;
            }
          }
          return false;
        }

        if (!byIds(['_txtDate', '_txtTaskDate', '_txtSDATE', '_txtSdate'], values.date)) result.missing.push('date');
        if (!byIds(['_selSTIMEH', '_selTimeH', '_selHH', '_selHOUR'], values.hour)) result.missing.push('hour');
        if (!byIds(['_selSTIMEM', '_selTimeM', '_selMM', '_selMIN'], values.minute)) result.missing.push('minute');
        if (!byIds(['_selETIMEH', '_selETimeH'], values.hour)) result.missing.push('end_hour');
        if (!byIds(['_selETIMEM', '_selETimeM'], values.minute)) result.missing.push('end_minute');
        if (!byOptionText(values.item)) result.missing.push('item');
        if (values.reason && !byNearbyText('事由', values.reason)) result.missing.push('reason');
        if (!byNearbyText('工作概述', values.description, true)) result.missing.push('description');
        if (!byNearbyText('處理情形', values.status, true)) result.missing.push('status');
        return result;
        """,
        {
            "date": target_roc_date,
            "hour": hour,
            "minute": minute,
            "item": fields.get("勤務項目", ""),
            "reason": fields.get("事由", ""),
            "description": fields.get("工作概述", ""),
            "status": fields.get("處理情形", ""),
        },
    )

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
    time.sleep(5)
    # The legacy app can keep login119 in the address bar after posting. The
    # real proof is whether authenticated AP pages load, so callers verify that.


def query_duty_sheet(driver: webdriver.Chrome, target_roc_date: str) -> DutySheet:
    open_ap(driver, DUTY_TABLE_AP)
    time.sleep(1)
    js_set(driver, "_txtTaskDate", target_roc_date)
    if not js_click(driver, "_btnQuery"):
        js_click(driver, "_btnSearch")
    time.sleep(1.5)
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
        const result = {unit: '', rows: [], summary: {}, staff: {}};
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
    sheet = DutySheet(
        roc_date=target_roc_date,
        unit=data.get("unit", ""),
        rows=[
            DutyRow(
                slot=row["slot"],
                columns={key: nums(value) for key, value in row["columns"].items()},
            )
            for row in data.get("rows", [])
        ],
        summary={key: roster_nums(value) for key, value in data.get("summary", {}).items()},
        staff=data.get("staff", {}),
    )
    return sheet


def query_visible_table(driver: webdriver.Chrome, ap_name: str, target_roc_date: str) -> list[list[str]]:
    open_ap(driver, ap_name)
    time.sleep(1)
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
    js_set(driver, "_txtPageNum", "100")
    for button_id in ("_btnQuery", "_btnSearch"):
        if js_click(driver, button_id):
            break
    time.sleep(1.5)
    return driver.execute_script(
        """
        return Array.from(document.querySelectorAll('table')).flatMap(table =>
          Array.from(table.querySelectorAll('tr')).map(tr =>
            Array.from(tr.children).map(td => (td.innerText || td.value || '').trim()).filter(Boolean)
          ).filter(row => row.length)
        );
        """
    )


def query_cases(driver: webdriver.Chrome, target_roc_date: str) -> list[CaseRecord]:
    open_ap(driver, CASE_QUERY_AP)
    time.sleep(1)
    js_set(driver, "_hidDeptno", "033006")
    js_set(driver, "_txtSDATE", target_roc_date)
    js_set(driver, "_txtEDATE", target_roc_date)
    js_set(driver, "_selSTIMEH", "00")
    js_set(driver, "_selSTIMEM", "00")
    js_set(driver, "_selETIMEH", "23")
    js_set(driver, "_selETIMEM", "59")
    js_click(driver, "_btnQuery")
    time.sleep(1.5)
    rows = driver.execute_script(
        """
        return Array.from(document.querySelectorAll('tr')).map(tr =>
          Array.from(tr.children).map(td => (td.innerText || '').trim()).filter(Boolean)
        ).filter(row => row.length >= 3);
        """
    )
    cases: list[CaseRecord] = []
    for row in rows:
        joined = " ".join(row)
        if not re.search(r"\d{1,2}:\d{2}:\d{2}", joined):
            continue
        times = re.findall(r"\d{1,2}:\d{2}:\d{2}", joined)
        category = ""
        for cell in row:
            if "緊急救護" in cell or "火警" in cell:
                category = cell
                break
        cases.append(
            CaseRecord(
                report_time=times[0] if times else "",
                return_time=times[-1] if len(times) > 1 else "",
                category=category,
                raw=row,
            )
        )
    return cases


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


def rest_starting_at(sheet: DutySheet, hour: int, next_sheet: DutySheet | None = None) -> dict[str, int]:
    starts: dict[str, int] = {}
    ordered_rows = sorted(sheet.rows, key=lambda item: slot_start(item.slot) if slot_start(item.slot) is not None else -1)
    for row in ordered_rows:
        start = slot_start(row.slot)
        end = slot_end(row.slot)
        if start == hour and end is not None:
            for no in row.columns.get("休息", []):
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


def external_duty_blocks(sheet: DutySheet, next_sheet: DutySheet | None = None) -> list[tuple[str, str, int, int | None]]:
    blocks: list[tuple[str, str, int, int | None]] = []
    ignore = {"值班", "救護", "備勤", "休息", "檢核欄"}
    active: dict[tuple[str, str], int] = {}
    ordered_rows = sorted(sheet.rows, key=lambda item: slot_start(item.slot) if slot_start(item.slot) is not None else -1)
    for row in ordered_rows:
        start = slot_start(row.slot)
        end = slot_end(row.slot)
        if start is None or end is None:
            continue
        current: set[tuple[str, str]] = set()
        for column, values in row.columns.items():
            if column in ignore:
                continue
            for no in values:
                current.add((column, no))
                active.setdefault((column, no), start)
        for key in list(active.keys()):
            if key not in current:
                duty_name, no = key
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
                blocks.append((duty_name, no, block_start, block_end))
        # Extend currently active keys through this row by keeping them in active.
    final_end = slot_end(ordered_rows[-1].slot) if ordered_rows else None
    if final_end is not None:
        for (duty_name, no), start in active.items():
            blocks.append((duty_name, no, start, final_end))
    return blocks


def prev_slot_duty(today: DutySheet, yesterday: DutySheet | None, handoff_hour: int) -> list[str]:
    if handoff_hour == 8:
        return people_at(yesterday, 6, "值班") if yesterday else []
    return people_at(today, handoff_hour - 2, "值班")


def case_counts(cases: list[CaseRecord], start_hour: int, end_hour: int) -> dict[str, int]:
    counts = {"救護": 0, "火警": 0}
    for case in cases:
        if not case.report_time:
            continue
        hour = int(case.report_time.split(":")[0])
        if start_hour <= hour < end_hour:
            if "火警" in case.category:
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


def officer_for_training(sheet: DutySheet) -> str:
    on_duty = set(sheet.summary.get("在勤", []))
    for no in ("2", "3", "4", "5"):
        if no in on_duty and name_of(sheet, no):
            return f"小隊長{name_of(sheet, no)}"
    if "1" in on_duty and name_of(sheet, "1"):
        return f"分隊長{name_of(sheet, '1')}"
    return "小隊長OOO"


def work_handoff_description() -> str:
    return "\n".join(
        [
            "（一）無線電：良好34支。",
            "（二）消防及救護車【各式消防救災救護車輛】在隊5台、出勤0台、報修1台。",
            "（三）後勤車【機車、幫浦車、指揮車、火場鑑識車】在隊5台、出勤0台、報修0台。",
            "（四）救災器材裝備【橡皮艇、救生艇】在隊2台、出勤0台。",
            "（五）重要記事：（比如○○車輛或橡皮艇報修、防颱應變中心成立等事項）。",
            "（六）TIC：隊上5支。",
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

    # 08 boundary, including rest-start exceptions.
    today_on = set(today.summary.get("在勤", []))
    yesterday_on = set(yesterday.summary.get("在勤", [])) if yesterday else set()
    today_rest_start_08 = rest_starting_at(today, 8, tomorrow)
    yesterday_rest_start_06 = rest_starting_at(yesterday, 6, today) if yesterday else {}

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
        if no in yesterday_rest_start_06:
            at = 6
            minute = 0
            reason = "休息後退勤"
        else:
            at = 8
            minute = 5
            reason = "退勤"
        actor = entry_actor_at(today, yesterday, 8 if reason == "退勤" else at, 0 if reason == "退勤" else minute)
        actions.append(
            PlannedAction(
                kind="entry_log",
                time=f"{at:02d}:{minute:02d}",
                actor=actor,
                target=no,
                fields={
                    "登打時間": "08:00" if reason == "退勤" else f"{at:02d}:{minute:02d}",
                    "系統寫入時間": f"{at:02d}:{minute:02d}",
                    "出或入": "出",
                    "領用事由及地點": reason,
                    "手提無線電編號": handheld_radio(no),
                    "是否歸還": "是",
                },
                source="昨日在勤且今日未在勤",
                duplicate_key=f"entry:{target}:{at}{minute:02d}:out:{no}:{reason}",
            )
        )

    for no, end in sorted(today_rest_start_08.items(), key=lambda item: int(item[0])):
        if no in today_on and no in yesterday_on:
            actions.append(
                PlannedAction(
                    kind="entry_log",
                    time="08:00",
                    actor=entry_actor_at(today, yesterday, 8, 0),
                    target=no,
                    fields={
                        "登打時間": "08:00",
                        "系統寫入時間": "08:00",
                        "出或入": "出",
                        "領用事由及地點": "休息",
                        "手提無線電編號": "",
                        "是否歸還": "",
                    },
                    source="昨日與今日皆在勤且今日08起休息",
                    duplicate_key=f"entry:{target}:8:out:{no}:休息",
                )
            )
            actions.append(
                PlannedAction(
                    kind="entry_log",
                    time=f"{end:02d}:00",
                    actor=entry_actor_at(today, yesterday, end, 0),
                    target=no,
                    fields={
                        "登打時間": f"{end:02d}:00",
                        "系統寫入時間": f"{end:02d}:00",
                        "出或入": "入",
                        "領用事由及地點": "返隊",
                        "手提無線電編號": "",
                        "是否歸還": "",
                    },
                    source="今日08起休息結束",
                    duplicate_key=f"entry:{target}:{end}:in:{no}:返隊",
                )
            )

    # External duty sign-out/sign-in. Sign-out is entered by the previous duty
    # desk; sign-in is entered by the duty desk covering the external duty end.
    for duty_name, no, start, end in external_duty_blocks(today, tomorrow):
        actions.append(
            PlannedAction(
                kind="entry_log",
                time=f"{start:02d}:00",
                actor=entry_actor_at(today, yesterday, start, 0),
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
            )
        )
        if end is None:
            continue
        actions.append(
            PlannedAction(
                kind="entry_log",
                time=f"{end:02d}:00",
                actor=duty_actor_at(today, yesterday, max(end - 1, 0), 0),
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
            )
        )

    # Duty handoff entry log and work log.
    for hour in HANDOFF_HOURS:
        outgoing = prev_slot_duty(today, yesterday, hour)
        incoming = people_at(today, hour, "值班")
        actor = outgoing[0] if outgoing else duty_actor_at(today, yesterday, hour)
        if hour == 8:
            time_range = "22-08"
            counts = case_counts_overnight(yesterday_cases, today_cases)
        else:
            start_hour = hour - 2
            time_range = f"{start_hour:02d}-{hour:02d}"
            counts = case_counts(today_cases, start_hour, hour)
        for no in outgoing:
            actions.append(
                PlannedAction(
                    kind="entry_log",
                    time=f"{hour:02d}:00",
                    actor=actor,
                    target=no,
                    fields={
                        "登打時間": f"{hour:02d}:00",
                        "系統寫入時間": f"{hour:02d}:00",
                        "出或入": "值退",
                        "領用事由及地點": "值退",
                        "手提無線電編號": "",
                        "是否歸還": "",
                    },
                    source="值班交接",
                    duplicate_key=f"entry:{target}:{hour}:值退:{no}",
                )
            )
        for no in incoming:
            actions.append(
                PlannedAction(
                    kind="entry_log",
                    time=f"{hour:02d}:00",
                    actor=actor,
                    target=no,
                    fields={
                        "登打時間": f"{hour:02d}:00",
                        "系統寫入時間": f"{hour:02d}:00",
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
                        "工作概述": work_handoff_description(),
                        "處理情形": work_handoff_status_text(time_range, counts),
                        "服勤人員": [actor],
                    },
                    source="值班交接",
                    duplicate_key=f"work:{target}:{hour}:值班交接:{actor}",
                )
            )

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
                source="無線電測試",
                duplicate_key=f"work:{target}:1110:無線電測試:{radio_actor}",
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

    def sort_key(index_and_action: tuple[int, PlannedAction]) -> tuple[int, int]:
        index, action = index_and_action
        hour, minute = [int(part) for part in action.time.split(":")]
        return hour * 60 + minute, index

    # Keep insertion order inside the same minute. This matters for handoff:
    # the outgoing "值退" row must be planned before the incoming "值班" row.
    return [action for _, action in sorted(enumerate(actions), key=sort_key)]


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


def build_driver(headless: bool) -> webdriver.Chrome:
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--window-size=1280,900")
    return webdriver.Chrome(options=options)


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
        driver.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
