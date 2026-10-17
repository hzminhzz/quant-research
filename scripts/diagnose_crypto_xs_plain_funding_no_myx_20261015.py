"""Post-hoc diagnostic: remove MYXUSDT and reselect 5-long/5-short baskets.

This is NOT a validation run. 2024-2025 outcomes are already observed.
Counterfactual rule:
- preserve original top-40 liquidity-screen panel;
- blacklist MYXUSDT;
- select the next funding-ranked name from the remaining panel to keep exactly
  5 longs + 5 shorts, 1.0 gross, 0.0 net;
- preserve signal, 48h cadence, native execution, costs, and funding accounting.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl
from ml4t.backtest import DataFeed, Engine

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.prepare_crypto_xs_plain_funding_decay_validation_20261015 import (
    DATA,
    MARK_STORE,
    VALID_END,
    VALID_START,
    load_bounded,
)
from scripts.run_crypto_xs_plain_funding_mvp_20261015 import (
    FundingBasketStrategy,
    build_baskets,
    required_funding_events,
)
from scripts.run_crypto_xs_plain_funding_decay_validation_20261015 import (
    backtest_config,
    daily_risk_metrics,
)
from scripts.run_crypto_xs_plain_funding_decay_validation_execution_fix1_20261015 import (
    validation_funding_events_by_hour,
)

OUT = (
    ROOT / "run_log" / "research_sessions"
    / "crypto_xs_plain_funding_decay_validation_20261015_v1"
    / "posthoc_no_myx"
)
EXCLUDED = "MYXUSDT"


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def mark_proxy_for_events(required: pl.DataFrame) -> pl.DataFrame:
    needed: dict[tuple[str, int, int], set[datetime]] = {}
    for symbol, ts in required.select("symbol", "timestamp").iter_rows():
        minute = _utc(ts).replace(second=0, microsecond=0)
        needed.setdefault((symbol, minute.year, minute.month), set()).add(minute)

    pieces: list[pl.DataFrame] = []
    missing_partitions: list[str] = []
    for (symbol, year, month), timestamps in sorted(needed.items()):
        path = (
            MARK_STORE / f"symbol={symbol}" / f"year={year:04d}"
            / f"month={month}" / "data.parquet"
        )
        if not path.exists():
            missing_partitions.append(str(path))
            continue
        times = pl.Series(
            "needed", sorted(timestamps), dtype=pl.Datetime("ms", "UTC")
        )
        piece = (
            pl.scan_parquet(path)
            .filter(pl.col("timestamp").is_in(times.implode()))
            .select(
                pl.col("timestamp").alias("mark_minute"),
                "symbol",
                pl.col("open").alias("mark_price"),
            )
            .collect()
        )
        pieces.append(piece)

    if missing_partitions:
        raise FileNotFoundError(
            f"missing mark partitions={len(missing_partitions)} "
            f"first={missing_partitions[0]}"
        )

    marks = pl.concat(pieces).sort("symbol", "mark_minute")
    if marks.group_by("symbol", "mark_minute").len().filter(pl.col("len") > 1).height:
        raise RuntimeError("duplicate mark-minute rows")

    joined = (
        required.select(
            "timestamp", "symbol", "funding_interval_hours", "funding_rate"
        )
        .with_columns(
            pl.col("timestamp").dt.truncate("1m").alias("mark_minute")
        )
        .join(marks, on=["symbol", "mark_minute"], how="left")
        .sort("timestamp", "symbol")
    )
    missing = joined.filter(
        pl.col("mark_price").is_null()
        | (~pl.col("mark_price").is_finite())
        | (pl.col("mark_price") <= 0)
    )
    if missing.height:
        raise RuntimeError(
            f"missing/invalid exact event-minute marks={missing.height}; "
            f"first={missing.select('timestamp','symbol','mark_minute').head(1).to_dicts()}"
        )
    return joined.select(
        "timestamp", "symbol", "funding_interval_hours",
        "funding_rate", "mark_price"
    )


def run_arm(
    name: str,
    prices: pl.DataFrame,
    funding_proxy: pl.DataFrame,
    baskets: dict[datetime, dict[str, float]],
    *,
    cost_multiplier: float,
    apply_funding: bool,
) -> dict:
    destination = OUT / name
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(destination)
    destination.mkdir(parents=True, exist_ok=True)

    selected = set().union(*(set(targets) for targets in baskets.values()))
    feed_prices = prices.filter(
        pl.col("symbol").is_in(sorted(selected))
        & (pl.col("timestamp") >= VALID_START)
        & (pl.col("timestamp") < VALID_END)
    ).sort("timestamp", "symbol")
    events = validation_funding_events_by_hour(funding_proxy, selected)
    flatten_ts = max(baskets) + timedelta(hours=48)

    strategy = FundingBasketStrategy(
        baskets, events, apply_funding=apply_funding, flatten_ts=flatten_ts
    )
    result = Engine(
        DataFeed(
            prices_df=feed_prices,
            entity_col="symbol",
            timestamp_col="timestamp",
        ),
        strategy,
        backtest_config(cost_multiplier),
    ).run()

    fills = result.to_fills_dataframe()
    trades = result.to_trades_dataframe()
    equity = result.to_equity_dataframe()
    state = result.to_portfolio_state_dataframe()
    rejected = result.to_rejected_orders_dataframe()
    ledger = (
        pl.DataFrame(strategy.funding_ledger)
        if strategy.funding_ledger
        else pl.DataFrame(
            schema={
                "timestamp": pl.Datetime("us", "UTC"),
                "symbol": pl.String,
                "funding_rate": pl.Float64,
                "mark_price": pl.Float64,
                "quantity": pl.Float64,
                "cashflow": pl.Float64,
                "cash_before": pl.Float64,
                "cash_after": pl.Float64,
            }
        )
    )

    fills.write_csv(destination / "fills.csv")
    trades.write_parquet(destination / "trades.parquet")
    equity.write_parquet(destination / "hourly_equity.parquet")
    state.write_parquet(destination / "portfolio_state.parquet")
    ledger.write_parquet(destination / "funding_ledger.parquet")
    if rejected.height:
        rejected.write_csv(destination / "rejected_orders.csv")

    daily_risk, daily = daily_risk_metrics(equity)
    daily.write_csv(destination / "daily_equity.csv")

    nonpositive = state.filter(pl.col("equity") <= 0)
    first_nonpositive = (
        nonpositive.row(0, named=True) if nonpositive.height else None
    )
    funding_total = float(ledger["cashflow"].sum()) if ledger.height else 0.0
    payload = {
        "arm": name,
        "cost_multiplier": cost_multiplier,
        "funding_applied": apply_funding,
        "rebalance_cycles": len(baskets),
        "symbols_ever_selected": len(selected),
        "fills": fills.height,
        "rejected_orders": rejected.height,
        "final_equity_usdt": float(equity["equity"][-1]),
        "total_return": float(equity["equity"][-1] / 100000.0 - 1.0),
        "min_equity_usdt": float(state["equity"].min()),
        "final_open_positions": int(state["open_positions"][-1]),
        "first_nonpositive_equity": first_nonpositive,
        "funding_cashflow_usdt": funding_total,
        "funding_events": ledger.height,
        "risk": daily_risk,
        "native_metrics": {
            k: (
                float(v)
                if isinstance(v, (int, float, np.number))
                and math.isfinite(float(v))
                else str(v)
            )
            for k, v in result.metrics.items()
        },
    }
    (destination / "metrics.json").write_text(
        json.dumps(payload, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> None:
    signal = pl.read_parquet(DATA / "signal_panel_preoutcome.parquet")
    original = build_baskets(signal)
    filtered_signal = signal.filter(pl.col("symbol") != EXCLUDED)
    baskets = build_baskets(filtered_signal)

    if len(baskets) != len(original):
        raise AssertionError("counterfactual changed number of cycles")
    changed = []
    for ts in sorted(original):
        before = original[ts]
        after = baskets[ts]
        if EXCLUDED in after:
            raise AssertionError("MYX remains in counterfactual basket")
        if len(after) != 10:
            raise AssertionError(f"{ts}: counterfactual basket has {len(after)} legs")
        if not math.isclose(sum(abs(x) for x in after.values()), 1.0, abs_tol=1e-12):
            raise AssertionError("gross target changed")
        if not math.isclose(sum(after.values()), 0.0, abs_tol=1e-12):
            raise AssertionError("net target changed")
        if before != after:
            changed.append(
                {
                    "decision_ts": ts,
                    "myx_weight_before": before.get(EXCLUDED),
                    "removed": sorted(set(before) - set(after)),
                    "added": sorted(set(after) - set(before)),
                }
            )

    prices, funding = load_bounded()
    required = required_funding_events(funding, baskets)
    funding_proxy = mark_proxy_for_events(required)

    OUT.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(changed).write_json(OUT / "basket_changes.json")
    required.write_parquet(OUT / "required_funding_events.parquet")
    funding_proxy.write_parquet(OUT / "funding_events_with_marks.parquet")

    base = run_arm(
        "base_cost_funding",
        prices,
        funding_proxy,
        baskets,
        cost_multiplier=1.0,
        apply_funding=True,
    )
    stress = run_arm(
        "double_cost_funding",
        prices,
        funding_proxy,
        baskets,
        cost_multiplier=2.0,
        apply_funding=True,
    )
    nofund = run_arm(
        "base_cost_no_funding",
        prices,
        funding_proxy,
        baskets,
        cost_multiplier=1.0,
        apply_funding=False,
    )

    summary = {
        "classification": "POST_HOC_DIAGNOSTIC_NOT_VALIDATION",
        "excluded_symbol": EXCLUDED,
        "counterfactual_rule": (
            "Blacklist MYXUSDT after the frozen top-40 liquidity screen; "
            "reselect next funding-ranked name from remaining panel to preserve "
            "5 longs, 5 shorts, 1.0 gross and 0.0 net."
        ),
        "cycles": len(baskets),
        "cycles_changed": len(changed),
        "required_funding_events": required.height,
        "all_funding_marks_exact_event_minute_open": True,
        "protected_2026_plus_accessed": False,
        "base": base,
        "double_cost": stress,
        "no_funding": nofund,
    }
    (OUT / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "classification": summary["classification"],
        "cycles_changed": len(changed),
        "base_return": base["total_return"],
        "base_sharpe": base["risk"]["daily_sharpe"],
        "base_max_dd": base["risk"]["max_drawdown"],
        "base_funding": base["funding_cashflow_usdt"],
        "base_first_nonpositive": base["first_nonpositive_equity"],
        "double_cost_return": stress["total_return"],
        "double_cost_sharpe": stress["risk"]["daily_sharpe"],
        "double_cost_max_dd": stress["risk"]["max_drawdown"],
        "no_funding_return": nofund["total_return"],
        "no_funding_sharpe": nofund["risk"]["daily_sharpe"],
        "no_funding_max_dd": nofund["risk"]["max_drawdown"],
    }, indent=2))


if __name__ == "__main__":
    main()
