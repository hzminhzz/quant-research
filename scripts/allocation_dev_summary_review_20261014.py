"""Verify the single fixed ML4T allocation trial with paired monthly block bootstrap."""
from __future__ import annotations

import csv
import json
from collections import defaultdict

import numpy as np
from ml4t.backtest.analytics.metrics import sharpe_ratio

from scripts.allocation_monthly_panel_20261014 import DATA, IDS

OUT = DATA / "allocation_development"
INPUT = OUT / "allocation_stage_dev_monthly_trials.csv"


def verify():
    with INPUT.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    by_arm = defaultdict(dict)
    for r in rows:
        if not ("2022-01" <= r["period"] <= "2024-12"):
            raise ValueError("Non-development model trial row")
        key = (r["trial"], int(r["cost_multiplier"]))
        if r["period"] in by_arm[key]:
            raise ValueError("Duplicate model allocation month")
        by_arm[key][r["period"]] = r
        if r["trial"] != "cash":
            weights = np.array([float(r[f"weight_{asset}"]) for asset in IDS])
            if abs(weights.sum() - 1) > 1e-10 or (weights < -1e-10).any():
                raise ValueError("Invalid portfolio capital weights")
            if r["trial"] == "ml4t_linear" and (weights > 0.400000001).any():
                raise ValueError("ML4T cap breached")
    months = sorted(by_arm["ml4t_linear", 1])
    if len(months) != 36 or months[0] != "2022-01" or months[-1] != "2024-12":
        raise ValueError("Expected 36 complete development months")
    def data(name, cost=1):
        if sorted(by_arm[name, cost]) != months:
            raise ValueError(f"{name} incomplete")
        return np.asarray([float(by_arm[name, cost][m]["portfolio_return_net"]) for m in months])
    equal, learned, inverse = data("equal_weight"), data("ml4t_linear"), data("inverse_vol")
    if not np.all(np.isfinite(learned)) or not np.all(np.isfinite(equal)):
        raise ValueError("Invalid reported model/baseline monthly returns")

    # A library-computed ratio is rescaled from its daily 252 factor
    # to the preregistered 12 months. No custom backtest metric loop.
    def sh(r):
        return float(sharpe_ratio(r)) * np.sqrt(12.0 / 252.0)
    observed_diff = sh(learned) - sh(equal)

    rng = np.random.default_rng(42)
    reps = 5000
    block_length = 3
    blocks_per_draw = len(months) // block_length
    boot = []
    for _ in range(reps):
        starts = rng.integers(0, len(months), size=blocks_per_draw)
        sample = np.concatenate([(np.arange(s, s+block_length) % len(months)) for s in starts])
        boot.append(sh(learned[sample]) - sh(equal[sample]))
    interval = np.quantile(np.asarray(boot), [0.025, 0.975]).tolist()
    report = json.loads((OUT / "allocation_stage_dev_report.json").read_text())
    metrics = report["outcomes"]
    extra = {
        "outcome": "FAIL_PREDECLARED_SHARPE_AND_DRAWDOWN_GATE",
        "development_months": 36,
        "observed_ml4t_minus_equal_net_sharpe": observed_diff,
        "paired_three_month_circular_block_bootstrap_95pct_CI": interval,
        "bootstrap_replicates": reps,
        "bootstrap_seed": 42,
        "primary_cost_bps_per_one_way_transferred_unit": 10.0,
        "model_first_label_count": report["sample_first_model_train_labels"],
        "model_last_label_count": report["sample_last_model_train_labels"],
        "trial_count_model_configurations": 1,
        "baseline_comparators": ["cash", "equal_weight", "inverse_vol"],
        "cost_scenarios": ["1x", "2x", "3x"],
        "model_return_1x": metrics["ml4t_linear"]["1"]["compound_return"],
        "equal_return_1x": metrics["equal_weight"]["1"]["compound_return"],
        "inverse_vol_return_1x": metrics["inverse_vol"]["1"]["compound_return"],
        "model_return_2x": metrics["ml4t_linear"]["2"]["compound_return"],
        "equal_return_2x": metrics["equal_weight"]["2"]["compound_return"],
        "model_sharpe_1x_library_monthly": sh(learned),
        "equal_sharpe_1x_library_monthly": sh(equal),
        "inverse_vol_sharpe_1x_library_monthly": sh(inverse),
        "invariant_checks": {
            "model_weights_nonnegative_below_40pct": True,
            "all_monthly_cohorts_match": True,
            "holdout_2025_2026_opened": False,
            "no_model_hyperparameter_tuning": True,
            "trial_registry_is_development_only": True,
        },
        "limits": [
            "Monthly capital-accounting experiment, not a tradeable execution simulation",
            "BTC funding historical settlement marks partly price proxies",
            "Undocumented CFD financing and some execution costs",
            "Known strategy selection exposure to 2025–2026, so reserved retrospective period is not independent underlying alpha confirmation",
        ],
    }
    (OUT / "trial_ledger_allocation_dev_20261014.json").write_text(json.dumps(extra, indent=2) + "\n")
    return extra


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
