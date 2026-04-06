# Polymarket Factory

A framework for rapidly spinning up, paper-trading, and evaluating Polymarket investment strategies.

**Goal:** Find strategies with real edge. Paper-trade each for ~a week, evaluate against kill/keep thresholds, promote winners to live trading.

Project memory lives in `MEMORY.md`. Keep durable project context there; `CLAUDE.md` and external Codex memory should stay as thin pointers.

---

## Architecture

```
You (idea) → new file in factory/strategies/ → add to STRATEGIES registry → runs automatically
                                                                                ↓
                                                Two-phase run (every 2h via cron/launchd):
                                                  Phase 1 — SCAN (:30)
                                                    ├── fetch 1000 markets (Gamma API, paginated)
                                                    ├── each strategy: scan → signals → cache to DB
                                                    └── LLM + news calls happen here (slow)
                                                  Phase 2 — EXECUTE (:00)
                                                    ├── read cached signals from scan phase
                                                    ├── env policy → dedup → size → open/skip
                                                    ├── check open positions → close resolved ones
                                                    └── notifications (Slack + WhatsApp) → dashboard publish
```

**Stack:** Python 3.12 · uv · Gamma API · DDGS news · Anthropic Claude API · Slack + WhatsApp
**Hosts:** GCP VM (primary) + Mac (legacy) — portable shell scripts, same codebase

---

## Adding a Strategy

1. Create `factory/strategies/my_strategy.py` implementing `Strategy`:
   ```python
   from .base import Strategy
   from ..models import Signal

   class MyStrategy(Strategy):
       name = "my_strategy"
       max_position_usdc = 10.0
       min_ev_pp = 10.0

       def scan(self, markets: list[dict]) -> list[Signal]:
           ...
   ```
2. Register in `factory/strategies/__init__.py`.
3. Test with a safe dry run before trusting it.

---

## Strategy Interface

```python
class Strategy(ABC):
    name: str
    mode: str               # preferred execution env: "paper" | "live"
    max_position_usdc: float
    min_ev_pp: float
    alert_only: bool        # if True, log/report only; runner will not open positions
    trading_enabled: bool   # explicit runner gate; keep False for alert-only strategies
    promotable: bool        # candidate for later graduation
    live_ready: bool        # reserved for later real-money path

    # portfolio taxonomy
    edge_type: str
    time_window: str        # super_short | intraday | short | medium | long
    target_hold_min_days: float
    target_hold_max_days: float
    scan_frequency: str

    def scan(self, markets) -> list[Signal]
    def size(self, signal) -> float
    def should_exit(self, trade, price) -> bool
```

## Time Window Taxonomy

- `super_short` = under 1 hour
- `intraday` = 1h to 24h
- `short` = 1–7 days
- `medium` = 8–30 days
- `long` = 31+ days

The runner uses time windows operationally:
- faster buckets run every cycle
- `medium` can skip midday churn
- `long` ideas can run once per day
- open exposure is capped by both strategy and time window

---

## Evaluation

Run weekly: `uv run eval/report.py`

| Metric | Kill | Keep |
|--------|------|------|
| Win rate | < 30% | > 50% |
| ROI | < -10% | > 0% |
| Min trades to evaluate | 5 | — |

The report aggregates by:
- strategy
- time window
- edge type
- active vs legacy

Alert-only graduation criteria and promotion workflow live in [`docs/alert_only_graduation.md`](docs/alert_only_graduation.md).

## Runtime Environments

The runner now supports three explicit environments:

- `research` — scan and log signals, but never open or resolve positions
- `paper` — paper-only trading and paper-only resolution
- `live` — real-money trading for explicit live-only strategies

Strategy attributes and environment policy interact like this:
- `mode="paper"` means the strategy may open positions only in the `paper` environment
- `mode="live"` means the strategy is kept out of paper trading and may open only in the `live` environment
- `live_ready=True` is required but not sufficient for `live`; the environment still decides whether execution is allowed

