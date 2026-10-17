"""Source-equivalent C3 US-only and native fill timing invariants."""
from datetime import datetime,timedelta,timezone
import polars as pl
import pytest
from scripts.mechanicalpremia_us2_2013_2026_v1 import FILES,H_ASSETS,D_ASSETS,TRIAL_WEIGHTS,HOLDOUT,load_development,run_native

def test_exact_us2_source_universe_and_fixed_weights():
    assert set(FILES)=={"US500","US100"}
    assert H_ASSETS=={"US500","US100"}
    assert D_ASSETS=={"US500","US100"}
    w=TRIAL_WEIGHTS["PORTFOLIO-SOURCE-RISK"]
    assert (w.h,w.d)==(0.2336,0.7664)
    assert (2*w.h/2+2*w.d/2)==1.0

def test_protected_data_boundary():
    assert HOLDOUT == datetime(2026,10,12,tzinfo=timezone.utc)
    for asset,first,last in [("US500",2012,2012),("US500",2027,2027),("US500",2026,2027),("JP225",2024,2024)]:
        with pytest.raises(ValueError):
            load_development(asset,from_year=first,until_year=last)

def test_two_independent_h1_d1_native_legs_per_instrument():
    start=datetime(2024,1,2,tzinfo=timezone.utc)
    base=[]
    for asset in ("US500","US100"):
        base.append(pl.DataFrame({
           "timestamp":[start+timedelta(minutes=i) for i in range(7)],
           "asset":[asset]*7,"open":[100.0]*7,"high":[101.0]*7,
           "low":[99.0]*7,"close":[100.0]*7,"volume":[100.0]*7,
           "h_enter":[True]+[False]*6,"d_enter":[True]+[False]*6,
           "d_exit":[False]*7,"last_h_atr":[1.0]*7,
           "last_d_atr":[1.0]*7,
        }))
    d=pl.concat(base).sort("timestamp","asset")
    s,r=run_native(d,"PORTFOLIO-SOURCE-RISK")
    buys=r.to_fills_dataframe().filter(pl.col("side")=="buy")
    assert set(buys["asset"]) == {"US500_H","US100_H","US500_D","US100_D"}
    assert r.metrics["num_rejected_orders"]==0
    assert s.end_equity>0
    assert abs(s.end_cash+sum(p["quantity"]*p["current_price"]*p["multiplier"] for p in s.end_positions.values())-s.end_equity)<0.01
    assert all(t.replace(tzinfo=timezone.utc)>start for t in buys["timestamp"])
