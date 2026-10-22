'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const ROOT_ID = '1HDPbtqU_87StkzOcxLub2utVU_UGF8FJ';
const TEMPLATE_ID = '1AUj5M4wwYg29aTwa70EtAkDB8W37LuWsP8uqNXtbKJU';
const SHEETS_MIME = 'application/vnd.google-apps.spreadsheet';
const SOURCE_DIR = path.join(__dirname, '..', 'apps-script');

function iterator(items) {
  let index = 0;
  return { hasNext: () => index < items.length, next: () => items[index++] };
}

function fixture() {
  const files = new Map();
  const folders = new Map();
  const properties = new Map();
  const events = { copies: [], foldersCreated: [], opened: [], locked: false, lockCalls: 0 };
  let nextId = 1;
  let openFailures = 0;
  let lockFailure = false;
  const templateSheets = ['人員未完成', '重要交辦事項', ...Array.from({ length: 31 }, (_, i) => `${i + 1}號`)];
  const templateData = {
    sheets: templateSheets,
    formula: '=IF(D3<>"",ROW()-2,"")',
    validation: "='人員未完成'!$A$3:$A$29",
  };

  function folder(name, parent, id = `folder-${nextId++}`) {
    const result = {
      id, name, children: [], files: [],
      getId: () => id,
      getName: () => name,
      getFoldersByName: (wanted) => iterator(result.children.filter((item) => item.name === wanted)),
      getFilesByName: (wanted) => iterator(result.files.filter((item) => item.name === wanted)),
      createFolder(wanted) {
        const created = folder(wanted, result);
        events.foldersCreated.push({ parentId: id, name: wanted, id: created.id });
        return created;
      },
    };
    folders.set(id, result);
    if (parent) parent.children.push(result);
    return result;
  }

  function file(name, parent, options = {}) {
    const id = options.id || `file-${nextId++}`;
    const data = structuredClone(options.data || templateData);
    const result = {
      id, name, data, parent,
      getId: () => id,
      getName: () => name,
      getMimeType: () => options.mime || SHEETS_MIME,
      isTrashed: () => false,
      getParents: () => iterator(parent ? [parent] : []),
      makeCopy(wanted, destination) {
        assert.ok(destination, 'copy must name its destination folder');
        const copy = file(wanted, destination, { data });
        events.copies.push({ templateId: id, name: wanted, destinationId: destination.id, id: copy.id });
        return copy;
      },
    };
    result.spreadsheet = {
      getId: () => id,
      getName: () => name,
      getSheetByName: (wanted) => data.sheets.includes(wanted) ? { name: wanted, fileId: id } : null,
    };
    files.set(id, result);
    if (parent) parent.files.push(result);
    return result;
  }

  const root = folder('電子通報收文', null, ROOT_ID);
  const templateFolder = folder('母檔', root);
  const template = file('115年XX月電子通報(母檔)', templateFolder, { id: TEMPLATE_ID });
  const props = {
    getProperty: (key) => properties.get(key) || null,
    setProperty: (key, value) => { properties.set(key, value); return props; },
    deleteProperty: (key) => properties.delete(key),
  };
  const open = (target) => {
    events.opened.push(target.id);
    if (openFailures > 0) { openFailures--; throw new Error('temporary spreadsheet open failure'); }
    return target.spreadsheet;
  };
  const sandbox = {
    console,
    MimeType: { GOOGLE_SHEETS: SHEETS_MIME },
    DriveApp: {
      getFolderById(id) { assert.ok(folders.has(id), `unexpected folder ID ${id}`); return folders.get(id); },
      getFileById(id) { assert.ok(files.has(id), `unexpected file ID ${id}`); return files.get(id); },
      getFilesByName: (name) => iterator([...files.values()].filter((item) => item.name === name)),
    },
    SpreadsheetApp: {
      open,
      openById(id) { assert.ok(files.has(id), `unknown spreadsheet ${id}`); return open(files.get(id)); },
      create() { assert.fail('must copy the whole template, not create a blank workbook'); },
      flush() {},
    },
    PropertiesService: { getScriptProperties: () => props },
    LockService: { getScriptLock: () => ({
      waitLock() {
        events.lockCalls++;
        if (lockFailure) throw new Error('lock is busy');
        assert.equal(events.locked, false);
        events.locked = true;
      },
      releaseLock() { assert.equal(events.locked, true); events.locked = false; },
    }) },
  };
  vm.createContext(sandbox);
  for (const name of ['code.js', 'helper.js']) {
    vm.runInContext(fs.readFileSync(path.join(SOURCE_DIR, name), 'utf8'), sandbox, { filename: name });
  }
  return {
    sandbox, events, root, template, files, folders, properties, folder, file,
    context(allowCreate) {
      const ctx = sandbox.newContext();
      if (allowCreate !== undefined) ctx.allowCreate = allowCreate;
      return ctx;
    },
    failNextOpen() { openFailures++; },
    failLock() { lockFailure = true; },
  };
}

