// The /ota page: asks /api/ota, writes what it gets as text (docs/OTA.md).
//
// Read-only by construction -- one GET, no controls -- and every value is written with textContent,
// never as markup: the numbers and strings come from a file another process wrote
// (tests/test_ota_api.py pins both). The pure helpers are exported on window.Ota for the node tests.
(function () {
  'use strict';

  const POLL_MS = 5000;
  const DASH = '—';

  // ── pure helpers ──

  const short = d => (typeof d === 'string' && d) ? d.replace(/^sha256:/, '').slice(0, 12) : '';

  function ago(s) {
    if (typeof s !== 'number' || !isFinite(s)) return '';
    s = Math.max(0, s);
    if (s < 120) return Math.floor(s) + ' s';
    if (s < 7200) return Math.floor(s / 60) + ' min';
    return Math.floor(s / 3600) + ' h';
  }

  // '2026-08-07T23:03:53.358Z' -> '2026-08-07 23:03:53 UTC'. The server only lets ISO times with a zone through.
  function when(t) {
    if (typeof t !== 'string' || !t) return '';
    return t.replace('T', ' ').replace(/\.\d+/, '').replace(/Z$/, ' UTC');
  }

  const SLOTS = ['booted', 'staged', 'rollback'];
  const FIELDS = [['Version', 'version', v => v], ['Digest', 'digest', short], ['Built', 'built_at', when]];

  // Rows of the image comparison. A row `differs` when two or more of the images that exist disagree on it:
  // that is what the page highlights, so the eye lands on what an update or a rollback would change.
  function imageRows(os) {
    os = os || {};
    return FIELDS.map(([label, key, show]) => {
      const raw = SLOTS.map(slot => (os[slot] && os[slot][key]) || '');
      const present = raw.filter(v => v);
      const cells = {};
      SLOTS.forEach((slot, i) => { cells[slot] = raw[i] ? show(raw[i]) : ''; });
      return { label, cells, differs: new Set(present).size > 1 };
    });
  }

  // null when all is well; otherwise the banner to show.
  function banner(data) {
    if (!data || typeof data !== 'object') return { kind: 'invalid', text: 'No answer from the dashboard server.' };
    const msg = typeof data.message === 'string' ? data.message : '';
    switch (data.status) {
      case 'ok': return null;
      case 'waiting': return { kind: 'waiting', text: msg || 'Waiting for the host to write the status file.' };
      case 'invalid': return { kind: 'invalid', text: msg || 'The status file cannot be used.' };
      case 'stale':
        return { kind: 'stale', text: typeof data.age_s === 'number'
          ? 'The status file is ' + ago(data.age_s) + ' old. Showing the last state the host wrote.'
          : (msg || 'The status file is out of date.') + ' Showing the last state the host wrote.' };
      default: return { kind: 'invalid', text: 'Unexpected answer from the dashboard server.' };
    }
  }

  // The "next boot" line. It warns when the next boot is not the image that is running.
  function nextBoot(nb) {
    if (!nb || !nb.version) return { warn: false, text: '' };
    if (nb.source === 'rollback') {
      return { warn: true, text: 'Next boot: ' + nb.version + ' — a rollback is queued, so a reboot switches to this image.' };
    }
    if (nb.source === 'staged') {
      return { warn: true, text: 'Next boot: ' + nb.version + ' — an update is staged, so a reboot installs it.' };
    }
    return { warn: false, text: 'Next boot: ' + nb.version + ' — the image that is running.' };
  }

  const serviceClass = s => s === 'active' ? 'ok' : s === 'failed' ? 'bad'
    : ['inactive', 'activating', 'deactivating', 'reloading', 'maintenance'].includes(s) ? 'warn' : 'dim';
  const selinuxClass = m => m === 'enforcing' ? 'ok' : m === 'permissive' ? 'warn' : m === 'disabled' ? 'bad' : 'dim';
  const ntpClass = v => v === true ? 'ok' : v === false ? 'bad' : 'dim';
  const diskClass = p => typeof p !== 'number' ? 'dim' : p >= 90 ? 'bad' : p >= 75 ? 'warn' : 'ok';

  window.Ota = { short, ago, when, imageRows, banner, nextBoot, serviceClass, selinuxClass, ntpClass, diskClass };

  // ── the page ──

  if (typeof document === 'undefined' || !document.getElementById('ota-root')) return;

  const $ = id => document.getElementById(id);

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }

  function table(head, rows) {
    const t = el('table', 'ota-table');
    const tr = el('tr');
    head.forEach(h => tr.appendChild(el('th', '', h)));
    t.appendChild(el('thead')).appendChild(tr);
    const body = el('tbody');
    rows.forEach(r => {
      const row = el('tr', r.cls || '');
      r.cells.forEach(c => row.appendChild(c instanceof Node ? c : el('td', '', c || DASH)));
      body.appendChild(row);
    });
    t.appendChild(body);
    return t;
  }

  function fact(label, value, cls) {
    const f = el('div', 'ota-fact');
    f.appendChild(el('span', 'k', label));
    f.appendChild(el('span', 'v ' + (cls || ''), value || DASH));
    return f;
  }

  function fill(id, ...children) { $(id).replaceChildren(...children); }

  function renderOs(os, nb) {
    const n = nextBoot(nb);
    const nextEl = $('ota-next');
    nextEl.textContent = n.text;
    nextEl.className = 'ota-next' + (n.text ? (n.warn ? ' warn' : ' ok') : '');
    nextEl.hidden = !n.text;
    const rows = imageRows(os).map(r => ({
      cls: r.differs ? 'diff' : '',
      cells: [el('th', '', r.label), r.cells.booted, r.cells.staged, r.cells.rollback],
    }));
    const queued = os && os.rollback_queued;
    fill('ota-images', table(['', 'Running', 'Staged', 'Rollback' + (queued ? ' (queued)' : '')], rows));
    fill('ota-os-facts', fact('Kernel', os && os.kernel), fact('Running since', when(os && os.booted_at)));
  }

  function renderComponents(list) {
    if (!list || !list.length) { fill('ota-components', el('p', 'ota-none', 'No components reported.')); return; }
    fill('ota-components', table(['Component', 'Version', 'Transaction', 'Installed'],
      list.map(c => ({ cells: [c.id, c.version, short(c.transaction_digest), when(c.installed_at)] }))));
  }

  function renderServices(list) {
    if (!list || !list.length) { fill('ota-services', el('p', 'ota-none', 'No services reported.')); return; }
    fill('ota-services', table(['Service', 'State', 'Since', 'Restarts'], list.map(s => {
      const name = el('td');
      name.appendChild(el('span', 'ota-dot ' + serviceClass(s.active_state)));
      name.appendChild(document.createTextNode(s.name));
      const state = s.active_state + (s.sub_state ? ' (' + s.sub_state + ')' : '');
      return { cells: [name, state, when(s.since), s.restarts === null || s.restarts === undefined ? '' : String(s.restarts)] };
    })));
  }

  function renderHealth(h) {
    h = h || {};
    const ntp = h.ntp_synced === true ? 'synchronized' : h.ntp_synced === false ? 'not synchronized' : 'unknown';
    const used = typeof h.var_used_pct === 'number' ? h.var_used_pct.toFixed(1) + ' % used' : '';
    const free = typeof h.var_free_bytes === 'number' ? (h.var_free_bytes / 1e9).toFixed(1) + ' GB free' : '';
    fill('ota-health',
      fact('SELinux', h.selinux, selinuxClass(h.selinux)),
      fact('Clock (NTP)', ntp, ntpClass(h.ntp_synced)),
      fact('/var', [used, free].filter(Boolean).join(' · '), diskClass(h.var_used_pct)));
  }

  function render(data) {
    const b = banner(data);
    const bar = $('ota-banner');
    bar.hidden = !b;
    bar.className = 'card ota-banner' + (b ? ' ' + b.kind : '');
    bar.textContent = b ? b.text : '';
    const show = !!data && (data.status === 'ok' || data.status === 'stale');
    $('ota-main').hidden = !show;
    $('ota-age').textContent = show && typeof data.age_s === 'number' ? 'written ' + ago(data.age_s) + ' ago' : '';
    if (!show) return;
    renderOs(data.os, data.next_boot);
    renderComponents(data.components);
    renderServices(data.services);
    renderHealth(data.health);
  }

  async function poll() {
    if (document.hidden) return;
    try {
      const r = await fetch('/api/ota', { cache: 'no-store' });
      render(r.ok ? await r.json() : null);
    } catch (e) {
      render(null);
    }
  }

  poll();
  setInterval(poll, POLL_MS);
})();
