"""Gold (XAUUSD) Standalone Intraday Volatility Breakout Backtest (2018-2026).

Evaluates the exact Peter breakout rules on Spot Gold only across 9 calendar years.
"""

from __future__ import annotations

import glob
from datetime import datetime, time
from pathlib import Path
import numpy as np
import polars as pl
from ml4t.backtest import BacktestConfig, DataFeed, Engine, OrderSide, OrderType, Strategy
from ml4t.backtest.config import CommissionType, ShareType, SlippageType

STORE = Path("/home/quant/dev/quant/ml4t-data/.data/store/forex_minute_XAUUSD")
YEARS = [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026]


class GoldBreakoutStrategy(Strategy):
    def __init__(self, breakout_mult: float = 0.40, risk_per_trade: float = 0.0033):
        super().__init__()
        self.breakout_mult = breakout_mult
        self.risk_per_trade = risk_per_trade
        self.daily_counts = {}

    def on_data(self, timestamp: datetime, data: dict[str, dict], context: dict, broker):
        equity = broker.get_account_value()
        dt = timestamp.date()
        bar = data.get("XAUUSD")
        if not bar:
            return
        sigs = bar.get("signals", {})
        if dt not in self.daily_counts:
            self.daily_counts[dt] = {"long": 0, "short": 0}

        pos = broker.get_position("XAUUSD")
        is_flat = pos is None or pos.quantity == 0

        # EOD exit
        if sigs.get("is_session_end", False):
            if not is_flat:
                broker.close_position("XAUUSD")
            return

        # Stop loss check
        if not is_flat and pos is not None:
            stop_price = sigs.get("session_open")
            if stop_price:
                if pos.quantity > 0 and bar["low"] <= stop_price:
                    broker.close_position("XAUUSD")
                    return
                elif pos.quantity < 0 and bar["high"] >= stop_price:
                    broker.close_position("XAUUSD")
                    return

        # Entry
        if is_flat and not sigs.get("is_session_end", False):
            prior_atr = sigs.get("prior_atr")
            session_open = sigs.get("session_open")
            if not prior_atr or prior_atr <= 0 or not session_open:
                return

            risk_dist = self.breakout_mult * prior_atr
            if risk_dist <= 0:
                return

            shares = (equity * self.risk_per_trade) / risk_dist
            long_trig = session_open + risk_dist
            short_trig = session_open - risk_dist

            if bar["high"] >= long_trig and self.daily_counts[dt]["long"] < 1:
                broker.submit_order(
                    asset="XAUUSD",
                    quantity=shares,
                    side=OrderSide.BUY,
                    order_type=OrderType.STOP,
                    stop_price=long_trig,
                )
                self.daily_counts[dt]["long"] += 1
            elif bar["low"] <= short_trig and self.daily_counts[dt]["short"] < 1:
                broker.submit_order(
                    asset="XAUUSD",
                    quantity=shares,
                    side=OrderSide.SELL,
                    order_type=OrderType.STOP,
                    stop_price=short_trig,
                )
                self.daily_counts[dt]["short"] += 1


