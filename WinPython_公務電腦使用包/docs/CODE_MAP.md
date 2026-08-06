# SinpoSmart_值班台程式地圖

本文件記錄 2026-07-29 PySide6 + QML 正式架構，以及仍保留的 Tk 回退邊界。

## 正式啟動路徑

- `duty_gui.pyw`：QML 正式入口，只呼叫 `qt_app.main.main()`；無黑窗由 VBS 隱藏啟動鏈負責。
- `qt_app/main.py`：載入 `.env`、建立 QApplication、單一執行個體鎖、QML engine、系統匣及 AppController。
- `qt_app/qml/Main.qml`：Apple-inspired 直向主介面；保留原介面的登入、值班、審核、工具與設定操作順序，並以全域 design token、共用控制項及 `AppleDialog` 統一畫面格式。
- `check_environment.py`：正式 Qt runtime 與 Chrome/ChromeDriver 檢查；不把舊 Tk GUI 套件列為 Qt 啟動條件。

## qt_app

- `controllers/app_controller.py`：QML 唯一 context facade，協調 session、排程、登打、工具、同步、更新與系統匣；不直接執行 Selenium。
- `controllers/session_controller.py`：登入 Slot 僅接受帳號、密碼及記住設定；包含 single-flight、120 秒安全逾時、逾時 worker 清理期間的重試阻擋、帳號選擇、DPAPI 儲存、登出與帳密同步確認，勤務番號只由登入後既有勤務網站查詢自動回填。
- `controllers/duty_controller.py`：任務投影、勤務查詢 `isRefreshing` 狀態、審核日期、手動暫停／恢復、到點判定與自動登出條件。
- `controllers/duty_execution_controller.py`：正式登打的 entry/work 雙通道佇列。
- `controllers/rescue_video_controller.py`：救護行車影片預覽、分類、來源清理二次確認與結果狀態協調。
- `controllers/tool_controller.py`：原生工具目錄與可用狀態；正式 Qt 路徑不啟動任何外部 Tk 工具視窗。
- 其他 controllers：勤務表、每日車輛、休息時間、勤務基準表、更新、工具、系統匣與工作紀錄設定。
- `models/`：QML 使用的帳號、工具、勤務任務與救護影片結果 ListModel。
- `workers/`：登入、帳密同步、即時勤務查詢、正式登打、工具、後台事件／值班看板同步、排程資料夾及更新檢查的 QThread worker；避免阻塞 QML 主執行緒，並由 Controller 在結束程式時等待清理。

## app_core

UI 無關服務層，不 import `duty_gui`、Tkinter 或 CustomTkinter：

- `login_verifier.py`、`session.py`、`credential_repository.py`、`credential_sync_service.py`：登入與帳密邊界，不重複實作勤務表番號查詢。
- `schedule_capture_service.py`、`schedule_repository.py`、`duty_task_projection.py`：沿用 `duty_rehearsal` 取得即時勤務快照，再由網站登入身分與當日 `staff` 自動回填番號，並負責本機排程與任務投影。
- `duty_submission_service.py`：重複檢查、填表、儲存與儲存後驗證。
- `duty_sheet_service.py`、`daily_vehicle_service.py`、`rest_monthly_service.py`：勤務表、每日車輛、休息時間與勤務基準表工具流程。
- `rescue_video_service.py`：不載入 Tk UI 的救護影片分類邊界，沿用既有分類核心並限制預覽／確認後清理模式。
- `work_log_settings_service.py`：工作紀錄預設值、未返隊案件車數例外與描述預覽。
- `operational_sync_service.py`、`diagnostics_service.py`：後台事件、值班看板與去敏問題包。
- `scheduled_folder_service.py`：16:30／21:55 Windows 截圖資料夾排程。

## duty_gui.py（回退）

舊 Tkinter／CustomTkinter 主程式目前保留作為回退與行為參考。正式 Qt 入口不 import 此檔；不要把新 QML 功能再橋接回隱藏 Tk 視窗。

目前區塊：

