"""Runtime environment policy for research, paper, and live factory runs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RunEnvironment = Literal["research", "paper", "live"]
ExecutionAction = Literal["skip", "alert", "paper", "live"]


@dataclass(frozen=True)
class EnvironmentDecision:
    action: ExecutionAction
    reason: str


@dataclass(frozen=True)
class EnvironmentPolicy:
    name: RunEnvironment
    lock_name: str
    resolves_positions: bool
    records_portfolio_snapshots: bool
    supports_open_positions: bool


def is_generated_strategy(strategy) -> bool:
    return ".generated." in type(strategy).__module__


def get_environment_policy(name: str) -> EnvironmentPolicy:
    normalized = (name or "paper").strip().lower()
    if normalized == "research":
        return EnvironmentPolicy(
            name="research",
            lock_name="research_runner",
            resolves_positions=False,
            records_portfolio_snapshots=False,
            supports_open_positions=False,
        )
    if normalized == "paper":
        return EnvironmentPolicy(
            name="paper",
            lock_name="paper_runner",
            resolves_positions=True,
            records_portfolio_snapshots=True,
            supports_open_positions=True,
        )
    if normalized == "live":
        return EnvironmentPolicy(
            name="live",
            lock_name="live_runner",
            resolves_positions=True,
            records_portfolio_snapshots=True,
            supports_open_positions=True,
        )
    raise ValueError(f"unknown environment: {name}")


def classify_strategy_execution(policy: EnvironmentPolicy, strategy, strategy_meta: dict) -> EnvironmentDecision:
    strategy_mode = getattr(strategy, "mode", "paper")
    trading_enabled = bool(strategy_meta.get("trading_enabled", not getattr(strategy, "alert_only", False)))

    if policy.name == "research":
        return EnvironmentDecision("alert", "research_environment")

    if policy.name == "paper":
        if strategy_mode == "live":
            return EnvironmentDecision("alert", "live_only_strategy")
        if not trading_enabled:
            return EnvironmentDecision("alert", "trading_disabled")
        return EnvironmentDecision("paper", "paper_environment")

    if is_generated_strategy(strategy):
        return EnvironmentDecision("skip", "generated_strategy_blocked")
    if strategy_mode != "live":
        return EnvironmentDecision("skip", "not_live_strategy")
    if not bool(strategy_meta.get("live_ready", getattr(strategy, "live_ready", False))):
        return EnvironmentDecision("skip", "not_live_ready")
    if not trading_enabled:
        return EnvironmentDecision("skip", "trading_disabled")
    return EnvironmentDecision("live", "live_environment")
