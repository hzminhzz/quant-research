"""Advanced Validation for 10-Asset Universe: Parameter Sensitivity & Crisis Stress Testing."""

import json
from pathlib import Path
import numpy as np
import polars as pl

from ml4t.backtest import Strategy, Engine, DataFeed, BacktestConfig
from ml4t.backtest.config import ShareType, CommissionType, SlippageType

FEATURES_PATH = Path("data/features/crypto_tsmom_top10_features.parquet")
OUT_DIR = Path("run_log/advanced_validation")
OUT_DIR.mkdir(parents=True, exist_ok=True)

DEV_START = pl.datetime(2021, 1, 1, 0, 0, 0, time_zone="UTC")
DEV_END = pl.datetime(2024, 12, 31, 23, 59, 59, time_zone="UTC")

df = pl.read_parquet(FEATURES_PATH).sort(["symbol", "timestamp"])


def run_sensitivity_sweep():
    print("\n=======================================================")
    print("PHASE 6.1: 10-ASSET PARAMETER SENSITIVITY SWEEP")
    print("=======================================================")

    dev_df = df.filter((pl.col("timestamp") >= DEV_START) & (pl.col("timestamp") <= DEV_END))
    
    # Add ROC_120 and ROC_240 if not present
    dev_df = dev_df.with_columns([
        ((pl.col("close") - pl.col("close").shift(120).over("symbol")) / pl.col("close").shift(120).over("symbol")).alias("roc_120"),
        ((pl.col("close") - pl.col("close").shift(240).over("symbol")) / pl.col("close").shift(240).over("symbol")).alias("roc_240"),
    ])

    lookbacks = [72, 120, 168, 240]
    target_vols = [0.15, 0.20, 0.25, 0.30]

    class Top10ParamStrat(Strategy):
        def __init__(self, lb_col, tv):
            super().__init__()
            self.lb_col = lb_col
            self.tv = tv
        def on_data(self, timestamp, data, context, broker):
            for sym, bar in data.items():
                sig = bar["signals"].get(self.lb_col)
                rvol = bar["signals"].get("realized_vol_168", 0.60)
                if sig is None or rvol is None or rvol <= 0.05: continue
                pos = broker.get_position(sym)
                is_l = pos is not None and pos.quantity > 0
                if sig > 0 and not is_l:
                    w = float(np.clip(self.tv / rvol / 10.0, 0.02, 0.20))
                    broker.order_target_percent(sym, w)
                elif sig <= 0 and is_l:
                    broker.order_target_percent(sym, 0.0)

    prices_df = dev_df.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
    signals_df = dev_df.select(["timestamp", "symbol", "roc_72", "roc_120", "roc_168", "roc_240", "realized_vol_168"])

    results = []
    for lb in lookbacks:
        lb_col = f"roc_{lb}"
        for tv in target_vols:
            feed = DataFeed(prices_df=prices_df, signals_df=signals_df)
            cfg = BacktestConfig(
                initial_cash=10000.0,
                share_type=ShareType.FRACTIONAL,
                commission_type=CommissionType.PERCENTAGE,
                commission_rate=0.00018,
                slippage_type=SlippageType.PERCENTAGE,
                slippage_rate=0.0,
            )
            res = Engine(feed, Top10ParamStrat(lb_col, tv), cfg).run()
            d_ret = res.to_daily_returns()
            daily_sr = float(d_ret.mean() / d_ret.std() * np.sqrt(365.25)) if d_ret.std() > 0 else 0.0
            tot_ret = float(res.metrics.get("total_return", 0.0))
            max_dd = float(res.metrics.get("max_drawdown", 0.0))
            results.append({
                "lookback_hours": lb,
                "target_vol": tv,
                "daily_sharpe": round(daily_sr, 3),
                "total_return_pct": round(tot_ret * 100, 2),
                "max_drawdown_pct": round(max_dd * 100, 2),
            })
            print(f"  LB: {lb:3d}h | TargetVol: {tv*100:2.0f}% -> Sharpe: {daily_sr:5.2f} | Return: {tot_ret*100:+7.2f}% | MaxDD: {max_dd*100:5.2f}%")

    robustness = sum(1 for r in results if r["daily_sharpe"] > 1.0) / len(results) * 100
    print(f"10-Asset Robustness Score (Sharpe > 1.00): {robustness:.1f}%")
    return results


