"""Audit native funding cashflow signs against intended validation basket sides."""
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_crypto_xs_plain_funding_mvp_20261015 import build_baskets

SESSION = "crypto_xs_plain_funding_decay_validation_20261015_v1"
DATA = ROOT / "data" / "processed" / SESSION
OUT = ROOT / "run_log" / "research_sessions" / SESSION / "decay_forensics"
LEDGER = OUT / "corrected_native_base_funding_ledger.parquet"
STATE = OUT / "corrected_native_base_portfolio_state.parquet"
TRADES = OUT / "corrected_native_base_trades.parquet"


def main() -> None:
    signal = pl.read_parquet(DATA / "signal_panel_preoutcome.parquet")
    baskets = build_baskets(signal)
    ledger = pl.read_parquet(LEDGER).sort("timestamp", "symbol")
    state = pl.read_parquet(STATE).sort("timestamp")
    trades = pl.read_parquet(TRADES)

    cycles = []
    for decision_ts, targets in sorted(baskets.items()):
        entry = decision_ts + timedelta(hours=1)
        exit_ = entry + timedelta(hours=48)
        for symbol, weight in targets.items():
            cycles.append({
                "decision_ts": decision_ts,
                "entry_ts": entry,
                "exit_ts": exit_,
                "symbol": symbol,
                "target_weight": weight,
                "target_side": "LONG" if weight > 0 else "SHORT",
            })
    cycle_df = pl.DataFrame(cycles)

    # Assign each ledger event to the intended cycle using the frozen
    # required-event convention: entry < event <= exit.
    joined_parts = []
    for row in cycle_df.iter_rows(named=True):
        part = ledger.filter(
            (pl.col("symbol") == row["symbol"])
            & (pl.col("timestamp") > row["entry_ts"])
            & (pl.col("timestamp") <= row["exit_ts"])
        )
        if part.height:
            joined_parts.append(
                part.with_columns(
                    pl.lit(row["decision_ts"]).alias("decision_ts"),
                    pl.lit(row["target_weight"]).alias("target_weight"),
                    pl.lit(row["target_side"]).alias("target_side"),
                )
            )
    assigned = pl.concat(joined_parts) if joined_parts else ledger.head(0)

    assigned = assigned.with_columns(
        pl.when(pl.col("quantity") > 0)
        .then(pl.lit("LONG"))
        .when(pl.col("quantity") < 0)
        .then(pl.lit("SHORT"))
        .otherwise(pl.lit("FLAT"))
        .alias("actual_side"),
        (pl.col("cashflow") > 0).alias("cashflow_positive"),
    ).with_columns(
        (pl.col("actual_side") == pl.col("target_side")).alias("side_matches_target"),
        (pl.col("quantity").abs() * pl.col("mark_price")).alias("abs_notional"),
    )

    unmatched = ledger.join(
        assigned.select("timestamp", "symbol").unique(),
        on=["timestamp", "symbol"],
        how="anti",
    )

    by_symbol = (
        assigned.group_by("symbol")
        .agg(
            pl.len().alias("events"),
            pl.col("cashflow").sum().alias("funding_usdt"),
            pl.col("abs_notional").mean().alias("avg_abs_notional"),
            pl.col("side_matches_target").mean().alias("side_match_share"),
            pl.col("cashflow_positive").mean().alias("positive_cashflow_share"),
        )
        .sort("funding_usdt")
    )

    by_year = (
        assigned.with_columns(pl.col("timestamp").dt.year().alias("year"))
        .group_by("year")
        .agg(
            pl.len().alias("events"),
            pl.col("cashflow").sum().alias("funding_usdt"),
            pl.col("side_matches_target").mean().alias("side_match_share"),
            pl.col("cashflow_positive").mean().alias("positive_cashflow_share"),
        )
        .sort("year")
    )

    mismatch = assigned.filter(~pl.col("side_matches_target"))
    mismatch_by_symbol = (
        mismatch.group_by("symbol")
        .agg(
            pl.len().alias("mismatch_events"),
            pl.col("cashflow").sum().alias("mismatch_funding_usdt"),
            pl.col("abs_notional").mean().alias("avg_abs_notional"),
        )
        .sort("mismatch_funding_usdt")
    )

    nonpositive = state.filter(pl.col("equity") <= 0)
    first_nonpositive = (
        nonpositive.row(0, named=True) if nonpositive.height else None
    )

    open_trades = trades.filter(pl.col("status") != "closed")
    summary = {
        "ledger_events": ledger.height,
        "assigned_events": assigned.height,
        "unmatched_events": unmatched.height,
        "total_funding_usdt": float(ledger["cashflow"].sum()),
        "assigned_funding_usdt": float(assigned["cashflow"].sum()),
        "side_match_share": float(assigned["side_matches_target"].mean()),
        "positive_cashflow_share": float(assigned["cashflow_positive"].mean()),
        "mismatch_events": mismatch.height,
        "mismatch_funding_usdt": float(mismatch["cashflow"].sum()) if mismatch.height else 0.0,
        "first_nonpositive_equity": first_nonpositive,
        "open_trade_records": open_trades.height,
        "worst_funding_symbols": by_symbol.head(15).to_dicts(),
        "best_funding_symbols": by_symbol.tail(15).sort("funding_usdt", descending=True).to_dicts(),
        "mismatch_symbols": mismatch_by_symbol.head(20).to_dicts(),
        "annual": by_year.to_dicts(),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    assigned.write_parquet(OUT / "native_funding_events_with_intended_side.parquet")
    by_symbol.write_csv(OUT / "native_funding_by_symbol.csv")
    mismatch.write_parquet(OUT / "native_funding_side_mismatches.parquet")
    (OUT / "native_funding_path_audit.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
