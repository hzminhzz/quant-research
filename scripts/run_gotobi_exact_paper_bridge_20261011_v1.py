"""Paper-method Gotobi reproduction using LSE, with immutable study bridge.

This does not replace the HistData 2006-2025 author's sample. It reproduces
the companion's fixed calendar, bar selection, and arithmetic on available
LSE 2020-2025 source; native execution is an explicitly separate benchmark.
"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests
from ml4t.backtest import Engine, Strategy, DataFeed, BacktestConfig, ExecutionMode
from ml4t.backtest.config import ExecutionPrice, CommissionType, SlippageType, ShareType
from ml4t.backtest.analytics import EquityCurve, TradeAnalyzer

ROOT = Path(__file__).resolve().parents[1]
SID = "gotobi_exact_paper_bridge_20261011_v1"
OUT = ROOT / "run_log" / SID
CALPATH = ROOT / "run_log/tokyo_fix_alpha_map_program1_20261010/execution_v1/calendar_event_registry.parquet"
STRICT = ROOT / "run_log/gotobi_paper_replication_20261011_v1/eligible_bank_dates.parquet"
JST = ZoneInfo("Asia/Tokyo")
UTC = timezone.utc
START = date(2020,1,1)
END = date(2025,12,31)
PIP = 0.01
NOMINAL = (5,10,15,20,25)
COSTS = (0.0,0.4,1.0,1.5)

def sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda:f.read(2**20),b""):
            h.update(block)
    return h.hexdigest()

def artifact(name,content):
    dest=OUT/name
    dest.parent.mkdir(parents=True,exist_ok=True)
    payload=json.dumps(content,indent=2,default=str,allow_nan=False)+"\n"
    if dest.exists():
        if json.loads(dest.read_text())!=json.loads(payload):
            raise RuntimeError(f"Refuse to overwrite existing evidence: {dest}")
    else:dest.write_text(payload)
    return dest

def cli(*args):
    res=subprocess.run([sys.executable,"scripts/research_session.py",*args,"--root","."],
                       cwd=ROOT,text=True,capture_output=True)
    if res.returncode:raise RuntimeError(res.stdout+res.stderr)
    return json.loads(res.stdout)

def record(tid):
    existing=ROOT/"run_log/research_sessions"/SID/"trials"/f"{tid}.json"
    if not existing.exists():
        cli("record","--session",SID,"--trial",tid,"--status","completed",
            "--artifact",f"run_log/{SID}/{tid}/result.json")

def source_calendar(calendar):
    """Author's last-calendar-day rollback, NOT prior nominal-30 rule."""
    bank=set(calendar["session"].to_list())
    assert bank
    labels={}
    for year in range(2020,2026):
        for month in range(1,13):
            boundary=date(year+1,1,1) if month==12 else date(year,month+1,1)
            month_end=boundary-timedelta(days=1)
            for which, day in [(f"nominal_{n}",date(year,month,n)) for n in NOMINAL]+[("last_calendar_day",month_end)]:
                current=day
                while current not in bank and current>=START:
                    current-=timedelta(days=1)
                if current>=START:
                    labels.setdefault(current,set()).add(which)
    author=(pl.DataFrame({"session":sorted(bank)}).with_columns(
        pl.col("session").is_in(list(labels)).alias("author_gotobi")))
    return author,labels

