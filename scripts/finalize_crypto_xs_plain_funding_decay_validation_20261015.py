"""Finalize the 2024-2025 plain-funding decay validation.

This finalizer uses only already-opened 2024-2025 evidence. It preserves the
invalid zero-funding attempt separately, treats corrected native insolvency as
an economic failure rather than an execution ambiguity, and applies the frozen
terminal taxonomy without changing any signal or threshold.
"""
from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
SESSION = "crypto_xs_plain_funding_decay_validation_20261015_v1"
SESSION_DIR = ROOT / "run_log" / "research_sessions" / SESSION
INVALID_OUT = SESSION_DIR / "validation"
FORENSICS = SESSION_DIR / "decay_forensics"
FINAL = SESSION_DIR / "validation_final"

REF_IC = 0.02399168729832182
REF_FUNDING_YIELD = 0.45797758483123224


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def corrected_arm(state_path: Path, ledger_path: Path) -> dict:
    state = pl.read_parquet(state_path).sort("timestamp")
    ledger = pl.read_parquet(ledger_path).sort("timestamp")
    nonpositive = state.filter(pl.col("equity") <= 0)
    first = nonpositive.row(0, named=True) if nonpositive.height else None
    return {
        "first_nonpositive_equity": first,
        "min_equity": float(state["equity"].min()),
        "final_equity": float(state["equity"][-1]),
        "final_cash": float(state["cash"][-1]),
        "final_open_positions": int(state["open_positions"][-1]),
        "funding_events": ledger.height,
        "funding_cashflow_usdt": float(ledger["cashflow"].sum()),
        "terminal_insolvency": bool(nonpositive.height),
        "last_state_timestamp": str(state["timestamp"][-1]),
    }


