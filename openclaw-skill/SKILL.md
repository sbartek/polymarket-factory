---
name: details
description: PPLayouts slash command router. Activate for ANY message that starts with "/" (slash command). Handles /details, /new_strategy, and replies "Unknown command" for anything else.
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

### /new_strategy <plain-language idea>

Run:
```
bash workdir:~/workai/projects/polymarket-factory command:"uv run python scripts/new_strategy_proposal.py \"<idea>\""
```

Where `<idea>` is the freeform text after `/new_strategy`.

Then reply with:
- the created proposal filename
- a short summary saying the draft is ready for review
- instructions to reply with `approve`, `revise`, `reject`, or `park`

If the user sends only `/new_strategy` with no explanation, reply:

```
Explain the idea in plain language after /new_strategy.
Example: /new_strategy Find markets that lag after breaking macro news for 3-30 day events.
```

## Unknown commands

If the message starts with `/` but is neither `/details` nor `/new_strategy`, reply with exactly:

```
Unknown command: /<command>
Available commands: /details <strategy>, /new_strategy <idea>
Strategies: ev, fade, weather, arb, resolution, stale, corr, portfolio, legacy, latest
```

## Examples

User: `/details fade` → run script with strategy=fade, return output
User: `/details ev` → run script with strategy=ev, return output
User: `/details portfolio` → show overall current book summary
User: `/details legacy` → show legacy open baggage summary
User: `/details latest` → show latest run summary
User: `/new_strategy Find markets that lag after breaking macro news` → create proposal draft and ask for review
User: `/new_strategy` → ask user to explain the idea in plain language
User: `/foo` → reply "Unknown command: /foo\nAvailable commands: /details <strategy>, /new_strategy <idea>\nStrategies: ev, fade, weather, arb, resolution, stale, corr, portfolio, legacy, latest"
User: `/help` → reply "Unknown command: /help\nAvailable commands: /details <strategy>, /new_strategy <idea>\nStrategies: ev, fade, weather, arb, resolution, stale, corr, portfolio, legacy, latest"
