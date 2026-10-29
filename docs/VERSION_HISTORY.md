# SinpoSmart 公務電腦使用包版本紀錄

這是正式 public-package-* 更新包的完整索引，依版本時間由新到舊排列。版本時間取自 yyyy.MM.dd.HHmm 版本號，均為台北時間；每一筆的完整變更與實際 GitHub 發布時間可由 Release 連結查看。

維護方式：每次建立新的正式更新包時，在表格最上方新增一列，摘要記錄該版可見變更並連到對應 GitHub Release。不要把未發布、本機設定或暫存檔列入此紀錄。

公務電腦內的「更新日誌」另由 `WinPython_公務電腦使用包/update_history.json` 提供；`major_history` 僅保留主要功能里程碑，`releases` 記錄各版摘要。每次正式發布都要更新該檔並保留既有版本摘要，讓尚未登入的電腦可在後續登入時逐版顯示更新內容；已讀版本比對也會補足舊更新器未寫入提醒標記的首次升級。

## 正式版本索引

| 版本 | 更新時間 | 更新摘要 | 完整說明 |
| --- | --- | --- | --- |
| `2026.10.29.1348` | 2026-10-29 13:48（台北時間） | 扣除人力改獨立新增／編輯視窗並更名卡片；精簡通報例行到期提示，保留登入保護。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.29.1348) |
| `2026.10.29.1333` | 2026-10-29 13:33（台北時間） | 新增帶隊官附記、人力扣除日期設定與獨立欄位檢查，清理訓練及備註開頭格式。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.29.1333) |
| `2026.10.29.1052` | 2026-10-29 10:52（台北時間） | 同日多班分段顯示，保留白天與跨午夜班，修正單獨深夜或清晨班誤顯示無班。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.29.1052) |
| `2026.10.29.0848` | 2026-10-29 08:48（台北時間） | 修正瀏覽器啟動逾時後的排隊行為，新增登入及通報的安全分階段診斷，避免虛構重試。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.29.0848) |
| `2026.10.28.1858` | 2026-10-28 18:58（台北時間） | 通報驗證回報實際安全錯誤分類與等待狀態，排除關閉取消誤報，驗證與收取紀錄分開。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.28.1858) |
| `2026.10.28.1610` | 2026-10-28 16:10（台北時間） | 修正通報密碼領取、確認與問題包上傳的 NAS 內網允許路徑，補齊真實傳輸層回歸。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.28.1610) |
| `2026.10.28.1314` | 2026-10-28 13:14（台北時間） | 支援從 NAS 後台遠端修改通報密碼，加密儲存、單次登入驗證及進度回報，保留防重複與登入保護。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.28.1314) |
| `2026.10.28.1049` | 2026-10-28 10:49（台北時間） | 問題包於背景同步 NAS，保存遮蔽後的登打、交接與通報失敗原因，保留斷線重試及原正式登打規則。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.28.1049) |
| `2026.10.27.1833` | 2026-10-27 18:33（台北時間） | 通報於密碼到期前一天23:59停用；登入最多送出一次，失敗持續暫停，儲存新密碼後自動驗證恢復。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.27.1833) |
| `2026.10.27.1547` | 2026-10-27 15:47（台北時間） | 交班前兩分鐘顯示當班通報置頂提醒，單位與姓名分行、收取時間排序，保留零則不跳與跨重啟防重複。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.27.1547) |
| `2026.10.27.1342` | 2026-10-27 13:42（台北時間） | 勤務表自動登打提前至每日10:30，保留下一消防日目標、舊排程轉換與防重複執行。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.27.1342) |
| `2026.10.27.1210` | 2026-10-27 12:10（台北時間） | 修正延後交班與更新重啟後的通報簽收責任恢復，保留跨日、取消與衝突守門，明確區分入表與簽收。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.27.1210) |
| `2026.10.27.0850` | 2026-10-27 08:50（台北時間） | 修正通報與民力登入的密碼到期提醒，自動暫不變更並等待導頁；強制換密碼保留人工處理提示。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.27.0850) |
| `2026.10.27.0148` | 2026-10-27 01:48（台北時間） | 簡化救護影片備份，依卡內日期選擇車號，阻擋換卡沿用預覽，補齊檢查原因及部分完成狀態。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.27.0148) |
| `2026.10.26.2212` | 2026-10-26 22:12（台北時間） | 勤務表新增救護2車，依兩表規則補足人員，維持訓練名單、到點排程與完成紀錄。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.26.2212) |
| `2026.10.24.1734` | 2026-10-24 17:34（台北時間） | 修正同址出入紀錄因二級火警等前綴而誤判未返隊，保留人員、時間、門牌與梯次安全檢查。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.24.1734) |
| `2026.10.24.1216` | 2026-10-24 12:16（台北時間） | 通報接回既有 Chrome 啟動失敗重試，以專用新 profile 復原，保留舊資料及收據／已讀守門。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.24.1216) |
| `2026.10.24.1149` | 2026-10-24 11:49（台北時間） | 通報失敗回報固定安全代碼，供後台區分瀏覽器、登入及列表讀取問題，保留既有收取流程。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.24.1149) |
| `2026.10.24.1057` | 2026-10-24 10:57（台北時間） | 恢復固定公務內網 NAS 預設路徑與心跳、更新完成回報，保留其他 HTTP 與轉址限制。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.24.1057) |
| `2026.10.24.0209` | 2026-10-24 02:09（台北時間） | 完整分頁與查詢新資料驗證、通報登入及收據安全復原、雲端授權、加密同步與更新包完整性修正。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.24.0209) |
| `2026.10.22.2011` | 2026-10-22 20:11（台北時間） | 同步班表職稱，修正小隊長「姓＋小」與分隊長「姓＋分」簽收，維持下拉驗證與一般人員姓名對應。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.22.2011) |
| `2026.10.22.1750` | 2026-10-22 17:50（台北時間） | 值班後台新增已收通報監看，回報當班／曆日計數、檢查時間、入表與已讀狀態，支援分片續傳、跨日去重及來源篩選。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.22.1750) |
| `2026.10.22.1148` | 2026-10-22 11:48（台北時間） | 帳密同步限成功登入本人，保留 Worker 其他人員密碼；器材依檢視／繼續清點接續原筆，等待正式完成並核對明細、日期與紀錄 ID。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.22.1148) |
| `2026.10.22.1011` | 2026-10-22 10:11（台北時間） | 通報每輪強制重載列表，修正漏收新件與已讀假警告；器材清點缺少結束時間時顯示明確原因，保留原紀錄。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.22.1011) |
| `2026.10.22.0816` | 2026-10-22 08:16（台北時間） | 新增通報背景自動收取、獨立帳密驗證、當班／曆日累計卡片與雲端跨年度月檔自動建立。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.22.0816) |
| `2026.10.20.0126` | 2026-10-20 01:26（台北時間） | 修正 GUI 退出過渡期造成更新誤判，等待自然退出並記錄原因代碼、PID、等待時間，安裝器獨立回報後台。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.20.0126) |
| `2026.10.19.2240` | 2026-10-19 22:40（台北時間） | 修復官方無標頭人員表的職稱同步，排除無番號實習生，保留原勤務登打與完整性檢查。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.19.2240) |
| `2026.10.19.2224` | 2026-10-19 22:24（台北時間） | 密碼欄新增英文大小寫即時提示，支援 Caps Lock／Shift 狀態及警示色，保留密碼遮蔽與既有登入流程。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.19.2224) |
| `2026.10.19.2034` | 2026-10-19 20:34（台北時間） | 修正登入驗證導頁造成的姓名遺失與番號誤判，恢復正確人員對應並保留登入阻擋及斷線重試。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.19.2034) |
| `2026.10.19.1932` | 2026-10-19 19:32（台北時間） | 阻擋失效帳密誤登入；登打登入失敗時置頂提醒，確認後安全關閉，保留正常交接及回報。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.19.1932) |
| `2026.10.18.1045` | 2026-10-18 10:45（台北時間） | 等待清單導頁與刷新完成後再驗證，補齊固定失敗階段，保留逐車完成與不用保養守門。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.18.1045) |
| `2026.10.18.0910` | 2026-10-18 09:10（台北時間） | 修復實站查詢資料來源替換、網站不用保養與器材完成判定，保留逐車結果。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.18.0910) |
| `2026.10.17.1253` | 2026-10-17 12:53（台北時間） | 修正車輛保養清點誤報完成，統一手動／自動日期並保留逐車核對結果與未確認原因。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.17.1253) |
| `2026.10.16.2349` | 2026-10-16 23:49（台北時間） | 修正空白帳密標籤造成截圖遮蔽誤判，回報具體截圖失敗原因與安全例外類別，保留敏感內容阻擋與原登入原因。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.16.2349) |
| `2026.10.15.2232` | 2026-10-15 22:32（台北時間） | 登入時辨識密碼到期與強制改密碼頁面，回報安全原因及遮蔽後的頁面證據；保護逾時與舊登入回覆的診斷隔離。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.10.15.2232) |
| `2026.09.25.1646` | 2026-09-25 16:46（台北時間） | 修正未返隊暫停手動確認後，最後一筆交接工作成功卻顯示到點待執行；班表重整保留完成狀態，單筆退勤已存在時也正確顯示。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.09.25.1646) |
| `2026.09.24.1818` | 2026-09-24 18:18（台北時間） | 新增主要功能更新日誌；成功更新後登入會顯示版本摘要，關閉後才能進入系統。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.09.24.1818) |
| `2026.09.23.2132` | 2026-09-23 21:32（台北時間） | 勤務表、車輛保養清點、休息時間、勤務基準表與民力系統完成後保留瀏覽器 10 分鐘並自動關閉；失敗時立即關閉。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.09.23.2132) |
| `2026.09.07.2203` | 2026-09-07 22:03（台北時間） | 勤務基準表開頁及月份查詢的網站提示自動確認後繼續，避免彈窗被誤判為瀏覽器中斷。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.09.07.2203) |
| `2026.08.27.1655` | 2026-08-27 16:55（台北時間） | 勤務基準表新增消防節假「消」：Google Sheet 標記「消」時，系統也登打「消」。新增完整版本紀錄索引。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.27.1655) |
| `2026.08.27.0009` | 2026-08-27 00:09（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.27.0009) |
| `2026.08.26.2353` | 2026-08-26 23:53（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.26.2353) |
| `2026.08.26.1524` | 2026-08-26 15:24（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.26.1524) |
| `2026.08.26.1417` | 2026-08-26 14:17（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.26.1417) |
| `2026.08.26.1327` | 2026-08-26 13:27（台北時間） | 修正隔日勤務表查詢後的等待流程：只在查詢後等待『設定勤務項目』與『設定勤務番號』，兩項設定完成後才等待正式登打表格，不會再進行第二次查詢。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.26.1327) |
| `2026.08.26.1252` | 2026-08-26 12:52（台北時間） | 修正隔天勤務表登打：查詢後等待設定勤務番號按鈕就緒，設定完成後直接等待正式表格。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.26.1252) |
| `2026.08.26.1234` | 2026-08-26 12:34（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.26.1234) |
| `2026.08.26.1013` | 2026-08-26 10:13（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.26.1013) |
| `2026.08.25.2214` | 2026-08-25 22:14（台北時間） | 勤務番號設定新增小視窗唯讀預檢與一次全新瀏覽器重試，確認前不刪除、填寫或儲存勤務表。；勤務基準表登打改由 Google 試算表來源鎖定月份，移除月份下拉選單。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.25.2214) |
| `2026.08.25.1709` | 2026-08-25 17:09（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.25.1709) |
| `2026.08.24.0858` | 2026-08-24 08:58（台北時間） | 救護行車紀錄器回報新增日期、車輛、案件數、總數量與使用時間；每次執行以獨立 run_id 顯示。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.24.0858) |
| `2026.08.23.1257` | 2026-08-23 12:57（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.23.1257) |
| `2026.08.22.2247` | 2026-08-22 22:47（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.22.2247) |
| `2026.08.20.1404` | 2026-08-20 14:04（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.20.1404) |
| `2026.08.18.0815` | 2026-08-18 08:15（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.18.0815) |
| `2026.08.18.0031` | 2026-08-18 00:31（台北時間） | 常駐預熱任務線、背景等待任務保護、閒置瀏覽器清理，以及統一錯誤明細與關閉操作。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.18.0031) |
| `2026.08.17.1709` | 2026-08-17 17:09（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.17.1709) |
| `2026.08.17.0953` | 2026-08-17 09:53（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.17.0953) |
| `2026.08.16.1524` | 2026-08-16 15:24（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.16.1524) |
| `2026.08.16.0942` | 2026-08-16 09:42（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.16.0942) |
| `2026.08.16.0101` | 2026-08-16 01:01（台北時間） | 值班交接優先採用剛更新的班表快照，避免重複遠端查詢。；工作紀錄改以工作時間前後兩分鐘進行防重複與送出後驗證。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.16.0101) |
| `2026.08.15.1916` | 2026-08-15 19:16（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.15.1916) |
| `2026.08.15.0958` | 2026-08-15 09:58（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.15.0958) |
| `2026.08.15.0929` | 2026-08-15 09:29（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.15.0929) |
| `2026.08.15.0026` | 2026-08-15 00:26（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.15.0026) |
| `2026.08.14.1516` | 2026-08-14 15:16（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.14.1516) |
| `2026.08.14.1350` | 2026-08-14 13:50（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.14.1350) |
| `2026.08.14.1002` | 2026-08-14 10:02（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.14.1002) |
| `2026.08.14.0841` | 2026-08-14 08:41（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.14.0841) |
| `2026.08.13.2146` | 2026-08-13 21:46（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.13.2146) |
| `2026.08.13.2017` | 2026-08-13 20:17（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.13.2017) |
| `2026.08.13.0940` | 2026-08-13 09:40（台北時間） | 修正同一勤務第一次暫時失敗、重試成功後，UI 紅色錯誤提示未清除的問題。；交接預檢維持靜默；若預檢登入失敗，登入頁會明確說明正式交接尚未執行。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.13.0940) |
| `2026.08.12.2336` | 2026-08-12 23:36（台北時間） | 修正返隊後影片分類、值班交接車輛統計與影片預覽欄寬。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.12.2336) |
| `2026.08.12.1743` | 2026-08-12 17:43（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.12.1743) |
| `2026.08.12.1603` | 2026-08-12 16:03（台北時間） | 修正車輛保養清點在保留瀏覽器時無法完成回報。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.12.1603) |
| `2026.08.12.1508` | 2026-08-12 15:08（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.12.1508) |
| `2026.08.12.1356` | 2026-08-12 13:56（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.12.1356) |
| `2026.08.12.1136` | 2026-08-12 11:36（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.12.1136) |
| `2026.08.12.0306` | 2026-08-12 03:06（台北時間） | 強化登入與開啟勤務頁面前的 Chrome session 中斷重試。；涵蓋值班登入、班表查詢、勤務登打、休息／勤務基準表、車輛保養與勤務表工具。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.12.0306) |
| `2026.08.11.1508` | 2026-08-11 15:08（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.11.1508) |
| `2026.08.09.1724` | 2026-08-09 17:24（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.09.1724) |
| `2026.08.09.0157` | 2026-08-09 01:57（台北時間） | 修正交接預檢通知與過期群組判定。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.09.0157) |
| `2026.08.09.0135` | 2026-08-09 01:35（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.09.0135) |
| `2026.08.09.0051` | 2026-08-09 00:51（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.09.0051) |
| `2026.08.09.0011` | 2026-08-09 00:11（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.09.0011) |
| `2026.08.08.2026` | 2026-08-08 20:26（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.08.2026) |
| `2026.08.08.1701` | 2026-08-08 17:01（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.08.1701) |
| `2026.08.08.1508` | 2026-08-08 15:08（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.08.1508) |
| `2026.08.08.1425` | 2026-08-08 14:25（台北時間） | 調整值班交接群組任務顯示順序。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.08.1425) |
| `2026.08.08.1358` | 2026-08-08 13:58（台北時間） | 修正未返隊交接、隔日空案件審核與交接三筆連動勾選。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.08.1358) |
| `2026.08.07.0930` | 2026-08-07 09:30（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.07.0930) |
| `2026.08.07.0036` | 2026-08-07 00:36（台北時間） | 修正未返隊案件的車輛出勤估算：緊急救護案件出勤人員達 4 人以上，判定為兩車出勤；無效返隊時間不再排除案件。；統一審核模式與值班模式的勤務列色彩：尚未到點與出入為藍色，工作與案件工作為綠色。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.07.0036) |
| `2026.08.06.2135` | 2026-08-06 21:35（台北時間） | 修正 Google 值班看板時段解析、手動登打鎖定、共用視窗圓角與勤務表消防車攻擊／中繼設定。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.06.2135) |
| `2026.08.06.2051` | 2026-08-06 20:51（台北時間） | QML 值班台：登出事件可靠送達、NAS 身分格式一致、系統更新結果提示。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.06.2051) |
| `2026.08.06.2018` | 2026-08-06 20:18（台北時間） | QML 值班台：三線登打、更新確認、SinpoSmart 通知、值班名牌重試與工具上次使用人員顯示修正。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.06.2018) |
| `2026.08.06.1847` | 2026-08-06 18:47（台北時間） | QML 值班台 NAS 同步、交接登打與診斷回報修正。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.06.1847) |
| `2026.08.06.1802` | 2026-08-06 18:02（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.06.1802) |
| `2026.08.06.1747` | 2026-08-06 17:47（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.06.1747) |
| `2026.08.06.1703` | 2026-08-06 17:03（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.08.06.1703) |
| `2026.07.29.1033` | 2026-07-29 10:33（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.07.29.1033) |
| `2026.07.29.0159` | 2026-07-29 01:59（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.07.29.0159) |
| `2026.07.27.2001` | 2026-07-27 20:01（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.07.27.2001) |
| `2026.07.27.1553` | 2026-07-27 15:53（台北時間） | 新增每日作業「行車紀錄器（BETA）」；以獨立程序啟動既有救護行車影片分類 GUI，保留明確確認與 SHA-256 驗證後才刪除來源影片的安全機制。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.07.27.1553) |
| `2026.07.26.2230` | 2026-07-26 22:30（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.07.26.2230) |
| `2026.07.26.0752` | 2026-07-26 07:52（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.07.26.0752) |
| `2026.07.25.2218` | 2026-07-25 22:18（台北時間） | 救災車輛任務編組規則更新：避免救護車重複登打，依備勤人數補足救災車人力，並於指揮官空白時優先由其他幹部補攻擊車第 2 位。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.07.25.2218) |
| `2026.07.22.0801` | 2026-07-22 08:01（台北時間） | 修正每日勤務表救護2車外勤補人與救災車編組人力規則。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.07.22.0801) |
| `2026.07.21.0106` | 2026-07-21 01:06（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.07.21.0106) |
| `2026.07.21.0036` | 2026-07-21 00:36（台北時間） | 值班 GUI 啟動時及每天 03:00 自動清理逾期資料；每日勤務表與夜間勤務 PNG 只保留 30 天 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.07.21.0036) |
| `2026.07.18.2110` | 2026-07-18 21:10（台北時間） | 修正班末自動登出判斷：只等待同一交接時間的自動勤務完成，休息返隊等手動勤務不再阻擋登出。已整合前一版 Google Site 值班看板同步功能；完整 smoke tests 76 項通過。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.07.18.2110) |
| `2026.07.16.2305` | 2026-07-16 23:05（台北時間） | 新增 Google Site 值班看板同步：從當日勤務表同步目前與下一時段人員。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.07.16.2305) |
| `2026.07.16.0825` | 2026-07-16 08:25（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.07.16.0825) |
| `2026.07.15.2309` | 2026-07-15 23:09（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.07.15.2309) |
| `2026.07.10.2139` | 2026-07-10 21:39（台北時間） | 修正班末值退提前手動完成時未排定自動登出；班末 10 分鐘後檢查當班交接紀錄，未完成每 10 分鐘重查。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.07.10.2139) |
| `2026.07.07.2209` | 2026-07-07 22:09（台北時間） | 每日勤務表登打前新增預檢：重複排班、漏排、公式錯誤會先擋下。；實習生番號會排除，不登打也不列入漏排。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.07.07.2209) |
| `2026.07.07.1000` | 2026-07-07 10:00（台北時間） | 勤務表登打會依輪休基準表的班表欄位排除實習生。；勤務分配表與救災任務編組表都會排除實習生番號。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.07.07.1000) |
| `2026.07.05.1531` | 2026-07-05 15:31（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.07.05.1531) |
| `2026.07.05.1418` | 2026-07-05 14:18（台北時間） | 手動登打時間規則調整與公務電腦更新包。；所有可手動登打的工作紀錄與出入登記都使用按下「手動登打」時的當下時間 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.07.05.1418) |
| `2026.07.05.1342` | 2026-07-05 13:42（台北時間） | 修正背景查詢時勤務網站空白 popup 會擋住畫面的問題。；背景 Chrome 不再停用 popup blocking | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.07.05.1342) |
| `2026.07.02.2246` | 2026-07-02 22:46（台北時間） | Adds manual pause/resume controls for duty-mode scheduling.；Adjusts logged-out GUI height and validates button spacing. | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.07.02.2246) |
| `2026.07.01.1911` | 2026-07-01 19:11（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.07.01.1911) |
| `2026.07.01.1857` | 2026-07-01 18:57（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.07.01.1857) |
| `2026.06.28.2037` | 2026-06-28 20:37（台北時間） | Verify each duty submit by re-querying official records before marking it successful.；If the record is not found after save, treat it as a failure so due tasks retry instead of silently completing. | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.28.2037) |
| `2026.06.28.1157` | 2026-06-28 11:57（台北時間） | 修正值班模式任務清單空白：當排程檔缺少 actions 時會由勤務表資料補回任務，且刷新任務清單後會將隱藏捲動區回到頂端，避免背景已觸發任務但畫面看起來一片空白。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.28.1157) |
| `2026.06.28.1145` | 2026-06-28 11:45（台北時間） | 修正登入時輸入番號與勤務系統實際辨識番號不一致時的誤用：現在會停止登入並提示番號不一致，避免值班模式載入錯誤人員清單。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.28.1145) |
| `2026.06.28.0805` | 2026-06-28 08:05（台北時間） | 修正 04-08 休息後退勤後，隔天 08 不再重複產生退勤/值退。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.28.0805) |
| `2026.06.28.0737` | 2026-06-28 07:37（台北時間） | 修正 SinpoSmart 事件重送、更新登出顯示與 19 番清晨退勤重複。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.28.0737) |
| `2026.06.28.0717` | 2026-06-28 07:17（台北時間） | 修正 1150627 消防日隔日凌晨休息任務產生：2番 00:00 休息、02:00 休息返隊，以及 4番 04:00 休息後退勤。；值班模式規劃測試，覆蓋隔日凌晨休息與休息後退勤情境。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.28.0717) |
| `2026.06.28.0654` | 2026-06-28 06:54（台北時間） | 修正 04-08 連續休息且隔天未在勤時誤產生休息/休息返隊與 06 休息後退勤。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.28.0654) |
| `2026.06.26.2023` | 2026-06-26 20:23（台北時間） | 變更：；統一登入失敗/登入失效處理。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.26.2023) |
| `2026.06.26.1828` | 2026-06-26 18:28（台北時間） | 補打逾時勤務時，等待登打佇列清空後才自動登出。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.26.1828) |
| `2026.06.26.0936` | 2026-06-26 09:36（台北時間） | 修正消防日值班交接判斷：先將勤務表值班列串成連續區段，再由區段交界產出值班交接，避免 08:00 誤抓當日 7~8 或 22:00 欄位。；重點： | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.26.0936) |
| `2026.06.26.0820` | 2026-06-26 08:20（台北時間） | 修正 08:00 跨日值班交接判斷：當今天勤務表缺少 06-08 列時，08:00 值班交接會回退抓前一天 22:00 值班人員，避免 26 番這類前晚 22-08 值班交接漏登。；py_compile 公務電腦主要 Python 檔 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.26.0820) |
| `2026.06.25.1645` | 2026-06-25 16:45（台北時間） | 值班交接時間改由實際勤務表值班列起點判斷，不再使用固定時段。；支援 00:00、06:00、07:00 與其他特殊值班交接切點。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.25.1645) |
| `2026.06.25.1218` | 2026-06-25 12:18（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.25.1218) |
| `2026.06.23.1959` | 2026-06-23 19:59（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.23.1959) |
| `2026.06.22.1210` | 2026-06-22 12:10（台北時間） | 補上 06-08 休息班的 08:00 休息返隊手動項目，維持休息不自動登打。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.22.1210) |
| `2026.06.22.0848` | 2026-06-22 08:48（台北時間） | 變更內容：；休息時間登打、勤務基準表登打固定使用今年，月份下拉只提供前一月、本月、下一月。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.22.0848) |
| `2026.06.21.2315` | 2026-06-21 23:15（台北時間） | 變更：；休息時間登打與勤務基準表登打新增年月選擇與年月不一致阻擋。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.21.2315) |
| `2026.06.21.1751` | 2026-06-21 17:51（台北時間） | Fix tool finish event reporting when content is provided.；Keep the existing SinpoSmart event payload structure and add defensive handling so one event failure does not stop th… | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.21.1751) |
| `2026.06.21.1231` | 2026-06-21 12:31（台北時間） | Report update-forced logout to the backend before the updater stops the GUI.；Persist SinpoSmart pending events before posting so update shutdown cannot lose the event. | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.21.1231) |
| `2026.06.19.1052` | 2026-06-19 10:52（台北時間） | 後台可用事件回報判斷現場公務電腦安裝版本。；包排除 jsonl runtime 紀錄。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.19.1052) |
| `2026.06.18.2201` | 2026-06-18 22:01（台北時間） | 四個工具開始後加入逾時保護，逾時會回報工具結果失敗，不再只停在執行中。；勤務系統 Selenium driver 加入 page_load_timeout 與 script_timeout，涵蓋休息時間、勤務基準表與值班模式。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.18.2201) |
| `2026.06.18.2021` | 2026-06-18 20:21（台北時間） | 後台可顯示各工具的開始、結束與結果。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.18.2021) |
| `2026.06.18.1331` | 2026-06-18 13:31（台北時間） | 加強出入登記簿的出或入欄位選擇與確認。；手動登打前略過已登打、已手動登打與登打中項目。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.18.1331) |
| `2026.06.18.1059` | 2026-06-18 10:59（台北時間） | 勤務表讀取若沒有讀到真正勤務表列，改為停止並提示，不再產生空白勤務資料。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.18.1059) |
| `2026.06.18.1033` | 2026-06-18 10:33（台北時間） | 修正勤務基準表日期欄位匹配：直接解析 _pln_列_日期，避免轉義失敗與 _pln_workday_8 這類非日期欄位被選中。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.18.1033) |
| `2026.06.18.1024` | 2026-06-18 10:24（台北時間） | 修正勤務基準表日期欄位選取，避免番號與日期相同時抓到 hidden 欄位。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.18.1024) |
| `2026.06.17.2337` | 2026-06-17 23:37（台北時間） | Update project agent guidance for the renamed 救護返隊小幫手 backend/admin path.；Publish a refreshed public-duty package version. | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.17.2337) |
| `2026.06.16.2355` | 2026-06-16 23:55（台北時間） | Record backend events when public-duty tools formally start execution.；Add tool codes for duty_sheet, rest_time, monthly_base, and daily_vehicle. | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.16.2355) |
| `2026.06.16.1239` | 2026-06-16 12:39（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.16.1239) |
| `2026.06.15.1433` | 2026-06-15 14:33（台北時間） | 新增 SinpoSmart 值班後台事件推送。；後台事件預設走內網 NAS：http://10.30.65.30:8080/api/sinposmart/events。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.15.1433) |
| `2026.06.15.1430` | 2026-06-15 14:30（台北時間） | 新增 SinpoSmart 值班後台事件推送。；檢查檔案：sinposmart-version.txt、sinposmart-public-package.zip、sinposmart-public-package.zip.sha256.txt。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.15.1430) |
| `2026.06.14.1951` | 2026-06-14 19:51（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.14.1951) |
| `2026.06.14.1939` | 2026-06-14 19:39（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.14.1939) |
| `2026.06.13.2302` | 2026-06-13 23:02（台北時間） | 修正勤務表截圖局部文字被 Excel 自動縮小的問題。；public-duty WinPython package assets for updater download. | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.13.2302) |
| `2026.06.12.1253` | 2026-06-12 12:53（台北時間） | 無線電試話比對改為 11:10 + 勤務項目「其他」+ 列內容包含「無線電」，不比對人員、不要求事由。；包含前版值班模式任務列表刷新防空白修正與狀態文字簡化。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.12.1253) |
| `2026.06.12.1224` | 2026-06-12 12:24（台北時間） | 值班模式任務列表刷新改為先完成資料計算再重建畫面，避免登打完成後因刷新例外出現整片空白。；值班模式狀態文字簡化：已存在(時間不同) 顯示為 已登打。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.12.1224) |
| `2026.06.10.0954` | 2026-06-10 09:54（台北時間） | 檢查更新確認後自動執行，不再要求在 PowerShell 視窗輸入 Y/N。；完成後 PowerShell 視窗會自動關閉，並在原程式執行中時重新啟動 GUI。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.10.0954) |
| `2026.06.09.2103` | 2026-06-09 21:03（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.09.2103) |
| `2026.06.09.2024` | 2026-06-09 20:24（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.09.2024) |
| `2026.06.08.0752` | 2026-06-08 07:52（台北時間） | Public duty computer update package. SHA-256: b03426f5b3fbb384fa07374c523fdd538ae680fa7d1bec80ab7bb8b992abd530 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.08.0752) |
| `2026.06.08.0727` | 2026-06-08 07:27（台北時間） | Public duty computer update package. SHA-256: f89721f4ffbb54030b0fcea454cc52a31955116d0cf4d3d70169a6625b80a0aa | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.08.0727) |
| `2026.06.07.2209` | 2026-06-07 22:09（台北時間） | Public duty computer update package. SHA-256: c3f196e6ef8471de9aad7198f6be92593c0bdb5b73d6527f15b317d90c2c4b45 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.07.2209) |
| `2026.06.07.1944` | 2026-06-07 19:44（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.07.1944) |
| `2026.06.07.1650` | 2026-06-07 16:50（台北時間） | 未提供可安全摘要的變更說明；請開啟 Release 查看完整內容。 | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.07.1650) |
| `2026.06.07.1430` | 2026-06-07 14:30（台北時間） | Public computer update package.；Use GitHub Release latest assets for updates. | [Release](https://github.com/seaflun/sinposmart/releases/tag/public-package-2026.06.07.1430) |
