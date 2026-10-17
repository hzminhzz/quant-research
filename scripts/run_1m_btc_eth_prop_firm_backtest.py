"""Test BTC & ETH 1-Minute Trend-Following Strategy with Real-Time Intraday Flatten (2025-2026)."""

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


def load_1m_data():
    print("Loading 1-minute BTC and ETH datasets from store (2025 to 2026-07)...")
    dfs = []
    for sym in ["BTCUSDT", "ETHUSDT"]:
        p = STORE / f"crypto_futures_minute_{sym}_PERP"
        files = sorted([f for f in p.glob("**/*.parquet") if "year=2025" in str(f) or "year=2026" in str(f)])
        df_sym = pl.concat([pl.read_parquet(f) for f in files]).filter(
            (pl.col("timestamp") >= START_DT) & (pl.col("timestamp") <= END_DT)
        ).sort("timestamp")

        # In case symbol column is missing or different
        if "symbol" not in df_sym.columns:
            df_sym = df_sym.with_columns(pl.lit(sym).alias("symbol"))

        # Compute 168-hour ROC (10,080 1m bars) and 120-hour EMA (7,200 1m bars)
        df_sym = df_sym.with_columns([
            ((pl.col("close") - pl.col("close").shift(10080)) / pl.col("close").shift(10080)).alias("roc_168h"),
            pl.col("close").ewm_mean(span=7200).alias("ema_120h"),
            # 24h realized volatility (1440 1m bars) for risk weighting
            pl.col("close").pct_change().rolling_std(window_size=1440).alias("vol_24h"),
        ])
        dfs.append(df_sym)
        print(f"Loaded {sym}: {len(df_sym):,} 1m bars ({df_sym['timestamp'].min()} to {df_sym['timestamp'].max()})")

    df_all = pl.concat(dfs).sort(["timestamp", "symbol"])
    return df_all


class MinuteTSMOMStrategy(Strategy):
    """1-minute trend following strategy with real-time floating drawdown circuit breaker."""
    def __init__(self, risk_multiplier: float = 1.0, daily_limit_pct: float = 0.04):
        super().__init__()
        self.risk_mult = risk_multiplier
        self.daily_limit_pct = daily_limit_pct
        self.current_date = None
        self.day_start_equity = INITIAL_CASH
        self.circuit_breaker_active = False
        self.triggers = 0
        self.worst_intraday_dd = 0.0

    def on_data(self, timestamp, data, context, broker):
        bar_date = timestamp.strftime("%Y-%m-%d")
        equity = float(broker.equity())

        # Day rollover at midnight UTC
        if self.current_date != bar_date:
            self.current_date = bar_date
            self.day_start_equity = equity
            self.circuit_breaker_active = False

        # Continuous 1-minute intraday floating drawdown calculation
        floating_daily_dd = (equity - self.day_start_equity) / self.day_start_equity
        if floating_daily_dd < self.worst_intraday_dd:
            self.worst_intraday_dd = floating_daily_dd

        # Circuit breaker trigger
        if not self.circuit_breaker_active and floating_daily_dd <= -self.daily_limit_pct:
            self.circuit_breaker_active = True
            self.triggers += 1
            # Real-time immediate 1-minute flatten
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

        # Sizing: Equal weight 50% BTC, 50% ETH scaled by risk_multiplier
        target_allocation = 0.50 * self.risk_mult

        for sym, bar in data.items():
            sig = bar["signals"].get("roc_168h")
            ema120 = bar["signals"].get("ema_120h")
            close_p = bar.get("close", 0.0)

            if sig is None or ema120 is None or close_p is None:
                continue

            pos = broker.get_position(sym)
            current_qty = pos.quantity if pos is not None else 0.0

            # Trend Long
            if close_p > ema120 and sig > 0.015:
                if current_qty <= 0:
                    broker.order_target_percent(sym, target_allocation)
            # Trend Short
            elif close_p < ema120 and sig < -0.015:
                if current_qty >= 0:
                    broker.order_target_percent(sym, -target_allocation)
            # Neutral / Flat
            else:
                if current_qty != 0:
                    broker.order_target_percent(sym, 0.0)


def run_1m_evaluation():
    df = load_1m_data()

    prices_df = df.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
    signals_df = df.select(["timestamp", "symbol", "roc_168h", "ema_120h", "vol_24h"])

    cfg = BacktestConfig(
        initial_cash=INITIAL_CASH,
        allow_short_selling=True,
        share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=0.00018,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=0.0,
    )

    test_configs = [
        ("Full Risk (No Breaker)", 1.0, 1.00),
        ("Full Risk + 4% 1m Breaker", 1.0, 0.04),
        ("Full Risk + 2.5% 1m Breaker", 1.0, 0.025),
        ("0.70x Risk + 2.5% 1m Breaker", 0.70, 0.025),
        ("0.50x Risk + 2.5% 1m Breaker", 0.50, 0.025),
    ]

    print("\n" + "=" * 105)
    print("=== BTC + ETH 1-MINUTE REAL-TIME BACKTEST (2025-2026: 19 MONTHS, ~830K BARS) ===")
    print("=" * 105)
    print(f"{'Configuration':<30} | {'Return':<9} | {'Max DD':<9} | {'Worst Day':<10} | {'Breaches':<9} | {'Sharpe':<7} | {'Triggers':<8} | {'Status'}")
    print("-" * 105)

    results_dict = {}

    for label, r_mult, breaker_pct in test_configs:
        feed = DataFeed(prices_df=prices_df, signals_df=signals_df)
        strat = MinuteTSMOMStrategy(risk_multiplier=r_mult, daily_limit_pct=breaker_pct)
        res = Engine(feed, strat, cfg).run()

        d_ret = np.array(res.to_daily_returns().drop_nulls().to_list())
        tot_ret = float(res.metrics.get("total_return", 0.0)) * 100
        max_dd = float(res.metrics.get("max_drawdown", 0.0)) * 100
        worst_d = float(np.min(d_ret)) * 100
        breaches = int(np.sum(d_ret <= -0.05))
        sr = float(d_ret.mean() / d_ret.std() * np.sqrt(365.25)) if d_ret.std() > 0 else 0.0

        compliant = (max_dd < 10.0) and (breaches == 0) and (worst_d > -5.0)
        status = "PASSED" if compliant else "FAILED"

        print(f"{label:<30} | {tot_ret:>7.2f}% | {max_dd:>7.2f}% | {worst_d:>8.2f}% | {breaches:>9} | {sr:>7.2f} | {strat.triggers:>8} | {status}")

        results_dict[label] = {
            "return_pct": tot_ret,
            "max_dd_pct": max_dd,
            "worst_day_pct": worst_d,
            "breaches": breaches,
            "sharpe": sr,
            "triggers": strat.triggers,
            "status": status,
        }

    print("-" * 105)
    with (OUT_DIR / "btc_eth_1m_prop_firm_results.json").open("w") as f:
        json.dump(results_dict, f, indent=2)


if __name__ == "__main__":
    run_1m_evaluation()
