"""Preregistered monthly development-only ml4t-models linear allocation comparison.

This is a capital-allocation STAGE diagnostic on observed native NAV streams,
not a replacement for ml4t-backtest strategy execution or a broker fill simulation.
Dates >= 2025-01-01 are never opened. No model or hyperparameter search.
"""
from __future__ import annotations

import csv
import hashlib
import json

import numpy as np
from ml4t.diagnostic.api import PortfolioAnalysis
from ml4t.models import (
    LinearFeaturePortfolioModel,
    LinearPortfolioConfig,
    PortfolioAllocationPipeline,
    PortfolioSequenceBatch,
)
from ml4t.models.portfolio.postprocessors import normalize_cross_sectional_weights

from scripts.allocation_monthly_panel_20261014 import (
    IDS,
    OUT,
    SRC_B0,
    SRC_BTC,
    SRC_RSI,
    _eligible_calendar,
    _load_c3,
    _native_csv,
)

FEATURES = ("lag_1m_return", "lag_3m_return", "vol21_daily_obs", "vol63_daily_obs", "dd63_daily_obs")
PRIMARY_REBALANCE_COST_BPS = 10.0
OUTCOME_MONTH_FIRST = "2022-01"
OUTCOME_MONTH_END = "2024-12"


def _sources():
    return {
        IDS[0]: _native_csv(SRC_B0, "utc_day", "timestamp", "equity"),
        IDS[1]: _load_c3(),
        IDS[2]: _native_csv(SRC_BTC, "session_date", "native_session_label_utc", "funding_adjusted_equity_usdt"),
        IDS[3]: _native_csv(SRC_RSI, "timestamp", "timestamp", "equity"),
    }


def development_arrays():
    source = _sources()
    _, eligible, months = _eligible_calendar(source)
    dates = list(eligible)
    mdates = [d for _, d in months]
    if mdates[0][:7] != "2019-09" or mdates[-1][:7] != "2024-12" or len(months) != 64:
        raise ValueError("Development monthly completeness gate failed")
    if any(d >= "2025-01-01" for d in dates):
        raise ValueError("Holdout access detected")

    nav = np.asarray([[source[a][d].value for a in IDS] for d in dates], dtype=np.float64)
    if not np.all(np.isfinite(nav)) or np.any(nav <= 0):
        raise ValueError("Unusable strategy NAV")
    monthly_idx = [dates.index(d) for d in mdates]
    monthly_nav = nav[monthly_idx]
    month_returns = monthly_nav[1:] / monthly_nav[:-1] - 1.0
    monthly_features = np.full((len(mdates), len(IDS), len(FEATURES)), np.nan, dtype=np.float64)
    for mi, di in enumerate(monthly_idx):
        if mi >= 3 and di >= 63:
            daily_equity = nav[di - 63:di + 1]
            daily_returns = daily_equity[1:] / daily_equity[:-1] - 1
            monthly_features[mi, :, 0] = monthly_nav[mi] / monthly_nav[mi - 1] - 1
            monthly_features[mi, :, 1] = monthly_nav[mi] / monthly_nav[mi - 3] - 1
            monthly_features[mi, :, 2] = np.std(daily_returns[-21:], axis=0, ddof=1)
            monthly_features[mi, :, 3] = np.std(daily_returns, axis=0, ddof=1)
            monthly_features[mi, :, 4] = monthly_nav[mi] / np.max(daily_equity, axis=0) - 1
    valid = np.all(np.isfinite(monthly_features), axis=(1, 2))
    valid_indices = [i for i in range(len(mdates) - 1) if valid[i] and i >= 3]
    if len([i for i in valid_indices if mdates[i + 1][:7] < OUTCOME_MONTH_FIRST]) < 20:
        raise ValueError("Insufficient past completed monthly labels to fit")
    return dates, mdates, month_returns, monthly_features, monthly_idx, nav, valid_indices


