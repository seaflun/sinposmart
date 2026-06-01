import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from tkcalendar import DateEntry
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import openpyxl
import re
import warnings
import json
import os
import tempfile
from datetime import datetime, timedelta
from urllib.parse import quote
from selenium.common.exceptions import UnexpectedAlertPresentException
import threading
from pathlib import Path
from openpyxl.utils import get_column_letter
from copy import copy

# ==========================================
# [區塊一] 模組導入與全域設定 (Imports & Config)
# ==========================================

# 隱藏 Excel 格式警告，保持黑視窗乾淨
warnings.filterwarnings("ignore", category=UserWarning)

# 全域狀態更新函數 (確保執行緒安全)
def log_status(msg):
    try:
        print(msg)
    except Exception:
        pass
    # 確保在有視窗的狀態下，將文字更新回 GUI 的狀態列
    if 'root' in globals() and 'status_var' in globals():
        root.after(0, lambda: sync_status_to_gui(msg))

def clean_status_message(msg):
    text = str(msg).strip()
    return re.sub(r'^(?:[➡⏳📂✅⚠❌🧠🖼☁🎉️]\s*)+', '', text).strip()

def sync_status_to_gui(msg):
    status_var.set(f"狀態: {clean_status_message(msg)}")
    if 'log_text' in globals():
        log_text.insert(tk.END, f"{msg}\n")
        log_text.see(tk.END)
# ==========================================
# [區塊二] 設定、日期、Excel 截圖與通知工具 (Config, Excel, Notification)
# 放置不直接操作勤務網站的共用工具；網站 Selenium 動作集中在區塊四、五。
# ==========================================
CONFIG_FILE = "config.json"
DEFAULT_CAPTURE_TOP_ROW = 3
DEFAULT_CAPTURE_BOTTOM_ROW = 36
DAILY_SCREENSHOT_DIR = "每日勤務表"
NIGHT_SCREENSHOT_DIR = "夜間勤務"

# 2-1. 設定檔讀寫
def get_default_config():
    return {
        "login": {
            "user_id": "tyfd01510",
            "user_pwd": "alan810730@Aggggg"
        },
        "last_selection": {
            "attack": "新坡15/KES-5922",
            "stop": "新坡11/KEC-2608",
            "amb1": "新坡91/BGV-2310",
            "amb2": "新坡93/BSL-9230"
        },
        "car_options": {
            "attack": ["新坡15/KES-5922", "新坡16/981-S5"],
            "stop": ["新坡11/KEC-2608"],
            "amb": ["新坡91/BGV-2310", "新坡92/BXB-7593", "新坡93/BSL-9230"]
        },
        "notification": {
            "enabled": True,
            "provider": "line",
            "line_channel_access_token": "5nA7PYBlQ+qzF+gPXXRqhn7bRaSuaqOFBakk2/ODCgw3p7K6JIf2jHSfuYqFvhC8LAXWQQeHM1SM4O774xdTPi0ibcT6gSYDbmyzmppHAvt0TP4fdmJTq/ZS1fO3iIcYQ1O0TunlRV+8l7Xrz4DSBwdB04t89/1O/w1cDnyilFU=",
            "line_to_id": "Uf2573574f8594fea56067df935a2542d",
            "line_group_id": "Uf2573574f8594fea56067df935a2542d",
            "gcs_bucket_name": "sinpo-duty-schedule-images",
            "gcs_service_account_json": "effortless-leaf-353501-63492cc3ece4.json"
        }
    }

def merge_config(defaults, loaded):
    for key, value in defaults.items():
        if key not in loaded:
            loaded[key] = value
        elif isinstance(value, dict) and isinstance(loaded[key], dict):
            loaded[key] = merge_config(value, loaded[key])
    return loaded

def resolve_config_path(path_value):
    if not path_value:
        return ""
    path_text = str(path_value).strip()
    path_obj = Path(path_text)
    if path_obj.is_absolute():
        return str(path_obj)
    return str((Path.cwd() / path_obj).resolve())

def screenshot_archive_root():
    script_dir = Path(__file__).resolve().parent
    if script_dir.name == "duty_sheet_legacy":
        return script_dir.parent
    return script_dir

def screenshot_date_name(target_date):
    digits = re.sub(r"\D", "", str(target_date or ""))
    if len(digits) >= 4:
        return digits[-4:]
    return datetime.now().strftime("%m%d")

def screenshot_archive_path(folder_name, target_date):
    output_dir = screenshot_archive_root() / folder_name
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"{screenshot_date_name(target_date)}.png"

def load_config():
    """載入設定檔，若不存在則給予預設值"""
    default_config = get_default_config()
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return merge_config(default_config, json.load(f))
    return default_config

def save_config(selection, login_settings=None, notification_settings=None):
    """儲存本次選擇、登入資訊與通知設定到設定檔"""
    config = load_config()
    if login_settings is None:
        login_settings = config.get("login", get_default_config()["login"])
    config["login"] = login_settings
    config["last_selection"] = selection
    if notification_settings is None:
        notification_settings = config.get("notification", get_default_config()["notification"])
    config["notification"] = notification_settings
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)


# 2-2. 日期、文字與 Excel 儲存格工具
def convert_to_minguo(date_obj):
    """西元轉民國格式 (例: 1150426)"""
    return f"{date_obj.year - 1911}{date_obj.strftime('%m%d')}"

def clean_v(v):
    """徹底清理番號：移除中文(全員)、0、標點符號，只留數字與逗號"""
    if v is None: return ""
    v_str = str(v).strip().replace(".0", "")
    v_str = re.sub(r'[，、。\.\n\r\s]+', ',', v_str)
    v_str = re.sub(r'[^0-9,]', '', v_str) 
    v_str = re.sub(r',+', ',', v_str).strip(',')
    return v_str if v_str not in ["0", "0.0", "nan", ""] else ""

def clean_to_list(v):
    """將清理後的番號字串轉為 List"""
    res = clean_v(v)
    return [x for x in res.split(',') if x] if res else []

def get_merged_val(sheet, row, col):
    """處理 Excel 合併儲存格讀取"""
    cell = sheet.cell(row=row, column=col)
    for merged_range in sheet.merged_cells.ranges:
        if cell.coordinate in merged_range:
            return sheet.cell(row=merged_range.min_row, column=merged_range.min_col).value
    return cell.value

def get_sheet_name_from_target_date(target_date):
    return f"{int(target_date[-2:])}號"

def sanitize_filename(name):
    return re.sub(r'[\\\\/:*?"<>|]+', "_", name)

