"""Program 1 v3 observational chart, pairwise minute/09:55 availability.

Not a trading signal, indicator feature, or native execution simulator. Uses the
same frozen 2020-Aug2026 source snapshots; no missing-price interpolation.
"""
from pathlib import Path
import numpy as np
import polars as pl
import statsmodels.api as sm
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"data/processed/tokyo_alpha_map_program1_v1"
CAL=ROOT/"run_log/tokyo_fix_alpha_map_program1_20261010/execution_v1/calendar_event_registry.parquet"
OUT=ROOT/"run_log/tokyo_alpha_map_program1_closure_v3/T2_alpha_windows"
DST=OUT/"coverage_corrected_cumulative_map.png"
CSV=OUT/"coverage_corrected_curves.csv"
ANCHOR=595

def ci(arr):
    if len(arr)<5:return float("nan"),float("nan"),float("nan")
    fit=sm.OLS(arr,np.ones((len(arr),1))).fit(cov_type="HAC",
        cov_kwds={"maxlags":min(5,len(arr)-1)},use_t=True)
    lo,hi=fit.conf_int()[0]
    return float(fit.params[0]),float(lo),float(hi)

def main():
    if DST.exists() or CSV.exists():raise RuntimeError("Chart artifacts already exist")
    files=[str(BASE/f"USDJPY_03_12_JST_{y}.parquet") for y in range(2020,2027)]
    data=(pl.scan_parquet(files)
      .with_columns(pl.col("timestamp").dt.convert_time_zone("Asia/Tokyo").alias("jst"))
      .with_columns(
        pl.col("jst").dt.date().alias("session"),
        (pl.col("jst").dt.hour().cast(pl.Int32)*60+pl.col("jst").dt.minute().cast(pl.Int32)).alias("minute"))
      .select("session","minute","open").collect())
    pivot=data.pivot(on="minute",index="session",values="open")
    reg=pl.read_parquet(CAL).select("session","gotobi","ordinary")
    panel=reg.join(pivot,on="session",how="left")
    if str(ANCHOR) not in panel.columns:raise RuntimeError("Missing anchor")
    anch=panel[str(ANCHOR)].to_numpy()
    got=panel["gotobi"].to_numpy()
    ord_=panel["ordinary"].to_numpy()
    out=[]
    for minute in range(180,721):
        if str(minute) not in panel.columns:
            values=np.full(len(anch),float("nan"))
        else:
            values=100*(panel[str(minute)].to_numpy()-anch)
        values=np.asarray(values,dtype=float)
        row={"minute":minute}
        for name,mask in [("gotobi",got),("ordinary",ord_)]:
            arr=values[mask&np.isfinite(values)]
            mean,lo,hi=ci(arr)
            row.update({name+"_mean":mean,name+"_lo":lo,name+"_hi":hi,
                        name+"_n":len(arr)})
        out.append(row)
    result=pl.DataFrame(out)
    OUT.mkdir(parents=True,exist_ok=True)
    result.write_csv(CSV)
    f,ax=plt.subplots(figsize=(12,6))
    for name,label in [("gotobi","Gotobi"),("ordinary","Ordinary Tokyo days")]:
        x=result["minute"].to_numpy()/60
        y=result[name+"_mean"].to_numpy()
        l=result[name+"_lo"].to_numpy()
        h=result[name+"_hi"].to_numpy()
        ax.plot(x,y,label=label)
        ax.fill_between(x,l,h,alpha=.15)
    ax.axvline(9+55/60,ls="--",color="grey",label="09:55 JST fix")
    ax.axhline(0,color="grey",lw=.7)
    ax.set(xlim=(3,12),xlabel="Tokyo local time (JST)",ylabel="USDJPY minus 09:55 price (pips)",
           title="Tokyo fixing alpha map (2020-Aug 2026) - pairwise available minutes")
    ax.legend()
    f.text(.1,.025,"HAC pointwise 95% intervals; eligible dates vary by minute; no filled missing bars.",fontsize=9)
    f.tight_layout(rect=[0,.05,1,1]); f.savefig(DST,dpi=150);plt.close(f)
    for m in [180,300,420,510,594,595,596,610,630,660,720]:
        r=result.filter(pl.col("minute")==m).to_dicts()[0]
        print(m,r["gotobi_n"],r["ordinary_n"],round(r["gotobi_mean"],3) if np.isfinite(r["gotobi_mean"]) else None)
    print(DST)
if __name__=="__main__":main()
