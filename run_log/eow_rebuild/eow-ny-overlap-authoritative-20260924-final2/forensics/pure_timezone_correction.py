#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime, timezone
import sys, json
import numpy as np
import polars as pl

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT))
from src.eow_rebuild import load_config, parse_utc, prepare_all_markets, build_events, EventBuildResult, legacy_oof_scores, trade_summary

RUN=ROOT/"run_log/eow_rebuild/eow-ny-overlap-authoritative-20260924-final2"
OUT=RUN/"forensics"
config=load_config(ROOT/"config/eow_rebuild.yaml")
start=parse_utc(config["validation"]["initial_training"]["start"])
end=datetime(2024,12,31,23,59,59,tzinfo=timezone.utc)
markets=prepare_all_markets(ROOT,config,end=end)
legacy=build_events(markets,config,variant="legacy_parity",roundtrip_cost_bps=4,decision_start=start,decision_end=end)
tz=build_events(markets,config,variant="timezone_only",roundtrip_cost_bps=4,decision_start=start,decision_end=end)
legacy_scores,legacy_model=legacy_oof_scores(legacy,markets,config)

# Pure timezone treatment: only DE30/NAS100 get local-clock session treatment.
by_old={}
by_new={}
for e in legacy.events: by_old.setdefault(e.symbol,[]).append(e)
for e in tz.events: by_new.setdefault(e.symbol,[]).append(e)
mixed_events=[]
for sym in ["JP225","HK33","DE30","NAS100"]:
    mixed_events.extend(by_old[sym] if sym in {"JP225","HK33"} else by_new[sym])
mixed=EventBuildResult("pure_timezone_only",4.0,mixed_events,pl.DataFrame(),{})
mixed_scores,mixed_model=legacy_oof_scores(mixed,markets,config)

def rows(events,scores):
    return pl.DataFrame([{
      "event_key":f"{e.symbol}|{e.date}","symbol":e.symbol,"date":e.date,
      "r":float(e.r_multiple),"score":float(s),"selected":bool(float(s)>=.5)
    } for e,s in zip(events,scores)])
ld=rows(legacy.events,legacy_scores); md=rows(mixed.events,mixed_scores)

per=[]
for sym in ["JP225","HK33","DE30","NAS100"]:
    a=ld.filter(pl.col("symbol")==sym); b=md.filter(pl.col("symbol")==sym)
    per.append({
      "symbol":sym,
      "legacy_candidates":len(a),"mixed_candidates":len(b),
      "legacy_selected":int(a["selected"].sum()),"mixed_selected":int(b["selected"].sum()),
      "legacy_selected_r":float(a.filter(pl.col("selected"))["r"].sum()),
      "mixed_selected_r":float(b.filter(pl.col("selected"))["r"].sum()),
      "selected_delta_r":float(b.filter(pl.col("selected"))["r"].sum()-a.filter(pl.col("selected"))["r"].sum()),
    })

# Gate spillover on JP/HK exact legacy events: all event paths identical by construction.
spill=[]
for sym in ["JP225","HK33"]:
    a=ld.filter(pl.col("symbol")==sym).select("event_key","r","score","selected")
    b=md.filter(pl.col("symbol")==sym).select("event_key",pl.col("score").alias("score_new"),pl.col("selected").alias("selected_new"))
    m=a.join(b,on="event_key")
    spill.append({
      "symbol":sym,"events":len(m),
      "mean_abs_score_change":float((m["score_new"]-m["score"]).abs().mean()),
      "gate_flips":int((m["selected_new"]!=m["selected"]).sum()),
      "legacy_selected_r":float(m.filter(pl.col("selected"))["r"].sum()),
      "mixed_model_selected_r":float(m.filter(pl.col("selected_new"))["r"].sum()),
      "meta_spillover_delta_r":float(m.filter(pl.col("selected_new"))["r"].sum()-m.filter(pl.col("selected"))["r"].sum()),
    })

payload={
 "definition":"Only DE30/NAS100 events receive timezone/local-session treatment. JP225/HK33 use exact legacy event objects. Shared legacy meta model is then retrained, so JP/HK changes measure cross-asset model spillover only.",
 "legacy":{"auc":legacy_model.mean_auc,"summary":trade_summary(legacy.events,legacy_scores,threshold=.5)},
 "pure_timezone":{"auc":mixed_model.mean_auc,"summary":trade_summary(mixed.events,mixed_scores,threshold=.5)},
 "delta_net_r":trade_summary(mixed.events,mixed_scores,threshold=.5)["net_r"]-trade_summary(legacy.events,legacy_scores,threshold=.5)["net_r"],
 "per_instrument":per,
 "jp_hk_meta_spillover":spill,
}
(OUT/"pure_timezone_correction.json").write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
print(json.dumps(payload,indent=2))
