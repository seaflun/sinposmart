from __future__ import annotations

import sys
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

PACKAGE = Path(__file__).resolve().parents[1] / "WinPython_公務電腦使用包"
sys.path.insert(0, str(PACKAGE))


def notice(number="100"):
    return {"key": number, "noticeId": number, "date": "115-10-21",
            "subject": "測試通報", "sender": "測試員", "isUnread": True,
            "contentUrl": f"https://oa.tyfd.gov.tw/bulletin/bulletin_content.php?id={number}"}


def snapshot(records=(), page=1, pages=1, total=None, **changes):
    value = {"origin": "https://oa.tyfd.gov.tw", "account": "新坡分隊/新坡分隊公務信箱(公務信箱)",
             "accountCount": 1, "login": False, "filtered": True, "ajaxActive": 0,
             "loading": False, "page": page, "pages": pages,
             "total": len(records) if total is None else total,
             "dateRows": len(records), "records": list(records)}
    value.update(changes)
    return value


class FakeDriver:
    def __init__(self, pages=None):
        self.pages = pages or [snapshot()]
        self.index = 0
        self.current_url = "about:blank"
        self.gets = []
        self.refresh_calls = 0
        self.async_calls = []
        self.quit_calls = 0
        self.login_inputs = {}
        self.on_next = None
        self.on_get = None
        self.on_refresh = None
        self.fetch_result = {"ok": True, "content": " 第一行\n第二行 "}

    def get(self, url):
        self.gets.append(url)
        self.current_url = url
        self.index = 0
        if self.on_get:
            self.on_get(self)

    def refresh(self):
        self.refresh_calls += 1
        self.index = 0
        if self.on_refresh:
            self.on_refresh(self)

    def execute_script(self, script, *args):
        if "notice:snapshot" in script:
            return self.pages[self.index]
        raise AssertionError("Unexpected script")

    def execute_async_script(self, script, *args):
        self.async_calls.append((script, args))
        return self.fetch_result

    def find_elements(self, by, selector):
        if selector in ("#login_name", "#password"):
            return [self.login_inputs[selector]] if selector in self.login_inputs else []
        if selector == "a[title='下一頁']":
            owner = self

            class Next:
                def click(self):
                    if owner.on_next:
                        owner.on_next()
                    else:
                        owner.index += 1

            return [Next()]
        return []

    def set_page_load_timeout(self, _value):
        pass

    def set_script_timeout(self, _value):
        pass

    def quit(self):
        self.quit_calls += 1