Generated strategies are blocked from `live` by environment policy.

---

## Strategy Roadmap

### Live trading

- [x] **`carry_rewards`** — Full-set purchases for ~4% APY Holding Rewards. `live_ready=True`, `mode=live`. Runs at 19:30 cycle (long time window). First live orders 2026-04-03.

### Active (paper trading)

- [x] **`ev_news`** — Claude scans top markets + news headlines, picks topics, estimates p̂ per market from news. Current taxonomy window: `short`.
- [x] **`spread_arb`** — Multi-outcome markets where sum of YES prices is materially below 1.0, with stricter practical filtering.
- [x] **`stale_market`** — Looks for liquid near/medium-term markets whose prices appear stale versus recent news.
- [x] **`correlated_pairs`** — MVP for logically inconsistent market pairs (prerequisite vs downstream, broader vs narrower).
- [x] **`correlated_laggard`** — Alert-only MVP for liquid leader / laggard divergences across obviously related markets.
- [x] **`esport48`** — Alert-only screener for esport markets expiring within 48 hours, using deterministic liquidity/price filters and subtype tagging.
- [x] **`celebrity_tabloid`** — Paper-trading celebrity-event screener. Tag-feed augmentation is live (`celebrities` / `pop-culture` / `reality-tv` / `music`), producing candidates beyond the base Gamma top-market feed.

Current graduation status:
- `correlated_laggard`: alert-only, `promotable=True`, `trading_enabled=False`
- `esport48`: alert-only, `promotable=True`, `trading_enabled=False`
- `celebrity_tabloid`: paper trading, `trading_enabled=True` — blocked by feed coverage

### Killed

- ❌ **`resolution_hunter`** — Killed 2026-04-03. -92.3% ROI / 8.3% WR on 12 trades. Root cause: CLOB prices resolve within hours; LLM news inference too slow to find real edge. See CR-20260403-006.
- ❌ **`fade_certainty`** — Killed. 0% WR, -100% ROI (10 trades).
- ❌ **`weather_edge`** — Killed. 43% WR, -12.7% ROI (136 trades).

### Planned — next builds

- [ ] **`polling_vs_market`**
- [ ] **`base_rate`**
- [ ] **`crypto_options_basis`**
- [ ] **`pre_event_drift`**

### Future (post-validation)

- [ ] Graduate `spread_arb` / `ev_news` to live after ≥15 closed trades + graduation checklist
- [ ] Strategy parameter tuning
- [ ] Monthly live vs paper calibration report
- [ ] Claude calibration retrospective (Brier score gate for LLM strategies)

---

## Operations

