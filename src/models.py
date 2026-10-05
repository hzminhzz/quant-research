"""Machine Learning Meta-Labeling & Combinatorial Purged Cross-Validation.

Governed by ML4T Skills:
- ml4t-cpcv (Combinatorial Purged CV)
- ml4t-purging-embargo
- ml4t-meta-labels

Implements Marcos López de Prado's two-stage meta-labeling architecture:
Stage 1 (Primary Model/Rule): Determines trade direction (+1 / -1) and entry timing.
Stage 2 (Meta-Model): Produces a raw ranking score for conditional trade selection.
Validation: Combinatorial Purged CV generates a distribution of backtest paths
without temporal leakage or lookahead contamination.
"""

from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import polars as pl
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score

from ml4t.diagnostic.splitters import CombinatorialCV

from src.validation import (
    ValidationContractError,
    fold_uniqueness_weights,
    order_events,
    purged_cpcv_splits,
    require_complete_oof_coverage,
)


@dataclass(frozen=True)
class CPCVResult:
    """Evaluation summary from CPCV using raw ranking scores."""
    n_splits: int
    n_paths: int
    mean_auc: float
    std_auc: float
    baseline_win_rate: float
    filtered_win_rate: float
    precision: float
    recall: float
    oof_probabilities: np.ndarray
    passed_quality_gate: bool


def train_meta_model_cpcv(
    X: np.ndarray,
    y_meta: np.ndarray,
    active_trade_mask: np.ndarray,
    n_groups: int = 8,
    n_test_groups: int = 2,
    label_horizon: int = 20,
    embargo_size: int = 4,
    conviction_threshold: float = 0.55,
    random_state: int = 42,
) -> CPCVResult:
    """Train secondary ML meta-model using Combinatorial Purged Cross-Validation.

    Parameters
    ----------
    X : np.ndarray
        Feature matrix (N, K).
    y_meta : np.ndarray
        Binary meta-labels (1 = profitable trade, 0 = unprofitable trade).
    active_trade_mask : np.ndarray
        Boolean mask where primary signal fired (only active trades are modeled).
    n_groups : int, default 8
        Number of groups for CPCV partition.
    n_test_groups : int, default 2
        Number of test groups per combination (C(8,2) = 28 combinations).
    label_horizon : int, default 20
        Number of bars to purge before test boundaries.
    embargo_size : int, default 4
        Embargo buffer bars after test boundaries.
    conviction_threshold : float, default 0.55
        Raw-score cutoff used to select trades; it is not a calibrated probability.
    """
    n_samples = len(X)
    oof_probs = np.full(n_samples, np.nan)
    oof_counts = np.zeros(n_samples, dtype=int)
    prob_sums = np.zeros(n_samples, dtype=float)

    cv = CombinatorialCV(
        n_groups=n_groups,
        n_test_groups=n_test_groups,
        label_horizon=label_horizon,
        embargo_size=embargo_size,
    )

    split_aucs = []

    for train_idx, test_idx in cv.split(X):
        # Meta-model only trains on rows where the primary signal fired
        train_trades = train_idx[active_trade_mask[train_idx]]
        test_trades = test_idx[active_trade_mask[test_idx]]

        if len(train_trades) < 30 or len(test_trades) < 5:
            continue

        X_train, y_train = X[train_trades], y_meta[train_trades]
        X_test, y_test = X[test_trades], y_meta[test_trades]

        # Skip degenerate splits with only 1 class
        if len(np.unique(y_train)) < 2:
            continue

        clf = HistGradientBoostingClassifier(
            max_depth=4,
            max_iter=50,
            min_samples_leaf=15,
            random_state=random_state,
        )
        clf.fit(X_train, y_train)

        probs = clf.predict_proba(X[test_idx])[:, 1]
        prob_sums[test_idx] += probs
        oof_counts[test_idx] += 1

        if len(np.unique(y_test)) == 2:
            auc = roc_auc_score(y_test, clf.predict_proba(X_test)[:, 1])
            split_aucs.append(auc)

    # Average probabilities across out-of-fold evaluations
    evaluated = oof_counts > 0
    oof_probs[evaluated] = prob_sums[evaluated] / oof_counts[evaluated]

    # Evaluate on all primary trade events
    trade_eval = active_trade_mask & evaluated & ~np.isnan(y_meta)
    y_true = y_meta[trade_eval].astype(int)
    y_pred_prob = oof_probs[trade_eval]

    baseline_win_rate = float(np.mean(y_true)) if len(y_true) > 0 else 0.0

    # Filtered trades exceeding conviction threshold
    acted_mask = y_pred_prob >= conviction_threshold
    if np.sum(acted_mask) >= 10:
        filtered_win_rate = float(np.mean(y_true[acted_mask]))
        prec = float(precision_score(y_true, acted_mask, zero_division=0))
        rec = float(recall_score(y_true, acted_mask, zero_division=0))
    else:
        filtered_win_rate = baseline_win_rate
        prec = baseline_win_rate
        rec = 0.0

    mean_auc = float(np.mean(split_aucs)) if split_aucs else 0.50
    std_auc = float(np.std(split_aucs)) if split_aucs else 0.0

    passed_gate = bool(
        mean_auc > 0.52
        and filtered_win_rate >= baseline_win_rate
        and np.sum(acted_mask) >= 20
    )

    return CPCVResult(
        n_splits=len(split_aucs),
        n_paths=n_groups - 1,
        mean_auc=mean_auc,
        std_auc=std_auc,
        baseline_win_rate=baseline_win_rate,
        filtered_win_rate=filtered_win_rate,
        precision=prec,
        recall=rec,
        oof_probabilities=oof_probs,
        passed_quality_gate=passed_gate,
    )


