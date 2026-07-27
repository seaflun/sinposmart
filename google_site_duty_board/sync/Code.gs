const BOARD_FILE_NAME = 'sinposmart-duty-board.json';

function doGet() {
  return json_({ok: false, error: 'write_only'});
}

function doPost(e) {
  try {
    const request = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    const properties = PropertiesService.getScriptProperties();
    const configuredKey = String(properties.getProperty('DUTY_BOARD_SYNC_KEY') || '');
    const requestKey = String(request.sync_key || '');
    if (!configuredKey || !requestKey || requestKey !== configuredKey) {
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
  if (!payload || payload.schema_version !== 1 || !Array.isArray(payload.days) ||
      !payload.days.length || typeof payload.content_hash !== 'string' ||
      !/^[a-f0-9]{64}$/.test(payload.content_hash)) {
    throw new Error('invalid payload');
  }
  payload.days.forEach(day => {
    if (!day || !/^\d{7}$/.test(String(day.roc_date || '')) || !Array.isArray(day.slots)) {
      throw new Error('invalid day');
    }
    day.slots.forEach(slot => {
      if (!slot || typeof slot.slot !== 'string' || !Number.isInteger(slot.start_hour) ||
          !Number.isInteger(slot.end_hour) || slot.start_hour < 0 || slot.start_hour > 24 ||
          slot.end_hour < 0 || slot.end_hour > 24 || !Array.isArray(slot.duty_nos) ||
          !Array.isArray(slot.names) || !slot.duty_nos.every(value => typeof value === 'string') ||
          !slot.names.every(value => typeof value === 'string')) {
        throw new Error('invalid slot');
      }
    });
  });
  return payload;
}

function getBoardFile_(properties) {
  const folderId = String(properties.getProperty('DUTY_BOARD_FOLDER_ID') || '');
  if (!folderId) {
    throw new Error('missing folder');
  }
  const folder = DriveApp.getFolderById(folderId);
  const files = folder.getFilesByName(BOARD_FILE_NAME);
  return files.hasNext() ? files.next() : folder.createFile(BOARD_FILE_NAME, '{}', MimeType.PLAIN_TEXT);
}

function stableJson_(value) {
  if (value === null || typeof value === 'boolean' || typeof value === 'number' || typeof value === 'string') {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return '[' + value.map(stableJson_).join(',') + ']';
  }
  if (value && typeof value === 'object') {
    return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + stableJson_(value[key])).join(',') + '}';
  }
  throw new Error('invalid canonical value');
}

function sha256_(value) {
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, value, Utilities.Charset.UTF_8)
    .map(byte => ('0' + ((byte + 256) % 256).toString(16)).slice(-2))
    .join('');
}

function json_(value) {
  return ContentService.createTextOutput(JSON.stringify(value)).setMimeType(ContentService.MimeType.JSON);
}
