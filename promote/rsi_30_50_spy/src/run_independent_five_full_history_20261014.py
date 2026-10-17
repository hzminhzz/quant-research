"""Native full-available-history extension for five preselected independent strategies.

Uses canonical ml4t-data, installed ml4t-engineer and ml4t-backtest.
Preserves the 2026-10-12+ repository protected data boundary.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
from ml4t.backtest import DataFeed, Engine
from ml4t.backtest.analytics.metrics import max_drawdown, sharpe_ratio

from src.strategies.independent_seven_data import load_daily
from scripts.run_independent_seven_2020_2022 import (
    CASES, _build, _config, _safe,
)

CASES_FROZEN = (
    "pivot-breakout-btc", "donchian-btc", "three-red-spy",
    "slope-hook", "rsi-30-50",
)
PROTECTED = datetime(2026, 10, 12, tzinfo=timezone.utc)
START_BY_ASSET = {
    "BTC": datetime(2019, 9, 1, tzinfo=timezone.utc),
    "ES": datetime(2011, 1, 1, tzinfo=timezone.utc),
}
OUTPUT = Path("run_log/independent_five_full_history_20261014")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def segments(equity: pl.DataFrame, *, calendar: str) -> dict:
    """Use ML4T-native analytics metrics for segments; no return simulator."""
    equity = equity.sort("timestamp")
    equity = equity.with_columns(
        pl.col("timestamp").str.to_datetime(strict=False).alias("parsed_ts")
    ) if equity.schema["timestamp"] == pl.String else equity.with_columns(
        pl.col("timestamp").alias("parsed_ts")
    )
    segments = {}
    windows = [
        ("full", None, None),
        ("pre_2020", None, "2020-01-01"),
        ("selected_2020_2022", "2020-01-01", "2023-01-01"),
        ("after_selection_2023_2025", "2023-01-01", "2026-01-01"),
        ("2026_ytd", "2026-01-01", "2026-10-12"),
    ] + [(str(y), f"{y}-01-01", f"{y+1}-01-01")
         for y in range(2011, 2027)]
    for label, after, before in windows:
        subset = equity
        if after is not None:
            subset = subset.filter(pl.col("parsed_ts") >= pl.lit(datetime.fromisoformat(after).replace(tzinfo=timezone.utc)))
        if before is not None:
            subset = subset.filter(pl.col("parsed_ts") < pl.lit(datetime.fromisoformat(before).replace(tzinfo=timezone.utc)))
        if subset.height < 2:
            continue
        values = subset["equity"].to_numpy()
        rets = subset["return"].to_numpy()
        rets = rets[~__import__("numpy").isnan(rets)]
        ratio = float(sharpe_ratio(rets)) if len(rets) >= 2 else None
        dd, _, _ = max_drawdown(values)
        segments[label] = {
            "sessions": len(values),
            "net_return_pct": float((values[-1] / values[0] - 1) * 100),
            "sharpe_252": ratio if ratio is not None and math.isfinite(ratio) else None,
            "max_drawdown_pct": float(dd * 100),
            "start": str(subset["parsed_ts"][0]),
            "end": str(subset["parsed_ts"][-1]),
        }
    return segments


def run_one(name: str, data: dict[str, pl.DataFrame], manifests: dict):
    asset, fee, slip = CASES[name]
    price, signals, strategy = _build(
        name, data,
        start=START_BY_ASSET[asset],
        end=PROTECTED,
    )
    if price.height < 400:
        raise ValueError(f"{name}: insufficient history ({price.height})")
    assert price["timestamp"].max() < PROTECTED, "Protected 2026-10-12+ leak"
    cfg = _config(fee, slip, leverage=(name == "donchian-btc"))
    engine = Engine(DataFeed(prices_df=price, signals_df=signals), strategy, cfg)
    result = engine.run()
    folder = OUTPUT / name
    folder.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "prices.parquet": price,
        "signals.parquet": signals,
    }
    for fname, frame in artifacts.items():
        frame.write_parquet(folder / fname)
    result.to_equity_dataframe().write_csv(folder / "equity.csv")
    result.to_trades_dataframe().write_csv(folder / "trades.csv")
    result.to_fills_dataframe().write_csv(folder / "fills.csv")
    result.to_rejected_orders_dataframe().write_csv(folder / "rejected_orders.csv")
    eq = result.to_equity_dataframe()
    report = {
        "strategy": name,
        "status": "EXPLORATORY_HISTORICAL_EXTENSION_NOT_INDEPENDENT_OOS",
        "source_asset": asset,
        "source_manifest": manifests[asset],
        "protected_after_utc": PROTECTED.isoformat(),
        "first": str(price["timestamp"].min()),
        "last": str(price["timestamp"].max()),
        "bars": price.height,
        "commission_bps_per_side": fee,
        "slippage_bps_per_side": slip,
        "engine": "ml4t-backtest==0.1.7",
        "feature_library": "ml4t-engineer==0.1.4",
        "metrics": _safe(result.metrics),
        "segments": segments(eq, calendar="crypto" if asset=="BTC" else "ES_proxy"),
        "fills": len(result.fills),
        "closed_trade_rows": len(result.trades),
        "native_rejections": len(result.rejected_orders),
        "artifact_sha256": {p: _sha(folder / p) for p in (
            "prices.parquet", "signals.parquet", "equity.csv",
            "trades.csv", "fills.csv", "rejected_orders.csv")},
        "caveats": [
            "Five separate strategy simulations, no Shannon portfolio",
            "Source proxy: Binance BTCUSDT perpetual for BTC, ES CFD/index for SPY",
            "BTC funding, index/CFD financing, SPY distributions absent",
            "2020-2022 was selection sample; later historical data not an untouched holdout",
            "Native next-bar fills, generic fee and slippage assumptions",
            "No parameter reoptimization; pivot stop entry-bar protection unqualified",
            "Engine Sharpe convention not independently calibrated for 365-day crypto",
        ],
    }
    (folder / "summary.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({
        "case": name, "bars": price.height, "first": report["first"], "last": report["last"],
        "trades": report["metrics"].get("num_trades"),
        "net_pct": report["metrics"].get("total_return_pct"),
        "sharpe": report["metrics"].get("sharpe"),
        "mdd_pct": report["metrics"].get("max_drawdown_pct"),
        "post_2022": report["segments"].get("after_selection_2023_2025"),
    }), flush=True)
    return report


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    data, manifests = {}, {}
    for asset, first in [("BTC", 2019), ("ES", 2011)]:
        print(f"LOADING {asset} {first}-2026", flush=True)
        data[asset], manifests[asset] = load_daily(
            asset, first_year=first, last_year=2026, end_exclusive=PROTECTED
        )
        print("DATA", json.dumps(manifests[asset]), flush=True)
    (OUTPUT / "data_manifest.json").write_text(json.dumps(manifests, indent=2) + "\n")
    outcomes = []
    for name in CASES_FROZEN:
        print("RUN", name, flush=True)
        try:
            outcomes.append(run_one(name, data, manifests))
        except Exception as exc:
            import traceback
            d = OUTPUT / name
            d.mkdir(exist_ok=True)
            (d / "failure.json").write_text(
                json.dumps({"case": name, "error": str(exc),
                            "traceback": traceback.format_exc()}, indent=2))
            print("FAILED", name, repr(exc), flush=True)
    summary = {
        "status": "COMPLETE" if len(outcomes)==len(CASES_FROZEN) else "INCOMPLETE",
        "expected": list(CASES_FROZEN),
        "completed": [x["strategy"] for x in outcomes],
        "protected": PROTECTED.isoformat(),
        "pre_registered_plan": "docs/plans/independent_five_full_history_20261014.md",
    }
    (OUTPUT / "manifest.json").write_text(json.dumps(summary, indent=2) + "\n")
    if len(outcomes) != len(CASES_FROZEN):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
