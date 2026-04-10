#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from factory.notify import send_slack

DATA_DIR = PROJECT_ROOT / "data"
RUN_LOG_DIR = DATA_DIR / "strategy-factory-runs"
LOCK_DIR = DATA_DIR / "locks"
LOCK_PATH = LOCK_DIR / "strategy-factory-local.lock"
LOCK_STALE_SECONDS = 6 * 3600
META_PATH = PROJECT_ROOT / "dashboard-data" / "strategy_factory_cycle_meta.json"


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_run_record(record: dict) -> None:
    RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = record.get("started_at", utcnow()).replace(":", "").replace("+00:00", "Z")
    run_path = RUN_LOG_DIR / f"strategy-factory-{stamp}.json"
    payload = json.dumps(record, indent=2, ensure_ascii=False) + "\n"
    run_path.write_text(payload, encoding="utf-8")
    (RUN_LOG_DIR / "latest.json").write_text(payload, encoding="utf-8")


def update_run_record(record: dict, **fields) -> None:
    record.update(fields)
    write_run_record(record)


@contextmanager
def file_lock() -> None:
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    if LOCK_PATH.exists():
        data = load_json(LOCK_PATH)
        acquired_at = data.get("acquired_at_epoch", 0)
        if time.time() - acquired_at > LOCK_STALE_SECONDS:
            LOCK_PATH.unlink(missing_ok=True)
        else:
            raise RuntimeError("another strategy factory run is already active")
    LOCK_PATH.write_text(json.dumps({
        "pid": os.getpid(),
        "acquired_at": utcnow(),
        "acquired_at_epoch": time.time(),
    }, indent=2), encoding="utf-8")
    try:
        yield
    finally:
        LOCK_PATH.unlink(missing_ok=True)


def _urlopen(url: str, *, headers: dict[str, str] | None = None, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def preflight(remote_url: str, api_key: str) -> None:
    if not api_key:
        raise RuntimeError("missing FACTORY_API_KEY")
    if not remote_url:
        raise RuntimeError("missing FACTORY_REMOTE_API_URL")
    _urlopen(f"{remote_url}/health", timeout=20)
    _urlopen(f"{remote_url}/ready", timeout=20)
    _urlopen(f"{remote_url}/benchmark/generated", headers={"x-api-key": api_key}, timeout=30)
    result = subprocess.run(
        ["git", "ls-remote", "--exit-code", "origin", "HEAD"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "git remote auth check failed")


def run_command(args: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=PROJECT_ROOT, env=env, capture_output=True, text=True)


def post_heartbeat(remote_url: str, api_key: str, *, success: bool, status: str, detail: str | None = None) -> None:
    params = {"success": "true" if success else "false", "status": status}
    if detail:
        params["detail"] = detail[:500]
    url = f"{remote_url}/heartbeat/strategy-factory?{urllib.parse.urlencode(params)}"
    _urlopen(url, headers={"x-api-key": api_key}, timeout=20)


def build_status_message(record: dict) -> str:
    status = record.get("status") or "unknown"
    started = record.get("started_at") or "unknown"
    finished = record.get("finished_at") or "unknown"
    eval_source = record.get("eval_source") or "unknown"
    generated = record.get("generated_count")
    archived = record.get("archived_count")
    error = record.get("error")
    lines = [
        f"*Strategy factory {status}*",
        f"started: {started}",
        f"finished: {finished}",
        f"eval_source: {eval_source}",
        f"generated: {generated if generated is not None else 'unknown'}",
        f"archived: {archived if archived is not None else 'unknown'}",
    ]
    if error:
        lines.append(f"error: {error}")
    return "\n".join(lines)


def notify_if_needed(record: dict) -> None:
    status = (record.get("status") or "").lower()
    if status not in {"degraded", "failed"}:
        return
    send_slack(build_status_message(record))


def run() -> int:
    remote_url = os.environ.get("FACTORY_REMOTE_API_URL", "https://factory.pplayouts.trade").rstrip("/")
    api_key = os.environ.get("FACTORY_API_KEY", "")
    record = {
        "started_at": utcnow(),
        "finished_at": None,
        "status": "running",
        "preflight_ok": False,
        "pull_ok": False,
        "cycle_ok": False,
        "push_ok": False,
        "heartbeat_ok": False,
        "eval_source": None,
        "degraded": False,
        "generated_count": None,
        "archived_count": None,
        "benchmark_fetches": [],
        "exit_code": None,
        "error": None,
    }
    write_run_record(record)
    try:
        with file_lock():
            preflight(remote_url, api_key)
            update_run_record(record, preflight_ok=True)

            pull = run_command(["git", "pull"])
            if pull.returncode != 0:
                raise RuntimeError(pull.stderr.strip() or pull.stdout.strip() or "git pull failed")
            update_run_record(record, pull_ok=True)

            env = dict(os.environ)
            env["FACTORY_REMOTE_API_URL"] = remote_url
            cycle = run_command(["uv", "run", "python", "scripts/strategy_factory_cycle.py"], env=env)
            if cycle.returncode != 0:
                raise RuntimeError(cycle.stderr.strip() or cycle.stdout.strip() or "strategy factory cycle failed")

            meta = load_json(META_PATH)
            degraded = meta.get("eval_source") == "cache"
            update_run_record(
                record,
                cycle_ok=True,
                eval_source=meta.get("eval_source"),
                degraded=degraded,
                generated_count=meta.get("generated_count"),
                archived_count=meta.get("archived_count"),
                benchmark_fetches=meta.get("benchmark_fetches", []),
            )

            push_ok = True
            add = run_command(["git", "add", "factory/strategies/generated/", "improvement/proposals/", "dashboard-data/", "benchmark-data/"])
            if add.returncode != 0:
                raise RuntimeError(add.stderr.strip() or add.stdout.strip() or "git add failed")
            if run_command(["git", "diff", "--staged", "--quiet"]).returncode != 0:
                commit = run_command(["git", "commit", "-m", f"strategy factory: auto-generated strategies {datetime.now().date()}"])
                if commit.returncode != 0:
                    raise RuntimeError(commit.stderr.strip() or commit.stdout.strip() or "git commit failed")
                push = run_command(["git", "push"])
                if push.returncode != 0:
                    push_ok = False
                    raise RuntimeError(push.stderr.strip() or push.stdout.strip() or "git push failed")
            update_run_record(record, push_ok=push_ok)

            hb_status = "degraded" if degraded else "ok"
            detail = "used cached eval report" if degraded else None
            post_heartbeat(remote_url, api_key, success=True, status=hb_status, detail=detail)
            update_run_record(record, heartbeat_ok=True)
            final_status = hb_status
            exit_code = 0
    except Exception as exc:
        final_status = "failed"
        exit_code = 1
        update_run_record(record, status="failed", error=str(exc))
        try:
            if remote_url and api_key:
                post_heartbeat(remote_url, api_key, success=False, status="failed", detail=str(exc))
                update_run_record(record, heartbeat_ok=True)
        except Exception:
            pass
    record["finished_at"] = utcnow()
    record["status"] = final_status
    record["exit_code"] = exit_code
    write_run_record(record)
    notify_if_needed(record)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(run())
