"""Native ml4t.backtest.Engine replay of the fixed Gotobi thesis.

No signals learned here. All positions are fixed 1000 USD base units in a
hypothetical JPY quote-currency account. Costs are an unverified 1-pip all-in
scenario. This is an implementation audit, NOT broker PnL or strategy approval.
"""
from __future__ import annotations
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
from ml4t.backtest import Strategy, Engine, DataFeed, BacktestConfig, ExecutionMode, OrderType, OrderStatus
from ml4t.backtest.config import ExecutionPrice, CommissionType, SlippageType, ShareType

ROOT=Path(__file__).resolve().parents[1]
SESSION="usdjpy_tokyo_fix_gotobi_engine_20261010_v1"
SRC=ROOT/"data/processed/tokyo_fix_gotobi_20261010/USDJPY_dev_20260101_20260831_1m.parquet"
EV=ROOT/"data/features/usdjpy_tokyo_fix_gotobi_20261010_continuous.parquet"
OUT=ROOT/"run_log"/SESSION
JST=ZoneInfo("Asia/Tokyo")
SIZE=1000.

class GotobiStrategy(Strategy):
    def __init__(self, arm, days):
        self.arm=arm
        self.days=set(days)
        self.orders=[]
        self.observed=Counter()
        self.errors=[]
    def on_start(self, broker):
        pass
    def on_data(self, timestamp, data, context, broker):
        local=timestamp.astimezone(JST)
        d=local.date()
        if d not in self.days or "USDJPY" not in data:
            return
        hhmm=local.strftime("%H:%M")
        target = {"H1":("08:29","09:53"),"H2":("09:55","10:29")}[self.arm]
        if hhmm==target[0]:
            if broker.get_position("USDJPY"):
                self.errors.append(f"Already open before entry: {timestamp}")
                return
            quantity=SIZE if self.arm=="H1" else -SIZE
            order=broker.submit_order("USDJPY",quantity)
            self.orders.append(("entry",d,order))
            self.observed["entry_signal"]+=1
        if hhmm==target[1]:
            if not broker.get_position("USDJPY"):
                self.errors.append(f"Missing position at scheduled exit: {timestamp}")
                return
            order=broker.close_position("USDJPY",order_type=OrderType.MARKET)
            self.orders.append(("exit",d,order))
            self.observed["exit_signal"]+=1
    def on_end(self, broker):
        if broker.get_position("USDJPY"):
            self.errors.append("Position remains after engine end")

def make_prices(days):
    ts=(pl.scan_parquet(SRC)
      .with_columns(pl.col("timestamp").dt.convert_time_zone("Asia/Tokyo").alias("jst"))
      .with_columns(pl.col("jst").dt.date().alias("session"),
        (pl.col("jst").dt.hour().cast(pl.Int32)*60+
         pl.col("jst").dt.minute().cast(pl.Int32)).alias("minute_jst"))
      .filter(pl.col("session").is_in(sorted(days)) &
              pl.col("minute_jst").is_between(480,630))
      .select("timestamp","symbol","open","high","low","close","volume")
      .sort("timestamp").collect())
    if ts.height!=len(days)*151:
        raise RuntimeError(f"Data completeness failed: {ts.height} vs {len(days)*151}")
    if ts["timestamp"].n_unique()!=ts.height:
        raise RuntimeError("Duplicate timestamps")
    return ts

def run(arm,costed,events):
    if arm=="H1":
        days=events.filter(pl.col("gotobi"))["session"].to_list()
    else:
        days=events.filter(pl.col("gotobi") &
                pl.col("h2_gate").fill_null(False))["session"].to_list()
    if not days:
        raise RuntimeError("No days selected")
    prices=make_prices(days)
    strategy=GotobiStrategy(arm,days)
    cfg=BacktestConfig(
        initial_cash=1000000.,
        allow_short_selling=True,allow_leverage=False,
        execution_mode=ExecutionMode.NEXT_BAR,
        execution_price=ExecutionPrice.OPEN,
        share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.NONE,commission_rate=0.,
        slippage_type=SlippageType.FIXED if costed else SlippageType.NONE,
        slippage_fixed=0.005 if costed else 0.,
        partial_fills_allowed=False,
    )
    engine=Engine(DataFeed(prices_df=prices),strategy,cfg)
    result=engine.run()
    recs=[]
    for role,d,order in strategy.orders:
        recs.append({"role":role,"session":str(d),
            "status":str(order.status),
            "filled_at":str(getattr(order,"filled_at",None)),
            "fill_price":str(getattr(order,"filled_price",getattr(order,"avg_fill_price",None))),
            "order_properties":{k:str(v) for k,v in vars(order).items()
                 if k in ["filled_at","fill_price","average_fill_price","avg_fill_price","executed_price","price"]}})
    filled=sum("FILLED" in x["status"].upper() for x in recs)
    expected=len(days)*2
    failures=strategy.errors+[f"filled orders {filled}/{expected}"] if filled!=expected else list(strategy.errors)
    if len(recs)!=expected:
        failures.append(f"submitted orders {len(recs)} expected {expected}")
    for row in recs:
        if row["filled_at"] in ("None",""):
            failures.append(f"unfilled {row['role']} {row['session']}")
            continue
        # Enforce JST timing invariants directly from actual order fills.
        from datetime import datetime
        dt=datetime.fromisoformat(row["filled_at"]).astimezone(JST)
        target=({"H1":{"entry":"08:30","exit":"09:54"},"H2":{"entry":"09:56","exit":"10:30"}}[arm])[row["role"]]
        if dt.strftime("%H:%M")!=target or dt.date().isoformat()!=row["session"]:
            failures.append(f"Fill timestamp mismatch {row['role']} {row['session']}: {dt} expected {target}")
    summary={
        "status":"PASS_IMPLEMENTATION" if not failures else "FAILED_IMPLEMENTATION",
        "arm":arm,"costed":costed,
        "engine":"ml4t.backtest.Engine (native NEXT_BAR OPEN)",
        "accounting":"JPY quote-value proxy, not retail USD account",
        "source_sha256":hashlib.sha256(SRC.read_bytes()).hexdigest(),
        "n_eligible_days":len(days),"native_feed_rows":prices.height,
        "fixed_usd_base_units":SIZE,
        "slippage_fixed_jpy_per_side":0.005 if costed else 0.,
        "submitted_orders":len(recs),"filled_orders":filled,
        "engine_metrics":{str(k):str(v) for k,v in result.metrics.items()},
        "errors":failures,
        "orders":recs,
    }
    trial=f"P4_{arm}_{'costed' if costed else 'zero_cost'}"
    path=OUT/trial/"result.json"
    if path.exists():
        raise RuntimeError(f"Refuse overwrite: {path}")
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(summary,indent=2,allow_nan=False)+"\n")
    return {k:v for k,v in summary.items() if k!="orders"}

def main():
    events=pl.read_parquet(EV)
    if events["session"].max()>=date(2026,9,1):
        raise RuntimeError("Holdout detected")
    outputs=[]
    for arm in ["H1","H2"]:
        for costed in [False,True]:
            outputs.append(run(arm,costed,events))
    print(json.dumps(outputs,indent=2))
if __name__=="__main__":
    main()
