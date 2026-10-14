"""Causal and native-integration checks for index-CFD Milkman prototypes."""
import math
from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from src.strategies.milkman_native_features import (
    attach_prior_daily_ema_gate,
    box_episode_signals,
    daily_bilbo_features,
    hourly_bilbo_features,
    legends_buy_day_features,
    legends_ema_daily_setups,
    morning_dip_features,
    phase_compression_features,
    swing_golden_gate_features,
)


def bars(n: int = 350, start: datetime = datetime(2020, 1, 1, tzinfo=UTC)) -> pl.DataFrame:
    close = [100.0 + 0.025 * i + math.sin(i / 4) * 1.3 for i in range(n)]
    return pl.DataFrame({
        "timestamp": [start + timedelta(days=i) for i in range(n)],
        "open": [c - 0.15 for c in close],
        "high": [c + 0.5 for c in close],
        "low": [c - 0.6 for c in close],
        "close": close,
        "volume": [100.0 + i for i in range(n)],
    })


def test_morning_native_er_and_simple_atr():
    x = morning_dip_features(bars(100))
    assert x.height == 100
    assert {"er15", "atr14_simple", "limit_level", "target_level", "choppy"} <= set(x.columns)
    assert x["er15"][:15].null_count() == 15
    assert abs(x["atr14_simple"][45] - 1.1) < 1e-6
    assert x["choppy"][14] is False


def test_legend_buy_day_fresh_exact_three():
    x = bars(10).with_columns(pl.Series("close", [10., 11., 10., 9., 8., 7., 10., 9., 8., 7.]))
    x = x.with_columns(
        pl.col("close").alias("open"),
        (pl.col("close") + 1).alias("high"),
        (pl.col("close") - 1).alias("low"),
    )
    y = legends_buy_day_features(x)
    # First fresh three-down occurs at index 4, not on fourth consecutive down.
    assert y["setup_complete"].to_list()[4] is True
    assert y["setup_complete"].to_list()[5] is False
    assert y["setup_complete"].to_list()[9] is True


def test_bilbo_uses_native_indicators_and_never_fires_during_warmup():
    x = phase_compression_features(bars(100))
    assert {"ema21", "atr14_wilder", "std21_sample", "grey"} <= set(x.columns)
    assert not any(x["grey"][:20])
    assert all(v is not None for v in x["grey"])
    assert hourly_bilbo_features(bars(80)).height == 80
    assert "prior_ema50" in daily_bilbo_features(bars(80))


def test_future_data_perturbation_does_not_change_past_signals():
    x = bars(180)
    old = phase_compression_features(x)
    changed = x.with_columns(
        pl.when(pl.int_range(pl.len()) >= 120).then(pl.col("close") + 20)
        .otherwise(pl.col("close")).alias("close"),
        pl.when(pl.int_range(pl.len()) >= 120).then(pl.col("high") + 20)
        .otherwise(pl.col("high")).alias("high"),
        pl.when(pl.int_range(pl.len()) >= 120).then(pl.col("low") + 20)
        .otherwise(pl.col("low")).alias("low"),
        pl.when(pl.int_range(pl.len()) >= 120).then(pl.col("open") + 20)
        .otherwise(pl.col("open")).alias("open"),
    )
    newer = phase_compression_features(changed)
    assert old["grey"][:120].to_list() == newer["grey"][:120].to_list()
    assert all((math.isnan(a) and math.isnan(b)) or a == b for a, b in zip(old["ema21"][:120], newer["ema21"][:120]))


def test_ema_threshold_lags_session_and_excludes_future():
    x = bars(340).with_columns(
        pl.col("timestamp").dt.date().alias("session_date"),
    )
    a = legends_ema_daily_setups(x, lookback_sessions=40)
    assert a["threshold_prev_only"][:40].null_count() == 40
    new = x.with_columns(
        pl.when(pl.int_range(pl.len()) == 300).then(pl.col("close") + 0.3)
        .otherwise(pl.col("close")).alias("close")
    )
    b = legends_ema_daily_setups(new, lookback_sessions=40)
    assert a["threshold_prev_only"][:301].to_list() == b["threshold_prev_only"][:301].to_list()


def test_monthly_levels_only_use_prior_month():
    m = bars(32).with_columns(
        pl.Series("timestamp", [datetime(2018 + i // 12, i % 12 + 1, 28, tzinfo=UTC) for i in range(32)])
    ).with_columns(pl.col("timestamp").dt.strftime("%Y-%m").alias("month"))
    d = m.tail(12)
    a = swing_golden_gate_features(d, m)
    assert a["prev_month_close"][-1] == m["close"][-2]
    assert a["prev_month_atr14"][-1] is not None
    with pytest.raises(ValueError, match="one COMPLETED"):
        swing_golden_gate_features(d, pl.concat([m, m.tail(1)]))


def test_hourly_box_only_first_out_of_compression_and_one_shot():
    x = bars(8).with_columns(
        pl.Series("timestamp", [datetime(2020, 1, 2, 14, tzinfo=UTC) + timedelta(hours=i) for i in range(8)]),
        pl.Series("grey", [True] * 5 + [False] * 3),
        pl.lit(True).alias("prior_daily_above_ema21"),
    )
    x = x.with_columns(
        pl.Series("high", [105., 105., 105., 105., 105., 107., 108., 109.]),
        pl.Series("low", [95.] * 8),
        pl.Series("close", [101.] * 5 + [106., 107., 108.]),
    )
    y = box_episode_signals(x, mode="hourly")
    assert y["box_close_break"].to_list() == [False] * 5 + [True, False, False]
    with pytest.raises(ValueError, match="prior_daily"):
        box_episode_signals(x.drop("prior_daily_above_ema21"), mode="hourly")


def test_duplicate_rejected():
    x = bars(30)
    x = pl.concat([x, x.tail(1)])
    with pytest.raises(ValueError, match="Duplicate"):
        morning_dip_features(x)


def test_prior_day_rth_gate_excludes_current_day_close():
    day = bars(65)
    hourly = day.tail(2)
    before = attach_prior_daily_ema_gate(hourly, day)
    changed = day.with_columns(
        pl.when(pl.int_range(pl.len()) == 64).then(pl.col("close") + .2)
        .otherwise(pl.col("close")).alias("close"),
    )
    after = attach_prior_daily_ema_gate(hourly, changed)
    assert before["prior_daily_above_ema21"].to_list() == after["prior_daily_above_ema21"].to_list()


def test_phase_grey_agrees_with_independent_pandas_oracle_after_seed_warmup():
    import pandas as pd

    data = bars(500)
    native = phase_compression_features(data)
    frame = data.to_pandas()
    c, hi, lo = frame["close"], frame["high"], frame["low"]
    previous = c.shift(1)
    tr = pd.concat([hi - lo, (hi - previous).abs(), (lo - previous).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    sd = c.rolling(21, min_periods=1).std(ddof=1)
    gap = 2 * (sd - atr)
    expansion = 2 * sd - 1.854 * atr
    oracle = (gap <= 0) & ~((gap.shift(1) <= gap) & (expansion > 0))
    # TA-Lib and pandas differ in EMA/RMA seed; the long warmup is explicit.
    mismatch = sum(bool(a) != bool(b) for a, b in zip(native["grey"][200:], oracle.iloc[200:]))
    assert mismatch == 0
