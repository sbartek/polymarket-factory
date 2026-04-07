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
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = PROJECT_ROOT / "benchmark-data"
HEARTBEAT_DIR = PROJECT_ROOT / "data" / "heartbeats"

app = FastAPI(title="Polymarket Factory API", docs_url=None, redoc_url=None)

VALID_SCOPES = {"alert-only", "generated", "all"}


def require_auth(x_api_key: str = Header(..., alias="x-api-key")) -> None:
    expected = os.environ.get("FACTORY_API_KEY", "")
    if not expected or x_api_key != expected:
        raise HTTPException(status_code=403, detail="Forbidden")


Auth = Depends(require_auth)


@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


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
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "eval" / "report.py")],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr.strip() or "eval report failed")
    return PlainTextResponse(result.stdout)


@app.post("/heartbeat/{slug}")
def post_heartbeat(slug: str, success: bool = True, _: None = Auth) -> JSONResponse:
    """Accept a heartbeat ping from a remote job (e.g. Mac strategy factory)."""
    HEARTBEAT_DIR.mkdir(parents=True, exist_ok=True)
    from datetime import UTC, datetime
    data = {
        "slug": slug,
        "success": success,
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    path = HEARTBEAT_DIR / f"{slug}.json"
    path.write_text(json.dumps(data))
    return JSONResponse({"ok": True, "slug": slug, "success": success})
