"""Independent verifier for final 2024-2025 funding decay validation."""
from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import polars as pl
from ml4t.diagnostic.api import compute_ic_hac_stats, cross_sectional_ic_series

ROOT = Path(__file__).resolve().parents[1]
SESSION = "crypto_xs_plain_funding_decay_validation_20261015_v1"
SESSION_DIR = ROOT / "run_log" / "research_sessions" / SESSION
VALID = SESSION_DIR / "validation"
FORENSICS = SESSION_DIR / "decay_forensics"
FINAL = SESSION_DIR / "validation_final"

REF_IC = 0.02399168729832182
REF_FUNDING_SPREAD = 0.0027302096098901084
REF_FUNDING_YIELD = 0.45797758483123224


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def recompute_ic() -> dict:
    panel = pl.read_parquet(VALID / "factor_panel_with_labels.parquet")
    pred = panel.select(
        pl.col("decision_ts").alias("date"), "symbol", "prediction"
    )
    ret = panel.select(
        pl.col("decision_ts").alias("date"),
        "symbol",
        pl.col("forward_return_48h").alias("forward_return"),
    )
    series = (
        cross_sectional_ic_series(
            pred,
            ret,
            pred_col="prediction",
            ret_col="forward_return",
            date_col="date",
            entity_col="symbol",
            method="spearman",
            min_obs=10,
        )
        .filter(pl.col("ic").is_not_null())
        .sort("date")
    )
    stats = compute_ic_hac_stats(series, ic_col="ic", maxlags=1, label_horizon=1)
    annual = (
        series.with_columns(pl.col("date").dt.year().alias("year"))
        .group_by("year")
        .agg(pl.len().alias("cycles"), pl.col("ic").mean().alias("mean_ic"))
        .sort("year")
    )
    return {
        "mean_ic": float(stats["mean_ic"]),
        "hac_t_stat": float(stats["t_stat"]),
        "cycles": series.height,
        "annual": annual.to_dicts(),
        "ic_ratio": float(stats["mean_ic"]) / REF_IC,
        "max_label_exit": str(panel["exit_ts"].max()),
    }


def recompute_opportunity() -> dict:
    signal = pl.read_parquet(
        ROOT / "data" / "processed" / SESSION / "signal_panel_preoutcome.parquet"
    )
    cycle = (
        signal.group_by("decision_ts")
        .agg(
            (
                pl.col("cum_funding_24h").top_k(5).mean()
                - pl.col("cum_funding_24h").bottom_k(5).mean()
            ).alias("spread")
        )
        .sort("decision_ts")
    )
    spread = float(cycle["spread"].mean())
    annual = (
        cycle.with_columns(pl.col("decision_ts").dt.year().alias("year"))
        .group_by("year")
        .agg(pl.col("spread").mean().alias("spread"))
        .sort("year")
    )
    return {
        "mean_spread": spread,
        "ratio": spread / REF_FUNDING_SPREAD,
        "annual": annual.to_dicts(),
    }


def insolvency(path: Path) -> dict:
    state = pl.read_parquet(path).sort("timestamp")
    bad = state.filter(pl.col("equity") <= 0)
    return {
        "first_nonpositive": bad.row(0, named=True) if bad.height else None,
        "min_equity": float(state["equity"].min()),
        "final_equity": float(state["equity"][-1]),
        "final_open_positions": int(state["open_positions"][-1]),
        "max_timestamp": str(state["timestamp"].max()),
    }


