"""Synthetic-quote regression checks for LSE quote-aware native ML4T fills."""
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from scripts import run_gotobi_lse_bidask_smoke_20261011 as q

D = date(2025,4,4)
JST = ZoneInfo("Asia/Tokyo")

def tick_at(h,m,s):
    return datetime.combine(D,time(h,m,s),tzinfo=JST).astimezone(timezone.utc)

def fake_seconds(buy_sec=1):
    return pl.DataFrame([
        {"ts":tick_at(2,59,58),"buy_ask":150.006,"sell_bid":150.000,"updates":2},
        {"ts":tick_at(3,0,buy_sec),"buy_ask":150.008,"sell_bid":150.001,"updates":9},
        {"ts":tick_at(9,53,58),"buy_ask":150.120,"sell_bid":150.110,"updates":3},
        {"ts":tick_at(9,54,1),"buy_ask":150.125,"sell_bid":150.110,"updates":5},
    ])

def test_quotes_never_use_earlier_or_future_tick():
    ev,error=q.selected_seconds(fake_seconds(),D,delay=1,extra=.25)
    assert error is None and len(ev)==4
    assert ev[0]["timestamp"]<=tick_at(2,59,59)
    assert ev[1]["timestamp"]>=tick_at(3,0,1)
    assert ev[2]["timestamp"]<=tick_at(9,53,59)
    assert ev[3]["timestamp"]>=tick_at(9,54,1)
    assert ev[1]["price"]==pytest.approx(150.008+.0025)
    assert ev[3]["price"]==pytest.approx(150.110-.0025)

def test_absent_quote_or_bad_age_rejected():
    ev,reason=q.selected_seconds(fake_seconds(buy_sec=8),D,1,.25)
    assert ev is None and "distance >5s" in reason

def test_native_engine_quote_fill_and_accounting(monkeypatch,tmp_path):
    monkeypatch.setattr(q,"SMOKE_DAYS",[D])
    monkeypatch.setattr(q,"OUT",tmp_path)
    calendar=pl.DataFrame({"session":[D],"gotobi":[True],"ordinary":[False]})
    res=q.run_arm(fake_seconds(),calendar,"synthetic_native","gotobi",1,.25)
    assert res["n"]==1
    assert res["source_quote_oracle_error"]<1e-6
    assert res["engine_jpy_reconciliation_error"]<1e-5
    assert res["net_usd"]==pytest.approx(
        (150.110-.0025-(150.008+.0025))*10000/(150.110-.0025))
    native=pl.read_parquet(tmp_path/"runs"/"synthetic_native"/"native_orders.parquet")
    assert native.height==2
    assert native["status"].to_list()==["filled","filled"]