def load_data():
    snap=[ROOT/f"data/processed/tokyo_alpha_map_program1_v1/USDJPY_03_12_JST_{y}.parquet"
          for y in range(2020,2026)]
    for p in snap:
        if not p.is_file():raise RuntimeError("Missing immutable prior LSE source "+str(p))
    if not CALPATH.is_file() or not STRICT.is_file():raise RuntimeError("Missing original calendar or strict gate")
    raw=(pl.scan_parquet([str(p) for p in snap],hive_partitioning=False)
        .filter(pl.col("timestamp")<datetime(2025,12,31,15,tzinfo=UTC))
        .with_columns(pl.col("timestamp").dt.convert_time_zone("Asia/Tokyo").alias("jst"))
        .with_columns(pl.col("jst").dt.date().alias("session"),
                      (pl.col("jst").dt.hour().cast(pl.Int32)*60+
                       pl.col("jst").dt.minute().cast(pl.Int32)).alias("minute"))
        .filter(pl.col("session").is_between(START,END))
        .sort("timestamp").collect())
    if raw["timestamp"].is_duplicated().any():raise RuntimeError("Duplicate source minute timestamps")
    if raw["symbol"].unique().to_list()!=["USDJPY"]:raise RuntimeError("Wrong vendor symbol")
    valid=pl.all_horizontal([pl.col(c).is_finite() & (pl.col(c)>0)
                             for c in ["open","high","low","close"]]) & (
         pl.col("high")>=pl.max_horizontal("open","close")) & (
         pl.col("low")<=pl.min_horizontal("open","close"))
    if raw.filter(~valid.fill_null(False)).height:raise RuntimeError("OHLC geometry fail")
    cal=(pl.scan_parquet(CALPATH).filter(pl.col("session").is_between(START,END))
         .select("session","gotobi","ordinary","weekday","year","month_end")
         .collect().sort("session"))
    strict=(pl.scan_parquet(STRICT).filter(pl.col("session").is_between(START,END))
           .select("session",pl.col("complete").alias("old_strict"))
           .collect())
    auth,labels=source_calendar(cal)
    cal=(cal.join(auth,on="session",validate="1:1")
         .join(strict,on="session",how="left",validate="1:1")
         .with_columns(pl.col("old_strict").fill_null(False))
         .with_columns((~pl.col("author_gotobi")).alias("author_ordinary")))
    # A month-end is an author Gotobi date even when it is not a nominal 30th.
    assert cal.filter(pl.col("session")==date(2025,10,31))["author_gotobi"].to_list()==[True]
    assert any("last_calendar_day" in tag for tag in labels.values())
    daybars=raw.group_by("session").agg(
        pl.len().alias("observed_03_12_rows"),
        pl.col("minute").n_unique().alias("observed_03_12_distinct"),
        *[pl.col(col).filter(pl.col("minute")==minute).first().alias(f"{name}_{col}")
          for name,minute in [("m0300",180),("m0954",594),("m0955",595),
                              ("m0956",596),("m0959",599)]
          for col in ["open","close"]],
    )
    panel=cal.join(daybars,on="session",how="left").sort("session")
    manifest={"source_file_sha256":[{"path":str(p.relative_to(ROOT)),"sha256":sha(p),"bytes":p.stat().st_size} for p in snap],
              "calendar_sha256":sha(CALPATH),"strict_gate_sha256":sha(STRICT),
              "source_article":"https://www.alphainacademia.com/p/can-you-beat-the-market-by-trading",
              "source_companion":"Alpha in Academia Gotobi companion v1.0.3 METHODOLOGY.md",
              "companion_rules":"5 10 15 20 25 final-calendar-day; each rolled back; duplicate dates once; entry open 0300 exit close 0955",
              "paper_source":"HistData bid candles from fixed UTC-5 to JST 2006-2025; not available locally",
              "local_source":"LSE reference USDJPY UTC-minute-open 2020-2025; not HistData bid",
              "observed_price_rows":raw.height,"bank_days":panel.height,
              "author_scheduled_days":panel.filter(pl.col("author_gotobi")).height,
              "old_scheduled_days":panel.filter(pl.col("gotobi")).height,
              "retained_months":72,"holdout_read":False,
              "skills":["ml4t-polars-patterns","ml4t-calendar-ops","ml4t-point-in-time",
                        "ml4t-run-backtest","ml4t-validate-data","ml4t-cost-model",
                        "ml4t-backtest-overfitting"],
              "original_head":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()}
    artifact("T0_source_gate/result.json",manifest)
    panel.write_parquet(OUT/"event_panel.parquet")
    return raw,panel,labels,manifest

def arm(panel,selector,exit_price,require_strict=False):
    subset=panel.filter(selector)
    if require_strict:subset=subset.filter(pl.col("old_strict"))
    eligible=(pl.col("m0300_open").is_not_null() &
              pl.col(exit_price).is_not_null() &
              (pl.col("m0300_open")>0) & (pl.col(exit_price)>0))
    out=subset.filter(eligible).with_columns(
        ((pl.col(exit_price)-pl.col("m0300_open"))/PIP).alias("gross_pips"),
        ((pl.col(exit_price)-pl.col("m0300_open"))/pl.col("m0300_open")).alias("gross_return"))
    return out.sort("session")

