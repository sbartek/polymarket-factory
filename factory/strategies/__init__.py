from .ev_news import EvNewsStrategy
from .fade_certainty import FadeCertaintyStrategy

# Registry — add new strategies here
STRATEGIES = [
    EvNewsStrategy(),
    FadeCertaintyStrategy(),
]
