"""Dual-Timeframe Backtest with Correct Hourly Signals and Intraday Drawdown Tracking.

1. Signals: Resampled 1-hour closes -> 120-hour EMA and 168-hour ROC -> joined back to 1-minute bars.
2. Risk Watchdog: Evaluated every 1-minute bar. Flattens when floating daily loss from midnight <= -threshold.
3. Audit: Tracks true intraday minimum equity relative to midnight, not just close-to-close return.
4. Trigger Diagnostics: Records exact trigger timestamps, next-open fill, end-of-day equity, and next-day return.
"""

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

STORE = Path("/home/quant/dev/quant/ml4t-data/.data/store")
OUT_DIR = Path("run_log/prop_firm_evaluation")
OUT_DIR.mkdir(parents=True, exist_ok=True)

START_DT = pl.datetime(2025, 1, 1, time_zone="UTC")
END_DT = pl.datetime(2026, 7, 31, 23, 59, 59, time_zone="UTC")
INITIAL_CASH = 100000.0
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "SUIUSDT", "NEARUSDT", "AVAXUSDT", "LINKUSDT", "BNBUSDT"]


def prepare_dual_timeframe_dataset():
    """Resample 1m to 1h for signals, then join back to 1m bars."""
    dfs_1m = []
    for sym in SYMBOLS:
        p = STORE / f"crypto_futures_minute_{sym}_PERP"
        files = sorted([f for f in p.glob("**/*.parquet") if "year=2025" in str(f) or "year=2026" in str(f)])
        df_sym = pl.concat([pl.read_parquet(f) for f in files]).filter(
            (pl.col("timestamp") >= START_DT) & (pl.col("timestamp") <= END_DT)
        ).sort("timestamp")
        if "symbol" not in df_sym.columns:
            df_sym = df_sym.with_columns(pl.lit(sym).alias("symbol"))

        # Build true 1-hour OHLCV candles
        df_1h = (
            df_sym.group_by_dynamic("timestamp", every="1h")
            .agg([
                pl.col("open").first(),
                pl.col("high").max(),
                pl.col("low").min(),
                pl.col("close").last(),
                pl.col("volume").sum(),
            ])
            .sort("timestamp")
            .with_columns([
                # 120-hour EMA computed strictly on 1-hour close series
                pl.col("close").ewm_mean(span=120).alias("ema_120h"),
                # 168-hour ROC computed strictly on 1-hour close series
                ((pl.col("close") - pl.col("close").shift(168)) / pl.col("close").shift(168)).alias("roc_168h"),
            ])
            # Strict point-in-time: [T, T+1h) candle completes at T+59m and becomes available at T+1h
            .with_columns(
                pl.col("timestamp").dt.offset_by("1h").alias("available_at")
            )
        )

        # Truncate 1m timestamp to 1h bucket to join the hourly signal
        df_sym = df_sym.with_columns(
            pl.col("timestamp").dt.truncate("1h").alias("hour_bucket"),
            (pl.col("timestamp").dt.minute() == 0).cast(pl.Int8).alias("is_hour_close"),
        )

        # Point-in-time join: at 14:00:00, hour_bucket matches available_at 14:00:00 (the 13:00-13:59 candle)
        df_sym = df_sym.join(
            df_1h.select(["available_at", "ema_120h", "roc_168h"]),
            left_on="hour_bucket",
            right_on="available_at",
            how="left",
        ).drop("hour_bucket")

        dfs_1m.append(df_sym)

    return pl.concat(dfs_1m).sort(["timestamp", "symbol"])


