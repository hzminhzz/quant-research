"""Non-gating profit-concentration diagnostics for AF30 sleeve and portfolio runs.

This module is deliberately explanatory. It never changes a sleeve disposition,
the seven qualification gates, the trial ledger, the selection family, weights or
the frozen portfolio rule. It answers three separate questions with explicit
definitions:

* What did each UTC calendar month contribute to the compounded net return?
* How much of realised profit is concentrated in the best one/two months?
* What happens to Sharpe, drawdown and compounded return if the richest month is
  set flat on the *same* calendar (an explanatory sensitivity, not an executable
  counterfactual)?

Instrument attribution is reconstructed from native fills, funding cashflows and
causal end-of-day marks, then reconciled to native daily equity. If the inputs do
not support that reconstruction the diagnostic says so; it never splits a
headline return arbitrarily.
"""
from __future__ import annotations

import io
import math
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from .common import QuantError, digest, file_hash, write_json
from .ts_gates import max_drawdown, net_sharpe

SCHEMA_VERSION = 1
KIND = 'profit_concentration'
SCOPES = {'sleeve', 'portfolio'}
STATUSES = {'AVAILABLE', 'UNAVAILABLE', 'INCONCLUSIVE', 'BLOCKED'}
INTERPRETATION = 'EXPLANATORY_ONLY_NOT_AN_EXECUTABLE_COUNTERFACTUAL'
NET_SHARE_STATUSES = {'AVAILABLE', 'NON_POSITIVE_NET_PROFIT', 'ZERO_NET_PROFIT',
                      'OFFSET_BY_LOSSES'}

DEFINITIONS = {
    'calendar_month': (
        'UTC calendar month of the daily net-return date, restricted to the '
        'development window already supplied to the run; no protected row is read.'
    ),
    'monthly_net_return': 'prod(1 + daily net return) - 1 inside the UTC calendar month.',
    'monthly_net_pnl': (
        'Last native daily equity in the month minus the prior month-end native '
        'equity (or declared initial cash for the first month), in account currency.'
    ),
    'profit_concentration_primary': (
        'Sum of the k largest positive monthly net returns divided by the sum of '
        'all positive monthly net returns. Bounded in [0, 1] whenever at least one '
        'positive month exists.'
    ),
    'profit_concentration_primary_pnl': (
        'The same top-k / gross-positive-month denominator using monthly account-'
        'currency net PnL instead of net return.'
    ),
    'profit_concentration_net': (
        'Top-k positive monthly return divided by the arithmetic sum of all monthly '
        'net returns. Reported only when the denominator is positive and top-k does '
        'not exceed it; otherwise null with a named denominator status.'
    ),
    'net_share_denominator_guard': (
        'A net-denominated share is not reported for zero/negative net PnL or when '
        'offsetting losses make the top-k sum exceed the net denominator. This avoids '
        'a ratio above one or a sign-flipped "share".'
    ),
    'richest_month_ablation': (
        'Every daily net return in the richest calendar month is set to exactly 0.0. '
        'The date axis, observation count, annualisation and all other months are '
        'unchanged. No trade, weight or price is re-simulated.'
    ),
    'instrument_attribution': (
        'Daily per-symbol net PnL = prior-quantity mark-to-market + signed-fill '
        'execution PnL - explicit commission + funding cashflow, marked at the last '
        'causal close on or before the date. The execution price already contains '
        'declared slippage, so slippage is not charged twice.'
    ),
    'interpretation': (
        'Explanatory only. The ablation is a sensitivity of the realised return '
        'series, not an executable counterfactual and not a new trial.'
    ),
}