def normalize_sheet_name(sheet_name, available_sheet_names):
    target_name = str(sheet_name).strip()
    if target_name in available_sheet_names:
        return target_name

    target_day_match = re.search(r"(\d+)", target_name)
    if target_day_match:
        target_day = int(target_day_match.group(1))
        for candidate in available_sheet_names:
            candidate_match = re.match(r"^\s*(\d+)", str(candidate).strip())
            if candidate_match and int(candidate_match.group(1)) == target_day:
                return candidate

    raise KeyError(f"Worksheet {sheet_name} does not exist.")

def resolve_capture_range(sheet):
    """以主表上方那列的大型合併儲存格決定左右邊界。"""
    merged_candidates = []
    for merged_range in sheet.merged_cells.ranges:
        min_col, min_row, max_col, max_row = merged_range.bounds
        if min_row != 3 or max_row != 3:
            continue
        merged_candidates.append((max_col - min_col, min_col, max_col))

    if not merged_candidates:
        return f"B{DEFAULT_CAPTURE_TOP_ROW}:AM{DEFAULT_CAPTURE_BOTTOM_ROW}"

    _, min_col, max_col = max(merged_candidates, key=lambda item: item[0])
    return (
        f"{get_column_letter(min_col)}{DEFAULT_CAPTURE_TOP_ROW}:"
        f"{get_column_letter(max_col)}{DEFAULT_CAPTURE_BOTTOM_ROW}"
    )

def resolve_night_capture_range(sheet):
    """夜間勤務截圖固定列 24-33，右界取第 6 列第一個含指揮官的欄位。"""
    end_col = 31  # AE
    for col in range(2, sheet.max_column + 1):
        cell_value = sheet.cell(row=6, column=col).value
        if cell_value is None:
            continue
        if "指揮官" in str(cell_value).strip():
            end_col = col
            break
    return f"B24:{get_column_letter(end_col)}33"

# 2-3. Excel 截圖輸出
def export_excel_sheet_to_image(excel_path, sheet_name, capture_range=None, output_path=None):
    """使用本機 Excel 將指定工作表輸出為 PNG，並回傳實際擷取範圍。"""
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        raise RuntimeError("Excel 截圖功能需要安裝 pywin32") from exc

    if output_path is None:
        output_dir = Path.cwd() / "screenshots"
        output_dir.mkdir(exist_ok=True)
        output_path = output_dir / f"{sanitize_filename(sheet_name)}_{datetime.now():%Y%m%d_%H%M%S}.png"
    else:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    pythoncom.CoInitialize()
    excel = None
    workbook = None
    chart_object = None

    try:
        excel = win32com.client.DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False

        wb_meta = openpyxl.load_workbook(excel_path, read_only=False, keep_vba=False, data_only=False)
        wb_values = openpyxl.load_workbook(excel_path, read_only=False, keep_vba=False, data_only=True)
        try:
            resolved_sheet_name = normalize_sheet_name(sheet_name, wb_meta.sheetnames)
            sheet_meta = wb_meta[resolved_sheet_name]
            sheet_values = wb_values[normalize_sheet_name(sheet_name, wb_values.sheetnames)]
            worksheet_index = wb_meta.sheetnames.index(resolved_sheet_name) + 1
            if not capture_range:
                capture_range = resolve_capture_range(sheet_meta)

            workbook = excel.Workbooks.Open(os.path.abspath(excel_path), ReadOnly=False)
            worksheet = workbook.Worksheets(worksheet_index)

            min_col, min_row, max_col, max_row = openpyxl.utils.range_boundaries(capture_range)
            value_matrix = []
            for row in range(min_row, max_row + 1):
                row_values = []
                for col in range(min_col, max_col + 1):
                    row_values.append(sheet_values.cell(row=row, column=col).value)
                value_matrix.append(tuple(row_values))
            worksheet.Range(capture_range).Value = tuple(value_matrix)

            on_duty_ids = set()
            for row in range(9, 37):
                duty_id = sheet_values.cell(row=row, column=41).value  # AO
                duty_status = sheet_values.cell(row=row, column=43).value  # AQ
                if duty_id and duty_status in ("上班", "外宿"):
                    try:
                        on_duty_ids.add(int(duty_id))
                    except (TypeError, ValueError):
                        pass

            gray_color = 0xA5A5A5
            for row in range(8, 22):
                for id_col, name_col in ((36, 37), (38, 39)):  # AJ/AK, AL/AM
                    cell_value = sheet_values.cell(row=row, column=id_col).value
                    id_cell = worksheet.Cells(row, id_col)
                    name_cell = worksheet.Cells(row, name_col)
                    id_cell.Interior.Pattern = 0
                    name_cell.Interior.Pattern = 0
                    if cell_value is None:
                        continue
                    try:
                        duty_id = int(cell_value)
                    except (TypeError, ValueError):
                        continue
                    if duty_id in on_duty_ids:
                        id_cell.Interior.Pattern = 1
                        id_cell.Interior.Color = gray_color
        finally:
            wb_meta.close()
            wb_values.close()
        export_range = worksheet.Range(capture_range)
        worksheet.Activate()
        excel.ActiveWindow.DisplayGridlines = False
        excel.ActiveWindow.Zoom = 90
        export_range.Select()
        time.sleep(1)

        export_range.CopyPicture(Appearance=1, Format=2)
        chart_object = worksheet.ChartObjects().Add(
            export_range.Left,
            export_range.Top,
            export_range.Width,
            export_range.Height
        )
        chart = chart_object.Chart
        chart.Paste()
        time.sleep(1)

        if not chart.Export(str(output_path)):
            raise RuntimeError("Excel 工作表匯出圖片失敗")

        return str(output_path), export_range.Address
    finally:
        if chart_object is not None:
            try:
                chart_object.Delete()
            except Exception:
                pass
        if workbook is not None:
            workbook.Close(False)
        if excel is not None:
            excel.Quit()
        pythoncom.CoUninitialize()

# 2-4. GCS 上傳與 LINE 群組通知
def upload_image_to_gcs(image_path, target_date, notification_config):
    try:
        from google.cloud import storage
    except ImportError as exc:
        raise RuntimeError("Google Cloud Storage 上傳功能需要安裝 google-cloud-storage") from exc

    service_account_json = resolve_config_path(notification_config.get("gcs_service_account_json", ""))
    bucket_name = notification_config.get("gcs_bucket_name", "").strip()
    if not service_account_json or not os.path.exists(service_account_json):
        raise ValueError("GCS Service Account JSON 檔案不存在")
    if not bucket_name:
        raise ValueError("GCS Bucket 名稱未設定")

    client = storage.Client.from_service_account_json(service_account_json)
    bucket = client.bucket(bucket_name)
    object_name = f"duty-schedules/{target_date}/{Path(image_path).name}"
    blob = bucket.blob(object_name)
    blob.upload_from_filename(image_path, content_type="image/png")

    try:
        blob.make_public()
    except Exception:
        pass

    return f"https://storage.googleapis.com/{bucket_name}/{quote(object_name)}"

