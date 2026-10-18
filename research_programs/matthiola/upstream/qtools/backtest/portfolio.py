import pandas as pd

from qtools.utils.dates import resample_to_last


def signal_to_weights(
    signal: pd.DataFrame,
    n_quantiles: int = 5,
    long_short: bool = True,
    rebalance: str | None = "ME",
) -> pd.DataFrame:
    """Quantile-sort signal into portfolio weights.

    Long-short: top quantile +equal, bottom quantile -equal.
        Dollar-neutral: sum(weights) = 0, gross = 2.
    Long-only: top quantile equal-weighted, sum = 1.

    If `rebalance` is a freq alias (e.g. 'ME', 'W'), weights are sparse
    (only at rebalance dates). None keeps the signal's native dates.
    """
    if rebalance is not None:
        rb_dates = resample_to_last(pd.DatetimeIndex(signal.index), rebalance)
        signal = signal.loc[rb_dates]

    ranks = signal.rank(axis=1, pct=True, method="first")
    top_thr = 1 - 1 / n_quantiles
    bot_thr = 1 / n_quantiles

    top = (ranks > top_thr).astype(float)
    top_w = top.div(top.sum(axis=1).replace(0, pd.NA), axis=0).fillna(0)

    if not long_short:
        return top_w

    bot = (ranks <= bot_thr).astype(float)
    bot_w = bot.div(bot.sum(axis=1).replace(0, pd.NA), axis=0).fillna(0)
    return top_w - bot_w


def equal_weight(mask: pd.DataFrame) -> pd.DataFrame:
    """Given a boolean mask (date × symbol), return equal weights per row."""
    m = mask.astype(float)
    return m.div(m.sum(axis=1).replace(0, pd.NA), axis=0).fillna(0)
