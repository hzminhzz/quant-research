"""Frozen 2020-2026 Gotobi event diagnostics, using ml4t.diagnostic.

The frozen calendar rules and complete 1-minute windows supply the event
panel; no account PnL or trade backtest loop is implemented here.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import numpy as np
import polars as pl
import statsmodels.api as sm
from ml4t.diagnostic import quantile_profile
from scripts.materialize_gotobi_2020_2026_usd10k_v1 import eligible_days,gotobi_days

ROOT=Path(__file__).resolve().parents[1]
SID="usdjpy_gotobi_2020_2026_usd10000_v1"
SRC=ROOT/"data/processed/gotobi_2020_2026_usd10k_v1/USDJPY_tokyo_windows_1m.parquet"
SNAP=ROOT/"data/processed/gotobi_2020_2026_usd10k_v1/calendar_coverage.json"
PANEL=ROOT/f"data/features/{SID}_events.parquet"
OUT=ROOT/"run_log"/SID

def write(path,payload):
    if path.exists():raise RuntimeError(f"Refusing overwrite {path}")
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(payload,indent=2,allow_nan=False,default=str)+"\n")

def hac(values):
    arr=np.asarray(values,dtype=float)
    if len(arr)<3:return {"count":len(arr),"status":"INCONCLUSIVE"}
    fit=sm.OLS(arr,np.ones((len(arr),1))).fit(cov_type="HAC",cov_kwds={"maxlags":min(5,len(arr)-1)})
    return {"count":len(arr),"mean":float(fit.params[0]),
            "ci95":[float(t) for t in fit.conf_int()[0]],
            "positive_fraction":float((arr>0).mean()),"t":float(fit.tvalues[0])}

def yearly(frame,field="h1_long_pips",cost=1.):
    return [{"year":int(y),"trades":x.height,
       "gross_mean_pips":float(x[field].mean()),
       "net_mean_pips":float(x[field].mean()-cost),
       "gross_total_pips":float(x[field].sum()),
       "net_total_pips":float(x[field].sum()-cost*x.height),
       "net_win_rate":float(x.filter(pl.col(field)>cost).height/x.height)
       } for y,x in frame.partition_by("year",as_dict=True).items()] # Polars tuple keys normalized below

def main():
    if PANEL.exists():raise RuntimeError("Event features already exist")
    f=(pl.scan_parquet(SRC).select("timestamp","open")
       .with_columns(pl.col("timestamp").dt.convert_time_zone("Asia/Tokyo").alias("jst"))
       .with_columns(pl.col("jst").dt.date().alias("session"),
         (pl.col("jst").dt.hour().cast(pl.Int32)*60+pl.col("jst").dt.minute().cast(pl.Int32)).alias("minute_jst"))
       .collect())
    if f.height%151!=0:raise RuntimeError("Snapshot corrupted")
    stamps={480:"p0800",509:"p0829",510:"p0830",593:"p0953",
            594:"p0954",595:"p0955",596:"p0956",629:"p1029",630:"p1030"}
    ev=(f.filter(pl.col("minute_jst").is_in(list(stamps)))
      .group_by("session").agg([
       pl.col("open").filter(pl.col("minute_jst")==m).first().alias(n)
       for m,n in stamps.items()])
      .sort("session"))
    sessions,calendar=eligible_days()
    gotobi=gotobi_days(calendar)
    if not set(ev["session"].to_list()).issubset(set(sessions)):raise RuntimeError("Nonbusiness events")
    ev=(ev.with_columns(
        pl.col("session").is_in(sorted(gotobi)).alias("gotobi"),
        pl.col("session").dt.year().alias("year"),
        ((pl.col("p0954")-pl.col("p0830"))*100).alias("h1_long_pips"),
        ((pl.col("p0956")-pl.col("p1030"))*100).alias("h2_short_pips"),
        ((pl.col("p0955")-pl.col("p0800"))*100).alias("extension_pips"))
       .with_columns(pl.col("extension_pips").rolling_std(20,min_samples=20).shift(1).alias("prior20_sd_pips"))
       .with_columns((pl.col("extension_pips")>1.5*pl.col("prior20_sd_pips")).fill_null(False).alias("h2_gate")))
    if ev["year"].max()!=2026 or ev.height!=1595:raise RuntimeError("Wrong cohort")
    PANEL.parent.mkdir(parents=True,exist_ok=True)
    ev.write_parquet(PANEL,compression="zstd")
    g=ev.filter(pl.col("gotobi"))
    ordinary=ev.filter(~pl.col("gotobi"))
    h1=sm.OLS(ev["h1_long_pips"].to_numpy(),
      sm.add_constant(ev["gotobi"].cast(pl.Float64).to_numpy())).fit(cov_type="HAC",cov_kwds={"maxlags":5})
    # Avoid the unsupported cross-sectional IC for one instrument.
    prof=quantile_profile(
      ev.select(pl.col("session").alias("timestamp"),"extension_pips","h2_short_pips"),
      feature="extension_pips",label="h2_short_pips",by=None,n_quantiles=5,min_per_bucket=10)
    def year_rows(frame,col):
        res=[]
        for sub in frame.partition_by("year",maintain_order=True):
            y=int(sub["year"][0])
            v=sub[col]
            res.append({"year":y,"n":sub.height,
              "mean_gross_pips":float(v.mean()),
              "mean_after_1pip_pips":float(v.mean()-1.0),
              "net_win_rate":float((v>1.).sum()/sub.height),
              "gross_total_pips":float(v.sum())})
        return res
    # H2 only after past-only 20-session gate; compare to ungated Gotobi short.
    h2=g.filter(pl.col("h2_gate"))
    path=OUT/"T1_prefx_event_diagnostics"/"result.json"
    write(path,{
       "scope":"Exploratory 2020-Aug 2026, 1m exact time windows, retrospective",
       "snapshot_sha256":hashlib.sha256(SRC.read_bytes()).hexdigest(),
       "sessions":ev.height,"gotobi":g.height,"ordinary":ordinary.height,
       "gotobi_pips":hac(g["h1_long_pips"].to_numpy()),
       "ordinary_pips":hac(ordinary["h1_long_pips"].to_numpy()),
       "gotobi_minus_ordinary_pips":float(h1.params[1]),
       "difference_ci95_pips":h1.conf_int()[1].tolist(),
       "cost_sensitivity_mean_pips":{str(c):float(g["h1_long_pips"].mean()-c) for c in (.8,1.,1.4)},
       "by_year":year_rows(g,"h1_long_pips"),
    })
    write(OUT/"T2_postfix_event_diagnostics"/"result.json",{
       "scope":"Exploratory conditional post-fix short, past 20 complete Tokyo sessions only",
       "gated":hac(h2["h2_short_pips"].to_numpy()),
       "ungated":hac(g["h2_short_pips"].to_numpy()),
       "gate_count":h2.height,
       "cost_sensitivity_mean_pips":{str(c):float(h2["h2_short_pips"].mean()-c) for c in (.8,1.,1.4)},
       "by_year":year_rows(h2,"h2_short_pips"),
       "ml4t_diagnostic_quantile_profile":{"means":dict(prof.means),"counts":dict(prof.counts),"monotonicity":prof.monotonicity,"is_pooled":prof.is_pooled}
    })
    print(json.dumps({"H1":json.loads(path.read_text()),"H2":json.loads((OUT/"T2_postfix_event_diagnostics"/"result.json").read_text())},indent=2,default=str))
if __name__=="__main__":main()
