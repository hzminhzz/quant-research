#!/usr/bin/env python3
"""Independent native fill audit for Dukascopy-only Strategy 2 research.

Checks data, next-open, limit-floor, 5/20 completed-bar targets/stops,
15:14 Chicago liquidation and ledger reconciliation across ALL trial runs.
Does not alter prices or rerun the strategy.
"""
from __future__ import annotations
import hashlib,json,math
from pathlib import Path
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
import polars as pl
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
SID="vwap_pullback_adx_dukascopy_20261012_v1"
OUT=ROOT/"run_log"/SID
SOURCE=ROOT/"data/processed/vwap_adx_dukascopy_2026_1m.parquet"
PINNED="4ce2efcf496fb77d936d12d866ef5ed5d1e1869879a6b30434a1d0232bb75425"
CT=ZoneInfo("America/Chicago")
TRIALS=[
 ("development",("gross","cost","stress")),
 ("validation",("gross","cost","stress")),
 ("robustness",("queue1tick",)),
 ("stress4tick",("stress4tick",)),
]

def parse(s):
 return datetime.fromisoformat(s).astimezone(timezone.utc).replace(tzinfo=None)

def sha(file):
 h=hashlib.sha256()
 with file.open("rb") as r:
  for block in iter(lambda:r.read(1<<20),b""):h.update(block)
 return h.hexdigest()

def bootstrap(x,seed):
 if len(x)<2:return None
 rng=np.random.default_rng(seed)
 size=len(x)
 iid=rng.choice(x,size=(10000,size),replace=True).sum(axis=1)
 block=5
 starts=rng.integers(0,size,size=(10000,math.ceil(size/block)))
 indices=(starts[:,:,None]+np.arange(block)[None,None,:])%size
 paths=x[indices.reshape((10000,-1))[:,:size]].sum(axis=1)
 return {
  "n":size, "total":float(x.sum()),"per_day_mean":float(x.mean()),
  "iid_total_95pct":list(map(float,np.quantile(iid,[.025,.975]))),
  "block5_total_95pct":list(map(float,np.quantile(paths,[.025,.975]))),
  "block5_nonpositive_fraction":float(np.mean(paths<=0))
 }

