"""Independent First-Passage Trials with Retail Prop Firm Costs (2025-2026).

Methodology:
- Evaluates independent challenge accounts initialized with $10,000 cash and zero open positions.
- Start dates sampled every 7 calendar days from 2025-01-01 to 2026-06-15 (76 independent trials).
- Terminating absorbing boundaries:
    1. TARGET PASSED: Equity >= $11,500 (+15.0% profit target).
    2. STATIC FLOOR BREACHED: Equity <= $9,000 (-10.0% static drawdown floor).
    3. DAILY LIMIT BREACHED: Intraday equity <= -5.0% from midnight starting balance.
- Retail Prop Firm Costs: 10 bps commission + 5 bps slippage per leg (30 bps roundtrip).
- Reports pass rate, standard error, 95% confidence interval, and regime-stratified breakdown.
"""

import json
from pathlib import Path
import sys
from datetime import datetime, timedelta, timezone
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml4t.backtest import Strategy, Engine, DataFeed, BacktestConfig
from ml4t.backtest.config import ShareType, CommissionType, SlippageType
from scripts.run_verified_dual_timeframe_audit import prepare_dual_timeframe_dataset

OUT_DIR = Path("run_log/prop_firm_evaluation")
OUT_DIR.mkdir(parents=True, exist_ok=True)

INITIAL_BALANCE = 10000.0
TARGET_EQUITY = 11500.0  # +15.0%
FLOOR_EQUITY = 9000.0    # -10.0%
COMMISSION_BPS = 0.0010  # 10 bps retail taker fee
SLIPPAGE_BPS = 0.0005    # 5 bps retail spread/slippage


class FirstPassageChallengeStrategy(Strategy):
    """Executes dual-timeframe strategy with absorbing boundaries for prop firm challenges."""
    def __init__(self, risk_mult: float = 1.0, daily_flatten_pct: float = 0.03):
        super().__init__()
        self.risk_mult = risk_mult
        self.daily_flatten_pct = daily_flatten_pct
        self.current_date = None
        self.day_start_equity = INITIAL_BALANCE
        self.circuit_breaker_active = False

        self.outcome = "IN_PROGRESS"
        self.end_timestamp = None
        self.final_equity = INITIAL_BALANCE
        self.lowest_equity = INITIAL_BALANCE
        self.worst_daily_dd = 0.0

    def on_data(self, timestamp, data, context, broker):
        bar_date = timestamp.strftime("%Y-%m-%d")
        equity = float(broker.equity())

        if equity < self.lowest_equity:
            self.lowest_equity = equity

        # Day rollover check (midnight UTC)
        if self.current_date != bar_date:
            self.current_date = bar_date
            self.day_start_equity = equity
            self.circuit_breaker_active = False

        floating_daily_dd = (equity - self.day_start_equity) / self.day_start_equity
        if floating_daily_dd < self.worst_daily_dd:
            self.worst_daily_dd = floating_daily_dd

        # --- ABSORBING BOUNDARY CHECKS ---
        # 1. Target Passed (+15%)
        if equity >= TARGET_EQUITY:
            self.outcome = "PASSED"
            self.end_timestamp = timestamp
            self.final_equity = equity
            raise StopIteration("Target reached")

        # 2. Daily Loss Breached (-5%)
        if floating_daily_dd <= -0.05:
            self.outcome = "BREACHED_DAILY"
            self.end_timestamp = timestamp
            self.final_equity = equity
            raise StopIteration("Daily limit breached")

        # 3. Static Floor Breached (-10%)
        if equity <= FLOOR_EQUITY:
            self.outcome = "BREACHED_STATIC_FLOOR"
            self.end_timestamp = timestamp
            self.final_equity = equity
            raise StopIteration("Static floor breached")

        # --- 1-MINUTE WATCHDOG FLATTEN ---
        if not self.circuit_breaker_active and floating_daily_dd <= -self.daily_flatten_pct:
            self.circuit_breaker_active = True
            for sym in data.keys():
                pos = broker.get_position(sym)
                if pos is not None and pos.quantity != 0:
                    broker.order_target_percent(sym, 0.0)
            return

        if self.circuit_breaker_active:
            for sym in data.keys():
                pos = broker.get_position(sym)
                if pos is not None and pos.quantity != 0:
                    broker.order_target_percent(sym, 0.0)
            return

        # --- 1-HOUR REBALANCE (minute == 0) ---
        if timestamp.minute != 0:
            return

        base_weight = 0.15 * self.risk_mult
        for sym, bar in data.items():
            sig = bar["signals"].get("roc_168h")
            ema120 = bar["signals"].get("ema_120h")
            close_p = bar.get("close", 0.0)

            if sig is None or ema120 is None or close_p is None:
                continue

            pos = broker.get_position(sym)
            current_qty = pos.quantity if pos is not None else 0.0

            if close_p > ema120 and sig > 0.015:
                if current_qty <= 0:
                    broker.order_target_percent(sym, base_weight)
            elif close_p < ema120 and sig < -0.015:
                if current_qty >= 0:
                    broker.order_target_percent(sym, -base_weight)
            else:
                if current_qty != 0:
                    broker.order_target_percent(sym, 0.0)


