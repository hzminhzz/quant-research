"""Frozen 2015-2021 Gold/FX ROC60 monthly research using native ML4T Engine.

This file is outside src/ and scripts/ on purpose: the 2026-10-15 frozen
session includes a hash of every existing src/*.py and scripts/*.py.
Code identity is recorded in each trial result separately; do not alter the
frozen session or prior task-owned sources. No post-2021 input is loaded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import traceback
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
from ml4t.backtest import (
    BacktestConfig,
    CommissionType,
    DataFeed,
    Engine,
    ExecutionMode,
    Strategy,
)
from ml4t.backtest.analytics import max_drawdown, sharpe_ratio, sortino_ratio
from ml4t.backtest.config import ShareType, SlippageType
from ml4t.engineer import compute_features

SESSION = "gold_fx_trend_diversification_mvp_20261015"
DATA = Path("data/processed/gold_fx_trend_diversification_20261015")
OUTPUT = Path("run_log/gold_fx_trend_diversification_mvp_20261015")
START = datetime(2015, 1, 1, tzinfo=UTC)
END = datetime(2022, 1, 1, tzinfo=UTC)
SYMBOLS = {"XAUUSD": "xau_tsmom_60_mvp", "EURUSD": "eur_tsmom_60_mvp", "AUDUSD": "aud_tsmom_60_mvp"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def features_and_feed(symbol: str) -> tuple[pl.DataFrame, pl.DataFrame, dict]:
    if symbol not in SYMBOLS:
        raise ValueError(f"Unexpected symbol {symbol}")
    source = DATA / f"{symbol}_NY17_daily_2013_2024.parquet"
    snapshot = pl.read_parquet(source).sort("timestamp")
    # Filter BEFORE native feature computation. No 2022+ prices are accessed.
    raw = snapshot.filter(pl.col("timestamp") < END)
    assert raw["timestamp"].n_unique() == raw.height
    if raw["timestamp"].min() >= START or raw["timestamp"].max() >= END:
        raise ValueError("Warmup or evaluation boundary invalid")
    frame = raw.select("timestamp", "open", "high", "low", "close", "volume")
    feat = compute_features(frame, [{"name": "roc", "params": {"period": 60}, "output": "roc60"}],
                            timestamp_col="timestamp")
    if not isinstance(feat, pl.DataFrame) or "roc60" not in feat.columns:
        raise TypeError("Native ml4t-engineer ROC60 unavailable")
    month = pl.col("timestamp").dt.convert_time_zone("America/New_York").dt.strftime("%Y-%m")
    annotated = feat.with_columns(month.alias("month")).with_columns(
        (pl.col("month") != pl.col("month").shift(1)).fill_null(True).alias("first_session_of_month")
    )
    # Completed first trading session is the earliest eligible MONTHLY decision.
    signal = annotated.filter(
        pl.col("first_session_of_month")
        & pl.col("roc60").is_finite()
        & (pl.col("timestamp") >= START)
        & (pl.col("timestamp") < END)
    ).select("timestamp", pl.col("roc60"),
             pl.when(pl.col("roc60") > 0).then(1)
               .when(pl.col("roc60") < 0).then(-1)
               .otherwise(0).alias("target_side"))
    prices = raw.filter(pl.col("timestamp") >= START).select(
        "timestamp", "open", "high", "low", "close", "volume"
    ).with_columns(asset=pl.lit(symbol))
    if signal["timestamp"].n_unique() != signal.height or not signal.height:
        raise ValueError("Empty or duplicate monthly signals")
    if prices["timestamp"].max() >= END:
        raise ValueError("Protected/foreign data")
    # Hard gate on prolonged source gaps before creating executable signals.
    gaps = prices["timestamp"].diff().dt.total_days()
    severe_gaps = sum(v is not None and v > 7 for v in gaps)
    if severe_gaps:
        raise ValueError(f"{symbol}: {severe_gaps} evaluation gaps longer than seven days")
    sig = signal.with_columns(asset=pl.lit(symbol))
    return prices, sig, {
        "input_snapshot": str(source), "input_snapshot_sha256": sha256(source),
        "execution_bars": prices.height, "signals": signal.height,
        "signal_min": str(signal["timestamp"].min()), "signal_max": str(signal["timestamp"].max()),
        "max_gap_days": max(v for v in gaps if v is not None),
        "source_clock": "NY 17:00 completed daily CFD proxy",
    }


class MonthlyTrend60(Strategy):
    """Read native ROC60 signal after completed monthly first session close."""
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.months_submitted: set[str] = set()
        self.orders = 0
        self.order_decisions: list[dict] = []

    def on_data(self, timestamp, data, context, broker) -> None:
        bar = data.get(self.symbol)
        if not bar:
            return
        sig = bar.get("signals") or {}
        side = sig.get("target_side")
        if side is None or not math.isfinite(float(side)):
            return
        side = int(side)
        if side not in (-1, 0, 1):
            raise ValueError("Side outside frozen contract")
        month = timestamp.astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).strftime("%Y-%m")
        if month in self.months_submitted:
            raise ValueError(f"Duplicate month decision: {month}")
        self.months_submitted.add(month)
        price = float(bar["close"])
        position = broker.get_position(self.symbol)
        current = float(position.quantity) if position is not None else 0.
        desired = side * .10 * float(broker.equity()) / price
        delta = desired - current
        self.order_decisions.append({
            "timestamp": str(timestamp), "month": month,
            "side": side, "prior_qty": current,
            "desired_qty": desired, "delta": delta,
            "decision_close": price,
        })
        if abs(delta) > 1e-8:
            order = broker.submit_order(self.symbol, delta)
            if order is None:
                raise RuntimeError(f"Native broker refused {self.symbol} {month}")
            self.orders += 1


def config() -> BacktestConfig:
    return BacktestConfig(
        initial_cash=100_000,
        execution_mode=ExecutionMode.NEXT_BAR,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=.0002,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=.0003,
        share_type=ShareType.FRACTIONAL,
        allow_short_selling=True,
        allow_leverage=False,
    )


def clean(v):
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if isinstance(v, dict):
        return {str(k): clean(x) for k,x in v.items()}
    if isinstance(v, (tuple, list)):
        return [clean(x) for x in v]
    return v if isinstance(v,(int,float,str,bool)) or v is None else str(v)


def run(symbol: str, outroot: Path = OUTPUT) -> dict:
    if symbol not in SYMBOLS:
        raise ValueError(symbol)
    trial_id = SYMBOLS[symbol]
    folder = outroot / trial_id / "attempt01"
    if folder.exists():
        raise FileExistsError(f"Never overwrite trial attempt: {folder}")
    folder.mkdir(parents=True)
    metadata = {
        "session":SESSION,"trial_id":trial_id,
        "attempt":"attempt01",
        "started_at":datetime.now(UTC).isoformat(),
        "status":"STARTED",
        "code_identity_sha256":sha256(Path(__file__)),
        "native_engine":"ml4t-backtest==0.1.7",
        "native_features":"ml4t-engineer==0.1.4 ROC60",
        "development":[str(START),str(END)],
        "protected_2025_2026":"NOT_ACCESSED",
        "assumed_cost_bps_per_side":{"commission":2,"slippage":3},
        "financing_swaps":"NOT_INCLUDED; unqualified executable costs",
    }
    (folder/"started.json").write_text(json.dumps(metadata,indent=2)+"\n")
    try:
        prices, signals, provenance = features_and_feed(symbol)
        prices.write_parquet(folder/"prices.parquet")
        signals.write_parquet(folder/"signals.parquet")
        model=MonthlyTrend60(symbol)
        result=Engine(DataFeed(prices_df=prices,signals_df=signals),model,config()).run()
        frames={
            "equity.csv": result.to_equity_dataframe(),
            "trades.csv": result.to_trades_dataframe(),
            "fills.csv": result.to_fills_dataframe(),
            "rejected_orders.csv": result.to_rejected_orders_dataframe(),
        }
        for file,df in frames.items():
            df.write_csv(folder/file)
        (folder/"decisions.json").write_text(json.dumps(model.order_decisions,indent=2)+"\n")
        eq=frames["equity.csv"]
        trades=frames["trades.csv"]
        if eq.is_empty() or eq["timestamp"].n_unique()!=eq.height:
            raise ValueError("Invalid native marked-equity series")
        trade_pnl=float(trades["pnl"].sum()) if not trades.is_empty() else 0.
        delta=float(eq["equity"][-1])-100_000
        if abs(delta-trade_pnl)>.02:
            raise ValueError(f"Native equity/trade PnL mismatch: {delta} vs {trade_pnl}")
        daily=eq.with_columns(pl.col("timestamp").dt.convert_time_zone("America/New_York")
                              .dt.date().alias("day")).group_by("day").agg(
            pl.col("equity").sort_by("timestamp").last().alias("equity")
        ).sort("day")
        ret=daily["equity"].pct_change().fill_null(0).to_numpy()
        num_closed=trades.filter(pl.col("status")=="closed").height if not trades.is_empty() else 0
        num_open=trades.filter(pl.col("status")!="closed").height if not trades.is_empty() else 0
        metrics={
            "net_return_pct":100*delta/100_000,
            "daily_sharpe":clean(float(sharpe_ratio(ret))),
            "daily_sortino":clean(float(sortino_ratio(ret))),
            "daily_max_drawdown":clean(float(max_drawdown(daily["equity"].to_list())[0])),
            "native_total_costs":clean(result.metrics.get("total_costs")),
            "native_metrics":clean(result.metrics),
            "daily_marks":daily.height,
            "closed_trades":num_closed,
            "open_trades_at_boundary":num_open,
            "filled_orders":frames["fills.csv"].height,
            "rejected_orders":len(result.rejected_orders),
            "broker_submissions":model.orders,
            "decision_months":len(model.months_submitted),
            "final_equity":float(eq["equity"][-1]),
            "trade_ledger_pnl":trade_pnl,
        }
        artifact_hashes={name:sha256(folder/name) for name in
            ("prices.parquet","signals.parquet","equity.csv","trades.csv","fills.csv","rejected_orders.csv","decisions.json")}
        report={**metadata,"status":"NATIVE_ENGINE_COMPLETED_PENDING_INDEPENDENT_AUDIT",
                "finished_at":datetime.now(UTC).isoformat(),
                "provenance":provenance,"metrics":metrics,"artifacts_sha256":artifact_hashes,
                "limitations":[
                    "Dukascopy Gold/FX quote data, not bid/ask executable CFD contracts",
                    "CFD swap/overnight financing excluded",
                    "Data gaps cannot be assumed liquid or filled",
                    "Underlying 2015-2021 development already historical, no unseen holdout",
                ]}
        (folder/"report.json").write_text(json.dumps(report,indent=2,default=str,allow_nan=False)+"\n")
        print("RESULT", json.dumps({"symbol":symbol,**metrics},default=str),flush=True)
        return report
    except Exception:
        metadata["status"]="FAILED"
        metadata["traceback"]=traceback.format_exc()
        (folder/"failed.json").write_text(json.dumps(metadata,indent=2)+"\n")
        raise


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--symbol",choices=tuple(SYMBOLS),required=True)
    parser.add_argument("--out",type=Path,default=OUTPUT)
    options=parser.parse_args()
    run(options.symbol,options.out)
