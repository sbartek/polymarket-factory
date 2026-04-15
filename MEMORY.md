# Polymarket Factory Memory

## What this project is

A framework for spinning up, paper-trading, and evaluating Polymarket prediction market strategies. The goal is to find strategies with real edge, paper-trade them, then promote winners to live trading.

Current host split:
- `gpplayouts` (GCP VM) is the primary runtime for paper scan/execute, live, API, and dashboard-facing data.
- `pplayouts` (Intel Mac) now only runs the local strategy factory at 09:30 and pushes generated strategy/proposal updates.

Dashboard at https://pplayouts-dashboard.bartekskorulski.workers.dev.

This file is the canonical durable project memory for both Claude and Codex. Keep high-signal operational facts here and keep external memory files as thin pointers to this file.

---

## Architecture

```
gpplayouts runtime (Linux, cron):
  paper scan   (:30 every 2h) -> fetch markets, run strategies, cache signals
  paper execute(:00 every 2h) -> read cached signals, open/skip, close resolved
  24h review   (07:30 daily)  -> DB-only briefing, no LLM/market fetch
  observer / trade_fetcher / API run as separate services

pplayouts runtime (macOS, launchd):
  strategy-factory-local (09:30 daily) -> pull repo, fetch remote eval/benchmarks,
  generate candidates, refresh dashboard artifacts, push repo changes
```

**Runtime environments:** `paper` (default) · `live` (explicit `mode="live"` plus `live_ready=True`) · `review` (DB-only 24h briefing)

**Removed 2026-04-16:** standalone `live` run (redundant with paper_and_live dual execution) and `research` run (replaced by 24h review).

**Key files:**
- `factory/runner.py` — main loop
- `factory/strategies/` — all strategy implementations
- `factory/strategy_meta.py` — exposure caps, cadence, active set
- `factory/broker.py` — paper broker / trade access layer
- `factory/live_broker.py` — real CLOB execution, $100 hard cap
- `factory/feed.py` — Gamma API wrappers
- `factory/claude.py` — LLM wrapper (Anthropic API -> Claude CLI -> codex fallback)
- `factory/db.py` — PostgreSQL persistence (SQLite remains only for local backup/runtime artifacts)
- `eval/report.py` — weekly kill/keep evaluation
- `scripts/` — 20+ operational scripts
- `dashboard/` — static web UI source
- `improvement/` — proposals (PR-xxx), experiments (EX-xxx), change log

---

## Strategy status (2026-04-16)

### Paper + Live (2)
| Strategy | Cap | 7d WR | Notes |
|----------|-----|-------|-------|
| `stale_market` | $50 | 50% | Claude judges stale markets vs news. |
| `price_move_fade` | $40 | 83% | Star performer. Cap raised $25→$40 on 2026-04-16. |

### Active paper trading (8)
| Strategy | Cap | Notes |
|----------|-----|-------|
| `spread_arb_v2` | $100 | Cap raised $80→$100. 8 open. |
| `polling_vs_market` | $30 | +$20.12 on 1 trade. Needs more data. |
| `ev_news_v2` | $40 | Replaces v1. 7 consecutive loss streak — review needed. |
| `thin_market_impact_fade` | $35 | Cap raised $25→$35. 19 open. |
| `mutually_exclusive_oversum` | $25 | 38% WR. Borderline. |
| `correlated_pairs` | $30 | 3 open, no closures. |
| `celebrity_tabloid` | $25 | 1 open. |
| `weather_edge_v4` | $20 | NEW paper 2026-04-16. 99 signals/30d, avg EV 62pp. |

### Alert-only
- correlated_laggard, carry_rewards, weather_convergence, weather_autocorrelation, weather_oversum, weather_edge_v3, conditional_probability_mispricing, base_rate_knn, overnight_gap_fade, news_impact_fade_by_recency, esport48, and others

