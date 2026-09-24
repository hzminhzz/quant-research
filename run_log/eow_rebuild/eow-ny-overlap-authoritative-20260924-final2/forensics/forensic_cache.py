#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, pickle, sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, polars as pl

ROOT=Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from src.eow_rebuild import (
    EventBuildResult, build_events, legacy_oof_scores, legacy_reported_sharpe,
    load_config, parse_utc, portfolio_daily_mtm, prepare_all_markets,
    score_frozen_model, trade_summary, walk_forward_scores
)

RUN=ROOT/"run_log/eow_rebuild/eow-ny-overlap-authoritative-20260924-final2"
OUT=RUN/"forensics"
CACHE=OUT/"cache"
CFG=ROOT/"config/eow_rebuild.yaml"
UTC=timezone.utc

def event_frame(events,scores):
    rows=[]
    for e,s in zip(events,scores):
        rows.append({
            "event_key":f"{e.symbol}|{e.date}",
            "symbol":e.symbol,"strategy_date":e.date,"year":int(e.date[:4]),"month":e.date[:7],
            "decision_time":e.decision_time,"entry_time":e.entry_time,"exit_time":e.exit_time,
            "direction":int(e.direction),"label":int(e.label),"r_multiple":float(e.r_multiple),
            "score":float(s),"selected":bool(float(s)>=0.5),"exit_reason":e.exit_reason,
            "holding_bars":int(e.holding_bars),"entry_price":float(e.entry_price),"delta":float(e.delta),
            "or_range":float(e.or_range),"atr20":float(e.atr20),
            "range_to_atr20_raw":float(e.or_range/e.atr20) if e.atr20 else None,
            **{f"feature_{k}":float(v) for k,v in e.features.items()},
        })
    return pl.DataFrame(rows,infer_schema_length=None)

def summary(events,scores,markets,cost):
    gated=trade_summary(events,scores,threshold=.5)
    gd,p=portfolio_daily_mtm(events,scores,markets,threshold=.5,risk_unit_pct=1.0,roundtrip_cost_bps=cost)
    ones=np.ones(len(events))
    ung=trade_summary(events,ones,threshold=.5)
    ud,up=portfolio_daily_mtm(events,ones,markets,threshold=.5,risk_unit_pct=1.0,roundtrip_cost_bps=cost)
    gated["portfolio"]=p; ung["portfolio"]=up
    return {"candidate_events":len(events),"gated":gated,"ungated":ung,
            "packed_sharpe":legacy_reported_sharpe(events,scores,threshold=.5)}

