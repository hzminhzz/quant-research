"""Read-only ML4T feature parity and H1 source-clock audit for 2023 USD index proxy."""
from datetime import datetime, timezone
import polars as pl
import numpy as np
import talib
from ml4t.engineer import compute_features,feature_catalog
from scripts.mechanicalpremia_source_universe_2013_v1 import load_development,_aggregate,build_signals

asset="US500"
prices=load_development(asset,from_year=2023,until_year=2023)
sample=prices.filter(pl.col("timestamp")>=pl.datetime(2023,1,1,time_zone="UTC"))
hourly=(_aggregate(sample.with_columns(hkey=pl.col("timestamp").dt.truncate("1h")),"hkey")
        .filter(pl.col("minutes")==60).drop("hkey","minutes"))
engineered=compute_features(hourly,[
    {"name":"atr","params":{"period":14},"output":"atr14"},
    {"name":"bollinger_bands","params":{"period":40,"nbdevup":2.0,"nbdevdn":2.0},"output":"bb40"},
])
h=engineered["high"].to_numpy()
l=engineered["low"].to_numpy()
c=engineered["close"].to_numpy()
expected_atr=talib.ATR(h,l,c,timeperiod=14)
expected_bb_up,mid,lower=talib.BBANDS(c,timeperiod=40,nbdevup=2.0,nbdevdn=2.0,matype=0)
actual_atr=engineered["atr14"].to_numpy()
actual_bb=engineered["bb40"].struct.field("upper").to_numpy()
valid_atr=np.isfinite(expected_atr)&np.isfinite(actual_atr)
valid_bb=np.isfinite(expected_bb_up)&np.isfinite(actual_bb)
print("registry_discovered", {key: feature_catalog.describe(key)["parameters"] for key in ("atr","bollinger_bands")})
print("NUMERICAL_PARITY",{
    "observations":len(c),
    "atr_compared":int(valid_atr.sum()),
    "atr_max_abs_error":float(np.max(np.abs(expected_atr[valid_atr]-actual_atr[valid_atr]))),
    "bb_compared":int(valid_bb.sum()),
    "bb_upper_max_abs_error":float(np.max(np.abs(expected_bb_up[valid_bb]-actual_bb[valid_bb]))),
})
# Volatility filter matches MQL5's sorted[50] for 100 completed ATR values.
a=actual_atr
index=np.where(np.isfinite(a))[0]
med=a.copy()*np.nan
for i in range(99,len(a)):
    w=a[i-99:i+1]
    if np.isfinite(w).all():
        med[i]=np.sort(w)[50]
mql5_signal=(a<med)&(c>expected_bb_up)
actual_signal=((engineered.with_columns(
    pl.col("atr14").rolling_quantile(0.5,interpolation="higher",window_size=100,min_samples=100).alias("med"))
    .select((pl.col("atr14")<pl.col("med"))&(pl.col("close")>pl.col("bb40").struct.field("upper"))))
    .to_series().fill_null(False).to_numpy())
both=np.isfinite(med)
print("SIGNAL_PARITY",{"eligible_h1_bars":int(both.sum()),"oracle_signals":int(mql5_signal[both].sum()),
                     "engineer_signals":int(actual_signal[both].sum()),
                     "disagreements":int(np.count_nonzero(actual_signal[both]!=mql5_signal[both]))})
print("data",{"count":len(c),"min_date":str(hourly["timestamp"].min()),"max_date":str(hourly["timestamp"].max())})
