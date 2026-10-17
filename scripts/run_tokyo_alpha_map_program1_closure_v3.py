"""Program 1 v3 close-out: coverage-corrected A-D event diagnostics.

This performs event inference only, never simulated fills. Native historical
execution and accounting remain the independently audited v2 Engine artifacts.
No September 2026 or later data are read.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import numpy as np
import polars as pl
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests

ROOT=Path(__file__).resolve().parents[1]
SID="tokyo_alpha_map_program1_closure_v3"
OUT=ROOT/"run_log"/SID
BASE=ROOT/"data/processed/tokyo_alpha_map_program1_v1"
SRC=[BASE/f"USDJPY_03_12_JST_{y}.parquet" for y in range(2020,2027)]
CAL=ROOT/"run_log/tokyo_fix_alpha_map_program1_20261010/execution_v1/calendar_event_registry.parquet"
HISTORY=ROOT/"run_log/tokyo_fix_alpha_map_program1_20261010/execution_v1/original_gate_history.parquet"
PREV=ROOT/"run_log/tokyo_alpha_map_program1_native_exploratory_v2"
WINDOWS={
"A_0300_0500":(180,300,1),"A_0500_0700":(300,420,1),
"A_0700_0830":(420,510,1),"A_0830_0954":(510,594,1),
"A_0956_1010":(596,610,1),"A_1010_1030":(610,630,1),
"A_1030_1200":(630,720,1),
"L_0300_0954":(180,594,1),"L_0500_0954":(300,594,1),
"L_0700_0954":(420,594,1),"L_0830_0954":(510,594,1),
"B_0956_1010":(596,610,-1),"B_0956_1030":(596,630,-1),
"B_0956_1100":(596,660,-1),
"D_main_0930_0954":(570,594,1),"D_placebo_1130_1154":(690,714,1),
"D_main_short_0956_1000":(596,600,-1),
"D_placebo_short_1156_1200":(716,720,-1),
}
B_NAMES=["B_0956_1010","B_0956_1030","B_0956_1100"]


def save(label,data):
    path=OUT/label/"result.json"
    if path.exists():raise RuntimeError(f"Refuse to overwrite frozen evidence {path}")
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,indent=2,allow_nan=False,default=str)+"\n")


def hac_mean(vals):
    v=np.asarray(vals,dtype=float)
    if len(v)<3:return {"n":len(v),"status":"INSUFFICIENT"}
    fit=sm.OLS(v,np.ones((len(v),1))).fit(
        cov_type="HAC",cov_kwds={"maxlags":min(5,len(v)-1)},use_t=True)
    return {"n":len(v),"mean_pips":float(fit.params[0]),
        "ci95_pips":list(map(float,fit.conf_int()[0])),
        "p_two_sided":float(fit.pvalues[0]),
        "positive_fraction":float((v>0).mean()),
        "median_pips":float(np.median(v)),
        "sd_pips":float(np.std(v,ddof=1))}


def controlled(df):
    if df.height<30 or df["gotobi"].n_unique()!=2:return {"status":"INSUFFICIENT"}
    x=[np.ones(df.height),df["gotobi"].cast(pl.Float64).to_numpy()]
    for v in [1,2,3,4]:x.append((df["weekday"]==v).cast(pl.Float64).to_numpy())
    for v in range(2021,2027):x.append((df["year"]==v).cast(pl.Float64).to_numpy())
    matrix=np.column_stack(x)
    if np.linalg.matrix_rank(matrix)<matrix.shape[1]:
        # Excluded levels can be unobserved in some narrow historical cohorts.
        keep=[0,1]+[i for i in range(2,matrix.shape[1]) if matrix[:,i].sum()>0]
        matrix=matrix[:,keep]
    fit=sm.OLS(df["return_pips"].to_numpy(),matrix).fit(
        cov_type="HAC",cov_kwds={"maxlags":5},use_t=True)
    return {"n":df.height,"gotobi_increment_pips":float(fit.params[1]),
        "ci95_pips":list(map(float,fit.conf_int()[1])),
        "p_unadjusted":float(fit.pvalues[1]),"controls":"weekday and year fixed effects",
        "rank":int(np.linalg.matrix_rank(matrix))}


def byyear(df,field="return_pips"):
    out=[]
    for x in df.partition_by("year",maintain_order=True):
        if not x.height:continue
        out.append({"year":int(x["year"][0]),"n":x.height,
            "mean_gross_pips":float(x[field].mean()),
            "mean_net_at_1pip":float(x[field].mean()-1)})
    return out


def window(prices,registry,name,a,b,sign):
    f=prices.filter(pl.col("minute").is_between(a,b))
    grouped=(f.group_by("session").agg(
        pl.len().alias("count"),
        pl.col("minute").n_unique().alias("unique"),
        pl.col("open").filter(pl.col("minute")==a).first().alias("first"),
        pl.col("open").filter(pl.col("minute")==b).first().alias("last")))
    all_days=registry.join(grouped,on="session",how="left").with_columns(
        pl.col("count").fill_null(0),pl.col("unique").fill_null(0))
    good=all_days.filter((pl.col("count")==b-a+1)&(pl.col("unique")==b-a+1))
    valid=good.with_columns(((pl.col("last")-pl.col("first"))*100*sign).alias("return_pips"))
    assert valid["session"].max().year<=2026
    return valid,{"name":name,"start_jst":a,"end_jst":b,
        "expected_bars":b-a+1,"eligible":valid.height,"expected_days":registry.height,
        "coverage":valid.height/registry.height,
        "gotobi":int(valid["gotobi"].sum()),"ordinary":int(valid["ordinary"].sum()),
        "eligible_2026":valid.filter(pl.col("year")==2026).height,
        "last_eligible":str(valid["session"].max()),
        "excluded_by_year":all_days.filter(~((pl.col("count")==b-a+1)&(pl.col("unique")==b-a+1))).group_by("year").agg(pl.len().alias("n")).sort("year").to_dicts(),
        "excluded_by_weekday":all_days.filter(~((pl.col("count")==b-a+1)&(pl.col("unique")==b-a+1))).group_by("weekday").agg(pl.len().alias("n")).sort("weekday").to_dicts(),
        "missing_dates":[str(x) for x in all_days.filter(~((pl.col("count")==b-a+1)&(pl.col("unique")==b-a+1)))["session"].to_list()],
    }


def main():
    if (OUT/"T1_window_coverage/result.json").exists():
        raise RuntimeError("Completed once already. Bump version to rerun")
    registry=pl.read_parquet(CAL).select(
        "session","gotobi","ordinary","rolled_gotobi","month_end","quarter_end",
        "weekday","year","nominal_days","negative_control","complete_full"
    ).sort("session")
    prices=(pl.scan_parquet([str(p) for p in SRC])
       .with_columns(pl.col("timestamp").dt.convert_time_zone("Asia/Tokyo").alias("jst"))
       .with_columns(pl.col("jst").dt.date().alias("session"),
          (pl.col("jst").dt.hour().cast(pl.Int32)*60+
           pl.col("jst").dt.minute().cast(pl.Int32)).alias("minute"))
       .filter(pl.col("session").is_in(registry["session"].to_list()))
       .select("session","minute","timestamp","open")
       .sort("timestamp")
       .collect())
    if prices["timestamp"].is_duplicated().sum():raise RuntimeError("Duplicate UTC data")
    if prices["session"].max().year>2026 or prices["session"].max().month>8 and prices["session"].max().year==2026:
        raise RuntimeError("Holdout detected")
    if not all(p.exists() for p in SRC):raise RuntimeError("Missing canonical snapshot")
    original=pl.read_parquet(HISTORY).select("session","original_gate")
    allframes={};coverage=[];test_ids=[];test_ps=[]
    alpha={};post={};calendar={}
    for name,(a,b,sgn) in WINDOWS.items():
        df,quality=window(prices,registry,name,a,b,sgn)
        allframes[name]=df
        coverage.append(quality)
        g=df.filter(pl.col("gotobi"))
        ord_=df.filter(pl.col("ordinary"))
        estimate=controlled(df)
        if "p_unadjusted" in estimate:
            test_ids.append(name)
            test_ps.append(estimate["p_unadjusted"])
        profile={
            "cohort":quality["eligible"],"gotobi":hac_mean(g["return_pips"].to_numpy()),
            "ordinary":hac_mean(ord_["return_pips"].to_numpy()),
            "controlled_gotobi_premium":estimate,
            "gotobi_byyear":byyear(g),
            "cost_sensitivity_gotobi_net_mean_pips":{
                str(cost):float(g["return_pips"].mean()-cost) for cost in [.8,1.,1.4]
            } if g.height else {},
        }
        if name.startswith(("A_","L_")):alpha[name]=profile
        if name.startswith("B_"):
            groups={"B0_ordinary":ord_,"B1_gotobi":g,
              "B2_month_end":df.filter(pl.col("month_end")),
              "B3_original_gate_gotobi":df.join(original,on="session",how="left").filter(
                  pl.col("gotobi")&pl.col("original_gate").fill_null(False))}
            profiles={}
            for k,v in groups.items():
                z=hac_mean(v["return_pips"].to_numpy())
                profiles[k]={"sample":z,
                    "costed_net_mean_pips":float(v["return_pips"].mean()-1) if v.height else None,
                    "byyear":byyear(v)}
                if k=="B3_original_gate_gotobi":profiles[k]["selection_warning"]="Gate conditions on pre-fix price extension; not a total calendar-effect estimate"
            post[name]={**profile,"groups":profiles}
    # Calendar C regression, distinct nominal categories with monthend+rolled controls.
    for n in ["A_0830_0954","B_0956_1030"]:
        df=allframes[n]
        cols={"gotobi":df["gotobi"].cast(pl.Int8).to_numpy(),
          "rolled":df["rolled_gotobi"].cast(pl.Int8).to_numpy(),
          "month_end":df["month_end"].cast(pl.Int8).to_numpy(),
          "quarter_end":df["quarter_end"].cast(pl.Int8).to_numpy(),
          "friday":(df["weekday"]==4).cast(pl.Int8).to_numpy()}
        for d in [5,10,15,20,25,30]:
            cols[f"nominal_{d}"]=df["nominal_days"].str.contains(str(d)).fill_null(False).cast(pl.Int8).to_numpy()
        # Category statistics, without claiming overlapping categories independent.
        sub={}
        for k,mask in cols.items():
            vals=df["return_pips"].to_numpy()[mask.astype(bool)]
            sub[k]={"n":len(vals),"description":"overlapping calendar categories" if k in ["rolled","month_end","quarter_end"] else "category",
                "summary":hac_mean(vals),"eligible_min30":len(vals)>=30}
        # Parsimonious jointly adjusted model; nominal dummies overlap gotobi
        # so omit gotobi main indicator. Use weekday/year controls.
        keys=[k for k in cols if k!="gotobi"]
        X=[np.ones(df.height)]
        X += [cols[k] for k in keys]
        X += [(df["weekday"]==v).cast(pl.Int8).to_numpy() for v in [1,2,3]]
        X += [(df["year"]==y).cast(pl.Int8).to_numpy() for y in range(2021,2027)]
        mat=np.column_stack(X)
        selected=list(range(len(X)))
        # Exclude linearly dependent columns using rank-increase.
        independent=[];rank=0
        for idx in selected:
            pick=independent+[idx]
            newrank=np.linalg.matrix_rank(mat[:,pick])
            if newrank>rank:independent=pick;rank=newrank
        model=sm.OLS(df["return_pips"].to_numpy(),mat[:,independent]).fit(
            cov_type="HAC",cov_kwds={"maxlags":5},use_t=True)
        coefficients={}
        for idx in independent:
            if 1<=idx<=len(keys):
                k=keys[idx-1]
                coefficients[k]={"estimate":float(model.params[independent.index(idx)]),
                    "p":float(model.pvalues[independent.index(idx)]),
                    "ci95":list(map(float,model.conf_int()[independent.index(idx)]))}
        calendar[n]={"groups":sub,"regression":{
            "regressors":keys,
            "estimable_coefficients":coefficients,
            "rank":rank,"n":df.height,
            "warning":"Nominal date and rolled/month-end groups overlap; individual coefficients are conditional, not causal."
        }}
    # Placebo and negative control on their own complete-window cohorts.
    placebo={}
    for key,m,p in [("prefx","D_main_0930_0954","D_placebo_1130_1154"),
                    ("short","D_main_short_0956_1000","D_placebo_short_1156_1200")]:
        a=allframes[m].select("session",pl.col("return_pips").alias("main"))
        b=allframes[p].select("session",pl.col("return_pips").alias("placebo"))
        match=registry.join(a,on="session").join(b,on="session")
        both=match.with_columns((pl.col("main")-pl.col("placebo")).alias("return_pips"))
        placebo[key]={"matched_dates":both.height,
            "controlled_difference":controlled(both),
            "gotobi_diff":hac_mean(both.filter(pl.col("gotobi"))["return_pips"].to_numpy()),
            "ordinary_diff":hac_mean(both.filter(pl.col("ordinary"))["return_pips"].to_numpy())}
    neg={}
    for name in ["A_0830_0954","B_0956_1010"]:
        f=allframes[name].with_columns(pl.col("negative_control").alias("test_flag"))
        size=f.filter(pl.col("test_flag")).height
        neg[name]={"n_negative_control":size,
          "negative_control_mean":hac_mean(f.filter(pl.col("test_flag"))["return_pips"].to_numpy()),
          "gotobi_mean":hac_mean(f.filter(pl.col("gotobi"))["return_pips"].to_numpy())}
    adjusted=multipletests(test_ps,method="holm")[1]
    family={k:{"p_raw":float(p),"p_holm18":float(adj)} for k,p,adj in zip(test_ids,test_ps,adjusted)}
    # When full-window outcome differs from the native expansion, show both,
    # do not promote the retrospective unadjusted p-value as confirmation.
    native={}
    for key in ["T1_gotobi_short","T2_ordinary_short","T3_gotobi_long_reference"]:
        native[key]=json.loads((PREV/key/"result.json").read_text())
        native[key]={k:v for k,v in native[key].items() if k in
          ["trades","net_pnl_usd","end_equity_usd","net_mean_pips","profit_factor","daily_closed_sharpe_with_bank_day_flats"]}
    oracle=json.loads((PREV/"T4_independent_oracle/result.json").read_text())
    if oracle["status"]!="PASS" or oracle["fills_checked"]!=4118:raise RuntimeError("Previous native verification failed")
    save("T1_window_coverage",{
      "cohort_definition":"Each event has every minute from entry through exit; different windows have different denominators. No forward fills.",
      "full_window_prior_complete":999,"expected_bank_days":registry.height,
      "source_identity":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in SRC},
      "calendar_identity":hashlib.sha256(CAL.read_bytes()).hexdigest(),
      "windows":coverage,"new_price_source":False,"holdout_read":False})
    save("T2_alpha_windows",{"results":alpha})
    save("T3_postfix",{"results":post})
    save("T4_calendar",calendar)
    save("T5_refutation",{"placebo":placebo,"negative_dates":neg,
          "increment_test_family_18":family,
          "past_testing":"Previous Program 1 used 126 declared tests, historical outcomes already explored. This v3 Holm18 cannot erase earlier trial selection.",
          "long_14_34_64min_post_1155_placebo":"NOT_AVAILABLE_IN_FROZEN_03_12_SOURCE; no fabricated endpoints"})
    save("T6_reconciliation",{
       "previous_native_engine":"tokyo_alpha_map_program1_native_exploratory_v2",
       "starting_usd_equity":10000,"fixed_usd_position_notional":10000,
       "previous_native_results":native,
       "independent_fill_oracle_status":"PASS",
       "fill_count":oracle["fills_checked"],
       "conclusion":"EXPLORATORY_NOT_APPROVED",
       "candidate_selection":"No new strategy passes previous Program 1 frozen evidence gates. v2 native executions are implementation demonstrations only."})
    # Export machine-readable decision matrix, no changes to older frozen data.
    print(json.dumps({
       "window_coverage":{v["name"]:{"n":v["eligible"],"pct":round(v["coverage"]*100,1),"gotobi":v["gotobi"],"end":v["last_eligible"]} for v in coverage},
       "B_0956_1010":post["B_0956_1010"]["groups"],
       "holm":family,
       "oracle_fills":oracle["fills_checked"],
    },indent=2))
if __name__=="__main__":main()
