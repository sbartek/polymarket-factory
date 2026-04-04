from .base import Strategy
from .carry_rewards import CarryRewardsStrategy
from .celebrity_tabloid import CelebrityTabloidStrategy
from .correlated_laggard import CorrelatedLaggardStrategy
from .correlated_pairs import CorrelatedPairsStrategy
from .esport48 import Esport48Strategy
from .ev_news import EvNewsStrategy
from .fade_certainty_v2 import FadeCertaintyV2Strategy
from .mutually_exclusive_oversum import MutuallyExclusiveOversumStrategy
from .polling_vs_market import PollingVsMarketStrategy
from .resolution_hunter_v2 import ResolutionHunterV2Strategy
from .spread_arb import SpreadArbStrategy
from .stale_market import StaleMarketStrategy
from .weather_edge_v2 import WeatherEdgeV2Strategy


def _load_generated_strategies():
    from importlib import import_module
    from pathlib import Path

    generated = []
    package_dir = Path(__file__).resolve().parent / "generated"
    if not package_dir.exists():
        return generated

    for path in sorted(package_dir.glob("auto_*.py")):
        module_name = f"{__name__}.generated.{path.stem}"
        try:
            module = import_module(module_name)
        except Exception as exc:
            print(f"[strategies] failed to import generated module {module_name}: {exc}")
            continue
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and issubclass(attr, Strategy) and attr is not Strategy:
                try:
                    instance = attr()
                except Exception as exc:
                    print(f"[strategies] failed to init generated strategy {attr_name}: {exc}")
                    continue
                if getattr(instance, "name", ""):
                    generated.append(instance)
    return generated


# Registry — add new strategies here
STRATEGIES = [
    EvNewsStrategy(),
    SpreadArbStrategy(),
    StaleMarketStrategy(),
    CorrelatedPairsStrategy(),
    CorrelatedLaggardStrategy(),
    Esport48Strategy(),
    CelebrityTabloidStrategy(),
    CarryRewardsStrategy(),
    PollingVsMarketStrategy(),
    MutuallyExclusiveOversumStrategy(),
    FadeCertaintyV2Strategy(),
    ResolutionHunterV2Strategy(),
    WeatherEdgeV2Strategy(),
] + _load_generated_strategies()
