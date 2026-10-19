from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from src.data_vault.panel_builder import validate_panel
from src.engine.common import QuantError
from src.engine.ts_runner import align_carry_events, run_native_ts
from src.engine.ts_spec import TimeSeriesSpec

START = datetime(2020, 1, 1, tzinfo=UTC)
BARS = 40
SYMBOLS = ('A', 'B')


def make_spec() -> TimeSeriesSpec:
    return TimeSeriesSpec.model_validate({
        'spec_kind': 'time_series',
        'sleeve_id': 'af30_carry_integration',
        'selection_family_id': 'af30_time_series',
        'book_strategy': 11,
        'thesis': 'Carry integration reconciliation test.',
        'market_classes': [{
            'name': 'indices', 'symbols': list(SYMBOLS),
            'panel_root': 'data/vault/markets_20261015/index_1h',
            'bar_seconds': 3600, 'periods_per_year': 252,
        }],
        'windows': {
            'train': {'start': '2020-01-01T00:00:00Z', 'end': '2021-01-01T00:00:00Z'},
            'validation': {'start': '2021-01-01T00:00:00Z', 'end': '2022-01-01T00:00:00Z'},
            'protected': {'start': '2026-01-01T00:00:00Z', 'end': '2026-10-01T00:00:00Z'},
        },
        'features': [
            {'name': 'f', 'expr': {'op': 'col', 'name': 'close'}},
            {'name': 'atr_14', 'expr': {'op': 'col', 'name': 'close'}},
        ],
        'forecast': {'feature': 'f', 'horizon_bars': 1,
                     'scaling': {'kind': 'bounded_linear', 'scale': 10.0, 'cap': 2.0}},
        'stops': {'feature': 'atr_14', 'multiple': 0.05},
        'costs': {'commission_bps_one_way': 1.0, 'slippage_bps_one_way': 1.0,
                  'spread_bps': 0.0, 'spread_included_in_slippage': True},
        'initial_cash': 100000.0,
    })


def make_panel() -> pl.DataFrame:
    rows = []
    for index in range(BARS):
        for offset, symbol in enumerate(SYMBOLS):
            close = 100.0 + index * 0.05 + offset * 0.5
            rows.append({
                'timestamp': START + timedelta(hours=index), 'symbol': symbol,
                'open': close, 'high': close + 0.1, 'low': close - 0.1, 'close': close,
                'volume': 1000.0, 'carry_rate': 0.0, 'spread_bps': 0.0,
                'session_id': '24x7', 'bar_in_session': index, 'is_tradable': True,
            })
    return validate_panel(pl.DataFrame(rows))


def make_targets() -> pl.DataFrame:
    rows = []
    for hour in (2, 10):
        timestamp = START + timedelta(hours=hour)
        rows.append({'timestamp': timestamp, 'symbol': 'A', 'target_weight': 0.5,
                     'stop_loss_dist_pct': 0.05})
        rows.append({'timestamp': timestamp, 'symbol': 'B', 'target_weight': -0.5,
                     'stop_loss_dist_pct': 0.05})
    return pl.DataFrame(rows, schema={'timestamp': pl.Datetime('us', 'UTC'), 'symbol': pl.String,
                                      'target_weight': pl.Float64, 'stop_loss_dist_pct': pl.Float64})


def make_events(hour: int = 5, rate: float = 0.0002) -> pl.DataFrame:
    timestamp = START + timedelta(hours=hour)
    return pl.DataFrame({
        'timestamp': [timestamp, timestamp],
        'symbol': list(SYMBOLS),
        'funding_rate': [rate, rate],
        'mark_price': [100.2, 100.7],
        'curve_at': [START, START],
        'mark_at': [timestamp - timedelta(hours=1)] * 2,
        'curve_name': ['US10Y', 'US10Y'],
    })


def test_native_carry_reconciles_and_records_provenance():
    spec, panel = make_spec(), make_panel()
    result = run_native_ts(panel, make_targets(), spec, spec.market_classes[0],
                           carry_events=make_events(),
                           carry_metadata={'status': 'MODELED', 'curve': {'name': 'US10Y'},
                                           'sign_convention': 'positive_rate_charges_longs'})
    assert result.metrics['independent_accounting']['status'] == 'PASS'
    assert result.metrics['carry_status'] == 'MODELED'
    assert result.metrics['carry_events'] == 2
    assert result.metrics['carry_curve'] == 'US10Y'
    assert result.funding.height == 2
    assert set(result.funding.columns) >= {'timestamp', 'symbol', 'rate', 'mark', 'cashflow'}
    assert result.metrics['funding_total'] == pytest.approx(result.funding['cashflow'].sum())
    assert result.funding['source_event_at'].unique().to_list() == [START + timedelta(hours=5)]


def test_long_pays_and_short_receives():
    spec, panel = make_spec(), make_panel()
    result = run_native_ts(panel, make_targets(), spec, spec.market_classes[0],
                           carry_events=make_events(rate=0.001))
    flows = dict(zip(result.funding['symbol'], result.funding['cashflow']))
    positions = dict(zip(result.funding['symbol'], result.funding['quantity']))
    assert positions['A'] > 0 and positions['B'] < 0
    assert flows['A'] < 0 and flows['B'] > 0


def test_alignment_snaps_to_the_native_clock_and_keeps_the_schedule():
    panel = make_panel()
    events = make_events(hour=4).with_columns(
        (pl.col('timestamp') + pl.duration(minutes=30)).alias('timestamp'))
    aligned = align_carry_events(events, panel)
    assert aligned.height == 2
    assert aligned['timestamp'].unique().to_list() == [START + timedelta(hours=5)]
    assert aligned['source_event_at'].unique().to_list() == [START + timedelta(hours=4, minutes=30)]


def test_nonfinite_rate_is_blocked_before_execution():
    with pytest.raises(QuantError) as exc:
        align_carry_events(make_events().with_columns(pl.lit(float('nan')).alias('funding_rate')),
                           make_panel())
    assert exc.value.status == 'BLOCKED_DATA'


def test_invalid_mark_is_blocked_before_execution():
    with pytest.raises(QuantError) as exc:
        align_carry_events(make_events().with_columns(pl.lit(0.0).alias('mark_price')), make_panel())
    assert exc.value.status == 'BLOCKED_DATA'


def test_duplicate_settlement_mapping_is_blocked():
    missing = [START + timedelta(hours=4), START + timedelta(hours=5)]
    panel = make_panel().filter(~pl.col('timestamp').is_in(missing))
    first = make_events(hour=4)
    second = make_events(hour=5)
    with pytest.raises(QuantError) as exc:
        align_carry_events(pl.concat([first, second]), panel)
    assert exc.value.status == 'BLOCKED_DATA'


def test_two_runs_are_identical():
    spec, panel = make_spec(), make_panel()
    first = run_native_ts(panel, make_targets(), spec, spec.market_classes[0],
                          carry_events=make_events())
    second = run_native_ts(panel, make_targets(), spec, spec.market_classes[0],
                           carry_events=make_events())
    assert first.equity.equals(second.equity)
    assert first.funding.equals(second.funding)
    assert first.metrics['funding_total'] == second.metrics['funding_total']
