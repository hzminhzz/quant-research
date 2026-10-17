"""Audit bi-weekly fresh account cohorts under retail prop firm costs."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml4t.backtest import Engine, DataFeed, BacktestConfig
from ml4t.backtest.config import ShareType, CommissionType, SlippageType
from scripts.run_independent_first_passage_trials import prepare_dual_timeframe_dataset, FirstPassageChallengeStrategy, INITIAL_BALANCE

OUT_DIR = Path("run_log/prop_firm_evaluation")
OUT_DIR.mkdir(parents=True, exist_ok=True)

df = prepare_dual_timeframe_dataset()
prices_df = df.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
signals_df = df.select(["timestamp", "symbol", "roc_168h", "ema_120h", "is_hour_close"])

start_dt = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
end_dt = datetime(2026, 6, 15, 0, 0, tzinfo=timezone.utc)

start_dates = []
curr = start_dt
while curr <= end_dt:
    start_dates.append(curr)
    curr += timedelta(days=14)

print(f"Evaluating {len(start_dates)} bi-weekly fresh account cohorts under retail costs...")

audit_output = {}

for r_mult in [1.0, 0.5]:
    outcomes = {"PASSED": 0, "BREACHED_STATIC_FLOOR": 0, "BREACHED_DAILY": 0, "IN_PROGRESS": 0}
    days_to_pass = []
    cohort_records = []

    for s_date in start_dates:
        p_sub = prices_df.filter(pl.col("timestamp") >= s_date)
        s_sub = signals_df.filter(pl.col("timestamp") >= s_date)

        cfg = BacktestConfig(
            initial_cash=INITIAL_BALANCE,
            allow_short_selling=True,
            share_type=ShareType.FRACTIONAL,
            commission_type=CommissionType.PERCENTAGE,
            commission_rate=0.0010,  # 10 bps retail taker fee
            slippage_type=SlippageType.PERCENTAGE,
            slippage_rate=0.0005,    # 5 bps retail spread/slippage
        )
        strat = FirstPassageChallengeStrategy(risk_mult=r_mult, daily_flatten_pct=0.03 if r_mult == 1.0 else 0.025)
        try:
            Engine(DataFeed(prices_df=p_sub, signals_df=s_sub), strat, cfg).run()
            outcome = strat.outcome
        except StopIteration:
            outcome = strat.outcome

        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        d_taken = (strat.end_timestamp - s_date).total_seconds() / 86400.0 if strat.end_timestamp else None
        if outcome == "PASSED" and d_taken:
            days_to_pass.append(d_taken)

        cohort_records.append({
            "start_date": s_date.strftime("%Y-%m-%d"),
            "end_date": strat.end_timestamp.strftime("%Y-%m-%d") if strat.end_timestamp else None,
            "outcome": outcome,
            "days_taken": round(d_taken, 1) if d_taken else None,
            "lowest_equity": strat.lowest_equity,
            "final_equity": strat.final_equity,
        })

    total_starts = len(start_dates)
    completed = outcomes["PASSED"] + outcomes["BREACHED_STATIC_FLOOR"] + outcomes["BREACHED_DAILY"]

    min_pass_rate = outcomes["PASSED"] / total_starts * 100
    max_pass_rate = (outcomes["PASSED"] + outcomes["IN_PROGRESS"]) / total_starts * 100
    comp_pass_rate = outcomes["PASSED"] / completed * 100 if completed > 0 else 0.0

    p_hat = outcomes["PASSED"] / completed if completed > 0 else 0.0
    naive_se = np.sqrt(p_hat * (1 - p_hat) / completed) * 100 if completed > 0 else 0.0

    cost_per_pass = (total_starts * 100.0) / outcomes["PASSED"] if outcomes["PASSED"] > 0 else float("inf")

    print(f"\n--- SIZING: {r_mult:.2f}x RISK ---")
    print(f"Total Cohorts: {total_starts}")
    print(f"  Passed: {outcomes['PASSED']} | Breached Floor: {outcomes['BREACHED_STATIC_FLOOR']} | Breached Daily: {outcomes['BREACHED_DAILY']} | In Progress: {outcomes['IN_PROGRESS']}")
    print(f"  Completed Pass Rate: {comp_pass_rate:.1f}% (Naive i.i.d. SE: +/-{naive_se:.1f}%)")
    print(f"  All-Start Pass Rate Bounds: [{min_pass_rate:.1f}%, {max_pass_rate:.1f}%]")
    if days_to_pass:
        print(f"  Avg Days to Pass: {np.mean(days_to_pass):.1f} days")
    print(f"  Challenge Fee Cost per Observed Pass ($100 fee): ${cost_per_pass:,.2f}")

    audit_output[f"risk_{r_mult}"] = {
        "total_cohorts": total_starts,
        "outcomes": outcomes,
        "completed_pass_rate_pct": round(comp_pass_rate, 2),
        "naive_se_pct": round(naive_se, 2),
        "all_start_bounds_pct": [round(min_pass_rate, 2), round(max_pass_rate, 2)],
        "cost_per_pass_usd": round(cost_per_pass, 2) if cost_per_pass != float("inf") else None,
        "cohorts": cohort_records,
    }

with (OUT_DIR / "biweekly_cohort_audit_retail_costs.json").open("w") as f:
    json.dump(audit_output, f, indent=2)
