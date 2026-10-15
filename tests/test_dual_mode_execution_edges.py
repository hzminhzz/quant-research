"""Native lifecycle regressions: no future intrabar move before an opening exit."""
import polars as pl
import pytest

from src.engine.backtest_runner import run_native
from src.engine.common import QuantError
from tests.dual_mode_fixtures import make_panel, manual_targets, zero_carry
from tests.dual_mode_fixtures import test_spec as spec_fixture


def test_scheduled_opening_exit_precedes_later_intrabar_stop():
    panel = zero_carry(make_panel(hours=40))
    times = panel['timestamp'].unique().sort().to_list()
    panel = panel.with_columns(pl.when((pl.col('symbol') == 'BTCUSDT_PERP') & (pl.col('timestamp') == times[10]))
                              .then(90.).otherwise(pl.col('low')).alias('low'))
    opening = manual_targets(panel, when=(1,), weights={'BTCUSDT_PERP': .5})
    exiting = manual_targets(panel, when=(9,), weights={'BTCUSDT_PERP': 0.})
    result = run_native(panel, pl.concat([opening, exiting]), spec_fixture())
    assert result.metrics['final_equity'] == pytest.approx(100000.)
    assert result.fills['price'].to_list() == [100., 100.]


def test_gap_stop_fills_at_adverse_open_not_stop_level():
    panel = zero_carry(make_panel(hours=40))
    times = panel['timestamp'].unique().sort().to_list()
    affected = (pl.col('symbol') == 'BTCUSDT_PERP') & (pl.col('timestamp') == times[10])
    panel = panel.with_columns(pl.when(affected).then(90.).otherwise(pl.col('open')).alias('open'),
                              pl.when(affected).then(89.).otherwise(pl.col('low')).alias('low'))
    result = run_native(panel, manual_targets(panel, weights={'BTCUSDT_PERP': .5}), spec_fixture())
    assert result.metrics['final_equity'] == pytest.approx(95000.)
    assert result.fills['price'].to_list() == [100., 90.]


def test_resize_preserves_frozen_absolute_stop():
    panel = zero_carry(make_panel(hours=40))
    first = manual_targets(panel, when=(1,), weights={'BTCUSDT_PERP': .25}, distance=.05)
    increase = manual_targets(panel, when=(9,), weights={'BTCUSDT_PERP': .5}, distance=.20)
    decrease = manual_targets(panel, when=(19,), weights={'BTCUSDT_PERP': .1}, distance=.10)
    result = run_native(panel, pl.concat([first, increase, decrease]), spec_fixture())
    updates = result.metrics['protection_updates']
    assert len(updates) == 3
    assert [u['stop_price'] for u in updates] == [95., 95., 95.]
    assert [u['quantity'] for u in updates] == [250., 500., 100.]
    assert result.metrics['final_equity'] == pytest.approx(100000.)


def test_missing_quote_with_held_position_does_not_use_stale_mark():
    panel = zero_carry(make_panel(hours=40))
    times = panel['timestamp'].unique().sort().to_list()
    broken = panel.filter(~((pl.col('symbol') == 'BTCUSDT_PERP') & (pl.col('timestamp') == times[10])))
    with pytest.raises(QuantError, match='no tradable opening'):
        run_native(broken, manual_targets(panel, weights={'BTCUSDT_PERP': .5}), spec_fixture())


def test_realistic_costs_reconcile_to_native_fill_cash():
    panel = zero_carry(make_panel(hours=40))
    spec = spec_fixture()
    spec = spec.model_copy(update={'costs': spec.costs.model_copy(update={'commission_bps_one_way': 5., 'slippage_bps_one_way': 4.})})
    result = run_native(panel, manual_targets(panel), spec)
    assert result.metrics['final_equity'] < 100000.
    assert result.metrics['independent_accounting']['status'] == 'PASS'
    assert result.fills['commission'].sum() > 0
