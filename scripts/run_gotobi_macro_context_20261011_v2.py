"""Nonprice Gotobi: delayed yield, archival policy events, bank-calendar tests.

Frozen session 2020-2025; historical reference feed, NOT valid unseen OOS.
Policy decision archival dates are EX-POST ONLY. Yield series are vendor
snapshots and publication/vintages UNVERIFIED despite conservative 3d delay.
"""
from __future__ import annotations
import json,hashlib,math,subprocess,sys
from pathlib import Path
from datetime import datetime,date,time,timedelta,timezone
from zoneinfo import ZoneInfo
from types import SimpleNamespace
import numpy as np
import polars as pl
from scipy.stats import spearmanr
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_squared_error
from ml4t.backtest import Engine, Strategy, DataFeed, BacktestConfig, ExecutionMode
from ml4t.backtest.config import ExecutionPrice, CommissionType, SlippageType, ShareType
from ml4t.backtest.analytics import EquityCurve
import run_gotobi_exact_paper_bridge_20261011_v1 as paper

ROOT=Path(__file__).resolve().parents[1]
SID="gotobi_macro_context_20261011_v2"
OUT=ROOT/"run_log"/SID
DAT=ROOT/"data/processed/gotobi_macro_context_20261011_v1"
CAL=ROOT/"run_log/gotobi_exact_paper_bridge_20261011_v1/event_panel.parquet"
SOURCE=ROOT/"run_log/gotobi_exact_paper_bridge_20261011_v1/native/trades.parquet"
JST=ZoneInfo("Asia/Tokyo")
UTC=timezone.utc
TARGET="net_pips"
COSTS=[1.0,1.5,2.0]

def sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda:f.read(2**20),b""):h.update(block)
    return h.hexdigest()

def dump(path,obj):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    text=json.dumps(obj,indent=2,default=str,allow_nan=False)+"\n"
    if path.exists():
        if json.loads(path.read_text())!=json.loads(text):
            raise RuntimeError(f"Existing evidence mismatch: {path}")
    else:path.write_text(text)

def parquet(path,frame):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if not pl.read_parquet(path).equals(frame):
            raise RuntimeError(f"Existing parquet mismatch: {path}")
    else:frame.write_parquet(path)

def cli(*args):
    p=subprocess.run([sys.executable,"scripts/research_session.py",*args,"--root","."],
                     cwd=ROOT,text=True,capture_output=True)
    if p.returncode:raise RuntimeError(p.stdout+p.stderr)
    return json.loads(p.stdout)

def record(tid):
    proof=ROOT/"run_log/research_sessions"/SID/"trials"/f"{tid}.json"
    if proof.exists():return
    cli("record","--session",SID,"--trial",tid,"--status","completed",
        "--artifact",f"run_log/{SID}/{tid}/result.json")

def sources():
    manifest=json.loads((DAT/"source_manifest.json").read_text())
    for source in manifest["data"]:
        assert sha(ROOT/source["local"])==source["local_sha256"]
        assert sha(Path(source["source"]))==source["source_sha256"]
    assert len(manifest["data"])==3
    trades=pl.read_parquet(SOURCE).sort("session")
    calendar=pl.read_parquet(CAL).filter(pl.col("session").dt.year()<=2025).sort("session")
    assert trades.height==370 and calendar["session"].max()<date(2026,1,1)
    for t in trades["entry_at"]:
        assert t.astimezone(JST).hour==3 and t.astimezone(JST).minute==0
    events=pl.read_parquet(DAT/"rate_events.parquet")
    bad=events.filter(pl.col("archive_created_at_utc")>pl.col("event_at_utc")).height
    assert bad>0
    s={"source_manifest_sha256":sha(DAT/"source_manifest.json"),
       "historical_event_total":events.height,
       "archival_records_created_after_event":bad,
       "rate_events_not_usable_as_historical_PIT_features":True,
       "vendor_yield_vintages_available":False,
       "assumed_yield_delay_days":3,
       "trade_labels_source_hash":sha(SOURCE),
       "calendar_source_hash":sha(CAL),
       "native_events":trades.height,
       "protected_2026_holdout_read":False}
    dump(OUT/"T0_source_audit/result.json",s)
    record("T0_source_audit")
    return trades,calendar,events,manifest

