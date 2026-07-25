# SinpoSmart Google Site 值班看板 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 WinPython 值班 GUI 每小時讀取完整勤務日資料並以 HTTPS 同步至 Google Drive JSON，供僅限 `sinpo666@gmail.com` 的既有 Google Site 看板顯示目前與下一時段人員。

**Architecture:** 保留一個既有 GUI 寫入端與兩個獨立 Apps Script Web App。GUI 將完整當日及下一勤務日的時段、番號、姓名正規化並以標準函式庫 `urllib` POST 至同步端；同步端比對內容雜湊後更新單一 Drive JSON，顯示端以台北時間從完整時段資料選出目前與下一時段，再供既有 Google Site iframe 使用。

**Tech Stack:** Python 3.11、Tkinter/CustomTkinter、Selenium、`urllib.request`、`unittest`、Google Apps Script V8、DriveApp、HtmlService、clasp、Google Sites。

## Global Constraints

- 只修改 `WinPython_公務電腦使用包/` 內的 GUI 發送端；不修改 NAS runtime、`ambulance_return_bot` 或任何 NAS 部署檔。
- SinpoSmart 勤務表是唯一資料來源；同步操作只能讀取勤務資料，不得送出或改寫勤務網站正式資料。
- 不新增 Python 檔、不新增第三方 dependency；看板邏輯放入既有 `duty_gui.py`，測試放入既有 `tests/test_smoke.py`。
- 同步端 URL 與同步密鑰只存公務電腦的使用者環境變數及 Apps Script Script Properties；不得寫入 `.env`、Git、JSON、log、Google Site 或截圖。
- JSON 與兩個 Apps Script 專案必須由 `sinpo666@gmail.com` 建立／持有並置於指定 Google Drive 資料夾；不建立新的 Google Site 頁面。
- 平板只以 `sinpo666@gmail.com` 開啟既有 Google Site，不安裝程式、不寫入資料、也不登入勤務系統。
- `UPDATE/`、版本檔、Git commit、GitHub release 只在使用者明確要求發布時處理；commit 前僅 stage 本次功能檔，且不得 stage 使用者既有的 `AGENTS.md` 變更或 runtime config。

---

## File Structure

- Modify: `WinPython_公務電腦使用包/duty_gui.py` — 完整勤務日 JSON 正規化、HTTPS 發送、值班模式每小時重新查詢與發送。
- Modify: `tests/test_smoke.py` — 正規化、雜湊、HTTP 發送與每小時觸發的單元測試。
- Modify: `.gitignore` — 忽略 clasp 所建立的 project ID 檔。
- Create: `google_site_duty_board/sync/Code.gs` — 公務電腦使用的只寫入同步 Web App。
- Create: `google_site_duty_board/sync/appsscript.json` — 同步 Web App 的 V8、台北時區與 Drive scope。
- Create: `google_site_duty_board/view/Code.gs` — 僅供平板 iframe 使用的私有顯示 Web App。
- Create: `google_site_duty_board/view/appsscript.json` — 顯示 Web App 的 V8、台北時區與 Drive read scope。
- Create: `WinPython_公務電腦使用包/docs/GOOGLE_SITE_DUTY_BOARD_SETUP.md` — 受控設定、clasp 部署、Google Site 嵌入與操作驗收說明。

## Interfaces

### GUI 至同步端的 POST 本文

```json
{
  "sync_key": "local-secret-not-logged",
  "payload": {
    "schema_version": 1,
    "days": [
      {
        "roc_date": "1150716",
        "slots": [
          {
            "slot": "8-9",
            "start_hour": 8,
            "end_hour": 9,
            "duty_nos": ["1", "2"],
            "names": ["王小明", "李小華"]
          }
        ]
      }
    ],
    "content_hash": "sha256-of-schema-version-and-days"
  }
}
```

`days[0]` 是 `duty_business_roc_date()` 對應的完整勤務日；`days[1]` 是下一勤務日完整資料（勤務網站尚未提供時可省略）。所有時段都保留，不只保留當下人員。

### 同步端回覆

```json
{"ok": true, "changed": true}
```

`changed` 為 `false` 代表 Drive 既有 JSON 的內容雜湊相同，未改寫遠端檔案。

---

### Task 1: 先為完整勤務日 payload 與 HTTP 發送建立失敗測試

**Files:**
- Modify: `tests/test_smoke.py:3-12`
- Modify: `tests/test_smoke.py:2010-2014`

