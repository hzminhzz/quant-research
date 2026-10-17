"""Ingestion tests use raw-layout fixtures, not pre-certified inputs."""
from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from src.data_vault import DataVault, PanelBuilder
from src.engine.common import QuantError
from tests.dual_mode_fixtures import make_panel


def raw_store(root, *, missing_mark=False, jitter_ms=0, hours=24):
    panel = make_panel(hours=hours, symbols=('BTCUSDT_PERP',), start=datetime(2025, 1, 1, tzinfo=UTC))
    price_dir = root / 'crypto_futures_ohlcv_1h_BINANCE_UM_PERP/symbol=BTCUSDT/year=2025/month=1'
    price_dir.mkdir(parents=True)
    panel.select('timestamp', 'symbol', 'open', 'high', 'low', 'close', 'volume').write_parquet(price_dir / 'data.parquet')
    funding_dir = root / 'crypto_futures_funding_BTCUSDT_PERP/year=2025/month=1'
    funding_dir.mkdir(parents=True)
    records = [{'timestamp': datetime(2025, 1, 1, tzinfo=UTC) + timedelta(hours=h, milliseconds=jitter_ms),
                'symbol': 'BTCUSDT_PERP', 'funding_interval_hours': 8, 'funding_rate': .0001,
                'mark_price': None if missing_mark else 101.}
               for h in range(0, hours, 8)]
    pl.DataFrame(records, schema_overrides={'mark_price': pl.Float64}).write_parquet(funding_dir / 'data.parquet')
    return price_dir, funding_dir


def test_actual_layout_discovery_jitter_and_mark_proxy(tmp_path):
    store = tmp_path / 'raw'
    raw_store(store, missing_mark=True, jitter_ms=15)
    builder = PanelBuilder(store, tmp_path / 'vault')
    report = builder.discovery_report()
    assert report['price_symbols'] == report['matched_symbols'] == 1
    manifest = builder.build(start='2025-01-01', end='2025-01-02', spread_assumption='synthetic zero spread')
    vault = DataVault(tmp_path / 'vault')
    panel = vault.load()
    funding = vault.load_funding('2025-01-01', '2025-01-02')
    assert panel['is_tradable'].all()
    assert panel.filter(pl.col('carry_rate') != 0).height == 3
    assert funding['mark_source'].unique().to_list() == ['trade_open_proxy']
    assert funding['mark_price'].to_list() == [100., 100., 100.]
    assert (funding['source_event_at'] - funding['timestamp']).dt.total_milliseconds().to_list() == [15, 15, 15]
    assert manifest['entries'][0]['provenance']['funding_time_policy']['tolerance_ms'] == 1000


def test_later_missing_settlement_does_not_drop_earlier_history(tmp_path):
    store = tmp_path / 'raw'
    _, funding = raw_store(store, hours=32)
    source = pl.read_parquet(funding / 'data.parquet').filter(pl.col('timestamp').dt.hour() != 16)
    source.write_parquet(funding / 'data.parquet')
    builder = PanelBuilder(store, tmp_path / 'vault')
    builder.build(start='2025-01-01', end='2025-01-02', spread_assumption='fixture')
    panel = DataVault(tmp_path / 'vault').load()
    assert panel.height == 24
    assert panel.filter(pl.col('timestamp').dt.hour() < 16)['is_tradable'].all()
    assert not panel.filter(pl.col('timestamp').dt.hour() >= 16)['is_tradable'].any()


def test_observed_only_policy_retains_missing_marks_instead_of_inventing(tmp_path):
    store = tmp_path / 'raw'
    raw_store(store, missing_mark=True)
    PanelBuilder(store, tmp_path / 'vault', funding_mark_policy='observed_only').build(
        start='2025-01-01', end='2025-01-02', spread_assumption='fixture')
    funding = DataVault(tmp_path / 'vault').load_funding('2025-01-01', '2025-01-02')
    assert funding['mark_price'].null_count() == funding.height
    assert funding['mark_source'].unique().to_list() == ['missing']