def panelize(trades,calendar,events):
    # Use only author-scheduled Gotobi dates with prior audited native fills.
    base=(trades.join(calendar.select("session","author_gotobi","year","weekday"),
                      on="session",validate="1:1")
          .filter(pl.col("author_gotobi")).sort("session")
          .with_columns((pl.col("entry_at")-pl.duration(minutes=1)).alias("decision_at"),
                        ((pl.col("exit")-pl.col("entry"))/0.01).alias(TARGET)))
    # Recompute author dates and settlement subtype from the calendar only.
    original_calendar=(pl.read_parquet(paper.CALPATH)
             .filter(pl.col("session").is_between(date(2020,1,1),date(2025,12,31)))
             .sort("session"))
    auth,labels=paper.source_calendar(original_calendar)
    assert set(base["session"].to_list()).issubset(set(labels))
    subtype=pl.DataFrame([{"session":d,
                           "month_end":int("last_calendar_day" in tags),
                           "rolled":int(any(t.startswith("nominal_") and d.day!=int(t.split("_")[1])
                                            for t in tags))}
                         for d,tags in sorted(labels.items())]).sort("session")
    base=base.join(subtype,on="session",validate="1:1")
    for symbol,col in [("US10Y","us_yield"),("JP10Y","jp_yield")]:
        yield_df=(pl.read_parquet(DAT/f"{symbol}.parquet")
                  .select("available_at_assumed",pl.col("value").alias(col),
                          pl.col("observation_date").alias(col+"_date"))
                  .sort("available_at_assumed"))
        base=base.sort("decision_at").join_asof(
            yield_df,left_on="decision_at",right_on="available_at_assumed",
            strategy="backward").drop("available_at_assumed")
    base=base.with_columns((pl.col("us_yield")-pl.col("jp_yield")).alias("spread_10y"))
    # Policy meeting proximity is intentionally ex-post. Schedule metadata
    # created after many decisions => NEVER use this as a model input.
    near_dates=set()
    for t in events["event_at_utc"]:
        event_date=t.astimezone(JST).date()
        for delta in [-1,0,1]:
            near_dates.add(event_date+timedelta(days=delta))
    base=base.with_columns(pl.col("session").is_in(list(near_dates)).alias("near_rate_event_expost"))
    base=base.with_columns(pl.col("us_yield_date").cast(pl.Datetime("us","UTC")).alias("us_date_utc"),
                           pl.col("jp_yield_date").cast(pl.Datetime("us","UTC")).alias("jp_date_utc"))
    if base.filter((pl.col("us_date_utc")+pl.duration(days=3)>pl.col("decision_at"))|
                   (pl.col("jp_date_utc")+pl.duration(days=3)>pl.col("decision_at"))).height:
        raise RuntimeError("Availability violation")
    cols=["session","year","weekday","entry_at","exit_at","decision_at",
          "month_end","rolled","us_yield","jp_yield","spread_10y",
          "us_yield_date","jp_yield_date","near_rate_event_expost","net_pips",
          "entry","exit","pnl_jpy","pnl_usd"]
    base=base.select(cols).sort("session")
    parquet(OUT/"feature_panel.parquet",base)
    coverage=base.filter(pl.col("spread_10y").is_not_null()).height
    q={"source_trade_days":base.height,"yield_complete_days":coverage,
       "yield_fraction":coverage/base.height,
       "month_end_days":int(base["month_end"].sum()),
       "rolled_nominal_days":int(base["rolled"].sum()),
       "events_near_policy_decision_expost":base.filter(pl.col("near_rate_event_expost")).height,
       "min_observation_date":str(base["us_yield_date"].min()),
       "max_observation_date":str(base["us_yield_date"].max()),
       "hypothetical_yield_utc_availability":"observation_date+3 calendar days 00:00 UTC",
       "strict_verified_yield_vintages":False,
       "historical_policy_schedule_PIT":False,
       "enough_yield_coverage":coverage/base.height>=0.8}
    dump(OUT/"T1_feature_panel/result.json",q)
    record("T1_feature_panel")
    return base,q

