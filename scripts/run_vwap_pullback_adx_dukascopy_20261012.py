#!/usr/bin/env python3
"""Dukascopy-only 1m CFD OHLCV, native ML4T strategy; no NQ.F data.

Separate strategy version: CFD has no 15:55 bar. Positions are closed with
market order submitted after the 15:13 CT bar, filled at 15:14 CT bar OPEN.
Hypothetical NQ-equivalent PnL, not executable CFD or CME broker performance.
"""
from __future__ import annotations
import hashlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import polars as pl
import exchange_calendars as xcals
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import run_vwap_pullback_adx_phase4_20261012 as old
from scripts.run_vwap_pullback_adx_execfix_v3_20261012 import LegalLimitsEngine
from ml4t.backtest import OrderType

SID="vwap_pullback_adx_dukascopy_20261012_v1"
DATA=ROOT/"data/processed/vwap_adx_dukascopy_2026_1m.parquet"
SHA="4ce2efcf496fb77d936d12d866ef5ed5d1e1869879a6b30434a1d0232bb75425"
OUT=ROOT/"run_log"/SID
CHI=ZoneInfo("America/Chicago")
ASSET="DUK_USATECH"
START="08:30"
END="15:14"
MINUTES=405


class DukascopyClockStrategy(old.VwapPullback):
    def on_data(self,timestamp,data,context,broker):
        clock=timestamp.astimezone(CHI).strftime("%H:%M")
        if clock=="15:13":
            # The original CME clock is unreachable on this CFD feed.
            # Native NEXT_BAR executes any pending 15:12 signals at 15:13.
            if self.pending is not None:
                state=old.order_status(self.pending)
                if state=="pending":
                    raise RuntimeError("CFD close with unfilled market entry")
                if state=="filled":
                    self.metrics["filled_entries"]+=1
                self.pending=None
            self.cancel_children(broker)
            position=broker.get_position(ASSET)
            if position and position.quantity:
                o=broker.submit_order(ASSET,-int(position.quantity),order_type=OrderType.MARKET)
                if o is None:
                    raise RuntimeError("Cannot queue 15:14 CFD close")
                self.metrics["cfd_close_1514_queued"]+=1
            self.state="CONSUMED"
            return
        if clock=="15:14":
            position=broker.get_position(ASSET)
            if position and position.quantity:
                raise RuntimeError("CFD not flat at final 15:14 CT bar")
            self.cancel_children(broker)
            self.pending=None
            self.active=False
            self.state="IDLE"
            return
        return super().on_data(timestamp,data,context,broker)


def prepare():
    if hashlib.sha256(DATA.read_bytes()).hexdigest()!=SHA:
        raise RuntimeError("Data source changed")
    x=pl.read_parquet(DATA).sort("timestamp")
    if x["timestamp"].n_unique()!=x.height or x["symbol"].unique().to_list()!=[ASSET]:
        raise RuntimeError("Wrong CFD source")
    x=old.compute_features(x,[{"name":"adx","params":{"period":14}}])
    x=x.with_columns(pl.col("timestamp").dt.convert_time_zone("America/Chicago").alias("ct"))
    x=x.with_columns(pl.col("ct").dt.date().alias("day"),pl.col("ct").dt.strftime("%H:%M").alias("clock"))
    cash=pl.col("clock")>=pl.lit("08:30")
    x=x.with_columns(
        pl.when(cash).then((pl.col("high")+pl.col("low")+pl.col("close"))/3*pl.col("volume")).otherwise(0.0).cum_sum().over("day").alias("pv"),
        pl.when(cash).then(pl.col("volume")).otherwise(0.0).cum_sum().over("day").alias("vv"),
        pl.col("high").rolling_max(5).alias("next_tp"),
        pl.col("low").rolling_min(20).alias("next_sl"),
        pl.col("close").shift(1).alias("prior_close"),
        pl.col("adx").shift(1).alias("prior_adx"),
    ).with_columns(
        pl.when(pl.col("vv")>0).then(pl.col("pv")/pl.col("vv")).otherwise(None).alias("vwap")
    )
    orh=x.filter(pl.col("clock").is_between(pl.lit("08:30"),pl.lit("08:59"))).group_by("day").agg(
        pl.col("high").max().alias("or_high"),pl.len().alias("or_count")
    )
    return x.join(orh,on="day",how="left")


