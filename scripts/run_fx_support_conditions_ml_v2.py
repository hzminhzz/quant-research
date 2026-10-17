"""Versioned, fail-closed recovery of the preregistered ML support-retest arm.

Preserves the original failed attempt. The sole changed input treatment removes
one non-finite ATR/EMA warm-up row from the development feature matrix.
No holdout files or new ML hyperparameters are used.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from scripts.run_fx_support_conditions_trial import (
    FEATURES,
    SOURCE,
    evaluate_arm,
    load_panel,
    run_ml,
)

ROOT = Path(__file__).resolve().parents[1]
SESSION = "fx_support_conditions_20261008_ml_v2"
TRIAL = "I4_purged_lightgbm_v2"
OUT = ROOT / "run_log" / SESSION / TRIAL
EXPECTED_ISSUE_TIMESTAMP = "2010-01-05 18:30:00+00:00"


def drop_nonfinite_warmup(data: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    bad = pl.any_horizontal([~pl.col(c).is_finite() for c in FEATURES])
    excluded = data.filter(bad)
    retained = data.filter(~bad)
    if excluded.height != 1 or retained.height != 1394:
        raise RuntimeError(
            f"Unapproved data exclusion: excluded={excluded.height}, retained={retained.height}"
        )
    first = excluded.row(0, named=True)
    if first["symbol"] != "AUDUSD" or str(first["event_timestamp"]) != EXPECTED_ISSUE_TIMESTAMP:
        raise RuntimeError("Non-finite event identity changed; stop")
    if retained["event_timestamp"].max().year >= 2025:
        raise RuntimeError("Holdout event found")
    if retained.filter(pl.any_horizontal([~pl.col(c).is_finite() for c in FEATURES])).height:
        raise RuntimeError("Non-finite inputs remain")
    return retained, excluded


def run() -> dict[str, object]:
    frozen = ROOT / "run_log/research_sessions" / SESSION / "frozen_spec.json"
    if not frozen.is_file():
        raise RuntimeError("Initialize frozen successor before running the ML trial")
    if OUT.exists():
        raise RuntimeError("Immutable trial output already exists; refusing overwrite")

    parent = load_panel()
    cleaned, excluded = drop_nonfinite_warmup(parent)
    scored, model_report = run_ml(cleaned)
    report = evaluate_arm(scored, TRIAL, ml=model_report)
    report.update({
        "session_id": SESSION,
        "trial_id": TRIAL,
        "source_trial": "fx_support_conditions_20261008/I4_purged_lightgbm",
        "recovery_kind": "non-finite warmup exclusion only",
        "raw_panel_events": parent.height,
        "cleaned_panel_events": cleaned.height,
        "excluded_rows": [
            {
                "symbol": "AUDUSD",
                "event_timestamp": EXPECTED_ISSUE_TIMESTAMP,
                "reason": "Non-finite ATR100 warm-up ratio and EMA50 slope",
            }
        ],
        "holdout_opened": False,
        "holdout_scored": False,
    })
    OUT.mkdir(parents=True, exist_ok=False)
    scored_path = OUT / "scored_events.parquet"
    scored.write_parquet(scored_path, compression="zstd")
    report["event_ledger"] = scored_path.relative_to(ROOT).as_posix()
    report["score_source"] = SOURCE.relative_to(ROOT).as_posix()
    result_path = OUT / "result.json"
    result_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "session_id": SESSION,
        "trial": TRIAL,
        "disposition": report["selection_disposition"],
        "sample_base": report["sample_base"],
        "selected": report["selected"],
        "selected_lift_pp": report["selected_lift_vs_same_window_baseline_pp"],
        "preregistered_checks": report["preregistered_checks"],
        "model": report["model"],
        "result_path": result_path.relative_to(ROOT).as_posix(),
    }, indent=2, sort_keys=True, allow_nan=False))
    return report


if __name__ == "__main__":
    run()
