"""Technical execution fix for frozen 2024-2025 decay validation.

The frozen validation runner reused funding_events_by_hour() from the 2020-2023
MVP module. That helper filters events using the old DEV_START/DEV_END globals,
so the first validation execution applied zero 2024-2025 funding cashflows.

This wrapper changes only that helper window to the already-frozen validation
window and redirects outputs to a separate immutable directory. It delegates
all signal, labels, diagnostics, portfolio rules, costs and terminal/decay gates
to the frozen runner unchanged.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any
import sys

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.run_crypto_xs_plain_funding_decay_validation_20261015 as frozen
from scripts.prepare_crypto_xs_plain_funding_decay_validation_20261015 import (
    VALID_END,
    VALID_START,
)

FIX_OUT = (
    ROOT
    / "run_log"
    / "research_sessions"
    / frozen.SESSION
    / "validation_execution_fix1"
)


def validation_funding_events_by_hour(
    funding: pl.DataFrame, symbols: set[str]
) -> dict:
    selected = (
        funding.filter(
            pl.col("symbol").is_in(sorted(symbols))
            & (pl.col("timestamp") >= VALID_START)
            & (pl.col("timestamp") < VALID_END)
        )
        .sort("timestamp", "symbol")
    )
    out: dict = defaultdict(list)
    for row in selected.iter_rows(named=True):
        ts = frozen._utc(row["timestamp"])
        hour = ts.replace(minute=0, second=0, microsecond=0)
        out[hour].append(
            {
                "timestamp": ts,
                "symbol": row["symbol"],
                "funding_rate": float(row["funding_rate"]),
                "mark_price": float(row["mark_price"]),
            }
        )
    return dict(out)


def main() -> None:
    frozen.funding_events_by_hour = validation_funding_events_by_hour
    frozen.OUT = FIX_OUT
    frozen.main()


if __name__ == "__main__":
    main()
