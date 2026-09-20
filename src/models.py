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
