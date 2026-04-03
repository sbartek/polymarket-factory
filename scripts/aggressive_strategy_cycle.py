#!/usr/bin/env python3
"""Twice-daily aggressive evaluation + strategy generation cycle.

Flow:
1. Run evaluation report and capture text.
2. Summarize for dashboard.
3. Generate 2 new strategy proposals + alert-only strategy modules.
4. Refresh dashboard snapshot/bundle.

This is intentionally experimental and should be reviewed after one month.
"""
from __future__ import annotations

import importlib
import json
import os
import re
import subprocess
import sys
import shutil
from datetime import datetime
from pathlib import Path
from textwrap import dedent

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from factory.claude import call_claude

GENERATED_DIR = PROJECT_ROOT / "factory" / "strategies" / "generated"
GENERATED_ARCHIVE_DIR = GENERATED_DIR / "archive"
PROPOSALS_DIR = PROJECT_ROOT / "improvement" / "proposals"
DASHBOARD_DATA = PROJECT_ROOT / "dashboard-data"
EVAL_JSON = DASHBOARD_DATA / "evaluation.json"
BENCHMARK_DIR = PROJECT_ROOT / "benchmark-data"

GENERATED_RETENTION_GRACE_DAYS = 3
GENERATED_MIN_SIGNALS_FOR_GATE = 5
GENERATED_MIN_LABELED_FOR_GATE = 3
GENERATED_MIN_OBSERVED_SIGNALS_FOR_GATE = 3
GENERATED_MIN_OBSERVATION_COVERAGE = 0.30
GENERATED_MIN_BENCHMARK_SCORE = 0.60


def now_local() -> datetime:
    return datetime.now()


def run_cmd(args: list[str], env: dict | None = None) -> str:
    result = subprocess.run(args, cwd=PROJECT_ROOT, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"command failed: {' '.join(args)}")
    return result.stdout


def capture_eval_report() -> str:
    return run_cmd([sys.executable, str(PROJECT_ROOT / "eval" / "report.py")])


def next_daily_sequence(prefix: str) -> int:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    existing = sorted(GENERATED_DIR.glob(f"auto_{prefix}_*.py"))
    nums = []
    for path in existing:
        m = re.match(rf"auto_{prefix}_(\d+)", path.stem)
        if m:
            nums.append(int(m.group(1)))
    return (max(nums) + 1) if nums else 1


def slugify(text: str) -> str:
    return "_".join("".join(ch.lower() if ch.isalnum() else " " for ch in text).split())[:48] or "generated_strategy"


def class_name(name: str) -> str:
    return "".join(part.capitalize() for part in slugify(name).split("_")) + "Strategy"


def load_existing_strategy_names() -> list[str]:
    from factory.strategies import STRATEGIES
    return sorted({s.name for s in STRATEGIES})


def archived_module_name(module_name: str) -> str:
    stamp = now_local().strftime("%Y%m%d_%H%M%S")
    return f"{module_name}__archived_{stamp}.py"


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def generated_module_rows() -> list[dict]:
    rows = []
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(GENERATED_DIR.glob("auto_*.py")):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        name_match = re.search(r'^\s*name\s*=\s*"([^"]+)"', text, re.M)
        strategy_name = name_match.group(1) if name_match else path.stem
        rows.append({
            "module_name": path.stem,
            "strategy_name": strategy_name,
            "path": path,
            "mtime": datetime.fromtimestamp(path.stat().st_mtime),
        })
    return rows


def load_benchmark_scope(scope: str) -> dict:
    path = BENCHMARK_DIR / f"replay-benchmark-{scope}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def benchmark_lookup(scope: str) -> dict[str, dict]:
    payload = load_benchmark_scope(scope)
    return {
        row.get("strategy"): row
        for row in payload.get("strategies", [])
        if row.get("strategy")
    }


def proposal_paths_for_strategy(strategy_name: str) -> list[Path]:
    slug = slugify(strategy_name)
    return sorted(PROPOSALS_DIR.glob(f"PR-*-{slug}.md"))


def rewrite_proposal_status(paths: list[Path], *, status: str, note: str | None = None) -> None:
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        text = re.sub(r"(\- \*\*status:\*\*\s*)(.+)", rf"\1{status}", text, count=1)
        if note and note not in text:
            text = text.rstrip() + f"\n\n## Benchmark gate note\n\n{note}\n"
        path.write_text(text + ("\n" if not text.endswith("\n") else ""), encoding="utf-8")


