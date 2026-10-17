"""Read-only independent artifact audit for 2020-2022 native seven cases."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import polars as pl

ROOT = Path("run_log/independent_seven_2020_2022")
CASES = (
    "pivot-breakout-btc", "donchian-btc", "three-red-spy",
    "gold-macd-hook", "slope-hook", "fx-timing", "rsi-30-50",
)

def audit():
    rows = []
    for name in CASES:
        folder = ROOT / name
        report = json.loads((folder / "summary.json").read_text())
        prices = pl.read_parquet(folder / "prices.parquet")
        signals = pl.read_parquet(folder / "signals.parquet")
        equity = pl.read_csv(folder / "equity.csv", try_parse_dates=True)
        fills = pl.read_csv(folder / "fills.csv", try_parse_dates=True)
        trades = pl.read_csv(folder / "trades.csv")
        assert prices.height == signals.height == equity.height == report["observations"]
        assert report["native_engine"].startswith("ml4t-backtest")
        assert all(
            hashlib.sha256((folder / path).read_bytes()).hexdigest() == report["frozen_artifact_hashes"][key]
            for path, key in (("prices.parquet", "prices_sha256"),
                              ("signals.parquet", "signals_sha256"))
        )
        assert prices["timestamp"].n_unique() == prices.height
        assert prices["timestamp"].min().year == 2020
        assert prices["timestamp"].max().year == 2022
        assert prices["high"].min() > 0 and prices["low"].min() > 0
        assert prices.filter(
            (pl.col("open") > pl.col("high")) | (pl.col("open") < pl.col("low"))
            | (pl.col("close") > pl.col("high")) | (pl.col("close") < pl.col("low"))
        ).height == 0
        assert len(fills) == report["fills"] == report["metrics"]["num_fills"]
        assert len(trades) == report["closed_trades"]
        assert report["metrics"]["num_rejected_orders"] == 0
        last_native_equity = float(equity["equity"][-1])
        last_reported_equity = float(report["metrics"]["final_value"])
        assert abs(last_native_equity - last_reported_equity) < 0.001
        rows.append({
            "case": name, "status": "PASS", "native_final_equity": last_reported_equity,
            "native_sharpe": report["metrics"]["sharpe"],
            "native_max_dd_pct": report["metrics"]["max_drawdown_pct"],
            "native_net_return_pct": report["metrics"]["total_return_pct"],
            "native_closed_trades": report["metrics"]["num_trades"],
            "fills": len(fills), "bars": prices.height,
            "data_hashes_verified": True, "rejected_orders": 0,
        })
    payload = {
        "status": "PASS",
        "audit_type": "artifact_integrity_and_native_ledger_only",
        "cases": rows,
        "research_readiness": "EXPLORATORY; ETF proxy and execution-model limitations unresolved",
    }
    (ROOT / "independent_audit.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))

if __name__ == "__main__":
    audit()
