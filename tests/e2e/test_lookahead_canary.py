"""Lookahead canary: prove the prefix-invariance guard detects a deliberate leak.

A guard that never fails is not a guard. These tests feed the guard code with
known-bad behaviour and require it to raise. If the guard regresses into
something that always passes, the leak cases fail and say so.
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from src.features import compute_ema
from tests.e2e._market import ohlcv, random_walk
from tests.lookahead_guard import assert_prefix_invariant

pytestmark = pytest.mark.e2e

N_BARS = 200
CUT = 100
SEED = 20261009


@pytest.fixture(scope="module")
def frame() -> pl.DataFrame:
    closes = random_walk(N_BARS, seed=SEED)
    return ohlcv(closes, np.zeros(N_BARS, dtype=bool))


def test_guard_passes_on_causal_ema(frame: pl.DataFrame) -> None:
    assert_prefix_invariant(
        lambda data: compute_ema(data, span=20),
        frame,
        CUT,
        ["ema_20"],
    )


def test_guard_fails_on_forward_looking_close(frame: pl.DataFrame) -> None:
    def leak(data: pl.DataFrame) -> pl.DataFrame:
        return data.with_columns(pl.col("close").shift(-1).alias("feat"))

    with pytest.raises(AssertionError, match="lookahead detected in feat"):
        assert_prefix_invariant(leak, frame, CUT, ["feat"])


def test_guard_fails_on_full_sample_normalization(frame: pl.DataFrame) -> None:
    """The classic leak: a scaler fitted over the whole series, train or not."""

    def leak(data: pl.DataFrame) -> pl.DataFrame:
        mean = data["close"].mean()
        std = data["close"].std()
        return data.with_columns(((pl.col("close") - mean) / std).alias("feat"))

    with pytest.raises(AssertionError, match="lookahead detected in feat"):
        assert_prefix_invariant(leak, frame, CUT, ["feat"])


def test_guard_rejects_a_cut_outside_the_frame(frame: pl.DataFrame) -> None:
    with pytest.raises(ValueError, match="cut must fall inside the frame"):
        assert_prefix_invariant(lambda data: data, frame, N_BARS, ["close"])
