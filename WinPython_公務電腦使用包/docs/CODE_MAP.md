# 值班勤務系統自動化程式地圖

本文件先記錄目前大檔案的責任分區。這次整理只新增註解與文件，不搬動函式、不改執行邏輯。

## duty_gui.py

Tkinter 控制台主程式，負責登入畫面、值班模式、審核模式、背景查詢與提前登打佇列。

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

勤務表登打內嵌視窗，負責從 SinpoSmart 值班模式開啟勤務表登打表單，並呼叫舊的 `勤務表自動化\sinposmart_1.py` 核心流程。

目前定位：

- 內嵌小視窗由 `open_duty_sheet_dialog(...)` 建立，視覺風格接近值班模式。
- 外層值班模式若已登入，會把目前 session 帳號密碼帶入小視窗。
- 勤務表核心、`config.json`、service account JSON 與範例 Excel 已複製到 `duty_sheet_legacy`，公務包可獨立使用。
- 若本機包內找不到 `duty_sheet_legacy`，才回退搜尋同層舊專案 `勤務表自動化`。
- 不直接使用舊 GUI 的 `__main__` 區塊，避免舊 Tk globals 取代目前 SinpoSmart 主視窗。

## 後續拆檔建議

下一階段若要真的拆檔，建議先從低耦合處理：

1. 先拆 `compare_rehearsal_records.py`，因為它主要吃 JSON 與輸出比對結果。
2. 再拆 `duty_rehearsal.py` 的表單填寫與勤務表規則，避免瀏覽器操作和排程規則混在一起。
3. 最後拆 `duty_gui.py`，先保留主視窗，再把帳號管理、值班任務表、審核表抽成小模組。

每次拆檔後都應先跑：

```powershell
py -m py_compile .\duty_gui.py .\duty_rehearsal.py .\compare_rehearsal_records.py
```
