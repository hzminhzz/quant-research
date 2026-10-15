"""Read-only feature qualification on canonical Dukascopy index CFD data.

No writes, no trades, no backtests, no evaluation after 2024. Feature summaries
use native ml4t.engineer; source store is not modified. Prints JSON to stdout.

Run:
  uv run --no-sync python -m scripts.probe_milkman_index_features_20261014
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from src.strategies.independent_seven_data import load_daily
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

ROOT = Path("/home/quant/dev/quant/ml4t-data/.data/store")
MONTHS = (1, 2, 3)
YEAR = 2021
CUTOFF = datetime(2025, 1, 1, tzinfo=UTC)


def minute(asset: str) -> pl.DataFrame:
    key = f"index_minute_{asset}"
    files = sorted(p for m in MONTHS for p in
                   (ROOT / key / f"year={YEAR}" / f"month={m}").rglob("data.parquet"))
    if not files:
        raise FileNotFoundError(f"{key}: no canonical 2021 Q1 partitions")
    df = pl.scan_parquet([str(p) for p in files], hive_partitioning=False,
                        cast_options=pl.ScanCastOptions(datetime_cast="millisecond-upcast", integer_cast="allow-float")).select(
        "timestamp", "open", "high", "low", "close", "volume"
    ).filter(pl.col("timestamp") < pl.lit(CUTOFF)).collect().sort("timestamp")
    if df["timestamp"].dtype.time_zone != "UTC":
        raise ValueError(f"{key}: expected UTC timestamp")
    return df


def aggregate(raw: pl.DataFrame, every: str, *, start_hour: int, stop_hour: int,
              rth: bool = False) -> pl.DataFrame:
    local = pl.col("timestamp").dt.convert_time_zone("America/New_York")
    # Polars hour/minute are i8: widen before multiplying to avoid overflow.
    hm = local.dt.hour().cast(pl.Int32) * 60 + local.dt.minute().cast(pl.Int32)
    lo = 9 * 60 + 30 if rth else start_hour * 60
    hi = 16 * 60 if rth else stop_hour * 60
    x = raw.filter((hm >= lo) & (hm < hi)).with_columns(
        pl.col("timestamp").dt.truncate(every).alias("bucket"),
        local.dt.date().alias("session_date"),
    )
    minutes = int(every.rstrip("m"))
    y = x.group_by(["bucket", "session_date"]).agg(
        pl.col("open").sort_by("timestamp").first().alias("open"),
        pl.col("high").max().alias("high"),
        pl.col("low").min().alias("low"),
        pl.col("close").sort_by("timestamp").last().alias("close"),
        pl.col("volume").sum().alias("volume"),
        pl.len().alias("count"),
    ).filter(pl.col("count") == minutes).sort("bucket")
    return y.with_columns(
        (pl.col("bucket") + pl.duration(minutes=minutes)).alias("timestamp")
    ).drop("bucket", "count")


def session_es(raw: pl.DataFrame) -> pl.DataFrame:
    local = pl.col("timestamp").dt.convert_time_zone("America/New_York")
    h = local.dt.hour()
    return (raw.filter(h != 17).with_columns(
        pl.when(h >= 18).then(local.dt.date() + pl.duration(days=1))
        .otherwise(local.dt.date()).alias("globex_session")
    ).group_by("globex_session").agg(
        pl.col("open").sort_by("timestamp").first().alias("open"),
        pl.col("high").max().alias("high"), pl.col("low").min().alias("low"),
        pl.col("close").sort_by("timestamp").last().alias("close"),
        pl.col("volume").sum().alias("volume"),
        pl.len().alias("minutes"),
    ).filter(pl.col("minutes") >= 1000).sort("globex_session").with_columns(
        pl.col("globex_session").cast(pl.Datetime("us")).dt.replace_time_zone("UTC")
        .alias("timestamp")
    ).select("timestamp", "open", "high", "low", "close", "volume", "minutes"))


def main() -> None:
    nq, es = minute("NQ"), minute("ES")
    if nq.is_empty() or es.is_empty():
        raise RuntimeError("Empty canonical minute input")
    # Build features across overnight bars; restrict the entry clock only after computing them.
    mnq = aggregate(nq, "3m", start_hour=0, stop_hour=24)
    enq = aggregate(nq, "15m", start_hour=9, stop_hour=16, rth=True)
    hnq = aggregate(nq, "60m", start_hour=4, stop_hour=20)
    es_sessions = session_es(es)
    m_all = morning_dip_features(mnq)
    et = pl.col("timestamp").dt.convert_time_zone("America/New_York")
    m = m_all.filter(et.dt.hour().is_between(10, 11))
    e = legends_ema_daily_setups(enq, lookback_sessions=40)
    rth_d = enq.group_by("session_date").agg(
        pl.col("timestamp").max().alias("timestamp"),
        pl.col("open").sort_by("timestamp").first().alias("open"),
        pl.col("high").max().alias("high"),
        pl.col("low").min().alias("low"),
        pl.col("close").sort_by("timestamp").last().alias("close"),
        pl.col("volume").sum().alias("volume"),
    ).sort("timestamp")
    h = attach_prior_daily_ema_gate(hourly_bilbo_features(hnq), rth_d)
    bh = box_episode_signals(h, mode="hourly")
    b = legends_buy_day_features(es_sessions.drop("minutes"))
    daily, manifest = load_daily("ES", first_year=2019, last_year=2022,
                                 end_exclusive=CUTOFF)
    # Daily loader uses midnight SESSION LABEL, not availability timestamp.
    # Move to its actual 17:00 ET completed CFD session clock.
    day = pl.col("timestamp").dt.date().cast(pl.Datetime("us"))
    d = daily.with_columns(
        day.dt.replace_time_zone("America/New_York").dt.offset_by("17h")
        .dt.convert_time_zone("UTC").alias("timestamp"),
    ).with_columns(
        pl.col("timestamp").dt.convert_time_zone("America/New_York")
        .dt.strftime("%Y-%m").alias("month")
    )
    mo = (d.group_by("month").agg(
        pl.col("timestamp").max().alias("timestamp"),
        pl.col("open").sort_by("timestamp").first().alias("open"),
        pl.col("high").max().alias("high"),
        pl.col("low").min().alias("low"),
        pl.col("close").sort_by("timestamp").last().alias("close"),
        pl.col("volume").sum().alias("volume"),
        pl.len().alias("sessions")
    ).filter(pl.col("sessions") >= 12).sort("timestamp").drop("sessions"))
    gg = swing_golden_gate_features(d, mo)
    bd = daily_bilbo_features(d)
    bd_signals = box_episode_signals(bd, mode="daily")
    print(json.dumps({
        "status": "FEATURE_PROBE_ONLY",
        "cutoff_exclusive": CUTOFF.date().isoformat(),
        "data": {"nq_source": "Dukascopy CFD/index USATECH price alias NQ",
                 "es_source": "Dukascopy CFD/index USA500 price alias ES",
                 "raw_nq_minutes": nq.height, "raw_es_minutes": es.height,
                 "daily_source": manifest, "volume": "broker tick/quote activity, not CME volume"},
        "cases": {
            "morning_dip": {"bars_3min": m.height, "choppy_bars": int(m["choppy"].sum()), "atr_valid": m["atr14_simple"].is_finite().sum()},
            "legends_buy_day": {"globex_days": b.height, "fresh_three_down": int(b["setup_complete"].sum())},
            "legends_ema": {"rth_15m_bars": enq.height, "daily_setups": e.height,
                            "causal_strong_no_touch": int(e["setup_complete"].sum()),
                            "threshold_valid": int(e["threshold_prev_only"].is_finite().sum())},
            "bilbo_hourly": {"eth_hourly": h.height, "grey": int(h["grey"].sum()),
                             "prior_daily_gate_valid": int(h["prior_daily_above_ema21"].sum()),
                             "close_break_proxies": int(bh["box_close_break"].sum())},
            "swing_gg": {"daily_bars": gg.height,
                         "eligible_monthly_levels": int(gg["prev_month_atr14"].is_finite().sum())},
            "daily_bilbo": {"daily_bars": bd.height, "grey": int(bd["grey"].sum()),
                            "close_break_proxies": int(bd_signals["box_close_break"].sum())},
        },
        "limitations": "Features only. All CFDs are NOT NQ/ES futures nor stock or option parity. Exact parity, executions and fills remain unverified. Separate 2025-2026 allocation evaluation untouched.",
    }, default=str, indent=2))


if __name__ == "__main__":
    main()