**Interfaces:**
- Consumes: `duty_gui.build_duty_board_payload(schedule_data)` 與 `duty_gui.post_duty_board_payload(payload)`。
- Produces: 對完整時段、跨日資料、穩定雜湊、未設定同步、成功回覆與錯誤回覆的行為保護。

- [ ] **Step 1: 加入 mock 所需 import 與固定排程資料 helper**

在 `tests/test_smoke.py` 的 import 區加入：

```python
from unittest import mock
```

在 `PackageSmokeTests` 內加入下列 helper，讓各測試使用同一份完整兩日資料：

```python
def duty_board_schedule_payload(self) -> dict[str, object]:
    return {
        "target_date": "1150716",
        "today": {
            "roc_date": "1150716",
            "rows": [
                {"slot": "8-9", "columns": {"值班": ["1", "2"]}},
                {"slot": "9-10", "columns": {"值班": ["3"]}},
                {"slot": "23-0", "columns": {"值班": ["4"]}},
                {"slot": "0-1", "columns": {"值班": ["5"]}},
            ],
            "staff": {
                "1": {"name": "王小明", "role": "隊員"},
                "2": {"name": "李小華", "role": "隊員"},
                "3": {"name": "陳小美", "role": "隊員"},
                "4": {"name": "林小強", "role": "隊員"},
                "5": {"name": "周小安", "role": "隊員"},
            },
        },
        "tomorrow": {
            "roc_date": "1150717",
            "rows": [{"slot": "8-9", "columns": {"值班": ["6"]}}],
            "staff": {"6": {"name": "張小雲", "role": "隊員"}},
        },
    }
```

- [ ] **Step 2: 新增完整時段與穩定雜湊的失敗測試**

加入以下測試；在實作前會因函式尚不存在而失敗：

```python
def test_duty_board_payload_keeps_full_days_and_stable_hash(self) -> None:
    module = duty_gui_module()
    schedule = self.duty_board_schedule_payload()

    first = module.build_duty_board_payload(schedule)
    second = module.build_duty_board_payload(schedule)

    self.assertEqual(first["schema_version"], 1)
    self.assertEqual([day["roc_date"] for day in first["days"]], ["1150716", "1150717"])
    self.assertEqual(len(first["days"][0]["slots"]), 4)
    self.assertEqual(first["days"][0]["slots"][0]["duty_nos"], ["1", "2"])
    self.assertEqual(first["days"][0]["slots"][0]["names"], ["王小明", "李小華"])
    self.assertEqual(first["days"][0]["slots"][3]["start_hour"], 0)
    self.assertEqual(first["days"][0]["slots"][3]["end_hour"], 1)
    self.assertEqual(first["content_hash"], second["content_hash"])


def test_post_duty_board_payload_requires_configuration_and_ok_response(self) -> None:
    module = duty_gui_module()
    payload = module.build_duty_board_payload(self.duty_board_schedule_payload())
    previous_url = module.DUTY_BOARD_SYNC_URL
    previous_key = module.DUTY_BOARD_SYNC_KEY
    module.DUTY_BOARD_SYNC_URL = ""
    module.DUTY_BOARD_SYNC_KEY = ""
    try:
        with self.assertRaisesRegex(RuntimeError, "看板同步"):
            module.post_duty_board_payload(payload)
    finally:
        module.DUTY_BOARD_SYNC_URL = previous_url
        module.DUTY_BOARD_SYNC_KEY = previous_key

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"ok": true, "changed": false}'

    module.DUTY_BOARD_SYNC_URL = "https://example.invalid/exec"
    module.DUTY_BOARD_SYNC_KEY = "test-key"
    try:
        with mock.patch.object(module.urllib.request, "urlopen", return_value=Response()) as urlopen:
            result = module.post_duty_board_payload(payload)
        request = urlopen.call_args.args[0]
        sent = json.loads(request.data.decode("utf-8"))
        self.assertEqual(result, {"ok": True, "changed": False})
        self.assertEqual(sent["payload"]["content_hash"], payload["content_hash"])
        self.assertNotIn("test-key", request.full_url)
    finally:
        module.DUTY_BOARD_SYNC_URL = previous_url
        module.DUTY_BOARD_SYNC_KEY = previous_key
```

- [ ] **Step 3: 執行測試確認 RED**

Run:

