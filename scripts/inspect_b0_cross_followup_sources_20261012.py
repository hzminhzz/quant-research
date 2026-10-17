"""Read-only DAX source forensics and Nikkei alternative-feed availability.

Follow ml4t-validate-data and ml4t-polars-patterns. No simulation.
"""
from pathlib import Path
import hashlib, json
import polars as pl

ROOT=Path("/home/quant/dev/quant/ml4t-data/.data")
LIVE=ROOT/"store/index_minute_DAX"
ARCHIVE=ROOT/"archive/lse-index-refresh-20261005T112409Z/index_minute_DAX"
YEARS=[(2023,12),(2024,1),(2024,9),(2024,11),(2025,7),(2025,11),(2026,1),(2026,6)]
OUT=Path("run_log/one_bar_b0_cross_indices_20261012/followup_dax_nikkei_20261012")
OUT.mkdir(parents=True,exist_ok=True)
def get(r,y,m):
    f=r/f"year={y}/month={m}/data.parquet"
    if not f.is_file():return None
    return pl.read_parquet(f).select("timestamp","open","high","low","close","volume").sort("timestamp")
def stats(d):
    if d is None:return {"exists":False}
    return {"exists":True,"rows":d.height,"min":float(d["close"].min()),"median":float(d["close"].median()),"max":float(d["close"].max()),"lt3000":int(d["close"].lt(3000).sum()),"gt5000":int(d["close"].gt(5000).sum()),"first":str(d["timestamp"].min()),"last":str(d["timestamp"].max())}
def compare(a,b):
    if a is None or b is None:return {"overlap":0}
    j=a.join(b,on="timestamp",suffix="_prior",how="inner")
    if not j.height:return {"overlap":0}
    return {"overlap":j.height,
      "close_equal":int(j.select((pl.col("close")==pl.col("close_prior")).sum()).item()),
      "current_low_archive_high":int(j.select(((pl.col("close")<3000)&(pl.col("close_prior")>5000)).sum()).item()),
      "current_high_archive_low":int(j.select(((pl.col("close")>5000)&(pl.col("close_prior")<3000)).sum()).item()),
      "big_close_disagreement":int(j.select(((pl.col("close")-pl.col("close_prior")).abs()>1000).sum()).item()),
      "big_examples":j.filter((pl.col("close")-pl.col("close_prior")).abs()>1000).select(
          "timestamp","close","close_prior").head(10).to_dicts(),
    }
records=[]
for year,month in YEARS:
    a,b=get(LIVE,year,month),get(ARCHIVE,year,month)
    obj={"year":year,"month":month,"live":stats(a),"pre_refresh":stats(b),"paired":compare(a,b)}
    records.append(obj)
    print(year,month,"current",obj["live"]["rows"] if a is not None else 0,
          "prior",obj["pre_refresh"].get("rows"),"low_cur",obj["live"].get("lt3000"),
          "low_prior",obj["pre_refresh"].get("lt3000"),
          "overlap",obj["paired"].get("overlap"),"conflicts",obj["paired"].get("big_close_disagreement"),flush=True)
# Metadata (no full directory scan)
archives={}
for p in [ROOT/"store/.metadata/index_minute_DAX.json",
          ROOT/"archive/lse-index-refresh-20261005T112409Z/.metadata/index_minute_DAX.json",
          ROOT/"store/.metadata/index_minute_NIKKEI225.json"]:
    if p.is_file():
        x=json.loads(p.read_text())
        archives[str(p)]={k:v for k,v in x.items() if k!="partitions"}
for variant in ("duk27_deuidxeur_rebuild_v4","duk27_deuidxeur_rebuild_v3"):
    folder=ROOT/"rebuild"/variant/"index_minute_DAX"
    years=sorted({x.parent.parent.name for x in folder.glob("year=*/month=*/data.parquet")})
    archives[variant]={"year_range":years[:3]+years[-3:] if years else [],"count":len(list(folder.glob("year=*/month=*/data.parquet")))}
(OUT/"dax_source_comparison.json").write_text(json.dumps({"samples":records,"source_metadata":archives},indent=2,default=str)+"\n")
