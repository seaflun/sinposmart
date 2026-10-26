'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const ROOT_ID = '1HDPbtqU_87StkzOcxLub2utVU_UGF8FJ';
const TEMPLATE_ID = '1AUj5M4wwYg29aTwa70EtAkDB8W37LuWsP8uqNXtbKJU';
const SHEETS_MIME = 'application/vnd.google-apps.spreadsheet';
const SOURCE_DIR = path.join(__dirname, '..', 'apps-script');
const FIXTURE_SYNC_KEY = 'synthetic-notice-sync-key';
const FIXTURE_VERIFIER = crypto.createHash('sha256').update(FIXTURE_SYNC_KEY).digest('hex');

function iterator(items) {
  let index = 0;
  return { hasNext: () => index < items.length, next: () => items[index++] };
}

function fixture() {
  const files = new Map();
  const folders = new Map();
  const properties = new Map([['NOTICE_COLLECTION_SYNC_KEY_SHA256', FIXTURE_VERIFIER]]);
  const events = { copies: [], foldersCreated: [], opened: [], locked: false, lockCalls: 0, driveReads: 0 };
  let effectiveUser = 'sinpo666@gmail.com';
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
    Session: { getEffectiveUser: () => ({ getEmail: () => effectiveUser }) },
    Utilities: {
      DigestAlgorithm: { SHA_256: 'sha256' }, Charset: { UTF_8: 'utf8' },
      computeDigest: (algorithm, value, encoding) => Array.from(crypto.createHash(algorithm).update(value, encoding).digest()),
    },
    DriveApp: {
      getFolderById(id) { events.driveReads++; assert.ok(folders.has(id), `unexpected folder ID ${id}`); return folders.get(id); },
      getFileById(id) { events.driveReads++; assert.ok(files.has(id), `unexpected file ID ${id}`); return files.get(id); },
      getFilesByName(name) { events.driveReads++; return iterator([...files.values()].filter((item) => item.name === name)); },
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
    setEffectiveUser(email) { effectiveUser = email; },
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

function request(action, changes = {}) {
  return { postData: { contents: JSON.stringify({
    action, requestId: 'notice-fixture-123', sync_key: FIXTURE_SYNC_KEY,
    records: [{ key: '123', noticeId: '123', date: '115-11-01', subject: 'fixture', sender: 'fixture', content: 'fixture' }],
    ...changes,
  }) } };
}

test('missing or wrong keys are rejected before context, Drive, locks or receipts', () => {
  for (const action of ['checkExisting', 'getWriteResult', 'writeRecords']) {
    for (const syncKey of [undefined, '', 'wrong-synthetic-key', FIXTURE_VERIFIER]) {
      const f = fixture();
      const s = stubWritePipeline(f);
      let contexts = 0, receipts = 0;
      const originalContext = s.newContext;
      s.newContext = () => { contexts++; return originalContext(); };
      s.getWriteReceipt = () => { receipts++; return null; };
      const result = s.doPost(request(action, { sync_key: syncKey }));
      assert.equal(result.status, 'error');
      assert.match(result.message, /unauthorized/i);
      assert.equal(contexts, 0);
      assert.equal(receipts, 0);
      assert.equal(f.events.driveReads, 0);
      assert.equal(f.events.lockCalls, 0);
      assert.equal(f.events.opened.length, 0);
      assert.equal(f.events.copies.length, 0);
      assert.equal(result.uncertain, false);
      assert.equal(JSON.stringify(result).includes(FIXTURE_SYNC_KEY), false);
      assert.equal(JSON.stringify(result).includes(FIXTURE_VERIFIER), false);
    }
  }
});

test('an unset or malformed verifier refuses even a correct key before accessing records', () => {
  for (const verifier of [undefined, '', 'invalid-verifier']) {
    const f = fixture();
    f.properties.set('NOTICE_COLLECTION_SYNC_KEY_SHA256', verifier);
    const s = stubWritePipeline(f);
    const result = s.doPost(request('checkExisting'));
    assert.equal(result.status, 'error');
    assert.match(result.message, /unauthorized/i);
    assert.equal(f.events.driveReads, 0);
    assert.equal(f.events.lockCalls, 0);
  }
});

test('malformed request syntax never echoes an authentication key', () => {
  const f = fixture();
  const s = stubWritePipeline(f);
  const result = s.doPost({ postData: { contents: `{"sync_key":"${FIXTURE_SYNC_KEY}"` } });
  assert.equal(result.status, 'error');
  assert.match(result.message, /invalid request payload/i);
  assert.equal(JSON.stringify(result).includes(FIXTURE_SYNC_KEY), false);
  assert.equal(f.events.driveReads, 0);
  assert.equal(f.events.lockCalls, 0);
});

test('a correct key permits the existing receipt lookup contract', () => {
  const f = fixture();
  const s = stubWritePipeline(f);
  let receipts = 0;
  s.getWriteReceipt = () => { receipts++; return null; };
  const result = s.doPost(request('getWriteResult'));
  assert.equal(result.status, 'success');
  assert.equal(result.found, false);
  assert.equal(receipts, 1);
});

test('only the owner can configure a verifier and configuration never returns it', () => {
  const f = fixture();
  f.properties.delete('NOTICE_COLLECTION_SYNC_KEY_SHA256');
  const configured = f.sandbox.configureNoticeCollectionAuthorization(FIXTURE_VERIFIER.toUpperCase());
  assert.equal(JSON.stringify(configured), '{"configured":true}');
  assert.equal(f.properties.get('NOTICE_COLLECTION_SYNC_KEY_SHA256'), FIXTURE_VERIFIER);
  f.setEffectiveUser('other@example.invalid');
  assert.throws(() => f.sandbox.configureNoticeCollectionAuthorization('a'.repeat(64)), /unauthorized/i);
  assert.equal(f.properties.get('NOTICE_COLLECTION_SYNC_KEY_SHA256'), FIXTURE_VERIFIER);
});

test('owner configuration accepts only a SHA256 verifier and never stores a raw key', () => {
  for (const value of [undefined, '', FIXTURE_SYNC_KEY, 'g'.repeat(64), { verifier: FIXTURE_VERIFIER }]) {
    const f = fixture();
    assert.throws(() => f.sandbox.configureNoticeCollectionAuthorization(value), /invalid.*verifier/i);
    assert.equal(f.properties.get('NOTICE_COLLECTION_SYNC_KEY_SHA256'), FIXTURE_VERIFIER);
    assert.equal(Array.from(f.properties.values()).includes(FIXTURE_SYNC_KEY), false);
  }
});

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

function recipientSheet(choices) {
  return { getRange(row, column) {
    assert.equal(row, 3);
    assert.equal(column, 6);
    return { getDataValidation: () => ({ getCriteriaValues: () => [
      { getDisplayValues: () => choices.map((name) => [name]) },
    ] }) };
  } };
}

function confirmedRecipientRecord(name = '莊勝斌', role = '小隊長') {
  return { key: 'responsibility-notice', sender: '測試單位', subject: '責任歸屬測試', content: '有效內文',
    receivedAt: '2026.10.21.1005', responsibility: { schema_version: 1, status: 'confirmed',
      actorNo: '1', name, role, capturedAt: '2026-10-21T10:05:00+08:00',
      handoffSlotAt: '2026-10-21T08:00:00+08:00', evidenceKey: 'a'.repeat(64) } };
}

test('notice signing uses each frozen confirmed person and never a scheduled fallback', () => {
  const s = fixture().sandbox;
  const records = [confirmedRecipientRecord(), confirmedRecipientRecord('林宏澤', '隊員'),
    { ...confirmedRecipientRecord(), responsibility: undefined }];
  records[1].key = 'second'; records[2].key = 'legacy';
  let written;
  s.getWritableRows = () => [3, 4, 5];
  s.writeRows = (_sheet, _rows, values) => { written = values; return values.map(() => ({ success: true })); };
  const batch = { groups: { day: { target: { sheet: recipientSheet(['莊小', '宏澤', '預定接班乙']) },
    entries: records.map(record => ({ record, key: record.key, token: record.key })) } }, tokenResults: {} };
  s.writeGroups(batch, {}, s.createWriteResult(), '預定接班乙');
  assert.deepEqual(written.map(row => row[3]), ['莊小', '宏澤', '']);
});

test('unknown malformed or mismatched responsibility never signs a notice', () => {
  const s = fixture().sandbox;
  for (const change of [{ status: 'unknown' }, { actorNo: '' }, { handoffSlotAt: '2026-10-21T11:00:00+08:00' },
    { capturedAt: '2026-10-21T10:06:00+08:00' }, { evidenceKey: '' }, { name: '私人\n資料' }]) {
    const record = confirmedRecipientRecord(); Object.assign(record.responsibility, change);
    assert.equal(s.getCurrentDutyRecipient(record).recipient, '');
  }
});

test('compact notes retain notice identity receipt and full signer without erasing human notes', () => {
  const s = fixture().sandbox;
  const entry = { record: confirmedRecipientRecord(), signingRecipient: '莊小' };
  const note = s.withNoticeMetadataNote('人工備註', '123', '2026.10.21.1005', entry);
  assert.match(note, /人工備註/);
  assert.match(note, /1番 莊勝斌/);
  assert.equal(s.readNoticeIdFromNote(note), '123');
  assert.match(note, /SinpoSmart receivedAt: 2026\.10\.21\.1005/);
  assert.match(note, /^SinpoSmart signing:\n1番 莊勝斌$/m);
  assert.doesNotMatch(note, /\(莊小\)/);
  assert.doesNotMatch(note, /capturedAt=|evidence=/);
  assert.ok(note.length < 110);
  assert.equal(entry.record.responsibility.evidenceKey, 'a'.repeat(64));
  const again = s.withNoticeMetadataNote(note, '123', '2026.10.21.1005', entry);
  assert.equal(again, note);
  const old = '人工備註\nSinpoSmart noticeId: 123\nSinpoSmart receivedAt: 2026.10.21.1005\n'
    + 'SinpoSmart signing: 1番 莊勝斌 (莊小); capturedAt=2026-10-21T10:05:00+08:00; evidence=' + 'a'.repeat(64);
  assert.equal(s.withNoticeMetadataNote(old, '123', '2026.10.21.1005', entry), note);
  assert.equal(s.withNoticeMetadataNote(note.replace('signing:\n', 'signing: '), '123', '2026.10.21.1005', entry), note);
  entry.signingRecipient = '';
  const unknown = s.withNoticeMetadataNote(note, '123', '2026.10.21.1005', entry);
  assert.match(unknown, /signing: 待人工確認/);
  assert.doesNotMatch(unknown, /莊勝斌/);
});

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
    const candidate = s.getCurrentDutyRecipient(confirmedRecipientRecord(name, role || '')).recipient;
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
      s.getCurrentDutyRecipient(confirmedRecipientRecord(name, role || '')).recipient), '');
  }
  const ambiguous = confirmedRecipientRecord();
  ambiguous.responsibility.actorNo = ['2', '10'];
  assert.equal(s.getCurrentDutyRecipient(ambiguous).recipient, '');
  const misaligned = confirmedRecipientRecord();
  misaligned.responsibility.role = ['小隊長', '隊員'];
  assert.equal(s.getCurrentDutyRecipient(misaligned).recipient, '');

});