```powershell
py -m unittest `
  tests.test_smoke.PackageSmokeTests.test_duty_board_payload_keeps_full_days_and_stable_hash `
  tests.test_smoke.PackageSmokeTests.test_post_duty_board_payload_requires_configuration_and_ok_response -v
```

Expected: FAIL，訊息指出 `build_duty_board_payload` 或 `post_duty_board_payload` 尚不存在。

---

### Task 2: 在既有 GUI 實作正規化、HTTPS 發送與每小時來源重新查詢

**Files:**
- Modify: `WinPython_公務電腦使用包/duty_gui.py:15-38`
- Modify: `WinPython_公務電腦使用包/duty_gui.py:177-183`
- Modify: `WinPython_公務電腦使用包/duty_gui.py:349-399`
- Modify: `WinPython_公務電腦使用包/duty_gui.py:830-906`
- Modify: `WinPython_公務電腦使用包/duty_gui.py:3123-3150`
- Modify: `WinPython_公務電腦使用包/duty_gui.py:3151-3198`
- Modify: `WinPython_公務電腦使用包/duty_gui.py:3216-3229`

**Interfaces:**
- Consumes: 既有 `write_schedule_snapshot()` 產出的 `today`／`tomorrow`／`rows`／`staff` 結構。
- Produces: `build_duty_board_payload() -> dict[str, Any]`、`post_duty_board_payload() -> dict[str, Any]`、`DutyGui.check_hourly_duty_board_sync()` 與不阻塞 GUI 的同步 worker。

- [ ] **Step 1: 加入標準函式庫、受控設定與正規化函式**

在 import 區加入 `import hashlib`；在既有 NAS 設定常數之後加入：

```python
DUTY_BOARD_SYNC_URL = os.environ.get("SINPOSMART_DUTY_BOARD_SYNC_URL", "").strip()
DUTY_BOARD_SYNC_KEY = os.environ.get("SINPOSMART_DUTY_BOARD_SYNC_KEY", "").strip()


def duty_board_sync_timeout_seconds() -> int:
    try:
        return max(1, int(os.environ.get("SINPOSMART_DUTY_BOARD_SYNC_TIMEOUT_SECONDS", "8")))
    except ValueError:
        return 8


def duty_board_sync_enabled() -> bool:
    return bool(DUTY_BOARD_SYNC_URL and DUTY_BOARD_SYNC_KEY)


def normalize_duty_board_day(raw_day: dict[str, Any]) -> dict[str, Any] | None:
    roc_day = str(raw_day.get("roc_date", "")).strip()
    rows = raw_day.get("rows")
    staff = raw_day.get("staff")
    if len(roc_day) != 7 or not isinstance(rows, list) or not isinstance(staff, dict):
        return None
    slots: list[dict[str, Any]] = []
    for raw_row in rows:
        if not isinstance(raw_row, dict):
            continue
        slot = str(raw_row.get("slot", "")).strip()
        start = slot_start(slot)
        end = slot_end(slot)
        columns = raw_row.get("columns")
        duty_nos = columns.get("值班", []) if isinstance(columns, dict) else []
        if start is None or end is None or not isinstance(duty_nos, list):
            continue
        numbers = [str(no).strip() for no in duty_nos if str(no).strip()]
        names = [str(staff.get(no, {}).get("name", "")).strip() for no in numbers]
        slots.append({
            "slot": slot,
            "start_hour": start,
            "end_hour": end,
            "duty_nos": numbers,
            "names": [name for name in names if name],
        })
    return {"roc_date": roc_day, "slots": slots}


def build_duty_board_payload(schedule_data: dict[str, Any]) -> dict[str, Any]:
    days = [
        normalized
        for raw_day in (schedule_data.get("today"), schedule_data.get("tomorrow"))
        if isinstance(raw_day, dict)
        for normalized in [normalize_duty_board_day(raw_day)]
        if normalized is not None
    ]
    if not days:
        raise RuntimeError("勤務表沒有可同步的完整時段資料。")
    canonical = json.dumps({"schema_version": 1, "days": days}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "schema_version": 1,
        "days": days,
        "content_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }
```

- [ ] **Step 2: 加入 POST helper，禁止將密鑰帶入 URL 或例外訊息**

在既有 `post_credential_sync_payload()` 附近加入：

