# SinpoSmart_值班台交接紀錄

更新時間：2026-05-19 09:41

> 2026-07-29 現況：正式 GUI 已改由 `duty_gui.pyw` 啟動獨立的 PySide6 + QML 架構；下方 2026-05-19 內容保留為歷史紀錄，不再代表目前執行狀態。

## 2026-07-29 PySide6 + QML 交接重點

- 正式入口：`RUN_DUTY_GUI_WINPYTHON.vbs` → 隱藏執行 `RUN_DUTY_GUI_WINPYTHON.bat` → `python.exe duty_gui.pyw`。
- `duty_gui.pyw` 只呼叫 `qt_app.main.main()`；不建立或隱藏 Tk 主視窗。
- QML 介面位於 `qt_app\qml\Main.qml`，登入、任務、審核、工具、帳號、更新與設定由 `qt_app\controllers` 對接。
- UI 無關的帳密、排程、登打、診斷、同步、工具及排程資料夾邏輯位於 `app_core`。
- `duty_gui.py` 僅保留為舊 Tk 回退介面，不是正式啟動入口，也不會被 Qt 應用 import。
- 正式登入 Slot 只接受帳號、密碼與是否記住帳號；成功後由既有 `duty_rehearsal` 即時查詢網站登入身分及勤務資料，再以當日 `staff` 自動回填番號。登入表單及 Python 登入契約都不接受人工番號，也不提供人工番號確認卡。讀取本機舊排程或查詢歷史日期都不會啟用正式自動登打。
- 每日 16:30 開啟 `每日勤務表`、21:55 開啟 `夜間勤務`；Windows 桌面及資料夾操作在背景執行。
- 已提供只讀登入驗收模式；2026-07-29 已由使用者親自輸入授權帳密，確認真實登入成功，且程式成功讀回 `schedule_output_1150729.json`。自動番號查詢已改為只讀開啟網站既有工作紀錄新增頁，依登入帳號取得本人姓名後對應當日 `staff`；不按儲存或送出，也不顯示人工番號卡。相同 Session 已顯示 `1150729` 的真實審核任務與明細對話框。正式登打、NAS 事件與 Google 值班看板仍未驗收。

目前驗證命令：

```powershell
py -3 -m compileall -q app_core qt_app
pyside6-qmllint qt_app\qml\Main.qml
py -3 -m unittest tests.test_smoke tests.test_qt_shell tests.test_credential_repository tests.test_rescue_video_tool
```

2026-07-29 本機驗證結果：本次正式測試集合 201/201 通過，QML lint、Python 編譯、QML 根視窗、官方入口啟動與只讀正常退出皆通過；正式 `check_environment.py` 已實跑確認 Python、PySide6/QML runtime 與 Chrome/ChromeDriver，且不再匯入或建立 Tk GUI。Qt 入口會在 Windows 明確保留 PySide6 DLL 搜尋目錄，以確保 Qt Quick Controls 外掛可載入。一般登入與定時勤務查詢使用背景 Chrome；Qt 登入安全逾時為 120 秒，避免 Chrome 啟動或網站稍慢時在 Selenium 尚未完成前誤顯示登入失敗。逾時 worker 尚未真正退出前 `isBusy` 會保持啟用，第二次登入不會再建立另一個 Chrome；worker 清理後才允許重試，晚到結果仍會被拒絕。勤務與審核重新查詢期間由 `isRefreshing` 禁用日期切換與重複查詢，按鈕會立即顯示「更新中…」，worker 清理後才恢復。勤務查詢會在已驗證 AP 頁面比對網站登入身分與當日 `staff`；若登入階段尚未取得番號，會只讀開啟網站工作紀錄新增頁，以登入帳號比對既有人員欄位，再用記憶體 metadata 回填 Session，不改勤務 JSON 格式。QML 垂直測試已從帳密欄點擊一次登入，驗證只呼叫一次 LoginWorker、一次 ScheduleCaptureWorker，自動回填番號、清空密碼欄，並確認兩組 worker 都完成清理；另有「只開新增頁、不呼叫儲存」測試。登入、勤務查詢、登打、工具、更新與設定的錯誤 Signal 已統一接到可關閉的非阻斷錯誤橫幅，並以實際 QML 顯示及點擊關閉測試驗證。QML 行為測試另實際點擊任務列、手動暫停、繼續排程及手動登打按鈕，驗證確認視窗可開啟及取消且不送出資料；「下一項任務」亦依舊版規則從已載入排程自動計算，完成、暫停或人工確認項目不會列入。勤務表、休息時間及勤務基準表的 QML Service 在載入既有執行核心時，已不再載入 tkinter、CustomTkinter 或 tkcalendar；舊視窗程式只在舊入口實際開啟時才延後匯入。勤務表原生 QML 表單亦已補回消防車／救護車選項新增與移除，沿用 `car_options`、`hidden_car_options` 及既有選擇格式。救護行車影片工具已改為原生 QML 表單、結果 Model、背景 Worker 與刪除前二次確認，並沿用既有分類核心；驗收只使用假資料與預覽結果，不讀寫正式記憶卡或網路磁碟。QML 垂直工具測試已實際點擊勤務表、休息時間、勤務基準表與車輛保養的執行鍵，接受確認視窗後驗證各自 worker 只執行一次並清理；救護影片亦驗證 QML 預覽鍵、worker 與結果 Model 回填。所有工具均用假服務，未登入或送出正式資料。`ToolController` 的外部程序啟動器已移除，正式 Qt facade 無法再叫出舊 Tk 工具視窗。番號尚未回填時不啟用自動登打，頁面提示內容不寫入 log。另有未追蹤的 `tests/test_rescue_video_tool.py` 共 4 項測試屬其他未完成工作，未納入本次 201 項集合。

