# 班末工作完成後自動登出 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓班末值退不論手動或自動完成，都在原定交接時間 10 分鐘後檢查當班交接群組；完成才登出，未完成則每 10 分鐘重查，最後發布新的 SinpoSmart 公務電腦版本。

**Architecture:** 保留既有 Tk `after` 計時器與登入狀態，另保存原始交接時間，讓重查時間與班末分離。完成判斷沿用 `duty_action_compare`、`executed_due`、`manual_completed_keys`，只檢查同一交接時間、同一執行人員的 `entry_log` 與 `work_log`。

**Tech Stack:** Python 3.11、Tk/customtkinter、`unittest`、PowerShell、GitHub CLI。

## Global Constraints

- 不修改 `duty_rehearsal.py` 的勤務規劃邏輯。
- 不修改 NAS 後台或 `G:\我的雲端硬碟\專案\救護返隊小幫手\ambulance_return_bot`。
- 不新增 dependency，不新增或搬移 `.py` 檔。
- 不讀取、還原、stage 或打包 `WinPython_公務電腦使用包/duty_sheet_legacy/config.json`。
- release 固定包含 `sinposmart-version.txt`、`sinposmart-public-package.zip`、`sinposmart-public-package.zip.sha256.txt`。
- 每個 production 行為都先新增測試並確認 RED，再做最小 GREEN 修改。

---

### Task 1: 建立自動登出回歸測試

**Files:**
- Modify: `tests/test_smoke.py:459`

**Interfaces:**
- Consumes: `DutyGui.should_schedule_auto_logout`、`schedule_auto_logout`、`run_auto_logout`、`trigger_due_tasks`。
- Produces: 手動值退、10 分鐘重查、重啟補排三組行為契約。

- [x] **Step 1: 更新既有測試狀態欄位**

在兩個既有自動登出測試的 GUI stub 加入：

```python
gui.auto_logout_handoff_at = None
gui.pending_auto_logout_handoff_at = None
```

- [x] **Step 2: 新增手動值退仍排定班末加 10 分鐘的測試**

```python
def test_manual_handoff_checkout_schedules_auto_logout_from_planned_time(self) -> None:
    module = duty_gui_module()
    gui = object.__new__(module.DutyGui)
    scheduled = []
    gui.auto_logout_after_id = None
    gui.auto_logout_deadline = None
    gui.auto_logout_handoff_at = None
    gui.auto_logout_actor_no = ""
    gui.pending_auto_logout_deadline = None
    gui.pending_auto_logout_handoff_at = None
    gui.pending_auto_logout_actor_no = ""
    gui.submit_queues = {"entry": [], "work": []}
    gui.submit_worker_running = {"entry": False, "work": False}
    gui.manual_paused_due_indices = {}
    gui.duty_status_text = type("Status", (), {"set": lambda self, value: setattr(self, "value", value)})()
    gui.after = lambda delay, callback: scheduled.append((delay, callback)) or "after-id"
    gui.after_cancel = lambda _after_id: None
    gui.action_datetime = lambda _action: datetime(2026, 7, 10, 18, 0)
    action = {"kind": "entry_log", "source": "值班交接", "fields": {"出或入": "值退"}}

    self.assertTrue(gui.should_schedule_auto_logout(action, "manual"))
    gui.schedule_auto_logout("28", action)

    self.assertEqual(gui.auto_logout_handoff_at, datetime(2026, 7, 10, 18, 0))
    self.assertEqual(gui.auto_logout_deadline, datetime(2026, 7, 10, 18, 10))
    self.assertEqual(gui.auto_logout_actor_no, "28")
    self.assertEqual(len(scheduled), 1)
```

- [x] **Step 3: 新增未完成時每 10 分鐘重查且忽略下一班的測試**

建立 18:00 同一執行人員的值退、值班、工作三筆，另放一筆 20:00 下一班動作。第一次把 18:00 工作設為 `todo`，呼叫 `run_auto_logout(...)` 後驗證沒有登出、`auto_logout_deadline == 18:20`、狀態含「1 筆未完成」。再把工作設為 `done` 並執行 18:20 callback，驗證 `clear_login(trigger_type="system")` 被呼叫；20:00 動作保持 `todo`，證明不會阻擋。

- [x] **Step 4: 新增已完成值退在排程迴圈補建計時器的測試**

建立 `executed_due={0}` 且比較結果為 `done` 的 18:00 值退，呼叫 `trigger_due_tasks(datetime(2026, 7, 10, 18, 0))`，驗證 `ensure_auto_logout_scheduled("28", action)` 仍被呼叫，且不會再次送出勤務資料。