def send_line_messages(messages, channel_access_token, to_id):
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("LINE 發送功能需要安裝 requests") from exc

    if not channel_access_token or not to_id:
        raise ValueError("LINE Channel Access Token 或接收者 ID 未設定")

    response = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={
            "Authorization": f"Bearer {channel_access_token}",
            "Content-Type": "application/json"
        },
        json={"to": to_id, "messages": messages},
        timeout=60
    )
    response.raise_for_status()

def send_line_image(image_url, channel_access_token, to_id):
    send_line_messages(
        [{
            "type": "image",
            "originalContentUrl": image_url,
            "previewImageUrl": image_url
        }],
        channel_access_token,
        to_id
    )

def send_line_text(text, channel_access_token, to_id):
    send_line_messages(
        [{
            "type": "text",
            "text": text
        }],
        channel_access_token,
        to_id
    )

def send_group_notification(image_paths, target_date, notification_config):
    provider = (notification_config.get("provider") or "").lower().strip()
    if provider != "line":
        raise ValueError(f"不支援的通知平台: {provider}")

    channel_access_token = notification_config.get("line_channel_access_token", "").strip()
    to_id = (
        notification_config.get("line_to_id")
        or notification_config.get("line_group_id")
        or ""
    ).strip()
    completion_text = f"{target_date}勤務表登打完成"
    if isinstance(image_paths, (str, os.PathLike)):
        image_paths = [str(image_paths)]
    else:
        image_paths = [str(path) for path in image_paths]
    if not image_paths:
        raise ValueError("沒有可發送的截圖")

    image_urls = [
        upload_image_to_gcs(image_path, target_date, notification_config)
        for image_path in image_paths
    ]
    messages = [
        {
            "type": "image",
            "originalContentUrl": image_url,
            "previewImageUrl": image_url
        }
        for image_url in image_urls
    ]
    messages.append({
        "type": "text",
        "text": completion_text
    })
    send_line_messages(messages, channel_access_token, to_id)
    return {
        "provider": "LINE",
        "image_url": image_urls[0],
        "image_urls": image_urls,
        "text": completion_text
    }


def preview_night_excel_capture(excel_path, target_date):
    sheet_name = get_sheet_name_from_target_date(target_date)
    workbook = openpyxl.load_workbook(excel_path, read_only=False, keep_vba=False, data_only=False)
    try:
        resolved_sheet_name = normalize_sheet_name(sheet_name, workbook.sheetnames)
        capture_range = resolve_night_capture_range(workbook[resolved_sheet_name])
    finally:
        workbook.close()
    image_path, exported_range = export_excel_sheet_to_image(
        excel_path,
        sheet_name,
        capture_range=capture_range,
        output_path=screenshot_archive_path(NIGHT_SCREENSHOT_DIR, target_date)
    )
    return {
        "sheet_name": sheet_name,
        "image_path": image_path,
        "capture_range": exported_range
    }
def preview_excel_capture(excel_path, target_date):
    sheet_name = get_sheet_name_from_target_date(target_date)
    image_path, capture_range = export_excel_sheet_to_image(
        excel_path,
        sheet_name,
        output_path=screenshot_archive_path(DAILY_SCREENSHOT_DIR, target_date)
    )
    return {
        "sheet_name": sheet_name,
        "image_path": image_path,
        "capture_range": capture_range
    }


# ==========================================
# [區塊三] 演算法大腦 (Core Logic Algorithm)
# 專注於救災任務編組的分配邏輯
# ==========================================

def calculate_fire_mission(med_ids, disaster_ids, out_ids, daily_commander):
    """
    救災任務編組 v7.0:
    1. 司機第 1 位、幹部固定第 2 位。
    2. 備勤不足 5 人才抓補位。
    3. 確保每台車(攻擊、中繼)至少 2 人。
    """
    pool = list(disaster_ids)
    if len(disaster_ids) < 5:
        for p in med_ids:
            if p not in pool: pool.append(p)
            if len(pool) >= 5: break
    if len(pool) < 5:
        for p in out_ids:
            if p not in pool: pool.append(p)
            if len(pool) >= 5: break
            
    if str(daily_commander) in (med_ids + out_ids) and str(daily_commander) not in pool:
        pool.append(str(daily_commander))
    if len(pool) < 2: return None

    r_driver = disaster_ids[0] if disaster_ids else (pool[0] if pool else "")
    a_driver = disaster_ids[1] if len(disaster_ids) > 1 else (pool[1] if len(pool) > 1 else (pool[0] if pool else ""))

    all_officers = sorted([p for p in pool if 1 <= int(p) <= 5], key=lambda x: int(x))
    leader = str(daily_commander) if str(daily_commander) in pool else (all_officers[0] if all_officers else None)
    sub_leader = next((p for p in all_officers if p != leader), None)

    relay_team, attack_team = [r_driver], [a_driver]
    if sub_leader and sub_leader != r_driver: relay_team.insert(1, sub_leader)
    if leader and leader != a_driver: attack_team.insert(1, leader)
    
    occupied = set(relay_team + attack_team)
    others = [p for p in pool if p not in occupied]

    # 防呆：確保攻擊車與中繼車至少 2 人
    if len(attack_team) < 2 and others:
        attack_team.append(others.pop(0))
    if len(relay_team) < 2 and others:
        relay_team.append(others.pop(0))
        
    while len(relay_team) < 5 and others: 
        relay_team.append(others.pop(0))
        
    attack_team.extend(others)
    
    return {"relay": ",".join(relay_team), "attack": ",".join(attack_team)}


# ==========================================
# [區塊四] 瀏覽器底層操作 (Browser Core & JS Hooks)
# 放最強的 JS 注入與跨 Frame 搜尋工具
# ==========================================

