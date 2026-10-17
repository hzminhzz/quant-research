"""Native train/validation simulation and selection-aware economic checks."""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import polars as pl
from ml4t.diagnostic.evaluation.stats import (
    compute_return_statistics,
    deflated_sharpe_ratio,
    deflated_sharpe_ratio_from_statistics,
)
from scipy.stats import linregress

from src.engine.backtest_runner import NativeRun, run_native
from src.engine.signal_allocator import allocate
from src.engine.spec_parser import CandidateSpec


def scoped_dsr(candidate: pl.DataFrame, others: dict[str, pl.DataFrame], periods_per_year: int,
               *, historical_trial_count: int = 0) -> dict[str, Any]:
    """All trial returns must align; a period split is not a second strategy."""
    if not others:
        return {'status': 'INCONCLUSIVE', 'reason': 'A single series is PSR, not multiple-trial DSR'}
    dates = candidate['date'].to_list()
    arrays = [candidate['return'].to_numpy()]
    for name, frame in sorted(others.items()):
        if frame['date'].to_list() != dates:
            return {'status': 'INCONCLUSIVE', 'reason': f'Prior trial does not align with daily cohort: {name}'}
        arrays.append(frame['return'].to_numpy())
    matrix = np.column_stack(arrays)
    if not np.isfinite(matrix).all():
        return {'status': 'INCONCLUSIVE', 'reason': 'Nonfinite daily return evidence'}
    aligned_trials = matrix.shape[1]
    # Neither the current candidate nor its static-funding baseline counts as
    # historical trial evidence. Prior returns are hash-verified by _cohort.
    aligned_priors = len(others) - int('baseline' in others)
    raw_trials = max(aligned_trials, historical_trial_count + 1)
    if historical_trial_count < 10 or aligned_priors < 10:
        reason = ('Fewer than 10 prior attempts in global (market_scope, horizon) ledger'
                  if historical_trial_count < 10 else
                  'Fewer than 10 distinct historical trials with return-aligned evidence')
        return {'status': 'INCONCLUSIVE', 'reason': reason,
                'n_trials_raw': raw_trials, 'n_trials_prior': historical_trial_count,
                'n_trials_aligned': aligned_trials, 'n_trials_aligned_prior': aligned_priors,
                'n_trials_effective': None}
    try:
        cohort = deflated_sharpe_ratio(matrix, frequency='daily', periods_per_year=periods_per_year,
                                       correlation_method='effective_rank', min_k_eff=2.)
        sharpe, skew, pearson_kurtosis, autocorrelation, n = compute_return_statistics(arrays[0])
        # The matrix API selects its own best Sharpe. Evaluate the declared candidate
        # instead. Trials without aligned return artifacts cannot justify a
        # correlation discount: conservatively count them as independent.
        penalized_trials = max(float(cohort.n_trials_effective), float(raw_trials))
        selected = deflated_sharpe_ratio_from_statistics(
            observed_sharpe=sharpe, n_samples=n, n_trials=raw_trials,
            variance_trials=cohort.variance_trials, skewness=skew,
            excess_kurtosis=pearson_kurtosis - 3., autocorrelation=autocorrelation,
            frequency='daily', periods_per_year=periods_per_year,
            effective_trials=penalized_trials, min_k_eff=2.)
    except (ValueError, ZeroDivisionError, FloatingPointError, np.linalg.LinAlgError) as exc:
        return {'status': 'INCONCLUSIVE', 'reason': f'Native DSR cannot evaluate this cohort: {exc}'}
    if not math.isfinite(selected.probability):
        return {'status': 'INCONCLUSIVE', 'reason': 'Native DSR probability is not finite'}
    return {'status': 'COMPUTED', 'probability': float(selected.probability),
            'n_trials_raw': raw_trials, 'n_trials_prior': historical_trial_count,
            'n_trials_aligned': aligned_trials,
            'n_trials_aligned_prior': aligned_priors,
            'n_trials_effective': penalized_trials,
            'n_trials_effective_aligned_only': float(cohort.n_trials_effective),
            'has_adequate_sample': bool(selected.has_adequate_sample),
            'scope': 'declared selection family and recorded aligned returns; not all historical research',
            'candidate_native_sharpe': float(sharpe)}


def benchmark_beta(prices: pl.DataFrame, daily: pl.DataFrame, symbol: str) -> dict[str, Any]:
    source = prices.filter(pl.col('symbol') == symbol).sort('timestamp')
    if source.is_empty():
        return {'status': 'INCONCLUSIVE', 'reason': 'Benchmark source is missing'}
    initial = float(source['open'][0])
    benchmark = (source.with_columns(pl.col('timestamp').dt.date().alias('date'))
                 .group_by('date').agg(pl.col('close').last()).sort('date')
                 .with_columns((pl.col('close') / pl.col('close').shift(1).fill_null(initial) - 1).alias('benchmark_return')))
    joined = daily.select('date', 'return').join(benchmark.select('date', 'benchmark_return'), on='date', how='left')
    if joined['benchmark_return'].null_count() or joined.height < 3:
        return {'status': 'INCONCLUSIVE', 'reason': 'Benchmark and portfolio daily observations do not align'}
    try:
        fit = linregress(joined['benchmark_return'].to_numpy(), joined['return'].to_numpy())
    except ValueError as exc:
        return {'status': 'INCONCLUSIVE', 'reason': str(exc)}
    if not math.isfinite(fit.slope):
        return {'status': 'INCONCLUSIVE', 'reason': 'Benchmark variance is zero or beta is nonfinite'}
    return {'status': 'COMPUTED', 'beta': float(fit.slope), 'observations': joined.height,
            'method': 'OLS daily net portfolio returns on contemporaneous benchmark price returns'}


