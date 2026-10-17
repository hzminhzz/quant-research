"""Materialize immutable LSE macro snapshots without inspecting Gotobi outcomes.

Research-only source copies. Yield "available_at" = UTC midnight three
calendar days after observation date: conservative proxy, NOT proven true
historical publication/vintage. Calendar archive creation is preserved.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path
from datetime import datetime,timedelta,time,timezone
import polars as pl

ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path("/home/quant/dev/quant/ml4t-data/.artifacts/gotobi_macro_20261011")
DEST=ROOT/"data/processed/gotobi_macro_context_20261011_v1"
MANIFEST=DEST/"source_manifest.json"

def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(2**20),b""):h.update(block)
    return h.hexdigest()

def load(name):
    p=SOURCE/f"{name}.json"
    o=json.loads(p.read_text())
    if not o["rows"] or o["query"].get("start")!="2020-01-01" or o["query"].get("end")!="2025-12-31":
        raise ValueError("Invalid source/coverage "+name)
    return o,p

def prepare():
    if MANIFEST.exists():
        raise RuntimeError("Already materialized, do not replace a frozen input")
    DEST.mkdir(parents=True,exist_ok=True)
    evidence=[]
    for code in ("US10Y","JP10Y"):
        o,source=load(code)
        raw=(pl.DataFrame(o["rows"])
             .select(pl.col("date").str.to_date().alias("observation_date"),
                     pl.col("symbol").cast(pl.String),
                     pl.col("value").cast(pl.Float64)).sort("observation_date"))
        if raw["observation_date"].is_duplicated().any() or raw["value"].is_null().any():
            raise ValueError("Duplicate/null value "+code)
        if raw.filter(pl.col("value").is_nan()).height:
            raise ValueError("NaN yield "+code)
        # Temporal buffer is >=72 hours from midnight at start of date.
        # This is an ASSUMPTION, not proof of vendor vintage correctness.
        df=raw.with_columns(
           (pl.col("observation_date").cast(pl.Datetime("us","UTC"))+
              pl.duration(days=3)).alias("available_at_assumed"))
        path=DEST/f"{code}.parquet"
        if path.exists():raise RuntimeError("Refuse overwrite "+str(path))
        df.write_parquet(path)
        evidence.append({"name":code,"source":str(source),"source_sha256":sha(source),
                        "local":str(path.relative_to(ROOT)),"local_sha256":sha(path),
                        "rows":df.height,"start":str(df["observation_date"].min()),
                        "end":str(df["observation_date"].max()),
                        "available_at":"observation_date + 3 UTC calendar days, hypothetical",
                        "historical_vintage_verified":False})
        print("SOURCE",code,df.height,flush=True)
    o,source=load("rate_events")
    events=(pl.DataFrame(o["rows"]).select(
        pl.col("id").cast(pl.Int64),
        pl.col("date").str.to_date().alias("event_date"),
        pl.col("datetime").str.to_datetime(time_zone="UTC").alias("event_at_utc"),
        pl.col("created_at").str.to_datetime(time_zone="UTC").alias("archive_created_at_utc"),
        pl.col("updated_at").str.to_datetime(time_zone="UTC").alias("archive_updated_at_utc"),
        pl.col("region_code").cast(pl.String),
        pl.col("event").cast(pl.String)))
    if events["id"].is_duplicated().any() or events["event_at_utc"].null_count():
        raise ValueError("Bad event archive")
    events=events.sort("event_at_utc")
    p=DEST/"rate_events.parquet"
    if p.exists():raise RuntimeError("Refuse overwrite events")
    events.write_parquet(p)
    post=events.filter(pl.col("archive_created_at_utc")>pl.col("event_at_utc")).height
    evidence.append({"name":"rate_events","source":str(source),"source_sha256":sha(source),
                     "local":str(p.relative_to(ROOT)),"local_sha256":sha(p),
                     "rows":events.height,"archive_record_created_after_event":post,
                     "historical_schedule_availability_verified":False,
                     "used_for_trading_decisions":False})
    payload={"source":"LSE SDK v0.14.0","capture_not_point_in_time":True,
             "no_post_august_2026_market_data":True,
             "data":[*evidence],
             "privacy":"API credential not stored",
             "research_note":"Macro yield series may be revised. Assumed +3d lag is not a vintage archive."}
    MANIFEST.write_text(json.dumps(payload,indent=2)+"\n")
    print("COMPLETE",json.dumps({"rows":[x["rows"] for x in evidence],
                                "event_archive_postdated":post}),flush=True)

if __name__=="__main__":
    prepare()
