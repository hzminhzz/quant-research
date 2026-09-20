"""Event-Driven & Vectorized Backtest Execution Engine.

Implements realistic institutional execution with mandatory transaction costs:
- 2 bps commission fee per leg
- 1 bps slippage per leg
- Continuous daily equity tracking and Sharpe calculation
"""

from typing import Dict, Any, List, Optional
import polars as pl
import numpy as np


class CostModel:
    """Institutional transaction friction model."""

    def __init__(self, commission_bps: float = 2.0, slippage_bps: float = 1.0):
        self.commission_rate = commission_bps / 10000.0
        self.slippage_rate = slippage_bps / 10000.0
        self.total_one_way_friction = self.commission_rate + self.slippage_rate

    def apply_entry(self, price: float, side: int = 1) -> float:
        """Effective executed entry price accounting for slippage."""
        return price * (1.0 + side * self.slippage_rate)

    def apply_exit(self, price: float, side: int = 1) -> float:
        """Effective executed exit price accounting for slippage."""
        return price * (1.0 - side * self.slippage_rate)

    def roundtrip_fee(self) -> float:
        """Total commission friction per roundtrip."""
        return 2.0 * self.commission_rate


def run_intraday_backtest(
    df: pl.DataFrame,
    entry_signal_col: str,
    holding_bars: int = 16,
    exit_signal_col: Optional[str] = None,
    commission_bps: float = 2.0,
    slippage_bps: float = 1.0,
    initial_capital: float = 100000.0,
    timestamp_col: str = "timestamp",
    price_col: str = "close",
) -> Dict[str, Any]:
    """Simulate an institutional backtest over intraday price bars.

    Returns performance metrics and daily equity time series.
    """
    costs = CostModel(commission_bps=commission_bps, slippage_bps=slippage_bps)
    
    timestamps = df[timestamp_col].to_list()
    prices = df[price_col].to_numpy()
    entries = df[entry_signal_col].fill_null(False).to_numpy()
    exits = (
        df[exit_signal_col].fill_null(False).to_numpy()
        if exit_signal_col and exit_signal_col in df.columns
        else np.zeros(len(prices), dtype=bool)
    )

    n = len(prices)
    cash = initial_capital
    position = 0  # 1 = Long, 0 = Flat
    entry_price = 0.0
    bars_held = 0

    equity_series = np.full(n, initial_capital)
    trades = []

    for t in range(n):
        curr_price = prices[t]

        # 1. Exit logic if in position
        if position == 1:
            bars_held += 1
            is_timeout = bars_held >= holding_bars
            is_exit_trigger = exits[t]

            if is_timeout or is_exit_trigger:
                exec_exit = costs.apply_exit(curr_price, side=1)
                trade_pnl_pct = (exec_exit - entry_price) / entry_price - costs.roundtrip_fee()
                cash = cash * (1.0 + trade_pnl_pct)
                trades.append({
                    "exit_time": timestamps[t],
                    "entry_price": entry_price,
                    "exit_price": exec_exit,
                    "bars_held": bars_held,
                    "net_pnl_pct": trade_pnl_pct,
                    "reason": "exit_signal" if is_exit_trigger else "timeout",
                })
                position = 0
                bars_held = 0

        # 2. Entry logic if flat
        if position == 0 and entries[t]:
            position = 1
            entry_price = costs.apply_entry(curr_price, side=1)
            bars_held = 0

        # 3. Mark to market equity
        if position == 1:
            cur_unrealized = (curr_price - entry_price) / entry_price - costs.commission_rate
            equity_series[t] = cash * (1.0 + cur_unrealized)
        else:
            equity_series[t] = cash

    # Compute continuous daily equity & metrics
    equity_df = pl.DataFrame({
        "timestamp": timestamps,
        "equity": equity_series,
    })

    # Performance calculations
    total_trades = len(trades)
    win_trades = [tr for tr in trades if tr["net_pnl_pct"] > 0]
    win_rate = len(win_trades) / total_trades if total_trades > 0 else 0.0

    total_return = (cash - initial_capital) / initial_capital
    
    # Drawdown
    cum_max = np.maximum.accumulate(equity_series)
    drawdowns = (cum_max - equity_series) / cum_max
    max_drawdown = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

    # Downsample to daily for non-inflated Sharpe ratio
    daily_equity = (
        equity_df.with_columns(pl.col("timestamp").cast(pl.Utf8).str.slice(0, 10).alias("date"))
        .group_by("date")
        .agg(pl.col("equity").last())
        .sort("date")
    )

    daily_returns = daily_equity["equity"].pct_change().drop_nulls().to_numpy()
    if len(daily_returns) > 1 and np.std(daily_returns) > 0:
        annualized_sharpe = float(np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(252))
        downside = daily_returns[daily_returns < 0]
        sortino = (
            float(np.mean(daily_returns) / np.std(downside) * np.sqrt(252))
            if len(downside) > 0 and np.std(downside) > 0
            else 0.0
        )
    else:
        annualized_sharpe = 0.0
        sortino = 0.0

    # Profit Factor
    wins = sum(t["net_pnl_pct"] for t in trades if t["net_pnl_pct"] > 0)
    losses = abs(sum(t["net_pnl_pct"] for t in trades if t["net_pnl_pct"] < 0))
    profit_factor = float(wins / losses) if losses > 0 else (10.0 if wins > 0 else 1.0)

    return {
        "initial_capital": initial_capital,
        "ending_equity": float(cash),
        "total_return_pct": float(total_return * 100),
        "total_trades": total_trades,
        "win_rate_pct": float(win_rate * 100),
        "profit_factor": profit_factor,
        "max_drawdown_pct": float(max_drawdown * 100),
        "annualized_sharpe": annualized_sharpe,
        "sortino_ratio": sortino,
        "daily_equity": daily_equity,
        "trades": trades,
    }
