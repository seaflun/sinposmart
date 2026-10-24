var WRITE_RECEIPT_CACHE_PREFIX = "noticeWriteReceipt:";
var WRITE_RECEIPT_TTL_SECONDS = 10 * 60;
var MAX_RECORDS_PER_REQUEST = 200;
var DUTY_RECIPIENT_CACHE_PREFIX = "noticeDutyRecipient:v2:";

function doPost(e) {
  var startedAt = Date.now();
  var res = createWriteResult();
  var ctx = null;
  var lock = null;
  var locked = false;
  var requestId = "";
  var timing = {};
  var writeMayHaveStarted = false;
  var retryable = false;
  try {
    var data;
    try {
      data = JSON.parse(e.postData.contents);
    } catch (_parseError) {
      throw new Error("Invalid request payload");
    }
    authorizeNoticeCollection_(data);
    if (data && data.action === "getMonthlySpreadsheetLink") {
      return out(getMonthlySpreadsheetLink(data));
    }
    ctx = newContext();
    if (data && data.action === "checkExisting") {
      return checkExisting(validateRecords(data.records || []), ctx);
    }
    if (data && data.action === "getWriteResult") return getWriteResult(data.requestId);

    var request = parseWriteRequest(data);
    requestId = request.requestId;
    var receipt = getWriteReceipt(requestId);
    if (receipt) {
      timing.totalMs = Date.now() - startedAt;
      logWriteTiming(requestId, receipt.result, timing, true);
      return out(receiptResponse(receipt, requestId));
    }

    var dutyStartedAt = Date.now();
    var dutyState = getCurrentDutyRecipient();
    timing.dutyRecipientMs = Date.now() - dutyStartedAt;

    lock = LockService.getScriptLock();
    var lockStartedAt = Date.now();
    try {
      lock.waitLock(30000);
    } catch (lockErr) {
      retryable = true;
      throw lockErr;
    }
    timing.lockWaitMs = Date.now() - lockStartedAt;
    locked = true;

    receipt = getWriteReceipt(requestId);
    if (receipt) {
      timing.totalMs = Date.now() - startedAt;
      logWriteTiming(requestId, receipt.result, timing, true);
      return out(receiptResponse(receipt, requestId));
    }

    if (dutyState.slotKey !== getDutyRecipientContext().slotKey) {
      var refreshStartedAt = Date.now();
      dutyState = getCurrentDutyRecipient();
      timing.dutyRecipientRefreshMs = Date.now() - refreshStartedAt;
    }

    var groupingStartedAt = Date.now();
    writeMayHaveStarted = true;
    ctx.allowCreate = true;
    var batch = groupRecords(request.records, ctx, res);
    timing.groupRecordsMs = Date.now() - groupingStartedAt;
    var writeStartedAt = Date.now();
    writeGroups(batch, ctx, res, dutyState.recipient);
    writeContentUpdates(batch, res);
    timing.writeGroupsMs = Date.now() - writeStartedAt;
    resolvePendingRecords(batch, res);
    var flushStartedAt = Date.now();
    SpreadsheetApp.flush();
    timing.flushMs = Date.now() - flushStartedAt;
    timing.totalMs = Date.now() - startedAt;

    var response = {
      status: "success",
      requestId: requestId,
      result: res,
      timing: timing
    };
    saveWriteReceipt(requestId, response);
    logWriteTiming(requestId, res, timing, false);
    return out(response);
  } catch (err) {
    timing.totalMs = Date.now() - startedAt;
    logWriteTiming(requestId, res, timing, false, err);
    return out({
      status: "error",
      requestId: requestId,
      message: err.toString(),
      timing: timing,
      uncertain: writeMayHaveStarted,
      retryable: retryable
    });
  } finally {
    if (locked) lock.releaseLock();
  }
}

function authorizeNoticeCollection_(data) {
  var key = data && typeof data.sync_key === "string" ? data.sync_key : "";
  var verifier = String(PropertiesService.getScriptProperties()
    .getProperty("NOTICE_COLLECTION_SYNC_KEY_SHA256") || "").toLowerCase();
  if (!key || !/^[a-f0-9]{64}$/.test(verifier)) {
    throw new Error("Unauthorized notice request");
  }
  var digest = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, key, Utilities.Charset.UTF_8)
    .map(function(value) { return ("0" + ((value + 256) % 256).toString(16)).slice(-2); }).join("");
  var difference = 0;
  for (var index = 0; index < 64; index++) {
    difference |= verifier.charCodeAt(index) ^ digest.charCodeAt(index);
  }
  if (difference !== 0) throw new Error("Unauthorized notice request");
}

