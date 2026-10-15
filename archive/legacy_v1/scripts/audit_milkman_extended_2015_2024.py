"""Read-only audit of registered Milkman 2015-2024 annual native ledgers.

No new backtests or data reads. Verify file SHA256, trade/fill/accounting,
costs, holdout cutoff and year-level outcomes. Yearly books reset capital.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import polars as pl
from ml4t.backtest.analytics import sharpe_ratio

CASES=("legends_buy_day","legends_ema","bilbo_box_v2","swing_golden_gate")
YEARS=tuple(range(2015,2025))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(root: Path, *, corrected_root: Path | None = None):
    results={}
    for case in CASES:
        row={}
        for year in YEARS:
            original=root/case/str(year)
            correction=(corrected_root/case/str(year) if corrected_root and case in
                        ("legends_ema","bilbo_box_v2") and year in (2016,2017) else None)
            base=(correction if correction and (correction/"report.json").is_file()
                  else original)
            report=base/"report.json"
            failure=original/"failed.json"
            if not report.is_file():
                row[str(year)]=({"status":"BLOCKED_DATA_FULL_GLOBEX_MISSING",
                    "original_attempt":str(failure)}
                    if case=="legends_buy_day" and year in (2016,2017) and failure.is_file()
                    else {"status":"FAILED" if failure.is_file() else "MISSING"})
                continue
            r=json.loads(report.read_text())
            if r["year"]!=year or r["case"]!=case:
                raise ValueError("Trial identity mismatch")
            px=pl.read_parquet(base/"prices.parquet")
            sig=pl.read_parquet(base/"signals.parquet")
            eq=pl.read_csv(base/"equity.csv",try_parse_dates=True)
            trades=pl.read_csv(base/"trades.csv",try_parse_dates=True)
            fills=pl.read_csv(base/"fills.csv",try_parse_dates=True)
            for n in ("prices.parquet","signals.parquet"):
                if digest(base/n)!=r["hashes"][n]:
                    raise ValueError(f"{case} {year} {n} hash mismatch")
            if not px.height or px["timestamp"].max().year!=year or px["timestamp"].min().year!=year:
                raise ValueError(f"{case} {year} wrong price window")
            if px["timestamp"].max().year>=2025 or sig.filter(pl.col("timestamp").dt.year()>=2025).height:
                raise ValueError(f"{case} {year} PROTECTED WINDOW BREACH")
            if px["timestamp"].n_unique()!=px.height or sig["timestamp"].n_unique()!=sig.height:
                raise ValueError(f"{case} {year} duplicate prices/signals")
            delta=float(eq["equity"][-1])-100_000
            trade_pnl=float(trades["pnl"].sum()) if trades.height else 0
            if abs(delta-trade_pnl)>.02 or abs(delta/1000-r["net_return_pct"])>.0001:
                raise ValueError(f"{case} {year} PnL not reconciled")
            if r["fills"]!=fills.height or r["closed_trades"]>trades.height:
                raise ValueError(f"{case} {year} counts disagreement")
            ret=eq.with_columns(pl.col("timestamp").dt.convert_time_zone("America/New_York")
                .dt.date().alias("et_date")).group_by("et_date").agg(
                pl.col("equity").sort_by("timestamp").last().alias("equity")
            ).sort("et_date")["equity"].pct_change().fill_null(0).to_numpy()
            if r["closed_trades"]>0 and abs(sharpe_ratio(ret)-r["native_daily_sharpe"])>1e-7:
                raise ValueError(f"{case} {year} Sharpe mismatched")
            row[str(year)]={
                "status":r["status"],"trades":r["closed_trades"],
                "open":r["open_trades"],"fills":r["fills"],"rejections":r["rejections"],
                "net_return_pct":r["net_return_pct"],
                "daily_sharpe":r["native_daily_sharpe"],"maxdd":r["native_daily_maxdd"],
                "costs":r["total_costs"],"pnl":delta,
                "evidence":str(report),"report_sha256":digest(report),
                "original_attempt_failed":str(failure) if base!=original and failure.is_file() else None
            }
        results[case]=row
    totals={}
    for case,records in results.items():
        valid=[v for v in records.values() if v["status"]=="NATIVE_RECONCILED"]
        totals[case]={
            "registered_years":10,"yearly_complete":len(valid),
            "blocked_data_years":[y for y,v in records.items() if v["status"]=="BLOCKED_DATA_FULL_GLOBEX_MISSING"],
            "incomplete_years":[y for y,v in records.items() if v["status"] not in ("NATIVE_RECONCILED","BLOCKED_DATA_FULL_GLOBEX_MISSING")],
            "closed_trades_sum":sum(v["trades"] for v in valid),
            "positive_years":sum(v["net_return_pct"]>0 for v in valid),
            "negative_years":sum(v["net_return_pct"]<0 for v in valid),
            "zero_years":sum(v["net_return_pct"]==0 for v in valid),
            "annual_books_net_pnl_sum_usd":sum(v["pnl"] for v in valid),
            "annual_return_pct_unweighted_mean":(
                sum(v["net_return_pct"] for v in valid)/len(valid) if valid else None
            ),"disclaimer":"Independent $100k annual resets. Do not treat annual sum as compounded NAV, and do not promote."
        }
    return {
        "program":"milkman_2015_2024_cfd_dev_extension_v1",
        "review":"INDEPENDENT_LEDGER_AUDIT",
        "reserved_allocation_holdout":"NOT_TOUCHED",
        "source":"canonical ES/NQ Dukascopy CFD aliases",
        "root":str(root),"summaries":totals,"yearly":results,
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",type=Path,default=Path("run_log/milkman_cfd_2015_2024_dev_extension_v1_retry1"))
    p.add_argument("--corrected-root",type=Path,default=Path("run_log/milkman_cfd_2015_2024_data_gate_correction_v1"))
    p.add_argument("--out",type=Path,default=Path("docs/audit/milkman_2015_2024_cfd_dev_extension_v1.json"))
    a=p.parse_args()
    data=audit(a.root,corrected_root=a.corrected_root)
    if a.out.exists():
        raise FileExistsError(f"Preserve prior report: {a.out}")
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(data,indent=2,allow_nan=False)+"\n")
    print(json.dumps(data["summaries"],indent=2))
    if any(v["incomplete_years"] for v in data["summaries"].values()):
        raise SystemExit("INCONCLUSIVE: some non-data-blocked annual cases are incomplete")


if __name__=="__main__":
    main()
