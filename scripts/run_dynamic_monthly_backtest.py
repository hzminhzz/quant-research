"""Event-driven simulation of Dynamic Monthly Rolling Universe TSMOM Strategy."""

import json
from pathlib import Path
import numpy as np
import polars as pl

from ml4t.backtest import Strategy, Engine, DataFeed, BacktestConfig
from ml4t.backtest.config import ShareType, CommissionType, SlippageType

FEATURES_PATH = Path("data/features/crypto_tsmom_dynamic_top10_features.parquet")
OUT_DIR = Path("run_log/dynamic_universe")
OUT_DIR.mkdir(parents=True, exist_ok=True)

df = pl.read_parquet(FEATURES_PATH).sort(["symbol", "timestamp"])


class DynamicRollingUniverseTSMOM(Strategy):
    """Dynamically trades Point-in-Time Top 10 coins. Exits when dropped from universe."""

    def on_data(self, timestamp, data, context, broker):
        for sym, bar in data.items():
            in_universe = bar["signals"].get("is_in_top10_universe", 0.0) == 1.0
            sig = bar["signals"].get("roc_168")
            vol_w = bar["signals"].get("vol_scaled_weight", 0.10)

            pos = broker.get_position(sym)
            is_long = pos is not None and pos.quantity > 0

            # Rule 1: Dropped from Top 10 -> Force liquidation to cash
            if not in_universe and is_long:
                broker.order_target_percent(sym, 0.0)
                continue

            # Rule 2: In Top 10 -> Follow TSMOM trend signals
            if in_universe:
                if sig is not None and sig > 0.0 and not is_long:
                    # Enter long with volatility-targeted risk parity weight
                    w = float(np.clip(float(vol_w), 0.02, 0.15))
                    broker.order_target_percent(sym, w)
                elif sig is not None and sig <= 0.0 and is_long:
                    broker.order_target_percent(sym, 0.0)


class DynamicBuyAndHold(Strategy):
    """Dynamic benchmark: equal-weight across current month's Top 10 coins."""

    def on_data(self, timestamp, data, context, broker):
        for sym, bar in data.items():
            in_universe = bar["signals"].get("is_in_top10_universe", 0.0) == 1.0
            pos = broker.get_position(sym)
            is_long = pos is not None and pos.quantity > 0

            if not in_universe and is_long:
                broker.order_target_percent(sym, 0.0)
            elif in_universe and not is_long:
                broker.order_target_percent(sym, 0.10)


