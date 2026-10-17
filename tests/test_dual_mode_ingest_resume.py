from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from src.data_vault import PanelBuilder
from src.engine.common import QuantError
from tests.dual_mode_fixtures import make_panel


def _write_month(store, month, days):
    price = store / 'crypto_futures_ohlcv_1h_BINANCE_UM_PERP' / 'symbol=BTCUSDT' / f'year=2025/month={month}'
    funding = store / 'crypto_futures_funding_BTCUSDT_PERP' / f'year=2025/month={month}'
    price.mkdir(parents=True, exist_ok=True)
    funding.mkdir(parents=True, exist_ok=True)
    start = datetime(2025, month, 1, tzinfo=UTC)
    panel = make_panel(hours=24 * days, symbols=('BTCUSDT_PERP',), start=start)
    panel.select('timestamp', 'symbol', 'open', 'high', 'low', 'close', 'volume').write_parquet(price / 'data.parquet')
    pl.DataFrame([{'timestamp': start + timedelta(hours=h), 'symbol': 'BTCUSDT_PERP',
                   'funding_interval_hours': 8, 'funding_rate': .0001, 'mark_price': 100.}
                  for h in range(0, 24 * days, 8)]).write_parquet(funding / 'data.parquet')


def test_monthly_resume_reuses_valid_receipts_and_rejects_bad_hash(tmp_path):
    store, output = tmp_path / 'store', tmp_path / 'vault'
    _write_month(store, 1, 31)
    builder = PanelBuilder(store, output)
    first = builder.build(start='2025-01-01', end='2025-03-01', spread_assumption='fixture')
    assert first['entries']
    assert any(x['slice'] == '2025-02' for x in first['excluded'])
    jan = output / 'development/BTCUSDT_PERP/panel-2025-01.parquet'
    original = jan.read_bytes()

    _write_month(store, 2, 28)
    resumed = builder.build(start='2025-01-01', end='2025-03-01', spread_assumption='fixture')
    assert jan.read_bytes() == original
    assert len([x for x in resumed['entries'] if x['table'] == 'prices']) == 2
    assert resumed['manifest_hash'] != first['manifest_hash']

    jan.write_bytes(original + b'corruption')
    with pytest.raises(QuantError, match='bad sha256'):
        builder.build(start='2025-01-01', end='2025-03-01', spread_assumption='fixture')
