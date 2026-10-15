"""Synthetic checks for Stage 3 trial accounting and optional barrier sizing."""

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl

from src.engine.backtest_runner import TargetStrategy
from src.engine.common import append_trial
from src.engine.funnel import _cohort, _historical_trial_count
from src.oracle.stage3_falsifier import scoped_dsr
from src.portfolio.policy import barrier_leverage_scale
from tests.dual_mode_fixtures import test_spec as make_spec


def _returns(seed=1):
    rng = np.random.default_rng(seed)
    return pl.DataFrame({'date': [datetime(2025, 1, 1, tzinfo=UTC).date() + timedelta(days=i) for i in range(80)],
                         'return': rng.normal(0.0003, 0.01, 80)})


def test_single_winner_is_inconclusive_not_psr_as_dsr():
    result = scoped_dsr(_returns(), {}, 365)
    assert result['status'] == 'INCONCLUSIVE'
    assert 'single series' in result['reason']


def test_selection_dsr_requires_ten_aligned_returns_and_reports_rank_separately():
    candidate = _returns(0)
    nine = {f'trial-{i}': _returns(i + 1) for i in range(8)}
    insufficient = scoped_dsr(candidate, nine, 365)
    assert insufficient['status'] == 'INCONCLUSIVE'
    assert insufficient['n_trials_aligned'] == 9
    cohort = {f'trial-{i}': _returns(i + 1) for i in range(10)}
    insufficient_prior = scoped_dsr(candidate, cohort, 365, historical_trial_count=4)
    assert insufficient_prior['status'] == 'INCONCLUSIVE'
    assert '10 prior attempts' in insufficient_prior['reason']
    # Prior-count inflation cannot substitute for ten hash-verified and
    # date-aligned historical returns; the baseline is not a prior trial.
    misaligned_evidence = scoped_dsr(candidate, {'baseline': _returns(99), **dict(list(cohort.items())[:9])},
                                     365, historical_trial_count=50)
    assert misaligned_evidence['status'] == 'INCONCLUSIVE'
    assert misaligned_evidence['n_trials_aligned_prior'] == 9
    result = scoped_dsr(candidate, {'baseline': _returns(99), **cohort},
                        365, historical_trial_count=15)
    assert result['n_trials_aligned'] == 12
    assert result['n_trials_aligned_prior'] == 10
    assert result['n_trials_prior'] == 15
    assert result['n_trials_raw'] == 16
    assert result['n_trials_effective'] >= 16
    assert result['n_trials_effective_aligned_only'] <= result['n_trials_effective']


def test_ledger_counts_failures_but_cohort_ignores_other_scope_and_horizon(tmp_path):
    spec = make_spec().model_copy(update={'market_scope': 'crypto_perp'})
    for i, (scope, horizon, status) in enumerate([
        ('crypto_perp', 2, 'FALSIFIED_STAGE_3'), ('equity', 2, 'PASS'), ('crypto_perp', 8, 'PASS')
    ]):
        trial = tmp_path / f'{i}.parquet'
        _returns(i).write_parquet(trial)
        identity = {'attempt_id': str(i), 'candidate_id': f'old-{i}',
                    'selection_family_id': spec.selection_family_id,
                    'spec_hash': f'{i + 1:064x}', 'market_scope': scope,
                    'label_horizon_bars': horizon}
        append_trial(tmp_path, {**identity, 'event': 'stage3_started', 'status': 'RUNNING'})
        append_trial(tmp_path, {**identity, 'event': 'completed', 'status': status,
                                'daily_returns': {'train': {'path': trial.name,
                                                           'sha256': __import__('hashlib').sha256(trial.read_bytes()).hexdigest()}}})
    prior, unresolved = _cohort(tmp_path, spec)
    assert not unresolved
    assert list(prior) == [f'{1:064x}']
    assert _historical_trial_count(tmp_path, spec) == 1
    # Failed before Stage 3 still consumed a search attempt in the same market/horizon.
    append_trial(tmp_path, {'event': 'registered', 'attempt_id': 'early-fail',
                            'spec_hash': 'f' * 64, 'selection_family_id': 'other-family',
                            'market_scope': 'crypto_perp', 'label_horizon_bars': 2,
                            'status': 'FALSIFIED_STAGE_2'})
    assert _historical_trial_count(tmp_path, spec) == 2


def test_native_prop_anchor_is_prague_midnight_not_rebalance_cash():
    base = datetime(2025, 12, 20, 21, tzinfo=UTC)  # Prague 22:00
    moments = [base + timedelta(hours=i) for i in range(8)]
    spec = make_spec().model_copy(update={'barrier_overlay_enabled': True})
    empty_targets = pl.DataFrame(schema={
        'timestamp': pl.Datetime('us', 'UTC'), 'symbol': pl.String,
        'target_weight': pl.Float64, 'stop_loss_dist_pct': pl.Float64})
    strategy = TargetStrategy(empty_targets, spec, moments)

    class Broker:
        def __init__(self):
            self.value = 100_000.
            self.held = {}
        def get_positions(self):
            return self.held
        def equity(self):
            return self.value

    broker = Broker()
    strategy.on_data(moments[0], {}, {}, broker)
    assert strategy.barrier_midnight_balance is None
    # Prague midnight occurs at 23:00 UTC in December. The 22:00 UTC
    # bar closes at midnight and sets the anchor. Its replacement at 23:00
    # must NOT use the 23:00 bar's forward close (90k in this test).
    strategy.on_data(moments[1], {}, {}, broker)
    broker.value = 90_000.
    strategy.on_data(moments[2], {}, {}, broker)
    assert strategy.barrier_midnight_balance == 100_000.
    broker.value = 130_000.
    strategy.on_data(moments[3], {}, {}, broker)
    assert strategy.barrier_midnight_balance == 100_000.
    # The next day's first bar cannot substitute for a missed midnight mark.
    strategy.barrier_midnight_balance = None
    strategy.on_data(moments[4], {}, {}, broker)
    assert strategy.barrier_midnight_balance is None


def test_barrier_overlay_scales_at_floors_target_and_missing_marks():
    def scale(equity, midnight=100_000., marks=True):
        return barrier_leverage_scale(equity=equity, initial_balance=100_000.,
                                      midnight_balance=midnight, marks_available=marks)
    assert scale(100_000.) == 1.0
    assert 0 < scale(96_000.) < 1
    assert scale(95_000.) == 0.0
    assert 0 < scale(109_000.) < 1
    assert scale(110_000.) == 0.0
    assert scale(100_000., marks=False) == 0.0
    assert make_spec().barrier_overlay_enabled is False
