# Polymarket Factory Memory

## What this project is

A framework for spinning up, paper-trading, and evaluating Polymarket prediction market strategies. The goal is to find strategies with real edge, paper-trade them, then promote winners to live trading.

Runs automatically via launchd on the `pplayouts` machine (Intel Mac, Tailscale IP 100.75.233.52). Dashboard at https://pplayouts-dashboard.bartekskorulski.workers.dev.

This file is the canonical durable project memory for both Claude and Codex. Keep high-signal operational facts here and keep external memory files as thin pointers to this file.

---

## Architecture

```
runner.py (every 2h, 12x/day via launchd)
  ├── fetch 100 top markets (Gamma API)
  ├── each strategy: scan → signal → env policy → open/skip
  ├── check open positions → close resolved ones
  ├── WhatsApp summary (full at 09:00, delta at other runs)
  └── publish dashboard snapshot
```

**Runtime environments:** `research` (signals only) · `paper` (default) · `live` (explicit `mode="live"` plus `live_ready=True` only; currently `carry_rewards`)

**Key files:**
- `factory/runner.py` — main loop
- `factory/strategies/` — all strategy implementations
- `factory/strategy_meta.py` — exposure caps, cadence, active set
- `factory/broker.py` — paper broker (SQLite-backed)
- `factory/live_broker.py` — real CLOB execution, $100 hard cap
- `factory/feed.py` — Gamma API wrappers
- `factory/claude.py` — LLM wrapper (Anthropic API -> Claude CLI -> codex fallback)
- `factory/db.py` — SQLite schema, 15+ tables
- `eval/report.py` — weekly kill/keep evaluation
- `scripts/` — 20+ operational scripts
- `dashboard/` — static web UI source
- `improvement/` — proposals (PR-xxx), experiments (EX-xxx), change log

---

## Strategy status

### Live trading
| Strategy | Edge | Window | Notes |
|----------|------|--------|-------|
| `carry_rewards` | structural | long | Full-set YES+NO for ~4% APY. First live orders 2026-04-03. `live_ready=True`, `mode=live` |

### Active paper trading
| Strategy | Edge | Window | Status |
|----------|------|--------|--------|
| `ev_news` | information | medium | Claude scans news → p̂ estimate. 14 open, 1 closed (+77% ROI). LLM-heavy. |
| `spread_arb` | structural | medium | Buy all legs when Σ(YES) < 0.90. 0 open (clean retest 2026-04-04), 79 closed pre-fix (-89.1% ROI, bug-driven). MAX_DAYS 30. Awaiting fresh data. |
| `stale_market` | information | short | Claude judges stale markets vs news. 3 open, 2 closed (-100% ROI). Watch. |
| `correlated_pairs` | logical_inconsistency | medium | Logically inconsistent pairs. 0 trades. Early stage. |
| `celebrity_tabloid` | information | short | Tabloid corroboration. 17 open, 0 closed. Tag-feed fix working (6 candidates/run). |
| `polling_vs_market` | model_vs_market | medium | DDGS polls + LLM gap analysis. MIN_GAP_PP=10pp. Daily cadence. 0 trades. Added 2026-04-04. |

### Alert-only (needs graduation checklist before paper trading)
| Strategy | Notes |
|----------|-------|
| `correlated_laggard` | Liquid leader/laggard divergence. `promotable=True`. See EX-20260401-006. |
| `esport48` | Esport markets <48h. `promotable=True`. See EX-20260401-007. |
| `mutually_exclusive_oversum` | Oversum NO-fade. `promotable=True`. Promote after 20 alerts, >60% revert. Added 2026-04-04. |

### Killed
| Strategy | Verdict | Root cause |
|----------|---------|------------|
| `resolution_hunter` | KILL 2026-04-03 | -92.3% ROI / 12 trades. CLOB prices resolve within hours; LLM too slow. |
| `fade_certainty` | KILL | 0% WR, -100% ROI / 10 trades. |
| `weather_edge` | KILL | 43% WR, -12.7% ROI / 136 trades. Payoff asymmetry. |

---

## Evaluation thresholds

| Metric | Kill | Keep | Min trades |
|--------|------|------|------------|
| Win rate | < 30% | > 50% | 5 |
| ROI | < -10% | > 0% | 5 |

Run: `uv run eval/report.py`

---

## Live trading