class NoticeBrowserTests(unittest.TestCase):
    def browser(self, driver, **kwargs):
        from app_core.notice_collection_browser import NoticeBrowser
        return NoticeBrowser(PACKAGE, driver_factory=lambda: driver,
                             wait_seconds=0.03, poll_seconds=0.001, **kwargs)

    def test_empty_unread_filter_returns_without_content_requests(self):
        driver = FakeDriver()
        self.assertEqual(self.browser(driver).scan_unread("synthetic"), [])
        self.assertIn("is_read=0", driver.gets[-1])
        self.assertEqual(driver.async_calls, [])

    def test_repeated_scan_reloads_document_to_discover_new_unread_notice(self):
        driver = FakeDriver([snapshot()])
        server_pages = [snapshot()]
        driver.on_refresh = lambda current: setattr(current, "pages", list(server_pages))
        browser = self.browser(driver)
        self.assertEqual(browser.scan_unread("synthetic"), [])

        server_pages[:] = [snapshot([notice("101")])]
        self.assertEqual(driver.pages[0]["records"], [])
        result = browser.scan_unread("synthetic")

        self.assertEqual([row["key"] for row in result], ["101"])
        self.assertEqual(driver.async_calls, [])

    def test_collects_every_unread_page_and_preserves_identity(self):
        driver = FakeDriver([snapshot([notice("100")], 1, 2, 2),
                             snapshot([notice("101")], 2, 2, 2)])
        result = self.browser(driver).scan_unread("synthetic")
        self.assertEqual([row["key"] for row in result], ["100", "101"])
        self.assertEqual(driver.async_calls, [])

    def test_foreign_account_fails_before_content_or_mark_read(self):
        from app_core.notice_collection_service import NoticeCollectionError
        driver = FakeDriver([snapshot([notice()], account="其他帳號")])
        with self.assertRaises(NoticeCollectionError):
            self.browser(driver).scan_unread("synthetic")
        self.assertEqual(driver.async_calls, [])

    def test_foreign_login_redirect_cannot_receive_saved_credentials(self):
        from app_core.notice_collection_service import NoticeCollectionError, NoticeLoginRequired
        driver = FakeDriver([snapshot(origin="https://example.com", login=True)])
        driver.on_get = lambda current: setattr(current, "current_url", "https://example.com/login.php")
        user, password = Mock(), Mock()
        user.get_attribute.return_value = password.get_attribute.return_value = ""
        driver.login_inputs = {"#login_name": user, "#password": password}
        driver.find_elements = Mock(wraps=driver.find_elements)
        with self.assertRaises(NoticeCollectionError) as error:
            self.browser(driver).scan_unread("synthetic")
        self.assertNotIsInstance(error.exception, NoticeLoginRequired)
        driver.find_elements.assert_not_called()
        user.send_keys.assert_not_called()
        password.send_keys.assert_not_called()

    def test_auto_login_cannot_start_from_foreign_site(self):
        from app_core.notice_collection_service import NoticeCollectionError, NoticeLoginRequired
        driver = FakeDriver([snapshot(origin="https://example.com", login=True)])
        driver.on_get = lambda current: setattr(current, "current_url", "https://example.com/login.php")
        login = Mock()
        browser = self.browser(driver, login_runner=login)
        user, password = Mock(), Mock()
        user.get_attribute.return_value = password.get_attribute.return_value = ""
        driver.login_inputs = {"#login_name": user, "#password": password}
        driver.find_elements = Mock(wraps=driver.find_elements)
        with self.assertRaises(NoticeCollectionError) as error:
            browser.scan_unread("synthetic")
        self.assertNotIsInstance(error.exception, NoticeLoginRequired)
        login.assert_not_called()
        driver.find_elements.assert_not_called()
        user.send_keys.assert_not_called()
        password.send_keys.assert_not_called()

    def test_login_prefill_requires_the_oa_login_path(self):
        from app_core.notice_collection_service import NoticeCollectionError, NoticeLoginRequired
        driver = FakeDriver([snapshot(login=True)])
        user, password = Mock(), Mock()
        user.get_attribute.return_value = password.get_attribute.return_value = ""
        driver.login_inputs = {"#login_name": user, "#password": password}
        driver.find_elements = Mock(wraps=driver.find_elements)
        with self.assertRaises(NoticeCollectionError) as error:
            self.browser(driver).scan_unread("synthetic")
        self.assertNotIsInstance(error.exception, NoticeLoginRequired)
        driver.find_elements.assert_not_called()
        user.send_keys.assert_not_called()
        password.send_keys.assert_not_called()

    def test_stale_filtered_grid_is_never_accepted(self):
        from app_core.notice_collection_service import NoticeCollectionError
        driver = FakeDriver([snapshot([notice()], filtered=False)])
        with self.assertRaises(NoticeCollectionError):
            self.browser(driver).scan_unread("synthetic")

    def test_incomplete_or_repeated_page_fails_closed(self):
        from app_core.notice_collection_service import NoticeCollectionError
        driver = FakeDriver([snapshot([notice()], 1, 2, 2)])
        driver.on_next = lambda: None
        with self.assertRaises(NoticeCollectionError):
            self.browser(driver).scan_unread("synthetic")

    def test_content_is_requested_only_explicitly_and_never_marks_read(self):
        driver = FakeDriver([snapshot([notice()])])
        browser = self.browser(driver)
        browser.scan_unread("synthetic")
        self.assertEqual(browser.read_content(notice()), "第一行\n第二行")
        self.assertEqual(len(driver.async_calls), 1)
        self.assertIn("bulletin_content.php", driver.async_calls[0][1][1])
        self.assertNotIn("action=bulletin_read", driver.async_calls[0][1][1])

    def test_foreign_content_url_never_transmits_credentials(self):
        from app_core.notice_collection_service import NoticeCollectionError
        driver = FakeDriver([snapshot([notice()])])
        browser = self.browser(driver)
        browser.scan_unread("synthetic")
        for url in ("https://example.com/bulletin/bulletin_content.php?id=100",
                    "https://oa.tyfd.gov.tw/bulletin/bulletin_content.php?id=101",
                    "https://oa.tyfd.gov.tw/login.php?id=100"):
            with self.subTest(url=url), self.assertRaises(NoticeCollectionError):
                browser.read_content({**notice(), "contentUrl": url})
        self.assertEqual(driver.async_calls, [])

    def test_mark_read_requires_server_readback_not_css_change(self):
        driver = FakeDriver([snapshot([notice()])])
        browser = self.browser(driver)
        browser.scan_unread("synthetic")
        driver.pages = [snapshot()]
        self.assertEqual(browser.mark_read([notice()]), ["100"])
        self.assertIn("action=bulletin_read", driver.async_calls[0][1][1])
        self.assertGreaterEqual(len(driver.gets), 2)

    def test_mark_read_reloads_document_before_confirming_server_state(self):
        driver = FakeDriver([snapshot([notice()])])
        server_pages = [snapshot([notice()])]
        driver.on_refresh = lambda current: setattr(current, "pages", list(server_pages))
        original_fetch = driver.execute_async_script

        def mark_on_server(script, *args):
            response = original_fetch(script, *args)
            self.assertEqual(args[0], "mark")
            server_pages[:] = [snapshot()]
            return response

        driver.execute_async_script = mark_on_server
        browser = self.browser(driver)
        browser.scan_unread("synthetic")

        self.assertEqual(browser.mark_read([notice()]), ["100"])
        self.assertEqual(driver.pages[0]["records"], [])

    def test_mark_read_keeps_unconfirmed_rows_out_of_result(self):
        driver = FakeDriver([snapshot([notice()])])
        browser = self.browser(driver)
        browser.scan_unread("synthetic")
        self.assertEqual(browser.mark_read([notice()]), [])

    def test_expired_session_automatically_logs_in_then_reloads_unread(self):
        driver = FakeDriver([snapshot(login=True)])
        driver.on_get = lambda current: setattr(current, "current_url", "https://oa.tyfd.gov.tw/login.php")
        def complete_login(current, account, password, *, attempts):
            self.assertEqual((account, password, attempts), ("tyfd01214", "synthetic", 3))
            current.pages = [snapshot()]
            current.on_get = None
        login = Mock(side_effect=complete_login)
        browser = self.browser(driver, login_runner=login)
        self.assertEqual(browser.scan_unread("synthetic"), [])
        login.assert_called_once()
        self.assertEqual(len(driver.gets), 2)
        self.assertEqual(driver.async_calls, [])
        self.assertEqual(driver.quit_calls, 0)

    def test_session_exceeded_page_opens_canonical_login_before_reauthenticating(self):
        from app_core.notice_collection_browser import OA_LOGIN_URL, UNREAD_URL

        driver = FakeDriver([snapshot(login=False, accountCount=0, account="")])

        def navigate(current):
            if current.current_url == UNREAD_URL:
                current.current_url = "https://oa.tyfd.gov.tw/sess_exceed.php#bulletin/bulletin.php?action=bulletin_list&is_read=0"
            elif current.current_url == OA_LOGIN_URL:
                current.pages = [snapshot(login=True, accountCount=0, account="")]

        def complete_login(current, account, password, *, attempts):
            self.assertEqual(current.current_url, OA_LOGIN_URL)
            self.assertEqual((account, password, attempts), ("tyfd01214", "synthetic", 3))
            current.pages = [snapshot()]
            current.on_get = None

        driver.on_get = navigate
        login = Mock(side_effect=complete_login)
        browser = self.browser(driver, login_runner=login)
        self.assertEqual(browser.scan_unread("synthetic"), [])
        self.assertEqual(driver.gets, [UNREAD_URL, OA_LOGIN_URL, UNREAD_URL])
        login.assert_called_once()
        self.assertEqual(driver.async_calls, [])

    def test_foreign_session_exceeded_page_cannot_trigger_login(self):
        from app_core.notice_collection_browser import UNREAD_URL
        from app_core.notice_collection_service import NoticeCollectionError, NoticeLoginRequired

        driver = FakeDriver([snapshot(origin="https://example.com", login=False, accountCount=0, account="")])
        driver.on_get = lambda current: setattr(current, "current_url", "https://example.com/sess_exceed.php")
        login = Mock()
        with self.assertRaises(NoticeCollectionError) as error:
            self.browser(driver, login_runner=login).scan_unread("synthetic")
        self.assertNotIsInstance(error.exception, NoticeLoginRequired)
        self.assertEqual(driver.gets, [UNREAD_URL])
        login.assert_not_called()

    def test_session_exceeded_login_redirect_must_stay_on_allowed_oa_login(self):
        from app_core.notice_collection_browser import OA_LOGIN_URL, UNREAD_URL
        from app_core.notice_collection_service import NoticeCollectionError, NoticeLoginRequired

        driver = FakeDriver([snapshot(login=False, accountCount=0, account="")])

        def navigate(current):
            current.current_url = ("https://oa.tyfd.gov.tw/sess_exceed.php"
                                   if current.current_url == UNREAD_URL else "https://example.com/login.php")

        driver.on_get = navigate
        login = Mock()
        with self.assertRaises(NoticeCollectionError) as error:
            self.browser(driver, login_runner=login).scan_unread("synthetic")
        self.assertNotIsInstance(error.exception, NoticeLoginRequired)
        self.assertEqual(driver.gets, [UNREAD_URL, OA_LOGIN_URL])
        login.assert_not_called()

    def test_unknown_same_origin_page_is_not_treated_as_session_exceeded(self):
        from app_core.notice_collection_browser import UNREAD_URL
        from app_core.notice_collection_service import NoticeCollectionError, NoticeLoginRequired

        driver = FakeDriver([snapshot(login=False, accountCount=0, account="")])
        driver.on_get = lambda current: setattr(current, "current_url", "https://oa.tyfd.gov.tw/unexpected.php")
        login = Mock()
        with self.assertRaises(NoticeCollectionError) as error:
            self.browser(driver, login_runner=login).scan_unread("synthetic")
        self.assertNotIsInstance(error.exception, NoticeLoginRequired)
        self.assertEqual(driver.gets, [UNREAD_URL])
        login.assert_not_called()

    def test_daily_browser_options_are_actually_headless(self):
        from app_core.notice_collection_browser import NoticeBrowser
        browser = NoticeBrowser(PACKAGE)
        with patch("duty_rehearsal.create_webdriver_chrome_with_timeout") as create, \
                patch("pathlib.Path.mkdir"):
            browser._create_driver()
        options = create.call_args.args[0]
        self.assertIn("--headless=new", options.arguments)
        self.assertTrue(any(a.startswith("--user-data-dir=") for a in options.arguments))

    def test_force_verification_rebuilds_a_fresh_profile_and_uses_new_password(self):
        from app_core.notice_collection_browser import NoticeBrowser
        old, fresh = FakeDriver(), FakeDriver([snapshot(login=True)])
        fresh.on_get = lambda current: setattr(current, "current_url", "https://oa.tyfd.gov.tw/login.php")
        factory = Mock(side_effect=[old, fresh])
        def complete_login(current, account, password, *, attempts):
            current.pages = [snapshot()]
            current.on_get = None
        login = Mock(side_effect=complete_login)
        browser = NoticeBrowser(PACKAGE, driver_factory=factory, login_runner=login)
        self.assertEqual(browser.scan_unread("old-synthetic"), [])
        previous_profile = browser._profile_dir
        browser.begin_login_verification("new-synthetic")
        self.assertEqual(old.quit_calls, 1)
        self.assertNotEqual(browser._profile_dir, previous_profile)
        self.assertEqual(browser.scan_unread("new-synthetic"), [])
        self.assertEqual(login.call_args.args[2], "new-synthetic")
        self.assertEqual(factory.call_count, 2)

    def test_failed_automatic_login_is_bounded_and_does_not_open_another_driver(self):
        from app_core.notice_collection_service import NoticeLoginRequired
        driver = FakeDriver([snapshot(login=True)])
        driver.on_get = lambda current: setattr(current, "current_url", "https://oa.tyfd.gov.tw/login.php")
        login = Mock(side_effect=RuntimeError("synthetic-password must never be included"))
        browser = self.browser(driver, login_runner=login)
        with self.assertRaises(NoticeLoginRequired) as error:
            browser.scan_unread("synthetic-password")
        self.assertNotIn("synthetic-password", str(error.exception))
        self.assertEqual(login.call_args.kwargs, {"attempts": 3})
        self.assertEqual(driver.quit_calls, 0)

    def test_missing_password_does_not_start_a_browser(self):
        from app_core.notice_collection_service import NoticeLoginRequired
        factory = Mock()
        from app_core.notice_collection_browser import NoticeBrowser
        browser = NoticeBrowser(PACKAGE, driver_factory=factory)
        with self.assertRaises(NoticeLoginRequired):
            browser.scan_unread("")
        factory.assert_not_called()

    def test_closed_browser_is_recreated_on_next_cycle(self):
        from selenium.common.exceptions import InvalidSessionIdException
        from app_core.notice_collection_service import NoticeCollectionError
        from app_core.notice_collection_browser import NoticeBrowser
        first, second = FakeDriver(), FakeDriver()
        first.get = Mock(side_effect=InvalidSessionIdException())
        factory = Mock(side_effect=[first, second])
        browser = NoticeBrowser(PACKAGE, driver_factory=factory)
        with self.assertRaises(NoticeCollectionError):
            browser.scan_unread("synthetic")
        self.assertEqual(browser.scan_unread("synthetic"), [])
        self.assertEqual(factory.call_count, 2)
        self.assertEqual(first.quit_calls, 1)

    def test_temporary_navigation_timeout_does_not_start_another_browser(self):
        from selenium.common.exceptions import TimeoutException
        from app_core.notice_collection_service import NoticeCollectionError
        from app_core.notice_collection_browser import NoticeBrowser
        driver = FakeDriver()
        driver.get = Mock(side_effect=[TimeoutException(), None])
        factory = Mock(return_value=driver)
        browser = NoticeBrowser(PACKAGE, driver_factory=factory)
        with self.assertRaises(NoticeCollectionError):
            browser.scan_unread("synthetic")
        self.assertEqual(browser.scan_unread("synthetic"), [])
        self.assertEqual(factory.call_count, 1)

    def test_refresh_timeout_fails_closed_without_starting_another_browser(self):
        from selenium.common.exceptions import TimeoutException
        from app_core.notice_collection_service import NoticeCollectionError
        from app_core.notice_collection_browser import NoticeBrowser
        driver = FakeDriver()
        driver.refresh = Mock(side_effect=[TimeoutException(), None])
        factory = Mock(return_value=driver)
        browser = NoticeBrowser(PACKAGE, driver_factory=factory)

        with self.assertRaises(NoticeCollectionError):
            browser.scan_unread("synthetic")
        self.assertEqual(driver.async_calls, [])
        self.assertEqual(browser.scan_unread("synthetic"), [])
        self.assertEqual(factory.call_count, 1)

    def test_closed_browser_during_refresh_is_recreated_on_next_cycle(self):
        from selenium.common.exceptions import InvalidSessionIdException
        from app_core.notice_collection_service import NoticeCollectionError
        from app_core.notice_collection_browser import NoticeBrowser
        first, second = FakeDriver(), FakeDriver()
        first.refresh = Mock(side_effect=InvalidSessionIdException())
        factory = Mock(side_effect=[first, second])
        browser = NoticeBrowser(PACKAGE, driver_factory=factory)

        with self.assertRaises(NoticeCollectionError):
            browser.scan_unread("synthetic")
        self.assertEqual(first.async_calls, [])
        self.assertEqual(browser.scan_unread("synthetic"), [])
        self.assertEqual(factory.call_count, 2)
        self.assertEqual(first.quit_calls, 1)

    def test_authenticated_session_needs_no_login_attempt_or_visible_browser(self):
        driver = FakeDriver()
        login = Mock()
        browser = self.browser(driver, login_runner=login)
        self.assertEqual(browser.scan_unread("synthetic"), [])
        login.assert_not_called()

    def test_cancel_and_close_do_not_leave_owned_driver_running(self):
        from app_core.notice_collection_service import NoticeCollectionError
        driver = FakeDriver()
        browser = self.browser(driver)
        with self.assertRaises(NoticeCollectionError):
            browser.scan_unread("synthetic", cancel=lambda: True)
        self.assertEqual(driver.gets, [])
        browser.scan_unread("synthetic")
        browser.close()
        browser.close()
        self.assertEqual(driver.quit_calls, 1)

    @unittest.skipUnless(shutil.which("node"), "Node is unavailable for the DOM bridge fixture")
    def test_dom_fixture_parses_metadata_and_rejects_old_filter_grid(self):
        script = r"""
const fs = require('fs');
const run = new Function(fs.readFileSync(process.argv[1], 'utf8'));
const state = {filter:0, empty:false};
const date = {innerText:'115-10-21',getAttribute:name=>name==='rowspan'?'2':null};
const link = {getAttribute:()=>"javascript:changeForm('bulletin_read&id=100');"};
const frame = {src:'https://oa.tyfd.gov.tw/bulletin/bulletin_content.php?id=100'};
const detail = {tagName:'TR',innerText:'',querySelector:s=>s==='iframe'?frame:null,
  querySelectorAll:s=>s==='td'?[]:[]};
const row = {nextElementSibling:detail,innerText:'公告人員：測試隊/測試員',
  querySelectorAll:s=>s==='td'?[{innerText:'',getAttribute:()=>null},date,
    {innerText:'電子通報 download\n 測試主旨\n公告對象全體',getAttribute:()=>null}]:[link]};
const account = {childNodes:[{nodeType:3,textContent:' 新坡分隊/新坡分隊公務信箱(公務信箱) '}]};
const pager = {getAttribute:()=>`changeForm('bulletin_list&is_read=${state.filter}&list_condition=all');`};
global.location={origin:'https://oa.tyfd.gov.tw',hash:'#bulletin/bulletin.php?action=bulletin_list&is_read=0&list_condition=all'};
global.window={location:global.location,jQuery:{active:0}};
global.document={body:{innerText:''},querySelector:()=>null,querySelectorAll:s=>{
  if(s==='.user-menu .user-details')return [account];
  if(s==='p')return [{innerText:`第1/1頁 共${state.empty?0:1}筆`}];
  if(s==='tr')return state.empty?[]:[row,detail];
  if(s.startsWith('a[title='))return [pager];
  return [];
}};
const result=run('snapshot',null);
state.filter=2;
const stale=run('snapshot',null);
state.filter=0;state.empty=true;
const empty=run('snapshot',null);
console.log(JSON.stringify({result,staleFiltered:stale.filtered,empty}));
"""
        asset = PACKAGE / "app_core" / "notice_collection_dom.js"
        completed = subprocess.run([shutil.which("node"), "-e", script, str(asset)],
                                   capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertTrue(result["result"]["filtered"])
        self.assertEqual(result["result"]["records"], [{**notice(), "subject": "測試主旨"}])
        self.assertFalse(result["staleFiltered"])
        self.assertEqual((result["empty"]["total"], result["empty"]["records"]), (0, []))


if __name__ == "__main__":
    unittest.main()
