#!/usr/bin/env python3
from __future__ import annotations
import json,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from src.eow_rebuild import build_events,load_config,parse_utc,prepare_all_markets
RUN=ROOT/"run_log/eow_rebuild/eow-ny-overlap-authoritative-20260924-final2"; OUT=RUN/"forensics"
cfg=load_config(ROOT/"config/eow_rebuild.yaml")
dev_start=parse_utc(cfg["validation"]["initial_training"]["start"]); dev_end=datetime(2024,12,31,23,59,59,tzinfo=timezone.utc)
hold_end=parse_utc(cfg["validation"]["final_holdout"]["end"])
rows={}
for scope,end in [("development",dev_end),("full_historical",hold_end)]:
    markets=prepare_all_markets(ROOT,cfg,end=end)
    for variant,cost in [("legacy_parity",4.0),("timezone_only",4.0),("corrected_4bp",4.0),("corrected_6bp",6.0)]:
        v="corrected" if variant.startswith("corrected") else variant
        r=build_events(markets,cfg,variant=v,roundtrip_cost_bps=cost,decision_start=dev_start,decision_end=end)
        rows[f"{scope}/{variant}"]=r.diagnostics
(OUT/"build_diagnostics.json").write_text(json.dumps(rows,indent=2,sort_keys=True,default=str)+"\n")
print(json.dumps(rows,indent=2,sort_keys=True,default=str))