```bash
# Main runner cadence: every 2h (12x/day), but medium/long strategies skip some cycles.
# WhatsApp messaging policy:
# - 09:00 Europe/Madrid → full general summary
# - other runs → opened/closed delta update (plus a small alert snippet if relevant)

# Show open book (all groups + full position list)
uv run python scripts/open_positions.py

# Show only the 5 oldest open positions
uv run python scripts/open_positions.py --top-oldest 5

# Filter by strategy
uv run python scripts/open_positions.py --strategy ev_news

# Filter by time window
uv run python scripts/open_positions.py --time-window medium

# Manual run (paper env by default)
uv run python -m factory.runner

# Manual research-only run
FACTORY_ENV=research uv run python -m factory.runner

# Dedicated research entrypoint used by launchd
./run_factory_research.sh

# Manual live run
FACTORY_ENV=live uv run python -m factory.runner

# Dedicated live entrypoint used by launchd
./run_factory_live.sh

# Safe manual dry run (no writes, no closes, no sends)
uv run python -c "from factory.runner import run; run(environment='paper', dry_run=True)"

# Safe dry run of live environment policy
uv run python -c "from factory.runner import run; run(environment='live', dry_run=True)"

# Faster safe dry run for debugging the whole cycle
# (currently skips `ev_news` and trims other expensive strategy workloads)
uv run python -c "from factory.runner import run; run(environment='paper', dry_run=True, fast_dry_run=True)"

# Weekly evaluation
uv run eval/report.py

# Latest run summary
uv run python scripts/latest_run.py -n 1

# Inspect recent decisions
uv run python scripts/inspect_decisions.py --limit 20

# Inspect strategy-specific checks
uv run python scripts/strategy_checks.py stale_market --limit 10
uv run python scripts/strategy_checks.py correlated_laggard --limit 10
uv run python scripts/strategy_checks.py esport48 --limit 10
uv run python scripts/strategy_checks.py celebrity_tabloid --limit 10

# Inspect Phase A execution-reality snapshots for generated signals
uv run python scripts/signal_execution_checks.py --limit 20
uv run python scripts/signal_execution_checks.py --strategy spread_arb --limit 20

# Inspect current open book
uv run python scripts/open_positions.py --top-oldest 10

# Inspect legacy open baggage specifically
uv run python scripts/legacy_positions.py --top-oldest 20

# Analyze recent runs and decision patterns
uv run python scripts/run_analytics.py --runs 20

# Show active improvement-harness experiment threads
uv run python scripts/active_experiments.py

# Review alert-only graduation docs / checklists
sed -n '1,200p' docs/alert_only_graduation.md
sed -n '1,200p' improvement/experiments/EX-20260401-006-correlated-laggard-paper-eval.md
sed -n '1,200p' improvement/experiments/EX-20260401-007-esport48-paper-eval.md

# Create a new review-note stub for an active thread
uv run python scripts/new_review_note.py "correlated pairs 10-run review"

# Backfill missing legacy trade metadata after imports/migrations
uv run python scripts/backfill_trade_metadata.py

# Test /details skill
uv run openclaw-skill/scripts/strategy_details.py fade
```

## SQLite logging (Phase 1)

Runner executions also log to `data/factory.sqlite3`:
- `runs`
- `signals`
- `decisions`
- `run_logs`

Trade state is now SQLite-backed in `data/factory.sqlite3`. The runner/broker still exports `data/trades.csv` during the migration period for compatibility and easy inspection.

## Dashboard

Build the private static dashboard snapshot + bundle:

```bash
# Export JSON snapshot files
uv run python scripts/export_dashboard_data.py

# Build self-contained static bundle into dashboard-dist/
uv run python scripts/build_dashboard.py

# Sync/publish bundle into a dashboard branch checkout or separate repo
uv run python scripts/publish_dashboard.py ~/path/to/dashboard-publish-repo
```

Current publish target in this workspace:

```bash
uv run python scripts/publish_dashboard.py ~/workai/projects/pplayouts-dashboard
```

Operational notes:
- `scripts/publish_dashboard.py` runs `scripts.update_wiki.py` before export/build unless `--skip-export` is passed.
- `scripts.update_wiki.py` calls Claude/Codex tooling, so the publish flow may require external access and can take longer than a plain file sync.
- `run_aggressive_cycle.sh` writes its scheduled launchd output to `factory-aggressive.log`; that file is a disposable local log and is gitignored.

Local preview:

```bash
cd dashboard-dist
python3 -m http.server 8000
# then open /index.html?bundled=1
```

Dashboard JS tests:

```bash
npm install
npm run test:dashboard
```

These browser-side tests cover the `window.Dashboard` contract, `dataPath()` behavior, and the wiki page render/empty-state flow under `jsdom`. Run them before pushing dashboard UI changes.

See also:
- `docs/dashboard_metric_definitions.md`
- `docs/dashboard_snapshot_schema.md`
- `docs/dashboard_deployment.md`

# Daily backups

Create local daily snapshots with retention cleanup:

```bash
uv run python scripts/backup_db.py --keep 14
```