2026-07-29 後續驗證：正式測試集合增為 211/211 通過，QML lint 與 Python 編譯仍通過。五個工具的原生表單改為舊版固定主區加右側工具欄，不再以中央 Dialog 中斷主畫面；正式登打與來源清理的二次確認仍保留 Dialog。工具實際開始、成功與失敗已恢復舊版 `tool_action_started` / `tool_action_finished` 後台事件契約，包含 `tool_start` / `tool_finish`、工具名稱、顯示標籤、完成內容或失敗訊息；單純表單驗證錯誤不會誤報為工具執行失敗。登打事件已改回後台實際接受的 `action_queued` / `action_result`，保留自動或手動觸發類型、action 與 completion key；背景勤務與比對更新亦改回後台白名單的 `schedule_snapshot` / `comparison_snapshot`，不再送出會被視為錯誤的 `schedule_refresh`。一般登入失敗與逾時會送出不含密碼的 `login_failed`；背景勤務查詢若判定 Session 失效，會送出排程錯誤與 `login_expired`、清除 Session 並停止自動登打，不改載離線排程假裝仍可執行。更新前登出已保留最後登入身分與舊版 `logout` 事件格式；系統匣補回「縮小到背景」，預演與更新中狀態不再誤稱執行器未啟用。審核模式已補回舊版「載入預演 JSON」，檔案由 `ScheduleLoadWorker` 在背景經 `ScheduleRepository` 驗證後載入；預演期間關閉自動登打，回到值班模式才重新擷取正式當日勤務。

2026-07-29 完整生命週期補驗：正式測試集合再增為 213/213 通過。更新前登出事件改為同步寫入，確保更新程式終止 GUI 前事件已送達；背景正式登打失敗會保留結果 JSON 路徑，並自動匯出去敏 allowlist 問題包供後續診斷。這些驗證均使用 fake／離線測試，未再次登入或寫入正式勤務網站。

2026-07-29 跨日資料對齊：正式測試集合增為 214/214。Qt 即時勤務擷取改為沿用同一個已登入 WebDriver，一次建立前一日、當日與次日三份 `schedule_output_*.json` 及 `comparison_output_*.json`，後台 `schedule_snapshot` 亦回報三日摘要。這恢復舊版登入後維護三日勤務視窗的行為，同時避免為三個日期重複開啟瀏覽器；若整點前五分鐘恰逢其他勤務擷取執行中，整點更新不會被誤標為完成，而會在下一次計時檢查重試。

值班主畫面依舊版正式提交 `853512c` 還原為固定主區：未登入 `550×320`、登入後 `550×800`、審核模式 `780×650`；「每日作業」與「每月作業」兩列快捷鍵只在登入後顯示。勤務表、車輛保養、休息時間與勤務基準表會在主區右側增加 400 px 工具欄，使外框成為 `964×800`，主區寬度不變且不被遮住；行車紀錄器則開啟獨立非模態視窗。QML 行為測試已實際點擊五個快捷鍵，確認四個側板的開啟／關閉、外框尺寸與主區寬度，以及行車紀錄器獨立視窗。

2026-07-30 介面契約修正：勤務表、車輛保養、休息時間與勤務基準表由主視窗右側展開 400 px 工具欄，固定 550 px 主區不縮窄；行車紀錄器因檔案與結果內容較多，改為獨立非模態視窗，不屬右側工具欄。登入錯誤只顯示於登入區底部原有訊息列，不建立會擠壓視窗的頂部錯誤列；登入後該列固定顯示 Session 的「已登入：職稱 姓名」與時段，不再被勤務查詢、工具或案件載入錯誤覆蓋，並維持舊版 24 px 單行高度。審核模式頂部已恢復舊版「預演 JSON／選擇／載入」，選擇只回填可編輯路徑，按下「載入」後才以背景 worker 讀取並停用自動登打。首次帳號尚無番號時也會先背景載入當日本機快照，使用登入頁已辨識的姓名在 `staff` 唯一對應番號、職稱與任務；完整網站查詢繼續在背景執行，成功後優先於較晚完成的舊快照。

2026-07-30 即時抓取效能對齊舊 GUI：登入後的勤務背景工作只查昨天、今天、明天 3 份勤務表與昨天、今天 2 天未返隊案件；另一個背景工作同時查三天的工作紀錄與出入登記，共維持舊版 5 + 6 次內容查詢，不再以單一瀏覽器串行抓取 5 份勤務表、4 天案件及 6 份比對資料。勤務工作完成後立即更新任務與登入身分，不等待比對工作；若比對逾時，已取得的勤務資料仍可使用且不會被判成整體抓取失敗。

2026-07-30 QML 視覺設定集中化：`Main.qml` 的原有色值、字級與圓角數值全部保留，但改由單一 `design` 物件提供語意化 token；視窗、工具側欄、狀態色、框線、分隔線、按鈕、下拉選單與輸入框不再散落十六進位色碼或直接字級。新增靜態契約測試禁止 `design` 以外出現色碼、數字 `font.pixelSize` 與非零數字圓角，並以 QML lint 及完整離屏視窗互動測試確認畫面仍可載入。該階段另有尚未轉換的舊 CustomTkinter 行車影片測試，當時未納入 227 項集合；後續已改為正式 QML 契約並納入完整測試。

