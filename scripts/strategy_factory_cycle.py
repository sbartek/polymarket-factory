#!/usr/bin/env python3
"""Twice-daily strategy factory: evaluation + strategy generation cycle.

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
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from textwrap import dedent

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from factory.claude import call_claude

# Remote API mode: set FACTORY_REMOTE_API_URL to fetch eval + benchmarks from the VM API
# instead of reading local SQLite. Used when running strategy factory on Mac.
REMOTE_API_URL = os.environ.get("FACTORY_REMOTE_API_URL", "").rstrip("/")
REMOTE_API_KEY = os.environ.get("FACTORY_API_KEY", "")
REMOTE_API_RETRY_DELAYS_SECONDS = (2, 5)
REMOTE_API_DEFAULT_TIMEOUT = 60

GENERATED_DIR = PROJECT_ROOT / "factory" / "strategies" / "generated"
GENERATED_ARCHIVE_DIR = GENERATED_DIR / "archive"
PROPOSALS_DIR = PROJECT_ROOT / "improvement" / "proposals"
DASHBOARD_DATA = PROJECT_ROOT / "dashboard-data"
EVAL_JSON = DASHBOARD_DATA / "evaluation.json"
EVAL_REPORT_CACHE = DASHBOARD_DATA / "last_eval_report.txt"
STRATEGY_FACTORY_META_JSON = DASHBOARD_DATA / "strategy_factory_cycle_meta.json"
BENCHMARK_DIR = PROJECT_ROOT / "benchmark-data"

GENERATED_RETENTION_GRACE_DAYS = 3
GENERATED_MAX_TTL_DAYS = 14  # hard expiry even with insufficient benchmark evidence
GENERATED_MIN_SIGNALS_FOR_GATE = 5
GENERATED_MIN_LABELED_FOR_GATE = 3
GENERATED_MIN_OBSERVED_SIGNALS_FOR_GATE = 3
GENERATED_MIN_OBSERVATION_COVERAGE = 0.30
GENERATED_MIN_BENCHMARK_SCORE = 0.60
LAST_EVAL_SOURCE = "unknown"
LAST_BENCHMARK_FETCHES: list[dict] = []
LAST_GENERATION_SKIPPED_REASON: str | None = None


def now_local() -> datetime:
    return datetime.now()


def run_cmd(args: list[str], env: dict | None = None) -> str:
    result = subprocess.run(args, cwd=PROJECT_ROOT, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"command failed: {' '.join(args)}")
    return result.stdout


def _api_get(path: str, *, timeout: int = REMOTE_API_DEFAULT_TIMEOUT) -> bytes:
    url = f"{REMOTE_API_URL}{path}"
    req = urllib.request.Request(url, headers={"x-api-key": REMOTE_API_KEY})
    attempts = len(REMOTE_API_RETRY_DELAYS_SECONDS) + 1
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            retryable = exc.code == 429 or exc.code >= 500
            if attempt >= attempts or not retryable:
                raise
            delay = REMOTE_API_RETRY_DELAYS_SECONDS[attempt - 1]
            print(f"[remote] {path} returned HTTP {exc.code}; retrying in {delay}s ({attempt}/{attempts})")
            time.sleep(delay)
        except (TimeoutError, urllib.error.URLError) as exc:
            if attempt >= attempts:
                raise
            delay = REMOTE_API_RETRY_DELAYS_SECONDS[attempt - 1]
            print(f"[remote] {path} request failed ({exc.__class__.__name__}); retrying in {delay}s ({attempt}/{attempts})")
            time.sleep(delay)
    raise RuntimeError(f"remote request failed unexpectedly for {path}")


def fetch_benchmarks_remote() -> None:
    """Fetch benchmark JSONs from the VM API and write them to benchmark-data/."""
    global LAST_BENCHMARK_FETCHES
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    LAST_BENCHMARK_FETCHES = []
    for scope in ("alert-only", "generated"):
        data = _api_get(f"/benchmark/{scope}")
        (BENCHMARK_DIR / f"replay-benchmark-{scope}.json").write_bytes(data)
        LAST_BENCHMARK_FETCHES.append({
            "scope": scope,
            "source": "remote",
            "bytes": len(data),
            "fetched_at": now_local().isoformat(timespec="seconds"),
        })
        print(f"[remote] fetched benchmark/{scope} ({len(data)} bytes)")


def capture_eval_report() -> str:
    global LAST_EVAL_SOURCE
    if REMOTE_API_URL:
        print("[remote] fetching eval report from API...")
        try:
            text = _api_get("/eval").decode("utf-8")
            EVAL_REPORT_CACHE.parent.mkdir(parents=True, exist_ok=True)
            EVAL_REPORT_CACHE.write_text(text, encoding="utf-8")
            LAST_EVAL_SOURCE = "remote"
            return text
        except Exception as exc:
            if EVAL_REPORT_CACHE.exists():
                print(f"[remote] /eval failed ({exc.__class__.__name__}); using cached eval report from {display_path(EVAL_REPORT_CACHE)}")
                LAST_EVAL_SOURCE = "cache"
                return EVAL_REPORT_CACHE.read_text(encoding="utf-8")
            raise
    text = run_cmd([sys.executable, str(PROJECT_ROOT / "eval" / "report.py")])
    EVAL_REPORT_CACHE.parent.mkdir(parents=True, exist_ok=True)
    EVAL_REPORT_CACHE.write_text(text, encoding="utf-8")
    LAST_EVAL_SOURCE = "local"
    return text


def generation_skip_reason() -> str | None:
    if REMOTE_API_URL and LAST_EVAL_SOURCE == "cache":
        return "remote eval unavailable; using cached eval report"
    if REMOTE_API_URL and len(LAST_BENCHMARK_FETCHES) < 2:
        return "remote benchmark fetch incomplete"
    return None


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


def _paused_scan_body() -> str:
    """Scan body used when LLM code gen fails — strategy registers but produces no signals."""
    return (
        "def _eligible(self, ev: dict) -> dict | None:\n"
        "    return None  # paused — awaiting proper scan logic\n"
        "\n"
        "def scan(self, markets: list[dict]) -> list[Signal]:\n"
        "    print(f'  [{self.name}] 0 alerts (paused — no scan logic generated)')\n"
        "    return []"
    )


def _indent_for_class(body: str) -> str:
    """Add 4-space indent to method source for placement inside a class body."""
    result = []
    for line in body.splitlines():
        result.append("    " + line if line.strip() else "")
    return "\n".join(result)


def _generate_scan_body(spec: dict) -> str | None:
    """Ask Claude to write _eligible() and scan() for this spec.
    Returns raw method source (pre-class-indent) or None on failure."""
    ref_path = PROJECT_ROOT / "factory" / "strategies" / "fade_certainty_v2.py"
    ref_text = ref_path.read_text(encoding="utf-8") if ref_path.exists() else ""

    prompt = dedent(f"""
    Write Python scan logic for a Polymarket alert-only trading strategy.

    Strategy spec:
      name: {spec['name']}
      thesis: {spec['thesis']}
      entry_logic: {spec['entry_logic']}
      likely_inputs: {spec['likely_inputs']}
      market_types: {spec['market_types']}

    Each market event dict (ev) has:
      ev['title'] str, ev['slug'] str, ev['id'] str, ev['endDate'] str (ISO date),
      ev['volume24hr'] float, ev['volume'] float,
      ev['markets'] list — each sub-market has:
        m['id'], m['question'] str, m['closed'] bool,
        m['outcomePrices'] JSON str "[yes_price, no_price]"

    Already imported in the module: date (from datetime), event_url, get_yes_price, Signal, Strategy
    Helpers: event_url(ev) -> str, get_yes_price(ev) -> float | None
    Signal fields: strategy, market_id, market_title, outcome ("YES" or "NO"),
                   market_price, p_hat, ev_pp, confidence, closes, url, rationale
    Module constant: MAX_SIGNALS = 3

    Reference pattern to follow:
    ```python
    {ref_text[:2500]}
    ```

    Rules:
    - NO external API calls (no requests, no urllib, no HTTP of any kind)
    - Use only data from the ev dict and the helpers above
    - p_hat must be derived from market structure, NOT market_price + constant
    - End scan() with: print(f"  [{{self.name}}] {{len(signals)}} alerts (auto-generated)")
    - Return at most MAX_SIGNALS signals
    - Keep logic simple and directly implementable from available data

    Return ONLY the two methods with 4-space indentation (no class header, no imports):
    ```python
    def _eligible(self, ev: dict) -> dict | None:
        ...

    def scan(self, markets: list[dict]) -> list[Signal]:
        ...
    ```
    """).strip()

    try:
        raw = call_claude(prompt, max_tokens=2500, timeout=90)
        blocks = re.findall(r"```(?:python)?\s*(.*?)```", raw, re.S)
        for block in blocks:
            block = block.strip()
            if "def scan(" in block and "def _eligible(" in block:
                if re.search(r"\brequests\b|\burllib\b", block):
                    print(f"  [factory] rejecting scan body for {spec['name']} — uses HTTP calls")
                    return None
                return block
    except Exception as e:
        print(f"  [factory] LLM code gen error for {spec['name']}: {e}")
    return None


def _smoke_test_generated(py_path: Path, strategy_name: str) -> bool:
    """Return True if the module imports cleanly and scan([]) returns a list."""
    import py_compile
    import sys
    try:
        py_compile.compile(str(py_path), doraise=True)
    except py_compile.PyCompileError as e:
        print(f"  [factory] syntax error in {py_path.name}: {e}")
        return False
    module_name = f"factory.strategies.generated.{py_path.stem}"
    # Remove any cached version to ensure we load the freshly written file
    sys.modules.pop(module_name, None)
    try:
        import importlib
        importlib.invalidate_caches()
        mod = importlib.import_module(module_name)
        for attr_name in dir(mod):
            attr = getattr(mod, attr_name)
            if (isinstance(attr, type) and attr.__name__ != "Strategy"
                    and hasattr(attr, "scan") and callable(getattr(attr, "scan", None))):
                try:
                    result = attr().scan([])
                    if isinstance(result, list):
                        return True
                except Exception:
                    continue
    except Exception as e:
        print(f"  [factory] smoke test failed for {strategy_name}: {e}")
    return False


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
                    if age_days >= GENERATED_MAX_TTL_DAYS:
                        archived.append(archive_generated_module(
                            row,
                            f"hard TTL {GENERATED_MAX_TTL_DAYS}d expired with insufficient evidence: " + ", ".join(insufficiency),
                        ))
                        continue
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
    """Fallback when Claude fails to generate specs. Returns empty list to avoid
    generating the same stale_market_micro/resolution_hunter_conservative stubs
    that have been rejected dozens of times."""
    print("  [factory] LLM spec generation failed — skipping (no fallback stubs)")
    return []


def _build_strategy_history_context() -> str:
    """Build context about previously generated, rejected, and manually-built strategies."""
    # Previously generated names (from generated/ dir including archive)
    generated_dir = PROJECT_ROOT / "factory" / "strategies" / "generated"
    archive_dir = generated_dir / "archive"
    previously_generated = set()
    for d in [generated_dir, archive_dir]:
        if d.exists():
            for p in d.glob("auto_*.py"):
                name_match = re.search(r'name\s*=\s*"([^"]+)"', p.read_text(encoding="utf-8"))
                if name_match:
                    previously_generated.add(name_match.group(1))

    # Proposals dir — count how many times each base idea appeared
    proposals_dir = PROJECT_ROOT / "improvement" / "proposals"
    idea_counts: dict[str, int] = {}
    if proposals_dir.exists():
        for p in proposals_dir.glob("PR-*.md"):
            name = p.stem.split("-", 3)[-1] if "-" in p.stem else p.stem
            # Normalize: strip date suffixes like _20260414
            base = re.sub(r"_\d{8}(_gen)?$", "", name)
            idea_counts[base] = idea_counts.get(base, 0) + 1

    repeated = {k: v for k, v in idea_counts.items() if v >= 3}

    lines = []
    if repeated:
        lines.append("REJECTED IDEAS (generated 3+ times, always empty stubs, do NOT propose again):")
        for name, count in sorted(repeated.items(), key=lambda x: -x[1]):
            lines.append(f"  - {name} ({count} times)")

    lines.append("\nMANUALLY BUILT strategies (working, do not duplicate their concepts):")
    lines.append("  - stale_market: LLM judges if market lags news (profitable, +$10)")
    lines.append("  - ev_news: LLM estimates p_hat from DuckDuckGo news (profitable)")
    lines.append("  - spread_arb_v2: multi-outcome oversum arbitrage (profitable, +$15)")
    lines.append("  - price_move_fade: fade large price moves on short-term markets (80% WR)")
    lines.append("  - thin_market_impact_fade: fade transient impact on thin books (77% accuracy)")
    lines.append("  - conditional_probability_mispricing: nested threshold/deadline/stage violations (100% so far)")
    lines.append("  - expiry_convergence_buy: buy 75-92% leaders 3-7 days from expiry (new)")
    lines.append("  - overnight_gap_fade: fade overnight thin-book moves (20% accuracy — failing)")
    lines.append("  - volume_divergence_stale: triple-confirmation stale detection (0 signals — too strict)")
    lines.append("  - esport48: Pinnacle odds comparison via OddsPapi (new, awaiting data)")
    lines.append("  - base_rate_knn: semantic embedding kNN base rate estimation (new)")
    lines.append("  - weather strategies (6): ECMWF ensemble temperature forecasts (parsing fixed)")
    lines.append("  - correlated_laggard: token-overlap market pairing (improved matching)")
    lines.append("  - resolution_hunter_v2: LLM resolution detection (50% accuracy)")
    lines.append("  - celebrity_tabloid: gossip corroboration from tabloid sites")
    lines.append("  - polling_vs_market: polling data vs market price (+$20, tiny sample)")

    return "\n".join(lines)


def generate_strategy_specs(eval_text: str) -> list[dict]:
    existing = ", ".join(load_existing_strategy_names())
    history_context = _build_strategy_history_context()
    prompt = dedent(f"""
    You are generating two NEW Polymarket strategy ideas for an experimental research repo.

    Existing strategies:
    {existing}

    {history_context}

    Recent evaluation report:
    {eval_text[:8000]}

    Requirements:
    - Return EXACTLY 2 strategy specs as JSON array.
    - DO NOT propose strategies that overlap with the manually-built ones listed above.
    - DO NOT propose ideas from the REJECTED list — they have been tried and failed.
    - Each idea must be genuinely novel — a different edge type, data source, or market segment.
    - Prefer concrete, auditable ideas over vague LLM fantasies.
    - Include realistic caveats about fillability/capacity when relevant.
    - Keep them suitable for initial ALERT-ONLY implementation.
    - Prefer strategies that use only the standard market snapshot data (title, price,
      volume, endDate, sub-market list). Avoid strategies that require intraday candles,
      order book depth snapshots, trade history, or live news feeds — mark those as
      requires_external_data=true so they are paused until the data is available.

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
    - requires_external_data (bool): true if entry logic needs intraday candles, order book
      depth, trade history, live news, or any data beyond the standard market snapshot

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
    - **proposed_by:** strategy_factory_cycle
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


