"""Run event-driven backtests for 10-asset universe Time-Series Momentum trials."""

import json
from pathlib import Path
import numpy as np
import polars as pl

from ml4t.backtest import Strategy, Engine, DataFeed, BacktestConfig
from ml4t.backtest.config import ShareType, CommissionType, SlippageType

FEATURES_PATH = Path("data/features/crypto_tsmom_top10_features.parquet")
RUN_LOG_DIR = Path("run_log/crypto_tsmom_top10_universe")
RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)

DEV_START = pl.datetime(2021, 1, 1, 0, 0, 0, time_zone="UTC")
DEV_END = pl.datetime(2024, 12, 31, 23, 59, 59, time_zone="UTC")

INITIAL_CASH = 10000.0
MAKER_COMMISSION_RATE = 0.00018  # 1.8 bps maker fee
MAKER_SLIPPAGE_RATE = 0.00000    # 0.0 bps slippage


class EqualWeightTSMOM10(Strategy):
    """Trial 1: Equal-weight momentum across 10 assets (max 10% weight each)."""
    def on_data(self, timestamp, data, context, broker):
        for sym, bar in data.items():
            sig = bar["signals"].get("roc_168")
            if sig is None: continue
            pos = broker.get_position(sym)
            is_l = pos is not None and pos.quantity > 0
            if sig > 0.0 and not is_l:
                broker.order_target_percent(sym, 0.10)
            elif sig <= 0.0 and is_l:
                broker.order_target_percent(sym, 0.0)


class VolTargetedRiskParity10(Strategy):
    """Trial 2: Volatility-targeted risk-parity sizing across 10 assets."""
    def on_data(self, timestamp, data, context, broker):
        for sym, bar in data.items():
            sig = bar["signals"].get("roc_168")
            vol_w = bar["signals"].get("vol_scaled_weight", 0.10)
            if sig is None or vol_w is None: continue
            pos = broker.get_position(sym)
            is_l = pos is not None and pos.quantity > 0
            if sig > 0.0 and not is_l:
                broker.order_target_percent(sym, float(vol_w))
            elif sig <= 0.0 and is_l:
                broker.order_target_percent(sym, 0.0)


class CrossSectionalTop3Momentum10(Strategy):
    """Trial 3: Cross-sectional relative momentum (top 3 coins by ROC_168)."""
    def on_data(self, timestamp, data, context, broker):
        for sym, bar in data.items():
            is_top3 = bar["signals"].get("is_top_3_momentum", 0.0)
            sig = bar["signals"].get("roc_168")
            vol_w = bar["signals"].get("vol_scaled_weight", 0.10)
            if is_top3 is None or sig is None or vol_w is None: continue
            pos = broker.get_position(sym)
            is_l = pos is not None and pos.quantity > 0
            # Only buy if in top 3 momentum AND momentum is positive
            if is_top3 == 1.0 and sig > 0.0 and not is_l:
                # 33% target weight when concentrated in top 3
                broker.order_target_percent(sym, min(float(vol_w) * 2.5, 0.33))
            elif (is_top3 == 0.0 or sig <= 0.0) and is_l:
                broker.order_target_percent(sym, 0.0)


class RegimeGatedMaker10(Strategy):
    """Trial 4: Multi-factor regime-gated maker execution across 10 assets."""
    def on_data(self, timestamp, data, context, broker):
        for sym, bar in data.items():
            sig = bar["signals"].get("roc_168")
            adx = bar["signals"].get("adx", 20.0)
            chop = bar["signals"].get("choppiness_index", 50.0)
            vol_w = bar["signals"].get("vol_scaled_weight", 0.10)
            if sig is None or vol_w is None: continue

            trend_mult = float(np.clip(adx / 25.0, 0.5, 1.5)) if adx else 1.0
            chop_ok = chop is None or chop <= 55.0

            pos = broker.get_position(sym)
            is_l = pos is not None and pos.quantity > 0

            if sig > 0.0 and chop_ok and not is_l:
                w = float(np.clip(float(vol_w) * trend_mult, 0.02, 0.20))
                broker.order_target_percent(sym, w)
            elif (sig <= 0.0 or not chop_ok) and is_l:
                broker.order_target_percent(sym, 0.0)