test('officer signing writes a validated F value while keeping notice columns unchanged', () => {
  const s = fixture().sandbox;
  const sheet = recipientSheet(['莊小']);
  const record = { ...confirmedRecipientRecord(), sender: 'fixture sender', subject: 'fixture subject', content: 'fixture content' };
  const batch = { groups: { day: { target: { sheet }, entries: [{ record, key: 'fixture-key', token: 'one' }] } }, tokenResults: {} };
  let written;
  s.getWritableRows = () => [47];
  s.writeRows = (_sheet, _rows, values) => { written = values; return [{ success: true }]; };
  const result = s.createWriteResult();
  s.writeGroups(batch, {}, result);
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
    throw new Error('Signing must not read the roster');
  } }) });
  assert.equal(s.getCurrentDutyRecipient(confirmedRecipientRecord()).recipient, '莊小');
  assert.equal(s.getCurrentDutyRecipient(confirmedRecipientRecord()).recipient, '莊小');
  assert.equal(s.getCurrentDutyRecipient().recipient, '');
  assert.equal(reads, 0);
  assert.equal(cache.get('noticeDutyRecipient:1151022|19'), '勝斌');
});

function readonlyLinkFixture() {
  const f = fixture();
  const blocked = [];
  const forbid = (name) => () => { blocked.push(name); throw new Error('forbidden ' + name); };
  f.sandbox.out = (value) => value;
  f.sandbox.logWriteTiming = () => {};
  f.sandbox.newContext = forbid('newContext');
  f.sandbox.PropertiesService.getScriptProperties = () => ({
    getProperty(key) {
      assert.equal(key, 'NOTICE_COLLECTION_SYNC_KEY_SHA256');
      return f.properties.get(key) || null;
    },
    setProperty: forbid('setProperty'), deleteProperty: forbid('deleteProperty'),
  });
  f.sandbox.CacheService = { getScriptCache: forbid('cache') };
  f.sandbox.LockService = { getScriptLock: forbid('lock') };
  f.sandbox.SpreadsheetApp = {
    open: forbid('open'), openById: forbid('openById'),
    create: forbid('create'), flush: forbid('flush'),
  };
  f.sandbox.DriveApp.getFileById = forbid('getFileById');
  f.sandbox.DriveApp.getFilesByName = forbid('globalFileSearch');
  for (const folder of f.folders.values()) folder.createFolder = forbid('createFolder');
  const addFolder = f.folder;
  f.folder = (...args) => {
    const result = addFolder(...args);
    result.createFolder = forbid('createFolder');
    return result;
  };
  const addFile = f.file;
  f.file = (name, parent, options = {}) => {
    const result = addFile(name, parent, {
      id: `1ReadonlyMonthlyFixture_${f.files.size}_0123456789`, ...options,
    });
    result.makeCopy = forbid('makeCopy');
    return result;
  };
  f.template.makeCopy = forbid('makeCopy');
  f.link = (changes = {}) => JSON.parse(JSON.stringify(f.sandbox.doPost({ postData: {
    contents: JSON.stringify({ action: 'getMonthlySpreadsheetLink', year: 2026, month: 10,
      sync_key: FIXTURE_SYNC_KEY, ...changes }),
  } })));
  f.blocked = blocked;
  return f;
}

