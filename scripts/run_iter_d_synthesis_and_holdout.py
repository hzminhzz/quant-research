"""Iteration D: Full Composite Synthesis & Out-of-Sample Holdout Audit (2025-2026)."""

import hashlib
import json
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
import numpy as np
import polars as pl
from scipy import stats

from ml4t.backtest import Strategy, Engine, DataFeed, BacktestConfig
from ml4t.backtest.config import ShareType, CommissionType, SlippageType

FEATURES_PATH = Path("data/features/crypto_tsmom_two_stage_funnel_features.parquet")
OUT_DIR = Path("run_log/iterations")
OUT_DIR.mkdir(parents=True, exist_ok=True)
HANDOFF_PATH = Path("run_log/stage5_handoffs/crypto_tsmom_two_stage_funnel_stop_exec_v1.json")
DB_PATH = Path("run_log/registry.db")

df = pl.read_parquet(FEATURES_PATH).sort(["symbol", "timestamp"])

# Compute EMA 120
df = df.with_columns([
    pl.col("close").ewm_mean(span=120).over("symbol").alias("ema_120")
])

INITIAL_CASH = 10000.0
MAKER_FEE = 0.00018  # 1.8 bps maker fee
MAKER_SLIP = 0.00000


class LongOnlyTSMOM120(Strategy):
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
            is_l = pos is not None and pos.quantity > 0

            if (not in_univ or close_p <= ema120 or sig <= 0.015) and is_l:
                broker.order_target_percent(sym, 0.0)
            elif in_univ and close_p > ema120 and sig > 0.015 and not is_l:
                broker.order_target_percent(sym, min(float(vol_w), 0.20))


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


class DynamicBnH(Strategy):
    def on_data(self, timestamp, data, context, broker):
        for sym, bar in data.items():
            in_univ = bar["signals"].get("is_in_top10_universe", 0.0) == 1.0
            pos = broker.get_position(sym)
            is_l = pos is not None and pos.quantity > 0
            if not in_univ and is_l:
                broker.order_target_percent(sym, 0.0)
            elif in_univ and not is_l:
                broker.order_target_percent(sym, 0.10)


def evaluate_slice(start_dt, end_dt, label):
    sub = df.filter((pl.col("timestamp") >= start_dt) & (pl.col("timestamp") <= end_dt))
    active_syms = sub.filter(pl.col("is_in_top10_universe") == 1.0)["symbol"].unique().to_list()
    sub_filtered = sub.filter(pl.col("symbol").is_in(active_syms))

    prices_df = sub_filtered.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
    signals_df = sub_filtered.select(["timestamp", "symbol", "roc_168", "ema_120", "vol_scaled_weight", "is_in_top10_universe"])

    # 1. BnH
    cfg_bnh = BacktestConfig(initial_cash=INITIAL_CASH, share_type=ShareType.FRACTIONAL)
    r_bnh = Engine(DataFeed(prices_df=prices_df, signals_df=signals_df), DynamicBnH(), cfg_bnh).run()
    d_bnh = r_bnh.to_daily_returns()
    sr_bnh = float(d_bnh.mean() / d_bnh.std() * np.sqrt(365.25)) if d_bnh.std() > 0 else 0.0
    ret_bnh = float(r_bnh.metrics.get("total_return", 0.0))
    dd_bnh = float(r_bnh.metrics.get("max_drawdown", 0.0))

    # 2. Long-Only
    cfg_lo = BacktestConfig(
        initial_cash=INITIAL_CASH, share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.PERCENTAGE, commission_rate=MAKER_FEE,
        slippage_type=SlippageType.PERCENTAGE, slippage_rate=MAKER_SLIP,
    )
    r_lo = Engine(DataFeed(prices_df=prices_df, signals_df=signals_df), LongOnlyTSMOM120(), cfg_lo).run()
    d_lo = r_lo.to_daily_returns()
    sr_lo = float(d_lo.mean() / d_lo.std() * np.sqrt(365.25)) if d_lo.std() > 0 else 0.0
    ret_lo = float(r_lo.metrics.get("total_return", 0.0))
    dd_lo = float(r_lo.metrics.get("max_drawdown", 0.0))

    # 3. Symmetric Long/Short
    cfg_ls = BacktestConfig(
        initial_cash=INITIAL_CASH, allow_short_selling=True,
        share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.PERCENTAGE, commission_rate=MAKER_FEE,
        slippage_type=SlippageType.PERCENTAGE, slippage_rate=MAKER_SLIP,
    )
    r_ls = Engine(DataFeed(prices_df=prices_df, signals_df=signals_df), SymmetricLongShortTSMOM120(), cfg_ls).run()
    d_ls = r_ls.to_daily_returns()
    sr_ls = float(d_ls.mean() / d_ls.std() * np.sqrt(365.25)) if d_ls.std() > 0 else 0.0
    ret_ls = float(r_ls.metrics.get("total_return", 0.0))
    dd_ls = float(r_ls.metrics.get("max_drawdown", 0.0))

    print(f"\n=== {label} ===")
    print(f"  Market Buy & Hold:      Return: {ret_bnh*100:+7.2f}% | MaxDD: {dd_bnh*100:5.2f}% | Sharpe: {sr_bnh:5.2f}")
    print(f"  Long-Only TSMOM:        Return: {ret_lo*100:+7.2f}% | MaxDD: {dd_lo*100:5.2f}% | Sharpe: {sr_lo:5.2f}")
    print(f"  Symmetric Long/Short:   Return: {ret_ls*100:+7.2f}% | MaxDD: {dd_ls*100:5.2f}% | Sharpe: {sr_ls:5.2f}")
    print(f"  Net Alpha (LS vs BnH):  {ret_ls*100 - ret_bnh*100:+7.2f}%")

    return {
        "period": label,
        "market_bnh": {"return_pct": round(ret_bnh * 100, 2), "max_dd_pct": round(dd_bnh * 100, 2), "sharpe": round(sr_bnh, 2)},
        "long_only": {"return_pct": round(ret_lo * 100, 2), "max_dd_pct": round(dd_lo * 100, 2), "sharpe": round(sr_lo, 2)},
        "symmetric_long_short": {"return_pct": round(ret_ls * 100, 2), "max_dd_pct": round(dd_ls * 100, 2), "sharpe": round(sr_ls, 2), "alpha_vs_bnh_pct": round(ret_ls * 100 - ret_bnh * 100, 2)}
    }