def hac_slope(frame,col):
    df=frame.filter(pl.col(col).is_not_null()).sort("session")
    n=df.height
    if n<25 or df[col].n_unique()<2:return {"n":n,"status":"INSUFFICIENT"}
    xx=sm.add_constant(df[col].to_numpy().astype(float))
    model=sm.OLS(df[TARGET].to_numpy(),xx).fit(
       cov_type="HAC",cov_kwds={"maxlags":5},use_t=True)
    ic=spearmanr(df[col].to_numpy().astype(float),df[TARGET].to_numpy())
    return {"status":"ESTIMATED","n":n,"coefficient_pips_per_unit":float(model.params[1]),
            "p":float(model.pvalues[1]),"ci95":list(map(float,model.conf_int()[1])),
            "spearman":float(ic.statistic),
            "mean_when_positive":float(df.filter(pl.col(col)>0)[TARGET].mean())
                if df.filter(pl.col(col)>0).height else None}

def diagnostics(panel,events):
    per_family={}
    for name in ("spread_10y","month_end","rolled"):
        per_family[name]=hac_slope(panel,name)
    p=[per_family[name].get("p",1) for name in ("spread_10y","month_end","rolled")]
    adj=multipletests(p,method="holm")[1]
    for name,x in zip(("spread_10y","month_end","rolled"),adj):
        per_family[name]["holm3_p"]=float(x)
    per_period={}
    for period,years in [("dev_2020_22",[2020,2021,2022]),
                          ("test_2023_25",[2023,2024,2025]),
                          ("recent_2024_25",[2024,2025])]:
        sample=panel.filter(pl.col("year").is_in(years))
        per_period[period]={"n":sample.height,"mean_net_pips":float(sample[TARGET].mean()),
                           "gross_sum_usd":float(sample["pnl_usd"].sum()),
                           "yield_spearman":hac_slope(sample,"spread_10y")}
    policy=panel.group_by("near_rate_event_expost").agg(
        pl.len().alias("n"),pl.col(TARGET).mean().alias("mean_net_pips"),
        pl.col("pnl_usd").sum().alias("net_usd")).sort("near_rate_event_expost")
    result={"primary_three_family_tests":per_family,
            "hypothesis_periods":per_period,
            "policy_event_expost_descriptive":policy.to_dicts(),
            "policy_event_proximity_eligible_predictor":False,
            "policy_event_origin":"Backfilled LSE archive, 99 of 100 records created after event",
            "historical_yield_vintages_unverified":True,
            "false_discovery_control":"Holm for 3 preregistered family tests only",
            "conditional_causality":"Not established by associations"}
    dump(OUT/"T2_hypothesis_diagnostics/result.json",result)
    record("T2_hypothesis_diagnostics")
    return result

def forecasts(panel):
    available=panel.filter(pl.col("spread_10y").is_not_null()).sort("session")
    if available.height/panel.height<.8:
        raise RuntimeError("Insufficient macro feature coverage; do not run models")
    schemas={"ridge_calendar_only":["month_end","rolled"],
             "ridge_with_yield":["month_end","rolled","spread_10y"]}
    outputs=[]
    training=[]
    for test_year in (2023,2024,2025):
        tr=available.filter(pl.col("year")<test_year)
        te=available.filter(pl.col("year")==test_year)
        if tr.height<100 or not te.height:raise RuntimeError("Insufficient fold")
        x0=np.array(tr[TARGET].to_list())
        predicted={"session":te["session"].to_list(),"year":[test_year]*te.height,
                   TARGET:te[TARGET].to_list(),
                   "always_long":[True]*te.height}
        rec={"year":test_year,"train_n":tr.height,"test_n":te.height,
             "train_through":str(tr["session"].max()),"test_from":str(te["session"].min()),
             "train_mean_pips":float(x0.mean()),"model_fit":[]}
        baseline=np.repeat(x0.mean(),te.height)
        rec["train_mean_test_rmse"]=float(np.sqrt(mean_squared_error(te[TARGET],baseline)))
        for name,columns in schemas.items():
            pipe=Pipeline([("scaler",StandardScaler()),
                           ("model",Ridge(alpha=10.0))])
            pipe.fit(tr.select(columns).to_numpy().astype(float),x0)
            p=pipe.predict(te.select(columns).to_numpy().astype(float))
            predicted[name]=[bool(k>0) for k in p]
            predicted[name+"_predicted_pips"]=p.tolist()
            rec["model_fit"].append({"name":name,"features":columns,
                   "test_rmse":float(np.sqrt(mean_squared_error(te[TARGET],p))),
                   "n_traded":int((p>0).sum()),
                   "coef_scaled":pipe.named_steps["model"].coef_.tolist(),
                   "intercept":float(pipe.named_steps["model"].intercept_)})
        outputs.append(pl.DataFrame(predicted))
        training.append(rec)
    pred=pl.concat(outputs).sort("session")
    if pred["session"].is_duplicated().any():raise RuntimeError("Multiple predictions per event")
    for col in ["ridge_calendar_only","ridge_with_yield"]:
        assert pred[col].null_count()==0
    parquet(OUT/"walkforward_predictions.parquet",pred)
    result={"folds":training,"n_predicted":pred.height,
            "models":["ridge_calendar_only","ridge_with_yield"],
            "alpha":10.0,"binary_decision":"predict net pips > 0",
            "threshold_tuning":False,"model_select_from_test":False,
            "yield_vintages_verified":False,
            "policy_event_archive_used_as_model_feature":False}
    dump(OUT/"T3_walkforward/result.json",result)
    record("T3_walkforward")
    return pred,result

