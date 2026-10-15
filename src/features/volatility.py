"""Opt-in realized variation on ordered, single-instrument positive prices."""

import math
import polars as pl

from ._contracts import require_single_ordered


def add_signed_semivariance_jump_proxy(
    frame: pl.DataFrame,
    *,
    window: int,
    price_col: str = "close",
    instrument_col: str = "instrument",
    timestamp_col: str = "timestamp",
) -> pl.DataFrame:
    """Rolling up/down squared log returns and nonnegative RV-minus-BPV proxy.

    Bipower variation (BPV) is pi/2 times adjacent absolute return products.
    RV-minus-BPV is a descriptive jump proxy, not a jump test or event label.
    Each window requires returns from current and previous bars. No fills occur.
    """
    require_single_ordered(frame, instrument_col=instrument_col, timestamp_col=timestamp_col)
    if not isinstance(window, int) or isinstance(window, bool) or window < 2:
        raise ValueError("window must be an integer >= 2")
    if price_col not in frame.columns:
        raise ValueError(f"missing price column: {price_col}")
    price = frame[price_col]
    if price.null_count() or not price.is_finite().all() or price.min() <= 0:
        raise ValueError("prices must be finite and strictly positive")
    ret = (pl.col(price_col) / pl.col(price_col).shift(1)).log()
    pos = pl.when(ret > 0).then(ret.pow(2)).otherwise(ret.pow(2) * 0)
    neg = pl.when(ret < 0).then(ret.pow(2)).otherwise(ret.pow(2) * 0)
    rv = ret.pow(2).rolling_sum(window)
    # BPV has window-1 adjacent return pairs within same window.
    bpv = (ret.abs() * ret.shift(1).abs()).rolling_sum(window - 1) * (math.pi / 2)
    # Pairs end at t-window+2 through t. First output needs window returns.
    return frame.with_columns(
        pos.rolling_sum(window).alias("realized_up_semivariance"),
        neg.rolling_sum(window).alias("realized_down_semivariance"),
        (rv - bpv).clip(lower_bound=0).alias("rv_bpv_jump_proxy"),
    )
