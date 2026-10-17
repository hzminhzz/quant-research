"""Event-driven simulation of Two-Stage Funnel TSMOM with Stop Market Order execution."""

import json
from pathlib import Path
import numpy as np
import polars as pl

from ml4t.backtest import Strategy, Engine, DataFeed, BacktestConfig, OrderType, OrderSide
from ml4t.backtest.config import ShareType, CommissionType, SlippageType, StopFillMode

FEATURES_PATH = Path("data/features/crypto_tsmom_two_stage_funnel_features.parquet")
RUN_LOG_DIR = Path("run_log/crypto_tsmom_two_stage_funnel_stop_exec")
RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)

DEV_START = pl.datetime(2021, 1, 1, 0, 0, 0, time_zone="UTC")
DEV_END = pl.datetime(2024, 12, 31, 23, 59, 59, time_zone="UTC")

INITIAL_CASH = 10000.0
TAKER_FEE = 0.00045   # 4.5 bps
TAKER_SLIP = 0.00015  # 1.5 bps
MAKER_FEE = 0.00018   # 1.8 bps
MAKER_SLIP = 0.00000  # 0.0 bps

df = pl.read_parquet(FEATURES_PATH).sort(["symbol", "timestamp"])


class StopMarketBreakoutStrategy(Strategy):
    """Places resting Stop Market orders above current close when a token enters Top 5 leaders."""

    def __init__(self, offset: float = 0.002):
        super().__init__()
        self.offset = offset

    def on_data(self, timestamp, data, context, broker):
        account_val = broker.get_account_value() if hasattr(broker, "get_account_value") else broker.get_cash()
        if account_val <= 0:
            return

        for sym, bar in data.items():
            is_leader = bar["signals"].get("is_selected_leader", 0.0) == 1.0
            vol_w = bar["signals"].get("vol_scaled_weight", 0.10)
            pos = broker.get_position(sym)
            is_long = pos is not None and pos.quantity > 0

            # Exit rule: evicted from leaders -> sell to cash
            if not is_leader and is_long:
                broker.order_target_percent(sym, 0.0)
                continue

            # Entry rule: is leader and flat -> place resting STOP BUY order
            if is_leader and not is_long:
                # Cancel existing pending orders for this asset to avoid duplicates
                for o in list(broker.get_pending_orders()):
                    if o.asset == sym:
                        broker.cancel_order(o.order_id)

                stop_price = bar["close"] * (1.0 + self.offset)
                target_notional = account_val * min(float(vol_w), 0.20)
                target_qty = target_notional / stop_price

                if target_qty > 0 and stop_price > 0:
                    broker.submit_order(
                        asset=sym,
                        quantity=target_qty,
                        side=OrderSide.BUY,
                        order_type=OrderType.STOP,
                        stop_price=stop_price,
                    )


class PassiveMakerStrategy(Strategy):
    """Trades via passive post-only fills at next open."""

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


