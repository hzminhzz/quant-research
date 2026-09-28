#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from datetime import date
from pathlib import Path
import polars as pl
from scripts.run_crypto_salience import diagnostic,portfolio,sim
from src.experiment import compute_deflated_sharpe

WS=(7,14,30);CAN=14;COST=10.;TOPN=50
DEV0=date(2022,1,1);DEV1=date(2024,1,1);OOS0=date(2024,1,1);OOS1=date(2026,1,1)
OUT=Path("run_log/crypto_research/runs/20260928-realized-kurtosis-weekly-result.json")

def emit(x):
 s=json.dumps(x,indent=2,default=str);OUT.write_text(s+"\n",encoding="utf-8");print(s)

def load(root):
 p=str(root/"symbol=*"/"year=*"/"month=*"/"data.parquet")
 return (pl.scan_parquet(p,hive_partitioning=True)
  .filter(pl.col("symbol").str.ends_with("USDT")&(pl.col("symbol")!="BTCDOMUSDT")
          &(pl.col("timestamp")>=pl.datetime(2020,6,1,time_zone="UTC"))
          &(pl.col("timestamp")<pl.datetime(2026,1,9,time_zone="UTC")))
  .select("timestamp","symbol","open","close","quote_volume").sort(["symbol","timestamp"])
  .with_columns(pl.col("timestamp").shift(1).over("symbol").alias("_pt"),
                pl.col("close").shift(1).over("symbol").alias("_pc"))
  .with_columns(pl.when(pl.col("timestamp")-pl.col("_pt")==pl.duration(hours=1))
                .then((pl.col("close")/pl.col("_pc")).log()).otherwise(None).alias("_r"),
                pl.col("timestamp").dt.date().alias("date"))
  .with_columns((pl.col("_r")**2).alias("_r2"),(pl.col("_r")**3).alias("_r3"),(pl.col("_r")**4).alias("_r4"))
  .group_by(["symbol","date"]).agg(pl.col("open").first().alias("open"),pl.col("quote_volume").sum().alias("qv"),
      pl.col("_r").sum().alias("s1"),pl.col("_r2").sum().alias("s2"),pl.col("_r3").sum().alias("s3"),
      pl.col("_r4").sum().alias("s4"),pl.col("_r").count().alias("n"),pl.len().alias("hours"))
  .filter((pl.col("hours")==24)&(pl.col("n")==24)).drop("hours").sort(["symbol","date"]).collect())

def frame(d,w):
 x=(d.with_columns(
    *[pl.col(c).shift(1).rolling_sum(w).over("symbol").alias("_"+c) for c in ("s1","s2","s3","s4","n")],
    pl.col("qv").shift(1).rolling_sum(30).over("symbol").alias("_liq"),
    pl.col("date").shift(w).over("symbol").alias("_aw"),pl.col("date").shift(30).over("symbol").alias("_a30"),
    pl.col("open").shift(-7).over("symbol").alias("_o7"),pl.col("date").shift(-7).over("symbol").alias("_d7"),
    pl.col("open").shift(-1).over("symbol").alias("_o1"),pl.col("date").shift(-1).over("symbol").alias("_d1"),
    pl.col("open").shift(-8).over("symbol").alias("_o8"),pl.col("date").shift(-8).over("symbol").alias("_d8"))
   .with_columns((pl.col("_s1")/pl.col("_n")).alias("_mu"))
   .with_columns(((pl.col("_s2")-pl.col("_s1")**2/pl.col("_n"))/pl.col("_n")).alias("_m2"),
      ((pl.col("_s4")-4*pl.col("_mu")*pl.col("_s3")+6*pl.col("_mu")**2*pl.col("_s2")-3*pl.col("_n")*pl.col("_mu")**4)/pl.col("_n")).alias("_m4"))
   .with_columns((pl.col("_m4")/pl.col("_m2")**2-3).alias("signal"),
      (pl.col("_o7")/pl.col("open")-1).alias("fwd_ret"),(pl.col("_o8")/pl.col("_o1")-1).alias("delay_ret"))
   .filter((pl.col("date").dt.weekday()==1)&pl.col("signal").is_finite()&pl.col("_liq").is_finite()&(pl.col("_m2")>0)
      &(pl.col("_aw")==pl.col("date")-pl.duration(days=w))&(pl.col("_a30")==pl.col("date")-pl.duration(days=30))
      &(pl.col("_d7")==pl.col("date")+pl.duration(days=7))&(pl.col("_d1")==pl.col("date")+pl.duration(days=1))
      &(pl.col("_d8")==pl.col("date")+pl.duration(days=8))))
 out=[]
 for q in x.partition_by("date",maintain_order=True):
  q=q.sort("_liq",descending=True).head(TOPN)
  if q.height>=10:out.append(q.select("date","symbol","signal","fwd_ret","delay_ret"))
 return pl.concat(out,how="vertical").sort(["date","symbol"]) if out else pl.DataFrame()

