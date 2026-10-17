"""Frozen Program 2 event inference. No custom trading simulation or fills."""
from __future__ import annotations
import json
import hashlib
import io
from pathlib import Path
import numpy as np
import polars as pl
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LinearRegression
from ml4t.engineer import compute_features, labeling
from ml4t.diagnostic import analyze_signal, Evaluator
from ml4t.diagnostic.splitters.base import BaseSplitter
try:
    from materialize_tokyo_fix_program2_cross_currency_20261011_v1 import ROOT, SID, OUT, DATA, MAJORS, CROSSES, BOUND, sha
except ModuleNotFoundError:
    from scripts.materialize_tokyo_fix_program2_cross_currency_20261011_v1 import ROOT, SID, OUT, DATA, MAJORS, CROSSES, BOUND, sha
import yaml

CAL = ROOT/"run_log/tokyo_fix_alpha_map_program1_20261010/execution_v1/calendar_event_registry.parquet"

def save(name, obj):
    path=OUT/name
    encoded=json.dumps(obj,indent=2,default=str,allow_nan=False)+"\n"
    if path.exists():
        def equivalent(a,b):
            if isinstance(a,dict) and isinstance(b,dict):return a.keys()==b.keys() and all(equivalent(a[k],b[k]) for k in a)
            if isinstance(a,list) and isinstance(b,list):return len(a)==len(b) and all(equivalent(x,y) for x,y in zip(a,b))
            if isinstance(a,(float,int)) and isinstance(b,(float,int)):return bool(np.isclose(a,b,rtol=1e-10,atol=1e-10))
            return a==b
        if not equivalent(json.loads(path.read_text()),json.loads(encoded)):
            (OUT/(name.split('/')[0]+"_resume_difference.json")).write_text(encoded)
            raise RuntimeError(f"Immutable evidence differs: {path}")
        return
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(encoded)

def write_frame(df,path,kind="parquet"):
    """Resume only when serialization equals existing immutable bytes."""
    buffer=io.BytesIO()
    if kind=="parquet":df.write_parquet(buffer,compression="zstd")
    else:df.write_csv(buffer)
    payload=buffer.getvalue()
    if path.exists():
        if path.read_bytes()!=payload:
            old=pl.read_parquet(path) if kind=="parquet" else pl.read_csv(path,try_parse_dates=True)
            if not old.sort(old.columns).equals(df.sort(df.columns)):raise RuntimeError(f"Frozen frame differs: {path}")
    else:path.write_bytes(payload)

def admissible(df):
    """All OHLC valid and finite. Five consecutive unchanged closes are stale."""
    good=pl.all_horizontal([pl.col(c).is_finite() & (pl.col(c)>0) for c in ["open","high","low","close"]])
    good=good & (pl.col("low")<=pl.min_horizontal("open","close")) & (pl.col("high")>=pl.max_horizontal("open","close"))
    return df.with_columns(good.alias("geometry_ok")).with_columns(
        ((pl.col("close")==pl.col("close").shift(1)).cast(pl.Int8).rolling_sum(5).over("session")>=5).fill_null(False).alias("stale"))

def features(grid, horizons):
    """Registry returns on a dense null grid; gap mask prevents row-shift bias."""
    f=compute_features(grid,[{"name":"multi_horizon_returns","params":{"horizons":horizons,"log_returns":True}}],group_col="session",timestamp_col="timestamp",assume_sorted=True)
    return f.with_columns([pl.when(pl.col("close").is_not_null().cast(pl.Int32).rolling_sum(h+1).over("session")==h+1)
        .then(pl.col(f"multi_horizon_returns_log_ret_{h}m")).otherwise(None).alias(f"f{h}") for h in horizons])

class AnnualExpanding(BaseSplitter):
    """Exact calendar-year folds; all same-day labels stay on one side."""
    def __init__(self, years):
        self.years=np.asarray(years)
    def split(self, X, y=None, groups=None):
        for year in [2024,2025,2026]:
            train=np.flatnonzero(self.years<year); test=np.flatnonzero(self.years==year)
            if len(train)>=100 and len(test)>=20:
                yield train,test
    def get_n_splits(self,X=None,y=None,groups=None):
        return sum(1 for _ in self.split(X))