class FixedLong(Strategy):
    def __init__(self,dates):
        self.dates=set(dates)
        self.events=[]
    def on_start(self,broker):pass
    def on_data(self,timestamp,data,context,broker):
        local=timestamp.astimezone(JST)
        day=local.date()
        minute=local.hour*60+local.minute
        if day not in self.dates:
            if broker.get_position("USDJPY"):raise RuntimeError("Position on nonsignal")
            return
        if minute==179:
            if broker.get_position("USDJPY"):raise RuntimeError("Position already exists")
            order=broker.submit_order("USDJPY",10000)
            if order is None:raise RuntimeError("Entry order rejected")
            self.events.append((day,"buy",timestamp,order))
        if minute==595:
            if broker.get_position("USDJPY") is None:raise RuntimeError("Missing exit position")
            order=broker.close_position("USDJPY")
            if order is None:raise RuntimeError("Exit order rejected")
            self.events.append((day,"sell",timestamp,order))
    def on_end(self,broker):
        assert broker.get_position("USDJPY") is None

def native(trade_dates, all_dates, cost, name):
    if not trade_dates:
        return {"arm":name,"cost_pips":cost,"n":0,"net_usd":0.0,
                "status":"NO_TRADES","max_dd_pct":0.0}
    path=OUT/"runs"/(name+"_"+str(cost).replace(".","p"))
    required=[179,180,595,596]
    raw=(pl.scan_parquet([str(ROOT/f"data/processed/gotobi_paper_replication_20261011_v1/USDJPY_{year}.parquet")
                         for year in range(2023,2026)],hive_partitioning=False)
         .filter(pl.col("session").is_in(trade_dates) & pl.col("minute").is_in(required))
         .select("timestamp","symbol","open","high","low","close","volume","session","minute")
         .sort("timestamp").collect())
    counts=raw.group_by("session").agg(pl.len().alias("count"),pl.col("minute").n_unique().alias("unique"))
    assert counts.height==len(trade_dates)
    assert counts.filter((pl.col("count")!=4)|(pl.col("unique")!=4)).is_empty()
    frame=raw.select("timestamp","symbol","open","high","low","close","volume")
    initial_jpy=10000*float(frame["open"][0])
    strategy=FixedLong(trade_dates)
    cfg=BacktestConfig(initial_cash=initial_jpy,allow_leverage=True,initial_margin=.5,
                       execution_mode=ExecutionMode.NEXT_BAR,execution_price=ExecutionPrice.OPEN,
                       share_type=ShareType.FRACTIONAL,commission_type=CommissionType.NONE,
                       slippage_type=SlippageType.FIXED,slippage_fixed=cost*.01/2,
                       partial_fills_allowed=False)
    result=Engine(DataFeed(prices_df=frame),strategy,cfg).run()
    orders=pl.DataFrame([{"session":d,"role":role,"submitted_at":t,
             "filled_at":o.filled_at,"price":float(o.filled_price),
             "status":o.status.value,"quantity":float(o.quantity)}
             for d,role,t,o in strategy.events]).sort("submitted_at")
    assert orders.height==2*len(trade_dates)
    assert orders.filter(pl.col("status")!="filled").is_empty()
    a=orders.filter(pl.col("role")=="buy").select("session",pl.col("price").alias("buy"),
                                                     pl.col("filled_at").alias("entry_at"))
    b=orders.filter(pl.col("role")=="sell").select("session",pl.col("price").alias("sell"),
                                                      pl.col("filled_at").alias("exit_at"))
    oracle=raw.group_by("session").agg(
        pl.col("open").filter(pl.col("minute")==180).first().alias("source_buy"),
        pl.col("open").filter(pl.col("minute")==596).first().alias("source_sell"))
    trades=(a.join(b,on="session",validate="1:1").join(oracle,on="session",validate="1:1")
          .sort("session").with_columns(
           ((pl.col("sell")-pl.col("buy"))*10000).alias("pnl_jpy"))
          .with_columns((pl.col("pnl_jpy")/pl.col("sell")).alias("pnl_usd")))
    sourceerr=max(float((trades["buy"]-trades["source_buy"]-.005*cost).abs().max()),
                  float((trades["sell"]-trades["source_sell"]+.005*cost).abs().max()))
    recon_err=abs((float(result.metrics["final_value"])-initial_jpy)-float(trades["pnl_jpy"].sum()))
    assert sourceerr<1e-7 and recon_err<1e-5
    assert all(t.astimezone(JST).strftime("%H:%M")=="03:00" for t in trades["entry_at"])
    assert all(t.astimezone(JST).strftime("%H:%M")=="09:56" for t in trades["exit_at"])
    ledger=pl.DataFrame({"session":sorted(all_dates)}).join(
          trades.select("session","pnl_usd"),on="session",how="left").with_columns(
           pl.col("pnl_usd").fill_null(0))
    ledger=ledger.with_columns((10000+pl.col("pnl_usd").cum_sum()).alias("equity_usd"))
    times=[datetime.combine(ledger["session"][0]-timedelta(days=1),time.min,JST)]
    times.extend(datetime.combine(dd,time.min,JST) for dd in ledger["session"])
    eq=EquityCurve(times,[10000]+ledger["equity_usd"].to_list(),periods_per_year_override=252)
    byyear=trades.with_columns(pl.col("session").dt.year().alias("year")).group_by("year").agg(
       pl.len().alias("n"),pl.col("pnl_usd").sum().alias("net_usd")).sort("year").to_dicts()
    path.mkdir(parents=True,exist_ok=True)
    parquet(path/"orders.parquet",orders)
    parquet(path/"trades.parquet",trades)
    parquet(path/"daily_equity.parquet",ledger)
    resultobj={"arm":name,"cost_pips":cost,"n":trades.height,"net_usd":float(trades["pnl_usd"].sum()),
          "avg_net_usd_per_eligible_gotobi":float(trades["pnl_usd"].sum())/len(all_dates),
          "sharpe_flat_inclusive":float(eq.sharpe),
          "max_dd_pct":float(eq.max_dd)*100,
          "annual":byyear,"source_price_error_jpy":sourceerr,
          "engine_cash_reconciliation_jpy":recon_err,
          "risk":"hypothetical fill cost; broker model missing",
          "holdout_read":False}
    dump(path/"result.json",resultobj)
    return resultobj