test('a missing month is not created by a plain lookup', () => {
  const f = fixture();
  f.folder('115年', f.root);
  assert.equal(f.sandbox.getSpreadsheet('115年11月電子通報', f.context()), null);
  assert.equal(f.events.copies.length, 0);
  assert.equal(f.events.foldersCreated.length, 0);
});

test('a lookup for an absent next year creates neither a year nor a workbook', () => {
  const f = fixture();
  assert.equal(f.sandbox.getSpreadsheet('116年1月電子通報', f.context(false)), null);
  assert.equal(f.root.children.some((item) => item.name === '116年'), false);
  assert.equal(f.events.copies.length, 0);
});

test('first November write copies the entire mother workbook into 115年', () => {
  const f = fixture();
  const year = f.folder('115年', f.root);
  const before = structuredClone(f.template.data);
  const result = f.sandbox.getSpreadsheet('115年11月電子通報', f.context(true));
  assert.ok(result);
  assert.equal(f.events.copies.length, 1);
  assert.deepEqual(f.events.copies[0], {
    templateId: TEMPLATE_ID, name: '115年11月電子通報', destinationId: year.id, id: result.getId(),
  });
  assert.deepEqual(f.files.get(result.getId()).data, before);
  assert.deepEqual(f.template.data, before);
  assert.equal(f.template.name, '115年XX月電子通報(母檔)');
});

test('first January write creates 116年 directly under the verified root', () => {
  const f = fixture();
  const result = f.sandbox.getSpreadsheet('116年1月電子通報', f.context(true));
  assert.ok(result);
  assert.equal(f.events.foldersCreated.length, 1);
  assert.equal(f.events.foldersCreated[0].parentId, ROOT_ID);
  assert.equal(f.events.foldersCreated[0].name, '116年');
  assert.equal(f.events.copies[0].destinationId, f.events.foldersCreated[0].id);
  assert.equal(f.events.copies[0].name, '116年1月電子通報');
});

test('an existing monthly workbook is reused without changing its contents', () => {
  const f = fixture();
  const year = f.folder('115年', f.root);
  const existing = f.file('115年11月電子通報', year);
  existing.data.savedNotice = 'existing formal record';
  const before = structuredClone(existing.data);
  assert.equal(f.sandbox.getSpreadsheet(existing.name, f.context(true)).getId(), existing.id);
  assert.deepEqual(existing.data, before);
  assert.equal(f.events.copies.length, 0);
  assert.equal(f.events.foldersCreated.length, 0);
});

test('a month with the same name in another folder cannot replace the annual destination', () => {
  const f = fixture();
  const elsewhere = f.folder('unrelated', null);
  const wrong = f.file('115年11月電子通報', elsewhere);
  const year = f.folder('115年', f.root);
  const result = f.sandbox.getSpreadsheet(wrong.name, f.context(true));
  assert.notEqual(result.getId(), wrong.id);
  assert.equal(f.events.copies[0].destinationId, year.id);
});