def run_stress_testing():
    print("\n=======================================================")
    print("PHASE 6.2: 10-ASSET CRISIS STRESS TESTING")
    print("=======================================================")

    CRISES = [
        ("Terra-Luna Collapse", "2022-05-05", "2022-05-18"),
        ("FTX Contagion Shock", "2022-11-05", "2022-11-22"),
    ]

    class BnH10(Strategy):
        def on_data(self, timestamp, data, context, broker):
            for sym in data:
                pos = broker.get_position(sym)
                if pos is None or pos.quantity == 0:
                    broker.order_target_percent(sym, 0.10)

    class RiskParity10(Strategy):
        def on_data(self, timestamp, data, context, broker):
            for sym, bar in data.items():
                sig = bar["signals"].get("roc_168")
                vol_w = bar["signals"].get("vol_scaled_weight", 0.10)
                if sig is None or vol_w is None: continue
                pos = broker.get_position(sym)
                is_l = pos is not None and pos.quantity > 0
                if sig > 0 and not is_l:
                    broker.order_target_percent(sym, float(vol_w))
                elif sig <= 0 and is_l:
                    broker.order_target_percent(sym, 0.0)

    stress_records = []
    for name, s_date, e_date in CRISES:
        sub = df.filter(
            (pl.col("timestamp") >= pl.datetime(int(s_date[:4]), int(s_date[5:7]), int(s_date[8:10]), time_zone="UTC")) &
            (pl.col("timestamp") <= pl.datetime(int(e_date[:4]), int(e_date[5:7]), int(e_date[8:10]), 23, 59, 59, time_zone="UTC"))
        )
        prices_df = sub.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
        signals_df = sub.select(["timestamp", "symbol", "roc_168", "vol_scaled_weight"])

        # BnH
        feed1 = DataFeed(prices_df=prices_df, signals_df=signals_df)
        cfg1 = BacktestConfig(initial_cash=10000.0, share_type=ShareType.FRACTIONAL)
        res_bnh = Engine(feed1, BnH10(), cfg1).run()

        # Risk Parity Strat
        feed2 = DataFeed(prices_df=prices_df, signals_df=signals_df)
        cfg2 = BacktestConfig(
            initial_cash=10000.0, share_type=ShareType.FRACTIONAL,
            commission_type=CommissionType.PERCENTAGE, commission_rate=0.00018,
            slippage_type=SlippageType.PERCENTAGE, slippage_rate=0.0,
        )
        res_strat = Engine(feed2, RiskParity10(), cfg2).run()

        dd_bnh = float(res_bnh.metrics.get("max_drawdown", 0.0))
        ret_bnh = float(res_bnh.metrics.get("total_return", 0.0))
        dd_strat = float(res_strat.metrics.get("max_drawdown", 0.0))
        ret_strat = float(res_strat.metrics.get("total_return", 0.0))

        record = {
            "crisis": name,
            "period": f"{s_date} to {e_date}",
            "buy_and_hold_10_return_pct": round(ret_bnh * 100, 2),
            "buy_and_hold_10_drawdown_pct": round(dd_bnh * 100, 2),
            "strategy_return_pct": round(ret_strat * 100, 2),
            "strategy_drawdown_pct": round(dd_strat * 100, 2),
            "survives_under_20_pct": dd_strat <= 0.20,
        }
        stress_records.append(record)
        print(f"\n--- {name} ---")
        print(f"  10-Coin Buy & Hold Drop: {ret_bnh*100:+6.2f}% (MaxDD: {dd_bnh*100:5.2f}%)")
        print(f"  10-Coin Strategy Loss:   {ret_strat*100:+6.2f}% (MaxDD: {dd_strat*100:5.2f}%) -> SURVIVED: {dd_strat <= 0.20}")

    return stress_records


if __name__ == "__main__":
    sens = run_sensitivity_sweep()
    stress = run_stress_testing()
    with (OUT_DIR / "top10_sensitivity_and_stress.json").open("w") as f:
        json.dump({"sensitivity": sens, "stress_testing": stress}, f, indent=2)
    print("\nAdvanced validation for 10-asset universe saved successfully.")