def run_trials():
    print("Preparing 1-minute dataset for independent trial generation...")
    df = prepare_dual_timeframe_dataset()

    prices_df = df.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
    signals_df = df.select(["timestamp", "symbol", "roc_168h", "ema_120h", "is_hour_close"])

    # Generate weekly start dates from 2025-01-01 to 2026-06-15
    start_dt = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    end_dt = datetime(2026, 6, 15, 0, 0, tzinfo=timezone.utc)

    start_dates = []
    curr = start_dt
    while curr <= end_dt:
        start_dates.append(curr)
        curr += timedelta(days=7)

    print(f"Total start dates to evaluate: {len(start_dates)} independent weekly cohorts.")

    configs_to_test = [
        ("Full Risk (1.0x)", 1.0, 0.03),
        ("Calibrated Risk (0.5x)", 0.5, 0.025),
    ]

    all_results = {}

    for cfg_label, r_mult, breaker_pct in configs_to_test:
        print(f"\n=======================================================")
        print(f"=== RUNNING TRIALS: {cfg_label} (Retail Costs: 10 bps fee + 5 bps slip) ===")
        print(f"=======================================================")

        trial_records = []
        for idx, s_date in enumerate(start_dates):
            # Filter dataset from start_date onward
            p_sub = prices_df.filter(pl.col("timestamp") >= s_date)
            s_sub = signals_df.filter(pl.col("timestamp") >= s_date)

            cfg = BacktestConfig(
                initial_cash=INITIAL_BALANCE,
                allow_short_selling=True,
                share_type=ShareType.FRACTIONAL,
                commission_type=CommissionType.PERCENTAGE,
                commission_rate=COMMISSION_BPS,
                slippage_type=SlippageType.PERCENTAGE,
                slippage_rate=SLIPPAGE_BPS,
            )

            feed = DataFeed(prices_df=p_sub, signals_df=s_sub)
            strat = FirstPassageChallengeStrategy(risk_mult=r_mult, daily_flatten_pct=breaker_pct)

            try:
                Engine(feed, strat, cfg).run()
                outcome = strat.outcome
            except StopIteration:
                outcome = strat.outcome

            end_t = strat.end_timestamp or p_sub["timestamp"][-1]
            days_taken = (end_t - s_date).total_seconds() / 86400.0

            trial_records.append({
                "trial_id": idx + 1,
                "start_date": s_date.strftime("%Y-%m-%d"),
                "end_date": end_t.strftime("%Y-%m-%d") if isinstance(end_t, datetime) else str(end_t)[:10],
                "quarter": f"{s_date.year}-Q{(s_date.month - 1) // 3 + 1}",
                "outcome": outcome,
                "final_equity": strat.final_equity,
                "lowest_equity": strat.lowest_equity,
                "days_taken": round(days_taken, 1),
            })

            if (idx + 1) % 15 == 0 or (idx + 1) == len(start_dates):
                passed_so_far = sum(1 for t in trial_records if t["outcome"] == "PASSED")
                print(f"  Processed {idx + 1}/{len(start_dates)} trials | Passed so far: {passed_so_far}/{idx + 1}")

        # Compute Statistical Distribution
        passed = [t for t in trial_records if t["outcome"] == "PASSED"]
        breached_static = [t for t in trial_records if t["outcome"] == "BREACHED_STATIC_FLOOR"]
        breached_daily = [t for t in trial_records if t["outcome"] == "BREACHED_DAILY"]
        breached_total = breached_static + breached_daily
        in_prog = [t for t in trial_records if t["outcome"] == "IN_PROGRESS"]

        n_completed = len(passed) + len(breached_total)
        p_hat = len(passed) / n_completed if n_completed > 0 else 0.0
        se = np.sqrt(p_hat * (1.0 - p_hat) / n_completed) if n_completed > 0 else 0.0
        ci_lower = max(0.0, p_hat - 1.96 * se)
        ci_upper = min(1.0, p_hat + 1.96 * se)

        days_passed = [t["days_taken"] for t in passed]
        avg_days = float(np.mean(days_passed)) if days_passed else 0.0
        median_days = float(np.median(days_passed)) if days_passed else 0.0

        # Quarterly stratification
        quarters = sorted(list(set(t["quarter"] for t in trial_records)))
        q_breakdown = {}
        for q in quarters:
            q_trials = [t for t in trial_records if t["quarter"] == q]
            q_pass = sum(1 for t in q_trials if t["outcome"] == "PASSED")
            q_tot = sum(1 for t in q_trials if t["outcome"] in ("PASSED", "BREACHED_STATIC_FLOOR", "BREACHED_DAILY"))
            q_rate = (q_pass / q_tot * 100) if q_tot > 0 else 0.0
            q_breakdown[q] = {
                "trials": len(q_trials),
                "passed": q_pass,
                "pass_rate_pct": round(q_rate, 1),
            }

        # Expected Value per $100 challenge fee
        # Assume typical prop firm payout: 80% split on 5% monthly return = $400 payout on $10k account
        ev_fee = (p_hat * 400.0) - 100.0

        print("\n" + "=" * 70)
        print(f"=== STATISTICAL DISTRIBUTION: {cfg_label} ===")
        print("=" * 70)
        print(f"Total Trials Tested:           {len(trial_records)}")
        print(f"Completed Trials:              {n_completed}")
        print(f"  - Successfully PASSED (+15%): {len(passed)}")
        print(f"  - Breached Static Floor (-10%):{len(breached_static)}")
        print(f"  - Breached Daily Limit (-5%):  {len(breached_daily)}")
        print(f"In-Progress (Censored):        {len(in_prog)}")
        print(f"Empirical Pass Rate:           {p_hat * 100:.2f}%")
        print(f"Standard Error (SE):           ±{se * 100:.2f}%")
        print(f"95% Confidence Interval:       [{ci_lower * 100:.2f}%, {ci_upper * 100:.2f}%]")
        print(f"Average Days to Pass:          {avg_days:.1f} days (Median: {median_days:.1f} days)")
        print(f"Expected Return per $100 Fee:  ${ev_fee:+.2f}")

        print("\nPass Rate Stratified by Entry Quarter:")
        print(f"{'Quarter':<10} | {'Trials':<8} | {'Passed':<8} | {'Pass Rate'}")
        print("-" * 45)
        for q, stats in q_breakdown.items():
            print(f"{q:<10} | {stats['trials']:<8} | {stats['passed']:<8} | {stats['pass_rate_pct']:>8.1f}%")
        print("-" * 45)

        all_results[cfg_label] = {
            "total_trials": len(trial_records),
            "completed_trials": n_completed,
            "passed_count": len(passed),
            "breached_static_floor": len(breached_static),
            "breached_daily_limit": len(breached_daily),
            "pass_rate_pct": round(p_hat * 100, 2),
            "standard_error_pct": round(se * 100, 2),
            "ci_95": [round(ci_lower * 100, 2), round(ci_upper * 100, 2)],
            "avg_days_to_pass": round(avg_days, 1),
            "median_days_to_pass": round(median_days, 1),
            "quarterly_breakdown": q_breakdown,
            "trials": trial_records,
        }

    with (OUT_DIR / "independent_first_passage_trials_results.json").open("w") as f:
        json.dump(all_results, f, indent=2)


if __name__ == "__main__":
    run_trials()
