"""Monthly Cohort Audit: Fresh Account First-Passage Trials under Retail Prop Firm Costs.

Stratified by calendar month (17 monthly cohorts from Jan 2025 to May 2026).
Evaluates point-in-time point-in-time signals with 10 bps retail commission + 5 bps slippage.
Reports all-start bounds, naive iid standard error, and cost per pass ($100 challenge fee).
"""

from datetime import datetime, timezone
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
from scripts.run_verified_dual_timeframe_audit import prepare_dual_timeframe_dataset
from scripts.run_independent_first_passage_trials import FirstPassageChallengeStrategy, INITIAL_BALANCE

OUT_DIR = Path("run_log/prop_firm_evaluation")
OUT_DIR.mkdir(parents=True, exist_ok=True)

df = prepare_dual_timeframe_dataset()
prices_df = df.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
signals_df = df.select(["timestamp", "symbol", "roc_168h", "ema_120h", "is_hour_close"])

# Monthly cohorts: 1st of every month from 2025-01-01 to 2026-05-01 (17 cohorts)
cohort_dates = [
    datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc),
    datetime(2025, 2, 1, 0, 0, tzinfo=timezone.utc),
    datetime(2025, 3, 1, 0, 0, tzinfo=timezone.utc),
    datetime(2025, 4, 1, 0, 0, tzinfo=timezone.utc),
    datetime(2025, 5, 1, 0, 0, tzinfo=timezone.utc),
    datetime(2025, 6, 1, 0, 0, tzinfo=timezone.utc),
    datetime(2025, 7, 1, 0, 0, tzinfo=timezone.utc),
    datetime(2025, 8, 1, 0, 0, tzinfo=timezone.utc),
    datetime(2025, 9, 1, 0, 0, tzinfo=timezone.utc),
    datetime(2025, 10, 1, 0, 0, tzinfo=timezone.utc),
    datetime(2025, 11, 1, 0, 0, tzinfo=timezone.utc),
    datetime(2025, 12, 1, 0, 0, tzinfo=timezone.utc),
    datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
    datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc),
    datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc),
    datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc),
    datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc),
]

print(f"Running monthly cohort audit across {len(cohort_dates)} cohorts...")

audit_output = {}

for r_mult in [1.0, 0.5]:
    outcomes = {"PASSED": 0, "BREACHED_STATIC_FLOOR": 0, "BREACHED_DAILY": 0, "IN_PROGRESS": 0}
    days_to_pass = []
    cohort_records = []

    for s_date in cohort_dates:
        p_sub = prices_df.filter(pl.col("timestamp") >= s_date)
        s_sub = signals_df.filter(pl.col("timestamp") >= s_date)

        cfg = BacktestConfig(
            initial_cash=INITIAL_BALANCE,
            allow_short_selling=True,
            share_type=ShareType.FRACTIONAL,
            commission_type=CommissionType.PERCENTAGE,
            commission_rate=0.0010,  # 10 bps retail
            slippage_type=SlippageType.PERCENTAGE,
            slippage_rate=0.0005,    # 5 bps retail
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
            "lowest_equity": round(strat.lowest_equity, 2),
            "final_equity": round(strat.final_equity, 2),
        })

    total_starts = len(cohort_dates)
    completed = outcomes["PASSED"] + outcomes["BREACHED_STATIC_FLOOR"] + outcomes["BREACHED_DAILY"]

    min_pass_rate = outcomes["PASSED"] / total_starts * 100
    max_pass_rate = (outcomes["PASSED"] + outcomes["IN_PROGRESS"]) / total_starts * 100
    comp_pass_rate = outcomes["PASSED"] / completed * 100 if completed > 0 else 0.0

    p_hat = outcomes["PASSED"] / completed if completed > 0 else 0.0
    naive_se = np.sqrt(p_hat * (1.0 - p_hat) / completed) * 100 if completed > 0 else 0.0

    cost_per_pass = (total_starts * 100.0) / outcomes["PASSED"] if outcomes["PASSED"] > 0 else float("inf")

    print(f"\n=======================================================")
    print(f"=== SIZING: {r_mult:.2f}x RISK (Retail Prop Firm Costs) ===")
    print(f"=======================================================")
    print(f"Total Cohorts Evaluated:    {total_starts}")
    print(f"  - Successfully PASSED:    {outcomes['PASSED']}")
    print(f"  - Breached Static Floor:  {outcomes['BREACHED_STATIC_FLOOR']}")
    print(f"  - Breached Daily Limit:   {outcomes['BREACHED_DAILY']}")
    print(f"  - In-Progress (Censored): {outcomes['IN_PROGRESS']}")
    print(f"Completed Pass Rate:        {comp_pass_rate:.1f}% (Naive i.i.d. SE: +/-{naive_se:.1f}%)")
    print(f"All-Start Pass Rate Bounds: [{min_pass_rate:.1f}%, {max_pass_rate:.1f}%]")
    if days_to_pass:
        print(f"Avg Days to Pass:           {np.mean(days_to_pass):.1f} days (Median: {np.median(days_to_pass):.1f} days)")
    print(f"Challenge Cost per Pass:    ${cost_per_pass:,.2f} ($100 fee per cohort)")

    print("\nCohort-by-Cohort Results:")
    print(f"{'Start Date':<12} | {'End Date':<12} | {'Outcome':<22} | {'Days':<6} | {'Lowest Eq'}")
    print("-" * 65)
    for c in cohort_records:
        days_str = f"{c['days_taken']:>5.1f}" if c['days_taken'] is not None else "N/A"
        print(f"{c['start_date']:<12} | {str(c['end_date']):<12} | {c['outcome']:<22} | {days_str} | ${c['lowest_equity']:,.2f}")
    print("-" * 65)

    audit_output[f"risk_{r_mult}"] = {
        "total_cohorts": total_starts,
        "outcomes": outcomes,
        "completed_pass_rate_pct": round(comp_pass_rate, 2),
        "naive_se_pct": round(naive_se, 2),
        "all_start_bounds_pct": [round(min_pass_rate, 2), round(max_pass_rate, 2)],
        "cost_per_pass_usd": round(cost_per_pass, 2) if cost_per_pass != float("inf") else None,
        "cohorts": cohort_records,
    }

with (OUT_DIR / "monthly_cohort_audit_retail_costs.json").open("w") as f:
    json.dump(audit_output, f, indent=2)