def session_filter(prepared,start:date,end:date):
    calendar=xcals.get_calendar("XNYS")
    schedule={t.date() for t in calendar.sessions_in_range(str(start),str(end))}
    early={t.date() for t in calendar.early_closes if start<=t.date()<=end}
    eligible=sorted(schedule-early)
    grouped=prepared.filter(pl.col("day").is_between(start,end)).partition_by("day",as_dict=True)
    accepted=[]
    rejects={}
    for day in eligible:
        d=grouped.get((day,))
        if d is None:
            rejects[str(day)]="MISSING_SOURCE_DAY"
            continue
        cash=d.filter(pl.col("clock").is_between(pl.lit(START),pl.lit(END)))
        clocks=cash["clock"].to_list()
        if cash.height!=MINUTES or len(set(clocks))!=MINUTES or clocks[0]!=START or clocks[-1]!=END:
            rejects[str(day)]=f"INCOMPLETE_CASH_GRID_{cash.height}"
            continue
        if cash["timestamp"].diff().drop_nulls().to_list().count(timedelta(minutes=1))!=MINUTES-1:
            rejects[str(day)]="NONCONSECUTIVE_CASH_MINUTES"
            continue
        if cash["volume"].min()<=0 or cash.filter(pl.col("clock").is_between(pl.lit("08:30"),pl.lit("08:59"))).height!=30:
            rejects[str(day)]="ZERO_VOLUME_OR_BAD_OPEN_RANGE"
            continue
        if cash.select("adx","prior_adx","prior_close","vwap","next_tp","next_sl","or_high").null_count().sum_horizontal().sum()!=0:
            rejects[str(day)]="INVALID_CAUSAL_FEATURE"
            continue
        accepted.append(day)
    bars=prepared.filter(pl.col("day").is_in(accepted)&pl.col("clock").is_between(pl.lit(START),pl.lit(END))).with_columns(pl.lit(ASSET).alias("asset"))
    assert bars.height==len(accepted)*MINUTES
    qa={
        "source":"Dukascopy USATECH.IDX/USD CFD ONLY",
        "source_hash":SHA,"start":str(start),"end":str(end),
        "calendar_full_sessions":len(eligible),
        "accepted":len(accepted),"accepted_days":list(map(str,accepted)),
        "exclusions":rejects,"bar_count":bars.height,
        "session_open_ct":"08:30","last_executable_open_ct":"15:14",
        "hard_flat_at":"15:14 bar OPEN; queued after 15:13 bar close",
        "no_1555_fill":True,"CME_volume":False,"NQF_source_used":False
    }
    return bars,qa


def run(section:str,start:date,end:date,experiments):
    dest=OUT/section
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError(f"Do not overwrite previous Duk evidence {dest}")
    full=prepare()
    bars,qa=session_filter(full,start,end)
    if section=="development" and qa["accepted"]<100:raise RuntimeError(f"Too few dev days: {qa}")
    if section=="validation" and qa["accepted"]<25:raise RuntimeError(f"Too few Jul-Aug days: {qa}")
    dest.mkdir(parents=True,exist_ok=True)
    (dest/"source_qa.json").write_text(json.dumps(qa,indent=2)+"\n")
    old.OUT=dest
    old.Engine=LegalLimitsEngine
    old.VwapPullback=DukascopyClockStrategy
    old.SYM=ASSET
    studies=[]
    for mode in ("B1","B2","B3"):
        for label,fee,slip in experiments:
            print("START",section,mode,label,flush=True)
            info=old.run_mode(bars,mode,label,fee,slip)
            studies.append(info)
            print("DONE",section,mode,label,info["trades"],round(info["net_account_pnl_usd"],2),flush=True)
    (dest/"all_trials.json").write_text(json.dumps(studies,indent=2,default=str)+"\n")
    print(json.dumps({k:qa[k] for k in ["start","end","calendar_full_sessions","accepted","exclusions"]},indent=2),flush=True)


def main():
    if not (ROOT/"run_log/research_sessions"/SID/"frozen_spec.json").exists():
        raise RuntimeError("Must freeze spec before evaluating results")
    mode=sys.argv[1] if len(sys.argv)>1 else "qa"
    if mode=="qa":
        full=prepare()
        for part,start,end in (("development",date(2026,1,1),date(2026,6,30)),
                               ("validation",date(2026,7,1),date(2026,8,17))):
            _,qa=session_filter(full,start,end)
            print(json.dumps({k:qa[k] for k in ["start","end","calendar_full_sessions","accepted","exclusions"]},indent=2))
        return
    if mode=="development":
        run(mode,date(2026,1,1),date(2026,6,30),
            [("gross",0.0,0.0),("cost",2.5,.25),("stress",2.5,.5)])
    elif mode=="validation":
        run(mode,date(2026,7,1),date(2026,8,17),
            [("gross",0.0,0.0),("cost",2.5,.25),("stress",2.5,.5)])
    elif mode=="stress4tick":
        run(mode,date(2026,1,1),date(2026,6,30),[("stress4tick",2.5,1.0)])
    elif mode=="robustness":
        from scripts.run_vwap_pullback_adx_phase6_20261012 import Queue1TickEngine
        # Use separately identified native adapter for conservative LIMIT fill threshold.
        global LegalLimitsEngine
        original=LegalLimitsEngine
        class DukQueueEngine(Queue1TickEngine):
            pass
        try:
            LegalLimitsEngine=DukQueueEngine
            run(mode,date(2026,1,1),date(2026,6,30),
                [("queue1tick",2.5,.25)])
        finally:
            LegalLimitsEngine=original
    else:
        raise ValueError(mode)
if __name__=="__main__":main()
