"""Real Polars/Parquet regressions for quote-based multi-market vaults."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from scripts.quant import main
from src.data_vault import DataVault
from src.data_vault.market_materializer import (
    discover_price_sources,
    materialize_price_markets,
)
from src.engine.common import QuantError
from src.workbench import Workbench
from tests.dual_mode_fixtures import test_spec as fixture_spec


def _write_bars(root: Path, symbol: str, start: datetime, *, minutes: int, missing: int = -1):
    rows = [
        {"timestamp": start + timedelta(minutes=i), "symbol": symbol,
         "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.1, "volume": 1.0}
        for i in range(minutes) if i != missing
    ]
    target = root / f"year={start.year}/month={start.month}/day={start.day}/data.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_parquet(target)


def _write_daily(root: Path, symbol: str, *, year: int, month: int):
    start = datetime(year, month, 1, tzinfo=UTC)
    rows = [{"timestamp": start + timedelta(days=i), "symbol": symbol,
             "open": 1.25, "high": 1.26, "low": 1.24, "close": 1.251, "volume": 7.0}
            for i in range(3)]
    target = root / f"year={year}/month={month}/data.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_parquet(target)


def test_fx_hourly_materialization_preserves_cutoff_quality_and_resume(tmp_path):
    store, output = tmp_path / "raw", tmp_path / "vault"
    raw = store / "forex_minute_EURUSD"
    _write_bars(raw, "EURUSD", datetime(2025, 12, 31, 21, tzinfo=UTC), minutes=180, missing=3)
    _write_bars(raw, "EURUSD", datetime(2026, 1, 1, 0, tzinfo=UTC), minutes=120)
    manifest = materialize_price_markets(store, output, category="forex", granularity="1h",
                                         start="2025-12-01", end="2026-02-01",
                                         trusted_partitioning=True)
    assert len(manifest["entries"]) == 2
    assert manifest["quality_summary"]["execution_qualified"] is False
    assert manifest["quality_summary"]["rows_by_partition"] == {
        "development": 3, "protected": 2}
    vault = DataVault(output, run_log=tmp_path / "run_log")
    dev = vault.load(end="2026-02-01")
    assert dev.height == 3
    assert dev["timestamp"].max() < datetime(2026, 1, 1, tzinfo=UTC)
    assert dev["is_tradable"].to_list() == [False, True, True]
    assert dev["carry_rate"].to_list() == [0., 0., 0.]
    assert all("/development/" in path for path in vault.opened_files)
    with pytest.raises(QuantError, match="Workbench"):
        vault.unlock_holdout("eurusd", "a" * 64)
    assert all("UNKNOWN_NOT_EXECUTION_QUALIFIED" == e["provenance"]["carry_status"]
               for e in manifest["entries"])
    wb = Workbench(fixture_spec(output), run_log=tmp_path / 'workbench', isolate=False)
    with pytest.raises(QuantError, match='unknown spread and directional swap'):
        wb.backtest()
    price = output / "development/EURUSD/panel-2025-12.parquet"
    prior = price.read_bytes()
    again = materialize_price_markets(store, output, category="forex", granularity="1h",
                                      start="2025-12-01", end="2026-02-01",
                                      trusted_partitioning=True)
    assert len(again["entries"]) == 2 and price.read_bytes() == prior
    price.write_bytes(prior + b"tamper")
    with pytest.raises(QuantError, match="receipt output changed"):
        materialize_price_markets(store, output, category="forex", granularity="1h",
                                  start="2025-12-01", end="2026-02-01",
                                  trusted_partitioning=True)


def test_duplicate_hsi_path_excluded_and_canonical_symbol_identity(tmp_path):
    store, out = tmp_path / "raw", tmp_path / "vault"
    base = datetime(2025, 12, 1, tzinfo=UTC)
    _write_bars(store / "index_minute_HK33", "HK33", base, minutes=120)
    _write_bars(store / "index_minute_HSI", "HK33", base, minutes=120)
    sources, exclusions = discover_price_sources(store, category="index", granularity="1h")
    assert [s.symbol for s in sources] == ["HK33"]
    assert exclusions[0]["status"] == "ALIAS_MISMATCH"
    manifest = materialize_price_markets(store, out, category="index", granularity="1h",
                                         start="2025-12-01", end="2026-01-01")
    assert manifest["quality_summary"]["symbols_built"] == 1
    assert len(manifest["entries"]) == 1
    assert DataVault(out).load()["symbol"].unique().to_list() == ["HK33"]


def test_daily_fx_is_distinct_cadence_and_requires_trusted_protected_ingest(tmp_path):
    store, out = tmp_path / "raw", tmp_path / "vault"
    _write_daily(store / "forex_daily_EURGBP", "EURGBP", year=2025, month=12)
    _write_daily(store / "forex_daily_EURGBP", "EURGBP", year=2026, month=1)
    with pytest.raises(QuantError, match="trusted_partitioning"):
        materialize_price_markets(store, out, category="forex", granularity="1d",
                                  start="2025-12-01", end="2026-02-01")
    manifest = materialize_price_markets(store, out, category="forex", granularity="1d",
                                         start="2025-12-01", end="2026-02-01",
                                         trusted_partitioning=True)
    assert manifest["bar_seconds"] == 86400
    vault = DataVault(out)
    dev = vault.load()
    assert dev.height == 3
    assert dev["bar_in_session"].to_list() == [0, 0, 0]
    assert dev["is_tradable"].all()


def test_audited_daily_usdjpy_vendor_ticker_alias(tmp_path):
    store, out = tmp_path / 'raw', tmp_path / 'vault'
    _write_daily(store / 'forex_daily_USDJPY', 'JPY', year=2025, month=12)
    sources, missing = discover_price_sources(store, category='forex', granularity='1d')
    assert [s.symbol for s in sources] == ['USDJPY']
    assert not missing
    manifest = materialize_price_markets(store, out, category='forex', granularity='1d',
                                         start='2025-12-01', end='2026-01-01')
    assert manifest['entries'][0]['provenance']['raw_vendor_symbol'] == 'JPY'
    assert manifest['entries'][0]['provenance']['identity_override'] == 'AUDITED_USDJPY_DAILY_VENDOR_JPY_ALIAS'
    assert DataVault(out).load()['symbol'].unique().to_list() == ['USDJPY']


def test_market_cli_builds_price_only_fx_fixture(tmp_path, capsys):
    store = tmp_path / "raw"
    _write_bars(store / "forex_minute_EURUSD", "EURUSD",
                datetime(2025, 12, 31, 21, tzinfo=UTC), minutes=120)
    result = main(["materialize-markets", "--store", str(store),
                   "--output-root", str(tmp_path / "vaults"), "--groups", "forex",
                   "--frequencies", "1h", "--start", "2025-12-01",
                   "--end", "2026-01-01"])
    assert result == 0
    assert (tmp_path / "vaults/forex_1h/manifest.json").exists()
    assert '"status": "COMPILED"' in capsys.readouterr().out

def _write_seconds(root: Path, symbol: str, start: datetime, *, count: int, missing: int = -1):
    rows = [
        {"timestamp": start + timedelta(seconds=i), "symbol": symbol,
         "open": 101.0 + i * 0.01, "high": 101.3 + i * 0.01,
         "low": 100.7 + i * 0.01, "close": 101.1 + i * 0.01,
         "volume": 3.0}
        for i in range(count) if i != missing
    ]
    target = root / f"year={start.year}/month={start.month}/day={start.day}/data.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_parquet(target)


def test_native_minute_fx_retains_every_observed_row_without_hourly_aggregation(tmp_path):
    store, output = tmp_path / "raw", tmp_path / "vault"
    start = datetime(2025, 12, 31, 22, tzinfo=UTC)
    _write_bars(store / "forex_minute_EURUSD", "EURUSD", start, minutes=75, missing=9)
    manifest = materialize_price_markets(
        store, output, category="forex", granularity="1m",
        start="2025-12-01", end="2026-01-01")
    assert manifest["bar_seconds"] == 60
    assert manifest["quality_summary"]["rows_by_partition"]["development"] == 74
    assert manifest["quality_summary"]["observed_gaps_gt_cadence"] == 1
    data = DataVault(output).load()
    assert data.height == 74
    assert data["bar_in_session"].head(2).to_list() == [22 * 60, 22 * 60 + 1]
    assert data["is_tradable"].all()
    assert data["volume"].sum() == 74
    assert data["timestamp"].max() < datetime(2026, 1, 1, tzinfo=UTC)


def test_sparse_native_second_indices_are_daily_partitioned_and_protected(tmp_path):
    store, output = tmp_path / "raw", tmp_path / "vault"
    _write_seconds(store / "index_second_NQ", "NQ",
                   datetime(2025, 12, 31, 23, 59, 50, tzinfo=UTC),
                   count=10, missing=3)
    _write_seconds(store / "index_second_NQ", "NQ",
                   datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
                   count=8, missing=6)
    manifest = materialize_price_markets(
        store, output, category="index", granularity="1s",
        start="2025-12-01", end="2026-02-01", trusted_partitioning=True)
    assert manifest["bar_seconds"] == 1
    assert manifest["quality_summary"]["rows_by_partition"] == {
        "development": 9, "protected": 7}
    assert manifest["quality_summary"]["observed_gaps_gt_cadence"] == 2
    assert (output / "development/NQ/panel-2025-12-31.parquet").is_file()
    assert (output / "protected/NQ/panel-2026-01-01.parquet").is_file()
    vault = DataVault(output)
    dev = vault.load(end="2026-02-01")
    assert dev.height == 9
    assert dev["timestamp"].max() == datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC)
    assert dev["bar_in_session"].head(3).to_list() == [86390, 86391, 86392]
    assert all("/development/" in path for path in vault.opened_files)
    before = (output / "development/NQ/panel-2025-12-31.parquet").read_bytes()
    again = materialize_price_markets(
        store, output, category="index", granularity="1s",
        start="2025-12-01", end="2026-02-01", trusted_partitioning=True)
    assert manifest["manifest_hash"] == again["manifest_hash"]
    assert before == (output / "development/NQ/panel-2025-12-31.parquet").read_bytes()
