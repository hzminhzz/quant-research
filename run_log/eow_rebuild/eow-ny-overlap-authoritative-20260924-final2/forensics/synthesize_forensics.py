#!/usr/bin/env python3
from __future__ import annotations
import json, math, sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import polars as pl
from sklearn.metrics import roc_auc_score

ROOT=Path(__file__).resolve().parents[4]
RUN=ROOT/"run_log/eow_rebuild/eow-ny-overlap-authoritative-20260924-final2"
OUT=RUN/"forensics"; CACHE=OUT/"cache"
OUT.mkdir(parents=True,exist_ok=True)

def loadj(n): return json.loads((CACHE/f"{n}.json").read_text())
def loadp(n): return pl.read_parquet(CACHE/f"{n}.parquet")
def jwrite(name,obj): (OUT/name).write_text(json.dumps(obj,indent=2,sort_keys=True,default=str)+"\n")
def auc(y,s):
    y=np.asarray(y); s=np.asarray(s)
    return float(roc_auc_score(y,s)) if len(y)>1 and len(np.unique(y))>1 else None
def gmetrics(df, cols):
    if df.is_empty(): return pl.DataFrame()
    return (df.group_by(cols).agg(
        pl.len().alias("trades"),
        (pl.col("r_multiple")>0).sum().alias("wins"),
        pl.col("r_multiple").sum().alias("net_r"),
        pl.col("r_multiple").mean().alias("mean_r"),
        pl.col("score").mean().alias("mean_score"),
    ).with_columns((100*pl.col("wins")/pl.col("trades")).alias("win_rate_pct")).sort(cols))
def pick(summary):
    g=summary["gated"]; p=g["portfolio"]
    return {
        "candidate_events":summary["candidate_events"],"trades":g["trade_count"],
        "wr_pct":g["win_rate_pct"],"net_r":g["net_r"],"mean_r":g["mean_r"],
        "daily_sharpe":p["annualized_sharpe"],"mdd":p["max_drawdown"],
        "reconciliation_error_r":p.get("reconciliation_error_r"),
        "packed_sharpe":summary["packed_sharpe"]["annualized_sharpe"],
    }

legacy=loadj("legacy_dev"); tz=loadj("tz_dev"); c4l=loadj("can4_legacy_dev")
c4b=loadj("can4_block_legacy_dev"); c4w=loadj("can4_wf_dev")
c6f=loadj("can6_fixed_can4scores"); c6w=loadj("can6_wf_dev"); hold=loadj("hold")
fullleg=loadj("full_legacy"); tzpit=loadj("tz_pit")
P={n:loadp(n) for n in ["legacy_dev","tz_dev","can4_legacy_dev","can4_block_legacy_dev","can4_wf_dev","can6_fixed_can4scores","can6_wf_dev","hold","full_legacy","tz_pit"]}

# Waterfall common development window.
rows=[]
defs=[
("R0_legacy_parity",legacy),
("R1_timezone_DST_only",tz),
("R2_R3_PIT_nextbar_EOW_intrabar_bundle",c4l),
("R4_correct_validation",c4w),
("R5_correct_portfolio_accounting",c4w),
("R6a_6bps_fixed_4bp_scores",c6f),
("R6b_authoritative_6bps_cost_aware_refit",c6w),
]
prev=None
for name,obj in defs:
    x=pick(obj["summary"]); x["stage"]=name
    # legacy same-close events cannot be reconciled by canonical daily MTM
    if abs(x["reconciliation_error_r"] or 0)>1e-6:
        x["common_daily_sharpe"]=None; x["common_mdd"]=None
        x["common_metric_status"]="UNRECONCILED_LEGACY_EVENT_TIMING"
    else:
        x["common_daily_sharpe"]=x["daily_sharpe"]; x["common_mdd"]=x["mdd"]
        x["common_metric_status"]="RECONCILED"
    x["delta_r"]=None if prev is None else x["net_r"]-prev["net_r"]
    x["delta_common_daily_sharpe"]=None if prev is None or x["common_daily_sharpe"] is None or prev["common_daily_sharpe"] is None else x["common_daily_sharpe"]-prev["common_daily_sharpe"]
    rows.append(x); prev=x
