from .ev_news import EvNewsStrategy
from .fade_certainty import FadeCertaintyStrategy
from .weather_edge import WeatherEdgeStrategy

# Registry — add new strategies here
STRATEGIES = [
    EvNewsStrategy(),
    FadeCertaintyStrategy(),
    WeatherEdgeStrategy(),
]