def mark_generated_pending_review(row: dict, note: str) -> None:
    rewrite_proposal_status(
        proposal_paths_for_strategy(row["strategy_name"]),
        status="pending_benchmark_review",
        note=note,
    )


def archive_generated_module(row: dict, reason: str) -> dict:
    GENERATED_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    source = row["path"]
    target = GENERATED_ARCHIVE_DIR / archived_module_name(row["module_name"])
    shutil.move(str(source), str(target))
    proposal_paths = proposal_paths_for_strategy(row["strategy_name"])
    rewrite_proposal_status(proposal_paths, status="archived", note=f"Archived by benchmark gate: {reason}")
    return {
        "strategy_name": row["strategy_name"],
        "module": row["module_name"],
        "reason": reason,
        "archived_path": display_path(target),
        "proposal_paths": [display_path(p) for p in proposal_paths],
    }


def apply_generated_retention_gate() -> list[dict]:
    benchmark_rows = benchmark_lookup("generated")
    archived: list[dict] = []
    now = now_local()
    for row in generated_module_rows():
        age_days = (now - row["mtime"]).total_seconds() / 86400
        bench = benchmark_rows.get(row["strategy_name"])
        if bench:
            score = float(bench.get("benchmark_score") or 0.0)
            signals = int(bench.get("signals") or 0)
            labeled = int(bench.get("labeled_signals") or 0)
            observed = int(bench.get("observed_signals") or 0)
            observation_coverage = float(bench.get("observation_coverage") or 0.0)
            if (
                signals >= GENERATED_MIN_SIGNALS_FOR_GATE
                and labeled >= GENERATED_MIN_LABELED_FOR_GATE
                and observed >= GENERATED_MIN_OBSERVED_SIGNALS_FOR_GATE
                and observation_coverage >= GENERATED_MIN_OBSERVATION_COVERAGE
                and score < GENERATED_MIN_BENCHMARK_SCORE
            ):
                archived.append(archive_generated_module(
                    row,
                    f"benchmark_score {score:.3f} below {GENERATED_MIN_BENCHMARK_SCORE:.2f} with {signals} signals / {observed} observed / {labeled} labeled",
                ))
                continue
            if score < GENERATED_MIN_BENCHMARK_SCORE:
                insufficiency = []
                if signals < GENERATED_MIN_SIGNALS_FOR_GATE:
                    insufficiency.append(f"{signals} signals<{GENERATED_MIN_SIGNALS_FOR_GATE}")
                if observed < GENERATED_MIN_OBSERVED_SIGNALS_FOR_GATE:
                    insufficiency.append(f"{observed} observed<{GENERATED_MIN_OBSERVED_SIGNALS_FOR_GATE}")
                if labeled < GENERATED_MIN_LABELED_FOR_GATE:
                    insufficiency.append(f"{labeled} labeled<{GENERATED_MIN_LABELED_FOR_GATE}")
                if observation_coverage < GENERATED_MIN_OBSERVATION_COVERAGE:
                    insufficiency.append(
                        f"obs_cov {observation_coverage:.2f}<{GENERATED_MIN_OBSERVATION_COVERAGE:.2f}"
                    )
                if insufficiency:
                    mark_generated_pending_review(
                        row,
                        "Benchmark evidence still too thin for archive decision: " + ", ".join(insufficiency),
                    )
        if age_days >= GENERATED_RETENTION_GRACE_DAYS and not bench:
            archived.append(archive_generated_module(
                row,
                f"no generated benchmark evidence after {GENERATED_RETENTION_GRACE_DAYS} days",
            ))
    return archived


def _extract_json_block(raw: str, starts_with: str) -> str:
    text = (raw or "").strip()
    if not text:
        raise RuntimeError("model returned empty output")
    fenced = re.findall(r"```(?:json)?\s*(.*?)```", text, re.S)
    for block in fenced:
        block = block.strip()
        if block.startswith(starts_with):
            return block
    m = re.search(r"\[.*\]", text, re.S) if starts_with == "[" else re.search(r"\{.*\}", text, re.S)
    if m:
        return m.group(0)
    raise RuntimeError(f"could not extract JSON block from model output: {text[:400]}")


