"""Independent verifier for crypto_xs_plain_funding_phase4_20261015_v1.

Reads saved Phase 4 artifacts only. It does not rerun the strategy or alter research
inputs. The verifier recomputes accounting summaries and terminal gate semantics.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
SESSION = "crypto_xs_plain_funding_phase4_20261015_v1"
OUT = ROOT / "run_log" / "research_sessions" / SESSION / "phase4"
INITIAL_CASH = 100_000.0
SHARPE_MIN = 0.50
MAX_DD_FLOOR = -0.35


def daily_stats(equity: pl.DataFrame) -> dict[str, float | None]:
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
    max_dd = float((values / np.maximum.accumulate(values) - 1.0).min())
    return {"daily_sharpe": sharpe, "max_drawdown": max_dd}


def verify_arm(name: str) -> dict:
    path = OUT / name
    saved = json.loads((path / "metrics.json").read_text())
    fills = pl.read_csv(path / "fills.csv", try_parse_dates=True)
    equity = pl.read_parquet(path / "hourly_equity.parquet")
    funding = pl.read_parquet(path / "funding_ledger.parquet")

    final_equity = float(equity["equity"][-1])
    total_return = final_equity / INITIAL_CASH - 1.0
    commission = float(fills["commission"].sum()) if fills.height else 0.0
    slippage = (
        float((fills["slippage"].abs() * fills["quantity"].abs()).sum())
        if fills.height else 0.0
    )
    funding_total = float(funding["cashflow"].sum()) if funding.height else 0.0
    risk = daily_stats(equity)

    checks = {
        "final_equity_matches": math.isclose(
            final_equity, float(saved["final_equity_usdt"]), abs_tol=1e-7
        ),
        "return_matches": math.isclose(
            total_return, float(saved["total_return"]), abs_tol=1e-12
        ),
        "commission_matches": math.isclose(
            commission, float(saved["cost_ledger"]["commission"]), abs_tol=1e-6
        ),
        "slippage_matches": math.isclose(
            slippage, float(saved["cost_ledger"]["slippage"]), abs_tol=1e-6
        ),
        "funding_matches": math.isclose(
            funding_total, float(saved["funding_cashflow_usdt"]), abs_tol=1e-7
        ),
        "sharpe_matches": (
            risk["daily_sharpe"] is None and saved["daily_risk"]["daily_sharpe"] is None
        ) or math.isclose(
            float(risk["daily_sharpe"]),
            float(saved["daily_risk"]["daily_sharpe"]),
            rel_tol=1e-10,
            abs_tol=1e-10,
        ),
        "max_dd_matches": math.isclose(
            float(risk["max_drawdown"]),
            float(saved["daily_risk"]["max_drawdown"]),
            rel_tol=1e-10,
            abs_tol=1e-10,
        ),
        "protected_boundary_respected": equity["timestamp"].max().year <= 2023,
    }
    if not all(checks.values()):
        raise AssertionError(f"{name}: independent verification failed: {checks}")
    return {
        "final_equity": final_equity,
        "total_return": total_return,
        "commission": commission,
        "slippage": slippage,
        "funding": funding_total,
        "risk": risk,
        "checks": checks,
    }


def main() -> None:
    terminal = json.loads((OUT / "terminal_decision.json").read_text())
    base = verify_arm("native_funding_base_cost")
    stress = verify_arm("native_funding_double_cost")
    nofund = verify_arm("native_no_funding_decomposition")

    sensitivity = json.loads((OUT / "funding_mark_sensitivity.json").read_text())
    reasons = []
    if base["total_return"] <= 0:
        reasons.append("base-cost net total return is not positive")
    if base["risk"]["daily_sharpe"] is None or base["risk"]["daily_sharpe"] < SHARPE_MIN:
        reasons.append("base-cost daily Sharpe below frozen threshold")
    if base["risk"]["max_drawdown"] < MAX_DD_FLOOR:
        reasons.append("base-cost max drawdown breaches frozen threshold")
    if base["funding"] <= 0:
        reasons.append("realized funding cashflow is not positive")
    if stress["total_return"] <= 0:
        reasons.append("2x execution-cost portfolio is not net profitable")

    expected = (
        "INCONCLUSIVE"
        if not sensitivity["same_sign"]
        else "REJECT" if reasons else "VALIDATE"
    )
    if expected != terminal["decision"]:
        raise AssertionError(
            f"terminal decision mismatch saved={terminal['decision']} recomputed={expected}"
        )

    result = {
        "session": SESSION,
        "verified_decision": expected,
        "base": base,
        "double_cost": stress,
        "no_funding": nofund,
        "mark_sensitivity": sensitivity,
        "gate_reasons": reasons,
    }
    (OUT / "independent_verification.json").write_text(
        json.dumps(result, indent=2, default=str) + "\n"
    )
    print(json.dumps({
        "verified_decision": expected,
        "base_return": base["total_return"],
        "base_sharpe": base["risk"]["daily_sharpe"],
        "base_max_dd": base["risk"]["max_drawdown"],
        "base_funding": base["funding"],
        "double_cost_return": stress["total_return"],
        "no_funding_return": nofund["total_return"],
        "gate_reasons": reasons,
    }, indent=2))


if __name__ == "__main__":
    main()