def super_js_execute(driver, element_id, action="click", value=""):
    """地毯式搜尋全網頁 ID 並執行動作 (支援存在檢查)"""
    js_code = f"""
    function deepScan(win) {{
        var el = win.document.getElementById('{element_id}');
        if (el) {{
            if ('{action}' == 'click') {{ el.click(); if (el.onclick) el.onclick(); return true; }}
            else if ('{action}' == 'set') {{ el.value = '{value}'; el.dispatchEvent(new Event('change')); return true; }}
            else if ('{action}' == 'exists') {{ return (el.offsetWidth > 0 || el.offsetHeight > 0); }}
            return true;
        }}
        for (var i = 0; i < win.frames.length; i++) {{
            try {{ if (deepScan(win.frames[i])) return true; }} catch(e) {{}}
        }}
        return false;
    }}
    return deepScan(window.top);
    """
    return driver.execute_script(js_code)


# ==========================================
# [區塊五] 網頁自動化動作方塊 (Web Automation Steps)
# 拆解成獨立任務，方便主流程呼叫
# ==========================================

def step_login(driver, uid, pwd):
    log_status("➡️ 執行登入勤務管理系統...")
    driver.get("https://dutymgt.tyfd.gov.tw/tyfd119/login119")
    driver.find_element(By.ID, "_txtUsername").send_keys(uid)
    driver.find_element(By.ID, "_txtPassword").send_keys(pwd)
    driver.find_element(By.NAME, "login").click()

    log_status("⏳ 登入資料已送出，等待載入中...")
    time.sleep(5)

def step_navigate_menu(driver, wait):
    log_status("➡️ 正在開啟勤務分配表維護(外勤)...")
    wait.until(EC.frame_to_be_available_and_switch_to_it("ehrFrame"))
    driver.execute_script("""
        function bClick(w){
            var i=w.document.getElementsByName('nodeIcon1');
            for(var j=0;j<i.length;j++){if(i[j].src.indexOf('pnode')>-1)i[j].click();}
            var a=w.document.getElementsByTagName('a');
            for(var k=0;k<a.length;k++){if(a[k].innerText.indexOf('勤務分配表維護(外勤)')>-1){a[k].click();return true;}}
            var f=w.document.getElementsByTagName('frame');
            for(var l=0;l<f.length;l++){if(bClick(f[l].contentWindow))return true;}
            return false;
        }
        bClick(window.top);
    """)
    time.sleep(5)

def step_navigate_to_task_table(driver, wait):
    log_status("➡️ 正在開啟救災任務編組表...")
    driver.switch_to.default_content()
    try: wait.until(EC.frame_to_be_available_and_switch_to_it("ehrFrame"))
    except Exception as e: log_status(f"   ⚠️ 切換 ehrFrame 發生狀況: {e}")

    driver.execute_script("""
        function bClick(w){
            var i=w.document.getElementsByName('nodeIcon1');
            for(var j=0;j<i.length;j++){if(i[j].src.indexOf('pnode')>-1)i[j].click();}
            var a=w.document.getElementsByTagName('a');
            for(var k=0;k<a.length;k++){
                if(a[k].innerText.indexOf('救災任務編組表')>-1){
                    a[k].click();
                    return true;
                }
            }
            var f=w.document.getElementsByTagName('frame');
            for(var l=0;l<f.length;l++){if(bClick(f[l].contentWindow))return true;}
            return false;
        }
        bClick(window.top);
    """)
    time.sleep(5)
    return True

def step_prepare_content(driver, wait):
    log_status("➡️ 等待勤務基準表載入...")
    driver.switch_to.default_content()
    wait.until(EC.frame_to_be_available_and_switch_to_it("ehrFrame"))
    for i in range(5):
        try:
            wait.until(EC.frame_to_be_available_and_switch_to_it("contentFrame"))
            return True
        except: time.sleep(2)
    return False

def step_config_popups(driver, wait, out_duty_names, daily_commander):
    main_window = driver.current_window_handle
    
    # --- 1. 設定外勤項目 ---
    log_status(f"➡️ 開始設定外勤項目 (從 Excel 讀取到 {len(out_duty_names)} 項)...")
    
    # 🌟 恢復使用最強 JS 點擊，避免 Selenium 找不到框架崩潰
    super_js_execute(driver, "_btnOpenWinTaskCode", "click")
    
    try: wait.until(lambda d: len(d.window_handles) > 1)
    except: pass
    
    for h in driver.window_handles:
        if h != main_window:
            driver.switch_to.window(h)
            try:
                # 給小視窗一點時間載入，避免被系統清空
                time.sleep(1.5)
                
                for i in range(2, 8):
                    inp = wait.until(EC.presence_of_element_located((By.ID, f"_txtNAME{i}")))
                    inp.clear()
                    if (i-2) < len(out_duty_names): 
                        inp.send_keys(out_duty_names[i-2])
                
                time.sleep(0.5)
                driver.find_element(By.ID, "_btnSave").click()
                
                # 攔截存檔成功的警告窗
                try:
                    WebDriverWait(driver, 3).until(EC.alert_is_present())
                    driver.switch_to.alert.accept()
                except: pass
                
                # 確保存檔後視窗真的關閉
                try: wait.until(lambda d: len(d.window_handles) == 1)
                except: pass
            except Exception as e:
                log_status(f"   ❌ 外勤設定發生錯誤: {e}")
            break
            
    # 安全切回主視窗
    driver.switch_to.window(main_window)
    driver.switch_to.default_content()
    
    log_status("➡️ 等待勤務基準表載入...")
    time.sleep(3) # 外勤存檔後主網頁會重整，給它 3 秒緩衝
    
    wait.until(EC.frame_to_be_available_and_switch_to_it("ehrFrame"))
    wait.until(EC.frame_to_be_available_and_switch_to_it("contentFrame"))
    
    # --- 2. 設定勤務番號 ---
    log_status("➡️ 正在設定勤務番號...")
    
    # 🌟 恢復使用最強 JS 點擊
    super_js_execute(driver, "_btnOpenWinUserNo", "click")
    
    try: wait.until(lambda d: len(d.window_handles) > 1)
    except: pass
    
    for h in driver.window_handles:
        if h != main_window:
            driver.switch_to.window(h)
            try:
                time.sleep(1.5)
                
                js_select_v2 = f"""
                (function() {{
                    var commanderNo = "{daily_commander}".trim();
                    var bossNo = "1";
                    var allCbs = document.querySelectorAll('input[type="checkbox"]');
                    for (var a = 0; a < allCbs.length; a++) {{ allCbs[a].checked = false; }}
                    var rows = document.querySelectorAll('tr');
                    for (var i = 0; i < rows.length; i++) {{
                        var cells = rows[i].getElementsByTagName('td');
                        if (cells.length < 4) continue;
                        var inputNo = cells[3].querySelector('input[type="text"]');
                        if (inputNo) {{
                            var currentVal = inputNo.value.trim();
                            var cbs = rows[i].querySelectorAll('input[type="checkbox"]');
                            if (cbs.length < 2) continue; 
                            if (currentVal === bossNo || currentVal === "01") cbs[1].checked = true;
                            if (commanderNo !== "" && (currentVal === commanderNo || currentVal === ("0"+commanderNo).slice(-2))) cbs[0].checked = true;
                        }}
                    }}
                    return true;
                }})();
                """
                driver.execute_script(js_select_v2)
                
                time.sleep(0.5)
                driver.find_element(By.ID, "_btnSave").click()
                
                try:
                    WebDriverWait(driver, 3).until(EC.alert_is_present())
                    driver.switch_to.alert.accept()
                except: pass
                
                try: wait.until(lambda d: len(d.window_handles) == 1)
                except: pass
            except Exception as e: 
                log_status(f"   ❌ 指揮官小視窗操作失敗: {e}")
            break
            
    driver.switch_to.window(main_window)

