"""Native ML4T FX backtest against LSE historical bid/ask source quotes.

Engineering smoke only. Uses known sampled 2025-Apr and 2025-Jun days.
The frozen multi-year research pilot remains pending sufficient exports.
No protective holdout reads, broker fills, or fabricated executable quotes.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from datetime import date, datetime, timedelta, time, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl
from ml4t.backtest import BacktestConfig, DataFeed, Engine, Strategy, ExecutionMode
from ml4t.backtest.config import ExecutionPrice, CommissionType, ShareType, SlippageType
from ml4t.backtest.analytics import EquityCurve, TradeAnalyzer

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path("/home/quant/dev/quant/ml4t-data/.artifacts/gotobi-tick-probe")
OUT = ROOT / "run_log/gotobi_lse_bidask_execution_pilot_20261011_v1/engineering_smoke"
CAL = ROOT / "run_log/tokyo_fix_alpha_map_program1_20261010/execution_v1/calendar_event_registry.parquet"
JST = ZoneInfo("Asia/Tokyo")
UTC = timezone.utc
PIP = 0.01
NOTIONAL = 10000
# Intentional: smoke dates and files observed earlier; cannot be a fresh OOS test.
EXPECTED = [
    ("months/2025-04-01_2025-04-08/fx_USD_JPY_tick.parquet","712ebd050de025cec43b155e03cf3159fa6a20d724bf77fb026a388c83703e25"),
    ("2025-06-09_one_day/fx_USD_JPY_tick.parquet","d8f0427d0ca04439da2b808b37880279d1f16000309f54aadaaf51559ca9e077"),
    ("2025-06-10_one_day/fx_USD_JPY_tick.parquet","43fb9df1da796972c583646ba15026394fc34371b3a9be0475fb208a5664ce81"),
]
SMOKE_DAYS = [date(2025,4,d) for d in [2,3,4]] + [date(2025,6,10)]
ARM = [
    ("gotobi_latency1_extra0p25", "gotobi", 1, .25),
    ("ordinary_latency1_extra0p25", "ordinary", 1, .25),
    ("gotobi_latency0_extra0", "gotobi", 0, 0),
    ("gotobi_latency5_extra0p5", "gotobi", 5, .5),
]

def sha(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""):h.update(block)
    return h.hexdigest()

def write_json(path,obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded=json.dumps(obj,indent=2,default=str,allow_nan=False)+"\n"
    if path.exists():
        if path.read_text()!=encoded:raise RuntimeError(f"Immutable evidence drift: {path}")
    else:path.write_text(encoded)

def load():
    scans=[]
    manifest=[]
    for rel,want in EXPECTED:
        p=SOURCE/rel
        if not p.exists() or sha(p)!=want:raise RuntimeError(f"Missing/drifted source: {rel}")
        meta=pl.scan_parquet(p).collect_schema()
        if set(meta)!={"ts","symbol","bid","ask"}:raise RuntimeError("Schema mismatch")
        manifest.append({"path":str(p),"sha256":want,"size_bytes":p.stat().st_size})
        scans.append(pl.scan_parquet(p))
    ticks=pl.concat(scans).filter(
        (pl.col("ts")<datetime(2026,9,1,tzinfo=UTC)) &
        (pl.col("bid")>0)&(pl.col("ask")>=pl.col("bid")) &
        (pl.col("symbol")=="USD/JPY")
    ).collect()
    if ticks.is_empty():raise RuntimeError("No quotes")
    # LSE provides second-resolution time stamps, with many updates per second.
    # Worst attainable quote within that second, rather than picking favorable row.
    secs=(ticks.group_by("ts").agg(
        pl.col("ask").max().alias("buy_ask"),
        pl.col("bid").min().alias("sell_bid"),
        pl.col("bid").max().alias("max_bid"),
        pl.col("ask").min().alias("min_ask"),
        pl.len().alias("updates")).sort("ts"))
    if secs["ts"].is_duplicated().any():raise RuntimeError("Second aggregation failure")
    quoted_spread=((ticks["ask"]-ticks["bid"])/PIP)
    met={"sources":manifest,"raw_rows":ticks.height,"quote_seconds":secs.height,
         "duplicate_seconds":ticks.height-secs.height,
         "raw_spread_median_pips":float(quoted_spread.median()),
         "raw_spread_p95_pips":float(quoted_spread.quantile(.95)),
         "zero_negative_or_crossed_quotes_in_accepted_rows":0,
         "excluded_day_scope":"ONLY historical sampled April and June2025 files",
         "time_precision":str(ticks["ts"].dtype),
         "time_information_loss":"Multiple quote updates per second; max ask/min bid worst-of-second bound",
         "broker_executability":"UNVERIFIED reference quotes, not live executable broker prices",
         "holdout_read":False}
    return secs,met

def selected_seconds(secs,date_,delay,extra):
    day=date_
    def clock(hour,minute,second):
        return datetime.combine(day,time(hour,minute,second),tzinfo=JST).astimezone(UTC)
    targets=[clock(2,59,59),clock(3,0,0)+timedelta(seconds=delay),
             clock(9,53,59),clock(9,54,0)+timedelta(seconds=delay)]
    ts=secs["ts"].to_numpy()
    data=[]
    labels=["entry_decision","buy_ask_fill","exit_decision","sell_bid_fill"]
    for ix,t in enumerate(targets):
        # convert target to epoch microseconds to avoid timezone mismatches.
        stamp=np.datetime64(t.replace(tzinfo=None).isoformat() + "Z") if False else None
        # polars Datetime[us,UTC].to_numpy() is datetime64[us].
        target64=np.datetime64(t.astimezone(UTC).replace(tzinfo=None),"us")
        j=np.searchsorted(ts,target64,side="right" if ix in (0,2) else "left")
        if ix in (0,2):
            j-=1
        if j<0 or j>=len(ts):
            return None,f"{labels[ix]} quote not present"
        sec=secs.row(int(j),named=True)
        actual=sec["ts"]
        age=abs((actual-t).total_seconds())
        if age>5:
            return None,f"{labels[ix]} quote distance >5s: {age:.3f}"
        bid=sec["sell_bid"]
        ask=sec["buy_ask"]
        # Decision bars use midpoint of real worst-side second quotes, not future data.
        price= 0.5*(ask+bid) if ix in (0,2) else (ask+extra*PIP if ix==1 else bid-extra*PIP)
        data.append({"session":day,"role":labels[ix],"timestamp":actual,
                     "price":float(price),"src_bid":bid,"src_ask":ask,
                     "source_updates_in_second":sec["updates"],"target_clock_utc":t,
                     "distance_seconds":age,"spread_bound_pips":(ask-bid)/PIP})
    if not all(data[i]["timestamp"]<data[i+1]["timestamp"] for i in range(3)):
        return None,"nonmonotonic event times"
    return data,None

class QuoteLong(Strategy):
    def __init__(self,ordered):
        self.ordered=ordered
        self.events=[]
    def on_start(self,broker):pass
    def on_data(self,timestamp,data,context,broker):
        role=self.ordered.get(timestamp)
        if role is None:raise RuntimeError(f"unexpected event {timestamp}")
        day,act=role
        if act=="entry_decision":
            if broker.get_position("USDJPY"):raise RuntimeError("Already in position")
            order=broker.submit_order("USDJPY",NOTIONAL)
            if order is None:raise RuntimeError("Native entry rejected")
            self.events.append((day,act,timestamp,order))
        elif act=="exit_decision":
            if broker.get_position("USDJPY") is None:raise RuntimeError("Missing open position")
            order=broker.close_position("USDJPY")
            if order is None:raise RuntimeError("Native exit rejected")
            self.events.append((day,act,timestamp,order))
        elif act in ("buy_ask_fill","sell_bid_fill"):
            pass
    def on_end(self,broker):
        if broker.get_position("USDJPY") is not None:raise RuntimeError("Open exposure at end")

def run_arm(secs,calendar,name,group,delay,extra):
    events=[]
    rejected=[]
    for d in SMOKE_DAYS:
        cal=calendar.filter(pl.col("session")==d)
        if cal.is_empty() or not bool(cal[group][0]):continue
        four,reason=selected_seconds(secs,d,delay,extra)
        if four is None:
            rejected.append({"day":d.isoformat(),"reason":reason})
            continue
        events+=four
    if not events:return {"arm":name,"n":0,"status":"INELIGIBLE","rejections":rejected}
    event_frame=pl.DataFrame(events).sort("timestamp")
    ordered={r["timestamp"]:(r["session"],r["role"]) for r in events}
    if len(ordered)!=len(events):raise RuntimeError("Repeated event timestamp across dates")
    if not all(
        event_frame["timestamp"][i]<event_frame["timestamp"][i+1]
        for i in range(event_frame.height-1)):
        raise RuntimeError("Non-strict time sequence")
    px=(event_frame.select("timestamp",pl.lit("USDJPY").alias("symbol"),
                           pl.col("price").alias("open"))
        .with_columns(pl.col("open").alias("high"),pl.col("open").alias("low"),
                      pl.col("open").alias("close"),pl.lit(1.0).alias("volume")))
    starting_jpy=NOTIONAL*float(px["open"][0])
    strategy=QuoteLong(ordered)
    cfg=BacktestConfig(
        initial_cash=starting_jpy,allow_leverage=True,initial_margin=.5,
        execution_mode=ExecutionMode.NEXT_BAR,execution_price=ExecutionPrice.OPEN,
        share_type=ShareType.FRACTIONAL,commission_type=CommissionType.NONE,
        slippage_type=SlippageType.FIXED,slippage_fixed=0,
        partial_fills_allowed=False)
    result=Engine(DataFeed(prices_df=px),strategy,cfg).run()
    orders=pl.DataFrame([{"session":d,"role":act,"submitted_at":t,
              "filled_at":o.filled_at,"price":float(o.filled_price),
              "quantity":float(o.quantity),"status":o.status.value}
             for d,act,t,o in strategy.events]).sort("submitted_at")
    assert orders.height==2*(event_frame.height//4)
    if orders.filter(pl.col("status")!="filled").height:raise RuntimeError("Unexpected native fill")
    fills=event_frame.filter(pl.col("role").is_in(["buy_ask_fill","sell_bid_fill"])).select(
        "session","role","timestamp","price","src_bid","src_ask",
        "distance_seconds","spread_bound_pips")
    entry=orders.filter(pl.col("role")=="entry_decision").select(
        "session",pl.col("filled_at").alias("entry_at"),pl.col("price").alias("entry_price"))
    exit=orders.filter(pl.col("role")=="exit_decision").select(
        "session",pl.col("filled_at").alias("exit_at"),pl.col("price").alias("exit_price"))
    src_entry=fills.filter(pl.col("role")=="buy_ask_fill").select(
        "session",pl.col("timestamp").alias("expected_entry_at"),
        pl.col("price").alias("expected_entry"),pl.col("src_ask").alias("entry_source_ask"),
        pl.col("src_bid").alias("entry_source_bid"),
        pl.col("spread_bound_pips").alias("entry_spread_bound_pips"))
    src_exit=fills.filter(pl.col("role")=="sell_bid_fill").select(
        "session",pl.col("timestamp").alias("expected_exit_at"),
        pl.col("price").alias("expected_exit"),pl.col("src_bid").alias("exit_source_bid"),
        pl.col("src_ask").alias("exit_source_ask"),
        pl.col("spread_bound_pips").alias("exit_spread_bound_pips"))
    trades=(entry.join(exit,on="session",validate="1:1")
        .join(src_entry,on="session",validate="1:1")
        .join(src_exit,on="session",validate="1:1")
        .sort("session")
        .with_columns(((pl.col("exit_price")-pl.col("entry_price"))*NOTIONAL).alias("native_pnl_jpy"),
                      ((pl.col("exit_source_bid")-pl.col("entry_source_ask"))/PIP).alias("gross_bidask_pips")))
    if trades.filter((pl.col("entry_at")!=pl.col("expected_entry_at"))|
                     (pl.col("exit_at")!=pl.col("expected_exit_at"))).height:
        raise RuntimeError("Executed at unexpected quote time")
    if ((trades["entry_price"]-trades["expected_entry"]).abs().max()>1e-9 or
         (trades["exit_price"]-trades["expected_exit"]).abs().max()>1e-9):
        raise RuntimeError("Native Engine price mismatch to quote source")
    source_oracle=(trades["exit_source_bid"]-trades["entry_source_ask"]-2*extra*PIP)*NOTIONAL
    oracle_max=float((source_oracle-trades["native_pnl_jpy"]).abs().max())
    pnl_jpy=float(result.metrics["final_value"])-starting_jpy
    recon_err=abs(pnl_jpy-float(trades["native_pnl_jpy"].sum()))
    assert oracle_max<1e-6 and recon_err<1e-5
    trades=trades.with_columns((pl.col("native_pnl_jpy")/pl.col("exit_price")).alias("pnl_usd"))
    daily=calendar.select("session").join(trades.select("session","pnl_usd"),on="session",how="left").with_columns(
        pl.col("pnl_usd").fill_null(0)).with_columns(
        (10000+pl.col("pnl_usd").cum_sum()).alias("equity_usd"))
    times=([datetime.combine(calendar["session"][0]-timedelta(days=1),time(0,0),JST)]
           +[datetime.combine(d,time(0,0),JST) for d in daily["session"]])
    eq=EquityCurve(times,[10000]+daily["equity_usd"].to_list(),periods_per_year_override=252)
    analyzer=TradeAnalyzer([SimpleNamespace(pnl=p,pnl_percent=p/10000,status="closed") for p in trades["pnl_usd"]])
    report={"arm":name,"type":group,"delay_seconds":delay,"extra_slippage_pips_per_leg":extra,
            "status":"ENGINEERING_SMOKE_ONLY","n":trades.height,
            "mean_gross_bidask_pips":float(trades["gross_bidask_pips"].mean()),
            "mean_net_quote_pips":float((trades["exit_price"]-trades["entry_price"]).mean()/PIP),
            "net_usd":float(trades["pnl_usd"].sum()),
            "pnl_jpy":pnl_jpy,"engine_jpy_reconciliation_error":recon_err,
            "source_quote_oracle_error":oracle_max,
            "mean_entry_spread_pips":float(trades["entry_spread_bound_pips"].mean()),
            "mean_exit_spread_pips":float(trades["exit_spread_bound_pips"].mean()),
            "profit_factor":float(analyzer.profit_factor) if math.isfinite(float(analyzer.profit_factor)) else None,
            "daily_sharpe":float(eq.sharpe) if math.isfinite(float(eq.sharpe)) else None,
            "dates":trades["session"].dt.strftime("%Y-%m-%d").to_list(),
            "rejected":rejected,"no_protected_data_read":True}
    folder=OUT/"runs"/name
    folder.mkdir(parents=True,exist_ok=True)
    event_frame.write_parquet(folder/"quote_event_snapshots.parquet")
    orders.write_parquet(folder/"native_orders.parquet")
    trades.write_parquet(folder/"native_trades.parquet")
    daily.write_parquet(folder/"daily_equity.parquet")
    write_json(folder/"result.json",report)
    return report

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    secs,quality=load()
    cal=pl.read_parquet(CAL).filter(pl.col("session")<=date(2025,6,30)).select(
        "session","gotobi","ordinary","year","weekday").sort("session")
    results=[]
    for name,group,latency,extra in ARM:
        report=run_arm(secs,cal,name,group,latency,extra)
        print("SMOKE",name,report["n"],report.get("net_usd"),flush=True)
        results.append(report)
    manifest={"kind":"ENGINEERING_SMOKE_NOT_PREREGISTERED_MAIN_EVALUATION",
              "source_quality":quality,"results":results,
              "sample_dates":[d.isoformat() for d in SMOKE_DAYS],
              "export_rate_limit_observed":429,"prior_incomplete_export_excluded":True,
              "selection_uses_prior_observed_June10":True,
              "full_pilot":"BLOCKED_ON_SOURCE_EXPORTS","ready_for_truthful_quote_execution_mechanics":True,
              "live_broker_fill_truth_verified":False}
    write_json(OUT/"smoke_result.json",manifest)
    print(json.dumps({"status":manifest["kind"],"arm_summaries":[{
        "arm":a["arm"],"n":a["n"],"net_usd":a.get("net_usd")} for a in results]},indent=2),flush=True)

if __name__=="__main__":main()
