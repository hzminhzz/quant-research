"""Mechanical per-class sleeve gates, including a class-scoped DSR.

Sharpe, drawdown and the forecast-return HAC check are computed from one class's
net returns and one class's panel. DSR is computed over that class's *aligned*
trial-return matrix -- one row per common date, one column per trial -- so a
failed or abandoned trial that still has returns counts, and no cross-class
return series is ever mixed.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import polars as pl
from ml4t.diagnostic.evaluation.stats import deflated_sharpe_ratio
from ml4t.diagnostic.metrics import sharpe_ratio

from .common import QuantError
from .ts_spec import MarketClass, TimeSeriesSpec

GATE_NAMES = ('train_positive', 'validation_sharpe', 'validation_to_train',
              'cost_stress', 'validation_drawdown', 'forecast_hac', 'class_dsr')


def net_sharpe(returns: pl.Series | np.ndarray, periods_per_year: int) -> float | None:
    values = np.asarray(returns, dtype=float).ravel()
    if values.size < 3 or not np.isfinite(values).all():
        return None
    raw = sharpe_ratio(values, periods_per_year=periods_per_year)
    if isinstance(raw, dict):
        raw = raw.get('sharpe_ratio')
    if raw is None:
        return None
    value = float(raw)
    return value if math.isfinite(value) else None


def max_drawdown(returns: pl.Series | np.ndarray) -> float | None:
    values = np.asarray(returns, dtype=float).ravel()
    if values.size < 2 or not np.isfinite(values).all():
        return None
    equity = np.cumprod(1.0 + values)
    peak = np.maximum.accumulate(equity)
    return float(np.max(1.0 - equity / peak))


def forecast_return_hac(panel: pl.DataFrame, spec: TimeSeriesSpec) -> dict[str, Any]:
    """Within-symbol rank association between forecast and forward returns.

    Entry is the next bar's open and exit is the open after `label_horizon_bars`,
    matching the v1 stage-2 label endpoint. Newey-West (Bartlett) standard errors
    use lags equal to the label horizon.
    """
    horizon = spec.label_horizon_bars
    required = {'timestamp', 'symbol', 'open', 'forecast', 'in_pit_universe'}
    missing = required - set(panel.columns)
    if missing:
        raise QuantError('INVALID_DIAGNOSTIC', f'Forecast check is missing columns: {sorted(missing)}')
    frame = (panel.filter(pl.col('in_pit_universe'))
             .sort('symbol', 'timestamp')
             .with_columns(pl.col('open').shift(-1).over('symbol').alias('__entry'),
                           pl.col('open').shift(-(horizon + 1)).over('symbol').alias('__exit')))
    frame = frame.with_columns((pl.col('__exit') / pl.col('__entry') - 1).alias('__forward'))
    usable = frame.filter(
        pl.col('__forward').is_not_null() & pl.col('__forward').is_finite()
        & pl.col('forecast').is_not_null() & pl.col('forecast').is_finite()
    )
    if usable.height < 30:
        return {'status': 'INCONCLUSIVE', 'reason': 'Too few forecast/return observations',
                'observations': usable.height, 'lags': horizon}
    usable = usable.with_columns(
        pl.col('forecast').rank('average').over('symbol').alias('__fx'),
        pl.col('__forward').rank('average').over('symbol').alias('__fy'))
    x = usable['__fx'].to_numpy().astype(float)
    y = usable['__fy'].to_numpy().astype(float)
    if x.std() == 0 or y.std() == 0:
        return {'status': 'INCONCLUSIVE', 'reason': 'Degenerate forecast or return ranks',
                'observations': usable.height, 'lags': horizon}
    rho = float(np.corrcoef(x, y)[0, 1])
    t_stat = _hac_slope_t(x, y, lags=horizon)
    return {'status': 'PASS', 'spearman': rho, 't_stat': t_stat,
            'observations': int(usable.height), 'lags': horizon,
            'method': 'within-symbol ranks; OLS slope with Bartlett Newey-West errors'}


def _hac_slope_t(x: np.ndarray, y: np.ndarray, *, lags: int) -> float | None:
    x = x - x.mean()
    y = y - y.mean()
    design = np.column_stack([np.ones_like(x), x])
    beta, *_ = np.linalg.lstsq(design, y, rcond=None)
    residual = y - design @ beta
    scores = design * residual[:, None]
    omega = scores.T @ scores
    for lag in range(1, min(lags, len(x) - 1) + 1):
        weight = 1.0 - lag / (lags + 1)
        gamma = scores[lag:].T @ scores[:-lag]
        omega += weight * (gamma + gamma.T)
    try:
        xtx_inv = np.linalg.inv(design.T @ design)
    except np.linalg.LinAlgError:
        return None
    variance = float((xtx_inv @ omega @ xtx_inv)[1, 1])
    if not math.isfinite(variance) or variance <= 0:
        return None
    value = float(beta[1] / math.sqrt(variance))
    return value if math.isfinite(value) else None


def class_dsr(trial_returns: pl.DataFrame, periods_per_year: int,
              *, confidence: float = 0.95) -> dict[str, Any]:
    """DSR for one asset class over its aligned trial-return matrix."""
    if 'timestamp' not in trial_returns.columns:
        raise QuantError('INVALID_DIAGNOSTIC', 'DSR input requires a timestamp column')
    trials = [name for name in trial_returns.columns if name != 'timestamp']
    if not trials:
        raise QuantError('INVALID_DIAGNOSTIC', 'DSR input requires at least one trial return column')
    if trial_returns.height < 3:
        raise QuantError('INVALID_DIAGNOSTIC', 'DSR input requires at least three aligned rows')
    if trial_returns['timestamp'].n_unique() != trial_returns.height:
        raise QuantError('INVALID_DIAGNOSTIC', 'DSR trial returns must share one aligned date axis')
    matrix = trial_returns.select(trials).to_numpy().astype(float)
    if not np.isfinite(matrix).all():
        raise QuantError('INVALID_DIAGNOSTIC',
                         'DSR trial returns contain null or nonfinite values; align or exclude the trial')
    variances = matrix.std(axis=0)
    excluded = [trials[i] for i, value in enumerate(variances)
                if not np.isfinite(value) or value <= 0]
    kept = [name for name in trials if name not in excluded]
    if not kept:
        raise QuantError('INVALID_DIAGNOSTIC', 'Every trial in the DSR matrix has zero variance')
    try:
        result = deflated_sharpe_ratio(trial_returns.select(kept).to_numpy().astype(float),
                                       frequency='daily',
                                       periods_per_year=periods_per_year,
                                       confidence_level=confidence)
    except ValueError as exc:
        raise QuantError('INVALID_DIAGNOSTIC', f'DSR unavailable: {exc}') from exc
    return {'probability': float(result.probability), 'trials': int(result.n_trials),
            'observations': int(result.n_samples),
            'leader_sharpe_annualized': float(result.sharpe_ratio_annualized),
            'confidence': confidence,
            'trials_declared': kept,
            'excluded_zero_variance': excluded}


def gate_checks(spec: TimeSeriesSpec, *, train_sharpe: float | None,
                validation_sharpe: float | None, stress_sharpe: float | None,
                validation_drawdown: float | None, forecast_t: float | None,
                dsr_probability: float | None) -> dict[str, Any]:
    """Seven pure threshold checks; None means the statistic was unavailable."""
    gates = spec.gates
    checks = {
        'train_positive': {
            'value': train_sharpe, 'threshold': 0.0,
            'passed': train_sharpe is not None and train_sharpe > 0.0,
        },
        'validation_sharpe': {
            'value': validation_sharpe, 'threshold': gates.minimum_validation_net_sharpe,
            'passed': (validation_sharpe is not None
                       and validation_sharpe >= gates.minimum_validation_net_sharpe),
        },
        'validation_to_train': {
            'value': (validation_sharpe / train_sharpe
                      if validation_sharpe is not None and train_sharpe not in (None, 0) else None),
            'threshold': gates.minimum_validation_to_train_ratio,
            'passed': (train_sharpe is not None and validation_sharpe is not None
                       and train_sharpe > 0
                       and validation_sharpe >= gates.minimum_validation_to_train_ratio * train_sharpe),
        },
        'cost_stress': {
            'value': stress_sharpe, 'threshold': 0.0,
            'passed': stress_sharpe is not None and stress_sharpe > 0.0,
            'multiple': gates.cost_stress_multiple,
        },
        'validation_drawdown': {
            'value': validation_drawdown, 'threshold': gates.maximum_validation_drawdown,
            'passed': (validation_drawdown is not None
                       and validation_drawdown <= gates.maximum_validation_drawdown),
        },
        'forecast_hac': {
            'value': forecast_t, 'threshold': gates.minimum_forecast_return_t,
            'passed': forecast_t is not None and forecast_t >= gates.minimum_forecast_return_t,
        },
        'class_dsr': {
            'value': dsr_probability, 'threshold': gates.dsr_probability,
            'passed': dsr_probability is not None and dsr_probability >= gates.dsr_probability,
        },
    }
    return {'status': 'QUALIFIED' if all(c['passed'] for c in checks.values()) else 'FALSIFIED',
            'checks': checks, 'missing': [name for name, c in checks.items() if c['value'] is None]}


def evaluate_class(spec: TimeSeriesSpec, market_class: MarketClass, *,
                   train_returns: pl.Series | np.ndarray,
                   validation_returns: pl.Series | np.ndarray,
                   stress_returns: pl.Series | np.ndarray,
                   forecast_check: dict[str, Any],
                   class_dsr_result: dict[str, Any]) -> dict[str, Any]:
    """Compose the metric computation and the seven checks for one class."""
    periods = market_class.periods_per_year
    report = gate_checks(
        spec,
        train_sharpe=net_sharpe(train_returns, periods),
        validation_sharpe=net_sharpe(validation_returns, periods),
        stress_sharpe=net_sharpe(stress_returns, periods),
        validation_drawdown=max_drawdown(validation_returns),
        forecast_t=forecast_check.get('t_stat'),
        dsr_probability=class_dsr_result.get('probability'),
    )
    report['market_class'] = market_class.name
    report['periods_per_year'] = periods
    report['forecast_method'] = forecast_check.get('method')
    report['forecast_observations'] = forecast_check.get('observations')
    report['dsr'] = class_dsr_result
    if forecast_check.get('status') == 'INCONCLUSIVE' and report['status'] == 'FALSIFIED':
        report['status'] = 'INCONCLUSIVE'
        report['reason'] = forecast_check.get('reason')
    return report
