"""User-authorized 2025/2026 YTD Mechanical Premia replication.

Real ml4t.backtest.Engine + ml4t.engineer features. NOT a 12y continuous
portfolio, not broker-executable; 2025/2026 YTD expressly authorized.
Usage:
  uv run python -m scripts.run_mechanicalpremia_authorized_2025_2026 --year 2025 --trial SOURCE-RISK-7
"""
from __future__ import annotations
import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
import polars as pl
import numpy as np
from ml4t.diagnostic.api import PortfolioAnalysis
from scripts.mechanicalpremia_authorized_2025_2026_adapter import (
    ROOT, HOLDOUT, build_signals, load_development, run_native,
)
SESSION = "mechanicalpremia-authorized-2025-2026-ytd-v1"
OUT = ROOT / "run_log" / "research_sessions" / SESSION / "yearly_native"
REGISTRY = {"US500": 2013, "US100": 2013, "DE30": 2013, "EU50": 2014}
TRIALS = {"H1-SOURCE-3": "H1-ONLY", "D1-SOURCE-4": "D1-ONLY",
          "EQUAL-RISK-7": "PORTFOLIO-EQUAL-RISK",
          "SOURCE-RISK-7": "PORTFOLIO-SOURCE-RISK",
          "COST-STRESS": "PORTFOLIO-SOURCE-RISK"}

def json_clean(value):
    if isinstance(value, np.generic):
        return json_clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: json_clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_clean(v) for v in value]
    return value

def execute(year: int, trial: str, cost_mult: float = 1.0) -> dict:
    if year not in (2025, 2026) or trial not in TRIALS:
        raise ValueError("Year/trial outside preregistered development")
    if cost_mult not in (1.0, 1.5, 2.0):
        raise ValueError("Only 1.0/1.5/2.0 direct-cost stress permitted")
    if trial != "COST-STRESS" and cost_mult != 1.0:
        raise ValueError("Only COST-STRESS runs nonbaseline cost multipliers")
    all_frames = []
    evidence = []
    for instrument, first_year in REGISTRY.items():
        if year < first_year:
            evidence.append({"symbol": instrument, "state": "not_yet_available"})
            continue
        prices = load_development(instrument, from_year=year, until_year=year)
        frame = build_signals(prices)
        # Calculate causal Engineer features from previous 6 months before
        # clipping to calendar scoring year.
        start = datetime(year, 1, 1, tzinfo=timezone.utc)
        end = HOLDOUT if year == 2026 else datetime(2026, 1, 1, tzinfo=timezone.utc)
        frame = frame.filter((pl.col("timestamp") >= pl.lit(start)) &
                             (pl.col("timestamp") < pl.lit(end)))
        if frame.is_empty():
            raise ValueError(f"Missing scored quote bars for {instrument}/{year}")
        evidence.append({
            "symbol": instrument, "rows": frame.height,
            "first": str(frame["timestamp"].min()), "last": str(frame["timestamp"].max()),
            "h1_signals": int(frame["h_enter"].sum()),
            "d1_signals": int(frame["d_enter"].sum()),
            "d1_exits": int(frame["d_exit"].sum())
        })
        all_frames.append(frame)
    if not all_frames:
        raise ValueError("No eligible year data")
    combined = pl.concat(all_frames).sort("timestamp", "asset")
    if combined["timestamp"].max() >= HOLDOUT:
        raise AssertionError("New remaining holdout reached")
    strategy, result = run_native(
        combined, TRIALS[trial], commission_bps=cost_mult,
        slippage_bps=2*cost_mult,
    )
    target = OUT / f"year={year}" / trial / f"cost_{cost_mult:g}x"
    target.mkdir(parents=True, exist_ok=True)
    fills = result.to_fills_dataframe()
    trades = result.to_trades_dataframe()
    fills.write_parquet(target / "fills.parquet")
    trades.write_parquet(target / "trades.parquet")
    curve = pl.DataFrame({
        "timestamp": [ts for ts, _ in result.equity_curve],
        "equity": [float(value) for _, value in result.equity_curve],
    }).sort("timestamp")
    daily = (curve.with_columns(
            day=pl.col("timestamp").dt.convert_time_zone("America/New_York").dt.date()
        ).group_by("day").agg(pl.col("equity").last()).sort("day")
        .with_columns(pl.col("equity").pct_change().fill_null(0).alias("return")))
    daily.write_parquet(target / "daily_equity.parquet")
    risk = PortfolioAnalysis(
        returns=daily["return"].to_numpy(),
        periods_per_year=252,
    ).compute_summary_stats()
    closed = trades.filter(pl.col("status") == "closed")
    native = result.metrics
    report = {
        "state": "USER_AUTHORIZED_HOLDOUT_CONSUMED_UNQUALIFIED_CFD_BID_PROXY",
        "authorized_holdout_exposure": "2025 full and 2026 YTD through Oct11 are now observed, not pristine OOS",
        "window_end_exclusive": str(end),
        "session": SESSION, "year": year, "trial": trial,
        "cost_multiplier": cost_mult,
        "source_note": "H1 US500 US100 DE30; D1 those plus EU50; eligible-from-launch only",
        "coverage": evidence,
        "native": {k:native[k] for k in (
            "initial_cash","final_value","num_trades","num_orders",
            "num_fills","num_rejected_orders","win_rate",
            "total_commission","total_slippage","num_fills","total_costs",
            "max_drawdown_pct"
        )},
        "daily": {k:v for k,v in vars(risk).items() if isinstance(v,(str,int,float,np.generic,type(None)))},
        "closed_trades": closed.height,
        "open_trades": trades.filter(pl.col("status") == "open").height,
        "closed_net_pnl": float(closed["pnl"].sum()) if closed.height else 0.0,
        "native_end_equity": strategy.end_equity,
        "cash_plus_positions_reconciles": abs(
            strategy.end_equity - strategy.end_cash -
            sum(p["quantity"]*p["current_price"]*p["multiplier"]
                for p in strategy.end_positions.values())
        ) < 0.01,
        "positions": strategy.end_positions,
        "native_order_rejections": strategy.native_rejections[:10],
        "units": "SYNTHETIC price-units; EUR and USD index values NOT FX-converted; NOT tradable $ PnL",
        "blockers": [
            "H1 protective stop installed after first fill, entry minute uncovered",
            "BID quotes only; no observed ASK spread",
            "CFD lot size/multiplier, FX conversion, overnight financing unverified",
            "NY17 daily market session assumed even for DAX/EU50",
            "Open positions not carried across standalone yearly partitions",
        ],
        "artifacts": {"fills":str(target/"fills.parquet"),
                      "trades":str(target/"trades.parquet"),
                      "daily":str(target/"daily_equity.parquet")},
    }
    target.joinpath("summary.json").write_text(
        json.dumps(json_clean(report),indent=2,allow_nan=False,default=str)+"\n")
    print(json.dumps({
        "year": year, "trial": trial, "cost": cost_mult,
        "closed": closed.height, "open": report["open_trades"],
        "return": native["total_return_pct"],
        "daily_sharpe": report["daily"].get("sharpe_ratio"),
        "native_fills": native["num_fills"], "rejects":native["num_rejected_orders"],
        "artifact":str(target/"summary.json"),
    },default=str),flush=True)
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--year",type=int,required=True)
    p.add_argument("--trial",choices=sorted(TRIALS),required=True)
    p.add_argument("--cost-multiplier",type=float,default=1)
    a=p.parse_args()
    execute(a.year,a.trial,a.cost_multiplier)

if __name__ == "__main__":
    main()
