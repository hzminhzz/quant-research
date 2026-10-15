"""Milkman source-rule feature prototypes for existing index CFD bars.

These are decision-time FEATURES, not simulated orders, fills, or PnL.
Bars passed here must carry their completed-bar availability timestamp in UTC.
Canonical CFD data may reproduce price-rule geometry, not source instrument fills.

Reference:
  https://milkmantrades.com/morning-dip-limit.html
  https://milkmantrades.com/legends-buy-day.html
  https://milkmantrades.com/legends-ema.html
  https://milkmantrades.com/bilbo-box-replication.html
  https://milkmantrades.com/swing-gg-stocks.html
  https://milkmantrades.com/bilbo-daily.html

Native registered indicators are computed by ml4t.engineer.compute_features.
Only rule algebra, causal calendar joins, and the author's bespoke state machines
are local. Phase compression matches the algebra in public box_signals.py
after its 21-bar indicator warmup. No stock/option returns are synthesized.
"""
from __future__ import annotations

import math
from zoneinfo import ZoneInfo

import polars as pl
from ml4t.engineer import compute_features

REQUIRED = {"timestamp", "open", "high", "low", "close", "volume"}


def _base(raw: pl.DataFrame) -> pl.DataFrame:
    if not REQUIRED.issubset(raw.columns):
        raise ValueError(f"Missing columns {sorted(REQUIRED - set(raw.columns))}")
    df = raw.select("timestamp", "open", "high", "low", "close", "volume").sort("timestamp")
    if df["timestamp"].dtype.time_zone != "UTC":
        raise ValueError("Completed-bar timestamps must be UTC timezone-aware")
    if df["timestamp"].n_unique() != df.height:
        raise ValueError("Duplicate bar timestamp; one instrument per invocation")
    bad = df.filter(
        (pl.col("high") < pl.max_horizontal("open", "close", "low"))
        | (pl.col("low") > pl.min_horizontal("open", "close", "high"))
        | (pl.col("low") <= 0)
    )
    if bad.height:
        raise ValueError(f"Invalid OHLC bars: {bad.height}")
    return df


def _native(df: pl.DataFrame, specs: list[dict]) -> pl.DataFrame:
    return compute_features(df, specs, timestamp_col="timestamp")


def _p(name: str, period: int, output: str, **params: float) -> dict:
    return {"name": name, "params": {"period": period, **params}, "output": output}


def _sma_of_feature(df: pl.DataFrame, column: str, period: int, output: str) -> pl.Series:
    # Native SMA accepts a 'close' field. Temporarily rebind to a derived TR.
    bound = df.with_columns(pl.col(column).alias("close"))
    return _native(bound, [_p("sma", period, output)])[output]


def morning_dip_features(bars_3m: pl.DataFrame) -> pl.DataFrame:
    """NQ CFD signal geometry; 1-minute input cannot validate 1-second limit fills.

    Efficiency ratio ER15 = |C[t]-C[t-15]| / sum(|C[k]-C[k-1]|, k=t-14..t).
    Source ATR is simple mean(TR,14), NOT native Wilder ATR14.
    """
    base = _base(bars_3m)
    native = _native(base, [{"name": "trange", "output": "true_range"}])
    atr14_sma = _sma_of_feature(native, "true_range", 14, "atr14_simple")
    return (native.with_columns(atr14_sma.alias("atr14_simple"))
            .with_columns(
                pl.col("close").diff().abs().alias("abs_diff"),
            )
            .with_columns(
                (pl.col("close") - pl.col("close").shift(15)).abs().alias("net_change15"),
                pl.col("abs_diff").rolling_sum(15).alias("gross_change15"),
            )
            .with_columns(
                pl.when(pl.col("gross_change15") > 0)
                .then(pl.col("net_change15") / pl.col("gross_change15"))
                .otherwise(None).alias("er15"),
                (pl.col("close") - pl.col("atr14_simple")).alias("limit_level"),
                ((pl.col("high") + pl.col("low")) / 2).alias("target_level"),
                (pl.col("close") - 2.5 * pl.col("atr14_simple")).alias("stop_level"),
            )
            .with_columns(
                (pl.col("er15") <= 0.35).fill_null(False).alias("choppy")
            ))


