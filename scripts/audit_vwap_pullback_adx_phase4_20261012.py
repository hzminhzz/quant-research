#!/usr/bin/env python3
"""Independent evidence audit of native Engine Phase 4 fills; no backtest logic."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import math

import polars as pl

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/"run_log/vwap_pullback_adx_nq_20261012_proxy_v2/phase4"
DATA=ROOT/"data/processed/vwap_adx_nqf_2026h1_1m.parquet"
SHA="a0670b34b2175ca0df4a7ab98fa79bb02650cf4cce64ed67261ad29f706ebaad"
TICK=.25
TZ=__import__("zoneinfo").ZoneInfo("America/Chicago")


def stamp(s):
    dt=datetime.fromisoformat(s)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def inspect() -> dict:
    if hashlib.sha256(DATA.read_bytes()).hexdigest()!=SHA:
        raise AssertionError("Data hash drift")
    raw=pl.read_parquet(DATA)
    lookup={t.replace(tzinfo=None):i for i,t in enumerate(raw["timestamp"].to_list())}
    high=raw["high"].to_list()
    low=raw["low"].to_list()
    op=raw["open"].to_list()
    reports=[]
    for mode in ("B1","B2","B3"):
        for label in ("gross","cost","stress"):
            d=RUN/f"{mode}_{label}"
            tr=pl.read_parquet(d/"trades.parquet").sort("entry_time")
            fi=pl.read_parquet(d/"fills.parquet").sort("timestamp","order_id")
            sig=json.loads((d/"signals.json").read_text())
            met=json.loads((d/"metrics.json").read_text())
            fail=[]
            stats=dict(
                trades=tr.height,signals=len(sig),fills=fi.height,
                wrong_time=0,wrong_tp=0,wrong_sl=0,bad_entry_price=0,
                nonflat_end=0,nonalternating_fills=0,ambiguous_exit_bar=0,
                ambiguous_exit_wrong_side=0,immediate_tp_marketable=0,
                limit_slippage_below_limit=0,stop_gap_through=0,
                stop_exit=0,limit_exit=0,hard_exit=0,entrybar_exits=0,
            )
            if tr.height!=len(sig):
                fail.append("signal-count/trade-count mismatch")
            if fi.height!=tr.height*2:
                fail.append("each trade must have one entry and one exit fill")
            for i,t in enumerate(tr.iter_rows(named=True)):
                s=sig[i]
                en=t["entry_time"]
                ex=t["exit_time"]
                if en!=stamp(s["expected_entry_at"]):
                    stats["wrong_time"]+=1
                local_ex=ex.replace(tzinfo=timezone.utc).astimezone(TZ)
                if local_ex.strftime("%H:%M")>"15:55" or ex<en:
                    stats["nonflat_end"]+=1
                idx=lookup.get(en)
                if idx is None:
                    stats["wrong_time"]+=1
                    continue
                target=math.ceil((max(high[idx-5:idx])-1e-9)/TICK)*TICK
                stop=math.floor((min(low[idx-20:idx])+1e-9)/TICK)*TICK
                if abs(target-s["take_profit"])>1e-8:
                    stats["wrong_tp"]+=1
                if abs(stop-s["stop_loss"])>1e-8:
                    stats["wrong_sl"]+=1
                slip={"gross":0.,"cost":.25,"stress":.5}[label]
                if abs(t["entry_price"]-(op[idx]+slip))>1e-7:
                    stats["bad_entry_price"]+=1
                if op[idx]>=target:
                    stats["immediate_tp_marketable"]+=1
                if en==ex:
                    stats["entrybar_exits"]+=1
                x=lookup.get(ex)
                if x is not None and low[x]<=stop and high[x]>=target:
                    stats["ambiguous_exit_bar"]+=1
                    # A real stop-first OHLC model should exit via STOP.
                    out=fi.filter((pl.col("timestamp")==ex)&(pl.col("side")=="sell"))
                    if out.height!=1 or out["order_type"][0]!="stop":
                        stats["ambiguous_exit_wrong_side"]+=1
            for j,f in enumerate(fi.iter_rows(named=True)):
                expected="buy" if j%2==0 else "sell"
                if f["side"]!=expected:
                    stats["nonalternating_fills"]+=1
                if f["side"]=="sell":
                    t=f["order_type"]
                    if t=="stop":
                        stats["stop_exit"]+=1
                        bar_id=lookup.get(f["timestamp"])
                        if bar_id is not None and f["stop_price"] is not None and op[bar_id]<f["stop_price"]:
                            stats["stop_gap_through"]+=1
                    elif t=="limit":
                        stats["limit_exit"]+=1
                        if f["limit_price"] is not None and f["price"]<f["limit_price"]-1e-7:
                            stats["limit_slippage_below_limit"]+=1
                    elif t=="market":
                        stats["hard_exit"]+=1
            if abs(met["reconciliation_difference_usd"])>1e-5:
                fail.append("Trade/equity ledger reconciliation")
            for check in ("wrong_time","wrong_tp","wrong_sl","bad_entry_price",
                          "nonflat_end","nonalternating_fills","ambiguous_exit_wrong_side"):
                if stats[check]:
                    fail.append(f"{check}={stats[check]}")
            if len(sig) and max(datetime.fromisoformat(x["expected_entry_at"]).date() for x in sig)>datetime(2026,6,30).date():
                fail.append("development range crossed")
            reports.append({"mode":mode,"cost":label,"audit_counts":stats,
                            "fatal_findings":fail,
                            "execution_limitations":[
                                "No native atomic OCO guarantee; tested stop-first event/fill orders only.",
                                "Continuous proxy rolls and true CME volume are unverified.",
                                "Native fixed slippage is applied to resting limit orders below their limit; such prices are not literal valid limit fills.",
                            ]})
    return {"status":"PASS_MECHANICAL" if all(not v["fatal_findings"] for v in reports) else "FAILED_MECHANICAL",
            "exact_CME_execution_verified":False,
            "phase4_contract_qualified":False,
            "trials":reports}


def main():
    r=inspect()
    path=RUN/"independent_audit_v2.json"
    if path.exists():
        raise FileExistsError("Do not overwrite prior independent audit")
    path.write_text(json.dumps(r,indent=2)+"\n")
    print(json.dumps(r,indent=2))
    if r["status"]!="PASS_MECHANICAL":
        raise AssertionError("Independent native fill audit failed")


if __name__=="__main__":
    main()
