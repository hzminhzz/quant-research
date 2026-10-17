"""Run one of four preregistered development-only FX support followup trials.

No trading simulation: evaluate the parent D0 event outcome 'previous high
before first support-invalidation close' in 240 completed 30m bars. Four arms
have disjoint output artifacts. No 2025-2026 holdout is read or scored.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import polars as pl
import statsmodels.api as sm
from lightgbm import LGBMClassifier
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from statsmodels.stats.proportion import proportion_confint

ROOT = Path(__file__).resolve().parents[1]
SESSION = "fx_support_conditions_20261008"
SOURCE = ROOT / f"data/features/{SESSION}.parquet"
MANIFEST = ROOT / f"data/features/{SESSION}_manifest.json"
OUT = ROOT / "run_log" / SESSION
TARGET = "target_before_support_invalidation_240"
TRIALS = (
    "I1_unfiltered",
    "I2_momentum_confirmation",
    "I3_trend_volatility",
    "I4_purged_lightgbm",
)
FEATURES = (
    "candle_strength", "roc3_atr", "roc12_atr", "roc24_atr",
    "ema50_slope16_atr", "ema_gap_atr", "atr_ratio",
    "support_gap_atr", "distance_high_atr", "reference_height_atr",
    "bars_elapsed_calendar", "utc_hour_sin", "utc_hour_cos",
)
PAIRS = ("AUDUSD", "EURUSD", "GBPUSD")
ERAS = ((2010, 2013), (2014, 2017), (2018, 2021), (2022, 2024))
ML_FOLDS = ((2017, 2018), (2019, 2020), (2021, 2022), (2023, 2024))
ML_CUTOFF = 0.30
ML_PARAMS = {
    "n_estimators": 100,
    "learning_rate": 0.03,
    "max_depth": 2,
    "num_leaves": 7,
    "min_child_samples": 30,
    "reg_lambda": 10.0,
    "random_state": 42,
    "n_jobs": 1,
    "verbosity": -1,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_panel() -> pl.DataFrame:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if sha256_file(SOURCE) != manifest["data"]["sha256"]:
        raise RuntimeError("Input feature panel differs from frozen source identity")
    frame = pl.read_parquet(SOURCE).sort(["event_timestamp", "symbol"])
    if frame.height != 1395 or frame["event_timestamp"].max().year >= 2025:
        raise RuntimeError("Unexpected parent event count or holdout event detected")
    if frame.select(pl.all().null_count()).row(0) != tuple(0 for _ in frame.columns):
        raise RuntimeError("Incomplete feature panel")
    return frame


def predeclared_filter(frame: pl.DataFrame, arm: str) -> pl.DataFrame:
    if arm == TRIALS[0]:
        selected = pl.lit(True)
    elif arm == TRIALS[1]:
        # Features become available only when the retest 30m candle closes.
        selected = (pl.col("candle_strength") >= 0.75) & (pl.col("roc3_atr") > 0.0)
    elif arm == TRIALS[2]:
        selected = (
            (pl.col("ema_gap_atr") > 0.0)
            & (pl.col("ema50_slope16_atr") > 0.0)
            & (pl.col("atr_ratio") <= 1.20)
        )
    else:
        raise ValueError(f"Filter requested for non-filter arm: {arm}")
    return frame.with_columns(selected.alias("selected"))


def ml_matrix(frame: pl.DataFrame) -> np.ndarray:
    numeric = frame.select(list(FEATURES)).to_numpy().astype(np.float64)
    if not np.isfinite(numeric).all():
        raise ValueError("Non-finite ML feature detected")
    pair_onehot = np.column_stack([
        (frame["symbol"].to_numpy() == pair).astype(np.float64)
        for pair in PAIRS
    ])
    return np.column_stack([numeric, pair_onehot])


def ml_fold_selection(frame: pl.DataFrame, start_year: int, end_year: int) -> tuple[pl.DataFrame, pl.DataFrame]:
    test = frame.filter(pl.col("year").is_between(start_year, end_year)).sort(
        ["event_timestamp", "symbol"]
    )
    # Actual 240-complete-30m-bar label end is mandatory, followed by two
    # calendar days of embargo; training must also predate validation.
    split_start = datetime(start_year, 1, 1, tzinfo=timezone.utc)
    train = frame.filter(
        (pl.col("year") < start_year)
        & (pl.col("label_horizon_end") < split_start - timedelta(days=2))
    ).sort(["event_timestamp", "symbol"])
    if not test.is_empty() and not train.is_empty():
        if train["label_horizon_end"].max() >= test["event_timestamp"].min() - timedelta(days=2):
            raise RuntimeError("Train label horizon/embargo overlaps test event")
    return train, test


def run_ml(frame: pl.DataFrame) -> tuple[pl.DataFrame, dict[str, object]]:
    validated: list[pl.DataFrame] = []
    fold_results: list[dict[str, object]] = []
    for start_year, end_year in ML_FOLDS:
        train, test = ml_fold_selection(frame, start_year, end_year)
        if train.height < 200 or test.height < 20:
            raise RuntimeError(f"Insufficient samples in fixed fold {start_year}-{end_year}")
        x_train, x_test = ml_matrix(train), ml_matrix(test)
        y_train, y_test = train[TARGET].to_numpy().astype(int), test[TARGET].to_numpy().astype(int)
        if len(np.unique(y_train)) != 2 or len(np.unique(y_test)) != 2:
            raise RuntimeError(f"Single-class fixed fold {start_year}-{end_year}")
        clf = LGBMClassifier(**ML_PARAMS)
        clf.fit(x_train, y_train)
        predictions = clf.predict_proba(x_test)[:, 1]
        if not np.isfinite(predictions).all():
            raise RuntimeError("Non-finite ML probabilities")
        selected = predictions >= ML_CUTOFF
        validated.append(
            test.with_columns(
                pl.Series("pred_probability", predictions),
                pl.Series("selected", selected),
                pl.lit(f"{start_year}-{end_year}").alias("fold"),
            )
        )
        fold_results.append({
            "fold": f"{start_year}-{end_year}",
            "n_train": train.height,
            "n_test": test.height,
            "train_positive_rate": float(y_train.mean()),
            "test_positive_rate": float(y_test.mean()),
            "n_selected": int(selected.sum()),
            "selected_positive_rate": float(y_test[selected].mean()) if selected.any() else None,
            "average_precision": float(average_precision_score(y_test, predictions)),
            "roc_auc": float(roc_auc_score(y_test, predictions)),
            "brier_score": float(brier_score_loss(y_test, predictions)),
            "constant_train_base_brier": float(
                brier_score_loss(y_test, np.full(y_test.shape, y_train.mean()))
            ),
            "purge_rule": "actual 240-bar label end strictly before validation start - 2 calendar days",
            "last_train_label_end": str(train["label_horizon_end"].max()),
            "first_val_event": str(test["event_timestamp"].min()),
        })
    scored = pl.concat(validated, how="vertical").sort(["event_timestamp", "symbol"])
    if scored.group_by(["symbol", "event_timestamp"]).len().filter(pl.col("len") != 1).height:
        raise RuntimeError("Duplicate OOF predictions")
    return scored, {
        "type": "LightGBM fixed configuration, four expanding chronological OOF folds",
        "features": [*FEATURES, *(f"pair_{p}" for p in PAIRS)],
        "cutoff": ML_CUTOFF,
        "params": ML_PARAMS,
        "folds": fold_results,
        "pooled_average_precision": float(average_precision_score(
            scored[TARGET].to_numpy().astype(int), scored["pred_probability"].to_numpy()
        )),
        "pooled_brier_score": float(brier_score_loss(
            scored[TARGET].to_numpy().astype(int), scored["pred_probability"].to_numpy()
        )),
    }


def proportion(frame: pl.DataFrame, field: str = TARGET) -> dict[str, object] | None:
    if frame.is_empty():
        return None
    n = frame.height
    hits = int(frame[field].sum())
    lo, hi = proportion_confint(hits, n, method="wilson", alpha=0.05)
    return {
        "n": n,
        "hits": hits,
        "rate_pct": 100.0 * hits / n,
        "wilson_ci95_pct": [100.0 * float(lo), 100.0 * float(hi)],
    }


def cluster_intercept(frame: pl.DataFrame) -> dict[str, object] | None:
    if frame.height < 4 or frame["month"].n_unique() < 4:
        return None
    y = frame[TARGET].cast(pl.Int8).to_numpy().astype(float)
    fit = sm.OLS(y, np.ones((len(y), 1))).fit(
        cov_type="cluster", cov_kwds={"groups": frame["month"].to_numpy()}
    )
    point, se = float(fit.params[0]), float(fit.bse[0])
    return {
        "n_cluster_months": int(frame["month"].n_unique()),
        "se_pct": 100.0 * se,
        "ci95_pct": [100.0 * max(0.0, point - 1.96 * se), 100.0 * min(1.0, point + 1.96 * se)],
    }


def cluster_lift(frame: pl.DataFrame) -> dict[str, object] | None:
    selected = frame["selected"].cast(pl.Int8).to_numpy().astype(float)
    if frame.height < 6 or len(np.unique(selected)) != 2 or frame["month"].n_unique() < 4:
        return None
    y = frame[TARGET].cast(pl.Int8).to_numpy().astype(float)
    fit = sm.OLS(y, sm.add_constant(selected)).fit(
        cov_type="cluster", cov_kwds={"groups": frame["month"].to_numpy()}
    )
    point, se = float(fit.params[1]), float(fit.bse[1])
    return {
        "selected_vs_not_selected_lift_pp": 100.0 * point,
        "cluster_se_pp": 100.0 * se,
        "ci95_pp": [100.0 * (point - 1.96 * se), 100.0 * (point + 1.96 * se)],
    }


def evaluate_arm(frame: pl.DataFrame, arm: str, ml: dict[str, object] | None = None) -> dict[str, object]:
    selected = frame.filter(pl.col("selected"))
    not_selected = frame.filter(~pl.col("selected"))
    by_pair = {pair: proportion(selected.filter(pl.col("symbol") == pair)) for pair in PAIRS}
    by_era = {
        f"{a}-{b}": proportion(selected.filter(pl.col("year").is_between(a, b)))
        for a, b in ERAS
    }
    baseline = proportion(frame)
    chosen = proportion(selected)
    chosen_ci = cluster_intercept(selected)
    risk_first_lift = (
        chosen["rate_pct"] - baseline["rate_pct"]
        if chosen is not None and baseline is not None else None
    )
    min_count = (
        selected.height >= 100
        and all(by_pair[p] is not None and by_pair[p]["n"] >= 20 for p in PAIRS)
    )
    checks = {
        "minimum_100_selected": selected.height >= 100,
        "minimum_20_per_pair": all(by_pair[p] is not None and by_pair[p]["n"] >= 20 for p in PAIRS),
        "selected_240bar_target_first_at_least_35pct": chosen is not None and chosen["rate_pct"] >= 35.0,
        "selected_lift_above_same_period_baseline_8pp": risk_first_lift is not None and risk_first_lift >= 8.0,
        "monthly_cluster_95_lower_above_baseline": (
            chosen_ci is not None and baseline is not None
            and chosen_ci["ci95_pct"][0] > baseline["rate_pct"]
        ),
        "at_least_2_of_3_pair_rates_exceed_same_period_baseline": sum(
            int(by_pair[p] is not None and by_pair[p]["rate_pct"] > baseline["rate_pct"])
            for p in PAIRS
        ) >= 2,
    }
    if ml is not None:
        folds = ml["folds"]
        checks["at_least_3_of_4_ml_folds_improve_base_rate"] = sum(
            int(f["selected_positive_rate"] is not None and
                100.0 * f["selected_positive_rate"] >
                100.0 * f["test_positive_rate"]) for f in folds
        ) >= 3
        checks["all_4_ml_fold_brier_better_than_constant"] = all(
            f["brier_score"] < f["constant_train_base_brier"] for f in folds
        )
    if arm == TRIALS[0]:
        disposition = "DESCRIPTIVE_BASELINE"
    elif not min_count:
        disposition = "INCONCLUSIVE"
    else:
        disposition = "PASS" if all(checks.values()) else "REJECT"

    return {
        "schema_version": "support-followup-diagnostics-v1",
        "session_id": SESSION,
        "trial_id": arm,
        "status": "completed",
        "classification": "EXPLORATORY",
        "approval_status": "NOT_APPROVED",
        "selection_disposition": disposition,
        "holdout_opened": False,
        "holdout_scored": False,
        "parent_label": TARGET,
        "horizon": "240 completed 30m bars",
        "baseline_scope": "same dates as trial, all support holds",
        "sample_base": baseline,
        "selected": chosen,
        "excluded": proportion(not_selected),
        "selected_ci95_monthly_cluster": chosen_ci,
        "selected_lift_vs_same_window_baseline_pp": risk_first_lift,
        "selected_vs_excluded_cluster_lift": cluster_lift(frame),
        "selected_new_high_anytime_within_240": proportion(selected, "within_240_bars"),
        "by_pair": by_pair,
        "by_era": by_era,
        "preregistered_checks": checks,
        "model": ml,
        "limitations": [
            "Event/factor diagnostic, not a backtest or executable net PnL.",
            "Outcome uses first 30m closing breach of support, not broker intrabar stop fills.",
            "Not all high-break outcomes offer favorable risk:reward.",
            "For fixed rule arms, all results are exploratory development-sample diagnostics.",
            "For ML, only chronological out-of-fold 2017-2024 events are scored.",
            "Overlapping labels reduce effective sample size; monthly clustering is approximate.",
            "Prior D0 results have been observed on this same development history.",
            "No model or filter may be selected for deployment without new backtest and final holdout.",
        ],
    }


def run_arm(arm: str) -> dict[str, object]:
    if arm not in TRIALS:
        raise ValueError(f"Unrecognized trial: {arm}")
    frozen = ROOT / f"run_log/research_sessions/{SESSION}/frozen_spec.json"
    if not frozen.exists():
        raise RuntimeError("The immutable session must be frozen before any trial")
    trial_dir = OUT / arm
    if trial_dir.exists():
        raise RuntimeError("Trial output path already exists; do not overwrite recorded attempts")
    frame = load_panel()
    if arm == TRIALS[3]:
        scored, model_report = run_ml(frame)
    else:
        scored = predeclared_filter(frame, arm)
        model_report = None
    report = evaluate_arm(scored, arm, ml=model_report)
    trial_dir.mkdir(parents=True, exist_ok=False)
    scored.write_parquet(trial_dir / "scored_events.parquet", compression="zstd")
    report["event_ledger"] = (trial_dir / "scored_events.parquet").relative_to(ROOT).as_posix()
    report["score_source"] = SOURCE.relative_to(ROOT).as_posix()
    result_path = trial_dir / "result.json"
    result_path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "trial": arm,
        "status": "completed",
        "disposition": report["selection_disposition"],
        "sample_base": report["sample_base"],
        "selected": report["selected"],
        "selection_lift_pp": report["selected_lift_vs_same_window_baseline_pp"],
        "checks": report["preregistered_checks"],
        "result_path": result_path.relative_to(ROOT).as_posix(),
        "ml": report["model"],
    }, indent=2, sort_keys=True, allow_nan=False))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--trial", required=True, choices=TRIALS)
    options = parser.parse_args()
    run_arm(options.trial)
