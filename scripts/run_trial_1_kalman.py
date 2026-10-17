"""Candidate 1: Dynamic State-Space Kalman Filter Hedge Ratio with OU Optimal Barriers.

Trial ID: trial_1_kalman_ou_baseline
Research Session: btc_eth_statarb_kalman_regime
"""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import polars as pl

from ml4t.backtest import BacktestConfig, DataFeed, Engine, Strategy
from ml4t.backtest.config import CommissionType, ShareType, SlippageType

ROOT = Path(__file__).resolve().parents[1]
SESSION_ID = "btc_eth_statarb_kalman_regime"
TRIAL_ID = "trial_1_kalman_ou_baseline"

class KalmanOUStrategy(Strategy):
    """Pair trading strategy with dynamic Kalman beta and OU barriers."""

    def __init__(
        self,
        z_entry: float = 2.5,
        z_exit: float = 0.5,
        z_stop: float = 4.5,
        max_hold_bars: int = 240,  # 4 hours
        base_notional: float = 10_000.0,
    ):
        super().__init__()
        self.z_entry = z_entry
        self.z_exit = z_exit
        self.z_stop = z_stop
        self.max_hold_bars = max_hold_bars
        self.base_notional = base_notional

        self.in_trade = False
        self.trade_dir = 0
        self.entry_bar_idx = 0
        self.bar_idx = 0

    def on_start(self, broker) -> None:
        self.in_trade = False
        self.bar_idx = 0

    def on_data(self, timestamp, data, context, broker) -> None:
        self.bar_idx += 1
        if "BTCUSDT" not in data or "ETHUSDT" not in data:
            return

        z = context.get("z_score", 0.0)
        beta = context.get("beta", 1.0)

        # 1. Exit logic if in trade
        if self.in_trade:
            bars_held = self.bar_idx - self.entry_bar_idx
            # Check OU mean-reversion exit, stop-loss, or max holding time
            ou_reverted = (self.trade_dir == 1 and z <= self.z_exit) or (self.trade_dir == -1 and z >= -self.z_exit)
            stop_loss = (self.trade_dir == 1 and z >= self.z_stop) or (self.trade_dir == -1 and z <= -self.z_stop)
            time_exit = bars_held >= self.max_hold_bars

            if ou_reverted or stop_loss or time_exit:
                broker.close_position("BTCUSDT")
                broker.close_position("ETHUSDT")
                self.in_trade = False
                self.trade_dir = 0
                return

        # 2. Entry logic if flat
        if not self.in_trade:
            entry_signal = 0
            if z >= self.z_entry:
                # ETH is overpriced relative to BTC equilibrium: Short ETH, Long BTC
                entry_signal = 1
            elif z <= -self.z_entry:
                # ETH is underpriced relative to BTC equilibrium: Long ETH, Short BTC
                entry_signal = -1

            if entry_signal != 0:
                self.entry_bar_idx = self.bar_idx
                self.trade_dir = entry_signal

                # Sizing: ETH notional = $10k, BTC notional = beta * $10k
                btc_notional = self.base_notional * beta
                if entry_signal == 1:
                    broker.order_target_value("BTCUSDT", btc_notional)
                    broker.order_target_value("ETHUSDT", -self.base_notional)
                else:
                    broker.order_target_value("BTCUSDT", -btc_notional)
                    broker.order_target_value("ETHUSDT", self.base_notional)

                self.in_trade = True


def prepare_kalman_context() -> tuple[pl.DataFrame, pl.DataFrame]:
    btc = pl.read_parquet("data/processed/btc_1m.parquet")
    eth = pl.read_parquet("data/processed/eth_1m.parquet")
    df = (
        btc.select(["timestamp", "close"])
        .rename({"close": "btc_close"})
        .join(eth.select(["timestamp", "close"]).rename({"close": "eth_close"}), on="timestamp", how="inner")
        .sort("timestamp")
    )
    n = df.height

    x = np.log(df["btc_close"].to_numpy())
    y = np.log(df["eth_close"].to_numpy())

    # Kalman Filter
    V = 1e-4
    W = np.diag([1e-6, 1e-6])
    theta = np.array([0.0, 1.0])
    P = np.eye(2) * 1.0

    innovations = np.zeros(n)
    betas = np.zeros(n)

    for t in range(n):
        P = P + W
        F = np.array([1.0, x[t]])
        e = y[t] - F @ theta
        Q = F @ P @ F + V
        K = (P @ F) / Q
        theta = theta + K * e
        P = P - np.outer(K, F @ P)
        betas[t] = theta[1]
        innovations[t] = e

    df_kf = df.with_columns(
        pl.Series("e", innovations),
        pl.Series("beta", betas),
    ).with_columns([
        pl.col("e").rolling_mean(1440).alias("mean_e"),
        pl.col("e").rolling_std(1440).alias("std_e"),
    ]).with_columns([
        ((pl.col("e") - pl.col("mean_e")) / (pl.col("std_e") + 1e-12)).alias("z_score")
    ]).fill_null(0.0)

    context_df = df_kf.select(["timestamp", "z_score", "beta"]).sort("timestamp")
    prices_df = pl.concat([btc, eth]).select(["timestamp", "symbol", "open", "high", "low", "close", "volume"]).sort(["timestamp", "symbol"])
    return prices_df, context_df


def run():
    print("Preparing Kalman Filter state-space signals...")
    prices_df, context_df = prepare_kalman_context()

    feed = DataFeed(
        prices_df=prices_df,
        context_df=context_df,
        entity_col="symbol",
        timestamp_col="timestamp",
    )
    print(f"DataFeed created with {feed.n_bars} bars.")

    config = BacktestConfig(
        initial_cash=100_000.0,
        allow_short_selling=True,
        allow_leverage=True,
        share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=0.0004,  # 4 bps taker fee
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=0.0002,    # 2 bps slippage
    )

    strategy = KalmanOUStrategy(
        z_entry=2.5,
        z_exit=0.5,
        z_stop=4.5,
        max_hold_bars=240,  # 4h time stop
        base_notional=10_000.0,
    )

    print("Running ml4t.backtest Engine for Candidate 1...")
    engine = Engine(feed, strategy, config)
    result = engine.run()
    metrics = result.metrics

    print("\n================ CANDIDATE 1 (KALMAN OU) METRICS ================")
    print(f"Initial Cash:        ${metrics['initial_cash']:,.2f}")
    print(f"Final Value:         ${metrics['final_value']:,.2f}")
    print(f"Total Return:        {metrics['total_return_pct']:.2%}")
    print(f"Annualized Sharpe:   {metrics['sharpe']:.2f}")
    print(f"Max Drawdown:        {metrics['max_drawdown_pct']:.2%}")
    print(f"Total Trades:        {metrics['num_trades']}")
    print(f"Winning Trades:      {metrics['winning_trades']}")
    print(f"Losing Trades:       {metrics['losing_trades']}")
    print(f"Win Rate:            {metrics['win_rate']:.2%}")
    print(f"Total Commission:    ${metrics['total_commission']:,.2f}")
    print(f"Total Slippage:      ${metrics['total_slippage']:,.2f}")
    print(f"Total Costs Drag:    ${metrics['total_costs']:,.2f}")
    print(f"Profit Factor:       {metrics['profit_factor']:.2f}")
    print("=================================================================")

    out_file = ROOT / f"run_log/{SESSION_ID}/{TRIAL_ID}/result.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps({k: float(v) if isinstance(v, (int, float)) else str(v) for k, v in metrics.items()}, indent=2))
    print(f"Saved artifact to {out_file}")
    return out_file

if __name__ == "__main__":
    run()