test('a cached spreadsheet ID from a different folder does not bypass annual lookup', () => {
  const f = fixture();
  const elsewhere = f.folder('other annual reports', null);
  const wrong = f.file('115年11月電子通報', elsewhere);
  const year = f.folder('115年', f.root);
  const correct = f.file(wrong.name, year);
  f.properties.set(`spreadsheetId:${wrong.name}`, wrong.id);
  assert.equal(f.sandbox.getSpreadsheet(wrong.name, f.context(true)).getId(), correct.id);
  assert.equal(f.events.copies.length, 0);
});

test('a stale cached ID does not prevent reuse of the correctly filed workbook', () => {
  const f = fixture();
  const year = f.folder('115年', f.root);
  const correct = f.file('115年11月電子通報', year);
  f.properties.set(`spreadsheetId:${correct.name}`, 'deleted-file-id');
  assert.equal(f.sandbox.getSpreadsheet(correct.name, f.context(true)).getId(), correct.id);
  assert.equal(f.events.copies.length, 0);
});

test('duplicate annual folders fail without selecting one or copying anything', () => {
  const f = fixture();
  f.folder('115年', f.root);
  f.folder('115年', f.root);
  assert.throws(() => f.sandbox.getSpreadsheet('115年11月電子通報', f.context(true)));
  assert.equal(f.events.copies.length, 0);
  assert.equal(f.events.foldersCreated.length, 0);
});

test('duplicate monthly files in the correct year fail without overwriting either', () => {
  const f = fixture();
  const year = f.folder('115年', f.root);
  f.file('115年11月電子通報', year);
  f.file('115年11月電子通報', year);
  assert.throws(() => f.sandbox.getSpreadsheet('115年11月電子通報', f.context(true)));
  assert.equal(f.events.copies.length, 0);
});

test('a non-Sheets file using the target month name is not opened or replaced', () => {
  const f = fixture();
  const year = f.folder('115年', f.root);
  f.file('115年11月電子通報', year, { mime: 'application/pdf' });
  assert.throws(() => f.sandbox.getSpreadsheet('115年11月電子通報', f.context(true)));
  assert.equal(f.events.opened.length, 0);
  assert.equal(f.events.copies.length, 0);
});

test('a non-Sheets mother file cannot create a monthly workbook', () => {
  const f = fixture();
  f.template.getMimeType = () => 'application/pdf';
  assert.throws(() => f.sandbox.getSpreadsheet('115年11月電子通報', f.context(true)));
  assert.equal(f.events.copies.length, 0);
  assert.equal(f.events.foldersCreated.length, 0);
});

test('invalid target names cannot create annual folders or copies', () => {
  for (const name of ['115年0月電子通報', '115年13月電子通報', '../115年11月電子通報']) {
    const f = fixture();
    assert.throws(() => f.sandbox.getSpreadsheet(name, f.context(true)));
    assert.equal(f.events.copies.length, 0);
    assert.equal(f.events.foldersCreated.length, 0);
  }
});

test('a template copy failure does not open a workbook or report a completed copy', () => {
  const f = fixture();
  f.folder('115年', f.root);
  f.template.makeCopy = () => { throw new Error('copy unavailable'); };
  assert.throws(() => f.sandbox.getSpreadsheet('115年11月電子通報', f.context(true)), /copy unavailable/);
  assert.equal(f.events.opened.length, 0);
  assert.equal(f.events.copies.length, 0);
});

test('retry after a successful copy but failed open reuses the already created file', () => {
  const f = fixture();
  f.folder('115年', f.root);
  f.failNextOpen();
  assert.throws(() => f.sandbox.getSpreadsheet('115年11月電子通報', f.context(true)));
  assert.equal(f.events.copies.length, 1);
  const result = f.sandbox.getSpreadsheet('115年11月電子通報', f.context(true));
  assert.ok(result);
  assert.equal(f.events.copies.length, 1);
});

