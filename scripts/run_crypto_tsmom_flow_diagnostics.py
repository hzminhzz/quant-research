"""Run the frozen per-symbol TSMOM and flow Rank IC diagnostics.

This runner reads only the Phase 2 development feature and label artifacts. It
writes the declared diagnostic trial artifact; it does not run backtests or
inspect the prospective holdout.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import yaml
from scipy.stats import rankdata, t

from ml4t.diagnostic.metrics.ic import information_coefficient
from ml4t.diagnostic.metrics.ic_inference import compute_ic_hac_stats

ROOT = Path(__file__).resolve().parents[1]
SESSION_ID = "crypto_tsmom_flow_increment_20261008_v4"
SESSION_DIR = ROOT / "run_log" / "research_sessions" / SESSION_ID
CONFIG_PATH = ROOT / "config" / "research_sessions" / f"{SESSION_ID}.yaml"
FROZEN_PATH = SESSION_DIR / "frozen_spec.json"
PHASE2_REPORT_PATH = SESSION_DIR / "phase2_feature_report.json"
TRIAL_ID = "trial_4_flow_incremental_diagnostic"
OUTPUT_PATH = SESSION_DIR / "diagnostics" / f"{TRIAL_ID}.json"
TSMOM_TRIALS = {
    "trial_1_tsmom_72h_primary": 72,
    "trial_2_tsmom_24h_sensitivity": 24,
    "trial_3_tsmom_168h_sensitivity": 168,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_identity(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _finite(value: Any) -> float | None:
    number = float(value)
    return number if math.isfinite(number) else None


def _rank_values(values: np.ndarray) -> np.ndarray:
    ranks = rankdata(values, method="average").astype(np.float64)
    centered = ranks - ranks.mean()
    scale = float(np.sqrt(np.mean(centered * centered)))
    if not math.isfinite(scale) or scale == 0.0:
        raise ValueError("Rank IC requires non-constant inputs")
    return centered / scale


def _rank_ic_components(
    signal: np.ndarray, forward_return: np.ndarray
) -> tuple[float, np.ndarray]:
    """Return ML4T Spearman IC and its rank-score influence contributions.

    The influence series uses the Pearson-correlation influence function on
    centered, unit-variance empirical ranks. HAC inference is conditional on
    those empirical rank transforms; the report records this approximation.
    """
    signal = np.asarray(signal, dtype=np.float64).reshape(-1)
    forward_return = np.asarray(forward_return, dtype=np.float64).reshape(-1)
    valid = np.isfinite(signal) & np.isfinite(forward_return)
    signal = signal[valid]
    forward_return = forward_return[valid]
    if signal.size < 3:
        raise ValueError("Rank IC requires at least three finite pairs")

    ic_value = information_coefficient(signal, forward_return, method="spearman")
    if not isinstance(ic_value, (float, np.floating)):
        raise TypeError("ML4T Spearman IC returned an unexpected confidence result")
    rho = float(ic_value)
    ranked_signal = _rank_values(signal)
    ranked_return = _rank_values(forward_return)
    influence = (
        ranked_signal * ranked_return
        - 0.5 * rho * (ranked_signal * ranked_signal + ranked_return * ranked_return)
    )
    return rho, influence


def _hac_summary(
    estimate: float, influence: np.ndarray, label_horizon: int
) -> dict[str, Any]:
    n = int(influence.size)
    # The influence mean is zero by construction. Add the estimate so ML4T's
    # Newey-West mean-series API returns the estimator and its HAC standard error.
    hac = compute_ic_hac_stats(
        estimate + influence,
        label_horizon=label_horizon,
        allow_naive_fallback=False,
    )
    if int(hac["n_periods"]) != n:
        raise ValueError("HAC estimator changed the influence-series sample size")
    if not math.isclose(float(hac["mean_ic"]), estimate, rel_tol=0.0, abs_tol=1e-10):
        raise ValueError("Rank-correlation influence series does not center on its estimate")
    se = float(hac["hac_se"])
    critical = float(t.ppf(0.975, df=n - 1))
    return {
        "hac_se": _finite(se),
        "ci95_lower": _finite(estimate - critical * se),
        "ci95_upper": _finite(estimate + critical * se),
        "p_value_hac": _finite(hac["p_value"]),
        "effective_lags": int(hac["effective_lags"]),
        "n": n,
    }


def paired_rank_ic_hac(
    baseline: np.ndarray,
    augmented: np.ndarray,
    forward_return: np.ndarray,
    label_horizon: int,
) -> tuple[dict[str, Any], np.ndarray]:
    """Estimate paired Spearman IC change and its Newey-West interval."""
    baseline_ic, baseline_influence = _rank_ic_components(baseline, forward_return)
    augmented_ic, augmented_influence = _rank_ic_components(augmented, forward_return)
    delta = augmented_ic - baseline_ic
    delta_influence = augmented_influence - baseline_influence
    result = {
        "baseline_rank_ic": _finite(baseline_ic),
        "baseline_hac": _hac_summary(baseline_ic, baseline_influence, label_horizon),
        "augmented_rank_ic": _finite(augmented_ic),
        "augmented_hac": _hac_summary(augmented_ic, augmented_influence, label_horizon),
        "paired_rank_ic_delta": _finite(delta),
        "paired_delta_hac": _hac_summary(delta, delta_influence, label_horizon),
    }
    return result, delta_influence


def _pairs(
    frame: pl.DataFrame, symbol: str, signal_col: str, return_col: str
) -> tuple[list[datetime], np.ndarray, np.ndarray]:
    sample = (
        frame.filter(pl.col("symbol") == symbol)
        .select("timestamp", signal_col, return_col)
        .filter(
            pl.col(signal_col).is_not_null()
            & pl.col(signal_col).cast(pl.Float64).is_finite()
            & pl.col(return_col).is_finite()
        )
        .sort("timestamp")
    )
    return (
        sample["timestamp"].to_list(),
        sample[signal_col].cast(pl.Float64).to_numpy(),
        sample[return_col].to_numpy(),
    )


def _load_frozen_inputs() -> tuple[pl.DataFrame, dict[str, Any], dict[str, Any]]:
    frozen = json.loads(FROZEN_PATH.read_text())
    phase2 = json.loads(PHASE2_REPORT_PATH.read_text())
    config = yaml.safe_load(CONFIG_PATH.read_text())

    if phase2["status"] != "PASS" or phase2["checks"]["diagnostics_run"]:
        raise ValueError("Phase 2 artifact is not an eligible feature/label input")
    if phase2["holdout_values_read"] or phase2["frozen_spec_sha256"] != frozen["frozen_sha256"]:
        raise ValueError("Phase 2 report does not match the frozen development study")
    if config["session_id"] != SESSION_ID:
        raise ValueError("Session configuration identity mismatch")

    config_identity = _file_identity(CONFIG_PATH)
    if config_identity["sha256"] != frozen["identity"]["config"]["sha256"]:
        raise ValueError("Current configuration differs from the frozen identity")
    if config_identity["sha256"] != phase2["config_sha256"]:
        raise ValueError("Phase 2 report used a different configuration")

    flow_source_path = ROOT / "run_log" / "crypto_tsmom_flow_inputs_20261008_source_manifest.json"
    flow_source_identity = _file_identity(flow_source_path)
    frozen_flow_source = next(
        (
            item
            for item in frozen["identity"]["evidence"]
            if item["path"] == flow_source_identity["path"]
        ),
        None,
    )
    if frozen_flow_source is None or frozen_flow_source["sha256"] != flow_source_identity["sha256"]:
        raise ValueError("Flow source manifest differs from the frozen identity")

    for input_data in phase2["input_data"]:
        path = ROOT / input_data["path"]
        if _sha256(path) != input_data["sha256"]:
            raise ValueError(f"Phase 2 source identity changed: {input_data['path']}")

    feature_meta = phase2["feature_artifact"]
    label_meta = phase2["label_artifact"]
    feature_path = ROOT / feature_meta["path"]
    label_path = ROOT / label_meta["path"]
    if _sha256(feature_path) != feature_meta["sha256"]:
        raise ValueError("Phase 2 feature artifact identity changed")
    if _sha256(label_path) != label_meta["sha256"]:
        raise ValueError("Phase 2 label artifact identity changed")

    features = pl.read_parquet(feature_path)
    labels = pl.read_parquet(label_path)
    frame = features.join(
        labels,
        on=["timestamp", "symbol"],
        how="inner",
        validate="1:1",
    ).sort(["symbol", "timestamp"])
    if frame.height != features.height or frame.height != labels.height:
        raise ValueError("Feature and label artifacts do not have identical row keys")
    if frame.select(["timestamp", "symbol"]).unique().height != frame.height:
        raise ValueError("Duplicate symbol/timestamp keys in Phase 2 artifacts")

    evaluation = config["evaluation"]
    start = datetime.fromisoformat(evaluation["development_start"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(evaluation["development_end"].replace("Z", "+00:00"))
    timestamps = frame["timestamp"]
    observed_timestamps = timestamps.to_list()
    if observed_timestamps[0] < start or observed_timestamps[-1] >= end:
        raise ValueError("Phase 2 artifacts contain rows outside the development window")
    holdout_start = datetime.fromisoformat(
        evaluation["holdout_start"].replace("Z", "+00:00")
    )
    if observed_timestamps[-1] >= holdout_start:
        raise ValueError("Prospective holdout rows are forbidden in Phase 3")

    symbols = [item["symbol"] for item in config["instruments"]]
    if set(frame["symbol"].unique().to_list()) != set(symbols):
        raise ValueError("Phase 2 symbols do not match the frozen instrument universe")
    expected_rows = int((end - start).total_seconds() // 3600)
    for symbol in symbols:
        series = frame.filter(pl.col("symbol") == symbol)["timestamp"]
        if len(series) != expected_rows:
            raise ValueError(f"Unexpected development row count for {symbol}")
        time_values = series.to_numpy()
        if not np.all(np.diff(time_values) == np.timedelta64(1, "h")):
            raise ValueError(f"Non-contiguous hourly timestamps for {symbol}")

    return frame, {"frozen": frozen, "phase2": phase2, "config": config}, {
        "config": config_identity,
        "frozen_spec": _file_identity(FROZEN_PATH),
        "phase2_report": _file_identity(PHASE2_REPORT_PATH),
        "feature_artifact": _file_identity(feature_path),
        "label_artifact": _file_identity(label_path),
        "flow_source_manifest": flow_source_identity,
        "source_price_inputs": [
            {**item, **{"actual_sha256": _sha256(ROOT / item["path"])}}
            for item in phase2["input_data"]
        ],
    }


def _run_tsmom_diagnostics(
    frame: pl.DataFrame, symbols: list[str], horizons: list[int]
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for trial_id, lookback in TSMOM_TRIALS.items():
        signal_col = f"tsmom_{lookback}h_signal"
        by_symbol: list[dict[str, Any]] = []
        for symbol in symbols:
            horizon_results: dict[str, Any] = {}
            for horizon in horizons:
                return_col = f"forward_return_{horizon}h"
                timestamps, signal, outcome = _pairs(frame, symbol, signal_col, return_col)
                rho, influence = _rank_ic_components(signal, outcome)
                stats = _hac_summary(rho, influence, horizon)
                horizon_results[str(horizon)] = {
                    "rank_ic": _finite(rho),
                    **stats,
                    "sample_start_utc": timestamps[0].isoformat(),
                    "sample_end_utc": timestamps[-1].isoformat(),
                }
            by_symbol.append({"symbol": symbol, "by_forward_horizon_hours": horizon_results})
        results.append(
            {
                "trial_id": trial_id,
                "lookback_hours": lookback,
                "role": "primary" if lookback == 72 else "sensitivity",
                "by_symbol": by_symbol,
            }
        )
    return results


def _run_flow_diagnostic(
    frame: pl.DataFrame, symbols: list[str], horizons: list[int]
) -> dict[str, Any]:
    baseline_col = "tsmom_72h_flow_baseline_score"
    augmented_col = "tsmom_72h_flow_augmented_score"
    results_by_horizon: dict[str, Any] = {}

    for horizon in horizons:
        return_col = f"forward_return_{horizon}h"
        per_symbol: list[dict[str, Any]] = []
        all_timestamps: list[datetime] | None = None
        delta_influences: list[np.ndarray] = []
        deltas: list[float] = []

        for symbol in symbols:
            sample = (
                frame.filter(pl.col("symbol") == symbol)
                .select("timestamp", baseline_col, augmented_col, return_col)
                .filter(
                    pl.col(baseline_col).is_not_null()
                    & pl.col(baseline_col).cast(pl.Float64).is_finite()
                    & pl.col(augmented_col).is_finite()
                    & pl.col(return_col).is_finite()
                )
                .sort("timestamp")
            )
            timestamps = sample["timestamp"].to_list()
            if all_timestamps is None:
                all_timestamps = timestamps
            elif timestamps != all_timestamps:
                raise ValueError("Flow comparisons do not share identical UTC timestamps")

            baseline = sample[baseline_col].cast(pl.Float64).to_numpy()
            augmented = sample[augmented_col].to_numpy()
            outcome = sample[return_col].to_numpy()
            comparison, delta_influence = paired_rank_ic_hac(
                baseline, augmented, outcome, horizon
            )
            per_symbol.append({"symbol": symbol, **comparison})
            deltas.append(float(comparison["paired_rank_ic_delta"]))
            delta_influences.append(delta_influence)

        if all_timestamps is None or not delta_influences:
            raise ValueError("Flow diagnostic has no valid timestamps")
        mean_delta = float(np.mean(deltas))
        mean_influence = np.mean(np.stack(delta_influences), axis=0)
        equal_weight_hac = _hac_summary(mean_delta, mean_influence, horizon)
        results_by_horizon[str(horizon)] = {
            "primary": horizon == 1,
            "per_symbol": per_symbol,
            "equal_weight_mean_paired_delta": _finite(mean_delta),
            "equal_weight_mean_delta_hac": equal_weight_hac,
            "sample_start_utc": all_timestamps[0].isoformat(),
            "sample_end_utc": all_timestamps[-1].isoformat(),
        }

    return {
        "trial_id": TRIAL_ID,
        "primary_forward_horizon_hours": 1,
        "results_by_forward_horizon_hours": results_by_horizon,
        "acceptance_assessment": "NOT_EVALUABLE_OUT_OF_SAMPLE",
        "assessment_reason": (
            "The frozen prospective holdout starts 2026-08-01 and remains incomplete. "
            "These estimates use development data only."
        ),
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def main() -> None:
    if OUTPUT_PATH.exists():
        raise FileExistsError(f"Refusing to overwrite diagnostic artifact: {OUTPUT_PATH}")

    frame, inputs, identities = _load_frozen_inputs()
    config = inputs["config"]
    phase2 = inputs["phase2"]
    symbols = [item["symbol"] for item in config["instruments"]]
    horizons = [int(value) for value in config["evaluation"]["flow_feature"]["forward_return_horizons_hours"]]

    flow_baseline = "tsmom_72h_flow_baseline_score"
    flow_augmented = "tsmom_72h_flow_augmented_score"
    if frame.filter((pl.col(flow_baseline).is_null()) != (pl.col(flow_augmented).is_null())).height:
        raise ValueError("Baseline and augmented flow scores have different null boundaries")

    zero_denominator = config["evaluation"]["flow_feature"]["zero_denominator_observations"]
    expected_bad_time = datetime.fromisoformat(zero_denominator["timestamp_utc"].replace("Z", "+00:00"))
    invalid_counts: dict[str, int] = {}
    for symbol in symbols:
        invalid = frame.filter(
            (pl.col("symbol") == symbol)
            & pl.col("flow_imbalance").is_null()
            & pl.col("tsmom_72h_signal").is_not_null()
        )
        invalid_counts[symbol] = invalid.height
        if invalid.height != int(zero_denominator["count_per_symbol"]):
            raise ValueError(f"Unexpected invalid-flow count for {symbol}")
        if invalid["timestamp"].to_list() != [expected_bad_time]:
            raise ValueError(f"Unexpected invalid-flow timestamp for {symbol}")

    phase2_checks = phase2["checks"]
    if frame.height != int(phase2_checks["rows"]):
        raise ValueError("Joined Phase 2 artifacts differ from the frozen row count")
    if sum(invalid_counts.values()) != int(phase2_checks["flow_invalid_rows"]):
        raise ValueError("Invalid flow observations differ from the Phase 2 audit")

    report = {
        "schema_version": 1,
        "session_id": SESSION_ID,
        "phase": "Phase 3: Factor diagnostics",
        "trial_id": TRIAL_ID,
        "status": "COMPLETED",
        "classification": "EXPLORATORY",
        "approval_status": "NOT_APPROVED",
        "evidence_type": "descriptive_diagnostic",
        "recorded_at": datetime.now(UTC).isoformat(),
        "frozen_spec_sha256": inputs["frozen"]["frozen_sha256"],
        "outcome_access": {
            "development_values_read": True,
            "holdout_values_read": False,
            "strategy_metrics_computed": False,
            "backtests_run": False,
        },
        "scope": {
            "start_inclusive_utc": config["evaluation"]["development_start"],
            "end_exclusive_utc": config["evaluation"]["development_end"],
            "symbols": symbols,
            "rows_per_symbol": {
                symbol: frame.filter(pl.col("symbol") == symbol).height for symbol in symbols
            },
            "forward_return_horizons_hours": horizons,
            "primary_forward_horizon_hours": 1,
            "flow_invalid_rows_by_symbol": invalid_counts,
            "flow_invalid_timestamp_utc": zero_denominator["timestamp_utc"],
        },
        "identities": {
            **identities,
            "script": _file_identity(Path(__file__).resolve()),
        },
        "inference": {
            "rank_ic": "ml4t.diagnostic.metrics.ic.information_coefficient(method='spearman')",
            "hac": "ml4t.diagnostic.metrics.ic_inference.compute_ic_hac_stats; Newey-West Bartlett kernel; automatic bandwidth floored at forward_horizon_hours - 1; naive fallback disabled",
            "confidence_interval": "two-sided 95% Student-t interval with n-1 degrees of freedom",
            "rank_ic_hac_method_note": (
                "HAC is applied to first-order Pearson-correlation influence contributions "
                "of centered, unit-variance empirical average ranks. The interval is conditional "
                "on those empirical rank transforms; rank-transform estimation uncertainty "
                "is not separately estimated."
            ),
            "cross_asset_policy": "Compute each symbol separately; equal-weight paired change combines timestamp-aligned influence series; never pool raw assets as a cross-sectional panel.",
        },
        "tsmom_diagnostics": _run_tsmom_diagnostics(frame, symbols, horizons),
        "flow_diagnostic": _run_flow_diagnostic(frame, symbols, horizons),
        "limitations": [
            "All Rank IC estimates use development data and are descriptive, not out-of-sample evidence.",
            "The flow support criterion requires a prospective out-of-sample comparison and remains unevaluated.",
            "The declared prior trial history remains incomplete; no selection-bias adjustment is computed.",
            "The three-symbol equal-weight result is a time-aligned summary, not cross-sectional evidence.",
        ],
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_PATH.with_suffix(OUTPUT_PATH.suffix + ".tmp")
    temporary.write_text(json.dumps(_json_safe(report), indent=2, sort_keys=True) + "\n")
    temporary.replace(OUTPUT_PATH)
    print(json.dumps({"status": report["status"], "artifact": OUTPUT_PATH.relative_to(ROOT).as_posix(), "symbols": symbols, "rows": frame.height}, sort_keys=True))


if __name__ == "__main__":
    main()
