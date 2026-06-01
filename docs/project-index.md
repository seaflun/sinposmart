# Project Index

## Main entry points

- `duty_gui.pyw`: GUI 啟動包裝，呼叫 `duty_gui.main()`。
- `duty_gui.py`: 主要 GUI 與排程托盤程式。
- `start_duty_gui.bat`: Windows 批次啟動檔，執行 `duty_gui.pyw`。
- `RUN_DUTY_GUI_WINPYTHON.bat`: WinPython 可攜環境啟動檔。
- `RUN_DUTY_GUI_WINPYTHON.vbs`: WinPython 無主控台啟動檔。

## Current Python files

| 檔案路徑 | 推測用途 | 是否像正式程式 | 是否像測試 | 是否像暫存/備份 | 建議 |
|---|---|---|---|---|---|
| `duty_gui.py` | GUI、托盤與整合入口 | 是 | 否 | 否 | 保持根目錄，勿任意搬移 |
| `duty_rehearsal.py` | 勤務系統演練與比對流程 | 是 | 否 | 否 | 先讀此檔再改演練邏輯 |
| `compare_rehearsal_records.py` | 比對演練紀錄輸出 | 是 | 否 | 否 | 可列為比對相關優先檔 |
| `export_preview_texts.py` | 匯出預覽文字工具 | 可能 | 否 | 否 | 未確認前勿改執行方式 |
| `check_environment.py` | 環境檢查工具 | 可能 | 否 | 否 | 可移入 `scripts/` 前須確認呼叫方式 |
| `duty_sheet_automation.py` | 勤務表自動化流程 | 是 | 否 | 否 | 保持根目錄，確認排程或捷徑後再動 |
| `daily_vehicle_automation.py` | 每日車輛自動化流程 | 是 | 否 | 否 | 保持根目錄，確認排程或捷徑後再動 |
| `rest_time_automation.py` | 休息時間自動化流程 | 是 | 否 | 否 | 保持根目錄，確認設定檔依賴 |
| `duty_sheet_legacy/sinposmart_1.py` | 舊版勤務表流程 | 可能 | 否 | 是 | 視為 legacy，勿主動改 |
| `daily_vehicle_legacy/automation/ppe_selenium_daily.py` | 舊版每日車輛 Selenium 流程 | 可能 | 否 | 是 | 視為 legacy，勿主動改 |
| `WinPython_公務電腦使用包/duty_gui.py` | 可攜包內 GUI 副本 | 可能 | 否 | 是 | 不要與根目錄版本混改 |
| `WinPython_公務電腦使用包/duty_rehearsal.py` | 可攜包內演練副本 | 可能 | 否 | 是 | 不要與根目錄版本混改 |
| `WinPython_公務電腦使用包/compare_rehearsal_records.py` | 可攜包內比對副本 | 可能 | 否 | 是 | 不要與根目錄版本混改 |
| `WinPython_公務電腦使用包/duty_sheet_automation.py` | 可攜包內勤務表副本 | 可能 | 否 | 是 | 不要與根目錄版本混改 |
| `WinPython_公務電腦使用包/daily_vehicle_automation.py` | 可攜包內每日車輛副本 | 可能 | 否 | 是 | 不要與根目錄版本混改 |
| `WinPython_公務電腦使用包/rest_time_automation.py` | 可攜包內休息時間副本 | 可能 | 否 | 是 | 不要與根目錄版本混改 |
| `WinPython_公務電腦使用包/tools/check_environment.py` | 可攜包內環境檢查工具 | 可能 | 否 | 是 | 不要與根目錄版本混改 |
| `WinPython_公務電腦使用包/duty_sheet_legacy/sinposmart_1.py` | 可攜包內舊版勤務表流程 | 可能 | 否 | 是 | 視為可攜包內容，勿主動改 |
| `WinPython_公務電腦使用包/daily_vehicle_legacy/automation/ppe_selenium_daily.py` | 可攜包內舊版每日車輛流程 | 可能 | 否 | 是 | 視為可攜包內容，勿主動改 |

## Important directories

- `docs/`: 專案文件。
- `tmp/`: 暫存與實驗檔，不要提交。
- `outputs/`: 程式產出檔，不要提交。
- `archive/`: 舊版或備份檔，除非使用者要求，不要主動讀。
- `logs/`: log 檔，不要提交。
- `tests/`: 測試檔。
- `scripts/`: 一次性工具腳本。
- `snapshots/`: 歷次執行快照與比對輸出。
- `screenshots/`: 畫面截圖。
- `issue_reports/`: 問題回報壓縮檔。
- `duty_sheet_legacy/`: 舊版勤務表流程與設定。
- `daily_vehicle_legacy/`: 舊版每日車輛流程與 Selenium artifacts。
- `WinPython_公務電腦使用包/`: 公務電腦可攜執行包。
- `_整理封存/`: 既有封存資料，除非要求不要主動讀。

## Files Codex should read first

- `AGENTS.md`
- `HANDOFF.md`
- `CODE_MAP.md`
- `requirements.txt`
- `start_duty_gui.bat`
- `duty_gui.pyw`
- `duty_gui.py`
- `duty_rehearsal.py`
- `compare_rehearsal_records.py`
- `duty_sheet_automation.py`
- `daily_vehicle_automation.py`
- `rest_time_automation.py`
- `rest_time_automation_config.json`

## Files Codex should avoid unless asked

- `archive/`
- `tmp/`
- `outputs/`
- `logs/`
- `cache/`
- `.venv/`
- `venv/`
- `__pycache__/`
- `snapshots/`
- `_整理封存/`
- `WinPython_公務電腦使用包/`
- `daily_vehicle_legacy/.env`
- `duty_sheet_legacy/effortless-leaf-353501-63492cc3ece4.json`
- `WinPython_公務電腦使用包/duty_sheet_legacy/effortless-leaf-353501-63492cc3ece4.json`

## Build / run / test commands

- 安裝依賴：`py -m pip install -r requirements.txt`
- 啟動 GUI：`start_duty_gui.bat`
- 啟動 WinPython 可攜版：`RUN_DUTY_GUI_WINPYTHON.bat`
- Python 語法檢查範例：`py -m py_compile duty_gui.py duty_rehearsal.py compare_rehearsal_records.py duty_sheet_automation.py daily_vehicle_automation.py rest_time_automation.py`

目前未看到 `pyproject.toml`、`setup.py`、`package.json` 或正式測試指令設定。

## Known risks

- `daily_vehicle_legacy/.env`: 敏感環境設定，不能讀取或提交。
- `daily_vehicle_legacy/.env.example`: 範例設定，修改前仍需確認是否含真實資訊。
- `duty_sheet_legacy/effortless-leaf-353501-63492cc3ece4.json`: 檔名疑似 Google service account 憑證，不能讀取或提交。
- `WinPython_公務電腦使用包/duty_sheet_legacy/effortless-leaf-353501-63492cc3ece4.json`: 可攜包內疑似憑證副本，不能讀取或提交。
- `start_duty_gui.bat`、`duty_gui.pyw`、`RUN_DUTY_GUI_WINPYTHON.bat`、`RUN_DUTY_GUI_WINPYTHON.vbs` 可能被捷徑或使用者習慣呼叫，勿任意更名或搬移。
- 根目錄自動化檔可能被排程器呼叫：`duty_gui.py`、`duty_sheet_automation.py`、`daily_vehicle_automation.py`、`rest_time_automation.py`。
- `WinPython_公務電腦使用包/` 內有正式可攜副本，與根目錄檔案可能不同步，整理前需人工確認來源版本。