def legends_buy_day_features(daily_globex: pl.DataFrame) -> pl.DataFrame:
    """Exactly three consecutive lower FULL-Globex session closes.

    Output signal at completion of the third down session. The corresponding
    author's ENTRY is 18:00 ET the next Globex session, EXIT 09:30 ET.
    Raw daily CFD bars are insufficient for order-price parity.
    """
    df = _base(daily_globex)
    c = pl.col("close")
    down = c < c.shift(1)
    return df.with_columns(down.alias("down")).with_columns(
        (pl.col("down") & pl.col("down").shift(1) & pl.col("down").shift(2)
         & ~pl.col("down").shift(3)).fill_null(False).alias("setup_complete"),
    )


def phase_compression_features(bars: pl.DataFrame) -> pl.DataFrame:
    """Saty Phase Oscillator grey compression from Milkman's public code.

    BB centre EMA21, BB width 2*sample-stddev21, KC width 2*Wilder ATR14.
    The public source uses pandas min_periods=1 on std and EMA from bar 1.
    Native ML4T warms up for 21 bars; pre-warmup rows are null, not signals.
    Algebra simplifies source's price-side branch to:
      compression_gap = 2*(std21 - atr14)
      expansion_gap = 2*std21 - 1.854*atr14
      grey = gap<=0 and not (gap>=previous_gap and expansion_gap>0)
    """
    base = _base(bars)
    native = _native(base, [
        _p("ema", 21, "ema21"),
        _p("atr", 14, "atr14_wilder"),
        _p("stddev", 21, "std21_sample", ddof=1),
    ])
    return (native.with_columns(
        (2 * (pl.col("std21_sample") - pl.col("atr14_wilder"))).alias("compression_gap"),
        (2 * pl.col("std21_sample") - 1.854 * pl.col("atr14_wilder")).alias("expansion_gap"),
    ).with_columns(
        (pl.col("compression_gap") <= 0).alias("within_keltner"),
        (pl.col("compression_gap") >= pl.col("compression_gap").shift(1))
        .alias("gap_not_shrinking"),
    ).with_columns(
        (pl.col("within_keltner") &
         ~(pl.col("gap_not_shrinking") & (pl.col("expansion_gap") > 0)))
        .fill_null(False).alias("grey")
    ))


def legends_ema_daily_setups(rth_15m: pl.DataFrame, *, lookback_sessions: int = 252) -> pl.DataFrame:
    """Causal NQ CFD adaptation to 15m RTH no-EMA-touch trend-day setup.

    Author used entire 2008-2026 population 80th-percentile; this is NOT PIT.
    Here percentile is rolling PREVIOUS 252 completed sessions, so it can be
    used next session. Caller supplies 15m RTH-only bars and a session_date
    derived from America/New_York using the actual source clock.
    """
    if "session_date" not in rth_15m:
        raise ValueError("session_date (New York RTH trading date) is required")
    df = _base(rth_15m).with_columns(rth_15m.sort("timestamp")["session_date"])
    native = _native(df, [_p("ema", 20, "ema20")])
    daily = native.group_by("session_date").agg(
        pl.col("open").sort_by("timestamp").first().alias("open"),
        pl.col("high").max().alias("high"),
        pl.col("low").min().alias("low"),
        pl.col("close").sort_by("timestamp").last().alias("close"),
        pl.len().alias("n_15m_bars"),
        ((pl.col("low") <= pl.col("ema20")) &
         (pl.col("high") >= pl.col("ema20"))).any().alias("ema_touched"),
        pl.col("ema20").sort_by("timestamp").last().alias("last_completed_ema"),
    ).sort("session_date")
    return (daily.with_columns(
        ((pl.col("close") - pl.col("open")).abs()
         / (pl.col("high") - pl.col("low")).replace(0, None))
        .alias("trend_ratio")
    ).with_columns(
        pl.col("trend_ratio").shift(1).rolling_quantile(
            .80, window_size=lookback_sessions, min_samples=lookback_sessions,
        ).alias("threshold_prev_only")
    ).with_columns(
        (pl.col("trend_ratio") >= pl.col("threshold_prev_only"))
        .fill_null(False).alias("strong_trend"),
        ((~pl.col("ema_touched")) & pl.col("last_completed_ema").is_not_null())
        .alias("no_touch")
    ).with_columns(
        (pl.col("strong_trend") & pl.col("no_touch")
         & (pl.col("n_15m_bars") == 26))
        .fill_null(False).alias("setup_complete")
    ))


