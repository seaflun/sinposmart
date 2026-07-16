# SinpoSmart Google Site 值班看板

## 已部署組成

- 值班 GUI 從當日勤務表建立完整班表 payload，啟動後及每個整點最多同步一次。
- 同步 Apps Script 只接受具備同步金鑰的 HTTPS POST，資料有變化才覆寫 Drive 內的看板 JSON。
- 顯示 Apps Script 從同一個 JSON 讀取資料，僅呈現目前時段、下一時段與更新時間。
- Google Site 的既有「自動化」頁已嵌入顯示 Apps Script；「值班人員」頁的靜態名單不會被同步程式修改。

## 公務電腦設定

在執行值班 GUI 的 Windows 使用者環境設定下列變數後，重新開啟 GUI：

```text
SINPOSMART_DUTY_BOARD_SYNC_URL
SINPOSMART_DUTY_BOARD_SYNC_KEY
SINPOSMART_DUTY_BOARD_SYNC_TIMEOUT_SECONDS=8
```

前兩項由管理者以安全方式提供；不要寫入程式碼、批次檔、Git、截圖或日誌。未設定時 GUI 會略過看板同步，既有值班流程不受影響。

## Google 端維護

Apps Script 與資料檔均由 `sinpo666@gmail.com` 管理，放在指定的值班看板 Drive 資料夾。兩個 Apps Script 專案都使用 Script Properties：

- 同步專案：`DUTY_BOARD_FOLDER_ID`、`DUTY_BOARD_SYNC_KEY`
- 顯示專案：`DUTY_BOARD_FOLDER_ID`

顯示網頁程式必須維持「以部署者身分執行」與「僅限 sinpo666@gmail.com」存取。平板開啟看板前，請以該帳號登入。

## 日常驗證與金鑰輪替

1. 啟動值班 GUI，並確認可讀取當日勤務表。
2. 等待首次同步完成後，在 Google Site 的「自動化」頁確認目前與下一時段資料。
3. 若需輪替同步金鑰，同時更新同步 Apps Script 的 `DUTY_BOARD_SYNC_KEY` 與公務電腦的 `SINPOSMART_DUTY_BOARD_SYNC_KEY`；輪替完成後以一次實際班表同步驗證。

不要以測試假資料覆寫正式看板。若要停用同步，移除公務電腦上的兩個同步環境變數即可。