- Wallet: `0x5f640a669a9cF0Ad424c4dC6b34e900DAFdB35fc` (Polygon, ~48 USDC)
- CLOB credentials in `.env` (generated via `scripts/setup_clob_credentials.py`)
- Kill switch: `uv run python scripts/kill_live.py`
- `trades` table has `mode` column (`paper` | `live`)
- `PaperBroker` loads only `mode=paper` trades; `LiveBroker` loads only `mode=live` trades
- Generated strategies are blocked from `live` by environment policy and should stay in research/paper unless a human deliberately changes that

---

## Launchd schedule

| Job | Schedule |
|-----|----------|
| `com.polymarket.factory` | Every 2h at :00 (00:00, 02:00 … 22:00) · paper env |
| `com.polymarket.factory.live` | 19:30 daily · live env |
| `com.polymarket.factory.aggressive` | 10:30 / 22:30 daily |
| `com.polymarket.factory.research` | 07:30 daily |
| `com.polymarket.factory.backup` | 03:45 daily |

---

## Common commands

```bash
# Dry run (no writes, no sends)
uv run python -c "from factory.runner import run; run(environment='paper', dry_run=True)"

# Fast dry run (skips ev_news)
uv run python -c "from factory.runner import run; run(environment='paper', dry_run=True, fast_dry_run=True)"

# Open book
uv run python scripts/open_positions.py

# Latest run
uv run python scripts/latest_run.py -n 1

# Strategy-specific logs
uv run python scripts/strategy_checks.py <strategy> --limit 10

# Weekly eval
uv run eval/report.py

# Rebuild + publish dashboard
uv run python scripts/update_wiki.py
uv run python scripts/export_dashboard_data.py
uv run python scripts/build_dashboard.py
uv run python scripts/publish_dashboard.py ~/workai/projects/pplayouts-dashboard --commit --push
```

Dashboard publishing notes:

- Publish target repo: `~/workai/projects/pplayouts-dashboard`
- Canonical publish command: `.venv/bin/python scripts/publish_dashboard.py ~/workai/projects/pplayouts-dashboard`
- `scripts/publish_dashboard.py` is not a pure sync step; by default it runs `scripts.update_wiki.py`, `scripts.export_dashboard_data.py`, and `scripts.build_dashboard.py` before mirroring `dashboard-dist/`
- Verified on 2026-04-03: publishing completed successfully and the resulting dashboard repo commit was `28d6030`

---

## WhatsApp group

Group ID: `120363425524943226@g.us` (in `.env`). Members: Bartek + Pawel + Daniel.
Full summary at 09:00 Madrid time; delta updates at other runs.

---

## Known issues / active work (2026-04-03)

- `wiki/overview.md` is a duplicate of `wiki/meta/overview.md` — one should be removed
- Wiki pages missing for: `correlated_pairs`, `celebrity_tabloid`, `carry_rewards`
- No DB retention cleanup job — 730-day retention policy exists in config but no enforcement script runs it
- `mutually_exclusive_oversum` proposal (PR-20260403-002) overlaps with `spread_arb` — decision pending: unify or keep separate

## Fixed 2026-04-03 (session 2)

- **`celebrity_tabloid`**: 3 root causes fixed — strategy now fetches from `celebrities`/`pop-culture`/`reality-tv`/`music` tags (30 each) and merges with top-100 feed; `_market_text()` bug fixed (tags were silently dropped due to key not in allowed set); filters relaxed (MIN_VOLUME 10k→100, MAX_DAYS 45→365, MIN_CANDIDATE_SCORE 4.0→3.0, MIN_PRICE 0.12→0.08). Result: 6 candidates per run, 2 signals in test.
- **live broker partial-fill rollback**: `_open_full_set()` now retries NO leg once (2s delay); on second failure records `PARTIAL_YES_UNHEDGED` trade with CLOB order ID in notes + DB error event. Position now visible in open_positions for manual review. Also fixed `log_event()` call signature bug (market_id moved into payload).
- **`correlated_pairs`**: `_topic_key()` → `_topic_keys()` (returns set of ALL matching keywords, not just first). `_discover_pairs()` uses inverted index with deduplication across groups. Expanded `PAIR_KEYWORDS` with nba/nhl/mlb/nfl/mls/hormuz/bitcoin/crypto/hungary/ukraine/russia/musk/hamas/israel/netanyahu/gaza/hezbollah. Result: 3 pairs → 4 pairs including Trump+Iran logical pair.
- **Brier score tracking**: `FactoryDB.get_brier_score_data()` joins signals to closed trades at `run_id_opened`; filters to `resolved_outcome IN ('YES','NO')` (named-outcome sports markets excluded — their `exit_price` is unreliable). `eval/report.py` prints LLM calibration section. Empty now (both closed LLM trades have team-name outcomes); will populate as binary YES/NO markets resolve.
- **Tests**: 113 → 144 tests. Added `test_celebrity_tabloid_tags.py` (8), `test_correlated_pairs_discovery.py` (9), `test_live_broker_partial_fill.py` (7), `test_brier_scores.py` (7).

