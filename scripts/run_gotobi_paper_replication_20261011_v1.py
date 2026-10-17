"""Replicate paper's pre-fix Gotobi claim in native ML4T. All results retrospective."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
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
SID = "gotobi_paper_replication_20261011_v1"
DATA = ROOT / "data/processed" / SID
OUT = ROOT / "run_log" / SID
JST = ZoneInfo("Asia/Tokyo")
BOUND = datetime(2026, 8, 31, 15, tzinfo=timezone.utc)
STORE = Path("/home/quant/dev/quant/ml4t-data/.data/store/forex_minute_USDJPY")
CAL = ROOT / "run_log/tokyo_fix_alpha_map_program1_20261010/execution_v1/calendar_event_registry.parquet"
SOURCE_DOC_SHA = "9b6e885ce106c72afe25beb53849ebdcc16dd5e3463bc7442f8f392a4e46a2e5"

def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1048576), b""):
            h.update(block)
    return h.hexdigest()

def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(obj, indent=2, default=str, allow_nan=False) + "\n"
    if path.exists():
        if json.loads(path.read_text()) != json.loads(payload):
            raise RuntimeError(f"Refuse overwrite: {path}")
        return
    path.write_text(payload)

def cli(*cmd):
    p = subprocess.run([sys.executable, "scripts/research_session.py", *cmd, "--root", "."],
                       cwd=ROOT, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError("Session CLI: " + p.stdout + p.stderr)
    return json.loads(p.stdout)

def prepare():
    if (OUT / "source_manifest.json").exists():
        raise RuntimeError("Preparation already exists; do not regenerate immutable sources")
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    sources = []
    for year in range(2020, 2027):
        files = sorted(p for month in range(1, 9 if year == 2026 else 13)
                       for p in (STORE / f"year={year}" / f"month={month}").rglob("data.parquet"))
        if not files:
            raise RuntimeError(f"Missing local canonical LSE USDJPY {year}")
        data = (pl.scan_parquet(files, hive_partitioning=False)
                .filter(pl.col("timestamp") < BOUND)
                .with_columns(pl.col("timestamp").dt.convert_time_zone("Asia/Tokyo").alias("jst"))
                .filter(pl.col("jst").dt.year() == year)
                .with_columns(pl.col("jst").dt.date().alias("session"),
                              (pl.col("jst").dt.hour().cast(pl.Int32) * 60 + pl.col("jst").dt.minute().cast(pl.Int32)).alias("minute"))
                .filter(pl.col("minute").is_between(178, 596))
                .select("timestamp", "symbol", "open", "high", "low", "close", "volume",
                        "session", "minute")
                .sort("timestamp").collect())
        if data.is_empty() or data["timestamp"].is_duplicated().any():
            raise RuntimeError(f"Invalid/empty dataset {year}")
        if data["symbol"].unique().to_list() != ["USDJPY"]:
            raise RuntimeError("Provider symbol mismatch")
        path = DATA / f"USDJPY_{year}.parquet"
        if path.exists():
            raise RuntimeError("Refuse overwrite existing dataset")
        data.write_parquet(path, compression="zstd")
        sources.append({"path": str(path.relative_to(ROOT)), "sha256": sha(path),
                        "rows": data.height, "min": str(data["timestamp"].min()),
                        "max": str(data["timestamp"].max()),
                        "provider": "existing canonical LSE; research price not broker quotes",
                        "source_paths": [str(p) for p in files]})
        print("PREP", year, data.height, flush=True)
    write_json(OUT / "source_manifest.json", {
        "files": sources, "calendar": {"path": str(CAL.relative_to(ROOT)), "sha256": sha(CAL)},
        "uploaded_source_sha256": SOURCE_DOC_SHA, "uploaded_filename": "gotobi_usdjpy_ml4t_strategy_spec.md",
        "article": "https://www.alphainacademia.com/p/can-you-beat-the-market-by-trading",
        "article_corrected_period": "2006-2025 per July 27 2026 revision",
        "attachment_claimed_period": "2004-2024 (conflicts with source)",
        "source_basis": "USDJPY 1m, UTC bar-open timestamps, early-morning LSE proxy",
        "holdout_read": False, "hard_utc_max_exclusive": BOUND.isoformat(),
        "prior_research": "Program1/2/3/4A 2020-Aug2026 already evaluated, no fresh OOS"})
    write_json(OUT / "methodology.json", {
        "skills_read": ["ml4t-strategy-workflow", "ml4t-run-backtest", "ml4t-cost-model",
                        "ml4t-calendar-ops", "ml4t-validate-data", "ml4t-point-in-time",
                        "ml4t-lookahead-bias", "ml4t-sensitivity-analysis"],
        "invariants": ["minute-open UTC/JST clock", "next-bar only", "holiday rollback fixed",
                       "same-day no carry", "fixed USD10000", "quote JPY to USD conversion",
                       "no Sept/Oct2026", "failed trial ledger retained"],
        "current_repository_head": subprocess.check_output(["git", "rev-parse", "HEAD"],cwd=ROOT,text=True).strip(),
        "native_backtest_version": "0.1.7 as inspected Oct11",
        "known_limitation": "No firm historic executable bid/ask or queue data, zero intraday financing assumption"})

def freeze():
    write_json(OUT / "freeze_init.json", cli("init", "--spec", f"config/research_sessions/{SID}.yaml"))
    write_json(OUT / "freeze_check.json", cli("check", "--session", SID))
    print("FROZEN", flush=True)

def inputs():
    manifest = json.loads((OUT / "source_manifest.json").read_text())
    for obj in manifest["files"]:
        p = ROOT / obj["path"]
        if sha(p) != obj["sha256"]:
            raise RuntimeError(f"Data identity changed: {p}")
    if sha(CAL) != manifest["calendar"]["sha256"]:
        raise RuntimeError("Calendar hash drift")
    raw = pl.concat([pl.read_parquet(ROOT / obj["path"]) for obj in manifest["files"]]).sort("timestamp")
    assert raw["timestamp"].max() < BOUND
    cal = (pl.read_parquet(CAL).filter(pl.col("session") < date(2026, 9, 1))
           .select("session", "gotobi", "ordinary", "weekday", "year").sort("session"))
    valid = (pl.all_horizontal([pl.col(x).is_finite() & (pl.col(x) > 0)
                                for x in ["open", "high", "low", "close"]])
             & (pl.col("high") >= pl.max_horizontal("open", "close"))
             & (pl.col("low") <= pl.min_horizontal("open", "close")))
    raw = raw.with_columns(valid.fill_null(False).alias("valid"))
    quality = raw.filter(pl.col("minute").is_between(178, 596)).group_by("session").agg(
        pl.len().alias("rows"), pl.col("minute").n_unique().alias("unique"),
        pl.col("valid").sum().alias("valid"))
    gates = (cal.join(quality, on="session", how="left")
             .with_columns(pl.col("rows", "unique", "valid").fill_null(0))
             .with_columns(((pl.col("rows") == 419) & (pl.col("unique") == 419)
                           & (pl.col("valid") == 419)).alias("complete")))
    data_quality = {
        "total_bank_dates": cal.height, "complete_dates": gates.filter(pl.col("complete")).height,
        "complete_fraction": gates["complete"].mean(),
        "complete_gotobi": gates.filter(pl.col("complete") & pl.col("gotobi")).height,
        "complete_ordinary": gates.filter(pl.col("complete") & pl.col("ordinary")).height,
        "year": gates.group_by("year", "gotobi", "complete").len().sort("year", "gotobi", "complete").to_dicts(),
        "raw_rows": raw.height, "source_duplicate_timestamps": int(raw["timestamp"].is_duplicated().sum()),
        "source_invalid_ohlc": raw.filter(~pl.col("valid")).height,
        "zero_vendor_volume": raw.filter(pl.col("volume") == 0).height,
        "timezone": "Asia/Tokyo no DST; original UTC timestamps minute OPEN",
        "no_imputation": True, "holdout_read": False,
        "predeclared_gate": "Every minute 02:58-09:56 complete, valid OHLC geometry, inclusive"}
    write_json(OUT / "T0_data_gate/result.json", data_quality)
    gates.write_parquet(OUT / "eligible_bank_dates.parquet")
    return raw, cal, gates

class EarlyLong(Strategy):
    def __init__(self, dates, exit_minute):
        self.dates = set(dates)
        self.exit_minute = exit_minute
        self.events = []
    def on_start(self, broker):
        pass
    def on_data(self, timestamp, data, context, broker):
        here = timestamp.astimezone(JST)
        day = here.date()
        minute = here.hour * 60 + here.minute
        if day not in self.dates:
            assert broker.get_position("USDJPY") is None
            return
        if minute == 179:
            assert broker.get_position("USDJPY") is None
            order = broker.submit_order("USDJPY", 10000)
            if order is None:
                raise RuntimeError("Entry rejected")
            self.events.append((day, "entry", timestamp, order))
        if minute == self.exit_minute-1:
            assert broker.get_position("USDJPY") is not None
            order = broker.close_position("USDJPY")
            self.events.append((day, "exit", timestamp, order))
        if minute >= self.exit_minute:
            assert broker.get_position("USDJPY") is None
    def on_end(self, broker):
        assert broker.get_position("USDJPY") is None

def native(raw, cal, gates, name, category, cost, exit_minute):
    folder = OUT / "runs" / name
    eligible = gates.filter(pl.col("complete") & pl.col(category))["session"].to_list()
    if not eligible:
        raise RuntimeError("No eligible dates")
    bars = raw.filter(pl.col("session").is_in(eligible) & pl.col("minute").is_between(178, 596))
    df = bars.select("timestamp", "symbol", "open", "high", "low", "close", "volume")
    init_jpy = 10000 * float(df["open"][0])
    strategy = EarlyLong(eligible, exit_minute)
    cfg = BacktestConfig(initial_cash=init_jpy, allow_leverage=True, initial_margin=0.5,
                         execution_mode=ExecutionMode.NEXT_BAR, execution_price=ExecutionPrice.OPEN,
                         share_type=ShareType.FRACTIONAL, commission_type=CommissionType.NONE,
                         slippage_type=SlippageType.FIXED, slippage_fixed=cost * .01 / 2,
                         partial_fills_allowed=False)
    engine_result = Engine(DataFeed(prices_df=df), strategy, cfg).run()
    rows = pl.DataFrame([
        {"session": day, "role": role, "submitted_at": sub, "filled_at": o.filled_at,
         "filled_price": o.filled_price, "qty": o.quantity, "status": o.status.value}
        for day, role, sub, o in strategy.events]).sort("submitted_at")
    assert rows.height == 2*len(eligible) and rows.filter(pl.col("status") != "filled").is_empty()
    a = rows.filter(pl.col("role") == "entry").select("session",pl.col("filled_price").alias("entry"),
                                                     pl.col("filled_at").alias("entry_at"))
    z = rows.filter(pl.col("role") == "exit").select("session",pl.col("filled_price").alias("exit"),
                                                    pl.col("filled_at").alias("exit_at"))
    orig = bars.group_by("session").agg(
        pl.col("open").filter(pl.col("minute")==180).first().alias("src_entry"),
        pl.col("open").filter(pl.col("minute")==exit_minute).first().alias("src_exit"))
    trades = (a.join(z,on="session",validate="1:1").join(orig,on="session",validate="1:1")
             .join(cal,on="session",validate="1:1").sort("session")
             .with_columns(((pl.col("src_exit")-pl.col("src_entry"))/.01).alias("gross_pips"),
                           ((pl.col("exit")-pl.col("entry"))/.01).alias("net_pips"),
                           ((pl.col("exit")-pl.col("entry"))*10000).alias("pnl_jpy"))
             .with_columns((pl.col("pnl_jpy")/pl.col("exit")).alias("pnl_usd")))
    oracle_buy = trades["src_entry"]+cost*.005
    oracle_sell= trades["src_exit"]-cost*.005
    err = max(float((trades["entry"]-oracle_buy).abs().max()),
              float((trades["exit"]-oracle_sell).abs().max()))
    assert err < 1e-7
    assert all(t.astimezone(JST).minute == 0 and t.astimezone(JST).hour == 3
               for t in trades["entry_at"])
    assert all(t.astimezone(JST).hour==9 and t.astimezone(JST).minute == exit_minute-540
               for t in trades["exit_at"])
    recon = float(engine_result.metrics["final_value"])-init_jpy
    recon_err = abs(recon-float(trades["pnl_jpy"].sum()))
    assert recon_err < 1e-4
    daily = (cal.select("session").join(trades.select("session","pnl_usd"),on="session",how="left")
             .with_columns(pl.col("pnl_usd").fill_null(0))
             .with_columns((10000+pl.col("pnl_usd").cum_sum()).alias("equity_usd")))
    times = ([datetime.combine(cal["session"][0]-timedelta(days=1),datetime.min.time(),JST)]
             +[datetime.combine(d,datetime.min.time(),JST) for d in daily["session"]])
    curve= EquityCurve(times,[10000]+daily["equity_usd"].to_list(),periods_per_year_override=252)
    analyzer=TradeAnalyzer([SimpleNamespace(pnl=p,pnl_percent=p/10000,status="closed")
                            for p in trades["pnl_usd"]])
    byyear=trades.group_by("year").agg(pl.len().alias("n"),pl.col("gross_pips").mean(),
                             pl.col("net_pips").mean(),pl.col("pnl_usd").sum()).sort("year").to_dicts()
    stats={"name":name,"group":category,"cost_pips":cost,"exit_jst":f"09:{exit_minute-540:02d}",
           "n":trades.height,"mean_gross_pips":float(trades["gross_pips"].mean()),
           "mean_net_pips":float(trades["net_pips"].mean()),"net_usd":float(trades["pnl_usd"].sum()),
           "final_usd_equity":float(daily["equity_usd"][-1]),
           "daily_sharpe_flat_inclusive":float(curve.sharpe),
           "max_closed_equity_dd_pct":float(curve.max_dd*100),
           "win_rate":float(analyzer.win_rate),"profit_factor":float(analyzer.profit_factor),
           "years":byyear,"native_orders":rows.height,
           "native_jpy_pnl":recon,"reconciliation_error_jpy":recon_err,
           "fill_source_error_jpy":err, "holdout_read":False}
    folder.mkdir(parents=True,exist_ok=True)
    rows.write_parquet(folder/"orders.parquet")
    trades.write_parquet(folder/"trades.parquet")
    daily.write_parquet(folder/"daily.parquet")
    write_json(folder/"result.json", stats)
    print("NATIVE",name,stats["n"],round(stats["net_usd"],3),flush=True)
    return stats,trades

def hac(y, x=None):
    y=np.asarray(y,dtype=float)
    x=np.ones((len(y),1)) if x is None else np.asarray(x,dtype=float)
    if len(y) < 20 or np.linalg.matrix_rank(x) != x.shape[1]:
        return {"status":"INSUFFICIENT","n":len(y)}
    m=sm.OLS(y,x).fit(cov_type="HAC",cov_kwds={"maxlags":5},use_t=True)
    return {"status":"ESTIMATED","n":len(y),"coefficient":float(m.params[0]),
            "lower95":float(m.conf_int()[0,0]),"upper95":float(m.conf_int()[0,1]),
            "p":float(m.pvalues[0])}

def record(trial):
    artifact=f"run_log/{SID}/{trial}/result.json"
    terminal=ROOT/f"run_log/research_sessions/{SID}/trials/{trial}.json"
    if terminal.exists():
        return
    cli("record","--session",SID,"--trial",trial,"--status","completed","--artifact",artifact)

def run():
    ck=cli("check","--session",SID)
    if ck["status"]!="PASS":
        raise RuntimeError("Frozen session gate failed: "+str(ck))
    raw,cal,gates=inputs()
    record("T0_data_gate")
    g,gt=native(raw,cal,gates,"gotobi_1pip","gotobi",1.0,594)
    write_json(OUT/"T1_main_native/result.json",g); record("T1_main_native")
    o,ot=native(raw,cal,gates,"ordinary_1pip","ordinary",1.0,594)
    write_json(OUT/"T2_ordinary_native/result.json",o); record("T2_ordinary_native")
    costs=[g]
    for c in [0.0,1.5,2.0]:
        costs.append(native(raw,cal,gates,f"gotobi_{str(c).replace('.','p')}pip","gotobi",c,594)[0])
    bounds=[native(raw,cal,gates,f"gotobi_exit{m}_1pip","gotobi",1.0,m)[0]
            for m in [595,596]]
    write_json(OUT/"T3_cost_and_boundary/result.json",{"cost_ladder":costs,"exit_boundary":bounds})
    record("T3_cost_and_boundary")
    full=pl.concat([gt,ot]).sort("session")
    columns=[full["gotobi"].cast(pl.Float64).to_numpy(),np.ones(full.height)]
    for key in ["weekday","year"]:
        for val in sorted(full[key].unique().to_list())[1:]:
            columns.append((full[key]==val).cast(pl.Float64).to_numpy())
    test_main=hac(gt["pnl_usd"])
    test_premium=hac(full["pnl_usd"],np.column_stack(columns))
    adj=multipletests([test_main["p"],test_premium["p"]],method="holm")[1]
    test_main["holm2_p"]=float(adj[0])
    test_premium["holm2_p"]=float(adj[1])
    periods={}
    for label, filter_ in [
        ("development_2020_2023",pl.col("year")<=2023),
        ("retrospective_2024_2025",pl.col("year").is_between(2024,2025)),
        ("observed_2026_jan_aug",pl.col("year")==2026)]:
        sample=gt.filter(filter_)
        periods[label]={"n":sample.height,"net_usd":float(sample["pnl_usd"].sum()),
                        "net_pips_mean":float(sample["net_pips"].mean()) if sample.height else None}
    passed={
        "absolute_hac_lower_gt_0":test_main["lower95"]>0,
        "calendar_holm_p_lt_05":test_premium["coefficient"]>0 and test_premium["holm2_p"]<.05,
        "net_usd_gt_0":g["net_usd"]>0,
        "stable_2024_2025":periods["retrospective_2024_2025"]["net_usd"]>0,
        "stable_2026":periods["observed_2026_jan_aug"]["net_usd"]>0,
        "net_1p5pip_gt_0":next(x for x in costs if x["cost_pips"]==1.5)["net_usd"]>0,
        "completeness_ge_70pct":json.loads((OUT/"T0_data_gate/result.json").read_text())["complete_fraction"]>=.7}
    verdict="PASSED_EXPLORATORY_ONLY" if all(passed.values()) else "REJECTED_OR_INCONCLUSIVE"
    refutation={"gotobi_hac":test_main,"controlled_gotobi_premium_hac":test_premium,
                "periods":periods,"frozen_checks":passed,"decision":verdict,
                "existing_trial_multiplicity":"Historical Program1/2/3/4 already explored; Holm2 does not correct complete trial family",
                "mechanism_identified":False,"holdout_read":False}
    write_json(OUT/"T4_refutation/result.json",refutation);record("T4_refutation")
    audit={"source_fill_oracle_max_error_jpy":max(x["fill_source_error_jpy"] for x in costs+bounds+[o]),
           "native_jpy_reconciliation_max_error":max(x["reconciliation_error_jpy"] for x in costs+bounds+[o]),
           "native_runs":len(costs)+len(bounds)+1,"trades_reconciled":sum(x["n"] for x in costs+bounds+[o]),
           "all_fill_orders":sum(x["native_orders"] for x in costs+bounds+[o]),
           "native_engine":True,"no_custom_portfolio_simulation":True,
           "holdout_read":False}
    write_json(OUT/"T5_independent_audit/result.json",audit);record("T5_independent_audit")
    report=f"""# Gotobi paper replication - native USDJPY pre-fix MVP

