"""WhatsApp notifications via OpenClaw CLI."""
import os
import subprocess


def send_whatsapp(text: str):
    group_id = os.environ.get("WHATSAPP_GROUP_ID")
    if not group_id:
        return
    try:
        subprocess.run(
            ["openclaw", "message", "send",
             "--channel", "whatsapp",
             "--target", group_id,
             "--message", text],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        pass
