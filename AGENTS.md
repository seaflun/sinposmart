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

## Working rules

- 開始修改前，先找出最小相關檔案集合。
- 不要無限制掃描整個 repo。
- 不要主動讀取 `archive/`、`tmp/`、`outputs/`、`logs/`，除非使用者明確要求。
- 優先修改既有檔案，不要建立重複檔。
- 大改前先提出 plan。
- 不要改動 `.env`、密鑰、憑證、production config。
- 不要新增 dependency，除非使用者明確同意。
- 不要修改程式邏輯，除非任務明確要求。

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

## Completion report

每次完成任務後，必須回報：

1. 修改了哪些檔案
2. 新增了哪些檔案
3. 是否新增 `.py` 檔
4. 是否搬移 `.py` 檔
5. 執行了哪些測試
6. 哪些風險尚未處理