function configureNoticeCollectionAuthorization(verifierSha256) {
  var email = String(Session.getEffectiveUser().getEmail() || "").toLowerCase();
  if (email !== "sinpo666@gmail.com") throw new Error("Unauthorized configuration");
  if (typeof verifierSha256 !== "string" || !/^[a-fA-F0-9]{64}$/.test(verifierSha256)) {
    throw new Error("Invalid authorization verifier");
  }
  PropertiesService.getScriptProperties().setProperty(
    "NOTICE_COLLECTION_SYNC_KEY_SHA256", verifierSha256.toLowerCase());
  return { configured: true };
}

function createWriteResult() {
  return {
    success: 0,
    skipped: 0,
    errors: 0,
    messages: [],
    handledKeys: [],
    writtenKeys: [],
    skippedKeys: [],
    errorKeys: []
  };
}

function parseWriteRequest(data) {
  if (Array.isArray(data)) {
    return { records: validateRecords(data), requestId: "" };
  }
  if (!data || data.action !== "writeRecords" || !Array.isArray(data.records)) {
    throw new Error("Invalid records payload");
  }
  var requestId = normalizeRequestId(data.requestId);
  if (!requestId) throw new Error("Request ID is required");
  return {
    records: validateRecords(data.records),
    requestId: requestId
  };
}

function validateRecords(records) {
  if (!Array.isArray(records) || records.length > MAX_RECORDS_PER_REQUEST) {
    throw new Error("Invalid records payload");
  }
  records.forEach(function(record) {
    if (!record || typeof record !== "object" || Array.isArray(record)) {
      throw new Error("Invalid record");
    }
    if (!/^\d{3}-\d{2}-\d{2}$/.test(String(record.date || ""))) {
      throw new Error("Invalid record date");
    }
    ["key", "subject", "sender", "content", "noticeId", "receivedAt"].forEach(function(field) {
      if (record[field] !== undefined && typeof record[field] !== "string") {
        throw new Error("Invalid record field");
      }
    });
  });
  return records;
}

function normalizeRequestId(value) {
  var requestId = norm(value);
  if (!requestId) return "";
  if (!/^[A-Za-z0-9_-]{8,128}$/.test(requestId)) {
    throw new Error("Invalid request ID");
  }
  return requestId;
}

function getWriteResult(requestId) {
  var normalizedRequestId = normalizeRequestId(requestId);
  if (!normalizedRequestId) throw new Error("Request ID is required");
  var receipt = getWriteReceipt(normalizedRequestId);
  return out({
    status: "success",
    requestId: normalizedRequestId,
    found: Boolean(receipt),
    result: receipt ? receipt.result : null
  });
}

function getWriteReceipt(requestId) {
  if (!requestId) return null;
  try {
    var raw = CacheService.getScriptCache().get(WRITE_RECEIPT_CACHE_PREFIX + requestId);
    if (!raw) return null;
    var receipt = JSON.parse(raw);
    if (receipt && receipt.status === "success" && receipt.result) return receipt;
  } catch (err) {
    console.log("Notice write receipt read failed: " + err.toString());
  }
  return null;
}

function saveWriteReceipt(requestId, response) {
  if (!requestId) return;
  try {
    var raw = JSON.stringify(response);
    if (raw.length <= 95000) {
      CacheService.getScriptCache().put(
        WRITE_RECEIPT_CACHE_PREFIX + requestId,
        raw,
        WRITE_RECEIPT_TTL_SECONDS
      );
    }
  } catch (err) {
    console.log("Notice write receipt save failed: " + err.toString());
  }
}

function receiptResponse(receipt, requestId) {
  return {
    status: "success",
    requestId: requestId,
    result: receipt.result,
    timing: receipt.timing || {},
    receipt: true
  };
}

function logWriteTiming(requestId, res, timing, receipt, err) {
  console.log(JSON.stringify({
    event: "notice_write",
    requestId: requestId || "legacy",
    receipt: Boolean(receipt),
    success: res && res.success || 0,
    skipped: res && res.skipped || 0,
    errors: res && res.errors || 0,
    timing: timing,
    error: err ? err.toString() : ""
  }));
}

