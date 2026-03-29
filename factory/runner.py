"""
Main runner — called 3x/day by launchd.
1. Fetch market snapshot
2. Run each strategy → collect signals
3. Size + open positions (skip duplicates)
4. Check open positions → close resolved ones
5. Send WhatsApp summary
"""
import sys
from datetime import datetime

from .broker import PaperBroker
from .feed import fetch_top, fetch_closed, get_market_winner, get_submarket_outcome, get_yes_price
from .models import Signal
from .notify import send_whatsapp
from .portfolio import summary, format_summary
from .strategies import STRATEGIES


def resolve_open_positions(broker: PaperBroker):
    """Check open positions against Gamma API and close resolved ones."""
    open_positions = broker.get_open_positions()
    closed_count = 0
    for t in open_positions:
        market_id = t["market_id"]
        if not market_id:
            continue

        # Handle compound market IDs: "event-slug:submarket_id"
        if ":" in market_id:
            event_slug, submarket_id = market_id.split(":", 1)
        else:
            event_slug, submarket_id = market_id, None

        try:
            events = fetch_closed(event_slug)
            if not events:
                continue
            ev = events[0]
            winner = (
                get_submarket_outcome(ev, submarket_id)
                if submarket_id
                else get_market_winner(ev)
            )
            if winner:
                broker.close_position(t["id"], winner)
                closed_count += 1
                print(f"  Closed [{t['strategy']}] {t['market_title'][:50]} → {winner} | "
                      f"P&L ${float(t.get('pnl_usdc', 0)):+.2f}")
        except Exception as e:
            print(f"  Error resolving {market_id}: {e}")
    return closed_count


def format_wa_summary(new_trades: list[tuple], closed_count: int, stats: dict, now: str) -> str:
    lines = [f"*Polymarket Factory — {now}*\n"]

    if new_trades:
        lines.append(f"*New positions ({len(new_trades)}):*")
        for sig, amount in new_trades:
            flag = "⚡" if sig.ev_pp >= 15 else "  "
            lines.append(
                f"{flag} [{sig.strategy}] {sig.outcome} {sig.market_title[:45]}\n"
                f"   Market: {sig.market_price*100:.0f}% | p̂: {sig.p_hat*100:.0f}% | "
                f"EV: +{sig.ev_pp:.0f}pp | ${amount} | {sig.confidence}"
            )
    else:
        lines.append("No new positions this run.")

    if closed_count:
        lines.append(f"\n{closed_count} position(s) resolved — see portfolio for P&L.")

    lines.append(f"\n{format_summary(stats)}")
    lines.append("\n_Paper trading only — not financial advice._")
    return "\n".join(lines)


def run():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{'='*60}")
    print(f"POLYMARKET FACTORY — {now}")
    print(f"{'='*60}\n")

    broker = PaperBroker()

    # Step 1: resolve any positions that closed
    print("Checking open positions for resolution...")
    closed_count = resolve_open_positions(broker)
    print(f"  {closed_count} resolved.\n")

    # Step 2: fetch market snapshot (shared across all strategies)
    print("Fetching market snapshot...", end=" ", flush=True)
    markets = fetch_top(limit=100)
    print(f"{len(markets)} markets.\n")

    # Step 3: run each strategy
    new_trades: list[tuple[Signal, float]] = []

    for strategy in STRATEGIES:
        print(f"Running [{strategy.name}]...")
        try:
            signals = strategy.scan(markets)
        except Exception as e:
            print(f"  Error in {strategy.name}.scan(): {e}")
            continue

        for sig in signals:
            # Skip if we already have this position
            if broker.has_position(sig.market_id, strategy.name):
                print(f"  [{strategy.name}] skip duplicate: {sig.market_title[:45]}")
                continue

            amount = strategy.size(sig)
            if amount < 1.0:
                print(f"  [{strategy.name}] skip tiny size (${amount}): {sig.market_title[:45]}")
                continue

            trade = broker.open_position(sig, amount)
            new_trades.append((sig, amount))
            print(f"  [{strategy.name}] OPEN {sig.outcome} {sig.market_title[:45]} "
                  f"| EV +{sig.ev_pp:.0f}pp | ${amount} | {sig.confidence}")

        print()

    # Step 4: portfolio snapshot
    stats = summary(broker)
    print(format_summary(stats))

    # Step 5: WhatsApp notification
    wa_msg = format_wa_summary(new_trades, closed_count, stats, now)
    send_whatsapp(wa_msg)
    print("\nWhatsApp notification sent.")
    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    run()
