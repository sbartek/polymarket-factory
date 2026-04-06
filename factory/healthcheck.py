"""Dead man's switch monitoring via healthchecks.io."""

from __future__ import annotations

import os
import urllib.request


def ping(slug: str, *, success: bool = True) -> None:
    """Send a ping to healthchecks.io.

    Args:
        slug: Check slug name (e.g. "scan", "execute", "observer").
        success: If False, appends /fail to signal a job failure.
    """
    ping_key = os.environ.get("HEALTHCHECKS_PING_KEY", "")
    if not ping_key:
        return

    suffix = "" if success else "/fail"
    url = f"https://hc-ping.com/{ping_key}/{slug}{suffix}"

    try:
        urllib.request.urlopen(url, timeout=5)
    except Exception:
        pass  # monitoring should never break the job
