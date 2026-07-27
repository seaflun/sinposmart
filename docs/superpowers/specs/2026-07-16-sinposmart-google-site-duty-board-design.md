# SinpoSmart Google Site 值班看板設計規格

## 目標

讓公務電腦上的 WinPython 值班 GUI 每小時從 SinpoSmart 勤務表讀取整個勤務日的資料，透過網頁同步至 Google Drive 的 JSON 檔；平板以 `sinpo666@gmail.com` 登入既有 Google Site 後，只顯示目前時段、下一時段與資料更新時間。

## 範圍與限制

- 不建立新的 Google Site 頁面；僅在既有「值班人員」頁嵌入動態區塊。
- 平板僅負責顯示，不執行同步、不登入勤務系統，也不需要 Google Drive 桌面版。
- 公務電腦沒有 Google Drive 桌面版，因此必須用 HTTPS 將資料送至 Apps Script。
- SinpoSmart 勤務表是唯一資料來源；Google Site 的靜態人員清單不是資料來源。
- Apps Script 專案與 JSON 檔放在 `sinpo666@gmail.com` 指定的 Google Drive 資料夾。
- 不改 NAS runtime、不修改值班後台、不送出或變更勤務網站的正式資料。
- 不在程式碼、Git、Google Site、截圖或 log 儲存密碼、cookie、token 或同步密鑰。

## 元件與責任

### 1. WinPython 值班 GUI

- 沿用既有勤務表讀取流程，取得整個勤務日的時段、值班番號與姓名。
- 值班模式登入成功後同步一次；執行期間每小時再讀取與同步一次。
- 將完整勤務日資料正規化為看板 JSON，不只傳送當下值班人員。
- 比較正規化內容雜湊；資料未變更時不呼叫遠端寫入。
- 以 HTTPS POST 將 JSON 與獨立同步密鑰送至同步 Apps Script。
- 送出失敗時顯示安全訊息並保留既有看板資料；下個整點再嘗試。

### 2. 同步 Apps Script

- 是小型、只寫入的網頁端點；公務電腦不需要登入 Google。
- 只接受 POST；驗證請求內容中的獨立同步密鑰。
- 驗證通過後，讀取指定 Drive JSON 的內容雜湊；不同才覆寫同一個 JSON 檔。
- 回覆只包含成功與是否變更，不回傳勤務表內容。
- 拒絕無效密鑰或不符合資料格式的請求，且不記錄密鑰。

### 3. 顯示 Apps Script

- 只限 `sinpo666@gmail.com` 存取，讀取同一個私有 JSON 檔並產生簡潔 HTML。
- 依 `Asia/Taipei` 時間從完整時段資料選出目前與下一時段的人員。
- 顯示最後一次資料變更時間；尚無資料時顯示「尚無值班資料」。
- 僅提供給既有 Google Site iframe 使用，不提供 JSON 下載或同步入口。

### 4. 平板

- 以 `sinpo666@gmail.com` 登入並開啟既有 Google Site。
- 只顯示嵌入式看板；不需安裝程式或配置同步。

## 資料格式

JSON 只包含看板所需資訊：格式版本、勤務日期、最後內容變更時間，以及完整勤務日的時段清單。每個時段保留開始時間、結束時間、值班番號與對應姓名。

內容雜湊只根據勤務日期與時段清單產生；擷取時間不參與計算，避免相同資料造成重複遠端寫入。

顯示端從完整時段清單自行計算目前與下一時段，避免只傳送「當下人員」而在時段交接時顯示舊資料。

## 受控設定

- 公務電腦以本機、未納入 Git 的設定保存同步 Apps Script 基本網址與同步密鑰。
- 同步 Apps Script 以 Script Properties 保存目標 JSON 檔案 ID 與同一組同步密鑰。
- 顯示 Apps Script 以 Script Properties 保存目標 JSON 檔案 ID。
- 不使用 NAS 後台事件密鑰，不共用既有帳密同步設定。

## 使用流程

1. 值班 GUI 成功登入後讀取完整勤務日資料。
2. GUI 將時段、番號與姓名轉為看板 JSON，內容不同才 POST 至同步 Apps Script。
3. 同步 Apps Script 更新 Google Drive 的單一 JSON 檔。
4. 顯示 Apps Script 讀取 JSON 並輸出目前／下一時段區塊。
5. 平板在既有 Google Site 看見動態區塊。

## 失敗行為

- 勤務表無法讀取：不寫入空資料；平板維持上一份有效資訊。
- 網頁同步失敗：GUI 顯示安全錯誤訊息；下個整點重試。
- JSON 不存在或無法解析：顯示端顯示「尚無值班資料」，不顯示技術細節。
- 同步密鑰不符：同步端拒絕請求，不改寫 Drive JSON。

## 驗收標準

1. GUI 可擷取完整勤務日的時段、值班番號與姓名，且不送出勤務網站資料。
2. 初次同步後，Drive 指定資料夾只有一份有效 JSON；資料不變時不改寫。
3. 資料變更後，JSON 更新，平板在既有 Google Site 顯示正確的目前與下一時段人員。
4. 平板只使用 `sinpo666@gmail.com` 觀看；其他帳號不得存取顯示 Apps Script。
5. 網路、勤務表或同步失敗時，平板不會變成空白看板。
6. 公務電腦、log、Git 與 Google Site 均不出現憑證或同步密鑰。

## 不在本次範圍

- NAS 後台、`/admin/sinposmart`、事件 API 或容器部署。
- Google Drive 桌面版安裝或平板端資料寫入。
- 多台公務電腦同時寫入、複雜重試機制、公開看板或歷史查詢。