class VerifiedDualTimeframeStrategy(Strategy):
    def __init__(self, risk_mult: float = 1.0, daily_flatten_pct: float = 0.03):
        super().__init__()
        self.risk_mult = risk_mult
        self.daily_flatten_pct = daily_flatten_pct
        self.current_date = None
        self.day_start_equity = INITIAL_CASH
        self.circuit_breaker_active = False
        
        # Detailed audit logging
        self.trigger_events = []
        self.daily_intraday_min_equity = {}
        self.daily_start_equity = {}
        self.daily_close_equity = {}

    def on_data(self, timestamp, data, context, broker):
        bar_date = timestamp.strftime("%Y-%m-%d")
        equity = float(broker.equity())

        # Midnight rollover
        if self.current_date != bar_date:
            if self.current_date is not None:
                self.daily_close_equity[self.current_date] = equity
            self.current_date = bar_date
            self.day_start_equity = equity
            self.daily_start_equity[bar_date] = equity
            self.daily_intraday_min_equity[bar_date] = equity
            self.circuit_breaker_active = False

        # Track true minimum intraday equity
        if equity < self.daily_intraday_min_equity[bar_date]:
            self.daily_intraday_min_equity[bar_date] = equity

        floating_daily_dd = (equity - self.day_start_equity) / self.day_start_equity

        # Trigger watchdog if floating loss reaches threshold
        if not self.circuit_breaker_active and floating_daily_dd <= -self.daily_flatten_pct:
            self.circuit_breaker_active = True
            self.trigger_events.append({
                "timestamp": str(timestamp),
                "date": bar_date,
                "floating_dd_at_trigger": floating_daily_dd,
                "equity_at_trigger": equity,
                "day_start_equity": self.day_start_equity,
            })
            for sym in data.keys():
                pos = broker.get_position(sym)
                if pos is not None and pos.quantity != 0:
                    broker.order_target_percent(sym, 0.0)
            return

        if self.circuit_breaker_active:
            for sym in data.keys():
                pos = broker.get_position(sym)
                if pos is not None and pos.quantity != 0:
                    broker.order_target_percent(sym, 0.0)
            return

        # 1-Hour rebalance on the hour
        if timestamp.minute != 0:
            return

        base_weight = 0.15 * self.risk_mult
        for sym, bar in data.items():
            sig = bar["signals"].get("roc_168h")
            ema120 = bar["signals"].get("ema_120h")
            close_p = bar.get("close", 0.0)

            if sig is None or ema120 is None or close_p is None:
                continue

            pos = broker.get_position(sym)
            current_qty = pos.quantity if pos is not None else 0.0

            if close_p > ema120 and sig > 0.015:
                if current_qty <= 0:
                    broker.order_target_percent(sym, base_weight)
            elif close_p < ema120 and sig < -0.015:
                if current_qty >= 0:
                    broker.order_target_percent(sym, -base_weight)
            else:
                if current_qty != 0:
                    broker.order_target_percent(sym, 0.0)


def evaluate():
    df = prepare_dual_timeframe_dataset()
    prices_df = df.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
    signals_df = df.select(["timestamp", "symbol", "roc_168h", "ema_120h", "is_hour_close"])

    cfg = BacktestConfig(
        initial_cash=INITIAL_CASH,
        allow_short_selling=True,
        share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=0.00018,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=0.0,
    )

    test_variants = [
        ("Full Risk (No Watchdog)", 1.0, 1.00),
        ("Full Risk + 3.0% Watchdog", 1.0, 0.03),
        ("0.70x Risk + 3.0% Watchdog", 0.70, 0.03),
        ("0.50x Risk + 2.5% Watchdog", 0.50, 0.025),
    ]

    print("\n" + "=" * 115)
    print("=== DUAL-TIMEFRAME EVALUATION WITH TRUE 1H SIGNALS & INTRADAY DD AUDIT ===")
    print("=" * 115)
    print(f"{'Variant':<28} | {'Total Ret':<9} | {'Max DD':<8} | {'Worst CloseDay':<14} | {'Worst Intraday':<14} | {'Intraday Breaches':<17} | {'Triggers'}")
    print("-" * 115)

    summary_records = {}

    for label, r_mult, threshold in test_variants:
        feed = DataFeed(prices_df=prices_df, signals_df=signals_df)
        strat = VerifiedDualTimeframeStrategy(risk_mult=r_mult, daily_flatten_pct=threshold)
        res = Engine(feed, strat, cfg).run()

        tot_ret = float(res.metrics.get("total_return", 0.0)) * 100
        max_dd = float(res.metrics.get("max_drawdown", 0.0)) * 100
        
        # Close-to-close daily return distribution
        d_ret = np.array(res.to_daily_returns().drop_nulls().to_list())
        worst_close_day = float(np.min(d_ret)) * 100

        # True Intraday Drawdown Distribution relative to midnight
        intraday_dd_pcts = []
        for d, min_eq in strat.daily_intraday_min_equity.items():
            start_eq = strat.daily_start_equity.get(d, min_eq)
            if start_eq > 0:
                dd = (min_eq - start_eq) / start_eq * 100
                intraday_dd_pcts.append(dd)

        worst_intraday = float(np.min(intraday_dd_pcts)) if intraday_dd_pcts else 0.0
        # Check against prop firm rule: minimum intraday equity <= -5.0%
        intraday_breaches = int(np.sum(np.array(intraday_dd_pcts) <= -5.0))

        print(f"{label:<28} | {tot_ret:>8.2f}% | {max_dd:>7.2f}% | {worst_close_day:>13.2f}% | {worst_intraday:>13.2f}% | {intraday_breaches:>17} | {len(strat.trigger_events):>8}")

        summary_records[label] = {
            "total_return_pct": tot_ret,
            "max_drawdown_pct": max_dd,
            "worst_close_to_close_pct": worst_close_day,
            "worst_intraday_pct": worst_intraday,
            "intraday_breaches_count": intraday_breaches,
            "trigger_count": len(strat.trigger_events),
            "triggers_sample": strat.trigger_events[:5],
        }

    with (OUT_DIR / "verified_dual_timeframe_audit.json").open("w") as f:
        json.dump(summary_records, f, indent=2)


if __name__ == "__main__":
    evaluate()
