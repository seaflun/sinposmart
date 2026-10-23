# -*- coding: utf-8 -*-
"""Owned OA browser session for metadata-first electronic notice collection."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

from selenium.common.exceptions import InvalidSessionIdException, NoSuchWindowException
from selenium.webdriver.common.by import By

from app_core.login_verifier import OASessionExpiredError
from app_core.notice_collection_service import (
    FIXED_NOTICE_ACCOUNT,
    NoticeCollectionError,
    NoticeLoginRequired,
)


OA_ORIGIN = "https://oa.tyfd.gov.tw"
OA_LOGIN_URL = OA_ORIGIN + "/login.php"
UNREAD_URL = OA_ORIGIN + (
    "/module_page.php?module=bulletin#bulletin/bulletin.php?"
    "action=bulletin_list&is_read=0&list_condition=all"
)
EXPECTED_ACCOUNT_LABEL = "新坡分隊/新坡分隊公務信箱(公務信箱)"
_SCRIPT = Path(__file__).with_name("notice_collection_dom.js").read_text(encoding="utf-8")


class NoticeBrowser:
    def __init__(self, package_root: Path, *, driver_factory=None, login_runner=None,
                 wait_seconds: float = 25, poll_seconds: float = 0.2,
                 max_pages: int = 100) -> None:
        self.package_root = Path(package_root)
        self._driver_factory = driver_factory or self._create_driver
        self._login_runner = login_runner or self._run_oa_login
        self._driver = None
        local_root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SinpoSmart"
        self._profile_root = local_root
        self._profile_dir = local_root / "notice_browser_profile"
        self._wait_seconds = wait_seconds
        self._poll_seconds = poll_seconds
        self._max_pages = max_pages

    def _create_driver(self):
        from selenium.webdriver.chrome.options import Options
        from duty_rehearsal import create_webdriver_chrome_with_timeout

        profile = self._profile_dir
        profile.mkdir(parents=True, exist_ok=True)
        options = Options()
        options.add_argument(f"--user-data-dir={profile}")
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1120,800")
        options.add_argument("--disable-popup-blocking")
        options.add_experimental_option("prefs", {"credentials_enable_service": False,
                                                 "profile.password_manager_enabled": False})
        return create_webdriver_chrome_with_timeout(options)

    @staticmethod
    def _run_oa_login(driver, account: str, password: str, *, attempts: int) -> None:
        from app_core.login_verifier import run_oa_login

        run_oa_login(driver, account, password, attempts=attempts)

    def begin_login_verification(self, password: str) -> None:
        if not password:
            raise NoticeLoginRequired("請先在值班台儲存 tyfd01214 的帳號密碼。")
        self.close()
        # A fresh owned profile cannot reuse an earlier authenticated session to
        # falsely validate a newly saved password. No cookie jar is exported.
        self._profile_dir = self._profile_root / "notice_verification_profiles" / uuid4().hex

    @staticmethod
    def _check_cancel(cancel) -> None:
        if cancel is not None and cancel():
            raise NoticeCollectionError("通報收取已停止。")

    def _get_driver(self):
        if self._driver is None:
            try:
                self._driver = self._driver_factory()
                self._driver.set_page_load_timeout(30)
                self._driver.set_script_timeout(20)
            except Exception:
                self.close()
                raise NoticeCollectionError("通報專用瀏覽器無法啟動，請確認 Chrome 狀態。") from None
        return self._driver

    def _snapshot(self) -> dict:
        try:
            result = self._driver.execute_script(_SCRIPT, "snapshot", None)
        except (InvalidSessionIdException, NoSuchWindowException):
            self.close()
            raise NoticeCollectionError("通報專用視窗已關閉，下輪將重新開啟。") from None
        except Exception:
            raise NoticeCollectionError("通報頁未正常回應，請確認通報專用瀏覽器。") from None
        if not isinstance(result, dict):
            raise NoticeCollectionError("通報頁資料格式無法確認。")
        return result

    def _assert_identity(self, state: dict) -> None:
        if state.get("origin") != OA_ORIGIN:
            raise NoticeCollectionError("通報頁來源不符，已停止操作。")
        if state.get("sessionExpired") is True:
            raise NoticeLoginRequired("入口網作業逾時，請重新登入。")
        if state.get("login") or self._is_session_exceeded_page():
            raise NoticeLoginRequired("通報背景登入狀態已失效。")
        if state.get("accountCount") != 1 or state.get("account") != EXPECTED_ACCOUNT_LABEL:
            raise NoticeCollectionError("通報頁登入身分不符，僅允許新坡分隊公務信箱。")

    def _is_session_exceeded_page(self) -> bool:
        parsed = urlsplit(str(self._driver.current_url))
        return (parsed.scheme == "https" and parsed.netloc == "oa.tyfd.gov.tw"
                and parsed.path == "/sess_exceed.php" and not parsed.query)

    def _assert_login_target(self) -> None:
        parsed = urlsplit(str(self._driver.current_url))
        if (parsed.scheme != "https" or parsed.netloc != "oa.tyfd.gov.tw"
                or parsed.path not in {"/login.php", "/login_main.php"}):
            raise NoticeCollectionError("登入頁來源或路徑不符，未填入任何帳號密碼。")

    def scan_unread(self, password: str, cancel=None) -> list[dict]:
        self._check_cancel(cancel)
        if not password:
            raise NoticeLoginRequired("請先在值班台儲存 tyfd01214 的帳號密碼。")
        self._get_driver()
        try:
            return self._scan_pages(cancel)
        except NoticeLoginRequired:
            self._check_cancel(cancel)
            if self._is_session_exceeded_page():
                try:
                    self._driver.get(OA_LOGIN_URL)
                except Exception:
                    raise NoticeCollectionError("通報登入頁重新整理失敗，請確認連線。") from None
            self._assert_login_target()
            self._check_cancel(cancel)
            try:
                self._login_runner(self._driver, FIXED_NOTICE_ACCOUNT, password, attempts=3)
            except OASessionExpiredError:
                raise NoticeLoginRequired("入口網作業逾時，將於下輪重新登入。") from None
            except Exception:
                raise NoticeLoginRequired("通報背景登入未成功，請確認已儲存的密碼與網站狀態。") from None
            self._check_cancel(cancel)
            return self._scan_pages(cancel)
        except NoticeCollectionError:
            raise
        except Exception:
            raise NoticeCollectionError("通報列表載入未完成，已保留原有未讀狀態。") from None

    def _wait_page(self, expected_page: int, previous_keys, cancel) -> dict:
        deadline = time.monotonic() + self._wait_seconds
        while True:
            self._check_cancel(cancel)
            state = self._snapshot()
            self._assert_identity(state)
            rows = state.get("records", [])
            keys = tuple(str(row.get("key", "")) for row in rows if isinstance(row, dict))
            page = state.get("page")
            pages = state.get("pages")
            total = state.get("total")
            ready = (
                state.get("filtered") is True and not state.get("loading")
                and not state.get("ajaxActive") and page == expected_page
                and isinstance(pages, int) and pages >= page
                and isinstance(total, int) and total >= len(rows)
                and state.get("dateRows") == len(rows)
                and len(keys) == len(set(keys))
                and all(keys)
                and (previous_keys is None or keys != previous_keys)
                and ((total == 0 and not rows and page == pages == 1) or bool(rows))
            )
            if ready:
                for row in rows:
                    self._validated_content_url(row)
                return state
            if time.monotonic() >= deadline:
                raise NoticeCollectionError("未讀列表尚未完成載入或資料不完整，已停止本輪收取。")
            time.sleep(self._poll_seconds)

    def _scan_pages(self, cancel) -> list[dict]:
        self._check_cancel(cancel)
        try:
            self._driver.get(UNREAD_URL)
            # The fragment route can retain an earlier document, including an
            # empty unread list. Reload before accepting metadata or readback.
            self._driver.refresh()
        except (InvalidSessionIdException, NoSuchWindowException):
            self.close()
            raise NoticeCollectionError("通報專用視窗已關閉，下輪將重新開啟。") from None
        except Exception:
            raise NoticeCollectionError("通報列表重新整理失敗，請確認連線。") from None
        state = self._wait_page(1, None, cancel)
        pages, total = state["pages"], state["total"]
        if pages > self._max_pages:
            raise NoticeCollectionError("未讀通報頁數過多，請先人工確認收取範圍。")
        rows = []
        seen = set()
        for page in range(1, pages + 1):
            self._check_cancel(cancel)
            if state["pages"] != pages or state["total"] != total:
                raise NoticeCollectionError("未讀列表在查詢期間變動，將於下輪重新確認。")
            for row in state["records"]:
                key = str(row["key"])
                if key in seen:
                    raise NoticeCollectionError("通報分頁出現重複識別碼，已停止本輪收取。")
                seen.add(key)
                rows.append(dict(row, isUnread=True))
            if page < pages:
                previous_keys = tuple(str(row["key"]) for row in state["records"])
                links = self._driver.find_elements(By.CSS_SELECTOR, "a[title='下一頁']")
                if len(links) != 1:
                    raise NoticeCollectionError("無法唯一確認通報下一頁按鈕。")
                links[0].click()
                state = self._wait_page(page + 1, previous_keys, cancel)
        if len(rows) != total:
            raise NoticeCollectionError("未讀通報筆數與網站總數不一致，已停止本輪收取。")
        return rows

    @staticmethod
    def _validated_content_url(record: dict) -> str:
        notice_id = str(record.get("noticeId", ""))
        key = str(record.get("key", ""))
        url = str(record.get("contentUrl", ""))
        parsed = urlsplit(url)
        if (not re.fullmatch(r"\d+", notice_id) or key != notice_id
                or parsed.scheme != "https" or parsed.netloc != "oa.tyfd.gov.tw"
                or parsed.path != "/bulletin/bulletin_content.php"
                or parse_qs(parsed.query) != {"id": [notice_id]} or parsed.fragment):
            raise NoticeCollectionError("通報識別碼或內文來源無法確認，已停止操作。")
        return url

    def _fetch(self, operation: str, url: str, cancel) -> dict:
        self._check_cancel(cancel)
        self._assert_identity(self._snapshot())
        try:
            result = self._driver.execute_async_script(_SCRIPT, operation, url)
        except (InvalidSessionIdException, NoSuchWindowException):
            self.close()
            raise NoticeCollectionError("通報專用視窗已關閉，下輪將重新開啟。") from None
        except Exception:
            raise NoticeCollectionError("通報網站連線未完成，請稍後再試。") from None
        self._check_cancel(cancel)
        if not isinstance(result, dict):
            raise NoticeCollectionError("通報網站回覆格式無法確認。")
        if result.get("login"):
            raise NoticeLoginRequired("通報登入已過期，下輪將在背景重新登入。")
        self._assert_identity(self._snapshot())
        return result

    def read_content(self, record: dict, cancel=None) -> str:
        url = self._validated_content_url(record)
        if self._driver is None:
            raise NoticeCollectionError("通報瀏覽器尚未登入。")
        result = self._fetch("content", url, cancel)
        content = str(result.get("content", "") or "")
        content = "\n".join(re.sub(r"[ \t\u3000]+", " ", line).strip()
                            for line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
                            if line.strip())
        if not result.get("ok") or not content or content in {"內文抓取失敗", "讀取失敗", "權限限制"}:
            raise NoticeCollectionError("通報內文尚未完整讀取，已保留未讀狀態。")
        return content

    def mark_read(self, records: list[dict], cancel=None) -> list[str]:
        if not records:
            return []
        candidates = {}
        for record in records:
            self._validated_content_url(record)
            self._check_cancel(cancel)
            notice_id = str(record["noticeId"])
            url = OA_ORIGIN + "/bulletin/bulletin.php?" + urlencode({"action": "bulletin_read", "id": notice_id})
            result = self._fetch("mark", url, cancel)
            if result.get("ok"):
                candidates[str(record["key"])] = record
        remaining = {str(row["key"]) for row in self._scan_pages(cancel)}
        return [key for key in candidates if key not in remaining]

    def close(self) -> None:
        driver, self._driver = self._driver, None
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