def step_select_vehicles_popup(driver, wait, main_window, cars_dict):
    log_status("➡️ 正在鎖定車輛設定視窗...")
    try:
        wait.until(lambda d: len(d.window_handles) > 1)
        for h in driver.window_handles:
            if h != main_window:
                driver.switch_to.window(h)
                break
        time.sleep(1.5)
    except Exception as e:
        log_status(f"❌ 找不到車輛設定視窗: {e}")
        return

    js_select_car_v2 = r"""
    function forceSelect(selectId, targetText) {
        var sel = document.getElementById(selectId);
        if (!sel) return "找不到ID";
        var parts = targetText.split(/[/／]/);
        var mainKey = parts[0].trim();
        for (var i = 0; i < sel.options.length; i++) {
            var optText = sel.options[i].text;
            if (optText.indexOf(mainKey) !== -1 || optText.indexOf(targetText.trim()) !== -1) {
                sel.selectedIndex = i;
                sel.dispatchEvent(new Event('input', { bubbles: true }));
                sel.dispatchEvent(new Event('change', { bubbles: true }));
                if(typeof sel.onchange === 'function') {
                    try { sel.onchange({target: sel, srcElement: sel, type: 'change'}); } catch(e){}
                }
                return "成功選中: " + optText;
            }
        }
        return "找不到匹配項";
    }
    return {
        '攻擊車': forceSelect('_selCALL_TYPEA', arguments[0]),
        '中繼車': forceSelect('_selCALL_TYPEB', arguments[1]),
        '救護1': forceSelect('_selCALL_TYPEF', arguments[2]),
        '救護2': forceSelect('_selCALL_TYPEG', arguments[3])
    };
    """
    try:
        driver.execute_script(js_select_car_v2, cars_dict['attack'], cars_dict['stop'], cars_dict['amb1'], cars_dict['amb2'])
        time.sleep(1)
        driver.execute_script("var btn = document.getElementById('_btnSave'); if (btn) { btn.click(); return true; } return false;")
        
        # 確保存檔後，車輛設定的小視窗真的關閉了才繼續
        wait.until(lambda d: len(d.window_handles) == 1)
        
    except Exception as e: log_status(f"   ❌ 車輛設定執行錯誤: {e}")
    driver.switch_to.window(main_window)

def step_batch_fill_duty(driver, duty_map):
    """批次填寫勤務基準表"""
    if not duty_map: return
    js_data = str(duty_map).replace("'", '"')
    js_fill = f"""
    function deepBatchFill(win, data) {{
        var oldAlert = win.alert; var oldConfirm = win.confirm;
        win.alert = function(msg) {{ console.log("攔截: " + msg); }};
        win.confirm = function(msg) {{ return true; }};
        var count = 0;
        for (var id in data) {{
            var el = win.document.getElementById(id);
            if (el && data[id] !== "") {{
                el.focus(); el.value = data[id];
                el.dispatchEvent(new Event('input', {{bubbles: true}}));
                el.dispatchEvent(new Event('change', {{bubbles: true}}));
                el.dispatchEvent(new Event('blur', {{bubbles: true}}));
                try {{ if(typeof el.onchange === 'function') el.onchange({{target: el, type: 'change'}}); }} catch(e){{}}
                count++;
            }}
        }}
        for(var i=0; i<win.frames.length; i++) {{
            try {{ count += deepBatchFill(win.frames[i], data); }} catch(e){{}}
        }}
        win.alert = oldAlert; win.confirm = oldConfirm;
        return count;
    }}
    return deepBatchFill(window.top, {js_data});
    """
    try:
        count = driver.execute_script(js_fill)
    except Exception as e: log_status(f"   ❌ 批次填寫異常: {e}")

def step_fill_mission_cells(driver, mission_map):
    """批次填寫救災任務編組表"""
    js_data = str(mission_map).replace("'", '"')
    js_fill_and_save = f"""
    function deepProcess(win, data) {{
        var foundAny = false;
        for (var id in data) {{
            var el = win.document.getElementById(id);
            if (el) {{
                el.value = data[id];
                el.dispatchEvent(new Event('input', {{bubbles: true}}));
                el.dispatchEvent(new Event('change', {{bubbles: true}}));
                el.dispatchEvent(new Event('blur', {{bubbles: true}}));
                if(typeof el.onchange === 'function') el.onchange();
                foundAny = true;
            }}
        }}
        var btn = win.document.getElementById('_btnSave');
        if (btn) {{ btn.click(); return "SUCCESS_WITH_SAVE"; }}
        for(var i=0; i<win.frames.length; i++) {{
            try {{ var res = deepProcess(win.frames[i], data); if (res) return res; }} catch(e){{}}
        }}
        return foundAny ? "SUCCESS_NO_SAVE" : null;
    }}
    return deepProcess(window.top, {js_data});
    """
    try:
        result = driver.execute_script(js_fill_and_save)
    except Exception as e: log_status(f"   ❌ 任務填寫報錯: {e}")


# ==========================================
# [區塊六] 主控制流程 (Orchestrator - 流程大總管)
# 負責串聯 Excel 解析、網站填寫、截圖與通知。
# ==========================================

