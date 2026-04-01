# Polymarket Factory

A framework for rapidly spinning up, paper-trading, and evaluating Polymarket investment strategies.

**Goal:** Find strategies with real edge. Paper-trade each for ~a week, evaluate against kill/keep thresholds, promote winners to live trading.

---

## Architecture

```
You (idea) → new file in factory/strategies/ → add to STRATEGIES registry → runs automatically
                                                                                ↓
                                                              runner.py (3x/day via launchd)
                                                                ├── fetch 100 top markets (Gamma API)
                                                                ├── each strategy: scan → signal → size → open position
                                                                ├── check open positions → close resolved ones
                                                                └── WhatsApp summary → Polymarket Signals group
```

**Stack:** Python 3.11+ · uv · Gamma API · DDGS news · Claude API · OpenClaw WhatsApp

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
    mode: str               # "paper" | "live"
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

---

## Strategy Roadmap

### Active (paper trading)

- [x] **`ev_news`** — Claude scans top markets + news headlines, picks topics, estimates p̂ per market from news.
- [x] **`spread_arb`** — Multi-outcome markets where sum of YES prices is materially below 1.0, with stricter practical filtering.
- [x] **`resolution_hunter`** — Looks for markets likely already resolved in the real world but not yet settled by the market.
- [x] **`stale_market`** — Looks for liquid near/medium-term markets whose prices appear stale versus recent news.
- [x] **`correlated_pairs`** — MVP for logically inconsistent market pairs (prerequisite vs downstream, broader vs narrower).
- [x] **`correlated_laggard`** — Alert-only MVP for liquid leader / laggard divergences across obviously related markets.
- [x] **`esport48`** — Alert-only screener for esport markets expiring within 48 hours, using deterministic liquidity/price filters and subtype tagging.

Current graduation status:
- `correlated_laggard`: alert-only, `promotable=True`, `trading_enabled=False`
- `esport48`: alert-only, `promotable=True`, `trading_enabled=False`

### Paused after early paper results

- [ ] **`fade_certainty`** — Paused after ugly early paper results.
- [ ] **`weather_edge`** — Paused after negative early paper results; maybe worth revisiting later as a much narrower v2.

### Planned — next builds

- [ ] **`polling_vs_market`**
- [ ] **`base_rate`**
- [ ] **`crypto_options_basis`**
- [ ] **`pre_event_drift`**

### Future (post-validation)

- [ ] Live trading via Polymarket CLOB API
- [ ] Strategy parameter tuning
- [ ] Multi-outcome market support improvements
- [ ] Portfolio-level risk limits refinement
- [ ] Full trade-state migration from CSV to SQLite

---

## Operations

```bash
# Show open book (all groups + full position list)
uv run python scripts/open_positions.py

# Show only the 5 oldest open positions
uv run python scripts/open_positions.py --top-oldest 5

# Filter by strategy
uv run python scripts/open_positions.py --strategy ev_news

# Filter by time window
uv run python scripts/open_positions.py --time-window medium

# Manual run
uv run python -m factory.runner

# Safe manual dry run (no writes, no closes, no sends)
uv run python -c "from factory.runner import run; run(dry_run=True)"

# Faster safe dry run for debugging the whole cycle
# (currently skips `ev_news` and trims other expensive strategy workloads)
uv run python -c "from factory.runner import run; run(dry_run=True, fast_dry_run=True)"

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

Local preview:

```bash
cd dashboard-dist
python3 -m http.server 8000
# then open /index.html?bundled=1
```

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

## Launchd

Main factory job:
- `com.polymarket.factory` — 09:30 / 14:30 / 19:30 CEST

Backup template included in repo:
- `launchd/com.polymarket.factory.backup.plist`
- default schedule: `03:45` daily

Logs:
- runner: `factory.log`
- backup job: `factory-backup.log`

`.env` (not committed):
```env
WHATSAPP_GROUP_ID=120363425524943226@g.us
```

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
