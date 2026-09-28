import numpy as np
from scripts.run_crypto_external_trend import metrics, simulate

def test_one_bar_execution_lag_blocks_same_day_profit():
    ret=np.array([[np.nan],[0.10],[0.0]],dtype=float)
    target=np.array([[10000.0],[10000.0],[10000.0]])
    reb=np.array([True,False,False])
    spread=np.zeros_like(target)
    eq, *_=simulate(ret,target,reb,spread)
    assert eq[0]==10000.0
    assert eq[1]>10000.0

def test_cost_and_carry_cannot_improve_equity():
    ret=np.array([[np.nan],[0.01],[0.01]],dtype=float)
    target=np.array([[-10000.0],[-10000.0],[-10000.0]])
    reb=np.array([True,False,False])
    spread=np.full_like(target,0.001)
    base=simulate(ret,target,reb,spread,short_carry=0.0)[0]
    stressed=simulate(ret,target,reb,spread,short_carry=0.10)[0]
    assert stressed[-1] <= base[-1]

def test_metrics_uses_anchor_before_window():
    dates=np.array(["2026-03-20","2026-03-21","2026-03-22"],dtype="datetime64[D]")
    eq=np.array([100.0,101.0,102.0])
    m=metrics(dates,eq,"2026-03-21")
    assert m["n_days"]==2
    assert abs(m["total_return"] - 0.02) < 1e-12
