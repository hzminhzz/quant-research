"""Native ML4T feature rebuild of seven uploaded Empirica Lab strategy variants.

This module produces decision-time features/signals, not fills or trade PnL.
Every indicator is sourced from ml4t.engineer.compute_features; Polars
expressions only combine registered indicator outputs into decision rules.
A result at timestamp t becomes tradable after that bar has completed.
"""
from __future__ import annotations

import polars as pl
from ml4t.engineer import compute_features

NAMES = (
    "pivot-breakout-btc", "donchian-btc", "three-red-spy",
    "gold-macd-hook", "slope-hook", "fx-timing", "rsi-30-50",
)
DONCHIAN_WINDOWS = (10, 15, 20, 30, 45, 65, 95, 140, 200)


def _base(prices: pl.DataFrame) -> pl.DataFrame:
    expected = {"timestamp", "open", "high", "low", "close", "volume"}
    if not expected.issubset(prices.columns):
        raise ValueError(f"Missing OHLC/time columns: {sorted(expected - set(prices.columns))}")
    ordered = prices.sort("timestamp")
    if ordered["timestamp"].n_unique() != ordered.height:
        raise ValueError("Duplicate timestamps; compute one instrument at a time")
    return ordered


def _native(df: pl.DataFrame, specs: list[dict]) -> pl.DataFrame:
    return compute_features(df, specs, timestamp_col="timestamp")


def _ind(name: str, period: int, output: str) -> dict:
    return {"name": name, "params": {"period": period}, "output": output}


def _rebind_close(df: pl.DataFrame, col: str, specs: list[dict]) -> pl.DataFrame:
    """Pass an intermediate indicator as the close input to native features."""
    return _native(df.with_columns((pl.col(col) + 1000.0).alias("close")), specs)


def pivot_breakout_btc(prices: pl.DataFrame) -> pl.DataFrame:
    """Seven-bar confirmed pivot; report source's prior-pivot breakout setup.

    Source has stateful stop updates and intrabar breakout fills. This method
    does not invent those fills or assume an intraday stop priority.
    """
    df = _base(prices)
    native = _native(df, [
        _ind("sma", 50, "sma50"), _ind("sma", 10, "sma10"),
        {"name": "donchian_channels", "params": {"period": 7}, "output": "pivot7"},
    ])
    return (native.with_columns(
        pl.when(pl.col("high").shift(3) == pl.col("pivot7_0"))
        .then(pl.col("high").shift(3)).otherwise(None).forward_fill().alias("confirmed_pivot_high"),
        pl.when(pl.col("low").shift(3) == pl.col("pivot7_1"))
        .then(pl.col("low").shift(3)).otherwise(None).forward_fill().alias("confirmed_pivot_low"),
    ).with_columns(
        ((pl.col("high") > pl.col("confirmed_pivot_high").shift(1))
         & (pl.col("close").shift(1) > pl.col("sma50").shift(1))
         & pl.col("confirmed_pivot_low").shift(1).is_not_null())
        .fill_null(False).alias("breakout_observed"),
        (pl.col("close") < pl.col("sma10")).fill_null(False).alias("below_sma10"),
    ))


def donchian_btc(prices: pl.DataFrame) -> pl.DataFrame:
    """Nine close-only breakout channels and 60-bar volatility target.

    Uses the source's CLOSE channels, rather than high/low Donchian defaults.
    Source uses 252 day annualization and caps leverage at 2.0.
    """
    df = _base(prices)
    channel_spec = [
        {"name": "maximum", "params": {"timeperiod": n}, "output": f"highclose_{n}"}
        for n in DONCHIAN_WINDOWS
    ] + [
        {"name": "minimum", "params": {"timeperiod": n}, "output": f"lowclose_{n}"}
        for n in DONCHIAN_WINDOWS
    ]
    native = _native(df, channel_spec)
    native = native.with_columns(pl.col("close").pct_change().alias("daily_return"))
    vol = _rebind_close(native, "daily_return", [
        {"name": "stddev", "params": {"period": 60, "ddof": 1}, "output": "vol60"},
    ])
    native = native.with_columns(vol["vol60"].alias("daily_vol60"))
    for n in DONCHIAN_WINDOWS:
        hi, lo, state = f"highclose_{n}", f"lowclose_{n}", f"direction_{n}"
        native = native.with_columns(
            pl.when(pl.col("close") >= pl.col(hi).shift(1)).then(1.0)
            .when(pl.col("close") <= pl.col(lo).shift(1)).then(-1.0)
            .otherwise(None).forward_fill().fill_null(0.0).alias(state)
        )
    directions = [pl.col(f"direction_{n}") for n in DONCHIAN_WINDOWS]
    return native.with_columns(
        (pl.sum_horizontal(*directions) / len(directions)).alias("average_direction"),
        (pl.lit(0.25) / (pl.col("daily_vol60") * (252.0 ** 0.5)))
        .clip(0.0, 2.0).fill_nan(None).fill_null(0.0).alias("vol_leverage"),
    ).with_columns(
        (pl.col("average_direction") * pl.col("vol_leverage")).alias("target_exposure")
    )