```python
def post_duty_board_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not duty_board_sync_enabled():
        raise RuntimeError("尚未設定 Google Site 看板同步網址或同步密鑰。")
    body = json.dumps({"sync_key": DUTY_BOARD_SYNC_KEY, "payload": payload}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        DUTY_BOARD_SYNC_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=duty_board_sync_timeout_seconds()) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Google Site 看板同步失敗：HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Google Site 看板同步連線失敗。") from exc
    try:
        result = json.loads(response_body) if response_body else {}
    except json.JSONDecodeError:
        result = {}
    if not isinstance(result, dict) or not result.get("ok"):
        raise RuntimeError("Google Site 看板同步未回報成功。")
    return result
```

- [ ] **Step 3: 在 DutyGui 初始化、排程成功回呼與整點檢查接上 worker**

在 `DutyGui.__init__` 的既有 snapshot state 後加入：

```python
self.duty_board_completed_hours: set[str] = set()
self.duty_board_sync_running = False
self.duty_board_last_hash = ""
self.after(65000, self.check_hourly_duty_board_sync)
```

新增下列方法。`queue_duty_board_sync()` 僅在設定齊全、沒有相同雜湊且沒有進行中 worker 時傳送；成功後才記住雜湊，失敗只寫入既有安全錯誤 log，不清空看板資料：

```python
def queue_duty_board_sync(self, schedule_data: dict[str, Any]) -> None:
    if self.duty_board_sync_running or not duty_board_sync_enabled():
        return
    try:
        payload = build_duty_board_payload(schedule_data)
    except Exception as exc:
        log_automation_exception("duty_board_payload", exc)
        return
    if payload["content_hash"] == self.duty_board_last_hash:
        return
    self.duty_board_sync_running = True

    def worker() -> None:
        try:
            post_duty_board_payload(payload)
        except Exception as exc:
            log_automation_exception("duty_board_sync", exc)
            self.after(0, self._duty_board_sync_finished)
            return
        self.after(0, lambda: self._duty_board_sync_finished(payload["content_hash"]))

    threading.Thread(target=worker, daemon=True).start()


def _duty_board_sync_finished(self, content_hash: str = "") -> None:
    self.duty_board_sync_running = False
    if content_hash:
        self.duty_board_last_hash = content_hash


def check_hourly_duty_board_sync(self) -> None:
    try:
        now = datetime.now()
        if not (self.simple_mode.get() and self.session and self.session.verified) or now.minute >= 5:
            return
        hour_key = f"duty-board-{duty_business_roc_date(now)}-{now:%Y%m%d%H}"
        if hour_key in self.duty_board_completed_hours or self.snapshot_running:
            return
        if self.refresh_schedule_background(duty_business_roc_date(now), hour_key, target_dates=[duty_business_roc_date(now)]):
            self.duty_board_completed_hours.add(hour_key)
    finally:
        self.after(60000, self.check_hourly_duty_board_sync)
```

Change `refresh_schedule_background()` to return `False` for its existing early-return guard and `True` immediately after starting its worker thread. Existing call sites continue to ignore its return value.

In `_schedule_succeeded()`, read the selected active schedule JSON once after `today_path` is found. If the login session still matches, pass that schedule dictionary to `queue_duty_board_sync()` before returning; do not include session credentials in the payload.

- [ ] **Step 4: 執行 Task 1 測試確認 GREEN，再加入整點觸發測試**

新增下列測試，確認值班模式會在整點前五分鐘內只啟動一次既有背景勤務表重新查詢：

```python
def test_hourly_duty_board_sync_reuses_schedule_refresh_once(self) -> None:
    module = duty_gui_module()
    gui = object.__new__(module.DutyGui)
    gui.simple_mode = type("Mode", (), {"get": lambda self: True})()
    gui.session = module.LoginSession(actor_no="1", user_id="user", password="secret", verified=True)
    gui.duty_board_completed_hours = set()
    gui.snapshot_running = False
    scheduled = []
    refreshes = []
    gui.after = lambda delay, callback: scheduled.append((delay, callback)) or "after-id"
    gui.refresh_schedule_background = lambda target, label, target_dates=None: refreshes.append((target, label, target_dates)) or True
    with mock.patch.object(module, "datetime") as mocked_datetime:
        mocked_datetime.now.return_value = datetime(2026, 7, 16, 9, 2)
        mocked_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        gui.check_hourly_duty_board_sync()
        gui.check_hourly_duty_board_sync()
    self.assertEqual(len(refreshes), 1)
    self.assertEqual(refreshes[0][0], "1150716")
    self.assertEqual(len(scheduled), 2)
```