def main():
    print("=" * 80)
    print("GOLD (XAUUSD) ONLY: 9-YEAR SYSTEMATIC BREAKOUT BACKTEST (2018 - 2026)")
    print("Execution: Native STOP orders, Stop at Open, EOD Close, 0.33% Risk per trade")
    print("=" * 80)

    yearly_results = []
    cum_equity = 100_000.0
    initial_cash = 100_000.0

    for y in YEARS:
        files = glob.glob(f"{STORE}/year={y}/**/*.parquet")
        if not files:
            print(f"Year {y}: no files found!")
            continue

        dfs = [
            pl.read_parquet(f)
            .select(["timestamp", "open", "high", "low", "close", "volume"])
            .with_columns(
                pl.col("timestamp").cast(pl.Datetime("us", "UTC")),
                pl.col("volume").cast(pl.Float64),
            )
            for f in files
        ]
        raw = (
            pl.concat(dfs)
            .filter((pl.col("low") >= 1000.0) & (pl.col("high") <= 5000.0))
            .with_columns(
                pl.lit("XAUUSD").alias("symbol"),
                pl.col("volume").cast(pl.Float64),
            )
            .unique("timestamp")
            .sort("timestamp")
        )

        # Session processing (08:00 to 17:00 America/New_York)
        raw = raw.with_columns(
            local_ts=pl.col("timestamp").dt.convert_time_zone("America/New_York")
        ).with_columns(
            date=pl.col("local_ts").dt.date(),
            bar_time=pl.col("local_ts").dt.time(),
        )

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
            daily.with_columns(prev_close=pl.col("d_close").shift(1))
            .with_columns(
                tr=pl.max_horizontal(
                    pl.col("d_high") - pl.col("d_low"),
                    (pl.col("d_high") - pl.col("prev_close")).abs(),
                    (pl.col("d_low") - pl.col("prev_close")).abs(),
                )
            )
            .with_columns(atr=pl.col("tr").rolling_mean(5))
            .with_columns(prior_atr=pl.col("atr").shift(1))
            .select(["symbol", "date", "prior_atr"])
        )

        session = raw.filter((pl.col("bar_time") >= time(8, 0)) & (pl.col("bar_time") <= time(17, 0)))
        opens = session.group_by(["symbol", "date"]).agg(session_open=pl.col("open").first())

        joined = (
            session.join(daily, on=["symbol", "date"], how="inner")
            .join(opens, on=["symbol", "date"], how="inner")
            .with_columns(
                is_session_end=(
                    (pl.col("timestamp") == pl.col("timestamp").max().over(["symbol", "date"]))
                    | (pl.col("bar_time") >= time(17, 0))
                )
            )
            .drop("local_ts")
        )

        prices = joined.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
        signals = joined.select(["timestamp", "symbol", "prior_atr", "session_open", "is_session_end"])

        feed = DataFeed(prices_df=prices, signals_df=signals)
        cfg = BacktestConfig(
            initial_cash=cum_equity,
            allow_short_selling=True,
            allow_leverage=True,
            share_type=ShareType.FRACTIONAL,
            commission_type=CommissionType.PERCENTAGE,
            commission_rate=0.00005,  # 0.5 bps
            slippage_type=SlippageType.PERCENTAGE,
            slippage_rate=0.00005,    # 0.5 bps
        )

        res = Engine(feed, GoldBreakoutStrategy(breakout_mult=0.40, risk_per_trade=0.0033), cfg).run()

        ret = float(res.metrics.get("total_return", 0.0) or 0.0)
        dd = float(res.metrics.get("max_drawdown", 0.0) or 0.0)
        pf = float(res.metrics.get("profit_factor", 0.0) or 0.0)
        wins = int(res.metrics.get("winning_trades", 0) or 0)
        losses = int(res.metrics.get("losing_trades", 0) or 0)
        tot = wins + losses
        wr = (wins / tot) if tot > 0 else 0.0

        cum_equity = cum_equity * (1.0 + ret)

        yearly_results.append({
            "year": y, "return": ret, "max_dd": dd, "pf": pf, "wr": wr, "trades": tot, "equity": cum_equity
        })

        print(f"Year {y}: Return={ret:+6.2%} | MaxDD={dd:5.2%} | PF={pf:5.3f} | WinRate={wr:5.2%} | Trades={tot:3d} | End Equity=${cum_equity:,.2f}")

    total_ret = (cum_equity / initial_cash) - 1.0
    cagr = ((cum_equity / initial_cash) ** (1.0 / len(YEARS))) - 1.0
    ret_list = [r["return"] for r in yearly_results]
    ann_sr = np.mean(ret_list) / (np.std(ret_list) + 1e-6)

    print("\n" + "=" * 80)
    print("9-YEAR GOLD (XAUUSD) PERFORMANCE SUMMARY (2018 - 2026)")
    print("=" * 80)
    print(f"Initial Balance:          ${initial_cash:,.2f}")
    print(f"Final Balance:            ${cum_equity:,.2f}")
    print(f"Total Cumulative Return:  {total_ret:+.2%}")
    print(f"Compound Annual Growth:   {cagr:.2%} (CAGR)")
    print(f"Annualized Sharpe Ratio:  {ann_sr:.2f}")
    print(f"Total Completed Trades:   {sum(r['trades'] for r in yearly_results):,}")
    print(f"Profitable Years Ratio:   {sum(1 for r in yearly_results if r['return'] > 0)} / {len(YEARS)} ({sum(1 for r in yearly_results if r['return'] > 0) / len(YEARS):.1%})")
    print("=" * 80)


if __name__ == "__main__":
    main()
