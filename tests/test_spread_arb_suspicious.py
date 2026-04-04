"""
Tests for spread_arb._looks_suspicious() fix.

Root cause: original logic `len(active) <= 5 and not has_catch_all` was inverted —
it rejected small clean sets and passed large incomplete baskets.
Fix: reject when there is no catch-all leg (incomplete open field).
"""
from factory.strategies.spread_arb import SpreadArbStrategy


def _legs(*questions: str, price: float = 0.15) -> list[dict]:
    return [{"id": str(i), "question": q, "yes_price": price, "est_size": 2.0}
            for i, q in enumerate(questions)]


s = SpreadArbStrategy()


# ---------------------------------------------------------------------------
# Should be suspicious (incomplete open field, no catch-all)
# ---------------------------------------------------------------------------

def test_tournament_winner_no_field_is_suspicious():
    """NBA winner with 4 teams but no 'Field/Other' — incomplete basket."""
    legs = _legs("Will Celtics win?", "Will Lakers win?", "Will Warriors win?", "Will Bucks win?")
    assert s._looks_suspicious("2026 NBA Champion", legs)


def test_election_no_field_is_suspicious():
    """Election with 3 named candidates but no 'Other' leg."""
    legs = _legs("Will Alice win?", "Will Bob win?", "Will Carol win?")
    assert s._looks_suspicious("Governor election winner 2026", legs)


def test_award_no_field_is_suspicious():
    """Award winner with nominees listed but no field leg."""
    legs = _legs("Will Film A win?", "Will Film B win?", "Will Film C win?")
    assert s._looks_suspicious("Best Picture award nominee winner", legs)


def test_champion_no_field_is_suspicious():
    """Championship market without catch-all."""
    legs = _legs("Will Team A win?", "Will Team B win?", "Will Team C win?")
    assert s._looks_suspicious("2026 NHL Stanley Cup champion", legs)


def test_next_to_no_field_is_suspicious():
    """'Next to leave' cabinet market — many hidden candidates."""
    legs = _legs("Will Tulsi leave?", "Will Pete leave?", "Will Lori leave?")
    assert s._looks_suspicious("Who will be the next to leave the Trump Cabinet?", legs)


def test_who_will_be_no_field_is_suspicious():
    """'Who will be' phrasing without field leg."""
    legs = _legs("Outcome A", "Outcome B", "Outcome C")
    assert s._looks_suspicious("Who will be the next Fed chair?", legs)


# ---------------------------------------------------------------------------
# Should NOT be suspicious (has catch-all or unrelated title)
# ---------------------------------------------------------------------------

def test_winner_with_field_leg_not_suspicious():
    """Winner market but includes an 'Other/Field' leg — basket is complete."""
    legs = _legs("Will Team A win?", "Will Team B win?", "Field")
    assert not s._looks_suspicious("2026 World Cup winner", legs)


def test_winner_with_other_leg_not_suspicious():
    legs = _legs("Candidate A", "Candidate B", "Other")
    assert not s._looks_suspicious("Election winner 2026", legs)


def test_unrelated_title_not_suspicious():
    """No open-field keywords in title — pass through."""
    legs = _legs("Yes", "No", "Maybe")
    assert not s._looks_suspicious("Will CPI exceed 3% in June?", legs)


def test_regression_large_leg_count_with_no_field_still_suspicious():
    """Old logic passed baskets with > 5 legs even without a field — now correctly rejected."""
    legs = _legs(*[f"Team {i}" for i in range(8)])
    assert s._looks_suspicious("FIFA World Cup winner 2026", legs)


def test_regression_small_leg_count_with_field_not_suspicious():
    """Old logic incorrectly rejected 3-leg baskets with no field — now only field matters."""
    legs = _legs("Option A", "Option B", "Field")
    assert not s._looks_suspicious("Who will win the award?", legs)
