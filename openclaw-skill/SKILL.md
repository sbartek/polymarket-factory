---
name: details
description: PPLayouts slash command router. Activate for ANY message that starts with "/" (slash command). Handles /details and replies "Unknown command" for anything else.
---

# PPLayouts — Slash Command Router

## When to trigger

Activate on ANY message that starts with `/`:
- `/details fade`
- `/details weather`
- `/anything`
- `/foo`
- `/help`

## Known commands

### /details <strategy>

Run:
```
bash workdir:~/workai/projects/polymarket-factory command:"uv run openclaw-skill/scripts/strategy_details.py <strategy>"
```

Replace `<strategy>` with the name or shortcut from the message.

Valid strategies and shortcuts:
- `ev_news` or `ev`
- `fade_certainty` or `fade`
- `weather_edge` or `weather`
- `spread_arb` or `arb`
- `resolution_hunter` or `resolution` or `hunter`
- `stale_market` or `stale`
- `correlated_pairs` or `corr` or `pairs`
- `portfolio` or `book`
- `legacy`
- `latest` or `run`

Return the script output as-is — already formatted for WhatsApp.

## Unknown commands

If the message starts with `/` but is NOT `/details`, reply with exactly:

```
Unknown command: /<command>
Available commands: /details <strategy>
Strategies: ev, fade, weather, arb, resolution
```

## Examples

User: `/details fade` → run script with strategy=fade, return output
User: `/details ev` → run script with strategy=ev, return output
User: `/foo` → reply "Unknown command: /foo\nAvailable commands: /details <strategy>\nStrategies: ev, fade, weather, arb, resolution"
User: `/help` → reply "Unknown command: /help\nAvailable commands: /details <strategy>\nStrategies: ev, fade, weather, arb, resolution"
�� reply "Unknown command: /help\nAvailable commands: /details <strategy>\nStrategies: ev, fade, weather, arb, resolution"