def stats(fr,selector_count,cost=1.0):
    if not fr.height:
        return {"n":0,"status":"INCONCLUSIVE_NO_BARS","scheduled":selector_count}
    pnl=fr["gross_pips"]-cost
    r=(fr["gross_pips"]-cost)*PIP/fr["m0300_open"]
    pf=(float(pnl.filter(pnl>0).sum()) /
        abs(float(pnl.filter(pnl<0).sum()))) if len(pnl.filter(pnl<0)) else None
    first,last=fr["session"][0],fr["session"][-1]
    elapsed_years=max((last-first).days/365.25,1)
    event_per_year=fr.height/elapsed_years
    event_sharpe=(float(r.mean()/r.std(ddof=1)*math.sqrt(event_per_year))
                  if fr.height>1 and float(r.std(ddof=1))>0 else None)
    return {"n":fr.height,"scheduled":selector_count,"excluded":selector_count-fr.height,
            "gross_mean_pips":float(fr["gross_pips"].mean()),
            "net_mean_pips":float(pnl.mean()),
            "total_net_pips":float(pnl.sum()),
            "net_win_rate":float((pnl>0).mean()),
            "net_profit_factor":pf,
            "mean_net_return_on_entry_price":float(r.mean()),
            "author_event_annualized_sharpe":event_sharpe,
            "per_trade_gross_median_pips":float(fr["gross_pips"].median()),
            "cost_roundtrip_pips":cost}

def costladder(fr, scheduled):
    return [stats(fr,scheduled,c) for c in COSTS]

def fixed_bridge(panel):
    old=pl.col("gotobi")
    author=pl.col("author_gotobi")
    defs=[
        ("B0_previous_calendar_strict_0954open",old,"m0954_open",True),
        ("B1_paper_calendar_strict_0954open",author,"m0954_open",True),
        ("B2_paper_calendar_boundary_0954open",author,"m0954_open",False),
        ("B3_paper_calendar_boundary_0955open",author,"m0955_open",False),
        ("B4_paper_calendar_boundary_0955close",author,"m0955_close",False),
        ("B5_paper_calendar_boundary_0959close",author,"m0959_close",False),
    ]
    bridge=[]
    out={}
    for name,selector,exitname,strict in defs:
        rows=arm(panel,selector,exitname,strict)
        count=panel.filter(selector & (pl.col("old_strict") if strict else pl.lit(True))).height
        bridge.append({"name":name,"exit_price_column":exitname,
                      "strict":strict,**stats(rows,count)})
        out[name]=rows
    for name in ["B0_previous_calendar_strict_0954open",
                 "B1_paper_calendar_strict_0954open",
                 "B2_paper_calendar_boundary_0954open",
                 "B3_paper_calendar_boundary_0955open",
                 "B4_paper_calendar_boundary_0955close",
                 "B5_paper_calendar_boundary_0959close"]:
        rows=out[name]
        rows.select("session","year","weekday","gross_pips","gross_return").write_parquet(
            OUT/f"bridge_{name}.parquet")
    paired=[]
    for a,b in zip(bridge,bridge[1:]):
        x=out[a["name"]].select("session",pl.col("gross_pips").alias("start"))
        y=out[b["name"]].select("session",pl.col("gross_pips").alias("end"))
        matched=x.join(y,on="session",validate="1:1")
        paired.append({"from":a["name"],"to":b["name"],
                       "common":matched.height,
                       "start_only":x.height-matched.height,
                       "end_only":y.height-matched.height,
                       "matched_mean_delta_pips":float((matched["end"]-matched["start"]).mean()) if matched.height else None,
                       "cohort_mean_delta_pips":b["gross_mean_pips"]-a["gross_mean_pips"]})
    old_set=set(panel.filter(old)["session"].to_list())
    auth_set=set(panel.filter(author)["session"].to_list())
    shifts={"old_count":len(old_set),"author_count":len(auth_set),
            "in_both":len(old_set&auth_set),
            "old_only":sorted(x.isoformat() for x in old_set-auth_set),
            "author_only":sorted(x.isoformat() for x in auth_set-old_set)}
    result={"bridge":bridge,"pairs":paired,"calendar_event_changes":shifts}
    artifact("T2_bridge/result.json",result)
    return out,result

def hac(y,design=None):
    y=np.asarray(y,dtype=float)
    if design is None:design=np.ones((len(y),1))
    if len(y)<18 or np.linalg.matrix_rank(design)!=design.shape[1]:
        return {"status":"INSUFFICIENT","n":len(y)}
    fit=sm.OLS(y,design).fit(cov_type="HAC",cov_kwds={"maxlags":5},use_t=True)
    return {"status":"ESTIMATED","n":len(y),
            "coef":float(fit.params[0]),"ci95":fit.conf_int()[0].tolist(),
            "p":float(fit.pvalues[0])}

