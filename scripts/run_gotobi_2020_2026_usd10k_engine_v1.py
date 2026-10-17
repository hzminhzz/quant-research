"""Native ML4T Engine historical Gotobi backtest with USD 10,000 start.

No custom trading simulator. Converts native closed JPY trade ledger into USD
at contemporaneous exit fill rates; native Engine is not an FX cash account.
"""
from __future__ import annotations
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import exchange_calendars as xc
import numpy as np
import polars as pl
from ml4t.backtest import (
    Strategy, Engine, DataFeed, BacktestConfig, ExecutionMode,
    OrderType, OrderStatus,
)
from ml4t.backtest.config import (
    ExecutionPrice, CommissionType, SlippageType, ShareType,
)

ROOT=Path(__file__).resolve().parents[1]
SID="usdjpy_gotobi_2020_2026_usd10000_v1"
SRC=ROOT/"data/processed/gotobi_2020_2026_usd10k_v1/USDJPY_tokyo_windows_1m.parquet"
PANEL=ROOT/f"data/features/{SID}_events.parquet"
OUT=ROOT/"run_log"/SID
JST=ZoneInfo("Asia/Tokyo")
START_USD=10000.
POSITION_USD=10000.
SLIP_JPY=0.005

class GotobiFixedTime(Strategy):
    def __init__(self, arm, days):
        self.arm=arm
        self.days=set(days)
        self.orders=[]
        self.errors=[]
        self.counters=Counter()
    def on_start(self,broker):
        pass
    def on_data(self,timestamp,data,context,broker):
        local=timestamp.astimezone(JST)
        d=local.date()
        if d not in self.days or "USDJPY" not in data:return
        time=local.strftime("%H:%M")
        event={"H1":("08:29","09:53"),"H2":("09:55","10:29")}[self.arm]
        if time==event[0]:
            if broker.get_position("USDJPY"):
                self.errors.append(f"Overlapping position {d}")
                return
            signed=POSITION_USD if self.arm=="H1" else -POSITION_USD
            o=broker.submit_order("USDJPY",signed)
            self.orders.append(("entry",d,o))
            self.counters["entries"]+=1
        if time==event[1]:
            if not broker.get_position("USDJPY"):
                self.errors.append(f"Missing position at exit {d}")
                return
            o=broker.close_position("USDJPY",order_type=OrderType.MARKET)
            self.orders.append(("exit",d,o))
            self.counters["exits"]+=1
    def on_end(self,broker):
        if broker.get_position("USDJPY"):
            self.errors.append("Terminal position remains open")

def prepare(days):
    frame=(pl.scan_parquet(SRC)
        .with_columns(pl.col("timestamp").dt.convert_time_zone("Asia/Tokyo").alias("jst"))
        .with_columns(pl.col("jst").dt.date().alias("session"))
        .filter(pl.col("session").is_in(sorted(days)))
        .select("timestamp","symbol","open","high","low","close","volume")
        .sort("timestamp").collect())
    if frame.height!=len(days)*151 or frame["timestamp"].n_unique()!=frame.height:
        raise RuntimeError(f"Incomplete selected sessions: {frame.height} != {len(days)*151}")
    return frame

