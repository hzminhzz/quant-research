"""Cross-sectional ranking model wrappers with a single fit/predict contract.

All wrappers ingest a long-format feature matrix `X` (rows = date × symbol),
a target `y` (per-row scalar; typically `fwd_rank_21d`), and a matching `dates`
series. They emit scalar scores at predict time — higher = more attractive
(long leg).

Unification matters because the walk-forward runner, the IC evaluator, and
the future backtest layer should not care which model produced the scores.
"""
from __future__ import annotations

from dataclasses import dataclass

import lightgbm as lgb
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.linear_model import Lasso, Ridge

# ---------------------------------------------------------------------------
# cross-sectional z-score (shared helper)
# ---------------------------------------------------------------------------

def cs_zscore(X: pd.DataFrame, dates: pd.Series) -> pd.DataFrame:
    """Per-date cross-sectional z-score. Rows with all-same-value day fall to 0."""
    cols = X.columns.tolist()
    df = X.copy()
    df["_d"] = pd.to_datetime(dates).values
    grp = df.groupby("_d")[cols]
    means = grp.transform("mean")
    stds = grp.transform("std").replace(0, np.nan)
    z = (X.reset_index(drop=True) - means.reset_index(drop=True)) / stds.reset_index(
        drop=True
    )
    z.index = X.index
    return z


def _decile_labels(y: pd.Series, dates: pd.Series, n_bins: int = 10) -> pd.Series:
    """Convert continuous target to integer relevance labels 0..n_bins-1 per date.

    Used by rank-based boosters (LGBMRanker, XGBRanker) which require ordinal
    labels plus a per-group structure.
    """
    def _bin(s: pd.Series) -> pd.Series:
        if s.notna().sum() < n_bins:
            return pd.Series(np.nan, index=s.index)
        return pd.qcut(s, n_bins, labels=False, duplicates="drop").astype("float")

    df = pd.DataFrame({"y": y.values, "d": pd.to_datetime(dates).values}, index=y.index)
    labels = df.groupby("d", sort=False)["y"].transform(_bin)
    return labels


# ---------------------------------------------------------------------------
# base contract
# ---------------------------------------------------------------------------

class BaseRanker:
    name: str = "base"

    def fit(self, X: pd.DataFrame, y: pd.Series, dates: pd.Series) -> "BaseRanker":
        raise NotImplementedError

    def predict(self, X: pd.DataFrame, dates: pd.Series) -> np.ndarray:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# linear baselines
# ---------------------------------------------------------------------------

@dataclass
class LinearRanker(BaseRanker):
    kind: str = "ridge"   # "ridge" | "lasso"
    alpha: float = 1.0

    def __post_init__(self):
        self.name = f"linear_{self.kind}"
        self.model = Ridge(alpha=self.alpha) if self.kind == "ridge" else Lasso(
            alpha=self.alpha, max_iter=5000
        )

    def fit(self, X, y, dates):
        Xz = cs_zscore(X, dates)
        mask = Xz.notna().all(axis=1) & y.notna()
        self.model.fit(Xz.loc[mask].values, y.loc[mask].values)
        return self

    def predict(self, X, dates):
        Xz = cs_zscore(X, dates).fillna(0.0)   # 0 = per-date mean
        return self.model.predict(Xz.values)


# ---------------------------------------------------------------------------
# LightGBM ranker
# ---------------------------------------------------------------------------

@dataclass
class LGBMRankerModel(BaseRanker):
    n_estimators: int = 400
    num_leaves: int = 31
    learning_rate: float = 0.05
    min_child_samples: int = 50
    n_bins: int = 10
    random_state: int = 42
    name: str = "lgbm_ranker"

    def __post_init__(self):
        self.model = lgb.LGBMRanker(
            n_estimators=self.n_estimators,
            num_leaves=self.num_leaves,
            learning_rate=self.learning_rate,
            min_child_samples=self.min_child_samples,
            random_state=self.random_state,
            verbose=-1,
        )

    def fit(self, X, y, dates):
        d = pd.to_datetime(dates)
        labels = _decile_labels(y, d, n_bins=self.n_bins)
        # require at least half the features to be present — any(axis=1) would
        # admit rows with a single non-NaN feature, which are near-useless for
        # a cross-sectional ranker and add noise to the pairwise objective.
        min_feats = max(1, X.shape[1] // 2)
        mask = (X.notna().sum(axis=1) >= min_feats) & labels.notna()
        # rank boosters need rows sorted by group, with contiguous groups
        order = np.argsort(d[mask].values, kind="mergesort")
        Xs = X.loc[mask].iloc[order]
        ys = labels.loc[mask].iloc[order].astype(int).values
        ds = d[mask].iloc[order].values
        group_sizes = pd.Series(ds).groupby(pd.Series(ds), sort=False).size().values
        self.model.fit(Xs.values, ys, group=group_sizes)
        return self

    def predict(self, X, dates):
        return self.model.predict(X.values)


# ---------------------------------------------------------------------------
# XGBoost ranker
# ---------------------------------------------------------------------------

@dataclass
class XGBRankerModel(BaseRanker):
    n_estimators: int = 400
    max_depth: int = 5
    learning_rate: float = 0.05
    n_bins: int = 10
    random_state: int = 42
    name: str = "xgb_ranker"

    def __post_init__(self):
        self.model = xgb.XGBRanker(
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            learning_rate=self.learning_rate,
            objective="rank:pairwise",
            tree_method="hist",
            random_state=self.random_state,
            verbosity=0,
        )

    def fit(self, X, y, dates):
        d = pd.to_datetime(dates)
        labels = _decile_labels(y, d, n_bins=self.n_bins)
        min_feats = max(1, X.shape[1] // 2)
        mask = (X.notna().sum(axis=1) >= min_feats) & labels.notna()
        order = np.argsort(d[mask].values, kind="mergesort")
        Xs = X.loc[mask].iloc[order]
        ys = labels.loc[mask].iloc[order].astype(int).values
        ds = d[mask].iloc[order].values
        group_sizes = pd.Series(ds).groupby(pd.Series(ds), sort=False).size().values
        self.model.fit(Xs.values, ys, group=group_sizes)
        return self

    def predict(self, X, dates):
        return self.model.predict(X.values)


# ---------------------------------------------------------------------------
# naive equal-weight baseline
# ---------------------------------------------------------------------------

@dataclass
class EqualWeightBaseline(BaseRanker):
    """Equal-weight sum of z-scored classic signals — the "can the ML model
    beat handmade?" yardstick.

    The default picks up the features that had positive IC-IR in
    01_feature_eda. `signs` lets callers invert a feature (e.g. use
    +low_vol_60 but -vol_20d) without forking the class.
    """
    features: tuple[str, ...] = ("size_adv_60", "vol_60d", "reversal_1w")
    signs: tuple[float, ...] | None = None
    name: str = "naive_ew"

    def __post_init__(self):
        if self.signs is None:
            self.signs = tuple(1.0 for _ in self.features)
        elif len(self.signs) != len(self.features):
            raise ValueError(
                f"signs length {len(self.signs)} != features length {len(self.features)}"
            )

    def fit(self, X, y, dates):
        return self

    def predict(self, X, dates):
        sub = X[list(self.features)]
        z = cs_zscore(sub, dates).fillna(0.0)
        signed = z.values * np.asarray(self.signs, dtype=float)
        return signed.sum(axis=1)
