from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from src.data_vault.panel_builder import validate_panel
from src.engine.common import QuantError, file_hash
from src.engine.cost_qualification import qualify_costs, run_qualified_ts
from src.engine.ts_spec import TimeSeriesSpec

START = datetime(2020, 1, 1, tzinfo=UTC)
BARS = 40
SYMBOLS = ('A', 'B')
PRICE_ONLY = {'quality_summary': {'execution_qualified': False,
                                  'source_provenance': 'price-only, no financing/spread certification'}}


def make_spec() -> TimeSeriesSpec:
    return TimeSeriesSpec.model_validate({
        'spec_kind': 'time_series',
        'sleeve_id': 'af30_cost_qualification',
        'selection_family_id': 'af30_time_series',
        'book_strategy': 11,
        'thesis': 'Cost qualification gate test.',
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
        for symbol, weight in (('A', 0.5), ('B', -0.5)):
            rows.append({'timestamp': timestamp, 'symbol': symbol,
                         'target_weight': weight, 'stop_loss_dist_pct': 0.05})
    return pl.DataFrame(rows, schema={'timestamp': pl.Datetime('us', 'UTC'), 'symbol': pl.String,
                                      'target_weight': pl.Float64, 'stop_loss_dist_pct': pl.Float64})


def make_events() -> pl.DataFrame:
    timestamp = START + timedelta(hours=5)
    return pl.DataFrame({
        'timestamp': [timestamp, timestamp],
        'symbol': list(SYMBOLS),
        'funding_rate': [0.0002, 0.0002],
        'mark_price': [100.2, 100.7],
        'curve_at': [START, START],
        'mark_at': [timestamp - timedelta(hours=1)] * 2,
        'curve_name': ['US10Y', 'US10Y'],
    })


MODELED = {'status': 'MODELED', 'curve': {'name': 'US10Y'},
           'sign_convention': 'positive_rate_charges_longs'}


def test_price_only_index_sleeve_reaches_native_pnl():
    spec = make_spec()
    result = run_qualified_ts(make_panel(), make_targets(), spec, spec.market_classes[0],
                             vault_manifest=PRICE_ONLY, carry_events=make_events(),
                             carry_metadata=MODELED)
    assert result.metrics['independent_accounting']['status'] == 'PASS'
    qualification = result.metrics['cost_qualification']
    assert qualification['status'] == 'DECLARED_ASSUMPTIONS'
    assert qualification['carry_status'] == 'MODELED'
    assert any('commission_bps_one_way=1.0' in line for line in qualification['assumptions'])


def test_unmodeled_financing_is_refused_with_a_named_reason(monkeypatch):
    spec = make_spec()
    called = []
    monkeypatch.setattr('src.engine.cost_qualification.run_native_ts',
                        lambda *a, **k: called.append(1))
    with pytest.raises(QuantError) as exc:
        run_qualified_ts(make_panel(), make_targets(), spec, spec.market_classes[0],
                         vault_manifest=PRICE_ONLY, carry_events=make_events(),
                         carry_metadata={'status': 'UNKNOWN_NOT_MODELLED'})
    assert exc.value.status == 'BLOCKED_DATA'
    assert 'UNKNOWN_NOT_MODELLED' in exc.value.reason
    assert called == []


def test_rejected_qualification_writes_no_artifact_and_consumes_no_claim(tmp_path: Path, monkeypatch):
    claim = tmp_path / 'claims' / 'holdout.claim'
    claim.parent.mkdir()
    claim.write_bytes(b'reserved-once')
    before = file_hash(claim)
    workspace = tmp_path / 'run_log'
    monkeypatch.setattr('src.engine.cost_qualification.run_native_ts', lambda *a, **k: None)
    with pytest.raises(QuantError):
        run_qualified_ts(make_panel(), make_targets(), make_spec(), make_spec().market_classes[0],
                         vault_manifest=PRICE_ONLY, carry_events=None, carry_metadata=None)
    assert file_hash(claim) == before
    assert list(workspace.rglob('*')) == []


def test_execution_qualified_vault_passes_without_carry():
    spec = make_spec()
    manifest = {'quality_summary': {'execution_qualified': True}}
    result = run_qualified_ts(make_panel(), make_targets(), spec, spec.market_classes[0],
                              vault_manifest=manifest)
    assert result.metrics['cost_qualification']['status'] == 'EXECUTION_QUALIFIED'
    assert result.metrics['cost_qualification']['carry_status'] == 'NOT_APPLIED'
    assert result.metrics['independent_accounting']['status'] == 'PASS'


def test_manifest_without_declaration_is_blocked():
    with pytest.raises(QuantError) as exc:
        qualify_costs(make_spec(), make_spec().market_classes[0], vault_manifest={})
    assert exc.value.status == 'BLOCKED_DATA'


def test_unvalidated_zero_cost_copy_is_rejected():
    spec = make_spec()
    zero = spec.costs.model_copy(update={'commission_bps_one_way': 0.0})
    tampered = spec.model_copy(update={'costs': zero})
    with pytest.raises(QuantError) as exc:
        qualify_costs(tampered, tampered.market_classes[0], vault_manifest=PRICE_ONLY,
                      carry_metadata=MODELED)
    assert exc.value.status == 'INVALID_SPEC'


def test_qualification_hash_is_stable_and_cost_sensitive():
    spec = make_spec()
    first = qualify_costs(spec, spec.market_classes[0], vault_manifest=PRICE_ONLY,
                          carry_metadata=MODELED)
    second = qualify_costs(spec, spec.market_classes[0], vault_manifest=PRICE_ONLY,
                           carry_metadata=MODELED)
    assert first.sha256 == second.sha256
    dearer = spec.model_copy(update={
        'costs': spec.costs.model_copy(update={'slippage_bps_one_way': 2.0}),
    })
    assert qualify_costs(dearer, dearer.market_classes[0], vault_manifest=PRICE_ONLY,
                         carry_metadata=MODELED).sha256 != first.sha256