2026-07-30 導航契約對齊舊 GUI：移除沒有可見入口、且舊版不存在的第三個「工具中心」頁面；QML 模式只保留值班與審核兩種狀態。五個工具仍只在登入後由值班畫面的原按鈕開啟，其中四個使用主視窗右側面板，行車紀錄器使用獨立非模態視窗。工具執行紀錄與 `ToolController` 後端保留，不因移除重複頁面而刪除。

2026-07-30 工作紀錄設定對齊舊 GUI：右側面板的標題與「消防救護車出勤由未返隊案件帶入」說明改回同一個淡藍標頭；一般數量輸入框恢復舊版 48×30，案件車數維持舊版 42×28；底部按鈕順序恢復為左側「還原預設」、右側「儲存／取消」。`WorkLogSettingsController.save()` 現在回傳成功狀態，儲存或驗證失敗時面板不會關閉，使用者可直接修正內容。相關正式測試集合為 228/228 通過。

2026-07-30 登入卡片字型與尺寸對齊舊 GUI：帳號／密碼標題及「記住帳號密碼」恢復 11 px，帳號框維持 38 px、密碼框恢復 36 px，底部原有登入訊息列恢復 14 px；不改變帳號選擇、密碼遮罩、可直接編輯及錯誤只留在底部訊息列的既有契約。完整正式測試集合為 229/229 通過，QML lint、Python 編譯與差異檢查正常。

2026-07-30 值班任務統一格式對齊：任務列、狀態 pill 與底部操作按鈕不再各自設定色彩、框線、字型及尺寸，改由中央 `design` token 與 `DutyTaskCard`、`DutyTaskStatusPill`、`DutyActionButton` 三個共用 QML 元件套用。選取任務恢復舊版只顯示 2 px 藍框、不改列底色；執行中恢復藍底白字，待處理恢復灰底深色字，完成恢復淡綠底；模式鍵為 112×38，三個任務操作鍵為 104×38。離屏渲染已實際驗證尺寸、狀態色及選取後白底，完整正式測試集合為 230/230 通過。

2026-07-30 全域語意格式收斂：`AppleButton` 統一由 `tone` 決定底色、hover、框線、字色與框線寬度，涵蓋一般、主要、成功、警告、每月工具、資訊、透明與強調中性色；畫面實例不再個別設定 `fillColor`、`hoverColor`、`strokeColor` 或 `textColor`。帳號選擇、設定齒輪、五個工具快捷鍵、審核模式底部按鈕與任務操作列皆使用同一中央規則；四張審核統計卡亦只傳入 `todo`、`review`、`ready`、`done` 語意。靜態契約禁止執行區重新加入局部色彩覆寫，離屏 QML 已驗證工具與統計卡 tone；完整測試維持 230/230 通過。

2026-07-30 勤務表工具側板對齊舊 GUI：可見文字恢復為「日期／中繼車／救護 1 車／救護 2 車／完成後發送勤務表截圖／啟動登打／關閉」，移除重複的頂部關閉鍵，補回日期前後切換鍵，並把原有狀態列放回底部。新增車輛沿用主要色、移除車輛沿用審核警告色、啟動登打沿用舊版綠色，全部由中央 tone 與尺寸 token 控制；正式執行仍保留 Qt 確認視窗及背景 worker。離屏測試已實際切換日期、檢查文字與執行完整流程，完整測試為 231/231 通過。

2026-07-30 全程式自動套用統一格式：`PrimaryButton` 與 `DangerButton` 改為直接繼承中央 `AppleButton`，四個右側工具面板改用共用的 `ToolPanelTitle`、`ToolFieldLabel`、`ToolBrowseButton`、`ToolDateStepButton`、`ToolAddButton`、`ToolRemoveButton`、`ToolRunButton`、`ToolCloseButton` 與 `ToolStatusBar`；畫面只保留文字、資料綁定與事件，不再為每個工具重複設定色彩、框線、字型、尺寸或 tone。新增靜態契約禁止執行畫面直接使用原生 Qt 輸入及按鈕控制項，並禁止四個工具側板重新加入局部格式；完整測試為 232/232 通過。

2026-07-30 休息時間工具側板對齊舊 GUI：移除舊版不存在的頂部關閉鍵與上次使用卡片，補回淡藍標頭及「勤務表檔案」表單卡；年月下拉恢復 78×32，底部按鈕恢復左側填滿的「啟動登打」與右側 90×38「關閉」，狀態列移回最底部並顯示「準備就緒。人員」。選擇 Excel 後會像舊版立即保存路徑、讀取工作簿月份、更新年月下拉及狀態列；正式執行仍保留 Qt 確認視窗與背景 worker。完整測試為 234/234 通過。

2026-07-30 勤務基準表工具側板對齊舊 GUI：移除舊版不存在的頂部關閉鍵與上次使用卡片，恢復淡藍標頭、「固定來源」卡片及單行「Google 試算表 / 輪休基準表  人員」文字；年月下拉沿用全域 78×32 元件，底部恢復左側填滿的「啟動登打」、右側 90×38「關閉」及最底部狀態列。正式執行仍保留 Qt 確認視窗、背景 worker 與既有錯誤分類。完整測試為 235/235 通過。

