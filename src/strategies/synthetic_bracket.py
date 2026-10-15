"""Data-free native synthetic bracket fixture, not a tradable strategy."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import polars as pl

from src.strategies.base import StrategyPlugin


@dataclass(frozen=True)
class SyntheticBracket:
    name: str = "synthetic_bracket_v1"
    native_execution_capabilities: frozenset[str] = frozenset(
        {"ml4t.backtest", "next_open_market_entry", "stop_first_native_oco"}
    )

    def compute_Primary_Signal(self, features: pl.DataFrame) -> datetime:
        if features.height < 4 or "available_at" not in features.columns:
            raise ValueError("Synthetic fixture requires verified completed bars")
        decision = features["timestamp"][1]
        if features["available_at"][0] > decision:
            raise ValueError("Decision precedes feature availability")
        return decision

    def generate_events(self, features: pl.DataFrame) -> dict[str, Any]:
        return {"signal_at": self.compute_Primary_Signal(features),
                "quantity": 1.0, "stop_price": 99.0, "limit_price": 101.4}

    def get_feature_manifest(self) -> dict[str, Any]:
        return {"features": ["typprice"], "source": "synthetic_only",
                "labels": [], "decision_channel": "available_at <= decision_at"}

    def get_barrier_config(self) -> dict[str, Any]:
        return {"stop": 99.0, "limit": 101.4,
                "fill": "native stop may gap/slip; OHLC queue priority unverified"}


REGISTRY: dict[str, StrategyPlugin] = {SyntheticBracket.name: SyntheticBracket()}


def registered_strategies() -> dict[str, StrategyPlugin]:
    return dict(REGISTRY)
