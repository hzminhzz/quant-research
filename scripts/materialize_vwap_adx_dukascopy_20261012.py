#!/usr/bin/env python3
"""Create bounded Dukascopy-only CFD OHLCV input for Strategy 2."""

from __future__ import annotations
import hashlib,json
from pathlib import Path
from datetime import datetime,timezone
import polars as pl
ROOT=Path(__file__).resolve().parents[1]
STORE=Path("/home/quant/dev/quant/ml4t-data/.data/rebuild/duk21_usatechidxusd/index_minute_NQ")
OUT=ROOT/"data/processed/vwap_adx_dukascopy_2026_1m.parquet"
MANIFEST=ROOT/"run_log/vwap_pullback_adx_dukascopy_20261012_v1/source_manifest.json"

def sha(f):
 h=hashlib.sha256()
 with f.open("rb") as p:
  for chunk in iter(lambda:p.read(1<<20),b""):h.update(chunk)
 return h.hexdigest()

def main():
 if OUT.exists() or MANIFEST.exists():raise FileExistsError("No overwriting previous evidence")
 files=sorted((STORE/"year=2025/month=12").glob("day=*/data.parquet"))
 for i in range(1,9):
  files+=sorted((STORE/f"year=2026/month={i}").glob("day=*/data.parquet"))
 assert files and len(files)>200
 a=pl.concat([pl.scan_parquet(str(f),hive_partitioning=False) for f in files],how="vertical").filter(
  (pl.col("timestamp")>=datetime(2025,12,1,tzinfo=timezone.utc))&
  (pl.col("timestamp")<datetime(2026,10,12,tzinfo=timezone.utc))).sort("timestamp").collect()
 assert a["symbol"].unique().to_list()==["NQ"]
 assert a["timestamp"].n_unique()==a.height
 assert a.select(pl.all().null_count()).sum_horizontal().sum()==0
 assert a.filter((pl.col("high")<pl.max_horizontal("open","low","close"))|(pl.col("low")>pl.min_horizontal("open","high","close"))).is_empty()
 assert a.filter(pl.col("volume")<0).is_empty()
 # The source label NQ is a Dukascopy CFD alias; never suggest CME.
 a=a.with_columns(pl.lit("DUK_USATECH").alias("symbol"))
 OUT.parent.mkdir(parents=True,exist_ok=True)
 a.write_parquet(OUT,compression="zstd")
 filehashes={str(f.relative_to(STORE)):sha(f) for f in files}
 report={
  "source_kind":"Dukascopy USATECH.IDX/USD CFD/index","source_canonical_root":str(STORE),
  "rebuilt_manifest":"/home/quant/dev/quant/ml4t-data/.data/rebuild/duk21_usatechidxusd_pass.json",
  "raw_file_count":len(files),
  "source_file_manifest_sha256":hashlib.sha256(json.dumps(filehashes,sort_keys=True).encode()).hexdigest(),
  "source_file_hashes":filehashes,"prepared_path":str(OUT.relative_to(ROOT)),
  "prepared_sha256":sha(OUT),"rows":a.height,
  "first":str(a["timestamp"].min()),"last":str(a["timestamp"].max()),
  "source_volume_semantics":"Dukascopy broker-reported tick/quote activity proxy NOT CME volume",
  "source_tradeable_instrument":"NOT CME futures",
  "quality_ohlc_invalid":0,"quality_nulls":0,
  "negative_volume":0,"zero_volume_rows":a.filter(pl.col("volume")==0).height,
  "unscored":True,
 }
 MANIFEST.parent.mkdir(parents=True,exist_ok=True)
 MANIFEST.write_text(json.dumps(report,indent=2)+"\n")
 print(json.dumps({k:v for k,v in report.items() if k!="source_file_hashes"},indent=2))
if __name__=="__main__":main()
