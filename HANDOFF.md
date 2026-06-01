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

## 2026-05-25 進度更新

### 已完成

- 已依 `AGENTS.md` 先同步雲端 `專案\skill`，本次確認並安裝 10 個含 `SKILL.md` 的 skills；本機既有 skill 已先備份到 `%USERPROFILE%\.codex\skills\_backups`。
- 核心 GUI 已改為 `SinpoSmart` 顯示名稱，加入系統匣圖示、關閉視窗時縮到系統匣、Windows 通知標題與單一執行個體鎖。
- 登入流程加入本機帳密記憶功能，使用 Windows DPAPI 保護已儲存帳密，並保留手動輸入流程。
- 值班模式已加強自動登打佇列、到點執行、登打前重查比對、失敗時產生 `issue_reports` 壓縮包。
- 比對邏輯已補強休息、返隊、外勤、案件工作紀錄與近似時間判斷，降低錯把既有紀錄列為待補登的機率。
- 已新增 `duty_sheet_automation.py`，把舊勤務表登打流程包成 SinpoSmart 內嵌視窗，先沿用舊專案核心，不重寫舊 Selenium 流程。
- 公務電腦使用包、WinPython 啟動批次檔、環境檢查與相依套件清單已更新到目前 SinpoSmart 需求。

### 目前驗證

- `py -m py_compile duty_gui.py duty_gui.pyw duty_rehearsal.py compare_rehearsal_records.py export_preview_texts.py check_environment.py duty_sheet_automation.py` 通過。
- 目前已有 `schedule_output_1150519.json` 到 `schedule_output_1150522.json`、`comparison_output_1150518.json` 到 `comparison_output_1150523.json` 可作為近期比對資料。
- `issue_reports` 內已有 2026-05-21 的失敗封包，可用來追查當時自動登打或比對問題。

### 目前風險

- 工作樹仍有大量未提交變更，包含核心程式、文件、公務電腦包與測試輸出；提交前需再確認哪些檔案要納入版本控管。
- `HANDOFF.md` 舊段落在目前 PowerShell 顯示為亂碼，本次只追加新段落，沒有重寫舊內容。
- `duty_sheet_automation.py` 仍依賴舊 `duty_sheet_legacy\sinposmart_1.py`，正式使用前應先在測試模式確認 Excel、車輛欄位與 LINE/GCS 設定。

### 下一步

1. 在勤務電腦執行 `SETUP_WINPYTHON.bat` 與 `RUN_DUTY_GUI_WINPYTHON.vbs`，確認無 console 啟動、系統匣、通知與 Chrome 啟動正常。
2. 用實際帳號跑登入、查詢、審核模式，先確認比對結果符合勤務系統既有紀錄。
3. 若自動登打失敗，優先保留最新 `issue_reports\issue_report_*.zip`，再回頭看提交前重查比對與欄位填入流程。
4. 核心值班登打穩定後，再逐步驗證勤務表登打視窗，不要同時打開多個新功能問題。
