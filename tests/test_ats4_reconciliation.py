from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import polars as pl
import pytest
from ml4t.backtest import AssetClass, BacktestConfig, ContractSpec, DataFeed, Engine
from ml4t.backtest.config import (
    CommissionType,
    ExecutionMode,
    FillOrdering,
    SlippageType,
)

from src.engine.ats4_reconciliation import reconcile_m8_n8
from src.research_control.m8_n8 import N8LongOnly


def bars():
    t = datetime(2020, 1, 1, tzinfo=UTC)
    return pl.DataFrame({'timestamp': [t + timedelta(minutes=30 * i) for i in range(5)],
                         'symbol': ['source'] * 5, 'open': [100., 101., 102., 103., 104.],
                         'high': [101., 102., 103., 104., 105.], 'low': [99., 100., 101., 102., 103.],
                         'close': [100.5, 101.5, 102.5, 103.5, 104.5], 'volume': [10.] * 5})


def native_run():
    source = bars()
    signals = pl.DataFrame({'timestamp': source['timestamp'], 'asset': ['source'] * 5,
                            'm8_n8_long': [1, 0, 0, 0, 0]})
    strategy = N8LongOnly('source', source['timestamp'][0], source['timestamp'][-1])
    config = BacktestConfig(initial_cash=100_000., allow_short_selling=False, allow_leverage=False,
                            execution_mode=ExecutionMode.NEXT_BAR, fill_ordering=FillOrdering.EXIT_FIRST,
                            commission_type=CommissionType.PERCENTAGE, commission_rate=.6 / 10_000,
                            slippage_type=SlippageType.PERCENTAGE, slippage_rate=3 / 10_000)
    result = Engine(DataFeed(prices_df=source.rename({'symbol': 'asset'}), signals_df=signals), strategy,
                    config, contract_specs={'source': ContractSpec('source', AssetClass.EQUITY,
                                                                    multiplier=1.)}).run()
    return source, result, strategy


def test_literal_hand_worked_event_ledger_and_timing():
    source, result, strategy = native_run()
    report = reconcile_m8_n8(result, strategy, source, [source['timestamp'][0]], 1)
    entry = 101. * 1.0003
    exit_ = 102. * .9997
    entry_fee, exit_fee = entry * .00006, exit_ * .00006
    assert report['status'] == 'PASS'
    assert report['orders'][0]['decision_available_at'] == '2020-01-01T00:30:00+00:00'
    assert report['orders'][0]['filled_at'] == '2020-01-01T00:30:00+00:00'
    assert report['orders'][1]['created_at'] == '2020-01-01T00:30:00+00:00'
    assert report['orders'][1]['decision_available_at'] == '2020-01-01T01:00:00+00:00'
    assert report['orders'][1]['filled_at'] == report['orders'][1]['decision_available_at']
    assert report['ledger'][0]['cash'] == 100_000.
    assert report['ledger'][1]['cash'] == pytest.approx(100_000 - entry - entry_fee)
    assert report['ledger'][1]['equity'] == pytest.approx(100_000 - entry - entry_fee + 101.5)
    assert report['ledger'][2]['cash'] == pytest.approx(100_000 - entry - entry_fee + exit_ - exit_fee)
    assert report['ledger'][-1]['position'] == 0


def altered_result(result, *, fills=None, portfolio=None, equity=None, rejected=None):
    return SimpleNamespace(
        rejected_orders=result.rejected_orders if rejected is None else rejected,
        to_fills_dataframe=lambda: result.to_fills_dataframe() if fills is None else fills,
        to_portfolio_state_dataframe=lambda: result.to_portfolio_state_dataframe() if portfolio is None else portfolio,
        to_equity_dataframe=lambda: result.to_equity_dataframe() if equity is None else equity,
    )


@pytest.mark.parametrize('mutation', ['missing_fill', 'duplicate_fill', 'missing_mark', 'duplicate_mark',
                                      'forged_cash_offset', 'wrong_commission', 'wrong_quantity', 'same_bar_fill',
                                      'portfolio_equity_only', 'wrong_fill_asset', 'naive_source_time',
                                      'nonpositive_price'])
