"""7-Asset Multi-Year Intraday Volatility Breakout Backtest with Bitcoin Futures (2018-2026).

Replicates Peter's multi-asset systematic model across all 7 assets:
1. ES (S&P 500 Futures / SPY proxy)
2. NQ (Nasdaq 100 Futures / QQQ proxy)
3. US30 (Dow Jones Futures / DIA proxy)
4. CL (Crude Oil Futures / USO proxy)
5. XAUUSD (Spot Gold / GLD proxy)
6. DAX (Germany 40 Futures / Peter's live market)
7. BTC (Bitcoin Futures / Peter's live crypto market)

Uses native STOP orders, stop-loss at Open, EOD exit, and 0.33% risk per trade.
"""

from __future__ import annotations

import glob
import json
import sys
from datetime import datetime, time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import polars as pl
from ml4t.backtest import BacktestConfig, DataFeed, Engine, OrderSide, OrderType, Strategy
from ml4t.backtest.config import CommissionType, ShareType, SlippageType

STORE = Path("/home/quant/dev/quant/ml4t-data/.data/store")

ASSET_CONFIG = {
    "ES": {"folder": "index_minute_ES", "tz": "America/New_York", "open": time(9, 30), "close": time(16, 0), "min_p": None, "max_p": None},
    "NQ": {"folder": "index_minute_NQ", "tz": "America/New_York", "open": time(9, 30), "close": time(16, 0), "min_p": None, "max_p": None},
    "US30": {"folder": "index_minute_US30", "tz": "America/New_York", "open": time(9, 30), "close": time(16, 0), "min_p": None, "max_p": None},
    "CL": {"folder": "commodity_minute_CL", "tz": "America/New_York", "open": time(9, 0), "close": time(16, 0), "min_p": 0.01, "max_p": 200.0},
    "XAUUSD": {"folder": "forex_minute_XAUUSD", "tz": "America/New_York", "open": time(8, 0), "close": time(17, 0), "min_p": 1000.0, "max_p": 5000.0},
    "DAX": {"folder": "index_minute_DAX", "tz": "Europe/Berlin", "open": time(9, 0), "close": time(17, 30), "min_p": 8000.0, "max_p": 30000.0},
    "BTC": {"folder": "crypto_futures_minute_BTCUSDT_PERP", "tz": "America/New_York", "open": time(9, 30), "close": time(16, 0), "min_p": 1000.0, "max_p": 200000.0},
}


class Peter7AssetStrategy(Strategy):
    def __init__(self, breakout_mult: float = 0.40, risk_per_trade: float = 0.0033):
        super().__init__()
        self.breakout_mult = breakout_mult
        self.risk_per_trade = risk_per_trade
        self.daily_counts: Dict[tuple[str, Any], Dict[str, int]] = {}

    def on_data(self, timestamp: datetime, data: dict[str, dict], context: dict, broker):
        equity = broker.get_account_value()
        dt = timestamp.date()

        for symbol, bar in data.items():
            sigs = bar.get("signals", {})
            key = (symbol, dt)
            if key not in self.daily_counts:
                self.daily_counts[key] = {"long": 0, "short": 0}

            pos = broker.get_position(symbol)
            is_flat = pos is None or pos.quantity == 0

            # 1. EOD Exit: Flatten position on session-end bar
            if sigs.get("is_session_end", False):
                if not is_flat:
                    broker.close_position(symbol)
                continue

            # 2. Stop-Loss Exit: Stop order triggered if retraces to session_open
            if not is_flat and pos is not None:
                stop_price = sigs.get("session_open")
                if stop_price is not None:
                    if pos.quantity > 0 and bar["low"] <= stop_price:
                        broker.close_position(symbol)
                        continue
                    elif pos.quantity < 0 and bar["high"] >= stop_price:
                        broker.close_position(symbol)
                        continue

            # 3. Entry: Native STOP order at exact breakout band
            if is_flat and not sigs.get("is_session_end", False):
                prior_atr = sigs.get("prior_atr")
                session_open = sigs.get("session_open")
                if not prior_atr or prior_atr <= 0 or not session_open:
                    continue

                risk_dist = self.breakout_mult * prior_atr
                if risk_dist <= 0:
                    continue

                shares = (equity * self.risk_per_trade) / risk_dist
                long_trig = session_open + risk_dist
                short_trig = session_open - risk_dist

                # Long Breakout
                if bar["high"] >= long_trig and self.daily_counts[key]["long"] < 1:
                    broker.submit_order(
                        asset=symbol,
                        quantity=shares,
                        side=OrderSide.BUY,
                        order_type=OrderType.STOP,
                        stop_price=long_trig,
                    )
                    self.daily_counts[key]["long"] += 1

                # Short Breakout
                elif bar["low"] <= short_trig and self.daily_counts[key]["short"] < 1:
                    broker.submit_order(
                        asset=symbol,
                        quantity=shares,
                        side=OrderSide.SELL,
                        order_type=OrderType.STOP,
                        stop_price=short_trig,
                    )
                    self.daily_counts[key]["short"] += 1