test('getTarget uses the notice year, month and day rather than retrieval time', () => {
  const f = fixture();
  f.folder('115年', f.root);
  const first = f.sandbox.getTarget('115-11-01', f.context(true));
  const next = f.sandbox.getTarget('116-01-02', f.context(true));
  assert.equal(first.fileName, '115年11月電子通報');
  assert.equal(first.sheetName, '1號');
  assert.ok(first.sheet);
  assert.equal(next.fileName, '116年1月電子通報');
  assert.equal(next.sheetName, '2號');
  assert.ok(next.sheet);
});

function stubWritePipeline(f) {
  const s = f.sandbox;
  s.getWriteReceipt = () => null;
  s.saveWriteReceipt = () => {};
  s.logWriteTiming = () => {};
  s.getCurrentDutyRecipient = () => ({ slotKey: 'fixture', recipient: '' });
  s.getDutyRecipientContext = () => ({ slotKey: 'fixture' });
  s.writeGroups = () => {};
  s.writeContentUpdates = () => {};
  s.resolvePendingRecords = () => {};
  s.out = (value) => value;
  return s;
}

function request(action) {
  return { postData: { contents: JSON.stringify({
    action, requestId: 'notice-fixture-123',
    records: [{ key: '123', noticeId: '123', date: '115-11-01', subject: 'fixture', sender: 'fixture', content: 'fixture' }],
  }) } };
}

test('checkExisting is read-only even when the year and month do not exist', () => {
  const f = fixture();
  const s = stubWritePipeline(f);
  const result = s.doPost(request('checkExisting'));
  assert.equal(result.status, 'success');
  assert.equal(f.events.copies.length, 0);
  assert.equal(f.events.foldersCreated.length, 0);
  assert.equal(f.events.lockCalls, 0);
});

test('writeRecords permits creation only inside the acquired script lock', () => {
  const f = fixture();
  const s = stubWritePipeline(f);
  s.groupRecords = (_records, ctx) => {
    assert.equal(f.events.locked, true);
    assert.equal(ctx.allowCreate, true);
    assert.ok(s.getSpreadsheet('115年11月電子通報', ctx));
    return {};
  };
  const result = s.doPost(request('writeRecords'));
  assert.equal(result.status, 'success', result.message);
  assert.equal(f.events.lockCalls, 1);
  assert.equal(f.events.copies.length, 1);
  assert.equal(f.events.locked, false);
});

test('a busy script lock never starts creating folders or monthly files', () => {
  const f = fixture();
  const s = stubWritePipeline(f);
  f.failLock();
  s.groupRecords = () => assert.fail('must not enter write pipeline without a lock');
  const result = s.doPost(request('writeRecords'));
  assert.equal(result.status, 'error');
  assert.equal(result.retryable, true);
  assert.equal(f.events.copies.length, 0);
  assert.equal(f.events.foldersCreated.length, 0);
});

function dutyRecipientBoard(name, role, changes = {}) {
  const slot = { start_hour: 19, duty_nos: ['2'], names: [name], ...changes };
  if (role !== undefined) slot.roles = [role];
  return { days: [{ roc_date: '1151022', slots: [slot] }] };
}

function recipientSheet(choices) {
  return { getRange(row, column) {
    assert.equal(row, 3);
    assert.equal(column, 6);
    return { getDataValidation: () => ({ getCriteriaValues: () => [
      { getDisplayValues: () => choices.map((name) => [name]) },
    ] }) };
  } };
}

