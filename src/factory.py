"""ML4T Systematic Strategy Factory.

Vectorized signal generation, factor diagnostics, and institutional backtesting
for Breakout and Mean-Reversion strategy families across Germany 40 (DAX) and Nikkei 225.
"""

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import ml4t.diagnostic as mld
from ml4t.diagnostic.evaluation.stats import deflated_sharpe_ratio_from_statistics
import ml4t.engineer as mle
from ml4t.backtest import BacktestConfig, Strategy, run_backtest
from ml4t.backtest.config import CommissionType, SlippageType
import numpy as np
import polars as pl


def compute_factory_features(df_15m: pl.DataFrame) -> pl.DataFrame:
    """Resample 15m OHLCV to 1H bars and compute technical indicator suite with ml4t-engineer.

    Guarantees zero forward lookahead bias by shifting rolling windows appropriately.
    """
    df_1h = (
        df_15m.group_by_dynamic("timestamp", every="1h")
        .agg([
            pl.col("open").first(),
            pl.col("high").max(),
            pl.col("low").min(),
            pl.col("close").last(),
            pl.col("volume").sum(),
            pl.col("symbol").first(),
        ])
        .drop_nulls()
    )

    df_feat = mle.compute_features(
        df_1h,
        [
            {"name": "rsi", "params": {"period": 2}, "output": "rsi_2"},
            {"name": "rsi", "params": {"period": 5}, "output": "rsi_5"},
            {"name": "rsi", "params": {"period": 14}, "output": "rsi_14"},
            {"name": "atr", "params": {"period": 14}, "output": "atr_14"},
            {"name": "adx", "params": {"period": 14}, "output": "adx_14"},
            {"name": "ema", "params": {"period": 20}, "output": "ema_20"},
            {"name": "ema", "params": {"period": 50}, "output": "ema_50"},
            {"name": "ema", "params": {"period": 200}, "output": "ema_200"},
            {
                "name": "bollinger_bands",
                "params": {"period": 20, "nbdevup": 2.0, "nbdevdn": 2.0},
            },
        ],
        timestamp_col="timestamp",
    )

    c = pl.col("close")
    o = pl.col("open")
    h = pl.col("high")
    l = pl.col("low")
    atr = pl.col("atr_14")

    # Bollinger Bands
    bb_upper = pl.col("bollinger_bands").struct.field("upper")
    bb_lower = pl.col("bollinger_bands").struct.field("lower")
    bb_mid = pl.col("bollinger_bands").struct.field("middle")

    # Donchian rolling channels (strictly using prior bars)
    donchian_high_10 = pl.col("high").shift(1).rolling_max(window_size=10)
    donchian_high_20 = pl.col("high").shift(1).rolling_max(window_size=20)
    donchian_low_20 = pl.col("low").shift(1).rolling_min(window_size=20)

    # Candlestick geometry
    candle_range = h - l
    candle_body = (c - o).abs()
    lower_wick = pl.when(c > o).then(o - l).otherwise(c - l)
    upper_wick = pl.when(c > o).then(h - c).otherwise(h - o)

    # Bullish / Bearish engulfing definition
    po = pl.col("open").shift(1)
    pc = pl.col("close").shift(1)
    bull_engulf = (pc < po) & (c > o) & (o <= pc) & (c >= po)
    bear_engulf = (pc >= po) & (c < o) & (o >= pc) & (c <= po)

    # Forward returns for factor diagnostics (20 bars = ~1 day)
    fwd_ret_20 = (c.shift(-20) / c - 1.0).alias("fwd_ret_20")

    # Slice warmup bars if dataset is large enough
    if len(df_feat) > 205:
        df_feat = df_feat.slice(205)

    return df_feat.with_columns([
        bb_upper.alias("bb_upper"),
        bb_lower.alias("bb_lower"),
        bb_mid.alias("bb_mid"),
        donchian_high_10.alias("donchian_high_10"),
        donchian_high_20.alias("donchian_high_20"),
        donchian_low_20.alias("donchian_low_20"),
        candle_range.alias("candle_range"),
        candle_body.alias("candle_body"),
        lower_wick.alias("lower_wick"),
        upper_wick.alias("upper_wick"),
        bull_engulf.alias("bull_engulf"),
        bear_engulf.alias("bear_engulf"),
        ((c - pl.col("ema_50")) / atr).alias("ema50_stretch"),
        fwd_ret_20,
    ])


