"""Reconcile native B0 index-transfer ledgers and compute ML4T risk metrics."""
from __future__ import annotations
import json
from datetime import date, timedelta
from pathlib import Path
import numpy as np
import polars as pl
from ml4t.backtest.analytics import sharpe_ratio, calmar_ratio, max_drawdown

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"run_log/one_bar_b0_cross_indices_20261012/phase34"
BASE=ROOT/"run_log/one_bar_practical_1m_20261012/by_year"
SYMS=("NQ","ES","DAX","NIKKEI225")
PERIODS={"full":(date(2013,1,1),date(2026,7,15)),
         "pre_DAX_corruption_2013_2023":(date(2013,1,1),date(2024,1,1)),
         "2018_2023":(date(2018,1,1),date(2024,1,1)),
         "2018_2025":(date(2018,1,1),date(2026,1,1)),
         "2022_2025":(date(2022,1,1),date(2026,1,1)),
         "2026":(date(2026,1,1),date(2026,7,15))}

def trades(sym):
    paths=([BASE/str(y)/"native_full_tick_cost/evaluation_trades.csv" for y in range(2013,2027)] if sym=="NQ" else
           [OUT/sym/str(y)/"native_costed_synthetic/evaluation_trades.csv" for y in range(2013,2027)])
    if not all(x.is_file() for x in paths):
        raise RuntimeError("Missing annual native trade file for "+sym)
    return pl.concat([pl.read_csv(x,try_parse_dates=False) for x in paths],how="diagonal_relaxed").filter(
        pl.col("status")=="closed").with_columns(
        pl.col("entry_time").str.to_datetime(time_zone="UTC",strict=False).dt.date().alias("utc_date"),
        pl.col("pnl").cast(pl.Float64,strict=False).alias("pnl"))

def cut(df,start,end):
    return df.filter((pl.col("utc_date")>=start)&(pl.col("utc_date")<end))

def daily_R(df,start,end):
    a=df.group_by("utc_date").agg((pl.col("pnl").sum()/1000.0).alias("R"))
    d=dict(zip(a["utc_date"].to_list(),a["R"].to_list()))
    return np.array([d.get(start+timedelta(days=i),0.) for i in range((end-start).days)],dtype=np.float64)

def metrics(df,start,end):
    pnl=df["pnl"].to_numpy()
    n=len(pnl)
    gain=pnl[pnl>0].sum()
    loss=-pnl[pnl<0].sum()
    r=daily_R(df,start,end)
    sh=float(sharpe_ratio(r,annualize=False)*np.sqrt(365.25)) if r.std()>0 else None
    equity=1000.0+np.r_[0.,np.cumsum(r)]
    maxdd,peak,trough=max_drawdown(equity)
    if equity[-1]>0 and maxdd<0:
        cagr=(equity[-1]/equity[0])**(365.25/len(r))-1
        cal=float(calmar_ratio(cagr,maxdd))
    else:
        cagr=cal=None
    return {
      "closed_trades":int(n),"net_R":float(pnl.sum()/1000.),
      "mean_R_per_trade":float(pnl.mean()/1000.) if n else None,
      "win_rate":float((pnl>0).mean()) if n else None,
      "profit_factor":float(gain/loss) if loss else None,
      "worst_trade_R":float(pnl.min()/1000.) if n else None,
      "daily_realized_sharpe":sh,
      "calmar_on_fixed_1000R_balance":cal,
      "max_realized_drawdown_R":float(equity[peak]-equity[trough]),
      "initial_balance_R":1000.0,
      "realized_only_not_mark_to_market":True,
    }

def bootstrap(series,nrep=2000,block=5):
    n=len(next(iter(series.values())))
    rng=np.random.default_rng(20261012+block)
    nb=(n+block-1)//block
    blockstarts=rng.integers(0,n,size=(nrep,nb),dtype=np.int32)
    indices=((blockstarts[:,:,None]+np.arange(block,dtype=np.int32))%n).reshape(nrep,-1)[:,:n]
    out={}
    nq_sharpe=None
    for sym,x in series.items():
        sampled=x[indices]
        pnl=sampled.sum(axis=1)
        mean=sampled.mean(axis=1)
        sd=sampled.std(axis=1,ddof=1)
        sh=np.divide(mean,sd,out=np.zeros_like(mean),where=sd>0)*np.sqrt(365.25)
        cum=sampled.cumsum(axis=1)
        running=np.maximum.accumulate(np.concatenate([np.zeros((nrep,1)),cum],axis=1),axis=1)[:,1:]
        dd=np.max(running-cum,axis=1)
        row={
          "iterations":nrep,"block_days":block,
          "terminal_R_p05_p50_p95":np.quantile(pnl,[.05,.5,.95]).tolist(),
          "prob_terminal_R_positive":float((pnl>0).mean()),
          "sharpe_p05_p50_p95":np.quantile(sh,[.05,.5,.95]).tolist(),
          "drawdown_R_p50_p95":np.quantile(dd,[.5,.95]).tolist(),
          "prob_drawdown_over_10R":float((dd>10).mean()),
        }
        if sym=="NQ":nq_sharpe=sh
        else:
            delta=sh-nq_sharpe
            row["paired_delta_sharpe_vs_NQ_p05_p50_p95"]=np.quantile(delta,[.05,.5,.95]).tolist()
            row["prob_sharpe_exceeds_NQ"]=float((delta>0).mean())
        out[sym]=row
    return out

