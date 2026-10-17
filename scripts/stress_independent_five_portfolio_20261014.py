"""Cost sensitivity of two multi-strategy return overlays.

Every stressed sleeve is re-executed with ml4t.backtest.Engine and
unchanged frozen price/signal inputs; portfolios remain analytical
aggregations with NO extra cross-sleeve rebalance costs.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import polars as pl
from ml4t.backtest import Engine, DataFeed

from scripts.run_independent_seven_2020_2022 import CASES, _config
from scripts.stress_independent_five_full_history_20261014 import new_strategy
from scripts.analyze_independent_five_portfolio_20261014 import (
    ROOT, OUT, CASES as CASES_FIVE, START,
    align_business_days, window_metrics,
    portfolio_daily_rebalanced, portfolio_static_initial_capital,
)

CHOSEN = ("equal_five", "market_group_equal_risk_train2020_2022")


def run():
    baseline = json.loads((OUT/"summary.json").read_text())
    out = {"status":"EXPLORATORY_POST_OBSERVATION_COST_STRESS",
           "scope":"native ML4T per-strategy stress, analytical portfolio overlay",
           "scenario_weights":"frozen from original base-cost 2020-2022 training",
           "portfolios":{},"source_native_trials":[]}
    for multiple in (2,3):
        stressed = {}
        for name in CASES_FIVE:
            source = ROOT / name
            meta = json.loads((source/"summary.json").read_text())
            for p in ("prices.parquet","signals.parquet"):
                assert hashlib.sha256((source/p).read_bytes()).hexdigest() == (
                    meta["artifact_sha256"][p])
            prices = pl.read_parquet(source/"prices.parquet")
            signals = pl.read_parquet(source/"signals.parquet")
            asset, fee, slip = CASES[name]
            cfg = _config(fee*multiple, slip*multiple,
                          leverage=(name=="donchian-btc"))
            result = Engine(
                DataFeed(prices_df=prices,signals_df=signals),
                new_strategy(name),cfg,
            ).run()
            if result.metrics["num_rejected_orders"]:
                raise ValueError(f"{name} stress: rejected orders")
            frame = result.to_equity_dataframe().to_pandas()
            idx = pd.DatetimeIndex(pd.to_datetime(frame["timestamp"],utc=True))
            series = pd.Series(frame["equity"].to_numpy(dtype=float),index=idx)
            stressed[name] = series.pct_change().fillna(0.0).rename(name)
            assert abs(series.iloc[-1]-result.metrics["final_value"]) < .001
            out["source_native_trials"].append({
                "case":name, "cost_multiple":multiple,
                "native_net_return_pct":result.metrics["total_return_pct"],
                "native_fills":result.metrics["num_fills"],
                "native_rejections":result.metrics["num_rejected_orders"],
            })
        aligned = align_business_days(stressed, start=START)
        assert len(aligned) == baseline["days"]
        label = f"{multiple}x"
        (OUT/f"net_returns_{label}_cost.csv").write_text(
            aligned.to_csv(index_label="date"))
        out["portfolios"][label] = {}
        for portfolio in CHOSEN:
            weights = pd.Series(baseline["portfolios"][portfolio]["weights"])
            portfolio_results={}
            for mode,fn in (
                ("daily_rebalanced",portfolio_daily_rebalanced),
                ("static_capital",portfolio_static_initial_capital),
            ):
                r=fn(aligned,weights)
                portfolio_results[mode]=window_metrics(r)
            out["portfolios"][label][portfolio]=portfolio_results
            score=portfolio_results["daily_rebalanced"]["full_common"]
            print(f"{label} {portfolio} net={score['total_return']:.4f} "
                  f"sharpe={score['sharpe_ratio']:.3f} "
                  f"mdd={score['max_drawdown']:.3f}", flush=True)
    (OUT/"portfolio_cost_stress.json").write_text(
        json.dumps(out,indent=2,allow_nan=False)+"\n")
    print("DONE native sleeve cost trials",len(out["source_native_trials"]))

if __name__=="__main__":
    run()
