"""Frozen Tokyo calendar event study. Event markouts are not simulated fills.

Calendar estimators use statsmodels because cross-sectional IC does not apply.
Polars expressions implement fixed markouts and the strictly past-only gate.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import inspect
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import polars as pl
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests
import yaml
from ml4t.engineer import compute_features, labeling
from ml4t.diagnostic import analyze_signal, Evaluator
from ml4t.backtest import Engine, Strategy
from ml4t.backtest.analytics.metrics import max_drawdown
from ml4t.backtest.analytics.trades import TradeAnalyzer

ROOT = Path(__file__).resolve().parents[1]
SID = "tokyo_alpha_map_program1_v1"
OUT = ROOT / "run_log/tokyo_fix_alpha_map_program1_20261010/execution_v1"
DEST = ROOT / "data/processed" / SID
STORE = Path("/home/quant/dev/quant/ml4t-data/.data/store/forex_minute_USDJPY")
CAL = ROOT / "run_log/tokyo_fix_alpha_map_program1_20261010/calendar_audit_v1/calendar_dates.csv"
SPEC = ROOT / f"config/research_sessions/{SID}.yaml"
# Minute-open endpoints, fixed signs. Do not select a minute from plotted curves.
WINDOWS = {
    "A_0300_0500": (180,300,1), "A_0500_0700": (300,420,1),
    "A_0700_0830": (420,510,1), "A_0830_0954": (510,594,1),
    "A_0956_1010": (596,610,1), "A_1010_1030": (610,630,1),
    "A_1030_1200": (630,720,1),
    "L_0300_0954": (180,594,1), "L_0500_0954": (300,594,1),
    "L_0700_0954": (420,594,1), "L_0830_0954": (510,594,1),
    "B_0956_1010": (596,610,-1), "B_0956_1030": (596,630,-1),
    "B_0956_1100": (596,660,-1),
    "D_main_0930_0954": (570,594,1), "D_placebo_1130_1154": (690,714,1),
    "D_main_short_0956_1000": (596,600,-1), "D_placebo_short_1156_1200": (716,720,-1),
}
GROUPS = ["gotobi", "ordinary", "rolled_gotobi", "month_end"]

def sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()

def write(path,payload):
    path=Path(path)
    if path.exists():raise RuntimeError(f"Immutable artifact already exists: {path}")
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(payload,indent=2,allow_nan=False,default=str)+"\n")

def calendar():
    f=pl.read_csv(CAL,try_parse_dates=True,schema_overrides={"nominal_dates":pl.String,"nominal_days":pl.String}).filter(pl.col("tokyo_bank_business_day"))
    f=f.rename({"date":"session","month_end_bank_business_day":"month_end", "quarter_end_bank_business_day":"quarter_end", "ordinary_bank_business_day":"ordinary", "negative_control_dom_2_7_12_17_22_27":"negative_control"}).with_columns(pl.col("session").dt.year().alias("year"))
    business=set(f["session"].to_list());negative=set()
    for year in range(2020,2027):
        for month in range(1,13):
            if (year,month)>(2026,8):continue
            for dom in [2,7,12,17,22,27]:
                d=date(year,month,dom)
                while d not in business and d>=date(2020,1,1):d-=timedelta(days=1)
                if d in business:negative.add(d)
    actual=set(f.filter(pl.col("gotobi"))["session"].to_list())
    return f.with_columns(pl.col("session").is_in(sorted(negative-actual)).alias("negative_control"))

def source_paths():
    # Parse partition identities before any Parquet read/hash. No September files.
    paths=[]
    for y in range(2020,2027):
        for p in (STORE/f"year={y}").glob("month=*/day=*/data.parquet"):
            d=date(y,int(p.parents[1].name.split("=")[1]),int(p.parent.name.split("=")[1]))
            if date(2020,1,1)<=d<date(2026,9,1):paths.append(p)
    return sorted(paths)

def prepare():
    if (DEST/"source_manifest.json").exists():raise RuntimeError("Snapshot already exists")
    cal=calendar()
    days=cal["session"].to_list()
    manifests=[];coverage=[];snapshots=[];gate_parts=[]
    paths=source_paths()
    assert paths and all("month=9" not in str(p) for p in paths if "year=2026" in str(p))
    for y in range(2020,2027):
        selected=[p for p in paths if f"year={y}/" in str(p)]
        manifest=[{"path":str(p),"sha256":sha(p),"size_bytes":p.stat().st_size} for p in selected]
        f=(pl.scan_parquet(selected,hive_partitioning=False)
           .filter(pl.col("timestamp")<pl.datetime(2026,8,31,15,time_zone="UTC"))
           .with_columns(pl.col("timestamp").dt.convert_time_zone("Asia/Tokyo").alias("jst"))
           .with_columns(pl.col("jst").dt.date().alias("session"),
              (pl.col("jst").dt.hour().cast(pl.Int32)*60+pl.col("jst").dt.minute()).alias("minute_jst"))
           .filter(pl.col("session").is_in(days)&pl.col("minute_jst").is_between(180,720))
           .select("timestamp","symbol","open","high","low","close","volume","session","minute_jst").sort("timestamp").collect())
        assert f["symbol"].unique().to_list()==["USDJPY"]
        bad=f.filter(pl.any_horizontal([~pl.col(c).is_finite()|pl.col(c).is_null()|(pl.col(c)<=0) for c in ["open","high","low","close"]])|(pl.col("high")<pl.col("low"))|~pl.col("open").is_between(pl.col("low"),pl.col("high"))|~pl.col("close").is_between(pl.col("low"),pl.col("high")))
        assert bad.height==0 and f["timestamp"].is_duplicated().sum()==0
        assert f.filter(pl.col("timestamp").dt.second()!=0).height==0
        # Retain all available rows in immutable bounded snapshot. Exclusion
        # evidence and original narrow-cohort gate need the incomplete full days.
        target=DEST/f"USDJPY_03_12_JST_{y}.parquet"
        f.drop("session","minute_jst").write_parquet(target,compression="zstd")
        assert f.height<1_000_000 and target.stat().st_size<100_000_000
        snapshots.append({"path":str(target.relative_to(ROOT)),"rows":f.height,"sha256":sha(target),"size_bytes":target.stat().st_size})
        manifests.extend(manifest)
        coverage.extend(f.group_by("session").agg(pl.len().alias("rows"),pl.col("minute_jst").n_unique().alias("distinct_minutes")).to_dicts())
        gate_parts.append(f.filter(pl.col("minute_jst").is_between(480,630)))
    counts=pl.DataFrame(coverage)
    registry=cal.join(counts,on="session",how="left").with_columns(pl.col("rows").fill_null(0),pl.col("distinct_minutes").fill_null(0)).with_columns(((pl.col("rows")==541)&(pl.col("distinct_minutes")==541)).alias("complete_full"))
    registry.write_parquet(OUT/"calendar_event_registry.parquet")
    registry.write_csv(OUT/"calendar_event_registry.csv")
    write(OUT/"gap_audit.json",{"expected":registry.height,"complete":registry.filter(pl.col("complete_full")).height,"excluded":registry.filter(~pl.col("complete_full")).to_dicts(),"no_forward_fill":True,"window_minutes":541,"calendar_sha256":sha(CAL),"selection_limitation":"Full-window complete-case exclusion may depend on provider outages; cohort comparison provided, no missing-price imputation."})
    write(DEST/"source_manifest.json",{"source":str(STORE),"source_files":manifests,"selected_source_partition_count":len(manifests),"snapshots":snapshots,"holdout_partition_read":False,"jst_end_exclusive":"2026-09-01","UTC_cutoff":"2026-08-31T15:00:00Z","timestamp_semantics":"minute BAR OPEN; inherited local source contract; executable bid/ask unavailable","provider_versions":{p:importlib.metadata.version(p) for p in ["ml4t-data","ml4t-engineer","ml4t-diagnostic","ml4t-backtest","polars","statsmodels"]}})
    write(OUT/"api_identity.json",{"compute_features":str(inspect.signature(compute_features)),"Engine":str(inspect.signature(Engine)),"TradeAnalyzer":str(inspect.signature(TradeAnalyzer)),"imports_verified":["labeling","analyze_signal","Evaluator","Strategy"],"event_method":"statsmodels OLS calendar associations; no cross-sectional IC or feature catalog equivalent"})
    print(json.dumps({"snapshots":snapshots,"complete":registry.filter(pl.col("complete_full")).height}))

def freeze():
    manifest=json.loads((DEST/"source_manifest.json").read_text())
    prior=yaml.safe_load((ROOT/"config/research_sessions/usdjpy_gotobi_2020_2026_usd10000_v1.yaml").read_text())
    tests=[]
    for w in WINDOWS:
        tests.extend([f"{w}:mean:{g}" for g in GROUPS]);tests.append(f"{w}:increment")
    for w in [x for x in WINDOWS if x.startswith("B_")]:
        tests.extend([f"{w}:gated_mean",f"{w}:gated_increment",f"{w}:original_gate_mean",f"{w}:original_gate_increment"])
    terms=["nominal_5","nominal_10","nominal_15","nominal_20","nominal_25","nominal_30","rolled_gotobi","month_end","quarter_end","weekday_4"]
    for w in ["L_0830_0954","B_0956_1030"]:tests.extend([f"C:{w}:{t}" for t in terms])
    for w in ["L_0830_0954","B_0956_1030"]:tests.append(f"D:negative:{w}")
    tests.extend(["D:matched_pre_difference","D:matched_post_difference"])
    prior.update({"session_id":SID,"thesis":"A-D retrospective Tokyo settlement-calendar associations in full 03-12 JST sessions; USD buying pressure before 09:55 may reverse afterward.","falsifier":"No positive global-Holm-significant Gotobi increment; nonpositive base cost lower bound; insufficient n/year support; unstable signs or placebo concern. Onset remains unresolved unless fixed interval increment passes Holm and HAC lag robustness.","data":[{"id":f"year_{i}","symbol":"USDJPY","role":"prices","path":x["path"]} for i,x in enumerate(manifest["snapshots"])],"evaluation":{"development_start":"2020-01-01T00:00:00Z","development_end":"2026-08-31T15:00:00Z","holdout_start":"2026-08-31T15:00:00Z","holdout_end":"2026-10-10T00:00:00Z","status":"Entire2020-Aug2026 already inspected: EXPLORATORY only; holdout JST>=September1 never read.","windows":{k:list(v) for k,v in WINDOWS.items()},"hac":{"maxlags":5,"kernel":"bartlett","use_correction":True,"use_t":True,"robustness_lags":[1,10]},"controls":["weekday","year"],"dag":"Calendar and weekday/year -> demand and returns; latent importer flow -> returns. No return, extension or volume controls. Calendar associations do not identify dealer flows.","calendar":"Official Cabinet Office holiday dates + BOJ bank closure rule; previous-bank-business-day rollback is an assumption. No nominal30 in February; month-end separate. Nominal collisions excluded only from C regression.","gates":"B3 original extension open0955-open0800 >1.5 sampleSD preceding20 complete0800-1030 bank dates; report original as sensitivity AND strict541-minute gate. Identically gated ordinary controls. Gate is potentially mediator-selected.","global_holm_test_ids":tests,"minimum":{"strategy_n":100,"controls_n":200,"years_with15events":5,"positive_net_years":5,"calendar_category_n":30,"calendar_category_years":4},"selection":"At most two: one pre and one post. Positive increment Holm p<.05 and CI lower>0, positive 1pip mean CI lower>0, positive1.4pip point mean; 2024-25 pooled net>=0; every leaveyearout increment and net positive; alternative HAC lag signs; placebo concern unresolved means NONE. Full-cohort coverage<80percent flags missingness generalization unresolved and rejects strategy selection. Tie earliest entry or earliest exit. Native Engine only after gates.","placebos":"Pre0930-0954 vs1130-1154; post0956-1000 vs1156-1200 matched4min diagnostic; main14/34/64min post horizons unavailable at11:55. Negative nominal2/7/12/17/22/27 rollback, exclude actualGotobi.","initial_equity_usd":10000,"position_base_usd":10000,"no_compounding":True},"baseline":"Same window ordinary Tokyo bank business days, weekday/year adjusted; gated ordinary for B3.","evidence":[str((DEST/"source_manifest.json").relative_to(ROOT)),str(CAL.relative_to(ROOT)),str((OUT/"calendar_event_registry.parquet").relative_to(ROOT))],"trials":[{"id":t,"kind":"diagnostic" if t=="T0_data_gate" else "preregistered","description":desc} for t,desc in [("T0_data_gate","Calendar, source hashes, gap audit and CLI check"),("T1_A_map","Fixed A intervals and accumulations; descriptive minute curves"),("T2_B_reversal","Three fixed horizons all groups and original/strict gates"),("T3_C_calendar","Two small calendar regressions; nominal collisions excluded"),("T4_D_refutation","Negative-calendar and matched-placebo contrasts; yearly and lag robustness"),("T5_candidate_screen","Apply frozen gates; conditional native Engine max2; NONE valid")]]})
    prior["instruments"][0]["session"]="Tokyo bank calendar on official public holidays + BOJ closure rule"
    if SPEC.exists():raise RuntimeError("Frozen YAML already exists")
    SPEC.write_text(yaml.safe_dump(prior,sort_keys=False))
    subprocess.run([sys.executable,str(ROOT/"scripts/research_session.py"),"init","--spec",str(SPEC.relative_to(ROOT)),"--root",str(ROOT)],check=True)
    write(OUT/"planned_tests.json",{"tests":tests,"count":len(tests),"known_legacy_count":"Incomplete; Holm applies only to this program; DSR/PBO not reproducible","cost_scenarios":[.8,1.,1.4],"pointwise_curves":"descriptive541minute x4groups; no per-minute inferential selection"})

def fit_hac(y,x=None,lag=5):
    y=np.asarray(y,dtype=float)
    if x is None:x=np.ones((len(y),1))
    x=np.asarray(x,dtype=float)
    if len(y)<=x.shape[1]+1 or np.linalg.matrix_rank(x)!=x.shape[1]:return None
    return sm.OLS(y,x).fit(cov_type="HAC",cov_kwds={"maxlags":min(lag,len(y)-1),"kernel":"bartlett","use_correction":True},use_t=True)

def coefficient(fit,index=0):
    if fit is None:return {"status":"INCONCLUSIVE","p":1.,"estimate":None,"ci95":None}
    return {"status":"ESTIMATED","estimate":float(fit.params[index]),"ci95":fit.conf_int()[index].tolist(),"p":float(fit.pvalues[index]),"df_resid":float(fit.df_resid)}

def controls(f, treatment):
    cols=[np.ones(f.height),np.asarray(treatment,dtype=float)]
    cols.extend((f["weekday"].to_numpy()==v).astype(float) for v in sorted(f["weekday"].unique())[1:])
    cols.extend((f["year"].to_numpy()==v).astype(float) for v in sorted(f["year"].unique())[1:])
    return np.column_stack(cols)

def increment(f,col,treatment="gotobi",lag=5):
    x=controls(f,f[treatment].cast(pl.Float64).to_numpy())
    out=coefficient(fit_hac(f[col].to_numpy(),x,lag),1)
    out.update(n=f.height,n_treatment=f.filter(pl.col(treatment)).height,n_control=f.filter(~pl.col(treatment)).height)
    return out

def summary(f,col):
    a=f[col].to_numpy()
    out=coefficient(fit_hac(a));out.update(n=len(a),median=float(np.median(a)) if len(a) else None,sd=float(np.std(a,ddof=1)) if len(a)>1 else None)
    scenarios={}
    for c in [0.,.8,1.,1.4]:
        net=a-c
        metric=TradeAnalyzer([SimpleNamespace(pnl=float(v),pnl_percent=0.,status="event_markout") for v in net])
        # An additive markout curve in pip units, not a capital-account backtest.
        anchor=1_000_000.;values=np.r_[anchor,anchor+np.cumsum(net)]
        dd,peak,_=max_drawdown(values)
        pf=metric.profit_factor
        scenarios[str(c)]={"mean_net_pips":float(np.mean(net)) if len(net) else None,"ci95_net_pips":[v-c for v in out["ci95"]] if out["ci95"] else None,"win_rate":metric.win_rate,"profit_factor":float(pf) if np.isfinite(pf) else None,"max_additive_markout_drawdown_pips":float(dd*values[peak]),"metrics_source":"ml4t.backtest.analytics.TradeAnalyzer,max_drawdown; event endpoints only, not fills or MTM"}
    out["cost_scenarios"]=scenarios
    out["years"]=[{"year":int(x["year"][0]),"n":x.height,"mean_pips":float(x[col].mean()),"net1_pips":float(x[col].mean()-1)} for x in f.partition_by("year",maintain_order=True)]
    return out


def run():
    config=yaml.safe_load(SPEC.read_text())
    frozen=json.loads((ROOT/f"run_log/research_sessions/{SID}/frozen_spec.json").read_text())
    assert frozen
    assert config == frozen["spec"], "Working declaration differs from frozen specification"
    config=frozen["spec"]
    assert {k:list(v) for k,v in WINDOWS.items()}==config["evaluation"]["windows"]
    assert sha(CAL)==json.loads((OUT/"gap_audit.json").read_text())["calendar_sha256"]
    if (OUT/"results.json").exists():raise RuntimeError("Results already exist")
    manifest=json.loads((DEST/"source_manifest.json").read_text())
    for x in manifest["snapshots"]:assert sha(ROOT/x["path"])==x["sha256"]
    reg=pl.read_parquet(OUT/"calendar_event_registry.parquet")
    f=(pl.scan_parquet([ROOT/x["path"] for x in manifest["snapshots"]])
       .with_columns(pl.col("timestamp").dt.convert_time_zone("Asia/Tokyo").alias("jst"))
       .with_columns(pl.col("jst").dt.date().alias("session"),(pl.col("jst").dt.hour().cast(pl.Int32)*60+pl.col("jst").dt.minute()).alias("minute_jst")).collect())
    points=sorted({m for a,b,_ in WINDOWS.values() for m in [a,b]}|{480,595})
    all_ev=f.group_by("session").agg([pl.col("open").filter(pl.col("minute_jst")==m).first().alias(f"p{m}") for m in points]+[pl.col("minute_jst").filter(pl.col("minute_jst").is_between(480,630)).n_unique().alias("narrow_minutes")]).sort("session")
    all_ev=all_ev.join(reg,on="session").sort("session").with_columns(((pl.col("p595")-pl.col("p480"))*100).alias("extension_pips"))
    original=all_ev.filter(pl.col("narrow_minutes")==151).with_columns(pl.col("extension_pips").rolling_std(20,min_samples=20).shift(1).alias("original_prior20_sd"))
    original=original.with_columns((pl.col("extension_pips")>1.5*pl.col("original_prior20_sd")).fill_null(False).alias("original_gate"))
    original.select("session","extension_pips","original_prior20_sd","original_gate").write_parquet(OUT/"original_gate_history.parquet")
    ev=all_ev.filter(pl.col("complete_full")).join(original.select("session","original_prior20_sd","original_gate"),on="session",how="left").sort("session")
    ev=ev.with_columns(pl.col("extension_pips").rolling_std(20,min_samples=20).shift(1).alias("prior20_sd"),*[((pl.col(f"p{b}")-pl.col(f"p{a}"))*100*sign).alias(w) for w,(a,b,sign) in WINDOWS.items()]).with_columns((pl.col("extension_pips")>1.5*pl.col("prior20_sd")).fill_null(False).alias("strict_gate"))
    assert ev["session"].max()<date(2026,9,1) and ev["session"].is_duplicated().sum()==0
    ev.write_parquet(OUT/"event_panel.parquet")
    results={"classification":"EXPLORATORY","approval":"NOT_APPROVED","n":ev.height,"windows":{},"tests":{},"calendar":{},"refutation":{},"candidates":[]}
    tests=results["tests"]
    def register(id_,payload):
        assert id_ in config["evaluation"]["global_holm_test_ids"] and id_ not in tests
        tests[id_]=payload
    for w in WINDOWS:
        r={"groups":{}}
        for g in GROUPS:
            r["groups"][g]=summary(ev.filter(pl.col(g)),w)
            register(f"{w}:mean:{g}",{k:v for k,v in r["groups"][g].items() if k in ["status","p","estimate","ci95","n","df_resid"]})
        r["increment"]=increment(ev,w);register(f"{w}:increment",dict(r["increment"]))
        r["increment_lag_robustness"]={str(l):increment(ev,w,lag=l) for l in [1,10]}
        r["yearly_increment"]=[{"year":y,"n":ev.filter(pl.col("year")==y).height,"adjusted_increment_pips":increment(ev.filter(pl.col("year")==y),w)["estimate"]} for y in range(2020,2027)]
        r["unadjusted_difference_pips"]=r["groups"]["gotobi"]["estimate"]-r["groups"]["ordinary"]["estimate"]
        if w.startswith("B_"):
            for name,gate in [("gated","strict_gate"),("original_gate","original_gate")]:
                e=ev.filter(pl.col(gate));g=e.filter(pl.col("gotobi"))
                r[name]={"summary":summary(g,w),"increment":increment(e,w)}
                register(f"{w}:{name}_mean",{k:v for k,v in r[name]["summary"].items() if k in ["status","p","estimate","ci95","n","df_resid"]})
                register(f"{w}:{name}_increment",dict(r[name]["increment"]))
        results["windows"][w]=r
    coverage=reg.group_by("year","weekday","gotobi").agg(pl.len().alias("expected"),pl.col("complete_full").sum().alias("complete")).sort("year","weekday","gotobi")
    coverage.write_csv(OUT/"coverage_by_calendar.csv")
    # Mutually exclusive nominal classes; collisions retained once in A/B.
    c=ev.filter(~pl.col("nominal_days").fill_null("").str.contains(";"))
    for w in ["L_0830_0954","B_0956_1030"]:
        weekdays=sorted(c["weekday"].unique().to_list())[1:]
        names=["constant"]+[f"nominal_{d}" for d in [5,10,15,20,25,30]]+["rolled_gotobi","month_end","quarter_end"]+[f"weekday_{d}" for d in weekdays]+[f"year_{y}" for y in range(2021,2027)]
        cols=[np.ones(c.height)]+[(c["nominal_days"].fill_null("").to_numpy()==str(d)).astype(float) for d in [5,10,15,20,25,30]]+[c[t].cast(pl.Float64).to_numpy() for t in ["rolled_gotobi","month_end","quarter_end"]]+[(c["weekday"].to_numpy()==d).astype(float) for d in weekdays]+[(c["year"].to_numpy()==y).astype(float) for y in range(2021,2027)]
        x=np.column_stack(cols);fit=fit_hac(c[w].to_numpy(),x)
        cr={"n":c.height,"excluded_collisions":ev.height-c.height,"rank":int(np.linalg.matrix_rank(x)),"columns":len(names),"coefficients":{}}
        for term in ["nominal_5","nominal_10","nominal_15","nominal_20","nominal_25","nominal_30","rolled_gotobi","month_end","quarter_end","weekday_4"]:
            t=coefficient(fit,names.index(term))
            subgroup=c.filter(pl.col("nominal_days")==term.split("_")[1]) if term.startswith("nominal_") else c.filter(pl.col("weekday")==4) if term=="weekday_4" else c.filter(pl.col(term))
            t.update(n=subgroup.height,years=subgroup["year"].n_unique(),descriptive=summary(subgroup,w))
            if t["n"]<30 or t["years"]<4:t["interpretation"]="SMALL_SUBSET_INCONCLUSIVE";t["status"]="INCONCLUSIVE";t["p"]=1.
            cr["coefficients"][term]=t;register(f"C:{w}:{term}",{k:v for k,v in t.items() if k!="descriptive"})
        results["calendar"][w]=cr
    n=ev.filter(~pl.col("gotobi"))
    for w in ["L_0830_0954","B_0956_1030"]:
        r=increment(n,w,"negative_control");r["summary"]=summary(n.filter(pl.col("negative_control")),w)
        results["refutation"][f"negative:{w}"]=r;register(f"D:negative:{w}",{k:v for k,v in r.items() if k!="summary"})
    for kind,main,placebo in [("pre","D_main_0930_0954","D_placebo_1130_1154"),("post","D_main_short_0956_1000","D_placebo_short_1156_1200")]:
        p=ev.with_columns((pl.col(main)-pl.col(placebo)).alias("paired"));r=increment(p,"paired")
        results["refutation"][f"matched_{kind}"]=r;register(f"D:matched_{kind}_difference",r)
    ids=config["evaluation"]["global_holm_test_ids"]
    assert set(ids)==set(tests)
    adjusted=multipletests([tests[t]["p"] for t in ids],alpha=.05,method="holm")[1]
    for id_,p in zip(ids,adjusted):tests[id_]["holm_p"]=float(p)
    # Selection records each fixed candidate. Never choose largest historical mean.
    screen=[]
    for w in [k for k in WINDOWS if k.startswith(("L_","B_"))]:
        r=results["windows"][w];g=ev.filter(pl.col("gotobi"));s=r["groups"]["gotobi"];inc=r["increment"]
        year_rows=s["years"]
        loyo=[{"omitted":y,"increment":increment(ev.filter(pl.col("year")!=y),w)["estimate"],"net1":float(g.filter(pl.col("year")!=y)[w].mean()-1)} for y in range(2020,2027)]
        fail=[]
        if ev.height/reg.height<.8:fail.append("missingness_generalization_unresolved")
        if g.height<100 or inc["n_control"]<200:fail.append("sample")
        if sum(x["n"]>=15 for x in year_rows)<5:fail.append("year_sample")
        if tests[f"{w}:increment"]["holm_p"]>=.05 or inc["ci95"] is None or inc["ci95"][0]<=0:fail.append("increment_uncertain")
        if s["ci95"] is None or s["ci95"][0]-1<=0:fail.append("base_net_uncertain")
        if s["estimate"]<=1.4:fail.append("stress_cost")
        if sum(x["net1_pips"]>0 for x in year_rows)<5:fail.append("year_signs")
        if g.filter(pl.col("year").is_in([2024,2025]))[w].mean()<1:fail.append("2024_25_net")
        if any(x["increment"] is None or x["increment"]<=0 or x["net1"]<=0 for x in loyo):fail.append("leave_year_out")
        if any(v["estimate"] is None or v["estimate"]<=0 for v in r["increment_lag_robustness"].values()):fail.append("hac_lag_sign")
        # A calendar premium cannot be called settlement-specific until direct
        # matched placebo comparison has positive lower bound and Holm support.
        placebo_test=tests["D:matched_pre_difference" if w.startswith("L_") else "D:matched_post_difference"]
        if placebo_test["holm_p"]>=.05 or placebo_test["ci95"] is None or placebo_test["ci95"][0]<=0:fail.append("placebo_specificity_unresolved")
        screen.append({"window":w,"failures":fail,"leave_year_out":loyo,"qualifies":not fail})
    # Original/strict gated B3 screened too, with identical controls and full gates.
    for w in [k for k in WINDOWS if k.startswith("B_")]:
        for gate in ["original_gate","strict_gate"]:
            e=ev.filter(pl.col(gate));g=e.filter(pl.col("gotobi"));s=summary(g,w);inc=increment(e,w)
            name="original_gate" if gate=="original_gate" else "gated"
            fail=[]
            if g.height<100 or inc["n_control"]<200:fail.append("sample")
            if sum(x["n"]>=15 for x in s["years"])<5:fail.append("year_sample")
            if tests[f"{w}:{name}_increment"]["holm_p"]>=.05 or inc["ci95"] is None or inc["ci95"][0]<=0:fail.append("increment_uncertain")
            if s["ci95"] is None or s["ci95"][0]-1<=0:fail.append("base_net_uncertain")
            if s["estimate"] is None or s["estimate"]<=1.4:fail.append("stress_cost")
            if sum(x["net1_pips"]>0 for x in s["years"])<5:fail.append("year_signs")
            deterior=g.filter(pl.col("year").is_in([2024,2025]))
            if deterior.is_empty() or deterior[w].mean()<1:fail.append("2024_25_net")
            # Screen cannot identify total-calendar effect for a mediator gate.
            fail.append("conditional_calendar_specificity_unresolved")
            screen.append({"window":f"{w}:{gate}","failures":fail,"qualifies":not fail})
    results["candidate_screen"]=screen
    passing=[x for x in screen if x["qualifies"]]
    if passing:
        raise RuntimeError("Qualifying candidates require native Engine stage; do not claim NONE")
    results["native_backtest"]={"status":"NOT_RUN_NO_QUALIFYING_CANDIDATES","count":0,"reason":"All fixed candidates failed frozen statistical/economic gates; no execution optimizer."}
    results["onset_intervals"]=[w for w in WINDOWS if w in ["A_0300_0500","A_0500_0700","A_0700_0830","A_0830_0954"] and results["windows"][w]["groups"]["gotobi"]["estimate"]>0 and tests[f"{w}:increment"]["holm_p"]<.05 and all(v["estimate"]>0 for v in results["windows"][w]["increment_lag_robustness"].values())]
    # Pointwise HAC bands across dates. No minute test belongs to selection.
    curves=[];minute_rows=f.join(ev.select("session","gotobi","ordinary","rolled_gotobi","month_end"),on="session",how="inner")
    anchor=minute_rows.filter(pl.col("minute_jst")==595).select("session",pl.col("open").alias("fix_open"))
    minute_rows=minute_rows.join(anchor,on="session").with_columns(((pl.col("open")-pl.col("fix_open"))*100).alias("centered_pips"))
    for group in GROUPS:
        data=minute_rows.filter(pl.col(group)).sort("session","minute_jst")
        for minute in range(180,721):
            v=data.filter(pl.col("minute_jst")==minute)["centered_pips"].to_numpy()
            stat=coefficient(fit_hac(v));curves.append({"group":group,"minute_jst":minute,"n":len(v),"mean":stat["estimate"],"lower":stat["ci95"][0],"upper":stat["ci95"][1]})
    curve=pl.DataFrame(curves);curve.write_parquet(OUT/"minute_curves.parquet")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,2,figsize=(14,8),sharex=True)
    for ax,group in zip(axes.flat,GROUPS):
        z=curve.filter(pl.col("group")==group);x=z["minute_jst"].to_numpy()/60
        ax.plot(x,z["mean"].to_numpy());ax.fill_between(x,z["lower"].to_numpy(),z["upper"].to_numpy(),alpha=.2);ax.axvline(595/60,color="red",ls="--",label="09:55 fix");ax.axhline(0,color="gray",lw=.5);ax.set_title(group);ax.set_ylabel("pips vs 09:55 open");ax.set_xlabel("JST hour");ax.legend()
    fig.suptitle("USDJPY Tokyo bank dates 2020-Aug2026; 95% pointwise HAC bands; exploratory")
    fig.tight_layout();fig.savefig(OUT/"minute_alpha_map.png",dpi=150);plt.close(fig)
    table=[]
    for window,row in results["windows"].items():
        for group,stat in row["groups"].items():
            table.append({"window":window,"group":group,"n":stat["n"],"gross_mean_pips":stat["estimate"],"median_pips":stat["median"],"sd_pips":stat["sd"],"gross_ci_low":stat["ci95"][0] if stat["ci95"] else None,"gross_ci_high":stat["ci95"][1] if stat["ci95"] else None,"net1_mean_pips":stat["cost_scenarios"]["1.0"]["mean_net_pips"],"net1_win_rate":stat["cost_scenarios"]["1.0"]["win_rate"],"net1_profit_factor":stat["cost_scenarios"]["1.0"]["profit_factor"],"adjusted_gotobi_increment":row["increment"]["estimate"],"increment_holm_p":tests[f"{window}:increment"]["holm_p"]})
    pl.DataFrame(table).write_csv(OUT/"window_table.csv")
    write(OUT/"results.json",results)
    ledger=[{"id":t,"status":"completed" if tests[t]["status"]=="ESTIMATED" else "inconclusive","p":tests[t]["p"],"holm_p":tests[t]["holm_p"],"result_file":"results.json"} for t in ids]
    ledger.extend([{"id":f"cost_{c}","status":"completed","meaning":"Deterministic translation, not independent significance test"} for c in [.8,1,1.4]])
    ledger.extend([{"id":"native_backtests","status":"not_qualified","count":0},{"id":"11:55_post14_34_64min","status":"unavailable","reason":"Endpoints outside frozen12:00 boundary"}])
    write(OUT/"trial_ledger.json",{"declared_holm_count":len(ids),"trials":ledger,"prior_trials":"Incomplete known history; DSR/PBO not asserted","timing":"Frozen init before outcomes; existing entire history already observed"})
    for tid in ["T0_data_gate","T1_A_map","T2_B_reversal","T3_C_calendar","T4_D_refutation","T5_candidate_screen"]:
        artifact=OUT/("gap_audit.json" if tid=="T0_data_gate" else "results.json")
        subprocess.run([sys.executable,str(ROOT/"scripts/research_session.py"),"record","--session",SID,"--trial",tid,"--status","completed","--artifact",str(artifact.relative_to(ROOT)),"--root",str(ROOT)],check=True,stdout=subprocess.DEVNULL)
    print(json.dumps({"n":ev.height,"gotobi":ev.filter(pl.col("gotobi")).height,"holm_tests":len(tests),"candidates":0,"onset_intervals":results["onset_intervals"]}))

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("stage",choices=["prepare","freeze","run"]);a=p.parse_args();globals()[a.stage]()
