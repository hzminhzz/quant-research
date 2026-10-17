"""Independent source-bar and native-fill oracle for frozen 07:00 Gotobi study.

The oracle does not run a portfolio backtester or use the strategy implementation.
It independently checks source minute opens, order submission/fill clocks, cash
conversion, sample eligibility, pre-decision feature availability, and identities.
"""
from __future__ import annotations
import hashlib
import json
import math
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl

ROOT=Path(__file__).resolve().parents[1]
SID="tokyo_fix_prefx_0700_0830_20261011_v1"
OUT=ROOT/"run_log"/SID
SEAL=date(2026,9,1)
JST=ZoneInfo("Asia/Tokyo")
SRC=[ROOT/f"data/processed/tokyo_alpha_map_program1_v1/USDJPY_03_12_JST_{y}.parquet" for y in range(2020,2027)]
CAL=ROOT/"run_log/tokyo_fix_alpha_map_program1_20261010/execution_v1/calendar_event_registry.parquet"
COSTS={f"gotobi_c{c}":float(c) for c in ["0","0.8","1","1.4","2","3"]}
COSTS.update({"ordinary_c1":1.,"gotobi_delay1":1.,"gotobi_delay2":1.,
              "placebo_gotobi_c1":1.,"placebo_ordinary_c1":1.})
PIP=.01

def sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda:f.read(1<<20),b""):
            h.update(b)
    return h.hexdigest()

def cmp(a,b,desc,tol=1e-7):
    if a is None or b is None or not math.isclose(float(a),float(b),rel_tol=1e-11,abs_tol=tol):
        raise AssertionError(f"{desc}: {a}!={b}")

