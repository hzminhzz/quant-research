"""Focused checks for the annual-ledger tearsheet aggregation."""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/generate_tearsheet.py"
SPEC = importlib.util.spec_from_file_location("one_bar_tearsheet", SCRIPT)
REPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORT)


def test_completed_ledgers_reconcile_to_annual_and_summary_totals():
    REPORT.verify_recovery_audit()
    zero = REPORT.load_ledgers("native_zero_cost")
    costed = REPORT.load_ledgers("native_full_tick_cost")
    zero_stats, _, _, _ = REPORT.summarize(zero, "native_zero_cost")
    costed_stats, _, _, costed_annual = REPORT.summarize(costed, "native_full_tick_cost")

    assert zero_stats["closed_trades"] == costed_stats["closed_trades"] == 5462
    assert abs(zero_stats["net_pnl_usd"] - 247566.38) < 0.01
    assert abs(costed_stats["net_pnl_usd"] - 166107.92) < 0.01
    annual = {row["year"]: row for row in costed_annual}
    assert abs(annual[2026]["net_pnl_usd"] - (-14166.96)) < 0.01
    assert sum(row["trades"] for row in costed_annual) == 5462


def test_daily_cashflow_series_includes_no_exit_days_and_cash_base():
    frame = REPORT.load_ledgers("native_full_tick_cost")
    metrics, daily, _, _ = REPORT.summarize(frame, "native_full_tick_cost")
    session_frame = REPORT.add_session_date(frame)
    exit_dates = session_frame["session_date"].n_unique()
    assert daily.height > exit_dates
    assert daily.filter(REPORT.pl.col("session_date").dt.weekday() > 5).is_empty()
    sunday = session_frame.filter(REPORT.pl.col("exit_time").dt.weekday() == 7)
    assert sunday.height == 87
    assert sunday.filter(REPORT.pl.col("session_date").dt.weekday() != 1).is_empty()
    assert metrics["utc_sunday_exits_included"] == 87
    assert daily.height == metrics["daily_session_observations"]
    assert daily["trades"].sum() == frame.height
    assert daily["net_pnl_usd"].sum() == pytest.approx(frame["pnl"].sum())
    assert daily["gross_pnl_usd"].sum() == pytest.approx(frame["gross_pnl"].sum())
    assert daily["net_return"][0] == pytest.approx(daily["net_pnl_usd"][0] / 1_000_000)
    assert daily["net_return"][1] == pytest.approx(daily["net_pnl_usd"][1] / daily["net_realized_equity_usd"][0])
    assert daily["net_realized_equity_usd"][-1] == pytest.approx(1_000_000 + metrics["net_pnl_usd"])
    assert metrics["drawdown_basis"].startswith("Daily realized trade cash flows")
    assert metrics["annualization_periods"] == 252
    assert daily.height >= 63


def test_session_date_rolls_at_chicago_1700_cutoff():
    exits = REPORT.pl.DataFrame({"exit_time": [
        "2026-01-05T22:59:00+00:00", "2026-01-05T23:00:00+00:00",
    ]}).with_columns(REPORT.pl.col("exit_time").str.to_datetime(time_zone="UTC"))
    sessions = REPORT.add_session_date(exits)["session_date"].to_list()
    assert [str(day) for day in sessions] == ["2026-01-05", "2026-01-06"]


import pytest
