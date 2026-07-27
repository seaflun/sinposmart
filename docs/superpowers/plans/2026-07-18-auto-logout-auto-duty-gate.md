# 自動登出只等待到點自動勤務 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓自動登出只等待同一交接時間內實際會到點自動登打的勤務完成。

**Architecture:** 保留既有自動勤務分類 `DutyGui.is_auto_duty_action()` 作為唯一政策來源。`DutyGui.auto_logout_group_indices()` 在既有執行人、時間與種類條件上套用該分類，避免非自動勤務成為登出門檻。

**Tech Stack:** Python 3、Tkinter/CustomTkinter、unittest。

## Global Constraints

- 只修改既有 `WinPython_公務電腦使用包/duty_gui.py` 與 `tests/test_smoke.py`。
- 不新增 Python 檔、不搬移檔案、不新增 dependency。
- 不修改排程產生邏輯、登入憑證或正式網站資料。
- 保留現有格式與使用者尚未提交的其他變更。
- 未經使用者要求，不建立 commit。

---

### Task 1: 排除非自動勤務的登出阻擋

**Files:**
- Modify: `tests/test_smoke.py:584-661`
- Modify: `WinPython_公務電腦使用包/duty_gui.py:3563-3570`

**Interfaces:**
- Consumes: `DutyGui.is_auto_duty_action(action: dict[str, Any]) -> bool`
- Produces: `DutyGui.auto_logout_group_indices(actor_no: str, handoff_at: datetime) -> list[int]` 只回傳到點自動勤務索引。

- [ ] **Step 1: 擴充既有測試，加入同時段非自動休息返隊**

在 `test_auto_logout_rechecks_until_handoff_group_is_complete()` 的 `duty_actions` 加入：

```python
{"key": "rest-return", "at": handoff_at, "kind": "entry_log", "actor": "28", "source": "休息結束", "fields": {"出或入": "入", "領用事由及地點": "休息返隊"}},
```

並在 `duty_action_compare` 加入：

```python
3: {"group": "todo"},
4: {"group": "todo"},
```

同時把原本的 `next-shift` 索引由 `3` 順延為 `4`。既有斷言保留不變：第一次檢查只能計入未完成的自動工作一筆；工作完成後，即使休息返隊仍為 `todo`，也必須呼叫 `clear_login(trigger_type="system")`。

- [ ] **Step 2: 執行單一回歸測試並確認紅燈**

Run:

```powershell
py -3 -m unittest tests.test_smoke.PackageSmokeTests.test_auto_logout_rechecks_until_handoff_group_is_complete -v
```

Expected: FAIL；目前實作會把休息返隊納入群組，未完成數量不是一筆，或第二次檢查不會呼叫系統登出。

- [ ] **Step 3: 實作最小判斷修改**

將 `auto_logout_group_indices()` 改為：

```python
    def auto_logout_group_indices(self, actor_no: str, handoff_at: datetime) -> list[int]:
        return [
            index
            for index, action in enumerate(self.duty_actions)
            if action.get("kind") in ("entry_log", "work_log")
            and self.is_auto_duty_action(action)
            and str(action.get("actor", "")) == str(actor_no)
            and self.action_datetime(action) == handoff_at
        ]
```

- [ ] **Step 4: 執行單一回歸測試並確認綠燈**

Run:

```powershell
py -3 -m unittest tests.test_smoke.PackageSmokeTests.test_auto_logout_rechecks_until_handoff_group_is_complete -v
```

Expected: PASS。

- [ ] **Step 5: 執行相關自動登出測試與完整 smoke tests**

Run:

```powershell
py -3 -m unittest tests.test_smoke.PackageSmokeTests.test_auto_logout_waits_until_submit_queues_are_idle tests.test_smoke.PackageSmokeTests.test_auto_logout_waits_until_manual_pause_is_resumed tests.test_smoke.PackageSmokeTests.test_manual_handoff_checkout_schedules_auto_logout_from_planned_time tests.test_smoke.PackageSmokeTests.test_auto_logout_rechecks_until_handoff_group_is_complete tests.test_smoke.PackageSmokeTests.test_completed_handoff_checkout_restores_auto_logout_timer -v
py -3 -m unittest tests.test_smoke -v
```

Expected: 所有測試 PASS，零 failures、零 errors。

- [ ] **Step 6: 驗證真實 1150718 資料與差異範圍**

以唯讀腳本載入 `schedule_output_1150718.json` 與 `comparison_output_1150718.json`，確認 14:00、8 番的登出群組排除索引 30「9 番休息返隊」，且其餘到點自動勤務仍在群組中。

Run:

```powershell
git diff --check
git diff -- tests/test_smoke.py "WinPython_公務電腦使用包/duty_gui.py"
git status --short
```

Expected: `git diff --check` 無錯誤；程式差異只包含測試案例與一個自動勤務篩選條件。保留並不提交其他既有變更。