2026-07-30 每日車輛保養清點對齊舊 GUI：右側工具面板移除舊版不存在的頂部關閉鍵、上次使用卡片、執行日期、作業清單及「完成後自動關閉」敘述，只保留淡藍標頭、舊版開啟瀏覽器提示、左側「啟動清點」、右側「關閉」及最底部狀態列；正式確認文字恢復為「將開啟瀏覽器執行車輛保養清點，是否繼續？」。`DailyVehicleService` 的 `KEEP_BROWSER_OPEN` 由新版錯誤的 `false` 恢復為舊版 `true`，避免流程完成後主動關閉瀏覽器；PID 防重複、短效帳密環境變數、Qt worker 與安全錯誤訊息保持不變。完整測試為 236/236 通過。

2026-07-30 工具可見內容與全域格式收尾：勤務表及行車紀錄器移除舊版不存在的「上次使用／時間／人員／結果」卡片，勤務表標頭改用四個工具共用的 `ToolPanelHeader`；QML 不再保留可供頁面個別套色的使用紀錄卡元件或專用色彩 token。`ToolController`、後台事件及使用紀錄資料仍完整保留，只移除未獲授權的可見介面。靜態契約明確禁止所有工具頁重新加入該卡片，完整測試維持 236/236 通過，QML lint、Python 編譯與差異檢查正常。

2026-07-30 行車紀錄器獨立視窗對齊舊 GUI：比對實際啟動的 `RescueVideoApp._build_public_duty_gui()`，移除 QML 誤搬自未啟用表單的來源、目的地、偏移、修復及單純複製欄位，恢復 `1100×720`、最小 `980×560` 的非模態獨立視窗、深藍標頭、車號／日期、自動檢查、預覽分類、複製後刪除已驗證來源、六欄分類結果及底部摘要。記憶卡、Z 槽、工作／返隊紀錄、當日車號與偏移改由 `RescueVideoService` 背景自動檢查；未通過時兩個執行鍵停用，每五秒及日期／車號異動後重新檢查，刪除確認文字恢復舊版。原本 4 項要求 CustomTkinter 子視窗的過期測試已保留檔案並改為 PySide6/QML、核心檔案、按鈕順序及更新備份契約；完整測試為 242/242 通過，QML lint、Python 編譯與差異檢查正常。正式記憶卡與 Z 槽尚未執行。

2026-07-30 Qt 背景工作生命週期收斂：`SessionController` 的 NAS 帳密同步及 `AppController` 的 16:30／21:55 排程資料夾操作不再直接建立無法追蹤的 `threading.Thread`，改由新增的 `CredentialSyncWorker`、`ScheduledFolderWorker` 與各自的 QThread 執行。Controller 保存所有 worker／thread 配對，成功、失敗與 finished 均以 Signal 回傳，程式關閉時會停止計時器並等待執行中的工作清理；同步 payload、錯誤文字、排程時間與 Windows 操作流程不變。新增靜態契約禁止 `qt_app/controllers` 重新建立 Python thread，並測試成功、失敗、關閉等待及排程資料夾完成清理。完整測試增為 245/245 通過，QML lint、Python 編譯與差異檢查正常。

2026-07-30 後台同步生命週期收斂：正式 Qt 路徑的一般登入／登出／錯誤／工具／登打事件及值班看板同步改由 `OperationalSyncWorker` 與 `AppController` 保存的 QThread 執行，不再從 `OperationalSyncService` 另開無法在程式關閉時等待的 daemon thread；關閉程式會等待尚未完成的事件寫入與看板同步。更新前的登出事件仍保留同步 `immediate=True` 契約，確保更新程式終止 GUI 前已送達；事件 payload、pending JSONL、看板 hash 去重及舊測試 fake 介面不變。新增同步看板去重、受控工作執行緒、關閉等待與 Controller 禁止直接呼叫非受控 async 路徑測試；完整測試增為 249/249 通過。此驗證使用 fake／離線資料，未登入或寫入正式勤務網站與後台。

2026-07-30 帳號選擇視窗按鈕與刪除流程對齊舊 GUI：視窗尺寸、每欄 12 筆與帳號列配置維持不變；刪除、選擇及關閉按鈕不再使用不會被自訂 `AppleButton` 文字元件讀取的 `palette.buttonText`，改為全域共用的 `danger`、`infoStrong`、`neutralStrong` 語意 tone。實際顯示恢復舊版白底紅字紅框刪除鍵、淡藍底藍字藍框選擇鍵及灰底關閉鍵，不新增頁面色碼或獨立樣式。帳號清單恢復依數字番號排序；刪除後會保存並回填排序後第一個帳號，刪除最後一筆會清空帳密，DPAPI 儲存失敗則保留原清單及 Model。離屏 QML 測試已實際開啟帳號視窗、讀回三種共用色彩與框線，點擊「選擇」後確認視窗關閉、帳號及可編輯的遮罩密碼回填；完整測試增為 251/251 通過。

2026-07-30 QML 對話框格式集中化：原本 11 個手動登打、審核明細、帳號刪除、更新、帳密同步、行車影片來源刪除、勤務車輛新增／移除及四項工具確認視窗均不再直接使用平台預設 `Dialog` 外觀，改由唯一的全域 `AppleDialog` 提供白色面板、淡藍標題列、統一字型、圓角、框線與底部按鈕列。各視窗仍只指定標題、內容、`standardButtons` 與 accepted／rejected 行為；「是」統一使用主要藍色、「否／關閉」統一使用灰色，不新增頁面局部色碼。靜態契約禁止 runtime 再出現直接 `Dialog`，離屏 QML 已實際開啟手動登打確認視窗、驗證按鈕 tone／色彩並執行拒絕流程；既有整合測試亦逐一接受或拒絕工具及影片確認。完整測試維持 251/251 通過。