def control(panel,main):
    ordinary=arm(panel,pl.col("author_ordinary"),"m0955_close")
    joined=pl.concat([main,ordinary]).sort("session")
    if joined.height<30:raise RuntimeError("Too few dates for comparison")
    include=[joined["author_gotobi"].cast(pl.Float64).to_numpy(),np.ones(joined.height)]
    for col in ["weekday","year"]:
        for value in sorted(joined[col].unique().to_list())[1:]:
            include.append((joined[col]==value).cast(pl.Float64).to_numpy())
    dependent=((joined["gross_pips"]-1.0)*PIP/joined["m0300_open"]).to_numpy()
    outcome=hac(dependent,np.column_stack(include))
    base=hac(((main["gross_pips"]-1.0)*PIP/main["m0300_open"]).to_numpy())
    if base["status"]=="ESTIMATED" and outcome["status"]=="ESTIMATED":
        p=multipletests([base["p"],outcome["p"]],method="holm")[1]
        base["holm2_p"],outcome["holm2_p"]=map(float,p)
    byyear=main.with_columns((pl.col("gross_pips")-1.0).alias("net_pips")).group_by("year").agg(
        pl.len().alias("n"),pl.col("gross_pips").mean().alias("gross_mean"),
        pl.col("net_pips").mean().alias("net_mean"),
        pl.col("net_pips").sum().alias("total_net_pips")).sort("year").to_dicts()
    comp={"gotobi_mean_hac_net_return":base,"calendar_premium_hac_net_return":outcome,
          "gotobi_yearly":byyear,"ordinary_paper_rule":stats(ordinary,panel.filter(pl.col("author_ordinary")).height),
          "retrospective_2024_2025":stats(main.filter(pl.col("year").is_between(2024,2025)),
                                          panel.filter(pl.col("author_gotobi") & pl.col("year").is_between(2024,2025)).height),
          "multiplicity":"Holm2 only within this study; prior session count incomplete"}
    ordinary.select("session","gross_pips").write_parquet(OUT/"ordinary_paper_window.parquet")
    artifact("T3_ordinary_control/result.json",comp)
    return comp

class LongFix(Strategy):
    def __init__(self,dates):
        self.dates=set(dates)
        self.events=[]
    def on_start(self,broker):pass
    def on_data(self,timestamp,data,context,broker):
        here=timestamp.astimezone(JST)
        d=here.date()
        clock=here.hour*60+here.minute
        if d not in self.dates:
            assert broker.get_position("USDJPY") is None
            return
        if clock==179:
            assert broker.get_position("USDJPY") is None
            o=broker.submit_order("USDJPY",10000)
            if o is None:raise RuntimeError("No entry order")
            self.events.append((d,"entry",timestamp,o))
        if clock==595:
            assert broker.get_position("USDJPY") is not None
            o=broker.close_position("USDJPY")
            if o is None:raise RuntimeError("No exit order")
            self.events.append((d,"exit",timestamp,o))
    def on_end(self,broker):
        assert broker.get_position("USDJPY") is None