def run_trials():
    print("Loading 10-asset development panel...")
    df = (
        pl.scan_parquet(FEATURES_PATH)
        .filter((pl.col("timestamp") >= DEV_START) & (pl.col("timestamp") <= DEV_END))
        .collect()
        .sort(["symbol", "timestamp"])
    )

    prices_df = df.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
    signals_df = df.select([
        "timestamp", "symbol", "roc_168", "vol_scaled_weight", "is_top_3_momentum", "adx", "choppiness_index"
    ])

    cfg = BacktestConfig(
        initial_cash=INITIAL_CASH,
        allow_short_selling=False,
        share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=MAKER_COMMISSION_RATE,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=MAKER_SLIPPAGE_RATE,
    )

    trials_to_run = [
        ("trial_1_top10_equal_weight_tsmom", EqualWeightTSMOM10(), "Equal-weight TSMOM (10% max weight per coin)"),
        ("trial_2_top10_vol_targeted_risk_parity", VolTargetedRiskParity10(), "Volatility-Targeted Risk Parity TSMOM (10 coins)"),
        ("trial_3_top10_cross_sectional_top_quintile", CrossSectionalTop3Momentum10(), "Cross-Sectional Relative Momentum (Top 3 Coins)"),
        ("trial_4_top10_regime_gated_maker", RegimeGatedMaker10(), "Multi-Factor Regime-Gated 10-Asset TSMOM"),
    ]

    for trial_id, strat, desc in trials_to_run:
        print(f"\n==================================================")
        print(f"Running {trial_id}: {desc}")
        print(f"==================================================")
        feed = DataFeed(prices_df=prices_df, signals_df=signals_df)
        engine = Engine(feed, strat, cfg)
        res = engine.run()

        m = res.metrics
        num_trades = int(m.get("num_trades", 0))
        total_ret = float(m.get("total_return", 0.0))
        max_dd = float(m.get("max_drawdown", 0.0))
        total_costs = float(m.get("total_costs", 0.0))
        total_comm = float(m.get("total_commission", 0.0))
        total_slip = float(m.get("total_slippage", 0.0))
        final_val = float(m.get("final_value", INITIAL_CASH))
        gross_pnl = float(m.get("total_gross_pnl", 0.0))
        fee_drag = float(total_costs / gross_pnl * 100.0) if gross_pnl > 0 else 100.0

        daily_ret = res.to_daily_returns()
        daily_sharpe = float(daily_ret.mean() / daily_ret.std() * np.sqrt(365.25)) if daily_ret.std() > 0 else 0.0

        print(f"  Final Value:      ${final_val:,.2f} ({total_ret*100:+.2f}%)")
        print(f"  Daily Sharpe:     {daily_sharpe:.3f}")
        print(f"  Max Drawdown:     {max_dd*100:.2f}%")
        print(f"  Total Trades:     {num_trades}")
        print(f"  Total Costs:      ${total_costs:,.2f} (Fee drag: {fee_drag:.2f}%)")

        record = {
            "trial_id": trial_id,
            "description": desc,
            "period": {"start": str(DEV_START), "end": str(DEV_END)},
            "capital": {"initial": INITIAL_CASH, "final": final_val},
            "performance": {
                "total_return": total_ret,
                "annualized_daily_sharpe": daily_sharpe,
                "engine_buggy_sharpe": float(m.get("sharpe", 0.0)),
                "max_drawdown": max_dd,
                "win_rate": float(m.get("win_rate", 0.0)),
                "profit_factor": float(m.get("profit_factor", 0.0)),
            },
            "execution": {
                "trades": num_trades,
                "total_commission": total_comm,
                "total_slippage": total_slip,
                "total_costs": total_costs,
                "gross_pnl": gross_pnl,
                "fee_drag_pct": fee_drag,
            },
            "falsifier_checks": {
                "min_sharpe_1_00": daily_sharpe >= 1.00,
                "max_drawdown_20_pct": max_dd <= 0.20,
                "fee_drag_under_15_pct": fee_drag <= 15.0,
            }
        }
        trial_dir = RUN_LOG_DIR / trial_id
        trial_dir.mkdir(parents=True, exist_ok=True)
        res_file = trial_dir / "result.json"
        with res_file.open("w") as f:
            json.dump(record, f, indent=2)
        print(f"  Saved result artifact to {res_file}")


if __name__ == "__main__":
    run_trials()