def estimate(y, x, index=1, clusters=None):
    if len(y)<30 or np.std(y)==0:
        return {"n":len(y),"status":"INSUFFICIENT","p":1.0}
    fit=sm.OLS(y,x).fit(cov_type="HAC",cov_kwds={"maxlags":min(5,len(y)-1)},use_t=True)
    out={"n":len(y),"coef":float(fit.params[index]),"ci95":list(map(float,fit.conf_int()[index])),"p":float(fit.pvalues[index])}
    if clusters is not None and len(np.unique(clusters))>=20:
        c=sm.OLS(y,x).fit(cov_type="cluster",cov_kwds={"groups":clusters},use_t=True)
        out["month_cluster_ci95"]=list(map(float,c.conf_int()[index]))
    return out

def mean_hac(values):
    vals=np.asarray(values,dtype=float)
    return estimate(vals,np.ones((len(vals),1)),0)

def controls(df):
    cols=[np.ones(df.height)]
    cols += [(df["weekday"].to_numpy()==v).astype(float) for v in range(1,5)]
    cols += [(df["year"].to_numpy()==v).astype(float) for v in range(2021,2027)]
    return cols

def fx_exposures(legs, quotes):
    """Independent economic oracle, not a broker or simulator."""
    usd={"USD":1.,"JPY":1/quotes["USDJPY"],"EUR":quotes["EURUSD"],"GBP":quotes["GBPUSD"],"AUD":quotes["AUDUSD"]}
    units={c:0. for c in usd};gross=0.
    for pair,q in legs.items():
        base,quote=pair[:3],pair[3:]
        units[base]+=q; units[quote]-=q*quotes[pair]
        gross+=abs(q)*usd[base]
    return {"units":units,"usd_values":{c:v*usd[c] for c,v in units.items()},"gross_usd":gross}

