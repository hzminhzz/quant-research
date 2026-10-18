import hashlib

import pandas as pd


def universe_key(symbols: list[str]) -> str:
    """Stable short hash of a symbol list (order-insensitive) for cache filenames."""
    return hashlib.md5("_".join(sorted(symbols)).encode()).hexdigest()[:10]


def ticker_level_name(cols: pd.MultiIndex, source: str) -> str:
    """Return the MultiIndex level name that holds tickers.

    yfinance has shipped the level as 'Ticker' historically but the name is
    not contractually stable across versions. Accept a short list of known
    aliases and raise a clear error if none match.
    """
    names = [n for n in cols.names if n is not None]
    for candidate in ("Ticker", "Ticker/Symbol", "symbol", "Symbol"):
        if candidate in names:
            return candidate
    raise ValueError(
        f"{source}: could not find ticker level in MultiIndex columns "
        f"(levels={names}). yfinance may have changed its schema."
    )


def require_ohlcv_columns(df: pd.DataFrame, source: str) -> None:
    """Assert the long-format frame has the standard OHLCV columns."""
    required = {"date", "symbol", "open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"{source}: long-format frame missing columns {sorted(missing)}; "
            f"got {sorted(df.columns)}"
        )
