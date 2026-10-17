"""Synthetic verification of the four declared support/reclaim trial gates."""

from datetime import datetime, timedelta, timezone

import numpy as np
import polars as pl

from scripts.run_fx_support_conditions_trial import (
    FEATURES,
    ML_CUTOFF,
    ML_PARAMS,
    TRIALS,
    ml_fold_selection,
    ml_matrix,
    predeclared_filter,
    proportion,
)


def _data():
    stamp = datetime(2018, 1, 1, tzinfo=timezone.utc)
    return pl.DataFrame({
        "symbol": ["EURUSD"] * 5,
        "event_timestamp": [stamp + timedelta(days=i) for i in range(5)],
        "label_horizon_end": [stamp + timedelta(days=i + 7) for i in range(5)],
        "year": [2018] * 5,
        "month": ["2018-01"] * 5,
        "target_before_support_invalidation_240": [True, False, True, False, False],
        "within_240_bars": [True, True, True, False, False],
        "candle_strength": [0.8, 0.8, 0.7, 0.9, 0.6],
        "roc3_atr": [0.5, -0.1, 0.2, 0.0, 0.1],
        "roc12_atr": [0.3] * 5,
        "roc24_atr": [0.5] * 5,
        "ema50_slope16_atr": [0.5, 0.5, -0.1, 0.5, 0.5],
        "ema_gap_atr": [0.2, -0.2, 0.2, 0.2, 0.2],
        "atr_ratio": [1.1, 1.1, 1.1, 1.3, 1.0],
        "support_gap_atr": [0.1] * 5,
        "distance_high_atr": [4.0] * 5,
        "reference_height_atr": [5.0] * 5,
        "bars_elapsed_calendar": [20.0] * 5,
        "utc_hour_sin": [0.1] * 5,
        "utc_hour_cos": [0.2] * 5,
    })


def test_predeclared_filters_do_not_read_labels():
    data = _data()
    # Outcome flips do not change the decision at signal time.
    flipped = data.with_columns(
        (~pl.col("target_before_support_invalidation_240")).alias(
            "target_before_support_invalidation_240"
        )
    )
    for arm, count in [(TRIALS[0], 5), (TRIALS[1], 1), (TRIALS[2], 2)]:
        original = predeclared_filter(data, arm)
        changed = predeclared_filter(flipped, arm)
        assert original["selected"].to_list() == changed["selected"].to_list()
        assert int(original["selected"].sum()) == count


def test_ml_matrix_has_no_labels_or_future_timestamps():
    d = _data()
    matrix = ml_matrix(d)
    assert matrix.shape == (5, len(FEATURES) + 3)
    assert np.isfinite(matrix).all()
    assert all(k not in FEATURES for k in (
        "target_before_support_invalidation_240",
        "first_new_high_bars",
        "label_horizon_end",
        "within_240_bars",
    ))
    assert ML_CUTOFF == 0.30
    assert ML_PARAMS["n_jobs"] == 1


def test_fold_train_purges_overlapping_horizon_and_embargo():
    t = datetime(2017, 1, 1, tzinfo=timezone.utc)
    frame = _data().with_columns(
        pl.Series("year", [2016, 2016, 2016, 2017, 2018]),
        pl.Series("event_timestamp", [
            t - timedelta(days=28),
            t - timedelta(days=12),
            t - timedelta(days=1),
            t + timedelta(days=4),
            t + timedelta(days=400),
        ]),
        pl.Series("label_horizon_end", [
            t - timedelta(days=10),
            t - timedelta(days=1),
            t + timedelta(days=8),
            t + timedelta(days=10),
            t + timedelta(days=450),
        ]),
    )
    train, valid = ml_fold_selection(frame, 2017, 2018)
    assert train.height == 1
    assert valid.height == 2
    assert train["label_horizon_end"].max() < t - timedelta(days=2)


def test_proportion_is_exact_and_wilson_finite():
    p = proportion(_data())
    assert p is not None
    assert p["n"] == 5 and p["hits"] == 2
    assert p["rate_pct"] == 40.0
    assert p["wilson_ci95_pct"][0] < 40 < p["wilson_ci95_pct"][1]
