"""JP225 substitution parity regression: protect no DE30 and time/entry invariants."""
from datetime import datetime, timedelta, timezone
import polars as pl
import pytest
from scripts.mechanicalpremia_jp225_substitution_v1 import (
    H_ASSETS, D_ASSETS, FILES, DATA_SYMBOLS, HOLDOUT,
    TRIAL_WEIGHTS, load_development, run_native,
)
def test_exact_substitution_and_source_allocation():
    assert H_ASSETS == {"US500","US100","JP225"}
    assert D_ASSETS == {"US500","US100","JP225","EU50"}
    assert "DE30" not in FILES
    assert DATA_SYMBOLS["JP225"]=="NIKKEI225"
    assert (TRIAL_WEIGHTS["PORTFOLIO-SOURCE-RISK"].h,
            TRIAL_WEIGHTS["PORTFOLIO-SOURCE-RISK"].d) == (0.2336,0.7664)
def test_new_protected_boundary_and_invalid_years():
    assert HOLDOUT == datetime(2026,10,12,tzinfo=timezone.utc)
    for frm,to in [(2012,2012),(2027,2027),(2013,2025),(2026,2027)]:
        with pytest.raises(ValueError):
            load_development("JP225",from_year=frm,until_year=to)
def test_native_seven_positions_no_de30():
    first=datetime(2024,5,6,tzinfo=timezone.utc)
    symbols=("US500","US100","JP225","EU50")
    data=pl.concat([pl.DataFrame({
        "timestamp":[first+timedelta(minutes=i) for i in range(6)],
        "asset":[sym]*6,"open":[100.0]*6,"high":[101.0]*6,
        "low":[99.0]*6,"close":[100.0]*6,"volume":[100.0]*6,
        "h_enter":[True]+[False]*5,"d_enter":[True]+[False]*5,
        "d_exit":[False]*6,"last_h_atr":[1.0]*6,
        "last_d_atr":[1.0]*6,
    }) for sym in symbols]).sort("timestamp","asset")
    _,out=run_native(data,"PORTFOLIO-SOURCE-RISK")
    f=out.to_fills_dataframe().filter(pl.col("side")=="buy")
    assert set(f["asset"].to_list())=={
        "US500_H","US100_H","JP225_H",
        "US500_D","US100_D","JP225_D","EU50_D"
    }
    assert out.metrics["num_rejected_orders"] == 0
    assert all(ts.replace(tzinfo=timezone.utc)>first for ts in f["timestamp"])
