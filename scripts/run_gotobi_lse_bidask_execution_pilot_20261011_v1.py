"""Frozen April 2020-2026 quote-aware native ML4T execution pilot.

Fail closed until all fourteen external LSE raw bid/ask exports exist,
pass completeness/sha gates, and are frozen in the session CLI.
Never opens September/October2026 protected holdout.
"""
from __future__ import annotations
import hashlib
import json
import subprocess
import sys
from datetime import date, timedelta, datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests

import run_gotobi_lse_bidask_smoke_20261011 as core

ROOT = Path(__file__).resolve().parents[1]
SID = "gotobi_lse_bidask_execution_pilot_20261011_v1"
OUT = ROOT / "run_log" / SID / "full"
SRC = core.SOURCE / "months"
SPEC = ROOT / "config/research_sessions" / f"{SID}.yaml"
CAL = core.CAL

def planned():
    for year in range(2020,2027):
        for a,b in [("04-01","04-08"),("04-08","04-15")]:
            yield f"{year}-{a}",f"{year}-{b}"

def read_gate():
    missing=[]
    failed=[]
    found=[]
    for start,end in planned():
        base=SRC/f"{start}_{end}"
        meta=base/"manifest.json"
        parquet=base/"fx_USD_JPY_tick.parquet"
        if not meta.exists() or not parquet.exists():
            missing.append({"start":start,"end":end,"reason":"no validated raw tick export"})
            continue
        try:
            manifest=json.loads(meta.read_text())
            assert manifest["interval"]==[start,end]
            assert manifest["rows"]>0 and manifest["rows"]<2500000
            assert set(manifest["schema"])=={"ts","symbol","bid","ask"}
            assert core.sha(parquet)==manifest["sha256"]
            last=datetime.fromisoformat(manifest["last"])
            bound=datetime.fromisoformat(end+"T00:00:00+00:00")
            assert bound-timedelta(hours=70)<=last<bound
            assert manifest["crossed"]==0
            found.append({"start":start,"end":end,"path":str(parquet),
                          "sha256":manifest["sha256"],"rows":manifest["rows"],
                          "last":manifest["last"]})
        except Exception as e:
            failed.append({"start":start,"end":end,"reason":str(e)})
    return {"status":"PASS" if not missing and not failed else "BLOCKED",
            "required_exports":14,"accepted_exports":len(found),
            "missing":missing,"failed":failed,"sources":found,
            "export_row_cap":2500000,
            "clock":"UTC raw seconds, simulated JST executions",
            "date_bounds":"2020-2026 April2-14 JST; every year identical",
            "holdout_read":False}

def cli(*args):
    p=subprocess.run([sys.executable,"scripts/research_session.py",*args,"--root","."],
                     cwd=ROOT,capture_output=True,text=True)
    if p.returncode:raise RuntimeError(p.stdout+p.stderr)
    return json.loads(p.stdout)

def hac(y,x=None):
    y=np.asarray(y,dtype=float)
    if x is None:x=np.ones((len(y),1))
    if len(y)<20 or np.linalg.matrix_rank(x)!=x.shape[1]:
        return {"n":len(y),"status":"INSUFFICIENT_FOR_INFERENCE"}
    m=sm.OLS(y,x).fit(cov_type="HAC",cov_kwds={"maxlags":5},use_t=True)
    return {"n":len(y),"status":"ESTIMATED",
            "coefficient":float(m.params[0]),
            "ci95":[float(z) for z in m.conf_int()[0]],
            "p":float(m.pvalues[0])}

def record(trial):
    terminal=ROOT/"run_log/research_sessions"/SID/"trials"/f"{trial}.json"
    if terminal.exists():return
    cli("record","--session",SID,"--trial",trial,"--status","completed",
        "--artifact",f"run_log/{SID}/full/{trial}/result.json")

