"""Factory API — serves benchmark JSONs and eval report to remote clients (e.g. Mac strategy factory).

Start with:
    uvicorn api.server:app --host 127.0.0.1 --port 8765

Protected by FACTORY_API_KEY env var. All endpoints require X-Api-Key header.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg2
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = PROJECT_ROOT / "benchmark-data"
HEARTBEAT_DIR = PROJECT_ROOT / "data" / "heartbeats"
API_LOG_DIR = PROJECT_ROOT / "data" / "api"
EVAL_ERROR_LOG = API_LOG_DIR / "eval-errors.log"
ENV_FILE = PROJECT_ROOT / ".env"
EVAL_TIMEOUT_SECONDS = 180

app = FastAPI(title="Polymarket Factory API", docs_url=None, redoc_url=None)

VALID_SCOPES = {"alert-only", "generated", "all"}


def _load_dotenv() -> None:
    """Load project .env into process env when the service launcher didn't."""
    if not ENV_FILE.exists():
        return
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()


def _log_eval_failure(code: str, detail: str) -> None:
    API_LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    with EVAL_ERROR_LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp}\t{code}\t{detail}\n")


def require_auth(x_api_key: str = Header(..., alias="x-api-key")) -> None:
    expected = os.environ.get("FACTORY_API_KEY", "")
    if not expected or x_api_key != expected:
        raise HTTPException(status_code=403, detail="Forbidden")


Auth = Depends(require_auth)


@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.get("/ready")
def ready() -> JSONResponse:
    checks = {
        "factory_api_key": bool(os.environ.get("FACTORY_API_KEY")),
        "database_url": bool(os.environ.get("DATABASE_URL")),
        "eval_report": (PROJECT_ROOT / "eval" / "report.py").exists(),
        "database_connectivity": False,
    }
    db_error = None
    if checks["database_url"]:
        try:
            conn = psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=5)
            conn.close()
            checks["database_connectivity"] = True
        except Exception as exc:
            db_error = f"{exc.__class__.__name__}: {exc}"
    ready_state = all(checks.values())
    payload = {"status": "ready" if ready_state else "not_ready", "checks": checks}
    if db_error:
        payload["database_error"] = db_error
    status_code = 200 if ready_state else 503
    return JSONResponse(payload, status_code=status_code)


@app.get("/benchmark/{scope}")
def get_benchmark(scope: str, _: None = Auth) -> FileResponse:
    if scope not in VALID_SCOPES:
        raise HTTPException(status_code=400, detail=f"scope must be one of {sorted(VALID_SCOPES)}")
    path = BENCHMARK_DIR / f"replay-benchmark-{scope}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"benchmark not found for scope={scope}")
    return FileResponse(path, media_type="application/json")


@app.get("/eval")
def get_eval(_: None = Auth) -> PlainTextResponse:
    try:
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "eval" / "report.py")],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=EVAL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        detail = f"eval_subprocess_timeout after {EVAL_TIMEOUT_SECONDS}s"
        _log_eval_failure("eval_subprocess_timeout", detail)
        raise HTTPException(status_code=504, detail=detail) from exc
    except Exception as exc:
        detail = f"eval_subprocess_crash: {exc.__class__.__name__}"
        _log_eval_failure("eval_subprocess_crash", f"{detail}: {exc}")
        raise HTTPException(status_code=500, detail=detail) from exc
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        detail = stderr or stdout or "eval report failed"
        _log_eval_failure("eval_subprocess_failed", detail)
        raise HTTPException(status_code=500, detail=f"eval_subprocess_failed: {detail}")
    return PlainTextResponse(result.stdout)


@app.post("/heartbeat/{slug}")
def post_heartbeat(slug: str, success: bool = True, status: str = "ok", detail: str | None = None, _: None = Auth) -> JSONResponse:
    """Accept a heartbeat ping from a remote job (e.g. Mac strategy factory)."""
    HEARTBEAT_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "slug": slug,
        "success": success,
        "status": status,
        "detail": detail,
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    path = HEARTBEAT_DIR / f"{slug}.json"
    path.write_text(json.dumps(data))
    return JSONResponse({"ok": True, "slug": slug, "success": success, "status": status})