def main() -> None:
    if (FINAL / "terminal_decision.json").exists():
        raise FileExistsError("validation final evidence already exists")

    ic = load_json(INVALID_OUT / "ic_diagnostics.json")
    opportunity = load_json(INVALID_OUT / "funding_opportunity_decay.json")
    nofund = load_json(INVALID_OUT / "validation_native_no_funding" / "metrics.json")
    carry = load_json(FORENSICS / "funding_persistence_summary.json")
    path_audit = load_json(FORENSICS / "native_funding_path_audit.json")
    double = load_json(FORENSICS / "corrected_native_double_cost_diagnostic.json")

    base = corrected_arm(
        FORENSICS / "corrected_native_base_portfolio_state.parquet",
        FORENSICS / "corrected_native_base_funding_ledger.parquet",
    )
    first_ts = base["first_nonpositive_equity"]["timestamp"]
    if isinstance(first_ts, str):
        first_ts_dt = datetime.fromisoformat(first_ts)
    else:
        first_ts_dt = first_ts
    if first_ts_dt.tzinfo is None:
        first_ts_aware = first_ts_dt.replace(tzinfo=UTC)
    else:
        first_ts_aware = first_ts_dt.astimezone(UTC)

    state = pl.read_parquet(
        FORENSICS / "corrected_native_base_portfolio_state.parquet"
    ).sort("timestamp")
    ledger = pl.read_parquet(
        FORENSICS / "corrected_native_base_funding_ledger.parquet"
    ).sort("timestamp")
    state_cut = state.filter(
        pl.col("timestamp")
        <= first_ts_aware.replace(tzinfo=None)
    )
    ledger_cut = ledger.filter(pl.col("timestamp") <= first_ts_aware)
    elapsed_years = (
        (state_cut["timestamp"].max() - state_cut["timestamp"].min()).total_seconds()
        / (365.25 * 24 * 3600)
    )
    avg_gross = float(state_cut["gross_exposure"].mean())
    funding_before = float(ledger_cut["cashflow"].sum())
    pre_insolvency_yield = funding_before / avg_gross / elapsed_years

    mismatch = pl.read_parquet(
        FORENSICS / "native_funding_side_mismatches.parquet"
    ).sort("timestamp")
    first_mismatch = mismatch["timestamp"].min() if mismatch.height else None

    myx = ledger.filter(pl.col("symbol") == "MYXUSDT")
    myx_after = float(
        myx.filter(pl.col("timestamp") > first_ts_aware)["cashflow"].sum()
    )
    all_after = float(
        ledger.filter(pl.col("timestamp") > first_ts_aware)["cashflow"].sum()
    )
    rate_validation = carry["validation_2024_2025"]
    rate_reference = carry["reference_2022_2023"]

    # Frozen terminal taxonomy: unchanged portfolio fails economically because
    # both base and 2x-cost accounts become insolvent.
    decision = "REJECT"
    decay = "STRUCTURAL_DECAY"
    reasons = [
        "Corrected base-cost native portfolio becomes insolvent on 2025-09-08 19:00 UTC.",
        "Corrected 2x-cost native portfolio also becomes insolvent on 2025-09-08 19:00 UTC.",
        "No-funding arm also crosses negative equity on the same timestamp, confirming the fatal event is primarily price/tail risk rather than funding accounting.",
    ]

    result = {
        "decision": decision,
        "decay_classification": decay,
        "mechanism_diagnosis": (
            "FUNDING_CARRY_ALIVE__PRICE_ALPHA_DECAYED__SINGLE_NAME_SHORT_SQUEEZE_FATAL"
        ),
        "stage": "2024_2025_DECAY_VALIDATION_FINAL",
        "classification": "VALIDATION",
        "approval_status": "NOT_APPROVED",
        "protected_2026_plus_accessed": False,
        "reasons": reasons,
        "ic": ic,
        "opportunity": opportunity,
        "base_corrected": base,
        "double_cost_corrected": double,
        "no_funding": nofund,
        "carry_forensics": carry,
        "native_path_audit": path_audit,
        "pre_insolvency_native_funding": {
            "funding_cashflow_usdt": funding_before,
            "average_gross_exposure_usdt": avg_gross,
            "elapsed_years": elapsed_years,
            "annualized_funding_yield_on_average_gross": pre_insolvency_yield,
            "ratio_to_2022_2023_reference": (
                pre_insolvency_yield / REF_FUNDING_YIELD
            ),
        },
        "decay_ratios": {
            "price_rank_ic_ratio_to_2022_2023": ic["mean_ic"] / REF_IC,
            "funding_opportunity_spread_ratio_to_2022_2023": opportunity[
                "funding_spread_ratio_to_2022_2023"
            ],
            "funding_persistence_ratio_to_2022_2023": carry["ratios"][
                "funding_persistence_ratio"
            ],
            "unit_notional_realized_carry_ratio_to_2022_2023": carry["ratios"][
                "realized_carry_ratio"
            ],
            "pre_insolvency_native_funding_yield_ratio_to_2022_2023": (
                pre_insolvency_yield / REF_FUNDING_YIELD
            ),
        },
        "causal_path": {
            "first_nonpositive_equity_timestamp": str(first_ts_aware),
            "first_side_mismatch_timestamp": (
                str(first_mismatch) if first_mismatch is not None else None
            ),
            "side_mismatches_begin_after_insolvency": (
                first_mismatch is not None and first_mismatch > first_ts_aware
            ),
            "funding_before_insolvency_usdt": funding_before,
            "funding_after_insolvency_usdt": all_after,
            "myx_funding_after_insolvency_usdt": myx_after,
            "myx_total_funding_usdt": float(myx["cashflow"].sum()),
            "myx_side_match_share": next(
                (
                    row["side_match_share"]
                    for row in path_audit["worst_funding_symbols"]
                    if row["symbol"] == "MYXUSDT"
                ),
                None,
            ),
        },
        "invalid_attempt": {
            "path": str(INVALID_OUT.relative_to(ROOT)),
            "reason": (
                "Imported legacy funding-event helper filtered 2024-2025 events "
                "using the old 2020-2023 development window, so funding-aware "
                "portfolio results from that attempt are invalid. IC, funding-"
                "opportunity diagnostics, and the no-funding arm remain valid."
            ),
        },
        "execution_fix_amendment": str(
            (SESSION_DIR / "execution_fix1_amendment.json").relative_to(ROOT)
        ),
        "interpretation": {
            "funding_compression_hypothesis_supported": False,
            "price_predictive_decay_supported": True,
            "portfolio_survivability_supported": False,
            "notes": [
                "2025 mean 48h rank IC is approximately zero while funding spreads are larger than the mature 2022-2023 reference.",
                "Rate-space forward funding carry remains strongly positive and persistent.",
                "The unchanged equal-notional portfolio is bankrupted by a MYXUSDT short squeeze before the signal can flip the position.",
                "Post-insolvency stale-side funding losses are a consequence of negative account value preventing native target-weight rebalancing.",
            ],
        },
    }
    write_json(FINAL / "terminal_decision.json", result)
    print(json.dumps({
        "decision": decision,
        "decay_classification": decay,
        "mechanism_diagnosis": result["mechanism_diagnosis"],
        "mean_ic": ic["mean_ic"],
        "ic_2024": ic["annual"][0]["mean_ic"],
        "ic_2025": ic["annual"][1]["mean_ic"],
        "funding_spread_ratio": result["decay_ratios"][
            "funding_opportunity_spread_ratio_to_2022_2023"
        ],
        "unit_notional_carry_ratio": result["decay_ratios"][
            "unit_notional_realized_carry_ratio_to_2022_2023"
        ],
        "pre_insolvency_native_funding_yield": pre_insolvency_yield,
        "pre_insolvency_funding_yield_ratio": result["decay_ratios"][
            "pre_insolvency_native_funding_yield_ratio_to_2022_2023"
        ],
        "base_first_insolvency": str(first_ts_aware),
        "double_first_insolvency": str(double["first_nonpositive_equity"]["timestamp"]),
        "funding_before_insolvency": funding_before,
        "funding_after_insolvency": all_after,
        "myx_after_insolvency": myx_after,
    }, indent=2))


if __name__ == "__main__":
    main()
