"""Recompute frozen FX support event features from development prices only."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import polars as pl
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_fx_support_conditions_panel import (
    FEATURE_NAMES,
    SYMBOLS,
    build_symbol,
)

SESSION = "fx_support_ml4t_execution_20261008"
PANEL = ROOT / "data/features/fx_support_conditions_20261008.parquet"
PANEL_MANIFEST = ROOT / "data/features/fx_support_conditions_20261008_manifest.json"
PARENT = ROOT / "run_log/fx_support_reclaim_newhigh_20261008/D0_support_hold_new_high/event_labels.parquet"
OOF = ROOT / "run_log/fx_support_conditions_20261008_ml_v2/I4_purged_lightgbm_v2/scored_events.parquet"
FROZEN = ROOT / "run_log/research_sessions/fx_support_ml4t_execution_20261008/frozen_spec.json"
OUTPUT = ROOT / f"run_log/{SESSION}/feature_integrity_v1.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> dict[str, object]:
    if OUTPUT.exists():
        raise RuntimeError(f"Refusing to overwrite immutable evidence: {OUTPUT}")

    parent = pl.read_parquet(PARENT)
    frozen_panel = pl.read_parquet(PANEL)
    manifest = json.loads(PANEL_MANIFEST.read_text(encoding="utf-8"))
    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))

    # build_symbol reads only the two explicit DEV snapshots per symbol and
    # invokes the installed public ml4t.engineer.compute_features API.
    regenerated = pl.concat(
        [build_symbol(symbol, parent) for symbol in SYMBOLS],
        how="vertical",
    ).sort(["event_timestamp", "symbol"])
    frozen_panel = frozen_panel.sort(["event_timestamp", "symbol"])

    identity_cols = [
        "symbol", "event_timestamp", "reference_high_timestamp",
        "reference_high", "origin_support",
    ]
    compare_cols = identity_cols + FEATURE_NAMES
    if regenerated.height != 1395 or frozen_panel.height != 1395:
        raise AssertionError("Frozen event panel row count changed")
    if regenerated.select(identity_cols).to_dicts() != frozen_panel.select(identity_cols).to_dicts():
        raise AssertionError("Event identity or frozen trade levels changed")

    comparisons: dict[str, dict[str, float | int]] = {}
    for name in FEATURE_NAMES:
        regenerated_values = regenerated[name].to_numpy()
        frozen_values = frozen_panel[name].to_numpy()
        both_finite = np.isfinite(regenerated_values) & np.isfinite(frozen_values)
        same_nan = np.isnan(regenerated_values) & np.isnan(frozen_values)
        if not np.all(both_finite | same_nan):
            raise AssertionError(f"Finite/non-finite feature status changed: {name}")
        finite_delta = np.abs(regenerated_values[both_finite] - frozen_values[both_finite])
        max_abs = float(finite_delta.max()) if finite_delta.size else 0.0
        mismatch_count = int((finite_delta > 1e-8).sum())
        comparisons[name] = {
            "compared": regenerated.height,
            "max_abs_error": max_abs,
            "nonfinite_equal_pairs": int(same_nan.sum()),
            "mismatch_gt_1e-8": mismatch_count,
        }
        if comparisons[name]["mismatch_gt_1e-8"]:
            raise AssertionError(f"Frozen feature mismatch: {name}")

    oof = pl.read_parquet(OOF)
    event_keys = ["symbol", "event_timestamp"]
    unmatched = oof.join(frozen_panel.select(event_keys), on=event_keys, how="anti")
    if oof.height != 730 or unmatched.height:
        raise AssertionError("OOF events do not map one-to-one to the frozen feature panel")
    if oof.filter(pl.col("event_timestamp").dt.year() >= 2025).height:
        raise AssertionError("OOF signal timestamp is outside development")
    decision_last = oof.select(
        (pl.col("event_timestamp") + pl.duration(minutes=30)).max()
    ).item()
    if decision_last.year >= 2025:
        raise AssertionError("OOF decision timestamp is outside development")
    if oof.filter(pl.col("selected")).height != 112:
        raise AssertionError("Frozen selected event count changed")

    input_paths = [
        ROOT / f"data/processed/ftmo_fx_reversion_202610/{symbol}_dev_{era}_5m.parquet"
        for symbol in SYMBOLS
        for era in ("2010_2017", "2018_2024")
    ]
    input_bounds = []
    for path in input_paths:
        # Explicit DEV names only. No holdout-named path is opened or hashed.
        if "holdout" in path.name.lower() or "dev_" not in path.name:
            raise AssertionError("Non-development path rejected")
        frame = pl.scan_parquet(path).select(
            pl.col("timestamp").min().alias("first"),
            pl.col("timestamp").max().alias("last"),
            pl.len().alias("rows"),
        ).collect()
        input_bounds.append({
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": sha256(path),
            "rows": frame["rows"][0],
            "first_timestamp": str(frame["first"][0]),
            "last_timestamp": str(frame["last"][0]),
        })
        if frame["last"][0].year > 2024:
            raise AssertionError("Development snapshot extends beyond 2024")

    frozen_evidence = {item["path"]: item for item in frozen["identity"]["evidence"]}
    for path in (PANEL, PANEL_MANIFEST, OOF):
        rel = path.relative_to(ROOT).as_posix()
        record = frozen_evidence.get(rel)
        if not record or not record["exists"] or sha256(path) != record["sha256"]:
            raise AssertionError(f"Frozen evidence identity failed: {rel}")
    if sha256(PARENT) != manifest["source"]["sha256"]:
        raise AssertionError("Parent event ledger identity differs from feature manifest")

    report = {
        "schema_version": "fx-support-feature-integrity-v1",
        "session_id": SESSION,
        "status": "PASS",
        "ml4t_engineer": {
            "package_version": "0.1.4",
            "api": "ml4t.engineer.compute_features",
            "regenerated_indicators": ["ema50", "atr20", "atr100"],
            "feature_panel_manifest_sha256": sha256(PANEL_MANIFEST),
        },
        "fixed_event_features": comparisons,
        "event_count": regenerated.height,
        "oof_event_count": oof.height,
        "oof_selected_count": oof.filter(pl.col("selected")).height,
        "oof_probability_sha256": sha256(OOF),
        "oof_signal_first": str(oof["event_timestamp"].min()),
        "oof_signal_last": str(oof["event_timestamp"].max()),
        "oof_decision_last": str(decision_last),
        "availability": "30m retest event features become available at event_timestamp + 30m",
        "labels": "custom inherited path-dependent outcomes; not generated by ml4t.engineer labeling",
        "development_inputs": input_bounds,
        "holdout_opened": False,
        "post_2024_prices_opened": False,
        "frozen_panel_sha256": sha256(PANEL),
        "parent_event_ledger_sha256": sha256(PARENT),
        "invariants": {
            "event_identity_and_levels_exact": True,
            "fixed_features_match_within_1e-8": True,
            "oof_keys_subset_of_panel": True,
            "oof_decisions_before_2025": True,
            "oof_cutoff_count": 112,
        },
        "source_manifest_identity": manifest["data"]["sha256"],
    }
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, sort_keys=True, allow_nan=False))
