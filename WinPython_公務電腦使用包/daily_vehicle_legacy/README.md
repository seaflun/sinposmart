# 每日車輛自動化

這個資料夾目前只保留 Selenium 車輛流程。公務電腦使用包的 GUI 會透過外層 `daily_vehicle_automation.py` 啟動 `automation/ppe_selenium_daily.py`，並把目前登入帳號暫時傳入執行環境；本資料夾沒有 Flask `app.py`、Web 控制頁或 LINE Webhook 入口。

## 檔案

- `automation/ppe_selenium_daily.py`：Selenium 車輛保養清點流程
- `requirements-selenium.txt`：直接執行 Selenium 腳本時需要的 Python 依賴
- `.env.example`：直接執行腳本時可複製成 `.env` 的範例設定

## `.env` 設定

透過外層 GUI 執行時，帳號與密碼由 GUI 傳入，不需要在這裡建立 `.env`。若要直接測試 Selenium 腳本，先複製 `.env.example` 成 `.env`，再填入：

```dotenv
PPE_ACCOUNT=...
PPE_PASSWORD=...
HEADLESS=true
KEEP_BROWSER_OPEN=false
SELENIUM_TIMEOUT_SECONDS=60
SELENIUM_REMOTE_READY_TIMEOUT_SECONDS=180
SELENIUM_REMOTE_URL=
LINE_CHANNEL_ACCESS_TOKEN=...
LINE_TO_USER_ID=Uxxxxxxxx
LINE_TO_USER_IDS=
SEND_LINE_RESULT=true
```

說明：

- `PPE_ACCOUNT` / `PPE_PASSWORD`：直接執行腳本時使用的 PPE 登入帳號密碼
- `SELENIUM_REMOTE_URL`：留空時使用本機 Chrome；若要接遠端 Selenium Grid，再填入遠端網址
- `LINE_CHANNEL_ACCESS_TOKEN`：需要推播執行結果時才填寫的 LINE Bot channel access token
- `LINE_TO_USER_ID` / `LINE_TO_USER_IDS`：推播執行結果的對象；多個對象可用逗號分隔填在 `LINE_TO_USER_IDS`
- `SEND_LINE_RESULT`：直接執行 Selenium 腳本時是否由腳本自行推播結果

## 本機啟動

公務電腦日常使用請從外層 GUI 按鈕啟動。若要單獨測試本流程：

```powershell
py -m pip install -r requirements-selenium.txt
py automation\ppe_selenium_daily.py
```

## 執行結果

- 成功時會更新 `artifacts/selenium-last-run.png` 與 `artifacts/selenium-last-run.html`
- 失敗時會保留 `artifacts/selenium-error.*`
- 若 `SEND_LINE_RESULT=true` 且 LINE 設定完整，腳本會推播成功或失敗訊息
