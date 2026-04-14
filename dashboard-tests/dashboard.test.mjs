import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { JSDOM } from 'jsdom';
import { afterEach, describe, expect, it, vi } from 'vitest';


const projectRoot = resolve(import.meta.dirname, '..');
const dashboardJs = readFileSync(resolve(projectRoot, 'dashboard', 'dashboard.js'), 'utf8');
const wikiHtml = readFileSync(resolve(projectRoot, 'dashboard', 'wiki.html'), 'utf8');
const wikiInlineScript = [...wikiHtml.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)?.[1] ?? '';


let activeDom;


function bootDashboard(url = 'https://example.test/wiki?bundled=1') {
  activeDom = new JSDOM(wikiHtml.replace(/<script[\s\S]*?<\/script>/g, ''), {
    url,
    runScripts: 'outside-only'
  });
  global.window = activeDom.window;
  global.document = activeDom.window.document;
  global.location = activeDom.window.location;
  activeDom.window.eval(dashboardJs);
  return activeDom.window;
}


async function flushAsyncWork() {
  await Promise.resolve();
  await new Promise((resolvePromise) => setTimeout(resolvePromise, 0));
}


afterEach(() => {
  vi.restoreAllMocks();
  activeDom?.window.close();
  activeDom = undefined;
  delete global.window;
  delete global.document;
  delete global.location;
});


describe('dashboard.js', () => {
  it('exports the helpers the pages consume', () => {
    const window = bootDashboard();

    expect(window.Dashboard).toBeDefined();
    expect(window.Dashboard.loadJson).toBeTypeOf('function');
    expect(window.Dashboard.loadSnapshot).toBeTypeOf('function');
    expect(window.Dashboard.dataPath).toBeTypeOf('function');
    expect(window.Dashboard.classifyStrategies).toBeTypeOf('function');
  });

  it('classifyStrategies groups strategies by execution mode', () => {
    const window = bootDashboard();
    const strategies = [
      { strategy_name: 'stale_market', status: 'active', is_generated: false, alert_only: false, trading_enabled: true, live_ready: true, recent_signals_count: 5 },
      { strategy_name: 'ev_news', status: 'active', is_generated: false, alert_only: false, trading_enabled: true, live_ready: false, recent_signals_count: 10 },
      { strategy_name: 'spread_arb_v2', status: 'active', is_generated: false, alert_only: false, trading_enabled: true, live_ready: false, recent_signals_count: 3 },
      { strategy_name: 'fade_certainty_v2', status: 'active', is_generated: false, alert_only: true, trading_enabled: false, live_ready: false, recent_signals_count: 22 },
      { strategy_name: 'base_rate_knn', status: 'active', is_generated: false, alert_only: true, trading_enabled: false, live_ready: false, recent_signals_count: 0 },
      { strategy_name: 'volume_divergence', status: 'active', is_generated: false, alert_only: false, trading_enabled: false, live_ready: false, recent_signals_count: 0 },
      { strategy_name: 'auto_stub', status: 'active', is_generated: true, alert_only: false, trading_enabled: true, live_ready: false, recent_signals_count: 0 },
      { strategy_name: 'killed_one', status: 'paused', is_generated: false, alert_only: false, trading_enabled: true, live_ready: false, recent_signals_count: 0 },
    ];

    const result = window.Dashboard.classifyStrategies(strategies);

    expect(result.paper_and_live.map(s => s.strategy_name)).toEqual(['stale_market']);
    expect(result.paper.map(s => s.strategy_name)).toEqual(['ev_news', 'spread_arb_v2']);
    expect(result.alert_active.map(s => s.strategy_name)).toEqual(['fade_certainty_v2']);
    expect(result.alert_dead.map(s => s.strategy_name)).toEqual(['base_rate_knn', 'volume_divergence']);
  });

  it('uses bundled data paths on hosted or bundled pages', () => {
    let window = bootDashboard('https://example.test/wiki?bundled=1');
    expect(window.Dashboard.dataPath('wiki')).toBe('./data/wiki.json');

    window = bootDashboard('https://example.test/wiki');
    expect(window.Dashboard.dataPath('wiki')).toBe('./data/wiki.json');
  });

  it('uses local dashboard-data paths on localhost without bundled mode', () => {
    const window = bootDashboard('http://localhost:8000/wiki.html');
    expect(window.Dashboard.dataPath('wiki')).toBe('../dashboard-data/wiki.json');
  });

  it('throws on failed JSON fetches', async () => {
    const window = bootDashboard();
    window.fetch = vi.fn().mockResolvedValue({ ok: false });

    await expect(window.Dashboard.loadJson('./data/wiki.json')).rejects.toThrow('Failed to load ./data/wiki.json');
  });
});


describe('wiki page', () => {
  it('renders wiki navigation and content when wiki data loads', async () => {
    const window = bootDashboard();

    const responses = {
      './data/manifest.json': { generated_at: '2026-04-03T15:04:44Z', git_commit: 'abc123', warnings: [] },
      './data/overview.json': { latest_run_status: 'ok', alerts: [] },
      './data/strategies.json': [],
      './data/runs.json': [],
      './data/experiments.json': [],
      './data/execution-checks.json': [],
      './data/evaluation.json': null,
      './data/wiki.json': [
        { section: 'meta', section_label: 'Meta', slug: 'overview', title: 'Overview', html: '<h1>Overview</h1><p>Hello</p>' },
        { section: 'strategies', section_label: 'Strategies', slug: 'alpha', title: 'Alpha', html: '<h1>Alpha</h1><p>World</p>' }
      ]
    };
    window.fetch = vi.fn(async (path) => ({
      ok: true,
      json: async () => responses[path]
    }));

    window.eval(wikiInlineScript);
    await flushAsyncWork();

    expect(window.document.getElementById('wiki-empty').classList.contains('hidden')).toBe(true);
    expect(window.document.getElementById('wiki-layout').style.display).toBe('grid');
    expect(window.document.querySelectorAll('#wiki-sidebar a')).toHaveLength(2);
    expect(window.document.getElementById('wiki-content').innerHTML).toContain('<h1>Overview</h1>');
  });

  it('shows the empty state when wiki data fetch fails', async () => {
    const window = bootDashboard();

    window.fetch = vi.fn(async (path) => {
      if (path === './data/wiki.json') {
        return { ok: false };
      }
      return {
        ok: true,
        json: async () => {
          if (path === './data/manifest.json') return { generated_at: '2026-04-03T15:04:44Z', git_commit: 'abc123', warnings: [] };
          if (path === './data/overview.json') return { latest_run_status: 'ok', alerts: [] };
          return [];
        }
      };
    });

    window.eval(wikiInlineScript);
    await flushAsyncWork();

    expect(window.document.getElementById('wiki-empty').classList.contains('hidden')).toBe(false);
    expect(window.document.getElementById('wiki-layout').style.display).toBe('none');
  });
});
