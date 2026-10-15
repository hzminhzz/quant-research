"""Adversarial synthetic evidence. No historical market simulation."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from math import comb
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from src.portfolio.barrier_controller import RiskSnapshot, evaluate_risk
from src.validation.oracle import (
    FrozenIdentity,
    OracleContractError,
    RefitResult,
    checked_splits,
    evaluate_phase3,
    reconstruct_paths,
)


@pytest.mark.parametrize("n,k", [(5, 2), (6, 3)])
def test_cpcv_group_segments_reconstruct_distinct_paths(n, k):
    paths = reconstruct_paths(n, k)
    assert len(paths) == comb(n - 1, k - 1)
    assert len({tuple(path) for path in paths}) == len(paths)
    assert all(sorted(group for _, group in path) == list(range(n)) for path in paths)
    assert len({pair for path in paths for pair in path}) == k * comb(n, k)
    if n == 5:
        assert any(len({p for p, path in enumerate(paths) if any(s == split for s, _ in path)}) > 1
                   for split in range(comb(n, k)))


def _timeline(n=100):
    origin = datetime(2025, 1, 1, tzinfo=UTC)
    starts = tuple(origin + timedelta(days=i) for i in range(n))
    ends = tuple(t + timedelta(hours=12) for t in starts)
    return starts, ends


@pytest.mark.parametrize("n,k", [(5, 2), (6, 3)])
def test_native_cpcv_split_exact_purge_and_embargo(n, k):
    starts, ends = _timeline(120)
    folds = checked_splits(starts, ends, n_groups=n, n_test_groups=k,
                           embargo=timedelta(days=2))
    assert len(folds) == comb(n, k)
    for fold in folds:
        assert set(fold.train).isdisjoint(fold.test)
        assert all(not (starts[i] <= ends[j] and starts[j] <= ends[i])
                   and not (ends[j] < starts[i] <= ends[j] + timedelta(days=2))
                   for i in fold.train for j in fold.test)
    with pytest.raises(OracleContractError):
        checked_splits(starts, ends, n_groups=n, n_test_groups=k,
                       embargo=timedelta(0))
    bad_ends = list(ends)
    bad_ends[0] = starts[-1] + timedelta(days=1)
    with pytest.raises(OracleContractError):
        checked_splits(starts, tuple(bad_ends), n_groups=n, n_test_groups=k,
                       embargo=timedelta(days=2))


def _oracle_input(n=160):
    starts, ends = _timeline(n)
    y = np.random.default_rng(18).normal(size=n)
    ids = ("candidate", "baseline")
    days = starts
    digest = sha256(np.ascontiguousarray(y, dtype="<f8").shape.__repr__().encode()
                    + np.ascontiguousarray(y, dtype="<f8").tobytes()
                    + repr((starts, ends, days, ids)).encode()).hexdigest()
    identity = FrozenIdentity("a" * 64, "b" * 64, digest, "c" * 64, "d" * 64)
    def refit(target, splits):
        # Synthetic stand-in refits on every target; no production estimator.
        stats = np.array([float(np.dot(target, y)), float(np.dot(target, -y))])
        returns = np.column_stack([y * 0.005 + 0.002, -y * 0.005 - 0.002])
        train = np.tile([2., 1.], (len(splits), 1))
        test = np.tile([2., 1.], (len(splits), 1))
        return RefitResult(stats, returns, train, test)
    return {"trial_ids": ids, "selected_trial_id": "candidate", "targets": y,
            "starts": starts, "ends": ends, "daily_dates": days,
            "holdout_start": starts[-1] + timedelta(days=2), "identity": identity,
            "observed_data_sha256": digest, "ledger_complete": True, "refit": refit,
            "blocks": tuple(tuple(range(i, i + 10)) for i in range(0, n, 10)),
            "n_groups": 5, "n_test_groups": 2, "embargo": timedelta(days=1),
            "seed": 9, "permutations": 39, "alpha": 0.5, "dsr_floor": 0.1,
            "pbo_ceiling": 0.05, "min_effect": 0.}


def test_refit_permutation_selected_vs_null_max_and_native_gates():
    inputs = _oracle_input()
    # Fail closed if native DSR deems sample insufficient; no surrogate score.
    try:
        result = evaluate_phase3(**inputs)
    except OracleContractError as exc:
        assert "native selected DSR" in str(exc)
    else:
        assert result.selected_p >= 1 / 40
        assert result.path_count == 4 and result.split_count == 10
        assert result.n_trials_raw == 2 and result.n_trials_effective >= 2
        assert result.holdout_access is False
    assert inputs["targets"].shape == (160,)


@pytest.mark.parametrize("change", [
    lambda a: a.update(ledger_complete=False),
    lambda a: a.update(identity=replace(a["identity"], data_sha256="f" * 64)),
    lambda a: a.update(identity=replace(a["identity"], code_sha256="")),
    lambda a: a.update(holdout_start=a["ends"][-1]),
    lambda a: a.update(blocks=((0, 1), (2, 3))),
    lambda a: a.update(trial_ids=("candidate", "candidate")),
])
def test_oracle_blocks_incomplete_or_mismatched_evidence(change):
    inputs = _oracle_input()
    change(inputs)
    with pytest.raises(OracleContractError):
        evaluate_phase3(**inputs)


def _snapshot(utc, *, balance=100_000., floating_pnl=0., midnight_balance=100_000.,
              existing=0., stress=0., gap=0., next_midnight=100_000.):
    midnight = utc.astimezone(ZoneInfo("Europe/Prague")).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return RiskSnapshot(utc, utc, midnight, 100_000., midnight_balance, balance,
                        floating_pnl, existing, stress, gap, 0., 0., next_midnight)


def _risk(snapshot, **changes):
    inputs = {"win_probability": 0.6, "reward_to_risk": 2., "probability_at": snapshot.now,
              "probability_sha256": "a" * 64, "calibrated": True,
              "loss_per_unit": 10., "notional_per_unit": 1_000., "max_notional": 20_000.}
    inputs.update(changes)
    return evaluate_risk(snapshot, **inputs)


def test_prague_midnight_unrealized_target_and_stress_reserve():
    before = datetime(2026, 3, 28, 22, 59, tzinfo=UTC)
    after = before + timedelta(minutes=2)
    assert _snapshot(before).midnight_at != _snapshot(after).midnight_at
    assert _risk(_snapshot(after, floating_pnl=-5_000.)).reason == "daily_floor"
    assert _risk(_snapshot(after, balance=95_000., floating_pnl=-5_000.,
                           midnight_balance=94_000.)).reason == "overall_floor"
    assert _risk(_snapshot(after, floating_pnl=10_000.)).reason == "TARGET_PROXIMITY_UNREALIZED"
    assert _risk(_snapshot(after, balance=110_000.)).reason == "TARGET_BALANCE_REVIEW_REQUIRED"
    assert _risk(_snapshot(after, balance=95_500., stress=500.)).reason == "existing_risk_exhausts_cushion"
    assert _risk(_snapshot(after, balance=95_500., gap=500.)).reason == "existing_risk_exhausts_cushion"
    assert _risk(_snapshot(after, balance=96_000., next_midnight=101_500.)).reason == "existing_risk_exhausts_cushion"


def test_taper_notional_stale_probability_and_bad_marks():
    now = datetime(2026, 10, 15, 11, tzinfo=UTC)
    full = _risk(_snapshot(now))
    near_floor = _risk(_snapshot(now, balance=95_500.))
    near_target = _risk(_snapshot(now, balance=109_500.))
    assert full.status == near_floor.status == near_target.status == "ALLOW_RESEARCH_ONLY"
    assert 0 < near_floor.proposed_risk_cash < full.proposed_risk_cash
    assert 0 < near_target.proposed_risk_cash < full.proposed_risk_cash
    assert full.max_notional <= 20_000.
    assert full.proposed_risk_cash <= full.max_notional * 10 / 1000
    assert _risk(_snapshot(now), calibrated=False).reason == "uncalibrated_or_stale_probability"
    assert _risk(_snapshot(now), probability_at=now - timedelta(days=31)).reason == "uncalibrated_or_stale_probability"
    assert _risk(replace(_snapshot(now), mark_time=now - timedelta(minutes=3))).reason == "stale_or_gap"
    with pytest.raises(ValueError):
        _risk(replace(_snapshot(now), floating_pnl=float("nan")))