@dataclass
class MetaModelResult:
    """Evaluation summary for LightGBM Meta-Classifier trained with CPCV raw scores."""
    model: Any
    oof_probabilities: np.ndarray
    feature_names: List[str]
    feature_importances: Dict[str, float]
    shap_values: Optional[np.ndarray]
    mean_auc: float
    brier_score: Optional[float]
    baseline_win_rate: float
    filtered_win_rate: float
    precision: float
    recall: float
    f1_score: float
    passed_quality_gate: bool
    score_semantics: str = "raw_model_score"
    oof_coverage: Optional[np.ndarray] = None
    oof_score_mse: float = 0.0
    fold_diagnostics: Optional[List[Dict[str, Any]]] = None
    std_auc: float = 0.0
    min_auc: float = 0.0
    max_auc: float = 0.0

    @property
    def oof_scores(self) -> np.ndarray:
        """Return OOF ranking scores; legacy field name is retained for compatibility."""
        return self.oof_probabilities


def train_meta_classifier_cpcv(
    events: List[Any],
    feature_cols: Optional[List[str]] = None,
    n_groups: int = 6,
    n_test_groups: int = 2,
    embargo_size: int = 5,
    conviction_threshold: float = 0.52,
    use_monotonic_constraints: bool = True,
    sample_weights: Optional[np.ndarray] = None,
    random_state: int = 42,
    require_temporal_contract: bool = False,
    embargo_duration: timedelta = timedelta(0),
    compute_shap: bool = True,
) -> MetaModelResult:
    """Train institutional LightGBM Meta-Classifier using Combinatorial Purged CV (CPCV).

    Parameters
    ----------
    events : List[ORBTradeEvent]
        List of candidate breakout trade events extracted by MetaLabelingORBDatasetBuilder.
    feature_cols : List[str], optional
        List of feature names extracted in events. Defaults to canonical high-information vector.
    n_groups : int, default 6
        Number of time-series groups for CPCV partition.
    n_test_groups : int, default 2
        Number of test groups per combination.
    embargo_size : int, default 5
        Embargo buffer size to prevent leakage between folds.
        conviction_threshold : float, default 0.52
        Raw-score cutoff used to select trades; it is not a calibrated probability.
    use_monotonic_constraints : bool, default True
        Enforce economically rational sign constraints on trees:
        - rvol_1h: +1 (Higher volume -> higher breakout follow-through)
        - range_to_atr20: -1 (Over-expanded range -> mean reversion / exhaustion)
        - wick_upper_ratio (for long): -1 (Upper rejection shadow -> failed breakout)
    sample_weights : np.ndarray, optional
        Sample uniqueness weights w_i = u_i * |r_i| to neutralize concurrency clustering.
    """
    import lightgbm as lgb
    from sklearn.metrics import f1_score
    import shap

    if not events:
        raise ValueError("Cannot train meta-classifier on empty event list.")

    temporal_contract = True
    try:
        events = order_events(events)
    except ValidationContractError:
        temporal_contract = False
        if require_temporal_contract:
            raise

    default_features = [
        "rvol_1h",
        "vwap_alignment",
        "wick_exhaustion",
        "range_to_atr20",
        "garman_klass_norm",
        "spx_alignment",
        "nr7_flag",
        "breakout_bar_range_ratio",
    ]
    feat_names = feature_cols or default_features

    # Build X and y
    X_list = []
    y_list = []
    for e in events:
        feat_dict = e.features
        row = [feat_dict.get(k, 0.0) for k in feat_names]
        X_list.append(row)
        y_list.append(e.label)

    X = np.array(X_list, dtype=np.float32)
    y = np.array(y_list, dtype=np.int32)
    n_samples = len(X)

    if sample_weights is None or len(sample_weights) != n_samples:
        weights = np.ones(n_samples, dtype=np.float32)
    else:
        weights = sample_weights.astype(np.float32)

    # Monotonic constraints: +1 = positive, -1 = negative, 0 = unconstrained
    # Map feature names to monotonic constraints
    mono_map = {
        "rvol_1h": 1,
        "vwap_alignment": 1,
        "wick_exhaustion": -1,
        "breakout_bar_range_ratio": -1,
        "spx_alignment": 1,
    }
    mono_constraints = [mono_map.get(col, 0) for col in feat_names] if use_monotonic_constraints else None


    # CPCV split plan. Temporal-contract events use interval purging; legacy
    # fixtures without aware timestamps retain the compatibility splitter.
    if temporal_contract:
        split_plan = purged_cpcv_splits(
            events,
            n_groups=n_groups,
            n_test_groups=n_test_groups,
            embargo=embargo_duration,
        )
    else:
        cv = CombinatorialCV(
            n_groups=n_groups,
            n_test_groups=n_test_groups,
            embargo_size=embargo_size,
        )
        split_plan = [
            (train_idx, test_idx, None) for train_idx, test_idx in cv.split(X)
        ]

    oof_probs_sum = np.zeros(n_samples, dtype=np.float64)
    oof_counts = np.zeros(n_samples, dtype=np.int32)
    split_aucs = []
    fold_diagnostics: List[Dict[str, Any]] = []
    failed_folds: List[int] = []

    lgb_params = {
        "objective": "binary",
        "metric": "binary_logloss",
        "boosting_type": "gbdt",
        "learning_rate": 0.03,
        "num_leaves": 15,
        "max_depth": 4,
        "min_child_samples": 20,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "monotone_constraints": mono_constraints if use_monotonic_constraints else None,
        "random_state": random_state,
        "verbose": -1,
        "n_estimators": 80,
    }

    # Run Out-Of-Fold predictions across CPCV paths
    for fold_number, (train_idx, test_idx, split_diagnostics) in enumerate(split_plan):
        fold_record: Dict[str, Any] = {
            "fold": fold_number,
            "train_count": int(len(train_idx)),
            "test_count": int(len(test_idx)),
            "split": asdict(split_diagnostics) if split_diagnostics is not None else None,
        }
        if len(train_idx) < 30 or len(test_idx) < 5:
            fold_record.update(status="FAILED", failure_reason="insufficient_samples")
            fold_diagnostics.append(fold_record)
            failed_folds.append(fold_number)
            continue

        X_tr, y_tr = X[train_idx], y[train_idx]
        X_te, y_te = X[test_idx], y[test_idx]
        if temporal_contract:
            fold_weights = fold_uniqueness_weights(events, train_idx)
            w_tr = fold_weights if sample_weights is None else weights[train_idx] * fold_weights
        else:
            w_tr = weights[train_idx]

        if len(np.unique(y_tr)) < 2:
            fold_record.update(status="FAILED", failure_reason="single_class_training")
            fold_diagnostics.append(fold_record)
            failed_folds.append(fold_number)
            continue

        clf = lgb.LGBMClassifier(**lgb_params)
        clf.fit(X_tr, y_tr, sample_weight=w_tr)

        preds = clf.predict_proba(X_te)[:, 1]
        oof_probs_sum[test_idx] += preds
        oof_counts[test_idx] += 1

        if len(np.unique(y_te)) == 2:
            split_aucs.append(roc_auc_score(y_te, preds))
            fold_record["auc"] = float(split_aucs[-1])
        else:
            fold_record["auc"] = None
        fold_record.update(status="FIT", failure_reason=None)
        fold_diagnostics.append(fold_record)

    if temporal_contract and failed_folds:
        error = ValidationContractError(
            f"CPCV fold validation failed for folds {failed_folds}"
        )
        error.fold_diagnostics = fold_diagnostics  # type: ignore[attr-defined]
        raise error

    # Average OOF scores. A validated temporal run must never backfill an
    # unevaluated event with 0.5; legacy fixtures retain the old compatibility
    # behavior until migrated to aware event timestamps.
    evaluated = oof_counts > 0
    if temporal_contract:
        require_complete_oof_coverage(oof_counts, np.ones(n_samples, dtype=bool))
        oof_probabilities = np.full(n_samples, np.nan, dtype=np.float64)
    else:
        oof_probabilities = np.full(n_samples, 0.5, dtype=np.float64)
    oof_probabilities[evaluated] = oof_probs_sum[evaluated] / oof_counts[evaluated]

    mean_auc = float(np.mean(split_aucs)) if split_aucs else 0.50
    std_auc = float(np.std(split_aucs)) if split_aucs else 0.0
    min_auc = float(np.min(split_aucs)) if split_aucs else 0.50
    max_auc = float(np.max(split_aucs)) if split_aucs else 0.50
    # Raw-score mean squared error is descriptive only; it is not a calibration metric.
    finite_scores = np.isfinite(oof_probabilities)
    score_mse = float(np.mean((y[finite_scores] - oof_probabilities[finite_scores]) ** 2))
    baseline_wr = float(np.mean(y)) if len(y) > 0 else 0.0

    acted_mask = oof_probabilities >= conviction_threshold
    if np.sum(acted_mask) >= 10:
        filtered_wr = float(np.mean(y[acted_mask]))
        prec = float(precision_score(y, acted_mask, zero_division=0))
        rec = float(recall_score(y, acted_mask, zero_division=0))
        f1 = float(f1_score(y, acted_mask, zero_division=0))
    else:
        filtered_wr = baseline_wr
        prec = baseline_wr
        rec = 0.0
        f1 = 0.0

    # Fit the final model on all development data for descriptive inference only.
    final_clf = lgb.LGBMClassifier(**lgb_params)
    if temporal_contract:
        development_uniqueness = fold_uniqueness_weights(
            events, np.arange(n_samples, dtype=int)
        )
        final_weights = development_uniqueness * weights
    else:
        final_weights = weights
    final_clf.fit(X, y, sample_weight=final_weights)

    # Feature importances
    imp_vals = final_clf.feature_importances_
    feat_imp = {feat_names[i]: float(imp_vals[i]) for i in range(len(feat_names))}

    # TreeSHAP is diagnostic-only and can be skipped for repeated inner
    # walk-forward fits. This does not change folds, scores, or the fitted model.
    shap_vals = None
    if compute_shap:
        try:
            explainer = shap.TreeExplainer(final_clf)
            shap_vals = explainer.shap_values(X)
            if isinstance(shap_vals, list) and len(shap_vals) == 2:
                shap_vals = shap_vals[1]  # positive class
        except Exception:
            shap_vals = None

    passed_gate = bool(mean_auc >= 0.52 and filtered_wr >= baseline_wr)

    return MetaModelResult(
        model=final_clf,
        oof_probabilities=oof_probabilities,
        feature_names=feat_names,
        feature_importances=feat_imp,
        shap_values=shap_vals,
        mean_auc=mean_auc,
        brier_score=None,
        baseline_win_rate=baseline_wr,
        filtered_win_rate=filtered_wr,
        precision=prec,
        recall=rec,
        f1_score=f1,
        passed_quality_gate=passed_gate,
        score_semantics="raw_model_score",
        oof_coverage=oof_counts,
        oof_score_mse=score_mse,
        fold_diagnostics=fold_diagnostics,
        std_auc=std_auc,
        min_auc=min_auc,
        max_auc=max_auc,
    )