Run:

```powershell
py -m unittest `
  tests.test_smoke.PackageSmokeTests.test_duty_board_payload_keeps_full_days_and_stable_hash `
  tests.test_smoke.PackageSmokeTests.test_post_duty_board_payload_requires_configuration_and_ok_response `
  tests.test_smoke.PackageSmokeTests.test_hourly_duty_board_sync_reuses_schedule_refresh_once -v
```

Expected: PASS。

---

### Task 3: 建立可版控的同步與顯示 Apps Script 原始碼

**Files:**
- Modify: `.gitignore:1-65`
- Create: `google_site_duty_board/sync/Code.gs`
- Create: `google_site_duty_board/sync/appsscript.json`
- Create: `google_site_duty_board/view/Code.gs`
- Create: `google_site_duty_board/view/appsscript.json`

**Interfaces:**
- Consumes: Task 2 的 POST 本文與 Script Properties `DUTY_BOARD_FOLDER_ID`、`DUTY_BOARD_SYNC_KEY`。
- Produces: 單一 `sinposmart-duty-board.json` 與不洩漏 JSON 的同步回覆；僅限 `sinpo666@gmail.com` 的 HTML 看板。

- [ ] **Step 1: 忽略 clasp project ID 檔**

在 `.gitignore` 的 secrets 區加入：

```gitignore
google_site_duty_board/**/.clasp.json
```

- [ ] **Step 2: 建立同步端 Apps Script**

建立 `google_site_duty_board/sync/appsscript.json`：

```json
{
  "timeZone": "Asia/Taipei",
  "exceptionLogging": "STACKDRIVER",
  "runtimeVersion": "V8",
  "oauthScopes": ["https://www.googleapis.com/auth/drive"]
}
```

建立 `google_site_duty_board/sync/Code.gs`：

```javascript
const BOARD_FILE_NAME = 'sinposmart-duty-board.json';

function doGet() {
  return json_({ok: false, error: 'write_only'});
}

function doPost(e) {
  try {
    const request = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    const properties = PropertiesService.getScriptProperties();
    if (String(request.sync_key || '') !== String(properties.getProperty('DUTY_BOARD_SYNC_KEY') || '')) {
      return json_({ok: false, error: 'unauthorized'});
    }
    const payload = validatePayload_(request.payload);
    const canonical = stableJson_({schema_version: payload.schema_version, days: payload.days});
    const expectedHash = sha256_(canonical);
    if (payload.content_hash !== expectedHash) {
      return json_({ok: false, error: 'invalid_hash'});
    }
    const file = getBoardFile_(properties);
    let previous = {};
    try {
      previous = JSON.parse(file.getBlob().getDataAsString() || '{}');
    } catch (_error) {
      previous = {};
    }
    const changed = previous.content_hash !== payload.content_hash;
    if (changed) {
      file.setContent(JSON.stringify({
        schema_version: payload.schema_version,
        days: payload.days,
        content_hash: payload.content_hash,
        updated_at: Utilities.formatDate(new Date(), 'Asia/Taipei', "yyyy-MM-dd'T'HH:mm:ssXXX"),
      }, null, 2));
    }
    return json_({ok: true, changed: changed});
  } catch (_error) {
    return json_({ok: false, error: 'invalid_payload'});
  }
}

function validatePayload_(payload) {
  if (!payload || payload.schema_version !== 1 || !Array.isArray(payload.days) || !payload.days.length || typeof payload.content_hash !== 'string') {
    throw new Error('invalid payload');
  }
  payload.days.forEach(day => {
    if (!day || !/^\d{7}$/.test(String(day.roc_date || '')) || !Array.isArray(day.slots)) throw new Error('invalid day');
    day.slots.forEach(slot => {
      if (!slot || typeof slot.slot !== 'string' || !Number.isInteger(slot.start_hour) || !Number.isInteger(slot.end_hour) || !Array.isArray(slot.duty_nos) || !Array.isArray(slot.names)) {
        throw new Error('invalid slot');
      }
    });
  });
  return payload;
}

function getBoardFile_(properties) {
  const folderId = String(properties.getProperty('DUTY_BOARD_FOLDER_ID') || '');
  if (!folderId) throw new Error('missing folder');
  const folder = DriveApp.getFolderById(folderId);
  const files = folder.getFilesByName(BOARD_FILE_NAME);
  return files.hasNext() ? files.next() : folder.createFile(BOARD_FILE_NAME, '{}', MimeType.PLAIN_TEXT);
}

