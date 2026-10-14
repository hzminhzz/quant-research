"""Independent read-only native-broker audit for the frozen Gold/FX MVP.

Checks next-bar fill chronology, native ROC60 sign and schedule,
broker/slippage costs, original data identities and accounting invariants.
Results use ml4t.backtest.analytics for risk metrics. This code does NOT
re-run or modify the backtests or frozen source files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
from ml4t.backtest.analytics import max_drawdown, sharpe_ratio

from research_programs.gold_fx_trend_20261015 import (
    DATA,
    END,
    OUTPUT,
    SESSION,
    START,
    SYMBOLS,
)

AUDIT_OUT=Path("docs/audit/gold_fx_trend_diversification_mvp_20261015_verified.json")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_one(symbol: str, root: Path) -> dict:
    folder=root/SYMBOLS[symbol]/"attempt01"
    report_file=folder/"report.json"
    if not report_file.is_file():
        raise FileNotFoundError(f"Missing native run: {report_file}")
    r=json.loads(report_file.read_text())
    if r["status"]!="NATIVE_ENGINE_COMPLETED_PENDING_INDEPENDENT_AUDIT":
        raise AssertionError("Unexpected engine state")
    for name,digest in r["artifacts_sha256"].items():
        if sha(folder/name)!=digest:
            raise AssertionError(f"Tampered artifact {folder/name}")
    snapshot=DATA/f"{symbol}_NY17_daily_2013_2024.parquet"
    if sha(snapshot)!=r["provenance"]["input_snapshot_sha256"]:
        raise AssertionError("Frozen data identity changed")
    px=pl.read_parquet(folder/"prices.parquet").sort("timestamp")
    sig=pl.read_parquet(folder/"signals.parquet").sort("timestamp")
    eq=pl.read_csv(folder/"equity.csv",try_parse_dates=True).sort("timestamp")
    fills=pl.read_csv(folder/"fills.csv",try_parse_dates=True)
    tr=pl.read_csv(folder/"trades.csv",try_parse_dates=True)
    rejected=pl.read_csv(folder/"rejected_orders.csv")
    decisions=json.loads((folder/"decisions.json").read_text())
    if fills.height:
        fills=fills.with_columns(
            pl.col("timestamp").dt.replace_time_zone("UTC")
            if fills["timestamp"].dtype.time_zone is None
            else pl.col("timestamp")
        )
    if not (px["timestamp"].min()>=START and px["timestamp"].max()<END):
        raise AssertionError("Execution price cutoff")
    if sig["timestamp"].max()>=END or eq["timestamp"].max()>=END:
        raise AssertionError("Evaluation cutoff breached")
    if px["timestamp"].n_unique()!=px.height or sig["timestamp"].n_unique()!=sig.height:
        raise AssertionError("Duplicate source timestamps")
    if eq["timestamp"].to_list()!=px["timestamp"].to_list():
        raise AssertionError("Native daily equity series fails price clock")
    if len(decisions)!=84 or fills.height!=84 or rejected.height:
        raise AssertionError("Unexpected 84 monthly orders/fills or rejections")
    if sig.height!=84 or not all(v in (-1,0,1) for v in sig["target_side"]):
        raise AssertionError("Frozen signal schedule")
    source=pl.read_parquet(snapshot).sort("timestamp").filter(pl.col("timestamp")<END)
    # Independently verify all 84 native ROC decisions against c[t]/c[t-60].
    source_rows={t:i for i,t in enumerate(source["timestamp"])}
    for s in sig.iter_rows(named=True):
        idx=source_rows[s["timestamp"]]
        if idx<60:
            raise AssertionError("Missing 60-session warmup")
        ratio=source["close"][idx]/source["close"][idx-60]-1.
        intended=1 if ratio>0 else -1 if ratio<0 else 0
        if intended!=s["target_side"]:
            raise AssertionError("ROC60 direction mismatch")
        # Detect any first-session schedule that was not the first eligible month bar.
        month=s["timestamp"].astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).strftime("%Y-%m")
        if idx and source["timestamp"][idx-1].astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).strftime("%Y-%m")==month:
            raise AssertionError("Not first eligible monthly session")
    # One order per decision. Fill must happen at exactly the next *observed*
    # source price bar, never on the decision bar.
    pxrows=px.to_dicts()
    idxpx={row["timestamp"]:i for i,row in enumerate(pxrows)}
    for i,(decision,fill) in enumerate(zip(decisions,fills.iter_rows(named=True))):
        stamp=datetime.fromisoformat(decision["timestamp"])
        ix=idxpx[stamp]
        if ix+1>=len(pxrows) or fill["timestamp"]!=pxrows[ix+1]["timestamp"]:
            raise AssertionError(f"{symbol}: fill not next-bar after decision {i}")
        side = "buy" if decision["delta"]>0 else "sell"
        if fill["side"]!=side:
            raise AssertionError("Fill direction mismatch")
        if abs(fill["quantity"]-abs(decision["delta"]))>1e-5:
            raise AssertionError("Position size/fill mismatch")
        price=pxrows[ix+1]["open"]
        expected=price*(1+.0003 if side=="buy" else 1-.0003)
        if not math.isclose(fill["price"],expected,rel_tol=2e-9,abs_tol=2e-9):
            raise AssertionError(f"Unexpected fill slippage: {fill['price']} {expected}")
    pnl=float(tr["pnl"].sum())
    delta=float(eq["equity"][-1])-100_000.
    if abs(pnl-delta)>.02 or abs(delta-(r["metrics"]["final_equity"]-100_000))>.02:
        raise AssertionError("Native cash/equity/trade ledger discrepancy")
    commissions=float(fills["commission"].sum())
    if abs(commissions-r["metrics"]["native_metrics"]["total_commission"])>.01:
        raise AssertionError("Broker total commissions do not match fills")
    if r["metrics"]["rejected_orders"]!=0 or r["metrics"]["broker_submissions"]!=84:
        raise AssertionError("Engine submitted unexpected orders")
    true_open=int(tr.filter(pl.col("status")=="open").height)
    partial=int(tr.filter(pl.col("status")=="partial").height)
    # A ledger row with status partial is a realized partial CLOSE, not an
    # additional independently open position. The previous runner's
    # open_trades_at_boundary counts both partial and open rows.
    if true_open!=1:
        raise AssertionError("Expected one genuinely open inventory lot at boundary")
    returns=eq["equity"].pct_change().fill_null(0).to_numpy()
    sharpe=float(sharpe_ratio(returns))
    dd=float(max_drawdown(eq["equity"].to_list())[0])
    if abs(sharpe-r["metrics"]["daily_sharpe"])>1e-8:
        raise AssertionError("Daily Sharpe reconciliation")
    if abs(dd-r["metrics"]["daily_max_drawdown"])>1e-8:
        raise AssertionError("Drawdown reconciliation")
    halves={}
    for label,lower,upper in (
        ("2015_2017",datetime(2015,1,1,tzinfo=UTC),datetime(2018,1,1,tzinfo=UTC)),
        ("2018_2021",datetime(2018,1,1,tzinfo=UTC),END),
    ):
        h=eq.filter((pl.col("timestamp")>=lower)&(pl.col("timestamp")<upper))
        vals=h["equity"].pct_change().fill_null(0).to_numpy()
        halves[label]={
            "net_change_pct_first_to_last":100*(float(h["equity"][-1])/float(h["equity"][0])-1),
            "daily_sharpe":float(sharpe_ratio(vals)),
            "daily_marks":h.height,
        }
    return {
        "case":SYMBOLS[symbol], "symbol":symbol, "audit":"PASS",
        "file":str(report_file),"report_sha256":sha(report_file),
        "input_sha256":sha(snapshot),
        "execution_bars":px.height,"decision_months":84,
        "native_fills":fills.height,"rejected_orders":rejected.height,
        "broker_total_commission":commissions,
        "true_open_position_rows":true_open,
        "realized_partial_close_rows":partial,
        "closed_trade_rows":int(tr.filter(pl.col("status")=="closed").height),
        "equity_reconciliation_usd":pnl-delta,
        "net_equity_return_pct":r["metrics"]["net_return_pct"],
        "daily_sharpe":sharpe,
        "daily_max_drawdown":dd,
        "subperiods":halves,
        "execution_verified":"all 84 fills at next actual native bar open, with 3bps slippage",
        "caveats":"No certified spread/swap/overnight financing, exposure normalized to 10% notional",
    }


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",type=Path,default=OUTPUT)
    parser.add_argument("--out",type=Path,default=AUDIT_OUT)
    args=parser.parse_args()
    audited={symbol:audit_one(symbol,args.root) for symbol in SYMBOLS}
    verified={
        "session":SESSION,"audited_at":datetime.now(UTC).isoformat(),
        "status":"PASS" if all(x["audit"]=="PASS" for x in audited.values()) else "BLOCKED",
        "cases":audited,
        "positive_net_sharpe":sum(a["daily_sharpe"]>0 for a in audited.values()),
        "frozen_two_of_three_gate":sum(a["daily_sharpe"]>0 for a in audited.values())>=2,
        "decision":"REJECT_MVP_NO_PORTFOLIO_STAGE",
        "holdout_2025_2026":"NOT_ACCESSED",
        "trial_accounting":"3 preregistered; 3 completed; no optimizer or cost-search",
    }
    if args.out.exists():
        raise FileExistsError(f"Append-only audit: {args.out}")
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(verified,indent=2,allow_nan=False)+"\n")
    print(json.dumps({k:{"return":v["net_equity_return_pct"],
                          "sharpe":v["daily_sharpe"],
                          "dd":v["daily_max_drawdown"],
                          "open_rows":v["true_open_position_rows"],
                          "partial_close_rows":v["realized_partial_close_rows"],
                          "subperiods":v["subperiods"]} for k,v in audited.items()},indent=2))
    print(verified["status"],verified["decision"])


if __name__=="__main__":
    main()
