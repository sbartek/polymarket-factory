from datetime import UTC, datetime, timedelta

from factory.strategies.esport48 import (
    Esport48Strategy,
    _extract_team_names,
    _normalize_team,
    _team_match_score,
    _is_esport_event,
)


def _market(
    slug: str,
    title: str,
    price: float,
    volume: float,
    end_date: str | None = None,
    tags: list[dict] | None = None,
) -> dict:
    if end_date is None:
        end_date = (datetime.now(UTC) + timedelta(hours=24)).isoformat().replace("+00:00", "Z")
    return {
        "slug": slug,
        "title": title,
        "volume24hr": volume,
        "endDate": end_date,
        "tags": tags or [{"slug": "esports", "label": "Esports"}],
        "markets": [{
            "closed": False,
            "outcomePrices": [price, 1 - price],
        }],
    }


class TestTeamNameExtraction:
    def test_simple_vs(self):
        assert _extract_team_names("FaZe vs Natus Vincere (BO3)") == ("FaZe", "Natus Vincere")

    def test_vs_dot(self):
        assert _extract_team_names("Team Liquid vs. Cloud9") == ("Team Liquid", "Cloud9")

    def test_with_tournament_suffix(self):
        assert _extract_team_names("NRG vs Legacy (BO3) - PGL Bucharest Major") == ("NRG", "Legacy")

    def test_no_vs(self):
        assert _extract_team_names("Valorant Champions Final winner") is None


class TestTeamMatching:
    def test_exact(self):
        assert _team_match_score("FaZe", "FaZe") == 1.0

    def test_with_esports_suffix(self):
        assert _team_match_score("FaZe Esports", "FaZe") >= 0.8

    def test_unrelated(self):
        assert _team_match_score("FaZe", "Cloud9") < 0.5


class TestEsportDetection:
    def test_esport_event(self):
        ev = _market("cs2-match", "CS2: NRG vs Legacy (BO3)", 0.6, 20000)
        assert _is_esport_event(ev) is True

    def test_non_esport_event(self):
        ev = _market("soccer", "Will Barcelona win?", 0.6, 20000, tags=[{"slug": "soccer"}])
        assert _is_esport_event(ev) is False


class TestStrategy:
    def test_is_alert_only(self):
        s = Esport48Strategy()
        assert s.alert_only is True
        assert s.trading_enabled is False

    def test_no_api_key_returns_empty(self):
        import os
        old = os.environ.pop("ODDSPAPI_API_KEY", None)
        try:
            s = Esport48Strategy()
            signals = s.scan([_market("cs2", "CS2: FaZe vs NaVi (BO3)", 0.65, 20000)])
            assert signals == []
        finally:
            if old:
                os.environ["ODDSPAPI_API_KEY"] = old

    def test_skips_non_esport(self):
        s = Esport48Strategy()
        # Even with API key, non-esport markets should be filtered before API calls
        ev = _market("macro", "Will CPI rise?", 0.6, 50000, tags=[{"slug": "macro"}])
        assert not _is_esport_event(ev)