function checkExisting(records, ctx) {
  var existingKeys = [];
  var retryKeys = [];
  records.forEach(function(record) {
    var target = getTarget(record.date, ctx);
    if (target.error) return;
    var noticeIndex = getNoticeIndex(target, ctx);
    var noticeId = norm(record.noticeId);
    var existingEntry = noticeId
      ? getNoticeIdEntry(noticeIndex, noticeId)
      : getCompositeEntry(noticeIndex, buildCompositeKey(record));
    if (!existingEntry) return;
    if (isNoticeContentUnavailable(existingEntry.content)) {
      retryKeys.push(getRecordKey(record));
    } else {
      existingKeys.push(getRecordKey(record));
    }
  });
  return out({
    status: "success",
    existingKeys: existingKeys,
    retryKeys: retryKeys
  });
}

function groupRecords(records, ctx, res) {
  var batch = {
    groups: {},
    updates: [],
    dependencies: [],
    tokenResults: {},
    nextToken: 1
  };
  var entries = records.map(function(record, index) {
    return { record: record, index: index };
  });
  entries.sort(function(left, right) {
    var idOrder = Number(Boolean(norm(right.record.noticeId))) -
      Number(Boolean(norm(left.record.noticeId)));
    return idOrder || left.index - right.index;
  });
  entries.forEach(function(entry) {
    prepareRecord(entry, batch, ctx, res);
  });
  Object.keys(batch.groups).forEach(function(key) {
    batch.groups[key].entries.sort(function(left, right) {
      return left.index - right.index;
    });
  });
  return batch;
}

function prepareRecord(entry, batch, ctx, res) {
  var record = entry.record;
  var recordKey = getRecordKey(record);
  entry.key = recordKey;
  try {
    var target = getTarget(record.date, ctx);
    if (target.error) {
      addError(res, recordKey, target.error);
      return;
    }
    var noticeIndex = getNoticeIndex(target, ctx);
    var noticeId = norm(record.noticeId);
    var composite = buildCompositeKey(record);
    var existingId = noticeId ? getNoticeIdEntry(noticeIndex, noticeId) : null;
    if (existingId) {
      if (existingId.persisted) {
        if (shouldRewriteNotice(existingId, record)) {
          batch.updates.push({ target: target, row: existingId.row, entry: entry });
        } else if (isNoticeContentUnavailable(existingId.content)) {
          addError(res, recordKey, "內文仍無法讀取");
        } else {
          addSkipped(res, recordKey);
        }
      } else {
        batch.dependencies.push({ key: recordKey, tokens: [existingId.token] });
      }
      return;
    }
    if (noticeId && hasLegacyComposite(noticeIndex, composite)) {
      var legacyEntry = claimLegacyNotice(target, noticeIndex, composite, noticeId);
      if (shouldRewriteNotice(legacyEntry, record)) {
        batch.updates.push({ target: target, row: legacyEntry.row, entry: entry });
      } else if (isNoticeContentUnavailable(legacyEntry.content)) {
        addError(res, recordKey, "內文仍無法讀取");
      } else {
        addSkipped(res, recordKey);
      }
      return;
    }
    if (!noticeId) {
      var compositeEntry = getCompositeEntry(noticeIndex, composite);
      if (compositeEntry) {
        if (compositeEntry.persisted) {
          if (shouldRewriteNotice(compositeEntry, record)) {
            batch.updates.push({ target: target, row: compositeEntry.row, entry: entry });
          } else if (isNoticeContentUnavailable(compositeEntry.content)) {
            addError(res, recordKey, "內文仍無法讀取");
          } else {
            addSkipped(res, recordKey);
          }
        } else {
          batch.dependencies.push({
            key: recordKey,
            tokens: compositeEntry.pendingTokens.slice()
          });
        }
        return;
      }
    }
    var groupKey = target.fileName + "|" + target.sheetName;
    if (!batch.groups[groupKey]) {
      batch.groups[groupKey] = {
        target: target,
        entries: []
      };
    }
    var token = "pending-" + batch.nextToken++;
    entry.key = recordKey;
    entry.token = token;
    batch.groups[groupKey].entries.push(entry);
    reserveRecord(noticeIndex, record, token);
  } catch (err) {
    addError(res, recordKey, err.toString());
  }
}

function shouldRewriteNotice(existingEntry, record) {
  return Boolean(existingEntry && existingEntry.persisted && existingEntry.row) &&
    isNoticeContentUnavailable(existingEntry.content) &&
    !isNoticeContentUnavailable(record.content);
}