2026-07-30 Qt 更新包離線驗證：現有 `UPDATE\WinPython_公務電腦使用包.zip`（2026-07-27 20:01）及舊 alias ZIP（2026-07-10 21:39）不含 `qt_app`、`app_core` 或 QML，不能視為目前 PySide6 版本的可發布成品，本輪未覆寫或發布。使用共用 `sinposmart-update-package` 建置腳本在 Windows Temp 的去敏複本離線封裝成功：83 個檔案，包含 29 個 Qt Python、1 個 QML、17 個 app_core，必要檔案無缺漏、敏感／runtime 檔案 0、內部版本 `2026.07.27.2001` 與 SHA256 一致。`update_package.ps1` 已在停止現有 GUI 前新增六個 PySide6/QML 必要檔案檢查，遠端若仍是舊 ZIP 會明確拒絕安裝。正式 `UPDATE` ZIP、版本號、GitHub Release 與公務電腦更新仍待使用者明確授權後重建及驗收。

2026-07-30 正式 Qt 入口生命週期驗證：新增不出現在介面的 `--startup-smoke-test` 隔離驗收參數，直接由正式 `duty_gui.pyw` 進入 `qt_app.main`、建立 QApplication、單一執行個體服務及真實 QML 根視窗，250 ms 後經 Qt event loop 正常退出。此模式不讀 `.env`、不初始化系統匣、不啟動登入／Selenium、不建立正式排程服務，並使用臨時 Credential／Schedule 儲存區及停用外部同步；正常退出與 QML 載入失敗均明確關閉 local server、移除 server name、等待 Controller worker 並清理臨時目錄。實際離屏入口執行、QML lint、Python 編譯與正式 `tests/` 測試均通過，結果為 253/253（另含 116 個 subtests），無 `QThread: Destroyed`；測試在 event loop 完成後直接稽核 `sys.modules`，確認正式入口未載入 `duty_gui`、Tkinter、CustomTkinter、pystray、PIL ImageTk 或 Selenium。直接對 repo 根目錄執行未限定範圍的 pytest 會誤收集 `tmp/tk_ui_reference_localappdata` 內附帶的 Python idlelib 測試；正式測試命令必須限定為 `py -m pytest tests -q`，該參考目錄未刪除或修改。

2026-07-30 全域字型來源收斂與 Windows 實際渲染：中文字型只由 `qt_app.main.configure_application_font()` 依序選擇 Microsoft JhengHei UI、Microsoft JhengHei、Noto Sans TC 或 Segoe UI，QML 不再另外硬編 `fontFamily` 或任何 `font.family`，所有視窗與控制項自動繼承 QApplication 的同一字型；字級仍由中央 `design` token 控制。Qt offscreen 平台在本機不提供字型資料庫，因此純離屏截圖會顯示方框，不可當成公務電腦實際字形證據；Windows 平台讀回 215 個字型並選中 Microsoft JhengHei UI，將主視窗移到螢幕外實際渲染後，確認 550×320 登入畫面的日期、標題、帳號、密碼、帳號選擇、記住帳密、登入及底部狀態列中文皆正常。

2026-07-30 登入後 Windows 實際渲染比對：使用臨時 Credential repository、停用外部同步及記憶體假 Session／勤務資料，未連線勤務網站即將主視窗渲染為舊版固定 550×800；確認「已登入：職稱 姓名」狀態列、登出、每日／每月工具列、任務欄位、狀態 pill、審核模式與三個底部操作鍵位置正常。右上設定齒輪原先被 Windows 字型 fallback 當成彩色 emoji，已改為中央 `SettingsButton` 內建的單色 QML 向量圖示，並由 design token 恢復舊 GUI 的 34×34；頁面不再設定字型、色彩、尺寸或圖示樣式。實際 QML 測試會讀回該按鈕尺寸，防止退回 38×34 或彩色文字 glyph。

2026-07-30 勤務表右側面板 Windows 實際渲染：離線 Session 中實際點擊「勤務表登打」後，主視窗由 550×800 向右擴為 964×800；主區仍為 550 px，面板位於 x=564、y=14，尺寸 400×772，未遮住或縮窄主畫面。Excel、日期、攻擊／中繼／救護 1／救護 2 車、增刪車輛、完成後發送勤務表截圖、啟動登打、關閉及底部狀態列均可見。日期前後鍵原本因 32 px 按鈕繼承左右各 16 px padding，文字可用寬度為 0 而呈現空白；中央 `ToolDateStepButton` 已將左右 padding 統一為 0，恢復舊版 32×34 的 `<`／`>`。實際 QML 測試會檢查兩鍵文字、contentItem 可見寬度及日期切換結果。

2026-07-30 其餘右側工具 Windows 實際渲染：在同一離線 Session 逐一點擊車輛保養、休息時間及勤務基準表，三者均將外框維持 964×800，固定主區為 550 px（內部內容 x=14、寬 522），側板均為 x=564、y=14、400×772。車輛保養的提示、啟動／關閉與狀態列；休息時間的勤務表 Excel、115 年 07 月、啟動／關閉與狀態列；勤務基準表的固定來源、Google 試算表／輪休基準表、年月及底部按鈕均完整顯示。休息時間月份欄旁的淺藍圓角經實際子元件幾何比對，確認是與勤務基準表相同的 32×32 下拉 indicator，不是多出的捲軸或重疊元件，因此未做臆測性改版。QML 測試已補上四個側板精確幾何、主區不變，以及月下拉、選擇、啟動與關閉控制項的可見 contentItem 寬度。

