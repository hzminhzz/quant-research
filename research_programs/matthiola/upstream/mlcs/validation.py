"""Walk-forward cross-validation helpers.

Design choice: annual expanding window. For each out-of-sample year Y, the
training set is every row with date < Jan 1, Y; the test set is every row with
date in year Y. No purging/embargo — with monthly-horizon targets and annual
re-fit the look-ahead risk is minor, and the gain from purging is dwarfed by
the noise across folds.
"""
from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import pandas as pd


def walk_forward_years(
    dates: pd.Series,
    first_oos_year: int,
    last_oos_year: int,
) -> Iterator[tuple[int, np.ndarray, np.ndarray]]:
    """Yield `(oos_year, train_mask, test_mask)` one year at a time.

    Parameters
    ----------
    dates
        Date column (any dtype coercible to datetime) aligned 1:1 with the
        feature matrix rows.
    first_oos_year, last_oos_year
        Inclusive year range for out-of-sample evaluation.

    Notes
    -----
    Masks are boolean arrays aligned to `dates`. Skips any year where either
    side would be empty (e.g. last_oos_year past the data).
    """
    d = pd.to_datetime(dates)
    years = d.dt.year.values
    for oos_year in range(first_oos_year, last_oos_year + 1):
        train_mask = years < oos_year
        test_mask = years == oos_year
        if not train_mask.any() or not test_mask.any():
            continue
        yield oos_year, train_mask, test_mask