This currently backs up:
- `data/factory.sqlite3` → `backups/factory-YYYY-MM-DD.sqlite3`
- `data/trades.csv` → `backups/trades-YYYY-MM-DD.csv` (when present)

The live DB and local backups are gitignored.

## Deployment

The factory runs on **two hosts in parallel** — a GCP VM (primary) and a Mac (legacy/backup).

All `run_*.sh` scripts are **portable**: they detect `vm_env.sh` at runtime and source it on the VM, falling back to Mac paths otherwise. No host-specific forks needed.

```
if vm_env.sh exists → VM mode  (sources vm_env.sh: PATH, .env, git pull, DASHBOARD_REPO)
else               → Mac mode (sources .env, hardcoded Mac PATH)
```

### GCP VM (`factory-vm`)

- **Machine:** e2-micro (1 GB RAM + 1 GB swap), Debian 12, us-central1-a
- **Scheduler:** cron (8 jobs)
- **Notifications:** Slack webhook (SLACK_WEBHOOK_URL in .env)
- **LLM:** Anthropic API (ANTHROPIC_API_KEY in .env)
- **Dashboard publish:** pushes to `$DASHBOARD_REPO` (set in vm_env.sh)
- **Config:** `vm_env.sh` (untracked, VM-only) sets PATH, sources .env, auto-pulls code

### Mac (legacy)

- **Scheduler:** launchd (9 plist jobs)
- **Notifications:** WhatsApp via OpenClaw + Slack webhook
- **LLM:** Claude CLI / Codex (local) + Anthropic API fallback
- **Dashboard publish:** pushes to `~/workai/projects/pplayouts-dashboard`

### Cron schedule (VM)

| Job | Schedule | Script |
|-----|----------|--------|
| Scan | every 2h at :30 | `run_scan.sh` |
| Execute | every 2h at :00 | `run_execute.sh` |
| Observer | every 30 min | `run_observer.sh` |
| Trade fetcher | every 30 min (+5 offset) | `run_trade_fetcher.sh` |
| Research | daily 07:30 | `run_factory_research.sh` |
| Live | daily 19:30 | `run_factory_live.sh` |
| Aggressive cycle | daily 10:30 + 22:30 | `run_aggressive_cycle.sh` |
| DB backup | daily 03:45 | `run_backup.sh` |

### `.env` (not committed)

Required on both hosts:
```env
POLYMARKET_WALLET_PRIVATE_KEY=...
POLYMARKET_API_KEY=...
POLYMARKET_API_SECRET=...
POLYMARKET_API_PASSPHRASE=...
WHATSAPP_GROUP_ID=...
SLACK_WEBHOOK_URL=...
ANTHROPIC_API_KEY=...
```

---

## Wiki (Living Knowledge Base)

```bash
# Regenerate all wiki pages from DB data
uv run python scripts/update_wiki.py

# Update a single strategy page
uv run python scripts/update_wiki.py --page strategies --strategy ev_news

# Ask a question — answer filed back into wiki
uv run python scripts/ask_wiki.py "what should I focus on this week?" --file-back
```

Wiki pages live in `wiki/` (gitignored, auto-generated). Rendered at `/wiki.html` on the dashboard.

---

## Live Trading

```bash
# Kill switch — cancel all open CLOB orders
uv run python scripts/kill_live.py

# Dry-run kill switch (shows what would be cancelled)
uv run python scripts/kill_live.py --dry-run

# Generate CLOB credentials from wallet private key (run once)
uv run python scripts/setup_clob_credentials.py
```

Live positions are stored in `trades` table with `mode=live`. Paper positions use `mode=paper`.

---

## Running Tests

```bash
uv run pytest tests/ -v
```

Tests use temporary directories and never touch the real database or backups.

---

## Key Resources

- Polymarket Gamma API: https://gamma-api.polymarket.com/markets
- Polymarket CLOB API: https://clob.polymarket.com
- Deribit API: https://docs.deribit.com