**Decision: {verdict}. EXPLORATORY; NOT_APPROVED for live trading.**

## Source vs claims

The uploaded 1.0.0 strategy specification cites 2004-2024, but the
Alpha in Academia article corrected July 27, 2026 uses 2006-2025,
1,175 complete events, and reports +4.54 gross pips per trade for
03:00 JST open to 09:55 minute bar close. Its publisher specifically
does not claim observed customer orders, dealer hedges, non-Gotobi
controls, or executable broker spreads. The attached LightGBM, passive
execution, intraday spreads, and 16 production controls are proposals,
not source-tested profits.

## Local method

Canonical LSE UTC-open one-minute USDJPY, 2020-Aug2026 only.
Official Japanese bank calendar inherited unchanged. Every minute
02:58-09:56 required. Primary 03:00 native next-bar market BUY,
09:54 native next-bar market SELL; 1 pip all-in fixed adverse fill.
Fixed USD10,000 base, USD10,000 reference equity, no compounding.
JPY native ledger; exit-price USD conversion; cash and ordinary
same-window long as baselines. This pre-fix exit is intentionally
earlier than the article's 09:55-bar CLOSE and is not claimed exact
publication-rule replication. Native 09:55 and 09:56-open sensitivity
checks are separately recorded.

## Primary outcomes

