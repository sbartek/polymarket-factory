# PPLayouts SQLite + Decision Logging Migration Plan — 2026-03-31

## Goal

Replace the current CSV-based paper-trading state with a safer, queryable, transaction-backed SQLite design.

This migration is motivated by:
- race-condition risk in `trades.csv`
- increasingly complex reporting needs
- desire for structured decision logging
- need to separate active vs legacy strategy behavior cleanly
- future strategy growth (`correlated_pairs`, basket tracking, richer audits)

---

## Executive decision

### We will do
- move core state to **SQLite**
- keep **shared core tables** for common entities
- add **strategy-specific detail tables** only where they provide real value
- add **structured decision logging**
- add **run tracking** and eventually **run locking**
- keep CSV only as an optional export / compatibility layer during migration

### We will not do
- per-strategy core trade tables
- fake partitioning-by-strategy as the main schema design
- immediate big-bang replacement of all code paths at once

---

## Why SQLite

SQLite is the right next step because it gives us:
- transactions
- atomic commits
- file locking
- safer concurrent reads/writes than CSV
- easy local deployment
- simple backup/export
- SQL querying for reports, audits, and research

It is a better fit than CSV and much lighter than introducing a server database.

---

## Guiding design principles

1. **One shared source of truth** for core portfolio state
2. **Append logs, don’t just overwrite state**
3. **Record decisions, not only trades**
4. **Use normalized tables for shared concepts**
5. **Add strategy-specific detail tables only when the data shape truly differs**
6. **Preserve migration safety** through staged rollout

---

# Proposed schema

## Core shared tables

## 1) `runs`
One row per runner execution.

Suggested fields:
- `id` TEXT PRIMARY KEY
- `started_at` TEXT NOT NULL
- `finished_at` TEXT
- `mode` TEXT NOT NULL  -- `live` | `dry_run` | `fast_dry_run`
- `status` TEXT NOT NULL -- `running` | `success` | `failed` | `aborted`
- `markets_fetched` INTEGER DEFAULT 0
- `closed_count` INTEGER DEFAULT 0
- `new_positions_count` INTEGER DEFAULT 0
- `notes` TEXT

Purpose:
- audit each execution
- support per-run reporting
- join all decisions/signals/trades back to a specific run

---

## 2) `trades`
Shared trade state across all strategies.

Suggested fields:
- `id` TEXT PRIMARY KEY
- `strategy` TEXT NOT NULL
- `market_id` TEXT NOT NULL
- `market_title` TEXT NOT NULL
- `outcome` TEXT NOT NULL
- `amount_usdc` REAL NOT NULL
- `entry_price` REAL NOT NULL
- `shares` REAL NOT NULL
- `opened_at` TEXT NOT NULL
- `closes` TEXT
- `url` TEXT
- `status` TEXT NOT NULL -- `open` | `closed`
- `exit_price` REAL DEFAULT 0
- `closed_at` TEXT
- `pnl_usdc` REAL DEFAULT 0
- `resolved_outcome` TEXT
- `notes` TEXT
- `run_id_opened` TEXT REFERENCES runs(id)
- `run_id_closed` TEXT REFERENCES runs(id)
- `lifecycle_group` TEXT -- snapshot like `active` | `legacy`
- `time_window` TEXT -- snapshot at open time
- `edge_type` TEXT -- snapshot at open time

Purpose:
- current source of truth for paper positions
- historical trade archive
- lifecycle snapshot protects reporting even if strategy metadata later changes

---

## 3) `signals`
All generated signals, whether executed or not.

Suggested fields:
- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `run_id` TEXT NOT NULL REFERENCES runs(id)
- `strategy` TEXT NOT NULL
- `market_id` TEXT NOT NULL
- `market_title` TEXT NOT NULL
- `outcome` TEXT NOT NULL
- `market_price` REAL NOT NULL
- `p_hat` REAL NOT NULL
- `ev_pp` REAL NOT NULL
- `confidence` TEXT
- `closes` TEXT
- `url` TEXT
- `rationale` TEXT
- `time_window` TEXT
- `edge_type` TEXT
- `decision_status` TEXT -- `opened` | `duplicate` | `tiny_size` | `capped` | `rejected` | `dry_run_open`

Purpose:
- measure strategy output quality, not just executed trades
- analyze whether filters are too strict or too permissive

---

## 4) `decisions`
Structured decision audit trail.

