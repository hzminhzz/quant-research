"""Exploratory native ML4T Engine replay for Tokyo Alpha Map Program 1.

Uses previously frozen Program 1 data, official bank-date registry, and only
JST 08:29-10:10 complete minute windows. Previously rejected significance
criteria remain rejected. No holdout is read. All fills are native Engine.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl
import statsmodels.api as sm
from ml4t.backtest import (
    BacktestConfig, DataFeed, Engine, ExecutionMode, OrderStatus,
    OrderType, Strategy,
)
from ml4t.backtest.config import CommissionType, ExecutionPrice, ShareType, SlippageType

ROOT = Path(__file__).resolve().parents[1]
SID = "tokyo_alpha_map_program1_native_exploratory_v2"
OUT = ROOT / "run_log" / SID
PREVIOUS = ROOT / "data/processed/tokyo_alpha_map_program1_v1"
CALENDAR = ROOT / "run_log/tokyo_fix_alpha_map_program1_20261010/execution_v1/calendar_event_registry.parquet"
FILES = [PREVIOUS / f"USDJPY_03_12_JST_{year}.parquet" for year in range(2020, 2027)]
JST = ZoneInfo("Asia/Tokyo")
START_USD = 10000.
NOTIONAL_USD = 10000.
MIN_START = 8*60+29
MIN_END = 10*60+10
WINDOW_BARS = MIN_END-MIN_START+1
SLIP_JPY = .005  # 0.5 pip per entry/exit fill, 1.0 pip total


def save_json(path: Path, result: dict):
    if path.exists():
        raise RuntimeError(f"Immutable artifact already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, default=str, allow_nan=False)+"\n")


def load_window():
    for p in FILES:
        if not p.exists():
            raise RuntimeError(f"Missing frozen development source: {p}")
    registry = pl.read_parquet(CALENDAR).select(
        "session", "gotobi", "ordinary", "weekday", "year", "complete_full")
    frame = (
        pl.scan_parquet([str(p) for p in FILES])
        .with_columns(
            pl.col("timestamp").dt.convert_time_zone("Asia/Tokyo").alias("jst")
        )
        .with_columns(
            pl.col("jst").dt.date().alias("session"),
            (pl.col("jst").dt.hour().cast(pl.Int32)*60
             +pl.col("jst").dt.minute().cast(pl.Int32)).alias("minute_jst")
        )
        .filter(pl.col("minute_jst").is_between(MIN_START, MIN_END))
        .filter(pl.col("session")<date(2026, 9, 1))
        .sort("timestamp")
        .collect()
    )
    if frame.is_empty():
        raise RuntimeError("Source empty")
    if frame["timestamp"].is_duplicated().sum():
        raise RuntimeError("Duplicate minute timestamp")
    if frame.filter(
        pl.any_horizontal(
            pl.col("open").is_null(),pl.col("close").is_null(),
            pl.col("open")<=0,pl.col("open").is_nan(),
        )
    ).height:
        raise RuntimeError("Invalid price")
    counts = frame.group_by("session").agg(
        pl.len().alias("available_bars"),
        pl.col("minute_jst").n_unique().alias("unique_minutes")
    )
    dates = registry.join(counts,on="session",how="left").with_columns(
        pl.col("available_bars").fill_null(0),
        pl.col("unique_minutes").fill_null(0)
    ).with_columns(
        ((pl.col("available_bars")==WINDOW_BARS)
         & (pl.col("unique_minutes")==WINDOW_BARS)).alias("complete_execution")
    )
    good = dates.filter(pl.col("complete_execution"))
    if good.is_empty():
        raise RuntimeError("No eligible complete trade windows")
    clean = frame.filter(pl.col("session").is_in(good["session"].to_list()))
    assert clean.height==good.height*WINDOW_BARS
    if clean["session"].max()>=date(2026,9,1):
        raise RuntimeError("Protected holdout contamination")
    # Calendar baseline is bank dates including zero-trade dates.
    panel = good.select("session","gotobi","ordinary","weekday","year","complete_full")
    # Keep raw minute open array: no interpolation, no current or future close.
    values = (
        clean.filter(pl.col("minute_jst").is_in([510,594,596,610]))
        .group_by("session").agg(
            pl.col("open").filter(pl.col("minute_jst")==510).first().alias("p0830"),
            pl.col("open").filter(pl.col("minute_jst")==594).first().alias("p0954"),
            pl.col("open").filter(pl.col("minute_jst")==596).first().alias("p0956"),
            pl.col("open").filter(pl.col("minute_jst")==610).first().alias("p1010"),
        )
    )
    panel=panel.join(values,on="session",how="inner",validate="1:1").sort("session")
    if panel.height!=good.height:
        raise RuntimeError("Missing essential open timestamps")
    gate={
       "source":"Frozen Program 1 v1 seven annual 03:00-12:00 JST snapshots",
       "source_sha256":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in FILES},
       "calendar_sha256":hashlib.sha256(CALENDAR.read_bytes()).hexdigest(),
       "bank_business_days_expected":registry.height,
       "full_03_12_complete":int(registry["complete_full"].sum()),
       "execution_window":"08:29 to 10:10 JST inclusive, full 102 minute opens",
       "complete_execution_dates":good.height,
       "gotobi_complete":int(good["gotobi"].sum()),
       "ordinary_complete":int(good["ordinary"].sum()),
       "execution_dates_min":str(good["session"].min()),
       "execution_dates_max":str(good["session"].max()),
       "end_of_2026_coverage":good.filter(pl.col("year")==2026).group_by("complete_full").agg(pl.len()).to_dicts(),
       "year_counts":dates.group_by("year","complete_execution","gotobi").agg(pl.len().alias("n")).sort("year","complete_execution","gotobi").to_dicts(),
       "weekday_counts":dates.group_by("weekday","complete_execution").agg(pl.len().alias("n")).sort("weekday","complete_execution").to_dicts(),
       "excluded_dates":[str(d) for d in dates.filter(~pl.col("complete_execution"))["session"].to_list()],
       "holdout_read":False,"fill_interpolation":False,
       "limitations":["This uses only complete-case 08:29-10:10 JST windows.",
                      "No genuine executable broker bid/ask, commission or swaps.",
                      "All 2020-Aug2026 outcomes previously explored; not independent OOS."]
    }
    save_json(OUT/"T0_interval_data_gate/result.json",gate)
    src=OUT/"execution_bars.parquet"
    if src.exists():raise RuntimeError(f"Existing snapshot: {src}")
    src.parent.mkdir(parents=True,exist_ok=True)
    clean.select("timestamp","symbol","open","high","low","close","volume","session").write_parquet(src)
    pth=OUT/"event_panel.parquet"
    if pth.exists():raise RuntimeError(f"Existing event panel: {pth}")
    panel.write_parquet(pth)
    return clean,panel,registry,gate


class TimedStrategy(Strategy):
    def __init__(self, side: str, dates: list[date]):
        self.side=side
        self.dates=set(dates)
        self.events=[]
        self.failures=[]
        self.rules={
            "H1_long":("08:29","09:53",1),
            "B1_short":("09:55","10:09",-1),
            "B0_short":("09:55","10:09",-1),
        }
    def on_start(self,broker):pass
    def on_data(self,timestamp,data,context,broker):
        local=timestamp.astimezone(JST)
        day=local.date()
        if day not in self.dates or "USDJPY" not in data:
            return
        hhmm=local.strftime("%H:%M")
        entry,exit_,side=self.rules[self.side]
        if hhmm==entry:
            if broker.get_position("USDJPY"):
                self.failures.append("Unexpected pre-existing position "+str(day))
                return
            order=broker.submit_order("USDJPY", side*NOTIONAL_USD)
            self.events.append(("entry",day,order))
        if hhmm==exit_:
            if not broker.get_position("USDJPY"):
                self.failures.append("Missing position at scheduled exit "+str(day))
                return
            order=broker.close_position("USDJPY",order_type=OrderType.MARKET)
            self.events.append(("exit",day,order))
    def on_end(self,broker):
        if broker.get_position("USDJPY"):
            self.failures.append("Open position at end")


def yearly_summary(trades):
    result=[]
    for g in trades.partition_by("year",maintain_order=True):
        profits=g["pnl_usd"]
        loss=abs(float(profits.filter(profits<0).sum()))
        gains=float(profits.filter(profits>0).sum())
        result.append({
            "year":int(g["year"][0]),"trades":g.height,
            "net_usd":float(profits.sum()),
            "net_pips_mean":float(g["net_pips"].mean()),
            "net_pips_total":float(g["net_pips"].sum()),
            "win_rate":float((profits>0).sum()/g.height),
            "profit_factor":gains/loss if loss>0 else None})
    return result


def backtest(arm: str, all_prices: pl.DataFrame,panel:pl.DataFrame,registry:pl.DataFrame):
    segment=panel.filter(pl.col("gotobi") if arm!="B0_short" else pl.col("ordinary"))
    dates=segment["session"].to_list()
    if not dates:raise RuntimeError("No selected days")
    bars=(all_prices.filter(pl.col("session").is_in(dates))
      .select("timestamp","symbol","open","high","low","close","volume")
      .sort("timestamp"))
    if bars.height!=len(dates)*WINDOW_BARS:
        raise RuntimeError("Execution source has missing bar")
    strategy=TimedStrategy(arm,dates)
    initial_quote=START_USD*float(bars["open"][0])
    config=BacktestConfig(initial_cash=initial_quote,
      allow_short_selling=True,allow_leverage=True,initial_margin=.5,
      execution_mode=ExecutionMode.NEXT_BAR,execution_price=ExecutionPrice.OPEN,
      share_type=ShareType.FRACTIONAL,commission_type=CommissionType.NONE,
      commission_rate=0.,
      slippage_type=SlippageType.FIXED,slippage_fixed=SLIP_JPY,
      partial_fills_allowed=False)
    result=Engine(DataFeed(prices_df=bars),strategy,config).run()
    if strategy.failures:raise RuntimeError("Strategy errors: "+str(strategy.failures))
    if len(strategy.events)!=len(dates)*2:
        raise RuntimeError(f"Order count mismatch {len(strategy.events)} vs {len(dates)*2}")
    expected_time={"H1_long":{"entry":"08:30","exit":"09:54"},
                   "B1_short":{"entry":"09:56","exit":"10:10"},
                   "B0_short":{"entry":"09:56","exit":"10:10"}}[arm]
    raw=[]
    for role,d,order in strategy.events:
        if order.status is not OrderStatus.FILLED or order.filled_at is None:
            raise RuntimeError(f"Unfilled order: {d} {role} {order.status}")
        clock=order.filled_at.astimezone(JST)
        if clock.date()!=d or clock.strftime("%H:%M")!=expected_time[role]:
            raise RuntimeError(f"Bad native fill time: {clock} vs {d} {expected_time[role]}")
        price=float(order.filled_price)
        if not math.isfinite(price):
            raise RuntimeError("Nonfinite fill price")
        raw.append({"session":d,"role":role,"price":price,"filled_at":order.filled_at})
    filled=pl.DataFrame(raw)
    a=filled.filter(pl.col("role")=="entry").select("session",pl.col("price").alias("entry"),pl.col("filled_at").alias("entry_time"))
    z=filled.filter(pl.col("role")=="exit").select("session",pl.col("price").alias("exit"),pl.col("filled_at").alias("exit_time"))
    closed=a.join(z,on="session",validate="1:1").sort("session").join(
        segment.select("session","p0830","p0954","p0956","p1010"),
        on="session",validate="1:1"
    )
    if closed.height!=len(dates):
        raise RuntimeError("Trade count mismatch")
    sign=1 if arm=="H1_long" else -1
    expected_entry=(pl.col("p0830") + SLIP_JPY) if sign==1 else (pl.col("p0956")-SLIP_JPY)
    expected_exit=(pl.col("p0954") - SLIP_JPY) if sign==1 else (pl.col("p1010")+SLIP_JPY)
    closed=closed.with_columns(expected_entry.alias("oracle_entry"),expected_exit.alias("oracle_exit"))
    if closed.filter(((pl.col("entry")-pl.col("oracle_entry")).abs()>1e-8) |
                     ((pl.col("exit")-pl.col("oracle_exit")).abs()>1e-8)).height:
        raise RuntimeError("Native executed fill differs from bar-open oracle")
    closed=closed.with_columns(
      ((pl.col("exit")-pl.col("entry"))*sign*NOTIONAL_USD).alias("pnl_jpy"),
      ((pl.col("exit")-pl.col("entry"))*sign*100.).alias("net_pips"),
      pl.col("session").dt.year().alias("year"))
    closed=closed.with_columns((pl.col("pnl_jpy")/pl.col("exit")).alias("pnl_usd"))
    closed=closed.with_columns((START_USD+pl.col("pnl_usd").cum_sum()).alias("equity_usd"))
    closed=closed.with_columns((pl.col("equity_usd")-pl.col("equity_usd").cum_max()).alias("closed_dd_usd"))
    native_delta=float(result.metrics["final_value"])-initial_quote
    pjy=float(closed["pnl_jpy"].sum())
    if not np.isclose(native_delta,pjy,atol=1e-4):
        raise RuntimeError(f"JPY broker mismatch {native_delta} vs {pjy}")
    # Include flat Tokyo bank days in daily Sharpe (not per-trade Sharpe).
    daily=(
      registry.select("session").sort("session")
      .join(closed.select("session","pnl_usd"),on="session",how="left")
      .with_columns(pl.col("pnl_usd").fill_null(0.))
      .with_columns((START_USD+pl.col("pnl_usd").cum_sum()).alias("equity_usd"))
      .with_columns((pl.col("pnl_usd")/(pl.col("equity_usd")-pl.col("pnl_usd"))).alias("return"))
    )
    arr=daily["return"].to_numpy()
    sh=float(arr.mean()/arr.std(ddof=1)*np.sqrt(252)) if arr.std(ddof=1)>0 else None
    usd=float(closed["pnl_usd"].sum())
    gross_pips=float(closed["net_pips"].mean()+1.)
    pos=closed["pnl_usd"]
    gains=float(pos.filter(pos>0).sum());loss=abs(float(pos.filter(pos<0).sum()))
    pname={"H1_long":"T3_gotobi_long_reference","B1_short":"T1_gotobi_short","B0_short":"T2_ordinary_short"}[arm]
    path=OUT/pname
    path.mkdir(parents=True,exist_ok=True)
    trades=path/"trades.parquet"
    if trades.exists():raise RuntimeError("Duplicate trade artifact "+str(trades))
    closed.write_parquet(trades)
    summary={
      "arm":arm,"status":"NATIVE_ENGINE_PASS_RESEARCH_EXPLORATORY",
      "starting_balance_usd":START_USD,"fixed_base_notional_usd":NOTIONAL_USD,
      "trades":closed.height,"actual_fills":len(strategy.events),
      "first_date":str(closed["session"].min()),"last_date":str(closed["session"].max()),
      "gross_mean_pips":gross_pips,
      "net_mean_pips":float(closed["net_pips"].mean()),
      "net_pnl_usd":usd,"end_equity_usd":START_USD+usd,
      "cumulative_return_pct":100*usd/START_USD,
      "win_rate":float((pos>0).sum()/closed.height),
      "profit_factor":gains/loss if loss>0 else None,
      "daily_closed_sharpe_with_bank_day_flats":sh,
      "max_closed_trade_drawdown_usd":float(closed["closed_dd_usd"].min()),
      "max_closed_trade_drawdown_pct_initial":100*float(closed["closed_dd_usd"].min())/START_USD,
      "simulated_cost":"1 pip round trip, 0.5 pip each fill; not broker-calibrated",
      "sensitivity_mean_net_pips":{str(c):gross_pips-c for c in [.8,1.,1.4]},
      "native_quote_initial_jpy":initial_quote,
      "native_quote_total_pnl_jpy":native_delta,
      "native_quote_recon_error_jpy":float(abs(native_delta-pjy)),
      "years":yearly_summary(closed),
      "limitations":["All studied history was previously inspected, not unseen holdout",
                     "No executable bid/ask, commissions or financing, synthetic broker ledger",
                     "Drawdown based on closed trades only; not intratrade MTM",
                     "No evidence that Gotobi-specific effect survives multiple-testing correction"]
    }
    save_json(path/"result.json",summary)
    return summary


def main():
    if (OUT/"T0_interval_data_gate/result.json").exists():
        raise RuntimeError("Already executed. Version before repeating.")
    prices,panel,registry,gate=load_window()
    results=[]
    for arm in ["B1_short","B0_short","H1_long"]:
        results.append(backtest(arm,prices,panel,registry))
        print(json.dumps({"completed":arm,"trades":results[-1]["trades"],
             "usd_pnl":results[-1]["net_pnl_usd"]}),flush=True)
    # Calendar-day HAC regression; no selection of favorable windows.
    trial=OUT/"T5_comparison/result.json"
    comparison=panel.with_columns(
       ((pl.col("p0956")-pl.col("p1010"))*100.).alias("gross_short_pips")
    )
    design=np.column_stack([
       np.ones(comparison.height),
       comparison["gotobi"].cast(pl.Float64).to_numpy(),
       *[(comparison["weekday"]==v).cast(pl.Float64).to_numpy()
         for v in [1,2,3,4]],
       *[(comparison["year"]==v).cast(pl.Float64).to_numpy()
         for v in range(2021,2027)]
    ])
    mod=sm.OLS(comparison["gross_short_pips"].to_numpy(),design).fit(
        cov_type="HAC",cov_kwds={"maxlags":5},use_t=True)
    prem={
      "estimated_gotobi_increment_pips":float(mod.params[1]),
      "ci95_pips":[float(v) for v in mod.conf_int(alpha=.05)[1]],
      "p_unadjusted":float(mod.pvalues[1]),
      "prior_program_holm_claim":"No Gotobi-specific increment passed 126-test Holm family",
      "status":"EXPLORATORY_ONLY_NOT_MULTIPLICITY_ADJUSTED",
      "cohort_dates":int(comparison.height),
      "gotobi_n":int(comparison["gotobi"].sum()),
      "ordinary_n":int(comparison["ordinary"].sum()),
    }
    save_json(trial,prem)
    print(json.dumps({"data_gate":{k:gate[k] for k in ["bank_business_days_expected","full_03_12_complete","complete_execution_dates","gotobi_complete","ordinary_complete","execution_dates_min","execution_dates_max"]},"runs":results,"comparison":prem},indent=2))
if __name__=="__main__":
    main()
