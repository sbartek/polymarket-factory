const fmtNumber = (value, digits = 2) => {
  if (value === null || value === undefined) return '—';
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(value);
};

const fmtInt = (value) => {
  if (value === null || value === undefined) return '—';
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(value);
};

const fmtDate = (value) => {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
};

const fmtDuration = (seconds) => {
  if (seconds === null || seconds === undefined) return '—';
  if (seconds < 60) return `${seconds}s`;
  const min = Math.floor(seconds / 60);
  const sec = seconds % 60;
  return `${min}m ${sec}s`;
};

const fmtBytes = (value) => {
  if (value === null || value === undefined) return '—';
  const units = ['B', 'KB', 'MB', 'GB'];
  let size = Number(value);
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
};

const pillClass = (status) => {
  const s = (status || '').toLowerCase();
  if (s === 'ok' || s === 'active' || s === 'completed') return 'pill pill-ok';
  if (s === 'warning' || s === 'review_due' || s === 'paused') return 'pill pill-warning';
  if (s === 'error') return 'pill pill-error';
  return 'pill pill-neutral';
};

const ageLabel = (generatedAt) => {
  const t = new Date(generatedAt).getTime();
  if (Number.isNaN(t)) return { text: 'age unknown', cls: 'pill pill-neutral' };
  const mins = Math.round((Date.now() - t) / 60000);
  if (mins <= 90) return { text: `fresh · ${mins}m old`, cls: 'pill pill-ok' };
  if (mins <= 360) return { text: `stale · ${mins}m old`, cls: 'pill pill-warning' };
  return { text: `old · ${mins}m old`, cls: 'pill pill-error' };
};

function cleanSummary(text) {
  if (!text) return '—';
  let cleaned = text.replace(/`/g, '').replace(/^-\s*/gm, '').replace(/\s+/g, ' ').trim();
  if (cleaned.length > 220) cleaned = `${cleaned.slice(0, 217)}...`;
  return cleaned;
}

async function loadJson(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`Failed to load ${path}`);
  return res.json();
}

const dataPath = (name) => {
  const bundled = new URLSearchParams(window.location.search).get('bundled');
  const isLocal = location.hostname === 'localhost' || location.hostname === '127.0.0.1';
  return (bundled === '1' || !isLocal) ? `./data/${name}.json` : `../dashboard-data/${name}.json`;
};

async function loadSnapshot() {
  const [manifest, overview, strategies, runs, experiments, executionChecks, evaluation, benchmarks, storage, approvals, runHistory] = await Promise.all([
    loadJson(dataPath('manifest')),
    loadJson(dataPath('overview')),
    loadJson(dataPath('strategies')),
    loadJson(dataPath('runs')),
    loadJson(dataPath('experiments')),
    loadJson(dataPath('execution-checks')).catch(() => []),
    loadJson(dataPath('evaluation')).catch(() => null),
    loadJson(dataPath('benchmarks')).catch(() => null),
    loadJson(dataPath('storage')).catch(() => null),
    loadJson(dataPath('approvals')).catch(() => []),
    loadJson(dataPath('run-history')).catch(() => null),
  ]);
  return { manifest, overview, strategies, runs, experiments, executionChecks, evaluation, benchmarks, storage, approvals, runHistory };
}

function renderChrome(snapshot, pageTitle) {
  document.getElementById('page-title').textContent = pageTitle;
  document.getElementById('snapshot-meta').textContent = `Snapshot generated ${fmtDate(snapshot.manifest.generated_at)} · commit ${snapshot.manifest.git_commit || 'unknown'}`;
  const age = ageLabel(snapshot.manifest.generated_at);
  const ageEl = document.getElementById('snapshot-age');
  ageEl.className = age.cls;
  ageEl.textContent = age.text;
  const runEl = document.getElementById('run-status-pill');
  runEl.className = pillClass(snapshot.overview.latest_run_status);
  runEl.textContent = `run: ${snapshot.overview.latest_run_status}`;
}

function renderAlerts(snapshot) {
  const alerts = [...(snapshot.overview.alerts || []), ...(snapshot.manifest.warnings || []).map((message) => ({ level: 'warning', message }))];
  const section = document.getElementById('alerts-section');
  const list = document.getElementById('alerts-list');
  if (!section || !list) return;
  if (!alerts.length) {
    section.classList.add('hidden');
    return;
  }
  section.classList.remove('hidden');
  list.innerHTML = alerts.map((a) => `<div class="alert ${a.level === 'error' ? 'error' : a.level === 'info' ? 'info' : ''}">${a.message}</div>`).join('');
}

function renderNav(current) {
  document.querySelectorAll('[data-nav]').forEach((el) => {
    if (el.dataset.nav === current) el.classList.add('nav-active');
  });
}

function uniqueValues(items, key) {
  return [...new Set(items.map((item) => item[key]).filter(Boolean))].sort();
}

window.Dashboard = {
  fmtNumber, fmtInt, fmtDate, fmtDuration, fmtBytes, pillClass, cleanSummary,
  loadJson, loadSnapshot, renderChrome, renderAlerts, renderNav, uniqueValues, dataPath,
};