Suggested fields:
- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `run_id` TEXT NOT NULL REFERENCES runs(id)
- `strategy` TEXT
- `market_id` TEXT
- `decision_type` TEXT NOT NULL
- `decision` TEXT NOT NULL
- `reason` TEXT
- `details_json` TEXT
- `created_at` TEXT NOT NULL

Examples:
- `decision_type=cycle_skip`, `decision=skip`, `reason=fast_dry_run`
- `decision_type=duplicate_check`, `decision=skip`, `reason=already_open`
- `decision_type=size_check`, `decision=skip`, `reason=tiny_size`
- `decision_type=cap_check`, `decision=skip`, `reason=medium_window_cap_hit`
- `decision_type=execution`, `decision=open`, `reason=signal_passed_filters`
- `decision_type=resolution`, `decision=close`, `reason=market_resolved`

Purpose:
- answer “why didn’t this trade happen?”
- analyze blocked opportunities
- debug strategy behavior and runner policies

---

## 5) `run_logs`
Optional human-readable event log per run.

Suggested fields:
- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `run_id` TEXT NOT NULL REFERENCES runs(id)
- `level` TEXT NOT NULL -- `info` | `warn` | `error`
- `strategy` TEXT
- `message` TEXT NOT NULL
- `payload_json` TEXT
- `created_at` TEXT NOT NULL

Purpose:
- retain a timeline similar to current stdout logs
- easier debugging than scraping text output

---

# Strategy-specific detail tables

These are encouraged when useful, but only as supplements to shared core tables.

## `spread_arb_baskets`
Suggested fields:
- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `run_id` TEXT REFERENCES runs(id)
- `event_slug` TEXT
- `title` TEXT
- `leg_count` INTEGER
- `total_yes_sum` REAL
- `gap_pp` REAL
- `score` REAL
- `days_to_close` INTEGER
- `volume` REAL
- `decision` TEXT  -- `selected` | `rejected`
- `reason` TEXT

## `resolution_hunter_checks`
Suggested fields:
- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `run_id` TEXT REFERENCES runs(id)
- `market_slug` TEXT
- `candidate_score` REAL
- `news_count` INTEGER
- `claude_confidence` REAL
- `claude_outcome` TEXT
- `reason` TEXT
- `decision` TEXT

## `stale_market_checks`
Suggested fields:
- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `run_id` TEXT REFERENCES runs(id)
- `market_slug` TEXT
- `topic_key` TEXT
- `candidate_score` REAL
- `news_count` INTEGER
- `decision` TEXT
- `reason` TEXT

## `correlated_pairs_checks`
Suggested fields:
- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `run_id` TEXT REFERENCES runs(id)
- `slug_a` TEXT
- `slug_b` TEXT
- `relationship` TEXT
- `violation_pp` REAL
- `chosen_slug` TEXT
- `decision` TEXT
- `reason` TEXT

---

# Views

Instead of per-strategy core tables, create convenience views.

Examples:
- `open_trades`
- `active_open_trades`
- `legacy_open_trades`
- `signals_opened`
- `signals_skipped`
- `decisions_skipped`
- `trades_spread_arb` (view filtered on strategy)
- `trades_resolution_hunter`

This gives strategy-level convenience without breaking schema simplicity.

---

# Index plan

## `trades`
Indexes:
- `idx_trades_strategy`
- `idx_trades_status`
- `idx_trades_market_id`
- `idx_trades_opened_at`
- `idx_trades_strategy_status`
- `idx_trades_closes`

## `signals`
Indexes:
- `idx_signals_run_id`
- `idx_signals_strategy`
- `idx_signals_market_id`
- `idx_signals_decision_status`
- `idx_signals_strategy_run`

## `decisions`
Indexes:
- `idx_decisions_run_id`
- `idx_decisions_strategy`
- `idx_decisions_market_id`
- `idx_decisions_type`
- `idx_decisions_decision`
- `idx_decisions_run_strategy`

## strategy-specific detail tables
Index by:
- `run_id`
- primary lookup slug(s)
- `decision` where useful

---

# Concurrency / race-condition plan

SQLite helps, but we should also add run coordination.

## Minimum safety plan
- all write operations inside transactions
- one run row inserted at start, updated at finish
- trade open/close in atomic transaction

## Recommended run lock
Use one of:
- lock table with lease semantics
- lightweight lock file for live runs only

Recommended behavior:
- if a live run is already active, next live run exits cleanly
- dry runs remain read-only and can coexist

This avoids overlapping scheduled/manual live runs.

---

# Migration phases

