"""Independent numerical and causal audits of FOMC proxy-only Phase 3.

These tests do not call the evaluator, do not trade, and never load 2025+ bars.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import polars as pl
import pytest
import yaml
from scipy.stats import t

from scripts import fomc_sp500_overnight_phase3_proxy_20261015 as study

ROOT = Path(__file__).resolve().parents[1]


def test_nonexecuted_bid_proxy_return_definition():
    assert study.gross_return(100.0, 101.0) == pytest.approx(0.01)
    assert study.gross_return(100.0, 98.0) == pytest.approx(-0.02)
    with pytest.raises(ValueError):
        study.gross_return(0.0, 100.0)
    with pytest.raises(ValueError):
        study.gross_return(100.0, float("nan"))


def test_frozen_input_and_evaluation_contract():
    frozen_path = (
        ROOT / "run_log/research_sessions" / study.SESSION / "frozen_spec.json"
    )
    if frozen_path.exists():
        frozen = json.loads(frozen_path.read_text())
        assert frozen["status"] == "FROZEN"
        assert frozen["identity"]["data"][0]["sha256"] == study._hash(study.DATA)
        spec = frozen["spec"]
    else:
        # A clean Git worktree contains the published input and protocol.
        # The immutable local-only registry is not required for source audit.
        spec = yaml.safe_load(study.SPEC.read_text())
    assert spec["evaluation"]["holdout_start"] == "2025-01-01T00:00:00Z"
    assert spec["trials"][0]["kind"] == "diagnostic"
    assert len(spec["trials"]) == 1
    assert spec["costs"]["costs_mode"] == (
        "not_applicable_to_gross_proxy_signal_screen"
    )
    prices = pl.read_parquet(study.DATA)
    assert prices.height == 4 * study.EXPECTED_PAIRS
    assert prices["timestamp"].max() < study.HOLDOUT
    assert prices["timestamp"].min() >= datetime(2017, 1, 1, tzinfo=UTC)
    assert prices["quote_side"].unique().to_list() == ["historical_bid_only"]


def _independent_records() -> list[dict]:
    frozen_prices = pl.read_parquet(study.DATA)
    original = {
        (r["statement_date"], r["leg"], r["action"]): r
        for r in frozen_prices.iter_rows(named=True)
    }
    dates = [e["statement_date"] for e in study.eligible_events()]
    out = []
    for d in dates:
        row = {"statement_date": d}
        for leg in ("fomc", "control"):
            entry = original[(d, leg, "entry")]
            exit_ = original[(d, leg, "exit")]
            assert entry["timestamp"] < exit_["timestamp"]
            row[leg] = (exit_["open"] - entry["open"]) / entry["open"]
        row["paired"] = row["fomc"] - row["control"]
        out.append(row)
    return out


def _manual_nw_se(x: np.ndarray, lag: int = 2) -> float:
    # Independent scalar Bartlett HAC covariance of an OLS mean estimate.
    n = len(x)
    u = x - x.mean()
    s = float(np.dot(u, u))
    for k in range(1, lag + 1):
        s += 2 * (1 - k / (lag + 1)) * float(np.dot(u[k:], u[:-k]))
    return float(np.sqrt((n / (n - 1)) * s / (n**2)))


def test_event_ledger_reconciles_independently_to_frozen_raw_data():
    records = _independent_records()
    ledger = pl.read_csv(ROOT / "docs/audit" / (study.SESSION + "_event_pairs.csv"))
    metric = json.loads(
        (ROOT / "docs/audit" / (study.SESSION + "_metrics.json")).read_text()
    )
    assert len(records) == ledger.height == metric["events"] == 53
    assert metric["phase3_signal_decision"] == "INCONCLUSIVE"
    assert metric["recorded_historical_hyperliquid_returns"] is False
    assert metric["recorded_strategy_returns"] is False
    frozen_path = (
        ROOT / "run_log/research_sessions" / study.SESSION / "frozen_spec.json"
    )
    if frozen_path.exists():
        assert (
            metric["frozen_spec_sha256"]
            == json.loads(frozen_path.read_text())["spec_sha256"]
        )
    else:
        assert len(metric["frozen_spec_sha256"]) == 64
    assert metric["preflight_sha256"] == study._hash(study.AUDIT)

    expected = np.asarray([r["paired"] for r in records])
    observed = ledger["paired_gross_excess"].to_numpy()
    np.testing.assert_allclose(observed, expected, atol=1e-13, rtol=0)
    for leg, key in (
        ("fomc", "fomc_bid_proxy_gross"),
        ("control", "control_bid_proxy_gross"),
    ):
        expected_leg = np.array([r[leg] for r in records])
        assert float(expected_leg.mean()) == pytest.approx(
            metric[key]["mean_fraction"], abs=1e-12
        )

    source_means = metric["paired_bid_proxy_gross_increment"]
    assert float(expected.mean()) == pytest.approx(
        source_means["mean_fraction"], abs=1e-12
    )
    se = _manual_nw_se(expected)
    assert se * 10_000 == pytest.approx(source_means["standard_error_bps"], abs=1e-8)
    crit = t.ppf(0.975, len(expected) - 1)
    assert (expected.mean() - crit * se) * 10000 == pytest.approx(
        source_means["lower_95_bps"], abs=1e-8
    )
    assert (expected.mean() + crit * se) * 10000 == pytest.approx(
        source_means["upper_95_bps"], abs=1e-8
    )
    assert source_means["lower_95_bps"] < 0 < source_means["upper_95_bps"]


def test_frozen_event_calendar_control_dates_are_not_shifted():
    rows = _independent_records()
    from datetime import date, timedelta

    dates = [date.fromisoformat(row["statement_date"]) for row in rows]
    all_events = {ev["statement_date"]: ev for ev in study.eligible_events()}
    assert len(dates) == len(set(dates)) == 53
    for d in dates:
        event = all_events[d.isoformat()]
        c = date.fromisoformat(event["control_statement_date"])
        assert (d - c) == timedelta(days=7)
        assert d.weekday() == c.weekday()


def test_hac_boundary_with_constant_negative_alternative():
    # Independent formula rejects a series that is decisively negative.
    values = np.array([-0.002, -0.003, -0.0025, -0.0028, -0.0032, -0.0029])
    se = _manual_nw_se(values)
    assert (values.mean() + t.ppf(0.975, len(values) - 1) * se) < 0
