from .ev_news import EvNewsStrategy
from .fade_certainty import FadeCertaintyStrategy
from .resolution_hunter import ResolutionHunterStrategy
from .spread_arb import SpreadArbStrategy
from .weather_edge import WeatherEdgeStrategy

# Registry — add new strategies here
STRATEGIES = [
    EvNewsStrategy(),
    FadeCertaintyStrategy(),
    WeatherEdgeStrategy(),
    SpreadArbStrategy(),
    ResolutionHunterStrategy(),
]
