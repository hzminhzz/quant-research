"""Dual-Timeframe Prop Firm Strategy: 1-Hour Signals + 1-Minute Real-Time PnL Watchdog (2025-2026).

Universe: 9 Liquid Crypto Perps (BTC, ETH, SOL, DOGE, SUI, NEAR, AVAX, LINK, BNB).
Signals: Evaluated at top-of-the-hour (120h EMA, 168h ROC).
Risk Watchdog: Evaluated on every 1-minute bar. Flattens immediately if floating daily loss drops <= -3.0%.
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


def load_dual_timeframe_data():
    print(f"Loading 1m data for {len(SYMBOLS)} tokens from store (2025 to 2026-07)...")
    dfs = []
    for sym in SYMBOLS:
        p = STORE / f"crypto_futures_minute_{sym}_PERP"
        files = sorted([f for f in p.glob("**/*.parquet") if "year=2025" in str(f) or "year=2026" in str(f)])
        df_sym = pl.concat([pl.read_parquet(f) for f in files]).filter(
            (pl.col("timestamp") >= START_DT) & (pl.col("timestamp") <= END_DT)
        ).sort("timestamp")

        if "symbol" not in df_sym.columns:
            df_sym = df_sym.with_columns(pl.lit(sym).alias("symbol"))

        # Compute hourly signals (120h EMA = 7200 1m bars, 168h ROC = 10080 1m bars)
        df_sym = df_sym.with_columns([
            ((pl.col("close") - pl.col("close").shift(10080)) / pl.col("close").shift(10080)).alias("roc_168h"),
            pl.col("close").ewm_mean(span=7200).alias("ema_120h"),
            (pl.col("timestamp").dt.minute() == 0).cast(pl.Int8).alias("is_hour_bar"),
        ])
        dfs.append(df_sym)
        print(f"  {sym}: {len(df_sym):,} 1m bars loaded")

    df_all = pl.concat(dfs).sort(["timestamp", "symbol"])
    return df_all


class DualTimeframePropFirmStrategy(Strategy):
    """Executes on 1-Hour closes, monitors floating drawdown every 1-Minute."""
    def __init__(self, risk_multiplier: float = 1.0, daily_flatten_pct: float = 0.03):
        super().__init__()
        self.risk_mult = risk_multiplier
        self.daily_flatten_pct = daily_flatten_pct
        self.current_date = None
        self.day_start_equity = INITIAL_CASH
        self.circuit_breaker_active = False
        self.triggers = 0
        self.worst_intraday_dd = 0.0

    def on_data(self, timestamp, data, context, broker):
        bar_date = timestamp.strftime("%Y-%m-%d")
        equity = float(broker.equity())

        # Midnight reset (00:00 UTC)
        if self.current_date != bar_date:
            self.current_date = bar_date
            self.day_start_equity = equity
            self.circuit_breaker_active = False

        # --- 1-MINUTE REAL-TIME WATCHDOG ---
        floating_daily_dd = (equity - self.day_start_equity) / self.day_start_equity
        if floating_daily_dd < self.worst_intraday_dd:
            self.worst_intraday_dd = floating_daily_dd

        # If floating loss hits or exceeds daily threshold -> FLATTEN IMMEDIATELY
        if not self.circuit_breaker_active and floating_daily_dd <= -self.daily_flatten_pct:
            self.circuit_breaker_active = True
            self.triggers += 1
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

        # --- 1-HOUR REBALANCE LOGIC (Only runs when minute == 0) ---
        is_hour_close = timestamp.minute == 0
        if not is_hour_close:
            return  # No hourly trade signals between hour boundaries

        # Target allocation per active trend position (up to 5 positions, 15% each * risk_mult)
        base_weight = 0.15 * self.risk_mult

        for sym, bar in data.items():
            sig = bar["signals"].get("roc_168h")
            ema120 = bar["signals"].get("ema_120h")
            close_p = bar.get("close", 0.0)

            if sig is None or ema120 is None or close_p is None:
                continue

            pos = broker.get_position(sym)
            current_qty = pos.quantity if pos is not None else 0.0

            # Trend Long: Close > EMA120 and ROC168 > +1.5%
            if close_p > ema120 and sig > 0.015:
                if current_qty <= 0:
                    broker.order_target_percent(sym, base_weight)
            # Trend Short: Close < EMA120 and ROC168 < -1.5%
            elif close_p < ema120 and sig < -0.015:
                if current_qty >= 0:
                    broker.order_target_percent(sym, -base_weight)
            # Dead-band / Chop: Flatten to cash
            else:
                if current_qty != 0:
                    broker.order_target_percent(sym, 0.0)


def run_dual_timeframe_backtest():
    df = load_dual_timeframe_data()

    prices_df = df.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
    signals_df = df.select(["timestamp", "symbol", "roc_168h", "ema_120h", "is_hour_bar"])

    cfg = BacktestConfig(
        initial_cash=INITIAL_CASH,
        allow_short_selling=True,
        share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=0.00018,  # Maker fee 1.8 bps
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=0.0,
    )

    test_grid = [
        ("Full Risk (No Watchdog)", 1.0, 1.00),
        ("Full Risk + 3.0% 1m Watchdog", 1.0, 0.03),
        ("0.70x Risk + 3.0% 1m Watchdog", 0.70, 0.03),
        ("0.50x Risk + 2.5% 1m Watchdog", 0.50, 0.025),
    ]

    print("\n" + "=" * 105)
    print("=== DUAL-TIMEFRAME PROP FIRM BACKTEST (1H SIGNALS + 1M PnL WATCHDOG: 2025-2026) ===")
    print("=" * 105)
    print(f"{'Configuration':<30} | {'Total Ret':<10} | {'Max DD':<9} | {'Worst Day':<10} | {'Breaches':<9} | {'Sharpe':<7} | {'Triggers':<8} | {'Status'}")
    print("-" * 105)

    results = {}
    for label, r_mult, flatten_limit in test_grid:
        feed = DataFeed(prices_df=prices_df, signals_df=signals_df)
        strat = DualTimeframePropFirmStrategy(risk_multiplier=r_mult, daily_flatten_pct=flatten_limit)
        res = Engine(feed, strat, cfg).run()

        d_ret = np.array(res.to_daily_returns().drop_nulls().to_list())
        tot_ret = float(res.metrics.get("total_return", 0.0)) * 100
        max_dd = float(res.metrics.get("max_drawdown", 0.0)) * 100
        worst_d = float(np.min(d_ret)) * 100
        breaches = int(np.sum(d_ret <= -0.05))
        sr = float(d_ret.mean() / d_ret.std() * np.sqrt(365.25)) if d_ret.std() > 0 else 0.0

        compliant = (max_dd < 10.0) and (breaches == 0) and (worst_d > -5.0)
        status = "PASSED" if compliant else "FAILED"

        print(f"{label:<30} | {tot_ret:>9.2f}% | {max_dd:>7.2f}% | {worst_d:>8.2f}% | {breaches:>9} | {sr:>7.2f} | {strat.triggers:>8} | {status}")
        results[label] = {
            "total_return_pct": tot_ret,
            "max_drawdown_pct": max_dd,
            "worst_day_pct": worst_d,
            "breaches": breaches,
            "sharpe": sr,
            "triggers": strat.triggers,
            "status": status,
        }

    print("-" * 105)
    with (OUT_DIR / "dual_timeframe_prop_firm_results.json").open("w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    run_dual_timeframe_backtest()
