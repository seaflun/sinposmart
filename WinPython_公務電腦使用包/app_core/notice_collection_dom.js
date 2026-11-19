/* Metadata and text normalization adapted from SinpoSmart_通報收取/content.js.
 * This bridge never follows a notice subject link or modifies font styles.
 * notice:snapshot is the read-only metadata operation.
 */
return (function (operation, payload, done) {
  const expectedOrigin = 'https://oa.tyfd.gov.tw';
  const expectedAccount = '新坡分隊/新坡分隊公務信箱(公務信箱)';

  function identity() {
    const accounts = document.querySelectorAll('.user-menu .user-details');
    const account = accounts.length === 1
      ? Array.from(accounts[0].childNodes).filter(n => n.nodeType === 3)
        .map(n => n.textContent).join('').trim() : '';
    return { origin: window.location.origin, account, accountCount: accounts.length,
      sessionExpired: window.location.pathname === '/sess_exceed.php',
      login: !!document.querySelector('#login_name') && !!document.querySelector('input[type="password"]') };
  }

  function cleanText(content) {
    return String(content || '').replace(/\r\n?/g, '\n').replace(/\t|\u3000/g, ' ')
      .split('\n').map(line => line.replace(/[ ]{2,}/g, ' ').trim())
      .filter(line => line !== '').join('\n').trim();
  }

  function dateCell(row) {
    return Array.from(row.querySelectorAll('td')).find(td =>
      td.getAttribute('rowspan') === '2' && /^\d{3}-\d{2}-\d{2}$/.test(td.innerText.trim()));
  }

  function recordFromRow(row) {
    const date = dateCell(row);
    if (!date) return null;
    let detail = row.nextElementSibling;
    while (detail && detail.tagName === 'TR' && !dateCell(detail) && !detail.querySelector('iframe')) {
      detail = detail.nextElementSibling;
    }
    const links = [row, detail].filter(Boolean)
      .flatMap(tr => Array.from(tr.querySelectorAll('a[href*="bulletin_read&id="]')));
    const match = links.length && String(links[0].getAttribute('href')).match(/bulletin_read&id=(\d+)/);
    const iframe = detail && detail.querySelector('iframe');
    if (!match || !iframe) return null;
    const noticeId = match[1];
    const cells = row.querySelectorAll('td');
    const subject = cells.length < 3 ? '未知主旨' : cells[2].innerText
      .replace(/公告對象.*/g, '').replace(/download/gi, '').replace(/電子通報|一般信件/g, '')
      .replace(/類別：.*/g, '').replace(/\n/g, ' ').trim() || '未知主旨';
    const senderMatch = `${row.innerText} ${detail.innerText}`.match(/(?:發布者|公告人員|通報人員)\s*[:：]\s*([^ \n\t\r]+)/);
    let sender = senderMatch ? senderMatch[1].trim() : '未標示';
    if (sender.includes('/')) sender = sender.split('/').pop();
    sender = sender.replace(/^(.*?(?:科|室|隊|組|局|中心|所))/, '$1 ');
    const publisherMatch = `${row.innerText}\n${detail.innerText}`.match(/(?:發布者|公告人員|通報人員)\s*[:：][ \t]*([^\n\t\r]+)/);
    const publisher = publisherMatch ? publisherMatch[1].trim().slice(0, 240) : '';
    const weight = links[0].style?.fontWeight || '';
    const isUnread = weight === 'bold' || Number(weight) >= 600 ? true
      : weight === 'normal' || (weight !== '' && Number(weight) > 0 && Number(weight) <= 400) ? false : null;
    return { key: noticeId, noticeId, date: date.innerText.trim(), subject, sender, publisher,
      isUnread, contentUrl: iframe.src || iframe.getAttribute('src') || '' };
  }

  if (operation === 'snapshot') {
    const state = identity();
    const summary = Array.from(document.querySelectorAll('p')).map(e => e.innerText.trim())
      .map(text => text.match(/^第\s*(\d+)\s*\/\s*(\d+)\s*頁\s*共\s*(\d+)\s*筆$/)).find(Boolean);
    const rows = Array.from(document.querySelectorAll('tr')).filter(row => dateCell(row));
    const pagers = Array.from(document.querySelectorAll('a[title="第一頁"],a[title="上一頁"],a[title="下一頁"],a[title="最末頁"]'));
    const query = new URLSearchParams(location.hash.split('?').slice(1).join('?'));
    const readFilter = Number(query.get('is_read'));
    const pagerText = pagers.map(link => link.getAttribute('onclick') || link.getAttribute('href') || '');
    const filterConfirmed = query.has('is_read') && [0, 2].includes(readFilter) && pagers.length > 0
      && pagerText.every(text => new RegExp('(?:[&?])is_read=' + readFilter + '(?:[&\'";)]|$)').test(text));
    const dateConfirmed = ['start_date', 'end_date'].every(name => {
      const value = query.get(name);
      return value && /^\d{3}-\d{2}-\d{2}$/.test(value)
        && document.querySelector('input#' + name)?.value === value
        && pagerText.every(text => text.includes(name + '=' + value));
    });
    return { ...state, filtered: filterConfirmed, readFilter,
      dateFrom: dateConfirmed ? query.get('start_date') : '', dateTo: dateConfirmed ? query.get('end_date') : '',
      page: summary ? Number(summary[1]) : null, pages: summary ? Number(summary[2]) : null,
      total: summary ? Number(summary[3]) : null, dateRows: rows.length,
      records: rows.map(recordFromRow).filter(Boolean),
      ajaxActive: window.jQuery ? window.jQuery.active : 0,
      loading: document.body.innerText.includes('載入中，請稍候') };
  }

  const state = identity();
  if (state.origin !== expectedOrigin || state.accountCount !== 1 || state.account !== expectedAccount || state.login) {
    done({ ok: false, login: state.login });
    return;
  }
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 15000);
  fetch(payload, { method: 'GET', credentials: 'include', cache: 'no-store', signal: controller.signal })
    .then(async response => {
      const finalUrl = new URL(response.url);
      const html = await response.text();
      const parsed = new DOMParser().parseFromString(html, 'text/html');
      const login = /\/(?:login(?:_main)?|sess_exceed)\.php$/.test(finalUrl.pathname) || !!parsed.querySelector('#login_name');
      if (!response.ok || finalUrl.origin !== expectedOrigin || login) {
        done({ ok: false, login });
        return;
      }
      if (operation === 'mark') {
        done({ ok: true });
        return;
      }
      const requested = new URL(payload);
      if (finalUrl.pathname !== requested.pathname || finalUrl.searchParams.get('id') !== requested.searchParams.get('id')) {
        done({ ok: false });
        return;
      }
      if (operation === 'publication') {
        const frame = parsed.querySelector('.knowledgeContent iframe#content');
        const id = frame && new URL(frame.getAttribute('src'), expectedOrigin).searchParams.get('id');
        const times = Array.from(parsed.querySelectorAll('.knowledge span.time'))
          .map(node => node.textContent.trim().match(/^(\d{3}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*~/)).filter(Boolean);
        done(times.length === 1 && id === requested.searchParams.get('id')
          ? { ok: true, noticeId: id, publishedAt: times[0][1] } : { ok: false });
        return;
      }
      const target = parsed.querySelector('div[style*="word-break"]');
      if (!target) {
        done({ ok: false });
        return;
      }
      target.querySelectorAll('script,style,noscript').forEach(node => node.remove());
      target.querySelectorAll('br').forEach(node => node.replaceWith('\n'));
      target.querySelectorAll('p,div,li').forEach(node => node.append('\n'));
      const content = cleanText(target.textContent);
      // Text takes precedence: mixed notices intentionally keep text only.
      if (content) {
        done({ ok: true, content });
        return;
      }
      const nodes = Array.from(target.querySelectorAll('img'));
      if (!nodes.length || nodes.length > 8) {
        done({ ok: false });
        return;
      }
      const images = [];
      for (const node of nodes) {
        const source = new URL(node.getAttribute('src'), payload);
        if (source.origin !== expectedOrigin || source.pathname !== '/download_file.php'
            || source.username || source.password || source.hash) throw new Error('Invalid image source');
        const imageResponse = await fetch(source.href, { credentials: 'include', cache: 'no-store',
          redirect: 'error', signal: controller.signal });
        if (!imageResponse.ok) throw new Error('Image download failed');
        let blob = await imageResponse.blob();
        if (!blob.size || blob.size > 12 * 1024 * 1024) throw new Error('Invalid image');
        const signature = Array.from(new Uint8Array(await blob.slice(0, 8).arrayBuffer()));
        const mimeType = signature.join(',') === '137,80,78,71,13,10,26,10' ? 'image/png' :
          signature.slice(0, 3).join(',') === '255,216,255' ? 'image/jpeg' :
          signature.slice(0, 4).join(',') === '71,73,70,56' ? 'image/gif' : '';
        if (!mimeType) throw new Error('Invalid image format');
        if (blob.type !== mimeType) blob = new Blob([blob], { type: mimeType });
        const bitmap = await createImageBitmap(blob);
        let width = bitmap.width, height = bitmap.height;
        try {
          if (!width || !height || width * height > 40000000) throw new Error('Image dimensions exceed limit');
          if (blob.size > 2 * 1024 * 1024 || width * height > 1000000) {
            const scale = Math.min(1, 1600 / Math.max(width, height), Math.sqrt(1000000 / (width * height)));
            width = Math.max(1, Math.floor(width * scale));
            height = Math.max(1, Math.floor(height * scale));
            const canvas = document.createElement('canvas');
            canvas.width = width; canvas.height = height;
            const context = canvas.getContext('2d');
            context.fillStyle = '#fff'; context.fillRect(0, 0, width, height);
            context.drawImage(bitmap, 0, 0, width, height);
            blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.85));
          }
        } finally { bitmap.close(); }
        if (!blob || blob.size > 2 * 1024 * 1024) throw new Error('Image too large');
        const data = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result).split(',')[1]);
          reader.onerror = reject;
          reader.readAsDataURL(blob);
        });
        images.push({ mimeType: blob.type, data, width, height });
        if (images.reduce((sum, image) => sum + image.data.length, 0) > 8 * 1024 * 1024)
          throw new Error('Image batch too large');
      }
      done({ ok: true, content: '', images });
    })
    .catch(() => done({ ok: false }))
    .finally(() => window.clearTimeout(timer));
})(arguments[0], arguments[1], arguments[arguments.length - 1]);
