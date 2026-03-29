---
name: ppplayouts
description: PPLayouts prediction market paper-trading factory. Use when the user sends "/details" followed by a strategy name (ev_news, fade_certainty, weather_edge, spread_arb, resolution_hunter) or shortcut (ev, fade, weather, arb, resolution). Returns open and closed trades, P&L, ROI, and win rate for that strategy.
---

# PPLayouts Strategy Details

## When to trigger

Activate when a message matches: `/details <strategy>` or `details <strategy>`

Supported strategy names and shortcuts:
- `ev_news` or `ev`
- `fade_certainty` or `fade`
- `weather_edge` or `weather`
- `spread_arb` or `arb`
- `resolution_hunter` or `resolution` or `hunter`

## How to respond

Run the details script via Claude Code:

```
bash workdir:~/workai/projects/polymarket-factory command:"claude --permission-mode bypassPermissions --print 'Run this command and return its full output: uv run openclaw-skill/scripts/strategy_details.py <strategy>'"
```

Replace `<strategy>` with the strategy name or shortcut from the user's message.

## WhatsApp formatting rules

- Return the script output as-is — it is already formatted for WhatsApp
- No extra commentary needed
- If the strategy name is invalid, the script will say so

## Example

User sends: `/details weather`

You run:
```
bash workdir:~/workai/projects/polymarket-factory command:"claude --permission-mode bypassPermissions --print 'Run this command and return its full output: uv run openclaw-skill/scripts/strategy_details.py weather'"
```

Then return the output directly to the group.
