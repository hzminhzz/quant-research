"""Finalize a completed Phase 4 run after a post-arm dtype-only failure.

The frozen native runner completed all three portfolio arms, then failed while
joining funding-ledger timestamps (us precision) to frozen mark evidence
(ms precision) for the preregistered sensitivity calculation. This recovery
does not rerun or alter any native arm. It casts both join keys to canonical
millisecond UTC precision, computes the already-frozen sensitivity formula,
and applies the already-frozen gate function from the original runner.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_crypto_xs_plain_funding_phase4_20261015 import gate

SESSION = "crypto_xs_plain_funding_phase4_20261015_v1"
OUT = ROOT / "run_log" / "research_sessions" / SESSION / "phase4"
MARK_EVENTS = (
    ROOT / "data" / "processed" / SESSION
    / "required_funding_events_with_marks.parquet"
)


def sha256(path: Path) -> str:
    with path.open("rb") as fp:
        return hashlib.file_digest(fp, "sha256").hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def compute_sensitivity() -> dict:
    ledger_path = OUT / "native_funding_base_cost" / "funding_ledger.parquet"
    if not ledger_path.exists() or not MARK_EVENTS.exists():
        raise FileNotFoundError("completed base ledger or frozen mark evidence missing")
    ledger = pl.read_parquet(ledger_path).with_columns(
        pl.col("timestamp").cast(pl.Datetime("ms", "UTC"))
    )
    marks = pl.read_parquet(MARK_EVENTS).with_columns(
        pl.col("timestamp").cast(pl.Datetime("ms", "UTC"))
    )
    sensitivity = (
        ledger.select(
            "timestamp", "symbol", "quantity", "funding_rate", "cashflow"
        )
        .rename({"cashflow": "primary_cashflow"})
        .join(
            marks.select("timestamp", "symbol", "prior_mark_close"),
            on=["timestamp", "symbol"],
            how="left",
        )
        .with_columns(
            (
                -pl.col("quantity")
                * pl.col("prior_mark_close")
                * pl.col("funding_rate")
            ).alias("prior_close_cashflow")
        )
    )
    if sensitivity.height != ledger.height:
        raise AssertionError(
            f"sensitivity row count {sensitivity.height} != ledger {ledger.height}"
        )
    if sensitivity["prior_mark_close"].null_count():
        raise AssertionError("missing frozen prior-minute mark in sensitivity")
    primary = float(sensitivity["primary_cashflow"].sum())
    prior = float(sensitivity["prior_close_cashflow"].sum())
    same_sign = (primary > 0 and prior > 0) or (primary < 0 and prior < 0)
    sensitivity.write_parquet(OUT / "funding_mark_sensitivity.parquet")
    result = {
        "primary_event_minute_open_funding_usdt": primary,
        "prior_minute_close_funding_usdt": prior,
        "difference_usdt": prior - primary,
        "relative_difference": prior / primary - 1.0 if primary != 0 else None,
        "same_sign": same_sign,
        "events": sensitivity.height,
    }
    write_json(OUT / "funding_mark_sensitivity.json", result)
    return result


def main() -> None:
    terminal_path = OUT / "terminal_decision.json"
    if terminal_path.exists():
        raise FileExistsError("terminal Phase 4 evidence already exists")

    base_path = OUT / "native_funding_base_cost" / "metrics.json"
    stress_path = OUT / "native_funding_double_cost" / "metrics.json"
    nofund_path = OUT / "native_no_funding_decomposition" / "metrics.json"
    for path in (base_path, stress_path, nofund_path):
        if not path.exists():
            raise FileNotFoundError(f"native arm did not complete: {path}")

    base = load_json(base_path)
    stress = load_json(stress_path)
    nofund = load_json(nofund_path)
    sensitivity = compute_sensitivity()
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
        "finalization": {
            "method": "post-arm mechanical recovery",
            "native_arms_rerun": False,
            "original_runner_modified_after_freeze": False,
            "recovery_reason": (
                "Original frozen runner completed all native arms then failed "
                "because funding-ledger timestamps were datetime[us,UTC] while "
                "frozen mark evidence was datetime[ms,UTC]. Recovery casts both "
                "join keys to datetime[ms,UTC] and applies the original frozen gate."
            ),
        },
    }
    write_json(terminal_path, terminal)
    write_json(
        OUT / "recovery_metadata.json",
        {
            "session": SESSION,
            "original_runner": "scripts/run_crypto_xs_plain_funding_phase4_20261015.py",
            "original_runner_sha256": sha256(
                ROOT / "scripts" / "run_crypto_xs_plain_funding_phase4_20261015.py"
            ),
            "native_arm_artifacts_preserved": True,
            "native_arms_rerun": False,
            "timestamp_cast": "datetime[us,UTC] -> datetime[ms,UTC]",
            "terminal_decision": decision,
        },
    )
    print(json.dumps({
        "decision": decision,
        "reasons": reasons,
        "primary_funding": sensitivity[
            "primary_event_minute_open_funding_usdt"
        ],
        "prior_close_funding": sensitivity[
            "prior_minute_close_funding_usdt"
        ],
        "same_sign": sensitivity["same_sign"],
    }, indent=2))


if __name__ == "__main__":
    main()
