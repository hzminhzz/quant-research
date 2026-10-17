"""Phase 4 native backtest for the Phase-3-qualified plain funding factor."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from ml4t.backtest import BacktestConfig, DataFeed, Engine
from ml4t.backtest.config import CommissionType, ExecutionPrice, ShareType, SlippageType
from ml4t.backtest.types import ExecutionMode

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_crypto_xs_plain_funding_mvp_20261015 import (
    BASE_COMMISSION,
    BASE_SLIPPAGE,
    DEV_END,
    DEV_START,
    INITIAL_CASH,
    FundingBasketStrategy,
    build_baskets,
    funding_events_by_hour,
    load_bounded,
)

SESSION = "crypto_xs_plain_funding_phase4_20261015_v1"
PHASE3 = "crypto_xs_plain_funding_mvp_20261015_v1"
OUT = ROOT / "run_log" / "research_sessions" / SESSION / "phase4"
DATA = ROOT / "data" / "processed" / SESSION
FACTOR_PANEL = (
    ROOT / "run_log" / "research_sessions" / PHASE3 / "mvp" / "factor_panel.parquet"
)
MARK_EVENTS = DATA / "required_funding_events_with_marks.parquet"

SHARPE_MIN = 0.50
MAX_DD_FLOOR = -0.35


def sha256(path: Path) -> str:
    with path.open("rb") as fp:
        return hashlib.file_digest(fp, "sha256").hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False, default=str) + "\n")


def config(cost_multiplier: float) -> BacktestConfig:
    return BacktestConfig(
        initial_cash=INITIAL_CASH,
        allow_short_selling=True,
        allow_leverage=True,
        share_type=ShareType.FRACTIONAL,
        execution_mode=ExecutionMode.NEXT_BAR,
        execution_price=ExecutionPrice.OPEN,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=BASE_COMMISSION * cost_multiplier,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=BASE_SLIPPAGE * cost_multiplier,
    )


def daily_metrics(equity: pl.DataFrame) -> tuple[dict[str, Any], pl.DataFrame, dict[str, float]]:
    if equity.is_empty():
        raise ValueError("empty equity")
    daily = (
        equity.with_columns(pl.col("timestamp").dt.date().alias("date"))
        .group_by("date")
        .agg(pl.col("equity").last().alias("equity"))
        .sort("date")
        .with_columns(pl.col("equity").pct_change().fill_null(0.0).alias("return"))
    )
    returns = daily["return"].to_numpy()
    active = returns[1:] if len(returns) > 1 else np.asarray([], dtype=float)
    mean = float(active.mean()) if len(active) else 0.0
    std = float(active.std(ddof=1)) if len(active) > 1 else 0.0
    sharpe = mean / std * math.sqrt(365.25) if std > 0 else None

    values = daily["equity"].to_numpy()
    running_max = np.maximum.accumulate(values)
    drawdowns = values / running_max - 1.0
    max_dd = float(drawdowns.min())

    start_equity = float(values[0])
    final_equity = float(values[-1])
    days = max(1, (daily["date"][-1] - daily["date"][0]).days)
    cagr = (final_equity / start_equity) ** (365.25 / days) - 1.0
    calmar = cagr / abs(max_dd) if max_dd < 0 else None

    yearly = (
        daily.with_columns(pl.col("date").dt.year().alias("year"))
        .group_by("year")
        .agg(((pl.col("return") + 1).product() - 1).alias("return"))
        .sort("year")
    )
    yearly_map = {
        str(row["year"]): float(row["return"]) for row in yearly.iter_rows(named=True)
    }
    metrics = {
        "daily_sharpe": sharpe,
        "max_drawdown": max_dd,
        "cagr": float(cagr),
        "calmar": float(calmar) if calmar is not None and math.isfinite(calmar) else None,
        "daily_observations": daily.height,
    }
    return metrics, daily, yearly_map


def load_execution_inputs() -> tuple[
    pl.DataFrame, pl.DataFrame, dict[datetime, dict[str, float]], pl.DataFrame
]:
    if not FACTOR_PANEL.exists():
        raise FileNotFoundError(FACTOR_PANEL)
    if not MARK_EVENTS.exists():
        raise FileNotFoundError(MARK_EVENTS)

    prices, _ = load_bounded()
    panel = pl.read_parquet(FACTOR_PANEL)
    baskets = build_baskets(panel)
    marks = pl.read_parquet(MARK_EVENTS).sort("timestamp", "symbol")

    required = {
        "timestamp", "symbol", "funding_interval_hours", "funding_rate",
        "mark_proxy", "mark_quality", "prior_mark_close",
    }
    missing = required - set(marks.columns)
    if missing:
        raise ValueError(f"mark event evidence missing columns: {sorted(missing)}")
    if marks.group_by("symbol", "timestamp").len().filter(pl.col("len") > 1).height:
        raise ValueError("duplicate funding mark events")
    if marks.filter(
        (~pl.col("mark_proxy").is_finite()) | (pl.col("mark_proxy") <= 0)
        | (~pl.col("prior_mark_close").is_finite()) | (pl.col("prior_mark_close") <= 0)
        | (~pl.col("funding_rate").is_finite())
        | (~pl.col("mark_quality").is_in([
            "EVENT_MINUTE_OPEN", "PRIOR_MINUTE_CLOSE_FALLBACK"
        ]))
    ).height:
        raise ValueError("invalid funding mark evidence")
    fallback = marks.filter(
        pl.col("mark_quality") == "PRIOR_MINUTE_CLOSE_FALLBACK"
    )
    if fallback.select("symbol", "timestamp").to_dicts() != [{
        "symbol": "LITUSDT",
        "timestamp": datetime(2023, 2, 24, 0, 0, 0, 15_000, tzinfo=UTC),
    }]:
        raise ValueError("unexpected Phase 4 funding mark fallback set")

    funding_proxy = marks.select(
        "timestamp",
        "symbol",
        "funding_interval_hours",
        "funding_rate",
        pl.col("mark_proxy").alias("mark_price"),
    )
    return prices, funding_proxy, baskets, marks


def _verify_cost_ledger(fills: pl.DataFrame, native_metrics: dict[str, Any]) -> dict[str, float]:
    commission = float(fills["commission"].sum()) if fills.height else 0.0
    slippage = (
        float((fills["slippage"].abs() * fills["quantity"].abs()).sum())
        if fills.height else 0.0
    )
    native_commission = float(native_metrics["total_commission"])
    native_slippage = float(native_metrics["total_slippage"])
    if not math.isclose(commission, native_commission, rel_tol=1e-9, abs_tol=1e-6):
        raise AssertionError(
            f"commission mismatch fills={commission} native={native_commission}"
        )
    if not math.isclose(slippage, native_slippage, rel_tol=1e-9, abs_tol=1e-6):
        raise AssertionError(
            f"slippage mismatch fills={slippage} native={native_slippage}"
        )
    return {"commission": commission, "slippage": slippage}


def run_arm(
    arm: str,
    prices: pl.DataFrame,
    funding_proxy: pl.DataFrame,
    baskets: dict[datetime, dict[str, float]],
    *,
    cost_multiplier: float,
    apply_funding: bool,
) -> tuple[dict[str, Any], pl.DataFrame]:
    destination = OUT / arm
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"immutable Phase 4 arm already exists: {destination}")
    destination.mkdir(parents=True, exist_ok=True)

    selected_symbols = set().union(*(set(targets) for targets in baskets.values()))
    feed_prices = prices.filter(
        pl.col("symbol").is_in(sorted(selected_symbols))
        & (pl.col("timestamp") >= DEV_START)
        & (pl.col("timestamp") < DEV_END)
    ).sort("timestamp", "symbol")
    events = funding_events_by_hour(funding_proxy, selected_symbols)
    # Datetime arithmetic is explicit to keep the engine clock type stable.
    from datetime import timedelta
    flatten_ts = max(baskets) + timedelta(hours=48)
    if flatten_ts >= DEV_END:
        raise AssertionError("flatten timestamp reaches protected boundary")

    strategy = FundingBasketStrategy(
        baskets,
        events,
        apply_funding=apply_funding,
        flatten_ts=flatten_ts,
    )
    result = Engine(
        DataFeed(prices_df=feed_prices, entity_col="symbol", timestamp_col="timestamp"),
        strategy,
        config(cost_multiplier),
    ).run()

    fills = result.to_fills_dataframe()
    trades = result.to_trades_dataframe()
    equity = result.to_equity_dataframe()
    portfolio_state = result.to_portfolio_state_dataframe()
    rejected = result.to_rejected_orders_dataframe()

    fills.write_csv(destination / "fills.csv")
    trades.write_csv(destination / "trades.csv")
    equity.write_parquet(destination / "hourly_equity.parquet")
    portfolio_state.write_parquet(destination / "portfolio_state.parquet")
    if rejected.height:
        rejected.write_csv(destination / "rejected_orders.csv")
    if strategy.funding_ledger:
        funding_ledger = pl.DataFrame(strategy.funding_ledger)
    else:
        funding_ledger = pl.DataFrame(
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
    funding_ledger.write_parquet(destination / "funding_ledger.parquet")
    pl.DataFrame(strategy.rebalance_log).write_csv(destination / "rebalance_log.csv")

    if rejected.height:
        raise AssertionError(f"{arm}: native rejected orders={rejected.height}")
    if portfolio_state["open_positions"][-1] != 0:
        raise AssertionError(f"{arm}: final native portfolio not flat")

    fill_map = {
        row["order_id"]: row["timestamp"].replace(tzinfo=UTC)
        if row["timestamp"].tzinfo is None
        else row["timestamp"].astimezone(UTC)
        for row in fills.iter_rows(named=True)
    }
    missing_fills = set(strategy.order_expected_fill) - set(fill_map)
    if missing_fills:
        raise AssertionError(f"{arm}: {len(missing_fills)} submitted orders did not fill")
    for order_id, expected in strategy.order_expected_fill.items():
        if fill_map[order_id] != expected:
            raise AssertionError(
                f"{arm}: fill clock mismatch {order_id}: "
                f"{fill_map[order_id]} != {expected}"
            )

    if funding_ledger.height:
        cash_identity = (
            funding_ledger["cash_after"] - funding_ledger["cash_before"]
            - funding_ledger["cashflow"]
        ).abs().max()
        if float(cash_identity) > 1e-7:
            raise AssertionError(f"{arm}: funding cash-ledger identity failed")
    funding_total = (
        float(funding_ledger["cashflow"].sum()) if funding_ledger.height else 0.0
    )

    cost_ledger = _verify_cost_ledger(fills, result.metrics)
    native_final = float(result.metrics["final_value"])
    equity_final = float(equity["equity"][-1])
    if not math.isclose(native_final, equity_final, rel_tol=0.0, abs_tol=1e-7):
        raise AssertionError(f"{arm}: final equity mismatch")

    risk, daily, yearly = daily_metrics(equity)
    daily.write_csv(destination / "daily_equity.csv")

    gross_over_equity = (
        portfolio_state.filter(pl.col("equity") > 0)
        .select((pl.col("gross_exposure") / pl.col("equity")).max())
        .item()
    )
    payload = {
        "arm": arm,
        "cost_multiplier": cost_multiplier,
        "commission_bps_per_side": BASE_COMMISSION * 10_000 * cost_multiplier,
        "slippage_bps_per_side": BASE_SLIPPAGE * 10_000 * cost_multiplier,
        "funding_applied": apply_funding,
        "symbols_ever_selected": len(selected_symbols),
        "rebalance_cycles": len(baskets),
        "fills": fills.height,
        "closed_trades": trades.filter(pl.col("status") == "closed").height
        if trades.height else 0,
        "rejected_orders": rejected.height,
        "funding_events_with_position": funding_ledger.height,
        "funding_cashflow_usdt": funding_total,
        "final_equity_usdt": native_final,
        "net_pnl_usdt": native_final - INITIAL_CASH,
        "total_return": native_final / INITIAL_CASH - 1.0,
        "max_gross_exposure_over_equity": float(gross_over_equity or 0.0),
        "cost_ledger": cost_ledger,
        "daily_risk": risk,
        "yearly_returns": yearly,
        "native_metrics": {
            key: (
                float(value)
                if isinstance(value, (int, float, np.number))
                and math.isfinite(float(value))
                else str(value)
            )
            for key, value in result.metrics.items()
        },
    }
    write_json(destination / "metrics.json", payload)
    return payload, funding_ledger


def funding_mark_sensitivity(
    primary_ledger: pl.DataFrame,
    mark_events: pl.DataFrame,
) -> dict[str, Any]:
    if primary_ledger.is_empty():
        raise AssertionError("No realized funding events in base portfolio")
    sensitivity = (
        primary_ledger.select("timestamp", "symbol", "quantity", "funding_rate", "cashflow")
        .rename({"cashflow": "primary_cashflow"})
        .join(
            mark_events.select("timestamp", "symbol", "prior_mark_close"),
            on=["timestamp", "symbol"],
            how="left",
        )
        .with_columns(
            (-pl.col("quantity") * pl.col("prior_mark_close") * pl.col("funding_rate"))
            .alias("prior_close_cashflow")
        )
    )
    if sensitivity["prior_mark_close"].null_count():
        raise AssertionError("Missing prior mark close in sensitivity")
    primary = float(sensitivity["primary_cashflow"].sum())
    prior = float(sensitivity["prior_close_cashflow"].sum())
    same_sign = (primary > 0 and prior > 0) or (primary < 0 and prior < 0)
    sensitivity.write_parquet(OUT / "funding_mark_sensitivity.parquet")
    result = {
        "primary_event_minute_open_funding_usdt": primary,
        "prior_minute_close_funding_usdt": prior,
        "difference_usdt": prior - primary,
        "relative_difference": (prior / primary - 1.0) if primary != 0 else None,
        "same_sign": same_sign,
        "events": sensitivity.height,
    }
    write_json(OUT / "funding_mark_sensitivity.json", result)
    return result


def gate(
    base: dict[str, Any],
    stress: dict[str, Any],
    sensitivity: dict[str, Any],
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if base["total_return"] <= 0:
        reasons.append("base-cost net total return is not positive")
    sharpe = base["daily_risk"]["daily_sharpe"]
    if sharpe is None or float(sharpe) < SHARPE_MIN:
        reasons.append(f"base-cost daily Sharpe {sharpe} < {SHARPE_MIN}")
    max_dd = float(base["daily_risk"]["max_drawdown"])
    if max_dd < MAX_DD_FLOOR:
        reasons.append(f"base-cost max drawdown {max_dd} < {MAX_DD_FLOOR}")
    if base["funding_cashflow_usdt"] <= 0:
        reasons.append("realized funding cashflow is not positive")
    if stress["total_return"] <= 0:
        reasons.append("2x execution-cost portfolio is not net profitable")
    if not sensitivity["same_sign"]:
        return "INCONCLUSIVE", [
            "funding contribution changes sign under prior-minute-close mark sensitivity"
        ]
    return ("REJECT" if reasons else "VALIDATE"), reasons


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        parser.error("Use --run")
    frozen = ROOT / "run_log" / "research_sessions" / SESSION / "frozen_spec.json"
    if not frozen.exists():
        raise RuntimeError("Freeze the Phase 4 session before running portfolio PnL")
    if (OUT / "terminal_decision.json").exists():
        raise FileExistsError("Phase 4 terminal evidence already exists")
    OUT.mkdir(parents=True, exist_ok=True)

    prices, funding_proxy, baskets, mark_events = load_execution_inputs()
    base, base_ledger = run_arm(
        "native_funding_base_cost",
        prices,
        funding_proxy,
        baskets,
        cost_multiplier=1.0,
        apply_funding=True,
    )
    stress, _ = run_arm(
        "native_funding_double_cost",
        prices,
        funding_proxy,
        baskets,
        cost_multiplier=2.0,
        apply_funding=True,
    )
    nofund, _ = run_arm(
        "native_no_funding_decomposition",
        prices,
        funding_proxy,
        baskets,
        cost_multiplier=1.0,
        apply_funding=False,
    )
    sensitivity = funding_mark_sensitivity(base_ledger, mark_events)
    decision, reasons = gate(base, stress, sensitivity)

    terminal = {
        "decision": decision,
        "stage": "PHASE4_NATIVE_BACKTEST",
        "classification": "EXPLORATORY",
        "approval_status": "NOT_APPROVED",
        "protected_2024_plus_accessed": False,
        "reasons": reasons,
        "base": base,
        "double_cost": stress,
        "no_funding": nofund,
        "funding_mark_sensitivity": sensitivity,
        "price_only_net_pnl_usdt": nofund["net_pnl_usdt"],
        "funding_aware_increment_vs_no_funding_usdt": (
            base["net_pnl_usdt"] - nofund["net_pnl_usdt"]
        ),
        "mark_event_file": str(MARK_EVENTS.relative_to(ROOT)),
        "mark_event_sha256": sha256(MARK_EVENTS),
    }
    write_json(OUT / "terminal_decision.json", terminal)
    print(json.dumps({
        "decision": decision,
        "base_return": base["total_return"],
        "base_sharpe": base["daily_risk"]["daily_sharpe"],
        "base_max_dd": base["daily_risk"]["max_drawdown"],
        "base_funding": base["funding_cashflow_usdt"],
        "double_cost_return": stress["total_return"],
        "no_funding_return": nofund["total_return"],
        "sensitivity_same_sign": sensitivity["same_sign"],
        "reasons": reasons,
    }, indent=2))


if __name__ == "__main__":
    main()