def fallback_strategy_specs() -> list[dict]:
    prefix = now_local().strftime("%Y%m%d")
    return [
        {
            "name": f"stale_market_micro_{prefix}",
            "title": "Stale-market microcap variation with tighter repricing window",
            "edge_type": "stale_repricing",
            "time_window": "intraday",
            "thesis": "Some smaller but still tradable markets may lag repricing longer than the current stale_market filter allows, especially when topic overlap is obvious but liquidity is only moderate.",
            "market_types": "headline-driven binary markets",
            "likely_inputs": "Gamma top snapshot, title matching, basic price/volume filters",
            "entry_logic": "Look for moderate-volume markets with obvious topic overlap, non-extreme prices, and a narrower hold window than stale_market.",
            "exit_logic": "Alert-only initially; later review whether these should mean-revert quickly or hold into the next repricing leg.",
            "failure_modes": ["dead-book false positives", "topic matching too loose", "low capacity despite decent edge", "overlap with stale_market causing duplicate alerts"],
            "validation_plan": "Alert-only for first month; compare alert quality against stale_market and inspect Phase A execution checks before any promotion.",
        },
        {
            "name": f"resolution_hunter_conservative_{prefix}",
            "title": "Resolution-hunter conservative variation with stricter certainty gating",
            "edge_type": "resolution_lag",
            "time_window": "short",
            "thesis": "The current resolution_hunter may be too permissive; a stricter version could surface fewer but cleaner near-resolution opportunities where the market lags obvious settlement direction.",
            "market_types": "near-resolution event markets",
            "likely_inputs": "closed/open market snapshot, title filters, simple certainty screens",
            "entry_logic": "Require stronger evidence and narrower market states before raising an alert; prefer cases where ambiguity appears materially lower than price implies.",
            "exit_logic": "Hold logic remains resolution-focused; promotion only if alerts are materially cleaner than the base strategy.",
            "failure_modes": ["too few opportunities", "false sense of certainty", "headline ambiguity near resolution", "better precision but negligible capacity"],
            "validation_plan": "Run side-by-side with resolution_hunter as alert-only for one month; compare alert precision and Phase A execution realism.",
        },
    ]


def generate_strategy_specs(eval_text: str) -> list[dict]:
    existing = ", ".join(load_existing_strategy_names())
    prompt = dedent(f"""
    You are generating two NEW Polymarket strategy ideas for an experimental research repo.

    Existing strategies:
    {existing}

    Recent evaluation report:
    {eval_text[:12000]}

    Requirements:
    - Return EXACTLY 2 strategy specs as JSON array.
    - New ideas can be variations of existing ideas, but must be distinct.
    - Prefer concrete, auditable ideas over vague LLM fantasies.
    - Include realistic caveats about fillability/capacity when relevant.
    - Keep them suitable for initial ALERT-ONLY implementation.

    Each object must have:
    - name
    - title
    - edge_type (one of: information, structural, resolution_lag, stale_repricing, logical_inconsistency, model_vs_market, statistical_fade, other)
    - time_window (one of: super_short, intraday, short, medium, long)
    - thesis
    - market_types
    - likely_inputs
    - entry_logic
    - exit_logic
    - failure_modes (array of 3-6 short strings)
    - validation_plan

    Return JSON only.
    """)
    try:
        raw = call_claude(prompt, max_tokens=3000)
        payload = _extract_json_block(raw, "[")
        specs = json.loads(payload)
        if not isinstance(specs, list) or len(specs) != 2:
            raise RuntimeError("expected exactly 2 strategy specs")
        return specs
    except Exception:
        return fallback_strategy_specs()


def build_proposal_markdown(spec: dict, proposal_id: str, date_human: str) -> str:
    failures = "\n".join(f"- {item}" for item in spec.get("failure_modes", [])) or "- review needed"
    return dedent(f"""
    # Strategy Proposal

    - **proposal_id:** {proposal_id}
    - **date:** {date_human}
    - **proposed_by:** aggressive_strategy_cycle
    - **status:** pending_benchmark_review

    ## Plain-language idea

    {spec['title']}

    ## Structured thesis

    {spec['thesis']}

    ## Candidate metadata

    - **proposed_name:** {spec['name']}
    - **edge_type:** {spec['edge_type']}
    - **time_window:** {spec['time_window']}
    - **market_types:** {spec['market_types']}
    - **likely_inputs:** {spec['likely_inputs']}

    ## Candidate logic

    ### Entry

    {spec['entry_logic']}

    ### Exit / hold

    {spec['exit_logic']}

    ## Expected failure modes

    {failures}

    ## Validation plan

    {spec['validation_plan']}

    ## Open questions for review

    - aggressive auto-generated candidate

    ## Approval note

    Generated automatically under the aggressive strategy experiment.
    Retention now depends on replay-benchmark evidence or explicit review.
    """).strip() + "\n"