# 6-1. 單次勤務登打流程
def start_automation(user_id, user_pwd, target_date, excel_path, cars_config):
    # 紀錄流程開始的時間
    start_time = time.time()
    # ---------------- 1. 解析 Excel ----------------
    day_int = int(target_date[-2:])
    log_status(f"📂 讀取 Excel {day_int}號 分頁...")
    wb = openpyxl.load_workbook(excel_path, data_only=True, keep_vba=True)
    sheet = wb[f"{day_int}號"]
    
    ex_map = {"時間": 2, "值班": 3}
    for r in [5, 6]:
        for c in range(1, 100):
            v = str(sheet.cell(row=r, column=c).value or "").strip()
            if "休息" in v: ex_map["休息_Excel"] = c
            if "備勤緊急救護" in v: ex_map["救護_Excel"] = c
            if "備勤救災" in v: ex_map["備勤_Excel"] = c
            if "指揮官" in v: ex_map["指揮官"] = c

    cmd_all = []
    for r in range(10, 34):
        val = get_merged_val(sheet, r, ex_map["指揮官"])
        cmd_all.extend([int(x) for x in clean_to_list(val) if 1 <= int(x) <= 5])
    daily_commander = min(cmd_all) if cmd_all else ""

    out_names, out_excel_cols = [], []
    for c in range(ex_map["值班"] + 1, ex_map["休息_Excel"]):
        name = str(sheet.cell(row=5, column=c).value or "").strip()
        if name:
            out_names.append(name)
            out_excel_cols.append(c)

    num_out = len(out_names)
    web_idx = {
        "值班": 1, "外勤開始": 2, 
        "救護": 2 + num_out, "備勤": 2 + num_out + 1, "休息": 2 + num_out + 2
    }

    log_status(f"✅ Excel 讀取完成：外勤 {num_out} 項，指揮官為番號 {daily_commander if daily_commander else '無'}")
    
    # ---------------- 2. 瀏覽器自動化 ----------------
    driver = webdriver.Chrome()
    wait = WebDriverWait(driver, 20)

    try:
        step_login(driver, user_id, user_pwd)
        step_navigate_menu(driver, wait)
        
        if step_prepare_content(driver, wait):
            super_js_execute(driver, "_txtTaskDate", "set", target_date)
            super_js_execute(driver, "_btnQuery", "click")
            time.sleep(2)
            
            if super_js_execute(driver, "_btnDelete", "exists"):
                super_js_execute(driver, "_btnDelete", "click")
                wait.until(EC.alert_is_present())
                driver.switch_to.alert.accept()
                time.sleep(3)
                log_status("✅ 舊資料已刪除")
            
            step_config_popups(driver, wait, out_names, daily_commander)
            
            log_status("➡️ 等待勤務基準表載入...")
            driver.switch_to.default_content()
            
            # 🌟 回歸 JS 大法：每秒用 JS 掃描全網頁一次，看到格子出來就放行
            for _ in range(15):
                if super_js_execute(driver, "_pln_8_1", "exists"):
                    time.sleep(1)  # 看到格子後，給 1 秒鐘讓網頁背景程式綁定完畢
                    break
                time.sleep(1)
            else:
                log_status("⚠️ 等待表格載入較久，將強制繼續執行")
            
            log_status("🧠 勤務基準表計算中...")
            
            # --- 收集基準表 24H 購物車 ---
            duty_map = {}
            for r in range(10, 34):
                time_cell = str(sheet.cell(row=r, column=ex_map["時間"]).value or "").strip()
                if "-" not in time_cell: continue
                hour = str(int(time_cell.split("-")[0].strip()))
                
                duty_map[f"_pln_{hour}_{web_idx['值班']}"] = clean_v(get_merged_val(sheet, r, ex_map["值班"]))
                for i, col_idx in enumerate(out_excel_cols):
                    duty_map[f"_pln_{hour}_{web_idx['外勤開始'] + i}"] = clean_v(get_merged_val(sheet, r, col_idx))
                
                med_v = clean_v(get_merged_val(sheet, r, ex_map["救護_Excel"])) + "," + clean_v(get_merged_val(sheet, r, ex_map["救護_Excel"]+1))
                duty_map[f"_pln_{hour}_{web_idx['救護']}"] = med_v.strip(',')
                
                dis_v = ""
                for c in range(ex_map["備勤_Excel"] + 1, ex_map["指揮官"] + 1):
                    val = clean_v(get_merged_val(sheet, r, c))
                    if val: dis_v += str(val) + ","
                duty_map[f"_pln_{hour}_{web_idx['備勤']}"] = dis_v.strip(',')
                duty_map[f"_pln_{hour}_{web_idx['休息']}"] = clean_v(get_merged_val(sheet, r, ex_map["休息_Excel"]))

            team_tra_val = str(sheet["C35"].value or "").strip()
            remark_val = str(sheet["C34"].value or "").strip()
            if team_tra_val: duty_map["_areTeamTra"] = team_tra_val
            if remark_val: duty_map["_arePSREMARK"] = remark_val

            log_status(f"✅ 勤務基準表運算完畢，共填入 {len(duty_map)} 格")

            # --- 填入基準表並儲存 ---
            step_batch_fill_duty(driver, duty_map)
            time.sleep(1)
            driver.execute_script("""
                function clickSave(win) {
                    var btn = win.document.getElementById('_btnSave');
                    if(btn) { btn.click(); return true; }
                    for(var i=0; i<win.frames.length; i++) {
                        try { if(clickSave(win.frames[i])) return true; } catch(e){}
                    } return false;
                } clickSave(window.top);
            """)

            for _ in range(3): 
                try:
                    wait_alert = WebDriverWait(driver, 3)
                    wait_alert.until(EC.alert_is_present())
                    driver.switch_to.alert.accept()
                    time.sleep(1)
                except: break
            time.sleep(2)
            
            # --- 進入救災任務編組表 ---
            step_navigate_to_task_table(driver, wait) 
            driver.switch_to.default_content()
            wait.until(EC.frame_to_be_available_and_switch_to_it("ehrFrame"))
            wait.until(EC.frame_to_be_available_and_switch_to_it("contentFrame"))
            
            super_js_execute(driver, "_txtTaskDate", "set", target_date)
            super_js_execute(driver, "_btnQuery", "click")
            time.sleep(2)
            
            js_click_car = "function findAndClickBtn(win, id) { var btn = win.document.getElementById(id); if (btn) { btn.click(); return true; } for (var i = 0; i < win.frames.length; i++) { try { if (findAndClickBtn(win.frames[i], id)) return true; } catch(e) {} } return false; } return findAndClickBtn(window.top, '_btnOpenWinTaskCode');"
            if driver.execute_script(js_click_car):
                step_select_vehicles_popup(driver, wait, driver.current_window_handle, cars_config)
            
            log_status("➡️ 等待救災任務編組表載入...")
            driver.switch_to.default_content()
            
            # 🌟 同樣回歸 JS 大法
            for _ in range(15):
                if super_js_execute(driver, "_pln_8_1", "exists"):
                    time.sleep(1)
                    break
                time.sleep(1)
            else:
                log_status("⚠️ 等待表格載入較久，將強制繼續執行")
            
            log_status("🧠 救災任務編組計算中...")
            
            # --- 收集編組 24H 購物車 ---
            mission_map = {}
            for r in range(10, 34):
                time_cell = str(sheet.cell(row=r, column=ex_map["時間"]).value or "").strip()
                if "-" not in time_cell: continue
                hour = str(int(time_cell.split("-")[0].strip()))
                
                amb1_members = []
                for c in range(ex_map["救護_Excel"], ex_map["備勤_Excel"]):
                    amb1_members.extend(clean_to_list(get_merged_val(sheet, r, c)))
                amb1_members = [m for m in amb1_members if m] 
                
                disaster_ids = []
                for c in range(ex_map["備勤_Excel"], ex_map["指揮官"] + 1):
                    disaster_ids.extend(clean_to_list(get_merged_val(sheet, r, c)))
                disaster_ids = [m for m in disaster_ids if m]

                amb2_members = disaster_ids[:2]  
                out_ids = []
                for col_idx in out_excel_cols:
                    out_ids.extend(clean_to_list(get_merged_val(sheet, r, col_idx)))

                mission = calculate_fire_mission(amb1_members, disaster_ids, out_ids, daily_commander)
                if mission:
                    mission_map[f"_pln_{hour}_1"] = mission['attack']
                    mission_map[f"_pln_{hour}_2"] = mission['relay']
                    mission_map[f"_pln_{hour}_6"] = ",".join(amb1_members)
                    mission_map[f"_pln_{hour}_7"] = ",".join(amb2_members)

            if mission_map:
                log_status(f"✅ 救災任務編組運算完畢，共填入 {len(mission_map)} 格")
                time.sleep(5) 
                driver.switch_to.default_content()
                for frame_name in ['main', 'Content', 'contents', 'ehrFrame', 'contentFrame']:
                    try: driver.switch_to.frame(frame_name)
                    except: continue

                step_fill_mission_cells(driver, mission_map)
                time.sleep(1)
                try: driver.switch_to.alert.accept()
                except: pass
            
            notification_status = ""
            notification_config = load_config().get("notification", {})
            try:
                log_status("開始擷取勤務表截圖...")
                daily_preview = preview_excel_capture(excel_path, target_date)
                image_path = daily_preview["image_path"]
                log_status(f"勤務表截圖完成：{daily_preview['capture_range']}")
                night_preview = preview_night_excel_capture(excel_path, target_date)
                log_status(f"夜間勤務截圖完成：{night_preview['capture_range']}")
                if notification_config.get("enabled"):
                    log_status("開始上傳截圖並發送 LINE 通知...")
                    notification_result = send_group_notification(
                        image_path,
                        target_date,
                        notification_config
                    )
                    notification_status = "\n勤務表截圖已完成，並已發送 LINE 通知。"
                    log_status(
                        f"{notification_result['provider']} 通知已送出，共 {len(notification_result['image_urls'])} 張圖片"
                    )
                else:
                    notification_status = "\n勤務表截圖已完成。"
            except Exception as notify_error:
                notification_status = f"\n勤務表截圖或 LINE 通知失敗：{notify_error}"
                log_status(f"勤務表通知失敗：{notify_error}")

            # 計算總花費秒數
            end_time = time.time()
            elapsed_time = round(end_time - start_time, 1)
            
            log_status(f"🎉 全部完成！耗時 {elapsed_time} 秒")
            
            # 將秒數加入到最後的彈出視窗中
            success_msg = f"已登打並存檔完畢！{notification_status}\n本次自動化總共花費：{elapsed_time} 秒\n請回網頁做最後的複查。"
            root.after(0, lambda: messagebox.showinfo("成功", success_msg))

    except Exception as e:
        log_status(f"❌ 流程中斷：{e}")


