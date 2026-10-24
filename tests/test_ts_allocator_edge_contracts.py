"""Edge-case contract for the time-series ATS target allocator.

``tests/test_ts_allocator_contract.py`` pins the main allocation invariants.
This module covers the degraded inputs and the exact rejection precedence:

* null/NaN/inf/zero forecasts, stops and volatilities never receive weight;
* a stop multiple that reaches the decision price is ineligible, with the two
  immediate float neighbours proving the strict inequality;
* a subnormal stop makes the stop distance unrepresentable and is rejected;
* an unreachable declared cap and degenerate raw budgets raise
  ``INVALID_ALLOCATION``;
* duplicate ``(timestamp, symbol)`` rows are malformed upstream input: the
  observed (historical) behaviour is stated explicitly rather than blessed as
  supported;
* error precedence is declared-cap first, then first rebalance in panel order,
  and repeated runs raise the identical error;
* empty frames and only-ineligible frames keep the published schema;
* gross/cap invariants hold on every non-flat section of a mixed panel.

Synthetic fixtures only: no vault, protected window, casefile or market
evidence.
"""
from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import polars as pl
import pytest

from src.engine.common import QuantError
from src.engine.signal_allocator import TARGET_COLUMNS
from src.engine.ts_allocator import allocate_ts, capped_budgets
from src.engine.ts_spec import TimeSeriesSpec

START = datetime(2020, 1, 1, tzinfo=UTC)
BAR = datetime(2020, 1, 1, 0, 0, tzinfo=UTC)
TARGET_SCHEMA = {
    'timestamp': pl.Datetime('us', 'UTC'), 'symbol': pl.String,
    'target_weight': pl.Float64, 'stop_loss_dist_pct': pl.Float64,
}
MIN_POSITIVE = float(np.nextafter(0.0, 1.0))  # 5e-324, smallest subnormal


