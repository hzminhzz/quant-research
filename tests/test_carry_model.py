from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from src.engine.carry_model import (
    CarryConfig,
    CarryProduct,
    build_carry_sidecar,
    carry_cashflow,
    load_rate_curve,
)
from src.engine.common import QuantError, file_hash

START = datetime(2020, 1, 1, tzinfo=UTC)
END = datetime(2020, 1, 6, tzinfo=UTC)
CONFIG = CarryConfig(curve_name='US10Y', tenor='US10Y')


def curve(rows: list[tuple[int, float]]) -> pl.DataFrame:
    return pl.DataFrame({
        'timestamp': [datetime(2019, 12, 31, tzinfo=UTC) if day == 0
                      else datetime(2020, 1, day, tzinfo=UTC) for day, _ in rows],
        'rate_pct': [rate for _, rate in rows],
    })


def prices(symbols: tuple[str, ...] = ('DAX', 'NQ')) -> pl.DataFrame:
    rows = []
    for symbol in symbols:
        instant = START - timedelta(hours=1)
        index = 0
        while instant < END:
            rows.append({'timestamp': instant, 'symbol': symbol,
                         'close': 100.0 + index * 0.01})
            instant += timedelta(hours=1)
            index += 1
    return pl.DataFrame(rows).sort('symbol', 'timestamp')


DAX = CarryProduct(symbol='DAX', class_name='indices', kind='spot_cfd', income_yield_bps=0.0)
NQ = CarryProduct(symbol='NQ', class_name='indices', kind='spot_cfd', income_yield_bps=100.0)
GOLD = CarryProduct(symbol='XAUUSD', class_name='metals', kind='spot_cfd')


def test_positive_rate_charges_longs_and_pays_shorts():
    assert carry_cashflow(10.0, 100.0, 0.0001) == pytest.approx(-0.1)
    assert carry_cashflow(-10.0, 100.0, 0.0001) == pytest.approx(0.1)
    assert carry_cashflow(10.0, 100.0, -0.0001) == pytest.approx(0.1)


def test_daily_rate_and_income_adjustment():
    sidecar = build_carry_sidecar(prices(), curve([(0, 5.0), (1, 5.0), (2, 5.0), (3, 5.0)]),
                                  [DAX, NQ], CONFIG, start=START, end=END)
    latest = sidecar.events.filter(pl.col('timestamp') == datetime(2020, 1, 4, tzinfo=UTC))
    rates = dict(zip(latest['symbol'], latest['funding_rate']))
    assert rates['DAX'] == pytest.approx(0.05 / 365, abs=1e-15)
    assert rates['NQ'] == pytest.approx((0.05 - 0.01) / 365, abs=1e-15)


def test_curve_and_mark_reads_never_use_the_settlement_bar():
    sidecar = build_carry_sidecar(prices(), curve([(0, 4.0), (1, 5.0), (2, 10.0), (3, 20.0)]),
                                  [DAX], CONFIG, start=START, end=END)
    row = sidecar.events.filter(pl.col('timestamp') == datetime(2020, 1, 2, tzinfo=UTC)).row(0, named=True)
    assert row['curve_at'] == datetime(2020, 1, 1, tzinfo=UTC)
    assert row['mark_at'] == datetime(2020, 1, 1, 23, tzinfo=UTC)
    assert row['funding_rate'] == pytest.approx(0.05 / 365, abs=1e-15)


def test_continuous_futures_are_rejected_as_double_charge():
    product = CarryProduct(symbol='ES', class_name='indices', kind='continuous_future')
    with pytest.raises(QuantError) as exc:
        build_carry_sidecar(prices(symbols=('ES',)), curve([(1, 5.0)]), [product],
                            CONFIG, start=START, end=END)
    assert exc.value.status == 'INVALID_SPEC'
    assert 'double-charge' in exc.value.reason


def test_metal_without_lease_proxy_is_blocked_not_zero():
    with pytest.raises(QuantError) as exc:
        build_carry_sidecar(prices(symbols=('XAUUSD',)), curve([(0, 5.0), (1, 5.0)]), [GOLD],
                            CONFIG, start=START, end=END)
    assert exc.value.status == 'BLOCKED_DATA'
    assert 'lease-rate proxy' in exc.value.reason


def test_missing_curve_dataset_is_blocked(tmp_path: Path):
    with pytest.raises(QuantError) as exc:
        load_rate_curve(tmp_path, 'US30Y', start=START, end=END)
    assert exc.value.status == 'BLOCKED_DATA'


def test_load_rate_curve_reads_partitions_and_filters_window(tmp_path: Path):
    partition = tmp_path / 'bonds_daily_US10Y' / 'year=2020' / 'month=1' / 'data.parquet'
    partition.parent.mkdir(parents=True)
    pl.DataFrame({
        'timestamp': [datetime(2020, 1, 1, tzinfo=UTC), datetime(2020, 1, 2, tzinfo=UTC),
                      datetime(2020, 1, 7, tzinfo=UTC)],
        'symbol': ['US10Y'] * 3,
        'open': [1.5, 1.6, 1.7], 'high': [1.5, 1.6, 1.7],
        'low': [1.5, 1.6, 1.7], 'close': [1.5, 1.6, 1.7], 'volume': [0.0, 0.0, 0.0],
    }).write_parquet(partition)
    loaded = load_rate_curve(tmp_path, 'US10Y',
                             start=datetime(2020, 1, 2, tzinfo=UTC), end=END)
    assert loaded.height == 2
    assert loaded['rate_pct'].to_list() == [1.5, 1.6]


def test_sidecar_hash_is_stable_and_assumption_sensitive():
    data, rates = prices(), curve([(0, 5.0), (1, 5.0), (2, 5.0)])
    first = build_carry_sidecar(data, rates, [DAX, NQ], CONFIG, start=START, end=END)
    second = build_carry_sidecar(data, rates, [DAX, NQ], CONFIG, start=START, end=END)
    assert first.sha256 == second.sha256
    assert first.events.equals(second.events)
    richer = CarryProduct(symbol='NQ', class_name='indices', kind='spot_cfd', income_yield_bps=150.0)
    third = build_carry_sidecar(data, rates, [DAX, richer], CONFIG, start=START, end=END)
    assert third.sha256 != first.sha256


def test_writer_records_metadata_and_file_hash(tmp_path: Path):
    sidecar = build_carry_sidecar(prices(), curve([(0, 5.0), (1, 5.0), (2, 5.0)]), [DAX],
                                  CONFIG, start=START, end=END)
    written = sidecar.write(tmp_path / 'carry')
    metadata = (tmp_path / 'carry' / 'carry_metadata.json').read_text()
    assert written['events_file_sha256'] == file_hash(tmp_path / 'carry' / 'carry_events.parquet')
    assert sidecar.metadata['formula'] in metadata
    assert pl.read_parquet(tmp_path / 'carry' / 'carry_events.parquet').height == sidecar.events.height


def test_missing_initial_curve_observations_block_partial_carry():
    with pytest.raises(QuantError) as exc:
        build_carry_sidecar(prices(), curve([(3, 5.0)]), [DAX], CONFIG,
                            start=START, end=END)
    assert exc.value.status == 'BLOCKED_DATA'
    assert 'missing curve' in exc.value.reason.lower()
