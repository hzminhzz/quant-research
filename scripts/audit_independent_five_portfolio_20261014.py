"""Independent integrity audit of the 5-sleeve correlation and portfolio analysis."""
from __future__ import annotations
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.analyze_independent_five_portfolio_20261014 import (
    CASES, TRAIN_END, OUT, inverse_vol_between_market_groups,
    inverse_vol_group_weights,
)


def main():
    raw = pd.read_csv(OUT/"aligned_net_returns_business_days.csv",
                      index_col="date",parse_dates=["date"])
    assert list(raw.columns) == list(CASES)
    assert raw.shape[0] == 1768
    assert raw.index.is_unique and raw.index.is_monotonic_increasing
    assert not raw.isnull().any().any() and np.isfinite(raw.to_numpy()).all()
    assert raw.index.min().strftime("%Y-%m-%d") == "2020-01-01"
    assert raw.index.max().strftime("%Y-%m-%d") == "2026-10-09"
    assert (raw.index >= pd.Timestamp("2026-10-12",tz="UTC")).sum() == 0
    correlations = pd.read_csv(OUT/"correlation_business_days.csv",index_col=0)
    expect=raw.corr()
    assert np.allclose(correlations.to_numpy(),expect.to_numpy(),atol=1e-13)
    assert np.allclose(np.diag(correlations),np.ones(len(CASES)))
    assert np.allclose(correlations,correlations.T)
    ccal = pd.read_csv(OUT/"correlation_calendar_days.csv",index_col=0)
    # Weekend treatment is a small but explicit sensitivity.
    assert abs(ccal.loc["pivot-breakout-btc","donchian-btc"] -
               correlations.loc["pivot-breakout-btc","donchian-btc"]) < 0.05
    w=pd.read_csv(OUT/"allocations.csv",index_col="strategy")
    combos=pd.read_csv(OUT/"portfolio_daily_returns.csv",index_col="date")
    assert set(w.index)==set(CASES)
    assert all(abs(w[col].sum()-1.0)<1e-9 for col in w.columns)
    for name in w.columns:
        assert np.allclose(combos[name],raw.dot(w[name]),atol=1e-13)
    train=raw.loc[raw.index<TRAIN_END]
    assert np.allclose(
        w["market_bucket_inverse_vol_train2020_2022"],
        inverse_vol_group_weights(train),atol=1e-13)
    assert np.allclose(
        w["market_group_equal_risk_train2020_2022"],
        inverse_vol_between_market_groups(train),atol=1e-13)
    for name in w.columns:
        if name!="rsi_only_reference":
            assert w[name].max()<=.35+1e-12
    report=json.loads((OUT/"summary.json").read_text())
    assert report["status"]=="EXPLORATORY_COMPLETE"
    assert len(report["pair_diagnostics"]["pairs"]) == 10
    for k,v in report["portfolios"].items():
        assert abs(sum(v["risk_contribution_full"].values())-1.0)<1e-9
        assert len(v["daily_rebalanced"])==len(v["static_capital"])==4
        for mode in ("daily_rebalanced","static_capital"):
            m=v[mode]["full_common"]
            assert -1.0 <= m["max_drawdown"]<=0
            assert m["annual_volatility"]>0
            assert m["days"]==raw.shape[0]
            assert math.isfinite(m["sharpe_ratio"])
    stress = json.loads((OUT/"portfolio_cost_stress.json").read_text())
    assert len(stress["source_native_trials"]) == 10
    assert set(stress["portfolios"]) == {"2x","3x"}
    for trial in stress["source_native_trials"]:
        assert trial["case"] in CASES
        assert trial["cost_multiple"] in (2,3)
        assert trial["native_rejections"] == 0
    for mult in ("2x","3x"):
        scenario = pd.read_csv(OUT/f"net_returns_{mult}_cost.csv",index_col="date")
        assert scenario.shape == raw.shape
        for name in ("equal_five","market_group_equal_risk_train2020_2022"):
            expected = scenario.dot(w[name])
            calc = stress["portfolios"][mult][name]["daily_rebalanced"]["full_common"]
            # PortfolioAnalysis reproduces stored native-risk summary.
            from scripts.analyze_independent_five_portfolio_20261014 import ml4t_metrics
            observed = ml4t_metrics(expected)
            for key in ("total_return","sharpe_ratio","max_drawdown","cvar_95"):
                assert np.isclose(observed[key],calc[key],atol=1e-12)
    proof={
        "status":"PASS",
        "checks":[
            "five source return series on common observed calendar",
            "2026-10-12+ protected cutoff preserved",
            "correlation matrix reproduces directly from stored net returns",
            "BTC weekend UTC versus business calendar sensitivity disclosed",
            "all fixed weights sum to one and remain capped",
            "2020-2022-only inverse-vol weights independently reproduced",
            "daily portfolio return identity holds for all variants",
            "risk contributions reconcile to 100 percent",
            "native ML4T diagnostic summary metrics finite and complete",
            "ten native Engine stress outcomes and fixed-weight stressed portfolios reconcile",
        ],
        "limits":[
            "NOT an independent source execution audit",
            "NOT an actual broker-level merged portfolio backtest",
            "NOT a cost-calibrated rebalance or funding accounting test",
            "NOT an untouched holdout or strategy promotion",
        ],
    }
    (OUT/"audit.json").write_text(json.dumps(proof,indent=2)+"\n")
    print(json.dumps(proof,indent=2))


if __name__=="__main__":
    main()
