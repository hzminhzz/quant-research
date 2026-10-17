"""VOLT BREAK Phase 4: native ML4T backtest with audited entry-bar risk hook.

No hand-rolled order matching. All fills and cash accounting owned by
ml4t.backtest.Engine/Broker. 2018 warmup / 2019-2025 development ONLY.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from datetime import timezone
import numpy as np
import polars as pl
from ml4t.backtest import (
    AssetClass, BacktestConfig, ContractSpec, DataFeed, Engine, Strategy,
    CommissionType, ExecutionMode, StopFillMode
)
from ml4t.backtest.config import SlippageType
from ml4t.diagnostic.api import PortfolioAnalysis
from scripts.volt_break_native_adapter_20261012 import FixedPointStopFirst, VoltBreakNativeEngine

ROOT=Path(__file__).resolve().parents[1]
STORE=Path("/home/quant/dev/quant/ml4t-data/.data/store/index_minute_NQ")
OUT=ROOT/"run_log/research_sessions/volt_break_nq_20261012/phase4_native"
ASSET="NQ_CFD_PROXY"
COSTS={
  "zero":(0.0,0.0),
  "illustrative":(2.5,0.25),
  "double":(5.0,0.5),
}
MINUTES={"strict":1300,"coverage":1000}

def load_candidates() -> pl.DataFrame:
    files=[str(p) for y in range(2018,2026)
           for p in sorted((STORE/f"year={y}").glob("month=*/data.parquet"))]
    assert len(files)==96,(len(files),files[:3])
    raw=(pl.scan_parquet(files,hive_partitioning=False)
        .select(
           pl.col("timestamp").dt.replace_time_zone("UTC")
                 .dt.convert_time_zone("America/Chicago").alias("ct"),
           "open","high","low","close","volume"
         )
        .sort("ct")
        .with_columns(
           date=pl.col("ct").dt.date(),
           minute=pl.col("ct").dt.hour().cast(pl.Int32)*60 +
                  pl.col("ct").dt.minute().cast(pl.Int32))
        .with_columns(
            sess_date=pl.when(pl.col("minute")>=1020)
               .then(pl.col("date")+pl.duration(days=1))
               .otherwise(pl.col("date")))
        .collect())
    assert raw["ct"].n_unique()==raw.height
    assert raw.filter(pl.col("date").dt.year()==2026).is_empty()
    intraday=raw.filter(pl.col("date").dt.year().is_between(2019,2025) &
                      pl.col("minute").is_between(0,870))
    qualified=(intraday.group_by("date").agg(
         minutes=pl.col("minute").filter(pl.col("minute")<870).n_unique(),
         has_midnight=(pl.col("minute")==0).any(),
         has_exit=(pl.col("minute")==870).any(),
         min_volume=pl.col("volume").filter(pl.col("minute")<870).min()
       ).filter((pl.col("minutes")==870)&pl.col("has_midnight")&
                pl.col("has_exit")&(pl.col("min_volume")>0))
       .select("date"))
    assert qualified.height==1576,qualified.height
    allowed=intraday.join(qualified,on="date").sort("ct")
    session=(raw.group_by("sess_date").agg(
          n=pl.len(),h=pl.col("high").max(),l=pl.col("low").min(),
          c=pl.col("close").last()
         ).sort("sess_date").with_columns(prev_c=pl.col("c").shift(1)))
    for name,min_daily in MINUTES.items():
        dr=(session.with_columns(
              tr=pl.when((pl.col("n")>=min_daily)&
                         (pl.col("n").shift(1)>=min_daily))
              .then(pl.max_horizontal(pl.col("h")-pl.col("l"),
                   (pl.col("h")-pl.col("prev_c")).abs(),
                   (pl.col("l")-pl.col("prev_c")).abs()))
              .otherwise(None)
            ).with_columns(
                 atr=pl.col("tr").rolling_mean(window_size=15,min_samples=15).shift(1)
            ).select(pl.col("sess_date").alias("date"),
                     pl.col("atr").alias(f"atr_{name}")))
        allowed=allowed.join(dr,on="date",how="left")
    assert allowed["date"].n_unique()==1576
    # The full signal day is retained; the 14:30 row is an OPEN-only exit
    # snapshot, not information from the 14:30..14:31 trading minute.
    allowed=(allowed.with_columns(
         pv=((pl.col("high")+pl.col("low")+pl.col("close"))/3)*pl.col("volume")
       ).sort("ct").with_columns(
         v_sum=pl.col("volume").cum_sum().over("date"),
         pv_sum=pl.col("pv").cum_sum().over("date"))
       .with_columns(proxy_vwap=pl.col("pv_sum")/pl.col("v_sum")))
    mid=allowed.filter(pl.col("minute")==0).select("date",
                   pl.col("open").alias("midnight_open"))
    allowed=(allowed.join(mid,on="date")
       .with_columns(
          signal_strict=(pl.col("minute").is_between(599,839)) &
              ((pl.col("minute")+1)%30==0) &
              (pl.col("close")>pl.col("midnight_open")+0.30*pl.col("atr_strict"))&
              (pl.col("close")>pl.col("proxy_vwap")),
          signal_coverage=(pl.col("minute").is_between(599,839)) &
              ((pl.col("minute")+1)%30==0) &
              (pl.col("close")>pl.col("midnight_open")+0.30*pl.col("atr_coverage"))&
              (pl.col("close")>pl.col("proxy_vwap"))
       ))
    # Apply execution boundary snapshot at 14:30: don't expose after-cutoff
    # high/low/close to an Engine risk evaluation before the market flatten.
    allowed=(allowed.with_columns(
         pl.when(pl.col("minute")==870).then(pl.col("open"))
            .otherwise(pl.col("high")).alias("high"),
         pl.when(pl.col("minute")==870).then(pl.col("open"))
            .otherwise(pl.col("low")).alias("low"),
         pl.when(pl.col("minute")==870).then(pl.col("open"))
            .otherwise(pl.col("close")).alias("close")
       ).with_columns(
         pl.col("ct").dt.convert_time_zone("UTC").alias("timestamp"),
         pl.lit(ASSET).alias("asset")
       ).sort("timestamp"))
    return allowed

class VoltBreak(Strategy):
    asset=ASSET
    def __init__(self):
        self.entries=defaultdict(int)
        self.total_native_entries=0
        self.cap_violations=[]
        self.signal_decisions=0
        self.exit_orders=0

    def on_start(self,broker):
        broker.set_position_rules(FixedPointStopFirst(),asset=self.asset)

    def record_native_entry(self,fill):
        # Recorded from the native Broker fill *before* same-minute rule exits.
        local=fill.timestamp.astimezone(__import__("zoneinfo").ZoneInfo("America/Chicago"))
        day=local.date().isoformat()
        self.entries[day]+=1
        self.total_native_entries+=1
        if self.entries[day]>3:
            self.cap_violations.append(day)

    def on_data(self,timestamp,data,context,broker):
        bar=data[self.asset]
        local=timestamp.astimezone(__import__("zoneinfo").ZoneInfo("America/Chicago"))
        minute=local.hour*60+local.minute
        day=local.date().isoformat()
        pos=broker.get_position(self.asset)
        qty=float(pos.quantity) if pos else 0
        # At 14:29 after risk check, flatten at next 14:30 OPEN.
        if minute==869 and qty>0:
            broker.submit_order(self.asset,-qty)
            self.exit_orders+=1
            return
        if minute>839 or minute<599 or (minute+1)%30!=0:
            return
        if bar.get("signals",{}).get("go_long",False) and qty==0 and self.entries[day]<3:
            self.signal_decisions+=1
            broker.submit_order(self.asset,1)

def trial(input_df:pl.DataFrame,variant:str,cost:str) ->dict:
    com,slip=COSTS[cost]
    valid_days=input_df.filter(pl.col(f"atr_{variant}").is_not_null()).select("date").unique()
    candles=input_df.join(valid_days,on="date").sort("timestamp")
    assert candles.select("date").n_unique()==(156 if variant=="strict" else 491)
    signal_col=f"signal_{variant}"
    feed=DataFeed(
        prices_df=candles.select("timestamp","asset","open","high","low","close","volume"),
        signals_df=candles.select("timestamp","asset",pl.col(signal_col).alias("go_long"))
    )
    config=BacktestConfig(
        initial_cash=1_000_000,allow_short_selling=True,allow_leverage=True,
        fixed_margin_schedule={ASSET:(25000.,20000.)},
        execution_mode=ExecutionMode.NEXT_BAR,stop_fill_mode=StopFillMode.STOP_PRICE,
        commission_type=CommissionType.PER_CONTRACT if com>0 else CommissionType.NONE,
        commission_per_share=com,
        slippage_type=SlippageType.FIXED if slip>0 else SlippageType.NONE,
        slippage_fixed=slip
    )
    strategy=VoltBreak()
    engine=VoltBreakNativeEngine(feed,strategy,config,contract_specs={
       ASSET:ContractSpec(symbol=ASSET,asset_class=AssetClass.FUTURE,
                 multiplier=20,tick_size=.25,margin=25000.0)})
    result=engine.run()
    fills=result.to_fills_dataframe()
    trades=result.to_trades_dataframe()
    assert not strategy.cap_violations,strategy.cap_violations
    assert engine.adapter_entry_rule_evaluations==strategy.total_native_entries
    # Native ledger: any BUY opens one long; no accidental post-exit shorts.
    buys=fills.filter(pl.col("side")=="buy")
    sells=fills.filter(pl.col("side")=="sell")
    assert buys.height==strategy.total_native_entries,(buys.height,strategy.total_native_entries)
    assert buys.height==sells.height,(buys.height,sells.height)
    assert not result.to_trades_dataframe().filter(pl.col("status")=="open").height
    closed=trades.filter(pl.col("status")=="closed")
    assert closed.height==buys.height,(closed.height,buys.height)
    # Exit timestamps never past 14:30 CT.
    late=closed.with_columns(
        ct_exit=pl.col("exit_time").dt.convert_time_zone("America/Chicago")
      ).filter((pl.col("ct_exit").dt.hour().cast(pl.Int32)*60
                +pl.col("ct_exit").dt.minute().cast(pl.Int32))>870)
    assert late.height==0,late.height

    target=OUT/variant/cost
    target.mkdir(parents=True,exist_ok=True)
    trades.write_csv(target/"trades.csv")
    fills.write_csv(target/"fills.csv")
    # One observation per research day including flat days.
    curve=pl.DataFrame({"timestamp":[t for t,v in result.equity_curve],
                        "equity":[float(v) for t,v in result.equity_curve]})
    daily=(curve.with_columns(
        date=pl.col("timestamp").dt.convert_time_zone("America/Chicago").dt.date()
       ).group_by("date").agg(pl.col("equity").last()).sort("date"))
    daily.write_csv(target/"daily_equity.csv")
    equity=daily["equity"].to_numpy()
    returns=np.diff(np.r_[1_000_000.,equity])/np.r_[1_000_000.,equity][:-1]
    risk=PortfolioAnalysis(returns=returns,periods_per_year=252).compute_summary_stats()
    risk_values={k:v for k,v in vars(risk).items() if isinstance(v,(str,int,float,type(None),np.generic))}
    values=closed["pnl"].to_numpy()
    byyear=(closed.with_columns(year=pl.col("exit_time").dt.year())
        .group_by("year").agg(pl.len().alias("trades"),pl.col("pnl").sum().alias("net_pnl"),
             (pl.col("pnl")>0).mean().alias("win_rate")).sort("year"))
    byyear.write_csv(target/"yearly.csv")
    result_final=float(result.metrics["final_value"])
    ledger_pnl=float(np.sum(values))
    assert abs(result_final-1_000_000.-ledger_pnl)<1e-4,(result_final,ledger_pnl)
    stats={
      "variant":variant,"cost":cost,"calendar_days":valid_days.height,
      "signal_decisions":strategy.signal_decisions,
      "native_entry_count":buys.height,"native_exit_count":sells.height,
      "adapter_entry_risk_evaluations":engine.adapter_entry_rule_evaluations,
      "adapter_immediate_exit_fills":engine.adapter_entry_rule_exit_fills,
      "time_exit_orders":strategy.exit_orders,
      "total_net_pnl_usd":ledger_pnl,"final_equity_usd":result_final,
      "avg_trade_usd":float(np.mean(values)) if values.size else None,
      "win_rate":float(np.mean(values>0)) if values.size else None,
      "profit_factor":float(values[values>0].sum()/(-values[values<0].sum())) if np.any(values<0) else None,
      "winning_trades":int(np.sum(values>0)),"losing_trades":int(np.sum(values<0)),
      "daily_equity_risk_metrics":{k:(float(v) if isinstance(v,np.generic) else v) for k,v in risk_values.items()},
      "native_metrics":{k:(float(v) if isinstance(v,np.generic) else v) for k,v in result.metrics.items() if isinstance(v,(int,float,str,np.generic,type(None)))},
      "by_year":byyear.to_dicts(),
      "ledger_reconciliation_delta_usd":result_final-1_000_000-ledger_pnl,
      "attribution_risk": "source BID-only CFD proxy, provider VWAP, conservative stop-first ambiguous minute"
    }
    (target/"summary.json").write_text(json.dumps(stats,indent=2,default=str))
    return stats

def main():
    a=argparse.ArgumentParser()
    a.add_argument("--variant",choices=MINUTES)
    a.add_argument("--cost",choices=COSTS)
    args=a.parse_args()
    prepared=load_candidates()
    out={"qualified_dates":prepared["date"].n_unique(),
         "strict_atr_dates":prepared.filter(pl.col("atr_strict").is_not_null())["date"].n_unique(),
         "coverage_atr_dates":prepared.filter(pl.col("atr_coverage").is_not_null())["date"].n_unique(),
         "strict_signal_rows":int(prepared["signal_strict"].sum()),
         "coverage_signal_rows":int(prepared["signal_coverage"].sum())}
    print("INPUT",json.dumps(out),flush=True)
    variants=[args.variant] if args.variant else list(MINUTES)
    costs=[args.cost] if args.cost else list(COSTS)
    for variant in variants:
        for cost in costs:
            metrics=trial(prepared,variant,cost)
            print("RESULT",json.dumps({k:metrics[k] for k in ("variant","cost","calendar_days","native_entry_count","total_net_pnl_usd","avg_trade_usd","win_rate")}),flush=True)

if __name__=="__main__":main()