test('monthly spreadsheet link resolves exact ROC month metadata without opening or changing a sheet', () => {
  const f = readonlyLinkFixture();
  for (const [year, month, roc, id] of [
    [2026, 10, 115, '1NoticeOctoberWorkbook_0123456789abc'],
    [2027, 1, 116, '1NoticeJanuaryWorkbook_0123456789abc'],
  ]) {
    const folder = f.folder(`${roc}年`, f.root);
    f.file(`${roc}年${month}月電子通報`, folder, { id, data: { sheets: [] } });
    assert.deepEqual(f.link({ year, month }), {
      status: 'success', year, month, spreadsheetId: id,
      spreadsheetUrl: `https://docs.google.com/spreadsheets/d/${id}/edit`,
    });
  }
  assert.deepEqual(f.blocked, []);
  assert.deepEqual(f.events.copies, []);
  assert.deepEqual(f.events.foldersCreated, []);
  assert.deepEqual(f.events.opened, []);
  assert.equal(f.events.lockCalls, 0);
  assert.deepEqual([...f.properties], [['NOTICE_COLLECTION_SYNC_KEY_SHA256', FIXTURE_VERIFIER]]);
});

test('monthly spreadsheet link rejects invalid or coerced months before Drive access', () => {
  for (const changes of [{ year: '2026' }, { year: true }, { year: 2026.5 }, { year: 2010 },
    { year: 2911 }, { year: null }, { month: '10' }, { month: true }, { month: 10.5 },
    { month: 0 }, { month: 13 }, { month: null }]) {
    const f = readonlyLinkFixture();
    assert.deepEqual(f.link(changes), { status: 'error', error: 'invalid_month' });
    assert.equal(f.events.driveReads, 0);
    assert.deepEqual(f.blocked, []);
  }
});