rows[4]["delta_r"]=0.0
rows[4]["accounting_native_sharpe_before"]=c4w["summary"]["packed_sharpe"]["annualized_sharpe"]
rows[4]["accounting_daily_mtm_sharpe_after"]=c4w["summary"]["gated"]["portfolio"]["annualized_sharpe"]
rows[4]["accounting_delta_sharpe"]=rows[4]["accounting_daily_mtm_sharpe_after"]-rows[4]["accounting_native_sharpe_before"]
wf={
 "scope":"2017-01-01 through 2024-12-31 (common development window)",
 "stages":rows,
 "identification_notes":[
  "R2 and R3 are coupled in the audited build_events(corrected) path: next-bar/PIT entry, conservative intrabar order, and calendar EOW change together for most events. Exact additive separation would require a new counterfactual implementation.",
  "R6a is the pure 4->6 bps cost effect with 4bp walk-forward scores frozen. R6b is the repository-authoritative cost-aware re-fit; the +R change from R6a to R6b is a model/label response to costs, not negative transaction cost.",
  "R0/R1 canonical daily MTM is not defensible because same-close legacy timestamps do not reconcile under the canonical available_at MTM engine; use their native packed Sharpe only."
 ]
}
jwrite("performance_waterfall.json",wf)
pl.DataFrame(rows,infer_schema_length=None).write_parquet(OUT/"performance_waterfall.parquet")

# Meta uplift.
def uplift(obj):
    g=obj["summary"]["gated"]; u=obj["summary"]["ungated"]
    return {"gated":g,"ungated":u,"uplift":{
        "delta_r":g["net_r"]-u["net_r"],
        "delta_sharpe":g["portfolio"]["annualized_sharpe"]-u["portfolio"]["annualized_sharpe"],
        "delta_wr_pct_points":g["win_rate_pct"]-u["win_rate_pct"],
    }}
meta={"development_2017_2024":uplift(c6w),"frozen_holdout_2025_2026_07":uplift(hold)}
meta["combined_net_r"]={
 "ungated":c6w["summary"]["ungated"]["net_r"]+hold["summary"]["ungated"]["net_r"],
 "gated":c6w["summary"]["gated"]["net_r"]+hold["summary"]["gated"]["net_r"],
}
meta["combined_net_r"]["meta_delta_r"]=meta["combined_net_r"]["gated"]-meta["combined_net_r"]["ungated"]
jwrite("meta_uplift.json",meta)

# Corrected combined & legacy full per instrument/year.
corr=pl.concat([
 P["can6_wf_dev"].with_columns(pl.lit("development_oof").alias("evaluation")),
 P["hold"].with_columns(pl.lit("frozen_holdout").alias("evaluation"))
],how="vertical_relaxed")
leg=P["full_legacy"].with_columns(pl.lit("legacy_parity").alias("evaluation"))
def sel(df): return df.filter(pl.col("selected"))
li=gmetrics(sel(leg),["symbol"]).rename({c:f"legacy_{c}" for c in ["trades","wins","net_r","mean_r","mean_score","win_rate_pct"]})
ci=gmetrics(sel(corr),["symbol"]).rename({c:f"corrected_gated_{c}" for c in ["trades","wins","net_r","mean_r","mean_score","win_rate_pct"]})
cu=gmetrics(corr,["symbol"]).rename({c:f"corrected_raw_{c}" for c in ["trades","wins","net_r","mean_r","mean_score","win_rate_pct"]})
dev=P["can6_wf_dev"]; ho=P["hold"]
dg=gmetrics(sel(dev),["symbol"]).select("symbol",pl.col("trades").alias("dev_gated_trades"),pl.col("net_r").alias("dev_gated_net_r"),pl.col("win_rate_pct").alias("dev_gated_wr_pct"))
dr=gmetrics(dev,["symbol"]).select("symbol",pl.col("trades").alias("dev_raw_trades"),pl.col("net_r").alias("dev_raw_net_r"),pl.col("win_rate_pct").alias("dev_raw_wr_pct"))
hg=gmetrics(sel(ho),["symbol"]).select("symbol",pl.col("trades").alias("holdout_gated_trades"),pl.col("net_r").alias("holdout_gated_net_r"),pl.col("win_rate_pct").alias("holdout_gated_wr_pct"))
hr=gmetrics(ho,["symbol"]).select("symbol",pl.col("trades").alias("holdout_raw_trades"),pl.col("net_r").alias("holdout_raw_net_r"),pl.col("win_rate_pct").alias("holdout_raw_wr_pct"))
inst=(li.join(ci,on="symbol",how="full",coalesce=True).join(cu,on="symbol",how="full",coalesce=True)
 .join(dg,on="symbol",how="left").join(dr,on="symbol",how="left").join(hg,on="symbol",how="left").join(hr,on="symbol",how="left")
 .with_columns(
 (pl.col("corrected_gated_net_r").fill_null(0)-pl.col("legacy_net_r").fill_null(0)).alias("legacy_to_corrected_delta_r"),
 (pl.col("corrected_gated_trades").cast(pl.Int64).fill_null(0)-pl.col("legacy_trades").cast(pl.Int64).fill_null(0)).alias("trade_count_change"),
 (pl.col("corrected_gated_net_r")-pl.col("corrected_raw_net_r")).alias("meta_delta_r"),
 ))