- `Paths and date helpers`：預設檔案、日期、排程與比對檔路徑。
- `Session model`：目前登入 session。
- `Main GUI controller`：主視窗類別。
- `Layout construction`：視覺樣式、登入卡片、值班模式與審核模式版面。
- `Review data loading and date controls`：審核模式日期切換、排程讀取、比對資料讀取。
- `Saved account management`：本機帳號清單、帳號選擇小視窗。
- `Login, snapshots, and background refresh`：登入驗證、D-1/D/D+1 排程抓取、工作出入背景比對。
- `Login state and duty identity`：已登入文字、今日值班時段、登入/登出狀態切換。
- `Duty-mode task rendering and selection`：值班模式任務表、時間顯示、多選與到點觸發。
- `Submit pipeline`：提前登打佇列、瀏覽器提交、結果回寫。
- `Mode switching and audit table rendering`：值班/審核模式切換、篩選、審核表狀態。
- `Labels, summaries, and detail rendering`：番號姓名、內容摘要、下方明細。

## duty_rehearsal.py

勤務系統瀏覽器自動化與排程規則核心，負責讀勤務表、讀案件、規劃工作/出入任務、填入勤務系統。

目前區塊：

- `Data models`：勤務表、案件、預計任務資料模型。
- `Date, roster, and radio helpers`：民國日期、番號清理、無線電代碼。
- `Browser navigation helpers`：勤務系統 AP 頁面切換與登入錯誤偵測。
- `People picker helpers`：人員欄位直接設定與彈窗選人。
- `Form controls and submit helpers`：新增、儲存按鈕與表單控制項快照。
- `Work log automation`：工作紀錄填表。
- `Entry log automation`：出入紀錄填表。
- `Manual inspection tools`：手動檢查頁面格式用工具。
- `Login and query readers`：登入、勤務表、工作出入、案件查詢。
- `Duty table interpretation`：勤務表時段、人員、休息、外勤區間判定。
- `Work log text templates`：交接、無線電、在隊訓練等工作內容文字。
- `Actor selection and planned actions`：由勤務表決定登打人與產生排程任務。
- `CLI helpers`：命令列測試與摘要輸出。

## compare_rehearsal_records.py

審核模式比對器，負責把排程任務與勤務系統已登打資料比對，輸出審核狀態。

目前區塊：

- `Normalization helpers`：清理文字、姓名與頁面資料。
- `Date and time matching`：任務日期、跨日與近似時間比對。
- `Entry record matching`：出入紀錄比對。
- `Work and case matching`：工作紀錄、救護救災案件工作比對。
- `Display summaries`：審核表摘要文字。
- `Report builder`：整份比對報告組裝。
- `CLI entrypoint`：命令列入口。

## duty_sheet_automation.py

勤務表登打內嵌視窗，負責從 SinpoSmart 值班模式開啟勤務表登打表單，並呼叫包內 `duty_sheet_legacy\sinposmart_1.py` 核心流程。

目前定位：

- 內嵌小視窗由 `open_duty_sheet_dialog(...)` 建立，視覺風格接近值班模式。
- 外層值班模式若已登入，會把目前 session 帳號密碼帶入小視窗。
- 勤務表核心、`config.json`、service account JSON 與範例 Excel 已複製到 `duty_sheet_legacy`，公務包可獨立使用。
- 若本機包內找不到 `duty_sheet_legacy`，才回退搜尋同層舊專案 `勤務表自動化`。
- 不直接使用舊 GUI 的 `__main__` 區塊，避免舊 Tk globals 取代目前 SinpoSmart 主視窗。

## 後續重構原則

後續應沿用目前邊界：

1. QML 只做顯示與使用者操作，不持有帳密或 Selenium driver。
2. Controller 只協調狀態與 worker，不把長時間工作放在 GUI thread。
3. 可單元測試的規則留在 `app_core`；既有網站欄位規則仍以 `duty_rehearsal.py` 為唯一來源。
4. 未經使用者確認，不刪除 `duty_gui.py` 或其他回退檔案。

每次拆檔後都應先跑：

```powershell
py -3 -m compileall -q .\app_core .\qt_app
pyside6-qmllint .\qt_app\qml\Main.qml
py -3 -m unittest tests.test_smoke tests.test_qt_shell tests.test_credential_repository
```
