"""Notifications via WhatsApp (OpenClaw CLI) and Slack (webhook)."""
import json
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path


def configured_channels() -> dict[str, dict]:
    """Return lightweight per-channel configuration status for operator visibility."""
    group_id = os.environ.get("WHATSAPP_GROUP_ID")
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    return {
        "whatsapp": {
            "configured": bool(group_id),
            "target": group_id or None,
        },
        "slack": {
            "configured": bool(webhook_url),
            "target": "webhook" if webhook_url else None,
        },
    }


def _load_dotenv():
    """Load .env from project root if env vars not already set."""
    env_file = Path(__file__).parents[1] / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()


def _retry_settings() -> tuple[int, float]:
    """Return notification retry settings with safe defaults."""
    try:
        max_attempts = int(os.environ.get("NOTIFY_MAX_ATTEMPTS", "3"))
    except ValueError:
        max_attempts = 3
    try:
        backoff_seconds = float(os.environ.get("NOTIFY_RETRY_BACKOFF_SECONDS", "1.0"))
    except ValueError:
        backoff_seconds = 1.0
    return max(1, max_attempts), max(0.0, backoff_seconds)


def _find_openclaw() -> str | None:
    """Find openclaw binary: PATH first, then fnm-managed node bin dirs."""
    found = shutil.which("openclaw")
    if found:
        return found
    # Search fnm node version directories for globally installed openclaw
    fnm_dir = Path.home() / ".local" / "share" / "fnm" / "node-versions"
    if fnm_dir.is_dir():
        for version_dir in sorted(fnm_dir.iterdir(), reverse=True):
            candidate = version_dir / "installation" / "bin" / "openclaw"
            if candidate.exists():
                return str(candidate)
    return None


def send_whatsapp(text: str) -> bool:
    """Send a WhatsApp message. Returns True if confirmed sent, False otherwise."""
    group_id = os.environ.get("WHATSAPP_GROUP_ID")
    if not group_id:
        print("  [notify] WHATSAPP_GROUP_ID not set — skipping.")
        return False

    openclaw = _find_openclaw()
    if not openclaw:
        print("  [notify] openclaw not found in PATH or fnm — skipping.")
        return False

    try:
        result = subprocess.run(
            [openclaw, "message", "send",
             "--channel", "whatsapp",
             "--target", group_id,
             "--message", text],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            print(f"  [notify] openclaw error (rc={result.returncode}): {result.stderr.strip()[:200]}")
            return False
        # openclaw prints "✅ Sent via gateway" on success
        if "Sent" in result.stdout or "sent" in result.stdout.lower():
            return True
        # Non-zero stdout without a clear success marker — treat as failure
        if result.stdout.strip():
            print(f"  [notify] unexpected openclaw output: {result.stdout.strip()[:200]}")
        return False
    except subprocess.TimeoutExpired:
        print("  [notify] send_whatsapp timed out after 15s")
        return False
    except Exception as e:
        print(f"  [notify] send_whatsapp failed: {e}")
        return False


def send_slack(text: str) -> bool:
    """Send a Slack message via incoming webhook. Returns True on success."""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return False
    try:
        data = json.dumps({"text": text}).encode()
        req = urllib.request.Request(
            webhook_url, data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"  [notify] send_slack failed: {e}")
        return False


def _send_with_retry(name: str, sender, text: str, configured: bool) -> dict:
    """Retry configured channels with exponential backoff and per-channel reporting."""
    report = {"sent": False, "attempts": 0}
    if not configured:
        return report

    max_attempts, backoff_seconds = _retry_settings()
    for attempt in range(1, max_attempts + 1):
        report["attempts"] = attempt
        try:
            if sender(text):
                report["sent"] = True
                return report
        except Exception as e:
            print(f"  [notify] {name} send raised unexpectedly on attempt {attempt}: {e}")
        if attempt < max_attempts:
            delay = backoff_seconds * (2 ** (attempt - 1))
            print(f"  [notify] {name} delivery failed on attempt {attempt}/{max_attempts}; retrying in {delay:.1f}s")
            if delay > 0:
                time.sleep(delay)
    return report


def send_notification(text: str) -> dict:
    """Send via all available channels and return a per-channel delivery report."""
    cfg = configured_channels()
    whatsapp_report = _send_with_retry(
        "whatsapp",
        send_whatsapp,
        text,
        configured=cfg["whatsapp"]["configured"],
    )
    slack_report = _send_with_retry(
        "slack",
        send_slack,
        text,
        configured=cfg["slack"]["configured"],
    )
    return {
        "any_sent": any((whatsapp_report["sent"], slack_report["sent"])),
        "channels": {
            "whatsapp": whatsapp_report,
            "slack": slack_report,
        },
        "configured": cfg,
    }
