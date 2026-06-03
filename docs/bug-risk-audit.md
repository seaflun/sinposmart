# BUG 風險追蹤

更新日期：2026-06-03

## 目前最高風險

1. Google Drive 公開更新檔尚未同步到本機新版。
   - 本機 `UPDATE/VERSION.txt`：`2026.06.03.1552`
   - 公開 `VERSION.txt` 讀回：`2026.06.03.0843`
   - 公開 ZIP 內 `VERSION.txt` 讀回：`2026.06.03.0843`
   - 影響：公務電腦可能仍下載舊版，拿不到最新修補。
   - 狀態：未解，需等 Google DriveFS 同步或手動重新上傳固定 Drive file ID。

2. `.git/packed-refs.lock` 持續存在。
   - 影響：`git push` 已成功，但 Git 在 `pack-refs` 維護階段會報錯。
   - 狀態：未解；依專案規則不得未確認刪檔。

3. 外部系統流程尚未完整實站驗證。
   - 涉及：勤務系統登入與登打、每日車輛 Selenium、LINE/GCS 發送。
   - 影響：本機編譯與靜態測試通過，不代表外部網站流程一定成功。
   - 狀態：待實機帳密與外部服務驗證。

## 已修正並有回歸檢查

1. 自動登打成功後顯示為「已手動登打」。
   - 修正：自動 due 完成顯示「已登打」，手動完成才顯示「已手動登打」。
   - 回歸檢查：`tests/test_static_regressions.py::test_manual_and_due_completion_statuses_stay_distinct`

2. 登打失敗回呼少傳 `trigger_type`。
   - 修正：`_save_work_log_item_failed()` 的延遲回呼補上 `trigger_type`。
   - 影響：失敗時可正確清除「正在登打」、顯示錯誤、設定 due retry。
   - 回歸檢查：`tests/test_static_regressions.py::test_submit_failure_callbacks_pass_trigger_type`

3. `except as exc` 被 lambda 延遲捕捉後失效。
   - 修正：已改成先轉成字串或用 lambda default 捕捉。
   - 回歸檢查：`tests/test_static_regressions.py::test_except_variables_are_not_captured_by_delayed_lambdas`

4. 公務電腦啟動批次檔硬編碼 Python 路徑。
   - 修正：改用 WinPython 探測與 PATH fallback。
   - 驗證：`py check_environment.py`

5. 公務包更新器 ZIP file ID 指到舊檔。
   - 修正：`WinPython_公務電腦使用包/update_package.ps1` 改指目前 Drive 資料夾內 canonical ZIP file ID。
   - 補強：更新器下載 ZIP 後會檢查 ZIP 內 `VERSION.txt` 必須等於遠端 `VERSION.txt`，不一致就中止。
   - 補強：更新器永遠跳過勤務表設定、Google service account、每日車輛 `.env`，避免更新包誤帶本機設定或憑證。
   - 仍需：公開 Drive 檔案內容同步到新版。

## 仍可能出錯的點

1. 背景執行緒結束時 GUI 已關閉。
   - 風險：Tk `after()` 或 messagebox 可能在視窗銷毀後拋錯。
   - 已處理部分：每日車輛、勤務表、休假/月基本時數對話框已有 `winfo_exists()` 包裝。
   - 待觀察：主 GUI 的排程快照與比對 worker 仍依賴主視窗存活。

2. 防重複比對資料過期。
   - 風險：自動登打前比對快照若過舊，可能誤判已存在或漏判重複。
   - 已處理部分：成功/略過後會排程重新比對。
   - 待驗證：外部勤務系統資料刷新速度。

3. 休假/月基本時數 Excel 檔案被使用者開啟。
   - 風險：Excel workbook lock 或路徑空白造成讀取失敗。
   - 已處理部分：設定檔不再保存個人下載路徑；讀取流程補 `wb.close()`。
   - 待驗證：實際 Excel 檔被開啟時的錯誤提示是否清楚。

4. Google DriveFS 同步延遲或網路錯誤。
   - 風險：本機 `UPDATE` 檔已更新，但公開 URL 仍是舊版。
   - 已觀察：DriveFS log 曾出現 `NETWORK_TRANSPORT_ERROR`。
   - 待處理：同步完成後重新讀回公開版本。

5. 缺少完整 Selenium 整合測試。
   - 風險：網站欄位、文字、按鈕 ID 或登入流程改版時，靜態測試抓不到。
   - 已處理部分：新增靜態回歸測試。
   - 待處理：用測試帳號或實機流程做端到端驗證。

## 目前可重跑的檢查

```powershell
py tests\test_static_regressions.py
py check_environment.py
py -m py_compile duty_gui.py duty_gui.pyw duty_rehearsal.py compare_rehearsal_records.py duty_sheet_automation.py daily_vehicle_automation.py rest_time_automation.py check_environment.py
```
