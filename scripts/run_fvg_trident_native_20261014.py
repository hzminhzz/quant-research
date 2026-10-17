"""T1/T2 native ML4T Engine portfolio backtest for frozen FVG trident FX MVP.

All fills, commissions, stop orders, margin accounting and PnL are owned by
ml4t.backtest.Engine. No homemade market simulation.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from importlib.metadata import version
from pathlib import Path
from zoneinfo import ZoneInfo
import hashlib
import json
import math
import os
import sys
import traceback

import numpy as np
import polars as pl
from ml4t.backtest import BacktestConfig, DataFeed, Engine, ExecutionMode, OrderType, OrderStatus, Strategy
from ml4t.backtest.config import CommissionType, SlippageType, ExecutionPrice, ShareType, FillOrdering, EntryOrderPriority
from ml4t.backtest.core.shared import SubmitOrderOptions
from ml4t.backtest.accounting.gatekeeper import Gatekeeper
from ml4t.backtest.analytics import EquityCurve

ROOT = Path(__file__).resolve().parents[1]
SESSION = "fvg_trident_fx_mvp_20261014_v1"
OUT = ROOT / "run_log" / SESSION
DATA = ROOT / "data/processed/ftmo_fx_reversion_202610"
EVENTS = ROOT / "data/features/fvg_trident_fx_mvp_20261014_v1_events.parquet"
EXITS = ROOT / "data/features/fvg_trident_fx_mvp_20261014_v1_daily_exits.parquet"
PAIRS = ("EURUSD", "GBPUSD", "AUDUSD")
UTC = timezone.utc
NY = ZoneInfo("America/New_York")
START_CASH = 100_000.0


def digest(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def save_json(path,obj):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("x") as handle:
        json.dump(obj,handle,indent=2,default=str,allow_nan=False)
        handle.write("\n")


def load_prices():
    dfs=[]
    for pair in PAIRS:
        for era in ("2010_2017","2018_2024"):
            f=pl.read_parquet(DATA/f"{pair}_dev_{era}_5m.parquet")
            assert f["symbol"].unique().to_list()==[pair]
            dfs.append(f.select("timestamp","symbol","open","high","low","close","volume"))
    prices=pl.concat(dfs).sort("timestamp","symbol")
    assert prices["timestamp"].max() < datetime(2025,1,1,tzinfo=UTC)
    return prices


def config(slip):
    return BacktestConfig(
        initial_cash=START_CASH,
        execution_mode=ExecutionMode.NEXT_BAR,
        execution_price=ExecutionPrice.OPEN,
        allow_leverage=True,allow_short_selling=False,
        initial_margin=0.1,long_maintenance_margin=0.08,short_maintenance_margin=0.08,
        share_type=ShareType.INTEGER,
        commission_type=CommissionType.PERCENTAGE,commission_rate=0.000025,
        slippage_type=SlippageType.PERCENTAGE,slippage_rate=slip,
        partial_fills_allowed=False,
        next_bar_simple_cash_check=False,next_bar_queue_shadow_validation=False,
        skip_cash_validation=False,buying_power_reservation=False,
        fill_ordering=FillOrdering.PRIORITY,
        entry_order_priority=EntryOrderPriority.NOTIONAL_DESC
    )


class RiskGate(Gatekeeper):
    """Native Gatekeeper extension validates actual next-open entry sizes."""
    def __init__(self,broker,strategy,slip):
        super().__init__(broker.account,broker.commission_model,
                         multiplier_resolver=broker.get_multiplier)
        self.broker=broker;self.strategy=strategy;self.slip=slip

    def validate_order_with_code(self,order,price):
        state=self.strategy.by_order.get(order.order_id)
        if state is None:
            return super().validate_order_with_code(order,price)
        b=self.broker
        if order is state.get("stop"):
            if state["entry"].status is not OrderStatus.FILLED:
                return False,"Stop parent not filled","parent_not_filled"
            return super().validate_order_with_code(order,price)
        if order is state.get("close"):
            if not b.get_position(order.asset):
                return False,"Already exited via stop","already_flat"
            return super().validate_order_with_code(order,price)
        if order is not state["entry"]:
            return super().validate_order_with_code(order,price)
        b.mark_account_positions(use_open=True)
        opening=b._current_opens[order.asset]
        if opening <= state["stop_price"]:
            self.strategy.rejects["opening_below_stop"]+=1
            return False,"Gap below stop","entry_gap_below_stop"
        if order.asset in b.account.positions:
            self.strategy.rejects["position_already_open"]+=1
            return False,"Already open","position_already_open"
        positions=b.account.positions
        equity=b.account.cash+sum(p.quantity*b._current_opens.get(a,p.current_price)
                                  for a,p in positions.items())
        if equity <= 0:
            return False,"Nonpositive equity","nonpositive_equity"
        execution_price=opening*(1+self.slip)
        risk_open=sum(max(0.,p.entry_price-self.strategy.active[a]["stop_price"])*p.quantity
                      for a,p in positions.items() if a in self.strategy.active)
        gross=sum(abs(p.quantity*b._current_opens.get(a,p.current_price))
                  for a,p in positions.items())
        available_risk=min(0.005*equity,max(0.,0.01*equity-risk_open))
        distance=execution_price-state["stop_price"]
        if distance <= 0:
            return False,"Stop on wrong side","invalid_stop"
        size=math.floor(min(state["size_limit"],available_risk/distance,
                            max(0.,10*equity-gross)/execution_price)/1000)*1000
        if size < 1000:
            self.strategy.rejects["too_little_risk_or_margin"]+=1
            return False,"Below minimum 1000 units","min_lot"
        order.quantity=float(size)
        state["stop"].quantity=float(size)
        state["initial_risk_usd"]=size*distance
        state["entry_risk_fraction"]=state["initial_risk_usd"]/equity
        state["concurrent_risk_fraction"]=(risk_open+state["initial_risk_usd"])/equity
        state["gross_leverage"]=(gross+size*execution_price)/equity
        assert state["entry_risk_fraction"] <= .0050000001
        assert state["concurrent_risk_fraction"] <= .0100000001
        assert state["gross_leverage"] <= 10.000000001
        return super().validate_order_with_code(order,execution_price)


class FVGNativeStrategy(Strategy):
    def __init__(self,signals,exits,final,slip):
        self.signals=signals;self.exits=exits;self.final=final;self.slip=slip
        self.active={};self.states=[];self.by_order={};self.rejects=Counter()

    def on_start(self,broker):
        return None

    def on_end(self,broker):
        assert not broker.account.positions, "Unliquidated account after terminal close"

    def on_data(self,timestamp,data,context,broker):
        for symbol,state in list(self.active.items()):
            if symbol not in data:
                continue
            entry=state["entry"]
            if entry.status is OrderStatus.REJECTED:
                broker.cancel_order(state["stop"].order_id)
                self.rejects["entry_order_rejected"]+=1
                del self.active[symbol]
                continue
            if entry.status is not OrderStatus.FILLED:
                continue
            if not broker.get_position(symbol):
                # Native stop order closed the position; no duplicated exit.
                if state.get("close") is not None:
                    broker.cancel_order(state["close"].order_id)
                del self.active[symbol]
                continue
            if state.get("close") is not None:
                continue
            end=timestamp==self.final[symbol]
            daily=timestamp in self.exits.get(symbol,set())
            if daily or end:
                # For the terminal sample only, use MOC to ensure that no
                # positions survive missing 2025 data. Terminal exit is
                # reported separately and is not claimed to be an author exit.
                kind=OrderType.MOC if end else OrderType.MARKET
                if end:
                    broker.cancel_order(state["stop"].order_id)
                order=broker.close_position(symbol,order_type=kind)
                if order:
                    state["close"]=order
                    state["close_reason"]="terminal" if end else "d1_ema21"
                    self.by_order[order.order_id]=state
        for event in self.signals.get(timestamp,[]):
            symbol=event["symbol"]
            if symbol not in data or timestamp>=self.final[symbol]:
                self.rejects["missing_feed_or_terminal"]+=1
                continue
            if symbol in self.active or broker.get_position(symbol):
                self.rejects["already_open_or_pending"]+=1
                continue
            next_open=event["entry_target_timestamp"]
            current=timestamp+timedelta(minutes=5)
            if next_open!=current:
                raise AssertionError(f"Wrong signal clock: {next_open} != {current}")
            ny=next_open.astimezone(NY)
            if not (180<=ny.hour*60+ny.minute<390):
                raise AssertionError(f"Out of NY entry session: {next_open}, {ny}")
            close=data[symbol]["close"]
            stop=event["origin_stop"]
            distance=close*(1+self.slip)-stop
            if distance<=0:
                self.rejects["signal_below_stop"]+=1
                continue
            equity=broker.get_account_value()
            size=math.floor(min(.005*equity/distance,10*equity/close)/1000)*1000
            if size < 1000:
                self.rejects["signal_size_below_lot"]+=1
                continue
            state=dict(event,stop_price=stop,size_limit=size,
                       entry_risk_fraction=None,initial_risk_usd=None,
                       close=None,close_reason=None)
            entry=broker.submit_order(symbol,float(size),_options=SubmitOrderOptions(priority_notional=1e30))
            protective=broker.submit_order(symbol,float(-size),
                    order_type=OrderType.STOP,stop_price=stop,
                    _options=SubmitOrderOptions(priority_notional=1e20))
            if entry is None or protective is None:
                raise AssertionError("Native order submission failed")
            protective.parent_id=entry.order_id
            state["entry"]=entry;state["stop"]=protective
            self.by_order[entry.order_id]=state;self.by_order[protective.order_id]=state
            self.active[symbol]=state;self.states.append(state)


def make_schedule():
    entries=pl.read_parquet(EVENTS)
    exits=pl.read_parquet(EXITS)
    signal_map={}
    for e in entries.to_dicts():
        signal_map.setdefault(e["decision_timestamp"],[]).append(e)
    exit_map={}
    for e in exits.filter(pl.col("daily_exit")).to_dicts():
        exit_map.setdefault(e["symbol"],set()).add(e["available_at"]-timedelta(minutes=5))
    return entries,signal_map,exit_map


def month_cluster_ci(ledger):
    """Simple fixed-seed month-block bootstrap of mean executed trade R."""
    if ledger.is_empty():
        return None
    t=ledger.with_columns(pl.col("exit_time").dt.strftime("%Y-%m").alias("month"))
    grouped=t.group_by("month").agg(pl.col("net_R").sum().alias("sum_r"),pl.len().alias("n"))
    sums=grouped["sum_r"].to_numpy()
    counts=grouped["n"].to_numpy()
    if len(sums)<2:
        return None
    rng=np.random.default_rng(20261014)
    n=len(sums)
    vals=[]
    for _ in range(4000):
        idx=rng.integers(0,n,n)
        vals.append(float(sums[idx].sum()/counts[idx].sum()))
    return dict(lower_95=float(np.quantile(vals,.025)),
                upper_95=float(np.quantile(vals,.975)),
                months=n,seed=20261014,resamples=4000)


def run_arm(prices,entries,signal_map,exit_map,slip,trial):
    path=OUT/trial
    path.mkdir(parents=True,exist_ok=False)
    final={r["symbol"]:r["timestamp"] for r in prices.group_by("symbol")
           .agg(pl.col("timestamp").max()).to_dicts()}
    strat=FVGNativeStrategy(signal_map,exit_map,final,slip)
    eng=Engine(DataFeed(prices_df=prices),strat,config(slip))
    eng.broker.gatekeeper=RiskGate(eng.broker,strat,slip)
    print(f"{trial}: native Engine start; bars={prices.height}, signals={entries.height}, slippage per side={slip}",flush=True)
    result=eng.run()
    native=result.to_trades_dataframe()
    result.to_fills_dataframe().write_parquet(path/"native_fills.parquet")
    result.to_rejected_orders_dataframe().write_parquet(path/"native_rejected_orders.parquet")
    native.write_parquet(path/"native_trades.parquet")
    eq=result.to_equity_dataframe()
    eq.write_parquet(path/"native_equity.parquet")
    filled=[]; orders=[]
    for state in strat.states:
        for role in ("entry","stop","close"):
            order=state.get(role)
            if order:
                orders.append(dict(symbol=order.asset,role=role,order_id=order.order_id,
                                   quantity=order.quantity,status=order.status.value,
                                   created_at=order.created_at,filled_at=order.filled_at,
                                   filled_price=order.filled_price,rejection_code=order.rejection_code))
        if state["entry"].status is OrderStatus.FILLED:
            e=state["entry"]
            assert e.created_at==state["decision_timestamp"]
            assert e.filled_at>=state["entry_target_timestamp"]
            ny=e.filled_at.astimezone(NY)
            assert 180<=ny.hour*60+ny.minute<390,"Fill outside specified NY hours"
            assert state["initial_risk_usd"]>0
            filled.append(dict(symbol=e.asset,entry_time=e.filled_at,
                  initial_risk_usd=state["initial_risk_usd"],
                  entry_risk_fraction=state["entry_risk_fraction"],
                  concurrent_risk_fraction=state["concurrent_risk_fraction"],
                  gross_leverage_at_entry=state["gross_leverage"],
                  origin_stop=state["stop_price"],close_reason=(
                      "stop" if state["stop"].status is OrderStatus.FILLED
                      else state["close_reason"])))
    save_json(path/"order_lifecycle.json",orders)
    if native.height != len(filled):
        raise AssertionError(f"Trades/entries differ: {native.height}, {len(filled)}")
    if native.height:
        metadata=pl.DataFrame(filled).with_columns(
           pl.col("entry_time").cast(pl.Datetime("us","UTC")))
        ledger=native.join(metadata,on=["symbol","entry_time"],how="left")
        if ledger["initial_risk_usd"].null_count()>0:
            raise AssertionError("Entry metadata not matched to native trades")
        ledger=ledger.with_columns((pl.col("pnl")/pl.col("initial_risk_usd")).alias("net_R"))
        assert all(t.status=="closed" for t in result.trades)
        # Independent arithmetic oracle only, not an alternative simulator.
        for trade in result.trades:
            expected=(trade.exit_price-trade.entry_price)*trade.quantity-trade.fees
            assert abs(trade.pnl-expected)<1e-6
            expected_fees=(trade.entry_price+trade.exit_price)*trade.quantity*.000025
            assert abs(trade.fees-expected_fees)<1e-6
        pnl=float(ledger["pnl"].sum())
        assert abs(pnl-(result.metrics["final_value"]-START_CASH))<1e-4
        per_pair=ledger.group_by("symbol").agg(
            pl.len().alias("completed_trades"),
            pl.col("net_R").mean().alias("mean_net_R"),
            pl.col("pnl").sum().alias("net_usd")).sort("symbol").to_dicts()
        per_era=ledger.with_columns(pl.when(pl.col("entry_time").dt.year()<2018)
                     .then(pl.lit("2010-2017")).otherwise(pl.lit("2018-2024")).alias("era")).group_by("era").agg(
            pl.len().alias("completed_trades"),
            pl.col("net_R").mean().alias("mean_net_R"),
            pl.col("pnl").sum().alias("net_usd")).sort("era").to_dicts()
        years=ledger.with_columns(pl.col("entry_time").dt.year().alias("year")).group_by(
            "year","symbol").agg(pl.len().alias("trades"),
            pl.col("net_R").mean().alias("mean_net_R")).sort("year","symbol").to_dicts()
        wins=ledger.filter(pl.col("pnl")>0)
        losses=ledger.filter(pl.col("pnl")<0)
        pf= float(wins["pnl"].sum() / -losses["pnl"].sum()) if losses.height else None
        wr=wins.height/native.height
        mean_r=float(ledger["net_R"].mean())
        gross_r=float(((ledger["pnl"]+ledger["fees"])/ledger["initial_risk_usd"]).mean()) if "fees" in ledger.columns else None
        ci=month_cluster_ci(ledger)
    else:
        ledger=native
        pnl=0.0;per_pair=[];per_era=[];years=[];pf=None;wr=None;mean_r=None;gross_r=None;ci=None
    ledger.write_parquet(path/"trade_ledger.parquet")
    # Native equity curve is the sole source of portfolio daily returns/risk.
    daily=(eq.select("timestamp","equity").with_columns(
        pl.col("timestamp").dt.truncate("1d").alias("date")).group_by(
        "date").agg(pl.col("equity").last().alias("equity"))
        .sort("date"))
    daily.write_parquet(path/"daily_equity.parquet")
    risk=EquityCurve(timestamps=daily["date"].to_list(),
                     values=daily["equity"].to_list(),
                     periods_per_year_override=252)
    metric=dict(
        trial=trial,session_id=SESSION,classification="EXPLORATORY",
        approval_status="NOT_APPROVED",engine="ml4t.backtest.Engine",
        engine_version=version("ml4t-backtest"),engine_execution_mode="NEXT_BAR OPEN",
        native_orders=True,native_stops=True,
        input_development_bars=prices.height,signal_count=entries.height,
        attempted_entries=len(strat.states),filled_entries=len(filled),
        completed_trades=native.height,
        rejected=dict(strat.rejects),net_usd=pnl,
        mean_net_R=mean_r,gross_mean_R_before_fees=gross_r,
        win_rate=wr,profit_factor=pf,
        daily_equity_sharpe=risk.sharpe,
        daily_max_drawdown=risk.max_dd,
        continuous_max_drawdown=float(eq["drawdown"].min()),
        bootstrap_monthly_mean_R_95ci=ci,
        per_pair=per_pair,per_era=per_era,per_year=years,
        native_metrics=result.metrics,
        commission_per_side_bps=0.25,
        slippage_proxy_per_side_bps=slip*10000,
        modeled_roundtrip_bps=(.000025+slip)*20000,
        source_snapshots="LSE historical FX 2010-2024",
        holdout_opened=False,
        completed_position_balance=len(eng.broker.account.positions),
        audit="Native trade PnL verified against executed fill price and native fees; final portfolio equity reconciled",
        caveats=["Actual historical FTMO bid/ask and swaps are unavailable.",
                 "D1 stop rule is declared MVP approximation, not author-verified.",
                 "Terminated open positions are MOC-liquidated on final 2024 observation."])
    save_json(path/"result.json",metric)
    print(f"{trial}: native finished, trades={native.height}, meanR={mean_r}, netUSD={pnl}, maxDD={risk.max_dd}",flush=True)
    return metric


def main():
    entries,mapping,exits=make_schedule()
    if entries.height != 53:
        raise AssertionError(f"D0 source changed unexpectedly: {entries.height} != 53")
    prices=load_prices()
    if (OUT/"T1_literal_native_engine"/"result.json").exists():
        print("T1 already completed: refusing duplicate and will inspect native artifact",flush=True)
        return
    run_arm(prices,entries,mapping,exits,.00005,"T1_literal_native_engine")
    run_arm(prices,entries,mapping,exits,.00010,"T2_execution_stress")


if __name__=="__main__":
    try:
        main()
    except Exception as e:
        OUT.mkdir(parents=True,exist_ok=True)
        p=OUT/"native_run_failure.json"
        if not p.exists():
            save_json(p,dict(error=str(e),traceback=traceback.format_exc(),pid=os.getpid(),
                             t=datetime.now(UTC).isoformat()))
        raise
