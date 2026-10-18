import pandas as pd

_FREQ_ALIAS = {
    "D": None, "DAILY": None,
    "W": "W-FRI", "WEEKLY": "W-FRI",
    "M": "ME", "MONTHLY": "ME",
    "Q": "QE", "QUARTERLY": "QE",
    "Y": "YE", "YEARLY": "YE",
}


def trading_calendar(
    start: str,
    end: str,
    market: str = "US",
) -> pd.DatetimeIndex:
    """Approximate trading calendar. Use pandas_market_calendars for exact holidays."""
    if market.lower() == "crypto":
        return pd.date_range(start, end, freq="D")
    return pd.bdate_range(start, end)


def resample_to_last(
    index: pd.DatetimeIndex,
    freq: str,
) -> pd.DatetimeIndex:
    """Given a trading-day index, return the last trading day per period.

    freq: 'D' / 'W' / 'M' / 'Q' / 'Y' (case insensitive) or raw pandas alias.
    """
    alias = _FREQ_ALIAS.get(freq.upper(), freq)
    if alias is None:
        return index

    s = pd.Series(index, index=index)
    return pd.DatetimeIndex(s.resample(alias).last().dropna().values)
