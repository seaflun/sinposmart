const BOARD_FILE_NAME = 'sinposmart-duty-board.json';
const TAIPEI_TIME_ZONE = 'Asia/Taipei';

function doGet() {
  const board = loadBoard_();
  const model = selectDutySlots_(board);
  const current = model.current ? displaySlot_(model.current) : '目前沒有可顯示的值班資料';
  const next = model.next ? displaySlot_(model.next) : '下一時段尚無資料';
  const updatedAt = board.updated_at || '目前沒有更新時間';
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
  try {
    const folderId = String(PropertiesService.getScriptProperties().getProperty('DUTY_BOARD_FOLDER_ID') || '');
    if (!folderId) {
      return {};
    }
    const files = DriveApp.getFolderById(folderId).getFilesByName(BOARD_FILE_NAME);
    if (!files.hasNext()) {
      return {};
    }
    return JSON.parse(files.next().getBlob().getDataAsString() || '{}');
  } catch (_error) {
    return {};
  }
}

function selectDutySlots_(board) {
  const now = taipeiNow_();
  const timeline = [];
  const days = Array.isArray(board.days) ? board.days : [];
  days.forEach(day => {
    const dayNumber = rocDayNumber_(day && day.roc_date);
    if (dayNumber === null || !Array.isArray(day.slots)) {
      return;
    }
    day.slots.forEach(slot => {
      if (!slot || !Number.isInteger(slot.start_hour) || !Number.isInteger(slot.end_hour)) {
        return;
      }
      const start = dayNumber * 24 + businessHour_(slot.start_hour);
      let end = dayNumber * 24 + businessHour_(slot.end_hour);
      if (end <= start) {
        end += 24;
      }
      timeline.push({slot: slot, start: start, end: end});
    });
  });
  timeline.sort((left, right) => left.start - right.start);
  const currentIndex = timeline.findIndex(item => item.start <= now && now < item.end);
  if (currentIndex < 0) {
    return {current: null, next: timeline.find(item => item.start > now) || null};
  }
  return {
    current: timeline[currentIndex].slot,
    next: timeline[currentIndex + 1] ? timeline[currentIndex + 1].slot : null,
  };
}

function taipeiNow_() {
  const parts = Utilities.formatDate(new Date(), TAIPEI_TIME_ZONE, 'yyyy,M,d,H').split(',').map(Number);
  return Math.floor(Date.UTC(parts[0], parts[1] - 1, parts[2]) / 86400000) * 24 + parts[3];
}

function rocDayNumber_(rocDate) {
  const value = String(rocDate || '');
  if (!/^\d{7}$/.test(value)) {
    return null;
  }
  const year = Number(value.slice(0, 3)) + 1911;
  const month = Number(value.slice(3, 5));
  const day = Number(value.slice(5, 7));
  const date = new Date(Date.UTC(year, month - 1, day));
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) {
    return null;
  }
  return Math.floor(date.getTime() / 86400000);
}

function businessHour_(hour) {
  return hour < 8 ? hour + 24 : hour;
}

function displaySlot_(slot) {
  const names = Array.isArray(slot.names) ? slot.names.filter(Boolean) : [];
  const dutyNos = Array.isArray(slot.duty_nos) ? slot.duty_nos.filter(Boolean) : [];
  const people = names.length ? names.join('、') : dutyNos.map(number => '番號 ' + number).join('、');
  return String(slot.slot || '未標示時段') + '：' + (people || '未提供值班人員');
}

function escapeHtml_(value) {
  return String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
}
