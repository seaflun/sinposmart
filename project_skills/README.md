# Project Skills

本目錄只保留專案特有的 skill 指引；工程流程採用已安裝的 Matt Pocock engineering skills，不再保存或啟用 Superpowers 的專案內副本。NAS、Worker、Release、帳密、資料安全與正式環境驗證等專案規範仍以 `AGENTS.md` 與其對應專案特有 skill 為準。

## Canonical source and synchronization

Matt Pocock engineering skills 的唯一來源是共享雲端資料夾 `G:\我的雲端硬碟\專案\SKILL`。每次在本專案開始工作前，從目前 repo 向上找到並執行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "G:\我的雲端硬碟\專案\SKILL\install-skills-from-cloud.ps1"
```

此腳本會把所有已啟用、含 `SKILL.md` 的雲端 skills 平面同步到 `%USERPROFILE%\.codex\skills`，並驗證完整資料夾 fingerprint。若找不到腳本、同步失敗或 fingerprint 不一致，應停止工作。不要把工程 skill 複製回本目錄；以雲端來源加同步腳本作為單一真實來源，避免全域 skill 與專案副本版本漂移。

目前工程 skill 包含：`ask-matt`、`implement`、`tdd`、`code-review`、`diagnosing-bugs`、`grill-me`、`grill-with-docs`、`to-spec`、`to-tickets`、`triage`、`wayfinder`、`handoff`、`research`、`codebase-design`。

## Workflow selection

| 情境 | 使用流程 |
| --- | --- |
| 明確、可於單一 session 完成的小修改 | `implement` |
| 需求模糊且已有程式庫 | `grill-with-docs` |
| 需求模糊且沒有程式庫 | `grill-me` |
| 大型、跨 session 或多人／多 ticket 工作 | `grill-with-docs` → `to-spec` → `to-tickets` → 每張 ticket 使用 `implement` |
| 外部尚未整理的 bug、需求或 PR | `triage` → `implement` |
| 難重現、間歇性或效能退化問題 | `diagnosing-bugs` → 回歸測試 → `implement` |
| 路徑不明的大型工作 | `wayfinder` → `to-spec` → `to-tickets` |
| 不確定流程 | `ask-matt` |
| 需要換 session 或交接 | `handoff` |

`tdd` 用於可測的公開行為：先確認 public seam，再用小型 Red-Green 行為切片實作；避免對私有實作細節或任意 CSS 字串建立脆弱測試。完成後以 `code-review` 的 Standards／Spec 兩軸審查；必須提供明確比較基準，無規格時明記 Spec 無可比對規格。

## Examples

### UI 小修正

`implement` → 確認公開頁面與預期顯示 → `tdd` 建立最小回歸測試 → 修改模板／元件 → 執行相關頁面測試 → `code-review`。

### NAS／Worker 發版

`grill-with-docs` 或既有規格 → `to-spec`／`to-tickets`（大型修改時）→ `implement` → 單元與整合測試 → `code-review` → 依專案 Release State Ladder 執行 Source、Build、Release、NAS、Worker 驗證。

不要在本目錄放入 secrets、tokens、passwords、`.env`、logs 或 runtime output。