def evaluate_native_pair(runs: dict[str, NativeRun], prices: pl.DataFrame, spec: CandidateSpec,
                         *, prior_cohort: dict[str, pl.DataFrame] | None = None,
                         historical_trial_count: int = 0) -> dict[str, Any]:
    candidate, baseline = runs['candidate'], runs['baseline']
    dsr = scoped_dsr(candidate.daily, {'baseline': baseline.daily, **(prior_cohort or {})}, spec.periods_per_year,
                     historical_trial_count=historical_trial_count)
    beta = benchmark_beta(prices, candidate.daily, spec.benchmark)
    limitations = []
    if candidate.daily.height < spec.gates.minimum_daily_observations:
        limitations.append('too_few_daily_observations')
    if candidate.metrics['completed_trades'] < spec.gates.minimum_completed_trades:
        limitations.append('too_few_completed_trades')
    if dsr['status'] != 'COMPUTED':
        limitations.append('dsr_unavailable')
    elif not dsr['has_adequate_sample']:
        limitations.append('native_dsr_minimum_track_record_not_met')
    if beta['status'] != 'COMPUTED':
        limitations.append('benchmark_beta_unavailable')
    if candidate.metrics['short_stop_fraction'] is None:
        limitations.append('no_short_episodes')
    if candidate.metrics['daily_sharpe'] is None or baseline.metrics['daily_sharpe'] is None:
        limitations.append('sharpe_unavailable')
    checks = {}
    if not limitations:
        checks = {'dsr_probability': dsr['probability'] > spec.gates.dsr_probability,
                  'beta': abs(beta['beta']) <= spec.gates.maximum_abs_beta,
                  'short_squeeze_stops': candidate.metrics['short_stop_fraction'] <= spec.gates.maximum_short_stop_fraction,
                  'baseline_sharpe': (not spec.gates.require_baseline_sharpe_improvement or
                                      candidate.metrics['daily_sharpe'] > baseline.metrics['daily_sharpe'])}
    status = ('INCONCLUSIVE_STAGE_3' if limitations else 'PASS' if all(checks.values()) else 'FALSIFIED_STAGE_3')
    return {'status': status, 'checks': checks, 'dsr': dsr, 'beta': beta,
            'limitations': limitations, 'candidate': candidate.metrics, 'baseline': baseline.metrics}


def stage3(features: pl.DataFrame, spec: CandidateSpec, *, funding: pl.DataFrame,
           prior_cohort: dict[str, dict[str, pl.DataFrame]] | None = None,
           historical_trial_count: int = 0):
    """Train and validation run separately with frozen rules and train-history features."""
    reports, outputs = {}, {}
    prior_cohort = prior_cohort or {}
    if set(spec.prior_trial_ids) - set(prior_cohort):
        return {'status': 'INCONCLUSIVE_STAGE_3', 'reason': 'Declared prior-trial return evidence is missing'}, outputs
    for name, window in [('train', spec.windows.train), ('validation', spec.windows.validation)]:
        panel = features.filter((pl.col('timestamp') >= window.start) & (pl.col('timestamp') < window.end))
        if panel.is_empty():
            return {'status': 'BLOCKED_DATA', 'reason': f'{name} window has no panel observations'}, outputs
        events = (funding.filter((pl.col('timestamp') >= window.start) & (pl.col('timestamp') < window.end))
                  if funding.height else funding)
        arms = {}
        for arm, signal in [('candidate', spec.signal), ('baseline', spec.baseline)]:
            targets = allocate(panel, spec, signal=signal)
            arms[arm] = run_native(panel, targets, spec, funding=events)
            outputs[f'{name}_{arm}'] = arms[arm]
        prior = {}
        for trial_id, splits in prior_cohort.items():
            if name not in splits:
                return {'status': 'INCONCLUSIVE_STAGE_3', 'reason': f'Prior trial lacks {name}: {trial_id}'}, outputs
            prior[trial_id] = splits[name]
        reports[name] = evaluate_native_pair(arms, panel, spec, prior_cohort=prior,
                                             historical_trial_count=historical_trial_count)
    statuses = [report['status'] for report in reports.values()]
    status = ('FALSIFIED_STAGE_3' if 'FALSIFIED_STAGE_3' in statuses else
              'PASS' if all(s == 'PASS' for s in statuses) else 'INCONCLUSIVE_STAGE_3')
    return {'status': status, 'splits': reports,
            'split_accounting': 'Each frozen split starts flat with declared initial cash; no retuning'}, outputs
