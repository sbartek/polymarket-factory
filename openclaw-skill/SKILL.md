---
name: details
description: PPLayouts trading strategy details — open positions, closed trades, P&L, ROI, win rate. Use when user sends "/details <strategy>" or asks about a strategy. Strategies and shortcuts: ev_news (ev), fade_certainty (fade), weather_edge (weather), spread_arb (arb), resolution_hunter (resolution).
---

# PPLayouts — Strategy Details

## When to trigger

Activate on messages like:
- `/details weather`
- `/details fade`
- `details arb`
- `show me ev_news trades`
- `how is spread_arb doing?`
- `weather_edge results`

## How to respond

Extract the strategy name or shortcut from the message, then run:

```
bash workdir:~/workai/projects/polymarket-factory command:"uv run openclaw-skill/scripts/strategy_details.py <strategy>"
```

Replace `<strategy>` with the name or shortcut extracted from the message.

Valid strategies and shortcuts:
- `ev_news` or `ev`
- `fade_certainty` or `fade`
- `weather_edge` or `weather`
- `spread_arb` or `arb`
- `resolution_hunter` or `resolution` or `hunter`

## WhatsApp formatting rules

- Return the script output as-is — already formatted for WhatsApp
- No extra commentary needed
- If strategy is unknown, the script will say so

## Example

User: `/details weather`

Run with strategy=`weather`, return output directly.
