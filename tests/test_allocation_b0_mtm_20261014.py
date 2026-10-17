from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from allocation_b0_mtm_20261014 import account_at_marks, audit_year_boundaries, quantity_at


def ts(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def test_long_open_mark_then_close_includes_each_commission_once() -> None:
    fills = pl.DataFrame({
        "timestamp": [ts("2020-01-02T10:00:00"), ts("2020-01-02T12:00:00")],
        "side": ["buy", "sell"], "quantity": [1.0, 1.0],
        "price": [100.25, 101.0], "commission": [2.5, 2.5],
    })
    marks = pl.DataFrame({"timestamp": [ts("2020-01-02T11:00:00"), ts("2020-01-02T12:00:00")], "mark_price": [101.0, 101.0]})

    result = account_at_marks(fills, marks)

    assert result["position_quantity"].to_list() == [1.0, 0.0]
    assert result["ledger_equity"].to_list() == [1_000_012.5, 1_000_010.0]


def test_short_open_position_is_marked_as_a_liability() -> None:
    fills = pl.DataFrame({"timestamp": [ts("2020-01-02T10:00:00")], "side": ["sell"], "quantity": [1.0], "price": [100.0], "commission": [2.5]})
    marks = pl.DataFrame({"timestamp": [ts("2020-01-02T11:00:00")], "mark_price": [99.0]})

    result = account_at_marks(fills, marks)

    assert result["position_quantity"].item() == -1.0
    assert result["ledger_equity"].item() == 1_000_017.5


def test_no_source_mark_produces_no_nav_row() -> None:
    fills = pl.DataFrame(schema={"timestamp": pl.Datetime("us", "UTC"), "side": pl.String, "quantity": pl.Float64, "price": pl.Float64, "commission": pl.Float64})
    marks = pl.DataFrame(schema={"timestamp": pl.Datetime("us", "UTC"), "mark_price": pl.Float64})

    assert account_at_marks(fills, marks).is_empty()


def test_boundary_position_uses_only_fills_through_snapshot() -> None:
    fills = [
        {"timestamp": ts("2020-12-31T20:00:00"), "side": "buy", "quantity": 1.0},
        {"timestamp": ts("2021-01-04T20:00:00"), "side": "sell", "quantity": 1.0},
    ]

    assert quantity_at(fills, ts("2020-12-31T23:59:00")) == 1.0
    assert quantity_at(fills, ts("2021-01-04T20:00:00")) == 0.0


def test_native_year_boundaries_are_flat_but_not_one_continuous_path() -> None:
    result = audit_year_boundaries()

    assert result["status"] == "VERIFIED_FLAT_BUT_CONTINUITY_BLOCKED"
    assert len(result["boundary_details"]) == 11
    assert result["boundary_snapshots_all_flat"] is True
    assert result["all_year_worker_overlap_fill_and_equity_continuity_proven"] is False
    assert result["continuous_nav_created"] is False
    assert result["excluded_boundary"] == "2024-12/2025-01; no 2025 data read by authorization"
    assert all(not row["overlap"]["continuity_proven_for_overlap"] for row in result["boundary_details"])