function stableJson_(value) {
  if (Array.isArray(value)) return '[' + value.map(stableJson_).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + stableJson_(value[key])).join(',') + '}';
  return JSON.stringify(value);
}

function sha256_(value) {
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, value, Utilities.Charset.UTF_8)
    .map(byte => ('0' + ((byte + 256) % 256).toString(16)).slice(-2))
    .join('');
}

function json_(value) {
  return ContentService.createTextOutput(JSON.stringify(value)).setMimeType(ContentService.MimeType.JSON);
}
```

- [ ] **Step 3: 建立只顯示的 Apps Script**

建立 `google_site_duty_board/view/appsscript.json`：

```json
{
  "timeZone": "Asia/Taipei",
  "exceptionLogging": "STACKDRIVER",
  "runtimeVersion": "V8",
  "oauthScopes": ["https://www.googleapis.com/auth/drive.readonly"]
}
```

建立 `google_site_duty_board/view/Code.gs`：

```javascript
const BOARD_FILE_NAME = 'sinposmart-duty-board.json';

function doGet() {
  const board = loadBoard_();
  const model = selectDutySlots_(board);
  const current = model.current ? displaySlot_(model.current) : '尚無值班資料';
  const next = model.next ? displaySlot_(model.next) : '下一時段資料尚未同步';
  const updatedAt = board.updated_at || '尚無資料';
  const html = '<!doctype html><html><head><base target="_top">' +
    '<meta name="viewport" content="width=device-width, initial-scale=1">' +
    '<style>body{margin:0;font-family:"Microsoft JhengHei",sans-serif;color:#172033;background:#f5f7fb}.board{padding:16px}.title{font-size:18px;font-weight:700;margin-bottom:10px}.card{background:#fff;border:1px solid #d7e2f0;border-radius:12px;padding:12px;margin-top:8px}.label{font-size:12px;color:#64748b}.people{font-size:20px;font-weight:700;margin-top:4px}.updated{font-size:12px;color:#64748b;margin-top:12px}</style>' +
    '</head><body><main class="board"><div class="title">目前值班人員</div>' +
    '<section class="card"><div class="label">目前時段</div><div class="people">' + escapeHtml_(current) + '</div></section>' +
    '<section class="card"><div class="label">下一時段</div><div class="people">' + escapeHtml_(next) + '</div></section>' +
    '<div class="updated">資料更新：' + escapeHtml_(updatedAt) + '</div></main>' +
    '<script>setTimeout(function(){location.reload();},60000);</script></body></html>';
  return HtmlService.createHtmlOutput(html).setTitle('SinpoSmart 目前值班人員');
}

function loadBoard_() {
  const folderId = String(PropertiesService.getScriptProperties().getProperty('DUTY_BOARD_FOLDER_ID') || '');
  if (!folderId) return {};
  const files = DriveApp.getFolderById(folderId).getFilesByName(BOARD_FILE_NAME);
  if (!files.hasNext()) return {};
  try {
    return JSON.parse(files.next().getBlob().getDataAsString() || '{}');
  } catch (_error) {
    return {};
  }
}

function selectDutySlots_(board) {
  const days = Array.isArray(board.days) ? board.days : [];
  const nowHour = Number(Utilities.formatDate(new Date(), 'Asia/Taipei', 'H'));
  const fireHour = nowHour < 8 ? nowHour + 24 : nowHour;
  const timeline = [];
  days.forEach((day, dayIndex) => (day.slots || []).forEach(slot => {
    let start = Number(slot.start_hour);
    let end = Number(slot.end_hour);
    if (start < 8) start += 24;
    if (end <= 8) end += 24;
    if (end <= start) end += 24;
    timeline.push({slot: slot, start: start + dayIndex * 24, end: end + dayIndex * 24});
  }));
  timeline.sort((left, right) => left.start - right.start);
  const currentIndex = timeline.findIndex(item => item.start <= fireHour && fireHour < item.end);
  if (currentIndex < 0) return {current: null, next: timeline.find(item => item.start > fireHour) || null};
  return {current: timeline[currentIndex].slot, next: timeline[currentIndex + 1] ? timeline[currentIndex + 1].slot : null};
}

function displaySlot_(slot) {
  const names = (slot.names || []).filter(Boolean);
  const people = names.length ? names.join('、') : (slot.duty_nos || []).map(no => '第' + no + '番').join('、');
  return slot.slot + '　' + (people || '無值班人員');
}

