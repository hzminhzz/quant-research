"""Read-only source-clock/feature-delta audit on frozen 2023-2024 H1 bars.

No PnL, trade, fill, label, optimized parameters, or protected date access.
Indicators use ONLY registered ml4t-engineer pipelines.
"""
from __future__ import annotations
import json
from pathlib import Path
import polars as pl
from scripts.audit_mechanicalpremia_yen_squeeze_native_20261014 import build_complete_h1
from scripts.mechanicalpremia_yen_squeeze_native_strategy_20261014 import build_features as old_wilder_features
from scripts.mechanicalpremia_yen_squeeze_mt5atr_features_20261014 import build_mt5_features

ROOT=Path(__file__).resolve().parents[1]
SOURCES={
 "USDJPY":"data/processed/mechanicalpremia_yen_squeeze_mvp_20261014/USDJPY_2023_2024_1m.parquet",
 "GBPJPY":"data/processed/mechanicalpremia_yen_squeeze_mvp_20261014/GBPJPY_2023_2024_1m.parquet",
 "CADJPY":"data/processed/mechanicalpremia_yen_squeeze_proxy_20261014/CADJPY_2023_2024_1m.parquet",
}
DEST=ROOT/"docs/audit/mechanicalpremia_yen_squeeze_mt5atr_v4_real_feature_delta_20261014.json"

def main():
 if DEST.exists(): raise FileExistsError(DEST)
 out={}
 for symbol,p in SOURCES.items():
  minutes=pl.read_parquet(ROOT/p)
  if minutes.filter(pl.col("timestamp")>=pl.datetime(2025,1,1,time_zone="UTC")).height:
   raise AssertionError("protected market date in input")
  h1,_=build_complete_h1(minutes,naive_is_utc=minutes.schema["timestamp"].time_zone is None)
  old=old_wilder_features(h1)
  new=build_mt5_features(h1)
  old_flag=(pl.col("atr14")<pl.col("atr100_upper_median")).alias("eligible_old")
  new_flag=(pl.col("atr14")<pl.col("atr100_upper_median")).alias("eligible_new")
  combined=old.select("timestamp","atr14","atr100_upper_median").with_columns(old_flag).join(
   new.select("timestamp","atr14","atr100_upper_median").with_columns(new_flag),on="timestamp",suffix="_new")
  window=combined.filter(pl.col("eligible_old").is_not_null()&pl.col("eligible_new").is_not_null()&
     pl.col("atr14").is_finite()&pl.col("atr14_new").is_finite()&
     pl.col("atr100_upper_median").is_finite()&pl.col("atr100_upper_median_new").is_finite())
  stats=window.select(
      pl.len().alias("valid_h1"),
      (pl.col("eligible_old")!=pl.col("eligible_new")).sum().alias("regime_decision_differences"),
      pl.col("eligible_old").sum().alias("eligible_wilder"),
      pl.col("eligible_new").sum().alias("eligible_mt5"),
      (pl.col("atr14_new")-pl.col("atr14")).abs().mean().alias("mean_abs_atr_diff_jpy"),
      ((pl.col("atr14_new")-pl.col("atr14")).abs()/pl.col("atr14")).mean().alias("mean_abs_relative_atr_diff")
  ).row(0,named=True)
  out[symbol]={"h1_full":h1.height,**stats}
  print(symbol,json.dumps(out[symbol]),flush=True)
 DEST.write_text(json.dumps({"session_id":"mechanicalpremia-yen-squeeze-mt5atr-v4-20261014",
   "data_window":"2023-01-01 to 2024-12-31",
   "features":"ml4t-engineer registered pipelines only",
   "trials_outcomes_observed":False,
   "metrics":out},indent=2)+"\n")
 print("FEATURE_DELTA_COMPLETE",str(DEST))

if __name__=="__main__":main()
