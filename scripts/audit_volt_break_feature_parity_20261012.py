"""VOLT BREAK feature parity audit -- NO BACKTEST, NO 2026 DATA.

Compare earlier Globex-like 17:00-16:14 daily true-range convention with
Matteo's spoken 00:00-16:00 CT session convention (source transcript cited
in the accompanying report). Recompute exact daily-range coverage, ATR,
barrier and 30m signal disagreements. Do not inspect strategy P&L.
"""
import json
from pathlib import Path
import numpy as np
import polars as pl
from scripts.run_volt_break_phase4_native_20261012 import STORE,load_candidates,OUT

paths=[str(p) for y in range(2018,2026) for p in sorted((STORE/f"year={y}").glob("month=*/data.parquet"))]
assert len(paths)==96
data=(pl.scan_parquet(paths,hive_partitioning=False)
  .select(pl.col("timestamp").dt.replace_time_zone("UTC")
                .dt.convert_time_zone("America/Chicago").alias("ct"),
          "open","high","low","close","volume")
  .sort("ct")
  .with_columns(date=pl.col("ct").dt.date(),
       minute=pl.col("ct").dt.hour().cast(pl.Int32)*60+
              pl.col("ct").dt.minute().cast(pl.Int32))
  .filter(pl.col("minute").is_between(0,959))
  .collect())
daily=(data.group_by("date").agg(
      minute_count=pl.col("minute").n_unique(),
      first=pl.col("minute").min(),
      last=pl.col("minute").max(),
      h=pl.col("high").max(),l=pl.col("low").min(),
      c=pl.col("close").last())
    .sort("date")
    .with_columns(
      full=(pl.col("minute_count")==960)&(pl.col("first")==0)&(pl.col("last")==959),
      prev_c=pl.col("c").shift(1),
    )
    .with_columns(
      tr=pl.when(pl.col("full")&pl.col("full").shift(1).fill_null(False))
      .then(pl.max_horizontal(
        pl.col("h")-pl.col("l"),
        (pl.col("h")-pl.col("prev_c")).abs(),
        (pl.col("l")-pl.col("prev_c")).abs()
      )).otherwise(None)
    )
    .with_columns(
       atr_midnight_tr15=pl.col("tr").rolling_mean(window_size=15,min_samples=15).shift(1),
       atr_daily_wilder14=pl.col("tr").ewm_mean(alpha=1/14,adjust=False,min_samples=14)
    )
    .with_columns(
       atr_midnight_nested=pl.col("atr_daily_wilder14")
                  .rolling_mean(window_size=15,min_samples=15).shift(1)
    )
)
orig=load_candidates().filter((pl.col("minute").is_between(599,839))&
                         ((pl.col("minute")+1)%30==0))
mid=daily.select("date","minute_count","full",
        "atr_midnight_tr15","atr_midnight_nested")
v=orig.join(mid,on="date",how="left")
v=v.with_columns(
     signal_midnight_tr15=(pl.col("close")>
       pl.col("midnight_open")+0.30*pl.col("atr_midnight_tr15")) &
       (pl.col("close")>pl.col("proxy_vwap")),
     signal_midnight_nested=(pl.col("close")>
       pl.col("midnight_open")+0.30*pl.col("atr_midnight_nested")) &
       (pl.col("close")>pl.col("proxy_vwap"))
)
yearly=daily.filter(pl.col("date").dt.year().is_between(2019,2025)).with_columns(
       year=pl.col("date").dt.year()).group_by("year").agg(
        days=pl.len(),full_0000_1600=pl.col("full").sum(),
        min_daily_minutes=pl.col("minute_count").min(),
        median_daily_minutes=pl.col("minute_count").median(),
        median_last_minute=pl.col("last").median(),
        max_last_minute=pl.col("last").max()
       ).sort("year").to_dicts()
mean_features={}
for col in ["atr_strict","atr_coverage","atr_midnight_tr15","atr_midnight_nested"]:
    x=v.select("date",col).unique("date").drop_nulls()
    mean_features[col]={"eligible_days":x.height,"median_points":x[col].median(),
                      "median_barrier_increment_points":x[col].median()*.3 if x.height else None}
pairs={}
for baseline in ["strict","coverage"]:
    a=f"signal_{baseline}"
    for candidate in ["midnight_tr15","midnight_nested"]:
        b=f"signal_{candidate}"
        x=v.filter(pl.col(f"atr_{baseline}").is_not_null() &
                   pl.col(f"atr_{candidate}").is_not_null())
        pairs[f"{baseline}_vs_{candidate}"]={
            "common_qualified_days":x["date"].n_unique(),
            "possible_decisions":x.height,
            "original_positive_bars":int(x[a].sum()),
            "midnight_positive_bars":int(x[b].sum()),
            "disagree_bars":int(x.filter(pl.col(a)!=pl.col(b)).height),
            "feature_pearson":(lambda z: z if z is not None and np.isfinite(z) else None)(
               x.select(pl.corr(f"atr_{baseline}",f"atr_{candidate}")).item()),
            "median_abs_atr_delta_points":x.select((pl.col(f"atr_{baseline}")-
                         pl.col(f"atr_{candidate}")).abs().median()).item(),
        }
out={
"status":"FEATURE_PARITY_ONLY_NO_BACKTEST",
"source":"Dukascopy BID CFD minute OHLCV, 2018-2025",
"feature_origin":"Polars code in scripts/run_volt_break_phase4_native_20261012.py, not ml4t-engineer",
"original_atr_daily_session":"17:00 prior CT to 16:14 current CT",
"candidate_source_speech_daily_session":"00:00 to 16:00 CT same day",
"compare_only_not_strategy_optimization":True,
"daily_0000_to_1600_yearly":yearly,
"daily_variant_features":mean_features,
"signal_disagreements":pairs,
"source_limit":"CFD-proxy volume cannot produce authentic exchange-traded futures VWAP",
"note":"The nested Wilder14 ATR approximation is a diagnostic hypothesis; source daily ATR lookback is unspecified, so it is not asserted as exact."
}
path=OUT/"phase4_feature_parity_diagnostic_20261012.json"
path.write_text(json.dumps(out,indent=2,default=str,allow_nan=False))
print(json.dumps(out,indent=2,default=str,allow_nan=False))
