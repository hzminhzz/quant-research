"""Diagnostic 2x-cost native arm for frozen 2024-2025 decay validation.

Runs the frozen portfolio/cost model with corrected validation funding-event
window. It intentionally permits terminal insolvency so the economic failure is
recorded instead of aborting on the final-flat assertion.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import timedelta
from pathlib import Path

import polars as pl
from ml4t.backtest import DataFeed, Engine

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.run_crypto_xs_plain_funding_decay_validation_20261015 as frozen
from scripts.prepare_crypto_xs_plain_funding_decay_validation_20261015 import (
    DATA,
    VALID_END,
    VALID_START,
    load_bounded,
)
from scripts.run_crypto_xs_plain_funding_decay_validation_execution_fix1_20261015 import (
    validation_funding_events_by_hour,
)
from scripts.run_crypto_xs_plain_funding_mvp_20261015 import (
    FundingBasketStrategy,
    build_baskets,
)

OUT = (
    ROOT / "run_log" / "research_sessions"
    / "crypto_xs_plain_funding_decay_validation_20261015_v1"
    / "decay_forensics"
)


def main() -> None:
    signal = pl.read_parquet(DATA / "signal_panel_preoutcome.parquet")
    baskets = build_baskets(signal)
    prices, _ = load_bounded()
    marks = pl.read_parquet(DATA / "required_funding_events_with_marks.parquet")
    funding_proxy = marks.select(
        "timestamp", "symbol", "funding_interval_hours", "funding_rate",
        pl.col("mark_proxy").alias("mark_price"),
    )
    selected = set().union(*(set(targets) for targets in baskets.values()))
    feed_prices = prices.filter(
        pl.col("symbol").is_in(sorted(selected))
        & (pl.col("timestamp") >= VALID_START)
        & (pl.col("timestamp") < VALID_END)
    ).sort("timestamp", "symbol")
    events = validation_funding_events_by_hour(funding_proxy, selected)
    flatten_ts = max(baskets) + timedelta(hours=48)
    strategy = FundingBasketStrategy(
        baskets, events, apply_funding=True, flatten_ts=flatten_ts
    )
    result = Engine(
        DataFeed(prices_df=feed_prices, entity_col="symbol", timestamp_col="timestamp"),
        strategy,
        frozen.backtest_config(2.0),
    ).run()

    state = result.to_portfolio_state_dataframe()
    fills = result.to_fills_dataframe()
    trades = result.to_trades_dataframe()
    rejected = result.to_rejected_orders_dataframe()
    ledger = pl.DataFrame(strategy.funding_ledger)

    OUT.mkdir(parents=True, exist_ok=True)
    state.write_parquet(OUT / "corrected_native_double_cost_portfolio_state.parquet")
    fills.write_csv(OUT / "corrected_native_double_cost_fills.csv")
    trades.write_parquet(OUT / "corrected_native_double_cost_trades.parquet")
    ledger.write_parquet(OUT / "corrected_native_double_cost_funding_ledger.parquet")

    nonpositive = state.filter(pl.col("equity") <= 0)
    first_nonpositive = nonpositive.row(0, named=True) if nonpositive.height else None
    payload = {
        "arm": "corrected_native_double_cost_diagnostic",
        "cost_multiplier": 2.0,
        "final_value": float(result.metrics["final_value"]),
        "min_equity": float(state["equity"].min()),
        "final_equity": float(state["equity"][-1]),
        "final_cash": float(state["cash"][-1]),
        "final_open_positions": int(state["open_positions"][-1]),
        "rejected_orders": rejected.height,
        "fills": fills.height,
        "funding_events": ledger.height,
        "funding_cashflow_usdt": float(ledger["cashflow"].sum()),
        "first_nonpositive_equity": first_nonpositive,
        "last_state_ts": str(state["timestamp"][-1]),
        "terminal_insolvency": bool(nonpositive.height),
        "protected_2026_plus_accessed": bool(state["timestamp"].max().year >= 2026),
    }
    (OUT / "corrected_native_double_cost_diagnostic.json").write_text(
        json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
