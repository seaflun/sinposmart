# 每日車輛自動化

這個專案提供兩種入口：

- Web 控制頁：手動按下執行
- LINE Messaging API Webhook：收到 `幫我點今日車輛` 後自動執行

執行內容由 `automation/ppe_selenium_daily.py` 負責，完成後可把結果推回 LINE。

## 檔案

- `app.py`：Flask Web 入口、背景執行、LINE webhook
- `automation/ppe_selenium_daily.py`：Selenium 車輛流程
- `compose.nas.yml`：NAS / Docker Compose 參考
- `requirements-selenium.txt`：Python 依賴
- `.env`：帳號、LINE、Selenium 設定

## `.env` 設定

先複製 `.env.example` 成 `.env`，再填入：

```dotenv
PPE_ACCOUNT=...
PPE_PASSWORD=...
HEADLESS=true
KEEP_BROWSER_OPEN=false
SELENIUM_TIMEOUT_SECONDS=60
SELENIUM_REMOTE_READY_TIMEOUT_SECONDS=180
SELENIUM_REMOTE_URL=http://selenium:4444/wd/hub
LINE_CHANNEL_ACCESS_TOKEN=...
LINE_CHANNEL_SECRET=...
LINE_TO_USER_ID=Uxxxxxxxx
LINE_TO_USER_IDS=
LINE_WEBHOOK_COMMAND=run_daily_vehicle
SEND_LINE_RESULT=true
WEB_HOST=0.0.0.0
WEB_PORT=8080
```

說明：

- `LINE_CHANNEL_ACCESS_TOKEN`：LINE Bot channel access token
- `LINE_CHANNEL_SECRET`：LINE webhook 驗證簽章用
- `LINE_TO_USER_ID`：沒有 webhook 來源可回推時的預設對象
- `LINE_WEBHOOK_COMMAND`：允許觸發的文字指令，建議先用 `run_daily_vehicle`
- `SEND_LINE_RESULT`：直接執行 Selenium 腳本時是否由腳本自行推播

## 本機啟動

```powershell
py -m pip install -r requirements-selenium.txt
py app.py
```

啟動後可用：

- `GET /` 查看控制頁
- `POST /run` 手動觸發
- `GET /status` 查看目前狀態
- `POST /line/webhook` 接收 LINE 訊息

## LINE Webhook 流程

1. 在 LINE Developers 後台把 webhook URL 指到 `https://你的網域/line/webhook`
2. 啟用 webhook
3. 使用者傳送 `run_daily_vehicle` 或 `幫我點今日車輛`
4. 伺服器會先回 `已收到，開始執行每日車輛流程。`
5. 背景流程完成後，再用 push message 回報成功或失敗

## 執行結果

- 成功時會更新 `artifacts/selenium-last-run.png` 與 `artifacts/selenium-last-run.html`
- 失敗時會保留 `artifacts/selenium-error.*`
- Web 頁面可查看最近執行 log
