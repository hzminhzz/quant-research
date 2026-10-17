"""Official 3-Stage ML4T Pipeline for BTC/ETH Monk Pair Trading Scalp.

Implements:
  Stage 1: Feature & Label Engineering via ml4t.engineer & Polars patterns (.over('symbol'))
  Stage 2: Signal & Factor Diagnostics via ml4t.diagnostic.analyze_signal
  Stage 3: Event-Driven Backtest via ml4t.backtest (Engine, Strategy, BacktestConfig)
"""

from __future__ import annotations

import json
from pathlib import Path
import polars as pl

# ML4T Imports
from ml4t.engineer import compute_features
from ml4t.diagnostic import analyze_signal
from ml4t.backtest import BacktestConfig, DataFeed, Engine, Strategy
from ml4t.backtest.config import CommissionType, ShareType, SlippageType

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# STAGE 1: Feature & Label Engineering (ml4t.engineer + Polars Patterns)
# ---------------------------------------------------------------------------
def stage1_engineer_features(prices_lazy: pl.LazyFrame) -> pl.DataFrame:
    """Engineer multi-horizon returns, spread divergence, and volatility features.

    Adheres to ml4t-polars-patterns:
    - Lazy execution with scan_parquet
    - Vectorized per-symbol rolling operations with .over('symbol')
    - Vectorized cross-sectional operations with .over('timestamp')
    - All rolling features in a single with_columns call
    - No Python UDFs (.map_elements)
    """
    print("\n--- STAGE 1: ml4t.engineer & Polars Feature Engineering ---")

    # 1. Compute per-symbol base returns and momentum in a single vectorized with_columns call
    df_features = (
        prices_lazy
        .sort(["symbol", "timestamp"])
        .with_columns(
            returns=pl.col("close").pct_change().over("symbol"),
            ret_15m=pl.col("close").pct_change(15).over("symbol"),
            ret_30m=pl.col("close").pct_change(30).over("symbol"),
            ret_60m=pl.col("close").pct_change(60).over("symbol"),
            ret_240m=pl.col("close").pct_change(240).over("symbol"),
        )
    )

    # 2. Enrich using ml4t.engineer's official feature catalog
    print("Computing realized volatility via ml4t.engineer...")
    enriched = compute_features(
        df_features,
        features=["realized_volatility"],
        group_col="symbol",
        timestamp_col="timestamp",
    )
    df_collected = enriched.collect() if isinstance(enriched, pl.LazyFrame) else enriched

    print(f"Features computed. Shape: {df_collected.shape}")
    return df_collected


# ---------------------------------------------------------------------------
# STAGE 2: Factor & Signal Diagnostics (ml4t.diagnostic)
# ---------------------------------------------------------------------------
def stage2_diagnose_signal(df: pl.DataFrame):
    """Analyze the predictive information coefficient (IC) and decay of the spread signal."""
    print("\n--- STAGE 2: ml4t.diagnostic Factor Evaluation ---")

    # Divergence signal: ETH 60m return minus BTC 60m return
    pivoted = (
        df.select(["timestamp", "symbol", "ret_60m"])
        .pivot(on="symbol", index="timestamp", values="ret_60m")
        .with_columns(
            spread_factor=(pl.col("ETHUSDT") - pl.col("BTCUSDT"))
        )
        .drop_nulls()
    )

    # Prepare factors and prices for ml4t.diagnostic.analyze_signal
    # When spread_factor > 0 (ETH pumped more), strategy shorts ETH and longs BTC.
    # Therefore, factor score is +spread_factor for BTC and -spread_factor for ETH.
    factors = (
        df.select(["timestamp", "symbol"])
        .join(pivoted.select(["timestamp", "spread_factor"]), on="timestamp", how="inner")
        .with_columns(
            factor=pl.when(pl.col("symbol") == "BTCUSDT")
            .then(pl.col("spread_factor"))
            .otherwise(-pl.col("spread_factor"))
        )
        .select(["timestamp", "symbol", "factor"])
        .rename({"timestamp": "date", "symbol": "asset"})
        .sort(["date", "asset"])
    )

    prices = (
        df.select(["timestamp", "symbol", "close"])
        .rename({"timestamp": "date", "symbol": "asset", "close": "price"})
        .sort(["date", "asset"])
    )

    print("Running ml4t.diagnostic.analyze_signal across forward periods...")
    diag_res = analyze_signal(
        factor=factors,
        prices=prices,
        periods=(15, 60, 240, 1440),
        quantiles=2,
        min_assets=2,
        compute_turnover_flag=False,
    )

    print(f"Information Coefficient (Rank IC) across horizons: {diag_res.ic}")
    return diag_res