def main():
    spec=yaml.safe_load((ROOT/f"config/research_sessions/{SID}.yaml").read_text())
    ev=spec["evaluation"]; horizons=ev["horizons_minutes"]; anchors=ev["anchors_minutes"]
    frozen=ROOT/f"run_log/research_sessions/{SID}/frozen_spec.json"
    # The CLI's create-once freeze must precede every outcome calculation.
    if not frozen.exists():
        raise RuntimeError("Session not frozen")
    if (OUT/"analysis_complete.json").exists():
        raise RuntimeError("Version already completed")
    registry=pl.read_parquet(CAL).select("session","gotobi","ordinary","weekday","year").sort("session")
    assert registry["session"].max().isoformat()<"2026-09-01"
    quality=[]; raw={};clean={}
    for pair in MAJORS+CROSSES:
        frames=[]
        for path in sorted(DATA.glob(f"{pair}_*.parquet")):
            d=pl.read_parquet(path)
            assert d["timestamp"].max()<BOUND
            assert d["symbol"].unique().to_list()==[pair]
            d=admissible(d)
            duplicates=d["timestamp"].is_duplicated().sum()
            if duplicates:
                raise RuntimeError("Duplicate source minutes")
            daily=d.group_by("session").agg(pl.len().alias("observed"),pl.col("geometry_ok").sum().alias("valid_ohlc"),pl.col("stale").sum().alias("stale"))
            all_days=registry.filter(pl.col("year")==int(path.stem[-4:])).join(daily,on="session",how="left").with_columns(pl.col("observed").fill_null(0))
            write_frame(all_days.with_columns((601-pl.col("observed")).alias("missing_minutes")).sort("session"),OUT/f"coverage_{path.stem}_sorted.csv","csv")
            quality.append({"pair":pair,"year":int(path.stem[-4:]),"rows":d.height,"duplicates":int(duplicates),"invalid_ohlc":int((~d["geometry_ok"]).sum()),"stale_5":int(d["stale"].sum()),"bank_days":all_days.height,"full_days":all_days.filter(pl.col("observed")==601).height,"empty_days":all_days.filter(pl.col("observed")==0).height,"weekend_rows":d.filter(pl.col("session").dt.weekday()>5).height,"zero_volume":d.filter(pl.col("volume")==0).height,"last":str(d["timestamp"].max())})
            frames.append(d)
        raw[pair]=pl.concat(frames).sort("timestamp")
        clean[pair]=raw[pair].filter(pl.col("geometry_ok") & ~pl.col("stale")).select("timestamp","open","high","low","close","volume")
    save("T1_quality/result.json",{"quality":quality,"no_fill":True,"source_manifest_sha256":sha(OUT/"source_manifest.json"),"gate":"Exact minute presence, valid OHLC and no five-minute close staleness, independently per test"})
    grid=(registry.join(pl.DataFrame({"minute":range(180,781)}),how="cross").with_columns(
        (pl.col("session").cast(pl.Datetime("us")).dt.replace_time_zone("Asia/Tokyo")+pl.duration(minutes=pl.col("minute"))).dt.convert_time_zone("UTC").alias("timestamp")).sort("timestamp"))
    wide=grid.select("timestamp","session","minute","gotobi","ordinary","weekday","year")
    for pair in MAJORS:
        wide=wide.join(clean[pair].select("timestamp",pl.col("open").alias(pair),pl.col("close").alias(f"{pair}_close")),on="timestamp",how="left")
    # Immutable observed-only simultaneous panel, partitioned to bounded annual files.
    simultaneous=wide.drop_nulls(MAJORS+[f"{p}_close" for p in MAJORS])
    for year in range(2020,2027):
        write_frame(simultaneous.filter(pl.col("year")==year),DATA/f"synchronized_{year}.parquet")
    feat=grid
    for pair in MAJORS:
        p=grid.join(clean[pair],on="timestamp",how="left")
        f=features(p,horizons)
        feat=feat.join(f.select("timestamp",*[pl.col(f"f{h}").alias(f"{pair}_f{h}") for h in horizons]),on="timestamp")
    feat=feat.with_columns([(-pl.mean_horizontal([pl.col(f"{p}_f{h}") for p in MAJORS[1:]],ignore_nulls=False)).alias(f"USDfactor_f{h}") for h in horizons])
    # Features at anchor-2 minute close are available at anchor-1, strictly earlier.
    events=feat.filter(pl.col("minute").is_in([a-2 for a in anchors])).with_columns((pl.col("minute")+2).alias("anchor"),(pl.col("timestamp")+pl.duration(minutes=1)).alias("feature_available"),(pl.col("timestamp")+pl.duration(minutes=2)).alias("decision"))
    assert events.select((pl.col("feature_available")<pl.col("decision")).all()).item()
    write_frame(events,DATA/"decision_features.parquet")
    profiles=[];flow_events=[]
    for pair in MAJORS:
        for a,b in ev["flow_windows"]:
            sub=wide.filter(pl.col("minute").is_between(a,b)).group_by("session").agg(pl.col(pair).count().alias("count"),pl.col(pair).filter(pl.col("minute")==a).first().alias("entry"),pl.col(pair).filter(pl.col("minute")==b).first().alias("exit"))
            d=registry.join(sub,on="session").filter(pl.col("count")==b-a+1).with_columns(((pl.col("exit")/pl.col("entry")).log()*10000).alias("return_bps")).sort("session")
            x=np.column_stack([controls(d)[0],d["gotobi"].cast(pl.Float64).to_numpy(),*controls(d)[1:]])
            fit=estimate(d["return_bps"].to_numpy(),x,clusters=np.array([str(s)[:7] for s in d["session"]]))
            profiles.append({"id":f"{pair}_{a}_{b}","pair":pair,"start":a,"end":b,"gotobi":mean_hac(d.filter(pl.col("gotobi"))["return_bps"].to_numpy()),"ordinary":mean_hac(d.filter(pl.col("ordinary"))["return_bps"].to_numpy()),"increment":fit,"yearly":d.group_by("year","gotobi").agg(pl.len().alias("n"),pl.col("return_bps").mean()).sort("year","gotobi").to_dicts()})
            flow_events.append(d.with_columns(pl.lit(pair).alias("pair"),pl.lit(a).alias("start"),pl.lit(b).alias("end")))
    # Fixed weights avoid fitting contemporaneous USD factor loadings.
    for r,p in zip(profiles,multipletests([r["increment"]["p"] for r in profiles],method="holm")[1]):
        r["increment"]["p_holm_flow16"]=float(p)
    write_frame(pl.concat(flow_events,how="diagonal_relaxed"),OUT/"flow_events.parquet")
    save("T2_flow/result.json",{"profiles":profiles,"mechanism":"HYPOTHESIS: settlement USD demand and subsequent inventory unwind; calendar does not observe actual flows","causal_dag":"weekday/year -> calendar proxy and returns; global news -> all pair returns; settlement -> USD/JPY flow -> returns. Adjust weekday/year only. Concurrent cross returns are descriptive, not causal controls."})
    triangle=(raw["EURJPY"].filter(pl.col("geometry_ok")&~pl.col("stale")).select("timestamp",pl.col("close").alias("direct"))
        .join(wide.select("timestamp","USDJPY_close","EURUSD_close"),on="timestamp").drop_nulls()
        .with_columns(((pl.col("direct")/(pl.col("USDJPY_close")*pl.col("EURUSD_close"))).log()*10000).alias("error_bps")))
    write_frame(triangle,OUT/"triangle_identity.parquet")
    save("T3_decomposition/result.json",{"status":"PARTIAL_UNIDENTIFIED","USDfactor":"negative equal-weight mean closed log returns of EURUSD GBPUSD AUDUSD; fixed weights 1/3","JPYfactor":"UNKNOWN: no identity-bound compatible independent JPY crosses","EURJPY_usable_for_inference":False,"triangle_n":triangle.height,"triangle_median_bps":float(triangle["error_bps"].median()),"triangle_abs_p95_bps":float(triangle["error_bps"].abs().quantile(.95)),"triangle_gt5bps_fraction":float((triangle["error_bps"].abs()>5).mean()),"warning":"Cross-source legacy BID minute-close mismatch. Triangle residual is not predictive alpha."})
    # Native registry builds open-to-open markout labels. Dense nulls do not become fills.
    targetgrid=grid.join(clean["USDJPY"],on="timestamp",how="left")
    targetgrid=targetgrid.with_columns(pl.col("open").alias("close"))
    targets=features(targetgrid,horizons).with_columns([pl.col(f"f{h}").shift(-h).over("session").alias(f"y{h}") for h in horizons])
    labels=targets.filter(pl.col("minute").is_in([a+1 for a in anchors])).select("session",(pl.col("minute")-1).alias("anchor"),pl.col("open").alias("entry_price"),*[pl.col(f"y{h}")*10000 for h in horizons])
    events=events.join(labels,on=["session","anchor"]).sort("session")
    write_frame(events,DATA/"event_labels.parquet")
    lead=[];native=[]
    for a in anchors:
        for pair in MAJORS[1:]+["USDfactor"]:
            for lb in horizons:
                for h in horizons:
                    for group in ["gotobi","ordinary"]:
                        d=events.filter((pl.col("anchor")==a)&pl.col(group)).drop_nulls([f"{pair}_f{lb}",f"USDJPY_f{lb}",f"y{h}"]).sort("session")
                        ident=f"B_{a}_{pair}_L{lb}_H{h}_{group}"
                        dev=d.filter(pl.col("year")<=2023)
                        if dev.height<100 or d.height<150:
                            lead.append({"id":ident,"anchor":a,"pair":pair,"lookback":lb,"horizon":h,"group":group,"n":d.height,"status":"INSUFFICIENT","p":1.0});continue
                        scale=float(dev[f"{pair}_f{lb}"].std())
                        x_external=d[f"{pair}_f{lb}"].to_numpy()/scale
                        own=d[f"USDJPY_f{lb}"].to_numpy()/float(dev[f"USDJPY_f{lb}"].std())
                        x=np.column_stack([np.ones(d.height),x_external,own,*controls(d)[1:]])
                        y=d[f"y{h}"].to_numpy()
                        fit=estimate(y,x,clusters=np.array([str(s)[:7] for s in d["session"]]))
                        yearly=[]
                        for year in range(2020,2027):
                            mask=d["year"].to_numpy()==year
                            yearly.append({"year":year,**estimate(y[mask],np.column_stack([np.ones(mask.sum()),x_external[mask],own[mask]]))})
                        qdev=dev[f"{pair}_f{lb}"].quantile(.2),dev[f"{pair}_f{lb}"].quantile(.8)
                        quant={"train_only_cutoffs":qdev,"low":mean_hac(d.filter(pl.col(f"{pair}_f{lb}")<=qdev[0])[f"y{h}"].to_numpy()),"high":mean_hac(d.filter(pl.col(f"{pair}_f{lb}")>=qdev[1])[f"y{h}"].to_numpy())}
                        model=make_pipeline(StandardScaler(),LinearRegression())
                        evaluation=Evaluator(splitter=AnnualExpanding(d["year"].to_numpy()),metrics=["ic","hit_rate"],statistical_tests=[],tier=3).evaluate(np.column_stack([d[f"{pair}_f{lb}"].to_numpy(),d[f"USDJPY_f{lb}"].to_numpy()]),y,model,strategy_func=lambda predictions,actual:np.zeros_like(actual))
                        folds=evaluation.fold_results
                        native.append({"id":ident,"folds":folds})
                        lead.append({"id":ident,"anchor":a,"pair":pair,"lookback":lb,"horizon":h,"group":group,**fit,"yearly":yearly,"quantiles":quant,"scale_train_2020_2023":scale})
    pvals=[r["p"] for r in lead]
    for r,p in zip(lead,multipletests(pvals,method="holm")[1]):r["p_holm640"]=float(p)
    save("T4_leadlag/result.json",{"family_count":len(lead),"tests":lead,"native_walkforward":native,"units":"USDJPY forward log bps per development-SD external feature, conditional on prior USDJPY, weekday/year","no_portfolio_metrics":True})
    pl.DataFrame([{k:v for k,v in r.items() if k not in ["yearly","quantiles","ci95","month_cluster_ci95"]} for r in lead],infer_schema_length=None).write_csv(OUT/"leadlag_scalar.csv")
    # Three frozen simple candidates. These are event markout economic screens,
    # never fictitious fills. USDfactor confirmation must agree with direction.
    candidates=[]; candidate_panels=[]
    for name,direction,anchor,exit_min,hedge in ev["candidates"]:
        if hedge=="cross":
            candidates.append({"id":name,"status":"INELIGIBLE_SOURCE","qualifies":False});continue
        lb=15; entry=anchor+1
        e=events.filter((pl.col("anchor")==anchor)&pl.col("gotobi")).drop_nulls(["USDfactor_f15"])
        needed=["USDJPY"]+(["EURUSD"] if hedge=="EURUSD" else [])
        sub=wide.filter(pl.col("minute").is_between(entry,exit_min)).group_by("session").agg(*[pl.col(p).count().alias(f"n_{p}") for p in needed],*[pl.col(p).filter(pl.col("minute")==entry).first().alias(f"in_{p}") for p in needed],*[pl.col(p).filter(pl.col("minute")==exit_min).first().alias(f"out_{p}") for p in needed])
        d=e.join(sub,on="session").filter(pl.all_horizontal([pl.col(f"n_{p}")==exit_min-entry+1 for p in needed])).sort("session")
        d=d.with_columns((pl.col("USDfactor_f15")*direction>0).alias("confirmed"))
        # q_USD=10000 directional, 5000 hedged. Both legs have same sign to cancel USD.
        base=10000 if not hedge else 5000
        gross=direction*base*(pl.col("out_USDJPY")-pl.col("in_USDJPY"))/pl.col("out_USDJPY")
        if hedge:gross=gross+direction*5000*(pl.col("out_EURUSD")/pl.col("in_EURUSD")-1)
        d=d.with_columns(gross.alias("gross_usd"))
        for multiplier in [1,2,3]:
            cost=base*0.01/pl.col("out_USDJPY")*multiplier
            if hedge:cost=cost+5000/pl.col("in_EURUSD")*0.0001*multiplier
            d=d.with_columns((pl.col("gross_usd")-cost).alias(f"net_usd_cost{multiplier}"))
        selected=d.filter(pl.col("confirmed"))
        dev=selected.filter(pl.col("year")<=2023);valid=selected.filter(pl.col("year").is_between(2024,2025));stress=selected.filter(pl.col("year")==2026)
        unconditional=mean_hac(d["net_usd_cost1"].to_numpy());net=mean_hac(selected["net_usd_cost1"].to_numpy())
        matched=d.with_columns(pl.when(pl.col("confirmed")).then(pl.col("net_usd_cost1")).otherwise(0.).alias("confirmation_policy_markout"))
        increment=mean_hac((matched["confirmation_policy_markout"]-matched["net_usd_cost1"]).to_numpy())
        predictive=[r for r in lead if r["pair"]=="USDfactor" and r["anchor"]==anchor and r["lookback"]==15 and r["horizon"]==15 and r["group"]=="gotobi"]
        years=selected.group_by("year").agg(pl.len().alias("n"),pl.col("net_usd_cost1").mean()).sort("year").to_dicts()
        placebos=[r for r in lead if r["pair"]=="USDfactor" and r["anchor"] in [610,715] and r["lookback"]==15 and r["horizon"]==15 and r["group"]=="gotobi"]
        matched_placebo=events.filter((pl.col("anchor")==715)&pl.col("gotobi")).select("session",pl.col("y15").alias("placebo_y15"))
        match=d.join(matched_placebo,on="session").drop_nulls(["y15","placebo_y15"]).sort("session")
        scale=match.filter(pl.col("year")<=2023)["USDfactor_f15"].std()
        specificity=estimate((match["y15"]-match["placebo_y15"]).to_numpy(),np.column_stack([np.ones(match.height),match["USDfactor_f15"].to_numpy()/scale]))
        gates={"n100":selected.height>=100,"development_positive":dev.height>0 and dev["net_usd_cost1"].mean()>0,"validation_n50_positive":valid.height>=50 and valid["net_usd_cost1"].mean()>0,"stress_positive":stress.height>=20 and stress["net_usd_cost1"].mean()>0,"net_hac_lower_positive":net.get("ci95",[-1])[0]>0,"increment_hac_lower_positive":increment.get("ci95",[-1])[0]>0,"external_predictive_holm_pass":bool(predictive and predictive[0]["p_holm640"]<.05 and predictive[0].get("coef",0)>0),"placebo_not_same_direction_holm":not any(r["p_holm640"]<.05 and r.get("coef",0)>0 for r in placebos),"matched_specificity_lower_positive":specificity.get("ci95",[-1])[0]>0,"year_sign_5_of_7":sum(r["net_usd_cost1"]>0 for r in years)>=5,"source_comparable":True}
        candidates.append({"id":name,"qualifies":all(gates.values()),"gates":gates,"selected_n":selected.height,"unconditional_n":d.height,"net_cost1":net,"unconditional":unconditional,"increment_vs_unconditional":increment,"matched_specificity":specificity,"cost_sensitivity":{str(c):mean_hac(selected[f"net_usd_cost{c}"].to_numpy()) for c in [1,2,3]},"years":years,"gross_entry_notional_usd":10000,"costs":"Hypothetical 1/2/3 pip round-trip per leg, including spread+fees+slippage aggregate; broker costs UNKNOWN"})
        d.with_columns(pl.lit(name).alias("candidate")).write_parquet(OUT/f"{name}_markouts.parquet")
        candidate_panels.append(d)
    benchmarks=[]
    for name,a,b,direction in ev["benchmarks"]:
        for group in ["gotobi","ordinary"]:
            sub=wide.filter(pl.col("minute").is_between(a,b)).group_by("session").agg(pl.col("USDJPY").count().alias("count"),pl.col("USDJPY").filter(pl.col("minute")==a).first().alias("entry"),pl.col("USDJPY").filter(pl.col("minute")==b).first().alias("exit"))
            d=registry.filter(pl.col(group)).join(sub,on="session").filter(pl.col("count")==b-a+1).sort("session")
            vals=(direction*10000*(d["exit"]-d["entry"])/d["exit"]-100/d["exit"]).to_numpy()
            benchmarks.append({"id":name+"_"+group,"net_usd_1pip":mean_hac(vals),"kind":"USD10000 fixed base event markout, not new Engine run"})
    latency=[]
    for lag in ev["latency_minutes"]:
        a=595+lag;b=a+15
        d=events.filter((pl.col("anchor")==595)&pl.col("gotobi")).drop_nulls(["USDfactor_f15"])
        sub=wide.filter(pl.col("minute").is_between(a,b)).group_by("session").agg(pl.col("USDJPY").count().alias("count"),pl.col("USDJPY").filter(pl.col("minute")==a).first().alias("entry"),pl.col("USDJPY").filter(pl.col("minute")==b).first().alias("exit"))
        d=d.join(sub,on="session").filter(pl.col("count")==b-a+1).sort("session")
        scale=d.filter(pl.col("year")<=2023)["USDfactor_f15"].std()
        fit=estimate(np.log(d["exit"].to_numpy()/d["entry"].to_numpy())*10000,np.column_stack([np.ones(d.height),d["USDfactor_f15"].to_numpy()/scale]))
        latency.append({"lag_minutes":lag,**fit})
    save("T5_candidates/result.json",{"candidates":candidates,"benchmarks":benchmarks,"latency":latency,"kind":"Event markout economic screen, not strategy backtest","approval_status":"NOT_APPROVED","cash_benchmark_markout":0.})
    if any(c["qualifies"] for c in candidates):
        raise RuntimeError("Qualified candidate requires separate native Engine execution; do not close as no-qualifier")
    save("T6_native_disposition/result.json",{"status":"NO_QUALIFIER","native_candidate_runs":0,"reason":"Frozen statistical/economic gates failed or sources incompatible; mission prohibits forced backtest","previous_native_benchmarks":"Program1 frozen native replay is historical evidence only; new matched markouts are T5, with cash zero","holdout":"SEALED","DSR_PBO":"Not applicable: no selected native strategy; incomplete earlier Program1 search cannot be repaired"})
    # Same-time descriptive mean profiles; each minute has its own sample count.
    curves=[]
    for pair in MAJORS:
        ref=wide.filter(pl.col("minute")==595).select("session",pl.col(pair).alias("reference"))
        curve=wide.select("session","minute","gotobi",pair).join(ref,on="session").drop_nulls().with_columns(((pl.col(pair)/pl.col("reference")).log()*10000).alias("log_bps"))
        curves.append(curve.group_by("minute","gotobi").agg(pl.len().alias("n"),pl.col("log_bps").mean()).with_columns(pl.lit(pair).alias("pair")))
    curve=pl.concat(curves);curve.write_csv(OUT/"intraday_profiles.csv")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,2,figsize=(12,7),sharex=True)
    for ax,pair in zip(axes.flat,MAJORS):
        for gotobi in [True,False]:
            d=curve.filter((pl.col("pair")==pair)&(pl.col("gotobi")==gotobi)).sort("minute")
            ax.plot(d["minute"].to_numpy()/60,d["log_bps"].to_numpy(),label="Gotobi" if gotobi else "Ordinary")
        ax.axvline(595/60,color="gray",linestyle="--");ax.set_title(pair);ax.set_ylabel("log bps vs 09:55");ax.legend()
    fig.suptitle("Descriptive changing-cohort profiles; no portfolio or confidence claim")
    fig.tight_layout();fig.savefig(OUT/"intraday_profiles.png");plt.close(fig)
    save("analysis_complete.json",{"flow_hypotheses":len(profiles),"predictive_hypotheses":len(lead),"predictive_holm_survivors":sum(r["p_holm640"]<.05 for r in lead),"flow_holm_survivors":sum(r["increment"]["p_holm_flow16"]<.05 for r in profiles),"no_qualifier":True,"snapshot_hashes":{str(p.relative_to(ROOT)):sha(p) for p in DATA.glob("*.parquet")}})

if __name__=="__main__":main()
