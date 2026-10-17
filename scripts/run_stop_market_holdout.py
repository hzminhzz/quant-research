"""Out-of-sample holdout simulation of Two-Stage Funnel with Stop Market Order execution."""

import json
from pathlib import Path
import numpy as np
import polars as pl

from ml4t.backtest import Strategy, Engine, DataFeed, BacktestConfig, OrderType, OrderSide
from ml4t.backtest.config import ShareType, CommissionType, SlippageType, StopFillMode

FEATURES_PATH = Path("data/features/crypto_tsmom_two_stage_funnel_features.parquet")
OUT_DIR = Path("run_log/crypto_tsmom_two_stage_funnel_stop_exec")
OUT_DIR.mkdir(parents=True, exist_ok=True)

OOS_START = pl.datetime(2025, 1, 1, 0, 0, 0, time_zone="UTC")
OOS_END = pl.datetime(2026, 7, 31, 23, 59, 59, time_zone="UTC")

INITIAL_CASH = 10000.0
TAKER_FEE = 0.00045   # 4.5 bps
TAKER_SLIP = 0.00015  # 1.5 bps
MAKER_FEE = 0.00018   # 1.8 bps
MAKER_SLIP = 0.00000  # 0.0 bps

df = pl.read_parquet(FEATURES_PATH).sort(["symbol", "timestamp"])


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


class StopMarketBreakoutStrategy(Strategy):
    def __init__(self, offset: float = 0.002):
        super().__init__()
        self.offset = offset

    def on_data(self, timestamp, data, context, broker):
        acct_val = broker.get_account_value() if hasattr(broker, "get_account_value") else broker.get_cash()
        if acct_val <= 0:
            return

        for sym, bar in data.items():
            is_leader = bar["signals"].get("is_selected_leader", 0.0) == 1.0
            vol_w = bar["signals"].get("vol_scaled_weight", 0.10)
            pos = broker.get_position(sym)
            is_long = pos is not None and pos.quantity > 0

            if not is_leader and is_long:
                broker.order_target_percent(sym, 0.0)
                continue

            if is_leader and not is_long:
                for o in list(broker.get_pending_orders()):
                    if o.asset == sym:
                        broker.cancel_order(o.order_id)

                stop_price = bar["close"] * (1.0 + self.offset)
                notional = acct_val * min(float(vol_w), 0.20)
                qty = notional / stop_price
                if qty > 0 and stop_price > 0:
                    broker.submit_order(
                        asset=sym,
                        quantity=qty,
                        side=OrderSide.BUY,
                        order_type=OrderType.STOP,
                        stop_price=stop_price,
                    )


class PassiveMakerStrategy(Strategy):
    def on_data(self, timestamp, data, context, broker):
        for sym, bar in data.items():
            is_leader = bar["signals"].get("is_selected_leader", 0.0) == 1.0
            vol_w = bar["signals"].get("vol_scaled_weight", 0.10)
            pos = broker.get_position(sym)
            is_long = pos is not None and pos.quantity > 0

            if not is_leader and is_long:
                broker.order_target_percent(sym, 0.0)
            elif is_leader and not is_long:
                broker.order_target_percent(sym, min(float(vol_w), 0.20))


