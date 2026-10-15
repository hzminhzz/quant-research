"""Vectorized independent reconciliation of native fills, cashflows and marks.

This validates an existing native simulation. It does not generate trades or
serve as a fallback trading engine.
"""
from __future__ import annotations

import polars as pl

from src.engine.common import QuantError


def audit_accounting(prices: pl.DataFrame, fills: pl.DataFrame,
                     funding: pl.DataFrame, equity: pl.DataFrame,
                     initial_cash: float) -> dict:
    clock = equity.select('timestamp').sort('timestamp')
    if fills.is_empty():
        error = (equity['equity'] - initial_cash).abs().max()
        if error > 1e-6:
            raise QuantError('INVALID_ACCOUNTING', 'Equity changed without native fills')
        return {'status': 'PASS', 'max_equity_error': error, 'method': 'no-position identity'}
    changes = fills.with_columns(
        pl.col('timestamp').dt.replace_time_zone('UTC'),
        pl.col('asset').alias('symbol'),
        (pl.when(pl.col('side') == 'buy').then(1.).otherwise(-1.) * pl.col('quantity')).alias('quantity_delta'))
    quantity = (changes.group_by('timestamp', 'symbol').agg(pl.col('quantity_delta').sum())
                .sort('symbol', 'timestamp')
                .with_columns(pl.col('quantity_delta').cum_sum().over('symbol').alias('quantity')))
    cash_events = changes.select('timestamp',
                                 (-pl.col('quantity_delta') * pl.col('price') - pl.col('commission')).alias('cashflow'))
    if funding.height:
        cash_events = pl.concat([cash_events, funding.select('timestamp', 'cashflow')], how='vertical_relaxed')
        # Settlement must use the quantity strictly before that event timestamp.
        expected_quantity = (funding.sort('symbol', 'timestamp')
                             .join_asof(quantity.select('timestamp', 'symbol', pl.col('quantity').alias('expected_quantity')),
                                        on='timestamp', by='symbol', strategy='backward', allow_exact_matches=False, check_sortedness=False)
                             .with_columns(pl.col('expected_quantity').fill_null(0.)))
        quantity_error = (expected_quantity['quantity'] - expected_quantity['expected_quantity']).abs().max()
        flow_error = expected_quantity.select((pl.col('cashflow') + pl.col('expected_quantity')
                                                * pl.col('mark') * pl.col('rate')).abs().max()).item()
        if quantity_error > 1e-8 or flow_error > 1e-6:
            raise QuantError('INVALID_ACCOUNTING', 'Funding used post-event holdings or wrong sign/mark')
    else:
        flow_error = 0.0
    cash = (clock.join(cash_events.group_by('timestamp').agg(pl.col('cashflow').sum()),
                       on='timestamp', how='left').fill_null(0.).sort('timestamp')
            .with_columns((initial_cash + pl.col('cashflow').cum_sum()).alias('cash')))
    symbols = changes.select('symbol').unique()
    grid = clock.join(symbols, how='cross').sort('symbol', 'timestamp')
    marks = prices.select('timestamp', 'symbol', 'close').sort('symbol', 'timestamp')
    # Every input is explicitly sorted by symbol/time above; Polars cannot infer
    # sortedness within a 'by' group and otherwise emits an unhelpful warning.
    holdings = (grid.join_asof(quantity.select('timestamp', 'symbol', 'quantity'), on='timestamp', by='symbol', strategy='backward', check_sortedness=False)
                .join_asof(marks, on='timestamp', by='symbol', strategy='backward', check_sortedness=False)
                .with_columns(pl.col('quantity').fill_null(0.)))
    if holdings.filter((pl.col('quantity').abs() > 1e-10) & pl.col('close').is_null()).height:
        raise QuantError('INVALID_ACCOUNTING', 'No causal mark for an open position')
    value = holdings.group_by('timestamp').agg((pl.col('quantity') * pl.col('close').fill_null(0.)).sum().alias('positions'))
    reconstructed = (cash.join(value, on='timestamp').join(equity.select('timestamp', 'equity'), on='timestamp')
                     .with_columns((pl.col('cash') + pl.col('positions') - pl.col('equity')).abs().alias('error')))
    maximum = float(reconstructed['error'].max())
    tolerance = max(1e-6, float(equity['equity'].abs().max()) * 1e-10)
    if maximum > tolerance:
        raise QuantError('INVALID_ACCOUNTING', f'Native equity mismatch: {maximum} > {tolerance}')
    return {'status': 'PASS', 'max_equity_error': maximum, 'tolerance': tolerance,
            'max_funding_error': float(flow_error), 'bars_checked': reconstructed.height,
            'method': 'signed-fill cash + prior-event funding + causal marked holdings'}
