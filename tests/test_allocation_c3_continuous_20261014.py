from datetime import datetime, timezone

import polars as pl
import pytest

from scripts.allocation_c3_continuous_20261014 import (
    ARTIFACT_EVENT_TIMESTAMPS,
    END,
    boundary_carry,
    reconcile_native_artifacts,
)


def _write_artifact_fixture(root):
    pl.DataFrame({
        "timestamp": [datetime(2024, 12, 31, tzinfo=timezone.utc)],
        "equity": [100013.0],
    }).write_parquet(root / "continuous_equity.parquet")
    pl.DataFrame({
        "side": ["buy", "sell"],
        "quantity": [2.0, 1.0],
        "price": [100.0, 110.0],
        "commission": [1.0, 1.0],
        "timestamp": [datetime(2024, 12, 30), datetime(2024, 12, 31)],
    }).write_parquet(root / "fills.parquet")
    pl.DataFrame({
        "symbol": ["US500_D"],
        "direction": ["long"],
        "quantity": [1.0],
        "exit_price": [105.0],
        "multiplier": [1.0],
        "entry_time": [datetime(2024, 12, 30)],
        "exit_time": [datetime(2024, 12, 31)],
        "status": ["open"],
    }).write_parquet(root / "trades.parquet")
    pl.DataFrame({
        "year": [2024],
        "as_of": [datetime(2024, 12, 31, tzinfo=timezone.utc)],
        "year_end_equity": [100013.0],
    }).write_parquet(root / "year_end_equity.parquet")


def test_cutoff_is_exclusive_at_2025_start():
    assert END == datetime(2025, 1, 1, tzinfo=timezone.utc)


def test_native_trade_lifecycle_detects_year_boundary_carry():
    trades = pl.DataFrame({
        "symbol": ["US500_D", "US100_H"],
        "entry_time": [datetime(2023, 12, 29), datetime(2024, 1, 2)],
        "exit_time": [datetime(2024, 1, 3), datetime(2024, 1, 4)],
    })
    evidence = boundary_carry(trades)
    assert evidence[10] == {
        "boundary": "2024-01-01T00:00:00Z",
        "open_trade_count": 1,
        "symbols": ["US500_D"],
    }


def test_boundary_audit_requires_native_trade_lifecycle_fields():
    with pytest.raises(ValueError, match="Native trade ledger lacks"):
        boundary_carry(pl.DataFrame({"symbol": ["US500_D"]}))


def test_fill_cash_and_open_position_mark_reconcile(tmp_path):
    _write_artifact_fixture(tmp_path)
    result = reconcile_native_artifacts(tmp_path)
    assert result["ending_cash_reconstructed_from_native_fills"] == 99908.0
    assert result["ending_marked_positions_from_native_open_trades"] == 105.0
    assert result["reconciliation_delta"] == 0.0


@pytest.mark.parametrize(
    ("filename", "timestamp_column"),
    [
        ("continuous_equity.parquet", "timestamp"),
        ("fills.parquet", "timestamp"),
        ("trades.parquet", "entry_time"),
        ("trades.parquet", "exit_time"),
        ("year_end_equity.parquet", "as_of"),
    ],
)
def test_future_event_timestamp_fails_before_any_outcome_read(
    tmp_path, monkeypatch, filename, timestamp_column
):
    _write_artifact_fixture(tmp_path)
    path = tmp_path / filename
    frame = pl.read_parquet(path)
    dtype = frame.schema[timestamp_column]
    future = END if dtype.time_zone else END.replace(tzinfo=None)
    future_row = frame.tail(1).with_columns(pl.lit(future).cast(dtype).alias(timestamp_column))
    pl.concat([frame, future_row]).write_parquet(path)

    def forbidden_full_read(*args, **kwargs):
        raise AssertionError("Outcome columns were read before timestamp preflight failed")

    monkeypatch.setattr(pl, "read_parquet", forbidden_full_read)
    with pytest.raises(ValueError, match="at/after exclusive cutoff"):
        reconcile_native_artifacts(tmp_path)


def test_missing_event_timestamp_column_fails_before_outcome_read(tmp_path, monkeypatch):
    _write_artifact_fixture(tmp_path)
    fills_path = tmp_path / "fills.parquet"
    pl.read_parquet(fills_path).drop("timestamp").write_parquet(fills_path)

    def forbidden_full_read(*args, **kwargs):
        raise AssertionError("Outcome columns were read before schema validation failed")

    monkeypatch.setattr(pl, "read_parquet", forbidden_full_read)
    with pytest.raises(ValueError, match="missing required event timestamp"):
        reconcile_native_artifacts(tmp_path)


@pytest.mark.parametrize(
    ("filename", "column", "invalid_value", "error"),
    [
        ("fills.parquet", "side", "unknown-side", "unrecognized side"),
        ("trades.parquet", "direction", "unknown-direction", "unrecognized direction"),
    ],
)
def test_unrecognized_fill_side_or_trade_direction_fails_closed(
    tmp_path, filename, column, invalid_value, error
):
    _write_artifact_fixture(tmp_path)
    path = tmp_path / filename
    frame = pl.read_parquet(path).with_columns(pl.lit(invalid_value).alias(column))
    frame.write_parquet(path)
    with pytest.raises(ValueError, match=error):
        reconcile_native_artifacts(tmp_path)


def test_timestamp_contract_covers_every_saved_artifact():
    assert set(ARTIFACT_EVENT_TIMESTAMPS) == {
        "continuous_equity.parquet",
        "fills.parquet",
        "trades.parquet",
        "year_end_equity.parquet",
    }