# ---------------------------------------------------------------------------
# STAGE 3: Event-Driven Backtesting (ml4t.backtest)
# ---------------------------------------------------------------------------
class MonkPairTradingStrategy(Strategy):
    """Monk BTC/ETH Pair Trading Strategy implemented on ml4t.backtest.Strategy."""

    def __init__(
        self,
        divergence_threshold: float = 0.02,
        max_hold_bars: int = 1440,
        base_notional: float = 10_000.0,
    ):
        super().__init__()
        self.divergence_threshold = divergence_threshold
        self.max_hold_bars = max_hold_bars
        self.base_notional = base_notional

        self.in_trade = False
        self.entry_bar_idx = 0
        self.trade_dir = 0
        self.entry_equity = 0.0
        self.bar_idx = 0

    def on_start(self, broker) -> None:
        self.in_trade = False
        self.bar_idx = 0

    def on_data(self, timestamp, data, context, broker) -> None:
        self.bar_idx += 1
        if "BTCUSDT" not in data or "ETHUSDT" not in data:
            return

        # 1. Exit logic if in trade
        if self.in_trade:
            bars_held = self.bar_idx - self.entry_bar_idx
            current_equity = broker.get_account_value()
            net_pnl = current_equity - self.entry_equity

            # Exit if in profit net of fees, or max 24h hold reached
            if net_pnl > 0 or bars_held >= self.max_hold_bars:
                broker.close_position("BTCUSDT")
                broker.close_position("ETHUSDT")
                self.in_trade = False
                self.trade_dir = 0
                return

        # 2. Entry logic if flat
        if not self.in_trade:
            btc_ret_60 = context.get("btc_ret_60", 0.0)
            spread_div = context.get("spread_div", 0.0)

            entry_signal = 0
            if btc_ret_60 > 0 and spread_div >= self.divergence_threshold:
                # Pump: Long BTC / Short ETH
                entry_signal = 1
            elif btc_ret_60 < 0 and spread_div <= -self.divergence_threshold:
                # Dump: Short BTC / Long ETH
                entry_signal = -1

            if entry_signal != 0:
                self.entry_equity = broker.get_account_value()
                self.entry_bar_idx = self.bar_idx
                self.trade_dir = entry_signal

                if entry_signal == 1:
                    broker.order_target_value("BTCUSDT", self.base_notional)
                    broker.order_target_value("ETHUSDT", -self.base_notional)
                else:
                    broker.order_target_value("BTCUSDT", -self.base_notional)
                    broker.order_target_value("ETHUSDT", self.base_notional)

                self.in_trade = True


def stage3_run_backtest(df: pl.DataFrame):
    """Run event-driven simulation using ml4t.backtest Engine and BacktestConfig."""
    print("\n--- STAGE 3: ml4t.backtest Execution Simulation ---")

    # Pivot to get clean market context per timestamp
    pivoted = (
        df.select(["timestamp", "symbol", "ret_60m"])
        .pivot(on="symbol", index="timestamp", values="ret_60m")
        .rename({"BTCUSDT": "btc_ret_60", "ETHUSDT": "eth_ret_60"})
        .with_columns(
            spread_div=(pl.col("eth_ret_60") - pl.col("btc_ret_60"))
        )
        .fill_null(0.0)
        .sort("timestamp")
    )

    context_df = pivoted.select(["timestamp", "btc_ret_60", "eth_ret_60", "spread_div"])
    prices_df = df.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"]).sort(["timestamp", "symbol"])

    feed = DataFeed(
        prices_df=prices_df,
        context_df=context_df,
        entity_col="symbol",
        timestamp_col="timestamp",
    )
    print(f"Created DataFeed with {feed.n_bars} bars.")

    config = BacktestConfig(
        initial_cash=100_000.0,
        allow_short_selling=True,
        allow_leverage=True,
        share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=0.0004,  # 4 bps Binance VIP0 taker fee
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=0.0002,    # 2 bps conservative slippage
    )

    strategy = MonkPairTradingStrategy(
        divergence_threshold=0.02,
        max_hold_bars=1440,
        base_notional=10_000.0,
    )

    print("Running ml4t.backtest.Engine...")
    engine = Engine(feed, strategy, config)
    result = engine.run()
    metrics = result.metrics

    print("\n================ ML4T BACKTEST ENGINE METRICS ================")
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
    print("==============================================================")

    # Save official pipeline results to run_log
    out_dir = ROOT / "run_log/btc_eth_pair_trading_scalp/official_ml4t_pipeline"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metrics.json").write_text(json.dumps({k: float(v) if isinstance(v, (int, float)) else str(v) for k, v in metrics.items()}, indent=2))
    print(f"Saved official metrics to {out_dir / 'metrics.json'}")
    return result


def main():
    btc_path = ROOT / "data/processed/btc_1m.parquet"
    eth_path = ROOT / "data/processed/eth_1m.parquet"

    btc_lazy = pl.scan_parquet(btc_path)
    eth_lazy = pl.scan_parquet(eth_path)
    prices_lazy = pl.concat([btc_lazy, eth_lazy])

    # Stage 1: Feature Engineering via ml4t.engineer & Polars
    df_features = stage1_engineer_features(prices_lazy)

    # Stage 2: Signal Diagnostics via ml4t.diagnostic
    stage2_diagnose_signal(df_features)

    # Stage 3: Event-Driven Backtest via ml4t.backtest
    stage3_run_backtest(df_features)


if __name__ == "__main__":
    main()
