# -*- coding: utf-8 -*-
"""Owned OA browser session for metadata-first electronic notice collection."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from datetime import datetime
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

from selenium.common.exceptions import InvalidSessionIdException, NoSuchWindowException
from selenium.webdriver.common.by import By

from app_core.login_verifier import LoginVerificationError, OASessionExpiredError, OA_LOGIN_FAILURE_MESSAGES
from app_core.notice_collection_service import (
    FIXED_NOTICE_ACCOUNT,
    NoticeCollectionError,
    NoticeLoginRequired,
    NoticeLoginGuard,
    TAIPEI,
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
                 max_pages: int = 100, login_guard=None, now_factory=None) -> None:
        self.package_root = Path(package_root)
        self._driver_factory = driver_factory or self._create_driver
        self._login_runner = login_runner or self._run_oa_login
        self._driver = None
        local_root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SinpoSmart"
        self._profile_root = local_root
        self._profile_dir = local_root / "notice_browser_profiles"
        self._wait_seconds = wait_seconds
        self._poll_seconds = poll_seconds
        self._max_pages = max_pages
        self._publication_cache = {}
        self._login_guard = None if login_guard is False else login_guard or NoticeLoginGuard(self.package_root)
        self._now = now_factory or (lambda: datetime.now(TAIPEI))
        self._verifying_password = False
        self._attempt_started = False

    def _create_driver(self):
        from duty_rehearsal import build_driver

        return build_driver(headless=True, profile_root=self._profile_dir,
            prune_profiles=False, write_diagnostics=False, option_arguments=("--window-size=1120,800",),
            preferences={"credentials_enable_service": False, "profile.password_manager_enabled": False})

    @staticmethod
    def _run_oa_login(driver, account: str, password: str, *, attempts: int, **options) -> None:
        from app_core.login_verifier import run_oa_login

        run_oa_login(driver, account, password, attempts=attempts, **options)

    def begin_login_verification(self, password: str) -> None:
        if not password:
            raise NoticeLoginRequired("請先在值班台儲存 tyfd01214 的帳號密碼。", code="credentials_missing")
        self.close()
        # A fresh owned profile cannot reuse an earlier authenticated session to
        # falsely validate a newly saved password. No cookie jar is exported.
        self._profile_dir = self._profile_root / "notice_verification_profiles" / uuid4().hex
        self._verifying_password = True

    def end_login_verification(self) -> None:
        self._verifying_password = False

    def _check_cancel(self, cancel) -> None:
        if self._login_guard and not self._verifying_password:
            status = self._login_guard.status(self._now())
            if status["expired"]:
                raise NoticeLoginRequired(status["message"], code=status["code"])
        if cancel is not None and cancel():
            raise NoticeCollectionError("通報收取已停止。", code="cancelled")

    def _get_driver(self):
        if self._driver is None:
            try:
                self._driver = self._driver_factory()
                self._driver.set_page_load_timeout(30)
                self._driver.set_script_timeout(20)
            except Exception:
                self.close()
                raise NoticeCollectionError("通報專用瀏覽器無法啟動，請確認 Chrome 狀態。", code="browser_start_failed") from None
        return self._driver

    def _snapshot(self) -> dict:
        try:
            result = self._driver.execute_script(_SCRIPT, "snapshot", None)
        except (InvalidSessionIdException, NoSuchWindowException):
            self.close()
            raise NoticeCollectionError("通報專用視窗已關閉，下輪將重新開啟。", code="browser_window_closed") from None
        except Exception:
            raise NoticeCollectionError("通報頁未正常回應，請確認通報專用瀏覽器。", code="snapshot_failed") from None
        if not isinstance(result, dict):
            raise NoticeCollectionError("通報頁資料格式無法確認。", code="snapshot_invalid")
        return result

    def _assert_identity(self, state: dict) -> None:
        if state.get("origin") != OA_ORIGIN:
            raise NoticeCollectionError("通報頁來源不符，已停止操作。", code="origin_mismatch")
        if state.get("sessionExpired") is True:
            raise NoticeLoginRequired("入口網作業逾時，請重新登入。", code="session_expired")
        if state.get("login") or self._is_session_exceeded_page():
            raise NoticeLoginRequired("通報背景登入狀態已失效。", code="session_expired")
        if state.get("accountCount") != 1 or state.get("account") != EXPECTED_ACCOUNT_LABEL:
            raise NoticeCollectionError("通報頁登入身分不符，僅允許新坡分隊公務信箱。", code="account_mismatch")

    def _is_session_exceeded_page(self) -> bool:
        parsed = urlsplit(str(self._driver.current_url))
        return (parsed.scheme == "https" and parsed.netloc == "oa.tyfd.gov.tw"
                and parsed.path == "/sess_exceed.php" and not parsed.query)

    def _assert_login_target(self) -> None:
        parsed = urlsplit(str(self._driver.current_url))
        if (parsed.scheme != "https" or parsed.netloc != "oa.tyfd.gov.tw"
                or parsed.path not in {"/login.php", "/login_main.php"}):
            raise NoticeCollectionError("登入頁來源或路徑不符，未填入任何帳號密碼。", code="login_target_mismatch")

    def scan_unread(self, password: str, cancel=None) -> list[dict]:
        return self._scan_with_login(password, cancel)

    def scan_recent(self, password: str, start_date, end_date, cancel=None) -> list[dict]:
        if start_date > end_date or (end_date - start_date).days > 7:
            raise NoticeCollectionError("通報補查日期範圍無法確認。", code="publication_invalid")
        roc = lambda day: f"{day.year - 1911:03d}-{day.month:02d}-{day.day:02d}"
        rows = self._scan_with_login(password, cancel, read_filter=2, date_range=(roc(start_date), roc(end_date)))
        for row in rows:
            if row.get("isUnread") is False:
                row["publishedAt"] = self.read_publication(row, cancel)
        return rows

    def _scan_with_login(self, password: str, cancel=None, **filters) -> list[dict]:
        if self._login_guard:
            self._login_guard.require_allowed(self._now(), verification=self._verifying_password)
        self._check_cancel(cancel)
        if not password:
            raise NoticeLoginRequired("請先在值班台儲存 tyfd01214 的帳號密碼。", code="credentials_missing")
        self._get_driver()
        try:
            return self._scan_pages(cancel, **filters)
        except NoticeLoginRequired:
            self._check_cancel(cancel)
            if self._is_session_exceeded_page():
                try:
                    self._driver.get(OA_LOGIN_URL)
                except Exception:
                    raise NoticeCollectionError("通報登入頁重新整理失敗，請確認連線。", code="login_page_failed") from None
            self._assert_login_target()
            self._check_cancel(cancel)
            self._attempt_started = False
            try:
                options = ({"submit_limit": 1, "before_submit": self._before_login_submit,
                            "password_expiry_callback": self._record_password_expiry} if self._login_guard else {})
                self._login_runner(self._driver, FIXED_NOTICE_ACCOUNT, password, attempts=3, **options)
                self._check_cancel(cancel)
                rows = self._scan_pages(cancel, **filters)
                if self._login_guard and not self._verifying_password:
                    self._login_guard.finish_attempt(self._now())
                return rows
            except OASessionExpiredError:
                self._pause_failed_attempt("oa_login_unconfirmed")
                message = ("入口網登入尚未確認，已暫停自動登入，請儲存通報密碼重新驗證。" if self._login_guard
                           else "入口網作業逾時，將於下輪重新登入。")
                raise NoticeLoginRequired(message, code="session_expired") from None
            except Exception as exc:
                code = getattr(exc, "reason_code", "") or getattr(exc, "code", "")
                self._pause_failed_attempt(code)
                if isinstance(exc, NoticeCollectionError):
                    raise
                if isinstance(code, str) and code in OA_LOGIN_FAILURE_MESSAGES:
                    raise NoticeLoginRequired(OA_LOGIN_FAILURE_MESSAGES[code], code=code) from None
                raise NoticeLoginRequired("通報背景登入未成功，請確認已儲存的密碼與網站狀態。", code="login_failed") from None
        except NoticeCollectionError:
            raise
        except Exception:
            raise NoticeCollectionError("通報列表載入未完成，已保留原有未讀狀態。", code="scan_unexpected") from None

    def _before_login_submit(self) -> None:
        try:
            self._login_guard.begin_attempt(self._now(), verification=self._verifying_password)
            self._attempt_started = True
        except NoticeLoginRequired as exc:
            raise LoginVerificationError(str(exc), reason_code=exc.code) from None

    def _record_password_expiry(self, value: str) -> None:
        try:
            self._login_guard.record_expiry(value, pending=True)
            if not self._verifying_password:
                status = self._login_guard.status(self._now())
                if status["expired"]:
                    raise NoticeLoginRequired(status["message"], code=status["code"])
        except NoticeLoginRequired as exc:
            raise LoginVerificationError(str(exc), reason_code=exc.code) from None

    def _pause_failed_attempt(self, code: str) -> None:
        if self._login_guard and (self._attempt_started or code in self._login_guard.REASONS - {""}):
            self._login_guard.pause(code)

    def _wait_page(self, expected_page: int, previous_keys, cancel, *, read_filter=0, date_range=None) -> dict:
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
                and state.get("readFilter", 0) == read_filter
                and (date_range is None or (state.get("dateFrom"), state.get("dateTo")) == date_range)
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
                raise NoticeCollectionError("未讀列表尚未完成載入或資料不完整，已停止本輪收取。", code="list_wait_timeout")
            time.sleep(self._poll_seconds)

    def _scan_pages(self, cancel, *, read_filter=0, date_range=None) -> list[dict]:
        self._check_cancel(cancel)
        url = UNREAD_URL
        if read_filter == 2 and date_range:
            query = {"action": "bulletin_list", "is_read": 2, "list_condition": "all",
                     "start_date": date_range[0], "end_date": date_range[1], "orderby": "start_date"}
            url = OA_ORIGIN + "/module_page.php?module=bulletin#bulletin/bulletin.php?" + urlencode(query)
        try:
            self._driver.get(url)
            # The fragment route can retain an earlier document, including an
            # empty unread list. Reload before accepting metadata or readback.
            self._driver.refresh()
        except (InvalidSessionIdException, NoSuchWindowException):
            self.close()
            raise NoticeCollectionError("通報專用視窗已關閉，下輪將重新開啟。", code="browser_window_closed") from None
        except Exception:
            raise NoticeCollectionError("通報列表重新整理失敗，請確認連線。", code="list_navigation_failed") from None
        state = self._wait_page(1, None, cancel, read_filter=read_filter, date_range=date_range)
        pages, total = state["pages"], state["total"]
        if pages > self._max_pages:
            raise NoticeCollectionError("未讀通報頁數過多，請先人工確認收取範圍。", code="page_limit")
        rows = []
        seen = set()
        for page in range(1, pages + 1):
            self._check_cancel(cancel)
            if state["pages"] != pages or state["total"] != total:
                raise NoticeCollectionError("未讀列表在查詢期間變動，將於下輪重新確認。", code="list_changed")
            for row in state["records"]:
                key = str(row["key"])
                if key in seen:
                    raise NoticeCollectionError("通報分頁出現重複識別碼，已停止本輪收取。", code="duplicate_notice_id")
                seen.add(key)
                if read_filter == 2 and type(row.get("isUnread")) is not bool:
                    raise NoticeCollectionError("通報已讀狀態無法確認。", code="publication_invalid")
                rows.append(dict(row, isUnread=True if read_filter == 0 else row["isUnread"]))
            if page < pages:
                previous_keys = tuple(str(row["key"]) for row in state["records"])
                links = self._driver.find_elements(By.CSS_SELECTOR, "a[title='下一頁']")
                if len(links) != 1:
                    raise NoticeCollectionError("無法唯一確認通報下一頁按鈕。", code="next_page_ambiguous")
                links[0].click()
                state = self._wait_page(page + 1, previous_keys, cancel, read_filter=read_filter, date_range=date_range)
        if len(rows) != total:
            raise NoticeCollectionError("未讀通報筆數與網站總數不一致，已停止本輪收取。", code="count_mismatch")
        return rows

    def read_publication(self, record: dict, cancel=None) -> str:
        self._validated_content_url(record)
        if record.get("isUnread") is not False:
            raise NoticeCollectionError("未讀通報尚未入表，不開啟會標記已讀的詳頁。", code="publication_invalid")
        cache_key = (record["key"], record["date"], record.get("subject", ""))
        if cache_key in self._publication_cache:
            return self._publication_cache[cache_key]
        url = OA_ORIGIN + "/bulletin/bulletin.php?" + urlencode({"action": "bulletin_read", "id": record["noticeId"]})
        result = self._fetch("publication", url, cancel)
        try:
            raw = str(result["publishedAt"])
            year = int(raw[:3]) + 1911
            published = datetime.strptime(str(year) + raw[3:], "%Y-%m-%d %H:%M:%S").replace(tzinfo=TAIPEI)
            valid = result.get("ok") and str(result.get("noticeId")) == str(record["noticeId"]) and raw[:9] == record["date"]
        except (KeyError, TypeError, ValueError):
            valid = False
        if not valid:
            raise NoticeCollectionError("通報公布日期時間無法確認。", code="publication_invalid")
        value = published.isoformat(timespec="seconds")
        self._publication_cache[cache_key] = value
        return value

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
            raise NoticeCollectionError("通報識別碼或內文來源無法確認，已停止操作。", code="notice_url_invalid")
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
                from duty_rehearsal import quit_driver

                quit_driver(driver)
            except Exception:
                pass