def trade_backtests(pred):
    universe=pred["session"].to_list()
    out=[]
    for cost in COSTS:
        for arm in ("always_long","ridge_calendar_only","ridge_with_yield"):
            selected=pred.filter(pl.col(arm))["session"].to_list()
            run=native(selected,universe,cost,arm)
            out.append(run)
            print("NATIVE",cost,arm,run["n"],round(run["net_usd"],3),flush=True)
    primary={"runs":[x for x in out if x["cost_pips"]==1.0],
             "evaluation_cohort":len(universe),
             "strategy_order":"baseline always_long, calendar_only, add yield",
             "model_selection":"None; compare all",
             "qualification_eligible":False}
    dump(OUT/"T4_native_engine/result.json",primary);record("T4_native_engine")
    costruns={"runs":[x for x in out if x["cost_pips"]!=1.0],
              "historical_broker_costs_verified":False}
    dump(OUT/"T5_cost_robustness/result.json",costruns);record("T5_cost_robustness")
    return out

def audit(panel,pred,trades,manifest,results,quality,diagnoses):
    # Enforce same 2023-2025 native source label cohort independent of model results.
    original=trades.filter(pl.col("session").is_in(pred["session"].to_list())).sort("session")
    assert original.height==pred.height
    chosen=[r for r in results if r["arm"]=="always_long" and r["cost_pips"]==1.0][0]
    err=abs(chosen["net_usd"]-float(original["pnl_usd"].sum()))
    assert err<1e-6
    assert all(panel.filter(pl.col("session").is_in(pred["session"].to_list()))["decision_at"]<
               panel.filter(pl.col("session").is_in(pred["session"].to_list()))["entry_at"])
    assert pred.filter(pl.col("year")<2023).is_empty()
    checks={"baseline_source_ledger_usd_difference":err,
            "max_filled_order_source_error":max(x.get("source_price_error_jpy",0) for x in results),
            "max_native_jpy_reconciliation":max(x.get("engine_cash_reconciliation_jpy",0) for x in results),
            "yield_vintage_verified":False,"events_archive_pre_event_certified":False,
            "never_used_hindsight_policy_events_for_trading":True,
            "walkforward_only_prior_years":True,
            "input_source_hashes_match":True,
            "all_2023_2025_cohort_dates_matched":True,
            "protected_2026_sep_oct_holdout_read":False,
            "known_trials":7,"historical_other_session_trials_not_adjusted":True}
    dump(OUT/"T6_independent_audit/result.json",checks)
    record("T6_independent_audit")
    a=next(z for z in results if z["arm"]=="always_long" and z["cost_pips"]==1.0)
    cal=next(z for z in results if z["arm"]=="ridge_calendar_only" and z["cost_pips"]==1.0)
    mac=next(z for z in results if z["arm"]=="ridge_with_yield" and z["cost_pips"]==1.0)
    b24=mac["annual"]
    selected_years=[z["year"] for z in b24 if z["year"] in (2024,2025)]
    net_recent=sum(z["net_usd"] for z in b24 if z["year"] in (2024,2025))
    baseline_recent=sum(z["net_usd"] for z in cal["annual"] if z["year"] in (2024,2025))
    macro_increment=mac["net_usd"]-cal["net_usd"]
    qualified=False # vintage not verified, even if in-sample numerically favorable
    status="NOT_APPROVED_EXPLORATORY"
    report=[
      "# Gotobi non-price context MVP — 2020–2025 retrospective",
      "",
      "**Decision: NOT APPROVED.** Yield series are retrospective vendor snapshots.",
      "Three-day availability lag is hypothetical, not authenticated vintages.",
      "The LSE announcement archive dates are backfilled and cannot qualify as PIT model inputs.",
      "",
      "## Source, method and data integrity",
      f"- Original native trades: {trades.height} dates, only 2020–2025.",
      f"- Delayed US10Y/JP10Y coverage: {quality['yield_complete_days']}/{quality['source_trade_days']} = {quality['yield_fraction']:.1%}.",
      f"- Nonprice calendar flags: month-end {quality['month_end_days']}, rolled nominal {quality['rolled_nominal_days']}.",
      f"- Historical central bank archive: {manifest['data'][2]['rows']} records; {manifest['data'][2]['archive_record_created_after_event']} created after the event.",
      "- LSE yields are daily retrospective values. For hypothetical as-of joins, add 3 UTC calendar days after observation date; as-of backward only.",
      "- Calendar uses author Gotobi 5,10,15,20,25,month-last rollback, once per date.",
      "",
      "## Single-feature diagnostics, HAC5, Holm3",
      "",
      "| Predictor | N | HAC slope (pips/unit) | HAC p | Holm3 p |",
      "|---|---:|---:|---:|---:|",
    ]
    for key,entry in diagnoses["primary_three_family_tests"].items():
        report.append(f"| {key} | {entry['n']} | {entry.get('coefficient_pips_per_unit',float('nan')):+.3f} | {entry.get('p',float('nan')):.4f} | {entry.get('holm3_p',float('nan')):.4f} |")
    report+=["",
        "These are associations, not identified causes. Pooled inference is confounded by the severe 2020–2025 regime shift.",
        "Historical policy-event proximity is EX POST ONLY. It did NOT enter model fitting or trade decisions.",
        "",
        "## Native ml4t.backtest Engine — chronological annual models",
        "",
        "Fit train-only StandardScaler + Ridge(alpha=10) on preceding calendar years,",
        "starting training 2020–2022. Predict 2023, then retrain including 2023",
        "for 2024; continue for 2025. Trade if predicted net pips > 0.",
        "All arms use same complete macro-feature-eligible event dates.",
        "Execution at 03:00 OPEN, exit 09:56 OPEN, cost 0.5pip each side.",
        "",
        "| Strategy | Trades | 2023-25 net USD | Flat-inclusive Sharpe |",
        "|---|---:|---:|---:|",
        f"| Gotobi always-long | {a['n']} | {a['net_usd']:+.2f} | {a['sharpe_flat_inclusive']:.3f} |",
        f"| Calendar-only Ridge | {cal['n']} | {cal['net_usd']:+.2f} | {cal['sharpe_flat_inclusive']:.3f} |",
        f"| Calendar + delayed US–JP spread Ridge | {mac['n']} | {mac['net_usd']:+.2f} | {mac['sharpe_flat_inclusive']:.3f} |",
        "",
        f"- Macro increment versus calendar model: **{macro_increment:+.2f} USD** over 2023–2025.",
        f"- Macro model 2024–2025: **{net_recent:+.2f} USD**, calendar comparator **{baseline_recent:+.2f} USD**.",
        "",
        "| Year | Calendar-only USD | Calendar + yield USD |",
        "|---|---:|---:|",
    ]
    for year in (2023,2024,2025):
        x=sum(z["net_usd"] for z in cal["annual"] if z["year"]==year)
        y=sum(z["net_usd"] for z in mac["annual"] if z["year"]==year)
        report.append(f"| {year} | {x:+.2f} | {y:+.2f} |")
    report+=["",
      "## Cost and identification limits",
      "",
      "| Round trip pips | Always long USD | Calendar model USD | Calendar+yield USD |",
      "|---|---:|---:|---:|"]
    for cost in COSTS:
        rs=[next(z for z in results if z["arm"]==name and z["cost_pips"]==cost)
            for name in ("always_long","ridge_calendar_only","ridge_with_yield")]
        report.append(f"| {cost:.1f} | {rs[0]['net_usd']:+.2f} | {rs[1]['net_usd']:+.2f} | {rs[2]['net_usd']:+.2f} |")
    report+=["",
      "- The entire 2020–2025 history was previously observed in other Gotobi programs; these fold results are retrospective, NOT true OOS.",
      "- Macro series do not include historically verifiable first-publication and revision vintages. Added lag alone does not solve this.",
      "- 99/100 LSE interest-rate decision event records were archived after their event; policy-calendar predictor BLOCKED pending independent release calendars.",
      "- Native prices use LSE one-minute spot proxy and hypothetical 1/1.5/2pip all-in cost; broker fills not verified.",
      "- The calendar records date knowledge but no actual corporate settlement flow measurement.",
      "- No protected September–October2026 holdout used, no live orders, no Git commit or push.",
      "",
      "## Reproduce",
      f"- Spec `config/research_sessions/{SID}.yaml`",
      "- Source copies and hashes: `data/processed/gotobi_macro_context_20261011_v1/source_manifest.json`",
      f"- Runner `scripts/run_{SID}.py`",
      f"- Evidence `run_log/{SID}/T*/result.json`",
      f"- Test signals `run_log/{SID}/walkforward_predictions.parquet`",
      f"- Native execution `run_log/{SID}/runs/*`",
      "",
      "**Final: INCONCLUSIVE for deployable macro edge; model not qualified.**",
    ]
    path=ROOT/"docs/audit"/f"{SID}.md"
    body="\n".join(report)+"\n"
    if path.exists():
        if path.read_text()!=body:raise RuntimeError("Refuse overwrite audit")
    else:
        path.write_text(body)
    print(json.dumps({"status":status,"incremental_net_usd":macro_increment,
       "2024_25_macro_net_usd":net_recent,"all":a["net_usd"],
       "calendar":cal["net_usd"],"macro":mac["net_usd"],
       "features":quality,"family_p":{k:z.get("holm3_p") for k,z in diagnoses["primary_three_family_tests"].items()}},indent=2),flush=True)

def main():
    check=cli("check","--session",SID)
    if check["status"]!="PASS":
        raise RuntimeError("Frozen session verification failed")
    OUT.mkdir(parents=True,exist_ok=True)
    trades,cal,events,manifest=sources()
    panel,quality=panelize(trades,cal,events)
    diagnoses=diagnostics(panel,events)
    pred,folds=forecasts(panel)
    results=trade_backtests(pred)
    audit(panel,pred,trades,manifest,results,quality,diagnoses)

if __name__=="__main__":
    main()