- [x] **Step 5: 執行目標測試並確認 RED**

Run:

```powershell
py -m unittest `
  tests.test_smoke.PackageSmokeTests.test_manual_handoff_checkout_schedules_auto_logout_from_planned_time `
  tests.test_smoke.PackageSmokeTests.test_auto_logout_rechecks_until_handoff_group_is_complete `
  tests.test_smoke.PackageSmokeTests.test_completed_handoff_checkout_restores_auto_logout_timer -v
```

Expected: 3 項因 production 尚未支援手動排程、交接群組檢查與補排而失敗，不得是 import 或語法錯誤。

---

### Task 2: 實作班末完成檢查與週期重查

**Files:**
- Modify: `WinPython_公務電腦使用包/duty_gui.py:873-877`
- Modify: `WinPython_公務電腦使用包/duty_gui.py:3522-3607`
- Modify: `WinPython_公務電腦使用包/duty_gui.py:4375-4391`
- Modify: `WinPython_公務電腦使用包/duty_gui.py:4742-4783`

**Interfaces:**
- Produces: `auto_logout_handoff_at: datetime | None`、`pending_auto_logout_handoff_at: datetime | None`。
- Produces: `auto_logout_group_indices(actor_no: str, handoff_at: datetime) -> list[int]`。
- Produces: `ensure_auto_logout_scheduled(actor_no: str, action: dict[str, Any]) -> None`。
- Changes: `set_auto_logout_timer(actor_no, deadline, handoff_at)` 與 `run_auto_logout(expected_actor, expected_deadline, expected_handoff_at)`。

- [x] **Step 1: 加入原始交接時間狀態並在取消／暫停轉移時完整清除或保留**

在初始化加入兩個 datetime 狀態；`cancel_auto_logout()` 清除兩者；`hold_auto_logout_for_manual_pause()` 將 `auto_logout_handoff_at` 一併移到 `pending_auto_logout_handoff_at`。

- [x] **Step 2: 允許 manual 與 due 值退建立自動登出**

```python
def should_schedule_auto_logout(self, action: dict[str, Any], trigger_type: str) -> bool:
    if trigger_type not in ("manual", "due") or action.get("kind") != "entry_log":
        return False
    fields = action.get("fields", {})
    return str(action.get("source", "")).strip() == "值班交接" and str(fields.get("出或入", "")).strip() == "值退"
```

- [x] **Step 3: 保存交接時間並避免相同班末被重複排定**

`schedule_auto_logout()` 以 `handoff_at + timedelta(minutes=10)` 建立首次檢查；pending 與 active timer 都保存 `handoff_at`。`ensure_auto_logout_scheduled()` 比對人員與 `handoff_at`，相同班末已有 active 或 pending timer 時直接返回。

- [x] **Step 4: 實作同一交接群組完成判斷**

```python
def auto_logout_group_indices(self, actor_no: str, handoff_at: datetime) -> list[int]:
    return [
        index
        for index, action in enumerate(self.duty_actions)
        if action.get("kind") in ("entry_log", "work_log")
        and str(action.get("actor", "")) == str(actor_no)
        and self.action_datetime(action) == handoff_at
    ]
```

`run_auto_logout()` 先確認 session、人員、deadline、handoff 全部仍相符，再同步比較結果。佇列執行中、手動暫停或交接群組仍有未完成項目時，以 `datetime.now() + timedelta(minutes=10)` 重新排定相同 handoff；全部完成才呼叫 `clear_login(trigger_type="system")`。

- [x] **Step 5: 在排程迴圈補建已完成值退的計時器**

把 `action`、kind、人員與 `action_at` 判斷移到 `executed_due` 之前；若是已到點的班末值退，先呼叫 `ensure_auto_logout_scheduled()`，再依既有完成狀態決定是否跳過登打。

- [x] **Step 6: 執行目標測試確認 GREEN**

Run: Task 1 Step 5 的完整命令。

Expected: 3 項通過。

- [x] **Step 7: 執行完整 smoke 與編譯驗證**

```powershell
py -m unittest tests.test_smoke -v
py -m py_compile `
  "WinPython_公務電腦使用包\duty_gui.pyw" `
  "WinPython_公務電腦使用包\duty_gui.py" `
  "WinPython_公務電腦使用包\duty_rehearsal.py" `
  "WinPython_公務電腦使用包\compare_rehearsal_records.py" `
  "WinPython_公務電腦使用包\duty_sheet_automation.py" `
  "WinPython_公務電腦使用包\daily_vehicle_automation.py" `
  "WinPython_公務電腦使用包\rest_time_automation.py" `
  "WinPython_公務電腦使用包\check_environment.py"
