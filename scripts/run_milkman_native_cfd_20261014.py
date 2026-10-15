"""Six bounded development-only Milkman CFD trials on the native ML4T Engine.

Run one case at a time, preserving each terminal trial and errors.
    uv run --no-sync python -m scripts.run_milkman_native_cfd_20261014 --case legends_buy_day
Original Milkman futures/stocks/options ledgers are NOT reproduced here.
No data at/after 2025-01-01 UTC is queried.
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
)
from ml4t.backtest.config import ShareType, SlippageType, StopFillMode
from ml4t.engineer import compute_features

from src.strategies.independent_seven_data import load_daily
from src.strategies.milkman_native_broker import (
    BuyDayOvernight,
    DailyBoxCloseConfirmed,
    EmaNextDayReversion,
    HourlyBilboUnderlying,
    MorningDipLimit,
    SwingGateShort,
)
from src.strategies.milkman_native_features import (
    attach_prior_daily_ema_gate,
    box_episode_signals,
    daily_bilbo_features,
    hourly_bilbo_features,
    legends_buy_day_features,
    legends_ema_daily_setups,
    morning_dip_features,
    swing_golden_gate_features,
)

STORE = Path("/home/quant/dev/quant/ml4t-data/.data/store")
OUT = Path("run_log/milkman_native_cfd_mvp_20261014")
EVAL_CUTOFF = datetime(2025, 1, 1, tzinfo=UTC)
RUN_START = datetime(2022, 1, 1, tzinfo=UTC)
RUN_END = datetime(2022, 4, 1, tzinfo=UTC)
DAILY_START = datetime(2020, 1, 1, tzinfo=UTC)
DAILY_END = datetime(2023, 1, 1, tzinfo=UTC)
CASES = (
    "morning_dip_limit", "legends_buy_day", "legends_ema",
    "bilbo_box_v2", "swing_golden_gate", "daily_bilbo_boxes",
)


def minute(asset: str) -> pl.DataFrame:
    root = STORE / f"index_minute_{asset}"
    files = sorted([*root.joinpath("year=2021").rglob("data.parquet"),
                    *(p for p in root.joinpath("year=2022").rglob("data.parquet")
                      if any(f"month={m}/" in str(p) for m in (1, 2, 3)))])
    if not files:
        raise FileNotFoundError(f"No canonical index CFD 2021-2022 partitions: {root}")
    df = (pl.scan_parquet([str(p) for p in files], hive_partitioning=False,
          cast_options=pl.ScanCastOptions(
              datetime_cast="millisecond-upcast", integer_cast="allow-float"))
          .select("timestamp", "open", "high", "low", "close", "volume")
          .filter(pl.col("timestamp") < pl.lit(RUN_END))
          .collect().sort("timestamp"))
    if df.height < 200_000 or df["timestamp"].n_unique() != df.height:
        raise ValueError(f"{asset}: missing history or duplicate timestamps: {df.height}")
    if df["timestamp"].dtype.time_zone != "UTC":
        raise ValueError("Source is not timezone-aware UTC")
    return df


def aggregate(df: pl.DataFrame, every: int, *, et_start=0, et_end=24) -> pl.DataFrame:
    local = pl.col("timestamp").dt.convert_time_zone("America/New_York")
    # Polars .dt.hour() is i8: cast to i32 BEFORE multiplying by 60.
    hm = local.dt.hour().cast(pl.Int32) * 60 + local.dt.minute().cast(pl.Int32)
    x = df.filter((hm >= et_start * 60) & (hm < et_end * 60)).with_columns(
        pl.col("timestamp").dt.truncate(f"{every}m").alias("bucket"),
        local.dt.date().alias("session_date"),
    )
    return (x.group_by(["bucket", "session_date"]).agg(
        pl.col("open").sort_by("timestamp").first().alias("open"),
        pl.col("high").max().alias("high"),
        pl.col("low").min().alias("low"),
        pl.col("close").sort_by("timestamp").last().alias("close"),
        pl.col("volume").sum().alias("volume"),
        pl.len().alias("count"),
    ).filter(pl.col("count") == every).sort("bucket").with_columns(
        (pl.col("bucket") + pl.duration(minutes=every)).alias("timestamp")
    ).drop("bucket", "count"))


def price_feed(raw: pl.DataFrame, asset: str, *, day: bool = False) -> pl.DataFrame:
    # Source minute rows label BAR START. Native decisions observe BAR CLOSE.
    # The next engine bar's open is the earliest permissible market fill.
    out = raw if day else raw.with_columns(
        (pl.col("timestamp") + pl.duration(minutes=1)).alias("timestamp")
    )
    start, end = (DAILY_START, DAILY_END) if day else (RUN_START, RUN_END)
    out = out.filter((pl.col("timestamp") >= start) & (pl.col("timestamp") < end))
    return out.select("timestamp", "open", "high", "low", "close", "volume").with_columns(
        asset=pl.lit(asset)
    )


def globex_sessions(raw: pl.DataFrame) -> pl.DataFrame:
    local = pl.col("timestamp").dt.convert_time_zone("America/New_York")
    hour = local.dt.hour()
    x = raw.filter(hour != 17).with_columns(
        pl.when(hour >= 18).then(local.dt.date() + pl.duration(days=1))
        .otherwise(local.dt.date()).alias("session")
    )
    grouped = x.group_by("session").agg(
        pl.col("open").sort_by("timestamp").first().alias("open"),
        pl.col("high").max().alias("high"), pl.col("low").min().alias("low"),
        pl.col("close").sort_by("timestamp").last().alias("close"),
        pl.col("volume").sum().alias("volume"),
        pl.col("timestamp").max().alias("last_raw_start"),
        pl.len().alias("n_min"),
    ).filter(pl.col("n_min") >= 1000).sort("session")
    return grouped.with_columns(
        (pl.col("last_raw_start") + pl.duration(minutes=1)).alias("timestamp")
    )


def rth_daily(min15: pl.DataFrame) -> pl.DataFrame:
    return (min15.group_by("session_date").agg(
        pl.col("timestamp").max().alias("timestamp"),
        pl.col("open").sort_by("timestamp").first().alias("open"),
        pl.col("high").max().alias("high"),
        pl.col("low").min().alias("low"),
        pl.col("close").sort_by("timestamp").last().alias("close"),
        pl.col("volume").sum().alias("volume"),
        pl.len().alias("bars"),
    ).filter(pl.col("bars") == 26).sort("timestamp").drop("bars"))


def case_inputs(case: str):
    asset = "NQ" if case in ("morning_dip_limit", "legends_ema", "bilbo_box_v2") else "ES"
    info = {"asset": asset, "market": f"Dukascopy {asset}-alias CFD (not CME)",
            "development_start": str(DAILY_START if case in ("swing_golden_gate", "daily_bilbo_boxes") else RUN_START),
            "development_end_exclusive": str(DAILY_END if case in ("swing_golden_gate", "daily_bilbo_boxes") else RUN_END)}
    if case in ("swing_golden_gate", "daily_bilbo_boxes"):
        day, manifest = load_daily("ES", 2019, 2022, end_exclusive=DAILY_END)
        # Change SESSION LABEL to conservative completed 17:00 ET session close.
        d = day.with_columns(
            pl.col("timestamp").dt.date().cast(pl.Datetime("us"))
            .dt.replace_time_zone("America/New_York").dt.offset_by("17h")
            .dt.convert_time_zone("UTC").alias("timestamp"),
        ).with_columns(
            pl.col("timestamp").dt.convert_time_zone("America/New_York")
            .dt.strftime("%Y-%m").alias("month")
        )
        info["input"] = manifest
        if case == "swing_golden_gate":
            mo = d.group_by("month").agg(
                pl.col("timestamp").max().alias("timestamp"),
                pl.col("open").sort_by("timestamp").first().alias("open"),
                pl.col("high").max().alias("high"), pl.col("low").min().alias("low"),
                pl.col("close").sort_by("timestamp").last().alias("close"),
                pl.col("volume").sum().alias("volume"),
                pl.len().alias("sessions"),
            ).filter(pl.col("sessions") >= 12).sort("timestamp").drop("sessions")
            f = swing_golden_gate_features(d, mo).sort("timestamp")
            f = f.with_columns(
                (pl.col("month") != pl.col("month").shift(-1))
                .fill_null(True).alias("last_month_session"),
            )
            strat = SwingGateShort(asset)
            fields = ["down_gate_open", "down_gate_complete", "short_stop", "short_target",
                      "prev_close_above_ema21", "last_month_session"]
        else:
            f = box_episode_signals(daily_bilbo_features(d), mode="daily")
            strat = DailyBoxCloseConfirmed(asset)
            fields = ["box_close_break", "box_low", "prior_ema50"]
        prices = price_feed(d, asset, day=True)
        sig = f.filter(pl.col("timestamp") >= DAILY_START).select("timestamp", *fields)
        return prices, sig, strat, info

    raw = minute(asset)
    info["source_rows_2021_warmup_to_2022_q1"] = raw.height
    raw_price = price_feed(raw, asset)
    if case == "legends_buy_day":
        sess = globex_sessions(raw)
        features = legends_buy_day_features(sess.select(
            "timestamp", "open", "high", "low", "close", "volume"))
        f = sess.select("timestamp", "session").with_columns(
            features["setup_complete"].alias("entry_at_reopen")
        ).filter(pl.col("entry_at_reopen")).select("timestamp", "entry_at_reopen")
        local = pl.col("timestamp").dt.convert_time_zone("America/New_York")
        exit_time = (local.dt.hour() == 9) & (local.dt.minute() == 29)
        raw_exit = raw.filter(exit_time).select(
            (pl.col("timestamp") + pl.duration(minutes=1)).alias("timestamp")
        ).with_columns(exit_at_0930=pl.lit(True))
        sig = raw_price.select("timestamp").join(f, on="timestamp", how="left").join(
            raw_exit, on="timestamp", how="left"
        )
        return raw_price, sig, BuyDayOvernight(asset), info
    if case == "morning_dip_limit":
        bars = aggregate(raw, 3)
        f = morning_dip_features(bars)
        local = pl.col("timestamp").dt.convert_time_zone("America/New_York")
        clock = ((local.dt.hour().cast(pl.Int16) >= 10)
                 & (local.dt.hour().cast(pl.Int16) < 12))
        sig = f.filter(clock & pl.col("choppy") &
                       pl.col("atr14_simple").is_finite()).select(
            "timestamp", pl.col("limit_level").alias("entry_limit"),
            pl.col("target_level").alias("entry_target"),
            pl.col("stop_level").alias("entry_stop"),
        )
        return raw_price, sig, MorningDipLimit(asset), info

    bars15 = aggregate(raw, 15, et_start=9, et_end=16)
    # 09:30 start is not divisible by 15 in UTC? 15min grid still aligns.
    if case == "legends_ema":
        f = legends_ema_daily_setups(bars15, lookback_sessions=252)
        daily = f.select("session_date", "setup_complete", "last_completed_ema").sort("session_date")
        # Next RTH session's flag comes from the PREVIOUS completed session,
        # including exchange holidays and weekends.
        daily = daily.with_columns(
            pl.col("setup_complete").shift(1).fill_null(False).alias("prior_setup")
        ).select("session_date", "prior_setup")
        minute_signal = raw_price.with_columns(
            pl.col("timestamp").dt.convert_time_zone("America/New_York")
            .dt.date().alias("session_date")
        ).join(daily, on="session_date", how="left")
        ema15 = compute_features(bars15.select("timestamp", "open", "high", "low", "close", "volume"),
                                 [{"name": "ema", "params": {"period": 20}, "output": "ema20"}],
                                 timestamp_col="timestamp")
        aligned = minute_signal.join_asof(
            ema15.select("timestamp", pl.col("ema20").alias("prior_completed_ema")),
            on="timestamp", strategy="backward",
        )
        return raw_price, aligned.select("timestamp", "prior_setup", "prior_completed_ema"), EmaNextDayReversion(asset), info

    if case == "bilbo_box_v2":
        hourly = aggregate(raw, 60, et_start=4, et_end=20)
        daily = rth_daily(bars15)
        h = attach_prior_daily_ema_gate(hourly_bilbo_features(hourly), daily)
        d_atr = compute_features(daily.select("timestamp", "open", "high", "low", "close", "volume"),
                                 [{"name": "atr", "params": {"period": 14}, "output": "datr14"}],
                                 timestamp_col="timestamp")
        d_atr = d_atr.with_columns(
            pl.col("timestamp").dt.convert_time_zone("America/New_York").dt.date().alias("et_day"),
            pl.col("datr14").shift(1).alias("prior_datr14"),
        )
        h = h.join(d_atr.select("et_day", "prior_datr14"), on="et_day", how="left")
        signal = box_episode_signals(h, mode="hourly").filter(
            pl.col("box_close_break") & pl.col("prior_datr14").is_finite()
        ).select("timestamp", "box_low", "prior_datr14").with_columns(
            entry_signal=pl.lit(True)
        )
        five = aggregate(raw, 5, et_start=4, et_end=20)
        prices = price_feed(five, asset, day=True).filter((pl.col('timestamp') >= RUN_START) & (pl.col('timestamp') < RUN_END))
        sig = prices.select("timestamp").join(signal, on="timestamp", how="left")
        return prices, sig, HourlyBilboUnderlying(asset), info
    raise ValueError(case)


def config() -> BacktestConfig:
    return BacktestConfig(
        initial_cash=100_000.0, execution_mode=ExecutionMode.NEXT_BAR,
        stop_fill_mode=StopFillMode.STOP_PRICE,
        commission_type=CommissionType.PERCENTAGE, commission_rate=.0002,
        slippage_type=SlippageType.PERCENTAGE, slippage_rate=.0002,
        share_type=ShareType.FRACTIONAL, allow_short_selling=True,
        allow_leverage=True, initial_margin=.5,
    )


def clean(v):
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if isinstance(v, dict):
        return {str(k): clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


def run(case: str, outroot: Path):
    folder = outroot / case
    if folder.exists():
        raise FileExistsError(f"Do not replace existing trial: {folder}")
    folder.mkdir(parents=True, exist_ok=False)
    manifest = {"case": case, "program": "milkman_native_cfd_mvp_20261014",
                "status": "STARTED", "registered_at": datetime.now(UTC).isoformat(),
                "execution": "ml4t.backtest.Engine NEXT_BAR",
                "protected_2025_2026_evaluation": "NOT_ACCESSED",
                "cost_per_side_bps": {"commission": 2, "slippage": 2},
                "input_capital": 100000, "capital_fraction": .1}
    (folder / "preregistered.json").write_text(json.dumps(manifest, indent=2) + "\n")
    try:
        prices, signals, strategy, info = case_inputs(case)
        # Native DataFeed forms a union of signal and market clocks.
        # Never allow warmup-only feature timestamps into the execution feed.
        signals = signals.filter(
            (pl.col('timestamp') >= prices['timestamp'].min()) &
            (pl.col('timestamp') <= prices['timestamp'].max())
        ).with_columns(asset=pl.lit(info['asset']))
        if not prices.height or prices["timestamp"].max() >= EVAL_CUTOFF:
            raise ValueError("Empty trial or protected cutoff breached")
        if prices["timestamp"].n_unique() != prices.height:
            raise ValueError("Duplicate price timestamps")
        if signals["timestamp"].n_unique() != signals.height:
            raise ValueError("Duplicate signal timestamps")
        prices.write_parquet(folder / "prices.parquet")
        signals.write_parquet(folder / "signals.parquet")
        hashes = {name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
                  for name in ("prices.parquet", "signals.parquet")}
        print("INPUT", case, prices.height, signals.height, flush=True)
        result = Engine(DataFeed(prices_df=prices, signals_df=signals),
                        strategy, config()).run()
        for name, method in (
            ("equity.csv", result.to_equity_dataframe),
            ("trades.csv", result.to_trades_dataframe),
            ("fills.csv", result.to_fills_dataframe),
            ("rejected_orders.csv", result.to_rejected_orders_dataframe),
        ):
            method().write_csv(folder / name)
        report = {**manifest, "status": "NATIVE_EXECUTION_COMPLETED",
                  "ended_at": datetime.now(UTC).isoformat(), "inputs": info,
                  "input_sha256": hashes, "bars": prices.height,
                  "signals": signals.height, "broker_submissions": strategy.decisions,
                  "trades": len(result.trades), "fills": len(result.fills),
                  "rejected_orders": len(result.rejected_orders),
                  "metrics": clean(result.metrics),
                  "caveat": "Only CFD price-proxy MVP. Costs exploratory, no CFD financing, no intrabar tick priority, no futures/stock/options parity."}
        (folder / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        print("RESULT", json.dumps({k: report[k] for k in ("case","status","trades","fills","broker_submissions","metrics")}), flush=True)
        return report
    except Exception:
        err = {**manifest, "status": "FAILED", "ended_at": datetime.now(UTC).isoformat(),
               "traceback": traceback.format_exc()}
        (folder / "failed.json").write_text(json.dumps(err, indent=2) + "\n")
        raise


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--case", required=True, choices=CASES)
    a.add_argument("--out", type=Path, default=OUT)
    args = a.parse_args()
    run(args.case, args.out)


if __name__ == "__main__":
    main()
