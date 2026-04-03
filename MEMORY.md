# Polymarket Factory — Claude Context

## What this project is

A framework for spinning up, paper-trading, and evaluating Polymarket prediction market strategies. The goal is to find strategies with real edge, paper-trade them, then promote winners to live trading.

Runs automatically via launchd on the `pplayouts` machine (Intel Mac, Tailscale IP 100.75.233.52). Dashboard at https://pplayouts-dashboard.bartekskorulski.workers.dev.

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

**Runtime environments:** `research` (signals only) · `paper` (default) · `live` (carry_rewards only)

**Key files:**
- `factory/runner.py` — main loop
- `factory/strategies/` — all strategy implementations
- `factory/strategy_meta.py` — exposure caps, cadence, active set
- `factory/broker.py` — paper broker (SQLite-backed)
- `factory/live_broker.py` — real CLOB execution, $100 hard cap
- `factory/feed.py` — Gamma API wrappers
- `factory/claude.py` — LLM wrapper (Anthropic API → Claude CLI → codex fallback)
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
| `ev_news` | information | medium | Claude scans news → p̂ estimate. 15 open, 0 closed. LLM-heavy. |
| `spread_arb` | structural | medium | Buy all legs when Σ(YES) < 0.93. 76 open, 3 closed. |
| `stale_market` | information | short | Claude judges stale markets vs news. 3 open, 2 closed. |
| `correlated_pairs` | logical_inconsistency | medium | Logically inconsistent pairs. Early eval. |
| `celebrity_tabloid` | information | short | Tabloid corroboration. 0 signals — top-100 feed lacks celebrity markets. |

### Alert-only (needs graduation checklist before paper trading)
| Strategy | Notes |
|----------|-------|
| `correlated_laggard` | Liquid leader/laggard divergence. `promotable=True`. See EX-20260401-006. |
| `esport48` | Esport markets <48h. `promotable=True`. See EX-20260401-007. |

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

---

## WhatsApp group

Group ID: `120363425524943226@g.us` (in `.env`). Members: Bartek + Pawel + Daniel.
Full summary at 09:00 Madrid time; delta updates at other runs.

---

## Known issues / active work (2026-04-03)

- `celebrity_tabloid` gets 0 signals — needs tag-filtered feed, not top-100
- `wiki/overview.md` is a duplicate of `wiki/meta/overview.md` — one should be removed
- Wiki pages missing for: `correlated_pairs`, `celebrity_tabloid`, `carry_rewards`
- Live broker has no partial-fill rollback (YES fills, NO fails → unhedged)
- No DB retention policy — `market_snapshot_archives` grows unbounded
- No Brier score tracking for LLM strategies (ev_news, stale_market)

---

## Context files

- `MEMORY.md` (this file) — full project context for Claude and codex
- `CLAUDE.md` — one-liner pointing here; auto-loaded by Claude Code
- No `AGENTS.md` yet — add one if codex needs auto-loading too

---

## Wiki system

Auto-generated from DB via Claude (Karpathy pattern). Pages in `wiki/` (gitignored).

```bash
uv run python scripts/update_wiki.py        # regenerate all pages
uv run python scripts/ask_wiki.py "question" --file-back  # Q&A filed into wiki
```

Wiki rendered at `/wiki.html` on dashboard.
