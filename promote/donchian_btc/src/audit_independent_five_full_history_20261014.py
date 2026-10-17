"""Independent read-only audit of five full-history native ML4T backtests."""
from __future__ import annotations
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
import polars as pl

ROOT = Path("run_log/independent_five_full_history_20261014")
FROZEN = ("pivot-breakout-btc", "donchian-btc",
          "three-red-spy", "slope-hook", "rsi-30-50")
PROTECTED = datetime(2026, 10, 12, tzinfo=timezone.utc)


def audit():
    results = []
    manifest = json.loads((ROOT / "manifest.json").read_text())
    assert manifest["status"] == "COMPLETE"
    assert tuple(manifest["completed"]) == FROZEN
    assert (ROOT / "exit_code.txt").read_text().strip() == "0"
    for case in FROZEN:
        directory = ROOT / case
        report = json.loads((directory / "summary.json").read_text())
        assert report["status"].startswith("EXPLORATORY_")
        assert report["protected_after_utc"] == PROTECTED.isoformat()
        for filename, expected in report["artifact_sha256"].items():
            digest = hashlib.sha256((directory / filename).read_bytes()).hexdigest()
            assert digest == expected, (case, filename)
        price = pl.read_parquet(directory / "prices.parquet")
        signal = pl.read_parquet(directory / "signals.parquet")
        eq = pl.read_csv(directory / "equity.csv")
        fills = pl.read_csv(directory / "fills.csv")
        trades = pl.read_csv(directory / "trades.csv")
        assert price.height == signal.height == eq.height == report["bars"]
        assert price["timestamp"].n_unique() == price.height
        assert price["timestamp"].max() < PROTECTED
        assert signal["timestamp"].max() < PROTECTED
        assert not price.select(pl.all().is_null().sum()).row(0)[0]
        assert (price["close"] > 0).all()
        assert price.filter((pl.col("high") < pl.col("low")) |
                            (pl.col("open") > pl.col("high")) |
                            (pl.col("open") < pl.col("low")) |
                            (pl.col("close") > pl.col("high")) |
                            (pl.col("close") < pl.col("low"))).height == 0
        assert fills.height == report["fills"] == report["metrics"]["num_fills"]
        assert trades.height == report["closed_trade_rows"]
        assert report["native_rejections"] == 0 == report["metrics"]["num_rejected_orders"]
        assert math.isclose(float(eq["equity"][-1]), report["metrics"]["final_value"], abs_tol=.001)
        assert math.isclose(
            (float(eq["equity"][-1]) / 100000.0 - 1) * 100,
            report["metrics"]["total_return_pct"], abs_tol=.001
        )
        assert set(report["segments"]).issuperset(
            {"full", "selected_2020_2022", "after_selection_2023_2025", "2026_ytd"}
        )
        results.append({
            "case":case, "outcome":"PASS", "price_rows":price.height,
            "fills":fills.height, "source_end":report["last"],
            "net_pct":report["metrics"]["total_return_pct"],
            "sha256_verified":True,
        })
    payload = {
        "status":"PASS",
        "scope":"artifact hashes, source cutoff, native equity/fill/trade reconciliation",
        "cases":results,
        "excluded":"no source-parity certification, no cost calibration, no true unseen holdout",
    }
    (ROOT / "audit.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))

if __name__ == "__main__":
    audit()
