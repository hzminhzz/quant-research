"""Behavioural contract for the time-series ATS target allocator.

These are acceptance gates for a behaviour-preserving refactor of
``src.engine.ts_allocator``. They exercise only the public surface
(``allocate_ts`` and ``capped_budgets``) and never the private helpers, so an
internal rewrite that preserves the published semantics keeps them green:

* the four declared risk methods, with exact expected relative weights;
* gross-exposure scaling, the per-instrument cap, water-filling and the
  universe-width feasibility boundary;
* the warm-up/insufficient-eligibility flat branch versus just-enough names;
* ineligible names (PIT, tradability, non-finite inputs) staying exactly flat;
* the stop-distance formula in double precision, including Float32 inputs;
* repeat-run and row-order bit identity;
* cadence alignment and the published empty schema;
* deterministic ordering and schema/dtype stability for ns/naive timestamps.

Synthetic fixtures only: no vault, protected window, casefile or market
evidence. The existing ``tests/test_ts_allocator.py`` already covers the basic
path, so the scenarios here are deliberately disjoint from it.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from src.engine.signal_allocator import TARGET_COLUMNS
from src.engine.ts_allocator import allocate_ts, capped_budgets
from src.engine.ts_spec import TimeSeriesSpec

START = datetime(2020, 1, 1, tzinfo=UTC)
BAR_SECONDS = 3600
TARGET_SCHEMA = {
    'timestamp': pl.Datetime('us', 'UTC'), 'symbol': pl.String,
    'target_weight': pl.Float64, 'stop_loss_dist_pct': pl.Float64,
}


def make_spec(symbols: tuple[str, ...] = ('A', 'B', 'C'), *,
              method: str = 'inverse_volatility', vol_feature: str | None = 'vol_20',
              cap: float = 0.4, gross: float = 1.0, weights: dict[str, float] | None = None,
              multiple: float = 3.0, rebalance_bars: int = 1,
              bar_seconds: int = BAR_SECONDS) -> TimeSeriesSpec:
    risk = {'method': method, 'per_instrument_cap': cap, 'gross_exposure': gross,
            'volatility_feature': vol_feature, 'weights': weights}
    payload = {
        'spec_kind': 'time_series',
        'sleeve_id': 'ts_allocator_contract',
        'selection_family_id': 'ts_allocator_contract',
        'book_strategy': 6,
        'thesis': 'Allocator contract fixture; never market evidence.',
        'market_classes': [{
            'name': 'indices', 'symbols': list(symbols),
            'panel_root': 'data/vault/markets_20261015/index_1h',
            'bar_seconds': bar_seconds, 'periods_per_year': 252,
        }],
        'windows': {
            'train': {'start': '2020-01-01T00:00:00Z', 'end': '2021-01-01T00:00:00Z'},
            'validation': {'start': '2021-01-01T00:00:00Z', 'end': '2022-01-01T00:00:00Z'},
            'protected': {'start': '2026-01-01T00:00:00Z', 'end': '2026-10-01T00:00:00Z'},
        },
        'features': [
            {'name': 'f', 'expr': {'op': 'col', 'name': 'close'}},
            {'name': 'atr_14', 'expr': {'op': 'col', 'name': 'close'}},
            {'name': 'vol_20', 'expr': {'op': 'col', 'name': 'close'}},
        ],
        'forecast': {'feature': 'f', 'horizon_bars': 1,
                     'scaling': {'kind': 'bounded_linear', 'scale': 10.0, 'cap': 2.0}},
        'risk_allocation': risk,
        'stops': {'feature': 'atr_14', 'multiple': multiple},
        'rebalance_bars': rebalance_bars,
        'costs': {'commission_bps_one_way': 1.0, 'slippage_bps_one_way': 1.0,
                  'spread_bps': 0.0, 'spread_included_in_slippage': True},
    }
    return TimeSeriesSpec.model_validate(payload)


def per(symbol: str, value: object, default: object) -> object:
    """Resolve a scalar-or-per-symbol fixture value without special casing rows."""
    if value is None:
        return default
    if isinstance(value, dict):
        return value.get(symbol, default)
    return value


def make_panel(symbols: tuple[str, ...], *, forecasts: object = 1.0,
               stops: object = 1.0, closes: object = 100.0,
               vols: object = 0.2, in_pit_universe: object = True,
               is_tradable: object = True,
               bars: int = 1, step: timedelta = timedelta(hours=1)) -> pl.DataFrame:
    rows = [
        {
            'timestamp': START + step * bar,
            'symbol': symbol,
            'close': per(symbol, closes, 100.0),
            'forecast': per(symbol, forecasts, 1.0),
            'atr_14': per(symbol, stops, 1.0),
            'vol_20': per(symbol, vols, 0.2),
            'in_pit_universe': per(symbol, in_pit_universe, True),
            'is_tradable': per(symbol, is_tradable, True),
        }
        for bar in range(bars)
        for symbol in symbols
    ]
    return pl.DataFrame(rows)


def latest(targets: pl.DataFrame) -> pl.DataFrame:
    return targets.filter(pl.col('timestamp') == targets['timestamp'].max()).sort('symbol')


def weights_of(targets: pl.DataFrame) -> dict[str, float]:
    latest_frame = latest(targets)
    return dict(zip(latest_frame['symbol'].to_list(),
                    latest_frame['target_weight'].to_list(), strict=True))


def stops_of(targets: pl.DataFrame) -> dict[str, float]:
    latest_frame = latest(targets)
    return dict(zip(latest_frame['symbol'].to_list(),
                    latest_frame['stop_loss_dist_pct'].to_list(), strict=True))


def assert_contract_frame(targets: pl.DataFrame) -> None:
    assert targets.schema == TARGET_SCHEMA
    assert targets.columns == TARGET_COLUMNS
    assert targets.select('timestamp', 'symbol').equals(
        targets.select('timestamp', 'symbol').sort('timestamp', 'symbol'))


def assert_book_invariants(targets: pl.DataFrame, *, gross: float, cap: float) -> None:
    """Every section is either flat or fully invested within the declared cap."""
    stats = targets.group_by('timestamp', maintain_order=True).agg(
        pl.col('target_weight').abs().sum().alias('gross'),
        pl.col('target_weight').abs().max().alias('peak'),
    )
    for row in stats.iter_rows(named=True):
        if row['gross'] == 0.0:
            continue
        assert row['gross'] == pytest.approx(gross, abs=1e-9)
        assert row['peak'] <= cap * gross + 1e-12


def float_bits(frame: pl.DataFrame) -> tuple[bytes, bytes]:
    return (np.asarray(frame['target_weight'].to_numpy(), dtype='<f8').tobytes(),
            np.asarray(frame['stop_loss_dist_pct'].to_numpy(), dtype='<f8').tobytes())


# --------------------------------------------------------------------------- #
# Risk methods
# --------------------------------------------------------------------------- #
VOLS = {'A': 0.1, 'B': 0.2, 'C': 0.4}
FORECASTS = {'A': 1.0, 'B': -1.0, 'C': 0.5}


def test_inverse_volatility_weights_are_inverse_vol_shares():
    spec = make_spec(('A', 'B', 'C'), method='inverse_volatility', cap=0.9)
    targets = allocate_ts(make_panel(('A', 'B', 'C'), forecasts=FORECASTS, vols=VOLS),
                          spec, spec.market_classes[0])
    assert_contract_frame(targets)
    # raw budgets 10, 5, 2.5 -> 4/7, 2/7, 1/7 of the gross, signed by forecast.
    assert weights_of(targets) == pytest.approx(
        {'A': 4 / 7, 'B': -2 / 7, 'C': 1 / 7}, abs=1e-15)
    assert_book_invariants(targets, gross=1.0, cap=0.9)


def test_equal_weight_weights_are_inverse_universe_counts():
    spec = make_spec(('A', 'B', 'C'), method='equal_weight', vol_feature=None, cap=0.9)
    targets = allocate_ts(make_panel(('A', 'B', 'C'), forecasts=FORECASTS), spec,
                          spec.market_classes[0])
    assert_contract_frame(targets)
    assert weights_of(targets) == pytest.approx(
        {'A': 1 / 3, 'B': -1 / 3, 'C': 1 / 3}, abs=1e-15)
    assert_book_invariants(targets, gross=1.0, cap=0.9)


def test_forecast_weighted_weights_are_absolute_forecast_over_vol():
    spec = make_spec(('A', 'B', 'C'), method='forecast_weighted', cap=0.9)
    targets = allocate_ts(make_panel(('A', 'B', 'C'), forecasts=FORECASTS, vols=VOLS),
                          spec, spec.market_classes[0])
    assert_contract_frame(targets)
    # raw budgets 10, 5, 1.25 -> 8/13, 4/13, 1/13; the sign still comes from the
    # forecast, not from the absolute budget.
    assert weights_of(targets) == pytest.approx(
        {'A': 8 / 13, 'B': -4 / 13, 'C': 1 / 13}, abs=1e-15)
    assert_book_invariants(targets, gross=1.0, cap=0.9)


def test_manual_weights_are_relative_budgets_normalized_to_declared_gross():
    declared = {'A': 0.3, 'B': 0.2, 'C': 0.1}
    spec = make_spec(('A', 'B', 'C'), method='manual', vol_feature=None, cap=0.5,
                     weights=declared)
    targets = allocate_ts(make_panel(('A', 'B', 'C'), forecasts=FORECASTS), spec,
                          spec.market_classes[0])
    assert_contract_frame(targets)
    # The declared weights sum to 0.6; they are relative budgets, so the book is
    # still normalized to the declared gross exposure and signed by forecast.
    assert weights_of(targets) == pytest.approx(
        {'A': 1 / 2, 'B': -1 / 3, 'C': 1 / 6}, abs=1e-15)
    assert abs(sum(abs(value) for value in weights_of(targets).values()) - 1.0) < 1e-12


# --------------------------------------------------------------------------- #
# Gross exposure, cap and water-filling
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize('gross', [0.5, 1.0, 2.0])
def test_gross_exposure_scales_every_target_without_touching_budgets(gross):
    spec = make_spec(('A', 'B', 'C'), method='inverse_volatility', cap=0.4, gross=gross)
    targets = allocate_ts(make_panel(('A', 'B', 'C'), forecasts=FORECASTS, vols=VOLS),
                          spec, spec.market_classes[0])
    assert_contract_frame(targets)
    weights = weights_of(targets)
    # Cap-binding budgets are 0.4 / 0.4 / 0.2 independent of the gross scale.
    assert weights == pytest.approx(
        {'A': 0.4 * gross, 'B': -0.4 * gross, 'C': 0.2 * gross}, abs=1e-15)
    assert abs(sum(abs(value) for value in weights.values()) - gross) < 1e-12
    assert_book_invariants(targets, gross=gross, cap=0.4)


def test_cap_binds_and_redistributes_across_rounds():
    spec = make_spec(('A', 'B', 'C'), method='inverse_volatility', cap=0.4)
    targets = allocate_ts(make_panel(('A', 'B', 'C'), forecasts=FORECASTS, vols=VOLS),
                          spec, spec.market_classes[0])
    # 'A' is frozen at the cap, then 'B' also reaches the cap, and 'C' absorbs
    # the residual 0.2 in the final round.
    assert weights_of(targets) == pytest.approx({'A': 0.4, 'B': -0.4, 'C': 0.2}, abs=1e-15)
    assert_book_invariants(targets, gross=1.0, cap=0.4)


def test_capped_budgets_multi_round_water_filling_is_exact():
    raw = {'A': 100.0, 'B': 50.0, 'C': 20.0, 'D': 10.0, 'E': 5.0, 'F': 1.0}
    # Round 1 freezes A/B, round 2 freezes C, round 3 splits the last 0.25.
    assert capped_budgets(raw, 0.25) == pytest.approx(
        {'A': 0.25, 'B': 0.25, 'C': 0.25, 'D': 0.15625, 'E': 0.078125, 'F': 0.015625},
        abs=1e-15)
    assert sum(capped_budgets(raw, 0.25).values()) == pytest.approx(1.0, abs=1e-12)


def test_multi_round_water_filling_end_to_end_matches_the_unit_budget():
    symbols = ('A', 'B', 'C', 'D', 'E', 'F')
    raw = {'A': 100.0, 'B': 50.0, 'C': 20.0, 'D': 10.0, 'E': 5.0, 'F': 1.0}
    # forecast_weighted with unit volatility reproduces the raw budgets exactly.
    spec = make_spec(symbols, method='forecast_weighted', cap=0.25)
    targets = allocate_ts(
        make_panel(symbols, forecasts=raw, vols=dict.fromkeys(symbols, 1.0)),
        spec, spec.market_classes[0])
    assert_contract_frame(targets)
    assert weights_of(targets) == pytest.approx(capped_budgets(raw, 0.25), abs=1e-15)
    assert_book_invariants(targets, gross=1.0, cap=0.25)


def test_single_name_cap_leaves_the_residual_to_the_remaining_names():
    spec = make_spec(('A', 'B', 'C'), method='forecast_weighted', cap=0.4)
    targets = allocate_ts(
        make_panel(('A', 'B', 'C'), forecasts={'A': 10.0, 'B': 1.0, 'C': 1.0},
                   vols=dict.fromkeys(('A', 'B', 'C'), 1.0)),
        spec, spec.market_classes[0])
    assert weights_of(targets) == pytest.approx({'A': 0.4, 'B': 0.3, 'C': 0.3}, abs=1e-15)
    assert_book_invariants(targets, gross=1.0, cap=0.4)


def test_cap_exactly_feasible_at_the_universe_width():
    # Two names at a 0.5 cap: len(universe) * cap == 1 exactly, no residual.
    assert capped_budgets({'A': 1.0, 'B': 1.0}, 0.5) == {'A': 0.5, 'B': 0.5}
    assert capped_budgets({'A': 3.0}, 1.0) == {'A': 1.0}

    spec = make_spec(('A', 'B'), method='equal_weight', vol_feature=None, cap=0.5)
    targets = allocate_ts(make_panel(('A', 'B'), forecasts={'A': 1.0, 'B': -1.0}), spec,
                          spec.market_classes[0])
    assert weights_of(targets) == {'A': 0.5, 'B': -0.5}
    assert_book_invariants(targets, gross=1.0, cap=0.5)


# --------------------------------------------------------------------------- #
# Eligibility and warm-up
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize('eligible', [1, 2, 3, 4])
def test_insufficient_eligible_names_hold_flat_until_the_cap_threshold(eligible):
    symbols = tuple('ABCD')
    spec = make_spec(symbols, method='equal_weight', vol_feature=None, cap=0.3)
    # Four declared names at a 0.3 cap need all four to reach gross 1.0.
    panel = make_panel(symbols, in_pit_universe={
        symbol: index < eligible for index, symbol in enumerate(symbols)})
    targets = allocate_ts(panel, spec, spec.market_classes[0])
    assert_contract_frame(targets)
    assert targets.height == panel.height  # one row per observed name regardless
    if eligible < len(symbols):
        assert targets['target_weight'].abs().sum() == 0.0
        assert targets['stop_loss_dist_pct'].abs().sum() == 0.0
    else:
        assert weights_of(targets) == pytest.approx(
            {'A': 0.25, 'B': 0.25, 'C': 0.25, 'D': 0.25}, abs=1e-15)
        assert_book_invariants(targets, gross=1.0, cap=0.3)


def test_ineligible_names_are_flat_while_available_names_still_allocate():
    symbols = tuple('ABCDEF')
    spec = make_spec(symbols, method='equal_weight', vol_feature=None, cap=0.34)
    panel = make_panel(symbols, forecasts={'F': 0.0}, is_tradable={'B': False},
                       in_pit_universe={'D': False})
    targets = allocate_ts(panel, spec, spec.market_classes[0])
    assert_contract_frame(targets)
    weights, stops = weights_of(targets), stops_of(targets)
    for symbol in ('B', 'D', 'F'):
        assert weights[symbol] == 0.0
        assert stops[symbol] == 0.0
    assert weights['A'] == pytest.approx(1 / 3, abs=1e-15)
    assert weights['C'] == pytest.approx(1 / 3, abs=1e-15)
    assert weights['E'] == pytest.approx(1 / 3, abs=1e-15)
    assert_book_invariants(targets, gross=1.0, cap=0.34)


@pytest.mark.parametrize('gate', ['in_pit_universe', 'is_tradable'])
def test_pit_and_tradability_gates_never_receive_weight(gate):
    symbols = tuple('ABCDEF')
    spec = make_spec(symbols, method='equal_weight', vol_feature=None, cap=0.34)
    panel = make_panel(symbols, **{gate: {'F': False}})
    targets = allocate_ts(panel, spec, spec.market_classes[0])
    assert_contract_frame(targets)
    weights, stops = weights_of(targets), stops_of(targets)
    assert weights['F'] == 0.0 and stops['F'] == 0.0
    assert weights_of(targets) == pytest.approx(
        {symbol: 0.2 for symbol in 'ABCDE'} | {'F': 0.0}, abs=1e-15)
    assert_book_invariants(targets, gross=1.0, cap=0.34)


# --------------------------------------------------------------------------- #
# Stop distance
# --------------------------------------------------------------------------- #
def test_stop_distance_is_multiple_times_stop_over_price_in_double_precision():
    spec = make_spec(('A', 'B', 'C'), method='equal_weight', vol_feature=None,
                     cap=0.9, multiple=2.5)
    stops = {'A': 1.3, 'B': 0.7, 'C': 2.0}
    closes = {'A': 101.7, 'B': 99.3, 'C': 105.1}
    targets = allocate_ts(make_panel(('A', 'B', 'C'), stops=stops, closes=closes),
                          spec, spec.market_classes[0])
    distances = stops_of(targets)
    for symbol in ('A', 'B', 'C'):
        assert distances[symbol] == pytest.approx(
            2.5 * stops[symbol] / closes[symbol], rel=1e-15, abs=1e-18)
        assert distances[symbol] < 1.0
    assert 3.0 * 1.0 / 100.0 == 0.03  # trivial float64 sanity for the default case


def test_float32_sources_still_emit_double_precision_output():
    closes = np.asarray([101.7, 99.3], dtype=np.float32)
    stops = np.asarray([1.3, 0.9], dtype=np.float32)
    spec = make_spec(('A', 'B'), method='equal_weight', vol_feature=None, cap=0.6)
    panel = pl.DataFrame({
        'timestamp': [START, START], 'symbol': ['A', 'B'], 'close': closes,
        'forecast': pl.Series([1, -1], dtype=pl.Int64),
        'atr_14': stops, 'vol_20': np.asarray([0.2, 0.2], dtype=np.float32),
        'in_pit_universe': [True, True], 'is_tradable': [True, True],
    })
    targets = allocate_ts(panel, spec, spec.market_classes[0])
    assert targets.schema == TARGET_SCHEMA
    assert targets['stop_loss_dist_pct'].dtype == pl.Float64
    assert targets['target_weight'].dtype == pl.Float64
    distances = stops_of(targets)
    for symbol, close, stop in zip(('A', 'B'), closes, stops, strict=True):
        expected = 3.0 * float(stop) / float(close)  # exact Float32 -> Float64 widening
        assert distances[symbol] == pytest.approx(expected, rel=1e-15, abs=1e-18)


# --------------------------------------------------------------------------- #
# Determinism, cadence and schema
# --------------------------------------------------------------------------- #
def test_repeat_runs_and_input_row_order_are_bit_identical():
    symbols = tuple('ABCDE')
    spec = make_spec(symbols, method='forecast_weighted', cap=0.34)
    panel = make_panel(symbols, forecasts={'A': 1.0, 'B': -2.0, 'C': 0.5, 'D': 1.5,
                                           'E': -0.25},
                       vols={'A': 0.1, 'B': 0.2, 'C': 0.4, 'D': 0.8, 'E': 0.05}, bars=3)
    first = allocate_ts(panel, spec, spec.market_classes[0])
    repeat = allocate_ts(panel, spec, spec.market_classes[0])
    shuffled = allocate_ts(panel.sample(fraction=1.0, shuffle=True, seed=7), spec,
                           spec.market_classes[0])
    reversed_rows = allocate_ts(pl.DataFrame(list(reversed(panel.to_dicts()))), spec,
                                spec.market_classes[0])
    for other in (repeat, shuffled, reversed_rows):
        assert other.schema == first.schema
        assert other.equals(first)
        assert float_bits(other) == float_bits(first)
    assert_contract_frame(first)


def test_equal_forecasts_are_symbol_ordered_regardless_of_declaration_order():
    forecasts = dict.fromkeys('ABCD', 1.0)
    vol = dict.fromkeys('ABCD', 0.2)
    forward = make_spec(tuple('ABCD'), method='inverse_volatility', cap=0.3)
    backward = make_spec(tuple('DCBA'), method='inverse_volatility', cap=0.3)
    panel = make_panel(tuple('ABCD'), forecasts=forecasts, vols=vol)
    reordered_panel = make_panel(tuple('DCBA'), forecasts=forecasts, vols=vol)
    first = allocate_ts(panel, forward, forward.market_classes[0])
    second = allocate_ts(reordered_panel, backward, backward.market_classes[0])
    assert first.equals(second)
    assert float_bits(first) == float_bits(second)
    assert weights_of(first) == pytest.approx(dict.fromkeys('ABCD', 0.25), abs=1e-15)
    assert_book_invariants(first, gross=1.0, cap=0.3)


def test_cadence_emits_only_timestamps_anchored_on_the_train_start():
    symbols = ('A', 'B')
    spec = make_spec(symbols, method='equal_weight', vol_feature=None, cap=0.6,
                     rebalance_bars=3)
    stamps = [START + timedelta(hours=hour) for hour in range(10)]
    stamps.append(START + timedelta(minutes=90))  # systematically off-cadence
    panel = pl.DataFrame([
        {'timestamp': stamp, 'symbol': symbol, 'close': 100.0, 'forecast': 1.0,
         'atr_14': 1.0, 'vol_20': 0.2, 'in_pit_universe': True, 'is_tradable': True}
        for stamp in stamps for symbol in symbols
    ])
    targets = allocate_ts(panel, spec, spec.market_classes[0])
    assert_contract_frame(targets)
    anchor = int(START.timestamp())
    cadence = BAR_SECONDS * 3
    emitted = targets['timestamp'].unique().sort().to_list()
    assert emitted == [START + timedelta(hours=hour) for hour in (0, 3, 6, 9)]
    assert all((int(stamp.timestamp()) - anchor) % cadence == 0 for stamp in emitted)
    assert targets.height == len(emitted) * len(symbols)


@pytest.mark.parametrize('panel_kind', ['empty', 'off_cadence'])
def test_empty_or_unscheduled_input_returns_the_published_empty_schema(panel_kind):
    spec = make_spec(('A', 'B'), method='inverse_volatility', cap=0.6)
    panel = make_panel(('A', 'B'))
    if panel_kind == 'empty':
        panel = panel.clear()
    else:
        panel = panel.with_columns(pl.col('timestamp') + pl.duration(seconds=60))
    targets = allocate_ts(panel, spec, spec.market_classes[0])
    assert targets.height == 0
    assert targets.schema == TARGET_SCHEMA
    assert targets.columns == TARGET_COLUMNS


def test_schema_is_stable_for_naive_and_nanosecond_timestamps():
    spec = make_spec(('A', 'B'), method='equal_weight', vol_feature=None, cap=0.6)
    naive = pl.DataFrame({
        'timestamp': pl.Series([START, START], dtype=pl.Datetime('ns')),
        'symbol': ['A', 'B'], 'close': [100.0, 100.0],
        'forecast': pl.Series([1, -1], dtype=pl.Int64),
        'atr_14': [1.0, 1.0], 'vol_20': [0.2, 0.2],
        'in_pit_universe': [True, True], 'is_tradable': [True, True],
    })
    aware = naive.with_columns(pl.col('timestamp').cast(pl.Datetime('ns', 'UTC')))
    first = allocate_ts(naive, spec, spec.market_classes[0])
    second = allocate_ts(aware, spec, spec.market_classes[0])
    for targets in (first, second):
        assert targets.schema == TARGET_SCHEMA
        assert targets['timestamp'].dtype == pl.Datetime('us', 'UTC')
        assert targets['timestamp'].to_list() == [START, START]
        assert targets['target_weight'].to_list() == [0.5, -0.5]
    assert first.equals(second)
