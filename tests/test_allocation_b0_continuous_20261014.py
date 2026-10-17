from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import allocation_b0_continuous_20261014 as continuous


def test_b0_frozen_runtime_parameters_are_single_contract_and_costed() -> None:
    assert continuous.START.isoformat() == "2013-01-01"
    assert continuous.END.isoformat() == "2024-12-31"
    assert continuous.LOOKBACK == 50
    assert continuous.STOP_POINTS == 50.0
    assert continuous.MULTIPLIER == 20.0
    assert continuous.COMMISSION == 2.5
    assert continuous.SLIPPAGE_POINTS == 0.25
    assert continuous.MAX_ENTRIES_PER_SESSION == 2


def test_promoted_b0_spec_and_full_tick_cost_case_match_replay() -> None:
    verification = continuous.verify_frozen_b0()

    assert verification["status"] == "VERIFIED"
    assert all(verification["checks"].values())


def test_source_partition_selection_never_includes_2025_or_later() -> None:
    paths = continuous.eligible_source_files()

    assert paths
    dates = [
        (int(path.parts[-4].split("=")[1]), int(path.parts[-3].split("=")[1]),
         int(path.parts[-2].split("=")[1]))
        for path in paths
    ]
    assert min(year for year, _, _ in dates) >= 2013
    assert max(year for year, _, _ in dates) <= 2024
    assert all((year, month, day) <= (2024, 12, 31) for year, month, day in dates)


def test_daily_cash_plus_mark_reconciles_native_equity(tmp_path: Path) -> None:
    daily_path = tmp_path / "daily_equity.csv"
    fills_path = tmp_path / "fills.csv"
    daily_path.write_text("utc_day,timestamp,equity\n2020-01-02,2020-01-02T12:00:00.000000+0000,1000017.5\n")
    fills_path.write_text(
        "side,quantity,price,timestamp,commission\n"
        "buy,1.0,100.0,2020-01-02T10:00:00.000000+0000,2.5\n"
    )
    stamp = datetime(2020, 1, 2, 12, tzinfo=timezone.utc)
    marks = pl.DataFrame({
        "timestamp": [stamp],
        "mark_price": [101.0],
    })

    account, summary = continuous.reconcile_daily(daily_path, fills_path, marks)

    assert account["cash_balance"].item() == 997_997.5
    assert account["position_quantity"].item() == 1.0
    assert account["position_market_value"].item() == 2_020.0
    assert account["ledger_equity"].item() == 1_000_017.5
    assert summary["max_abs_cash_plus_mark_vs_native_equity_usd"] == 0.0
    assert summary["source_mark_missing_count"] == 0