def run_holdout_simulation():
    print("Filtering 19-month out-of-sample holdout (2025-2026)...")
    oos = df.filter((pl.col("timestamp") >= OOS_START) & (pl.col("timestamp") <= OOS_END))
    active_syms = oos.filter(pl.col("is_in_top10_universe") == 1.0)["symbol"].unique().to_list()
    oos_sub = oos.filter(pl.col("symbol").is_in(active_syms))

    prices_df = oos_sub.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
    signals_df = oos_sub.select(["timestamp", "symbol", "is_selected_leader", "vol_scaled_weight", "is_in_top10_universe"])

    # 1. Buy & Hold benchmark
    f_bnh = DataFeed(prices_df=prices_df, signals_df=signals_df)
    cfg_bnh = BacktestConfig(initial_cash=INITIAL_CASH, share_type=ShareType.FRACTIONAL)
    r_bnh = Engine(f_bnh, DynamicBnH(), cfg_bnh).run()
    d_bnh = r_bnh.to_daily_returns()
    sr_bnh = float(d_bnh.mean() / d_bnh.std() * np.sqrt(365.25)) if d_bnh.std() > 0 else 0.0

    # 2. Stop Market Breakout Strategy (Taker)
    f_stop = DataFeed(prices_df=prices_df, signals_df=signals_df)
    cfg_stop = BacktestConfig(
        initial_cash=INITIAL_CASH,
        share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=TAKER_FEE,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=TAKER_SLIP,
        stop_fill_mode=StopFillMode.STOP_PRICE,
    )
    r_stop = Engine(f_stop, StopMarketBreakoutStrategy(offset=0.002), cfg_stop).run()
    d_stop = r_stop.to_daily_returns()
    sr_stop = float(d_stop.mean() / d_stop.std() * np.sqrt(365.25)) if d_stop.std() > 0 else 0.0

    # 3. Passive Maker Strategy
    f_maker = DataFeed(prices_df=prices_df, signals_df=signals_df)
    cfg_maker = BacktestConfig(
        initial_cash=INITIAL_CASH,
        share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=MAKER_FEE,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=MAKER_SLIP,
    )
    r_maker = Engine(f_maker, PassiveMakerStrategy(), cfg_maker).run()
    d_maker = r_maker.to_daily_returns()
    sr_maker = float(d_maker.mean() / d_maker.std() * np.sqrt(365.25)) if d_maker.std() > 0 else 0.0

    ret_b = float(r_bnh.metrics.get("total_return", 0.0))
    dd_b = float(r_bnh.metrics.get("max_drawdown", 0.0))

    ret_s = float(r_stop.metrics.get("total_return", 0.0))
    dd_s = float(r_stop.metrics.get("max_drawdown", 0.0))
    trades_s = len(r_stop.trades)
    costs_s = float(r_stop.metrics.get("total_costs", 0.0))

    ret_m = float(r_maker.metrics.get("total_return", 0.0))
    dd_m = float(r_maker.metrics.get("max_drawdown", 0.0))
    trades_m = len(r_maker.trades)
    costs_m = float(r_maker.metrics.get("total_costs", 0.0))

    print("\n" + "=" * 70)
    print("=== 19-MONTH OUT-OF-SAMPLE HOLDOUT (2025-01-01 to 2026-07-31) ===")
    print("=" * 70)
    print(f"Market Buy & Hold:      Return: {ret_b*100:+6.2f}% | MaxDD: {dd_b*100:5.2f}% | Daily Sharpe: {sr_bnh:5.2f}")
    print(f"Stop Market Strategy:   Return: {ret_s*100:+6.2f}% | MaxDD: {dd_s*100:5.2f}% | Daily Sharpe: {sr_stop:5.2f} | Trades: {trades_s} | Costs: ${costs_s:,.2f}")
    print(f"Passive Maker Strategy: Return: {ret_m*100:+6.2f}% | MaxDD: {dd_m*100:5.2f}% | Daily Sharpe: {sr_maker:5.2f} | Trades: {trades_m} | Costs: ${costs_m:,.2f}")
    print(f"\nNet Alpha (Stop vs BnH):  {ret_s*100 - ret_b*100:+6.2f}%")
    print(f"Net Alpha (Maker vs BnH): {ret_m*100 - ret_b*100:+6.2f}%")

    out_record = {
        "holdout_period": "2025-01-01 to 2026-07-31 (19 Months)",
        "buy_and_hold": {"return_pct": round(ret_b * 100, 2), "max_dd_pct": round(dd_b * 100, 2), "sharpe": round(sr_bnh, 2)},
        "stop_market_strategy": {"return_pct": round(ret_s * 100, 2), "max_dd_pct": round(dd_s * 100, 2), "sharpe": round(sr_stop, 2), "trades": trades_s, "costs": costs_s, "alpha_vs_bnh_pct": round(ret_s * 100 - ret_b * 100, 2)},
        "passive_maker_strategy": {"return_pct": round(ret_m * 100, 2), "max_dd_pct": round(dd_m * 100, 2), "sharpe": round(sr_maker, 2), "trades": trades_m, "costs": costs_m, "alpha_vs_bnh_pct": round(ret_m * 100 - ret_b * 100, 2)},
    }
    with (OUT_DIR / "holdout_execution_comparison.json").open("w") as f:
        json.dump(out_record, f, indent=2)


if __name__ == "__main__":
    run_holdout_simulation()