def test_rejects_execution_and_ledger_mutations(mutation):
    source, result, strategy = native_run()
    fills, portfolio, equity = (result.to_fills_dataframe(), result.to_portfolio_state_dataframe(),
                                result.to_equity_dataframe())
    if mutation == 'missing_fill':
        fills = fills.head(1)
    elif mutation == 'duplicate_fill':
        fills = pl.concat([fills, fills.tail(1)])
    elif mutation in ('missing_mark', 'duplicate_mark'):
        portfolio = portfolio.head(4) if mutation == 'missing_mark' else pl.concat([portfolio, portfolio.tail(1)])
    elif mutation == 'forged_cash_offset':
        portfolio = portfolio.with_columns((pl.col('cash') + 1).alias('cash'))
        equity = equity.with_columns((pl.col('equity') + 1).alias('equity'))
    elif mutation == 'wrong_commission':
        fills = fills.with_columns(pl.when(pl.col('side') == 'buy').then(pl.col('commission') + 1)
                                   .otherwise(pl.col('commission')).alias('commission'))
    elif mutation == 'wrong_quantity':
        strategy.orders[0]['entry_order'].filled_quantity = 2.
    elif mutation == 'same_bar_fill':
        fills = fills.with_columns(pl.when(pl.col('side') == 'buy').then(source['timestamp'][0].replace(tzinfo=None))
                                   .otherwise(pl.col('timestamp')).alias('timestamp'))
    elif mutation == 'portfolio_equity_only':
        portfolio = portfolio.with_columns((pl.col('equity') + 1).alias('equity'))
    elif mutation == 'wrong_fill_asset':
        fills = fills.with_columns(pl.lit('other').alias('asset'))
    elif mutation == 'naive_source_time':
        source = source.with_columns(pl.col('timestamp').dt.replace_time_zone(None))
    elif mutation == 'nonpositive_price':
        source = source.with_columns(pl.when(pl.arange(0, pl.len()) == 1).then(0.).otherwise(pl.col('open')).alias('open'))
    with pytest.raises(ValueError):
        reconcile_m8_n8(altered_result(result, fills=fills, portfolio=portfolio, equity=equity),
                        strategy, source, [source['timestamp'][0]], 1)


def test_rejects_missing_or_duplicate_orders_and_wrong_cost():
    source, result, strategy = native_run()
    strategy.orders[0]['exit_order'] = None
    with pytest.raises(ValueError, match='order submissions'):
        reconcile_m8_n8(result, strategy, source, [source['timestamp'][0]], 1)
    source, result, strategy = native_run()
    strategy.orders.append(strategy.orders[0].copy())
    with pytest.raises(ValueError, match='order submissions'):
        reconcile_m8_n8(result, strategy, source, [source['timestamp'][0]], 1)
    source, result, strategy = native_run()
    with pytest.raises(ValueError, match='filled_price'):
        reconcile_m8_n8(result, strategy, source, [source['timestamp'][0]], 2)


def test_rejects_rejected_orders_and_same_bar_native_order_time():
    source, result, strategy = native_run()
    with pytest.raises(ValueError, match='rejected'):
        reconcile_m8_n8(altered_result(result, rejected=[object()]), strategy, source,
                        [source['timestamp'][0]], 1)
    source, result, strategy = native_run()
    strategy.orders[0]['entry_order'].filled_at = source['timestamp'][0]
    with pytest.raises(ValueError, match='filled_at'):
        reconcile_m8_n8(result, strategy, source, [source['timestamp'][0]], 1)


@pytest.mark.parametrize('mutation, message', [('wrong_asset', 'order.asset'),
                                               ('wrong_order_type', 'order.order_type'),
                                               ('wrong_signal_metadata', 'strategy.signal_at'),
                                               ('pending_order', 'pending order')])
def test_rejects_native_order_identity_and_state_mutations(mutation, message):
    source, result, strategy = native_run()
    if mutation == 'wrong_asset':
        strategy.orders[0]['entry_order'].asset = 'other'
    elif mutation == 'wrong_order_type':
        strategy.orders[0]['entry_order'].order_type = 'limit'
    elif mutation == 'wrong_signal_metadata':
        strategy.orders[0]['signal_at'] = source['timestamp'][1]
    else:
        strategy.pending_exit = strategy.orders[0]['exit_order']
    with pytest.raises(ValueError, match=message):
        reconcile_m8_n8(result, strategy, source, [source['timestamp'][0]], 1)
