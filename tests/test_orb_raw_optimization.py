from __future__ import annotations

import numpy as np

from src.orb_raw_optimization import (
    _bh_adjust,
    _bucket,
    _quantile_edges,
    _sharpe,
)


def test_walk_forward_quantile_edges_are_training_only_primitives():
    training = np.arange(1.0, 11.0)
    edges = _quantile_edges(training, 5)
    assert len(edges) == 4
    buckets = _bucket(np.array([1.0, 3.0, 5.0, 7.0, 10.0]), edges)
    assert buckets.tolist() == [0, 1, 2, 3, 4]


def test_low_cardinality_factor_reduces_bucket_count():
    edges = _quantile_edges(np.array([0.0, 0.0, 1.0, 1.0]), 5)
    assert len(edges) == 1
    assert _bucket(np.array([0.0, 1.0]), edges).tolist() == [0, 1]


def test_bh_adjustment_is_monotonic_and_bounded():
    q = _bh_adjust({"a": 0.001, "b": 0.02, "c": 0.5})
    assert 0.0 <= q["a"] <= q["b"] <= q["c"] <= 1.0


def test_daily_sharpe_zero_for_constant_zero_returns():
    assert _sharpe(np.zeros(100)) == 0.0
