"""Watchdog — check heartbeats and alert Slack if any job is overdue.

Run via cron every 10 minutes:
  */10 * * * * cd ~/polymarket-factory && bash run_watchdog.sh >> logs/watchdog.log 2>&1
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from factory.healthcheck import check_heartbeats, check_signal_repeats
from factory.notify import send_slack


def main():
    problems = check_heartbeats() + check_signal_repeats()
    if not problems:
        return

    lines = ["*Watchdog alert* — cron job issues detected:\n"]
    for p in problems:
        emoji = {
            "overdue": "🔴", "failed": "🟡", "never_reported": "⚪",
            "corrupt": "⚠️", "signal_repeat": "🔁", "degraded": "🟠",
        }.get(p["status"], "❓")
        lines.append(f"{emoji} *{p['slug']}*: {p['status']} — {p['detail']}")

    message = "\n".join(lines)
    print(message)

    if send_slack(message):
        print("[watchdog] Slack alert sent")
    else:
        print("[watchdog] Slack send failed or not configured")


if __name__ == "__main__":
    main()