def audit_all():
 if sha(SOURCE)!=PINNED:raise RuntimeError("Source hash drift")
 prices=pl.read_parquet(SOURCE).sort("timestamp")
 row_index={t.replace(tzinfo=None):i for i,t in enumerate(prices["timestamp"].to_list())}
 highs=prices["high"].to_numpy()
 lows=prices["low"].to_numpy()
 opens=prices["open"].to_numpy()
 out={"source":"DUKASCOPY_USATECH_CFD_ONLY","source_sha256":PINNED,
      "CME_volume_confirmed":False,"NQF_data_used":False,
      "fixed_exit_rule":"15:14 CT next-open","exact_original_1555_CME_strategy":False,
      "runs":{},"statistics":{},"problems":[]}
 for category,variants in TRIALS:
  checks={}
  for mode in ("B1","B2","B3"):
   for variant in variants:
    folder=OUT/category/f"{mode}_{variant}"
    trades=pl.read_parquet(folder/"trades.parquet").sort("entry_time")
    fills=pl.read_parquet(folder/"fills.parquet") # native journal order, no lexicographic order-ID sorting
    signal=json.loads((folder/"signals.json").read_text())
    m=json.loads((folder/"metrics.json").read_text())
    problems=[]
    stats={
     "trades":trades.height,"fills":fills.height,
     "first_signal":signal[0]["signal_at"] if signal else None,
     "last_signal":signal[-1]["signal_at"] if signal else None,
     "limit_fill_count":0,"hard_exit_count":0,
     "same_bar_entry_exit":0,"dual_touch_exits":0,
     "source_price_not_cme":True
    }
    if trades.height!=len(signal) or fills.height!=2*trades.height:
     problems.append("incomplete native trade to signal or fill ledger")
    slip={"gross":0.,"cost":.25,"stress":.5,"queue1tick":.25,"stress4tick":1.0}[variant]
    fee=0 if variant=="gross" else 2.50
    for i,row in enumerate(trades.iter_rows(named=True)):
     s=signal[i]
     entry=row["entry_time"]
     eidx=row_index.get(entry)
     if eidx is None or eidx<20:
      problems.append("source entry missing 20 prior bars")
      continue
     if entry!=parse(s["expected_entry_at"]):
      problems.append("next-bar causality")
     tp=math.ceil((max(highs[eidx-5:eidx])-1e-9)/.25)*.25
     sl=math.floor((min(lows[eidx-20:eidx])+1e-9)/.25)*.25
     if abs(tp-s["take_profit"])>1e-7 or abs(sl-s["stop_loss"])>1e-7:
      problems.append("noncausal tp/sl lookback")
     if abs(row["entry_price"]-(opens[eidx]+slip))>1e-7:
      problems.append("entry execution price")
     entry_local=entry.replace(tzinfo=timezone.utc).astimezone(CT)
     exit_time=row["exit_time"]
     exit_local=exit_time.replace(tzinfo=timezone.utc).astimezone(CT)
     if exit_local.date()!=entry_local.date() or exit_local.strftime("%H:%M")>"15:14":
      problems.append("overnight / 15:14 cutoff")
     if exit_time==entry:stats["same_bar_entry_exit"]+=1
     x=row_index.get(exit_time)
     if x is not None and lows[x]<=sl and highs[x]>=tp:
      stats["dual_touch_exits"]+=1
      exit_fill=fills.filter((pl.col("timestamp")==exit_time)&(pl.col("side")=="sell"))
      # Multiple trades may use the same timestamp, so order-level ambiguity
      # cannot be resolved by timestamp alone when more than one sell.
      if exit_fill.height==1 and exit_fill["order_type"][0]!="stop":
       problems.append("dual touch not stop-first")
    for j,f in enumerate(fills.iter_rows(named=True)):
     if f["side"]!=("buy" if j%2==0 else "sell"):
      problems.append("unexpected native order/reversal")
     if abs(f["commission"]-fee)>1e-8:
      problems.append("commission")
     if f["order_type"]=="limit":
      stats["limit_fill_count"]+=1
      if (f["side"]=="sell" and f["price"]+1e-8<f["limit_price"]) or (f["side"]=="buy" and f["price"]-1e-8>f["limit_price"]):
       problems.append("limit price floor")
      if abs(f["slippage"])>1e-9:
       problems.append("illegal adverse limit slippage")
     elif abs(f["slippage"]-slip)>1e-8:
      problems.append("aggressive fill slippage")
     if f["order_type"]=="market" and f["side"]=="sell":
      stats["hard_exit_count"]+=1
      local=f["timestamp"].replace(tzinfo=timezone.utc).astimezone(CT)
      if local.strftime("%H:%M")!="15:14":
       problems.append("unexpected market close time")
    if abs(m["reconciliation_difference_usd"])>1e-5:
     problems.append("native net trade/account mismatch")
    checks[f"{mode}_{variant}"]={**stats,
      "net_pnl_usd":float(m["net_account_pnl_usd"]),
      "sharpe":m["daily_equity_sharpe"],
      "errors":sorted(set(problems))}
    if problems:
     out["problems"].append((category,f"{mode}_{variant}",checks[f"{mode}_{variant}"]["errors"]))
  out["runs"][category]=checks
 for category in ("development","validation"):
  analysis={}
  for mode in ("B1","B2","B3"):
   d=pl.read_parquet(OUT/category/f"{mode}_cost/daily_equity.parquet").sort("day")
   days=[str(x) for x in d["day"].to_list()]
   pnl=np.diff(np.r_[1_000_000.,d["equity"].to_numpy()])
   monthly={}
   for month in sorted(set(s[:7] for s in days)):
    monthly[month]={"trading_days":sum(s.startswith(month) for s in days),
      "pnl_usd":round(float(sum(pnl[i] for i,s in enumerate(days) if s.startswith(month))),2)}
   analysis[mode]={"monthly":monthly,"block_bootstrap":bootstrap(pnl,20261012),
                  "days":days}
  days2=analysis["B2"]["days"]
  days3=analysis["B3"]["days"]
  if days2!=days3:
   out["problems"].append((category,"paired_sessions","B2/B3 day identities disagree"))
  else:
   x2=pl.read_parquet(OUT/category/"B2_cost/daily_equity.parquet").sort("day")["equity"].to_numpy()
   x3=pl.read_parquet(OUT/category/"B3_cost/daily_equity.parquet").sort("day")["equity"].to_numpy()
   diff=np.diff(np.r_[1_000_000.,x3])-np.diff(np.r_[1_000_000.,x2])
   analysis["paired_B3_minus_B2"]=bootstrap(diff,20261013)
  for mode in ("B1","B2","B3"):analysis[mode].pop("days",None)
  out["statistics"][category]=analysis
 out["status"]="PASS_MECHANICAL_CFD_PROXY" if not out["problems"] else "FAILED_EXECUTION_AUDIT"
 out["CME_qualified"]=False
 out["July_September_complete"]=False
 out["September_available"]=False
 out["Nov_prospective_holdout_accessed"]=False
 path=OUT/"independent_dukascopy_audit_v2.json"
 if path.exists():raise FileExistsError("Do not overwrite first audit")
 path.write_text(json.dumps(out,indent=2,default=str)+"\n")
 print(json.dumps({
  "status":out["status"],"problems":out["problems"],
  "development":{k:{"monthly":v.get("monthly"),"block_ci":v.get("block_bootstrap",{}).get("block5_total_95pct")} for k,v in out["statistics"]["development"].items() if k!="paired_B3_minus_B2"},
  "validation_months":out["statistics"]["validation"]},indent=2)[:10500])
 if out["problems"]:raise RuntimeError("Audit failed, do not accept figures")
if __name__=="__main__":audit_all()