def native(calendar):
    # External previous data contain 02:59 decision bar and 09:56 next-open.
    dates=set(calendar.filter(pl.col("author_gotobi"))["session"].to_list())
    paths=[ROOT/f"data/processed/gotobi_paper_replication_20261011_v1/USDJPY_{y}.parquet"
           for y in range(2020,2026)]
    raw=(pl.scan_parquet(paths,hive_partitioning=False).filter(
        pl.col("session").is_in(dates) & pl.col("minute").is_in([179,180,595,596]))
         .select("timestamp","symbol","open","high","low","close","volume","session","minute")
         .sort("timestamp").collect())
    counts=raw.group_by("session").agg(pl.len().alias("rows"),
                        pl.col("minute").n_unique().alias("uniq"))
    good=counts.filter((pl.col("rows")==4)&(pl.col("uniq")==4))["session"].to_list()
    if not good:raise RuntimeError("No next-bar eligible dates")
    bars=raw.filter(pl.col("session").is_in(good))
    d=bars.select("timestamp","symbol","open","high","low","close","volume")
    start_jpy=10000*float(d["open"][0])
    strategy=LongFix(good)
    cfg=BacktestConfig(initial_cash=start_jpy,allow_leverage=True,
                       initial_margin=.5,execution_mode=ExecutionMode.NEXT_BAR,
                       execution_price=ExecutionPrice.OPEN,share_type=ShareType.FRACTIONAL,
                       commission_type=CommissionType.NONE,slippage_type=SlippageType.FIXED,
                       slippage_fixed=.005,partial_fills_allowed=False)
    run=Engine(DataFeed(prices_df=d),strategy,cfg).run()
    orders=pl.DataFrame([{"session":day,"role":role,"submitted_at":submission,
           "filled_at":order.filled_at,"filled_price":float(order.filled_price),
           "status":order.status.value,"qty":float(order.quantity)}
           for day,role,submission,order in strategy.events])
    assert orders.height==len(good)*2
    assert orders.filter(pl.col("status")!="filled").is_empty()
    a=orders.filter(pl.col("role")=="entry").select(
         "session",pl.col("filled_at").alias("entry_at"),
         pl.col("filled_price").alias("entry"))
    b=orders.filter(pl.col("role")=="exit").select(
         "session",pl.col("filled_at").alias("exit_at"),
         pl.col("filled_price").alias("exit"))
    source=bars.group_by("session").agg(
        pl.col("open").filter(pl.col("minute")==180).first().alias("src_entry"),
        pl.col("open").filter(pl.col("minute")==596).first().alias("src_exit"))
    trades=(a.join(b,on="session",validate="1:1")
            .join(source,on="session",validate="1:1").sort("session")
            .with_columns(((pl.col("exit")-pl.col("entry"))*10000).alias("pnl_jpy"))
            .with_columns((pl.col("pnl_jpy")/pl.col("exit")).alias("pnl_usd")))
    source_err=max(float((trades["entry"]-trades["src_entry"]-.005).abs().max()),
                   float((trades["exit"]-trades["src_exit"]+.005).abs().max()))
    assert source_err<1e-8
    assert all(x.astimezone(JST).hour==3 and x.astimezone(JST).minute==0 for x in trades["entry_at"])
    assert all(x.astimezone(JST).hour==9 and x.astimezone(JST).minute==56 for x in trades["exit_at"])
    err=abs(float(run.metrics["final_value"])-start_jpy-float(trades["pnl_jpy"].sum()))
    assert err<1e-4
    account=calendar.select("session").join(trades.select("session","pnl_usd"),
                           on="session",how="left").with_columns(pl.col("pnl_usd").fill_null(0))
    curve=account.with_columns((10000+pl.col("pnl_usd").cum_sum()).alias("balance"))
    eq=EquityCurve(
       [datetime.combine(calendar["session"][0]-timedelta(days=1),time.min,JST)]
       +[datetime.combine(dd,time.min,JST) for dd in curve["session"]],
       [10000]+curve["balance"].to_list(),periods_per_year_override=252)
    analyzer=TradeAnalyzer([SimpleNamespace(pnl=x,pnl_percent=x/10000,status="closed")
                            for x in trades["pnl_usd"]])
    summary={"n":trades.height,"expected_eligible_calendar":len(dates),
             "excluded_missing_4_boundary_bars":len(dates)-len(good),
             "net_usd":float(trades["pnl_usd"].sum()),"gross_avg_pips":float(
             ((trades["src_exit"]-trades["src_entry"])/PIP).mean()),
             "daily_sharpe":float(eq.sharpe),"profit_factor":float(analyzer.profit_factor),
             "source_fill_error":source_err,"native_jpy_reconciliation_error":err,
             "fixed_usd_notional":10000,"no_compounding":True,
             "native_execution":"market NEXT_BAR open at 03:00 and 09:56 with 0.5pip per-side adverse slippage",
             "not_exact_0955_close":"The publication close is used only in descriptive author markouts"}
    dest=OUT/"native"
    dest.mkdir(parents=True,exist_ok=True)
    orders.write_parquet(dest/"orders.parquet")
    trades.write_parquet(dest/"trades.parquet")
    curve.write_parquet(dest/"daily_equity.parquet")
    artifact("T4_native_market/result.json",summary)
    return summary