2026-07-30 行車紀錄器 Windows 實際渲染：使用 Windows 平台、Microsoft JhengHei UI 與離線假服務建立 `1100×720` 邏輯視窗；本機 125% DPI 擷取為 `1375×900`，未讀取正式記憶卡、Z 槽或網路資料。標頭、工具表單標題與資料結果標題分別沿用全域 `StrongHeaderTitle`（23px）、`ToolSectionTitle`（14px）及 `DataSectionTitle`（15px），對齊舊 GUI 的既定語意層級，移除行車紀錄器專用字級及頁面層 `section` 樣式；日期欄位沿用全域 `AppleTextField` 的啟用／停用文字色，背景預設值 worker 清理後實際讀回可編輯且文字色為 `#172033`。QML 頁面只保留語意元件、資料與事件，不再個別設定這些格式。

2026-07-30 登入後讀取量與速度稽核：直接比對舊 `DutyGui.write_schedule_snapshot()`、`refresh_comparison_background()` 與新 `ScheduleCaptureService`，兩者一次即時更新都查 3 份勤務表（前日／當日／次日）、2 天未返隊案件，以及 3 天各 2 張工作／出入紀錄表；新版沒有增加日期或資料表數量，勤務與比對亦維持兩個背景工作並行。實際差異是登入 worker 已取得登入姓名，但先前建立勤務查詢 request 時未傳遞，可能在同次登入後又開工作紀錄新增頁辨識一次。`ScheduleCaptureRequest` 現在保留本次驗證登入取得的姓名，勤務表讀回後先直接與當日 `staff` 唯一比對；只有無法唯一對應時才執行原有只讀網站查詢。測試同時鎖定查詢量與姓名快速路徑，完整集合維持 253 項及 116 個 subtests 通過。

2026-07-30 修改後 Qt 套件離線重建：先建立不含敏感及 runtime 資料的 Windows Temp 複本，再使用共用建置流程產生驗證版 `2026.07.30.0333`；ZIP 共 85 個檔案，PySide6/QML 必要檔案無缺漏，不安全項目 0，內部版本一致，SHA256 為 `59a7ac1d5c5510d21ca439e6201abd4a24cfbe01a936a9df4fb299bbed2b646f`。正式 `UPDATE`、版本與 GitHub Release 均未修改。封裝稽核另確認 `work_log_defaults.json` 是新安裝所需預設檔，但既有安裝的使用者設定不得被更新包覆寫；`update_package.ps1` 已將它加入既有的 `preserveIfExistsFiles`，並由 PowerShell 解析與契約測試鎖定。

2026-07-30 QML 樣式模組拆分：全域顏色、字級、框線、圓角與共用尺寸由 `qt_app\qml\styles\Design.qml` 單一檔案提供，並由 `styles\qmldir` 宣告為 `Design` singleton，全部畫面及共用元件直接引用同一來源；沒有設定頁或個別頁面覆寫。更新包完整性閘門同步要求兩個樣式檔，避免只更新 `Main.qml` 而遺漏全域格式。此步不改任何舊 GUI 既定數值、可見文字、畫面格局或操作行為。

2026-07-30 QML 基礎控制項拆分：`AppleButton`、`AppleCheckBox`、`AppleComboBox`、`AppleTextArea` 與 `AppleTextField` 已由 `Main.qml` 移至 `qt_app\qml\components`，以 `components\qmldir` 提供同名型別；頁面用法、properties、尺寸及樣式綁定不變，`Main.qml` 從 3,068 行降為 2,880 行。正式入口 smoke、全 QML 目錄無警告 lint、Python 編譯及完整測試均通過，結果為 254 項及 124 個 subtests；Windows Temp 去敏封裝版 `2026.07.30.0354` 共 92 個檔案，9 個必要 QML 檔無缺漏、不安全項目 0，SHA256 為 `2cb7488d7de2044f25c7b5a0d2f729b5c70a3a8ab5c4b68e6b95799d18e46a0a`。正式 `UPDATE`、版本與 GitHub Release 未修改。

2026-07-30 QML 語意元件第二批拆分：`AppleDialog`、`PrimaryButton`、`DangerButton`、`SettingsButton`、`DutyActionButton`、`DutyTaskCard`、`DutyTaskStatusPill` 與 `AuditSummaryCard` 已移至同一個 `qt_app\qml\components` 模組，全部直接使用 `Design` singleton；頁面仍只指定語意、資料與事件，沒有新增局部色彩、字型、框線或尺寸。`Main.qml` 由 2,880 行降為 2,670 行，既有文字、固定 550 px 主區、右側 400 px 工具板、獨立行車紀錄器視窗及操作行為均不變。

2026-07-30 後台事件順序穩定化：完整回歸曾捕捉到登入失效時三條獨立 QThread 偶發形成 `error → logout → login_expired`；事件紀錄改由 `AppController` 的單一 FIFO lane 依排入順序執行，值班看板同步仍可獨立並行，不會因事件服務延遲阻塞資料載入。關閉程式會等待執行中工作並依序清空已排入事件；登入失效案例連續 20 次皆維持 `error → login_expired → logout`。完整測試為 254 項及 132 個 subtests，15 個 QML 檔 lint、Python 編譯及正式入口 smoke 均通過。Windows Temp 去敏封裝版 `2026.07.30.0404` 共 98 個檔案，22 個更新必要檔無缺漏、不安全項目 0，SHA256 為 `e3de168978145abb0e3b236710e4bf039d7f3ed70ddc3527d2692231a1b9af89`；正式 `UPDATE`、版本與 GitHub Release 未修改。

