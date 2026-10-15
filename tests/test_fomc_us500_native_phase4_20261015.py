"""Independent Phase-4 native ledger and risk verification.

Audits archived REAL ml4t-backtest fills/trades/equity. This module never
recreates fills, optimizes the thesis, or reads the protected 2025+ holdout.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import polars as pl
import pytest

ROOT = Path(__file__).resolve().parents[1]
SESSION = "fomc_us500_overnight_native_phase4_20261015_v1"
DATA = ROOT / "data/processed" / SESSION / "minute_windows_bid.parquet"
ARCH = ROOT / "docs/audit" / SESSION
PREFLIGHT = (
    ROOT
    / "docs/audit/fomc_overnight_uncertainty_premium_us500_cfd_20261015_v1_source_preflight_v2.json"
)
CASES = {
    "fomc_primary_3x_10bps": ("fomc", 3.0, 10.0),
    "ordinary_baseline_3x_10bps": ("control", 3.0, 10.0),
    "fomc_3x_20bps_cost_stress": ("fomc", 3.0, 20.0),
    "fomc_1x_10bps": ("fomc", 1.0, 10.0),
    "fomc_5x_10bps": ("fomc", 5.0, 10.0),
    "fomc_3x_zero_cost_diagnostic": ("fomc", 3.0, 0.0),
}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _json(p: Path) -> dict:
    return json.loads(p.read_text())


def _utc(x: datetime) -> datetime:
    return x.replace(tzinfo=UTC) if x.tzinfo is None else x.astimezone(UTC)


def test_frozen_session_and_immutable_pre_holdout_windows():
    frozen = _json(ARCH / "frozen_spec.json")
    expected = _json(PREFLIGHT)
    phase4 = pl.read_parquet(DATA)
    assert frozen["status"] == "FROZEN"
    assert frozen["approval_status"] == "NOT_APPROVED"
    assert frozen["spec"]["evaluation"]["holdout_start"] == "2025-01-01T00:00:00Z"
    assert frozen["identity"]["data"][0]["sha256"] == _sha(DATA)
    assert [x["id"] for x in frozen["spec"]["trials"]] == list(CASES)
    assert phase4.height == 100_382
    assert phase4["timestamp"].max() < datetime(2025, 1, 1, tzinfo=UTC)
    assert phase4["timestamp"].n_unique() == phase4.height
    assert phase4["symbol"].unique().to_list() == ["ES"]
    for flag in ("enter", "exit", "entry_fill_clock", "exit_fill_clock"):
        assert phase4[flag].sum() == 106
    # Every event with source qualification must appear on both sleeves.
    declared = [e for e in expected["events"] if e.get("source_coverage_complete")]
    assert len(declared) == 53
    for e in declared:
        d = e["statement_date"]
        for leg in ("fomc", "control"):
            slice_ = phase4.filter(
                (pl.col("statement_date") == d) & (pl.col("leg") == leg)
            )
            assert slice_["enter"].sum() == slice_["exit"].sum() == 1
            for flag, key in (
                ("enter", "entry"),
                ("entry_fill_clock", "entry"),
                ("exit", "exit"),
                ("exit_fill_clock", "exit"),
            ):
                source = e["quote_checks"][leg + "_" + key]
                expected_time = (
                    source["decision_utc"]
                    if flag in ("enter", "exit")
                    else source["required_fill_bar"]["timestamp_utc"]
                )
                obs = slice_.filter(pl.col(flag) == 1)["timestamp"][0]
                assert obs == datetime.fromisoformat(expected_time)


@pytest.mark.parametrize("name", list(CASES))
def test_native_broker_fills_and_trade_equity_reconcile(name: str):
    leg, lev, bps = CASES[name]
    dest = ARCH / name
    m = _json(dest / "metrics.json")
    fills = pl.read_parquet(dest / "native_fills.parquet")
    trades = pl.read_parquet(dest / "native_trades.parquet")
    equity = pl.read_parquet(dest / "native_minute_equity.parquet")
    state = pl.read_parquet(dest / "native_portfolio_state.parquet")
    rejected = pl.read_parquet(dest / "rejected_orders.parquet")
    assert fills.height == 106
    assert trades.height == 53
    assert rejected.height == 0
    assert trades["status"].unique().to_list() == ["closed"]
    assert equity.height == state.height > 40_000
    assert m["closed_trades"] == 53
    assert m["rejected_orders"] == 0
    assert m["native_fill_clock_exact"]
    assert m["native_trade_cash_equity_reconciled"]
    assert m["qualified_historical_perp_funding"] is False
    assert m["target_notional_leverage"] == lev
    assert m["roundtrip_hypothetical_bps"] == bps

    # Native closed PnL is execution-price-aware; native gross_pnl is after
    # slippage and BEFORE commissions, so do not subtract slippage twice.
    assert np.allclose(
        trades["pnl"].to_numpy(),
        (trades["gross_pnl"] - trades["fees"]).to_numpy(),
        rtol=1e-9,
        atol=0.02,
    )
    pnl = float(trades["pnl"].sum())
    assert pnl == pytest.approx(m["native_trade_net_pnl"], abs=0.02)
    assert equity["equity"][-1] == pytest.approx(100_000 + pnl, abs=0.02)
    assert state["equity"][-1] == pytest.approx(equity["equity"][-1], abs=0.02)
    assert state["open_positions"][-1] == 0
    positive = float(trades.filter(pl.col("pnl") > 0)["pnl"].sum())
    negative = float(trades.filter(pl.col("pnl") < 0)["pnl"].sum())
    manual_pf = positive / abs(negative) if negative < 0 else None
    assert m["profit_factor"] == pytest.approx(manual_pf, abs=1e-10)
    assert m["win_rate"] == pytest.approx(float((trades["pnl"] > 0).sum() / 53))
    assert m["native_engine_metrics"]["num_orders"] == 106
    assert m["native_engine_metrics"]["num_rejected_orders"] == 0
    assert m["max_gross_to_equity_observed"] >= lev * 0.9

    price = pl.read_parquet(DATA).filter(
        (pl.col("leg") == leg)
        & ((pl.col("entry_fill_clock") == 1) | (pl.col("exit_fill_clock") == 1))
    )
    price_at = {_utc(r["timestamp"]): r["open"] for r in price.iter_rows(named=True)}
    assert len(price_at) == 106
    fill_times = [_utc(x) for x in fills["timestamp"].to_list()]
    assert len(set(fill_times)) == 106
    assert set(fill_times) == set(price_at)
    for r in fills.iter_rows(named=True):
        opn = price_at[_utc(r["timestamp"])]
        direction = 1 if r["side"] == "buy" else -1
        slippage = bps / 40000
        assert r["price_source"] == "open"
        assert r["price"] == pytest.approx(opn * (1 + direction * slippage), abs=1e-6)
        assert r["slippage"] == pytest.approx(opn * slippage, abs=1e-6)
        assert r["commission"] == pytest.approx(
            r["price"] * r["quantity"] * bps / 40000, abs=0.02
        )

    # Ledger cash plus marked exposure MUST equal equity on native snapshots
    # because this is a synthetic 1x contract notional multiplier scenario.
    discrepancy = (state["cash"] + state["net_exposure"] - state["equity"]).abs().max()
    assert discrepancy < 1.0, f"native cash/exposure/equity mismatch: {discrepancy}"


def test_daily_equity_metrics_and_frozen_decision():
    m = _json(ARCH / "fomc_primary_3x_10bps/metrics.json")
    daily = pl.read_csv(ARCH / "fomc_primary_3x_10bps/daily_equity.csv")
    assert daily["daily_return"].null_count() == 0
    returns = daily["daily_return"].to_numpy()
    # Library annualized Sharpe from actual *calendar-daily* values,
    # not from irregular sampled minute-bar marks.
    independent = float(np.mean(returns) / np.std(returns, ddof=1)) * np.sqrt(365)
    expected = m["daily_equity_risk_ml4t_diagnostic"]["sharpe_ratio"]
    assert independent == pytest.approx(expected, abs=0.01)
    drawdown = (daily["equity"] / daily["equity"].cum_max() - 1).min()
    assert float(drawdown) == pytest.approx(
        m["daily_equity_risk_ml4t_diagnostic"]["max_drawdown"], abs=1e-10
    )
    native_intraminute = float(
        pl.read_parquet(ARCH / "fomc_primary_3x_10bps/native_minute_equity.parquet")[
            "drawdown"
        ].min()
    )
    assert native_intraminute < float(drawdown)
    assert native_intraminute < -0.10
    result = _json(ARCH / "final_decision.json")
    assert result["research_verdict"] == "REJECT"
    assert result["executed_trial_count"] == 6
    assert "Primary daily-equity Sharpe <0.50" in result["criteria_failures_or_limits"]
    assert "Double friction 20bps net PnL <=0" in result["criteria_failures_or_limits"]
    assert (
        _json(ARCH / "fomc_3x_20bps_cost_stress/metrics.json")["native_trade_net_pnl"]
        < 0
    )
