# PR-20260403-003 — Live Trading Readiness Plan

**Goal:** Prepare polymarket-factory for real trades in ~4 weeks, while keeping paper runs as the default for new/experimental strategies.

**Model:** Two-track system — live broker for proven strategies, paper broker for everything else. Start tiny (~€50 USDC), validate the paper-to-live gap, scale only when gap is understood.

---

## Phase 1 — Infrastructure (Week 1)

### 1.1 Fund Polymarket wallet

- ~€50 USDC on Polygon via MetaMask
- Connect to Polymarket CLOB API: generate API keys from the UI
- Store in `.env`: `POLYMARKET_API_KEY`, `POLYMARKET_API_SECRET`, `POLYMARKET_PASSPHRASE`, `POLYMARKET_WALLET_PRIVATE_KEY`

### 1.2 CLOB API wrapper

Create `factory/clob.py` — thin wrapper around `py-clob-client`:
- `get_order_book(token_id)` — real bid/ask depth
- `place_market_order(token_id, side, amount_usdc)` — GTC market order
- `place_limit_order(token_id, side, size, price)` — FOK limit
- `get_open_orders()` — poll for fills
- `cancel_all()` — kill switch

This is the only new external dependency. Keep it isolated — nothing in strategies touches it directly.

### 1.3 LiveBroker implementation

Create `factory/live_broker.py` implementing the same `Broker` interface as `PaperBroker`:
- `open_position()` → calls `clob.place_market_order()`, stores actual fill price in DB
- `close_position()` → calls `clob.place_market_order()` on opposite side
- Hard position cap: refuse to open if total live exposure > $100
- Log every order with CLOB order ID for reconciliation

### 1.4 Health check + alerting

Add `factory/healthcheck.py`:
- Called at end of every runner cycle
- If no successful run in 6 hours → send WhatsApp alert
- If a strategy raises an exception → log + send alert (currently silent)
- If total live exposure > $80 → send alert

---

## Phase 2 — Validation (Weeks 1–2)

### 2.1 Claude calibration retrospective

Before trusting ev_news/resolution_hunter/stale_market with real money, measure Claude's actual accuracy:

```bash
uv run python scripts/claude_calibration.py
```

Script to write: for all closed trades where `signal.source == "claude"`, compare `signal.p_hat` to actual outcome. Compute:
- Mean calibration error (p̂ vs outcome)
- Brier score
- Edge over market price at signal time

**Gate:** If Claude's Brier score is not better than naive market price → do NOT put ev_news/stale_market on live. Only spread_arb and resolution_hunter (deterministic logic) go live first.

### 2.2 Slippage reality check

Run `scripts/signal_execution_checks.py` on last 30 days of signals. For each signal:
- What was the quoted bid/ask at signal time?
- What would actual fill have been at `fill_price_10` (smallest bucket)?
- How many signals were positive EV after realistic slippage?

**Gate:** If >30% of signals become negative EV after $10 slippage → position sizing is too aggressive. Halve `max_position_usdc` for that strategy.

### 2.3 Define graduation criteria for live

Write `docs/live_graduation.md`. A strategy needs ALL of:
- [ ] ≥ 15 closed paper trades
- [ ] Win rate ≥ 45%
- [ ] ROI ≥ 0% on paper
- [ ] Positive EV after slippage on ≥ 60% of signals (from execution snapshots)
- [ ] Manual review by Bartek — no obvious data snooping or edge case abuse
- [ ] `live_ready = True` set explicitly in strategy class

---

## Phase 3 — Live Trading (Weeks 2–3)

### 3.1 Runner dual-track mode

Update `runner.py` to route each strategy to the right broker:

```python
broker = LiveBroker() if strategy.live_ready and strategy.mode == "live" else PaperBroker()
```

Paper positions continue as normal. Live positions go to CLOB. Both log to the same SQLite DB with a `mode` column (`paper` | `live`).

### 3.2 First live strategies (candidates)

Based on current state, likely first to graduate:
- **`spread_arb`** — deterministic math, no Claude dependency, cleanest edge
- **`resolution_hunter`** — Claude-assisted but deterministic candidate scoring; moderate risk

Start with `max_position_usdc = 5.0` for both (vs paper's $25). Total live exposure cap: $50.

Do NOT put ev_news or stale_market on live until Claude calibration (2.1) passes.

### 3.3 Position sizing for live

Live sizing should be more conservative than paper:
- Use `fill_price_25` slippage estimate to check EV
- Minimum edge after slippage: 8pp (vs 10pp on paper)
- Hard max per position: $10 until 30 live trades completed

### 3.4 Kill switch

Add `scripts/kill_live.py` — cancels all open CLOB orders and sets `mode = "paper"` on all strategies with `live_ready = True`. One command to halt live trading entirely.

---

## Phase 4 — Parallel Tracks (Ongoing)

### 4.1 Paper = experiment track (no changes)

New strategies always start as `alert_only=True`, paper broker. The aggressive_strategy_cycle continues as-is. Paper results feed the graduation pipeline.

### 4.2 Live = proven track

Only strategies that passed the graduation checklist. Reviewed monthly. Positions stay small until gap between paper ROI and live ROI is measured and understood.

### 4.3 Monthly live calibration report

Extend `eval/report.py` to produce a live vs paper comparison:
- Live ROI vs paper ROI for the same strategy and period
- Mean slippage: estimated vs actual
- Fill rate: what % of signals actually got filled at signal price ± 2pp

This is the core feedback loop to understand if paper results are predictive of live results.

---

## Prioritized Task List

| # | Task | Phase | Effort | Blocker for live? |
|---|------|-------|--------|-------------------|
| 1 | Fund Polymarket wallet (~€50 USDC) | 1.1 | 30 min | YES |
| 2 | Create `factory/clob.py` wrapper | 1.2 | 2–3h | YES |
| 3 | Create `factory/live_broker.py` | 1.3 | 3–4h | YES |
| 4 | Runner dual-track routing | 3.1 | 1h | YES |
| 5 | Claude calibration script | 2.1 | 2h | YES (for LLM strategies) |
| 6 | Slippage reality check | 2.2 | 1h | Yes |
| 7 | Write `docs/live_graduation.md` | 2.3 | 30 min | Yes |
| 8 | Graduate spread_arb to live | 3.2 | 30 min | — |
| 9 | Kill switch script | 3.4 | 1h | No (but add before live) |
| 10 | Health check + alerting | 1.4 | 2h | No (but add before live) |
| 11 | Monthly live calibration report | 4.3 | 3h | No (post-live) |

---

## What Stays the Same

- Paper broker runs for all non-graduated strategies
- 3x/day launchd schedule unchanged
- WhatsApp summaries unchanged
- Dashboard unchanged
- Auto-generated strategies continue as alert-only paper experiments
- Aggressive strategy cycle continues (it's useful for ideas, just don't auto-promote to live)

---

## Risks to Manage

- **VPN**: Use API-based trading (not frontend). Residential IP VPN. Keep Polymarket account balance ≤ $50 and withdraw regularly.
- **Oracle risk**: UMA dispute process on Polymarket. Don't trade markets with ambiguous resolution criteria.
- **Spread arb execution**: Multi-leg positions may not fill simultaneously. Start with single-leg test trades before committing to full arb baskets.
- **Polish tax**: Prediction markets = gambling under Polish law. Keep records. 10% on net winnings > 2,280 PLN threshold.
