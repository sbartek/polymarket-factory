from factory.environment import classify_strategy_execution, get_environment_policy


class DummyStrategy:
    def __init__(self, *, mode: str = "paper", live_ready: bool = False, module: str = "factory.strategies.dummy"):
        self.mode = mode
        self.live_ready = live_ready
        self.__class__.__module__ = module


def test_research_environment_turns_tradeable_strategy_into_alert_only():
    policy = get_environment_policy("research")
    strategy = DummyStrategy(mode="paper", live_ready=False)
    decision = classify_strategy_execution(policy, strategy, {"trading_enabled": True, "live_ready": False})
    assert decision.action == "alert"
    assert decision.reason == "research_environment"


def test_paper_environment_keeps_live_only_strategy_out_of_paper_positions():
    policy = get_environment_policy("paper")
    strategy = DummyStrategy(mode="live", live_ready=True)
    decision = classify_strategy_execution(policy, strategy, {"trading_enabled": True, "live_ready": True})
    assert decision.action == "alert"
    assert decision.reason == "live_only_strategy"


def test_live_environment_only_allows_live_ready_live_strategy():
    policy = get_environment_policy("live")
    strategy = DummyStrategy(mode="live", live_ready=True)
    decision = classify_strategy_execution(policy, strategy, {"trading_enabled": True, "live_ready": True})
    assert decision.action == "live"
    assert decision.reason == "live_environment"


def test_live_environment_blocks_generated_strategies():
    policy = get_environment_policy("live")
    strategy = DummyStrategy(mode="live", live_ready=True, module="factory.strategies.generated.auto_test")
    decision = classify_strategy_execution(policy, strategy, {"trading_enabled": True, "live_ready": True})
    assert decision.action == "skip"
    assert decision.reason == "generated_strategy_blocked"
