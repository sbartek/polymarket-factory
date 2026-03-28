"""WhatsApp notifications via OpenClaw CLI."""
import os
import shutil
import subprocess


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