```

Expected: smoke 全數通過，`py_compile` exit 0。

---

### Task 3: 建立並驗證公務電腦更新包

**Files:**
- Modify: `WinPython_公務電腦使用包/VERSION.txt`
- Modify: `UPDATE/VERSION.txt`
- Modify: `UPDATE/sinposmart-version.txt`
- Generate ignored assets: `UPDATE/sinposmart-public-package.zip`、`UPDATE/sinposmart-public-package.zip.sha256.txt`

- [x] **Step 1: 產生本地版本並執行固定打包腳本**

```powershell
$version = Get-Date -Format "yyyy.MM.dd.HHmm"
powershell -NoProfile -ExecutionPolicy Bypass -File `
  "$env:USERPROFILE\.codex\skills\sinposmart-update-package\scripts\build_update_package.ps1" `
  -ProjectRoot (Resolve-Path '.').Path -Version $version
```

- [x] **Step 2: 建立 GitHub Release 固定資產名稱**

```powershell
Copy-Item -LiteralPath 'UPDATE\WinPython_公務電腦使用包.zip' -Destination 'UPDATE\sinposmart-public-package.zip' -Force
$hash = (Get-FileHash -LiteralPath 'UPDATE\sinposmart-public-package.zip' -Algorithm SHA256).Hash.ToLowerInvariant()
$version | Set-Content -LiteralPath 'UPDATE\sinposmart-version.txt' -Encoding UTF8
"$hash  sinposmart-public-package.zip" | Set-Content -LiteralPath 'UPDATE\sinposmart-public-package.zip.sha256.txt' -Encoding UTF8
```

- [x] **Step 3: 驗證 zip 版本與敏感檔排除**

打開 canonical zip，驗證包含 `duty_gui.py` 與 `VERSION.txt`；`VERSION.txt` 等於 `$version`；不得包含 `duty_sheet_legacy/config.json`、service account JSON、`.env`、runtime outputs、logs、tmp、snapshots 或 Excel 活頁簿；本地 SHA 必須等於 sha256 檔。

---

### Task 4: Commit、Push、Release 與遠端讀回

**Files to stage:**
- `docs/superpowers/specs/2026-07-10-auto-logout-work-record-check-design.md`
- `docs/superpowers/plans/2026-07-10-auto-logout-work-record-check.md`
- `tests/test_smoke.py`
- `WinPython_公務電腦使用包/duty_gui.py`
- `WinPython_公務電腦使用包/VERSION.txt`
- `UPDATE/VERSION.txt`
- `UPDATE/sinposmart-version.txt`

- [x] **Step 1: 執行 commit 前完整驗證與 staged scope 檢查**

重新執行完整 smoke、`py_compile`、zip 檢查、`git diff --check`。只用明確路徑 `git add` 上述 7 個檔案；確認 runtime `config.json` 仍未 stage。

- [ ] **Step 2: 建立 release commit 並 push**

```powershell
git commit -m "修正班末工作完成後自動登出並發布 $version"
git push -u origin (git branch --show-current)
```

- [ ] **Step 3: 建立 GitHub Release**

```powershell
$tag = "public-package-$version"
gh release create $tag `
  'UPDATE\sinposmart-version.txt' `
  'UPDATE\sinposmart-public-package.zip' `
  'UPDATE\sinposmart-public-package.zip.sha256.txt' `
  --target (git branch --show-current) `
  --title "SinpoSmart 公務電腦更新包 $version" `
  --notes "修正班末值退提前手動完成時未排定自動登出；班末 10 分鐘後檢查當班交接紀錄，未完成每 10 分鐘重查。"
```

- [ ] **Step 4: 驗證 latest 與直接 tag 下載**

用 `gh release list --limit 3` 確認新 tag 為 Latest。分別從 `releases/latest/download` 與 `releases/download/$tag` 下載三個資產，驗證版本檔、zip 內 `VERSION.txt`、下載 zip SHA 與下載 sha256 檔四者完全一致。

- [ ] **Step 5: 最終 git 與 release 讀回**

確認 `git status --short` 只剩使用者自有 runtime config 刪除；記錄 commit hash、tag、版本、SHA、release URL 與直接下載驗證結果。
