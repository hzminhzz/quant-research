from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl

from scripts.prepare_crypto_xs_plain_funding_decay_validation_20261015 import (
    ORIGINAL_ANCHOR,
    VALID_END,
    VALID_START,
)


def test_validation_window_is_before_protected_2026():
    assert VALID_START == datetime(2024, 1, 1, tzinfo=UTC)
    assert VALID_END == datetime(2026, 1, 1, tzinfo=UTC)


def test_original_48h_anchor_is_preserved():
    first_candidates = [
        VALID_START + timedelta(days=i) for i in range(4)
    ]
    valid = [
        ts
        for ts in first_candidates
        if int((ts - ORIGINAL_ANCHOR).total_seconds() / 3600) % 48 == 0
    ]
    assert valid
    assert all(ts < VALID_END for ts in valid)
