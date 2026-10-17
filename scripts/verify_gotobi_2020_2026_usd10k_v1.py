"""Independent native-fill oracle for 2020-Aug2026 USDJPY Gotobi experiment.

Reads the frozen price snapshot AND the Engine fill ledger separately. Does
not submit orders, simulate a backtest, or change strategy results.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import polars as pl

ROOT=Path(__file__).resolve().parents[1]
SID="usdjpy_gotobi_2020_2026_usd10000_v1"
PRICE=ROOT/"data/processed/gotobi_2020_2026_usd10k_v1/USDJPY_tokyo_windows_1m.parquet"
OUT=ROOT/"run_log"/SID/"T5_native_fill_oracle"/"result.json"
ASSUMED_SLIP_JPY=0.005
USD_SIZE=10000.

def main():
    if OUT.exists():
        raise RuntimeError(f"Immutable artifact already exists: {OUT}")
    px=(pl.scan_parquet(PRICE)
        .with_columns(pl.col("timestamp").dt.convert_time_zone("Asia/Tokyo").alias("jst"))
        .with_columns(pl.col("jst").dt.date().alias("session"),
          (pl.col("jst").dt.hour().cast(pl.Int32)*60+pl.col("jst").dt.minute().cast(pl.Int32)).alias("minute"))
        .filter(pl.col("minute").is_in([510,594,596,630]))
        .group_by("session").agg([
          pl.col("open").filter(pl.col("minute")==m).first().alias(n)
          for m,n in {510:"p0830",594:"p0954",596:"p0956",630:"p1030"}.items()])
        .sort("session").collect())
    output=[]
    for arm,path in [
        ("H1",ROOT/"run_log"/SID/"T3_H1_engine_costed"),
        ("H2",ROOT/"run_log"/SID/"T4_H2_engine_costed"),
    ]:
        reported=json.loads((path/"result.json").read_text())
        ledger=pl.read_parquet(path/"native_fills_reconciled_trades.parquet").select(
           "session","entry","exit","pnl_jpy","pnl_usd","net_pips")
        joined=ledger.join(px,on="session",how="inner",validate="1:1")
        if joined.height!=ledger.height:
            raise AssertionError(f"{arm}: missing independent source rows")
        if arm=="H1":
            expected_entry=pl.col("p0830")+ASSUMED_SLIP_JPY
            expected_exit=pl.col("p0954")-ASSUMED_SLIP_JPY
            sign=1
        else:
            expected_entry=pl.col("p0956")-ASSUMED_SLIP_JPY
            expected_exit=pl.col("p1030")+ASSUMED_SLIP_JPY
            sign=-1
        audit=(joined.with_columns(expected_entry.alias("test_entry"),
                 expected_exit.alias("test_exit"))
              .with_columns(
                 ((pl.col("test_exit")-pl.col("test_entry"))*sign*USD_SIZE).alias("test_jpy"),
                 ((pl.col("test_exit")-pl.col("test_entry"))*sign*100).alias("test_pips"))
              .with_columns((pl.col("test_jpy")/pl.col("test_exit")).alias("test_usd")))
        fail=audit.filter(
            ((pl.col("entry")-pl.col("test_entry")).abs()>1e-8) |
            ((pl.col("exit")-pl.col("test_exit")).abs()>1e-8) |
            ((pl.col("pnl_jpy")-pl.col("test_jpy")).abs()>1e-7) |
            ((pl.col("pnl_usd")-pl.col("test_usd")).abs()>1e-7) |
            ((pl.col("net_pips")-pl.col("test_pips")).abs()>1e-8))
        if fail.height:
            raise AssertionError(f"{arm}: independent fill/FX conversion failure on {fail.height} trades")
        calc_jpy=float(audit["test_jpy"].sum())
        calc_usd=float(audit["test_usd"].sum())
        if not np.isclose(calc_jpy,float(reported["native_pnl_jpy"]),atol=1e-5):
            raise AssertionError("Native quote PnL mismatch")
        if not np.isclose(10000.+calc_usd,float(reported["final_equity_usd"]),atol=1e-8):
            raise AssertionError("Native USD conversion mismatch")
        output.append({"leg":arm,"status":"PASS",
            "matched_trades":audit.height,"matched_source_quotes":2*audit.height,
            "native_realized_jpy":calc_jpy,"realized_usd_converted_at_exit":calc_usd,
            "usd_start":10000.,"usd_end":10000.+calc_usd,
            "assumed_roundtrip_cost_pips":1.0})
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps({"status":"PASS", "method":"independent minute source to native fill/JPY/USD reconciliation","arms":output},indent=2)+"\n")
    print(OUT.read_text())
if __name__=="__main__":main()