- Eligible: {json.loads((OUT/'T0_data_gate/result.json').read_text())['complete_dates']} of {cal.height} banking dates
  ({100*json.loads((OUT/'T0_data_gate/result.json').read_text())['complete_fraction']:.1f}%);
  Gotobi {gt.height}, ordinary {ot.height}.
- Gotobi gross {g['mean_gross_pips']:+.3f} pips/trade, net {g['mean_net_pips']:+.3f},
  USD PnL {g['net_usd']:+.2f}, net PF {g['profit_factor']:.3f},
  flat-inclusive daily Sharpe {g['daily_sharpe_flat_inclusive']:.3f}.
- Ordinary gross {o['mean_gross_pips']:+.3f}, net {o['mean_net_pips']:+.3f} pips/trade,
  USD PnL {o['net_usd']:+.2f}.
- Gotobi net HAC mean: {test_main['coefficient']:+.3f} USD/trade,
  95% CI [{test_main['lower95']:+.3f}, {test_main['upper95']:+.3f}],
  p={test_main['p']:.4g}.
- Controlled Gotobi minus ordinary: {test_premium['coefficient']:+.3f} USD/trade,
  HAC 95% CI [{test_premium['lower95']:+.3f}, {test_premium['upper95']:+.3f}],
  Holm2 p={test_premium['holm2_p']:.4g}.
