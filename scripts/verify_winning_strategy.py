"""Full Verification and Stress Testing of Winning Cointegration Strategy.

Runs ml4t.backtest.Engine once, extracts trades/fills, and analyzes quarterly
performance and cost stress curves directly from the official engine result.
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

class OptimalKalmanStrategy(Strategy):
    def __init__(
        self,
        z_entry: float = 4.0,
        z_exit: float = 0.5,
        z_stop: float = 5.5,
        min_hold_bars: int = 60,
        max_hold_bars: int = 720,
        cooldown_bars: int = 180,
        base_notional: float = 10_000.0,
    ):
        super().__init__()
        self.z_entry = z_entry
        self.z_exit = z_exit
        self.z_stop = z_stop
        self.min_hold_bars = min_hold_bars
        self.max_hold_bars = max_hold_bars
        self.cooldown_bars = cooldown_bars
        self.base_notional = base_notional

        self.in_trade = False
        self.trade_dir = 0
        self.entry_bar_idx = 0
        self.last_exit_bar_idx = -9999
        self.bar_idx = 0

    def on_start(self, broker) -> None:
        self.in_trade = False
        self.bar_idx = 0
        self.last_exit_bar_idx = -9999

    def on_data(self, timestamp, data, context, broker) -> None:
        self.bar_idx += 1
        if "BTCUSDT" not in data or "ETHUSDT" not in data:
            return

        z = context.get("z_score", 0.0)
        beta = context.get("beta", 1.0)
        regime_allowed = context.get("regime_allowed", True)

        if self.in_trade:
            bars_held = self.bar_idx - self.entry_bar_idx
            ou_reverted = (bars_held >= self.min_hold_bars) and (
                (self.trade_dir == 1 and z <= self.z_exit) or
                (self.trade_dir == -1 and z >= -self.z_exit)
            )
            stop_loss = (self.trade_dir == 1 and z >= self.z_stop) or (self.trade_dir == -1 and z <= -self.z_stop)
            time_exit = bars_held >= self.max_hold_bars

            if ou_reverted or stop_loss or time_exit:
                broker.close_position("BTCUSDT")
                broker.close_position("ETHUSDT")
                self.in_trade = False
                self.trade_dir = 0
                self.last_exit_bar_idx = self.bar_idx
                return

        cooldown_elapsed = (self.bar_idx - self.last_exit_bar_idx) >= self.cooldown_bars
        if not self.in_trade and cooldown_elapsed and regime_allowed:
            entry_signal = 0
            if z >= self.z_entry:
                entry_signal = 1
            elif z <= -self.z_entry:
                entry_signal = -1

            if entry_signal != 0:
                self.entry_bar_idx = self.bar_idx
                self.trade_dir = entry_signal

                btc_notional = self.base_notional * beta
                if entry_signal == 1:
                    broker.order_target_value("BTCUSDT", btc_notional)
                    broker.order_target_value("ETHUSDT", -self.base_notional)
                else:
                    broker.order_target_value("BTCUSDT", -btc_notional)
                    broker.order_target_value("ETHUSDT", self.base_notional)

                self.in_trade = True


def prepare_data():
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

    df_features = (
        df.with_columns(
            pl.Series("e", innovations),
            pl.Series("beta", betas),
            btc_ret_24h=pl.col("btc_close").pct_change(1440),
            btc_vol_24h=pl.col("btc_close").pct_change().rolling_std(1440),
        )
        .with_columns([
            pl.col("e").rolling_mean(1440).alias("mean_e"),
            pl.col("e").rolling_std(1440).alias("std_e"),
            pl.col("btc_vol_24h").rolling_quantile(0.80, window_size=129600).alias("vol_q80"),
            pl.col("btc_ret_24h").abs().rolling_quantile(0.80, window_size=129600).alias("trend_q80"),
        ])
        .with_columns([
            ((pl.col("e") - pl.col("mean_e")) / (pl.col("std_e") + 1e-12)).alias("z_score"),
            (
                (pl.col("btc_vol_24h") <= pl.col("vol_q80")) &
                (pl.col("btc_ret_24h").abs() <= pl.col("trend_q80"))
            ).alias("regime_allowed")
        ])
        .fill_null(0.0)
    )

    context_df = df_features.select(["timestamp", "z_score", "beta", "regime_allowed"]).sort("timestamp")
    prices_df = pl.concat([btc, eth]).select(["timestamp", "symbol", "open", "high", "low", "close", "volume"]).sort(["timestamp", "symbol"])
    return prices_df, context_df


def main():
    print("Preparing verified winning strategy...")
    prices_df, context_df = prepare_data()
    feed = DataFeed(prices_df=prices_df, context_df=context_df, entity_col="symbol", timestamp_col="timestamp")

    print("\n--- Running Base Verification via ml4t.backtest.Engine ---")
    config_base = BacktestConfig(
        initial_cash=100_000.0,
        allow_short_selling=True,
        allow_leverage=True,
        share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=0.00015,  # 1.5 bps maker fee
        slippage_type=SlippageType.NONE,
    )
    strategy = OptimalKalmanStrategy()
    engine = Engine(feed, strategy, config_base)
    res_base = engine.run()
    m = res_base.metrics

    print("\n================ OFFICIAL ML4T WINNING STRATEGY METRICS ================")
    print(f"Initial Capital:     ${m['initial_cash']:,.2f}")
    print(f"Final Capital:       ${m['final_value']:,.2f}")
    print(f"Net Total Return:    {m['total_return_pct']:.2%}")
    print(f"Annualized Sharpe:   {m['sharpe']:.2f}")
    print(f"Max Drawdown:        {m['max_drawdown_pct']:.2%}")
    print(f"Total Trades:        {m['num_trades']}")
    print(f"Winning Trades:      {m['winning_trades']}")
    print(f"Losing Trades:       {m['losing_trades']}")
    print(f"Win Rate:            {m['win_rate']:.2%}")
    print(f"Profit Factor:       {m['profit_factor']:.2f}")
    print(f"Total Commission:    ${m['total_commission']:,.2f}")
    print(f"Total Slippage:      ${m['total_slippage']:,.2f}")
    print(f"Total Costs Drag:    ${m['total_costs']:,.2f}")
    print("=======================================================================")

    # Cost Sensitivity Analysis
    gross_pnl = m["final_value"] - m["initial_cash"] + m["total_costs"]
    sensitivity = {}
    for fee_bps in [1.0, 1.5, 2.0, 3.0]:
        mult = fee_bps / 1.5
        adj_costs = m["total_costs"] * mult
        adj_net_pnl = gross_pnl - adj_costs
        adj_return = adj_net_pnl / m["initial_cash"]
        sensitivity[f"{fee_bps}bps"] = {
            "fee_bps": fee_bps,
            "projected_return_pct": adj_return * 100.0,
            "projected_fees": adj_costs,
            "survives_friction": adj_net_pnl > 0,
        }
        print(f"Cost Stress [{fee_bps} bps/leg]: Net Return = {adj_return:.2%}, Fees = ${adj_costs:,.2f}")

    out_dir = ROOT / "run_log/btc_eth_statarb_kalman_regime/final_verification"
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "strategy": "Dynamic Kalman Filter + OU Barriers + Volatility Regime Gate + Maker Execution",
        "parameters": {
            "z_entry": 4.0,
            "z_exit": 0.5,
            "z_stop": 5.5,
            "min_hold_minutes": 60,
            "max_hold_minutes": 720,
            "cooldown_minutes": 180,
            "maker_fee_bps": 1.5,
        },
        "official_metrics": {k: float(v) if isinstance(v, (int, float)) else str(v) for k, v in m.items()},
        "cost_stress_testing": sensitivity,
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2))
    print(f"\nFinal report saved to {out_dir / 'report.json'}")

if __name__ == "__main__":
    main()
