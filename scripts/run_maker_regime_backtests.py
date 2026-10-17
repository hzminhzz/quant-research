"""Run event-driven backtests for Maker Execution & Regime-Conditioned TSMOM using ml4t.backtest."""

import json
from pathlib import Path
import numpy as np
import polars as pl
from scipy import stats

from ml4t.backtest import Strategy, Engine, DataFeed, BacktestConfig
from ml4t.backtest.config import ShareType, CommissionType, SlippageType

FEATURES_PATH = Path("data/features/crypto_tsmom_features.parquet")
RUN_LOG_DIR = Path("run_log/crypto_tsmom_maker_regime")
RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)

DEV_START = pl.datetime(2021, 1, 1, 0, 0, 0, time_zone="UTC")
DEV_END = pl.datetime(2024, 12, 31, 23, 59, 59, time_zone="UTC")

INITIAL_CASH = 10000.0
MAKER_COMMISSION_RATE = 0.00018  # 1.8 bps maker fee
MAKER_SLIPPAGE_RATE = 0.00000    # 0.0 bps slippage


class MakerBaselineVolTargetedStrategy(Strategy):
    """Trial 1: Volatility-Targeted TSMOM under Maker Execution."""
    def on_data(self, timestamp, data, context, broker):
        for sym, bar in data.items():
            sig = bar["signals"].get("roc_168")
            vol_w = bar["signals"].get("vol_scaled_weight", 0.20)
            if sig is None or vol_w is None:
                continue
            pos = broker.get_position(sym)
            is_long = pos is not None and pos.quantity > 0

            if sig > 0.0 and not is_long:
                broker.order_target_percent(sym, float(vol_w))
            elif sig <= 0.0 and is_long:
                broker.order_target_percent(sym, 0.0)


class ContinuousRegimeScaledStrategy(Strategy):
    """Trial 2: Multi-Factor Regime-Scaled TSMOM (ADX + Vol Rank)."""
    def on_data(self, timestamp, data, context, broker):
        for sym, bar in data.items():
            sig = bar["signals"].get("roc_168")
            regime_w = bar["signals"].get("regime_scaled_weight", 0.20)
            if sig is None or regime_w is None:
                continue
            pos = broker.get_position(sym)
            is_long = pos is not None and pos.quantity > 0

            if sig > 0.0 and not is_long:
                broker.order_target_percent(sym, float(regime_w))
            elif sig <= 0.0 and is_long:
                broker.order_target_percent(sym, 0.0)


class ChoppinessFilteredMakerStrategy(Strategy):
    """Trial 3: Choppiness-Filtered TSMOM under Maker Execution."""
    def on_data(self, timestamp, data, context, broker):
        for sym, bar in data.items():
            sig = bar["signals"].get("roc_168")
            chop = bar["signals"].get("choppiness_index", 50.0)
            regime_w = bar["signals"].get("regime_scaled_weight", 0.20)
            if sig is None or chop is None or regime_w is None:
                continue
            pos = broker.get_position(sym)
            is_long = pos is not None and pos.quantity > 0

            # Suppress entry during consolidation (choppiness_index > 55)
            if sig > 0.0 and chop <= 55.0 and not is_long:
                broker.order_target_percent(sym, float(regime_w))
            elif (sig <= 0.0 or chop > 60.0) and is_long:
                broker.order_target_percent(sym, 0.0)


def compute_dsr(observed_sr_annual: float, n_trials: int, all_annual_sharpes: list[float], n_obs_daily: int = 1461) -> float:
    daily_srs = [s / np.sqrt(365.25) for s in all_annual_sharpes]
    obs_daily = observed_sr_annual / np.sqrt(365.25)
    sr_std = float(np.std(daily_srs)) if len(daily_srs) > 1 and np.std(daily_srs) > 1e-6 else 0.01

    euler_mascheroni = 0.5772156649
    e_max_sr = sr_std * (
        (1 - euler_mascheroni) * stats.norm.ppf(1 - 1.0 / n_trials)
        + euler_mascheroni * stats.norm.ppf(1 - 1.0 / (n_trials * np.e))
    )
    sr_se = 1.0 / np.sqrt(n_obs_daily - 1)
    test_stat = (obs_daily - e_max_sr) / sr_se
    return float(stats.norm.cdf(test_stat))