def generate_strategy_code(spec: dict, module_name: str, *, force_paused: bool = False) -> str:
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

    # Skip LLM call if strategy explicitly requires unavailable external data
    needs_external = spec.get('requires_external_data', False)
    if force_paused or needs_external:
        if needs_external and not force_paused:
            print(f"  [factory] {spec['name']} requires external data — using paused skeleton")
        scan_body = _paused_scan_body()
        is_paused = True
    else:
        scan_body = _generate_scan_body(spec)
        is_paused = scan_body is None
        if is_paused:
            print(f"  [factory] LLM code gen failed for {spec['name']} — using paused skeleton")
            scan_body = _paused_scan_body()

    indented_body = _indent_for_class(scan_body)

    return (
        f'"""\nAuto-generated strategy: {spec["name"]}\n'
        f'Generated by strategy_factory_cycle.py.\n\n'
        f'This strategy is intentionally ALERT-ONLY on creation.\n'
        f'It must earn promotion later.\n\n'
        f'Design notes:\n{comment}\n"""\n'
        f'from __future__ import annotations\n\n'
        f'from datetime import date\n\n'
        f'from ..base import Strategy\n'
        f'from ...feed import event_url, get_yes_price\n'
        f'from ...models import Signal\n\n'
        f'MAX_SIGNALS = 3\n\n\n'
        f'class {strategy_class}(Strategy):\n'
        f'    name = "{spec["name"]}"\n'
        f'    alert_only = True\n'
        f'    trading_enabled = False\n'
        f'    promotable = False\n'
        f'    live_ready = False\n'
        f'    promotion_criteria = ""\n'
        f'    edge_type = "{edge_type}"\n'
        f'    time_window = "{time_window}"\n'
        f'    target_hold_min_days = {min_days}\n'
        f'    target_hold_max_days = {max_days}\n'
        f'    scan_frequency = "auto-generated"\n'
        f'    paused = {str(is_paused)}\n'
        f'    min_ev_pp = 8.0\n'
        f'    last_check_details: list[dict] = []\n\n'
        f'{indented_body}\n'
    )


