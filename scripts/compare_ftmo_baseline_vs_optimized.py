"""Side-by-side FTMO 2-Step Challenge Monte Carlo Comparison.

Compares:
1. Baseline ORB (Raw High/Low, Opposite SL, Fixed +2R TP)
2. Microstructure-Optimized ORB (Crabel Stretch k=0.15, Breakeven @ +1.0R, Opposite SL)
"""

from typing import Any, Dict, List
import numpy as np
import polars as pl
from ml4t.diagnostic.evaluation.stats import deflated_sharpe_ratio_from_statistics

from src.ftmo_simulator import FTMOSimulator, FTMOConfig
from scripts.sweep_microstructure_portfolio import run_portfolio_variant


def main():
    print("Running 5-Asset Portfolio backtests for Baseline and Optimized variants...")
    _, _, _, _, _, _, _, trades_base = run_portfolio_variant(k_stretch=0.0, sl_ratio=1.0, use_be=False)
    _, _, _, _, _, _, _, trades_opt = run_portfolio_variant(k_stretch=0.15, sl_ratio=1.0, use_be=True)

    print(f"Baseline trades generated: {len(trades_base)}")
    print(f"Optimized trades generated: {len(trades_opt)} (filtered 155 false breakouts)\n")

    cfg = FTMOConfig()
    sim_base = FTMOSimulator(trades=trades_base, config=cfg)
    sim_opt = FTMOSimulator(trades=trades_opt, config=cfg)

    print("=" * 115)
    print("FTMO 2-STEP CHALLENGE: BASELINE VS MICROSTRUCTURE-OPTIMIZED (5,000 MONTE CARLO TRIALS PER TIER)")
    print("=" * 115)
    print(
        f"{'Configuration':<22} | {'Risk/Tr':<7} | {'Step 1%':<8} | {'Step 2%':<8} | {'Funded%':<8} | "
        f"{'Daily Breach%':<14} | {'MaxDD Breach%':<14} | {'Days to Fund':<12} | {'Fee ROI':<10}"
    )
    print("-" * 115)

    risk_tiers = [0.75, 1.00, 1.25, 1.50]

    for r in risk_tiers:
        res_b = sim_base.run_monte_carlo(n_simulations=5000, risk_pct=r, random_seed=42)
        res_o = sim_opt.run_monte_carlo(n_simulations=5000, risk_pct=r, random_seed=42)

        print(
            f"{'Baseline ORB':<22} | {r:>5.2f}% | "
            f"{res_b['step1_pass_rate_pct']:>6.1f}% | {res_b['step2_conditional_pass_rate_pct']:>6.1f}% | {res_b['overall_two_step_pass_rate_pct']:>6.1f}% | "
            f"{res_b['daily_loss_breach_rate_pct']:>12.1f}% | {res_b['max_loss_breach_rate_pct']:>12.1f}% | "
            f"{res_b['median_total_days_to_funded']:>10.0f} d | {res_b['expected_roi_on_fee_pct']:>+8.1f}%"
        )
        print(
            f"{'Optimized (Crabel+BE)':<22} | {r:>5.2f}% | "
            f"{res_o['step1_pass_rate_pct']:>6.1f}% | {res_o['step2_conditional_pass_rate_pct']:>6.1f}% | {res_o['overall_two_step_pass_rate_pct']:>6.1f}% | "
            f"{res_o['daily_loss_breach_rate_pct']:>12.1f}% | {res_o['max_loss_breach_rate_pct']:>12.1f}% | "
            f"{res_o['median_total_days_to_funded']:>10.0f} d | {res_o['expected_roi_on_fee_pct']:>+8.1f}%"
        )
        print("-" * 115)


if __name__ == "__main__":
    main()