# ==========================================
# [區塊七] GUI 使用者介面 (Tkinter Setup)
# ==========================================

# 7-1. GUI 事件處理
def browse_file():
    f = filedialog.askopenfilename(filetypes=[("Excel files", "*.xlsx *.xlsm")])
    entry_file.delete(0, tk.END); entry_file.insert(0, f)

def on_submit():
    uid, pwd, f_path = entry_id.get(), entry_pwd.get(), entry_file.get()
    m_date = convert_to_minguo(cal.get_date())
    
    login_config = {
        "user_id": uid,
        "user_pwd": pwd
    }
    notification_config = load_config().get("notification", get_default_config()["notification"]).copy()
    notification_config["enabled"] = bool(send_group_var.get())
    cars_config = {
        'attack': attack_car_var.get(),
        'stop': stop_car_var.get(),
        'amb1': amb1_car_var.get(),
        'amb2': amb2_car_var.get()
    }
    # 按下啟動時，自動記憶這次選了什麼
    save_config(cars_config, login_settings=login_config, notification_settings=notification_config)
    
    if not f_path: 
        messagebox.showwarning("提示", "請選擇 Excel 檔案！")
        return
    
    #  防止連點，在執行期間鎖死按鈕
    btn_submit.config(state="disabled", text="⏳ 執行中，請稍候...")

    #  建立一個背景執行緒來跑主流程，避免視窗卡死
    def run_task():
        try:
            start_automation(uid, pwd, m_date, f_path, cars_config)
        finally:
            # 結束後把按鈕恢復原狀
            root.after(0, lambda: btn_submit.config(state="normal", text="⚡ 啟動全自動流程"))

    # 啟動執行緒 (daemon=True 代表關閉視窗時背景也會強制結束)
    threading.Thread(target=run_task, daemon=True).start()

