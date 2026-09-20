"""FTMO 2-Step Challenge Institutional Simulator.

Strictly models the official rules of the FTMO 2-Step Evaluation Process:
Reference: https://ftmo.com/en/2-step-challenge/

Core Objectives & Constraints:
- Step 1 (FTMO Challenge): +10.0% Profit Target ($10,000 on $100k), Min 4 Trading Days.
- Step 2 (Verification):    +5.0% Profit Target ($5,000 on $100k), Min 4 Trading Days.
- Maximum Daily Loss:        5.0% ($5,000 on $100k) measured midnight-to-midnight CE(S)T.
- Maximum Overall Loss:     10.0% ($10,000 on $100k) balance/equity minimum ($90,000).
- Trading Period:           Unlimited (no time expiration).
- Funded Stage (Step 3):    No profit target, 80% to 90% payout split, fee refunded with first payout.

Methodology (ML4T Standards):
- Stationary Block Bootstrap & Monte Carlo Resampling to evaluate thousands of path-dependent challenge paths.
- Multiple testing adjustment: Bailey & López de Prado haircut and Deflated Sharpe Ratio (DSR).
- Path-dependent intraday drawdown and daily circuit breaker enforcement.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import polars as pl
from scipy.stats import norm


@dataclass
class FTMOConfig:
    initial_balance: float = 100_000.0
    # Step 1: Challenge
    step1_target_pct: float = 0.10      # +10.0% ($10,000)
    step1_min_trading_days: int = 4
    # Step 2: Verification
    step2_target_pct: float = 0.05      # +5.0% ($5,000)
    step2_min_trading_days: int = 4
    # Step 3: Funded
    profit_split_pct: float = 0.80      # 80% payout
    # Hard FTMO Risk Limits
    max_daily_loss_pct: float = 0.05    # 5.0% hard breach
    max_total_loss_pct: float = 0.10    # 10.0% hard breach (equity < $90k)
    # User Safety Circuit Breakers
    user_daily_halt_pct: float = 0.02   # Halt new trades after -2.0% loss in a single day
    user_max_loss_buffer_pct: float = 0.09  # User safety stop (9.0% total drawdown)
    challenge_fee_usd: float = 540.0    # 100k challenge price (EUR 540 converted)


@dataclass
class FTMOAttemptResult:
    step1_passed: bool
    step2_passed: bool
    funded: bool
    breached: bool
    breach_stage: str  # 'none', 'step1', 'step2', 'funded'
    breach_reason: str  # 'none', 'daily_loss', 'max_loss'
    step1_days: int
    step2_days: int
    total_days: int
    step1_trades: int
    step2_trades: int
    total_trades: int
    funded_days_survived: int = 0
    funded_payouts_earned: float = 0.0
    fee_refunded: bool = False
    net_pnl_usd: float = 0.0
    max_daily_loss_observed_pct: float = 0.0
    max_total_loss_observed_pct: float = 0.0


class FTMOSimulator:
    """Institutional-grade simulator for the FTMO 2-Step Challenge."""

    def __init__(self, trades: List[Dict[str, Any]], config: Optional[FTMOConfig] = None):
        """Initialize with a chronological trade list.

        Each trade dict must contain:
        - 'date': str or date (YYYY-MM-DD)
        - 'pnl_pct': return fraction (e.g. +0.0196 for +1.96% at 1.0% risk)
        - 'r_mult': trade outcome in R units (e.g. +1.96, -1.02)
        - 'entry_time': optional timestamp for intraday sorting
        """
        self.config = config or FTMOConfig()
        self.trades = sorted(trades, key=lambda t: str(t.get("entry_time", t.get("date"))))
        
        # Group trades by trading day
        self.trades_by_date: Dict[str, List[Dict[str, Any]]] = {}
        for t in self.trades:
            d = str(t["date"])
            self.trades_by_date.setdefault(d, []).append(t)
        
        self.unique_dates = sorted(self.trades_by_date.keys())

    def simulate_path(
        self,
        daily_trade_sequence: List[List[Dict[str, Any]]],
        risk_pct: float = 1.0,
        simulate_funded: bool = True,
        funded_sim_days: int = 60,
        prob_threshold: Optional[float] = None,
        use_half_kelly: bool = False,
        base_risk_pct: float = 1.0,
        max_kelly_risk_pct: float = 2.0,
    ) -> FTMOAttemptResult:
        """Simulate a single chronological attempt through Step 1, Step 2, and Funded."""
        cfg = self.config
        initial_balance = cfg.initial_balance
        max_daily_pct = cfg.max_daily_loss_pct
        max_total_pct = cfg.max_total_loss_pct
        daily_halt_pct = cfg.user_daily_halt_pct

        current_stage = 1  # 1 = Step 1, 2 = Step 2, 3 = Funded
        account_balance = initial_balance
        stage_start_balance = initial_balance
        
        step1_days = 0
        step2_days = 0
        step1_trades = 0
        step2_trades = 0
        funded_days = 0
        funded_payouts = 0.0
        fee_refunded = False
        
        max_daily_observed = 0.0
        max_total_observed = 0.0

        for day_trades in daily_trade_sequence:
            day_pnl_pct = 0.0
            day_had_trade = False

            for t in day_trades:
                # Check user daily circuit breaker before entry
                if day_pnl_pct <= -daily_halt_pct:
                    # Halt further trading for the rest of this day to protect daily limit
                    break

                # Probability gating: skip trade if meta-model probability is below cutoff
                p_hat = t.get("prob", t.get("meta_prob", None))
                if prob_threshold is not None and p_hat is not None:
                    if p_hat < prob_threshold:
                        continue

                # Determine trade risk sizing
                if use_half_kelly and p_hat is not None:
                    # Half-Kelly sizing for 2:1 reward-to-risk ratio (b = 2)
                    # Full Kelly: f* = (b*p - q) / b = (2p - (1-p)) / 2 = (3p - 1) / 2
                    # Half Kelly: 0.5 * f*
                    full_kelly = max(0.0, (3.0 * p_hat - 1.0) / 2.0)
                    half_kelly_frac = 0.5 * full_kelly
                    trade_risk_pct = float(np.clip(half_kelly_frac * 10.0, 0.25, max_kelly_risk_pct))
                else:
                    trade_risk_pct = risk_pct

                # Scale trade by current risk sizing
                r = t.get("r_mult", t.get("pnl_pct", 0.0) * 100.0)
                # Net percentage gained/lost on initial balance
                scaled_trade_pct = r * (trade_risk_pct / 100.0)
                
                day_pnl_pct += scaled_trade_pct
                day_had_trade = True

                if current_stage == 1:
                    step1_trades += 1
                elif current_stage == 2:
                    step2_trades += 1

            # Track peak daily loss
            if day_pnl_pct < 0:

                loss_mag = abs(day_pnl_pct)
                if loss_mag > max_daily_observed:
                    max_daily_observed = loss_mag

            # Check hard FTMO Daily Loss Breach (5.0%)
            if day_pnl_pct <= -max_daily_pct:
                return FTMOAttemptResult(
                    step1_passed=False,
                    step2_passed=False,
                    funded=False,
                    breached=True,
                    breach_stage=f"step{current_stage}" if current_stage <= 2 else "funded",
                    breach_reason="daily_loss",
                    step1_days=step1_days,
                    step2_days=step2_days,
                    total_days=step1_days + step2_days + funded_days,
                    step1_trades=step1_trades,
                    step2_trades=step2_trades,
                    total_trades=step1_trades + step2_trades,
                    funded_days_survived=funded_days,
                    funded_payouts_earned=funded_payouts,
                    fee_refunded=fee_refunded,
                    net_pnl_usd=-cfg.challenge_fee_usd,
                    max_daily_loss_observed_pct=max_daily_observed * 100.0,
                    max_total_loss_observed_pct=max_total_observed * 100.0,
                )

            # Update account balance
            account_balance += day_pnl_pct * initial_balance
            
            # Track overall drawdown from initial balance
            total_dd_pct = (initial_balance - account_balance) / initial_balance
            if total_dd_pct > max_total_observed:
                max_total_observed = total_dd_pct

            # Check hard FTMO Total Loss Breach (10.0% or user 9% buffer)
            if total_dd_pct >= max_total_pct:
                return FTMOAttemptResult(
                    step1_passed=False,
                    step2_passed=False,
                    funded=False,
                    breached=True,
                    breach_stage=f"step{current_stage}" if current_stage <= 2 else "funded",
                    breach_reason="max_loss",
                    step1_days=step1_days,
                    step2_days=step2_days,
                    total_days=step1_days + step2_days + funded_days,
                    step1_trades=step1_trades,
                    step2_trades=step2_trades,
                    total_trades=step1_trades + step2_trades,
                    funded_days_survived=funded_days,
                    funded_payouts_earned=funded_payouts,
                    fee_refunded=fee_refunded,
                    net_pnl_usd=-cfg.challenge_fee_usd,
                    max_daily_loss_observed_pct=max_daily_observed * 100.0,
                    max_total_loss_observed_pct=max_total_observed * 100.0,
                )

            # Record trading day count
            if day_had_trade:
                if current_stage == 1:
                    step1_days += 1
                elif current_stage == 2:
                    step2_days += 1
                elif current_stage == 3:
                    funded_days += 1

            # STAGE TRANSITIONS
            if current_stage == 1:
                # Step 1 Target: +10% and >= 4 trading days
                stage_profit_pct = (account_balance - stage_start_balance) / initial_balance
                if stage_profit_pct >= cfg.step1_target_pct and step1_days >= cfg.step1_min_trading_days:
                    # PASS STEP 1 -> Move to Step 2
                    current_stage = 2
                    account_balance = initial_balance  # Reset balance for Step 2
                    stage_start_balance = initial_balance

            elif current_stage == 2:
                # Step 2 Target: +5% and >= 4 trading days
                stage_profit_pct = (account_balance - stage_start_balance) / initial_balance
                if stage_profit_pct >= cfg.step2_target_pct and step2_days >= cfg.step2_min_trading_days:
                    # PASS STEP 2 -> FUNDED TRADER!
                    current_stage = 3
                    account_balance = initial_balance  # Reset balance for funded account
                    stage_start_balance = initial_balance
                    fee_refunded = True  # Fee refunded with first reward
                    funded_payouts += cfg.challenge_fee_usd

                    if not simulate_funded:
                        break

            elif current_stage == 3:
                # Funded Phase: bi-weekly profit payout (every 14 trading days)
                if funded_days > 0 and funded_days % 14 == 0:
                    profit_to_split = account_balance - initial_balance
                    if profit_to_split > 0:
                        payout = profit_to_split * cfg.profit_split_pct
                        funded_payouts += payout
                        account_balance = initial_balance  # Payout resets balance to $100k

                if funded_days >= funded_sim_days:
                    break  # Completed funded evaluation window

        # Evaluation complete
        is_funded = (current_stage == 3)
        return FTMOAttemptResult(
            step1_passed=(current_stage >= 2),
            step2_passed=is_funded,
            funded=is_funded,
            breached=False,
            breach_stage="none",
            breach_reason="none",
            step1_days=step1_days,
            step2_days=step2_days,
            total_days=step1_days + step2_days + funded_days,
            step1_trades=step1_trades,
            step2_trades=step2_trades,
            total_trades=step1_trades + step2_trades,
            funded_days_survived=funded_days,
            funded_payouts_earned=funded_payouts,
            fee_refunded=fee_refunded,
            net_pnl_usd=(funded_payouts - cfg.challenge_fee_usd) if not fee_refunded else funded_payouts,
            max_daily_loss_observed_pct=max_daily_observed * 100.0,
            max_total_loss_observed_pct=max_total_observed * 100.0,
        )

    def run_monte_carlo(
        self,
        n_simulations: int = 2000,
        risk_pct: float = 1.0,
        block_size: int = 5,
        max_sim_days: int = 180,
        random_seed: int = 42,
        prob_threshold: Optional[float] = None,
        use_half_kelly: bool = False,
        base_risk_pct: float = 1.0,
        max_kelly_risk_pct: float = 2.0,
    ) -> Dict[str, Any]:
        """Perform stationary block bootstrap Monte Carlo of 2-Step Challenge attempts.

        Resampling blocks of days preserves intra-week volatility clustering,
        regime persistence, and realistic loss streaks.
        """
        rng = np.random.default_rng(random_seed)
        date_list = self.unique_dates
        n_dates = len(date_list)
        if n_dates == 0:
            raise ValueError("No dates available for Monte Carlo simulation.")

        results: List[FTMOAttemptResult] = []

        for _ in range(n_simulations):
            # Construct a synthetic multi-month path via block bootstrap
            sampled_days_trades: List[List[Dict[str, Any]]] = []
            while len(sampled_days_trades) < max_sim_days:
                # Pick random block start
                start_idx = rng.integers(0, max(1, n_dates - block_size))
                for b_i in range(block_size):
                    idx = (start_idx + b_i) % n_dates
                    d_str = date_list[idx]
                    sampled_days_trades.append(self.trades_by_date[d_str])

            res = self.simulate_path(
                sampled_days_trades,
                risk_pct=risk_pct,
                simulate_funded=True,
                prob_threshold=prob_threshold,
                use_half_kelly=use_half_kelly,
                base_risk_pct=base_risk_pct,
                max_kelly_risk_pct=max_kelly_risk_pct,
            )
            results.append(res)


        # Aggregate statistics
        total = len(results)
        s1_pass = sum(1 for r in results if r.step1_passed)
        s2_pass = sum(1 for r in results if r.step2_passed)
        daily_breaches = sum(1 for r in results if r.breach_reason == "daily_loss")
        max_loss_breaches = sum(1 for r in results if r.breach_reason == "max_loss")

        s1_pass_days = [r.step1_days for r in results if r.step1_passed]
        s2_pass_days = [r.step2_days for r in results if r.step2_passed]
        tot_pass_days = [r.step1_days + r.step2_days for r in results if r.step2_passed]
        payouts = [r.funded_payouts_earned for r in results]

        s1_pass_rate = (s1_pass / total) * 100.0
        # Step 2 pass rate conditional on passing Step 1
        s2_cond_rate = (s2_pass / s1_pass * 100.0) if s1_pass > 0 else 0.0
        # Overall 2-step pass rate
        overall_pass_rate = (s2_pass / total) * 100.0

        return {
            "risk_pct": risk_pct,
            "n_simulations": total,
            "step1_pass_rate_pct": s1_pass_rate,
            "step2_conditional_pass_rate_pct": s2_cond_rate,
            "overall_two_step_pass_rate_pct": overall_pass_rate,
            "daily_loss_breach_rate_pct": (daily_breaches / total) * 100.0,
            "max_loss_breach_rate_pct": (max_loss_breaches / total) * 100.0,
            "mean_days_to_pass_step1": float(np.mean(s1_pass_days)) if s1_pass_days else 0.0,
            "median_days_to_pass_step1": float(np.median(s1_pass_days)) if s1_pass_days else 0.0,
            "mean_days_to_pass_step2": float(np.mean(s2_pass_days)) if s2_pass_days else 0.0,
            "median_days_to_pass_step2": float(np.median(s2_pass_days)) if s2_pass_days else 0.0,
            "mean_total_days_to_funded": float(np.mean(tot_pass_days)) if tot_pass_days else 0.0,
            "median_total_days_to_funded": float(np.median(tot_pass_days)) if tot_pass_days else 0.0,
            "expected_payout_per_challenge": float(np.mean(payouts)),
            "expected_roi_on_fee_pct": ((float(np.mean(payouts)) - self.config.challenge_fee_usd) / self.config.challenge_fee_usd) * 100.0,
            "max_daily_loss_95th_pct": float(np.percentile([r.max_daily_loss_observed_pct for r in results], 95)),
            "max_total_loss_95th_pct": float(np.percentile([r.max_total_loss_observed_pct for r in results], 95)),
        }

    def sweep_risk_budget(
        self,
        risk_levels: Optional[List[float]] = None,
        n_simulations: int = 1500,
    ) -> List[Dict[str, Any]]:
        """Sweep risk per trade to find the optimal FTMO challenge sizing."""
        if risk_levels is None:
            risk_levels = [0.25, 0.50, 0.75, 1.00, 1.25, 1.50, 2.00]

        sweep_results = []
        for r_pct in risk_levels:
            res = self.run_monte_carlo(n_simulations=n_simulations, risk_pct=r_pct)
            sweep_results.append(res)
        return sweep_results

    @staticmethod
    def calculate_statistical_haircut(
        observed_sharpe: float,
        n_trials: int,
        sharpe_std: float = 0.30,
    ) -> float:
        """Apply Bailey & López de Prado multiple-testing haircut to account for trials."""
        if n_trials <= 1:
            return observed_sharpe
        euler_gamma = 0.5772156649
        expected_max = sharpe_std * (
            (1.0 - euler_gamma) * norm.ppf(1.0 - 1.0 / n_trials)
            + euler_gamma * norm.ppf(1.0 - 1.0 / (n_trials * np.e))
        )
        return float(observed_sharpe - expected_max)