function escapeHtml_(value) {
  return String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
}
```

- [ ] **Step 4: 靜態檢查 Apps Script 原始碼與 Git ignore**

Run:

```powershell
rg -n -i 'DUTY_BOARD_SYNC_KEY\s*=|SINPOSMART_DUTY_BOARD_SYNC_KEY\s*=' google_site_duty_board
git check-ignore -v google_site_duty_board/sync/.clasp.json google_site_duty_board/view/.clasp.json
```

Expected: 第一個命令沒有輸出任何密鑰值或設定值；第二個命令顯示 `.gitignore` 的新規則。

---

### Task 4: 部署兩個 Apps Script、設定公務電腦與嵌入既有 Google Site

**Files:**
- Create: `WinPython_公務電腦使用包/docs/GOOGLE_SITE_DUTY_BOARD_SETUP.md`
- Generate locally and ignore: `google_site_duty_board/sync/.clasp.json`
- Generate locally and ignore: `google_site_duty_board/view/.clasp.json`

**Interfaces:**
- Consumes: Task 2 產生的 `SINPOSMART_DUTY_BOARD_SYNC_URL`／`SINPOSMART_DUTY_BOARD_SYNC_KEY` 與 Task 3 Apps Script 原始碼。
- Produces: 指定 Drive 資料夾中的 JSON、同步端 `/exec` URL、私有顯示端 `/exec` URL、既有 Google Site 的 iframe。

- [ ] **Step 1: 以 sinpo666 帳號登入 clasp 並建立兩個獨立專案**

Run:

```powershell
clasp login
Push-Location google_site_duty_board/sync
clasp create --type webapp --title "SinpoSmart 值班看板同步"
clasp push
Pop-Location
Push-Location google_site_duty_board/view
clasp create --type webapp --title "SinpoSmart 值班看板顯示"
clasp push
Pop-Location
```

Expected: 各資料夾產生 ignored `.clasp.json`，並顯示 `Pushed` 成功。使用 Google Drive 網頁將兩個 Apps Script 專案移入指定的 `sinpo666@gmail.com` Drive 資料夾；移動後不更換 script ID。

- [ ] **Step 2: 設定 Script Properties 與 Web App 發布權限**

在兩個 Apps Script 專案的 Project Settings > Script properties 都設定 `DUTY_BOARD_FOLDER_ID` 為指定 Drive 資料夾 ID。同步專案另設定 `DUTY_BOARD_SYNC_KEY`；顯示專案不保存同步密鑰。

在同步專案執行 New deployment > Web app，選擇「Execute as: Me」與「Who has access: Anyone」；此 URL 只接受帶正確本文密鑰的 POST，`GET` 不回傳勤務資料。

在顯示專案執行 New deployment > Web app，選擇「Execute as: Me」與「Who has access: Only myself」；此帳號即 `sinpo666@gmail.com`。

Run:

```powershell
Push-Location google_site_duty_board/sync
clasp deployments
Pop-Location
Push-Location google_site_duty_board/view
clasp deployments
Pop-Location
```

Expected: 各自有一個 Web App deployment；兩個 URL 不相同。

- [ ] **Step 3: 在公務電腦以使用者環境變數設定同步端，不改 `.env`**

在可安全貼入同步端 URL 的公務電腦使用者工作階段執行下列命令。`Set-Clipboard` 讓操作人員直接把密鑰貼入同步 Apps Script 的 Script property，不將密鑰顯示或寫入 Git：

```powershell
$syncUrl = Read-Host '貼上同步 Apps Script 的 /exec URL'
$syncKey = [Convert]::ToBase64String((1..32 | ForEach-Object { Get-Random -Maximum 256 }))
[Environment]::SetEnvironmentVariable('SINPOSMART_DUTY_BOARD_SYNC_URL', $syncUrl, 'User')
[Environment]::SetEnvironmentVariable('SINPOSMART_DUTY_BOARD_SYNC_KEY', $syncKey, 'User')
[Environment]::SetEnvironmentVariable('SINPOSMART_DUTY_BOARD_SYNC_TIMEOUT_SECONDS', '8', 'User')
Set-Clipboard -Value $syncKey
Remove-Variable syncKey
Remove-Variable syncUrl
```

Expected: 將剪貼簿中的密鑰貼入同步專案 `DUTY_BOARD_SYNC_KEY` 後關閉並重新以 `RUN_DUTY_GUI_WINPYTHON.bat` 或 `duty_gui.pyw` 啟動 GUI；不使用 console 方式常態啟動。

- [ ] **Step 4: 嵌入既有 Google Site 並執行端對端驗收**

在既有 `https://sites.google.com/view/sinpo666/%E5%80%BC%E7%8F%AD%E4%BA%BA%E5%93%A1` 頁面選擇 Embed URL，貼入顯示 Apps Script `/exec` URL，保留既有人員清單與介紹頁，不建立新頁面。