def run_arm(arm,events):
    selected=events.filter(pl.col("gotobi")) if arm=="H1" else events.filter(
       pl.col("gotobi") & pl.col("h2_gate").fill_null(False))
    days=selected["session"].to_list()
    if not days:raise RuntimeError(f"No {arm} signals")
    data=prepare(days)
    first_open=float(data["open"][0])
    # Engine-native quote JPY uses margin cushion because JPY/USD may change
    # over 2020-2026; a fixed USD account is reconstructed from native fills.
    proxy_jpy_cash=START_USD*first_open
    strategy=GotobiFixedTime(arm,days)
    config=BacktestConfig(initial_cash=proxy_jpy_cash,allow_leverage=True,
       initial_margin=0.50,allow_short_selling=True,
       execution_mode=ExecutionMode.NEXT_BAR,execution_price=ExecutionPrice.OPEN,
       share_type=ShareType.FRACTIONAL,
       commission_type=CommissionType.NONE,commission_rate=0.,
       slippage_type=SlippageType.FIXED,slippage_fixed=SLIP_JPY,
       partial_fills_allowed=False)
    result=Engine(DataFeed(prices_df=data),strategy,config).run()
    records=[]
    for role,d,order in strategy.orders:
        if order.status is not OrderStatus.FILLED:
            raise RuntimeError(f"Rejected/unfilled {arm}: {d}, {role}, {order.status}")
        if order.filled_at is None:raise RuntimeError("Missing native timestamp")
        ftime=order.filled_at.astimezone(JST)
        expected={"H1":{"entry":"08:30","exit":"09:54"},
                  "H2":{"entry":"09:56","exit":"10:30"}}[arm][role]
        if ftime.date()!=d or ftime.strftime("%H:%M")!=expected:
            raise RuntimeError(f"Fill time mismatched: {arm} {d} {role} {ftime}")
        price=float(getattr(order,"filled_price",getattr(order,"avg_fill_price",float("nan"))))
        if not np.isfinite(price):raise RuntimeError("No executed price")
        records.append({"session":d,"role":role,"fill_price":price,
                        "filled_at":order.filled_at,"order_id":str(order.order_id)})
    if len(records)!=len(days)*2 or strategy.errors:
        raise RuntimeError(f"Orders {len(records)} vs {len(days)*2}; errors {strategy.errors}")
    frame=pl.DataFrame(records)
    entry=frame.filter(pl.col("role")=="entry").select(
         "session",pl.col("fill_price").alias("entry"),pl.col("filled_at").alias("entry_time"))
    exit_=frame.filter(pl.col("role")=="exit").select(
         "session",pl.col("fill_price").alias("exit"),pl.col("filled_at").alias("exit_time"))
    closed=entry.join(exit_,on="session",how="inner",validate="1:1").sort("session")
    ref=selected.select("session","p0830","p0954","p0956","p1030")
    closed=closed.join(ref,on="session",validate="1:1")
    s=1. if arm=="H1" else -1.
    expected_entry=pl.col("p0830")+SLIP_JPY if arm=="H1" else pl.col("p0956")-SLIP_JPY
    expected_exit=pl.col("p0954")-SLIP_JPY if arm=="H1" else pl.col("p1030")+SLIP_JPY
    checked=closed.with_columns(
        expected_entry.alias("oracle_entry"),
        expected_exit.alias("oracle_exit"))
    if checked.filter(((pl.col("entry")-pl.col("oracle_entry")).abs()>1e-8)|
           ((pl.col("exit")-pl.col("oracle_exit")).abs()>1e-8)).height:
        raise RuntimeError("Native fill price does not match exact minute-open oracle")
    closed=(checked.with_columns(
          ((pl.col("exit")-pl.col("entry"))*s*POSITION_USD).alias("pnl_jpy"),
          ((pl.col("exit")-pl.col("entry"))*s*100).alias("net_pips"),
          pl.col("session").dt.year().alias("year"))
          .with_columns((pl.col("pnl_jpy")/pl.col("exit")).alias("pnl_usd"))
          .with_columns((START_USD+pl.col("pnl_usd").cum_sum()).alias("equity_usd"))
          .with_columns((pl.col("equity_usd")-pl.col("equity_usd").cum_max()).alias("closed_drawdown_usd")))
    quote_pnl=float(closed["pnl_jpy"].sum())
    engine_pnl=float(result.metrics["final_value"])-proxy_jpy_cash
    if abs(quote_pnl-engine_pnl)>1e-4:
        raise RuntimeError(f"Native JPY reconciliation failure {engine_pnl} vs {quote_pnl}")
    years=[]
    for p in closed.partition_by("year",maintain_order=True):
        v=p["pnl_usd"]
        winners=float(v.filter(v>0).sum())
        losses=abs(float(v.filter(v<0).sum()))
        years.append({
         "year":int(p["year"][0]),"trades":p.height,
         "net_pips":float(p["net_pips"].sum()),
         "mean_net_pips":float(p["net_pips"].mean()),
         "net_pnl_usd":float(v.sum()),
         "net_return_pct_of_initial_capital":100*float(v.sum())/START_USD,
         "win_rate":float((v>0).sum()/p.height),
         "profit_factor":winners/losses if losses>0 else None})
    # Daily USD-equity Sharpe with flat business days, not per-trade annualization.
    dates=[t.date() for t in xc.get_calendar("XTKS").sessions_in_range("2020-01-01","2026-08-31")]
    daily=(pl.DataFrame({"session":dates}).join(
        closed.group_by("session").agg(pl.col("pnl_usd").sum()),on="session",how="left")
        .with_columns(pl.col("pnl_usd").fill_null(0))
        .sort("session")
        .with_columns((START_USD+pl.col("pnl_usd").cum_sum()).alias("usd_equity"))
        .with_columns((pl.col("pnl_usd")/(pl.col("usd_equity")-pl.col("pnl_usd"))).alias("daily_ret")))
    arr=daily["daily_ret"].to_numpy()
    annual_sharpe=float(arr.mean()/arr.std(ddof=1)*np.sqrt(252)) if arr.std(ddof=1)>0 else None
    gross_sensitivity={str(cost):float(selected["h1_long_pips" if arm=="H1" else "h2_short_pips"].mean()-cost)
                       for cost in (.8,1.,1.4)}
    outdir=OUT/("T3_H1_engine_costed" if arm=="H1" else "T4_H2_engine_costed")
    if outdir.exists():raise RuntimeError(f"Existing trial {outdir}")
    outdir.mkdir(parents=True,exist_ok=True)
    closed.write_parquet(outdir/"native_fills_reconciled_trades.parquet")
    summary={
      "strategy":arm,"status":"PASS_IMPLEMENTATION_NOT_APPROVED",
      "account_start_usd":START_USD,"position_notional_usd":POSITION_USD,
      "position_sizing":"Fixed base 10,000 USD, no compounding",
      "accounting":"Native Engine simulates JPY quote; USD realized PnL converted at each exit, starts at USD 10,000; uncalibrated spot-CFD proxy",
      "native_start_jpy":proxy_jpy_cash,
      "native_end_jpy":float(result.metrics["final_value"]),
      "native_pnl_jpy":engine_pnl,
      "source_sha256":hashlib.sha256(SRC.read_bytes()).hexdigest(),
      "engine":"ml4t.backtest.Engine, NEXT_BAR OPEN, native FX-like quote proxy",
      "assumed_slippage_jpy_per_side":SLIP_JPY,
      "assumed_all_in_cost_pips":1.,
      "num_trade_days":len(days),"submitted_filled_orders":len(records),
      "net_pnl_usd":float(closed["pnl_usd"].sum()),
      "final_equity_usd":START_USD+float(closed["pnl_usd"].sum()),
      "return_pct_on_usd_start":100*float(closed["pnl_usd"].sum())/START_USD,
      "mean_net_pips":float(closed["net_pips"].mean()),
      "win_rate":float((closed["pnl_usd"]>0).sum()/closed.height),
      "daily_usd_equity_sharpe_flat_days":annual_sharpe,
      "max_closed_trade_drawdown_usd":float(closed["closed_drawdown_usd"].min()),
      "max_closed_trade_drawdown_pct_initial":100*float(closed["closed_drawdown_usd"].min())/START_USD,
      "engine_native_quote_pnl_reconciliation":abs(engine_pnl-quote_pnl),
      "yearly":years,"cost_sensitivity_mean_pips_from_event_screen":gross_sensitivity,
      "limitations":["No executable bid/ask history; price slip is hypothetical.",
        "Native JPY broker uses proxy margin; USD closed PnL converted from actual native order fills.",
        "Closed-trade drawdown omits intratrade peak/trough.",
        "All history retrospective including previously inspected 2026 development; holdout unopened."]
    }
    (outdir/"result.json").write_text(json.dumps(summary,indent=2,allow_nan=False)+"\n")
    return summary

def main():
    ev=pl.read_parquet(PANEL)
    if ev["session"].max()>=date(2026,9,1):raise RuntimeError("Holdout contamination")
    result=[run_arm("H1",ev),run_arm("H2",ev)]
    print(json.dumps(result,indent=2,allow_nan=False))
if __name__=="__main__":main()