# 7-2. GUI 初始化與畫面配置
if __name__ == "__main__":
    # 🌟 1. 先讀取設定檔
    current_config = load_config()
    login = current_config["login"]
    last = current_config["last_selection"]
    opts = current_config["car_options"]

    root = tk.Tk()
    root.title("🚒 新坡全自動勤務分配表及救災任務編組表V2.0")
    # 稍微加寬拉長，給予元件足夠的呼吸空間
    root.geometry("450x800") 
    # 禁止使用者隨意縮放視窗導致跑版
    root.resizable(False, False) 

    # 設定全局字體，讓中文字體顯示更美觀
    default_font = ("微軟正黑體", 10)
    title_font = ("微軟正黑體", 14, "bold")
    root.option_add("*Font", default_font)

    # 設定按鈕的進階樣式
    style = ttk.Style()
    style.configure("TButton", font=("微軟正黑體", 10), padding=3)
    style.configure("Action.TButton", font=("微軟正黑體", 12, "bold"), padding=10)

    # 主容器：給予邊界留白
    main_frame = ttk.Frame(root, padding="20 15 20 15")
    main_frame.pack(fill="both", expand=True)

    # --- 頂部大標題 ---
    ttk.Label(main_frame, text="🚒 新坡分隊關心您的眼睛", font=title_font, anchor="center").pack(fill="x", pady=(0, 15))

    # ==========================================
    # 區塊 1：系統登入資訊
    # ==========================================
    frame_login = ttk.LabelFrame(main_frame, text="👤 登入資訊", padding="10 10 10 10")
    frame_login.pack(fill="x", pady=5)
    
    # 使用 grid 排版：標籤靠右 (sticky="e")，輸入框靠左 (sticky="w")
    ttk.Label(frame_login, text="系統帳號:").grid(row=0, column=0, sticky="e", padx=5, pady=6)
    entry_id = ttk.Entry(frame_login, width=32)
    entry_id.insert(0, login.get("user_id", ""))
    entry_id.grid(row=0, column=1, sticky="w", padx=5, pady=6)
    
    ttk.Label(frame_login, text="系統密碼:").grid(row=1, column=0, sticky="e", padx=5, pady=6)
    entry_pwd = ttk.Entry(frame_login, width=32, show="*")
    entry_pwd.insert(0, login.get("user_pwd", ""))
    entry_pwd.grid(row=1, column=1, sticky="w", padx=5, pady=6)

    # ==========================================
    # 區塊 2：班表與日期設定
    # ==========================================
    frame_file = ttk.LabelFrame(main_frame, text="📅 班表資料", padding="10 10 10 10")
    frame_file.pack(fill="x", pady=10)

    ttk.Label(frame_file, text="Excel 路徑:").grid(row=0, column=0, sticky="e", padx=5, pady=6)
    
    # 將輸入框與瀏覽按鈕包在一個子框架內，讓它們並排
    file_subframe = ttk.Frame(frame_file)
    file_subframe.grid(row=0, column=1, sticky="w", padx=5, pady=6)
    entry_file = ttk.Entry(file_subframe, width=22)
    entry_file.pack(side="left", padx=(0, 5))
    ttk.Button(file_subframe, text="📁 瀏覽", command=browse_file, width=8).pack(side="left")

    ttk.Label(frame_file, text="班表日期:").grid(row=1, column=0, sticky="e", padx=5, pady=6)
    
    tomorrow = datetime.now() + timedelta(days=1)
    cal = DateEntry(frame_file, width=30, background='darkblue', foreground='white', borderwidth=2, 
                    year=tomorrow.year, month=tomorrow.month, day=tomorrow.day, 
                    date_pattern='yyyy/mm/dd')
    cal.grid(row=1, column=1, sticky="w", padx=5, pady=6)

    send_group_var = tk.BooleanVar(value=current_config.get("notification", {}).get("enabled", True))
    ttk.Checkbutton(
        frame_file,
        text="是否傳送勤務表截圖至值班台",
        variable=send_group_var
    ).grid(row=2, column=1, sticky="w", padx=5, pady=6)

    # ==========================================
    # 區塊 3：主力車設定
    # ==========================================
    frame_car = ttk.LabelFrame(main_frame, text="🚚 主力車設定", padding="10 10 10 10")
    frame_car.pack(fill="x", pady=5)

    # 統一寬度為 32，確保上下對齊
    combo_width = 30 
    
    # 🌟 2. 修改 Combobox 的預設值與選項清單
    tk.Label(frame_car, text="攻擊車:").grid(row=0, column=0, sticky="e", padx=5, pady=6)
    attack_car_var = tk.StringVar(value=last['attack']) # 預設選上次的
    attack_combo = ttk.Combobox(frame_car, textvariable=attack_car_var, values=opts['attack'], width=combo_width)
    attack_combo.grid(row=0, column=1, sticky="w", padx=5, pady=6)
    
    tk.Label(frame_car, text="中繼車:").grid(row=1, column=0, sticky="e", padx=5, pady=6)
    stop_car_var = tk.StringVar(value=last['stop'])
    stop_combo = ttk.Combobox(frame_car, textvariable=stop_car_var, values=opts['stop'], width=combo_width)
    stop_combo.grid(row=1, column=1, sticky="w", padx=5, pady=6)
    
    tk.Label(frame_car, text="救護 1 車:").grid(row=2, column=0, sticky="e", padx=5, pady=6)
    amb1_car_var = tk.StringVar(value=last['amb1'])
    amb1_combo = ttk.Combobox(frame_car, textvariable=amb1_car_var, values=opts['amb'], width=combo_width)
    amb1_combo.grid(row=2, column=1, sticky="w", padx=5, pady=6)
    
    tk.Label(frame_car, text="救護 2 車:").grid(row=3, column=0, sticky="e", padx=5, pady=6)
    amb2_car_var = tk.StringVar(value=last['amb2'])
    amb2_combo = ttk.Combobox(frame_car, textvariable=amb2_car_var, values=opts['amb'], width=combo_width)
    amb2_combo.grid(row=3, column=1, sticky="w", padx=5, pady=6)

    # ==========================================
    # 區塊 4：執行
    # ==========================================
    action_frame = ttk.Frame(main_frame)
    action_frame.pack(fill="x", pady=(20, 0), padx=15)

    # fill="x" 讓按鈕填滿寬度，更有視覺焦點
    btn_submit = ttk.Button(action_frame, text="⚡ 啟動全自動流程", command=on_submit, style="Action.TButton")
    btn_submit.pack(fill="x")

    log_frame = ttk.LabelFrame(main_frame, text="執行紀錄", padding="10 10 10 10")
    log_frame.pack(fill="both", expand=True, pady=(15, 0))

    log_text = scrolledtext.ScrolledText(log_frame, height=10, wrap="word", state="normal")
    log_text.pack(fill="both", expand=True)
    log_text.insert(tk.END, "準備就緒\n")
    
    # ==========================================
    # 底部狀態列 (Status Bar)
    # ==========================================
    status_var = tk.StringVar(value="狀態: 準備就緒")
    status_bar = ttk.Label(root, textvariable=status_var, relief="sunken", anchor="w", padding=5)
    status_bar.pack(side="bottom", fill="x")

    root.mainloop()
