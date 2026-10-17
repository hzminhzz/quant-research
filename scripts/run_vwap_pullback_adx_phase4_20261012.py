#!/usr/bin/env python3
"""Phase 4 Strategy 2 native ml4t.backtest research only, 2026 H1 NQ.F proxy.

EXPLORATORY: provider-defined continuous NQ.F, not dated CME contract data.
All strategy orders are executed by ml4t.backtest.Engine, not a custom simulator.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl
from ml4t.engineer import compute_features
from ml4t.backtest import (
    Strategy, DataFeed, Engine, BacktestConfig, OrderType, ExecutionMode,
    StopFillMode, CommissionType, ContractSpec, AssetClass,
)
from ml4t.backtest.config import SlippageType, FillOrdering
from ml4t.backtest.analytics.metrics import sharpe_ratio, calmar_ratio, max_drawdown, cagr, returns_from_values

ROOT = Path(__file__).resolve().parents[1]
SID = "vwap_pullback_adx_nq_20261012_proxy_v2"
OUT = ROOT / "run_log" / SID / "phase4"
SOURCE = ROOT / "data/processed/vwap_adx_nqf_2026h1_1m.parquet"
QUALITY = ROOT / "run_log" / SID / "phase2_quality_report.json"
SYM = "NQ.F"
EXPECTED_SHA = "a0670b34b2175ca0df4a7ab98fa79bb02650cf4cce64ed67261ad29f706ebaad"
TICK = 0.25
MULTIPLIER = 20
INITIAL = 1_000_000.0


def sha(path: Path) -> str:
    dig=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""):
            dig.update(b)
    return dig.hexdigest()


def prepare() -> pl.DataFrame:
    if sha(SOURCE) != EXPECTED_SHA:
        raise RuntimeError("Frozen 2026 H1 source changed")
    x=pl.read_parquet(SOURCE).sort("timestamp")
    if x["timestamp"].n_unique()!=x.height or x["volume"].min()<=0:
        raise RuntimeError("Bad source identity/volume")
    x=compute_features(x,[{"name":"adx","params":{"period":14}}])
    ct=pl.col("timestamp").dt.convert_time_zone("America/Chicago")
    x=x.with_columns(ct.alias("ct")).with_columns(
        pl.col("ct").dt.date().alias("day"),
        pl.col("ct").dt.strftime("%H:%M").alias("clock"),
    )
    is_cash=pl.col("clock")>=pl.lit("08:30")
    x=x.with_columns(
        pl.when(is_cash).then(
            ((pl.col("high")+pl.col("low")+pl.col("close"))/3)*pl.col("volume")
        ).otherwise(0).cum_sum().over("day").alias("pv"),
        pl.when(is_cash).then(pl.col("volume")).otherwise(0).cum_sum().over("day").alias("vv"),
        pl.col("high").rolling_max(5).alias("next_tp"),
        pl.col("low").rolling_min(20).alias("next_sl"),
        pl.col("close").shift(1).alias("prior_close"),
        pl.col("adx").shift(1).alias("prior_adx"),
    ).with_columns(
        pl.when(pl.col("vv")>0).then(pl.col("pv")/pl.col("vv")).otherwise(None).alias("vwap")
    )
    or_high=(x.filter(pl.col("clock").is_between(pl.lit("08:30"),pl.lit("08:59")))
        .group_by("day").agg(pl.col("high").max().alias("or_high"),pl.len().alias("or_count")))
    x=x.join(or_high,on="day",how="left")
    quality=json.loads(QUALITY.read_text())
    good=quality["accepted_sessions"]
    x=x.filter(pl.col("day").cast(pl.String).is_in(good)
        & pl.col("clock").is_between(pl.lit("08:30"),pl.lit("15:55")))
    if x["day"].n_unique()!=122 or x.height!=122*446 or x.filter(pl.col("or_count")!=30).height:
        raise RuntimeError("Session coverage mismatch")
    if x.filter((pl.col("clock")=="15:55")).height!=122:
        raise RuntimeError("Missing exact 15:55 open")
    if x.filter(pl.col("vwap").is_null()|pl.col("adx").is_null()).height:
        raise RuntimeError("Missing causal indicators")
    return x.with_columns(pl.lit(SYM).alias("asset"))


def high_tick(v:float)->float:
    return math.ceil((v-1e-9)/TICK)*TICK


def low_tick(v:float)->float:
    return math.floor((v+1e-9)/TICK)*TICK


def order_status(order)->str:
    return order.status.value if order is not None else "missing"


class VwapPullback(Strategy):
    """State transitions evaluated on completed minute t; native fills at t+1 open."""

    def __init__(self, mode:str):
        self.mode=mode
        self.day=None
        self.state="IDLE"
        self.armed_at=None
        self.pending=None
        self.active=False
        self.tp_order=None
        self.sl_order=None
        self.metrics=Counter()
        self.signal_log=[]
        self.fill_windows=[]

    def cancel_children(self,broker):
        for order in [self.tp_order,self.sl_order]:
            if order is not None and order_status(order)=="pending":
                broker.cancel_order(order.order_id)
        self.tp_order=None
        self.sl_order=None

    def signal(self, timestamp, bar, broker):
        tp=high_tick(float(bar["signals"]["next_tp"]))
        sl=low_tick(float(bar["signals"]["next_sl"]))
        if not (tp>sl>0):
            self.metrics["bad_entry_levels"]+=1
            return
        # Submit entry first. Submit protective STOP ahead of LIMIT, making
        # stop-first queue ordering on an OHLC-both-hit bar when EXIT_FIRST
        # processes eligible native orders in submission order.
        entry=broker.submit_order(SYM,1,order_type=OrderType.MARKET)
        if entry is None or order_status(entry)!="pending":
            self.metrics["entry_submit_failure"]+=1
            return
        stop=broker.submit_order(SYM,-1,order_type=OrderType.STOP,stop_price=sl)
        take=broker.submit_order(SYM,-1,order_type=OrderType.LIMIT,limit_price=tp)
        if stop is None or take is None or order_status(stop)!="pending" or order_status(take)!="pending":
            self.metrics["child_submit_failure"]+=1
            for order in (stop,take,entry):
                if order is not None and order_status(order)=="pending":
                    broker.cancel_order(order.order_id)
            return
        # The parent property is descriptive; ml4t-backtest v0.1.7 is not
        # an atomic broker OCO engine. Engine results must be audited.
        stop.parent_id=entry.order_id
        take.parent_id=entry.order_id
        self.sl_order=stop
        self.tp_order=take
        self.pending=entry
        self.state="CONSUMED"
        self.signal_log.append({
            "mode":self.mode,"signal_at":timestamp.isoformat(),
            "expected_entry_at":(timestamp+timedelta(minutes=1)).isoformat(),
            "take_profit":tp,"stop_loss":sl,
            "adx":float(bar["signals"]["adx"]),
            "adx_prev":float(bar["signals"]["prior_adx"]),
            "vwap":float(bar["signals"]["vwap"]),
            "decision_close":float(bar["close"]),
        })
        self.metrics["signals"]+=1

    def on_data(self,timestamp,data,context,broker):
        bar=data[SYM]
        local=timestamp.astimezone(__import__("zoneinfo").ZoneInfo("America/Chicago"))
        day=local.date()
        clock=local.strftime("%H:%M")
        if self.day!=day:
            if self.day is not None and (self.pending is not None or broker.get_position(SYM)):
                raise RuntimeError("Overnight inventory or entry remained pending")
            self.cancel_children(broker)
            self.day=day
            self.state="IDLE"
            self.armed_at=None
            self.active=False
        pos=broker.get_position(SYM)
        qty=float(pos.quantity) if pos else 0
        if qty<0 or qty>1:
            raise RuntimeError(f"Reversal/overfill: {qty} at {timestamp}")
        # If our pending entry filled, it can also exit on the same entry bar.
        if self.pending is not None:
            entry_status=order_status(self.pending)
            if entry_status=="filled":
                self.pending=None
                self.metrics["filled_entries"]+=1
                if qty==0:
                    self.cancel_children(broker)
                    self.active=False
                    self.state="IDLE"
                    self.metrics["entry_bar_exits"]+=1
                    return
                self.active=True
            elif entry_status in ("cancelled","rejected"):
                self.cancel_children(broker)
                self.pending=None
                self.state="IDLE"
                self.metrics["rejected_entry"]+=1
                return
            else:
                # Entry is submitted at t close. It must fill at t+1 open.
                return
        if self.active and qty==0:
            self.cancel_children(broker)
            self.active=False
            self.state="IDLE"
            self.armed_at=None
            self.metrics["closed_trades"]+=1
            # Never re-arm based on the ambiguous bar that just exited.
            return
        if clock=="15:54":
            if qty:
                self.cancel_children(broker)
                exit_order=broker.submit_order(SYM,-1,order_type=OrderType.MARKET)
                if exit_order is None:
                    raise RuntimeError("Failed to queue 15:55 market flat")
                self.metrics["hard_exits_queued"]+=1
            return
        if clock>="15:55":
            if qty:
                self.metrics["late_inventory"]+=1
                raise RuntimeError("Not flat at 15:55 CT")
            self.cancel_children(broker)
            return
        if qty or self.active:
            return
        if clock<"09:00" or clock>="15:54":
            return
        signal=bar.get("signals",{})
        if (not signal or signal.get("or_high") is None
            or signal.get("next_tp") is None or signal.get("next_sl") is None
            or signal.get("vwap") is None or signal.get("adx") is None
            or signal.get("prior_adx") is None or signal.get("prior_close") is None):
            return
        close=float(bar["close"])
        high=float(bar["high"])
        low=float(bar["low"])
        or_high=float(signal["or_high"])
        vwap=float(signal["vwap"])
        adx=float(signal["adx"])
        prev_adx=float(signal["prior_adx"])
        if self.state=="IDLE":
            if float(signal["prior_close"])<=or_high and high>or_high and close>or_high:
                self.metrics["g1_breakouts"]+=1
                if self.mode=="B1":
                    self.signal(timestamp,bar,broker)
                else:
                    self.state="ARMED"
                    self.armed_at=timestamp
            return
        if self.state=="ARMED":
            if timestamp<=self.armed_at:
                return
            if low<=vwap:
                self.state="TOUCHED"
                self.metrics["g2_touches"]+=1
            else:
                return
        if self.state=="RETOUCH":
            if low<=vwap:
                self.state="TOUCHED"
                self.metrics["g2_touches"]+=1
            else:
                return
        if self.state=="TOUCHED":
            if close<=vwap:
                return
            self.metrics["g3_reclaims"]+=1
            if self.mode=="B2":
                self.signal(timestamp,bar,broker)
            elif adx>20 and adx<=prev_adx:
                self.metrics["g4_adx"]+=1
                self.signal(timestamp,bar,broker)
            elif adx>20:
                self.state="WAIT_ADX"
                self.metrics["wait_adx"]+=1
            else:
                self.state="RETOUCH"
            return
        if self.state=="WAIT_ADX":
            if close<=vwap:
                self.state="TOUCHED"
            elif adx<=20:
                self.state="RETOUCH"
            elif adx<=prev_adx:
                self.metrics["g4_adx"]+=1
                self.signal(timestamp,bar,broker)

    def on_end(self,broker):
        pos=broker.get_position(SYM)
        if pos and pos.quantity:
            raise RuntimeError("Native backtest ended with open inventory")


def run_mode(feed:pl.DataFrame,mode:str,cost_label:str,fee:float,slip_pts:float)->dict:
    strat=VwapPullback(mode)
    config=BacktestConfig(
        initial_cash=INITIAL,
        allow_short_selling=False,
        allow_leverage=True,
        fixed_margin_schedule={SYM:(25000.0,20000.0)},
        execution_mode=ExecutionMode.NEXT_BAR,
        fill_ordering=FillOrdering.EXIT_FIRST,
        stop_fill_mode=StopFillMode.STOP_PRICE,
        commission_type=CommissionType.PER_CONTRACT if fee else CommissionType.NONE,
        commission_per_share=fee,
        slippage_type=SlippageType.FIXED if slip_pts else SlippageType.NONE,
        slippage_fixed=slip_pts,
    )
    spec=ContractSpec(symbol=SYM,asset_class=AssetClass.FUTURE,multiplier=MULTIPLIER,
                      tick_size=TICK,margin=25000.0)
    result=Engine(
        DataFeed(
            prices_df=feed.select("timestamp","asset","open","high","low","close","volume"),
            signals_df=feed.select("timestamp","asset","or_high","prior_close","vwap","adx",
                                   "prior_adx","next_tp","next_sl"),
        ),
        strat,config,contract_specs={SYM:spec},
    ).run()
    folder=OUT / f"{mode}_{cost_label}"
    if folder.exists():
        raise FileExistsError(f"Refuse to overwrite prior trial: {folder}")
    folder.mkdir(parents=True)
    fills=result.to_fills_dataframe()
    trades=result.to_trades_dataframe()
    curve=result.to_equity_dataframe()
    trades.write_parquet(folder/"trades.parquet")
    fills.write_parquet(folder/"fills.parquet")
    curve.write_parquet(folder/"equity.parquet")
    (folder/"signals.json").write_text(json.dumps(strat.signal_log,indent=2)+"\n")
    (folder/"transitions.json").write_text(json.dumps(strat.metrics,indent=2)+"\n")
    metrics=dict(result.metrics)
    day=curve.with_columns(pl.col("timestamp").dt.convert_time_zone("America/Chicago").dt.date().alias("day"))
    daily=day.group_by("day").agg(pl.col("equity").last().alias("equity")).sort("day")
    daily.write_parquet(folder/"daily_equity.parquet")
    wealth=[INITIAL,*daily["equity"].to_list()]
    daily_ret=returns_from_values(wealth)
    sharpe=sharpe_ratio(daily_ret,annualize=True) if np.std(daily_ret)>0 else None
    dd=max_drawdown(wealth)[0]
    years=len(daily_ret)/252
    cagr_value=cagr(INITIAL,wealth[-1],years) if years>0 and wealth[-1]>0 else None
    calmar=calmar_ratio(cagr_value,dd) if cagr_value is not None and dd else None
    complete=trades.filter(pl.col("status")=="closed") if trades.height else trades
    pnl=complete["pnl"].to_numpy() if complete.height else np.array([])
    final_equity=wealth[-1]
    net_pnl=final_equity-INITIAL
    trade_pnl=float(np.sum(pnl)) if pnl.size else 0.0
    reconcile=net_pnl-trade_pnl
    summary={
        "mode":mode,"cost":cost_label,"fee_per_side_usd":fee,
        "adverse_slippage_points_per_side":slip_pts,
        "trades":int(len(pnl)), "signals":len(strat.signal_log),
        "gross_pnl_total_usd":float(complete["gross_pnl"].sum()) if complete.height else 0.0,
        "native_trade_net_pnl_usd":trade_pnl,"net_account_pnl_usd":net_pnl,
        "reconciliation_difference_usd":reconcile,
        "win_rate":float(np.mean(pnl>0)) if pnl.size else None,
        "expectancy_net_usd":float(np.mean(pnl)) if pnl.size else None,
        "daily_equity_sharpe":float(sharpe) if sharpe is not None else None,
        "daily_equity_max_dd_pct":float(dd*100),
        "daily_equity_calmar":float(calmar) if calmar is not None else None,
        "max_open_position":1,
        "strategy_transitions":dict(strat.metrics),
        "native_engine_metrics":{k:(v.item() if isinstance(v,np.generic) else v) for k,v in metrics.items()
                                if isinstance(v,(str,int,float,np.generic,bool,type(None)))},
        "last_day":str(daily["day"].max()) if daily.height else None,
        "session_days":int(daily.height),
        "interpretation":"exploratory vendor-defined futures price proxy; not executable CME futures",
    }
    (folder/"metrics.json").write_text(json.dumps(summary,indent=2,default=str)+"\n")
    return summary


def main()->None:
    if OUT.exists() and any(OUT.iterdir()):
        raise FileExistsError(f"Phase4 path contains prior evidence; do not overwrite: {OUT}")
    feed=prepare()
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/"run_provenance.json").write_text(json.dumps({
        "session":SID,
        "source_sha256":sha(SOURCE),
        "source":str(SOURCE.relative_to(ROOT)),
        "model":"LSE NQ.F provider-defined continuous futures proxy",
        "contract_level":False,
        "CME_verified_volume":False,
        "CME_execution_verified":False,
        "development_interval":"2026-01-01 through 2026-06-30, Chicago cash sessions",
        "qualifying_sessions":122,
        "tick_points":TICK,"multiplier_usd_per_point_assumed":MULTIPLIER,
        "costs":"Illustrative not verified: $2.50/side and adverse 0.25 point/side",
        "assumptions":"Native ml4t-backtest NEXT_BAR; stop first submission ahead of limit; no atomic OCO; audit required",
    },indent=2)+"\n")
    reports=[]
    for mode in ("B1","B2","B3"):
        for label,fee,slip in (("gross",0.,0.),("cost",2.50,.25),("stress",2.50,.5)):
            print("START",mode,label,flush=True)
            summary=run_mode(feed,mode,label,fee,slip)
            reports.append(summary)
            print("DONE",mode,label,summary["trades"],summary["net_account_pnl_usd"],flush=True)
    (OUT/"all_trials.json").write_text(json.dumps(reports,indent=2,default=str)+"\n")
    print(json.dumps(reports,indent=2,default=str))


if __name__=="__main__":
    main()
