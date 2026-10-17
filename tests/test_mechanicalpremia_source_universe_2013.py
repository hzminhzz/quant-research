"""Original-universe instrument membership and native trade clock tests."""
from datetime import datetime, timedelta, timezone
import polars as pl
import pytest
from scripts.mechanicalpremia_source_universe_2013_v1 import (
    FILES, H_ASSETS, D_ASSETS, HOLDOUT, load_development, run_native,
)

def test_exact_source_universe():
    assert set(FILES) == {"US500", "US100", "DE30", "EU50"}
    assert H_ASSETS == {"US500", "US100", "DE30"}
    assert D_ASSETS == {"US500", "US100", "DE30", "EU50"}
    for p in FILES.values():
        assert p.is_dir()

def test_reject_crossing_protected_test():
    with pytest.raises(ValueError, match="protected"):
        load_development("US500", from_year=2024, until_year=2025)

def test_seven_independent_sleeves_in_native_engine():
    start=datetime(2018,5,14,tzinfo=timezone.utc)
    series=[]
    for sym in ("US500","US100","DE30","EU50"):
        series.append(pl.DataFrame({
            "timestamp":[start+timedelta(minutes=i) for i in range(5)],
            "asset":[sym]*5,"open":[100.0]*5,"high":[101.0]*5,
            "low":[99.0]*5,"close":[100.0]*5,"volume":[100.0]*5,
            "h_enter":[True,False,False,False,False],
            "d_enter":[True,False,False,False,False],
            "d_exit":[False]*5,"last_h_atr":[1.0]*5,
            "last_d_atr":[1.0]*5,
        }))
    frame=pl.concat(series).sort("timestamp","asset")
    _,result=run_native(frame,"PORTFOLIO-SOURCE-RISK")
    fills=result.to_fills_dataframe()
    buys=fills.filter(pl.col("side")=="buy")
    assert buys.height==7,buys
    assert "EU50_D" in buys["asset"]
    assert "EU50_H" not in buys["asset"]
    assert set(buys["asset"])=={
        "US500_H","US100_H","DE30_H",
        "US500_D","US100_D","DE30_D","EU50_D",
    }
    assert result.metrics["num_rejected_orders"]==0
    assert all(t.replace(tzinfo=timezone.utc) >
               start for t in buys["timestamp"])

def test_source_risk_budgets_divided_across_seven_legs():
    from scripts.mechanicalpremia_source_universe_2013_v1 import TRIAL_WEIGHTS
    x=TRIAL_WEIGHTS["PORTFOLIO-SOURCE-RISK"]
    assert abs(3*(x.h/3)+4*(x.d/4)-1)<1e-12
