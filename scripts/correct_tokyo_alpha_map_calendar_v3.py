"""Correct v3 calendar nominal-day classification; immutable erratum.

Original closure v3 T4 used substring matching for nominal 5 and 15/25.
This independent correction uses exact semicolon token matching.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import polars as pl
import statsmodels.api as sm
from scripts.run_tokyo_alpha_map_program1_closure_v3 import ROOT, BASE, CAL, window

OUT=ROOT/"run_log/tokyo_alpha_map_program1_closure_v3/T4_calendar/nominal_exact_token_erratum.json"

def exact_nominal(series:pl.Series,day:int)->np.ndarray:
    # REGEX matches a full semicolon-separated token; never substring 5 in 15.
    return series.fill_null("").str.contains(rf"(^|;){day}($|;)").to_numpy().astype(int)

def main():
    if OUT.exists():raise RuntimeError("Erratum exists; do not overwrite")
    registry=pl.read_parquet(CAL).select("session","gotobi","ordinary",
        "rolled_gotobi","month_end","quarter_end","weekday","year",
        "nominal_days","negative_control","complete_full").sort("session")
    prices=(pl.scan_parquet([str(BASE/f"USDJPY_03_12_JST_{y}.parquet") for y in range(2020,2027)])
      .with_columns(pl.col("timestamp").dt.convert_time_zone("Asia/Tokyo").alias("jst"))
      .with_columns(pl.col("jst").dt.date().alias("session"),
          (pl.col("jst").dt.hour().cast(pl.Int32)*60+
           pl.col("jst").dt.minute().cast(pl.Int32)).alias("minute"))
      .select("session","minute","timestamp","open").sort("timestamp").collect())
    # Regression design: mutually exclusive nominal days except rare double-roll event,
    # plus separate overlapping calendar indicators, weekday and year effects.
    corrected={}
    for key,start,end,side in [("A_0830_0954",510,594,1),("B_0956_1030",596,630,-1)]:
        df,_=window(prices,registry,key,start,end,side)
        categories={f"nominal_{d}":exact_nominal(df["nominal_days"],d)
                    for d in [5,10,15,20,25,30]}
        for name,flag in [("rolled","rolled_gotobi"),
                          ("month_end","month_end"),("quarter_end","quarter_end")]:
            categories[name]=df[flag].cast(pl.Int8).to_numpy()
        categories["friday"]=(df["weekday"]==4).cast(pl.Int8).to_numpy()
        keys=list(categories)
        features=[np.ones(df.height)]+[categories[k] for k in keys]
        features += [(df["weekday"]==d).cast(pl.Int8).to_numpy() for d in [1,2,3]]
        features += [(df["year"]==y).cast(pl.Int8).to_numpy() for y in range(2021,2027)]
        design=np.column_stack(features)
        inds=[];rank=0
        for i in range(design.shape[1]):
            val=np.linalg.matrix_rank(design[:,inds+[i]])
            if val>rank:inds.append(i);rank=val
        model=sm.OLS(df["return_pips"].to_numpy(),design[:,inds]).fit(
            cov_type="HAC",cov_kwds={"maxlags":5},use_t=True)
        coeff={}
        for k in keys:
            index=keys.index(k)+1
            if index not in inds:continue
            j=inds.index(index)
            coeff[k]={"n_label":int(categories[k].sum()),
                "estimate_pips":float(model.params[j]),
                "p_unadjusted":float(model.pvalues[j]),
                "ci95_pips":[float(v) for v in model.conf_int()[j]]}
        corrected[key]={"n":int(df.height),"rank":int(rank),"coefficients":coeff}
    # Independent invariant: five must not include 15th/25th; collision contains both.
    checks={}
    for value,want in [("5",1),("15",0),("25",0),("30;5",1),("10",0),("",0)]:
        got=int(exact_nominal(pl.Series("nominal_days",[value]),5)[0])
        assert got==want,(value,got,want)
        checks[value]=got
    OUT.write_text(json.dumps({
        "status":"CALENDAR_ERRATUM_VERIFIED",
        "invalid_original":"T4_calendar/result.json nominal_5 matched 15 and 25 using substring, its nominal-category groups and regression are invalid",
        "corrected_method":"Semicolon-delimited exact nominal token, with overlapping category caveats",
        "regressions":corrected,"label_unit_tests":checks,
        "not_confirmatory":"Retrospective research; original previous v3 T4 remains unmodified",
    },indent=2)+"\n")
    print(json.dumps({"checks":checks,"by_regression":corrected},indent=2))
if __name__=="__main__":main()
