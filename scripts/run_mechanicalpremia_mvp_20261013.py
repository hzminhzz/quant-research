"""Execute one preregistered Mechanical Premia development trial on native ML4T.

Example:
  uv run python -m scripts.run_mechanicalpremia_mvp_20261013 --trial H1-ONLY
Never opens/aggregates observations from 2025-01-01 onward.
This is a price-proxy exploratory run. Broker-cost, trailing-stop entry-minute
protection and original MT5 session fidelity are NOT certified.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl
from ml4t.diagnostic.api import PortfolioAnalysis

from scripts.mechanicalpremia_native_20261013 import (
    ROOT, HOLDOUT, TRIAL_WEIGHTS, build_signals, load_development, run_native,
)

OUT = ROOT / "run_log" / "research_sessions" / "mechanicalpremia-two-engine-mvp-20261013" / "native_research_v2"


def run(trial: str, *, assets: list[str],
        until: datetime = HOLDOUT, cost_multiplier: float = 1.0):
    if until > HOLDOUT:
        raise ValueError("Never open protected data")
    frames = []
    for asset in assets:
        prices = load_development(asset, until=until)
        feature = build_signals(prices)
        print(
            "FEATURES", asset, prices.height,
            feature.select("h_enter", "d_enter", "d_exit").sum().to_dicts(),
            flush=True,
        )
        frames.append(feature)
    full = pl.concat(frames).sort("timestamp", "asset")
    strategy, result = run_native(
        full, trial, commission_bps=1.0 * cost_multiplier,
        slippage_bps=2.0 * cost_multiplier,
    )
    out = OUT / trial / ("_".join(assets)) / f"cost_{cost_multiplier:g}x"
    out.mkdir(parents=True, exist_ok=True)
    fills = result.to_fills_dataframe()
    trades = result.to_trades_dataframe()
    fills.write_parquet(out / "native_fills.parquet")
    trades.write_parquet(out / "native_trades.parquet")
    curve = pl.DataFrame({
        "timestamp": [timestamp for timestamp, _ in result.equity_curve],
        "equity": [float(value) for _, value in result.equity_curve],
    }).sort("timestamp")
    if curve.is_empty():
        raise AssertionError("Native Engine returned no equity curve")
    daily = (curve.with_columns(
        day=pl.col("timestamp").dt.convert_time_zone("America/New_York").dt.date())
        .group_by("day").agg(pl.col("equity").last()).sort("day")
        .with_columns(pl.col("equity").pct_change().fill_null(0).alias("return")))
    daily.write_parquet(out / "daily_equity.parquet")
    risk = PortfolioAnalysis(
        returns=daily["return"].to_numpy(), periods_per_year=252,
    ).compute_summary_stats()
    def _json_native(value):
        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, (datetime,)):
            return value.isoformat()
        return str(value)
    risk_metrics = {
        key: value for key, value in vars(risk).items()
        if isinstance(value, (int, float, np.generic, str, type(None)))
    }
    native_metrics = {
        key: value for key, value in result.metrics.items()
        if isinstance(value, (int, float, np.generic, str, type(None)))
    }
    closed = trades.filter(pl.col("status") == "closed")
    year = (closed.with_columns(
        year=pl.col("exit_time").dt.year()
    ).group_by("year").agg(
        pl.len().alias("trades"), pl.col("pnl").sum().alias("net_pnl"),
        (pl.col("pnl") > 0).mean().alias("win_rate")
    ).sort("year")) if closed.height else pl.DataFrame()
    if year.height:
        year.write_parquet(out / "closed_trade_yearly.parquet")
    summary = {
        "feature_revision": "v2_mql5_upper_middle_median",
        "status": "ENGINEERED_NATIVE_EXECUTION_UNQUALIFIED_PROXY",
        "research_session": "mechanicalpremia-two-engine-mvp-20261013",
        "trial": trial,
        "assets": assets,
        "start": str(full["timestamp"].min()),
        "last_authorized_bar": str(full["timestamp"].max()),
        "holdout_start": str(HOLDOUT),
        "bars_per_asset": {asset: frames[i].height for i, asset in enumerate(assets)},
        "cost_multiplier": cost_multiplier,
        "commission_bps_per_side": 1.0 * cost_multiplier,
        "slippage_bps_per_side": 2.0 * cost_multiplier,
        "spread_cost_bps": "UNKNOWN",
        "financing": "UNKNOWN",
        "native_metrics": native_metrics,
        "daily_risk_metrics": risk_metrics,
        "native_rejections": strategy.native_rejections[:25],
        "final_native_broker_cash": strategy.end_cash,
        "final_native_broker_equity": strategy.end_equity,
        "final_native_positions": strategy.end_positions,
        "cash_plus_positions_equals_equity": abs(strategy.end_equity - strategy.end_cash - sum(
            p["quantity"] * p["current_price"] * p["multiplier"]
            for p in strategy.end_positions.values())) < 0.01,
        "native_rejection_count": len(strategy.native_rejections),
        "order_intents_h1": strategy.h_entry_count,
        "order_intents_d1": strategy.d_entry_count,
        "intent_rejects": strategy.intent_rejects,
        "closed_trade_years": year.to_dicts(),
        "unresolved_fidelity": [
            "Actual Dukascopy/broker CFD contract size, tick/lot, funding, quotes, spread, holidays are not certified",
            "17:00 America/New_York daily session boundary is a research assumption, not proven source MT5 clock",
            "H1 stop installed after first broker confirmation: the entry minute is unprotected",
            "OHLC-only feed: reconstructed spread and stop gap fills cannot prove broker execution",
            "Synthetic price-unit fractional share sizing cannot be called a real CFD lot backtest",
            "Native H1 trailing uses source prior ATR and proxy close rather than actual live BID sampled every 60 s",
            "Portfolio native legs use _H/_D synthetic instruments to preserve independent strategy positions",
            "Only 2024 available before protected holdout in frozen ES/NQ files; insufficient for robust validation",
        ],
        "paths": {
            "fills": str(out / "native_fills.parquet"),
            "trades": str(out / "native_trades.parquet"),
            "daily_equity": str(out / "daily_equity.parquet"),
        },
    }
    def clean(value):
        if isinstance(value, np.generic):
            return clean(value.item())
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [clean(v) for v in value]
        return value
    cleaned = clean(summary)
    report = json.dumps(cleaned, default=_json_native, indent=2, allow_nan=False)
    (out / "summary.json").write_text(report)
    print(report, flush=True)
    return cleaned


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trial", choices=list(TRIAL_WEIGHTS), required=True)
    parser.add_argument("--assets", default="ES_PROXY,NQ_PROXY")
    parser.add_argument("--cost-multiplier", type=float, choices=[1.0, 1.5, 2.0], default=1.0)
    parser.add_argument("--until", default="2025-01-01")
    args = parser.parse_args()
    until = datetime.fromisoformat(args.until).replace(tzinfo=timezone.utc)
    run(args.trial, assets=args.assets.split(","), until=until, cost_multiplier=args.cost_multiplier)


if __name__ == "__main__":
    main()