## Verified operational notes (2026-04-03)

- The live Workers wiki bug was caused by `dashboard/wiki.html` calling `Dashboard.loadJson(...)` while `dashboard/dashboard.js` did not export `loadJson` on `window.Dashboard`; the fix was to export `loadJson`, rebuild, and republish
- There is now a small JS dashboard test harness: `npm run test:dashboard` runs `vitest` + `jsdom` tests for the `window.Dashboard` export contract, `dataPath()` behavior, and wiki render/empty-state behavior
- The dashboard wiki renderer in `scripts/build_dashboard.py` now preserves identifiers with underscores such as `ev_news` and `stale_market` instead of turning them into accidental italics
- `scripts/export_dashboard_data.py` now includes generated-strategy lifecycle metadata in `dashboard-data/strategies.json`, including active vs archived state, proposal/module paths, benchmark score, label count, and archive reason when available
- `dashboard/strategies.html` now has a generated/core origin filter plus generated lifecycle and benchmark columns, and `dashboard/index.html` now marks generated strategies directly in the strategy snapshot
- The replay benchmark is surfaced in the dashboard overview via `dashboard-data/benchmarks.json`; source artifacts live in `benchmark-data/replay-benchmark-*.json`
- `scripts/build_replay_benchmark.py` now emits `strategy_slices` grouped by `strategy`, `edge_type`, and `time_window`; the Strategies page reads those rows from `dashboard-data/benchmarks.json`
- The replay benchmark now derives `price_window` directional labels from later observed prices already stored in `signals` and `signal_execution_checks`, using each strategy's hold window from `factory/strategy_meta.py`
- There is now a `market_observations` table populated from `factory/runner.py` market snapshots; `scripts/build_replay_benchmark.py` prefers this table for forward price labels and only falls back to `signals` / `signal_execution_checks` when observation history is absent
- `factory/runner.py` now also stores the raw fetched Gamma snapshot per run in `market_snapshot_archives`, so future runs are reconstructible from original payloads instead of only derived observations
- Historical backfill is not feasible from current local artifacts; the repo has SQLite state and `trades.csv`, but no stored raw market snapshot history before `market_snapshot_archives`, and `run_logs` do not contain enough payload detail to reconstruct old market states
- The dashboard now exports `storage.json` and shows a Storage panel on Overview with current project size, DB size, raw snapshot archive size, observation row count, and recent raw snapshot payload sizes
- Current storage policy is raw snapshot retention for 730 days, with a soft alert near 90 GB and a hard reference limit of 100 GB for project storage
- `dashboard/reference.html` was refreshed to document the replay benchmark, the explicit `research / paper / live` split, the current launchd schedules, and the live-only `carry_rewards` path
- There is now a dedicated research entrypoint in `run_factory_research.sh` plus `launchd/com.polymarket.factory.research.plist`, installed into `~/Library/LaunchAgents` and loaded in `launchd` under `gui/501` for 07:30 daily, logging to `factory-research.log`
- There is now a dedicated live launchd path: `run_factory_live.sh` plus `launchd/com.polymarket.factory.live.plist`, scheduled for 19:30 and writing to `factory-live.log` (gitignored)
- `com.polymarket.factory`, `com.polymarket.factory.aggressive`, and `com.polymarket.factory.live` all exist in `launchd` under `gui/501`; `launchctl print gui/501/<label>` is the reliable check because `launchctl list` may show nothing while idle for calendar agents
- `factory-aggressive.log` is not an input file; it is the stdout/stderr sink for `launchd/com.polymarket.factory.aggressive.plist`, can be deleted safely, and will be recreated by the next aggressive cycle run
- Keep `factory-aggressive.log` ignored in the repo; `.gitignore` includes it alongside `factory.log`
- The wiki update path uses `factory/claude.py`, which calls Anthropic if `ANTHROPIC_API_KEY` is set and otherwise shells out to `claude --permission-mode bypassPermissions --print ...`; this can block unless external access is allowed

