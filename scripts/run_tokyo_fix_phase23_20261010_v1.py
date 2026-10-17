"""Completeness-gated Gotobi feature and event diagnostics, development data only.

Reuses the immutable parent thesis. Cross-sectional IC does not apply to one FX
instrument, so ml4t.diagnostic.quantile_profile assesses event-level extension.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

import numpy as np
import polars as pl
import statsmodels.api as sm
from ml4t.engineer import compute_features
from ml4t.diagnostic import quantile_profile
from scripts.run_tokyo_fix_gotobi_diagnostics_20261010 import business, candidates

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data/processed/tokyo_fix_gotobi_20261010/USDJPY_dev_20260101_20260831_1m.parquet"
OUT = ROOT / "data/features/usdjpy_tokyo_fix_gotobi_20261010_continuous.parquet"
DIAG = ROOT / "run_log/usdjpy_tokyo_fix_gotobi_engine_20261010_v1/phase3/result.json"
AUDIT = ROOT / "run_log/usdjpy_tokyo_fix_gotobi_engine_20261010_v1/data_gate.json"

def save_json(path, data):
    if path.exists():
        raise RuntimeError(f"Refuse to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str, allow_nan=False) + "\n")

def mean_ci(values):
    v=np.asarray(values, dtype=float)
    if len(v)<3:
        return {"n":len(v),"status":"INCONCLUSIVE"}
    fit=sm.OLS(v,np.ones((len(v),1))).fit(cov_type="HAC",cov_kwds={"maxlags":min(5,len(v)-1)})
    return {"n":len(v),"mean_pips":float(fit.params[0]),"ci95_pips":fit.conf_int()[0].tolist(),"win_rate":float((v>0).mean())}

def main():
    if OUT.exists() or DIAG.exists() or AUDIT.exists():
        raise RuntimeError("Artifacts exist; create a new version, never overwrite")
    f=(pl.scan_parquet(SRC)
       .sort("timestamp")
       .with_columns(pl.col("timestamp").dt.convert_time_zone("Asia/Tokyo").alias("jst"))
       .with_columns(pl.col("jst").dt.date().alias("session"),
          (pl.col("jst").dt.hour().cast(pl.Int32)*60+pl.col("jst").dt.minute().cast(pl.Int32)).alias("minute_jst"))
       .collect())
    # Window must contain EVERY minute open 08:00..10:30 (151 observations).
    windows=(f.filter(pl.col("minute_jst").is_between(480,630))
      .group_by("session").agg(
        pl.len().alias("rows"),
        pl.col("minute_jst").n_unique().alias("unique_minutes"))
      .sort("session"))
    all_biz=[d for d in windows["session"].to_list() if business(d)]
    complete=windows.filter((pl.col("rows")==151)&(pl.col("unique_minutes")==151))
    valid={d for d in complete["session"].to_list() if business(d)}
    removed=sorted(set(all_biz)-valid)
    prices=f.filter(pl.col("session").is_in(sorted(valid)))
    # Safe train-only indicator context, not a backtest entry filter.
    computed=compute_features(
        f.select("timestamp","symbol","open","high","low","close","volume"),
        [{"name":"ema","params":{"period":50},"output":"ema50"},
         {"name":"atr","params":{"period":20},"output":"atr20"}],
        group_col="symbol",timestamp_col="timestamp",
    )
    if isinstance(computed,pl.LazyFrame): computed=computed.collect()
    enrich=(computed
       .with_columns(pl.col("timestamp").dt.convert_time_zone("Asia/Tokyo").alias("jst"))
       .filter(pl.col("jst").dt.strftime("%H:%M")=="08:29")
       .with_columns(pl.col("jst").dt.date().alias("session"))
       .select("session",pl.col("ema50").shift(1).alias("pre_ema50"),
                         pl.col("atr20").shift(1).alias("pre_atr20")))
    names={480:"p0800",510:"p0830",594:"p0954",595:"p0955",596:"p0956",630:"p1030"}
    ev=(prices.filter(pl.col("minute_jst").is_in(list(names)))
      .group_by("session")
      .agg([pl.col("open").filter(pl.col("minute_jst")==minute).first().alias(label)
            for minute,label in names.items()])
      .sort("session")
      .join(enrich,on="session",how="left",validate="1:1")
      .with_columns(
         pl.col("session").is_in(sorted(candidates())).alias("gotobi"),
         ((pl.col("p0954")-pl.col("p0830"))*100).alias("h1_long_pips"),
         ((pl.col("p0956")-pl.col("p1030"))*100).alias("h2_short_pips"),
         ((pl.col("p0955")-pl.col("p0800"))*100).alias("extension_pips"),
      )
      .with_columns(
         pl.col("extension_pips").rolling_std(window_size=20,min_samples=20).shift(1).alias("prior20_sd_pips")
      )
      .with_columns((pl.col("extension_pips")>1.5*pl.col("prior20_sd_pips")).alias("h2_gate")))
    if ev.is_empty() or ev["session"].max().year!=2026 or ev["session"].max().month>8:
        raise RuntimeError("Empty or holdout contamination")
    if ev.filter(pl.any_horizontal(*[pl.col(n).is_null() for n in names.values()])).height:
        raise RuntimeError("Missing required time price after continuity filter")
    if ev["session"].n_unique()!=len(valid):
        raise RuntimeError("Missing eligible events")
    OUT.parent.mkdir(parents=True,exist_ok=True)
    ev.write_parquet(OUT)
    save_json(AUDIT,{"source_sha256":hashlib.sha256(SRC.read_bytes()).hexdigest(),
         "calendar":"Bank of Japan official holiday schedule https://www.boj.or.jp/en/about/outline/holi.htm, Jan-Aug 2026 matches enumerated date list",
         "calendar_source_verified":"2026-10-10","heldout_not_read":True,
         "business_days_seen":len(all_biz),"complete_days":len(valid),"incomplete_days":len(removed),
         "incomplete_dates":[str(d) for d in removed],
         "gotobi_complete":int(ev["gotobi"].sum()),"total_events":ev.height,
         "minute_window":"08:00 through 10:30 JST inclusive, exactly 151 unique minute opens",
         "vendor_bid_ask":"not available; fixed slippage is hypothetical",
         "pretrade_features":"ml4t.engineer EMA50 ATR20, not used to change frozen entry rule"})
    g=ev.filter(pl.col("gotobi"))["h1_long_pips"].to_numpy()
    oth=ev.filter(~pl.col("gotobi"))["h1_long_pips"].to_numpy()
    fit=sm.OLS(ev["h1_long_pips"].to_numpy(),
        sm.add_constant(ev["gotobi"].cast(pl.Float64).to_numpy())).fit(cov_type="HAC",cov_kwds={"maxlags":5})
    gated=ev.filter(pl.col("gotobi")&pl.col("h2_gate").fill_null(False))
    profile={"status":"NOT_ATTEMPTED"}
    try:
        res=quantile_profile(
            ev.select(pl.col("session").alias("timestamp"),"extension_pips","h2_short_pips"),
            feature="extension_pips", label="h2_short_pips",by=None,
            n_quantiles=5,min_per_bucket=10)
        profile={"status":"COMPUTED_WITH_ML4T_DIAGNOSTIC","summary":str(res)[:3500]}
    except Exception as exc:
        profile={"status":"INCONCLUSIVE_LIBRARY_CONTRACT","error":str(exc)}
    out={
       "status":"EXPLORATORY","data_audit":str(AUDIT.relative_to(ROOT)),
       "feature_panel":str(OUT.relative_to(ROOT)),
       "library_features":["ml4t.engineer.compute_features: ema50, atr20"],
       "library_diagnostic":profile,
       "H1":{"gotobi":mean_ci(g),"ordinary":mean_ci(oth),
           "gotobi_minus_ordinary_pips":float(fit.params[1]),
           "difference_ci95_pips":fit.conf_int()[1].tolist(),
           "scenario_net_gotobi_mean_pips":{str(c):float(g.mean()-c) for c in (.8,1.0,1.4)}},
       "H2":{"gated":mean_ci(gated["h2_short_pips"].to_numpy()),
             "ungated":mean_ci(ev.filter(pl.col("gotobi"))["h2_short_pips"].to_numpy()),
             "selected_days":[str(d) for d in gated["session"].to_list()]}
    }
    save_json(DIAG,out)
    print(json.dumps({"audit":json.loads(AUDIT.read_text()),"diagnostics":out},indent=2,default=str))
if __name__=="__main__":
    main()