def main():
 a=argparse.ArgumentParser();a.add_argument("--root",type=Path,required=True);z=a.parse_args()
 d=load(z.root);fs={w:frame(d,w) for w in WS};di={w:diagnostic(fs[w],DEV0,DEV1) for w in WS}
 dev={w:sim(portfolio(fs[w],DEV0,DEV1),COST) for w in WS};cd=di[CAN];cm=dev[CAN]["metrics"]
 gate=cd["mean_ic"]>.02 and cd["hac_p"]<.05 and cd["high_minus_low"]>0 and cm["annualized_sharpe"]>.7 and cm["total_return"]>0 and sum(dev[w]["metrics"]["total_return"]>0 for w in WS)>=2
 out={"schema_version":1,"run_id":"20260928-realized-kurtosis-weekly","strategy_family":"realized_kurtosis","research_archetype":"cross_sectional_higher_moment_factor","universe_symbols":d["symbol"].n_unique(),
      "development_diagnostics":{str(w):di[w] for w in WS},"development":{str(w):dev[w] for w in WS},"development_gate_passed":gate,"oos_consumed":False,
      "trial_accounting":{"previous_parameter_trials":106,"new_parameter_trials":3,"cumulative_parameter_trials":109}}
 if not gate:
  out.update(classification="REJECT",success_gate_candidate=False,conclusion="Development gate failed; OOS not consumed.");emit(out);return
 res={};sharp=[]
 for w in WS:
  rows=portfolio(fs[w],OOS0,OOS1);res[str(w)]={str(m):sim(rows,COST*m) for m in (1,2,3)};sharp.append(res[str(w)]["1"]["metrics"]["annualized_sharpe"])
 b=res[str(CAN)]["1"];bm=b["metrics"];odi=diagnostic(fs[CAN],OOS0,OOS1)
 ex=sim(portfolio(fs[CAN],OOS0,OOS1,exclude={"BTCUSDT","ETHUSDT"}),COST)
 strong=max(b["asset_contribution"],key=lambda s:abs(b["asset_contribution"][s])) if b["asset_contribution"] else None
 exs=sim(portfolio(fs[CAN],OOS0,OOS1,exclude={strong}),COST) if strong else None
 delay=sim(portfolio(fs[CAN],OOS0,OOS1,retcol="delay_ret"),COST)
 yrs=all(b["by_year"].get(str(y),{}).get("total_return",-1)>=0 for y in (2024,2025));stable=sum(res[str(w)]["1"]["metrics"]["total_return"]>0 for w in WS)>=2
 dsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp,n_obs_days=max(bm["n_weeks"]*7,1));gdsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp+[0.]*106,n_obs_days=max(bm["n_weeks"]*7,1))
 qual=bm["annualized_sharpe"]>1 and odi["mean_ic"]>.02 and res[str(CAN)]["2"]["metrics"]["total_return"]>0 and stable and yrs and bm["max_drawdown"]>-.35 and ex["metrics"]["total_return"]>0 and delay["metrics"]["total_return"]>0 and (exs is None or exs["metrics"]["total_return"]>0)
 out.update(oos_consumed=True,oos_diagnostics=odi,oos_results=res,exclude_btc_eth=ex,strongest_asset=strong,exclude_strongest=exs,delay_one_day=delay,
   multiple_testing={"family_dsr":dsr,"global_109_trial_proxy":gdsr,"pbo":"N/A: three preregistered windows"},success_gate_candidate=qual,classification="EXPLORATORY_PASS" if qual else "REJECT");emit(out)
if __name__=="__main__":main()
