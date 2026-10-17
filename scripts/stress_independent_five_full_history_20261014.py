"""Exploratory 2x/3x native execution cost stress, same frozen five signals."""
from __future__ import annotations
import json
from pathlib import Path
import polars as pl
from ml4t.backtest import Engine, DataFeed
from scripts.run_independent_seven_2020_2022 import (
    CASES, _config, PivotNativeStopRule, ExposureRule, BinaryRule
)
from scripts.run_independent_five_full_history_20261014 import OUTPUT, CASES_FROZEN


def new_strategy(case: str):
    return (PivotNativeStopRule("BTC") if case == "pivot-breakout-btc"
            else ExposureRule("BTC") if case == "donchian-btc"
            else BinaryRule("ES"))


def main():
    outcomes = []
    for case in CASES_FROZEN:
        folder = OUTPUT / case
        prices = pl.read_parquet(folder / "prices.parquet")
        signals = pl.read_parquet(folder / "signals.parquet")
        source_summary = json.loads((folder / "summary.json").read_text())
        asset, commission, slippage = CASES[case]
        for multiple in (2, 3):
            cfg = _config(commission * multiple, slippage * multiple,
                          leverage=case == "donchian-btc")
            result = Engine(DataFeed(prices_df=prices, signals_df=signals),
                            new_strategy(case), cfg).run()
            m = result.metrics
            one = {
                "case": case,
                "stress_multiple": multiple,
                "baseline_cost_bps_per_side": commission + slippage,
                "stress_cost_bps_per_side": (commission + slippage) * multiple,
                "net_return_pct": m["total_return_pct"],
                "sharpe_252_native": m["sharpe"],
                "mdd_pct": m["max_drawdown_pct"],
                "filled_orders": m["num_fills"],
                "completed_trades": m["num_trades"],
                "rejected_orders": m["num_rejected_orders"],
                "original_price_hash": source_summary["artifact_sha256"]["prices.parquet"],
                "original_signal_hash": source_summary["artifact_sha256"]["signals.parquet"],
            }
            outcomes.append(one)
            print(json.dumps(one), flush=True)
    path = OUTPUT / "cost_stress_2x_3x.json"
    path.write_text(json.dumps({
        "status": "EXPLORATORY_POST_BASELINE_COST_STRESS",
        "trials": outcomes,
        "basis": "native Engine, exact same five price and signal parquet files",
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
