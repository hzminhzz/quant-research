#!/usr/bin/env python3
"""Independent Phase5/6 native trade/fill and uncertainty audit.

No trading execution or signal generation. Only verify saved native orders
against the raw source and apply session bootstrap to daily PnL.
"""
from __future__ import annotations
import hashlib,json,math
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import polars as pl
ROOT=Path(__file__).resolve().parents[1]
CT=ZoneInfo("America/Chicago")
V3=ROOT/"run_log/vwap_pullback_adx_nq_20261012_proxy_v3_execfix/phase4_remediated"
V4=ROOT/"run_log/vwap_pullback_adx_nq_20261012_proxy_v4_phase56"
V5=ROOT/"run_log/vwap_pullback_adx_nas100_20261012_cross_source/phase5_cross_source"
SOURCE={
 "dev":ROOT/"data/processed/vwap_adx_nqf_2026h1_1m.parquet",
 "partial":ROOT/"data/processed/vwap_adx_nqf_2026h2_validation_1m.parquet",
 "index":ROOT/"data/processed/vwap_adx_nas100_2026h2_1m.parquet",
}
SHAS={
 "dev":"a0670b34b2175ca0df4a7ab98fa79bb02650cf4cce64ed67261ad29f706ebaad",
 "partial":"21bd6e367df44b934386e59e831c7e8090116de9d5fd9ac82ca8a8ff9d7c4839",
 "index":"da3891d4ae7d686da6832081f322c7b2571bcc92e0e0ce5581b860a7e9d66e17"
}

def tz_naive(value):
 return datetime.fromisoformat(value).astimezone(timezone.utc).replace(tzinfo=None)

def raw_map(kind):
 p=SOURCE[kind]
 assert hashlib.sha256(p.read_bytes()).hexdigest()==SHAS[kind]
 a=pl.read_parquet(p).sort("timestamp")
 return {v.replace(tzinfo=None):i for i,v in enumerate(a["timestamp"].to_list())},a

def trial_audit(folder,price_idx,raw,slip):
 trades=pl.read_parquet(folder/"trades.parquet").sort("entry_time")
 fills=pl.read_parquet(folder/"fills.parquet")  # native journal order; lexical ORD-101 sorts before ORD-99
 sig=json.loads((folder/"signals.json").read_text())
 summary=json.loads((folder/"metrics.json").read_text())
 issues=[]
 if trades.height!=len(sig) or fills.height!=2*trades.height:
  issues.append("trade/entry/fill count mismatch")
 for ix,row in enumerate(trades.iter_rows(named=True)):
  try:
   signal=sig[ix]
   entry=row["entry_time"]
   idx=price_idx[entry]
   target=math.ceil((max(raw["high"][idx-5:idx].to_list())-1e-9)/.25)*.25
   stop=math.floor((min(raw["low"][idx-20:idx].to_list())+1e-9)/.25)*.25
   if abs(target-signal["take_profit"])>1e-7 or abs(stop-signal["stop_loss"])>1e-7:
    issues.append("invalid lookback level")
   if entry!=tz_naive(signal["expected_entry_at"]):
    issues.append("noncausal fill timestamp")
   if abs(row["entry_price"]-raw["open"][idx]-slip)>1e-7:
    issues.append("entry price mismatch")
   e=row["exit_time"].replace(tzinfo=timezone.utc).astimezone(CT)
   if e.strftime("%H:%M")>"15:55" or e.date()!=entry.replace(tzinfo=timezone.utc).astimezone(CT).date():
    issues.append("cutoff or overnight violation")
  except (IndexError,KeyError) as exc:
   issues.append(f"source lookup {str(exc)}")
 expect_fee=0 if slip==0 else 2.50
 for j,f in enumerate(fills.iter_rows(named=True)):
  if f["side"]!=("buy" if j%2==0 else "sell"):
   issues.append("unpaired/reverse fill")
  if abs(f["commission"]-expect_fee)>1e-7:
   issues.append("fee mismatch")
  if f["order_type"]=="limit":
   if f["side"]=="sell" and f["price"]+1e-8<f["limit_price"]:
    issues.append("illegal limit fill")
   if f["side"]=="buy" and f["price"]-1e-8>f["limit_price"]:
    issues.append("illegal buy limit")
   if abs(f["slippage"])>1e-9:
    issues.append("limit adverse slippage")
  elif abs(f["slippage"]-slip)>1e-8:
   issues.append("aggressive slippage mismatch")
 if abs(summary["reconciliation_difference_usd"])>1e-5:
  issues.append("native equity/trade reconciliation mismatch")
 return {"trades":trades.height,"fills":fills.height,
         "limit_fills":fills.filter(pl.col("order_type")=="limit").height,
         "errors":dict((x,issues.count(x)) for x in sorted(set(issues))),
         "net_pnl_usd":summary["net_account_pnl_usd"]}

