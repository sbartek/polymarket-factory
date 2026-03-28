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

**Stack:** Python 3.11+ · uv · Gamma API · DDGS news · Claude API (+ CLI fallback) · OpenClaw WhatsApp

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
           ...  # return list of Signal objects
   ```
2. Register in `factory/strategies/__init__.py`:
   ```python
   from .my_strategy import MyStrategy
   STRATEGIES = [..., MyStrategy()]
   ```
3. Test: `uv run python -m factory.runner`

---

## Strategy Interface

```python
class Strategy(ABC):
    name: str
    mode: str               # "paper" | "live"
    max_position_usdc: float
    min_ev_pp: float

    def scan(self, markets) -> list[Signal]   # find opportunities
    def size(self, signal) -> float           # Kelly sizing (override if needed)
    def should_exit(self, trade, price) -> bool  # early exit logic (default: hold to resolution)
```

---

## Evaluation

Run weekly: `uv run eval/report.py`

| Metric | Kill | Keep |
|--------|------|------|
| Win rate | < 30% | > 50% |
| ROI | < -10% | > 0% |
| Min trades to evaluate | 5 | — |

---

## Strategy Roadmap

### Active (paper trading)

- [x] **`ev_news`** — Claude scans top markets + news headlines, picks 3 topics, estimates p̂ per market from news. Min EV 10pp. LLM-heavy, 3 Claude calls/run.
- [x] **`fade_certainty`** — Statistical fade of markets >93% or <7%. Min volume $30K, 7–120 days to close, excludes price-oracle markets. No LLM. Fast.

### Planned — Week 2

- [ ] **`spread_arb`** — YES + NO prices should sum to ~$1. When they don't (gap > 2% fees), buy both sides for near risk-free arb. Fully mechanical, no LLM. *Priority: high — free money when it occurs.*

- [ ] **`resolution_hunter`** — Markets where the outcome is already known (event happened) but not yet officially settled. Still trading at 20–50% when it should be 0% or 100%. LLM cross-checks current facts vs market price. *Priority: high — potentially highest single-trade EV.*

### Planned — Week 3+

- [ ] **`polling_vs_market`** — For election markets: compare Polymarket price vs polling aggregates. Trade toward polls when gap > 10pp. No LLM beyond initial setup. Requires active election markets.

- [ ] **`base_rate`** — Statistical only: "what % of the time does this *type* of event occur?" (e.g., incumbent party loses X% of elections, central bank cuts when CPI > Z%). Compare historical frequency vs market price. No LLM.

- [ ] **`correlated_pairs`** — Find two logically linked markets priced inconsistently (e.g., "Trump imposes 50% tariffs on China" at 30% AND "US-China trade war escalates" at 75%). LLM identifies inconsistent pairs, trade the cheaper side.

- [ ] **`stale_market`** — Markets with no trades in 48h+ have stale prices. After relevant news, these reprice slowly. Find stale markets where news changes the outcome probability.

- [ ] **`crypto_options_basis`** — Compare Polymarket crypto price markets against Deribit options-implied probabilities (free API). Trade when they disagree by >10pp.

- [ ] **`pre_event_drift`** — Before scheduled events (Fed meeting, election day), markets drift toward 50% as uncertainty peaks. Buy the base-rate-favored side 3–5 days before.

### Future (post-validation)

- [ ] Live trading via Polymarket CLOB API (MetaMask + USDC on Polygon, ~€50 to start)
- [ ] Strategy parameter tuning (EV threshold, sizing, hold period)
- [ ] Multi-outcome market support (currently only binary YES/NO)
- [ ] Portfolio-level risk limits (max total exposure, max per-topic concentration)

---

## Operations

```bash
# Manual run
uv run python -m factory.runner

# Weekly evaluation
uv run eval/report.py

# Logs
tail -f factory.log

# Open positions
cat data/trades.csv
```

**LaunchAgent:** `com.polymarket.factory` — fires at 09:30 / 14:30 / 19:30 CEST.
Logs: `factory.log`. Trades: `data/trades.csv`.

`.env` (not committed):
```
WHATSAPP_GROUP_ID=120363425524943226@g.us
```

---

## Key Resources

- Polymarket Gamma API: https://gamma-api.polymarket.com/markets
- Polymarket CLOB API: https://clob.polymarket.com
- Deribit API (for crypto_options_basis): https://docs.deribit.com