def swing_golden_gate_features(daily: pl.DataFrame, monthly: pl.DataFrame) -> pl.DataFrame:
    """CFD adaptation of source short gate; all monthly rails are fixed in advance.

    Monthly data must be completed months (no partial month). `month` is the
    year-month in actual market session time, not in UTC calendar time.
    The feature observes gate opens and completion; broker orders are separate.
    """
    if "month" not in monthly.columns or "month" not in daily.columns:
        raise ValueError("Both daily and monthly must carry session-calendar month")
    if monthly["month"].n_unique() != monthly.height:
        raise ValueError("Monthly input must contain exactly one COMPLETED bar per month")
    d = _base(daily).with_columns(daily.sort("timestamp")["month"])
    m = _base(monthly).with_columns(monthly.sort("timestamp")["month"])
    mn = _native(m, [_p("atr", 14, "monthly_atr14")])
    rails = mn.with_columns(
        pl.col("close").shift(1).alias("prev_month_close"),
        pl.col("monthly_atr14").shift(1).alias("prev_month_atr14"),
    ).select("month", "prev_month_close", "prev_month_atr14")
    joined = _native(d, [_p("ema", 21, "daily_ema21")]).join(rails, on="month", how="left")
    return joined.with_columns(
        (pl.col("prev_month_close") - .382 * pl.col("prev_month_atr14")).alias("down_gate_open"),
        (pl.col("prev_month_close") - .618 * pl.col("prev_month_atr14")).alias("down_gate_complete"),
        (pl.col("prev_month_close") - pl.col("prev_month_atr14")).alias("short_target"),
        pl.col("prev_month_close").alias("short_stop"),
        (pl.col("close").shift(1) > pl.col("daily_ema21").shift(1))
        .fill_null(False).alias("prev_close_above_ema21"),
    )


def daily_bilbo_features(daily: pl.DataFrame) -> pl.DataFrame:
    """Index CFD compression state, not equity universe or stock trade parity."""
    out = phase_compression_features(daily)
    ema = _native(_base(daily), [_p("ema", 50, "ema50")])
    return out.with_columns(ema["ema50"].shift(1).alias("prior_ema50"))


def hourly_bilbo_features(hourly_eth: pl.DataFrame) -> pl.DataFrame:
    """Index CFD ETH-hourly compression. Original option PnL is unavailable."""
    return phase_compression_features(hourly_eth)