def three_red_spy(prices: pl.DataFrame) -> pl.DataFrame:
    df = _base(prices)
    return df.with_columns((pl.col("close") < pl.col("open")).alias("red")).with_columns(
        (pl.col("red") & pl.col("red").shift(1) & pl.col("red").shift(2))
        .fill_null(False).alias("entry_signal"),
        (pl.col("close") > pl.col("open")).alias("exit_signal"),
    )


def gold_macd_hook(prices: pl.DataFrame) -> pl.DataFrame:
    """Native MACD line, native EMA signal, WMA(15)->SMA(7) Hull proxy."""
    df = _base(prices)
    base = _native(df, [_ind("wma", 15, "wma15"),
                        {"name": "macd", "params": {"fast_period": 12, "slow_period": 26},
                         "output": "macd_line"}])
    hma = _rebind_close(base, "wma15", [_ind("sma", 7, "hull_proxy")])
    sig = _rebind_close(base, "macd_line", [_ind("ema", 9, "macd_signal")])
    base = base.with_columns(
        (hma["hull_proxy"] - 1000.0).alias("hull_proxy"),
        (sig["macd_signal"] - 1000.0).alias("macd_signal"),
    ).with_columns(
        (pl.col("macd_line") - pl.col("macd_signal")).alias("histogram"),
        (pl.col("close") > pl.col("open")).alias("green"),
    )
    return base.with_columns(
        ((pl.col("macd_line") > 0) &
         (pl.col("histogram") > pl.col("histogram").shift(1)) &
         (pl.col("histogram").shift(1) < pl.col("histogram").shift(2)) &
         (pl.col("hull_proxy") > pl.col("hull_proxy").shift(1)))
        .fill_null(False).alias("entry_signal"),
        (pl.col("green") & pl.col("green").shift(1) & pl.col("green").shift(2))
        .fill_null(False).alias("exit_signal"),
    )


def slope_hook(prices: pl.DataFrame) -> pl.DataFrame:
    df = _base(prices)
    native = _native(df, [
        {"name": "typprice", "output": "typical"},
        _ind("sma", 5, "sma5"),
    ])
    slope = _rebind_close(native, "typical", [
        {"name": "linearreg_slope", "params": {"timeperiod": 3}, "output": "slope3"}
    ])
    native = native.with_columns(slope["slope3"])
    return native.with_columns(
        ((pl.col("slope3") > pl.col("slope3").shift(1)) &
         (pl.col("slope3").shift(1) < pl.col("slope3").shift(2)) &
         (pl.col("close") < pl.col("open"))).fill_null(False).alias("entry_signal"),
        (pl.col("close") > pl.col("sma5")).fill_null(False).alias("exit_signal"),
    )


def fx_timing(prices_by_symbol: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Friday FXE-vs-UUP signal for next session's SPY/BIL allocation."""
    required = {"FXE", "UUP", "SPY", "BIL"}
    if required != set(prices_by_symbol):
        raise ValueError(f"Required exact FX timing symbols: {sorted(required)}")
    outputs = []
    for symbol, raw in prices_by_symbol.items():
        df = _base(raw)
        native = _native(df, [_ind("roc", 20, f"roc_{symbol.lower()}")])
        outputs.append(native.select(
            "timestamp", pl.col("close").alias(f"close_{symbol.lower()}"),
            f"roc_{symbol.lower()}"
        ))
    joined = outputs[0]
    for piece in outputs[1:]:
        joined = joined.join(piece, on="timestamp", how="inner")
    return (joined.sort("timestamp")
        .with_columns((pl.col("roc_fxe") > pl.col("roc_uup")).alias("fxe_leads"))
        .with_columns(
            (pl.col("timestamp").dt.weekday() == 5).alias("week_last_session"),
        )
        .with_columns(
            pl.when(pl.col("week_last_session")).then(pl.col("fxe_leads"))
            .otherwise(None).forward_fill().fill_null(False).alias("hold_spy_next_session")
        ))


def rsi_30_50(prices: pl.DataFrame) -> pl.DataFrame:
    df = _base(prices)
    native = _native(df, [_ind("rsi", 5, "rsi5"), _ind("sma", 200, "sma200")])
    return native.with_columns(
        ((pl.col("rsi5") < 30) & (pl.col("close") > pl.col("sma200")))
        .fill_null(False).alias("entry_signal"),
        (pl.col("rsi5") >= 50).fill_null(False).alias("exit_signal"),
    )


FEATURE_BUILDERS = {
    "pivot-breakout-btc": pivot_breakout_btc,
    "donchian-btc": donchian_btc,
    "three-red-spy": three_red_spy,
    "gold-macd-hook": gold_macd_hook,
    "slope-hook": slope_hook,
    "fx-timing": fx_timing,
    "rsi-30-50": rsi_30_50,
}
