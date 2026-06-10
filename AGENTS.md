# AGENTS.md

1. 貼上程式碼時，講述總共有幾行。
2. 修改其中一段程式碼時，講述是第幾行到第幾行，且要對齊原本格式。
3. 不能隨意刪除檔案，需通過使用者確認。
4. 每次在本專案開始工作前，先確認雲端 `專案\skill` 內所有含 `SKILL.md` 的 skills，並全部同步到本機 `%USERPROFILE%\.codex\skills` 後再使用。

## Language

- 回覆使用繁體中文，除非使用者要求英文。

## Project map

- `docs/`: 專案文件。
- `tmp/`: 暫存與實驗檔，不要提交。
- `outputs/`: 程式產出檔，不要提交。
- `archive/`: 舊版或備份檔，除非使用者要求，不要主動讀。
- `logs/`: log 檔，不要提交。
- `tests/`: 測試檔。
- `scripts/`: 一次性工具腳本。
- `duty_sheet_legacy/`: 勤務表舊版流程與設定。
- `daily_vehicle_legacy/`: 每日車輛舊版 Selenium 流程。
- `WinPython_公務電腦使用包/`: 公務電腦可攜執行包。

## Current work

- 目前工作重點是讓另一個公務自動化專案可登入與登打四個公務網站。
- 四個公務網站使用同一組已授權的公務帳號密碼，但每個網站仍需明確列入允許清單後才能使用。
- 優先採用專用 Chrome Profile 保存登入狀態，不直接依賴日常 Chrome Profile。
- Chrome Profile 的用途是保留 session、cookie 與登入狀態；不要把它視為可被 Selenium 穩定操作的帳號密碼下拉選單。
- 若網站未保持登入，優先分析該網站的實際登入流程，再決定是由程式填入網頁 input，或提示使用者手動完成一次登入。
- 不要在新專案重複寫死帳號密碼；應使用既有受控設定來源或共用 credential loader。
- log、截圖、錯誤訊息與回覆內容不得顯示密碼、token、cookie 或其他憑證內容。

## Operation modes

- 值班模式：用於正式執行日常勤務登打、車輛或其他公務網站資料填報；重點是依既有流程穩定完成輸入、送出前確認、保存結果與回報異常。
- 審核模式：用於送出前或送出後檢查資料是否正確，包含比對來源資料、檢查缺漏、確認欄位值、標示異常項目；此模式原則上不主動送出或修改正式資料，除非使用者明確要求。
- 設定模式：用於維護網站清單、帳號設定來源、Chrome Profile 路徑、欄位對應、預設值與執行參數；不得顯示或回報密碼、token、cookie。
- 登入維護模式：用於處理 Chrome Profile、session、cookie、Google 帳號狀態與公務網站登入狀態；優先讓使用者手動完成必要的一次性登入，再由程式沿用狀態。
- 除錯模式：用於定位流程卡住的位置、元素選取失敗、網站改版、驗證碼、權限或 session 過期問題；除錯輸出不得包含憑證或敏感個資。
- 手動協助模式：當網站阻擋自動化、需要人工確認、驗證碼或二階段驗證時，程式應停在可操作畫面，提示使用者手動處理後再繼續。
- 測試模式：用於驗證流程、欄位定位、資料轉換與登入狀態；不得對正式網站送出不可回復的資料，除非使用者明確確認。

## Working rules

- 開始修改前，先找出最小相關檔案集合。
- 不要無限制掃描整個 repo。
- 不要主動讀取 `archive/`、`tmp/`、`outputs/`、`logs/`，除非使用者明確要求。
- 優先修改既有檔案，不要建立重複檔。
- 大改前先提出 plan。
- 不要改動 `.env`、密鑰、憑證、production config。
- 不要新增 dependency，除非使用者明確同意。
- 不要修改程式邏輯，除非任務明確要求。
- 啟動 SinpoSmart GUI 時，預設使用無黑窗模式：優先用 `WinPython_公務電腦使用包\RUN_DUTY_GUI_WINPYTHON.bat`、`duty_gui.pyw` 或 `pythonw.exe`；不要直接用 `py duty_gui.py`、`python duty_gui.py` 或會留下黑色 console 視窗的方式啟動，除非正在做明確的 console 除錯。

## Python file policy

- 不要任意新增 `.py` 檔。
- 優先修改既有 `.py` 檔，而不是建立新版本。
- 禁止建立 `*_new.py`、`*_fixed.py`、`*_final.py`、`*_backup.py`、`*_old.py`、`copy_*.py`、`test2.py`、`try.py`、`demo.py`。
- 不要為了避開修改既有檔案而建立新的 Python 檔。
- 不要為同一功能建立多個替代實作。
- 暫存實驗檔只能放 `tmp/`，而且不能被正式程式 import。
- 一次性工具腳本放 `scripts/`。
- 測試放 `tests/`。
- 正式程式留在目前既有位置，除非使用者明確要求重構。

新增任何 `.py` 檔前，必須先回答：

1. 這個檔案的職責是什麼？
2. 為什麼不能加到既有檔案？
3. 這個檔案會被誰 import 或執行？
4. 它是正式程式、測試、工具腳本，還是暫存實驗？
5. 要怎麼測試？
6. 是否會造成重複邏輯？

理由不充分時，請修改既有檔案。

## Python movement policy

- 不要搬移現有 `.py` 檔，除非使用者明確要求。
- 搬移 Python 檔可能破壞 import、相對路徑、排程、捷徑、啟動指令與自動化流程。
- 搬移任何 `.py` 檔前，必須先分析：
  1. 誰 import 它
  2. 它如何被執行
  3. 是否使用相對路徑
  4. 是否被排程器、捷徑、bat、PowerShell 或外部工具呼叫
  5. 要怎麼測試搬移後仍可執行
- 不要搬移 main.py、app.py、run.py、bot.py、config 檔或任何可執行腳本，除非使用者確認。

## Ignore policy

- 不要提交 cache、logs、build output、temporary files、outputs。
- 不要提交 `.env`、key、pem、token、secret、credentials。
- 發現敏感檔案時，只回報風險，不要讀取內容。

## Git commit rules

- commit 前先執行 `git status --short`，確認只包含本次任務相關檔案。
- 不要把 `tmp/`、`outputs/`、`logs/`、cache、build output 或敏感檔案加入 commit。
- commit 前回報預計提交的檔案清單；若有不確定是否屬於本次任務的變更，先詢問使用者。
- commit message 使用繁體中文或清楚的英文，內容需描述實際變更，不使用 `update`、`fix` 這類過度籠統訊息。
- 未經使用者要求，不要自動建立 commit。
- 若使用者要求 commit，先測試或說明無法測試的原因，再提交。
- commit 後回報 commit hash 與提交檔案摘要。

## Completion report

每次完成任務後，必須回報：

1. 修改了哪些檔案
2. 新增了哪些檔案
3. 是否新增 `.py` 檔
4. 是否搬移 `.py` 檔
5. 執行了哪些測試
6. 哪些風險尚未處理