def main():
    status=cli("check","--session",SID)
    if status["status"]!="PASS":raise RuntimeError("Freeze audit rejected: "+str(status["status"]))
    OUT.mkdir(parents=True,exist_ok=True)
    raw,panel,labels,manifest=load_data()
    record("T0_source_gate")
    auth=arm(panel,pl.col("author_gotobi"),"m0955_close")
    auth.write_parquet(OUT/"author_paper_exact_trades.parquet")
    exact={"variants":costladder(auth,panel.filter(pl.col("author_gotobi")).height),
           "published_reference":{"histdata_period":"2006-2025","completed_events":1175,
                                  "gross_mean_pips":4.54,"net_mean_1pip":3.54},
           "limitations":"LSE 2020-2025, not HistData BID 2006-2025, paper closing-bar fill is descriptive",
           "source_rule":"03:00 open to 09:55 close; last calendar day rollback"}
    artifact("T1_author_exact/result.json",exact);record("T1_author_exact")
    bridge_data,bridge=fixed_bridge(panel);record("T2_bridge")
    control_data=control(panel,auth);record("T3_ordinary_control")
    native_data=native(panel);record("T4_native_market")
    overlap=auth.join(bridge_data["B0_previous_calendar_strict_0954open"].select(
        "session",pl.col("gross_pips").alias("old_gross")),on="session",how="inner")
    paired_delta=float((overlap["gross_pips"]-overlap["old_gross"]).mean()) if overlap.height else None
    # Deterministic calendar and source identity checks, no second portfolio simulator.
    key_sanity={
        "monthly_last_bank_day_included":all(
            max(panel.filter((pl.col("session").dt.year()==year) &
                       (pl.col("session").dt.month()==month))["session"].to_list())
            in labels for year in range(2020,2026) for month in range(1,13)),
        "article_date_rule_differs_from_prior":len(bridge["calendar_event_changes"]["author_only"])>0,
        "all_source_scheduled_dates_unique":len(labels)==len(set(labels)),
        "max_observed_source_timestamp_before_holdout":str(raw["timestamp"].max()),
        "no_holdout_ever_read":True,
        "native_fill_error":native_data["source_fill_error"],
        "accounting_error":native_data["native_jpy_reconciliation_error"],
        "bridge_common_old_to_exact_n":overlap.height,
        "common_old_vs_exact_return_pips_delta":paired_delta,
    }
    assert all([key_sanity["monthly_last_bank_day_included"],
                key_sanity["article_date_rule_differs_from_prior"],
                key_sanity["all_source_scheduled_dates_unique"]])
    artifact("T5_independent_audit/result.json",key_sanity);record("T5_independent_audit")
    base=bridge["bridge"][0];paper=exact["variants"][2]
    p24=control_data["retrospective_2024_2025"]
    line=[
        "# Gotobi research companion v1.0.3: exact-method LSE replication bridge",
        "",
        "**Status: COMPLETED / EXPLORATORY / NOT_APPROVED.**",
        "",
        "We reproduced the original companion's date and bar arithmetic on the",
        "available 2020-2025 canonical LSE one-minute OHLCV, not its original",
        "HistData fixed-UTC-5 bid candles over 2006-2025. The latter source",
        "and 2006-2019 interval cannot be claimed reproduced by this run.",
        "",
        "## Original author source",
        "",
        "Original companion v1.0.3 `METHODOLOGY.md`:",
        "- Nominal 5/10/15/20/25/final CALENDAR date; roll each back to last Japan bank day.",
        "- Enter USDJPY long at 03:00 JST OPEN.",
        "- Exit 09:55 JST minute-bar CLOSE; not the 09:54/09:55 OPEN.",
        "- Require only the entry bar and the chosen exit bar, not all 416 intermediate bars.",
        "- Cost ladder 0, 0.4, 1.0, 1.5 hypothetical pips.",
        "- Source profit factors and event-annualized Sharpe are not continuous-account metrics.",
        "",
        "## Fixed bridge: 2020-2025 LSE reference feed",
        "",
        "| Rule change | Completed | Gross pips/trade | Net pips/trade @ 1pip |",
        "|---|---:|---:|---:|"
    ]
    for item in bridge["bridge"]:
        line.append(f"| {item['name']} | {item['n']} | {item['gross_mean_pips']:+.3f} | {item['net_mean_pips']:+.3f} |")
    line+=["","## Matched-date bridge (not a causal decomposition)","","| Change | Shared dates | New cohort | Matched gross delta | Cohort gross delta |",
           "|---|---:|---:|---:|---:|"]
    for x in bridge["pairs"]:
        line.append(f"| {x['from']} -> {x['to']} | {x['common']} | {x['end_only']} | "
                    f"{x['matched_mean_delta_pips']:+.3f} | {x['cohort_mean_delta_pips']:+.3f} |")
    line+=["",
         "## Author exact rule, paper-style statistics on LSE",
         "",
         f"- Author scheduled events: **{paper['scheduled']}**.",
         f"- Complete exact-price windows: **{paper['n']}**; incomplete: {paper['excluded']}.",
         f"- Gross mean **{paper['gross_mean_pips']:+.3f} pips**.",
         f"- Mean after 1pip hypothetical round trip: **{paper['net_mean_pips']:+.3f} pips**.",
         f"- Event-annualized Sharpe (author convention) **{paper['author_event_annualized_sharpe']:.3f}**.",
         f"- Published HistData 2006-2025: 1,175 events and +4.54 gross pips, which is a distinct provider/period.",
         "",
         "## Comparison with ordinary mornings and weak years",
         "",
         f"- Same-clock ordinary business days, exact close: mean gross {control_data['ordinary_paper_rule']['gross_mean_pips']:+.3f} pips, n={control_data['ordinary_paper_rule']['n']}.",
         f"- Controlled Gotobi premium HAC5: {control_data['calendar_premium_hac_net_return']}.",
         f"- Gotobi absolute net-return HAC5: {control_data['gotobi_mean_hac_net_return']}.",
         f"- Retrospective 2024-25: n={p24['n']}, gross {p24['gross_mean_pips']:+.3f} pips, net {p24['net_mean_pips']:+.3f} pips/trade.",
         "",
         "| Year | Trades | Mean gross pips | Mean net pips |",
         "|---|---:|---:|---:|"]
    for year in control_data["gotobi_yearly"]:
        line.append(f"| {year['year']} | {year['n']} | {year['gross_mean']:+.3f} | {year['net_mean']:+.3f} |")
    line+=["",
        "## Separate native ML4T market execution",
        "",
        f"- Native 03:00 OPEN to 09:56 OPEN, 1pip hypothetical cost: n={native_data['n']} and PnL USD {native_data['net_usd']:+.2f}.",
        f"- Native account Sharpe (flat-inclusive) {native_data['daily_sharpe']:+.3f}, not the author's event-annualized statistic.",
        f"- Native/source fill error < {native_data['source_fill_error']:.2g} JPY, JPY account reconciliation < {native_data['native_jpy_reconciliation_error']:.2g}.",
        "- The exact paper 09:55 close is a bar-field price, **not verified executable at that close**.",
        "- Canonical LSE OHLCV is not the paper's HistData bid feed. Real broker quotes/cost remain unknown.",
        "- The 2020-2025 LSE period was already inspected in earlier Gotobi programs; NOT new unseen OOS.",
        "- No Sept-Oct2026 protected data were read, no commit/push, no live order.",
        "",
        "## Reproduction",
        "",
        f"- Frozen declaration: `config/research_sessions/{SID}.yaml`.",
        f"- Source manifest: `run_log/{SID}/T0_source_gate/result.json`.",
        f"- Exact paper event ledger: `run_log/{SID}/author_paper_exact_trades.parquet`.",
        f"- Native executed orders/trades: `run_log/{SID}/native/`.",
        f"- Trial evidence: `run_log/{SID}/T*/result.json`.",
        "",
        "**Decision: research discrepancy audited; no trading strategy qualified.**",
    ]
    report=ROOT/"docs/audit"/f"{SID}.md"
    if report.exists():raise RuntimeError("Refuse overwrite existing audit")
    report.write_text("\n".join(line)+"\n")
    artifact("T6_report/result.json",
             {"report":str(report.relative_to(ROOT)),
              "original_gross_pips":4.54,"local_gross_pips":paper["gross_mean_pips"],
              "local_net1":paper["net_mean_pips"],
              "2024_2025_net1":p24["net_mean_pips"],
              "status":"EXPLORATORY_NOT_APPROVED","no_holdout_read":True})
    record("T6_report")
    print(json.dumps({"status":"COMPLETE","paper_exact":paper,
                      "bridge":[{"name":v["name"],"n":v["n"],
                                 "gross":v["gross_mean_pips"]} for v in bridge["bridge"]],
                      "ordinary":control_data["ordinary_paper_rule"]["gross_mean_pips"],
                      "year_2024_2025":p24["net_mean_pips"],
                      "native_net_usd":native_data["net_usd"]},indent=2),flush=True)

if __name__=="__main__":
    main()
