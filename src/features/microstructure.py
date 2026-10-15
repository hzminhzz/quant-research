"""Opt-in microstructure features. Source semantics are mandatory, not inferred."""

import polars as pl
from ml4t.engineer.features.microstructure import bid_ask_imbalance, effective_tick_rule
from ._contracts import require_single_ordered


def require_market_structure_capability(name: str) -> None:
    """Reject unsupported auction, VPIN, and volume-profile claims explicitly."""
    if name.lower().replace("-", "_") in {"auction", "vpin", "volume_profile", "ofi"}:
        raise NotImplementedError(f"{name} requires separately verified event-level source and implementation")
    raise ValueError(f"unknown market-structure capability: {name}")


def _reject_false_claim(alias: str) -> None:
    normalized = alias.lower().replace("-", "_")
    if any(term in normalized for term in ("auction", "vpin", "volume_profile", "ofi", "trade_volume")):
        raise ValueError("proxy cannot be labeled auction, VPIN, volume profile, OFI, or trade volume")


def add_book_imbalance(
    frame: pl.DataFrame,
    *,
    source_kind: str,
    bid_size_col: str = "bid_size",
    ask_size_col: str = "ask_size",
    alias: str = "book_size_imbalance",
    instrument_col: str = "instrument",
    timestamp_col: str = "timestamp",
) -> pl.DataFrame:
    """Compute resting book-size imbalance only for verified LOB snapshots.

    This is not event-level order-flow imbalance (OFI). Quote updates and
    broker tick volume do not measure resting bid/ask size.
    """
    if source_kind != "exchange_lob_snapshot":
        raise ValueError("book imbalance requires exchange_lob_snapshot; CFD tick/quote volume is not LOB OFI")
    _reject_false_claim(alias)
    require_single_ordered(frame, instrument_col=instrument_col, timestamp_col=timestamp_col)
    if not {bid_size_col, ask_size_col} <= set(frame.columns):
        raise ValueError("book imbalance requires bid_size and ask_size columns")
    if frame.select(
        (pl.col(bid_size_col).is_null() | pl.col(ask_size_col).is_null()
         | ~pl.col(bid_size_col).is_finite() | ~pl.col(ask_size_col).is_finite()
         | (pl.col(bid_size_col) < 0) | (pl.col(ask_size_col) < 0)
         | ~((pl.col(bid_size_col) + pl.col(ask_size_col)) > 0)
         | ~(pl.col(bid_size_col) + pl.col(ask_size_col)).is_finite()).any()
    ).item():
        raise ValueError("book sizes must be finite nonnegative with finite positive total")
    return frame.with_columns(bid_ask_imbalance(bid_size_col, ask_size_col).alias(alias))


def add_trade_sign_proxy(
    frame: pl.DataFrame,
    *,
    source_kind: str,
    price_col: str = "close",
    alias: str = "price_change_sign_proxy",
    instrument_col: str = "instrument",
    timestamp_col: str = "timestamp",
) -> pl.DataFrame:
    """Label native tick-rule price-change sign as proxy, never VPIN or OFI.

    Rows must be in causal timestamp order within one instrument. This helper
    deliberately does not consume broker quote counts or claimed trade volume.
    """
    if source_kind not in {"exchange_trades", "cfd_quotes"}:
        raise ValueError("source_kind must identify exchange_trades or cfd_quotes")
    _reject_false_claim(alias)
    require_single_ordered(frame, instrument_col=instrument_col, timestamp_col=timestamp_col)
    if price_col not in frame.columns:
        raise ValueError(f"missing price column: {price_col}")
    if frame[price_col].null_count() or not frame[price_col].is_finite().all():
        raise ValueError("prices must be finite and non-null")
    return frame.with_columns(effective_tick_rule(price_col).alias(alias))
