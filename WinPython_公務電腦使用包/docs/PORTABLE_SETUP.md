# 換電腦執行說明

## 需要準備

1. WinPython 或 Python 3.11 以上
2. Google Chrome
3. Python 套件：

```powershell
python -m pip install -r requirements.txt
```

## 第一次檢查

在專案資料夾執行：

```powershell
python check_environment.py
```

看到最後一行 `[OK] Environment check passed. Start SinpoSmart with duty_gui.pyw.` 就表示基本環境可用。

## 啟動 GUI

公務電腦正式啟動建議雙擊：

```text
RUN_DUTY_GUI_WINPYTHON.vbs
```

或直接執行：

```powershell
python duty_gui.pyw
```

## 緊急 Tk 回退

只有在 QML 正式介面無法使用、且已確認需要回退時，才使用 `legacy_tk/`。它不會被正式啟動器載入，也不會隨 QML 的基本安裝自動安裝相依套件。

先在套件根目錄使用同一份 WinPython 安裝回退介面的選用套件：

```powershell
python -m pip install -r legacy_tk\requirements.txt
```

接著以同一份 WinPython 的 `pythonw.exe` 開啟 `legacy_tk\duty_gui.py`，例如：

```powershell
& "D:\WinPython-3.11.9\python-3.11.9.amd64\pythonw.exe" .\legacy_tk\duty_gui.py
```

這是暫時的相容回退，不是日常正式入口；問題排除後仍應回到 `duty_gui.pyw`。

## 需要一起帶走的檔案

程式必要檔：

- `duty_gui.pyw`：PySide6 + QML 正式入口
- `qt_app/`：QML 介面、controller、model 與 worker
- `app_core/`：登入、班表、登打、同步與診斷服務
- `duty_gui.py`：QML 相容入口
- `legacy_tk/`：已隔離的 Tk 回退介面與其選用依賴；更新包會保留它，但正式啟動不會載入它
- `duty_rehearsal.py`
- `compare_rehearsal_records.py`
- `rest_time_automation.py`
- `requirements.txt`
- `check_environment.py`
- `find_winpython.ps1`
- `SETUP_WINPYTHON.bat`
- `RUN_DUTY_GUI_WINPYTHON.bat`
- `RUN_DUTY_GUI_WINPYTHON.vbs`

資料檔可選：

- `rehearsal_output_*.json`：已有的預演/審核快照
- `snapshots/`：歷次自動查詢快照
- `*_preview.txt`、`*_compare_report.txt`：文字報表

不用把帳號密碼寫進檔案。每位值班人員在 GUI 登入即可。

## 注意

- Selenium 會自動處理 ChromeDriver，但電腦必須能啟動 Chrome。
- 若公司或機關電腦封鎖 Selenium Manager 下載驅動，環境檢查會卡在 ChromeDriver 啟動失敗；那時再改成手動放置 `chromedriver.exe`。
- 正式 GUI 會在登入後即時讀取勤務與比對資料；自動登打仍會先做重複查詢與送出後驗證。