def load_year_data(year: int) -> pl.DataFrame:
    asset_frames: List[pl.DataFrame] = []

    for sym, cfg in ASSET_CONFIG.items():
        folder = cfg["folder"]
        tz = cfg["tz"]
        s_open = cfg["open"]
        s_close = cfg["close"]
        min_p = cfg["min_p"]
        max_p = cfg["max_p"]

        files = glob.glob(f"{STORE}/{folder}/year={year}/**/*.parquet")
        if not files:
            continue

        dfs = [
            pl.read_parquet(f)
            .select(["timestamp", "open", "high", "low", "close", "volume"])
            .with_columns(
                pl.col("timestamp").cast(pl.Datetime("us", "UTC")),
                pl.col("volume").cast(pl.Float64),
                pl.lit(sym).alias("symbol"),
            )
            for f in files
        ]

        raw = (
            pl.concat(dfs)
            .filter((pl.col("low") > 0) & (pl.col("high") >= pl.col("low")))
            .unique(["symbol", "timestamp"])
            .sort(["symbol", "timestamp"])
        )

        if min_p is not None and max_p is not None:
            raw = raw.filter((pl.col("low") >= min_p) & (pl.col("high") <= max_p))

        # Local time for session detection
        raw = raw.with_columns(
            local_ts=pl.col("timestamp").dt.convert_time_zone(tz)
        ).with_columns(
            date=pl.col("local_ts").dt.date(),
            bar_time=pl.col("local_ts").dt.time(),
        )

        # Daily ATR(5) point-in-time calculation
        daily = (
            raw.group_by(["symbol", "date"])
            .agg(
                d_open=pl.col("open").first(),
                d_high=pl.col("high").max(),
                d_low=pl.col("low").min(),
                d_close=pl.col("close").last(),
            )
            .sort(["symbol", "date"])
        )

        daily = (
            daily.with_columns(prev_close=pl.col("d_close").shift(1).over("symbol"))
            .with_columns(
                tr=pl.max_horizontal(
                    pl.col("d_high") - pl.col("d_low"),
                    (pl.col("d_high") - pl.col("prev_close")).abs(),
                    (pl.col("d_low") - pl.col("prev_close")).abs(),
                )
            )
            .with_columns(atr=pl.col("tr").rolling_mean(5).over("symbol"))
            .with_columns(prior_atr=pl.col("atr").shift(1).over("symbol"))
            .select(["symbol", "date", "prior_atr"])
        )

        # Filter strictly to designated session hours
        session = raw.filter((pl.col("bar_time") >= s_open) & (pl.col("bar_time") <= s_close))
        opens = session.group_by(["symbol", "date"]).agg(session_open=pl.col("open").first())

        joined = (
            session.join(daily, on=["symbol", "date"], how="inner")
            .join(opens, on=["symbol", "date"], how="inner")
            .with_columns(
                is_session_end=(
                    (pl.col("timestamp") == pl.col("timestamp").max().over(["symbol", "date"]))
                    | (pl.col("bar_time") >= s_close)
                ),
            )
            .drop("local_ts")
        )
        asset_frames.append(joined)

    if not asset_frames:
        return pl.DataFrame()

    return pl.concat(asset_frames).sort(["symbol", "timestamp"])


