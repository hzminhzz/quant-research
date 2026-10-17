from datetime import datetime, timedelta, timezone

import numpy as np
import polars as pl

from src.btc_structure_reversal import Pivot, build_signal_frame
from src.btc_structure_reversal_attribution import (
    add_attribution_features,
    latest_confirmed_low_anchor_indices,
)


def _frame(n: int) -> pl.DataFrame:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    t = np.arange(n, dtype=float)
    close = 100.0 + 0.04 * t + 2.0 * np.sin(t / 5.0)
    return pl.DataFrame(
        {
            "timestamp": [start + timedelta(hours=int(i)) for i in range(n)],
            "symbol": ["BTCUSDT"] * n,
            "open": close - 0.1,
            "high": close + 0.8,
            "low": close - 0.8,
            "close": close,
            "volume": np.full(n, 10.0),
            "quote_volume": close * 10.0,
        }
    )


def test_low_anchor_is_unavailable_before_pivot_confirmation():
    anchors = latest_confirmed_low_anchor_indices(
        8, [Pivot("L", pivot_index=2, confirmation_index=4, price=90.0)]
    )
    assert anchors[:4].tolist() == [-1, -1, -1, -1]
    assert anchors[4:].tolist() == [2, 2, 2, 2]


def test_attribution_features_are_append_invariant_away_from_fractal_boundary():
    short_raw = _frame(80)
    full_raw = _frame(100)
    short_sig, short_pivots = build_signal_frame(short_raw)
    full_sig, full_pivots = build_signal_frame(full_raw)
    short = add_attribution_features(short_sig, short_pivots)
    full = add_attribution_features(full_sig, full_pivots)

    # The last two bars of the short prefix cannot yet have right-confirmed
    # pivots. Everything earlier must be identical after future bars append.
    n = 77
    for col in ("ema20", "ema20_slope3", "anchored_vwap", "adx14", "adx14_delta3"):
        a = short[col][:n].to_numpy()
        b = full[col][:n].to_numpy()
        assert np.allclose(a, b, equal_nan=True), col
    for col in ("r1_ema_signal", "r2_avwap_signal", "r3_regime_signal"):
        assert short[col][:n].to_list() == full[col][:n].to_list(), col


def test_trial_signals_are_strict_subsets_of_parent_signal():
    sig, pivots = build_signal_frame(_frame(100))
    out = add_attribution_features(sig, pivots)
    base = out["entry_signal"].to_numpy().astype(bool)
    for col in ("r1_ema_signal", "r2_avwap_signal", "r3_regime_signal"):
        trial = out[col].to_numpy().astype(bool)
        assert np.all(~trial | base)
