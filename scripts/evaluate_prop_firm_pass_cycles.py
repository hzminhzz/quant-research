"""Evaluate Sequential Prop Firm Challenge Cycles (Static 10% Max Drawdown Floor).

Rules:
- Initial balance: $100,000
- Static floor: $90,000 (Account fails if equity < $90,000)
- Daily limit: 5% of midnight starting equity
- Step 1: Reach $110,000 (+10%), min 4 trading days
- Step 2: Reset to $100,000, reach $105,000 (+5%), min 4 trading days
- On Funded: Record success, launch new $100k challenge attempt on next day
- On Breach: Record failure, launch new $100k challenge attempt on next day
"""

import json
from pathlib import Path
import sys
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml4t.backtest import Strategy, Engine, DataFeed, BacktestConfig
from ml4t.backtest.config import ShareType, CommissionType, SlippageType
from scripts.run_verified_dual_timeframe_audit import prepare_dual_timeframe_dataset, VerifiedDualTimeframeStrategy, INITIAL_CASH

OUT_DIR = Path("run_log/prop_firm_evaluation")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def simulate_challenge_cycles(equity_records: list[dict]):
    """Simulates sequential challenge attempts across chronological minute equity records."""
    attempts = []
    current_attempt = {
        "id": 1,
        "stage": "step1",
        "start_time": equity_records[0]["timestamp"],
        "account_balance": 100000.0,
        "trading_days": set(),
        "start_day_equity": 100000.0,
        "current_day": None,
    }

    # Track base equity curve multiplier
    base_eq_start = equity_records[0]["equity"]

    for row in equity_records:
        ts = row["timestamp"]
        cur_day = ts[:10]
        cur_base_eq = row["equity"]

        # If starting a new attempt
        if "attempt_base_eq_start" not in current_attempt:
            current_attempt["attempt_base_eq_start"] = cur_base_eq
            current_attempt["account_balance"] = 100000.0
            current_attempt["stage_start_base_eq"] = cur_base_eq
            current_attempt["stage_start_balance"] = 100000.0

        # Midnight day rollover
        if current_attempt["current_day"] != cur_day:
            current_attempt["current_day"] = cur_day
            current_attempt["trading_days"].add(cur_day)
            current_attempt["start_day_equity"] = current_attempt["account_balance"]

        # Calculate current virtual account equity
        stage_growth = cur_base_eq / current_attempt["stage_start_base_eq"]
        cur_account_equity = current_attempt["stage_start_balance"] * stage_growth

        # Daily loss check from midnight starting equity
        daily_loss_pct = (cur_account_equity - current_attempt["start_day_equity"]) / current_attempt["start_day_equity"]

        # Static max loss check ($90,000 floor)
        static_drawdown_pct = (cur_account_equity - 100000.0) / 100000.0

        # 1. Breach Check
        if cur_account_equity <= 90000.0 or daily_loss_pct <= -0.05:
            reason = "daily_loss" if daily_loss_pct <= -0.05 else "max_loss_floor"
            current_attempt["status"] = "BREACHED"
            current_attempt["reason"] = reason
            current_attempt["end_time"] = ts
            current_attempt["days_taken"] = len(current_attempt["trading_days"])
            attempts.append(current_attempt)

            # Start next attempt
            current_attempt = {
                "id": len(attempts) + 1,
                "stage": "step1",
                "start_time": ts,
                "trading_days": set(),
                "current_day": None,
            }
            continue

        # 2. Step 1 Target Check ($110,000 / +10%, min 4 trading days)
        if current_attempt["stage"] == "step1":
            if cur_account_equity >= 110000.0 and len(current_attempt["trading_days"]) >= 4:
                # Transition to Step 2
                current_attempt["stage"] = "step2"
                current_attempt["step1_days"] = len(current_attempt["trading_days"])
                current_attempt["trading_days"] = set()
                current_attempt["current_day"] = None
                current_attempt["stage_start_balance"] = 100000.0
                current_attempt["stage_start_base_eq"] = cur_base_eq
                current_attempt["start_day_equity"] = 100000.0
                continue

        # 3. Step 2 Target Check ($105,000 / +5%, min 4 trading days)
        elif current_attempt["stage"] == "step2":
            if cur_account_equity >= 105000.0 and len(current_attempt["trading_days"]) >= 4:
                # Passed Challenge -> FUNDED!
                current_attempt["status"] = "FUNDED"
                current_attempt["end_time"] = ts
                current_attempt["step2_days"] = len(current_attempt["trading_days"])
                current_attempt["total_days"] = current_attempt["step1_days"] + current_attempt["step2_days"]
                attempts.append(current_attempt)

                # Start next attempt
                current_attempt = {
                    "id": len(attempts) + 1,
                    "stage": "step1",
                    "start_time": ts,
                    "trading_days": set(),
                    "current_day": None,
                }
                continue

    # Close out in-progress attempt at end of dataset
    if "status" not in current_attempt:
        current_attempt["status"] = "IN_PROGRESS"
        current_attempt["end_time"] = equity_records[-1]["timestamp"]
        current_attempt["days_taken"] = len(current_attempt["trading_days"])
        attempts.append(current_attempt)

    return attempts


def run_evaluation():
    print("Preparing 1-minute dataset for sequential challenge simulation...")
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

    variants = [
        ("Full Risk + 3.0% Watchdog", 1.0, 0.03),
        ("0.70x Risk + 3.0% Watchdog", 0.70, 0.03),
        ("0.50x Risk + 2.5% Watchdog", 0.50, 0.025),
    ]

    print("\n" + "=" * 95)
    print("=== PROP FIRM FUNDING CYCLE AUDIT (STATIC 10% FLOOR: $90,000, 2025-2026) ===")
    print("=" * 95)
    print(f"{'Variant':<28} | {'Attempts':<9} | {'Funded':<8} | {'Breached':<9} | {'Pass Rate':<10} | {'Avg Days to Fund'}")
    print("-" * 95)

    all_results = {}

    for label, r_mult, threshold in variants:
        feed = DataFeed(prices_df=prices_df, signals_df=signals_df)
        strat = VerifiedDualTimeframeStrategy(risk_mult=r_mult, daily_flatten_pct=threshold)
        res = Engine(feed, strat, cfg).run()

        # Extract 1-minute equity series
        eq_series = res.to_equity_dataframe()
        records = [
            {"timestamp": str(ts), "equity": float(eq)}
            for ts, eq in zip(eq_series["timestamp"].to_list(), eq_series["equity"].to_list())
        ]

        attempts = simulate_challenge_cycles(records)

        funded_count = sum(1 for a in attempts if a["status"] == "FUNDED")
        breached_count = sum(1 for a in attempts if a["status"] == "BREACHED")
        total_finished = funded_count + breached_count
        pass_rate = (funded_count / total_finished * 100) if total_finished > 0 else 0.0

        funded_days = [a["total_days"] for a in attempts if a["status"] == "FUNDED"]
        avg_days = float(np.mean(funded_days)) if funded_days else 0.0

        print(f"{label:<28} | {len(attempts):>8} | {funded_count:>8} | {breached_count:>9} | {pass_rate:>9.1f}% | {avg_days:>15.1f} days")

        all_results[label] = {
            "total_attempts": len(attempts),
            "funded_count": funded_count,
            "breached_count": breached_count,
            "pass_rate_pct": pass_rate,
            "avg_days_to_fund": avg_days,
            "attempts": attempts,
        }

    with (OUT_DIR / "prop_firm_challenge_cycles_results.json").open("w") as f:
        json.dump(all_results, f, indent=2)


if __name__ == "__main__":
    run_evaluation()
