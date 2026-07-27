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
pythonw duty_gui.pyw
```

## 需要一起帶走的檔案

程式必要檔：

- `duty_gui.py`
- `duty_gui.pyw`
- `duty_rehearsal.py`
- `compare_rehearsal_records.py`
- `duty_sheet_automation.py`
- `daily_vehicle_automation.py`
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
- 目前 GUI 還是預演/審核與登入狀態階段，尚未正式送出登打資料。
