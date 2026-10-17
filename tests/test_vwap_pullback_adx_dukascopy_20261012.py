"""Dukascopy-only Strategy 2 source, cutoff, and native execution regression."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import polars as pl

from scripts.run_vwap_pullback_adx_dukascopy_20261012 import (
    prepare,session_filter,DukascopyClockStrategy,ROOT,OUT,DATA,SHA,
)
from scripts.run_vwap_pullback_adx_phase4_20261012 import sha

SID="vwap_pullback_adx_dukascopy_20261012_v1"
CT=ZoneInfo("America/Chicago")


def test_data_only_dukascopy_not_lse():
    x=pl.read_parquet(DATA)
    assert sha(DATA)==SHA
    assert x["symbol"].unique().to_list()==["DUK_USATECH"]
    assert x["timestamp"].min().year==2025
    assert x["timestamp"].max().strftime("%Y-%m-%d")=="2026-08-17"
    assert (ROOT/"run_log/research_sessions"/SID/"frozen_spec.json").exists()
    manifest=json.loads((OUT/"source_manifest.json").read_text())
    assert "duk21_usatechidxusd" in manifest["source_canonical_root"]
    assert manifest["source_tradeable_instrument"]=="NOT CME futures"


def test_cfd_session_is_1514_not_1555():
    a=prepare()
    from datetime import date
    dev,q1=session_filter(a,date(2026,1,1),date(2026,6,30))
    val,q2=session_filter(a,date(2026,7,1),date(2026,8,17))
    assert q1["accepted"]==103 and q2["accepted"]==33
    assert dev.height==103*405 and val.height==33*405
    assert "15:55" not in dev["clock"].unique().to_list()
    assert "15:55" not in val["clock"].unique().to_list()
    assert "15:14" in dev["clock"].unique().to_list()
    assert val["day"].min().isoformat()=="2026-07-01"
    assert val["day"].max().isoformat()=="2026-08-17"


def test_native_clock_queues_exit_after_1513_for_1514_open():
    class Position:
        quantity=1
    class FakeOrder:
        order_id="exit"
    class Broker:
        def __init__(self):self.active=True;self.orders=[]
        def get_position(self,asset):return Position() if self.active else None
        def submit_order(self,*args,**kwargs):
            self.orders.append((args,kwargs))
            return FakeOrder()
        def cancel_order(self,*args):return True
    broker=Broker()
    strategy=DukascopyClockStrategy("B2")
    strategy.on_data(datetime(2026,7,7,15,13,tzinfo=CT),{}, {},broker)
    assert len(broker.orders)==1
    assert broker.orders[0][0][:2]==("DUK_USATECH",-1)
    broker.active=False
    strategy.on_data(datetime(2026,7,7,15,14,tzinfo=CT),{}, {},broker)
    assert len(broker.orders)==1
    assert strategy.metrics["cfd_close_1514_queued"]==1


def test_audited_runs_and_no_nqf_source():
    a=json.loads((OUT/"independent_dukascopy_audit_v2.json").read_text())
    assert a["status"]=="PASS_MECHANICAL_CFD_PROXY"
    assert a["NQF_data_used"] is False
    assert a["CME_qualified"] is False
    assert not a["problems"]
    assert sum(len(v) for v in a["runs"].values())==24
    assert a["statistics"]["validation"]["B3"]["monthly"]["2026-07"]["trading_days"]==22
    assert a["statistics"]["validation"]["B3"]["monthly"]["2026-08"]["trading_days"]==11