def run_trials():
    print("Loading development feature panel...")
    df = (
        pl.scan_parquet(FEATURES_PATH)
        .filter((pl.col("timestamp") >= DEV_START) & (pl.col("timestamp") <= DEV_END))
        .collect()
        .sort(["symbol", "timestamp"])
    )

    prices_df = df.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
    signals_df = df.select(["timestamp", "symbol", "roc_168", "vol_scaled_weight", "regime_scaled_weight", "choppiness_index", "vol_rank_90d"])

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
        ("trial_1_maker_execution_baseline", MakerBaselineVolTargetedStrategy(), "Volatility-Targeted TSMOM (Maker Fills)"),
        ("trial_2_continuous_regime_scaled", ContinuousRegimeScaledStrategy(), "Continuous Regime-Scaled TSMOM (ADX + Vol Rank)"),
        ("trial_3_choppiness_filtered_maker", ChoppinessFilteredMakerStrategy(), "Choppiness-Filtered Regime TSMOM (Maker Fills)"),
    ]

    all_prior_sharpes = [0.237, 0.198, 0.208, 0.240, 0.211, 0.128, 0.129]
    trial_equity_frames = {}

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
        sharpe = float(m.get("sharpe", 0.0))
        max_dd = float(m.get("max_drawdown", 0.0))
        total_costs = float(m.get("total_costs", 0.0))
        total_comm = float(m.get("total_commission", 0.0))
        total_slip = float(m.get("total_slippage", 0.0))
        final_val = float(m.get("final_value", INITIAL_CASH))
        gross_pnl = float(m.get("total_gross_pnl", 0.0))
        fee_drag = float(total_costs / gross_pnl * 100.0) if gross_pnl > 0 else 100.0

        all_prior_sharpes.append(sharpe)
        trial_equity_frames[trial_id] = res.to_equity_dataframe()

        print(f"  Final Value:      ${final_val:,.2f} ({total_ret*100:+.2f}%)")
        print(f"  Sharpe Ratio:     {sharpe:.3f}")
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
                "annualized_sharpe": sharpe,
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
                "min_sharpe_0_80": sharpe >= 0.80,
                "max_drawdown_25_pct": max_dd <= 0.25,
                "fee_drag_under_20_pct": fee_drag <= 20.0,
            }
        }
        trial_dir = RUN_LOG_DIR / trial_id
        trial_dir.mkdir(parents=True, exist_ok=True)
        res_file = trial_dir / "result.json"
        with res_file.open("w") as f:
            json.dump(record, f, indent=2)
        print(f"  Saved result artifact to {res_file}")

    # Trial 4: Regime-Sliced Diagnostics & DSR Audit
    best_sharpe = max(all_prior_sharpes)
    total_trials_count = len(all_prior_sharpes)
    dsr_prob = compute_dsr(best_sharpe, total_trials_count, all_prior_sharpes, n_obs_daily=1461)

    print(f"\n==================================================")
    print(f"Trial 4: Regime Slicing & Cumulative DSR Audit")
    print(f"==================================================")
    print(f"  Total Trials Evaluated Across All Sessions: {total_trials_count}")
    print(f"  Peak Development Sharpe:                    {best_sharpe:.3f}")
    print(f"  Deflated Sharpe Ratio (DSR):                {dsr_prob:.4f}")

    # Regime-slicing for Trial 2
    eq2 = trial_equity_frames["trial_2_continuous_regime_scaled"].with_columns(
        pl.col("timestamp").dt.cast_time_unit("ms")
    )
    # Join with btc vol rank to slice returns by regime tercile
    btc_regime = df.filter(pl.col("symbol") == "BTCUSDT").select(["timestamp", "vol_rank_90d"])
    eq_joined = eq2.join(btc_regime, on="timestamp", how="inner")
    low_vol = eq_joined.filter(pl.col("vol_rank_90d") < 0.33)["return"]
    mid_vol = eq_joined.filter((pl.col("vol_rank_90d") >= 0.33) & (pl.col("vol_rank_90d") < 0.66))["return"]
    high_vol = eq_joined.filter(pl.col("vol_rank_90d") >= 0.66)["return"]

    def ann_sr(s):
        return float(s.mean() / s.std() * np.sqrt(8760)) if s.std() > 0 else 0.0

    regime_breakdown = {
        "low_volatility": {"observations": len(low_vol), "annualized_sharpe": ann_sr(low_vol)},
        "mid_volatility": {"observations": len(mid_vol), "annualized_sharpe": ann_sr(mid_vol)},
        "high_volatility": {"observations": len(high_vol), "annualized_sharpe": ann_sr(high_vol)},
    }
    print("  Regime-Sliced Sharpe Breakdown:", regime_breakdown)

    trial_4_record = {
        "trial_id": "trial_4_regime_sliced_dsr_audit",
        "description": "Regime-sliced performance attribution and DSR audit across 10 cumulative trials",
        "regime_attribution": regime_breakdown,
        "multiple_testing": {
            "cumulative_trials_count": total_trials_count,
            "all_evaluated_sharpes": all_prior_sharpes,
            "best_sharpe": best_sharpe,
            "deflated_sharpe_probability": dsr_prob,
        },
        "falsifier_checks": {
            "min_dsr_probability_0_80": dsr_prob >= 0.80,
        }
    }
    trial_4_dir = RUN_LOG_DIR / "trial_4_regime_sliced_dsr_audit"
    trial_4_dir.mkdir(parents=True, exist_ok=True)
    with (trial_4_dir / "result.json").open("w") as f:
        json.dump(trial_4_record, f, indent=2)
    print(f"  Saved Trial 4 artifact to {trial_4_dir / 'result.json'}")


if __name__ == "__main__":
    run_trials()
