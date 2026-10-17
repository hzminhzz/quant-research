"""Exploratory event diagnostics for frozen Tokyo fixing thesis; no strategy simulation."""
from __future__ import annotations
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import statsmodels.api as sm
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
SESSION = "usdjpy_tokyo_fix_gotobi_20261010"
INPUT = ROOT / "data/processed/tokyo_fix_gotobi_20261010/USDJPY_dev_20260101_20260831_1m.parquet"
OUT = ROOT / "run_log" / SESSION
FEATURE = ROOT / "data/features" / f"{SESSION}_events.parquet"

# BOJ Tokyo bank closures in the development interval. Calendar verification
# remains a separate acceptance gate; do not mistake this for a certified feed.
HOLIDAYS = set(map(date.fromisoformat, [
    "2026-01-01","2026-01-02","2026-01-12",
    "2026-02-11","2026-02-23","2026-03-20",
    "2026-04-29","2026-05-04","2026-05-05","2026-05-06",
    "2026-07-20","2026-08-11",
]))

def business(d:date)->bool:
    return d.weekday()<5 and d not in HOLIDAYS

def roll(d:date)->date:
    while not business(d):
        d-=timedelta(days=1)
    return d

def candidates()->set[date]:
    out=set()
    for year in [2026]:
        for month in range(1,9):
            for day in [5,10,15,20,25,30]:
                try:
                    out.add(roll(date(year,month,day)))
                except ValueError:
                    pass
            nextmonth=date(year+int(month==12),month%12+1,1)
            out.add(roll(nextmonth-timedelta(days=1)))
    return out

def hac_ci(values:np.ndarray, lags:int=5)->dict:
    if len(values)<3:
        return {"n":int(len(values)),"mean":None,"ci95":None}
    fit=sm.OLS(values, np.ones((len(values),1))).fit(cov_type="HAC",cov_kwds={"maxlags":min(lags,len(values)-1)})
    return {"n":len(values),"mean":float(fit.params[0]),"ci95":[float(x) for x in fit.conf_int(alpha=0.05)[0]],"t":float(fit.tvalues[0])}

def main()->None:
    if OUT.exists() and (OUT/"H1_prefx_event_diagnostic"/"result.json").exists():
        raise RuntimeError("Existing outcome; refusing overwrite")
    df=(
        pl.scan_parquet(INPUT)
        .select("timestamp","open")
        .with_columns(
            pl.col("timestamp").dt.convert_time_zone("Asia/Tokyo").alias("jst")
        )
        .with_columns(
            pl.col("jst").dt.date().alias("session"),
            pl.col("jst").dt.strftime("%H:%M").alias("hhmm"),
        )
        .filter(pl.col("hhmm").is_in(["08:00","08:30","09:54","09:55","09:56","10:30"]))
        .group_by("session")
        .agg(pl.col("open").filter(pl.col("hhmm")=="08:00").first().alias("p0800"),
             pl.col("open").filter(pl.col("hhmm")=="08:30").first().alias("p0830"),
             pl.col("open").filter(pl.col("hhmm")=="09:54").first().alias("p0954"),
             pl.col("open").filter(pl.col("hhmm")=="09:55").first().alias("p0955"),
             pl.col("open").filter(pl.col("hhmm")=="09:56").first().alias("p0956"),
             pl.col("open").filter(pl.col("hhmm")=="10:30").first().alias("p1030"),
             pl.col("hhmm").n_unique().alias("observed_times"))
        .filter(pl.col("observed_times")==6)
        .sort("session")
        .collect()
    )
    dates=df["session"].to_list()
    gotobi=candidates()
    eligible=[business(d) for d in dates]
    df=df.filter(pl.Series("is_biz", eligible))
    df=df.with_columns(
        pl.Series("gotobi", [d in gotobi for d in df["session"].to_list()]),
        ((pl.col("p0954")-pl.col("p0830"))*100).alias("h1_long_pips"),
        ((pl.col("p0956")-pl.col("p1030"))*100).alias("h2_short_pips"),
        ((pl.col("p0955")-pl.col("p0800"))*100).alias("extension_pips"),
    ).with_columns(
        pl.col("extension_pips").rolling_std(window_size=20,min_samples=20).shift(1).alias("prior20_sd_pips")
    ).with_columns(
        (pl.col("extension_pips")>1.5*pl.col("prior20_sd_pips")).alias("h2_gate"),
    )
    if df["session"].max() >= date(2026,9,1):
        raise RuntimeError("Holdout contamination")
    FEATURE.parent.mkdir(parents=True,exist_ok=True)
    if FEATURE.exists():
        raise RuntimeError("Event panel exists")
    df.write_parquet(FEATURE)
    OUT.mkdir(parents=True,exist_ok=True)
    result={"session":SESSION,"development":"2026-01-01 through 2026-08-31 JST","source_sha256":hashlib.sha256(INPUT.read_bytes()).hexdigest(),"calendar":"PROVISIONAL 2026 Tokyo holiday enumerations; verify against authoritative BOJ before trading","events":df.height,"gotobi_dates_expected":len(gotobi),"gotobi_events":int(df["gotobi"].sum()),"days_with_six_required_minutes":df.height}
    g=df.filter(pl.col("gotobi"))["h1_long_pips"].to_numpy()
    ng=df.filter(~pl.col("gotobi"))["h1_long_pips"].to_numpy()
    # Difference of event means in a single time series, with a calendar-day HAC regression.
    valid=df.select("gotobi","h1_long_pips")
    fit=sm.OLS(valid["h1_long_pips"].to_numpy(),sm.add_constant(valid["gotobi"].cast(pl.Float64).to_numpy())).fit(cov_type="HAC",cov_kwds={"maxlags":5})
    result["H1"]={"gotobi":hac_ci(g),"ordinary":hac_ci(ng),"gotobi_minus_ordinary_pips":float(fit.params[1]),"difference_ci95_pips":[float(a) for a in fit.conf_int()[1]],"scenario_cost_adjusted_gotobi_mean_pips":{str(c):float(g.mean()-c) for c in [0.8,1.0,1.4]},"gotobi_win_rate":float((g>0).mean())}
    gated=df.filter(pl.col("gotobi") & pl.col("h2_gate").fill_null(False))
    allg=df.filter(pl.col("gotobi"))
    result["H2"]={"gated":hac_ci(gated["h2_short_pips"].to_numpy()),"ungated":hac_ci(allg["h2_short_pips"].to_numpy()),"gated_event_dates":[str(x) for x in gated["session"].to_list()],"scenario_cost_adjusted_gated_mean_pips":{str(c):float(gated["h2_short_pips"].mean()-c) if gated.height else None for c in [0.8,1.0,1.4]}}
    for arm,data in [("H1_prefx_event_diagnostic",result["H1"]),("H2_postfix_event_diagnostic",result["H2"])]:
        dest=OUT/arm
        dest.mkdir(exist_ok=True)
        (dest/"result.json").write_text(json.dumps({"provenance":{k:v for k,v in result.items() if k not in ["H1","H2"]},"result":data},indent=2)+"\n")
    print(json.dumps(result,indent=2))
if __name__=="__main__":
    main()
