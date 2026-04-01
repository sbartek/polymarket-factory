from .celebrity_tabloid import CelebrityTabloidStrategy
from .correlated_laggard import CorrelatedLaggardStrategy
from .correlated_pairs import CorrelatedPairsStrategy
from .esport48 import Esport48Strategy
from .ev_news import EvNewsStrategy
from .fade_certainty import FadeCertaintyStrategy
from .resolution_hunter import ResolutionHunterStrategy
from .spread_arb import SpreadArbStrategy
from .stale_market import StaleMarketStrategy
from .weather_edge import WeatherEdgeStrategy

# Registry — add new strategies here
# 2026-03-31: fade_certainty and weather_edge are intentionally paused after
# early paper-trading results came in materially negative. Keep imports for now
# so the code/history remains easy to revisit, but do not run them by default.
STRATEGIES = [
    EvNewsStrategy(),
    SpreadArbStrategy(),
    ResolutionHunterStrategy(),
    StaleMarketStrategy(),
    CorrelatedPairsStrategy(),
    CorrelatedLaggardStrategy(),
    Esport48Strategy(),
    CelebrityTabloidStrategy(),
]
