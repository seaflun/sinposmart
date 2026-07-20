# SinpoSmart 值班 GUI 定時清理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓長期運行的值班 GUI 每天 03:00 清理逾期執行資料，並只保留 30 天的每日勤務表與夜間勤務 PNG。

**Architecture:** 沿用現有檔案期限規則，抽出接受規則集合與基準時間的通用清理函式。GUI 啟動時清理一次，之後用 Tkinter `after` 計算並安排下一個本機 03:00，回呼完成後再安排隔日。

**Tech Stack:** Python 3、Tkinter／CustomTkinter、`pathlib`、`unittest`

## Global Constraints

- 只修改既有 `duty_gui.py` 與 `tests/test_smoke.py`，不新增或搬移 Python 檔案。
- 「每日勤務表」與「夜間勤務」第一層 `.png` 保留 30 天。
- JSON 既有 7／14／45 天規則不變。
- 車輛作業截圖、表單測試 PNG、其他副檔名、子資料夾與 NAS 資料不處理。
- 每個檔案的讀取或刪除錯誤須略過，不能中斷 GUI。
- 保留工作樹內與本需求無關的變更，不納入 commit 或 release。

---

### Task 1: 通用期限清理與 30 天 PNG 規則

**Files:**
- Modify: `tests/test_smoke.py:2114`
- Modify: `WinPython_公務電腦使用包/duty_gui.py:41-63`
- Modify: `WinPython_公務電腦使用包/duty_gui.py:809-820`

**Interfaces:**
- Consumes: `(folder: Path, pattern: str, keep_days: int)` 規則集合與可選的 `datetime` 基準時間。
- Produces: `cleanup_old_files(rules, now=None)`, `cleanup_old_json_files()`, `cleanup_old_screenshot_files()`。

- [ ] **Step 1: 寫入失敗測試**

在 `PackageSmokeTests` 加入暫存資料夾測試，建立 31 天舊 PNG、29 天新 PNG、31 天舊 TXT，呼叫：

```python
module.cleanup_old_files(((root, "*.png", 30),), now)
```

斷言只有舊 PNG 被刪除。

- [ ] **Step 2: 驗證測試因功能不存在而失敗**

Run:

```powershell
py -3 -m unittest tests.test_smoke.PackageSmokeTests.test_cleanup_old_files_removes_only_expired_matching_files -v
```

Expected: `AttributeError: module 'duty_gui' has no attribute 'cleanup_old_files'`

- [ ] **Step 3: 實作最小清理函式**

在常數區加入：

```python
SCREENSHOT_CLEAN_RULES = (
    (Path(__file__).resolve().parent / DAILY_SCREENSHOT_DIR, "*.png", 30),
    (Path(__file__).resolve().parent / NIGHT_SCREENSHOT_DIR, "*.png", 30),
)
```

以現有錯誤略過策略實作：

```python
def cleanup_old_files(rules, now: datetime | None = None) -> None:
    now = now or datetime.now()
    for folder, pattern, keep_days in rules:
        if not folder.exists():
            continue
        for old_path in folder.glob(pattern):
            try:
                age = now - datetime.fromtimestamp(old_path.stat().st_mtime)
                if age > timedelta(days=keep_days):
                    old_path.unlink()
            except Exception:
                continue


def cleanup_old_json_files() -> None:
    cleanup_old_files(AUTO_CLEAN_RULES)


def cleanup_old_screenshot_files() -> None:
    cleanup_old_files(SCREENSHOT_CLEAN_RULES)
```

- [ ] **Step 4: 驗證聚焦測試通過**

Run:

```powershell
py -3 -m unittest tests.test_smoke.PackageSmokeTests.test_cleanup_old_files_removes_only_expired_matching_files -v
```

Expected: `Ran 1 test` and `OK`

### Task 2: 每天 03:00 的 GUI 排程

**Files:**
- Modify: `tests/test_smoke.py:2114`
- Modify: `WinPython_公務電腦使用包/duty_gui.py:988-997`
- Modify: `WinPython_公務電腦使用包/duty_gui.py:4277-4290`

**Interfaces:**
- Consumes: `cleanup_old_json_files()`, `cleanup_old_screenshot_files()`。
- Produces: `milliseconds_until_next_cleanup(now=None) -> int`, `DutyGui.schedule_daily_cleanup()`, `DutyGui.run_daily_cleanup()`。