def generate_strategy_code(spec: dict, module_name: str) -> str:
    strategy_class = class_name(spec['name'])
    edge_type = spec['edge_type']
    time_window = spec['time_window']
    min_days, max_days = {
        'super_short': (0.01, 0.04),
        'intraday': (0.05, 1.0),
        'short': (1.0, 7.0),
        'medium': (7.0, 30.0),
        'long': (30.0, 90.0),
    }.get(time_window, (1.0, 7.0))
    comment = json.dumps({
        'title': spec['title'],
        'thesis': spec['thesis'],
        'market_types': spec['market_types'],
        'entry_logic': spec['entry_logic'],
        'exit_logic': spec['exit_logic'],
        'failure_modes': spec['failure_modes'],
    }, ensure_ascii=False)
    return dedent(f'''"""
Auto-generated strategy: {spec['name']}
Generated by aggressive_strategy_cycle.py.

This strategy is intentionally ALERT-ONLY on creation.
It must earn promotion later.

Design notes:
{comment}
"""
from __future__ import annotations

from datetime import date

from ..base import Strategy
from ...feed import event_url, get_yes_price
from ...models import Signal

MIN_VOLUME = 10000
MIN_PRICE = 0.12
MAX_PRICE = 0.88
MAX_SIGNALS = 3


def _days_to_close(end_date: str | None) -> int | None:
    if not end_date:
        return None
    try:
        return (date.fromisoformat(end_date[:10]) - date.today()).days
    except ValueError:
        return None


class {strategy_class}(Strategy):
    name = "{spec['name']}"
    alert_only = True
    trading_enabled = False
    promotable = False
    live_ready = False
    promotion_criteria = ""
    edge_type = "{edge_type}"
    time_window = "{time_window}"
    target_hold_min_days = {min_days}
    target_hold_max_days = {max_days}
    scan_frequency = "auto-generated"
    paused = False
    min_ev_pp = 8.0
    last_check_details: list[dict] = []

    def _eligible(self, ev: dict) -> dict | None:
        title = str(ev.get("title") or "")
        slug = str(ev.get("slug") or ev.get("id") or "")
        if not slug or not title:
            return None
        volume = float(ev.get("volume24hr") or ev.get("volume") or 0)
        if volume < MIN_VOLUME:
            return None
        price = get_yes_price(ev)
        if price is None or not (MIN_PRICE <= price <= MAX_PRICE):
            return None
        days = _days_to_close(ev.get("endDate"))
        if days is None or days < 0:
            return None
        text = title.lower()
        keywords = {json.dumps([w for w in slugify(spec['title']).split('_') if len(w) >= 4][:8])}
        matches = sum(1 for kw in keywords if kw in text)
        if matches == 0:
            return None
        return {{
            "slug": slug,
            "title": title,
            "price": price,
            "volume": volume,
            "days": days,
            "matches": matches,
            "url": event_url(ev),
            "closes": (ev.get("endDate") or "")[:10],
        }}

    def scan(self, markets: list[dict]) -> list[Signal]:
        self.last_check_details = []
        candidates = []
        for ev in markets:
            row = self._eligible(ev)
            if row:
                candidates.append(row)
        candidates.sort(key=lambda row: (-row["matches"], -row["volume"], abs(row["price"] - 0.5)))
        signals: list[Signal] = []
        for row in candidates[:MAX_SIGNALS]:
            pull = min(0.03 + 0.01 * row["matches"], 0.10)
            if row["price"] < 0.5:
                outcome = "YES"
                market_price = row["price"]
                p_hat = min(row["price"] + pull, 0.95)
            else:
                outcome = "NO"
                market_price = 1 - row["price"]
                p_hat = min((1 - row["price"]) + pull, 0.95)
            ev_pp = round((p_hat - market_price) * 100, 1)
            decision = "alert" if ev_pp >= self.min_ev_pp else "watch"
            self.last_check_details.append({{
                "market_slug": row["slug"],
                "title": row["title"][:120],
                "topic_key": "{spec['name']}",
                "candidate_score": row["matches"],
                "news_count": 0,
                "decision": decision,
                "reason": "auto_generated_keyword_match",
            }})
            if decision != "alert":
                continue
            signals.append(Signal(
                strategy=self.name,
                market_id=row["slug"],
                market_title=row["title"][:100],
                outcome=outcome,
                market_price=round(market_price, 4),
                p_hat=round(p_hat, 4),
                ev_pp=ev_pp,
                confidence="low",
                closes=row["closes"],
                url=row["url"],
                rationale="auto_generated_alert_only",
            ))
        print(f"  [{{self.name}}] {{len(signals)}} alerts (auto-generated)")
        return signals
''')


