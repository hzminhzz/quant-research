"""Production-ready Volatility-Targeted Regime-Conditioned Time-Series Momentum Strategy.

Frozen Version: 1.0.0
Author: ml4t-quant-research
"""

from dataclasses import dataclass
import datetime as dt
from typing import Any
import numpy as np
from ml4t.backtest import Strategy


@dataclass
class StrategyRiskConfig:
    max_portfolio_drawdown: float = 0.15
    max_gross_leverage: float = 1.0
    max_single_weight: float = 0.35
    target_annual_vol: float = 0.20
    conviction_deadband: float = 0.015


class CryptoTSMOMRegimeStrategy(Strategy):
    """Symmetric or Long/Flat Time-Series Momentum with Volatility Targeting and Regime Conditioning."""

    def __init__(self, risk_config: StrategyRiskConfig | None = None):
        super().__init__()
        self.risk_config = risk_config or StrategyRiskConfig()
        self.high_water_mark: float = 0.0
        self.kill_switch_tripped: bool = False

    def on_start(self, broker: Any) -> None:
        cash = broker.get_cash()
        self.high_water_mark = cash
        self.kill_switch_tripped = False

    def on_data(
        self,
        timestamp: dt.datetime,
        data: dict[str, dict[str, Any]],
        context: dict[str, Any],
        broker: Any,
    ) -> None:
        # 1. Kill-Switch Check
        current_equity = broker.get_portfolio_value() if hasattr(broker, "get_portfolio_value") else broker.get_cash()
        if current_equity > self.high_water_mark:
            self.high_water_mark = current_equity

        current_dd = (self.high_water_mark - current_equity) / self.high_water_mark if self.high_water_mark > 0 else 0.0
        if current_dd >= self.risk_config.max_portfolio_drawdown and not self.kill_switch_tripped:
            self.kill_switch_tripped = True
            print(f"[KILL-SWITCH TRIPPED at {timestamp}] Drawdown {current_dd:.2%} >= limit {self.risk_config.max_portfolio_drawdown:.2%}. Flattening.")
            if hasattr(broker, "flatten_all_positions"):
                broker.flatten_all_positions()
            return

        if self.kill_switch_tripped:
            return

        # 2. Iterate Assets & Evaluate Signals
        for sym, bar in data.items():
            sig = bar.get("signals", {}).get("roc_168")
            regime_w = bar.get("signals", {}).get("regime_scaled_weight")
            chop = bar.get("signals", {}).get("choppiness_index", 50.0)

            if sig is None or regime_w is None:
                continue

            pos = broker.get_position(sym)
            current_qty = pos.quantity if pos is not None else 0.0
            is_long = current_qty > 0

            # Trend conviction & choppiness filter
            in_trend = abs(sig) >= self.risk_config.conviction_deadband
            is_choppy = chop is not None and chop > 55.0

            target_weight = 0.0
            if sig > 0.0 and in_trend and not is_choppy:
                # Volatility-scaled long position
                target_weight = min(float(regime_w), self.risk_config.max_single_weight)
            else:
                target_weight = 0.0

            # State-change execution to prevent fee churn
            if target_weight > 0.0 and not is_long:
                broker.order_target_percent(sym, target_weight)
            elif target_weight <= 0.0 and is_long:
                broker.order_target_percent(sym, 0.0)