def get_breakout_strategies() -> Dict[str, Dict[str, Any]]:
    """Return the 3 verified Breakout Strategy definitions."""
    return {
        "B1: Donchian 10h Breakout + Trend": {
            "name": "Donchian 10h Breakout + Trend",
            "family": "Breakout",
            "description": (
                "New 10-bar high breakout with 200 EMA macro trend and RSI"
                " confirmation"
            ),
            "expr": (
                (pl.col("close") > pl.col("donchian_high_10"))
                & (pl.col("close") > pl.col("ema_200"))
                & (pl.col("rsi_14") > 52)
            ),
            "hold_bars": 20,
        },
        "B2: Trend Continuation Expansion": {
            "name": "Trend Continuation Expansion",
            "family": "Breakout",
            "description": (
                "Impulse break above prior high with body >= 0.5 ATR in bull"
                " trend"
            ),
            "expr": (
                (pl.col("close") > pl.col("high").shift(1))
                & (pl.col("candle_body") > 0.5 * pl.col("atr_14"))
                & (pl.col("close") > pl.col("ema_200"))
                & (pl.col("ema_50") > pl.col("ema_200"))
            ),
            "hold_bars": 20,
        },
        "B3: Bollinger Band Upper Thrust": {
            "name": "Bollinger Band Upper Thrust",
            "family": "Breakout",
            "description": (
                "Closing thrust above 2.0-std upper Bollinger Band with ADX"
                " trend strength"
            ),
            "expr": (
                (pl.col("close") > pl.col("bb_upper"))
                & (pl.col("adx_14") >= 18)
                & (pl.col("close") > pl.col("ema_200"))
            ),
            "hold_bars": 24,
        },
    }


def get_mean_reversion_strategies() -> Dict[str, Dict[str, Any]]:
    """Return the 3 verified Mean-Reversion Strategy definitions."""
    return {
        "M1: Dual RSI Oversold Dip": {
            "name": "Dual RSI Oversold Dip",
            "family": "Mean Reversion",
            "description": (
                "Confluence of ultra-short RSI_2 < 15 and medium-term RSI_14 <"
                " 45"
            ),
            "expr": (pl.col("rsi_2") < 15) & (pl.col("rsi_14") < 45),
            "hold_bars": 20,
        },
        "M2: Volatility-Filtered Engulfing Dip": {
            "name": "Volatility-Filtered Engulfing Dip",
            "family": "Mean Reversion",
            "description": (
                "Bullish engulfing with significant body (>=0.35 ATR) on"
                " intraday pullback (RSI < 55)"
            ),
            "expr": (
                (pl.col("bull_engulf"))
                & (pl.col("candle_body") > 0.35 * pl.col("atr_14"))
                & (pl.col("rsi_14").shift(1) < 55)
            ),
            "hold_bars": 20,
        },
        "M3: EMA Mean-Reversion Snapback": {
            "name": "EMA Mean-Reversion Snapback",
            "family": "Mean Reversion",
            "description": (
                "Severe downward stretch (< -1.4 ATR below EMA50) with"
                " oversold RSI_5 < 30"
            ),
            "expr": (pl.col("ema50_stretch") < -1.4) & (pl.col("rsi_5") < 30),
            "hold_bars": 20,
        },
    }


