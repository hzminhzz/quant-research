#!/usr/bin/env python3
"""Bounded LSE NQ.F validation source materialization; no trading outcomes."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
from datetime import datetime,timezone
import polars as pl
ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path("/home/quant/dev/quant/ml4t-data/.artifacts/lse-orb/raw-nq/futures_NQ.F_1m.parquet")
DEST=ROOT/"data/processed/vwap_adx_nqf_2026h2_validation_1m.parquet"
MANIFEST=ROOT/"run_log/vwap_pullback_adx_nq_20261012_proxy_v4_phase56/phase5_input_manifest.json"
SOURCE_SHA="c12e2aaf9e7a4bbe8224d09a53bc7416f7088a2693d87adf3de0138fbf6a8edd"
def sha(f):
 h=hashlib.sha256()
 with f.open("rb") as r:
  for b in iter(lambda:r.read(1<<20),b""):h.update(b)
 return h.hexdigest()
def main():
 if DEST.exists() or MANIFEST.exists():raise FileExistsError("existing evidence: do not overwrite")
 if sha(SOURCE)!=SOURCE_SHA:raise RuntimeError("SOURCE_DRIFT")
 x=pl.read_parquet(SOURCE).rename({"ts":"timestamp"}).filter(
  (pl.col("timestamp")>=datetime(2026,6,1,tzinfo=timezone.utc))&
  (pl.col("timestamp")<datetime(2026,10,12,tzinfo=timezone.utc)))
 assert x.height>120000
 assert x["timestamp"].is_sorted()
 assert x["timestamp"].n_unique()==x.height
 assert x["volume"].min()>0
 assert x.select(pl.all().null_count()).sum_horizontal().sum()==0
 assert x.filter((pl.col("high")<pl.max_horizontal("open","close","low"))|
                 (pl.col("low")>pl.min_horizontal("open","close","high"))).is_empty()
 assert x["symbol"].unique().to_list()==["NQ.F"]
 DEST.parent.mkdir(exist_ok=True,parents=True)
 x.write_parquet(DEST,compression="zstd")
 manifest={
 "source_vendor":"London Strategic Edge","source_symbol":"NQ.F",
 "source_contract_mapping":"UNKNOWN_CONTINUOUS",
 "source_volume_contract_verified":False,
 "input_source":str(SOURCE),"source_sha256":SOURCE_SHA,
 "prepared_path":str(DEST.relative_to(ROOT)),"prepared_sha256":sha(DEST),
 "rows":x.height,"min_timestamp":str(x["timestamp"].min()),
 "max_timestamp":str(x["timestamp"].max()),
 "data_end_is_bounded":True,"requested_validation_end":"2026-10-12",
 "test_window_primary":"2026-07-01 to 2026-09-30 full CT sessions",
 "october":"Oct 1-2 available, diagnostics only",
 "invalid_ohlc":0,"duplicate_timestamp":0,"zero_volume":0,
 "no_strategy_outcomes_inspected":True}
 MANIFEST.parent.mkdir(exist_ok=True,parents=True)
 MANIFEST.write_text(json.dumps(manifest,indent=2)+"\n")
 print(json.dumps(manifest,indent=2))
if __name__=="__main__":main()