test('duty recipients use verified leadership roles and retain ordinary dropdown names', () => {
  const s = fixture().sandbox;
  const sheet = recipientSheet(['鄧分', '莊小', '孫小', '簡小', '張小', '宏澤', '小明']);
  for (const [name, role, expected] of [
    ['莊勝斌', '小隊長', '莊小'], ['孫領班', '小隊長', '孫小'],
    ['簡永豐', '小隊長', '簡小'], ['張領班', '小隊長', '張小'],
    ['鄧主管', '分隊長', '鄧分'], ['林宏澤', '隊員', '宏澤'],
    ['王小明', '隊員', '小明'], ['林宏澤', undefined, '宏澤'],
    ['莊小', undefined, '莊小'], ['宏澤', undefined, '宏澤'],
  ]) {
    const candidate = s.findDutyRecipient(dutyRecipientBoard(name, role), '1151022', 19);
    assert.equal(s.getValidDutyRecipient(sheet, candidate), expected, `${name}/${role}`);
  }
});

test('a surname alone never assigns an officer recipient or bypasses validation', () => {
  const s = fixture().sandbox;
  const sheet = recipientSheet(['莊小', '張小', '宏澤']);
  for (const [name, role] of [
    ['莊隊員', '隊員'], ['莊隊員', undefined], ['張隊員', '副小隊長'],
    ['莊勝斌', undefined], ['許主管', '小隊長'],
  ]) {
    assert.equal(s.getValidDutyRecipient(sheet,
      s.findDutyRecipient(dutyRecipientBoard(name, role), '1151022', 19)), '');
  }
  const ambiguous = dutyRecipientBoard('莊勝斌', '小隊長', { duty_nos: ['2', '10'] });
  assert.equal(s.findDutyRecipient(ambiguous, '1151022', 19), '');
  const misaligned = dutyRecipientBoard('莊勝斌', undefined, { roles: ['小隊長', '隊員'] });
  assert.equal(s.getValidDutyRecipient(sheet, s.findDutyRecipient(misaligned, '1151022', 19)), '');
  assert.equal(s.findDutyRecipient(dutyRecipientBoard('莊勝斌', '小隊長'), '1151023', 19), '');
});

test('officer signing writes a validated F value while keeping notice columns unchanged', () => {
  const s = fixture().sandbox;
  const sheet = recipientSheet(['莊小']);
  const record = { sender: 'fixture sender', subject: 'fixture subject', content: 'fixture content' };
  const batch = { groups: { day: { target: { sheet }, entries: [{ record, key: 'fixture-key', token: 'one' }] } }, tokenResults: {} };
  let written;
  s.getWritableRows = () => [47];
  s.writeRows = (_sheet, _rows, values) => { written = values; return [{ success: true }]; };
  const result = s.createWriteResult();
  s.writeGroups(batch, {}, result,
    s.findDutyRecipient(dutyRecipientBoard('莊勝斌', '小隊長'), '1151022', 19));
  assert.deepEqual(Array.from(written[0]), ['fixture sender', 'fixture subject', 'fixture content', '莊小']);
  assert.equal(result.success, 1);
});

test('the recipient cache cannot reuse a pre-role cropped name after deployment', () => {
  const s = fixture().sandbox;
  const cache = new Map([['noticeDutyRecipient:1151022|19', '勝斌']]);
  s.CacheService = { getScriptCache: () => ({
    get: (key) => cache.get(key) || null,
    put: (key, value) => cache.set(key, value),
  }) };
  s.getDutyRecipientContext = () => ({ rocDate: '1151022', hour: 19, slotKey: '1151022|19' });
  let reads = 0;
  s.DriveApp.getFileById = () => ({ getBlob: () => ({ getDataAsString: () => {
    reads++;
    return JSON.stringify(dutyRecipientBoard('莊勝斌', '小隊長'));
  } }) });
  assert.equal(s.getCurrentDutyRecipient().recipient, '莊小');
  assert.equal(s.getCurrentDutyRecipient().recipient, '莊小');
  assert.equal(reads, 1);
  assert.equal(cache.get('noticeDutyRecipient:1151022|19'), '勝斌');
});
