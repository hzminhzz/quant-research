"""VOLT BREAK feature-corrected NQ.F research.

Indicators MUST come from ml4t-engineer: ATR(14), SMA(15) of ATR,
and minute typical price. There is no session VWAP feature in the ML4T
registry, so only anchored weighted cumulative arithmetic uses pandas.
Native ML4T Backtest Broker owns fills and PnL. 2025 only; 2026 sealed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import polars as pl
import talib
from ml4t.engineer import compute_features
from ml4t.engineer.features.trend import sma
from ml4t.backtest import (AssetClass, BacktestConfig, ContractSpec,
       DataFeed, CommissionType, ExecutionMode, StopFillMode)
from ml4t.backtest.config import SlippageType
from scripts.volt_break_native_adapter_20261012 import VoltBreakNativeEngine
from scripts.run_volt_break_phase4_native_20261012 import VoltBreak
from ml4t.diagnostic.api import PortfolioAnalysis

ROOT=Path(__file__).resolve().parents[1]
SRC=Path("/home/quant/dev/quant/ml4t-data/.data/store/lse_futures_minute_NQ/year=2025")
OUT=ROOT/"run_log/research_sessions/volt_break_nq_20261012/phase4_engineer_lse"
ASSET="NQ.F"  # Provider-defined futures-series symbol; roll mapping unverified.
COSTS={"zero":(0.,0.),"illustrative":(2.5,.25),"double":(5.,.5)}
CT=ZoneInfo("America/Chicago")

def make_features():
    paths=sorted(SRC.rglob("*.parquet"))
    assert len(paths)==4,paths
    manifest=json.loads(Path("/home/quant/dev/quant/ml4t-data/.data/store/.metadata/lse_futures_minute_NQ.json").read_text())
    reference={p["path"]:p["sha256"] for p in manifest["partitions"]}
    hashes={}
    for path in paths:
        rel="lse_futures_minute_NQ/"+str(path.relative_to(SRC.parent.parent))
        # Verified by explicit path if metadata uses year=2025/month=...
        rel="lse_futures_minute_NQ/year=2025/"+str(path.relative_to(SRC))
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        assert reference[rel]==digest,(rel,digest,reference.get(rel))
        hashes[rel]=digest
    source=pl.concat([pl.read_parquet(path) for path in paths]).sort("timestamp")
    assert source["product"].unique().to_list()==["NQ.F"]
    assert source["timestamp"].n_unique()==source.height
    df=source.to_pandas()
    df["timestamp"]=pd.to_datetime(df["timestamp"],utc=True)
    df["ct"]=df["timestamp"].dt.tz_convert(CT)
    df["date"]=df["ct"].dt.date
    df["minute"]=df["ct"].dt.hour*60+df["ct"].dt.minute

    # 2025 cash-like daily volatility session 00:00--16:00 CT (exclusive).
    session_rows=df.loc[df["minute"].between(0,959)].copy()
    grouped=session_rows.groupby("date",sort=True)
    daily=grouped.agg(
        open=("open","first"),high=("high","max"),low=("low","min"),
        close=("close","last"),volume=("volume","sum"),
        minutes=("minute","nunique"),first=("minute","min"),last=("minute","max"))
    complete=daily.loc[(daily["minutes"]==960)&(daily["first"]==0)&(daily["last"]==959)].copy()
    complete["date"]=complete.index
    assert len(complete)>=40,("too few complete daily bars",len(complete))
    complete["timestamp"]=pd.to_datetime(complete["date"].astype(str)).dt.tz_localize(CT).dt.tz_convert("UTC")

    # The authoritative indicator calculations use ML4T Engineer.
    daily_input=pl.from_pandas(complete[["timestamp","open","high","low","close","volume"]].reset_index(drop=True))
    engineered=compute_features(daily_input,
         [{"name":"atr","params":{"period":14},"output":"daily_atr14"}],
         timestamp_col="timestamp")
    daily_atr=engineered["daily_atr14"].to_numpy()
    assert np.allclose(daily_atr,talib.ATR(complete["high"].to_numpy(),
        complete["low"].to_numpy(),complete["close"].to_numpy(),timeperiod=14),
        atol=1e-6,rtol=0,equal_nan=True),"ATR14 disagrees with TA-Lib"
    nested_sma=sma(daily_atr,period=15,implementation="numba")
    assert np.allclose(nested_sma,talib.SMA(daily_atr,timeperiod=15),
                       atol=1e-6,rtol=0,equal_nan=True),"SMA15 of ATR14 disagrees with TA-Lib"
    complete["atr14"]=daily_atr
    complete["sma15_atr14"]=nested_sma
    # Use strictly PREVIOUS completed daily volatility observation.
    complete["volatility_for_next_open"]=complete["sma15_atr14"].shift(1)
    valid=complete.loc[complete["volatility_for_next_open"].notna()].copy()
    assert not valid.empty, "not enough daily ATR warmup"
    assert (valid["volatility_for_next_open"]>0).all()

    # ML4T Engineer typical price. The engineer catalog has no anchored VWAP,
    # so its exact volume-weighted accumulation is delegated to grouped pandas
    # cumulative sums; there is no custom Polars indicator computation.
    minute_input=source.select("timestamp","open","high","low","close","volume")
    feature_minutes=compute_features(minute_input,
        [{"name":"typprice","output":"ml4t_typical_price"}],timestamp_col="timestamp").to_pandas()
    assert len(feature_minutes)==len(df)
    assert np.array_equal(feature_minutes["timestamp"].to_numpy(),df["timestamp"].to_numpy())
    df["ml4t_typical_price"]=feature_minutes["ml4t_typical_price"].to_numpy()
    assert np.allclose(df["ml4t_typical_price"].to_numpy(),
                       talib.TYPPRICE(df["high"].to_numpy(),
                           df["low"].to_numpy(),df["close"].to_numpy()),
                       rtol=0,atol=1e-6)
    active=df.loc[df["minute"].between(0,870)].copy()
    active=active.loc[active["date"].isin(valid.index)].sort_values("timestamp")
    active["cum_vol"]=active.groupby("date")["volume"].cumsum()
    active["cum_pv"]=(active["ml4t_typical_price"]*active["volume"]).groupby(active["date"]).cumsum()
    active["anchored_vwap"]=active["cum_pv"]/active["cum_vol"]
    assert active["cum_vol"].gt(0).all()
    midnight=active.loc[active["minute"]==0,["date","open"]].set_index("date")["open"]
    active["midnight_open"]=active["date"].map(midnight)
    active["atr_sma15_prior"]=active["date"].map(valid["volatility_for_next_open"])
    active["noise_barrier"]=active["midnight_open"]+0.30*active["atr_sma15_prior"]
    boundary=(active["minute"].between(599,839)&((active["minute"]+1)%30==0))
    active["go_long"]=boundary&(active["close"]>active["noise_barrier"])&(active["close"]>active["anchored_vwap"])
    # At 14:30 only the known OPEN is legitimate: do not reveal the later
    # high/low/close on the compulsory flatten event.
    mask=active["minute"]==870
    for c in ["high","low","close"]:
        active.loc[mask,c]=active.loc[mask,"open"]
    assert (active.groupby("date")["minute"].nunique()==871).all()
    samples=active.loc[boundary,["date","minute","timestamp","close","midnight_open",
                                  "atr_sma15_prior","noise_barrier","anchored_vwap","go_long"]]
    OUT.mkdir(parents=True,exist_ok=True)
    complete[["timestamp","atr14","sma15_atr14","volatility_for_next_open","minutes"]].to_csv(
        OUT/"engineer_daily_atr14_sma15.csv",index=False)
    samples.to_csv(OUT/"engineer_signal_values.csv",index=False)
    provenance={
        "provider":"LSE","symbol":"NQ.F","2025_source_partitions":hashes,
        "source_rows":len(df),"complete_0000_1600_sessions":len(complete),
        "signal_eligible_sessions":len(valid),"signals_before_execution":int(active["go_long"].sum()),
        "ml4t_engineer":["atr(period=14)","sma(ATR14,period=15)","typprice"],
        "daily_atr_parity_talib":True,"sma_atr_parity_talib":True,
        "minute_typprice_parity_talib":True,"timestamp_clock":"America/Chicago, DST-aware",
        "VWAP_method":"pandas grouped cumulative(ml4t typprice*provider volume)/cumulative(volume)",
        "limitations":["Provider NQ.F dated contract / roll semantics unknown",
           "Volume provided by LSE, not independently authenticated CME prints",
           "Original creator did not specify the inner ATR_Daily period: chosen conventional 14",
           "Only late 2025 development data; 2026 protected and unread"]
    }
    (OUT/"feature_parity.json").write_text(json.dumps(provenance,indent=2,allow_nan=False))
    return active,provenance

def run_trial(active,variant):
    commission,slip=COSTS[variant]
    frame=pl.from_pandas(active[["timestamp","open","high","low","close","volume","go_long"]].reset_index(drop=True))
    frame=frame.with_columns(pl.lit(ASSET).alias("asset"))
    feed=DataFeed(prices_df=frame.select("timestamp","asset","open","high","low","close","volume"),
                  signals_df=frame.select("timestamp","asset","go_long"))
    config=BacktestConfig(initial_cash=1_000_000,allow_short_selling=True,allow_leverage=True,
      fixed_margin_schedule={ASSET:(25000.,20000.)},
      execution_mode=ExecutionMode.NEXT_BAR,stop_fill_mode=StopFillMode.STOP_PRICE,
      commission_type=CommissionType.PER_CONTRACT if commission else CommissionType.NONE,
      commission_per_share=commission,
      slippage_type=SlippageType.FIXED if slip else SlippageType.NONE,
      slippage_fixed=slip)
    class VoltBreakLSE(VoltBreak):
        asset=ASSET
    strategy=VoltBreakLSE()
    engine=VoltBreakNativeEngine(feed,strategy,config,contract_specs={
       ASSET:ContractSpec(symbol=ASSET,asset_class=AssetClass.FUTURE,
                          multiplier=20,tick_size=.25,margin=25000)})
    result=engine.run()
    trades=result.to_trades_dataframe()
    fills=result.to_fills_dataframe()
    closed=trades.filter(pl.col("status")=="closed")
    buys=fills.filter(pl.col("side")=="buy")
    sells=fills.filter(pl.col("side")=="sell")
    assert not strategy.cap_violations
    assert len(buys)==len(sells)==len(closed)==strategy.total_native_entries
    assert not trades.filter(pl.col("status")=="open").height
    assert abs(float(closed["pnl"].sum() or 0)-float(result.metrics["final_value"]-1_000_000))<1e-4
    target=OUT/variant
    target.mkdir(parents=True,exist_ok=True)
    trades.write_csv(target/"trades.csv")
    fills.write_csv(target/"fills.csv")
    curve=pl.DataFrame({"timestamp":[ts for ts,value in result.equity_curve],
                        "equity":[float(value) for ts,value in result.equity_curve]})
    curve=(curve.with_columns(date=pl.col("timestamp").dt.convert_time_zone("America/Chicago").dt.date())
            .group_by("date").agg(pl.col("equity").last()).sort("date"))
    curve.write_csv(target/"daily_equity.csv")
    # Full 2025 daily calendar: no trades in warmup days, account remains flat.
    all_dates=sorted(active["date"].unique())
    daily=curve.to_pandas().set_index("date")["equity"].reindex(all_dates).ffill().fillna(1_000_000.)
    eq=daily.to_numpy()
    ret=np.diff(np.r_[1_000_000.,eq])/np.r_[1_000_000.,eq][:-1]
    risk=PortfolioAnalysis(returns=ret,periods_per_year=252).compute_summary_stats()
    sm={k:(float(v) if np.isscalar(v) and isinstance(v,(float,np.floating,int,np.integer)) and np.isfinite(v) else None)
        for k,v in vars(risk).items() if isinstance(v,(float,int,np.floating,np.integer))}
    vals=closed["pnl"].to_numpy() if len(closed)>0 else np.array([])
    stats={"variant":variant,"trades":len(closed),"signals":int(active["go_long"].sum()),
        "session_days":len(all_dates),"first_day":str(all_dates[0]),"last_day":str(all_dates[-1]),
        "total_pnl_usd":float(vals.sum()),"win_rate":float(np.mean(vals>0)) if len(vals) else None,
        "expectancy_usd":float(vals.mean()) if len(vals) else None,
        "profit_factor":float(vals[vals>0].sum()/-vals[vals<0].sum()) if np.any(vals<0) else None,
        "immediate_entry_minute_exits":engine.adapter_entry_rule_exit_fills,
        "native_costs":float(result.metrics["total_costs"]),"final_equity":float(result.metrics["final_value"]),
        "calendar_risk":sm,"native_trade_metrics":{k:v for k,v in result.metrics.items()
            if k in ("sharpe","calmar","max_drawdown","max_drawdown_pct","total_gross_pnl")},
        "explicit_no_2026_input":True}
    (target/"summary.json").write_text(json.dumps(stats,indent=2,default=str,allow_nan=False))
    print("BACKTEST",json.dumps(stats,default=str,allow_nan=False),flush=True)
    return stats

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--only-feature",action="store_true")
    args=parser.parse_args()
    df,provenance=make_features()
    print("FEATURES",json.dumps({k:provenance[k] for k in
        ("source_rows","complete_0000_1600_sessions","signal_eligible_sessions","signals_before_execution")},
        allow_nan=False),flush=True)
    if args.only_feature:return
    for variant in COSTS:
        run_trial(df,variant)

if __name__=="__main__":
    main()
