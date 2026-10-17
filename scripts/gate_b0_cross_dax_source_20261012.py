"""Follow-up read-only integrity gate for DAX and Nikkei B0 replication.

ML4T procedures: validate-data, polars-patterns, calendar-ops, point-in-time,
run-backtest. No custom execution loop. Preserve canonical data and B0.
"""
from __future__ import annotations
import json, hashlib
from datetime import datetime,timezone
from pathlib import Path
import polars as pl

R=Path("/home/quant/dev/quant/ml4t-data/.data/store")
OUT=Path("run_log/one_bar_b0_cross_indices_20261012/followup_dax_nikkei_20261012")
OUT.mkdir(parents=True,exist_ok=True)
CUTOFF=datetime(2026,7,15,tzinfo=timezone.utc)
FLOOR=5000.0 # Fixed from uncontaminated pre-2024 source values (min >7000)
def scan_symbol(symbol):
    source=R/("index_minute_"+symbol)
    paths=[str(x) for x in source.glob("year=*/month=*/data.parquet")
          if int(x.parent.parent.name[5:])>=2024 and
          (int(x.parent.parent.name[5:])<2026 or int(x.parent.name[6:])<=7)]
    raw=(pl.scan_parquet(paths,hive_partitioning=False,extra_columns="ignore")
         .select("timestamp","open","high","low","close","volume")
         .filter(pl.col("timestamp")<CUTOFF)
         .sort("timestamp").collect(engine="streaming"))
    return raw
def counts_by_calendar(series):
    a=series.with_columns(
        pl.col("timestamp").dt.year().alias("year"),
        (pl.col("close")<FLOOR).alias("scale_low"),
        (pl.col("close")>=FLOOR).alias("scale_high"))
    return a.group_by("year").agg(
      pl.len().alias("rows"),
      pl.col("scale_low").sum().alias("rows_low"),
      pl.col("scale_high").sum().alias("rows_high"),
      pl.col("close").median().alias("median_price"),
    ).sort("year").to_dicts()
def bar_quality(frame):
    a=frame.with_columns(pl.col("timestamp").dt.truncate("30m").alias("slot"))
    b=a.group_by("slot").agg(
      pl.len().alias("n"),
      pl.col("timestamp").n_unique().alias("distinct"),
      pl.col("timestamp").min().alias("first"),
      pl.col("timestamp").max().alias("last"))
    b=b.with_columns(((pl.col("n")==30)&(pl.col("distinct")==30)&
       (pl.col("first")==pl.col("slot"))&
       (pl.col("last")==pl.col("slot")+pl.duration(minutes=29))).alias("complete"))
    return {"observed_30m_bins":b.height,"complete_30m_bins":int(b["complete"].sum()),
            "incomplete_30m_bins":int((~b["complete"]).sum())}
def raw_file_hash_sample(symbol,year,month):
    p=R/("index_minute_"+symbol)/f"year={year}/month={month}/data.parquet"
    h=hashlib.sha256(p.read_bytes()).hexdigest()
    return {"file":str(p),"sha256":h,"bytes":p.stat().st_size}
def main():
    d=scan_symbol("DAX")
    all_row={}
    for year in (2024,2025,2026):
        annual=d.filter(pl.col("timestamp").dt.year()==year)
        safe=annual.filter(
          (pl.min_horizontal("open","high","low","close")>=FLOOR))
        # This is an ex-post data quarantine, NOT a replacement tradable series.
        high=annual.filter(pl.col("close")>=FLOOR)
        source=bar_quality(annual)
        remain=bar_quality(safe)
        switches=annual.with_columns(
          (pl.col("close")<FLOOR).alias("low_state")).select(
            (pl.col("low_state")!=pl.col("low_state").shift(1)).fill_null(False).sum()).item()
        all_row[str(year)]={
          "raw_rows":annual.height,"raw_30m":source,
          "close_low_rows":int(annual["close"].lt(FLOOR).sum()),
          "all_OHLC_above_floor_rows":safe.height,
          "high_close_rows":high.height,
          "quarantined_rows":annual.height-safe.height,
          "safe_30m":remain,
          "retained_complete_bin_fraction_of_original":
              remain["complete_30m_bins"]/source["complete_30m_bins"] if source["complete_30m_bins"] else None,
          "scale_state_switches":int(switches),
          "classification":"NO_CAUSAL_BAR_FABRICATION",
        }
        print("DAX",year,all_row[str(year)],flush=True)
    ref_dir=R/"equity_daily_DAX"
    paths=[str(x) for x in ref_dir.rglob("*.parquet") if int(x.parent.parent.name[5:])>=2024]
    ref=(pl.scan_parquet(paths,extra_columns="ignore",hive_partitioning=False)
       .select(pl.col("timestamp").cast(pl.Date).alias("day"),"close")
       .filter(pl.col("day")<pl.lit(CUTOFF.date())).collect(engine="streaming"))
    daily_ref={"rows":ref.height,"unique_days":ref["day"].n_unique(),
       "duplicate_days":ref.height-ref["day"].n_unique(),
       "min_close":float(ref["close"].min()),
       "max_close":float(ref["close"].max()),
       "source_provenance_verified":False}
    report={
      "status":"DIAGNOSTIC_QUARANTINE_ONLY_NOT_REPAIRED",
      "source":"London Strategic Edge DE30/EUR, 1m index CFD price proxy",
      "reference":"equity_daily_DAX used ONLY for scale sanity; provenance and duplicate days unresolved",
      "floor_rule":"5000 index points fixed below uncontaminated 2013-2023 historical min; NOT a trading strategy feature",
      "rule":"Quarantine any low-scale OHLC bar. Do not rescale or fill missing minutes. Complete 30m bins require all 30 original verified minutes.",
      "repair_readiness":"Must source independent point-in-time 1m replacement for rejected timestamps, or reject missing 30m windows.",
      "years":all_row,"daily_reference":daily_ref,
      "source_sample_sha256":[raw_file_hash_sample("DAX",2024,9),raw_file_hash_sample("DAX",2026,6)]
    }
    (OUT/"dax_quality_repair_gate.json").write_text(json.dumps(report,indent=2)+"\n")
    return report
if __name__=="__main__": main()