def write_generated_strategy(spec: dict, prefix: str, seq: int) -> dict | None:
    # Deduplication: avoid colliding with an existing explicit or generated strategy name
    existing_names = set(load_existing_strategy_names())
    original_name = spec['name']
    if spec['name'] in existing_names:
        spec = {**spec, 'name': spec['name'] + '_gen'}
        if spec['name'] in existing_names:
            print(f"  [factory] skipping {original_name} — name collision even with _gen suffix")
            return None
        print(f"  [factory] renamed {original_name} → {spec['name']} (collision with existing strategy)")

    safe_name = slugify(spec['name'])
    module_name = f"auto_{prefix}_{seq:03d}_{safe_name}"
    proposal_id = f"PR-{prefix}-{seq:03d}"
    date_human = f"{prefix[:4]}-{prefix[4:6]}-{prefix[6:]}"

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)

    py_path = GENERATED_DIR / f"{module_name}.py"
    md_path = PROPOSALS_DIR / f"{proposal_id}-{safe_name}.md"

    py_path.write_text(generate_strategy_code(spec, module_name), encoding="utf-8")

    # Smoke test: if import or scan([]) fail, overwrite with paused skeleton
    if not _smoke_test_generated(py_path, spec['name']):
        print(f"  [factory] smoke test failed — rewriting {spec['name']} as paused skeleton")
        py_path.write_text(generate_strategy_code(spec, module_name, force_paused=True), encoding="utf-8")

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
    python = str(PROJECT_ROOT / ".venv" / "bin" / "python")
    if not REMOTE_API_URL:
        # Only rebuild benchmarks when running locally with SQLite access.
        run_cmd([python, "scripts/build_replay_benchmark.py", "--scope", "alert-only"], env=env)
        run_cmd([python, "scripts/build_replay_benchmark.py", "--scope", "generated"], env=env)
        run_cmd([python, "scripts/export_dashboard_data.py"], env=env)
    run_cmd([python, "scripts/build_dashboard.py"], env=env)


