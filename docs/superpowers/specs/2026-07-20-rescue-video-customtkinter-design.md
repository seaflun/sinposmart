# 救護行車影片分類 CustomTkinter 整合設計

## 目標

在值班模式的「每日作業」增加第三項「救護行車影片」，以主值班 GUI 管理的 CustomTkinter 視窗完成影片預覽、複製與通過驗證後的來源刪除。

## 使用者流程

1. 已登入的值班模式顯示第三個每日作業按鈕。
2. 按鈕開啟 `CTkToplevel`，不建立第二個 `tk.Tk()` 根視窗。
3. 使用者選擇或自動偵測記憶卡，確認車號、日期與時間偏移後，依序執行預覽、複製或複製並刪除已驗證來源。
4. 結果、CSV 與執行紀錄只寫入套件的 `runtime_outputs/rescue_video`；分類仍讀取同一套件的 `runtime_outputs/comparison`。

## 架構

- `rescue_video_classifier.py`：沿用現有分類、工作／返隊比對、原子複製與 SHA-256 刪除驗證邏輯；不含任何 UI。
- `rescue_video_dialog.py`：以 CustomTkinter 建立 `CTkToplevel`、表單、結果表與背景執行佇列；只呼叫分類核心。
- `duty_gui.py`：每日作業改成三欄，新增按鈕與最薄的開啟方法；將既有 `COMPARISON_OUTPUT_DIR`、`RUNTIME_OUTPUT_DIR` 和工具事件回呼傳入對話窗。

## 新增 Python 檔案的必要性

1. `rescue_video_classifier.py` 的職責是保留可測試且不依賴 UI 的分類安全邏輯。
2. `rescue_video_dialog.py` 的職責是提供唯一的 CustomTkinter 使用介面；把它塞入已很大的 `duty_gui.py` 會提高衝突與維護風險。
3. 前者由後者 import，後者由 `duty_gui.py` import。
4. 兩者都是公務電腦套件正式程式，不是暫存或替代版本。
5. 核心以單元測試驗證，對話窗以純函式、匯入、背景作業與套件 smoke test 驗證。
6. 現有獨立專案的安全邏輯只移植一次，不在 `duty_gui.py` 重複實作。

## 安全與封裝邊界

- Z 槽案件目的地與「只刪除已通過大小、時間及 SHA-256 驗證的來源」規則維持不變。
- 不使用登入帳密，不變更 NAS、後台或 Google Site。
- 套件更新器已排除 `runtime_outputs`；新 CSV 與執行結果不會被打入更新包。
- `customtkinter` 已存在套件需求中，不新增第三方依賴。

## 驗證

- 先加入會失敗的測試，確認第三個每日作業按鈕、套件內檔案、腳本相對路徑與 CTk 對話窗入口存在。
- 執行影片分類核心測試、值班台 smoke suite 與所有 Python/pyw 編譯檢查。
- 在值班台 GUI 中手動開啟第三個按鈕，確認不建立第二個根視窗。
