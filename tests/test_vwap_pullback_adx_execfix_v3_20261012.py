"""Behavioral red/green evidence for the v3 native fill adapter.

Use synthetic 1m OHLC only. These cases assert native engine OCO, stop-first,
legal sell limit price floors, and entry/stop adverse slippage semantics.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

import polars as pl
import pytest

from ml4t.backtest import (
    BacktestConfig, DataFeed, OrderStatus, OrderType, Strategy, ExecutionMode,
    ContractSpec,AssetClass, CommissionType,
)
from ml4t.backtest.config import SlippageType,FillOrdering
from scripts.run_vwap_pullback_adx_execfix_v3_20261012 import LegalLimitsEngine

SYM="NQ.F"
START=datetime(2026,1,7,15,0,tzinfo=timezone.utc)


class LinkedBracket(Strategy):
    def __init__(self):
        self.submitted=False
        self.entry=None
        self.stop=None
        self.target=None

    def on_data(self,timestamp,data,context,broker):
        if self.submitted:
            return
        self.submitted=True
        self.entry=broker.submit_order(SYM,1,order_type=OrderType.MARKET)
        self.stop=broker.submit_order(SYM,-1,order_type=OrderType.STOP,stop_price=95.0)
        self.target=broker.submit_order(SYM,-1,order_type=OrderType.LIMIT,limit_price=105.0)
        self.stop.parent_id=self.entry.order_id
        self.target.parent_id=self.entry.order_id


def simulate(open1=100.,high1=108.,low1=96.,slip=.25,fee=2.50):
    bars=pl.DataFrame({
        "timestamp":[START+timedelta(minutes=i) for i in range(4)],
        "asset":[SYM]*4,
        "open":[100.,open1,100.,100.],
        "high":[101.,high1,101.,101.],
        "low":[99.,low1,99.,99.],
        "close":[100.,100.,100.,100.],
        "volume":[1000.]*4,
    })
    strategy=LinkedBracket()
    cfg=BacktestConfig(
        initial_cash=1000000.0,allow_short_selling=False,allow_leverage=True,
        execution_mode=ExecutionMode.NEXT_BAR,fill_ordering=FillOrdering.EXIT_FIRST,
        commission_type=CommissionType.PER_CONTRACT,commission_per_share=fee,
        slippage_type=SlippageType.FIXED if slip else SlippageType.NONE,
        slippage_fixed=slip,
        fixed_margin_schedule={SYM:(25000.,20000.)},
    )
    spec=ContractSpec(symbol=SYM,asset_class=AssetClass.FUTURE,multiplier=20.0,tick_size=.25,margin=25000.)
    result=LegalLimitsEngine(DataFeed(prices_df=bars),strategy,cfg,contract_specs={SYM:spec}).run()
    return strategy,result


def test_native_sell_limit_legal_floor_even_with_fixed_adverse_slippage():
    strategy,result=simulate(open1=100,high1=110,low1=96,slip=.5)
    assert strategy.entry.status==OrderStatus.FILLED
    assert strategy.target.status==OrderStatus.FILLED
    assert strategy.stop.status==OrderStatus.CANCELLED
    fills=result.to_fills_dataframe()
    assert fills.height==2
    entry=fills.filter(pl.col("side")=="buy").row(0,named=True)
    exit=fills.filter(pl.col("side")=="sell").row(0,named=True)
    assert entry["price"]==100.5
    assert exit["order_type"]=="limit"
    assert exit["price"]==105.0
    assert exit["slippage"]==0.0
    assert exit["price"]>=exit["limit_price"]
    assert exit["commission"]==2.50


def test_stop_first_dual_touch_native_oco_no_double_exit_no_reverse():
    strategy,result=simulate(open1=100,high1=110,low1=90,slip=.25)
    assert strategy.stop.status==OrderStatus.FILLED
    assert strategy.target.status==OrderStatus.CANCELLED
    fills=result.to_fills_dataframe()
    assert fills.height==2
    assert fills["side"].to_list()==["buy","sell"]
    assert fills["order_type"].to_list()==["market","stop"]
    assert fills["price"].to_list()==[100.25,94.75]
    trades=result.to_trades_dataframe()
    assert trades.height==1 and trades["status"][0]=="closed"
    assert all(p.quantity>=0 for p in result.positions.values()) if hasattr(result,"positions") and result.positions else True


def test_stop_gap_open_worse_than_stop_and_sibling_cancellation():
    strategy,result=simulate(open1=93.0,high1=110,low1=90,slip=.25)
    assert strategy.stop.status==OrderStatus.FILLED
    assert strategy.target.status==OrderStatus.CANCELLED
    fills=result.to_fills_dataframe()
    assert fills["price"].to_list()==[93.25,92.75]
    assert fills.height==2


def test_no_touch_still_open_at_end_and_both_exit_orders_pending():
    # This is an isolated execution diagnostic, not the actual flat-at-15:55 strategy.
    strategy,result=simulate(open1=100.0,high1=103,low1=97,slip=.25)
    assert result.to_fills_dataframe().height==1
    assert strategy.stop.status==OrderStatus.PENDING
    assert strategy.target.status==OrderStatus.PENDING


def test_time_label_stays_next_bar_open():
    strategy,result=simulate(open1=100,high1=106,low1=96)
    assert strategy.entry.filled_at==START+timedelta(minutes=1)
    assert strategy.target.filled_at==START+timedelta(minutes=1)