使用公務電腦登入值班模式，確認第一次只讀勤務表後 Drive 資料夾出現 `sinposmart-duty-board.json`。平板以 `sinpo666@gmail.com` 開啟既有頁面，驗證目前與下一時段人員及資料更新時間。以其他 Google 帳號開啟顯示 `/exec` URL，預期遭拒絕。讓 GUI 跨過下一個整點並確認完整勤務資料重新讀取；資料未變時 Drive JSON 的修改時間不變。

---

### Task 5: 補齊操作文件、完整回歸驗證與發布前停點

**Files:**
- Modify: `WinPython_公務電腦使用包/docs/README.md:41-55`
- Create: `WinPython_公務電腦使用包/docs/GOOGLE_SITE_DUTY_BOARD_SETUP.md`

**Interfaces:**
- Consumes: Task 4 的已部署 URL 與使用者環境變數名稱，不記錄 URL 值、folder ID 或密鑰值。
- Produces: 可由下一位維護者安全重設看板、重新部署與驗證的說明。

- [ ] **Step 1: 撰寫設定與故障排除文件**

`GOOGLE_SITE_DUTY_BOARD_SETUP.md` 必須列出：兩個 Apps Script 專案職責、三個公務電腦環境變數名稱、兩個 Script Properties 名稱、同步端與顯示端的不同存取權限、JSON 檔名、平板登入帳號、既有 Google Site URL、資料未更新時先確認 GUI 值班模式／網路／Apps Script deployment 的順序。文件只能寫設定鍵名稱，不得包含設定值。

在 `README.md` 的工具說明後新增連結：

```markdown
- Google Site 值班看板設定與驗收請見 `docs/GOOGLE_SITE_DUTY_BOARD_SETUP.md`；同步網址、資料夾 ID 與同步密鑰皆為公務電腦／Apps Script 的受控設定，不納入 Git。
```

- [ ] **Step 2: 執行完整本機驗證**

Run:

```powershell
py -m unittest tests.test_smoke -v
py -m py_compile `
  "WinPython_公務電腦使用包/duty_gui.py" `
  "WinPython_公務電腦使用包/duty_gui.pyw"
git diff --check
git status --short
```

Expected: unittest 全數通過、兩個 Python entry point 編譯成功、無 whitespace error；狀態只含本功能的 GUI、測試、Apps Script、文件與既有使用者 `AGENTS.md` 變更。

- [ ] **Step 3: 停在 commit／發布授權點**

先向使用者報告預計提交檔案清單、測試結果、Google Site 端對端驗證結果與未處理風險。只有使用者明確要求後，才更新 `WinPython_公務電腦使用包/VERSION.txt`、`UPDATE/VERSION.txt`、`UPDATE/sinposmart-version.txt`，建立更新包、commit、push 或發布 GitHub release；不得把 `.clasp.json`、`.env`、JSON、runtime outputs、log、密鑰或使用者既有 `AGENTS.md` 變更納入 commit。

## Plan Self-Review

- **Spec coverage:** Task 2 實作整日資料讀取與每小時同步；Task 3 將 JSON 安全寫入指定 Drive 並私有渲染；Task 4 將顯示嵌入既有 Site 並設定平板帳號；Task 5 覆蓋文件、完整驗證與發布界線。
- **No placeholders:** 所有檔案路徑、設定鍵、JSON contract、命令、測試名稱與部署權限均已明定；遠端 URL、folder ID 與密鑰刻意只由受控設定提供，沒有寫入程式碼或計畫內容。
- **Type consistency:** GUI 與 Apps Script 均使用 `schema_version`、`days`、`roc_date`、`slots`、`content_hash`、`sync_key`、`ok`、`changed`；Python 的 canonical JSON 與 Apps Script `stableJson_()` 均只對 `schema_version` 與 `days` 排序後計算 SHA-256。