def attach_prior_daily_ema_gate(hourly: pl.DataFrame, daily_rth: pl.DataFrame) -> pl.DataFrame:
    """Join last COMPLETED RTH-day EMA21 gate to each ETH hourly decision bar.

    Daily and hourly inputs must be from the SAME CFD instrument. The daily
    RTH bar timestamp must be the true post-close availability time. This
    is strictly prior-day: no current RTH day values enter a morning signal.
    """
    h = hourly.sort("timestamp")
    d = _native(_base(daily_rth), [_p("ema", 21, "rth_daily_ema21")])
    day = pl.col("timestamp").dt.convert_time_zone("America/New_York").dt.date()
    daily_gate = d.with_columns(day.alias("et_day")).with_columns(
        (pl.col("close") >= pl.col("rth_daily_ema21"))
        .shift(1).fill_null(False).alias("prior_daily_above_ema21")
    ).select("et_day", "prior_daily_above_ema21")
    if daily_gate["et_day"].n_unique() != daily_gate.height:
        raise ValueError("Daily RTH bars must have unique New York dates")
    return (h.with_columns(day.alias("et_day"))
            .join(daily_gate, on="et_day", how="left")
            .with_columns(pl.col("prior_daily_above_ema21").fill_null(False)))


def box_episode_signals(features: pl.DataFrame, *, mode: str) -> pl.DataFrame:
    """Source close-confirmed box state machine, without any simulated fills.

    Hourly: test only first bar after grey, first 5 grey bars freeze the box.
    Daily: after the box locks, keep a possible breakout for 20 later bars,
    veto when low hits box low first; report observation, not order fills.
    """
    if mode not in {"hourly", "daily"}:
        raise ValueError(mode)
    if mode == "hourly" and "prior_daily_above_ema21" not in features.columns:
        raise ValueError("Hourly Bilbo requires PIT prior_daily_above_ema21 gate")
    if mode == "daily" and "ema21" not in features.columns:
        raise ValueError("Daily Bilbo requires native daily EMA21")
    for c in ("grey", "timestamp", "high", "low", "close"):
        if c not in features:
            raise ValueError(f"Missing {c}")
    df = features.sort("timestamp")
    if df["timestamp"].n_unique() != df.height:
        raise ValueError("Duplicate timestamp")
    ts = df["timestamp"].to_list()
    highs, lows, closes, greys = (df[c].to_list() for c in ("high", "low", "close", "grey"))
    entries = [False] * df.height
    box_high = [None] * df.height
    box_low = [None] * df.height
    active = False
    n_grey = 0
    h = l = None
    end_idx = -1
    lock_idx = -1
    for i in range(df.height):
        grey = bool(greys[i])
        if grey and not active:
            active, n_grey, h, l, lock_idx = True, 1, highs[i], lows[i], -1
        elif grey and active and n_grey < 5:
            n_grey += 1
            h, l = max(h, highs[i]), min(l, lows[i])
            if n_grey == 5:
                lock_idx = i
                end_idx = i + 20
        elif grey and active:
            n_grey += 1
        elif active:
            if lock_idx < 0:
                lock_idx, end_idx = i - 1, i + 19
            # Once a bar exits compression, hourly study permits ONE decision.
            in_time = mode == "daily" or (ts[i] - ts[lock_idx]).total_seconds() <= 10 * 86400
            if mode == "daily":
                prev_ema = df["ema21"][i - 1] if i else None
                prev_trend = isinstance(prev_ema, (int, float)) and math.isfinite(prev_ema) and closes[i - 1] >= prev_ema
            else:
                prev_trend = bool(df["prior_daily_above_ema21"][i])
                close_et = ts[i].astimezone(ZoneInfo("America/New_York"))
                in_time = in_time and close_et.weekday() < 5 and 10 <= close_et.hour <= 15
            # Without intrabar tick ordering, a daily bar hitting both rails
            # cannot be credited as a long fill (conservative stop-first).
            unambiguous = mode == "hourly" or lows[i] > l
            if in_time and prev_trend and unambiguous and closes[i] > h and i > lock_idx:
                entries[i] = True
            active = mode == "daily" and not entries[i] and i < end_idx and lows[i] > l
        if active:
            box_high[i], box_low[i] = h, l
        else:
            box_high[i], box_low[i] = h, l
    return df.with_columns(
        pl.Series("box_high", box_high), pl.Series("box_low", box_low),
        pl.Series("box_close_break", entries),
    )