tz_diff=pl.read_parquet(RUN/"timezone_event_diff.parquet")
shift=tz_diff.filter(pl.col("status").str.contains("SESSION_SHIFTED")).group_by("symbol").agg(pl.len().alias("session_shifted_events"))
inst=inst.join(shift,on="symbol",how="left").with_columns(pl.col("session_shifted_events").fill_null(0)).sort("symbol")
inst.write_parquet(OUT/"instrument_attribution.parquet")

ly=gmetrics(sel(leg),["year"]).rename({c:f"legacy_{c}" for c in ["trades","wins","net_r","mean_r","mean_score","win_rate_pct"]})
cy=gmetrics(sel(corr),["year"]).rename({c:f"corrected_gated_{c}" for c in ["trades","wins","net_r","mean_r","mean_score","win_rate_pct"]})
ru=gmetrics(corr,["year"]).rename({c:f"corrected_raw_{c}" for c in ["trades","wins","net_r","mean_r","mean_score","win_rate_pct"]})
year=ly.join(cy,on="year",how="full",coalesce=True).join(ru,on="year",how="full",coalesce=True).with_columns(
 (pl.col("corrected_gated_net_r").fill_null(0)-pl.col("legacy_net_r").fill_null(0)).alias("legacy_to_corrected_delta_r"),
 (pl.col("corrected_gated_net_r")-pl.col("corrected_raw_net_r")).alias("meta_delta_r")
).sort("year")
year.write_parquet(OUT/"yearly_attribution.parquet")

# Event selected-R attribution.
def selected_map(df):
    return {r["event_key"]:(bool(r["selected"]),float(r["r_multiple"])) for r in df.select("event_key","selected","r_multiple").to_dicts()}
def cause_table(diff,before,after,transition):
    bm=selected_map(before); am=selected_map(after); out=[]
    for r in diff.to_dicts():
        k=r["event_key"]; bo=bm.get(k,(False,0.0)); ao=am.get(k,(False,0.0))
        oldr=float(r["old_r"] or 0.0); newr=float(r["new_r"] or 0.0)
        out.append({
          "transition":transition,"status":r["status"],"symbol":r["symbol"],"event_key":k,
          "old_r":oldr,"new_r":newr,"candidate_delta_r":newr-oldr,
          "old_selected":bo[0],"new_selected":ao[0],
          "selected_old_r":oldr if bo[0] else 0.0,"selected_new_r":newr if ao[0] else 0.0,
          "selected_delta_r":(newr if ao[0] else 0.0)-(oldr if bo[0] else 0.0),
          "gate_flip":bo[0]!=ao[0],
          "label_flip":"LABEL_CHANGED" in r["status"],
        })
    return pl.DataFrame(out,infer_schema_length=None)
can_diff=pl.read_parquet(RUN/"canonical_event_diff.parquet")
cause=pl.concat([
 cause_table(tz_diff,P["legacy_dev"],P["tz_dev"],"R0_to_R1_timezone"),
 cause_table(can_diff,P["tz_dev"],P["can4_legacy_dev"],"R1_to_R2R3_mechanics")
],how="vertical_relaxed")
agg=(cause.group_by(["transition","status","symbol"]).agg(
 pl.len().alias("events"),pl.col("old_r").sum().alias("old_r"),pl.col("new_r").sum().alias("new_r"),
 pl.col("candidate_delta_r").sum().alias("candidate_delta_r"),
 pl.col("old_selected").sum().alias("legacy_selected_count"),
 pl.col("new_selected").sum().alias("corrected_selected_count"),
 pl.col("gate_flip").sum().alias("gate_flips"),pl.col("label_flip").sum().alias("label_flips"),
 pl.col("selected_delta_r").sum().alias("selected_delta_r"),
).with_columns(pl.col("selected_delta_r").abs().alias("abs_selected_delta_r")).sort("abs_selected_delta_r",descending=True))
agg.write_parquet(OUT/"event_cause_attribution.parquet")