def audit(df):
    errors=[]
    for sym in SYMS[1:]:
        status=json.loads((OUT/sym/"summary.json").read_text())
        if status["status"]!="completed" or status["completed_years"]!=14:
            errors.append(sym+" not complete: "+str(status["failure_years"]))
            continue
        total=0
        for y in range(2013,2027):
            m=json.loads((OUT/sym/str(y)/"year_summary.json").read_text())
            e=next(x for x in m["trials"] if x["trial"]=="native_costed_synthetic")
            x=pl.read_csv(OUT/sym/str(y)/"native_costed_synthetic/evaluation_trades.csv")
            x=x.filter(pl.col("status")=="closed").with_columns(pl.col("pnl").cast(pl.Float64,strict=False))
            if x.height!=e["closed_trades"] or abs(float(x["pnl"].sum())-e["net_synthetic_accounting_usd"])>1e-5:
                errors.append(sym+" "+str(y)+" native PnL or count mismatch")
            if e["max_entry_fills_per_chicago_day"]>2:
                errors.append(sym+" "+str(y)+" daily entry cap violated")
            total+=x.height
        if total!=df[sym].height:
            errors.append(sym+" total closed trades mismatch")
    if df["NQ"].height!=5462 or abs(float(df["NQ"]["pnl"].sum())-166107.92)>1e-5:
        errors.append("NQ frozen control mismatch")
    return {"status":"PASS" if not errors else "FAILED","errors":errors}

def main():
    for sym in SYMS[1:]:
        if not (OUT/sym/"summary.json").is_file():
            raise RuntimeError("Native batch still running for "+sym)
    data={sym:trades(sym) for sym in SYMS}
    check=audit(data)
    if check["status"]!="PASS":
        raise RuntimeError(check["errors"])
    period_rows={}
    for label,(start,end) in PERIODS.items():
        period_rows[label]={sym:metrics(cut(data[sym],start,end),start,end) for sym in SYMS}
    mc={}
    for label in ("full","2026","pre_DAX_corruption_2013_2023"):
        start,end=PERIODS[label]
        valid_symbols=SYMS if label=="pre_DAX_corruption_2013_2023" else ("NQ","ES","NIKKEI225")
        panel={sym:daily_R(cut(data[sym],start,end),start,end) for sym in valid_symbols}
        mc[label]={"5day":bootstrap(panel,2000,5),"20day":bootstrap(panel,2000,20)}
    price_audit=json.loads((OUT/"extreme_price_jump_audit.json").read_text())
    assert price_audit["DAX"]["extreme_discontinuities"]==1000
    result={
       "status":"EXPLORATORY_COMPLETED_DAX_POST2023_DATA_BLOCKED",
       "study":"Frozen NQ B0 literal raw 50-point stop cross-index transfer",
       "synthetic_unit":"1R=50 raw index points; 20 synthetic units per point, 1 contract, per-side cost 2.50 synthetic units +0.25 point adverse slippage",
       "warning":"ES, DAX, Nikkei USD dollar PnL not tradable futures returns; no actual currency/contract/cost mapping.",
       "portfolio_measurement":"Calendar UTC daily realized trade PnL allocated to entry date, not mark-to-market. Calmar assumes initial 1000 synthetic R.",
       "no_holdout":"All data through 2026-07-14 already observed",
       "metrics":period_rows,"monte_carlo":mc,"audit":check,
       "price_jump_quality":price_audit,
       "instrument_decisions":{"NQ":"UNCHANGED_FROZEN_CONTROL",
          "ES":"EXPLORATORY_NEGATIVE_AFTER_SYNTHETIC_COSTS",
          "DAX":"PRE_2024_ONLY_DIAGNOSTIC; 2024-2026 SCALE_MIX_CORRUPTED; FULL_HISTORY_INVALID",
          "NIKKEI225":"EXPLORATORY_POSITIVE_SYNTHETIC_ONLY; REAL_COSTS_AND_LIVE_VALIDATION_UNRESOLVED",
          "HSI":"BLOCKED_1M_SOURCE_MISSING"},
       "blocked":"Hang Seng 1min data unavailable; DAX 2024-onward scale-mixed corruption; no real cross-contract currency mapping",
       "method":"ml4t.backtest.Engine original B0 strategy; ML4T analytics for risk; Polars-only future event labels; paired NumPy block bootstrap for uncertainty"
    }
    (OUT/"final_research_metrics.json").write_text(json.dumps(result,indent=2)+"\n")
    print("FINAL_AUDIT",check["status"])
    for period,rows in period_rows.items():
        print(period)
        for sym,v in rows.items():
            print(sym,"n",v["closed_trades"],"R",round(v["net_R"],2),"win",round(v["win_rate"]*100,2),"PF",round(v["profit_factor"],2) if v["profit_factor"] is not None else None,"sh",round(v["daily_realized_sharpe"],3) if v["daily_realized_sharpe"] is not None else None,"Cal",round(v["calmar_on_fixed_1000R_balance"],3) if v["calmar_on_fixed_1000R_balance"] is not None else None)
if __name__=="__main__":main()
