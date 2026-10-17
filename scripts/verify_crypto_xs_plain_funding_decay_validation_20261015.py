"""Independent verifier for 2024-2025 plain-funding decay validation."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import polars as pl
from ml4t.diagnostic.api import compute_ic_hac_stats, cross_sectional_ic_series

ROOT = Path(__file__).resolve().parents[1]
SESSION = "crypto_xs_plain_funding_decay_validation_20261015_v1"
OUT = ROOT / "run_log" / "research_sessions" / SESSION / "validation"
INITIAL_CASH = 100_000.0

REF_MEAN_IC = 0.02399168729832182
REF_FUNDING_YIELD = 0.45797758483123224


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def recompute_ic() -> dict:
    panel = pl.read_parquet(OUT / "factor_panel_with_labels.parquet")
    pred = panel.select(
        pl.col("decision_ts").alias("date"), "symbol", "prediction"
    )
    ret = panel.select(
        pl.col("decision_ts").alias("date"),
        "symbol",
        pl.col("forward_return_48h").alias("forward_return"),
    )
    series = cross_sectional_ic_series(
        pred,
        ret,
        pred_col="prediction",
        ret_col="forward_return",
        date_col="date",
        entity_col="symbol",
        method="spearman",
        min_obs=10,
    ).filter(pl.col("ic").is_not_null()).sort("date")
    stats = compute_ic_hac_stats(series, ic_col="ic", maxlags=1, label_horizon=1)
    return {
        "mean_ic": float(stats["mean_ic"]),
        "hac_t_stat": float(stats["t_stat"]),
        "cycles": series.height,
        "positive_share": float((series["ic"] > 0).mean()),
    }


def recompute_arm(name: str, funding_applied: bool) -> dict:
    path = OUT / name
    metrics = load_json(path / "metrics.json")
    fills = pl.read_csv(path / "fills.csv", try_parse_dates=True)
    equity = pl.read_parquet(path / "hourly_equity.parquet")
    state = pl.read_parquet(path / "portfolio_state.parquet")
    funding = pl.read_parquet(path / "funding_ledger.parquet")

    final_equity = float(equity["equity"][-1])
    total_return = final_equity / INITIAL_CASH - 1.0
    commission = float(fills["commission"].sum())
    slippage = float((fills["slippage"].abs() * fills["quantity"].abs()).sum())
    funding_total = float(funding["cashflow"].sum()) if funding.height else 0.0

    elapsed_years = (
        (state["timestamp"].max() - state["timestamp"].min()).total_seconds()
        / (365.25 * 24 * 3600)
    )
    avg_gross = float(state["gross_exposure"].mean())
    funding_yield = (
        funding_total / avg_gross / elapsed_years
        if funding_applied and avg_gross > 0 and elapsed_years > 0
        else 0.0
    )

    daily = (
        equity.with_columns(pl.col("timestamp").dt.date().alias("date"))
        .group_by("date")
        .agg(pl.col("equity").last().alias("equity"))
        .sort("date")
        .with_columns(pl.col("equity").pct_change().fill_null(0.0).alias("ret"))
    )
    returns = daily["ret"].to_numpy()[1:]
    std = float(returns.std(ddof=1))
    sharpe = float(returns.mean()) / std * math.sqrt(365.25) if std > 0 else None
    values = daily["equity"].to_numpy()
    max_dd = float((values / np.maximum.accumulate(values) - 1).min())

    checks = {
        "final_equity": math.isclose(
            final_equity, float(metrics["final_equity_usdt"]), abs_tol=1e-7
        ),
        "return": math.isclose(
            total_return, float(metrics["total_return"]), abs_tol=1e-12
        ),
        "commission": math.isclose(
            commission,
            float(metrics["cost_ledger"]["commission_usdt"]),
            abs_tol=1e-6,
        ),
        "slippage": math.isclose(
            slippage,
            float(metrics["cost_ledger"]["slippage_usdt"]),
            abs_tol=1e-6,
        ),
        "funding": math.isclose(
            funding_total, float(metrics["funding_cashflow_usdt"]), abs_tol=1e-7
        ),
        "funding_yield": math.isclose(
            funding_yield,
            float(metrics["annualized_funding_yield_on_avg_gross"]),
            rel_tol=1e-10,
            abs_tol=1e-10,
        ),
        "sharpe": (
            sharpe is None and metrics["risk"]["daily_sharpe"] is None
        ) or math.isclose(
            float(sharpe),
            float(metrics["risk"]["daily_sharpe"]),
            rel_tol=1e-10,
            abs_tol=1e-10,
        ),
        "max_dd": math.isclose(
            max_dd,
            float(metrics["risk"]["max_drawdown"]),
            rel_tol=1e-10,
            abs_tol=1e-10,
        ),
        "protected_2026": equity["timestamp"].max().year <= 2025,
    }
    if not all(checks.values()):
        raise AssertionError(f"{name}: verification failure {checks}")
    return {
        "total_return": total_return,
        "funding_usdt": funding_total,
        "funding_yield": funding_yield,
        "daily_sharpe": sharpe,
        "max_drawdown": max_dd,
        "checks": checks,
    }


def main() -> None:
    terminal = load_json(OUT / "terminal_decision.json")
    ic = recompute_ic()
    base = recompute_arm("validation_native_base_cost", True)
    stress = recompute_arm("validation_native_double_cost", True)
    nofund = recompute_arm("validation_native_no_funding", False)

    reasons = []
    if base["total_return"] <= 0:
        reasons.append("base-cost validation return is not positive")
    if stress["total_return"] <= 0:
        reasons.append("2x-cost validation return is not positive")
    if base["funding_yield"] <= 0:
        reasons.append("normalized realized funding yield is not positive")
    expected_terminal = "REJECT" if reasons else "VALIDATE"

    ic_ratio = ic["mean_ic"] / REF_MEAN_IC
    funding_ratio = base["funding_yield"] / REF_FUNDING_YIELD
    if expected_terminal == "REJECT":
        expected_decay = "STRUCTURAL_DECAY"
    elif ic["mean_ic"] <= 0:
        expected_decay = "MECHANISM_SHIFT_CARRY"
    elif ic_ratio >= 0.5 and funding_ratio >= 0.5:
        expected_decay = "NO_MATERIAL_DECAY"
    else:
        expected_decay = "PARTIAL_DECAY"

    if terminal["decision"] != expected_terminal:
        raise AssertionError(
            f"terminal mismatch {terminal['decision']} != {expected_terminal}"
        )
    if terminal["decay_classification"] != expected_decay:
        raise AssertionError(
            "decay mismatch "
            f"{terminal['decay_classification']} != {expected_decay}"
        )
    if not math.isclose(
        ic["mean_ic"], float(terminal["ic"]["mean_ic"]), abs_tol=1e-12
    ):
        raise AssertionError("IC mismatch against terminal artifact")

    result = {
        "verified_terminal_decision": expected_terminal,
        "verified_decay_classification": expected_decay,
        "ic": ic,
        "base": base,
        "double_cost": stress,
        "no_funding": nofund,
        "ic_ratio_to_reference": ic_ratio,
        "funding_yield_ratio_to_reference": funding_ratio,
        "reasons": reasons,
    }
    (OUT / "independent_verification.json").write_text(
        json.dumps(result, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
