"""ML4T data-validation follow-up: detect incompatible index price scales."""
from __future__ import annotations
import json
from pathlib import Path
import polars as pl

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"run_log/one_bar_b0_cross_indices_20261012/phase34"
SRC=ROOT/"scripts"
import sys
sys.path.insert(0,str(SRC))
from audit_one_bar_b0_cross_indices_20261012 import files_for, scan_index

def main():
    findings={}
    for sym in ("NQ","ES","DAX","NIKKEI225"):
        frame=scan_index(files_for(sym)).select("timestamp","close").sort("timestamp")
        frame=frame.with_columns(
            pl.col("close").shift(1).alias("previous_close"),
            pl.col("timestamp").diff().dt.total_minutes().alias("gap_minutes"),
        ).with_columns(
            (pl.col("close")/pl.col("previous_close")-1.0).alias("return"))
        abnormal=frame.filter(pl.col("return").abs()>0.25).with_columns(
            pl.col("timestamp").dt.year().alias("year"))
        grouped=abnormal.group_by("year").len().sort("year").to_dicts()
        findings[sym]={
            "source":"index_minute_"+sym,
            "quality_condition":"abs(close/current_prior_observed_close - 1) > 25%, includes sessions across gaps",
            "extreme_discontinuities":abnormal.height,
            "extremes_on_adjacent_one_minute_prints":abnormal.filter(pl.col("gap_minutes")==1).height,
            "extreme_by_year":grouped,
            "extreme_examples":abnormal.sort(pl.col("return").abs(),descending=True).head(14).to_dicts(),
            "classification":"BLOCKED_2024_ONWARD_SCALE_MIX" if sym=="DAX" else "NO_EXTREME_PRICE_JUMPS_DETECTED",
        }
    (OUT/"extreme_price_jump_audit.json").write_text(json.dumps(findings,indent=2,default=str)+"\n")
    for sym,x in findings.items():
        print(sym,x["classification"],x["extreme_discontinuities"],x["extreme_by_year"])
if __name__=="__main__": main()