## Phase 1 — Introduce SQLite alongside CSV

Deliverables:
- `factory/db.py`
- schema creation / migrations
- insert into `runs`
- insert into `decisions`
- insert into `signals`

Keep:
- trades still read/write from CSV for now

Why first:
- low-risk
- immediate observability wins
- no big trade-state cutover yet

Success criteria:
- every run recorded in DB
- every open/skip decision recorded in DB
- reports can start reading decision data if needed

---

## Phase 2 — Move `trades` to SQLite source of truth

Deliverables:
- broker reads/writes SQLite `trades`
- one-time CSV import script
- optional CSV export command for compatibility

Success criteria:
- runner no longer depends on `data/trades.csv`
- open/close is atomic and transaction-backed

---

## Phase 3 — Strategy-specific detail logging

Deliverables:
- `spread_arb_baskets`
- `resolution_hunter_checks`
- `stale_market_checks`
- `correlated_pairs_checks`

Success criteria:
- basket/pair/candidate research no longer depends on console output
- strategy tuning can use persisted detail records

---

Status: **DONE (2026-03-31)**

Delivered:
- `spread_arb_baskets`
- `resolution_hunter_checks`
- `stale_market_checks`
- `correlated_pairs_checks`
- runner hooks to persist strategy-specific details after scans

Outcome:
- strategy tuning no longer depends only on console output
- candidate/basket/pair reasoning is now queryable from SQLite

---

## Phase 4 — Reporting migration

Status: **MOSTLY DONE (2026-03-31)**

Delivered:
- portfolio summary effectively SQL-backed through SQLite-backed broker/trade state
- eval report reads through broker/SQLite path
- `/details` strategy output upgraded to use SQLite-backed data
- portfolio-level `/details` variants added:
  - `portfolio`
  - `legacy`
  - `latest`
- terminal query/report tooling added:
  - `latest_run.py`
  - `inspect_decisions.py`
  - `strategy_checks.py`
  - `open_positions.py`
  - `legacy_positions.py`
  - `run_analytics.py`

Remaining optional work:
- deeper SQL-native reporting for every view
- more portfolio-level analytics in chat-facing output

Outcome:
- operator visibility is now dramatically better
- ad hoc CSV inspection is no longer the normal path

---

## Phase 5 — Cleanup

Deliverables:
- deprecate CSV writes
- keep optional export tool only
- document DB backup and restore

---

# Decision logging plan

Every meaningful runner choice should emit a decision row.

## Must-log decision types
- run started
- run finished
- strategy skipped by cadence
- strategy skipped by fast dry run
- signal generated
- duplicate skip
- tiny size skip
- capped skip
- trade opened
- trade closed
- strategy error

## Nice-to-have detail payloads
Examples in `details_json`:
- cap numbers at time of rejection
- current exposure by strategy/window
- candidate score
- relationship classification
- basket score / leg count
- market price and p_hat snapshot

This makes the system explainable after the fact.

---

# Proposed file additions

- `factory/db.py`
- `factory/db_schema.sql` or migration helpers
- `scripts/import_trades_csv_to_sqlite.py`
- `scripts/export_trades_sqlite_to_csv.py`

Potential future:
- `scripts/inspect_run.py`
- `scripts/query_decisions.py`

---

# Rollout order I recommend

1. Add SQLite schema + `db.py`
2. Log `runs` + `decisions` + `signals`
3. Add run locking
4. Migrate broker/trades to SQLite
5. Add strategy detail tables
6. Migrate reports
7. Keep CSV only as export

---

# Risks and mitigations

## Risk: migration complexity
Mitigation:
- phased rollout
- keep CSV as fallback temporarily

## Risk: partial duplication during transition
Mitigation:
- make clear source-of-truth stage by stage
- document exactly what is authoritative at each phase

## Risk: dry-run pollution
Mitigation:
- `runs.mode` + `decision` flags clearly mark dry/fast dry
- no trade writes in dry mode

## Risk: schema churn from strategy evolution
Mitigation:
- keep core tables generic
- use detail tables for strategy-specific shape

---

# Bottom line

The right architecture is:
- **shared SQLite core tables** for runs, trades, signals, decisions
- **strategy-specific detail tables** only where the shape differs materially
- **views + indexes**, not per-strategy core trade tables
- **decision logging** as a first-class feature
- **run locking** to reduce overlap risk

This gives PPLayouts a safer state engine, better research visibility, and a path out of CSV fragility without turning the project into a database fetish object.
