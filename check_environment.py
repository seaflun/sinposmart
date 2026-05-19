# -*- coding: utf-8 -*-
"""Quick environment check for the duty automation GUI."""

from __future__ import annotations

import importlib.util
import platform
import sys
import tkinter as tk

from selenium import webdriver
from selenium.webdriver.chrome.options import Options


def ok(message: str) -> None:
    print(f"[OK] {message}")


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    raise SystemExit(1)


def main() -> int:
    version = sys.version_info
    if version < (3, 11):
        fail(f"Python 版本過舊：{platform.python_version()}，建議 3.11 以上。")
    ok(f"Python {platform.python_version()}")

    try:
        root = tk.Tk()
        root.withdraw()
        root.destroy()
    except Exception as exc:
        fail(f"Tkinter GUI 不可用：{exc}")
    ok("Tkinter GUI 可用")

    selenium_spec = importlib.util.find_spec("selenium")
    if selenium_spec is None:
        fail("找不到 selenium，請先執行：python -m pip install -r requirements.txt")
    ok("Selenium 已安裝")

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--window-size=1280,900")
    try:
        driver = webdriver.Chrome(options=options)
        driver.get("about:blank")
        driver.quit()
    except Exception as exc:
        fail(f"Chrome / ChromeDriver 啟動失敗：{exc}")
    ok("Chrome / ChromeDriver 可啟動")

    ok("環境檢查完成，可以執行 duty_gui.pyw")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
