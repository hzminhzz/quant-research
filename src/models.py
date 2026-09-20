"""Machine Learning Meta-Labeling & Combinatorial Purged Cross-Validation.

Governed by ML4T Skills:
- ml4t-cpcv (Combinatorial Purged CV)
- ml4t-purging-embargo
- ml4t-meta-labels

Implements Marcos López de Prado's two-stage meta-labeling architecture:
Stage 1 (Primary Model/Rule): Determines trade direction (+1 / -1) and entry timing.
Stage 2 (Meta-Model): Predicts P(profitable) to filter false positives and size bets.
Validation: Combinatorial Purged CV generates a distribution of backtest paths
without temporal leakage or lookahead contamination.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import polars as pl
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score

from ml4t.diagnostic.splitters import CombinatorialCV


@dataclass(frozen=True)
class CPCVResult:
    """Evaluation summary from Combinatorial Purged Cross-Validation."""
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
        Minimum meta-model probability to take the trade.
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
    """Evaluation summary for LightGBM Meta-Classifier trained with CPCV."""
    model: Any
    oof_probabilities: np.ndarray
    feature_names: List[str]
    feature_importances: Dict[str, float]
    shap_values: Optional[np.ndarray]
    mean_auc: float
    brier_score: float
    baseline_win_rate: float
    filtered_win_rate: float
    precision: float
    recall: float
    f1_score: float
    passed_quality_gate: bool


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
        Probability cutoff p_hat >= threshold to take the trade.
    use_monotonic_constraints : bool, default True
        Enforce economically rational sign constraints on trees:
        - rvol_1h: +1 (Higher volume -> higher breakout follow-through)
        - range_to_atr20: -1 (Over-expanded range -> mean reversion / exhaustion)
        - wick_upper_ratio (for long): -1 (Upper rejection shadow -> failed breakout)
    sample_weights : np.ndarray, optional
        Sample uniqueness weights w_i = u_i * |r_i| to neutralize concurrency clustering.
    """
    import lightgbm as lgb
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.metrics import brier_score_loss, f1_score
    import shap

    if not events:
        raise ValueError("Cannot train meta-classifier on empty event list.")

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


    # CPCV Splitter
    cv = CombinatorialCV(
        n_groups=n_groups,
        n_test_groups=n_test_groups,
        embargo_size=embargo_size,
    )

    oof_probs_sum = np.zeros(n_samples, dtype=np.float64)
    oof_counts = np.zeros(n_samples, dtype=np.int32)
    split_aucs = []

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
    for train_idx, test_idx in cv.split(X):
        if len(train_idx) < 30 or len(test_idx) < 5:
            continue

        X_tr, y_tr, w_tr = X[train_idx], y[train_idx], weights[train_idx]
        X_te, y_te = X[test_idx], y[test_idx]

        if len(np.unique(y_tr)) < 2:
            continue

        clf = lgb.LGBMClassifier(**lgb_params)
        clf.fit(X_tr, y_tr, sample_weight=w_tr)

        preds = clf.predict_proba(X_te)[:, 1]
        oof_probs_sum[test_idx] += preds
        oof_counts[test_idx] += 1

        if len(np.unique(y_te)) == 2:
            split_aucs.append(roc_auc_score(y_te, preds))

    # Average OOF probabilities
    evaluated = oof_counts > 0
    oof_probabilities = np.full(n_samples, 0.5, dtype=np.float64)
    oof_probabilities[evaluated] = oof_probs_sum[evaluated] / oof_counts[evaluated]

    # Metrics evaluation
    mean_auc = float(np.mean(split_aucs)) if split_aucs else 0.50
    brier = float(brier_score_loss(y, oof_probabilities))
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

    # Fit final calibrated model on all data for live inference
    final_clf = lgb.LGBMClassifier(**lgb_params)
    final_clf.fit(X, y, sample_weight=weights)

    # Feature importances
    imp_vals = final_clf.feature_importances_
    feat_imp = {feat_names[i]: float(imp_vals[i]) for i in range(len(feat_names))}

    # TreeSHAP values
    shap_vals = None
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
        brier_score=brier,
        baseline_win_rate=baseline_wr,
        filtered_win_rate=filtered_wr,
        precision=prec,
        recall=rec,
        f1_score=f1,
        passed_quality_gate=passed_gate,
    )

