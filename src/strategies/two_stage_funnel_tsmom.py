"""Two-Stage Funnel Time-Series Momentum Strategy (src/strategies/two_stage_funnel_tsmom.py).

Implements Liquidity Screen + Structural Trend Gating (Close > EMA200) + Risk-Adjusted Momentum Ranking.
"""

from dataclasses import dataclass
import datetime as dt
from typing import Any
from ml4t.backtest import Strategy


@dataclass
class TwoStageRiskConfig:
    max_portfolio_drawdown: float = 0.15
    max_single_weight: float = 0.20
    max_gross_leverage: float = 1.0
    kill_switch_enabled: bool = True


class TwoStageFunnelTSMOMStrategy(Strategy):
    """Executes long-only TSMOM exclusively on tokens passing the Two-Stage Trend Funnel."""

    def __init__(self, risk_config: TwoStageRiskConfig | None = None):
        super().__init__()
        self.risk_config = risk_config or TwoStageRiskConfig()
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
        # 1. Kill-Switch Drawdown Verification
        current_equity = (
            broker.get_portfolio_value()
            if hasattr(broker, "get_portfolio_value")
            else broker.get_cash()
        )
        if current_equity > self.high_water_mark:
            self.high_water_mark = current_equity

        dd = (self.high_water_mark - current_equity) / self.high_water_mark if self.high_water_mark > 0 else 0.0
        if self.risk_config.kill_switch_enabled and dd >= self.risk_config.max_portfolio_drawdown:
            if not self.kill_switch_tripped:
                self.kill_switch_tripped = True
                print(f"[KILL-SWITCH TRIPPED at {timestamp}] Drawdown {dd:.2%} >= limit {self.risk_config.max_portfolio_drawdown:.2%}. Halting and flattening.")
                if hasattr(broker, "flatten_all_positions"):
                    broker.flatten_all_positions()
            return

        if self.kill_switch_tripped:
            return

        # 2. State-Change Order Execution
        for sym, bar in data.items():
            is_leader = bar.get("signals", {}).get("is_selected_leader", 0.0) == 1.0
            vol_w = bar.get("signals", {}).get("vol_scaled_weight", 0.10)

            pos = broker.get_position(sym)
            current_qty = pos.quantity if pos is not None else 0.0
            is_long = current_qty > 0

            # State Transition 1: Token is no longer a selected leader -> Exit to cash immediately
            if not is_leader and is_long:
                broker.order_target_percent(sym, 0.0)
                continue

            # State Transition 2: Token became a selected leader -> Enter long position
            if is_leader and not is_long:
                target_w = min(float(vol_w), self.risk_config.max_single_weight)
                broker.order_target_percent(sym, target_w)