def test_non_ascii_venue_symbol_keeps_identity_under_portable_partition_path(tmp_path):
    from src.data_vault.panel_builder import symbol_partition_name

    symbol = '龙虾USDT_PERP'
    store = tmp_path / 'raw'
    price_dir = store / 'crypto_futures_ohlcv_1h_BINANCE_UM_PERP' / 'symbol=龙虾USDT' / 'year=2025/month=1'
    funding_dir = store / 'crypto_futures_funding_龙虾USDT_PERP/year=2025/month=1'
    price_dir.mkdir(parents=True)
    funding_dir.mkdir(parents=True)
    base = datetime(2025, 1, 1, tzinfo=UTC)
    make_panel(hours=24, symbols=(symbol,), start=base).select(
        'timestamp', 'symbol', 'open', 'high', 'low', 'close', 'volume'
    ).write_parquet(price_dir / 'data.parquet')
    pl.DataFrame([{'timestamp': base + timedelta(hours=h), 'symbol': symbol,
                   'funding_rate': 0.0001, 'funding_interval_hours': 8, 'mark_price': 100.0}
                  for h in range(0, 24, 8)]).write_parquet(funding_dir / 'data.parquet')
    assert symbol_partition_name(symbol).startswith('unicode-')
    output = tmp_path / 'vault'
    manifest = PanelBuilder(store, output).build(start='2025-01-01', end='2025-01-02',
                                                  spread_assumption='synthetic fixture')
    assert {entry['symbol'] for entry in manifest['entries']} == {symbol}
    assert all('unicode-' in entry['path'] for entry in manifest['entries'])
    assert DataVault(output).load()['symbol'].unique().to_list() == [symbol]


def test_missing_funding_source_is_not_zero_carry(tmp_path):
    store = tmp_path / 'raw'
    price = store / 'crypto_futures_ohlcv_1h_BINANCE_UM_PERP/symbol=BTCUSDT'
    price.mkdir(parents=True)
    with pytest.raises(QuantError, match='No matched source passed ingestion'):
        PanelBuilder(store, tmp_path / 'vault').build(start='2025-01-01', end='2025-01-02', spread_assumption='fixture')


def test_naive_raw_timestamp_is_not_silently_reclassified_as_utc(tmp_path):
    store = tmp_path / 'raw'
    price, _ = raw_store(store)
    path = price / 'data.parquet'
    pl.read_parquet(path).with_columns(pl.col('timestamp').dt.replace_time_zone(None)).write_parquet(path)
    with pytest.raises(QuantError, match='explicit timezone'):
        PanelBuilder(store, tmp_path / 'vault').build(start='2025-01-01', end='2025-01-02', spread_assumption='fixture')


def test_naive_canonical_timestamp_is_not_certified(tmp_path):
    panel = make_panel(hours=8).with_columns(pl.col('timestamp').dt.replace_time_zone(None))
    with pytest.raises(QuantError, match='explicit timezone'):
        PanelBuilder(tmp_path / 'raw', tmp_path / 'vault').publish(panel, provenance={'scope': 'fixture'})


def test_cfd_dst_sessions_compile_from_raw_minutes(tmp_path):
    source = tmp_path / 'raw'
    source.mkdir()
    rows = []
    for day, hour in [(7, 14), (10, 13)]:  # New York DST changes between these dates.
        opening = datetime(2025, 3, day, hour, 30, tzinfo=UTC)
        for minute in range(390):
            rows.append({'timestamp': opening + timedelta(minutes=minute),
                         'open': 100., 'high': 101., 'low': 99., 'close': 100., 'volume': 1.})
    pl.DataFrame(rows).write_parquet(source / 'data.parquet')
    output = tmp_path / 'vault'
    manifest = PanelBuilder(source, output).build_cfd(
        source_root=source, symbol='DUKASCOPY_USATECH_CFD', source_identity='synthetic Dukascopy schema fixture',
        start='2025-03-07', end='2025-03-11', exchange_calendar='XNYS',
        bar_seconds=1800, spread_bps=2., spread_assumption='fixture constant spread',
        carry_assumption='Cash-session-only fixture is flat overnight; no swaps are modeled')
    panel = DataVault(output).load()
    assert panel.height == 26 and panel['is_tradable'].all()
    firsts = panel.group_by('session_id').agg(pl.col('timestamp').min()).sort('session_id')
    assert firsts['timestamp'].dt.hour().to_list() == [14, 13]
    assert panel['bar_in_session'].max() == 12
    assert manifest['entries'][0]['provenance']['volume_semantics'] == 'broker_tick_or_quote_proxy'
    assert manifest['bar_seconds'] == 1800
