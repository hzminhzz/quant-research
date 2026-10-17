#!/usr/bin/env python3
"""Bounded NAS100 index price secondary proxy. No signal results in prep."""
from __future__ import annotations
import hashlib,json
from datetime import datetime,timezone
from pathlib import Path
import polars as pl
ROOT=Path(__file__).resolve().parents[1]
DIR=Path("/home/quant/dev/quant/ml4t-data/.data/store/index_minute_NAS100")
OUT=ROOT/"data/processed/vwap_adx_nas100_2026h2_1m.parquet"
MANIFEST=ROOT/"run_log/vwap_pullback_adx_nas100_20261012_cross_source/source_manifest.json"
files=[DIR/f"year=2026/month={i}/data.parquet" for i in range(6,11)]
def digest(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1<<20),b""):h.update(b)
 return h.hexdigest()
def main():
 if OUT.exists() or MANIFEST.exists():raise FileExistsError("no overwrite")
 source={str(p):digest(p) for p in files if p.exists()}
 a=pl.concat([pl.read_parquet(p) for p in files if p.exists()],how="vertical").sort("timestamp")
 a=a.filter((pl.col("timestamp")>=datetime(2026,6,1,tzinfo=timezone.utc))&
            (pl.col("timestamp")<datetime(2026,10,12,tzinfo=timezone.utc)))
 assert a.height>100000
 assert a["timestamp"].n_unique()==a.height
 assert a["volume"].min()>0
 assert a.select(pl.all().null_count()).sum_horizontal().sum()==0
 assert a.filter((pl.col("high")<pl.max_horizontal("open","close","low"))|(pl.col("low")>pl.min_horizontal("open","close","high"))).is_empty()
 OUT.parent.mkdir(parents=True,exist_ok=True)
 a.write_parquet(OUT,compression="zstd")
 d={"source":"London Strategic Edge","kind":"INDEX_NOT_FUTURES",
 "original_symbols":a["symbol"].unique().to_list(),
 "source_files":source,"prepared_sha256":digest(OUT),"prepared_path":str(OUT.relative_to(ROOT)),
 "rows":a.height,"first":str(a["timestamp"].min()),"last":str(a["timestamp"].max()),
 "cme_contracts":False,"exchange_volume_verified":False,
 "no_signal_outcomes_inspected":True,
 "comparison":"SECONDARY_CROSS_SOURCE_ONLY_NO_FUTURES_OOS_CLAIM"}
 MANIFEST.parent.mkdir(parents=True,exist_ok=True)
 MANIFEST.write_text(json.dumps(d,indent=2)+"\n")
 print(json.dumps(d,indent=2))
if __name__=="__main__":main()
