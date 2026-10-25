var NOTICE_WORKBOOK_ROOT_FOLDER_ID = "1HDPbtqU_87StkzOcxLub2utVU_UGF8FJ";
var NOTICE_WORKBOOK_TEMPLATE_ID = "1AUj5M4wwYg29aTwa70EtAkDB8W37LuWsP8uqNXtbKJU";

function getSpreadsheet(fileName, ctx) {
  if (ctx.ssCache[fileName]) return ctx.ssCache[fileName];
  var match = /^(\d{3})年(?:[1-9]|1[0-2])月電子通報$/.exec(fileName);
  if (!match) throw new Error("通報月份檔名無法確認，未建立檔案。");

  var root = DriveApp.getFolderById(NOTICE_WORKBOOK_ROOT_FOLDER_ID);
  var yearName = match[1] + "年";
  var folders = root.getFoldersByName(yearName);
  var folder = folders.hasNext() ? folders.next() : null;
  if (folders.hasNext()) throw new Error("通報年度資料夾同名超過一份：" + yearName);

  var file = null;
  if (folder) {
    var files = folder.getFilesByName(fileName);
    file = files.hasNext() ? files.next() : null;
    if (files.hasNext()) throw new Error("通報月份檔案同名超過一份：" + fileName);
  }
  if (!file) {
    if (!ctx.allowCreate) return null;
    var template = DriveApp.getFileById(NOTICE_WORKBOOK_TEMPLATE_ID);
    if (template.getMimeType() !== MimeType.GOOGLE_SHEETS) {
      throw new Error("通報母檔不是Google試算表，未建立月份檔案。");
    }
    if (!folder) folder = root.createFolder(yearName);
    file = template.makeCopy(fileName, folder);
  }
  if (file.getMimeType() !== MimeType.GOOGLE_SHEETS) {
    throw new Error("通報月份同名檔案不是Google試算表：" + fileName);
  }
  var ss = SpreadsheetApp.open(file);
  ctx.props.setProperty("spreadsheetId:" + fileName, ss.getId());
  ctx.ssCache[fileName] = ss;
  return ss;
}

function getNoticeIndex(target, ctx) {
  var key = target.fileName + "|" + target.sheetName;
  if (ctx.noticeCache[key]) return ctx.noticeCache[key];
  var noticeIndex = {
    ids: {},
    composites: {},
    legacyRows: {}
  };
  var lastRow = target.sheet.getLastRow();
  if (lastRow >= 3) {
    var rowCount = lastRow - 2;
    var values = target.sheet.getRange(3, 3, rowCount, 3).getValues();
    var notes = target.sheet.getRange(3, 4, rowCount, 1).getNotes();
    for (var index = 0; index < values.length; index++) {
      var subject = norm(values[index][1]);
      if (!subject) continue;
      var composite = buildCompositeKey({
        date: target.date,
        subject: subject,
        sender: values[index][0]
      });
      var compositeKey = noticeSetKey(composite);
      var noticeId = readNoticeIdFromNote(notes[index][0]);
      if (!noticeIndex.composites[compositeKey]) {
        noticeIndex.composites[compositeKey] = {
          persisted: true,
          pendingTokens: [],
          row: index + 3,
          content: values[index][2]
        };
      } else {
        noticeIndex.composites[compositeKey].persisted = true;
      }
      if (noticeId) {
        noticeIndex.ids[noticeSetKey(noticeId)] = {
          persisted: true,
          row: index + 3,
          content: values[index][2]
        };
      } else {
        if (!noticeIndex.legacyRows[compositeKey]) noticeIndex.legacyRows[compositeKey] = [];
        noticeIndex.legacyRows[compositeKey].push({
          row: index + 3,
          content: values[index][2]
        });
      }
    }
  }
  ctx.noticeCache[key] = noticeIndex;
  return noticeIndex;
}

function buildCompositeKey(record) {
  return [record.date, record.subject, record.sender].map(norm).join("|");
}

function getRecordKey(record) {
  return norm(record.key) || norm(record.noticeId) || buildCompositeKey(record);
}

function noticeSetKey(value) {
  return "key|" + norm(value);
}

function hasNoticeId(noticeIndex, noticeId) {
  return Boolean(noticeIndex.ids[noticeSetKey(noticeId)]);
}