def main():
    final=OUT/"T6_independent_oracle/result.json"
    if final.exists():
        raise RuntimeError("Immutable audit exists; do not overwrite")
    manifest=json.loads((OUT/"source_manifest.json").read_text())
    for s in manifest["sources"]:
        path=ROOT/s["path"]
        if sha(path)!=s["sha256"]:
            raise AssertionError(f"Source changed: {path}")
    if sha(CAL)!=manifest["calendar"]["sha256"]:
        raise AssertionError("Calendar changed")
    calendar=pl.read_parquet(CAL).filter(pl.col("session")<SEAL)
    gates=pl.read_parquet(OUT/"window_gates.parquet")
    eligible={r["session"]:r for r in gates.to_dicts()}
    feature=pl.read_parquet(OUT/"prior_features.parquet")
    assert feature["session"].max()<SEAL
    assert feature["available_at"].dt.convert_time_zone("Asia/Tokyo").dt.strftime("%H:%M").unique().to_list()==["06:59"]
    # Use only already-frozen source snapshots. Do not inspect live or protected data.
    source=(pl.scan_parquet(SRC)
        .with_columns(pl.col("timestamp").dt.convert_time_zone("Asia/Tokyo").alias("jst"))
        .with_columns(
            pl.col("jst").dt.date().alias("session"),
            (pl.col("jst").dt.hour().cast(pl.Int32)*60
             +pl.col("jst").dt.minute().cast(pl.Int32)).alias("minute"))
        .filter(pl.col("session")<SEAL)
        .filter(pl.col("minute").is_between(388,690))
        .select("session","timestamp","minute","open","high","low","close")
        .sort("timestamp").collect())
    if source["timestamp"].is_duplicated().sum():
        raise AssertionError("Source duplicates")
    byday={chunk["session"][0]:{r["minute"]:r for r in chunk.to_dicts()}
           for chunk in source.partition_by("session")}
    audits=[]
    totaltrades=0
    for name in sorted(COSTS):
        folder=OUT/"runs"/name
        records=json.loads((folder/"result.json").read_text())
        trades=pl.read_parquet(folder/"trades.parquet").sort("session")
        orders=pl.read_parquet(folder/"orders.parquet")
        if records["metrics"]["n"]!=trades.height:
            raise AssertionError("Summary count mismatch")
        if orders.height!=2*trades.height:
            raise AssertionError("One entry/exit per closed trade")
        group=records["group"]
        is_placebo=name.startswith("placebo_")
        gate_name="placebo_complete" if is_placebo else "execution_complete"
        expected_dates={r["session"] for r in eligible.values() if r[gate_name] and r[group]}
        actual_dates=set(trades["session"].to_list())
        if actual_dates!=expected_dates:
            raise AssertionError(f"{name}: date gate differs, {len(actual_dates)} vs {len(expected_dates)}")
        assert all(d<SEAL for d in actual_dates)
        entry=int(records["entry_minute"])
        end=int(records["exit_minute"])
        cost=COSTS[name]
        orders_by_day={}
        for o in orders.to_dicts():
            orders_by_day.setdefault(o["session"],{})[o["role"]]=o
        oracle_jpy=0.
        oracle_usd=0.
        for t in trades.to_dicts():
            d=t["session"]
            ref=byday[d]
            if entry not in ref or end not in ref:
                raise AssertionError(f"Missing fill source: {name}/{d}")
            a=ref[entry]
            z=ref[end]
            eo=orders_by_day[d].get("entry")
            xo=orders_by_day[d].get("exit")
            if eo is None or xo is None:raise AssertionError("Missing entry or exit order")
            if eo["status"]!="filled" or xo["status"]!="filled":raise AssertionError("Not filled")
            if eo["filled_at"]!=a["timestamp"] or xo["filled_at"]!=z["timestamp"]:
                raise AssertionError("Fill timestamp not matching exact source bar")
            if eo["submitted_at"]!=a["timestamp"]-timedelta(minutes=1):
                raise AssertionError("Entry signal after decision/fill bar")
            if xo["submitted_at"]!=z["timestamp"]-timedelta(minutes=1):
                raise AssertionError("Exit not next bar")
            if eo["quantity"]!=10000 or xo["quantity"]!=10000:
                raise AssertionError("Wrong notional units")
            expected_buy=float(a["open"])+cost*PIP/2
            expected_sell=float(z["open"])-cost*PIP/2
            cmp(eo["price"],expected_buy,"entry adverse price")
            cmp(xo["price"],expected_sell,"exit adverse price")
            cmp(t["entry_price"],expected_buy,"trade entry")
            cmp(t["exit_price"],expected_sell,"trade exit")
            cmp(t["source_entry"],a["open"],"original open entry")
            cmp(t["source_exit"],z["open"],"original open exit")
            pnl_jpy=10000*(expected_sell-expected_buy)
            pnl_usd=pnl_jpy/expected_sell
            cmp(t["gross_pips"],(z["open"]-a["open"])/PIP,"gross")
            cmp(t["net_pips"],(expected_sell-expected_buy)/PIP,"net")
            cmp(t["pnl_jpy"],pnl_jpy,"JPY")
            cmp(t["pnl_usd"],pnl_usd,"USD")
            oracle_jpy+=pnl_jpy
            oracle_usd+=pnl_usd
        cmp(records["native_pnl_jpy"],oracle_jpy,"native JPY account",tol=2e-5)
        cmp(records["metrics"]["net_usd"],oracle_usd,"native USD converted",tol=1e-5)
        cmp(records["metrics"]["end_balance_usd"],10000+oracle_usd,"final USD equity",tol=1e-5)
        audits.append({"run":name,"pass":True,"trades":trades.height,"fills":orders.height,
                       "sample_n":len(expected_dates),"net_usd":oracle_usd,
                       "entry_jst":f"{entry//60:02}:{entry%60:02}",
                       "exit_jst":f"{end//60:02}:{end%60:02}",
                       "roundtrip_cost_pips":cost})
        totaltrades+=trades.height

    # Verify that all features are older than decision time and have exact bar-clock references.
    row_errors=0
    for ev in feature.to_dicts():
        d=ev["session"]
        if d not in byday or 418 not in byday[d]:
            row_errors+=1
            continue
        if ev["feature_bar"]!=byday[d][418]["timestamp"]:
            raise AssertionError("Feature time inconsistent with original minute")
        if ev["available_at"]!=ev["feature_bar"]+timedelta(minutes=1):
            raise AssertionError("Feature availability improper")
        if ev["available_at"].astimezone(JST).hour!=6 or ev["available_at"].astimezone(JST).minute!=59:
            raise AssertionError("Feature available after 06:59 decision")
    if row_errors:raise AssertionError(f"Feature source unavailable {row_errors}")
    assert set(COSTS)=={p.name for p in (OUT/"runs").iterdir() if p.is_dir() and (p/"result.json").exists()}
    payload={
        "status":"PASS","source":"immutable seven annual LSE USDJPY source snapshot files",
        "source_identity_verified":True,"protected_holdout_read":False,
        "strategy_reexecution":False,"method":"Independent original-source open oracle; native timestamp, next-bar, cost and account reconciliation",
        "native_runs":len(audits),"trades_verified":totaltrades,
        "fills_verified":2*totaltrades,
        "features_timestamp_verified":feature.height,
        "scenarios":audits,
        "limitations":["Broker bid/ask not observed; slippage hypothetical",
                       "Fixed initial USD notional may exceed 1x remaining current equity after losses",
                       "No independent holdout"]
    }
    final.parent.mkdir(parents=True,exist_ok=True)
    final.write_text(json.dumps(payload,indent=2)+"\n")
    print(json.dumps({"status":payload["status"],"runs":len(audits),
          "trades_verified":totaltrades,"fills_verified":2*totaltrades,
          "feature_rows":feature.height},indent=2))

if __name__=="__main__":
    main()