def run_trials():
    print("Filtering development window (2021-2024)...")
    dev = df.filter((pl.col("timestamp") >= DEV_START) & (pl.col("timestamp") <= DEV_END))
    active_syms = dev.filter(pl.col("is_in_top10_universe") == 1.0)["symbol"].unique().to_list()
    dev_sub = dev.filter(pl.col("symbol").is_in(active_syms))

    prices_df = dev_sub.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
    signals_df = dev_sub.select(["timestamp", "symbol", "is_selected_leader", "vol_scaled_weight"])

    # Trial 1: Stop Market Breakout (+0.2% trigger, Taker Fee 4.5 bps, Slippage 1.5 bps)
    print("\n" + "=" * 65)
    print("Running Trial 1: Two-Stage Funnel Stop Market Breakout (+0.2% offset)")
    print("=" * 65)
    feed1 = DataFeed(prices_df=prices_df, signals_df=signals_df)
    cfg1 = BacktestConfig(
        initial_cash=INITIAL_CASH,
        share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=TAKER_FEE,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=TAKER_SLIP,
        stop_fill_mode=StopFillMode.STOP_PRICE,
    )
    res1 = Engine(feed1, StopMarketBreakoutStrategy(offset=0.002), cfg1).run()
    d1 = res1.to_daily_returns()
    sr1 = float(d1.mean() / d1.std() * np.sqrt(365.25)) if d1.std() > 0 else 0.0
    ret1 = float(res1.metrics.get("total_return", 0.0))
    dd1 = float(res1.metrics.get("max_drawdown", 0.0))
    trades1 = len(res1.trades)
    costs1 = float(res1.metrics.get("total_costs", 0.0))
    print(f"  Return: {ret1*100:+7.2f}% | MaxDD: {dd1*100:5.2f}% | Daily Sharpe: {sr1:5.3f} | Trades: {trades1} | Costs: ${costs1:,.2f}")

    rec1 = {
        "trial_id": "trial_1_two_stage_funnel_stop_market",
        "description": "Stop Market breakout execution at Close * 1.002 under taker friction",
        "performance": {"total_return": ret1, "daily_sharpe": sr1, "max_drawdown": dd1, "trades": trades1, "costs": costs1},
        "falsifier_checks": {"min_sharpe_1_00": sr1 >= 1.00, "max_drawdown_20_pct": dd1 <= 0.20}
    }
    with (RUN_LOG_DIR / "trial_1_two_stage_funnel_stop_market" / "result.json").open("w") as f:
        json.dump(rec1, f, indent=2)

    # Trial 2: Passive Maker Execution (1.8 bps fee, 0.0 bps slippage)
    print("\n" + "=" * 65)
    print("Running Trial 2: Two-Stage Funnel Passive Maker Execution")
    print("=" * 65)
    feed2 = DataFeed(prices_df=prices_df, signals_df=signals_df)
    cfg2 = BacktestConfig(
        initial_cash=INITIAL_CASH,
        share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=MAKER_FEE,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=MAKER_SLIP,
    )
    res2 = Engine(feed2, PassiveMakerStrategy(), cfg2).run()
    d2 = res2.to_daily_returns()
    sr2 = float(d2.mean() / d2.std() * np.sqrt(365.25)) if d2.std() > 0 else 0.0
    ret2 = float(res2.metrics.get("total_return", 0.0))
    dd2 = float(res2.metrics.get("max_drawdown", 0.0))
    trades2 = len(res2.trades)
    costs2 = float(res2.metrics.get("total_costs", 0.0))
    print(f"  Return: {ret2*100:+7.2f}% | MaxDD: {dd2*100:5.2f}% | Daily Sharpe: {sr2:5.3f} | Trades: {trades2} | Costs: ${costs2:,.2f}")

    rec2 = {
        "trial_id": "trial_2_two_stage_funnel_passive_maker",
        "description": "Passive maker execution under 1.8 bps fee and 0.0 bps slippage",
        "performance": {"total_return": ret2, "daily_sharpe": sr2, "max_drawdown": dd2, "trades": trades2, "costs": costs2},
        "falsifier_checks": {"min_sharpe_1_00": sr2 >= 1.00, "max_drawdown_20_pct": dd2 <= 0.20}
    }
    with (RUN_LOG_DIR / "trial_2_two_stage_funnel_passive_maker" / "result.json").open("w") as f:
        json.dump(rec2, f, indent=2)

    # Trial 3: Stop Offset Sensitivity Sweep (0.1%, 0.2%, 0.3%, 0.5%)
    print("\n" + "=" * 65)
    print("Running Trial 3: Stop Breakout Offset Sensitivity Sweep")
    print("=" * 65)
    sweep_results = []
    offsets = [0.001, 0.002, 0.003, 0.005]
    for off in offsets:
        f_sw = DataFeed(prices_df=prices_df, signals_df=signals_df)
        r_sw = Engine(f_sw, StopMarketBreakoutStrategy(offset=off), cfg1).run()
        d_sw = r_sw.to_daily_returns()
        sr_sw = float(d_sw.mean() / d_sw.std() * np.sqrt(365.25)) if d_sw.std() > 0 else 0.0
        ret_sw = float(r_sw.metrics.get("total_return", 0.0))
        dd_sw = float(r_sw.metrics.get("max_drawdown", 0.0))
        sweep_results.append({"offset_pct": off * 100, "sharpe": round(sr_sw, 3), "return_pct": round(ret_sw * 100, 2), "max_dd_pct": round(dd_sw * 100, 2)})
        print(f"  Offset: {off*100:4.2f}% -> Sharpe: {sr_sw:5.3f} | Return: {ret_sw*100:+7.2f}% | MaxDD: {dd_sw*100:5.2f}%")

    rec3 = {
        "trial_id": "trial_3_stop_market_sensitivity_sweep",
        "description": "Sensitivity sweep across Stop Market breakout offsets",
        "sweep_results": sweep_results,
    }
    with (RUN_LOG_DIR / "trial_3_stop_market_sensitivity_sweep" / "result.json").open("w") as f:
        json.dump(rec3, f, indent=2)


if __name__ == "__main__":
    for tid in ["trial_1_two_stage_funnel_stop_market", "trial_2_two_stage_funnel_passive_maker", "trial_3_stop_market_sensitivity_sweep"]:
        (RUN_LOG_DIR / tid).mkdir(parents=True, exist_ok=True)
    run_trials()