- [ ] **Step 1: 寫入排程失敗測試**

測試 02:30 到當日 03:00 為 1,800,000 毫秒、03:30 到隔日 03:00 為 84,600,000 毫秒；另以假的 `DutyGui.after` 驗證回呼會重新排程。

- [ ] **Step 2: 驗證測試因功能不存在而失敗**

Run:

```powershell
py -3 -m unittest tests.test_smoke.PackageSmokeTests.test_daily_cleanup_delay_targets_next_0300 tests.test_smoke.PackageSmokeTests.test_daily_cleanup_runs_both_rules_and_reschedules -v
```

Expected: missing helper or method failure.

- [ ] **Step 3: 實作下一個 03:00 計算與回呼**

加入：

```python
def milliseconds_until_next_cleanup(now: datetime | None = None) -> int:
    now = now or datetime.now()
    next_cleanup = now.replace(hour=3, minute=0, second=0, microsecond=0)
    if next_cleanup <= now:
        next_cleanup += timedelta(days=1)
    return max(1, int((next_cleanup - now).total_seconds() * 1000))
```

在 `DutyGui` 加入：

```python
def schedule_daily_cleanup(self) -> None:
    self.after(milliseconds_until_next_cleanup(), self.run_daily_cleanup)

def run_daily_cleanup(self) -> None:
    try:
        cleanup_old_json_files()
        cleanup_old_screenshot_files()
    finally:
        self.schedule_daily_cleanup()
```

啟動流程呼叫 `cleanup_old_screenshot_files()`，完成版面建立後呼叫 `self.schedule_daily_cleanup()`。

- [ ] **Step 4: 驗證排程測試通過**

Run:

```powershell
py -3 -m unittest tests.test_smoke.PackageSmokeTests.test_daily_cleanup_delay_targets_next_0300 tests.test_smoke.PackageSmokeTests.test_daily_cleanup_runs_both_rules_and_reschedules -v
```

Expected: `Ran 2 tests` and `OK`

### Task 3: 完整驗證、打包與發布

**Files:**
- Modify: `WinPython_公務電腦使用包/VERSION.txt`
- Modify: `UPDATE/VERSION.txt`
- Modify: `UPDATE/WinPython_公務電腦使用包.zip`
- Modify: `UPDATE/WinPython_公務電腦使用包.zip.sha256.txt`
- Create under ignored temp: `tmp/release_assets/<version>/sinposmart-*`

**Interfaces:**
- Consumes: 已通過測試的 GUI 與現有 package builder。
- Produces: commit、push、`public-package-<version>` GitHub Release、latest/direct-tag 下載驗證。

- [ ] **Step 1: 執行完整驗證**

Run:

```powershell
py -3 -m unittest tests.test_smoke -v
py -3 -m py_compile "WinPython_公務電腦使用包\duty_gui.pyw" "WinPython_公務電腦使用包\duty_gui.py" "WinPython_公務電腦使用包\duty_rehearsal.py" "WinPython_公務電腦使用包\compare_rehearsal_records.py" "WinPython_公務電腦使用包\duty_sheet_automation.py" "WinPython_公務電腦使用包\daily_vehicle_automation.py" "WinPython_公務電腦使用包\rest_time_automation.py" "WinPython_公務電腦使用包\check_environment.py"
git diff --check
```

Expected: all tests pass, compilation exits 0, diff check exits 0.

- [ ] **Step 2: 建立版本與 canonical package**

以 `Get-Date -Format "yyyy.MM.dd.HHmm"` 產生版本，執行 `sinposmart-update-package` 內建 builder，確認 ZIP 內有 `duty_gui.py` 與 `VERSION.txt`，且不含 config、secret、runtime output 或 Excel。

- [ ] **Step 3: 選擇性提交並推送**

先執行 `git status --short`，只 stage 本計畫列出的程式、測試、文件、版本與 canonical package，使用具體繁體中文 commit message，推送 `codex/duty-gui-daily-cleanup`。

- [ ] **Step 4: 建立並驗證 GitHub Release**

建立 tag `public-package-<version>`，上傳三個 `sinposmart-*` aliases。重新下載 GitHub Release 與 `releases/latest/download` 資產，驗證版本檔、ZIP 內部版本與 SHA-256 完全一致。
