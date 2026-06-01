# 值班勤務系統自動化交接紀錄

更新時間：2026-05-19 09:41

## 另一台電腦開始前

1. 等 Google Drive 顯示同步完成。
2. 在本資料夾開 PowerShell。
3. 執行：

```powershell
PowerShell -ExecutionPolicy Bypass -File .\sync_project_skills_before_use.ps1
```

4. 再執行環境檢查：

```powershell
py check_environment.py
```

5. 若要開 GUI：

```powershell
.\start_duty_gui.bat
```

## 2026-05-19 本機變更

### skill 同步規則

- 新增 `AGENTS.md`
- 新增 `sync_project_skills_before_use.ps1`
- 規則：每次在本專案開始工作前，先掃描雲端 `專案\skill` 內所有含 `SKILL.md` 的 skills，全部同步到本機 `%USERPROFILE%\.codex\skills` 後再使用。
- 雲端安裝腳本位置：`G:\我的雲端硬碟\專案\skill\install-skills-from-cloud.ps1`
- 目前會同步 10 個 skills。

### GUI 觸發狀態修正

修改 `duty_gui.py`：

- 第 314 行：按鈕文字由 `提前登打` 改成 `提前記錄`。
- 第 810-840 行：任務狀態由像是已執行的 `已觸發` 改成 `已記錄`，登入狀態也改成「到點後會記錄待接線任務」。
- 第 857-891 行：新增 `log_trigger()`，把到點或手動提前記錄的任務寫入 `duty_trigger_log.jsonl`。

這個修正的目的：目前系統尚未接上真正新增/儲存勤務紀錄的自動化，不能讓畫面誤導使用者以為已寫入勤務系統。

## 目前重要檔案

- `duty_rehearsal.py`：登入勤務系統、讀勤務表、案件、既有工作紀錄和出入紀錄，產生預演 actions。只讀，不儲存。
- `duty_gui.py`：Tkinter 控制台，載入預演 JSON、顯示任務、登入值班人員、到點記錄待接線任務。
- `duty_gui.pyw`：GUI 入口。
- `compare_rehearsal_records.py`：比對預演 actions 與系統既有紀錄。
- `export_preview_texts.py`：把預演 JSON 輸出成人可讀文字稿。
- `check_environment.py`：檢查 Python、Tkinter、Selenium、Chrome / ChromeDriver。
- `rehearsal_output_1150518.json`：目前主要測試資料。
- `snapshots\verify_compare_1150518.txt`：2026-05-19 產生的比對驗證檔。

## 已驗證

```powershell
py -m py_compile duty_gui.py duty_gui.pyw duty_rehearsal.py compare_rehearsal_records.py export_preview_texts.py check_environment.py
py compare_rehearsal_records.py rehearsal_output_1150518.json --out snapshots\verify_compare_1150518.txt
```

兩個命令都已在本機通過。

## 尚未完成

- GUI 尚未真正新增或儲存勤務系統資料。
- `提前記錄` 和到點流程目前只寫入本機 `duty_trigger_log.jsonl`。
- 下一步建議先做「填表但不儲存」：開啟新增頁、填入欄位、檢查欄位對應，再決定是否接上最後儲存按鈕。

## 2026-05-19 資料拆檔規則

- `schedule_output_日期.json`：只保存依勤務表、案件資料推導出的排程 actions。
- `comparison_output_日期.json`：只保存工作紀錄簿、出入暨領用無線電機登記簿的既有登打查詢結果。
- 舊的 `rehearsal_output_日期.json` 仍可讀，但新流程不再把排程和比對資料混在同一個檔案。
- 登入時只讀本機既有排程檔，不查勤務系統，避免影響登入時間。
- 每天 22:00 後背景查詢隔日勤務表並產生隔日 `schedule_output_日期.json`。
- 已登入狀態下，每小時整點前 5 分鐘內背景更新一次 `comparison_output_日期.json`。
- 這些 JSON 屬於 Google Drive 同步資料，已加入 `.gitignore`，不靠 Git 提交版本。

## 比交接文件更好的方法

最佳做法是把本資料夾變成 Git repo。Google Drive 負責同步檔案，Git 負責記錄每次改了哪些行、可以回復版本、也能讓兩台電腦先看差異再繼續。

建議流程：

```powershell
git init
git add .
git commit -m "Initial duty automation workspace"
```

之後每次工作完成：

```powershell
git status
git diff
git add <changed-files>
git commit -m "Describe the change"
```

如果暫時不使用 Git，就至少每次工作後更新本檔案。