def write_generated_strategy(spec: dict, prefix: str, seq: int) -> dict:
    safe_name = slugify(spec['name'])
    module_name = f"auto_{prefix}_{seq:03d}_{safe_name}"
    proposal_id = f"PR-{prefix}-{seq:03d}"
    date_human = f"{prefix[:4]}-{prefix[4:6]}-{prefix[6:]}"

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)

    py_path = GENERATED_DIR / f"{module_name}.py"
    md_path = PROPOSALS_DIR / f"{proposal_id}-{safe_name}.md"

    py_path.write_text(generate_strategy_code(spec, module_name), encoding="utf-8")
    md_path.write_text(build_proposal_markdown(spec, proposal_id, date_human), encoding="utf-8")
    return {
        "module": module_name,
        "strategy_name": spec['name'],
        "title": spec['title'],
        "path": str(py_path.relative_to(PROJECT_ROOT)),
        "proposal_path": str(md_path.relative_to(PROJECT_ROOT)),
        "time_window": spec['time_window'],
        "edge_type": spec['edge_type'],
    }


def summarize_eval(eval_text: str, generated: list[dict], archived: list[dict]) -> dict:
    prompt = dedent(f"""
    Summarize this strategy evaluation report for a static dashboard.
    Keep it compact and operational.

    Evaluation report:
    {eval_text[:12000]}

    Newly generated strategies:
    {json.dumps(generated, ensure_ascii=False, indent=2)}

    Archived generated strategies:
    {json.dumps(archived, ensure_ascii=False, indent=2)}

    Return JSON object with:
    - generated_at
    - headline
    - summary_lines (array of 3-6 short strings)
    - new_strategies (array of short strings)
    - archived_strategies (array of short strings)
    - risk_note
    JSON only.
    """)
    try:
        raw = call_claude(prompt, max_tokens=1200)
        payload = _extract_json_block(raw, "{")
        data = json.loads(payload)
    except Exception:
        data = {
            "headline": "Aggressive evaluation cycle completed",
            "summary_lines": [
                "Weekly evaluation report was captured and reviewed.",
                "Two new alert-only strategy variants were generated automatically.",
                "Older generated strategies may be archived when benchmark evidence is missing or weak.",
                "Dashboard was refreshed for the current cycle.",
            ],
            "new_strategies": [f"{row['strategy_name']} ({row['edge_type']}/{row['time_window']})" for row in generated],
            "archived_strategies": [f"{row['strategy_name']} — {row['reason']}" for row in archived],
            "risk_note": "Generated strategy retention is now benchmark-gated rather than auto-approved.",
        }
    data["generated_at"] = now_local().isoformat(timespec="seconds")
    return data


def refresh_dashboard() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = "."
    run_cmd([str(PROJECT_ROOT / ".venv" / "bin" / "python"), "scripts/build_replay_benchmark.py", "--scope", "alert-only"], env=env)
    run_cmd([str(PROJECT_ROOT / ".venv" / "bin" / "python"), "scripts/build_replay_benchmark.py", "--scope", "generated"], env=env)
    run_cmd([str(PROJECT_ROOT / ".venv" / "bin" / "python"), "scripts/export_dashboard_data.py"], env=env)
    run_cmd([str(PROJECT_ROOT / ".venv" / "bin" / "python"), "scripts/build_dashboard.py"], env=env)


def main() -> None:
    prefix = now_local().strftime("%Y%m%d")
    seq = next_daily_sequence(prefix)
    archived = apply_generated_retention_gate()
    eval_text = capture_eval_report()
    specs = generate_strategy_specs(eval_text)
    generated = []
    for idx, spec in enumerate(specs, start=seq):
        generated.append(write_generated_strategy(spec, prefix, idx))
    summary = summarize_eval(eval_text, generated, archived)
    DASHBOARD_DATA.mkdir(parents=True, exist_ok=True)
    EVAL_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    importlib.invalidate_caches()
    refresh_dashboard()
    print(json.dumps({"generated": generated, "archived": archived, "evaluation": summary}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
