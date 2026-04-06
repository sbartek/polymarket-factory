"""Notifications via WhatsApp (OpenClaw CLI) and Slack (webhook)."""
import json
import os
import shutil
import subprocess
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


def send_notification(text: str) -> dict:
    """Send via all available channels and return a per-channel delivery report."""
    cfg = configured_channels()
    whatsapp_sent = send_whatsapp(text)
    slack_sent = send_slack(text)
    return {
        "any_sent": any((whatsapp_sent, slack_sent)),
        "channels": {
            "whatsapp": {"sent": whatsapp_sent},
            "slack": {"sent": slack_sent},
        },
        "configured": cfg,
    }