### Killed
| Strategy | Verdict | Root cause |
|----------|---------|------------|
| `resolution_hunter` | KILL 2026-04-03 | -92.3% ROI / 12 trades. CLOB prices resolve within hours; LLM too slow. |
| `fade_certainty` | KILL | 0% WR. 24 positions force-closed 2026-04-16 ($48 exposure freed). |
| `weather_edge` v1 | KILL | 43% WR, -12.7% ROI / 136 trades. Payoff asymmetry. |

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

## Runtime schedule (2026-04-16)

### `gpplayouts` (primary runtime, Linux, **cron**)

| Job | Schedule |
|-----|----------|
| `paper_scan` | Every 2h at `:30` |
| `paper_execute` | Every 2h at `:00` |
| `24h_review` | 07:30 daily (`run_review.sh`) |
| `observer` | Every 30 min |
| `trade_fetcher` | Every 30 min (offset 5m) |
| `backup` | 03:45 daily |
| `watchdog` | Every 10 min |
| `factory-api` | systemd service on port 8765 behind `factory.pplayouts.trade` |

**Removed 2026-04-16:** standalone `live` (19:30) and `research` (07:30) cron entries.

### `pplayouts` (strategy-factory only, macOS, **launchd**)

| Job | Schedule |
|-----|----------|
| `com.polymarket.factory.strategy-factory-local` | 09:30 daily |

Important:
- `pplayouts` should not run the paper combined/scan/execute/observer jobs.
- On 2026-04-10 those stale launch agents were unloaded, disabled, and removed from `~/Library/LaunchAgents`.

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
- Current storage policy is raw snapshot retention for 730 days, with a disk-free alert when less than 20% of disk space remains
- `dashboard/reference.html` was refreshed to document the replay benchmark, the explicit `research / paper / live` split, the current launchd schedules, and the live-only `carry_rewards` path
- There is now a dedicated research entrypoint in `run_factory_research.sh` plus `launchd/com.polymarket.factory.research.plist`, installed into `~/Library/LaunchAgents` and loaded in `launchd` under `gui/501` for 07:30 daily, logging to `factory-research.log`
- There is now a dedicated live launchd path: `run_factory_live.sh` plus `launchd/com.polymarket.factory.live.plist`, scheduled for 19:30 and writing to `factory-live.log` (gitignored)
- `com.polymarket.factory`, `com.polymarket.factory.strategy-factory`, and `com.polymarket.factory.live` all exist in `launchd` under `gui/501`; `launchctl print gui/501/<label>` is the reliable check because `launchctl list` may show nothing while idle for calendar agents
- `factory-strategy-factory.log` is the stdout/stderr sink for `launchd/com.polymarket.factory.strategy-factory.plist`, can be deleted safely, and will be recreated by the next strategy factory run
- Keep `factory-strategy-factory.log` ignored in the repo; `.gitignore` includes it alongside `factory.log`
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
- `mutually_exclusive_oversum` alert-only — accumulating signals, promote after 20 validated alerts
- `spread_arb` retest — 0 open positions as of 2026-04-04, eval after 10+ closed trades
- verify Slack notifications on the GCloud VM after pulling the latest main; local review found the VM alias (`pplayouts`) but SSH auth from this environment failed, so in-machine verification is still pending

## Operational updates (2026-04-06)

- Multiple cleanup / hardening / hygiene commits were completed and pushed to `origin/main`:
  - `2ada71c` — align tests with current strategy contracts
  - `4e9f0e8` — improve notification delivery reporting
  - `2e20e6f` — add generated strategy proposals and repo hygiene
  - `1cbc6eb` — refresh replay benchmark artifacts
  - `dec5ceb` — add retention cleanup job and harden notifications
- A real retention cleanup path now exists:
  - `scripts/retention_cleanup.py`
  - `run_retention_cleanup.sh`
  - `launchd/com.polymarket.factory.retention_cleanup.plist`
  - plus test coverage for both DB cleanup behavior and the script entrypoint
- Notification hardening phase 2 is now in place:
  - per-channel retries/backoff
  - per-channel attempt counts in delivery reports
  - runner output now distinguishes cases like `sent_after_2_attempts`, `failed_after_3_attempts`, and `unconfigured`
