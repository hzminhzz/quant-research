"""2024-2025 untouched decay validation for the plain funding factor.

This script may run only after the validation session is frozen. It consumes the
pre-outcome signal/basket evidence and official funding-mark evidence prepared
before any validation forward return or portfolio PnL was computed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from ml4t.backtest import BacktestConfig, DataFeed, Engine
from ml4t.backtest.config import CommissionType, ExecutionPrice, ShareType, SlippageType
from ml4t.backtest.types import ExecutionMode
from ml4t.diagnostic.api import compute_ic_hac_stats, cross_sectional_ic_series

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.prepare_crypto_xs_plain_funding_decay_validation_20261015 import (
    DATA,
    SESSION,
    VALID_END,
    VALID_START,
    load_bounded,
)
from scripts.run_crypto_xs_plain_funding_mvp_20261015 import (
    BASE_COMMISSION,
    BASE_SLIPPAGE,
    INITIAL_CASH,
    FundingBasketStrategy,
    build_baskets,
    funding_events_by_hour,
)

OUT = ROOT / "run_log" / "research_sessions" / SESSION / "validation"
SIGNAL_PANEL = DATA / "signal_panel_preoutcome.parquet"
MARK_EVENTS = DATA / "required_funding_events_with_marks.parquet"

REF_MEAN_IC = 0.02399168729832182
REF_FUNDING_SPREAD = 0.0027302096098901084
REF_FUNDING_STD = 0.0013136886087678446
REF_FUNDING_IQR = 0.0003206761538461478
REF_FUNDING_YIELD = 0.45797758483123224
REF_NO_FUNDING_RETURN = 0.3622286629428122


def sha256(path: Path) -> str:
    with path.open("rb") as fp:
        return hashlib.file_digest(fp, "sha256").hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False, default=str) + "\n")


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def backtest_config(cost_multiplier: float) -> BacktestConfig:
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


def attach_validation_labels(signal: pl.DataFrame, prices: pl.DataFrame) -> pl.DataFrame:
    opens = prices.select("symbol", "timestamp", pl.col("open").alias("entry_open"))
    panel = signal.with_columns(
        (pl.col("decision_ts") + pl.duration(hours=1)).alias("entry_ts"),
        (pl.col("decision_ts") + pl.duration(hours=49)).alias("exit_ts"),
    )
    panel = (
        panel.join(
            opens.rename({"timestamp": "entry_ts"}),
            on=["symbol", "entry_ts"],
            how="left",
        )
        .join(
            opens.rename({"timestamp": "exit_ts", "entry_open": "exit_open"}),
            on=["symbol", "exit_ts"],
            how="left",
        )
        .with_columns(
            (pl.col("exit_open") / pl.col("entry_open") - 1).alias(
                "forward_return_48h"
            )
        )
        .filter(
            pl.col("entry_open").is_not_null()
            & pl.col("exit_open").is_not_null()
            & pl.col("forward_return_48h").is_finite()
        )
        .sort("decision_ts", "symbol")
    )
    if panel.height != signal.height:
        missing = signal.height - panel.height
        raise RuntimeError(f"validation forward labels missing rows={missing}")
    if panel.filter(pl.col("exit_ts") >= VALID_END).height:
        raise AssertionError("validation label crosses protected 2026 boundary")
    return panel


def ic_diagnostics(panel: pl.DataFrame) -> tuple[dict[str, Any], pl.DataFrame]:
    predictions = panel.select(
        pl.col("decision_ts").alias("date"), "symbol", "prediction"
    )
    returns = panel.select(
        pl.col("decision_ts").alias("date"),
        "symbol",
        pl.col("forward_return_48h").alias("forward_return"),
    )
    series = cross_sectional_ic_series(
        predictions,
        returns,
        pred_col="prediction",
        ret_col="forward_return",
        date_col="date",
        entity_col="symbol",
        method="spearman",
        min_obs=10,
    ).filter(pl.col("ic").is_not_null()).sort("date")
    if series.is_empty():
        raise RuntimeError("no validation IC series")
    stats = compute_ic_hac_stats(
        series, ic_col="ic", maxlags=1, label_horizon=1
    )
    values = series["ic"].to_numpy()
    ic_ir = (
        float(values.mean() / values.std(ddof=1))
        if len(values) > 1 and values.std(ddof=1) > 0
        else None
    )
    annual_rows: list[dict[str, Any]] = []
    for year, group in series.with_columns(
        pl.col("date").dt.year().alias("year")
    ).group_by("year", maintain_order=True):
        year_value = int(year[0] if isinstance(year, tuple) else year)
        annual_stats = compute_ic_hac_stats(
            group, ic_col="ic", maxlags=1, label_horizon=1
        )
        annual_rows.append(
            {
                "year": year_value,
                "cycles": group.height,
                "mean_ic": float(group["ic"].mean()),
                "ic_ir": float(
                    group["ic"].mean() / group["ic"].std()
                ) if group.height > 1 and group["ic"].std() else None,
                "positive_ic_share": float((group["ic"] > 0).mean()),
                "hac_t_stat": float(annual_stats["t_stat"]),
                "hac_p_value": float(annual_stats["p_value"]),
            }
        )
    annual = pl.DataFrame(annual_rows).sort("year")

    rolling = (
        series.with_columns(
            pl.col("ic").rolling_mean(91, min_samples=30).alias("rolling_6m_ic"),
            pl.col("ic").rolling_mean(183, min_samples=60).alias("rolling_12m_ic"),
        )
    )
    result = {
        "mean_ic": float(stats["mean_ic"]),
        "hac_t_stat": float(stats["t_stat"]),
        "hac_p_value": float(stats["p_value"]),
        "hac_se": float(stats["hac_se"]),
        "ic_ir": ic_ir,
        "positive_ic_share": float((series["ic"] > 0).mean()),
        "cycles": series.height,
        "annual": annual.to_dicts(),
        "reference_2022_2023_mean_ic": REF_MEAN_IC,
        "ic_ratio_to_reference": float(stats["mean_ic"]) / REF_MEAN_IC,
        "latest_6m_rolling_ic": (
            float(rolling["rolling_6m_ic"].drop_nulls()[-1])
            if rolling["rolling_6m_ic"].drop_nulls().len()
            else None
        ),
        "latest_12m_rolling_ic": (
            float(rolling["rolling_12m_ic"].drop_nulls()[-1])
            if rolling["rolling_12m_ic"].drop_nulls().len()
            else None
        ),
    }
    return result, rolling


def opportunity_metrics(signal: pl.DataFrame) -> tuple[dict[str, Any], pl.DataFrame]:
    per_cycle = (
        signal.group_by("decision_ts")
        .agg(
            (
                pl.col("cum_funding_24h").top_k(5).mean()
                - pl.col("cum_funding_24h").bottom_k(5).mean()
            ).alias("top5_minus_bottom5_funding_24h"),
            pl.col("cum_funding_24h").std().alias("xs_funding_std"),
            (
                pl.col("cum_funding_24h").quantile(0.75)
                - pl.col("cum_funding_24h").quantile(0.25)
            ).alias("xs_funding_iqr"),
            pl.len().alias("universe_size"),
        )
        .sort("decision_ts")
    )
    annual = (
        per_cycle.with_columns(pl.col("decision_ts").dt.year().alias("year"))
        .group_by("year")
        .agg(
            pl.len().alias("cycles"),
            pl.col("top5_minus_bottom5_funding_24h").mean().alias(
                "mean_top5_minus_bottom5"
            ),
            pl.col("xs_funding_std").mean().alias("mean_xs_std"),
            pl.col("xs_funding_iqr").mean().alias("mean_xs_iqr"),
        )
        .sort("year")
    )
    spread = float(per_cycle["top5_minus_bottom5_funding_24h"].mean())
    std = float(per_cycle["xs_funding_std"].mean())
    iqr = float(per_cycle["xs_funding_iqr"].mean())
    result = {
        "cycles": per_cycle.height,
        "mean_top5_minus_bottom5_funding_24h": spread,
        "mean_cross_section_funding_std": std,
        "mean_cross_section_funding_iqr": iqr,
        "funding_spread_ratio_to_2022_2023": spread / REF_FUNDING_SPREAD,
        "funding_std_ratio_to_2022_2023": std / REF_FUNDING_STD,
        "funding_iqr_ratio_to_2022_2023": iqr / REF_FUNDING_IQR,
        "annual": annual.to_dicts(),
    }
    return result, per_cycle


def daily_risk_metrics(equity: pl.DataFrame) -> tuple[dict[str, Any], pl.DataFrame]:
    daily = (
        equity.with_columns(pl.col("timestamp").dt.date().alias("date"))
        .group_by("date")
        .agg(pl.col("equity").last().alias("equity"))
        .sort("date")
        .with_columns(pl.col("equity").pct_change().fill_null(0.0).alias("return"))
    )
    returns = daily["return"].to_numpy()[1:]
    std = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    sharpe = (
        float(returns.mean()) / std * math.sqrt(365.25)
        if std > 0 else None
    )
    values = daily["equity"].to_numpy()
    running_max = np.maximum.accumulate(values)
    max_dd = float((values / running_max - 1.0).min())
    days = max(1, (daily["date"][-1] - daily["date"][0]).days)
    cagr = float((values[-1] / values[0]) ** (365.25 / days) - 1.0)
    calmar = cagr / abs(max_dd) if max_dd < 0 else None
    yearly = (
        daily.with_columns(pl.col("date").dt.year().alias("year"))
        .group_by("year")
        .agg(((pl.col("return") + 1).product() - 1).alias("return"))
        .sort("year")
    )
    return {
        "daily_sharpe": sharpe,
        "max_drawdown": max_dd,
        "cagr": cagr,
        "calmar": float(calmar) if calmar is not None else None,
        "daily_observations": daily.height,
        "yearly_returns": {
            str(row["year"]): float(row["return"])
            for row in yearly.iter_rows(named=True)
        },
    }, daily


def _verify_native_costs(
    fills: pl.DataFrame, metrics: dict[str, Any]
) -> dict[str, float]:
    commission = float(fills["commission"].sum()) if fills.height else 0.0
    slippage = (
        float((fills["slippage"].abs() * fills["quantity"].abs()).sum())
        if fills.height else 0.0
    )
    if not math.isclose(
        commission, float(metrics["total_commission"]), rel_tol=1e-9, abs_tol=1e-6
    ):
        raise AssertionError("native commission reconciliation failed")
    if not math.isclose(
        slippage, float(metrics["total_slippage"]), rel_tol=1e-9, abs_tol=1e-6
    ):
        raise AssertionError("native slippage reconciliation failed")
    return {"commission_usdt": commission, "slippage_usdt": slippage}


def run_native_arm(
    name: str,
    prices: pl.DataFrame,
    funding_proxy: pl.DataFrame,
    baskets: dict[datetime, dict[str, float]],
    *,
    cost_multiplier: float,
    apply_funding: bool,
) -> tuple[dict[str, Any], pl.DataFrame]:
    destination = OUT / name
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"immutable validation arm already exists: {destination}")
    destination.mkdir(parents=True, exist_ok=True)

    selected_symbols = set().union(*(set(targets) for targets in baskets.values()))
    feed_prices = (
        prices.filter(
            pl.col("symbol").is_in(sorted(selected_symbols))
            & (pl.col("timestamp") >= VALID_START)
            & (pl.col("timestamp") < VALID_END)
        )
        .sort("timestamp", "symbol")
    )
    if feed_prices.filter(pl.col("timestamp") >= VALID_END).height:
        raise AssertionError("2026 price reached native feed")

    events = funding_events_by_hour(funding_proxy, selected_symbols)
    flatten_ts = max(baskets) + timedelta(hours=48)
    if flatten_ts + timedelta(hours=1) >= VALID_END:
        raise AssertionError("flatten fill reaches protected 2026 boundary")

    strategy = FundingBasketStrategy(
        baskets,
        events,
        apply_funding=apply_funding,
        flatten_ts=flatten_ts,
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
    portfolio_state = result.to_portfolio_state_dataframe()
    rejected = result.to_rejected_orders_dataframe()

    if rejected.height:
        rejected.write_csv(destination / "rejected_orders.csv")
        raise AssertionError(f"{name}: rejected native orders={rejected.height}")
    if portfolio_state["open_positions"][-1] != 0:
        raise AssertionError(f"{name}: final portfolio not flat")
    if equity["timestamp"].max() >= VALID_END:
        raise AssertionError(f"{name}: native equity reaches 2026")

    fill_map = {
        row["order_id"]: _utc(row["timestamp"])
        for row in fills.iter_rows(named=True)
    }
    if set(strategy.order_expected_fill) - set(fill_map):
        raise AssertionError(f"{name}: submitted order without fill")
    for order_id, expected in strategy.order_expected_fill.items():
        if fill_map[order_id] != expected:
            raise AssertionError(
                f"{name}: fill clock mismatch {fill_map[order_id]} != {expected}"
            )

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
    if funding_ledger.height:
        identity = (
            funding_ledger["cash_after"]
            - funding_ledger["cash_before"]
            - funding_ledger["cashflow"]
        ).abs().max()
        if float(identity) > 1e-7:
            raise AssertionError(f"{name}: funding cash ledger mismatch")

    cost_ledger = _verify_native_costs(fills, result.metrics)
    final_equity = float(equity["equity"][-1])
    if not math.isclose(
        final_equity, float(result.metrics["final_value"]), abs_tol=1e-7
    ):
        raise AssertionError(f"{name}: native final equity mismatch")

    risk, daily = daily_risk_metrics(equity)
    daily.write_csv(destination / "daily_equity.csv")
    fills.write_csv(destination / "fills.csv")
    trades.write_csv(destination / "trades.csv")
    equity.write_parquet(destination / "hourly_equity.parquet")
    portfolio_state.write_parquet(destination / "portfolio_state.parquet")
    funding_ledger.write_parquet(destination / "funding_ledger.parquet")
    pl.DataFrame(strategy.rebalance_log).write_csv(destination / "rebalance_log.csv")

    funding_total = (
        float(funding_ledger["cashflow"].sum()) if funding_ledger.height else 0.0
    )
    elapsed_years = (
        (portfolio_state["timestamp"].max() - portfolio_state["timestamp"].min())
        .total_seconds()
        / (365.25 * 24 * 3600)
    )
    avg_gross = float(portfolio_state["gross_exposure"].mean())
    funding_yield = (
        funding_total / avg_gross / elapsed_years
        if apply_funding and avg_gross > 0 and elapsed_years > 0
        else 0.0
    )
    annual_funding_rows: list[dict[str, Any]] = []
    if funding_ledger.height:
        for year, group in funding_ledger.with_columns(
            pl.col("timestamp").dt.year().alias("year")
        ).group_by("year", maintain_order=True):
            year_value = int(year[0] if isinstance(year, tuple) else year)
            year_state = portfolio_state.filter(
                pl.col("timestamp").dt.year() == year_value
            )
            year_hours = (
                (
                    year_state["timestamp"].max()
                    - year_state["timestamp"].min()
                ).total_seconds()
                / 3600
                + 1
            )
            year_avg_gross = float(year_state["gross_exposure"].mean())
            year_funding = float(group["cashflow"].sum())
            annual_funding_rows.append(
                {
                    "year": year_value,
                    "funding_usdt": year_funding,
                    "events": group.height,
                    "avg_gross_usdt": year_avg_gross,
                    "annualized_funding_yield_on_avg_gross": (
                        year_funding
                        / year_avg_gross
                        / (year_hours / (365.25 * 24))
                    ) if year_avg_gross > 0 else None,
                }
            )

    payload = {
        "arm": name,
        "cost_multiplier": cost_multiplier,
        "funding_applied": apply_funding,
        "rebalance_cycles": len(baskets),
        "symbols_ever_selected": len(selected_symbols),
        "fills": fills.height,
        "rejected_orders": rejected.height,
        "funding_events_with_position": funding_ledger.height,
        "funding_cashflow_usdt": funding_total,
        "avg_gross_exposure_usdt": avg_gross,
        "annualized_funding_yield_on_avg_gross": funding_yield,
        "annual_funding": annual_funding_rows,
        "final_equity_usdt": final_equity,
        "net_pnl_usdt": final_equity - INITIAL_CASH,
        "total_return": final_equity / INITIAL_CASH - 1.0,
        "cost_ledger": cost_ledger,
        "risk": risk,
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


def terminal_and_decay(
    ic: dict[str, Any],
    opportunity: dict[str, Any],
    base: dict[str, Any],
    stress: dict[str, Any],
    nofund: dict[str, Any],
) -> tuple[str, str, list[str], dict[str, Any]]:
    reasons: list[str] = []
    if base["total_return"] <= 0:
        reasons.append("base-cost validation return is not positive")
    if stress["total_return"] <= 0:
        reasons.append("2x-cost validation return is not positive")
    if base["annualized_funding_yield_on_avg_gross"] <= 0:
        reasons.append("normalized realized funding yield is not positive")
    terminal = "REJECT" if reasons else "VALIDATE"

    ic_ratio = ic["mean_ic"] / REF_MEAN_IC
    funding_ratio = (
        base["annualized_funding_yield_on_avg_gross"] / REF_FUNDING_YIELD
    )
    price_only_ratio = nofund["total_return"] / REF_NO_FUNDING_RETURN
    if terminal == "REJECT":
        decay = "STRUCTURAL_DECAY"
    elif ic["mean_ic"] <= 0:
        decay = "MECHANISM_SHIFT_CARRY"
    elif ic_ratio >= 0.50 and funding_ratio >= 0.50:
        decay = "NO_MATERIAL_DECAY"
    else:
        decay = "PARTIAL_DECAY"

    ratios = {
        "ic_ratio_to_2022_2023": ic_ratio,
        "normalized_funding_yield_ratio_to_2022_2023": funding_ratio,
        "price_only_total_return_ratio_to_2022_2023": price_only_ratio,
        "funding_spread_ratio_to_2022_2023": opportunity[
            "funding_spread_ratio_to_2022_2023"
        ],
        "funding_std_ratio_to_2022_2023": opportunity[
            "funding_std_ratio_to_2022_2023"
        ],
        "funding_iqr_ratio_to_2022_2023": opportunity[
            "funding_iqr_ratio_to_2022_2023"
        ],
    }
    return terminal, decay, reasons, ratios


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        parser.error("use --run")

    frozen = ROOT / "run_log" / "research_sessions" / SESSION / "frozen_spec.json"
    if not frozen.exists():
        raise RuntimeError("freeze validation session before opening outcomes")
    terminal_path = OUT / "terminal_decision.json"
    if terminal_path.exists():
        raise FileExistsError("validation terminal evidence already exists")

    if not SIGNAL_PANEL.exists() or not MARK_EVENTS.exists():
        raise FileNotFoundError("pre-outcome signal or mark evidence missing")
    OUT.mkdir(parents=True, exist_ok=True)

    signal = pl.read_parquet(SIGNAL_PANEL)
    prices, _ = load_bounded()
    panel = attach_validation_labels(signal, prices)
    panel.write_parquet(OUT / "factor_panel_with_labels.parquet")
    ic, rolling = ic_diagnostics(panel)
    rolling.write_csv(OUT / "ic_series_and_rolling.csv")
    write_json(OUT / "ic_diagnostics.json", ic)

    opportunity, per_cycle = opportunity_metrics(signal)
    per_cycle.write_csv(OUT / "funding_opportunity_cycles.csv")
    write_json(OUT / "funding_opportunity_decay.json", opportunity)

    baskets = build_baskets(signal)
    mark_events = pl.read_parquet(MARK_EVENTS)
    if mark_events.filter(pl.col("timestamp") >= VALID_END).height:
        raise AssertionError("2026 funding mark event loaded")
    required = {
        "timestamp", "symbol", "funding_interval_hours", "funding_rate",
        "mark_proxy", "mark_quality",
    }
    if required - set(mark_events.columns):
        raise RuntimeError("funding mark evidence schema incomplete")
    funding_proxy = mark_events.select(
        "timestamp",
        "symbol",
        "funding_interval_hours",
        "funding_rate",
        pl.col("mark_proxy").alias("mark_price"),
    )

    base, _ = run_native_arm(
        "validation_native_base_cost",
        prices,
        funding_proxy,
        baskets,
        cost_multiplier=1.0,
        apply_funding=True,
    )
    stress, _ = run_native_arm(
        "validation_native_double_cost",
        prices,
        funding_proxy,
        baskets,
        cost_multiplier=2.0,
        apply_funding=True,
    )
    nofund, _ = run_native_arm(
        "validation_native_no_funding",
        prices,
        funding_proxy,
        baskets,
        cost_multiplier=1.0,
        apply_funding=False,
    )

    terminal, decay, reasons, ratios = terminal_and_decay(
        ic, opportunity, base, stress, nofund
    )
    result = {
        "decision": terminal,
        "decay_classification": decay,
        "stage": "2024_2025_DECAY_VALIDATION",
        "classification": "VALIDATION",
        "approval_status": "NOT_APPROVED",
        "protected_2026_plus_accessed": False,
        "reasons": reasons,
        "ic": ic,
        "opportunity": opportunity,
        "base": base,
        "double_cost": stress,
        "no_funding": nofund,
        "decay_ratios": ratios,
        "reference_2022_2023": {
            "mean_ic": REF_MEAN_IC,
            "funding_spread": REF_FUNDING_SPREAD,
            "funding_std": REF_FUNDING_STD,
            "funding_iqr": REF_FUNDING_IQR,
            "annualized_funding_yield_on_avg_gross": REF_FUNDING_YIELD,
            "no_funding_total_return": REF_NO_FUNDING_RETURN,
        },
        "signal_panel_sha256": sha256(SIGNAL_PANEL),
        "mark_events_sha256": sha256(MARK_EVENTS),
    }
    write_json(terminal_path, result)
    print(json.dumps({
        "decision": terminal,
        "decay_classification": decay,
        "mean_ic": ic["mean_ic"],
        "ic_ratio": ratios["ic_ratio_to_2022_2023"],
        "funding_yield": base["annualized_funding_yield_on_avg_gross"],
        "funding_yield_ratio": ratios[
            "normalized_funding_yield_ratio_to_2022_2023"
        ],
        "funding_spread_ratio": ratios[
            "funding_spread_ratio_to_2022_2023"
        ],
        "base_return": base["total_return"],
        "double_cost_return": stress["total_return"],
        "no_funding_return": nofund["total_return"],
        "base_sharpe": base["risk"]["daily_sharpe"],
        "base_max_dd": base["risk"]["max_drawdown"],
        "reasons": reasons,
    }, indent=2))


if __name__ == "__main__":
    main()
