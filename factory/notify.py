"""WhatsApp notifications via OpenClaw CLI."""
import os
import shutil
import subprocess
from pathlib import Path


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


def send_whatsapp(text: str):
    group_id = os.environ.get("WHATSAPP_GROUP_ID")
    if not group_id:
        print("  [notify] WHATSAPP_GROUP_ID not set — skipping.")
        return

    openclaw = shutil.which("openclaw") or \
        "/Users/barteks/.local/share/fnm/node-versions/v24.14.0/installation/bin/openclaw"

    try:
        result = subprocess.run(
            [openclaw, "message", "send",
             "--channel", "whatsapp",
             "--target", group_id,
             "--message", text],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            print(f"  [notify] openclaw error: {result.stderr.strip()[:200]}")
    except Exception as e:
        print(f"  [notify] send_whatsapp failed: {e}")