- Development 2020-23: {periods['development_2020_2023']['net_usd']:+.2f} USD;
  retrospective 2024-25: {periods['retrospective_2024_2025']['net_usd']:+.2f} USD;
  inspected 2026 Jan-Aug: {periods['observed_2026_jan_aug']['net_usd']:+.2f} USD.
- At 1.5 pips, net USD {next(x for x in costs if x['cost_pips']==1.5)['net_usd']:+.2f};
  at 2.0 pips, {next(x for x in costs if x['cost_pips']==2.0)['net_usd']:+.2f}.
- Frozen checks: {json.dumps(passed,sort_keys=True)}.

## Interpretation

No September-October 2026 protected observations were loaded.
All 2020-Aug2026 observations have already been examined in previous
Gotobi programs. Low early-morning bar coverage and unknown executable
broker costs constrain any inference beyond the retained cohort.
No customer-order-flow measurements or truly independent non-price
predictive features are present. HOLM2 applies only to this session;
full historical selection adjustment is not reproducible.

## Reproduction

- YAML: config/research_sessions/{SID}.yaml
- Runner: scripts/run_{SID}.py
- Frozen CLI: run_log/{SID}/freeze_init.json
- Source identities: run_log/{SID}/source_manifest.json
- Native ledgers: run_log/{SID}/runs/*/
- Event, cost, audit, trial evidence: run_log/{SID}/T*/result.json
- Native order and source-price oracle: {audit['all_fill_orders']} orders checked,
  max source error {audit['source_fill_oracle_max_error_jpy']:.3g} JPY,
  max cash reconciliation error {audit['native_jpy_reconciliation_max_error']:.3g} JPY.

**Next experiment:** prospective broker executable USDJPY quotes and market
fills at 02:59-09:55 JST, with Gotobi/ordinary comparison and previously
fixed entry/exit decisions. Do not unlock the September-October 2026
protected period to retune this mechanism.
"""
    path=ROOT/f"docs/audit/{SID}.md"
    if path.exists():
        if path.read_text()!=report:
            raise RuntimeError("Refuse overwrite final report")
    else:
        path.write_text(report)
    write_json(OUT/"T6_final_report/result.json",{"decision":verdict,"report":str(path.relative_to(ROOT)),
                                                 "checks":passed,"holdout_read":False})
    record("T6_final_report")
    print(json.dumps({"decision":verdict,"gotobi_net_usd":g["net_usd"],"gotobi_n":g["n"],
                      "ordinary_net_usd":o["net_usd"],"checks":passed},indent=2),flush=True)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("mode",choices=["prepare","freeze","run"])
    mode=p.parse_args().mode
    {"prepare":prepare,"freeze":freeze,"run":run}[mode]()

if __name__=="__main__":
    main()