2026-07-30 QML 工具共用元件完整拆分：`AppleTabButton`、工具標題／表單／資料格、選擇／日期／月份／增刪／執行／關閉按鈕、狀態列等 19 個純語意元件，以及具明確依賴注入的 `ToolSidePanel`、`WorkLogValueControl`，均移入 `qt_app\qml\components`。`ToolSidePanel.hostWindow` 與 `WorkLogValueControl.settingsController` 是必要 property，元件不再隱式存取頁面 ID；`Main.qml` 已無任何 inline `component`，由 2,670 行降為 2,439 行。完整測試為 254 項及 153 個 subtests，36 個 QML 檔 lint、Python 編譯及正式入口 smoke 均通過。Windows Temp 去敏封裝版 `2026.07.30.0411` 共 119 個檔案，43 個更新必要檔無缺漏、不安全項目 0，SHA256 為 `0a5df2029fd9b612233fd2c436c348bf710de3143c29ebd7309bb9548a74fa1a`；正式 `UPDATE`、版本與 GitHub Release 未修改。

2026-07-30 QML dialogs／pages 邊界建立：帳號管理及刪除確認移至 `dialogs\AccountManagerWindow.qml`，只注入 `SessionController`；行車紀錄器、資料夾選擇、5 秒檢查、結果表及來源刪除確認移至 `dialogs\RescueVideoWindow.qml`，只注入 `RescueVideoController`、host window 與錯誤回呼；日期、登入、遮罩密碼、帳號選擇及登入後狀態列移至 `pages\SessionHeader.qml`，透過 signal 要求 Main 開啟帳號或工作紀錄設定。既有物件名稱、文字、尺寸及操作契約不變，`Main.qml` 由 2,439 行降為 1,778 行。完整測試為 254 項及 158 個 subtests，39 個 QML 檔 lint、Python 編譯及正式入口 smoke 均通過。Windows Temp 去敏封裝版 `2026.07.30.0421` 共 124 個檔案，48 個更新必要檔無缺漏、不安全項目 0，SHA256 為 `6627bebed10cd79132d84c0198a85ba2604fcd7c66b46ea50cec570a5db3d0bf`；正式 `UPDATE`、版本與 GitHub Release 未修改。

授權人員可在公務包資料夾手動開啟只讀登入驗收：

```powershell
$python = .\find_winpython.ps1 | Select-Object -First 1
& $python .\duty_gui.pyw --read-only-login-acceptance
```

此模式不保存或同步帳密、不送出勤務、不寫入後台事件或 Google 值班看板；工具與設定頁籤停用。登入成功後只讀取勤務、案件與既有比對資料。

### 八階段遷移狀態

| 階段 | 程式狀態 | 尚待正式驗收 |
| --- | --- | --- |
| 0 現況基準 | 完成 | 無 |
| 1 後端邊界抽離 | 完成；Tk 回退仍保留 | 無 |
| 2 PySide6 + QML 殼層 | 完成；正式入口已切換 | 公務電腦實機長時間執行 |
| 3 登入與 Session | 真實登入及勤務查詢已通過；人工番號確認卡已移除；網站自動番號查詢程式與測試完成 | 下次自然登入時讀回番號，不為驗收重複要求登入 |
| 4 值班主控台 | 任務 Model、選取、暫停、繼續、手動登打確認及狀態投影完成 | 真實勤務資料人工目視 |
| 5 排程與登打佇列 | QTimer、entry/work 雙通道、去重、送出後查回及錯誤分類完成 | 使用者授權的可回復正式登打 |
| 6 審核模式 | 日期、篩選、離線預演 JSON、任務 Model 與明細完成；真實日期、任務列及明細視窗已顯示 | 真實勤務與既有紀錄內容的人工比對 |
| 7 工具介面 | 勤務表、休息時間、勤務基準表及每日車輛使用舊版固定主區加右側 QML 工具欄；行車紀錄器使用獨立非模態視窗；均已接 Controller／Worker／既有核心路徑 | 各正式 Excel、網站、記憶卡與網路磁碟執行 |
| 8 Windows 與正式切換 | 系統匣、單一執行個體、更新、問題包、無黑窗入口、Qt 必要檔案閘門及暫存封裝驗證完成；現有正式 ZIP 仍是舊成品 | 重建正式更新包、Release，並驗收公務電腦排程時點與通知 |

### PySide6 + QML 功能驗收矩陣

