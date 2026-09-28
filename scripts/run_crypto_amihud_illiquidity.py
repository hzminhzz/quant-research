#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,math
from datetime import date
from pathlib import Path
import numpy as np
import polars as pl
from scipy.stats import spearmanr
from scripts.run_crypto_risk_managed_xs_momentum import load_daily,week_ret_map,sim
from src.experiment import compute_deflated_sharpe

WINS=(14,30,60);CAN=30;COST=10.;MIN_XS=10
DEV0=date(2022,1,1);DEV1=date(2024,1,1);OOS0=date(2024,1,1);OOS1=date(2026,1,1)

def feature_frame(d,w):
 hist=max(w,30)+1
 x=(d.sort(["symbol","date"])
    .with_columns((pl.col("close")/pl.col("close").shift(1).over("symbol")-1).alias("_ret"))
    .with_columns((pl.col("_ret").abs()/pl.col("qv")).alias("_illiq"))
    .with_columns(
      pl.col("_illiq").shift(1).rolling_mean(w).over("symbol").alias("signal"),
      pl.col("qv").shift(1).rolling_sum(30).over("symbol").alias("_liq"),
      pl.col("date").shift(hist).over("symbol").alias("_anchor"))
    .filter((pl.col("date").dt.weekday()==1)&pl.col("signal").is_finite()&pl.col("_liq").is_finite()
            &(pl.col("_anchor")==pl.col("date")-pl.duration(days=hist))))
 out=[]
 for p in x.partition_by("date",maintain_order=True):
  p=p.sort("_liq",descending=True).head(100)
  if p.height>=MIN_XS:out.append(p.select("date","symbol","signal"))
 return pl.concat(out,how="vertical").sort(["date","symbol"]) if out else pl.DataFrame()

def targets(f,start,end,exclude=None):
 ex=exclude or set();out={}
 z=f.filter((pl.col("date")>=start)&(pl.col("date")<end))
 for p in z.partition_by("date",maintain_order=True):
  rows=sorted([(str(r["symbol"]),float(r["signal"])) for r in p.iter_rows(named=True) if str(r["symbol"]) not in ex],key=lambda q:q[1])
  if len(rows)<MIN_XS:continue
  k=max(2,len(rows)//5);w={}
  for s,_ in rows[:k]:w[s]=-.5/k
  for s,_ in rows[-k:]:w[s]=.5/k
  out[p["date"][0]]=w
 return out

def diagnostic(f,wr,start,end):
 vals=[];sp=[]
 for p in f.filter((pl.col("date")>=start)&(pl.col("date")<end)).partition_by("date",maintain_order=True):
  rows=[r for r in p.iter_rows(named=True) if (r["date"],str(r["symbol"])) in wr]
  if len(rows)<MIN_XS:continue
  s=np.array([float(r["signal"]) for r in rows]);y=np.array([wr[(r["date"],str(r["symbol"]))] for r in rows])
  ic=float(spearmanr(s,y).statistic)
  if np.isfinite(ic):vals.append(ic)
  ix=np.argsort(s);k=max(2,len(ix)//5);sp.append(float(y[ix[-k:]].mean()-y[ix[:k]].mean()))
 a=np.array(vals);m=float(a.mean()) if len(a) else 0.;sd=float(a.std(ddof=1)) if len(a)>1 else 0.
 return {"n_weeks":len(a),"mean_ic":m,"ic_ir":m/sd if sd>0 else 0.,"top_minus_bottom":float(np.mean(sp)) if sp else 0.}


def main():
 ap=argparse.ArgumentParser();ap.add_argument("--root",type=Path,required=True);a=ap.parse_args()
 d=load_daily(a.root);wr=week_ret_map(d);fs={w:feature_frame(d,w) for w in WINS}
 di={w:diagnostic(fs[w],wr,DEV0,DEV1) for w in WINS}
 dev={w:sim(targets(fs[w],DEV0,DEV1),wr,DEV0,DEV1,COST) for w in WINS}
 dr={w:dev[w]["metrics"]["total_return"] for w in WINS};ds={w:dev[w]["metrics"]["annualized_sharpe"] for w in WINS}
 gate=di[CAN]["mean_ic"]>.02 and di[CAN]["top_minus_bottom"]>0 and ds[CAN]>.70 and dr[CAN]>0 and sum(v>0 for v in dr.values())>=2
 out={"schema_version":1,"run_id":"20260928-amihud-illiquidity-premium-weekly","universe_symbols":d["symbol"].n_unique(),
      "development_diagnostics":{str(w):di[w] for w in WINS},
      "development":{str(w):dev[w] for w in WINS},"development_gate_passed":gate,"oos_consumed":False,
      "trial_accounting":{"previous_parameter_trials":71,"new_parameter_trials":3,"cumulative_parameter_trials":74}}
 if not gate:
  out.update(classification="REJECT",success_gate_candidate=False,conclusion="Development gate failed; OOS not consumed.")
  print(json.dumps(out,indent=2,default=str));return
 res={};sharp=[]
 for w in WINS:
  res[str(w)]={}
  tg=targets(fs[w],OOS0,OOS1)
  for m in (1,2,3):res[str(w)][str(m)]=sim(tg,wr,OOS0,OOS1,COST*m)
  sharp.append(res[str(w)]["1"]["metrics"]["annualized_sharpe"])
 base=res[str(CAN)]["1"];bm=base["metrics"];ex=sim(targets(fs[CAN],OOS0,OOS1,{"BTCUSDT","ETHUSDT"}),wr,OOS0,OOS1,COST)
 strong=max(base["asset_contribution"],key=base["asset_contribution"].get) if base.get("asset_contribution") else None
 exs=sim(targets(fs[CAN],OOS0,OOS1,{strong} if strong else set()),wr,OOS0,OOS1,COST) if strong else None
 yrs=all(base["by_year"].get(str(y),{}).get("total_return",-1)>=0 for y in (2024,2025))
 stable=sum(res[str(w)]["1"]["metrics"]["total_return"]>0 for w in WINS)>=2
 qual=(bm["annualized_sharpe"]>1 and bm["total_return"]>0 and res[str(CAN)]["2"]["metrics"]["total_return"]>0
       and stable and yrs and bm["max_drawdown"]>-.35 and ex["metrics"]["total_return"]>0
       and (exs is None or exs["metrics"]["total_return"]>0))
 dsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp,n_obs_days=max(bm["n_weeks"]*7,1))
 glob=compute_deflated_sharpe(bm["annualized_sharpe"],sharp+[0.]*71,n_obs_days=max(bm["n_weeks"]*7,1))
 out.update(oos_consumed=True,oos_diagnostics={str(w):diagnostic(fs[w],wr,OOS0,OOS1) for w in WINS},
            oos_results=res,exclude_btc_eth=ex,strongest_asset=strong,exclude_strongest=exs,
            multiple_testing={"family_dsr":dsr,"global_74_trial_proxy":glob,"pbo":"N/A: three preregistered lookbacks"},
            success_gate_candidate=qual,classification="EXPLORATORY_PASS" if qual else "REJECT")
 print(json.dumps(out,indent=2,default=str))

if __name__=="__main__":main()
