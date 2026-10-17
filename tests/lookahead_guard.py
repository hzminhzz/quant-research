"""Prefix-invariance guard for point-in-time feature code.

A causal transform must not change its output at rows before ``cut`` when only
rows from ``cut`` onward are mutated. Asserting this detects lookahead in any
feature pipeline.

:func:`assert_prefix_invariant` only has value if it fails on known-bad code.
``tests/e2e/test_lookahead_canary.py`` feeds it deliberate leaks and requires
it to raise.
"""

from __future__ import annotations

from typing import Callable, Sequence

import numpy as np
import polars as pl

__all__ = ["mutate_tail", "assert_prefix_invariant"]


def mutate_tail(
    frame: pl.DataFrame,
    cut: int,
    column: str = "close",
    factor: float = 5.0,
) -> pl.DataFrame:
    """Multiply every row from ``cut`` onward, so future data changes."""
    return frame.with_columns(
        pl.when(pl.int_range(pl.len()) >= cut)
        .then(pl.col(column) * factor)
        .otherwise(pl.col(column))
        .alias(column)
    )


def assert_prefix_invariant(
    transform: Callable[[pl.DataFrame], pl.DataFrame],
    frame: pl.DataFrame,
    cut: int,
    columns: Sequence[str],
) -> None:
    """Fail when mutating rows ``>= cut`` changes an output column before ``cut``."""
    if cut <= 0 or cut >= frame.height:
        raise ValueError(f"cut must fall inside the frame; got {cut} of {frame.height}")

    baseline = transform(frame)
    mutated = transform(mutate_tail(frame, cut))

    for column in columns:
        before = np.asarray(baseline[column][:cut].to_numpy(), dtype=float)
        after = np.asarray(mutated[column][:cut].to_numpy(), dtype=float)
        changed = np.flatnonzero(~np.isclose(before, after, equal_nan=True))
        if changed.size:
            row = int(changed[0])
            raise AssertionError(
                f"lookahead detected in {column}: mutating rows >= {cut} changed "
                f"the value at row {row} (< {cut}); "
                f"{before[row]!r} -> {after[row]!r}"
            )