def main() -> None:
    global LAST_GENERATION_SKIPPED_REASON
    if REMOTE_API_URL:
        print(f"[remote] API mode: {REMOTE_API_URL}")
        fetch_benchmarks_remote()
    prefix = now_local().strftime("%Y%m%d")
    seq = next_daily_sequence(prefix)
    archived = apply_generated_retention_gate()
    eval_text = capture_eval_report()
    generated = []
    LAST_GENERATION_SKIPPED_REASON = generation_skip_reason()
    if LAST_GENERATION_SKIPPED_REASON:
        print(f"[factory] skipping generation: {LAST_GENERATION_SKIPPED_REASON}")
    else:
        specs = generate_strategy_specs(eval_text)
        for idx, spec in enumerate(specs, start=seq):
            result = write_generated_strategy(spec, prefix, idx)
            if result is not None:
                generated.append(result)
    summary = summarize_eval(eval_text, generated, archived)
    DASHBOARD_DATA.mkdir(parents=True, exist_ok=True)
    EVAL_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    STRATEGY_FACTORY_META_JSON.write_text(
        json.dumps({
            "generated_at": now_local().isoformat(timespec="seconds"),
            "eval_source": LAST_EVAL_SOURCE,
            "benchmark_fetches": LAST_BENCHMARK_FETCHES,
            "generated_count": len(generated),
            "archived_count": len(archived),
            "generation_skipped_reason": LAST_GENERATION_SKIPPED_REASON,
        }, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    importlib.invalidate_caches()
    refresh_dashboard()
    print(json.dumps({"generated": generated, "archived": archived, "evaluation": summary}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