function hasComposite(noticeIndex, composite) {
  return Boolean(noticeIndex.composites[noticeSetKey(composite)]);
}

function getNoticeIdEntry(noticeIndex, noticeId) {
  return noticeIndex.ids[noticeSetKey(noticeId)] || null;
}

function getCompositeEntry(noticeIndex, composite) {
  return noticeIndex.composites[noticeSetKey(composite)] || null;
}

function hasLegacyComposite(noticeIndex, composite) {
  var rows = noticeIndex.legacyRows[noticeSetKey(composite)];
  return Boolean(rows && rows.length > 0);
}

function claimLegacyNotice(target, noticeIndex, composite, noticeId) {
  var compositeKey = noticeSetKey(composite);
  var rows = noticeIndex.legacyRows[compositeKey];
  if (!rows || rows.length === 0) throw new Error("Legacy notice row is unavailable");
  var legacyEntry = rows.shift();
  var noteRange = target.sheet.getRange(legacyEntry.row, 4);
  var note = noteRange.getNote();
  noteRange.setNote(withNoticeIdNote(note, noticeId));
  var claimedEntry = {
    persisted: true,
    row: legacyEntry.row,
    content: legacyEntry.content
  };
  noticeIndex.ids[noticeSetKey(noticeId)] = claimedEntry;
  return claimedEntry;
}

function reserveRecord(noticeIndex, record, token) {
  var noticeId = norm(record.noticeId);
  var compositeKey = noticeSetKey(buildCompositeKey(record));
  if (!noticeIndex.composites[compositeKey]) {
    noticeIndex.composites[compositeKey] = {
      persisted: false,
      pendingTokens: []
    };
  }
  noticeIndex.composites[compositeKey].pendingTokens.push(token);
  if (noticeId) {
    noticeIndex.ids[noticeSetKey(noticeId)] = {
      persisted: false,
      token: token
    };
  }
}

function readNoticeIdFromNote(note) {
  var lines = String(note || "").split(/\r?\n/);
  for (var index = 0; index < lines.length; index++) {
    var match = lines[index].match(/^\s*SinpoSmart noticeId:\s*(.*?)\s*$/);
    if (match && norm(match[1])) return norm(match[1]);
  }
  return "";
}

function withNoticeIdNote(note, noticeId) {
  return withNoticeMetadataNote(note, noticeId, "");
}

function withNoticeMetadataNote(note, noticeId, receivedAt, entry) {
  var current = String(note || "");
  var normalizedNoticeId = norm(noticeId);
  var normalizedReceivedAt = norm(receivedAt);
  if (!normalizedNoticeId && !normalizedReceivedAt) return current;
  var lines = current ? current.split(/\r?\n/) : [];

  if (normalizedNoticeId) {
    var noticeIdMarker = "SinpoSmart noticeId: " + normalizedNoticeId;
    var noticeIdUpdated = false;
    for (var noticeIdIndex = 0; noticeIdIndex < lines.length; noticeIdIndex++) {
      if (/^\s*SinpoSmart noticeId:\s*/.test(lines[noticeIdIndex])) {
        lines[noticeIdIndex] = noticeIdMarker;
        noticeIdUpdated = true;
        break;
      }
    }
    if (!noticeIdUpdated) lines.push(noticeIdMarker);
  }

  if (normalizedReceivedAt) {
    var receivedAtMarker = "SinpoSmart receivedAt: " + normalizedReceivedAt;
    var receivedAtUpdated = false;
    for (var receivedAtIndex = 0; receivedAtIndex < lines.length; receivedAtIndex++) {
      if (/^\s*SinpoSmart receivedAt:\s*/.test(lines[receivedAtIndex])) {
        lines[receivedAtIndex] = receivedAtMarker;
        receivedAtUpdated = true;
        break;
      }
    }
    if (!receivedAtUpdated) lines.push(receivedAtMarker);
  }

  if (entry && typeof entry.signingRecipient === "string") {
    lines = lines.filter(function(line) { return !/^SinpoSmart signing:/.test(line); });
    var proof = entry.record.responsibility;
    var signing = "SinpoSmart signing: unconfirmed; manual confirmation required";
    if (entry.signingRecipient) signing = "SinpoSmart signing: " + proof.actorNo + "番 " + proof.name
      + " (" + entry.signingRecipient + "); capturedAt=" + proof.capturedAt + "; evidence=" + proof.evidenceKey;
    lines.push(signing);
  }
  return lines.join("\n");
}