test('monthly spreadsheet link reports a missing year or month without creating anything or searching elsewhere', () => {
  for (const placement of ['missing-year', 'missing-month', 'wrong-parent']) {
    const f = readonlyLinkFixture();
    if (placement !== 'missing-year') f.folder('115年', f.root);
    if (placement === 'wrong-parent') {
      const other = f.folder('116年', f.root);
      f.file('115年10月電子通報', other);
      f.file('115年10月電子通報', f.root);
    }
    assert.deepEqual(f.link(), { status: 'error', error: 'spreadsheet_not_found' });
    assert.deepEqual(f.blocked, []);
    assert.deepEqual(f.events.copies, []);
    assert.deepEqual(f.events.foldersCreated, []);
  }
});

test('monthly spreadsheet link refuses ambiguous year folders or monthly files', () => {
  for (const duplicate of ['year', 'month']) {
    const f = readonlyLinkFixture();
    const year = f.folder('115年', f.root);
    f.file('115年10月電子通報', year);
    if (duplicate === 'year') f.folder('115年', f.root);
    else f.file('115年10月電子通報', year);
    assert.deepEqual(f.link(), { status: 'error', error: 'ambiguous_spreadsheet' });
    assert.deepEqual(f.blocked, []);
  }
});

test('monthly spreadsheet link rejects a same-name non-Sheets file', () => {
  const f = readonlyLinkFixture();
  const year = f.folder('115年', f.root);
  f.file('115年10月電子通報', year, { mime: 'application/pdf' });
  assert.deepEqual(f.link(), { status: 'error', error: 'invalid_spreadsheet' });
  assert.deepEqual(f.blocked, []);
});