def _train_batch(features: np.ndarray, outcome_returns: np.ndarray, train_indices: list[int]) -> PortfolioSequenceBatch:
    xs = features[train_indices]
    ys = outcome_returns[train_indices]
    if not np.all(np.isfinite(xs)) or not np.all(np.isfinite(ys)):
        raise ValueError("Training data incomplete")
    return PortfolioSequenceBatch(
        features=xs[np.newaxis, ...],
        returns=ys[np.newaxis, ...],
        asset_ids=IDS,
    )


def _model_weight(features: np.ndarray, labels: np.ndarray, i: int, valid_indices: list[int]) -> tuple[np.ndarray, int]:
    # Labels for training index j are NEXT month's strategy return. Require j+1 <= i.
    train = [j for j in valid_indices if j < i]
    if len(train) < 20:
        raise ValueError("Insufficient completed development monthly labels")
    pipeline = PortfolioAllocationPipeline(
        LinearFeaturePortfolioModel(LinearPortfolioConfig(
            ridge_alpha=0.0001,
            fit_intercept=True,
            gross_exposure=1.0,
            net_exposure=1.0,
            max_abs_weight=0.4,
            seed=42,
        ))
    )
    pipeline.fit(_train_batch(features, labels, train))
    batch = PortfolioSequenceBatch(features=features[i][None, None, :, :], asset_ids=IDS)
    output = pipeline.predict(batch).processed_weights.weights[0, 0, :].astype(float)
    if np.any(output < -1e-10) or np.any(output > 0.40000001) or abs(output.sum() - 1) > 1e-8:
        raise ValueError("ML4T returned infeasible long-only capital weights")
    return output, len(train)


def _inverse_vol_weight(features: np.ndarray, i: int) -> np.ndarray:
    vol = np.maximum(features[i, :, 3], 1e-6)
    scores = 1 / vol
    # Same installed constraint projector as ml4t-models learned allocator.
    result = normalize_cross_sectional_weights(
        scores.reshape((1, 1, len(IDS))), mask=np.ones((1, 1, len(IDS)), bool),
        gross_exposure=1.0, net_exposure=1.0, max_abs_weight=0.4
    )[0, 0, :]
    if not np.isclose(result.sum(), 1.0):
        raise ValueError("Inverse-vol comparator violated weights")
    return result


def _allocation_accounting(weights: np.ndarray, source_monthly_returns: np.ndarray, cost_multiplier: int):
    """Deterministic VECTOR allocation cash accounting. No strategy fill simulation."""
    if weights.shape != source_monthly_returns.shape or np.any(source_monthly_returns <= -1):
        raise ValueError("Unusable portfolio allocation panel")
    gross = np.sum(weights * source_monthly_returns, axis=1)
    prior_weights = np.vstack([np.zeros(weights.shape[1]), weights[:-1]])
    prior_rets = np.vstack([np.zeros(weights.shape[1]), source_monthly_returns[:-1]])
    prior_weighted = (prior_weights * (1 + prior_rets))
    prior_total = prior_weighted.sum(axis=1)
    pretrade = np.divide(prior_weighted, prior_total[:, None], out=np.zeros_like(prior_weighted),
                         where=prior_total[:, None] > 0)
    turnover = np.abs(weights - pretrade).sum(axis=1) / 2
    # Initial funding moves a complete unit of capital out of cash. The
    # risky-only L1/2 transfer formula applies only after that deployment.
    turnover[prior_total == 0] = np.abs(weights[prior_total == 0]).sum(axis=1)
    costs = turnover * (PRIMARY_REBALANCE_COST_BPS / 10000) * cost_multiplier
    net = (1 - costs) * (1 + gross) - 1
    return net, turnover, costs


def _metrics(returns: np.ndarray) -> dict:
    # Metrics through ml4t-diagnostic, configured for MONTHLY observations.
    analysis = PortfolioAnalysis(returns=np.asarray(returns), periods_per_year=12)
    stats = analysis.compute_summary_stats()
    summary = stats.summary()
    obj = dict(summary) if isinstance(summary, dict) else str(summary)
    return obj


