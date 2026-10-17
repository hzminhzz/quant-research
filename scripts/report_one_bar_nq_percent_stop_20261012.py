"""Reproduce realized-PnL risk comparison: original B0 vs 2021-anchored percent stop."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
from ml4t.backtest.analytics import sharpe_ratio, max_drawdown, calmar_ratio

ROOT = Path(__file__).resolve().parents[1]
B0 = ROOT / "run_log/one_bar_practical_1m_20261012/by_year"
PCT = ROOT / "run_log/one_bar_nq_percent_stop_20261012/by_year"
OUT = ROOT / "run_log/one_bar_nq_percent_stop_20261012/comparison_realized_daily.json"
PERIODS = {
    "2013_2021_ex_post_anchor": (date(2013, 1, 1), date(2022, 1, 1), range(2013, 2022)),
    "2022_2025": (date(2022, 1, 1), date(2026, 1, 1), range(2022, 2026)),
    "2026_through_jul14": (date(2026, 1, 1), date(2026, 7, 15), [2026]),
    "2022_through_jul2026": (date(2022, 1, 1), date(2026, 7, 15), range(2022, 2027)),
    "2013_through_jul2026": (date(2013, 1, 1), date(2026, 7, 15), range(2013, 2027)),
}
VARIANTS = {
    "B0": (B0, "native_full_tick_cost"),
    "percent_stop": (PCT, "percent_costed"),
}

def risk_stats(base: Path, trial: str, years, start: date, end: date) -> dict:
    frames = [
        pl.read_csv(base / str(y) / trial / "evaluation_trades.csv", try_parse_dates=True)
        for y in years
    ]
    trades = pl.concat(frames, how="diagonal_relaxed").filter(pl.col("status") == "closed")
    cash = trades.group_by(pl.col("entry_time").dt.date().alias("day")).agg(
        pl.col("pnl").sum().alias("pnl")
    )
    pnl_by_day = dict(zip(cash["day"].to_list(), cash["pnl"].to_list(), strict=True))
    n_days = (end - start).days
    pnl = np.asarray(
        [pnl_by_day.get(start + timedelta(days=i), 0.0) for i in range(n_days)],
        dtype=np.float64,
    )
    balance = 1_000_000.0 + np.r_[0.0, pnl.cumsum()]
    returns = pnl / 1_000_000.0
    sr = float(sharpe_ratio(returns, annualize=False) * np.sqrt(365.25))
    max_dd, peak, trough = max_drawdown(balance)
    growth = float((balance[-1] / balance[0]) ** (365.25 / n_days) - 1.0)
    calmar = float(calmar_ratio(growth, max_dd)) if max_dd else None
    wins = trades.filter(pl.col("pnl") > 0)["pnl"].sum()
    losses = -trades.filter(pl.col("pnl") < 0)["pnl"].sum()
    net = float(trades["pnl"].sum())
    assert abs(float(pnl.sum()) - net) < 1e-5
    return {
        "closed_trades": trades.height,
        "net_pnl_usd": round(net, 2),
        "win_rate": round(float((trades["pnl"] > 0).mean()), 8),
        "profit_factor": round(float(wins / losses), 6) if losses else None,
        "average_trade_pnl_usd": round(net / trades.height, 2) if trades.height else None,
        "daily_realized_entry_date_sharpe": round(sr, 5),
        "calmar_on_assigned_1m_account": round(calmar, 5) if calmar is not None else None,
        "max_realized_drawdown_usd": round(float(balance[trough] - balance[peak]), 2),
        "max_realized_drawdown_fraction": round(float(max_dd), 8),
        "cagr_on_assigned_1m_account": round(growth, 8),
        "calendar_days": n_days,
    }

def main() -> None:
    original = json.loads(
        (ROOT / "run_log/one_bar_nq_percent_stop_20261012/final_report.json").read_text()
    )
    assert original["status"] == "COMPLETED_EXPLORATORY"
    assert original["audit"]["status"] == "passed"
    results: dict = {}
    for name, (start, end, years) in PERIODS.items():
        values = {
            scenario: risk_stats(base, trial, years, start, end)
            for scenario, (base, trial) in VARIANTS.items()
        }
        delta = round(
            values["percent_stop"]["net_pnl_usd"] - values["B0"]["net_pnl_usd"], 2
        )
        results[name] = {"B0": values["B0"], "percent_stop": values["percent_stop"],
                         "net_pnl_delta_usd": delta}
        print(name, "B0", values["B0"]["net_pnl_usd"],
              "PCT", values["percent_stop"]["net_pnl_usd"], "delta", delta)
    assert results["2013_through_jul2026"]["B0"]["net_pnl_usd"] == 166107.92
    assert results["2013_through_jul2026"]["percent_stop"]["net_pnl_usd"] == 166881.66
    assert results["2026_through_jul14"]["percent_stop"]["net_pnl_usd"] == -18743.00
    report = {
        "status": "VERIFIED historical ledger-based diagnostic, NOT live approved",
        "stop_fraction": 50.0 / 14598.25,
        "anchor": "2021 median B0 entry 14598.25; earlier data is hindsight counterfactual",
        "portfolio_assumption": "fixed illustrative 1000000 USD initial capital",
        "daily_risk_method": "closed trade net PnL allocated to UTC entry date; every UTC calendar date including zero days; sqrt(365.25), rf0; realized-only not intraday MTM",
        "source": "Dukascopy USATECH.IDX/USD BID proxy, not CME NQ",
        "comparison": results,
    }
    OUT.write_text(json.dumps(report, indent=2) + "\n")

if __name__ == "__main__":
    main()