## Current plan state (2026-04-04)

Session 1: benchmark/control-loop stack — environment split, replay benchmark, generated retention gate, dashboard visibility, price-window labels, market observation history, raw snapshot archives, storage monitoring.

Session 2: strategy fixes — celebrity_tabloid tag feed + filter fixes, live broker partial-fill safety, correlated_pairs multi-keyword pairing, Brier score infrastructure. 144 tests passing.

Session 3 (2026-04-04): polling_vs_market integration + wiki cleanup + spread_arb diagnosis + fix.
- `polling_vs_market` added by Codex on pplayouts: registered as active, daily scan_frequency, MIN_GAP_PP=10pp, max_position_usdc=10, DDGS news search + LLM gap analysis.
- Added `polling_vs_market_checks` detail table + `log_polling_vs_market_check()` in db.py; runner.py hooked; queries.py getter + DETAIL_TABLE_GETTERS entry; strategy_checks.py column spec.
- 13 new tests for polling_vs_market; 168 tests total passing.
- `update_wiki.py` fixed: now seeds `by_strategy` for all ACTIVE_STRATEGIES with no trades.
- Stale `wiki/overview.md` duplicate removed (canonical page is `wiki/meta/overview.md`).
- **spread_arb root cause diagnosed**: `_looks_suspicious()` had inverted logic — passed incomplete tournament baskets (4 of 30 NBA teams etc.) as valid arbs. Fix: reject "winner/champion/election/award/next to/who will be" markets without a catch-all "Field/Other" leg. Also tightened `MAX_DAYS_TO_CLOSE` 90→30 days. 11 new tests.
- **spread_arb force-close + retest**: All 70 pre-fix positions closed (2 rounds). Full clean slate as of 2026-04-04. spread_arb now scanning fresh under fixed logic. Pre-fix stats: 79 closed, 2% WR, -89.1% ROI (dominated by incomplete basket bug).
- Portfolio: 132 → 62 open positions, $275 → ~$100 exposure.
- Dashboard reference.html: fixed sc-params value overflow (label col 55%→48%, smaller font, value col white-space:nowrap).
- `mutually_exclusive_oversum` built and deployed as alert-only: Σ(YES) > 1.08 → NO on most overpriced leg. Filters: incomplete open fields, price-target non-exclusive legs (hit/reach/dip keywords), MAX_OVERSUM=1.50. 15 tests. Promote to paper after 20 validated alerts showing >60% revert within 7 days.

Remaining backlog:
- DB retention cleanup job (730-day policy exists, no enforcement)
- `mutually_exclusive_oversum` alert-only — accumulating signals, promote after 20 validated alerts
- `spread_arb` retest — 0 open positions as of 2026-04-04, eval after 10+ closed trades

## Test alignment notes (2026-04-06)

- `weather_edge_v2` tests were updated to match the current v2 contract: widened-bin probability logic, probability floor behavior, and NO-only signaling. The strategy header/comment was also updated so it no longer falsely describes strict `[lo, hi)` bin semantics.
- `celebrity_tabloid` tag-feed scan test was updated to use a short-window fixture (`days=20`) consistent with the current strategy horizon (`MAX_DAYS = 30`), instead of the stale long-window fixture.
- `ev_news` is now canonically a `short` time-window strategy; the DB metadata backfill test was updated accordingly.
- After those test-alignment changes, the full suite passed locally: `uv run pytest -q` → `290 passed`.

---

## Context files

- `MEMORY.md` (this file) — canonical full project context for Claude and Codex
- `CLAUDE.md` — one-liner pointing here; auto-loaded by Claude Code
- `~/.codex/memories/polymarket-factory.md` — keep this as a tiny pointer to this file
- No `AGENTS.md` yet — add one if Codex needs auto-loading from inside the repo

---

## Wiki system

Auto-generated from DB via Claude (Karpathy pattern). Pages in `wiki/` (gitignored).

```bash
uv run python scripts/update_wiki.py        # regenerate all pages
uv run python scripts/ask_wiki.py "question" --file-back  # Q&A filed into wiki
```

Wiki rendered at `/wiki.html` on dashboard.
