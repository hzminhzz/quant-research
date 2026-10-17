"""Crisis stress testing and side-by-side audit of Stop Market execution."""

import json
from pathlib import Path
import polars as pl

from ml4t.backtest import Strategy, Engine, DataFeed, BacktestConfig, OrderType, OrderSide
from ml4t.backtest.config import ShareType, CommissionType, SlippageType, StopFillMode

FEATURES_PATH = Path("data/features/crypto_tsmom_two_stage_funnel_features.parquet")
OUT_DIR = Path("run_log/crypto_tsmom_two_stage_funnel_stop_exec")
OUT_DIR.mkdir(parents=True, exist_ok=True)

INITIAL_CASH = 10000.0
TAKER_FEE = 0.00045   # 4.5 bps
TAKER_SLIP = 0.00015  # 1.5 bps

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


def run_stress():
    crises = [
        ("Terra-Luna Collapse", "2022-05-05", "2022-05-18"),
        ("FTX Contagion Shock", "2022-11-05", "2022-11-22"),
    ]

    stress_records = []
    print("\n" + "=" * 65)
    print("PHASE 4: HISTORICAL CRISIS STRESS TESTING (STOP MARKET MODEL)")
    print("=" * 65)

    for name, s_date, e_date in crises:
        sub = df.filter(
            (pl.col("timestamp") >= pl.datetime(int(s_date[:4]), int(s_date[5:7]), int(s_date[8:10]), time_zone="UTC")) &
            (pl.col("timestamp") <= pl.datetime(int(e_date[:4]), int(e_date[5:7]), int(e_date[8:10]), 23, 59, 59, time_zone="UTC"))
        )
        active_syms = sub.filter(pl.col("is_in_top10_universe") == 1.0)["symbol"].unique().to_list()
        sub_filtered = sub.filter(pl.col("symbol").is_in(active_syms))

        prices_df = sub_filtered.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
        signals_df = sub_filtered.select(["timestamp", "symbol", "is_selected_leader", "vol_scaled_weight", "is_in_top10_universe"])

        # BnH
        feed1 = DataFeed(prices_df=prices_df, signals_df=signals_df)
        cfg1 = BacktestConfig(initial_cash=INITIAL_CASH, share_type=ShareType.FRACTIONAL)
        res_bnh = Engine(feed1, DynamicBnH(), cfg1).run()

        # Stop Market Strat
        feed2 = DataFeed(prices_df=prices_df, signals_df=signals_df)
        cfg2 = BacktestConfig(
            initial_cash=INITIAL_CASH,
            share_type=ShareType.FRACTIONAL,
            commission_type=CommissionType.PERCENTAGE,
            commission_rate=TAKER_FEE,
            slippage_type=SlippageType.PERCENTAGE,
            slippage_rate=TAKER_SLIP,
            stop_fill_mode=StopFillMode.STOP_PRICE,
        )
        res_stop = Engine(feed2, StopMarketBreakoutStrategy(), cfg2).run()

        ret_b = float(res_bnh.metrics.get("total_return", 0.0))
        dd_b = float(res_bnh.metrics.get("max_drawdown", 0.0))
        ret_s = float(res_stop.metrics.get("total_return", 0.0))
        dd_s = float(res_stop.metrics.get("max_drawdown", 0.0))

        record = {
            "crisis": name,
            "period": f"{s_date} to {e_date}",
            "market_bnh_drop": round(ret_b * 100, 2),
            "market_bnh_max_dd": round(dd_b * 100, 2),
            "stop_market_loss": round(ret_s * 100, 2),
            "stop_market_max_dd": round(dd_s * 100, 2),
            "survived_under_20_pct": dd_s <= 0.20,
        }
        stress_records.append(record)
        print(f"\n--- {name} ---")
        print(f"  Market Buy & Hold Drop: {ret_b*100:+6.2f}% (MaxDD: {dd_b*100:5.2f}%)")
        print(f"  Stop Market Strat Loss: {ret_s*100:+6.2f}% (MaxDD: {dd_s*100:5.2f}%) -> SURVIVED: {dd_s <= 0.20}")

    with (OUT_DIR / "crisis_stress_testing_results.json").open("w") as f:
        json.dump(stress_records, f, indent=2)


if __name__ == "__main__":
    run_stress()
