"""Read-only independent review of immutable native Milkman Engine ledgers.

Risk-adjusted statistics call ML4T's own analytics on daily marked equity,
NOT the engine's intraday-bar-level headline Sharpe. No source data touched.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import polars as pl
from ml4t.backtest.analytics import max_drawdown, sharpe_ratio, sortino_ratio

CASES = (
    "morning_dip_limit", "legends_buy_day", "legends_ema",
    "bilbo_box_v2", "swing_golden_gate", "daily_bilbo_boxes",
)


def audit(root: Path, *, swing_root: Path | None = None) -> dict:
    result = {"review": "INDEPENDENT_LEDGER_AUDIT", "cases": {}}
    for case in CASES:
        folder = (swing_root if case == 'swing_golden_gate' and swing_root else root) / case
        if not (folder / "report.json").is_file():
            result["cases"][case] = {"audit": "BLOCKED", "reason": "Missing native report"}
            continue
        r = json.loads((folder / "report.json").read_text())
        eq = pl.read_csv(folder / "equity.csv", try_parse_dates=True).sort("timestamp")
        prices = pl.read_parquet(folder / "prices.parquet")
        signals = pl.read_parquet(folder / "signals.parquet")
        fills = pl.read_csv(folder / "fills.csv", try_parse_dates=True)
        trades = pl.read_csv(folder / "trades.csv", try_parse_dates=True)
        if fills.height and fills["timestamp"].dtype.time_zone is None:
            # Engine serializes fill timestamps without offset, in UTC event clock.
            fills = fills.with_columns(pl.col("timestamp").dt.replace_time_zone("UTC"))
        if not eq.height or prices.is_empty():
            raise AssertionError(f"{case}: empty native price/equity")
        if prices["timestamp"].max().year >= 2025:
            raise AssertionError(f"{case}: PROTECTED DATA ACCESSED")
        if prices["timestamp"].n_unique() != prices.height or signals["timestamp"].n_unique() != signals.height:
            raise AssertionError(f"{case}: duplicate clock")
        if prices["timestamp"].min() != eq["timestamp"].min():
            raise AssertionError(f"{case}: incomplete engine equity")
        pnl = trades["pnl"].sum() if trades.height else 0
        delta = float(eq["equity"][-1] - r["metrics"]["initial_cash"])
        reconciled = abs(pnl - delta) <= .02
        if not reconciled:
            raise AssertionError(f"{case}: Engine PnL/trade ledger mismatch {pnl} != {delta}")
        if fills.height and not (fills["timestamp"].min() >= prices["timestamp"].min() and fills["timestamp"].max() <= prices["timestamp"].max()):
            raise AssertionError(f"{case}: fill outside price sample")

        local = pl.col("timestamp").dt.convert_time_zone("America/New_York")
        session = local.dt.date()
        if case == "legends_buy_day":
            session = pl.when(local.dt.hour() >= 18).then(
                local.dt.date() + pl.duration(days=1)
            ).otherwise(local.dt.date())
        daily = (eq.with_columns(session.alias("session"))
                 .group_by("session").agg(
                    pl.col("equity").sort_by("timestamp").last().alias("close_equity")
                 ).sort("session"))
        ret = daily["close_equity"].pct_change().fill_null(0)
        # Native ML4T daily-returns risk metrics; not custom Sharpe calculators.
        daily_sharpe = sharpe_ratio(ret.to_numpy())
        daily_sortino = sortino_ratio(ret.to_numpy())
        daily_maxdd = max_drawdown(daily["close_equity"].to_list())[0]
        source_closed = trades.filter(pl.col("status") == "closed").height if trades.height else 0
        open_trades = trades.filter(pl.col("status") != "closed").height if trades.height else 0
        # Negative development PnL is an economic falsifier, not a library failure.
        disposition = ("INCONCLUSIVE_NO_TRADES" if not trades.height else
                       "NEGATIVE_CFD_MVP" if delta < 0 else
                       "POSITIVE_CFD_MVP_UNQUALIFIED")
        if open_trades:
            disposition = "INCONCLUSIVE_OPEN_POSITION_AT_BOUNDARY"
        result["cases"][case] = {
            "native_status": r["status"], "audit": "LEDGER_RECONCILED",
            "evidence_dir": str(folder),
            "development_only": True,
            "time": [str(prices["timestamp"].min()), str(prices["timestamp"].max())],
            "price_bars": prices.height,
            "daily_marked_equity_sessions": daily.height,
            "filled_orders": fills.height, "closed_trades": source_closed,
            "open_trades_at_boundary": open_trades,
            "net_equity_return_pct": 100 * delta / float(r["metrics"]["initial_cash"]),
            "daily_equity_sharpe_252": daily_sharpe,
            "daily_equity_sortino_252": daily_sortino,
            "daily_equity_maxdd": daily_maxdd,
            "native_bar_sharpe_NOT_comparable": r["metrics"]["sharpe"],
            "pnl_reconcile_difference": pnl - delta,
            "broker_costs": r["metrics"]["total_costs"],
            "disposition": disposition,
        }
    return result


def main():
    arg = argparse.ArgumentParser()
    arg.add_argument("--root", type=Path, default=Path("run_log/milkman_native_cfd_mvp_20261014_retry2"))
    arg.add_argument("--swing-root", type=Path, default=None)
    args = arg.parse_args()
    result = audit(args.root, swing_root=args.swing_root)
    print(json.dumps(result, indent=2, default=str, allow_nan=False))


if __name__ == "__main__":
    main()