def evaluate_dynamic_run(start_dt, end_dt, label):
    sub = df.filter((pl.col("timestamp") >= start_dt) & (pl.col("timestamp") <= end_dt))
    
    # Only include symbols that appeared in the universe during this specific window
    active_symbols = sub.filter(pl.col("is_in_top10_universe") == 1.0)["symbol"].unique().to_list()
    sub_filtered = sub.filter(pl.col("symbol").is_in(active_symbols))
    print(f"\nProcessing {label}: {sub_filtered.shape[0]} rows across {len(active_symbols)} active universe symbols.")

    prices_df = sub_filtered.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
    signals_df = sub_filtered.select(["timestamp", "symbol", "roc_168", "vol_scaled_weight", "is_in_top10_universe"])

    cfg = BacktestConfig(
        initial_cash=10000.0,
        share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=0.00018,  # 1.8 bps maker
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=0.0,
    )

    # 1. Dynamic BnH
    feed1 = DataFeed(prices_df=prices_df, signals_df=signals_df)
    res_bnh = Engine(feed1, DynamicBuyAndHold(), cfg).run()
    d_bnh = res_bnh.to_daily_returns()
    sr_bnh = float(d_bnh.mean() / d_bnh.std() * np.sqrt(365.25)) if d_bnh.std() > 0 else 0.0

    # 2. Dynamic TSMOM
    feed2 = DataFeed(prices_df=prices_df, signals_df=signals_df)
    res_strat = Engine(feed2, DynamicRollingUniverseTSMOM(), cfg).run()
    d_strat = res_strat.to_daily_returns()
    sr_strat = float(d_strat.mean() / d_strat.std() * np.sqrt(365.25)) if d_strat.std() > 0 else 0.0

    ret_bnh = float(res_bnh.metrics.get("total_return", 0.0))
    dd_bnh = float(res_bnh.metrics.get("max_drawdown", 0.0))
    ret_strat = float(res_strat.metrics.get("total_return", 0.0))
    dd_strat = float(res_strat.metrics.get("max_drawdown", 0.0))
    trades_strat = int(res_strat.metrics.get("num_trades", 0))
    costs_strat = float(res_strat.metrics.get("total_costs", 0.0))
    gross_strat = float(res_strat.metrics.get("total_gross_pnl", 0.0))
    fee_drag = float(costs_strat / gross_strat * 100.0) if gross_strat > 0 else 100.0

    print("=" * 65)
    print(f"=== {label} ===")
    print("=" * 65)
    print(f"  Dynamic Buy & Hold: Return: {ret_bnh*100:+7.2f}% | MaxDD: {dd_bnh*100:5.2f}% | Sharpe: {sr_bnh:5.2f}")
    print(f"  Dynamic TSMOM:      Return: {ret_strat*100:+7.2f}% | MaxDD: {dd_strat*100:5.2f}% | Sharpe: {sr_strat:5.2f}")
    print(f"  Total Trades:       {trades_strat} | Fee Drag: {fee_drag:.2f}% (${costs_strat:,.2f})")
    print(f"  Net Alpha over BnH: {ret_strat*100 - ret_bnh*100:+7.2f}%")

    return {
        "period": label,
        "active_symbols_count": len(active_symbols),
        "bnh_return_pct": round(ret_bnh * 100, 2),
        "bnh_max_dd_pct": round(dd_bnh * 100, 2),
        "bnh_sharpe": round(sr_bnh, 2),
        "strat_return_pct": round(ret_strat * 100, 2),
        "strat_max_dd_pct": round(dd_strat * 100, 2),
        "strat_sharpe": round(sr_strat, 2),
        "trades": trades_strat,
        "fee_drag_pct": round(fee_drag, 2),
        "alpha_over_bnh_pct": round(ret_strat * 100 - ret_bnh * 100, 2),
    }


def main():
    res_dev = evaluate_dynamic_run(
        pl.datetime(2021, 1, 1, time_zone="UTC"),
        pl.datetime(2024, 12, 31, 23, 59, 59, time_zone="UTC"),
        "Development Window (2021-2024)"
    )

    res_2025 = evaluate_dynamic_run(
        pl.datetime(2025, 1, 1, time_zone="UTC"),
        pl.datetime(2025, 12, 31, 23, 59, 59, time_zone="UTC"),
        "Out-Of-Sample 2025 (Full Year)"
    )

    res_2026 = evaluate_dynamic_run(
        pl.datetime(2026, 1, 1, time_zone="UTC"),
        pl.datetime(2026, 7, 31, 23, 59, 59, time_zone="UTC"),
        "Out-Of-Sample 2026 (Jan - Jul 2026)"
    )

    res_holdout = evaluate_dynamic_run(
        pl.datetime(2025, 1, 1, time_zone="UTC"),
        pl.datetime(2026, 7, 31, 23, 59, 59, time_zone="UTC"),
        "Total 19-Month Holdout (2025-2026)"
    )

    summary_file = OUT_DIR / "dynamic_rolling_backtest_summary.json"
    with summary_file.open("w") as f:
        json.dump({
            "development": res_dev,
            "oos_2025": res_2025,
            "oos_2026": res_2026,
            "oos_holdout": res_holdout,
        }, f, indent=2)
    print(f"\nSaved dynamic rolling backtest summary to {summary_file}")


if __name__ == "__main__":
    main()