test('monthly spreadsheet link does not return a trashed workbook', () => {
  const f = readonlyLinkFixture();
  const year = f.folder('115年', f.root);
  const file = f.file('115年10月電子通報', year);
  file.isTrashed = () => true;
  assert.deepEqual(f.link(), { status: 'error', error: 'spreadsheet_not_found' });
  assert.deepEqual(f.blocked, []);
});

test('monthly spreadsheet link rejects an invalid metadata ID rather than constructing an unsafe URL', () => {
  for (const id of ['https://unsafe.invalid/private', 'A'.repeat(19), 'A'.repeat(129)]) {
    const f = readonlyLinkFixture();
    const year = f.folder('115年', f.root);
    f.file('115年10月電子通報', year, { id });
    assert.deepEqual(f.link(), { status: 'error', error: 'invalid_spreadsheet' });
    assert.deepEqual(f.blocked, []);
  }
});

test('monthly spreadsheet link keeps lookup failure distinct from a missing file without private error text', () => {
  const f = readonlyLinkFixture();
  const year = f.folder('115年', f.root);
  year.getFilesByName = () => { throw new Error('synthetic-private-detail'); };
  const result = f.link();
  assert.deepEqual(result, { status: 'error', error: 'lookup_failed' });
  assert.ok(!JSON.stringify(result).includes('synthetic-private-detail'));
  assert.deepEqual(f.blocked, []);
});

test('monthly spreadsheet link rejects missing wrong or unconfigured authorization before metadata access', () => {
  for (const scenario of ['missing', 'wrong', 'unconfigured']) {
    const f = readonlyLinkFixture();
    if (scenario === 'unconfigured') f.properties.delete('NOTICE_COLLECTION_SYNC_KEY_SHA256');
    const result = f.link(scenario === 'missing' ? { sync_key: undefined } :
      scenario === 'wrong' ? { sync_key: 'synthetic-wrong-private-key' } : {});
    assert.equal(result.status, 'error');
    assert.match(result.message, /Unauthorized notice request/);
    assert.ok(!JSON.stringify(result).includes('synthetic-wrong-private-key'));
    assert.equal(f.events.driveReads, 0);
    assert.deepEqual(f.blocked, []);
  }
});

test('monthly spreadsheet link ignores stale cached IDs and leaves properties unchanged', () => {
  const f = readonlyLinkFixture();
  const year = f.folder('115年', f.root);
  const id = '1CorrectMonthlyWorkbook_0123456789abc';
  f.file('115年10月電子通報', year, { id });
  f.properties.set('spreadsheetId:115年10月電子通報', 'unrelated-cached-workbook');
  const before = [...f.properties];
  assert.equal(f.link().spreadsheetId, id);
  assert.equal(f.link().spreadsheetId, id);
  assert.deepEqual([...f.properties], before);
  assert.deepEqual(f.blocked, []);
});
