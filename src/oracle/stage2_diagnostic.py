"""Native cross-sectional IC/HAC and a declared baseline null, before simulation."""
from __future__ import annotations

import math
from datetime import timedelta
from typing import Any

import polars as pl
from ml4t.diagnostic.api import compute_ic_hac_stats, cross_sectional_ic_series
from ml4t.engineer.labeling import fixed_time_horizon_labels

from src.engine.common import QuantError
from src.engine.spec_parser import CandidateSpec


def _json_stats(stats: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for key, value in stats.items():
        if hasattr(value, 'item'):
            value = value.item()
        out[key] = None if isinstance(value, float) and not math.isfinite(value) else value
    return out


def stage2(features: pl.DataFrame, spec: CandidateSpec) -> tuple[dict[str, Any], pl.DataFrame]:
    """Labels use next-open entry and future open exit, never enter the feature DAG.

    This endpoint is PRICE return. Funding cash transfers and stop-dependent
    execution are evaluated separately by the native Stage 3 engine.
    """
    horizon = spec.label_horizon_bars
    source = features.filter(pl.col('timestamp') < spec.windows.train.end).sort('symbol', 'timestamp').with_columns(
        pl.col('open').shift(-1).over('symbol').alias('__execution_open'),
        pl.col('timestamp').shift(-(horizon + 1)).over('symbol').alias('__label_end'))
    try:
        labeled = fixed_time_horizon_labels(source.filter(pl.col('__execution_open').is_not_null()),
                                            horizon=horizon, method='returns',
                                            price_col='__execution_open', timestamp_col='timestamp',
                                            group_col='symbol')
    except Exception as exc:
        raise QuantError('INVALID_DIAGNOSTIC', f'Native label computation failed: {exc}') from exc
    native_label = f'label_return_{horizon}p'
    if native_label not in labeled.columns:
        raise QuantError('INVALID_DIAGNOSTIC', 'Installed native fixed-horizon label schema differs')
    labeled = labeled.rename({native_label: 'label'})
    window = spec.windows.train
    candidates = labeled.filter((pl.col('timestamp') >= window.start)
                                 & (pl.col('timestamp') < window.end)
                                 & pl.col('in_pit_universe'))
    usable = candidates.filter((pl.col('__label_end') < window.end)
                                & ((pl.col('__label_end') - pl.col('timestamp')) ==
                                   timedelta(seconds=(horizon + 1) * spec.bar_seconds))
                                & pl.all_horizontal([pl.col(c).is_not_null() & pl.col(c).is_finite()
                                                     for c in ('label', spec.signal, spec.baseline)]))
    if usable.is_empty():
        return {'status': 'INCONCLUSIVE_STAGE_2', 'reason': 'No complete train-only forward labels',
                'eligible_rows': candidates.height, 'usable_rows': 0}, pl.DataFrame()
    series = []
    reports = {}
    for name in (spec.signal, spec.baseline):
        ic = cross_sectional_ic_series(usable.select('timestamp', 'symbol', name),
                                       usable.select('timestamp', 'symbol', 'label'),
                                       pred_col=name, ret_col='label', date_col='timestamp',
                                       entity_col='symbol', method='spearman',
                                       min_obs=spec.universe.minimum_assets)
        if 'ic' not in ic.columns:
            raise QuantError('INVALID_DIAGNOSTIC', 'Native IC schema differs from expected ic column')
        ic = ic.filter(pl.col('ic').is_not_null() & pl.col('ic').is_finite()).sort('timestamp')
        series.append(ic.select('timestamp', pl.col('ic').alias(name)))
        if ic.height < spec.gates.minimum_ic_observations:
            return {'status': 'INCONCLUSIVE_STAGE_2', 'reason': f'Too few finite IC observations: {name}',
                    'observations': ic.height, 'eligible_rows': candidates.height,
                    'usable_rows': usable.height}, ic
        try:
            reports[name] = _json_stats(compute_ic_hac_stats(ic, maxlags=horizon,
                                                            label_horizon=horizon,
                                                            allow_naive_fallback=False))
        except (ValueError, FloatingPointError, ZeroDivisionError) as exc:
            return {'status': 'INCONCLUSIVE_STAGE_2', 'reason': f'Native HAC unavailable: {exc}'}, ic
    paired = series[0].join(series[1], on='timestamp', how='inner').sort('timestamp')
    paired = paired.with_columns((pl.col(spec.signal) - pl.col(spec.baseline)).alias('incremental_ic'))
    candidate, baseline = reports[spec.signal], reports[spec.baseline]
    tstat, mean = candidate.get('t_stat'), candidate.get('mean_ic')
    base_mean = baseline.get('mean_ic')
    if any(v is None for v in (tstat, mean, base_mean)):
        return {'status': 'INCONCLUSIVE_STAGE_2', 'reason': 'Native HAC statistics are nonfinite',
                'diagnostics': reports}, paired
    conditions = {'candidate_mean_ic': mean >= spec.gates.minimum_ic,
                  'candidate_hac_t': tstat >= spec.gates.minimum_hac_t,
                  'baseline_increment': (not spec.gates.require_baseline_ic_improvement or mean > base_mean)}
    return {'status': 'PASS' if all(conditions.values()) else 'FALSIFIED_STAGE_2',
            'checks': conditions, 'diagnostics': reports,
            'label_endpoint': 'next-open forward price return; funding/stops tested in Stage 3',
            'hac_lags': horizon, 'eligible_rows': candidates.height, 'usable_rows': usable.height,
            'censored_or_unavailable_rows': candidates.height - usable.height,
            'observations': paired.height}, paired