function writeGroups(batch, ctx, res, dutyRecipient) {
  Object.keys(batch.groups).forEach(function(key) {
    var group = batch.groups[key];
    var entries = group.entries;
    if (entries.length === 0) return;
    var outcomes;
    try {
      var recipient = getValidDutyRecipient(group.target.sheet, dutyRecipient);
      var rows = getWritableRows(group.target, entries.length, ctx);
      var values = entries.map(function(entry) {
        var record = entry.record;
        return [record.sender, record.subject, record.content, recipient];
      });
      outcomes = writeRows(group.target.sheet, rows, values, entries);
    } catch (err) {
      outcomes = entries.map(function() {
        return { success: false, error: err.toString() };
      });
    }
    entries.forEach(function(entry, index) {
      var outcome = outcomes[index];
      batch.tokenResults[entry.token] = Boolean(outcome && outcome.success);
      if (outcome && outcome.success) {
        res.success++;
        pushKey(res.writtenKeys, entry.key);
        pushKey(res.handledKeys, entry.key);
      } else {
        addError(res, entry.key, outcome && outcome.error || "Write failed");
      }
    });
  });
}

function writeContentUpdates(batch, res) {
  batch.updates.forEach(function(update) {
    try {
      update.target.sheet.getRange(update.row, 5).setValue(update.entry.record.content);
      res.success++;
      pushKey(res.writtenKeys, update.entry.key);
      pushKey(res.handledKeys, update.entry.key);
    } catch (err) {
      addError(res, update.entry.key, err.toString());
    }
  });
}

function resolvePendingRecords(batch, res) {
  batch.dependencies.forEach(function(dependency) {
    var handled = dependency.tokens.some(function(token) {
      return batch.tokenResults[token] === true;
    });
    if (handled) {
      addSkipped(res, dependency.key);
    } else {
      addError(res, dependency.key, "Related record was not persisted");
    }
  });
}

function addSkipped(res, key) {
  res.skipped++;
  pushKey(res.skippedKeys, key);
  pushKey(res.handledKeys, key);
}

function addError(res, key, message) {
  res.errors++;
  pushKey(res.errorKeys, key);
  if (message) res.messages.push(message);
}

function pushKey(keys, key) {
  if (keys.indexOf(key) === -1) keys.push(key);
}

function getCurrentDutyRecipient() {
  var context = getDutyRecipientContext();
  var cache = null;
  try {
    cache = CacheService.getScriptCache();
    var cachedRecipient = cache.get(DUTY_RECIPIENT_CACHE_PREFIX + context.slotKey);
    if (cachedRecipient) {
      return { slotKey: context.slotKey, recipient: cachedRecipient };
    }
  } catch (err) {
    console.log("Duty recipient cache read failed: " + err.toString());
  }

  try {
    var raw = DriveApp.getFileById("1QHTnDgmrk779hU7lQXbdB6myKisbPXcP")
      .getBlob()
      .getDataAsString("UTF-8");
    var board = JSON.parse(raw);
    var recipient = findDutyRecipient(board, context.rocDate, context.hour);
    if (recipient && cache) {
      try {
        cache.put(DUTY_RECIPIENT_CACHE_PREFIX + context.slotKey, recipient, 300);
      } catch (cacheErr) {
        console.log("Duty recipient cache save failed: " + cacheErr.toString());
      }
    }
    return { slotKey: context.slotKey, recipient: recipient };
  } catch (err) {
    return { slotKey: context.slotKey, recipient: "" };
  }
}

function getDutyRecipientContext() {
  var timeZone = "Asia/Taipei";
  var now = new Date();
  var hour = parseInt(Utilities.formatDate(now, timeZone, "H"), 10);
  var fireDay = new Date(now.getTime() - (hour < 8 ? 24 * 60 * 60 * 1000 : 0));
  var dateKey = Utilities.formatDate(fireDay, timeZone, "yyyyMMdd");
  var rocDate = String(parseInt(dateKey.slice(0, 4), 10) - 1911) + dateKey.slice(4);
  return {
    hour: hour,
    rocDate: rocDate,
    slotKey: rocDate + "|" + hour
  };
}