def write_json(path,obj): path.write_text(json.dumps(obj,indent=2,sort_keys=True,default=str)+"\n")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--step",required=True,choices=[
        "legacy_dev","tz_dev","can4_legacy_dev","can4_block_legacy_dev","can4_wf_dev","can6_fixed_can4scores","can6_wf_dev","hold","full_legacy","tz_pit"])
    a=ap.parse_args()
    OUT.mkdir(parents=True,exist_ok=True); CACHE.mkdir(parents=True,exist_ok=True)
    config=load_config(CFG)
    dev_start=parse_utc(config["validation"]["initial_training"]["start"])
    dev_end=datetime(2024,12,31,23,59,59,tzinfo=UTC)
    hold_start=parse_utc(config["validation"]["final_holdout"]["start"])
    hold_end=parse_utc(config["validation"]["final_holdout"]["end"])
    step=a.step
    market_end = hold_end if step in {"hold","full_legacy"} else dev_end
    markets=prepare_all_markets(ROOT,config,end=market_end)
    diagnostics={}
    if step=="legacy_dev":
        res=build_events(markets,config,variant="legacy_parity",roundtrip_cost_bps=4,decision_start=dev_start,decision_end=dev_end)
        scores,m=legacy_oof_scores(res,markets,config); diagnostics={"mean_auc":m.mean_auc}
    elif step=="tz_dev":
        res=build_events(markets,config,variant="timezone_only",roundtrip_cost_bps=4,decision_start=dev_start,decision_end=dev_end)
        scores,m=legacy_oof_scores(res,markets,config); diagnostics={"mean_auc":m.mean_auc}
    elif step=="can4_legacy_dev":
        res=build_events(markets,config,variant="corrected",roundtrip_cost_bps=4,decision_start=dev_start,decision_end=dev_end)
        scores,m=legacy_oof_scores(res,markets,config); diagnostics={"mean_auc":m.mean_auc}
    elif step=="can4_block_legacy_dev":
        base=build_events(markets,config,variant="corrected",roundtrip_cost_bps=4,decision_start=dev_start,decision_end=dev_end)
        order={"JP225":0,"HK33":1,"DE30":2,"NAS100":3}
        block_events=sorted(base.events,key=lambda e:(order[e.symbol],parse_utc(e.decision_time)))
        res=EventBuildResult("corrected_block_order",4.0,block_events,pl.DataFrame(),{})
        scores,m=legacy_oof_scores(res,markets,config); diagnostics={"mean_auc":m.mean_auc,"ordering":"JP225->HK33->DE30->NAS100"}
    elif step=="can4_wf_dev":
        res=build_events(markets,config,variant="corrected",roundtrip_cost_bps=4,decision_start=dev_start,decision_end=dev_end)
        scores,wf,_=walk_forward_scores(res.events,config); diagnostics={"walk_forward":wf}
    elif step=="can6_fixed_can4scores":
        res=build_events(markets,config,variant="corrected",roundtrip_cost_bps=6,decision_start=dev_start,decision_end=dev_end)
        prior=pl.read_parquet(CACHE/"can4_wf_dev.parquet")
        smap={r["event_key"]:float(r["score"]) for r in prior.select("event_key","score").to_dicts()}
        scores=np.asarray([smap[f"{e.symbol}|{e.date}"] for e in res.events],dtype=float)
        diagnostics={"scores":"frozen from can4_wf_dev; only cost changed 4->6bp"}
    elif step=="can6_wf_dev":
        res=build_events(markets,config,variant="corrected",roundtrip_cost_bps=6,decision_start=dev_start,decision_end=dev_end)
        scores,wf,_=walk_forward_scores(res.events,config); diagnostics={"walk_forward":wf}
    elif step=="hold":
        res=build_events(markets,config,variant="corrected",roundtrip_cost_bps=6,decision_start=hold_start,decision_end=hold_end)
        with open(RUN/"frozen_model.pkl","rb") as f: model=pickle.load(f)
        scores=score_frozen_model(model,res.events); diagnostics={"model":"frozen_model.pkl"}
    elif step=="full_legacy":
        res=build_events(markets,config,variant="legacy_parity",roundtrip_cost_bps=4,decision_start=dev_start,decision_end=hold_end)
        scores,m=legacy_oof_scores(res,markets,config); diagnostics={"mean_auc":m.mean_auc}
    elif step=="tz_pit":
        pit={k:replace(v,legacy_spx_close=v.canonical_spx_close.copy(),legacy_spx_vwap=v.canonical_spx_vwap.copy()) for k,v in markets.items()}
        res=build_events(pit,config,variant="timezone_only",roundtrip_cost_bps=4,decision_start=dev_start,decision_end=dev_end)
        scores,m=legacy_oof_scores(res,markets,config); diagnostics={"mean_auc":m.mean_auc,"counterfactual":"canonical SPX availability arrays under timezone-only legacy-like entry/exit"}
    cost=6 if step in {"can6_fixed_can4scores","can6_wf_dev","hold"} else 4
    frame=event_frame(res.events,scores)
    frame.write_parquet(CACHE/f"{step}.parquet")
    payload={"step":step,"diagnostics":diagnostics,"summary":summary(res.events,scores,markets,cost)}
    write_json(CACHE/f"{step}.json",payload)
    print(json.dumps({"status":"OK","step":step,"events":len(res.events),"gated":payload["summary"]["gated"]["trade_count"],"net_r":payload["summary"]["gated"]["net_r"]},indent=2))

if __name__=="__main__": main()