- Full suite passed after the retention + notification work: `uv run pytest -q` → `300 passed`.

## Test alignment notes (2026-04-06)

- `weather_edge_v2` tests were updated to match the current v2 contract: widened-bin probability logic, probability floor behavior, and NO-only signaling. The strategy header/comment was also updated so it no longer falsely describes strict `[lo, hi)` bin semantics.
- `celebrity_tabloid` tag-feed scan test was updated to use a short-window fixture (`days=20`) consistent with the current strategy horizon (`MAX_DAYS = 30`), instead of the stale long-window fixture.
- `ev_news` is now canonically a `short` time-window strategy; the DB metadata backfill test was updated accordingly.
- After those test-alignment changes, the full suite passed locally: `uv run pytest -q` → `290 passed`.

## Operational updates (2026-04-10)

- Paper runtime and strategy-factory roles were clarified and cleaned up:
  - `gpplayouts` is the only host that should run paper scan/execute and API-backed evaluation.
  - `pplayouts` should only run `com.polymarket.factory.strategy-factory-local` at 09:30.
- `pplayouts` had stale launch agents loaded for `com.polymarket.factory`, `scan`, `execute`, `live`, `research`, `observer`, and `aggressive`; these were disabled/unloaded, then the stale plist files were removed from `~/Library/LaunchAgents`.
- `pplayouts` now has only `com.polymarket.factory.strategy-factory-local` installed and loaded.
- The strategy factory on `pplayouts` was broken for two reasons:
  - local `.env` was missing `FACTORY_API_KEY` and `FACTORY_REMOTE_API_URL`
  - remote `/eval` on `gpplayouts` failed because `api/server.py` launched `eval/report.py` without `DATABASE_URL` in that subprocess environment
- Fixes applied:
  - added missing strategy-factory env vars on `pplayouts`
  - `api/server.py` now loads `.env` into the API process before handling `/eval`
  - `run_strategy_factory_local.sh` now skips auto-commit/push if the cycle fails
- Verified after the fix:
  - `/benchmark/alert-only` from `pplayouts` returned `200`
  - `/eval` from `pplayouts` returned `200`
  - `./run_strategy_factory_local.sh` on `pplayouts` completed successfully
- Successful 2026-04-10 strategy-factory run generated and pushed:
  - `stale_market_micro_20260410`
  - `resolution_hunter_conservative_20260410`
- Rescued alert-only strategies added recently:
  - `conditional_outcome_count_asymmetry`
  - `conditional_outcome_drift`
  - `news_impact_fade_by_recency`
- First live evidence for the rescued set came from `gpplayouts`:
  - `news_impact_fade_by_recency` produced a live signal on `Will Paulo Costa win by KO or TKO?` with `NO`, market price `0.635`, `p_hat 0.73`, edge `9.5pp`, confidence `medium`
- New repo-native backlog category exists at `improvement/ideas/` for strategy concepts that are worth keeping but not worth implementing yet; the seven parked generated strategy leftovers were moved there as structured idea notes.
- Strategy-factory runtime hardening landed in `c11543a` with two follow-up fixes in `595c2ff` and `272a686`:
  - `scripts/strategy_factory_local_runner.py` now owns preflight, lockfile, structured run records, push handling, heartbeat posting, and degraded/failed Slack alerts.
  - `api/server.py` now exposes `/ready`, adds eval timeout/error logging, and accepts heartbeat `status` + `detail`.
  - `scripts/strategy_factory_cycle.py` now retries transient remote API failures, caches eval text, skips generation when remote eval falls back to cache, and writes `dashboard-data/strategy_factory_cycle_meta.json`.
  - `scripts/export_dashboard_data.py` now reads `data/strategy-factory-runs/latest.json` into `overview.json` and falls back to local SQLite when `DATABASE_URL` is absent.
  - `dashboard/index.html` now has a Strategy Factory panel sourced from `overview.strategy_factory`.