def daily(folder):
 d=pl.read_parquet(folder/"daily_equity.parquet").sort("day")
 days=[str(t) for t in d["day"].to_list()]
 x=np.diff(np.r_[1000000.,d["equity"].to_numpy()])
 return days,x

def bootstrap(x,seed):
 rng=np.random.default_rng(seed)
 if not len(x):return None
 plain=rng.choice(x,size=(10000,len(x)),replace=True).sum(axis=1)
 # 5-session circular block bootstrap preserves short serial dependence.
 blocks=5
 starts=rng.integers(0,len(x),size=(10000,math.ceil(len(x)/blocks)))
 offsets=np.arange(blocks)
 indexes=(starts[:,:,None]+offsets[None,None,:])%len(x)
 sims=x[indexes.reshape((10000,-1))[:,:len(x)]].sum(axis=1)
 return {"daily_mean_usd":float(np.mean(x)),
         "total_usd":float(x.sum()),
         "iid_total_95pct_ci_usd":list(map(float,np.quantile(plain,[.025,.975]))),
         "block5_total_95pct_ci_usd":list(map(float,np.quantile(sims,[.025,.975]))),
         "block5_probability_total_nonpositive":float(np.mean(sims<=0))}

def analyze_group(kind,root,labels):
 idx,raw=raw_map(kind)
 audits={}
 for mode in ("B1","B2","B3"):
  for label,slip in labels:
   p=root/f"{mode}_{label}"
   audits[f"{mode}_{label}"]=trial_audit(p,idx,raw,slip)
 return audits

def main():
 report={}
 labels=[("gross",0.0),("cost",.25),("stress",.5)]
 report["primary_nqf_subset"]={
  "provenance":"19/64 days; INCOMPLETE_SOURCE_DIAGNOSTIC_ONLY",
  "audits":analyze_group("partial",V4/"phase5_incomplete_nqf_19sessions",labels)
 }
 report["secondary_nas100_cross_source"]={
  "provenance":"CASH_INDEX_NOT_CME_OOS",
  "audits":analyze_group("index",V5,labels)
 }
 report["phase6_dev"]={
  "provenance":"Jan-Jun 2026 development only",
  "audits":analyze_group("dev",V4/"phase6",[("stress4tick",1.0),("limit_queue1tick",.25)])
 }
 # Add chronological month outcomes (trading days only, missing days remain zero).
 for key,root in [
  ("partial",V4/"phase5_incomplete_nqf_19sessions"),
  ("index",V5),
  ("development",V3)]:
  per={}
  for mode in ("B1","B2","B3"):
   days,x=daily(root/f"{mode}_cost")
   bymonth={}
   for month in sorted(set(d[:7] for d in days)):
    bymonth[month]={"days":sum(d.startswith(month) for d in days),
                    "net_usd":round(float(sum(x[i] for i,d in enumerate(days) if d.startswith(month))),2)}
   per[mode]={"calendar_months":bymonth,"sampling":bootstrap(x,20261012)}
  d2,x2=daily(root/"B2_cost")
  d3,x3=daily(root/"B3_cost")
  assert d2==d3
  per["B3_minus_B2_paired"]={"sessions":len(d2),
    "sampling":bootstrap(x3-x2,20261013)}
  report[key+"_monthly_and_bootstrap"]=per
 # Source completeness and trial counts cannot be treated as independent.
 report["not_deployment_approval"]=True
 report["missing_CME_dated_contracts_rolls_volume_and_fills"]=True
 report["trials_dsr_status"]="UNREPRODUCIBLE_FULL_HISTORICAL_TRIAL_ACCOUNTING"
 report["retrospective_OOS_not_pristine"]=True
 report["no_november_holdout_used"]=True
 errors=[(group,t,item["errors"]) for group,v in report.items()
  if isinstance(v,dict) and "audits" in v for t,item in v["audits"].items() if item["errors"]]
 report["all_native_execution_audits_pass"]=not errors
 report["errors"]=errors
 path=V4/"phase56_independent_audit_v2.json"
 if path.exists():raise FileExistsError("immutable audit already exists")
 path.write_text(json.dumps(report,indent=2,default=str)+"\n")
 print(json.dumps({"audits_pass":not errors,"errors":errors,
  "index_monthly":{m:report["index_monthly_and_bootstrap"][m]["calendar_months"] for m in ("B1","B2","B3")},
  "nqf_subset_monthly":{m:report["partial_monthly_and_bootstrap"][m]["calendar_months"] for m in ("B1","B2","B3")},
  "development_monthly":{m:report["development_monthly_and_bootstrap"][m]["calendar_months"] for m in ("B1","B2","B3")}},indent=2))
 if errors:raise AssertionError("Native replay failed independent audit")
if __name__=="__main__":main()
