from __future__ import annotations

import datetime as dt
import json
import os
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable

try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv(_path: Path) -> None:
        return None
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


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
        raise RuntimeError("Missing PPE_ACCOUNT or PPE_PASSWORD in .env")

    return {
        "username": username,
        "password": password,
        "headless": read_bool("HEADLESS", True),
        "keep_browser_open": read_bool("KEEP_BROWSER_OPEN", False),
        "send_line_result": read_bool("SEND_LINE_RESULT", True),
        "timeout_seconds": int(os.getenv("SELENIUM_TIMEOUT_SECONDS", "60")),
        "selenium_remote_url": os.getenv("SELENIUM_REMOTE_URL", "").strip(),
        "selenium_remote_ready_timeout_seconds": int(os.getenv("SELENIUM_REMOTE_READY_TIMEOUT_SECONDS", "180")),
        "line_channel_access_token": os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip(),
        "line_to_user_id": os.getenv("LINE_TO_USER_ID", "").strip(),
        "line_to_user_ids": [
            item.strip()
            for item in os.getenv("LINE_TO_USER_IDS", "").split(",")
            if item.strip()
        ],
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
    return any(date_text in cell_text for date_text in today_strings)


def wait_for_spinner(wait: WebDriverWait) -> None:
    try:
        wait.until(EC.invisibility_of_element_located((By.ID, "spinner-container")))
    except TimeoutException:
        pass


def query_grid_rows(driver: webdriver.Chrome, wait: WebDriverWait, context: str) -> list:
    wait_for_spinner(wait)
    search_button = wait.until(
        EC.element_to_be_clickable((By.XPATH, f"//button[contains(normalize-space(.), '{TEXT_SEARCH}')]"))
    )
    driver.execute_script("arguments[0].click();", search_button)
    wait_for_spinner(wait)

    deadline = time.time() + 10
    rows: list = []
    while time.time() < deadline:
        rows = driver.find_elements(By.XPATH, "//div[@id='grid']//tbody/tr")
        if rows:
            print(f"[{context}] rows loaded: {len(rows)}")
            return rows
        time.sleep(0.5)

    print(f"[{context}] rows loaded: 0")
    return rows


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


def send_line_push(config: dict[str, object], text: str) -> None:
    token = str(config["line_channel_access_token"])
    user_ids = list(config["line_to_user_ids"])
    fallback_user_id = str(config["line_to_user_id"])
    if not user_ids and fallback_user_id:
        user_ids = [fallback_user_id]
    if not token or not user_ids:
        print("[line] skipped: missing LINE_CHANNEL_ACCESS_TOKEN or LINE_TO_USER_IDS")
        return

    for user_id in user_ids:
        payload = json.dumps(
            {
                "to": user_id,
                "messages": [{"type": "text", "text": text[:5000]}],
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            "https://api.line.me/v2/bot/message/push",
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            print(f"[line] push sent to {user_id}: {getattr(response, 'status', 'unknown')}")


def login(driver: webdriver.Chrome, wait: WebDriverWait, username: str, password: str) -> None:
    print("[login] opening login page")
    driver.get(LOGIN_URL)
    wait.until(EC.presence_of_element_located((By.ID, "Account"))).send_keys(username)
    wait.until(EC.presence_of_element_located((By.ID, "Password"))).send_keys(password)
    wait.until(EC.element_to_be_clickable((By.ID, "btnSubmit"))).click()
    wait.until(EC.presence_of_element_located((By.XPATH, f"//*[contains(text(), '{TEXT_LOGOUT}')]")))
    print("[login] success")


def process_maintain_checks(driver: webdriver.Chrome, wait: WebDriverWait, today_strings: list[str], today: dt.datetime) -> None:
    needs_weekly = today.weekday() == 6
    needs_monthly = today.day == 28
    needs_half_year = (today.month == 6 and today.day == 30) or (today.month == 10 and today.day == 31)

    print("[maintain] opening maintain list")
    driver.get(MAINTAIN_LIST_URL)
    rows = query_grid_rows(driver, wait, "maintain")

    for index in range(1, len(rows) + 1):
        wait_for_spinner(wait)
        row_xpath = f"//div[@id='grid']//tbody/tr[{index}]"
        row_element = wait.until(EC.presence_of_element_located((By.XPATH, row_xpath)))
        cells = row_element.find_elements(By.TAG_NAME, "td")

        car_license = cells[8].get_attribute("textContent").strip() if len(cells) > 8 else f"car-{index}"
        day_text = cells[9].get_attribute("textContent").strip() if len(cells) > 9 else ""
        week_text = cells[10].get_attribute("textContent").strip() if len(cells) > 10 else ""
        month_text = cells[11].get_attribute("textContent").strip() if len(cells) > 11 else ""
        half_year_text = cells[12].get_attribute("textContent").strip() if len(cells) > 12 else ""

        daily_done = is_task_done(day_text, today_strings)
        weekly_done = is_task_done(week_text, today_strings) if needs_weekly else True
        monthly_done = is_task_done(month_text, today_strings) if needs_monthly else True
        half_year_done = is_task_done(half_year_text, today_strings) if needs_half_year else True

        if daily_done and weekly_done and monthly_done and half_year_done:
            print(f"[maintain] {car_license}: already done")
            continue

        print(f"[maintain] {car_license}: processing")
        maintain_button = wait.until(
            EC.presence_of_element_located((By.XPATH, f"{row_xpath}//button[contains(., '{TEXT_MAINTAIN}')]"))
        )
        driver.execute_script("arguments[0].click();", maintain_button)

        while True:
            wait_for_spinner(wait)
            wait.until(lambda current_driver: len(current_driver.find_elements(By.CSS_SELECTOR, "#scheduler .k-event")) > 0)
            date_label = f"{today.year}年{today.month}月{today.day}日"
            events = driver.find_elements(By.CSS_SELECTOR, "#scheduler .k-event")
            has_today = False
            target_event = None

            for event_element in events:
                aria_label = event_element.get_attribute("aria-label") or ""
                if date_label not in aria_label:
                    continue

                has_today = True
                class_names = event_element.get_attribute("class") or ""
                reviewed_flags = event_element.find_elements(By.CSS_SELECTOR, ".reviewed")
                if "checked" in class_names or "disable" in class_names or reviewed_flags:
                    continue

                target_event = event_element
                break

            if target_event is not None:
                driver.execute_script("arguments[0].click();", target_event)
                result = "SUCCESS"
            else:
                result = "ALL_DONE" if has_today else "NOT_FOUND"

            if result == "SUCCESS":
                wait.until(EC.visibility_of_element_located((By.ID, "maintainList")))
                submit_button = wait.until(
                    EC.presence_of_element_located((By.XPATH, "//button[@onclick='SaveProc()']"))
                )
                driver.execute_script("arguments[0].click();", submit_button)
                wait.until(
                    EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'swal') or contains(@class, 'sweet')]"))
                )
                driver.refresh()
                continue

            if result == "ALL_DONE":
                print(f"[maintain] {car_license}: all items completed")
            else:
                print(f"[maintain] {car_license}: calendar result = {result}")
            break

        try:
            return_button = wait.until(
                EC.presence_of_element_located(
                    (By.XPATH, f"//a[contains(@class, 'btnCancel') and contains(., '{TEXT_RETURN_TO_LIST}')]")
                )
            )
            driver.execute_script("arguments[0].click();", return_button)
        except TimeoutException:
            driver.get(MAINTAIN_LIST_URL)
            query_grid_rows(driver, wait, "maintain")


def process_equip_checks(driver: webdriver.Chrome, wait: WebDriverWait) -> None:
    print("[equip] opening equipment check list")
    driver.get(EQUIP_CHECK_LIST_URL)
    rows = query_grid_rows(driver, wait, "equip")

    for index in range(1, len(rows) + 1):
        wait_for_spinner(wait)
        row_xpath = f"//div[@id='grid']//tbody/tr[{index}]"
        row_element = wait.until(EC.presence_of_element_located((By.XPATH, row_xpath)))
        cells = row_element.find_elements(By.TAG_NAME, "td")

        car_license = cells[3].text.strip() if len(cells) > 3 else f"car-{index}"
        check_buttons = row_element.find_elements(
            By.XPATH,
            f".//button[text()='{TEXT_EQUIP_CHECK}' or contains(., '{TEXT_EQUIP_CHECK}')]",
        )

        if not check_buttons:
            print(f"[equip] {car_license}: already done")
            continue

        print(f"[equip] {car_license}: processing")
        driver.execute_script("arguments[0].click();", check_buttons[0])
        wait_for_spinner(wait)

        select_all_checkbox = wait.until(
            EC.presence_of_element_located((By.XPATH, "//input[@aria-label='Select all rows' and @type='checkbox']"))
        )
        driver.execute_script("arguments[0].click();", select_all_checkbox)

        submit_button = wait.until(
            EC.presence_of_element_located((By.XPATH, f"//button[contains(., '{TEXT_FINISH_EQUIP_CHECK}')]"))
        )
        driver.execute_script("arguments[0].click();", submit_button)

        wait.until(
            lambda current_driver: (
                any(
                    button.is_displayed()
                    for button in current_driver.find_elements(
                        By.XPATH,
                        "//button[contains(@class, 'swal-button') or contains(@class, 'swal2-confirm')]",
                    )
                )
                or "/CarEquipCheck/View" in current_driver.current_url
                or "/CarEquipCheck/Take" not in current_driver.current_url
            )
        )

        for confirm_button in driver.find_elements(
            By.XPATH,
            "//button[contains(@class, 'swal-button') or contains(@class, 'swal2-confirm')]",
        ):
            if confirm_button.is_displayed():
                driver.execute_script("arguments[0].click();", confirm_button)
                break

        wait.until(
            lambda current_driver: (
                "/CarEquipCheck/View" in current_driver.current_url
                or "/CarEquipCheck/Take" not in current_driver.current_url
            )
        )
        print(f"[equip] {car_license}: submitted")
        driver.get(EQUIP_CHECK_LIST_URL)
        query_grid_rows(driver, wait, "equip")


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


def main() -> None:
    config = load_config()
    driver = None

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
    if remote_url:
        print(f"[driver] using remote selenium: {remote_url}")
        wait_for_remote_selenium(remote_url, int(config["selenium_remote_ready_timeout_seconds"]))
        wait_for_login_site(LOGIN_URL, int(config["selenium_remote_ready_timeout_seconds"]))
        driver = webdriver.Remote(command_executor=remote_url, options=options)
    else:
        print("[driver] using local chrome")
        driver = webdriver.Chrome(options=options)

    wait = WebDriverWait(driver, int(config["timeout_seconds"]))
    driver.set_page_load_timeout(max(15, int(config["timeout_seconds"])))

    today = dt.datetime.now()
    today_strings = build_today_strings(today)

    print("=" * 50)
    print(f"date: {today.strftime('%Y/%m/%d')}")
    print(f"headless: {config['headless']}")
    print("=" * 50)

    try:
        login(driver, wait, str(config["username"]), str(config["password"]))
        process_maintain_checks(driver, wait, today_strings, today)
        process_equip_checks(driver, wait)
        save_artifacts(driver, "last-run")
        print("[done] automation finished")
        if config["send_line_result"]:
            send_line_push(config, f"PPE ?芸??歇摰?\n??: {today.strftime('%Y/%m/%d %H:%M:%S')}\n蝯?: ??")
    except Exception as error:
        if driver is not None:
            save_artifacts(driver, "error")
        message = (
            f"PPE ?芸??仃?n"
            f"??: {today.strftime('%Y/%m/%d %H:%M:%S')}\n"
            f"?航炊: {type(error).__name__}: {error}"
        )
        if config["send_line_result"]:
            try:
                send_line_push(config, message)
            except Exception as line_error:
                print(f"[line] push failed: {line_error}")
        print(traceback.format_exc())
        raise
    finally:
        if driver is not None and not config["keep_browser_open"]:
            try:
                driver.quit()
            except WebDriverException as error:
                print(f"[driver] quit skipped: {error}")


if __name__ == "__main__":
    main()