def _hex64(value: Any, name: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(
            char not in '0123456789abcdef' for char in value):
        raise QuantError('INVALID_EVIDENCE', f'{name} must be a lowercase sha256 hex digest')


def _require_columns(frame: pl.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise QuantError('INVALID_EVIDENCE', f'{label} is missing columns: {missing}')


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise QuantError('INVALID_EVIDENCE', f'{name} must be finite numeric data')
    return float(value)


def _frame_sha256(frame: pl.DataFrame | None, *, sort_by: list[str] | None = None) -> str:
    """Content hash of an in-memory frame, used as explicit source evidence."""
    if frame is None:
        raise QuantError('INVALID_EVIDENCE', 'Cannot hash an absent source frame')
    # Empty typed native frames can legitimately omit an identity column; their
    # content hash is still deterministic and is not evidence of a position.
    ordered = frame.sort(sort_by) if sort_by and frame.height else frame
    sink = io.BytesIO()
    ordered.write_ipc(sink)
    import hashlib
    return hashlib.sha256(sink.getvalue()).hexdigest()


def _prepare_daily(daily: pl.DataFrame, *, require_equity: bool) -> pl.DataFrame:
    if not isinstance(daily, pl.DataFrame) or daily.is_empty():
        raise QuantError('INCONCLUSIVE', 'Profit diagnostics need at least one daily observation')
    required = {'date', 'return'} | ({'equity'} if require_equity else set())
    _require_columns(daily, required, 'Daily returns')
    frame = daily.select('date', 'return', *(['equity'] if 'equity' in daily.columns else []))
    frame = frame.with_columns(pl.col('date').cast(pl.Date)).sort('date')
    if frame['date'].n_unique() != frame.height:
        raise QuantError('INVALID_EVIDENCE', 'Daily returns must have one row per date')
    if frame['return'].null_count():
        raise QuantError('INVALID_EVIDENCE', 'Daily returns contain null values')
    invalid = frame.filter(pl.col('return').is_finite().not_()
                           | (pl.col('return') <= -1.0)
                           | pl.col('date').is_null())
    if invalid.height:
        raise QuantError('INVALID_EVIDENCE', 'Daily returns must be finite and greater than -1')
    if 'equity' in frame.columns and (frame['equity'].null_count() or frame.filter(
            pl.col('equity').is_finite().not_() | (pl.col('equity') < 0)).height):
        raise QuantError('INVALID_EVIDENCE', 'Daily equity must be finite and non-negative')
    return frame


def _month_rows(daily: pl.DataFrame, *, initial_cash: float | None) -> list[dict[str, Any]]:
    frame = daily.with_columns(pl.col('date').dt.strftime('%Y-%m').alias('month'))
    aggregations = [
        pl.len().alias('observations'),
        ((pl.col('return') + 1.0).product() - 1.0).alias('net_return'),
        pl.col('return').sum().alias('sum_daily_returns'),
        pl.col('date').min().alias('first_date'),
        pl.col('date').max().alias('last_date'),
    ]
    if 'equity' in frame.columns:
        aggregations.append(pl.col('equity').last().alias('equity_end'))
    grouped = frame.group_by('month').agg(aggregations).sort('month')
    if 'equity_end' in grouped.columns:
        if initial_cash is None:
            raise QuantError('INVALID_EVIDENCE',
                             'Monthly net PnL requires the declared initial cash')
        grouped = (grouped.with_columns(
            pl.col('equity_end').shift(1).fill_null(float(initial_cash)).alias('equity_start'))
            .with_columns((pl.col('equity_end') - pl.col('equity_start')).alias('net_pnl')))
    rows = []
    for row in grouped.iter_rows(named=True):
        item = {
            'month': row['month'],
            'first_date': row['first_date'].isoformat(),
            'last_date': row['last_date'].isoformat(),
            'observations': int(row['observations']),
            'net_return': float(row['net_return']),
            'sum_daily_returns': float(row['sum_daily_returns']),
        }
        if 'equity_end' in grouped.columns:
            item['equity_start'] = float(row['equity_start'])
            item['equity_end'] = float(row['equity_end'])
            item['net_pnl'] = float(row['net_pnl'])
        rows.append(item)
    return rows


def _metrics(returns: pl.Series | np.ndarray, periods_per_year: int) -> dict[str, Any]:
    values = np.asarray(returns, dtype=float).ravel()
    if values.size == 0 or not np.isfinite(values).all():
        return {'sharpe': None, 'max_drawdown': None, 'compounded_return': None}
    if np.any(values <= -1.0):
        return {'sharpe': None, 'max_drawdown': None, 'compounded_return': None}
    compounded = float(np.prod(1.0 + values) - 1.0)
    return {
        'sharpe': net_sharpe(values, periods_per_year),
        'max_drawdown': max_drawdown(values),
        'compounded_return': compounded if math.isfinite(compounded) else None,
    }


def _share(top: float, denominator: float) -> float:
    value = top / denominator
    return float(min(1.0, max(0.0, value)))


def _net_share(top: float, net: float) -> tuple[float | None, str]:
    tolerance = 1e-12 * max(1.0, abs(net))
    if net > tolerance:
        if top <= net + tolerance:
            return float(top / net), 'AVAILABLE'
        return None, 'OFFSET_BY_LOSSES'
    if abs(net) <= tolerance:
        return None, 'ZERO_NET_PROFIT'
    return None, 'NON_POSITIVE_NET_PROFIT'


def _top_block(positive: list[dict[str, Any]], k: int, key: str,
               net_total: float) -> dict[str, Any]:
    selected = positive[:min(k, len(positive))]
    combined = float(sum(item[key] for item in selected))
    net_share, net_status = _net_share(combined, net_total)
    return {
        'requested_k': k,
        'effective_k': len(selected),
        'months': [item['month'] for item in selected],
        'combined': combined,
        'share_of_gross_positive': _share(combined, sum(item[key] for item in positive))
        if positive else None,
        'share_of_net': net_share,
        'net_share_status': net_status,
    }


def _concentration(months: list[dict[str, Any]], key: str) -> dict[str, Any]:
    positive = [item for item in months if item.get(key) is not None and item[key] > 0.0]
    positive.sort(key=lambda item: (-float(item[key]), item['month']))
    net_total = float(sum(float(item[key]) for item in months if item.get(key) is not None))
    gross_positive = float(sum(float(item[key]) for item in positive))
    status = 'AVAILABLE' if positive else 'UNAVAILABLE'
    output: dict[str, Any] = {
        'status': status,
        'measure': key,
        'definition': (DEFINITIONS['profit_concentration_primary'] if key == 'net_return'
                       else DEFINITIONS['profit_concentration_primary_pnl']),
        'gross_positive': gross_positive,
        'net_total': net_total,
        'net_denominator_status': _net_share(0.0, net_total)[1],
        'top_1': _top_block(positive, 1, key, net_total),
        'top_2': _top_block(positive, 2, key, net_total),
    }
    if not positive:
        output['reason'] = 'No positive monthly net return; profit concentration is undefined'
    return output


def _ablation(daily: pl.DataFrame, month: str, periods_per_year: int,
              before: dict[str, Any]) -> dict[str, Any]:
    frame = daily.with_columns(pl.col('date').dt.strftime('%Y-%m').alias('__month'))
    ablated = frame.with_columns(
        pl.when(pl.col('__month') == month).then(0.0).otherwise(pl.col('return'))
        .alias('return')).drop('__month')
    removed = int(frame.filter(pl.col('__month') == month).height)
    after = _metrics(ablated['return'], periods_per_year)
    delta = {}
    for name in ('sharpe', 'max_drawdown', 'compounded_return'):
        delta[name] = (None if before[name] is None or after[name] is None
                       else float(after[name] - before[name]))
    return {
        'status': 'AVAILABLE',
        'excluded_months': [month],
        'treatment': DEFINITIONS['richest_month_ablation'],
        'observations_ablated': removed,
        'same_calendar': True,
        'before': before,
        'after': after,
        'delta': delta,
        'interpretation': INTERPRETATION,
    }


def _richest_months(months: list[dict[str, Any]], count: int) -> list[str]:
    positive = [item for item in months if item['net_return'] > 0.0]
    positive.sort(key=lambda item: (-item['net_return'], item['month']))
    return [item['month'] for item in positive[:count]]


def _select_timestamp(frame: pl.DataFrame) -> pl.DataFrame:
    required = {'timestamp', 'symbol'}
    _require_columns(frame, required, 'Attribution input')
    dtype = frame.schema['timestamp']
    if not (isinstance(dtype, pl.Datetime) or dtype == pl.Date):
        raise QuantError('INVALID_EVIDENCE', 'Attribution timestamps must be temporal')
    return frame.with_columns(pl.col('timestamp').dt.date().alias('date'))


def attribute_instrument_pnl(*, panel: pl.DataFrame, fills: pl.DataFrame,
                             funding: pl.DataFrame | None, daily: pl.DataFrame,
                             initial_cash: float) -> dict[str, Any]:
    """Reconstruct per-symbol daily net PnL and reconcile it to native equity.

    The function is strict on purpose: a missing mark for an open position, a
    nonfinite fill/funding value, a duplicate daily mark or any unexplained equity
    difference is an evidence error, never a silently dropped instrument.
    """
    cash = _finite(initial_cash, 'initial_cash')
    if cash <= 0:
        raise QuantError('INVALID_EVIDENCE', 'initial_cash must be positive')
    daily_frame = _prepare_daily(daily, require_equity=True)
    if panel is None or panel.is_empty():
        raise QuantError('UNAVAILABLE', 'Instrument attribution requires a mark panel')
    _require_columns(panel, {'timestamp', 'symbol', 'close'}, 'Attribution panel')
    if panel.filter(pl.col('close').is_null() | pl.col('close').is_finite().not_()
                    | (pl.col('close') <= 0)).height:
        raise QuantError('INVALID_EVIDENCE', 'Attribution panel has an invalid close mark')

    marks = (_select_timestamp(panel.select('timestamp', 'symbol', 'close'))
             .sort('symbol', 'timestamp')
             .group_by('date', 'symbol')
             .agg(pl.col('close').sort_by(pl.col('timestamp')).last().alias('close'),
                  pl.col('timestamp').max().alias('mark_at'))
             .sort('symbol', 'date'))
    if marks.select(pl.struct('date', 'symbol').n_unique()).item() != marks.height:
        raise QuantError('INVALID_EVIDENCE', 'Attribution marks must be unique per date/symbol')

    fills_frame = fills if fills is not None else pl.DataFrame()
    if fills_frame.height:
        _require_columns(fills_frame, {'timestamp', 'side', 'quantity', 'price', 'commission'},
                         'Native fills')
        symbol_column = 'asset' if 'asset' in fills_frame.columns else 'symbol'
        if symbol_column not in fills_frame.columns:
            raise QuantError('INVALID_EVIDENCE', 'Native fills need an asset or symbol column')
        fills_frame = fills_frame.with_columns(pl.col(symbol_column).alias('symbol'))
        sides = {str(value).lower() for value in fills_frame['side'].unique().to_list()}
        if not sides <= {'buy', 'sell'}:
            raise QuantError('INVALID_EVIDENCE', f'Unknown native fill sides: {sorted(sides)}')
        if fills_frame.filter(pl.col('timestamp').is_null()
                              | pl.col('quantity').is_null()
                              | pl.col('price').is_null()
                              | pl.col('commission').is_null()
                              | (pl.col('quantity') <= 0)
                              | (pl.col('price') <= 0)
                              | (pl.col('commission') < 0)
                              | pl.col('quantity').is_finite().not_()
                              | pl.col('price').is_finite().not_()
                              | pl.col('commission').is_finite().not_()).height:
            raise QuantError('INVALID_EVIDENCE',
                             'Native fills contain negative, zero or nonfinite values')
        dtype = fills_frame.schema['timestamp']
        if not (isinstance(dtype, pl.Datetime) or dtype == pl.Date):
            raise QuantError('INVALID_EVIDENCE', 'Native fill timestamps must be temporal')
        signed = (pl.when(pl.col('side').str.to_lowercase() == 'buy').then(1.0)
                  .otherwise(-1.0) * pl.col('quantity'))
        has_slippage = 'slippage' in fills_frame.columns
        fill_daily = (fills_frame.with_columns(
            pl.col('timestamp').dt.date().alias('date'),
            signed.alias('quantity_delta'),
            (signed * pl.col('price')).alias('signed_notional'))
            .group_by('date', 'symbol')
            .agg(pl.col('quantity_delta').sum(),
                 pl.col('signed_notional').sum(),
                 pl.col('commission').sum(),
                 (pl.col('quantity') * pl.col('price')).sum().alias('gross_notional'),
                 pl.len().alias('trade_count'),
                 ((pl.col('slippage').abs() > 0).sum() if has_slippage else pl.lit(0))
                 .alias('slippage_events')))
    else:
        fill_daily = pl.DataFrame(schema={
            'date': pl.Date, 'symbol': pl.String, 'quantity_delta': pl.Float64,
            'signed_notional': pl.Float64, 'commission': pl.Float64,
            'gross_notional': pl.Float64, 'trade_count': pl.Int64,
            'slippage_events': pl.Int64})

    funding_frame = funding if funding is not None else pl.DataFrame()
    if funding_frame.height:
        _require_columns(funding_frame, {'timestamp', 'symbol', 'cashflow'}, 'Funding')
        dtype = funding_frame.schema['timestamp']
        if not (isinstance(dtype, pl.Datetime) or dtype == pl.Date):
            raise QuantError('INVALID_EVIDENCE', 'Funding timestamps must be temporal')
        if funding_frame.filter(pl.col('cashflow').is_null()
                                | pl.col('cashflow').is_finite().not_()).height:
            raise QuantError('INVALID_EVIDENCE', 'Funding contains null or nonfinite cashflow')
        funding_daily = (funding_frame.with_columns(
            pl.col('timestamp').dt.date().alias('date'))
            .group_by('date', 'symbol').agg(pl.col('cashflow').sum().alias('funding'))
            .sort('symbol', 'date'))
    else:
        funding_daily = pl.DataFrame(schema={
            'date': pl.Date, 'symbol': pl.String, 'funding': pl.Float64})

    symbols = sorted(set(fill_daily['symbol'].to_list()) | set(funding_daily['symbol'].to_list()))
    dates = daily_frame.select('date').sort('date')
    if symbols:
        grid = dates.join(pl.DataFrame({'symbol': symbols}), how='cross')
        grid = (grid.sort('symbol', 'date')
                .join(fill_daily, on=['date', 'symbol'], how='left')
                .with_columns(
                    pl.col('quantity_delta').fill_null(0.0),
                    pl.col('signed_notional').fill_null(0.0),
                    pl.col('commission').fill_null(0.0),
                    pl.col('gross_notional').fill_null(0.0),
                    pl.col('trade_count').fill_null(0),
                    pl.col('slippage_events').fill_null(0))
                .with_columns(
                    pl.col('quantity_delta').cum_sum().over('symbol').alias('quantity_end'))
                .with_columns(
                    pl.col('quantity_end').shift(1).over('symbol').fill_null(0.0)
                    .alias('quantity_start')))
        grid = grid.sort('symbol', 'date').join_asof(
            marks.select('date', 'symbol', 'close', 'mark_at').sort('symbol', 'date'),
            on='date', by='symbol', strategy='backward', check_sortedness=False)
        grid = (grid.with_columns(
            pl.col('close').shift(1).over('symbol').alias('mark_prev'))
            .with_columns(
                pl.when(pl.col('quantity_start') == 0.0).then(0.0)
                .otherwise(pl.col('quantity_start') * (pl.col('close') - pl.col('mark_prev')))
                .alias('mark_carry_pnl'),
                (pl.col('close') * pl.col('quantity_delta') - pl.col('signed_notional'))
                .alias('execution_pnl'))
            .join(funding_daily, on=['date', 'symbol'], how='left')
            .with_columns(pl.col('funding').fill_null(0.0))
            .with_columns(
                (pl.col('mark_carry_pnl') + pl.col('execution_pnl')
                 - pl.col('commission') + pl.col('funding')).alias('net_pnl')))
        # A mark is required for any position or fill on the date. A previously
        # flat symbol may legitimately have no earlier mark.
        needs_mark = ((pl.col('quantity_start') != 0.0) | (pl.col('quantity_end') != 0.0)
                      | (pl.col('quantity_delta') != 0.0))
        if grid.filter(needs_mark & pl.col('close').is_null()).height:
            raise QuantError('INVALID_ACCOUNTING', 'No causal end-of-day mark for an open position')
        if grid.filter((pl.col('quantity_start') != 0.0) & pl.col('mark_prev').is_null()).height:
            raise QuantError('INVALID_ACCOUNTING', 'No prior causal mark for an open position')
        if grid.filter((pl.col('funding') != 0.0) & (pl.col('quantity_start') == 0.0)
                       & (pl.col('quantity_end') == 0.0)).height:
            raise QuantError('INVALID_ACCOUNTING',
                             'Funding cashflow has no tracked position in the attribution window')
        if grid.filter(pl.col('net_pnl').is_null() | pl.col('net_pnl').is_finite().not_()).height:
            raise QuantError('INVALID_ACCOUNTING', 'Instrument attribution produced nonfinite PnL')
        grid = (grid.with_columns(
            (pl.col('date') - pl.col('mark_at').dt.date()).dt.total_days().alias('mark_staleness_days'))
            .select('date', 'symbol', 'quantity_start', 'quantity_end', 'close', 'mark_at',
                    'mark_staleness_days', 'quantity_delta', 'signed_notional',
                    'mark_carry_pnl', 'execution_pnl', 'commission', 'funding', 'net_pnl',
                    'trade_count', 'slippage_events'))
        per_day = (grid.group_by('date').agg(
            pl.col('net_pnl').sum().alias('attributed_pnl'),
            pl.col('mark_staleness_days').max().alias('max_mark_staleness_days'))
            .sort('date'))
    else:
        grid = pl.DataFrame(schema={
            'date': pl.Date, 'symbol': pl.String, 'quantity_start': pl.Float64,
            'quantity_end': pl.Float64, 'close': pl.Float64, 'mark_at': pl.Datetime,
            'mark_staleness_days': pl.Int64, 'quantity_delta': pl.Float64,
            'signed_notional': pl.Float64, 'mark_carry_pnl': pl.Float64,
            'execution_pnl': pl.Float64, 'commission': pl.Float64, 'funding': pl.Float64,
            'net_pnl': pl.Float64, 'trade_count': pl.Int64, 'slippage_events': pl.Int64})
        per_day = pl.DataFrame({'date': dates['date'], 'attributed_pnl': [0.0] * dates.height,
                                'max_mark_staleness_days': [None] * dates.height})

    equity = daily_frame.select('date', 'equity').sort('date')
    expected = equity.with_columns(
        pl.col('equity').shift(1).fill_null(float(initial_cash)).alias('equity_prev')
    ).with_columns((pl.col('equity') - pl.col('equity_prev')).alias('expected_pnl'))
    reconciled = (expected.join(per_day, on='date', how='left')
                  .with_columns(pl.col('attributed_pnl').fill_null(0.0))
                  .with_columns((pl.col('attributed_pnl') - pl.col('expected_pnl')).abs()
                                .alias('error')))
    maximum = float(reconciled['error'].max())
    tolerance = max(1e-6, float(equity['equity'].abs().max()) * 1e-10)
    if not math.isfinite(maximum) or maximum > tolerance:
        raise QuantError('INVALID_ACCOUNTING',
                         f'Instrument attribution does not reconcile to native equity: '
                         f'{maximum} > {tolerance}')

    month_frame = grid.with_columns(pl.col('date').dt.strftime('%Y-%m').alias('month'))
    monthly = (month_frame.group_by('month', 'symbol').agg(
        pl.col('net_pnl').sum(),
        pl.col('funding').sum(),
        pl.col('commission').sum(),
        pl.col('execution_pnl').sum(),
        pl.col('mark_carry_pnl').sum(),
        pl.col('trade_count').sum())
        .sort('month', 'symbol'))
    symbol_summary = (grid.group_by('symbol').agg(
        pl.col('net_pnl').sum().alias('net_pnl'),
        pl.col('funding').sum().alias('funding'),
        pl.col('commission').sum().alias('commission'),
        pl.col('execution_pnl').sum().alias('execution_pnl'),
        pl.col('mark_carry_pnl').sum().alias('mark_carry_pnl'),
        pl.col('trade_count').sum().alias('trade_count'),
        pl.col('slippage_events').sum().alias('slippage_events'))
        .sort('symbol'))
    return {
        'status': 'AVAILABLE',
        'method': DEFINITIONS['instrument_attribution'],
        'daily': grid,
        'monthly': monthly,
        'symbols': [dict(row) for row in symbol_summary.iter_rows(named=True)],
        'reconciliation': {
            'status': 'PASS',
            'max_daily_equity_error': maximum,
            'tolerance': tolerance,
            'observations': reconciled.height,
            'method': 'native fills + funding cashflows + causal daily marks vs native daily equity',
        },
        'cost_policy': {
            'commission': 'Explicit native fill commission is deducted.',
            'slippage': ('Native execution price already includes declared slippage; the '
                         'fill slippage field is provenance only and is not charged twice.'),
            'funding': 'Native funding cashflow is added to the instrument that held the position.',
        },
        'mark_policy': ('Last close on or before the UTC date; no future bar is used. '
                        'Missing marks for an open position fail closed.'),
        'source_hashes': {
            'panel': _frame_sha256(panel, sort_by=['timestamp', 'symbol']),
            'fills': _frame_sha256(fills_frame, sort_by=['timestamp', 'symbol']),
            'funding': (_frame_sha256(funding_frame, sort_by=['timestamp', 'symbol'])
                        if funding_frame.height else digest({'funding': 'EMPTY'})),
            'daily': _frame_sha256(daily_frame, sort_by=['date']),
            'attribution_daily': _frame_sha256(grid, sort_by=['date', 'symbol']),
            'attribution_monthly': _frame_sha256(monthly, sort_by=['month', 'symbol']),
        },
    }


def _serialise_attribution(attribution: dict[str, Any]) -> dict[str, Any]:
    status = attribution.get('status')
    if status not in STATUSES:
        raise QuantError('INVALID_EVIDENCE', f'Instrument attribution status {status} is invalid')
    output = {key: value for key, value in attribution.items()
              if key not in ('daily', 'monthly', 'symbols', 'source_hashes')}
    if status == 'AVAILABLE':
        if attribution['reconciliation']['status'] != 'PASS':
            raise QuantError('INVALID_EVIDENCE', 'Available attribution must reconcile to equity')
        output['symbols'] = attribution.get('symbols', [])
        output['monthly'] = [dict(row) for row in attribution['monthly'].iter_rows(named=True)]
        output['source_hashes'] = attribution['source_hashes']
        output['reconciliation'] = attribution['reconciliation']
        output['cost_policy'] = attribution['cost_policy']
        output['mark_policy'] = attribution['mark_policy']
    else:
        if not output.get('reason'):
            raise QuantError('INVALID_EVIDENCE', 'Unavailable attribution needs a reason')
    return output


def _source_hashes(*, daily: pl.DataFrame, panel: pl.DataFrame | None,
                   fills: pl.DataFrame | None, funding: pl.DataFrame | None,
                   extra: dict[str, str] | None) -> dict[str, str]:
    hashes = {'daily': _frame_sha256(daily, sort_by=['date'])}
    if panel is not None:
        hashes['panel'] = _frame_sha256(panel, sort_by=['timestamp', 'symbol'])
    if fills is not None:
        hashes['fills'] = _frame_sha256(fills.sort('timestamp') if fills.height else fills)
    if funding is not None:
        hashes['funding'] = (_frame_sha256(funding.sort('timestamp'))
                             if funding.height else digest({'funding': 'EMPTY'}))
    for key, value in (extra or {}).items():
        _hex64(value, f'source_hashes.{key}')
        hashes[key] = value
    return hashes


def build_profit_concentration(*, daily: pl.DataFrame, periods_per_year: int,
                               scope: str, initial_cash: float | None = None,
                               panel: pl.DataFrame | None = None,
                               fills: pl.DataFrame | None = None,
                               funding: pl.DataFrame | None = None,
                               instrument_attribution: dict[str, Any] | None = None,
                               source_hashes: dict[str, str] | None = None,
                               identity: dict[str, Any] | None = None,
                               provenance: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a deterministic, hashed diagnostic payload.

    Passing ``panel``/``fills``/``funding`` requests strict instrument
    attribution. Passing an explicit ``instrument_attribution`` record is the
    intended route for a portfolio scope (where native instrument fills do not
    exist) or for a caller that already reconstructed them.
    """
    if scope not in SCOPES:
        raise QuantError('INVALID_SPEC', f'Unknown profit diagnostic scope: {scope}')
    if not isinstance(periods_per_year, int) or periods_per_year < 1:
        raise QuantError('INVALID_SPEC', 'periods_per_year must be a positive integer')
    daily_frame = _prepare_daily(daily, require_equity=initial_cash is not None)
    months = _month_rows(daily_frame, initial_cash=initial_cash)
    periods = int(periods_per_year)
    headline = _metrics(daily_frame['return'], periods)

    if instrument_attribution is not None:
        attribution_record = _serialise_attribution(instrument_attribution)
        hashes = (source_hashes or {}).copy()
        hashes.update(attribution_record.get('source_hashes', {}))
    elif panel is not None:
        if initial_cash is None:
            raise QuantError('INVALID_EVIDENCE',
                             'Instrument attribution requires the declared initial cash')
        attribution = attribute_instrument_pnl(
            panel=panel, fills=fills if fills is not None else pl.DataFrame(),
            funding=funding, daily=daily_frame, initial_cash=float(initial_cash))
        attribution_record = _serialise_attribution(attribution)
        hashes = (source_hashes or {}).copy()
        hashes.update(attribution['source_hashes'])
    else:
        attribution_record = {
            'status': 'UNAVAILABLE',
            'reason': ('True instrument-level native fills/funding/marks are not available '
                       'at this scope; headline returns are not split arbitrarily.'),
        }
        hashes = source_hashes.copy() if source_hashes else {}

    hashes = hashes or _source_hashes(daily=daily_frame, panel=panel, fills=fills,
                                      funding=funding, extra=None)
    for key, value in hashes.items():
        _hex64(value, f'source_hashes.{key}')

    richest = _richest_months(months, 1)
    richest_two = _richest_months(months, 2)
    record: dict[str, Any] = {
        'schema_version': SCHEMA_VERSION,
        'kind': KIND,
        'scope': scope,
        'status': 'AVAILABLE' if months else 'INCONCLUSIVE',
        'gating': False,
        'selection_effect': 'none',
        'trial_effect': 'none',
        'interpretation': INTERPRETATION,
        'definitions': DEFINITIONS,
        'identity': identity or {},
        'provenance': {
            'scope': scope,
            'holdout_access': False,
            'periods_per_year': periods,
            'initial_cash': initial_cash,
            'return_definition': 'native daily net equity return',
            **(provenance or {}),
        },
        'source_hashes': hashes,
        'availability': {
            'monthly_returns': 'AVAILABLE' if months else 'INCONCLUSIVE',
            'instrument_attribution': attribution_record['status'],
            'instrument_reason': attribution_record.get('reason'),
        },
        'headline': headline,
        'months': months,
        'concentration': {
            'monthly_return': _concentration(months, 'net_return'),
            'monthly_pnl': (_concentration(months, 'net_pnl')
                            if months and 'net_pnl' in months[0] else None),
        },
        'richest_month_exclusion': (
            _ablation(daily_frame, richest[0], periods, headline) if richest else {
                'status': 'UNAVAILABLE',
                'reason': 'No positive month to exclude',
                'interpretation': INTERPRETATION,
            }),
        'richest_two_months_exclusion': (
            _ablation_two(daily_frame, richest_two, periods, headline)
            if len(richest_two) >= 2 else {
                'status': 'UNAVAILABLE',
                'reason': 'Fewer than two positive months to exclude',
                'interpretation': INTERPRETATION,
            }),
        'instrument_attribution': attribution_record,
    }
    validate_profit_concentration(record)
    return record


def _ablation_two(daily: pl.DataFrame, months: list[str], periods_per_year: int,
                  before: dict[str, Any]) -> dict[str, Any]:
    frame = daily.with_columns(pl.col('date').dt.strftime('%Y-%m').alias('__month'))
    ablated = frame.with_columns(
        pl.when(pl.col('__month').is_in(months)).then(0.0).otherwise(pl.col('return'))
        .alias('return')).drop('__month')
    removed = int(frame.filter(pl.col('__month').is_in(months)).height)
    after = _metrics(ablated['return'], periods_per_year)
    delta = {name: (None if before[name] is None or after[name] is None
                    else float(after[name] - before[name]))
             for name in ('sharpe', 'max_drawdown', 'compounded_return')}
    return {
        'status': 'AVAILABLE',
        'excluded_months': months,
        'treatment': ('Every daily net return in the richest two calendar months is set '
                      'to exactly 0.0; the calendar and all other months are unchanged.'),
        'observations_ablated': removed,
        'same_calendar': True,
        'before': before,
        'after': after,
        'delta': delta,
        'interpretation': INTERPRETATION,
    }


def validate_profit_concentration(record: dict[str, Any]) -> None:
    if not isinstance(record, dict):
        raise QuantError('INVALID_EVIDENCE', 'Profit diagnostic must be a mapping')
    if record.get('schema_version') != SCHEMA_VERSION or record.get('kind') != KIND:
        raise QuantError('INVALID_EVIDENCE', 'Profit diagnostic schema/kind is invalid')
    if record.get('scope') not in SCOPES:
        raise QuantError('INVALID_EVIDENCE', 'Profit diagnostic scope is invalid')
    if record.get('status') not in STATUSES:
        raise QuantError('INVALID_EVIDENCE', 'Profit diagnostic status is not terminal')
    if record.get('gating') is not False:
        raise QuantError('INVALID_EVIDENCE', 'Profit concentration must be explicitly non-gating')
    if record.get('selection_effect') != 'none' or record.get('trial_effect') != 'none':
        raise QuantError('INVALID_EVIDENCE', 'Profit diagnostics cannot affect selection or trials')
    if record.get('interpretation') != INTERPRETATION:
        raise QuantError('INVALID_EVIDENCE', 'Profit diagnostic must state its explanatory-only role')
    if not isinstance(record.get('definitions'), dict) or not record['definitions']:
        raise QuantError('INVALID_EVIDENCE', 'Profit diagnostic must retain its definitions')
    availability = record.get('availability')
    if not isinstance(availability, dict) or 'instrument_attribution' not in availability:
        raise QuantError('INVALID_EVIDENCE', 'Profit diagnostic must state availability')
    hashes = record.get('source_hashes')
    if not isinstance(hashes, dict) or not hashes:
        raise QuantError('INVALID_EVIDENCE', 'Profit diagnostic must retain source hashes')
    for key, value in hashes.items():
        _hex64(value, f'source_hashes.{key}')
    if record['status'] == 'AVAILABLE':
        months = record.get('months')
        if not isinstance(months, list) or not months:
            raise QuantError('INVALID_EVIDENCE', 'Available diagnostic needs monthly rows')
        for item in months:
            if 'month' not in item or 'net_return' not in item:
                raise QuantError('INVALID_EVIDENCE', 'Monthly rows need month and net_return')
            _finite(item['net_return'], 'months.net_return')
        concentration = record.get('concentration')
        if not isinstance(concentration, dict) or concentration.get('monthly_return') is None:
            raise QuantError('INVALID_EVIDENCE', 'Available diagnostic needs concentration')
        ablation = record.get('richest_month_exclusion')
        if not isinstance(ablation, dict):
            raise QuantError('INVALID_EVIDENCE', 'Available diagnostic needs an ablation record')
        if 'status' not in ablation or ablation.get('status') != 'UNAVAILABLE':
            for key in ('before', 'after', 'delta'):
                if key not in ablation:
                    raise QuantError('INVALID_EVIDENCE', f'Ablation is missing {key}')
    elif not record.get('reason'):
        raise QuantError('INVALID_EVIDENCE', 'Non-available diagnostic needs a reason')


def blocked_profit_concentration(*, scope: str, reason: str,
                                 source_hashes: dict[str, str] | None = None,
                                 identity: dict[str, Any] | None = None) -> dict[str, Any]:
    """A valid, non-PASS record for an incomplete/unsupported diagnostic."""
    record = {
        'schema_version': SCHEMA_VERSION,
        'kind': KIND,
        'scope': scope,
        'status': 'BLOCKED',
        'reason': reason,
        'gating': False,
        'selection_effect': 'none',
        'trial_effect': 'none',
        'interpretation': INTERPRETATION,
        'definitions': DEFINITIONS,
        'identity': identity or {},
        'provenance': {'scope': scope, 'holdout_access': False},
        'source_hashes': source_hashes or {'unavailable': digest({'reason': reason})},
        'availability': {
            'monthly_returns': 'BLOCKED',
            'instrument_attribution': 'BLOCKED',
            'instrument_reason': reason,
        },
    }
    validate_profit_concentration(record)
    return record


def diagnose_sleeve(*, daily: pl.DataFrame, periods_per_year: int, initial_cash: float,
                    panel: pl.DataFrame | None, fills: pl.DataFrame | None,
                    funding: pl.DataFrame | None,
                    identity: dict[str, Any] | None = None,
                    provenance: dict[str, Any] | None = None,
                    strict: bool = True) -> dict[str, Any]:
    """Diagnostic for one class-scoped sleeve run.

    ``strict`` raises an evidence error; the runner uses ``strict=False`` so a
    diagnostic failure is recorded as BLOCKED without changing the gate verdict.
    """
    if panel is None:
        return build_profit_concentration(
            daily=daily, periods_per_year=periods_per_year, scope='sleeve',
            initial_cash=initial_cash, instrument_attribution={
                'status': 'UNAVAILABLE',
                'reason': 'No native mark panel was supplied for instrument attribution'},
            identity=identity, provenance=provenance)
    try:
        return build_profit_concentration(
            daily=daily, periods_per_year=periods_per_year, scope='sleeve',
            initial_cash=initial_cash, panel=panel, fills=fills, funding=funding,
            identity=identity, provenance=provenance)
    except QuantError as exc:
        if strict:
            raise
        try:
            daily_hash = _frame_sha256(daily, sort_by=['date'])
        except (pl.exceptions.PolarsError, TypeError, ValueError):
            daily_hash = digest({'daily': 'UNAVAILABLE_AFTER_VALIDATION_ERROR'})
        return blocked_profit_concentration(
            scope='sleeve', reason=f'{exc.status}: {exc.reason}',
            source_hashes={'daily': daily_hash}, identity=identity)


def diagnose_portfolio(*, timestamps: pl.Series, returns: pl.Series,
                       periods_per_year: int,
                       source_hashes: dict[str, str],
                       identity: dict[str, Any] | None = None,
                       provenance: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return-only diagnostic for a qualified, class-scoped portfolio."""
    if len(timestamps) != len(returns) or len(returns) == 0:
        raise QuantError('INVALID_EVIDENCE', 'Portfolio diagnostics need aligned nonempty returns')
    dtype = timestamps.dtype
    if not (isinstance(dtype, pl.Datetime) or dtype == pl.Date):
        raise QuantError('INVALID_EVIDENCE', 'Portfolio timestamps must be temporal')
    daily = pl.DataFrame({'date': timestamps.dt.date(), 'return': returns})
    hashes = dict(source_hashes)
    hashes['daily'] = _frame_sha256(daily, sort_by=['date'])
    return build_profit_concentration(
        daily=daily, periods_per_year=periods_per_year, scope='portfolio',
        initial_cash=None, instrument_attribution={
            'status': 'UNAVAILABLE',
            'reason': ('Portfolio diagnostics operate on the weighted sleeve-return '
                       'composition; native per-instrument fills/funding are not present '
                       'at portfolio scope and headline returns are not split arbitrarily.')},
        source_hashes=hashes, identity=identity, provenance=provenance)


def frame_sha256(frame: pl.DataFrame, *, sort_by: list[str] | None = None) -> str:
    """Public content-hash helper for callers that must retain source evidence."""
    return _frame_sha256(frame, sort_by=sort_by)


def write_profit_concentration(record: dict[str, Any], folder: str | Path) -> dict[str, Any]:
    """Validate, write one hashed JSON artifact and return its evidence summary."""
    validate_profit_concentration(record)
    target = Path(folder) / 'profit_concentration.json'
    write_json(target, record)
    sha256 = file_hash(target)
    summary = {
        'status': record['status'],
        'gating': False,
        'selection_effect': 'none',
        'trial_effect': 'none',
        'artifact': target.name,
        'artifact_sha256': sha256,
        'source_hashes': record['source_hashes'],
        'availability': record['availability'],
        'interpretation': record['interpretation'],
    }
    if record.get('reason'):
        summary['reason'] = record['reason']
    return {'path': target, 'sha256': sha256, 'summary': summary}