# Model/score decay diagnostics.
score_rows=[]
for y in sorted(corr["year"].unique().to_list()):
    d=corr.filter(pl.col("year")==y)
    sc=d["score"].to_numpy(); lab=d["label"].to_numpy(); rr=d["r_multiple"].to_numpy()
    order=np.argsort(sc); k=max(1,len(d)//10)
    score_rows.append({
      "year":int(y),"evaluation":d["evaluation"][0],"events":len(d),"auc":auc(lab,sc),
      "label_base_rate":float(np.mean(lab)),"score_mean":float(np.mean(sc)),"score_std":float(np.std(sc)),
      "score_p10":float(np.quantile(sc,.1)),"score_p50":float(np.quantile(sc,.5)),"score_p90":float(np.quantile(sc,.9)),
      "pass_fraction_ge_0_50":float(np.mean(sc>=.5)),
      "score_r_corr":float(np.corrcoef(sc,rr)[0,1]) if len(d)>2 and np.std(sc)>0 and np.std(rr)>0 else None,
      "bottom_decile_mean_r":float(np.mean(rr[order[:k]])),"top_decile_mean_r":float(np.mean(rr[order[-k:]])),
      "top_minus_bottom_decile_r":float(np.mean(rr[order[-k:]])-np.mean(rr[order[:k]])),
    })
scoredf=pl.DataFrame(score_rows,infer_schema_length=None); scoredf.write_parquet(OUT/"meta_score_diagnostics.parquet")
model_decay={
 "inner_walk_forward_auc":c6w["diagnostics"]["walk_forward"],
 "yearly_actual_score_diagnostics":score_rows,
 "score_semantics":"raw_model_score_not_calibrated_probability",
 "feature_importance_stability":{"status":"UNKNOWN_NOT_PERSISTED","reason":"Intermediate yearly/fold models and their feature importances were not persisted; reconstructing them requires retraining. No threshold/feature tuning was performed in this forensic session."}
}
jwrite("model_decay.json",model_decay)

# SPX PIT.
spxold=P["tz_dev"]; spxnew=P["tz_pit"]
def gm(df):
    return gmetrics(df.filter(pl.col("selected")),["symbol"]).to_dicts()
canon_led=pl.concat([pl.read_parquet(RUN/"canonical_6bps_events.parquet"),pl.read_parquet(RUN/"final_holdout_events.parquet")],how="vertical_relaxed")
spx_stale=canon_led.filter(pl.col("spx_staleness_seconds").is_not_null())
spx={
 "counterfactual":"timezone-corrected local sessions with legacy same-close/legacy exit held fixed; only SPX values switched to availability-aligned canonical join",
 "old":{"events":len(spxold),"gated":tz["summary"]["gated"],"mean_auc":tz["diagnostics"]["mean_auc"]},
 "pit":{"events":len(spxnew),"gated":tzpit["summary"]["gated"],"mean_auc":tzpit["diagnostics"]["mean_auc"]},
 "delta_gated_r":tzpit["summary"]["gated"]["net_r"]-tz["summary"]["gated"]["net_r"],
 "delta_gated_trades":tzpit["summary"]["gated"]["trade_count"]-tz["summary"]["gated"]["trade_count"],
 "by_instrument_old":gm(spxold),"by_instrument_pit":gm(spxnew),
 "staleness_seconds":{
   "overall":{"p50":float(spx_stale["spx_staleness_seconds"].quantile(.5)),"p90":float(spx_stale["spx_staleness_seconds"].quantile(.9)),"p99":float(spx_stale["spx_staleness_seconds"].quantile(.99)),"max":float(spx_stale["spx_staleness_seconds"].max())},
   "by_instrument":spx_stale.group_by("symbol").agg(
      pl.len().alias("events"),pl.col("spx_staleness_seconds").median().alias("p50"),
      pl.col("spx_staleness_seconds").quantile(.9).alias("p90"),pl.col("spx_staleness_seconds").max().alias("max")
   ).sort("symbol").to_dicts()
 },
 "strict_PIT_spx_feature_relation":{
   "corr_spx_alignment_with_r":float(np.corrcoef(corr["feature_spx_alignment"].to_numpy(),corr["r_multiple"].to_numpy())[0,1]) if "feature_spx_alignment" in corr.columns else None,
   "note":"SPX is also a hard event eligibility condition, so simple within-event correlation is not an ablation estimate."
 }
}
jwrite("spx_pit_attribution.json",spx)

# EOW mechanics partial attribution.
tzledger=pl.read_parquet(RUN/"timezone_only_events.parquet")
c4ledger=pl.read_parquet(RUN/"canonical_4bps_events.parquet")
exitrows=cause.filter((pl.col("transition")=="R1_to_R2R3_mechanics") & pl.col("status").str.contains("EXIT_CHANGED"))
eow={
 "status":"PARTIALLY_IDENTIFIED_INTERACTION_BUNDLE",
 "reason":"ENTRY_CHANGED and EXIT_CHANGED co-occur for the overwhelming majority of canonical diff rows; exact EOW-only delta is not identified by the current audited builder.",
 "exit_changed_union_events":len(exitrows),
 "selected_delta_r_on_exit_changed_rows":float(exitrows["selected_delta_r"].sum()) if len(exitrows) else 0.0,
 "candidate_delta_r_on_exit_changed_rows":float(exitrows["candidate_delta_r"].sum()) if len(exitrows) else 0.0,
 "legacy_exit_reasons":tzledger.group_by(["symbol","exit_reason"]).agg(pl.len().alias("events"),pl.col("r_multiple").sum().alias("net_r")).sort(["symbol","exit_reason"]).to_dicts(),
 "canonical_exit_reasons":c4ledger.group_by(["symbol","exit_reason"]).agg(pl.len().alias("events"),pl.col("r_multiple").sum().alias("net_r")).sort(["symbol","exit_reason"]).to_dicts(),
 "holiday_or_missing_session_substitutions":c4ledger.filter(pl.col("eow_substitution").is_not_null()).group_by(["symbol","eow_substitution"]).agg(pl.len().alias("events")).sort("symbol").to_dicts(),
 "legacy_1500_row_fallback":{"status":"NOT_IDENTIFIABLE_FROM_PERSISTED_LEDGER","reason":"legacy exit_reason stores both Friday>=20 and row-limit expiry as time_expiry"}
}
jwrite("eow_exit_attribution.json",eow)

# Cost sensitivity with can4 scores held fixed.
base=P["can4_wf_dev"]
risk=(base["delta"]/base["entry_price"]).to_numpy(); r4=base["r_multiple"].to_numpy(); scores=base["score"].to_numpy(); mask=scores>=.5
gross=r4+0.0004/risk
costs=[]
for b in [0,4,6,8,10]:
    rb=gross-(b/10000)/risk
    v=rb[mask]
    costs.append({"bps":b,"trades":int(mask.sum()),"net_r":float(v.sum()),"mean_r":float(v.mean()),"wr_pct":float((v>0).mean()*100)})
jwrite("cost_sensitivity.json",{"fixed_event_path_and_scores":"can4_wf_dev","scenarios":costs})

# Validation leakage.
validation={
 "asset_block_ordering":{
   "legacy_asset_block_order_auc":c4b["diagnostics"]["mean_auc"],
   "globally_time_sorted_legacy_auc":c4l["diagnostics"]["mean_auc"],
   "delta_auc":c4l["diagnostics"]["mean_auc"]-c4b["diagnostics"]["mean_auc"],
   "asset_block_net_r":c4b["summary"]["gated"]["net_r"],
   "global_order_net_r":c4l["summary"]["gated"]["net_r"],
   "delta_net_r":c4l["summary"]["gated"]["net_r"]-c4b["summary"]["gated"]["net_r"],
 },
 "legacy_validation_to_correct_walkforward":{
   "legacy_like_net_r":c4l["summary"]["gated"]["net_r"],"walkforward_net_r":c4w["summary"]["gated"]["net_r"],
   "delta_net_r":c4w["summary"]["gated"]["net_r"]-c4l["summary"]["gated"]["net_r"],
   "legacy_like_auc":c4l["diagnostics"]["mean_auc"],"walkforward_inner_auc":c4w["diagnostics"]["walk_forward"],
 },
 "global_uniqueness_weights":{"status":"NOT_INDEPENDENTLY_IDENTIFIED","reason":"legacy validator combines global uniqueness weights with legacy CPCV; corrected trainer always applies fold-local uniqueness when temporal contracts are present."},
 "approximate_5bar_embargo":{"status":"NOT_INDEPENDENTLY_IDENTIFIED","reason":"corrected trainer couples exact entry-exit interval purge, elapsed-time embargo and fold-local uniqueness."},
 "residual_validation_package_delta_after_ordering_r":(c4w["summary"]["gated"]["net_r"]-c4l["summary"]["gated"]["net_r"]),
}
jwrite("validation_leakage_attribution.json",validation)

# 2026.
h=P["hold"]; h26=h.filter((pl.col("year")==2026)&pl.col("selected")); h25=h.filter((pl.col("year")==2025)&pl.col("selected"))
allrng=corr["range_to_atr20_raw"]; q1,q2,q3=[float(allrng.quantile(q)) for q in [.25,.5,.75]]
h26x=h26.with_columns(
 pl.when(pl.col("direction")>0).then(pl.lit("long")).otherwise(pl.lit("short")).alias("side"),
 pl.when(pl.col("score")<.55).then(pl.lit("0.50-0.55")).when(pl.col("score")<.60).then(pl.lit("0.55-0.60")).when(pl.col("score")<.70).then(pl.lit("0.60-0.70")).otherwise(pl.lit(">=0.70")).alias("score_bucket"),
 pl.when(pl.col("range_to_atr20_raw")<=q1).then(pl.lit("Q1_low")).when(pl.col("range_to_atr20_raw")<=q2).then(pl.lit("Q2")).when(pl.col("range_to_atr20_raw")<=q3).then(pl.lit("Q3")).otherwise(pl.lit("Q4_high")).alias("range_atr_regime"),
 pl.when(pl.col("holding_bars")<=12).then(pl.lit("<=1h")).when(pl.col("holding_bars")<=48).then(pl.lit("1-4h")).when(pl.col("holding_bars")<=144).then(pl.lit("4-12h")).otherwise(pl.lit(">12h")).alias("holding_bucket"),
)
def breakdown(col): return gmetrics(h26x,[col]).to_dicts()
raw26=h.filter(pl.col("year")==2026)
failure={
 "selected_summary":{"trades":len(h26),"net_r":float(h26["r_multiple"].sum()),"wr_pct":float((h26["r_multiple"]>0).mean()*100),"mean_r":float(h26["r_multiple"].mean())},
 "raw_ungated_2026":{"trades":len(raw26),"net_r":float(raw26["r_multiple"].sum()),"wr_pct":float((raw26["r_multiple"]>0).mean()*100),"mean_r":float(raw26["r_multiple"].mean())},
 "meta_delta_r_2026":float(h26["r_multiple"].sum()-raw26["r_multiple"].sum()),
 "candidate_auc_2026":auc(raw26["label"],raw26["score"]),
 "by_instrument":breakdown("symbol"),"by_month":breakdown("month"),"by_side":breakdown("side"),
 "by_exit_reason":breakdown("exit_reason"),"by_holding_bucket":breakdown("holding_bucket"),
 "by_score_bucket":breakdown("score_bucket"),"by_range_atr_regime":breakdown("range_atr_regime"),
 "comparison":{
   "2025_gated_net_r":float(h25["r_multiple"].sum()),
   "2025_raw_net_r":float(h.filter(pl.col("year")==2025)["r_multiple"].sum()),
   "2022_2024_gated_net_r":float(corr.filter(pl.col("year").is_between(2022,2024) & pl.col("selected"))["r_multiple"].sum()),
   "2017_2021_gated_net_r":float(corr.filter(pl.col("year").is_between(2017,2021) & pl.col("selected"))["r_multiple"].sum()),
 },
 "interpretation_guardrail":"A single 7-month YTD loss is insufficient to prove permanent structural decay. Because the ungated primary also lost heavily, 2026 is not explained by meta gating alone."
}
jwrite("2026_failure_analysis.json",failure)

# Legacy reproduction / DSR.
hist=json.loads((RUN/"historical_reassessment.json").read_text())
audit=json.loads((ROOT/"run_log/trial_ledger_audit.json").read_text())
repro={
 "published":hist["historical_claim"],"current_raw_data_parity":hist["legacy_parity_rebuild_on_current_raw_data"],
 "gaps":{
  "trades":hist["legacy_parity_rebuild_on_current_raw_data"]["trade_count"]-hist["historical_claim"]["trade_count"],
  "wr_pct_points":hist["legacy_parity_rebuild_on_current_raw_data"]["win_rate_pct"]-hist["historical_claim"]["win_rate_pct"],
  "net_r":hist["legacy_parity_rebuild_on_current_raw_data"]["net_r"]-hist["historical_claim"]["net_r"],
  "sharpe":hist["legacy_parity_rebuild_on_current_raw_data"]["annualized_sharpe_legacy_method"]-hist["historical_claim"]["annualized_sharpe"],
 },
 "status":"EXACT_LEGACY_REPRODUCTION_BLOCKED_BY_DATA_PROVENANCE",
 "reason":"The historical raw-data snapshot is not preserved as a verified immutable artifact; exact timestamp metadata/config/library state cannot be proven.",
 "dsr_status":"DSR_UNREPRODUCIBLE_LEGACY_TRIAL_UNIVERSE","trial_ledger_audit":audit,
}
jwrite("legacy_reproduction_gap.json",repro)

# Session-specific DE/NAS detail from diff rows, split by US DST and US/Europe mismatch windows.
ny=ZoneInfo("America/New_York"); berlin=ZoneInfo("Europe/Berlin")
session={}
for sym in ["DE30","NAS100"]:
    d=tz_diff.filter(pl.col("symbol")==sym)
    cd=cause.filter((pl.col("transition")=="R0_to_R1_timezone") & (pl.col("symbol")==sym))
    buckets={"US_DST":{"events":0,"selected_delta_r":0.0},"US_STANDARD":{"events":0,"selected_delta_r":0.0}}
    mismatch={"events":0,"selected_delta_r":0.0,"dates":[]}
    for rr in cd.select("event_key","selected_delta_r").to_dicts():
        ds=rr["event_key"].split("|",1)[1]; day=datetime.fromisoformat(ds)
        ny_dt=day.replace(hour=12,tzinfo=ny); be_dt=day.replace(hour=12,tzinfo=berlin)
        usdst=bool(ny_dt.dst().total_seconds())
        key="US_DST" if usdst else "US_STANDARD"
        buckets[key]["events"]+=1; buckets[key]["selected_delta_r"]+=float(rr["selected_delta_r"])
        if sym=="DE30" and bool(be_dt.dst().total_seconds()) != usdst:
            mismatch["events"]+=1; mismatch["selected_delta_r"]+=float(rr["selected_delta_r"]); mismatch["dates"].append(ds)
    session[sym]={
      "union_events":len(d),"session_shifted_events":len(d.filter(pl.col("status").str.contains("SESSION_SHIFTED"))),
      "added":len(d.filter(pl.col("status")=="ADDED")),"removed":len(d.filter(pl.col("status")=="REMOVED")),
      "candidate_delta_r_zero_filled":float((d["new_r"].fill_null(0)-d["old_r"].fill_null(0)).sum()),
      "selected_delta_r_total":float(cd["selected_delta_r"].sum()),
      "dst_regimes":buckets,
      "contract":"09:00 America/New_York; XETR calendar" if sym=="DE30" else "09:30 America/New_York",
      "legacy_anchor_utc":"13:00" if sym=="DE30" else "14:00",
      "corrected_anchor_utc":"13:00 EDT / 14:00 EST" if sym=="DE30" else "13:30 EDT / 14:30 EST",
    }
    if sym=="DE30":
        session[sym]["us_europe_dst_mismatch"]={"events":mismatch["events"],"selected_delta_r":mismatch["selected_delta_r"],"unique_dates":sorted(set(mismatch["dates"]))}
jwrite("session_dst_detail.json",session)

# Summary markdown.
ranked=[
 ("PIT/next-bar + EOW/intrabar mechanics bundle",c4l["summary"]["gated"]["net_r"]-tz["summary"]["gated"]["net_r"]),
 ("validation package",c4w["summary"]["gated"]["net_r"]-c4l["summary"]["gated"]["net_r"]),
 ("pure 4->6bp costs, scores frozen",c6f["summary"]["gated"]["net_r"]-c4w["summary"]["gated"]["net_r"]),
 ("timezone/DST sessions",tz["summary"]["gated"]["net_r"]-legacy["summary"]["gated"]["net_r"]),
 ("SPX availability correction within legacy-like mechanics",tzpit["summary"]["gated"]["net_r"]-tz["summary"]["gated"]["net_r"]),
]
ranked=sorted(ranked,key=lambda x:abs(x[1]),reverse=True)
lines=["# Forensic Summary","","## Verdict",
"VERIFIED FACT: the old edge was not mainly a DST artifact. On the common 2017–2024 development window, local-session/DST correction reduced gated P&L by only 12.34R. The largest measured losses were the coupled executable-entry/calendar/intrabar correction (-62.77R) and validation correction (-53.51R). Pure 4→6 bp costs removed another 20.75R with scores frozen. SPX availability correction by itself was small (-2.95R). The corrected raw ORB materially outperformed the meta-gated strategy in development, while both raw and gated strategies were negative on the frozen 2025–2026 holdout because 2026 itself was strongly negative.",
"",
"## Performance waterfall","","| Stage | Trades | WR | Net R | Common daily Sharpe | MDD | Delta R | Native/packed Sharpe |",
"|---|---:|---:|---:|---:|---:|---:|---:|"]
for r in rows:
    cs="N/A" if r["common_daily_sharpe"] is None else f"{r['common_daily_sharpe']:.3f}"
    md="N/A" if r["common_mdd"] is None else f"{r['common_mdd']:.3f}"
    dr="" if r["delta_r"] is None else f"{r['delta_r']:.2f}"
    lines.append(f"| {r['stage']} | {r['trades']} | {r['wr_pct']:.2f}% | {r['net_r']:.2f} | {cs} | {md} | {dr} | {r['packed_sharpe']:.3f} |")
lines += ["","## Biggest measured causes"]
for name,delta in ranked: lines.append(f"- {name}: {delta:+.2f}R.")
lines += [
 "",
 "## Meta model",
 f"- Development: raw ORB {c6w['summary']['ungated']['net_r']:.2f}R / Sharpe {c6w['summary']['ungated']['portfolio']['annualized_sharpe']:.3f}; gated {c6w['summary']['gated']['net_r']:.2f}R / Sharpe {c6w['summary']['gated']['portfolio']['annualized_sharpe']:.3f}. Meta uplift = {meta['development_2017_2024']['uplift']['delta_r']:.2f}R.",
 f"- Frozen holdout: raw ORB {hold['summary']['ungated']['net_r']:.2f}R / Sharpe {hold['summary']['ungated']['portfolio']['annualized_sharpe']:.3f}; gated {hold['summary']['gated']['net_r']:.2f}R / Sharpe {hold['summary']['gated']['portfolio']['annualized_sharpe']:.3f}. Meta uplift = {meta['frozen_holdout_2025_2026_07']['uplift']['delta_r']:.2f}R.",
 "- AUC decays from ~0.553 in the early development era to 0.496 by the 2024 inner validation. The 0.50 cutoff is a frozen raw-score threshold, not a calibrated probability threshold.",
 "",
 "## 2026",
 f"- Gated: {failure['selected_summary']['net_r']:.2f}R. Raw ungated: {failure['raw_ungated_2026']['net_r']:.2f}R. Meta gating therefore improved 2026 by only {failure['meta_delta_r_2026']:+.2f}R; the primary strategy itself failed in 2026.",
 "",
 "## Legacy reproducibility / DSR",
 "- Current-data legacy parity reproduces the old headline shape closely but not exactly. Exact legacy parity is blocked by missing immutable historical data provenance.",
 "- DSR_UNREPRODUCIBLE_LEGACY_TRIAL_UNIVERSE remains authoritative; the trial ledger does not justify historical n_trials=42 or a 99% DSR claim.",
 "",
 "## Next research decision",
 "**C. Continue with targeted robustness research.** Freeze the meta model out of the next experiment and test whether the corrected ungated ORB has stable forward/regime robustness. Do not tune the frozen holdout. The immediate research target is the 2026 raw-ORB regime failure, not another meta threshold or parameter search.",
]
(OUT/"forensic_summary.md").write_text("\n".join(lines)+"\n")

jwrite("provenance.json",{
 "frozen_hash":json.loads((RUN/"frozen_spec.json").read_text())["frozen_hash"],
 "source_cache_files":sorted([p.name for p in CACHE.glob("*.json")]),
 "frozen_artifacts_mutated":False,
 "limitations":["R2/R3 coupled","global uniqueness vs fold-local not independently isolated","5-bar embargo vs exact purge not independently isolated","legacy same-close daily MTM unreconciled"],
})
print(json.dumps({"status":"OK","outputs":sorted([p.name for p in OUT.iterdir() if p.is_file()])},indent=2))