def make_spec(symbols: tuple[str, ...] = ('A', 'B', 'C'), *,
              method: str = 'inverse_volatility', vol_feature: str | None = 'vol_20',
              cap: float = 0.4, gross: float = 1.0, weights: dict[str, float] | None = None,
              multiple: float = 3.0) -> TimeSeriesSpec:
    risk = {'method': method, 'per_instrument_cap': cap, 'gross_exposure': gross,
            'volatility_feature': vol_feature, 'weights': weights}
    payload = {
        'spec_kind': 'time_series',
        'sleeve_id': 'ts_allocator_edge',
        'selection_family_id': 'ts_allocator_edge',
        'book_strategy': 6,
        'thesis': 'Allocator edge fixture; never market evidence.',
        'market_classes': [{
            'name': 'indices', 'symbols': list(symbols),
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
            {'name': 'vol_20', 'expr': {'op': 'col', 'name': 'close'}},
        ],
        'forecast': {'feature': 'f', 'horizon_bars': 1,
                     'scaling': {'kind': 'bounded_linear', 'scale': 10.0, 'cap': 2.0}},
        'risk_allocation': risk,
        'stops': {'feature': 'atr_14', 'multiple': multiple},
        'costs': {'commission_bps_one_way': 1.0, 'slippage_bps_one_way': 1.0,
                  'spread_bps': 0.0, 'spread_included_in_slippage': True},
    }
    return TimeSeriesSpec.model_validate(payload)


def overridden(symbols: tuple[str, ...], field: str, bad_value: object,
               default: object) -> dict[str, object]:
    """Every symbol keeps ``default`` except ``F``, which takes ``bad_value``."""
    return {symbol: (bad_value if symbol == 'F' else default) for symbol in symbols}


def make_panel(symbols: tuple[str, ...], *, forecasts: object = 1.0,
               stops: object = 1.0, closes: object = 100.0,
               vols: object = 0.2, in_pit_universe: object = True,
               is_tradable: object = True) -> pl.DataFrame:
    def per(symbol: str, value: object, default: object) -> object:
        if value is None:
            return default
        if isinstance(value, dict):
            return value.get(symbol, default)
        return value

    return pl.DataFrame([
        {
            'timestamp': START,
            'symbol': symbol,
            'close': per(symbol, closes, 100.0),
            'forecast': per(symbol, forecasts, 1.0),
            'atr_14': per(symbol, stops, 1.0),
            'vol_20': per(symbol, vols, 0.2),
            'in_pit_universe': per(symbol, in_pit_universe, True),
            'is_tradable': per(symbol, is_tradable, True),
        }
        for symbol in symbols
    ])


def weights_by_symbol(targets: pl.DataFrame) -> dict[str, float]:
    return dict(zip(targets['symbol'].to_list(),
                    targets['target_weight'].to_list(), strict=True))


def stops_by_symbol(targets: pl.DataFrame) -> dict[str, float]:
    return dict(zip(targets['symbol'].to_list(),
                    targets['stop_loss_dist_pct'].to_list(), strict=True))


def section_stats(targets: pl.DataFrame) -> list[dict[str, object]]:
    stats = targets.group_by('timestamp', maintain_order=True).agg(
        pl.col('target_weight').abs().sum().alias('gross'),
        pl.col('target_weight').abs().max().alias('peak'),
        pl.col('stop_loss_dist_pct').abs().max().alias('max_stop'),
    )
    return list(stats.sort('timestamp').iter_rows(named=True))


SIX = tuple('ABCDEF')


def six_symbol_spec(**overrides: object) -> TimeSeriesSpec:
    settings = {'method': 'inverse_volatility', 'vol_feature': 'vol_20', 'cap': 0.34}
    settings.update(overrides)
    return make_spec(SIX, **settings)


# --------------------------------------------------------------------------- #
# Degenerate feature values
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize('bad_value', [None, float('nan'), float('inf'),
                                       float('-inf'), 0.0])
def test_non_positive_or_non_finite_forecasts_are_ineligible(bad_value):
    spec = six_symbol_spec()
    panel = make_panel(SIX, forecasts=overridden(SIX, 'forecast', bad_value, 1.0))
    targets = allocate_ts(panel, spec, spec.market_classes[0])
    weights, stops = weights_by_symbol(targets), stops_by_symbol(targets)
    assert weights['F'] == 0.0 and stops['F'] == 0.0
    # Five eligible names at a 0.34 cap: 1/5 each, fully invested.
    assert {symbol: weights[symbol] for symbol in 'ABCDE'} == pytest.approx(
        dict.fromkeys('ABCDE', 0.2), abs=1e-15)
    assert targets['target_weight'].abs().sum() == pytest.approx(1.0, abs=1e-12)


@pytest.mark.parametrize('bad_value', [None, float('nan'), float('inf'), -1.0, 0.0])
def test_non_positive_or_non_finite_stops_are_ineligible(bad_value):
    spec = six_symbol_spec()
    panel = make_panel(SIX, stops=overridden(SIX, 'stop', bad_value, 1.0))
    targets = allocate_ts(panel, spec, spec.market_classes[0])
    weights, stops = weights_by_symbol(targets), stops_by_symbol(targets)
    assert weights['F'] == 0.0 and stops['F'] == 0.0
    assert {symbol: weights[symbol] for symbol in 'ABCDE'} == pytest.approx(
        dict.fromkeys('ABCDE', 0.2), abs=1e-15)


def test_subnormal_stop_makes_the_distance_unrepresentable_and_is_rejected():
    # A subnormal stop is finite and positive, so it passes the eligibility
    # filter, but multiple * stop / close underflows to 0.0. A zero stop
    # distance is not a legal target, so the rebalance raises instead of
    # silently publishing a zero stop.
    spec = make_spec(tuple('ABCDE'), method='equal_weight', vol_feature=None, cap=0.34)
    panel = make_panel(tuple('ABCDE'), stops={'E': MIN_POSITIVE})
    for _ in range(2):
        with pytest.raises(QuantError) as excinfo:
            allocate_ts(panel, spec, spec.market_classes[0])
        assert excinfo.value.status == 'INVALID_ALLOCATION'
        assert 'stop distance' in excinfo.value.reason


@pytest.mark.parametrize('method', ['inverse_volatility', 'forecast_weighted'])
@pytest.mark.parametrize('bad_value', [None, float('nan'), float('inf'), 0.0, -0.2])
def test_non_positive_or_non_finite_volatility_is_ineligible(method, bad_value):
    spec = six_symbol_spec(method=method)
    panel = make_panel(SIX, vols=overridden(SIX, 'vol', bad_value, 0.2))
    targets = allocate_ts(panel, spec, spec.market_classes[0])
    weights, stops = weights_by_symbol(targets), stops_by_symbol(targets)
    assert weights['F'] == 0.0 and stops['F'] == 0.0
    # Equal forecast and equal volatility leave five equal budgets on both methods.
    assert {symbol: weights[symbol] for symbol in 'ABCDE'} == pytest.approx(
        dict.fromkeys('ABCDE', 0.2), abs=1e-15)


# --------------------------------------------------------------------------- #
# Stop-at-price boundary
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize('label, stop', [
    ('exactly_at_price', 50.0),
    ('just_below', float(np.nextafter(50.0, 0.0))),
    ('just_above', float(np.nextafter(50.0, float('inf')))),
])
def test_stop_multiple_at_the_decision_price_is_ineligible(label, stop):
    symbols = tuple('ABCD')
    spec = make_spec(symbols, method='equal_weight', vol_feature=None, cap=0.34,
                     multiple=2.0)
    panel = make_panel(symbols, stops={'D': stop})
    targets = allocate_ts(panel, spec, spec.market_classes[0]).sort('symbol')
    weights, distances = weights_by_symbol(targets), stops_by_symbol(targets)
    assert targets.schema == TARGET_SCHEMA
    if label == 'just_below':
        # 2 * stop < close, so the name is eligible with a sub-1.0 distance.
        assert weights['D'] == pytest.approx(0.25, abs=1e-15)
        assert distances['D'] == pytest.approx(2.0 * stop / 100.0, rel=1e-15)
        assert distances['D'] < 1.0
    else:
        # 2 * stop >= close disqualifies the name; the other three still allocate.
        assert weights['D'] == 0.0 and distances['D'] == 0.0
        for symbol in 'ABC':
            assert weights[symbol] == pytest.approx(1 / 3, abs=1e-15)
    assert targets['target_weight'].abs().sum() == pytest.approx(1.0, abs=1e-12)


# --------------------------------------------------------------------------- #
# Rejected books
# --------------------------------------------------------------------------- #
def test_unreachable_declared_cap_raises_before_reading_any_rebalance():
    # Two declared names at a 0.4 cap cannot reach gross 1.0 at all, so the
    # declaration itself is invalid even when the scheduled rows are all
    # ineligible.
    spec = make_spec(('A', 'B'), method='equal_weight', vol_feature=None, cap=0.4)
    panel = make_panel(('A', 'B'), forecasts=0.0, in_pit_universe=False,
                       is_tradable=False)
    with pytest.raises(QuantError) as excinfo:
        allocate_ts(panel, spec, spec.market_classes[0])
    assert excinfo.value.status == 'INVALID_ALLOCATION'
    assert 'caps' in excinfo.value.reason

    # The same declaration wins over a per-rebalance stop error later in the
    # panel: the declared-universe check precedes the rebalance loop.
    stop_broken = make_panel(tuple('ABC'), stops={'C': MIN_POSITIVE})
    with pytest.raises(QuantError) as excinfo:
        allocate_ts(stop_broken, spec, spec.market_classes[0])
    assert 'caps' in excinfo.value.reason


def test_unreachable_cap_is_not_evaluated_without_a_scheduled_rebalance():
    # The scheduler runs first: no aligned timestamp means an empty target frame
    # rather than a declaration error. Documented, not an endorsement.
    spec = make_spec(('A', 'B'), method='equal_weight', vol_feature=None, cap=0.4)
    panel = make_panel(('A', 'B')).with_columns(
        pl.col('timestamp') + pl.duration(minutes=30))
    targets = allocate_ts(panel, spec, spec.market_classes[0])
    assert targets.height == 0
    assert targets.schema == TARGET_SCHEMA


def test_degenerate_raw_budgets_raise_invalid_allocation():
    for raw in ({'A': 0.0, 'B': 0.0}, {'A': -1.0, 'B': -1.0},
                {'A': float('inf'), 'B': 1.0}):
        with pytest.raises(QuantError) as excinfo:
            capped_budgets(raw, 0.5)
        assert excinfo.value.status == 'INVALID_ALLOCATION'
        assert 'finite and positive' in excinfo.value.reason

    # A zero residual pool cannot absorb what the capped names leave behind.
    with pytest.raises(QuantError) as excinfo:
        capped_budgets({'A': 1.0, 'B': 0.0}, 0.5)
    assert excinfo.value.status == 'INVALID_ALLOCATION'
    assert 'Zero uncapped budgets' in excinfo.value.reason

    with pytest.raises(QuantError) as excinfo:
        capped_budgets({'A': 1.0}, 0.5)
    assert excinfo.value.status == 'INVALID_ALLOCATION'
    assert 'unreachable' in excinfo.value.reason

    assert capped_budgets({}, 0.5) == {}


# --------------------------------------------------------------------------- #
# Malformed input and error precedence
# --------------------------------------------------------------------------- #
def test_duplicate_timestamp_symbol_rows_are_malformed_but_documented():
    """Duplicate rows are an upstream contract violation, not a supported mode.

    The allocator keys the book by symbol, so a repeated (timestamp, symbol)
    pair emits one output row per input row and both twins inherit the same
    assignment - including an ineligible twin. The published gross is therefore
    over-allocated relative to the declaration. This pins the observed
    (historical) behaviour so a refactor does not silently change it; producers
    must emit one row per (timestamp, symbol).
    """
    symbols = tuple('ABCD')
    spec = make_spec(symbols, method='equal_weight', vol_feature=None, cap=0.34)
    panel = pl.DataFrame({
        'timestamp': [START] * 4, 'symbol': ['A', 'A', 'B', 'C'],
        'close': [100.0] * 4, 'forecast': [1.0, 0.0, 1.0, -1.0],
        'atr_14': [1.0] * 4, 'vol_20': [0.2] * 4,
        'in_pit_universe': [True] * 4, 'is_tradable': [True] * 4,
    })
    targets = allocate_ts(panel, spec, spec.market_classes[0])
    assert targets.schema == TARGET_SCHEMA
    assert targets.height == panel.height  # row multiplicity is preserved
    weights = weights_by_symbol(targets)
    assert weights['A'] == pytest.approx(1 / 3, abs=1e-15)
    assert sorted(targets['symbol'].to_list()) == ['A', 'A', 'B', 'C']
    assert weights['B'] == pytest.approx(1 / 3, abs=1e-15)
    assert weights['C'] == pytest.approx(-1 / 3, abs=1e-15)
    # Malformed input: the realized gross (4/3) exceeds the declared 1.0.
    assert targets['target_weight'].abs().sum() == pytest.approx(4 / 3, abs=1e-12)


def test_error_precedence_across_timestamps_is_deterministic():
    symbols = tuple('ABCDE')
    spec = make_spec(symbols, method='equal_weight', vol_feature=None, cap=0.34)
    early = make_panel(symbols, stops={'E': MIN_POSITIVE})
    late = make_panel(symbols, stops={'E': MIN_POSITIVE}).with_columns(
        pl.col('timestamp') + pl.duration(hours=1))
    clean = make_panel(symbols)
    for panel in (pl.concat([clean, late]), pl.concat([late, clean])):
        outcomes = []
        for _ in range(2):
            with pytest.raises(QuantError) as excinfo:
                allocate_ts(panel, spec, spec.market_classes[0])
            outcomes.append((excinfo.value.status, excinfo.value.reason))
        assert outcomes[0] == outcomes[1]
        assert outcomes[0][0] == 'INVALID_ALLOCATION'
        assert 'stop distance' in outcomes[0][1]
    # Row order inside the offending rebalance does not change the outcome.
    shuffled = early.sample(fraction=1.0, shuffle=True, seed=3)
    with pytest.raises(QuantError) as shuffled_exc:
        allocate_ts(shuffled, spec, spec.market_classes[0])
    with pytest.raises(QuantError) as ordered_exc:
        allocate_ts(early, spec, spec.market_classes[0])
    assert (shuffled_exc.value.status, shuffled_exc.value.reason) == (
        ordered_exc.value.status, ordered_exc.value.reason)


# --------------------------------------------------------------------------- #
# Empty / flat frames and per-section invariants
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize('extra_name', ['_row', '_ats_row_index', '_ats_eligible'])
def test_internal_temporary_column_names_do_not_collide_with_input(extra_name):
    symbols = tuple('ABCD')
    spec = make_spec(symbols, method='equal_weight', vol_feature=None, cap=0.34)
    baseline = allocate_ts(make_panel(symbols), spec, spec.market_classes[0])
    panel = make_panel(symbols).with_columns(pl.lit(7).alias(extra_name))

    actual = allocate_ts(panel, spec, spec.market_classes[0])

    assert actual.equals(baseline)


def test_empty_and_only_ineligible_frames_keep_the_published_contract():
    symbols = tuple('ABCD')
    spec = make_spec(symbols, method='equal_weight', vol_feature=None, cap=0.34)
    empty = make_panel(symbols).clear()
    empty_targets = allocate_ts(empty, spec, spec.market_classes[0])
    assert empty_targets.height == 0
    assert empty_targets.schema == TARGET_SCHEMA
    assert empty_targets.columns == TARGET_COLUMNS

    blocked = make_panel(symbols, in_pit_universe=False, is_tradable=False)
    blocked_targets = allocate_ts(blocked, spec, spec.market_classes[0])
    assert blocked_targets.height == blocked.height
    assert blocked_targets.schema == TARGET_SCHEMA
    assert blocked_targets['target_weight'].abs().max() == 0.0
    assert blocked_targets['stop_loss_dist_pct'].abs().max() == 0.0


def test_gross_and_cap_invariants_hold_on_every_non_flat_section():
    symbols = tuple('ABCDE')
    spec = make_spec(symbols, method='equal_weight', vol_feature=None, cap=0.34)
    eligible_plan = {0: 'AB', 1: 'ABCDE', 2: '', 3: 'ABCE', 4: 'ABCDE'}
    rows = [
        {'timestamp': BAR.replace(hour=bar), 'symbol': symbol, 'close': 100.0,
         'forecast': -1.0 if symbol == 'A' else 1.0,
         'atr_14': 1.0, 'vol_20': 0.2,
         'in_pit_universe': symbol in eligible, 'is_tradable': True}
        for bar, eligible in eligible_plan.items()
        for symbol in symbols
    ]
    panel = pl.DataFrame(rows)
    targets = allocate_ts(panel, spec, spec.market_classes[0])
    assert targets.schema == TARGET_SCHEMA
    assert targets.height == panel.height
    stats = section_stats(targets)
    assert [row['gross'] for row in stats] == pytest.approx(
        [0.0, 1.0, 0.0, 1.0, 1.0], abs=1e-9)
    for row in stats:
        if row['gross'] == 0.0:
            assert row['peak'] == 0.0
            assert row['max_stop'] == 0.0
            continue
        assert abs(row['gross'] - 1.0) < 1e-9
        assert row['peak'] <= 0.34 + 1e-12
        assert row['max_stop'] == pytest.approx(3.0 * 1.0 / 100.0, abs=1e-15)
