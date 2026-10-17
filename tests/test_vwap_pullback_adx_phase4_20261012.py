"""Focused tests for native VWAP/ADX Strategy 2, 2026 H1 proxy."""
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import json

from scripts.run_vwap_pullback_adx_phase4_20261012 import (
    high_tick, low_tick, VwapPullback, prepare, ROOT, SID
)

CT=ZoneInfo("America/Chicago")


class Pending:
    counter=0
    def __init__(self):
        Pending.counter+=1
        self.order_id=f"synthetic-{Pending.counter}"
        self.status=type("Status",(),{"value":"pending"})()
        self.parent_id=None


class FakeBroker:
    def __init__(self):
        self.orders=[]
    def get_position(self,sym):
        return None
    def submit_order(self,*args,**kwargs):
        o=Pending()
        self.orders.append((o,args,kwargs))
        return o
    def cancel_order(self,order_id):
        return True


def bar(clock,close,high,low,adx=22,prev_adx=23,prior_close=99.5):
    stamp=datetime(2026,1,7,int(clock[:2]),int(clock[3:]),tzinfo=CT)
    features=dict(
        or_high=100,prior_close=prior_close,vwap=99,
        adx=adx,prior_adx=prev_adx,next_tp=102,next_sl=98,
    )
    return stamp,{"NQ.F":{"open":close,"high":high,"low":low,"close":close,"signals":features}}


def feed(strategy,broker,*bars):
    for ts,b in bars:
        strategy.on_data(ts,b,{},broker)


def test_tick_levels():
    assert high_tick(100.01)==100.25
    assert low_tick(99.99)==99.75
    assert high_tick(100.5)==100.5


def test_same_candle_touch_reclaim():
    strategy=VwapPullback("B2")
    broker=FakeBroker()
    feed(strategy,broker,
         bar("08:59",99.5,100,99.0),
         bar("09:00",100.5,101,99.9),
         bar("09:01",100.2,100.7,98.5))
    assert len(strategy.signal_log)==1
    assert strategy.signal_log[0]["expected_entry_at"]==datetime(2026,1,7,9,2,tzinfo=CT).isoformat()
    assert [x[2]["order_type"].value for x in broker.orders]==["market","stop","limit"]


def test_delayed_adx_gate():
    strategy=VwapPullback("B3")
    broker=FakeBroker()
    feed(strategy,broker,
         bar("08:59",99.5,100,99.0),
         bar("09:00",100.5,101,99.9),
         bar("09:01",100.2,100.7,98.5,adx=23,prev_adx=22),
         bar("09:02",100.3,101.0,99.2,adx=22,prev_adx=23))
    assert strategy.metrics["wait_adx"]==1
    assert len(strategy.signal_log)==1
    assert strategy.signal_log[0]["expected_entry_at"]==datetime(2026,1,7,9,3,tzinfo=CT).isoformat()


def test_reclaim_adx_below_threshold_needs_touch_again():
    strategy=VwapPullback("B3")
    broker=FakeBroker()
    feed(strategy,broker,
         bar("08:59",99.5,100,99.0),
         bar("09:00",100.5,101,99.9),
         bar("09:01",100.2,100.7,98.5,adx=19,prev_adx=20),
         bar("09:02",100.3,101.0,99.2,adx=23,prev_adx=24))
    assert strategy.signal_log==[]
    feed(strategy,broker,bar("09:03",100.2,101.0,98.8,adx=21,prev_adx=23))
    assert len(strategy.signal_log)==1


def test_session_grid_and_dst():
    x=prepare()
    assert x.height==122*446
    assert x["day"].n_unique()==122
    assert "2026-03-06" not in x["day"].cast(str).to_list()
    offsets=set(str(t.utcoffset()) for t in x["ct"].to_list())
    assert "-1 day, 18:00:00" in offsets  # UTC-6 in winter
    assert "-1 day, 19:00:00" in offsets  # UTC-5 in summer


def test_native_fills_audited_and_reconciled():
    root=ROOT/"run_log"/SID/"phase4"
    evidence=json.loads((root/"independent_audit_v2.json").read_text())
    assert evidence["status"]=="PASS_MECHANICAL"
    assert all(not v["fatal_findings"] for v in evidence["trials"])
    assert not evidence["exact_CME_execution_verified"]
