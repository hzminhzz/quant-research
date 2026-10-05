import pandas as pd
import pytest
from scripts import run_btc_eth_relative_value as runner




def test_prepare_data_reads_canonical_stores_and_records_audit(tmp_path, monkeypatch):
    import json

    import polars as pl
    from ml4t.data.storage import create_storage

    start = pd.Timestamp("2020-09-01T00:00:00Z")
    end = start + pd.Timedelta(hours=2)
    monkeypatch.setattr(runner, "DATA_START", start)
    monkeypatch.setattr(runner, "DATA_END", end)
    monkeypatch.setattr(runner, "STORE_ROOT", tmp_path)
    monkeypatch.setattr(runner, "DATA_OUT", tmp_path / "audit")

    price_root = tmp_path / runner.PRICE_DATASET
    price_storage = create_storage(str(price_root), strategy="hive")
    funding_storage = create_storage(str(tmp_path), strategy="hive")
    timestamps = [
        start.to_pydatetime(),
        (start + pd.Timedelta(hours=1)).to_pydatetime(),
    ]
    funding_timestamps = [
        (start - pd.Timedelta(hours=1)).to_pydatetime(),
        *timestamps,
        end.to_pydatetime(),
    ]
    for symbol in runner.SYMBOLS:
        prices = pl.DataFrame({
            "timestamp": timestamps,
            "symbol": [symbol, symbol],
            "open": [1.0, 1.0],
            "high": [1.0, 1.0],
            "low": [1.0, 1.0],
            "close": [1.0, 1.0],
            "volume": [1.0, 1.0],
            "quote_volume": [1.0, 1.0],
        })
        price_storage.write(prices, f"symbol={symbol}")
        price_partition = next((price_root / f"symbol={symbol}").rglob("data.parquet")).parent
        (price_partition / "source.json").write_text(json.dumps({"source_key": f"price-{symbol}"}))

        key = runner.FUNDING_KEYS[symbol]
        funding = pl.DataFrame({
            "timestamp": funding_timestamps,
            "symbol": [symbol] * len(funding_timestamps),
            "funding_interval_hours": [1] * len(funding_timestamps),
            "funding_rate": [0.001, 0.001, 0.002, 0.002],
            "mark_price": [1.0] * len(funding_timestamps),
        })
        funding_storage.write(funding, key)
        for partition in (tmp_path / key.replace("/", "_")).rglob("data.parquet"):
            partition.parent.joinpath("source.json").write_text(
                json.dumps({"source_key": f"funding-{symbol}"})
            )

    manifest_path = price_root / "dataset_manifest.json"
    manifest_path.write_text(json.dumps({
        "completeness_status": "complete_for_requested_archives",
        "failure_count_this_run": 0,
    }))

    prices, funding, audit = runner.prepare_data()

    assert len(prices) == 2
    assert len(funding) == 4
    assert audit["symbols"]["BTCUSDT"]["partitions"][0]["source"]["source_key"] == "price-BTCUSDT"
    assert audit["funding"]["ETHUSDT"]["partitions"][0]["source"]["source_key"] == "funding-ETHUSDT"
    assert audit["symbols"]["BTCUSDT"]["manifest_identity"] == runner._sha256(manifest_path)
    assert audit["strategy_price_frame"]["fingerprint"]
    assert (tmp_path / "audit" / "data_audit.json").is_file()


def test_funding_loader_rejects_missing_settlement(tmp_path, monkeypatch):
    import polars as pl
    from ml4t.data.storage import create_storage

    start = pd.Timestamp("2020-09-01T00:00:00Z")
    monkeypatch.setattr(runner, "DATA_START", start)
    monkeypatch.setattr(runner, "DATA_END", start + pd.Timedelta(hours=17))
    monkeypatch.setattr(runner, "STORE_ROOT", tmp_path)
    key = runner.FUNDING_KEYS["BTCUSDT"]
    storage = create_storage(str(tmp_path), strategy="hive")
    storage.write(
        pl.DataFrame({
            "timestamp": [
                (start - pd.Timedelta(hours=4)).to_pydatetime(),
                start.to_pydatetime(),
                (start + pd.Timedelta(hours=8)).to_pydatetime(),
                (start + pd.Timedelta(hours=12)).to_pydatetime(),
                (start + pd.Timedelta(hours=16)).to_pydatetime(),
                (start + pd.Timedelta(hours=20)).to_pydatetime(),
                (start + pd.Timedelta(hours=24)).to_pydatetime(),
            ],
            "symbol": ["BTCUSDT"] * 7,
            "funding_interval_hours": [4] * 7,
            "funding_rate": [0.001] * 7,
            "mark_price": [1.0] * 7,
        }),
        key,
    )

    with pytest.raises(RuntimeError, match="disagrees with funding_interval_hours"):
        runner._load_funding(storage, "BTCUSDT")



def test_funding_loader_rejects_unsupported_observed_cadence(tmp_path, monkeypatch):
    import polars as pl
    from ml4t.data.storage import create_storage

    start = pd.Timestamp("2020-09-01T00:00:00Z")
    monkeypatch.setattr(runner, "DATA_START", start)
    monkeypatch.setattr(runner, "DATA_END", start + pd.Timedelta(hours=4))
    monkeypatch.setattr(runner, "STORE_ROOT", tmp_path)
    key = runner.FUNDING_KEYS["BTCUSDT"]
    storage = create_storage(str(tmp_path), strategy="hive")
    hours = [-1, 0, 2, 3, 4, 5]
    storage.write(
        pl.DataFrame({
            "timestamp": [(start + pd.Timedelta(hours=hour)).to_pydatetime() for hour in hours],
            "symbol": ["BTCUSDT"] * len(hours),
            "funding_interval_hours": [1, 1, 2, 1, 1, 1],
            "funding_rate": [0.001] * len(hours),
            "mark_price": [1.0] * len(hours),
        }),
        key,
    )

    with pytest.raises(RuntimeError, match="cadence evidence is invalid"):
        runner._load_funding(storage, "BTCUSDT")


def test_canonical_hourly_range_and_fingerprint(monkeypatch):
    start = pd.Timestamp("2020-09-01T00:00:00Z")
    end = start + pd.Timedelta(hours=3)
    monkeypatch.setattr(runner, "DATA_START", start)
    monkeypatch.setattr(runner, "DATA_END", end)
    frame = pd.DataFrame({"timestamp": pd.date_range(start, periods=3, freq="h", tz="UTC")})
    runner._check_hours(frame, "BTCUSDT")
    with pytest.raises(RuntimeError, match="incomplete"):
        runner._check_hours(frame.iloc[:-1], "BTCUSDT")
    assert runner._frame_fingerprint(frame, "UTC candle open time") == runner._frame_fingerprint(frame.copy(), "UTC candle open time")
    assert runner._frame_fingerprint(frame, "UTC candle open time") != runner._frame_fingerprint(frame, "UTC funding settlement time")