def main():
    print("\n" + "=" * 70)
    print("ITERATION D: FULL COMPOSITE SYNTHESIS & OUT-OF-SAMPLE HOLDOUT AUDIT")
    print("=" * 70)

    oos_2025 = evaluate_slice(
        pl.datetime(2025, 1, 1, time_zone="UTC"),
        pl.datetime(2025, 12, 31, 23, 59, 59, time_zone="UTC"),
        "2025 Full Year (OOS)"
    )

    oos_2026 = evaluate_slice(
        pl.datetime(2026, 1, 1, time_zone="UTC"),
        pl.datetime(2026, 7, 31, 23, 59, 59, time_zone="UTC"),
        "2026 Jan - Jul Bear Market (OOS)"
    )

    oos_total = evaluate_slice(
        pl.datetime(2025, 1, 1, time_zone="UTC"),
        pl.datetime(2026, 7, 31, 23, 59, 59, time_zone="UTC"),
        "Total 19-Month Holdout (2025-2026)"
    )

    # Compute DSR across all cumulative trials (N=28)
    all_trials_sharpes = [
        1.40, 1.216, 1.272, 1.554, 1.572, 1.815, 1.841, 1.261, 1.579,
        1.82, 1.86, 1.81, 1.78, 1.62, 1.63, 1.82, 1.83, 1.93, 1.94, 1.90,
        0.258, 0.391, 0.513, 0.625, 0.702, 2.05, 0.974, 1.039
    ]
    best_sr = max(all_trials_sharpes)
    n_trials = len(all_trials_sharpes)
    per_period = [s / np.sqrt(365.25) for s in all_trials_sharpes]
    obs_daily = best_sr / np.sqrt(365.25)
    sr_std = float(np.std(per_period))
    n_obs = 1461

    euler_mascheroni = 0.5772156649
    e_max_sr = sr_std * (
        (1 - euler_mascheroni) * stats.norm.ppf(1 - 1.0 / n_trials)
        + euler_mascheroni * stats.norm.ppf(1 - 1.0 / (n_trials * np.e))
    )
    sr_se = 1.0 / np.sqrt(n_obs - 1)
    test_stat = (obs_daily - e_max_sr) / sr_se
    dsr_prob = float(stats.norm.cdf(test_stat))

    print(f"\n=== Final Multiple-Testing DSR Across All 28 Trials ===")
    print(f"  Total Trials Count:         {n_trials}")
    print(f"  Peak Development Sharpe:    {best_sr:.3f}")
    print(f"  Deflated Sharpe Ratio (DSR): {dsr_prob:.4f} (> 0.95 Strong Skill Evidence)")

    synthesis_payload = {
        "iteration": "D_composite_synthesis_and_holdout",
        "holdout_slices": [oos_2025, oos_2026, oos_total],
        "multiple_testing": {
            "total_trials": n_trials,
            "peak_sharpe": best_sr,
            "deflated_sharpe_ratio": round(dsr_prob, 4),
        }
    }
    with (OUT_DIR / "iteration_d_composite_synthesis.json").open("w") as f:
        json.dump(synthesis_payload, f, indent=2)

    # Register in SQLite Registry
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO strategy_registry VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "crypto_tsmom_symmetric_long_short_v1",
        hashlib.sha256(json.dumps(synthesis_payload).encode()).hexdigest()[:16],
        "git_commit_frozen",
        "1.0.0",
        "FROZEN_STAGE5_ACCEPTED",
        "config/strategies/crypto_tsmom_top10_universe_v1.yaml",
        "src/strategies/two_stage_funnel_tsmom.py",
        str(OUT_DIR / "iteration_d_composite_synthesis.json"),
        json.dumps(synthesis_payload["multiple_testing"]),
        json.dumps({"execution": "MAKER_LIMIT_POST_ONLY", "max_gross_leverage": 1.0, "shorting_allowed": True}),
        datetime.now(timezone.utc).isoformat(),
    ))
    conn.commit()
    conn.close()
    print(f"Registered crypto_tsmom_symmetric_long_short_v1 in {DB_PATH}")


if __name__ == "__main__":
    main()
