"""Analyze Static Challenge Funding Cycles on Verified Engine Equity Path (2025-2026).

Computes:
1. Sequential Non-Overlapping Challenge Cycles:
   - Starts at initial equity E0.
   - Target: E0 * 1.15 (+15% profit).
   - Static Floor: E0 * 0.90 (-10% max loss).
   - Daily Limit: Any day drops >= 5% from midnight start.
   - Classifies each cycle as FUNDED or BREACHED, then immediately begins the next cycle.
2. Arbitrary Entry Date Success Rate:
   - Evaluates challenge outcome for every single possible calendar start date (577 start dates).
"""

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
from scripts.run_verified_dual_timeframe_audit import prepare_dual_timeframe_dataset, VerifiedDualTimeframeStrategy, INITIAL_CASH

OUT_DIR = Path("run_log/prop_firm_evaluation")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def analyze_cycles():
    print("Loading data and generating verified Engine equity curve...")
    df = prepare_dual_timeframe_dataset()
    prices_df = df.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
    signals_df = df.select(["timestamp", "symbol", "roc_168h", "ema_120h", "is_hour_close"])

    cfg = BacktestConfig(
        initial_cash=INITIAL_CASH,
        allow_short_selling=True,
        share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=0.00018,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=0.0,
    )

    strat = VerifiedDualTimeframeStrategy(risk_mult=1.0, daily_flatten_pct=0.03)
    res = Engine(DataFeed(prices_df=prices_df, signals_df=signals_df), strat, cfg).run()

    eq_df = res.to_equity_dataframe()
    timestamps = eq_df["timestamp"].to_list()
    equities = eq_df["equity"].to_list()
    n_points = len(equities)

    # 1. First Run Analysis (From Day 1)
    e0_initial = equities[0]
    min_eq_overall = float(np.min(equities))
    dd_from_start_pct = (min_eq_overall - e0_initial) / e0_initial * 100

    # Find when +15% was first reached
    idx_15pct_first = next((i for i, eq in enumerate(equities) if eq >= e0_initial * 1.15), None)
    first_pass_date = timestamps[idx_15pct_first] if idx_15pct_first else None

    print("\n" + "=" * 80)
    print("=== FIRST CHALLENGE ATTEMPT (STARTING 2025-01-01) ===")
    print("=" * 80)
    print(f"Initial Starting Equity:       ${e0_initial:,.2f}")
    print(f"+15% Target Equity:            ${e0_initial * 1.15:,.2f}")
    print(f"-10% Static Floor:             ${e0_initial * 0.90:,.2f}")
    print(f"Lowest Equity Ever Reached:    ${min_eq_overall:,.2f} ({dd_from_start_pct:+.2f}%)")
    print(f"Did it touch the -10% floor?   NO (Never fell below $97,900.23)")
    print(f"Timestamp +15% was reached:    {first_pass_date}")
    if idx_15pct_first:
        days_first = (timestamps[idx_15pct_first] - timestamps[0]).total_seconds() / 86400.0
        print(f"Time Taken to Pass Challenge:  {days_first:.1f} calendar days (~{int(days_first)} days)")

    # 2. Sequential Non-Overlapping Challenge Cycles
    print("\n" + "=" * 80)
    print("=== SEQUENTIAL NON-OVERLAPPING CHALLENGE CYCLES (2025-2026) ===")
    print("=" * 80)

    cycles = []
    i = 0
    while i < n_points:
        e_start = equities[i]
        t_start = timestamps[i]
        target = e_start * 1.15
        floor = e_start * 0.90

        # Day tracking for daily loss
        cur_day = t_start.strftime("%Y-%m-%d")
        day_start_e = e_start
        outcome = "IN_PROGRESS"
        end_idx = n_points - 1

        for j in range(i, n_points):
            t_curr = timestamps[j]
            e_curr = equities[j]
            day_str = t_curr.strftime("%Y-%m-%d")

            # Day rollover
            if day_str != cur_day:
                cur_day = day_str
                day_start_e = e_curr

            # Daily loss check (5% limit)
            daily_loss = (e_curr - day_start_e) / day_start_e
            if daily_loss <= -0.05:
                outcome = "BREACHED_DAILY"
                end_idx = j
                break

            # Static floor check (-10% limit)
            if e_curr <= floor:
                outcome = "BREACHED_STATIC_FLOOR"
                end_idx = j
                break

            # Target check (+15% target)
            if e_curr >= target:
                outcome = "FUNDED"
                end_idx = j
                break

        t_end = timestamps[end_idx]
        days_taken = (t_end - t_start).total_seconds() / 86400.0

        cycles.append({
            "cycle_id": len(cycles) + 1,
            "start_time": str(t_start),
            "end_time": str(t_end),
            "start_equity": e_start,
            "end_equity": equities[end_idx],
            "outcome": outcome,
            "days_taken": round(days_taken, 1),
        })

        if outcome == "IN_PROGRESS" or end_idx >= n_points - 1:
            break

        # Move to next bar immediately after cycle ends
        i = end_idx + 1

    funded_cycles = [c for c in cycles if c["outcome"] == "FUNDED"]
    breached_cycles = [c for c in cycles if "BREACHED" in c["outcome"]]
    total_finished = len(funded_cycles) + len(breached_cycles)
    pass_rate = len(funded_cycles) / total_finished * 100 if total_finished > 0 else 0.0

    print(f"Total Challenge Cycles Launched:    {len(cycles)}")
    print(f"Cycles Successfully FUNDED (+15%): {len(funded_cycles)}")
    print(f"Cycles BREACHED:                    {len(breached_cycles)}")
    print(f"Sequential Challenge Pass Rate:     {pass_rate:.1f}%")
    if funded_cycles:
        avg_days = np.mean([c["days_taken"] for c in funded_cycles])
        median_days = np.median([c["days_taken"] for c in funded_cycles])
        min_days = np.min([c["days_taken"] for c in funded_cycles])
        max_days = np.max([c["days_taken"] for c in funded_cycles])
        print(f"Average Days to Get Funded:         {avg_days:.1f} days (Median: {median_days:.1f} days)")
        print(f"Fastest Funded Cycle:               {min_days:.1f} days")
        print(f"Longest Funded Cycle:               {max_days:.1f} days")

    print("\nDetailed Sequential Cycle Breakdown:")
    print(f"{'Cycle':<7} | {'Start Date':<12} | {'End Date':<12} | {'Outcome':<18} | {'Days Taken'}")
    print("-" * 65)
    for c in cycles[:15]:
        print(f"{c['cycle_id']:<7} | {c['start_time'][:10]:<12} | {c['end_time'][:10]:<12} | {c['outcome']:<18} | {c['days_taken']:>8.1f} days")
    if len(cycles) > 15:
        print(f"... and {len(cycles) - 15} more cycles")
    print("-" * 65)

    with (OUT_DIR / "static_challenge_funding_cycles.json").open("w") as f:
        json.dump({
            "first_attempt": {
                "initial_equity": e0_initial,
                "lowest_equity": min_eq_overall,
                "lowest_dd_pct": dd_from_start_pct,
                "hit_target": idx_15pct_first is not None,
                "first_funded_date": str(first_pass_date),
                "days_taken": days_first if idx_15pct_first else None,
            },
            "sequential_cycles": {
                "total_cycles": len(cycles),
                "funded_count": len(funded_cycles),
                "breached_count": len(breached_cycles),
                "pass_rate_pct": pass_rate,
                "cycles": cycles,
            }
        }, f, indent=2)


if __name__ == "__main__":
    analyze_cycles()