function findDutyRecipient(board, rocDate, hour) {
  var days = Array.isArray(board.days) ? board.days : [];
  for (var dayIndex = 0; dayIndex < days.length; dayIndex++) {
    var day = days[dayIndex];
    if (String(day.roc_date) !== rocDate) continue;
    var slots = Array.isArray(day.slots) ? day.slots : [];
    for (var slotIndex = 0; slotIndex < slots.length; slotIndex++) {
      var slot = slots[slotIndex];
      if (Number(slot.start_hour) !== hour) continue;
      var names = Array.isArray(slot.names) ? slot.names : [];
      var dutyNos = Array.isArray(slot.duty_nos) ? slot.duty_nos : [];
      if (names.length !== 1 || dutyNos.length !== 1) return "";
      var fullName = norm(names[0]);
      if (fullName.length < 2) return "";
      var roles = Array.isArray(slot.roles) && slot.roles.length === names.length ? slot.roles : [];
      var role = norm(roles[0]);
      if (role === "小隊長") return fullName.charAt(0) + "小";
      if (role === "分隊長") return fullName.charAt(0) + "分";
      return fullName;
    }
  }
  return "";
}

function getValidDutyRecipient(sheet, recipient) {
  recipient = norm(recipient);
  if (!recipient) return "";
  try {
    var rule = sheet.getRange(3, 6).getDataValidation();
    var criteria = rule ? rule.getCriteriaValues() : [];
    var sourceRange = criteria[0];
    if (!sourceRange || typeof sourceRange.getDisplayValues !== "function") return "";
    var names = sourceRange.getDisplayValues();
    var candidates = [recipient, recipient.slice(1)];
    for (var candidateIndex = 0; candidateIndex < candidates.length; candidateIndex++) {
      if (!candidates[candidateIndex]) continue;
      for (var index = 0; index < names.length; index++) {
        if (norm(names[index][0]) === candidates[candidateIndex]) return candidates[candidateIndex];
      }
    }
  } catch (err) {
    return "";
  }
  return "";
}

function newContext() {
  return {
    props: PropertiesService.getScriptProperties(),
    allowCreate: false,
    ssCache: {},
    sheetCache: {},
    noticeCache: {},
    rowCache: {}
  };
}

function getMonthlySpreadsheetLink(data) {
  var year = data.year;
  var month = data.month;
  if (typeof year !== "number" || year !== Math.floor(year) || year < 2011 || year > 2910
      || typeof month !== "number" || month !== Math.floor(month) || month < 1 || month > 12) {
    return { status: "error", error: "invalid_month" };
  }
  try {
    var rocYear = year - 1911;
    var root = DriveApp.getFolderById(NOTICE_WORKBOOK_ROOT_FOLDER_ID);
    var folders = root.getFoldersByName(rocYear + "年");
    var folder = folders.hasNext() ? folders.next() : null;
    if (folders.hasNext()) return { status: "error", error: "ambiguous_spreadsheet" };
    if (!folder) return { status: "error", error: "spreadsheet_not_found" };
    var files = folder.getFilesByName(rocYear + "年" + month + "月電子通報");
    var file = files.hasNext() ? files.next() : null;
    if (files.hasNext()) return { status: "error", error: "ambiguous_spreadsheet" };
    if (!file || file.isTrashed()) return { status: "error", error: "spreadsheet_not_found" };
    if (file.getMimeType() !== MimeType.GOOGLE_SHEETS) {
      return { status: "error", error: "invalid_spreadsheet" };
    }
    var id = file.getId();
    if (typeof id !== "string" || !/^[A-Za-z0-9_-]{20,128}$/.test(id)) {
      return { status: "error", error: "invalid_spreadsheet" };
    }
    return {
      status: "success", year: year, month: month, spreadsheetId: id,
      spreadsheetUrl: "https://docs.google.com/spreadsheets/d/" + id + "/edit"
    };
  } catch (_lookupError) {
    return { status: "error", error: "lookup_failed" };
  }
}

function getTarget(dateText, ctx) {
  var p = dateText.split("-");
  var fileName = p[0] + "年" + parseInt(p[1], 10) + "月電子通報";
  var sheetName = parseInt(p[2], 10) + "號";
  var key = fileName + "|" + sheetName;
  if (ctx.sheetCache[key]) return ctx.sheetCache[key];
  var ss = getSpreadsheet(fileName, ctx);
  if (!ss) return { error: "找不到檔案：" + fileName, fileName: fileName, sheetName: sheetName };
  var sheet = ss.getSheetByName(sheetName);
  if (!sheet) return { error: "檔案存在但找不到分頁：" + sheetName, fileName: fileName, sheetName: sheetName };
  ctx.sheetCache[key] = {
    sheet: sheet,
    fileName: fileName,
    sheetName: sheetName,
    date: norm(dateText)
  };
  return ctx.sheetCache[key];
}
