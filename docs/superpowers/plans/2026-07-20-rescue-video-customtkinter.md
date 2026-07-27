# 救護行車影片 CustomTkinter 整合 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將救護行車影片分類工具加入值班台每日作業第三項，並以 CustomTkinter 對話窗提供完整安全工作流。

**Architecture:** `duty_gui.py` 只負責按鈕、共用路徑與工具事件；新分類核心與對話窗各自維持單一職責。所有本機結果寫入 `runtime_outputs`，不參與更新包。

**Tech Stack:** Python 3.11+、CustomTkinter、Tkinter、unittest。

## Global Constraints

- 不變更 NAS、後台、登入憑證或 Google Site。
- 不新增第三方套件。
- 不降低來源刪除的驗證條件。
- 不刪除原有獨立影片分類專案的檔案。

---

### Task 1: 匯入分類核心並建立回歸測試

**Files:**
- Create: `WinPython_公務電腦使用包/rescue_video_classifier.py`
- Create: `tests/test_rescue_video_tool.py`
- Modify: `tests/test_smoke.py`

- [ ] 寫入會失敗的測試：新模組可匯入、套件含分類核心與 CustomTkinter 對話窗、分類器在檔案驗證失敗時保留來源。
- [ ] 執行測試，確認因模組尚未存在而失敗。
- [ ] 移植既有分類核心，將預設工作紀錄與報告路徑改為由值班台傳入的套件內路徑。
- [ ] 執行核心測試確認通過。

### Task 2: 建立 CustomTkinter 分類對話窗

**Files:**
- Create: `WinPython_公務電腦使用包/rescue_video_dialog.py`
- Modify: `tests/test_rescue_video_tool.py`

- [ ] 寫入會失敗的測試：對話窗入口接受主視窗、比較資料夾、報告資料夾與工具事件回呼。
- [ ] 執行測試，確認因對話窗尚未存在而失敗。
- [ ] 實作 `CTkToplevel` 表單、結果表、背景執行、預檢與刪除確認；不使用 `tk.Tk()`。
- [ ] 執行對話窗與核心測試確認通過。

### Task 3: 加入每日作業第三項與封裝驗證

**Files:**
- Modify: `WinPython_公務電腦使用包/duty_gui.py:69-71`
- Modify: `WinPython_公務電腦使用包/duty_gui.py:1339-1351`
- Modify: `WinPython_公務電腦使用包/duty_gui.py:4173-4231`
- Modify: `WinPython_公務電腦使用包/update_package.ps1:275-291`
- Modify: `tests/test_smoke.py`

- [ ] 寫入會失敗的測試：每日作業有第三個按鈕、開啟方法會傳入 `COMPARISON_OUTPUT_DIR` 與 `RUNTIME_OUTPUT_DIR / "rescue_video"`、更新備份包含兩個新程式。
- [ ] 執行測試，確認因按鈕與入口尚未存在而失敗。
- [ ] 將每日作業欄位調整為三欄，加入「救護行車影片」按鈕與薄包裝開啟方法；沿用既有工具事件回呼。
- [ ] 更新備份清單與 smoke 測試。
- [ ] 執行完整測試、編譯檢查及 GUI 手動開啟測試。