| 原介面能力 | QML 執行路徑 | 現有證據 | 正式環境待驗收 |
| --- | --- | --- | --- |
| 登入、已儲存帳號、刪除帳號、登出 | `SessionController` → `LoginWorker` → `LoginVerifier`／`CredentialRepository` | single-flight、逾時、DPAPI、登入不重複查番號、職稱姓名格式、錯誤不覆蓋登入身分、固定底部訊息列與 QML 載入測試 | 真實登入已通過；其餘帳號管理仍需人工操作驗收 |
| 登入後快取優先與即時勤務、案件及既有紀錄查找 | `ScheduleLoadWorker` 快取回填 → `DutyController.refresh_live_schedule()` → `ScheduleCaptureWorker` → `ScheduleCaptureService` → 網站工作紀錄人員欄位與當日 `staff` 自動回填番號 | 未知番號也先載快取、登入姓名唯一對應番號與職稱、Session 回填、即時結果覆蓋快取、快照拆檔、歷史日期隔離及瀏覽器關閉測試 | 當日勤務讀回已通過；快取優先與自動番號回填待下次自然登入讀回 |
| 下一項任務、到點自動登打、手動登打、暫停及繼續 | `DutyController` → `DutyExecutionController` → `DutySubmissionWorker` → `DutySubmissionService` | 下一項任務沿用舊版候選與前班待辦規則；到點判斷、雙通道、去重、填表、儲存後查回及登入失效測試；QML 任務點選、暫停、繼續與手動確認取消已實際點擊 | 正式網站可回復範圍內的真實登打 |
| 值班／審核模式、日期與篩選、預演檔、明細 | `Main.qml` → `DutyController`／`ScheduleLoadWorker`／`ScheduleRepository`／`DutyTaskModel` | 560px 審核列邊界、日期跨月、篩選、QML 點擊明細、預演檔驗證、背景載入與關閉自動登打測試；真實審核任務列與明細視窗已開啟 | 真實勤務資料內容的人工目視比對 |
| 勤務表登打 | `DutySheetController` → `DutySheetWorker` → `DutySheetService` | 原生 QML 表單、車輛選項新增／移除、確認、worker、既有核心呼叫與錯誤測試；QML 執行鍵→確認視窗→worker 及清理已實際點擊驗證；載入執行核心不再匯入 Tk UI runtime | 正式 Excel 與網站執行 |
| 車輛保養清點 | `DailyVehicleController` → `DailyVehicleWorker` → `DailyVehicleService` | 原生 QML 確認、暫存帳密清理、程序完成與錯誤測試；QML 執行鍵→確認視窗→worker 及清理已實際點擊驗證 | 四個正式網站執行 |
| 休息時間／勤務基準表登打 | `RestMonthlyController` → `RestMonthlyWorker` → `RestMonthlyService` | 原生 QML 表單、月份檢查、瀏覽器關閉與錯誤測試；兩個 QML 執行鍵→共用確認視窗→各自 worker 及清理已實際點擊驗證；載入執行核心不再匯入 Tk UI runtime | 正式 Excel、Google 資料及網站執行 |
| 行車紀錄器 | `Main.qml` 獨立非模態視窗 → `RescueVideoController` → `RescueVideoWorker` → `RescueVideoService` → 既有分類核心 | 舊版 `1100×720` 車號／日期與自動檢查流程、六欄結果 Model、每五秒重查、背景執行、來源刪除二次確認、核心無 Tk import；離屏 QML 已實際驗證尺寸、欄寬、狀態、預覽鍵→worker→結果 Model、刪除確認→worker | 公務電腦記憶卡及 Z 槽操作 |
| 工作紀錄設定 | `WorkLogSettingsController` → `WorkLogSettingsService` | QML 編輯、放棄變更、還原、案件車數與儲存互動測試 | 真實案件描述預覽確認 |
| 更新、問題包、單一執行個體、系統匣、16:30／21:55 資料夾 | 對應 Qt Controller／`DiagnosticsService`／`ScheduledFolderService` | 更新確認、去敏 allowlist、local server、tray 與排程一次性測試；官方入口未新增 Chrome | 公務電腦系統匣通知與排程時點長時間驗收 |
| NAS 事件、帳密同步、Google 值班看板 | `OperationalSyncService`／`CredentialSyncService` | payload 去敏、佇列落盤、內容雜湊去重與確認對話框測試 | 正式 URL、token、NAS 與 Google 端讀回 |

只有「現有證據」欄通過不代表整列已完成；最後一欄全部驗收後，才能宣告完整 GUI 移植完成。

## 另一台電腦開始前

1. 等 Google Drive 顯示同步完成。
2. 在本資料夾開 PowerShell。
3. 執行：

```powershell
$cloudSkillRoot = "I:\我的雲端硬碟\專案\skill"
$localSkillRoot = Join-Path $env:USERPROFILE ".codex\skills"
New-Item -ItemType Directory -Force -Path $localSkillRoot
Copy-Item -LiteralPath (Join-Path $cloudSkillRoot "*") -Destination $localSkillRoot -Recurse -Force
```

4. 再執行環境檢查：

```powershell
py check_environment.py
```

5. 若要開 GUI：

```powershell
.\RUN_DUTY_GUI_WINPYTHON.vbs
```

## 2026-05-19 本機變更

### skill 同步規則

- 新增 `AGENTS.md`
- 新增 `AGENTS.md` 內的 skill 同步規則
- 規則：每次在本專案開始工作前，先掃描雲端 `專案\skill` 內所有含 `SKILL.md` 的 skills，全部同步到本機 `%USERPROFILE%\.codex\skills` 後再使用。
- 雲端 skill 來源位置：`I:\我的雲端硬碟\專案\skill`
- 目前實測會同步 14 個 skills。

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
- `duty_sheet_automation.py`：勤務表登打輔助流程。
- `daily_vehicle_automation.py`：車輛保養清點啟動器。
- `rest_time_automation.py`：休息時間與勤務基準表登打輔助流程。
- `check_environment.py`：檢查 Python、Tkinter、Selenium、Chrome / ChromeDriver。
- `rehearsal_output_1150518.json`：目前主要測試資料。
- `snapshots\verify_compare_1150518.txt`：2026-05-19 產生的比對驗證檔。

## 已驗證

```powershell
py -m py_compile duty_gui.py duty_gui.pyw duty_rehearsal.py compare_rehearsal_records.py duty_sheet_automation.py daily_vehicle_automation.py rest_time_automation.py check_environment.py
py compare_rehearsal_records.py rehearsal_output_1150518.json --out snapshots\verify_compare_1150518.txt
```

兩個命令都已在本機通過。

## 2026-05-19 當時尚未完成（已由後續正式登打實作取代）

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
