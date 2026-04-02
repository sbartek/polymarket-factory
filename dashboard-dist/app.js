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

async function loadJson(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`Failed to load ${path}`);
  return res.json();
}

function renderOverview(overview, manifest) {
  const cards = [
    ['Active exposure', `${fmtNumber(overview.open_exposure_active)} USDC`, `${fmtInt(overview.open_position_count_active)} active open positions`],
    ['Legacy exposure', `${fmtNumber(overview.open_exposure_legacy)} USDC`, `${fmtInt(overview.open_position_count_legacy)} paused / legacy open positions`],
    ['Active strategies', fmtInt(overview.active_strategy_count), 'Current active stack size'],
    ['Current experiments', fmtInt(overview.active_experiment_count), 'Counts active + review_due threads'],
    ['Latest run duration', fmtDuration(overview.latest_run_duration_seconds), fmtDate(overview.latest_run_started_at)],
  ];

  document.getElementById('overview-cards').innerHTML = cards.map(([label, value, sub]) => `
    <article class="kpi-card">
      <div class="kpi-label">${label}</div>
      <div class="kpi-value">${value}</div>
      <div class="kpi-sub">${sub}</div>
    </article>
  `).join('');

  document.getElementById('snapshot-meta').textContent = `Snapshot generated ${fmtDate(manifest.generated_at)} · commit ${manifest.git_commit || 'unknown'}`;
  const age = ageLabel(manifest.generated_at);
  const ageEl = document.getElementById('snapshot-age');
  ageEl.className = age.cls;
  ageEl.textContent = age.text;

  const runEl = document.getElementById('run-status-pill');
  runEl.className = pillClass(overview.latest_run_status);
  runEl.textContent = `run: ${overview.latest_run_status}`;

  const alerts = overview.alerts || [];
  const section = document.getElementById('alerts-section');
  const list = document.getElementById('alerts-list');
  if (!alerts.length && !(manifest.warnings || []).length) {
    section.classList.add('hidden');
  } else {
    section.classList.remove('hidden');
    const merged = [...alerts, ...(manifest.warnings || []).map((message) => ({ level: 'warning', message }))];
    list.innerHTML = merged.map((a) => `<div class="alert ${a.level === 'error' ? 'error' : a.level === 'info' ? 'info' : ''}">${a.message}</div>`).join('');
  }
}

function renderStrategies(strategies) {
  const body = document.getElementById('strategies-body');
  body.innerHTML = strategies.map((s) => `
    <tr>
      <td>
        <div class="strategy-name">${s.strategy_name}</div>
        ${s.warnings?.length ? `<div class="muted">${s.warnings.join(' ')}</div>` : ''}
      </td>
      <td><span class="${pillClass(s.status)}">${s.status}</span></td>
      <td>${fmtNumber(s.open_exposure)} USDC</td>
      <td>${fmtInt(s.open_positions)}</td>
      <td>${fmtInt(s.recent_decisions_count)}</td>
    </tr>
  `).join('');

  const active = strategies.filter((s) => s.status === 'active').length;
  const paused = strategies.filter((s) => s.status === 'paused').length;
  document.getElementById('strategy-summary').textContent = `${active} active · ${paused} paused`;
}

function renderRuns(runs) {
  const body = document.getElementById('runs-body');
  body.innerHTML = runs.map((r) => `
    <tr>
      <td>${fmtDate(r.started_at)}</td>
      <td><span class="${pillClass(r.status)}">${r.status}</span></td>
      <td>${fmtDuration(r.duration_seconds)}</td>
      <td>${fmtInt(r.strategies_checked)}</td>
      <td>${fmtInt(r.signals_generated)}</td>
      <td>${fmtInt(r.decisions_logged)}</td>
    </tr>
  `).join('');
}

function renderExperiments(experiments) {
  const current = experiments.filter((e) => ['active', 'review_due'].includes(e.status));
  const list = document.getElementById('experiments-list');
  list.innerHTML = current.map((e) => `
    <article class="experiment-card">
      <div class="panel-header">
        <div>
          <h3>${e.title}</h3>
          <div class="muted code">${e.experiment_id}</div>
        </div>
        <span class="${pillClass(e.status)}">${e.status}</span>
      </div>
      <p>${e.summary || e.hypothesis || 'No summary yet.'}</p>
      <div class="card-meta">
        <span class="pill pill-info">${e.scope_type}</span>
        <span class="pill pill-neutral">${e.scope_label}</span>
        ${e.review_due ? `<span class="pill pill-warning">review due ${e.review_due}</span>` : ''}
      </div>
    </article>
  `).join('') || '<div class="muted">No current experiments.</div>';

  document.getElementById('experiment-summary').textContent = `${current.length} current threads`;

  const groups = current.reduce((acc, exp) => {
    (acc[exp.scope_type] ||= []).push(exp);
    return acc;
  }, {});
  document.getElementById('scope-groups').innerHTML = Object.entries(groups).map(([scope, items]) => `
    <div class="scope-card">
      <div class="panel-header">
        <h3>${scope}</h3>
        <span class="muted">${items.length}</span>
      </div>
      <div class="stack">
        ${items.map((e) => `<div><strong>${e.title}</strong><div class="muted">${e.scope_label}</div></div>`).join('')}
      </div>
    </div>
  `).join('') || '<div class="muted">No active scope groups.</div>';
}

async function main() {
  try {
    const [manifest, overview, strategies, runs, experiments] = await Promise.all([
      loadJson('../dashboard-data/manifest.json'),
      loadJson('../dashboard-data/overview.json'),
      loadJson('../dashboard-data/strategies.json'),
      loadJson('../dashboard-data/runs.json'),
      loadJson('../dashboard-data/experiments.json'),
    ]);

    renderOverview(overview, manifest);
    renderStrategies(strategies);
    renderRuns(runs.slice(0, 10));
    renderExperiments(experiments);
  } catch (err) {
    document.body.innerHTML = `<div class="shell"><div class="panel"><h1>Dashboard failed to load</h1><p>${err.message}</p></div></div>`;
  }
}

main();