def main():
    years = [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026]
    yearly_stats: List[Dict[str, Any]] = []

    print("=" * 80)
    print("PETER'S 7-ASSET INTRADAY BREAKOUT BACKTEST WITH BITCOIN (2018 - 2026)")
    print("Assets: ES, NQ, US30, CL, XAUUSD, DAX, BTC")
    print("Execution: Native STOP orders, Stop at Open, EOD Close, 0.33% Risk")
    print("=" * 80)

    cum_equity = 100_000.0
    initial_capital = 100_000.0

    config = BacktestConfig(
        initial_cash=cum_equity,
        allow_short_selling=True,
        allow_leverage=True,
        share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=0.00005,  # 0.5 bps
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=0.00005,    # 0.5 bps
    )

    for year in years:
        print(f"\n--- Loading and simulating Calendar Year {year} ---")
        year_df = load_year_data(year)
        if year_df.is_empty():
            print(f"No data for {year}, skipping.")
            continue

        symbols_in_year = sorted(year_df["symbol"].unique().to_list())
        print(f"  Bars processed: {year_df.height:,} across {len(symbols_in_year)} symbols ({', '.join(symbols_in_year)})")

        prices = year_df.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
        signals = year_df.select(["timestamp", "symbol", "prior_atr", "session_open", "is_session_end"])

        feed = DataFeed(prices_df=prices, signals_df=signals)
        strat = Peter7AssetStrategy(breakout_mult=0.40, risk_per_trade=0.0033)

        config.initial_cash = cum_equity
        res = Engine(feed, strat, config).run()

        ret = float(res.metrics.get("total_return", 0.0) or 0.0)
        dd = float(res.metrics.get("max_drawdown", 0.0) or 0.0)
        pf = float(res.metrics.get("profit_factor", 0.0) or 0.0)
        wins = int(res.metrics.get("winning_trades", 0) or 0)
        losses = int(res.metrics.get("losing_trades", 0) or 0)
        total_trades = wins + losses
        win_rate = (wins / total_trades) if total_trades > 0 else 0.0

        cum_equity = cum_equity * (1.0 + ret)

        stat = {
            "year": year,
            "return": ret,
            "max_drawdown": dd,
            "profit_factor": pf,
            "win_rate": win_rate,
            "trades": total_trades,
            "end_equity": cum_equity,
        }
        yearly_stats.append(stat)

        print(f"  Result {year}: Return={ret:+.2%} | MaxDD={dd:.2%} | PF={pf:.3f} | WinRate={win_rate:.2%} | Trades={total_trades:,} | End Equity=${cum_equity:,.2f}")

    total_cum_return = (cum_equity / initial_capital) - 1.0
    n_years = len(yearly_stats)
    cagr = ((cum_equity / initial_capital) ** (1.0 / n_years)) - 1.0 if n_years > 0 else 0.0
    returns_series = [s["return"] for s in yearly_stats]
    sharpe_annual = (np.mean(returns_series) / (np.std(returns_series) + 1e-6)) if len(returns_series) > 1 else 0.0
    total_trades_all = sum(s["trades"] for s in yearly_stats)

    print("\n" + "=" * 80)
    print("9-YEAR 7-ASSET COMPREHENSIVE PERFORMANCE SUMMARY (2018 - 2026)")
    print("=" * 80)
    print(f"Initial Portfolio:         ${initial_capital:,.2f}")
    print(f"Final Portfolio Equity:    ${cum_equity:,.2f}")
    print(f"Total Cumulative Return:   {total_cum_return:+.2%}")
    print(f"Compound Annual Growth:    {cagr:.2%} (CAGR)")
    print(f"Annualized Sharpe Ratio:   {sharpe_annual:.2f}")
    print(f"Total Completed Trades:    {total_trades_all:,}")
    print(f"Profitable Years Ratio:    {sum(1 for s in yearly_stats if s['return'] > 0)} / {n_years} years ({sum(1 for s in yearly_stats if s['return'] > 0) / n_years:.1%})")
    print("=" * 80)

    # Save artifact
    output_path = ROOT / "run_log" / "peter_7asset_with_btc_backtest_result.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary_data = {
        "yearly_stats": yearly_stats,
        "total_cumulative_return": total_cum_return,
        "cagr": cagr,
        "sharpe_annual": sharpe_annual,
        "total_trades": total_trades_all,
        "assets": list(ASSET_CONFIG.keys()),
    }
    output_path.write_text(json.dumps(summary_data, indent=2))
    print(f"Saved audit artifact to: {output_path}")


if __name__ == "__main__":
    main()