def main() -> None:
    terminal = load_json(FINAL / "terminal_decision.json")
    ic = recompute_ic()
    opportunity = recompute_opportunity()

    base = insolvency(FORENSICS / "corrected_native_base_portfolio_state.parquet")
    double = insolvency(
        FORENSICS / "corrected_native_double_cost_portfolio_state.parquet"
    )
    nofund = insolvency(
        VALID / "validation_native_no_funding" / "portfolio_state.parquet"
    )

    base_ledger = pl.read_parquet(
        FORENSICS / "corrected_native_base_funding_ledger.parquet"
    ).sort("timestamp")
    first_base = base["first_nonpositive"]["timestamp"]
    if first_base.tzinfo is None:
        first_base_aware = first_base.replace(tzinfo=UTC)
    else:
        first_base_aware = first_base.astimezone(UTC)
    funding_before = float(
        base_ledger.filter(pl.col("timestamp") <= first_base_aware)[
            "cashflow"
        ].sum()
    )
    funding_after = float(
        base_ledger.filter(pl.col("timestamp") > first_base_aware)[
            "cashflow"
        ].sum()
    )

    state = pl.read_parquet(
        FORENSICS / "corrected_native_base_portfolio_state.parquet"
    ).sort("timestamp")
    state_cut = state.filter(
        pl.col("timestamp") <= first_base_aware.replace(tzinfo=None)
    )
    years = (
        (state_cut["timestamp"].max() - state_cut["timestamp"].min()).total_seconds()
        / (365.25 * 24 * 3600)
    )
    avg_gross = float(state_cut["gross_exposure"].mean())
    funding_yield = funding_before / avg_gross / years

    carry_cycles = pl.read_csv(
        FORENSICS / "funding_cycle_forensics.csv", try_parse_dates=True
    )
    carry_group = (
        carry_cycles.group_by("period")
        .agg(
            pl.col("funding_persistence_rank_ic").mean().alias("persistence"),
            pl.col("realized_portfolio_carry_48h").mean().alias("realized_carry"),
        )
    )
    carry_lookup = {
        row["period"]: row for row in carry_group.iter_rows(named=True)
    }
    ref = carry_lookup["2022_2023_reference"]
    val = carry_lookup["2024_2025_validation"]
    carry_ratio = float(val["realized_carry"] / ref["realized_carry"])
    persistence_ratio = float(val["persistence"] / ref["persistence"])

    mismatch = pl.read_parquet(
        FORENSICS / "native_funding_side_mismatches.parquet"
    )
    first_mismatch = mismatch["timestamp"].min()

    nofund_metrics = load_json(
        VALID / "validation_native_no_funding" / "metrics.json"
    )

    checks = {
        "terminal_reject": terminal["decision"] == "REJECT",
        "terminal_structural_decay": (
            terminal["decay_classification"] == "STRUCTURAL_DECAY"
        ),
        "ic_matches": math.isclose(
            ic["mean_ic"], terminal["ic"]["mean_ic"], abs_tol=1e-12
        ),
        "spread_matches": math.isclose(
            opportunity["mean_spread"],
            terminal["opportunity"]["mean_top5_minus_bottom5_funding_24h"],
            abs_tol=1e-15,
        ),
        "base_insolvent": base["first_nonpositive"] is not None,
        "double_insolvent": double["first_nonpositive"] is not None,
        "nofund_insolvent": nofund["first_nonpositive"] is not None,
        "same_base_nofund_failure_timestamp": (
            base["first_nonpositive"]["timestamp"]
            == nofund["first_nonpositive"]["timestamp"]
        ),
        "funding_positive_before_insolvency": funding_before > 0,
        "funding_negative_after_insolvency": funding_after < 0,
        "side_mismatch_after_insolvency": first_mismatch > first_base_aware,
        "carry_ratio_above_one": carry_ratio > 1,
        "persistence_not_decayed": persistence_ratio > 0.9,
        "price_only_loss_matches": math.isclose(
            float(nofund_metrics["total_return"]),
            -0.950490466376398,
            abs_tol=1e-12,
        ),
        "2026_sealed_labels": "2025-" in ic["max_label_exit"],
        "2026_sealed_base": "2025-" in base["max_timestamp"],
        "2026_sealed_double": "2025-" in double["max_timestamp"],
    }
    if not all(checks.values()):
        raise AssertionError(f"final validation verification failed: {checks}")

    result = {
        "verified_decision": "REJECT",
        "verified_decay_classification": "STRUCTURAL_DECAY",
        "verified_mechanism_diagnosis": (
            "FUNDING_CARRY_ALIVE__PRICE_ALPHA_DECAYED__SINGLE_NAME_SHORT_SQUEEZE_FATAL"
        ),
        "ic": ic,
        "opportunity": opportunity,
        "base": base,
        "double_cost": double,
        "no_funding": nofund,
        "funding_before_insolvency_usdt": funding_before,
        "funding_after_insolvency_usdt": funding_after,
        "pre_insolvency_annualized_funding_yield": funding_yield,
        "pre_insolvency_funding_yield_ratio_to_reference": (
            funding_yield / REF_FUNDING_YIELD
        ),
        "unit_notional_realized_carry_ratio": carry_ratio,
        "funding_persistence_ratio": persistence_ratio,
        "first_side_mismatch": str(first_mismatch),
        "checks": checks,
    }
    (FINAL / "independent_verification.json").write_text(
        json.dumps(result, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "verified_decision": result["verified_decision"],
        "verified_decay_classification": result["verified_decay_classification"],
        "mean_ic": ic["mean_ic"],
        "ic_2024": ic["annual"][0]["mean_ic"],
        "ic_2025": ic["annual"][1]["mean_ic"],
        "funding_spread_ratio": opportunity["ratio"],
        "carry_ratio": carry_ratio,
        "funding_persistence_ratio": persistence_ratio,
        "pre_insolvency_funding_yield": funding_yield,
        "base_first_insolvency": str(base["first_nonpositive"]["timestamp"]),
        "checks_all_pass": all(checks.values()),
    }, indent=2))


if __name__ == "__main__":
    main()