def complete():
    gate=read_gate()
    OUT.mkdir(parents=True,exist_ok=True)
    # The gate is a status snapshot, allowed to change as exports arrive.
    (OUT/"export_readiness.json").write_text(json.dumps(gate,indent=2)+"\n")
    if gate["status"]!="PASS":
        print(json.dumps({"status":"BLOCKED_EXPORTS","accepted":gate["accepted_exports"],
                          "required":gate["required_exports"],
                          "missing":[x["start"] for x in gate["missing"]],
                          "failed":gate["failed"],"no_native_full_run":True},indent=2))
        return 2
    core.EXPECTED=[(str(Path(source["path"]).relative_to(core.SOURCE)),source["sha256"])
                   for source in gate["sources"]]
    core.SMOKE_DAYS=[date(year,4,day)
                     for year in range(2020,2027) for day in range(2,15)]
    core.OUT=OUT
    assert len(core.SMOKE_DAYS)==91
    frozen_manifest=OUT/"raw_quote_source_manifest.json"
    if frozen_manifest.exists():
        if json.loads(frozen_manifest.read_text())!=gate:
            raise RuntimeError("Source identity changed from frozen first run")
    else:
        frozen_manifest.write_text(json.dumps(gate,indent=2)+"\n")
    if (ROOT/"run_log/research_sessions"/SID/"frozen_spec.json").exists():
        assert cli("check","--session",SID)["status"]=="PASS"
    else:
        core.write_json(OUT/"freeze_init.json",
                        cli("init","--spec",str(SPEC.relative_to(ROOT))))
        core.write_json(OUT/"freeze_check.json",
                        cli("check","--session",SID))
    data,quality=core.load()
    core.write_json(OUT/"T0_raw_quote_audit/result.json",quality)
    record("T0_raw_quote_audit")
    cal=pl.read_parquet(CAL).filter(
        pl.col("session")<date(2026,9,1)).select(
        "session","gotobi","ordinary","year","weekday").sort("session")
    result=[]
    mapping={"A0_gotobi_1s_0p25":"T1_gotobi_native",
             "A1_ordinary_1s_0p25":"T2_ordinary_native",
             "A2_gotobi_0s_0":"T3_latency_cost",
             "A3_gotobi_5s_0p5":"T3_latency_cost"}
    for name,typ,delay,extra in [
        ("A0_gotobi_1s_0p25","gotobi",1,.25),
        ("A1_ordinary_1s_0p25","ordinary",1,.25),
        ("A2_gotobi_0s_0","gotobi",0,0),
        ("A3_gotobi_5s_0p5","gotobi",5,.5)]:
        t=core.run_arm(data,cal,name,typ,delay,extra)
        result.append(t)
        print("NATIVE",name,t.get("n",0),t.get("net_usd"),flush=True)
        tid=mapping[name]
        if tid in ("T1_gotobi_native","T2_ordinary_native"):
            core.write_json(OUT/tid/"result.json",t)
            record(tid)
    core.write_json(OUT/"T3_latency_cost/result.json",{"runs":result[2:]})
    record("T3_latency_cost")
    g=pl.read_parquet(OUT/"runs/A0_gotobi_1s_0p25/native_trades.parquet")
    o=pl.read_parquet(OUT/"runs/A1_ordinary_1s_0p25/native_trades.parquet")
    both=pl.concat([g,o]).sort("session")
    both=both.join(cal,on="session")
    main=hac(g["pnl_usd"])
    controls=[both["gotobi"].cast(pl.Float64).to_numpy(),
              np.ones(both.height)]
    for v in ["weekday","year"]:
        for level in sorted(both[v].unique().to_list())[1:]:
            controls.append((both[v]==level).cast(pl.Float64).to_numpy())
    premium=hac(both["pnl_usd"],np.column_stack(controls))
    if main["status"]=="ESTIMATED" and premium["status"]=="ESTIMATED":
        adj=multipletests([main["p"],premium["p"]],method="holm")[1]
        main["holm2_p"],premium["holm2_p"]=map(float,adj)
    annual=g.with_columns(pl.col("session").dt.year().alias("year")).group_by(
        "year").agg(pl.len().alias("n"),pl.col("pnl_usd").sum()).sort("year").to_dicts()
    vs_24_25=float(g.filter(pl.col("session").dt.year().is_between(2024,2025))["pnl_usd"].sum())
    flags={"min_20_gotobi":g.height>=20,
           "1s25_won_money":result[0]["net_usd"]>0,
           "2024_25_positive":vs_24_25>0,
           "hac_lower_positive":main["status"]=="ESTIMATED" and main["ci95"][0]>0,
           "calendar_premium_significant":premium["status"]=="ESTIMATED"
                and premium["coefficient"]>0 and premium["holm2_p"]<.05}
    outcome={"status":"PILOT_INCONCLUSIVE" if not all(flags.values()) else "PILOT_PASSED_ONLY_NOT_LIVE",
             "flags":flags,"gotobi_hac":main,"premium_hac":premium,"annual":annual,
             "2024_25_net_usd":vs_24_25,
             "historical_selection_bias":"2020-Aug2026 already inspected, not independent OOS",
             "broker_quote_certification":"UNKNOWN"}
    core.write_json(OUT/"T4_refutation/result.json",outcome)
    record("T4_refutation")
    checks={"native_max_jpy_error":max(x["engine_jpy_reconciliation_error"] for x in result),
            "quote_oracle_max_error":max(x["source_quote_oracle_error"] for x in result),
            "total_native_trades":sum(x["n"] for x in result),
            "all_source_hashes_checked":True,"open_protected_holdout":False}
    core.write_json(OUT/"T5_quote_oracle/result.json",checks)
    record("T5_quote_oracle")
    core.write_json(OUT/"T6_final_audit/result.json",
                    {"outcome":outcome["status"],"all_arms":result,
                     "verification":checks,"no_live_orders":True})
    record("T6_final_audit")
    report=ROOT/"docs/audit"/f"{SID}.md"
    lines=["# LSE bid/ask Gotobi native execution pilot","",
        f"Decision: **{outcome['status']}**, never live-approved.","",
        "Reference LSE bid/ask per UTC second; many quotes have identical second timestamps.",
        "Worst ask/bid within selected execution second plus adverse extra cost.",
        "NEXT_BAR native ML4T with source-oracle reconciliation.","",
        "| Arm | Sessions | Net USD |","|---|---:|---:|"]
    for r in result:lines.append(f"| {r['arm']} | {r['n']} | {r['net_usd']:+.2f} |")
    lines+=["",f"2024-2025 Gotobi USD: {vs_24_25:+.2f}",
        f"Main HAC: {main}",f"Calendar premium HAC: {premium}",f"Flags: {flags}",
        "Source manifests: "+str(frozen_manifest.relative_to(ROOT)),
        "No broker fill/commission verification, no holdout use or new independent OOS.",
        "Only a limited April historical sample, not a full 2020-2026 population."]
    if report.exists():raise RuntimeError("Do not overwrite existing report")
    report.write_text("\n".join(lines)+"\n")
    print(json.dumps({"outcome":outcome,"native_source_audit":checks},indent=2),flush=True)
    return 0

if __name__=="__main__":
    raise SystemExit(complete())
