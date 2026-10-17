"""Diagnostic only: inspect corrected validation base arm without terminal gates."""
from __future__ import annotations

import sys
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


def main() -> None:
    signal = pl.read_parquet(DATA / "signal_panel_preoutcome.parquet")
    baskets = build_baskets(signal)
    prices, _ = load_bounded()
    marks = pl.read_parquet(DATA / "required_funding_events_with_marks.parquet")
    funding_proxy = marks.select(
        "timestamp",
        "symbol",
        "funding_interval_hours",
        "funding_rate",
        pl.col("mark_proxy").alias("mark_price"),
    )
    selected_symbols = set().union(*(set(targets) for targets in baskets.values()))
    feed_prices = (
        prices.filter(
            pl.col("symbol").is_in(sorted(selected_symbols))
            & (pl.col("timestamp") >= VALID_START)
            & (pl.col("timestamp") < VALID_END)
        )
        .sort("timestamp", "symbol")
    )
    events = validation_funding_events_by_hour(funding_proxy, selected_symbols)
    from datetime import timedelta
    flatten_ts = max(baskets) + timedelta(hours=48)
    strategy = FundingBasketStrategy(
        baskets, events, apply_funding=True, flatten_ts=flatten_ts
    )
    result = Engine(
        DataFeed(prices_df=feed_prices, entity_col="symbol", timestamp_col="timestamp"),
        strategy,
        frozen.backtest_config(1.0),
    ).run()
    state = result.to_portfolio_state_dataframe()
    trades = result.to_trades_dataframe()
    rejected = result.to_rejected_orders_dataframe()
    open_trades = trades.filter(pl.col("status") != "closed") if trades.height else trades
    out = (
        ROOT / "run_log" / "research_sessions"
        / "crypto_xs_plain_funding_decay_validation_20261015_v1"
        / "decay_forensics"
    )
    out.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(strategy.funding_ledger).write_parquet(
        out / "corrected_native_base_funding_ledger.parquet"
    )
    trades.write_parquet(out / "corrected_native_base_trades.parquet")
    state.write_parquet(out / "corrected_native_base_portfolio_state.parquet")
    print({
        "final_value": result.metrics["final_value"],
        "min_equity": float(state["equity"].min()),
        "final_equity": float(state["equity"][-1]),
        "final_cash": float(state["cash"][-1]),
        "final_open_positions": int(state["open_positions"][-1]),
        "rejected_orders": rejected.height,
        "funding_events": len(strategy.funding_ledger),
        "funding_total": float(sum(x["cashflow"] for x in strategy.funding_ledger)),
        "flatten_ts": str(flatten_ts),
        "last_state_ts": str(state["timestamp"][-1]),
    })
    print("tail_state")
    print(state.tail(8))
    print("open_trades")
    print(open_trades.tail(30))


if __name__ == "__main__":
    main()