class FactoryExecutionEngine(Strategy):
    """Institutional event-driven strategy executor with fixed holding timeout."""

    def __init__(self, max_hold_bars: int = 20):
        self.max_hold_bars = max_hold_bars

    def on_data(self, timestamp, data, context, broker):
        for asset, bar in data.items():
            pos = broker.get_position(asset)
            curr_p = bar["price"]
            sig = bar.get("signals", {}).get("signal", 0)

            if pos is not None:
                if pos.bars_held >= self.max_hold_bars:
                    broker.close_position(asset)
            elif pos is None:
                if sig == 1:
                    equity = broker.get_account_value()
                    shares = (equity * 0.95) / curr_p
                    if shares > 0:
                        broker.submit_order(asset, shares)


def run_strategy_backtest(
    df: pl.DataFrame,
    signal_expr: pl.Expr,
    hold_bars: int = 20,
    commission_bps: float = 2.0,
    slippage_bps: float = 1.0,
    n_trials: int = 50,
) -> Dict[str, Any]:
    """Execute event-driven backtest, compute metrics, and evaluate Deflated Sharpe Ratio."""
    sig_df = df.with_columns(
        pl.when(signal_expr).then(1).otherwise(0).alias("signal")
    ).select(["timestamp", "symbol", "signal"])

    cfg = BacktestConfig(
        initial_cash=100_000.0,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=commission_bps / 10_000.0,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=slippage_bps / 10_000.0,
    )

    res = run_backtest(
        df, FactoryExecutionEngine(hold_bars), signals=sig_df, config=cfg
    )
    eq_df = res.to_equity_dataframe()

    eq_daily = (
        eq_df.with_columns(pl.col("timestamp").dt.date().alias("date"))
        .group_by("date")
        .agg(pl.col("equity").last())
        .sort("date")
        .with_columns(pl.col("equity").pct_change().alias("daily_ret"))
        .drop_nulls()
    )

    daily_rets = eq_daily["daily_ret"].to_numpy()
    n_samples = len(daily_rets)
    if n_samples < 10:
        return {"error": "Insufficient trade days"}

    sr_ci = mld.metrics.sharpe_ratio_with_ci(
        daily_rets, periods_per_year=252, random_state=42
    )
    sortino = mld.metrics.sortino_ratio(daily_rets, periods_per_year=252)
    m = res.metrics

    dsr = deflated_sharpe_ratio_from_statistics(
        observed_sharpe=sr_ci["sharpe"],
        n_samples=n_samples,
        n_trials=n_trials,
        variance_trials=0.20,
    )

    # Spearman Rank IC on forward return
    df_eval = df.filter(pl.col("fwd_ret_20").is_not_null())
    sigs = (
        df_eval.select(signal_expr.alias("sig"))
        .to_series()
        .fill_null(False)
        .cast(pl.Float64)
    )
    rets = df_eval["fwd_ret_20"]
    ic_res = mld.metrics.pooled_ic(
        sigs.to_numpy(), rets.to_numpy(), method="spearman", confidence_intervals=True
    )

    return {
        "sharpe": float(sr_ci["sharpe"]),
        "sharpe_ci": [float(sr_ci["lower_ci"]), float(sr_ci["upper_ci"])],
        "sortino": float(sortino),
        "total_return_pct": float(m.get("total_return_pct", 0.0)),
        "win_rate_pct": float(m.get("win_rate", 0.0) * 100.0),
        "profit_factor": float(m.get("profit_factor", 0.0)),
        "max_drawdown_pct": float(m.get("max_drawdown_pct", 0.0)),
        "num_trades": int(m.get("num_trades", 0)),
        "rank_ic": float(ic_res["ic"]),
        "p_value": float(ic_res["p_value"]),
        "dsr_probability": float(dsr.probability),
        "dsr_haircut_sharpe": float(dsr.deflated_sharpe),
        "equity_dataframe": eq_df,
    }


def append_trial(
    trial_data: Dict[str, Any], filepath: str = "run_log/trials.jsonl"
) -> None:
    """Append strategy trial to the JSONL ledger for multiple-testing audit tracking."""
    p = Path(filepath)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(trial_data) + "\n")