function getWritableRows(target, count, ctx) {
  var key = target.fileName + "|" + target.sheetName;
  if (!ctx.rowCache[key]) ctx.rowCache[key] = scanRows(target);
  var rows = ctx.rowCache[key];
  while (rows.length < count) {
    var last = rows.length > 0 ? rows[rows.length - 1] : target.sheet.getLastRow();
    rows.push(last + 1);
  }
  var picked = rows.slice(0, count);
  ctx.rowCache[key] = rows.slice(count);
  return picked;
}

function scanRows(target) {
  var start = 3;
  var values = target.sheet.getRange(start, 3, 100, 1).getValues();
  var rows = [];
  for (var i = 0; i < values.length; i++) {
    if (values[i][0] === "") rows.push(start + i);
  }
  if (rows.length === 0) rows.push(start + values.length);
  return rows;
}

function writeRows(sheet, rows, values, entries) {
  var outcomes = new Array(rows.length);
  var i = 0;
  while (i < rows.length) {
    var j = i + 1;
    while (j < rows.length && rows[j] === rows[j - 1] + 1) j++;
    var count = j - i;
    try {
      sheet.getRange(rows[i], 3, count, 4).setValues(values.slice(i, j));
    } catch (err) {
      for (var failedIndex = i; failedIndex < j; failedIndex++) {
        outcomes[failedIndex] = { success: false, error: err.toString() };
      }
      i = j;
      continue;
    }
    writeNoticeNotes(sheet, rows, entries, i, j, outcomes);
    i = j;
  }
  return outcomes;
}

function writeNoticeNotes(sheet, rows, entries, start, end, outcomes) {
  var hasNoticeMetadata = false;
  for (var index = start; index < end; index++) {
    var record = entries[index].record;
    if (norm(record.noticeId) || norm(record.receivedAt)) {
      hasNoticeMetadata = true;
      break;
    }
  }
  if (!hasNoticeMetadata) {
    for (var noIdIndex = start; noIdIndex < end; noIdIndex++) {
      outcomes[noIdIndex] = { success: true };
    }
    return;
  }

  try {
    var count = end - start;
    var noteRange = sheet.getRange(rows[start], 4, count, 1);
    var notes = noteRange.getNotes();
    for (var noteIndex = start; noteIndex < end; noteIndex++) {
      var record = entries[noteIndex].record;
      notes[noteIndex - start][0] = withNoticeMetadataNote(
        notes[noteIndex - start][0],
        record.noticeId,
        record.receivedAt,
        entries[noteIndex]
      );
    }
    noteRange.setNotes(notes);
    for (var successIndex = start; successIndex < end; successIndex++) {
      outcomes[successIndex] = { success: true };
    }
  } catch (err) {
    writeNoticeNotesIndividually(sheet, rows, entries, start, end, outcomes, err);
  }
}

function writeNoticeNotesIndividually(sheet, rows, entries, start, end, outcomes, batchError) {
  for (var index = start; index < end; index++) {
    var record = entries[index].record;
    if (!norm(record.noticeId) && !norm(record.receivedAt)) {
      outcomes[index] = { success: true };
      continue;
    }
    try {
      var noteRange = sheet.getRange(rows[index], 4);
      noteRange.setNote(withNoticeMetadataNote(
        noteRange.getNote(),
        record.noticeId,
        record.receivedAt,
        entries[index]
      ));
      outcomes[index] = { success: true };
    } catch (err) {
      outcomes[index] = {
        success: false,
        error: batchError.toString() + "; " + err.toString()
      };
    }
  }
}

function norm(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function isNoticeContentUnavailable(content) {
  var value = norm(content);
  return !value || ["權限限制", "內文抓取失敗", "讀取失敗", "Session Time Out"].indexOf(value) !== -1 ||
    (value.indexOf("作業逾時") === 0 && value.indexOf("重新登入") !== -1);
}

function out(value) {
  return ContentService.createTextOutput(JSON.stringify(value))
    .setMimeType(ContentService.MimeType.JSON);
}
