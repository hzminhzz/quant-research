"""Evaluate Two-Stage Funnel TSMOM on FTMO / Prop Firm Challenge rules (5% daily DD, 10% max DD)."""

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
from src.ftmo_simulator import FTMOSimulator, FTMOConfig
FEATURES_PATH = Path("data/features/crypto_tsmom_two_stage_funnel_features.parquet")
OUT_DIR = Path("run_log/prop_firm_evaluation")
OUT_DIR.mkdir(parents=True, exist_ok=True)

df = pl.read_parquet(FEATURES_PATH).sort(["symbol", "timestamp"])

df = df.with_columns([
    pl.col("close").ewm_mean(span=120).over("symbol").alias("ema_120")
])

INITIAL_CASH = 100000.0  # $100k account standard for prop firm challenges


class SymmetricLongShortTSMOM120(Strategy):
    def on_data(self, timestamp, data, context, broker):
        for sym, bar in data.items():
            in_univ = bar["signals"].get("is_in_top10_universe", 0.0) == 1.0
            sig = bar["signals"].get("roc_168")
            ema120 = bar["signals"].get("ema_120")
            vol_w = bar["signals"].get("vol_scaled_weight", 0.10)
            close_p = bar.get("close", 0.0)

            if sig is None or ema120 is None or vol_w is None or close_p is None:
                continue

            pos = broker.get_position(sym)
            current_qty = pos.quantity if pos is not None else 0.0

            if not in_univ and current_qty != 0:
                broker.order_target_percent(sym, 0.0)
                continue

            if in_univ:
                target_w = float(np.clip(float(vol_w), 0.03, 0.20))
                # Long
                if close_p > ema120 and sig > 0.015:
                    if current_qty <= 0:
                        broker.order_target_percent(sym, target_w)
                # Short
                elif close_p < ema120 and sig < -0.015:
                    if current_qty >= 0:
                        broker.order_target_percent(sym, -target_w)
                # Cash
                else:
                    if current_qty != 0:
                        broker.order_target_percent(sym, 0.0)


def extract_trades_and_daily_returns():
    active_syms = df.filter(pl.col("is_in_top10_universe") == 1.0)["symbol"].unique().to_list()
    df_sub = df.filter(pl.col("symbol").is_in(active_syms))

    prices_df = df_sub.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
    signals_df = df_sub.select(["timestamp", "symbol", "roc_168", "ema_120", "vol_scaled_weight", "is_in_top10_universe"])

    cfg = BacktestConfig(
        initial_cash=INITIAL_CASH, allow_short_selling=True,
        share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.PERCENTAGE, commission_rate=0.00018,
        slippage_type=SlippageType.PERCENTAGE, slippage_rate=0.0,
    )
    res = Engine(DataFeed(prices_df=prices_df, signals_df=signals_df), SymmetricLongShortTSMOM120(), cfg).run()

    daily_ret = res.to_daily_returns()
    return res, daily_ret


def analyze_prop_firm_viability():
    res, daily_ret = extract_trades_and_daily_returns()
    daily_arr = np.array(daily_ret.drop_nulls().to_list())

    print("\n" + "=" * 70)
    print("=== EMPIRICAL DAILY DRAWDOWN DISTRIBUTION (100k ACCOUNT) ===")
    print("=" * 70)

    # Convert trades into format expected by FTMOSimulator
    ftmo_trades = []
    for t in res.trades:
        # trade pnl as fraction of initial balance
        pnl_pct = float(t.pnl / INITIAL_CASH)
        exit_dt = str(t.exit_time)[:10] if t.exit_time else "2021-01-01"
        ftmo_trades.append({
            "date": exit_dt,
            "pnl_pct": pnl_pct,
            "r_mult": float(np.sign(pnl_pct)),
            "entry_time": str(t.entry_time) if t.entry_time else exit_dt,
            "exit_time": str(t.exit_time) if t.exit_time else exit_dt,
        })

    print(f"Total Closed Strategy Trades: {len(ftmo_trades)}")

    # Daily Loss Distribution
    daily_losses = daily_arr[daily_arr < 0]
    worst_daily_loss = float(np.min(daily_arr)) * 100.0
    days_breaching_5pct = int(np.sum(daily_arr <= -0.05))
    days_breaching_3pct = int(np.sum(daily_arr <= -0.03))
    days_breaching_2pct = int(np.sum(daily_arr <= -0.02))

    print(f"Worst Historical Single-Day Loss: {worst_daily_loss:+.2f}%")
    print(f"Days Breaching 5.0% Daily Limit:   {days_breaching_5pct} days")
    print(f"Days Exceeding -3.0% Loss:         {days_breaching_3pct} days")
    print(f"Days Exceeding -2.0% Loss:         {days_breaching_2pct} days")

    # Run Monte Carlo simulation under FTMO 2-Step Rules
    config = FTMOConfig(
        initial_balance=100000.0,
        max_daily_loss_pct=0.05,  # 5.0% hard limit
        max_total_loss_pct=0.10,  # 10.0% hard limit
        step1_target_pct=0.10,    # +10%
        step2_target_pct=0.05,    # +5%
        user_daily_halt_pct=0.025 # User safety circuit breaker: stop trading day if down 2.5%
    )

    sim = FTMOSimulator(ftmo_trades, config)

    # Test risk scalings: 1.0x (unscaled), 0.5x (half-risk), 0.35x (conservative)
    risk_scalings = [1.0, 0.5, 0.35]
    mc_results = {}

    print("\n" + "=" * 70)
    print("=== MONTE CARLO FTMO CHALLENGE SIMULATION (1,000 PATHS PER TIER) ===")
    print("=" * 70)

    for r_scale in risk_scalings:
        print(f"\n--- Testing Risk Scaling: {r_scale:.2f}x ---")
        mc = sim.run_monte_carlo(
            n_simulations=1000,
            risk_pct=r_scale,
            block_size=5,
            random_seed=42,
        )
        p_pass = float(mc.get("step1_pass_rate_pct", 0.0))
        p_funded = float(mc.get("overall_two_step_pass_rate_pct", 0.0))
        p_daily_breach = float(mc.get("daily_loss_breach_rate_pct", 0.0))
        p_max_breach = float(mc.get("max_loss_breach_rate_pct", 0.0))
        ev_payout = float(mc.get("expected_payout_per_challenge", 0.0))

        print(f"  Step 1 Pass Rate (+10% Target): {p_pass:.1f}%")
        print(f"  Funded Pass Rate (Step 1 + 2):  {p_funded:.1f}%")
        print(f"  Daily Loss Breach Rate (5% Limit): {p_daily_breach:.1f}%")
        print(f"  Max Loss Breach Rate (10% Limit):  {p_max_breach:.1f}%")
        print(f"  Expected Net Payout:            ${ev_payout:,.2f}")

        mc_results[f"scale_{r_scale}"] = {
            "risk_scaling": r_scale,
            "step1_pass_rate_pct": round(p_pass, 2),
            "funded_pass_rate_pct": round(p_funded, 2),
            "daily_breach_rate_pct": round(p_daily_breach, 2),
            "max_loss_breach_rate_pct": round(p_max_breach, 2),
            "expected_payout_usd": round(ev_payout, 2),
        }

    with (OUT_DIR / "prop_firm_evaluation_results.json").open("w") as f:
        json.dump({
            "worst_daily_loss_pct": worst_daily_loss,
            "days_breaching_5pct": days_breaching_5pct,
            "mc_results": mc_results,
        }, f, indent=2)


if __name__ == "__main__":
    analyze_prop_firm_viability()
