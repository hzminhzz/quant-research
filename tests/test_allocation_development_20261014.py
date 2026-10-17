"""Allocation experiment invariants, synthetic only. No 2025+ source data read."""
from datetime import UTC, datetime

import numpy as np
import pytest

from scripts import allocation_linear_development_20261014 as model
from scripts import allocation_monthly_panel_20261014 as panel


def test_complete_monthly_panel_no_imputation_and_clock_gate():
    starts = ("2023-01-30", "2023-01-31", "2023-02-28")
    streams = {}
    for name in panel.IDS:
        streams[name] = {}
        for day in starts:
            t = datetime.fromisoformat(day).replace(tzinfo=UTC)
            t = t.replace(hour=23, minute=59) if name in panel.IDS[:2] else t
            streams[name][day] = panel.ObservedMark(day, t, 100.0)
    common, observed, months = panel._eligible_calendar(streams)
    assert len(common) == 3
    assert observed == list(starts)
    assert months == [("2023-01", "2023-01-31"), ("2023-02", "2023-02-28")]
    del streams[panel.IDS[0]]["2023-02-28"]
    common, observed, months = panel._eligible_calendar(streams)
    assert months == [("2023-01", "2023-01-31")]
    assert "2023-02-28" not in observed


def test_bad_native_cfd_clock_is_excluded_not_forward_filled():
    d = "2024-03-28"
    streams = {}
    for name in panel.IDS:
        t = datetime(2024, 3, 28, tzinfo=UTC)
        t = t.replace(hour=23, minute=59) if name in panel.IDS[:2] else t
        streams[name] = {d: panel.ObservedMark(d, t, 100.0)}
    streams[panel.IDS[1]][d] = panel.ObservedMark(d, datetime(2024, 3, 28, 20, tzinfo=UTC), 100.0)
    common, eligible, months = panel._eligible_calendar(streams)
    assert common == [d]
    assert eligible == []
    assert months == []


def test_portfolio_accounting_uses_pretrade_drift_and_deducts_synthetic_cost():
    weights = np.full((2, 4), 0.25)
    rets = np.asarray([[0.10, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0]])
    net, turnover, costs = model._allocation_accounting(weights, rets, cost_multiplier=1)
    assert turnover[0] == pytest.approx(1.0)
    assert net[0] == pytest.approx((1 - 0.001) * (1 + 0.025) - 1)
    pretrade = np.array([0.25 * 1.1, 0.25, 0.25, 0.25]) / 1.025
    assert turnover[1] == pytest.approx(np.abs(np.full(4, 0.25) - pretrade).sum() / 2)
    assert costs[1] > 0


def test_model_excludes_uncompleted_forward_labels(monkeypatch):
    features = np.ones((32, 4, 5), dtype=float)
    for i in range(32):
        features[i, :, 0] = i * 0.002 + np.arange(4) / 100
    returns = np.repeat(np.arange(31, dtype=float)[:, None] / 10000, 4, axis=1)
    captured = []
    orig = model._train_batch
    def spy(features, labels, idx):
        captured.extend(idx)
        return orig(features, labels, idx)
    monkeypatch.setattr(model, "_train_batch", spy)
    w, n = model._model_weight(features, returns, 25, list(range(31)))
    assert max(captured) == 24
    assert n == 25
    assert np.isclose(sum(w), 1)
    assert max(w) <= 0.40000001
    assert min(w) >= -1e-10


def test_holdout_boundary_declared_exclusive_and_model_exposure():
    assert panel.END == "2025-01-01"
    assert model.OUTCOME_MONTH_END == "2024-12"
    assert model.PRIMARY_REBALANCE_COST_BPS == 10.0