- Deployment nuance discovered on 2026-04-10:
  - GitHub Actions deploy only does `git pull` on `gpplayouts` / `pplayouts`; it does not restart the running API process on `gpplayouts`.
  - After deploying `c11543a`, `factory.pplayouts.trade/ready` still returned `404` until the existing `uvicorn api.server:app` process on `gpplayouts` was restarted manually via `run_api.sh`.
- End-to-end verification completed on 2026-04-10 after restarting the `gpplayouts` API and rerunning `pplayouts`:
  - `factory.pplayouts.trade/ready` returned `200` with `factory_api_key`, `database_url`, `eval_report`, and `database_connectivity` all true.
  - `./run_strategy_factory_local.sh` on `pplayouts` completed with `status=ok`, `preflight_ok=true`, `pull_ok=true`, `cycle_ok=true`, `push_ok=true`, `heartbeat_ok=true`, `eval_source=remote`, `generated_count=0`, `archived_count=0`.
  - `data/strategy-factory-runs/latest.json` now exists on `pplayouts`.
  - `dashboard-data/overview.json` on `pplayouts` now exports a non-null `strategy_factory` block and `dashboard-dist/` was rebuilt successfully (14 data files, 27 wiki pages).
- Follow-up operational/docs/dashboard work was pushed in `eaa363b`:
  - `.github/workflows/deploy.yml` now restarts the `gpplayouts` API after `git pull`
  - dashboard Overview now exposes recent strategy-factory run history
  - `README.md` and `MEMORY.md` were updated to reflect the hardened strategy-factory runtime path

## Runtime/test updates (2026-04-10, later session)

- Python/runtime stability work landed in two local commits that were then pushed to `main`:
  - `a9c2ace` — pin Python away from the `ddgs` / `primp` crash
  - `d954614` — restore SQLite test compatibility and align stale tests with current contracts
- Root cause of the remaining full-suite abort:
  - local `.venv` had been running Python `3.14.2`
  - `ddgs 9.12.0` + `primp 1.2.0` could abort the interpreter in native code when tests accidentally initialized the real `DDGS()` client on macOS/Python 3.14
- Fixes applied:
  - `pyproject.toml` now pins `requires-python` to `>=3.12,<3.14`
  - `.python-version` now pins the repo to `3.12`
  - `tests/test_ev_news_dedup.py` no longer initializes real `DDGS`; it uses a narrow SQLite-backed dedup stub instead
  - `factory/db.py` now supports an explicit SQLite compatibility mode again when constructed as `FactoryDB(path=...)`, while keeping PostgreSQL/DSN as the default runtime path
  - `factory/runner.py` now passes the active DB instance into `PaperBroker` during execute runs instead of creating a fresh default DB connection
  - stale tests were updated to match current contracts:
    - `price_move_fade` is promoted paper-trading, not alert-only
    - `weather_edge_v2` is paused alert-only, not promoted
    - notification config tests now account for `configured_channels()` requiring both `WHATSAPP_GROUP_ID` and an `openclaw` binary
    - execute-phase tests now mock `fetch_top_paginated`, which is the current fast-pass fetch path in `runner.py`
- Verification:
  - targeted regression batch for the restored SQLite path passed: `136 passed`
  - full local suite under Python 3.12 passed: `365 passed in 35.86s`

## Current plan state (2026-04-10)

- Completed:
  - strategy-factory runtime hardening and dashboard visibility
  - deploy workflow restart for `gpplayouts` API
  - Python 3.12 pin and removal of the local `ddgs` / `primp` crash path
  - restored SQLite compatibility for legacy tests and a fully green local suite
- Next:
  - verify the latest deploy run for `d954614` and confirm `gpplayouts` / `pplayouts` pulled the new commits cleanly
  - run one more real strategy-factory cycle on `pplayouts` after the latest deploy to confirm no operational drift
  - add CI enforcement for Python 3.12 so the runtime pin is checked outside local development
  - keep `origin/main` tracking tidy locally when pushing via explicit SSH URLs

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