def run():
    _, months, monthly_r, feats, _, _, valid = development_arrays()
    outputs = []
    for i in valid:
        next_month = months[i + 1][:7]
        if OUTCOME_MONTH_FIRST <= next_month <= OUTCOME_MONTH_END:
            weights, ntrain = _model_weight(feats, monthly_r, i, valid)
            outputs.append((i, next_month, weights, _inverse_vol_weight(feats, i), ntrain))
    if len(outputs) != 36 or outputs[0][1] != OUTCOME_MONTH_FIRST or outputs[-1][1] != OUTCOME_MONTH_END:
        raise ValueError("Development walk-forward cohort does not contain 36 months")
    idxs = np.array([o[0] for o in outputs], dtype=int)
    realized = monthly_r[idxs]
    model_w = np.asarray([o[2] for o in outputs])
    vol_w = np.asarray([o[3] for o in outputs])
    equal_w = np.full_like(model_w, 0.25)
    strategies = {"cash": np.zeros_like(equal_w), "equal_weight": equal_w,
                  "inverse_vol": vol_w, "ml4t_linear": model_w}
    results = {}
    rows = []
    for name, w in strategies.items():
        results[name] = {}
        for multiplier in (1, 2, 3):
            # Cash should not incur allocation-switch costs.
            net, turnover, costs = _allocation_accounting(w, realized, multiplier)
            if name == "cash":
                net[:] = 0
                turnover[:] = 0
                costs[:] = 0
            results[name][str(multiplier)] = {
                "metrics": _metrics(net),
                "compound_return": float(np.prod(1 + net) - 1),
                "average_one_way_monthly_turnover": float(np.mean(turnover)),
                "total_cost_fraction_of_monthly_nav": float(np.sum(costs)),
            }
            for k, item in enumerate(outputs):
                row = {
                    "period": item[1], "decision_common_session_date": months[item[0]],
                    "next_return_month": item[1],
                    "trial": name, "cost_multiplier": multiplier,
                    "model_training_label_count": item[4] if name == "ml4t_linear" else "",
                    "portfolio_return_net": float(net[k]), "strategy_return_gross": float(np.dot(w[k], realized[k])),
                    "one_way_turnover": float(turnover[k]), "allocation_cost_fraction": float(costs[k]),
                }
                for j, asset in enumerate(IDS):
                    row[f"weight_{asset}"] = float(w[k, j])
                rows.append(row)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "allocation_stage_dev_monthly_trials.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "classification": "EXPLORATORY DEVELOPMENT ONLY; NOT APPROVED",
        "source_months": len(months),
        "model_trial": "LinearFeaturePortfolioModel v0 fixed ridge_alpha=1e-4 gross=net=1 cap=40%",
        "train_scope": "completed labels strictly before each monthly prediction",
        "development_evaluation": "2022-01 through 2024-12",
        "eval_months": len(outputs),
        "locked_2025_2026_opened": False,
        "cost_base_one_way_bps": PRIMARY_REBALANCE_COST_BPS,
        "feature_names": FEATURES,
        "strategy_ids": IDS,
        "sample_first_model_train_labels": outputs[0][4],
        "sample_last_model_train_labels": outputs[-1][4],
        "outcomes": results,
        "input_identity_sha256": hashlib.sha256((OUT / "monthly_observed_panel.csv").read_bytes()).hexdigest(),
        "trial_count": 1,
        "limitations": [
            "Monthly capital-transfer accounting, not fills of broker CFD/perp positions.",
            "Weights assumed to become effective at monthly observed equity marks; delayed executable allocation not modeled.",
            "USDT to USD treated as unit parity; native leverage/sizing paths unchanged.",
            "C3 and B0 bid-CFD financing/spread and B0 stop/OCO differences remain unqualified.",
            "2025–2026 already observed for strategy selection, locked as allocator retrospective check."
        ],
    }
    (OUT / "allocation_stage_dev_report.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n")
    return manifest


if __name__ == "__main__":
    result = run()
    print(json.dumps({k: v for k, v in result.items() if k != "outcomes"}, indent=2))
    print(json.dumps(result["outcomes"], indent=2)[:14000])
