"""Independent checks for the task-owned native Engine adapter."""
from scripts.run_fx_support_ml4t_execution_v2 import p0

def test_entry_bar_protection_and_gap_rejection():
    rows=p0()
    tie=rows[0]
    assert tie['entry_status']=='filled'
    assert tie['stop_status']=='filled'
    assert tie['target_status']=='cancelled'
    assert tie['filled_at'].minute==30
    assert tie['created_at'].minute==25
    assert rows[1]['trades']==0
    assert rows[2]['trades']==0

def test_future_intrabar_exit_cannot_change_another_pairs_opening_size():
    from datetime import datetime,timedelta,timezone
    import polars as pl
    from scripts.run_fx_support_ml4t_execution_v2 import SupportStrategy,engine
    t=datetime(2024,1,2,tzinfo=timezone.utc)
    times=[t+timedelta(minutes=5*i) for i in range(16)]
    observed=[]
    for hit_stop in (False,True):
        rows=[]
        for symbol in ('EURUSD','GBPUSD'):
            for ts in times:
                low=1.08 if hit_stop and symbol=='EURUSD' and ts==times[12] else 1.099
                rows.append(dict(timestamp=ts,symbol=symbol,open=1.1,high=1.101,low=low,close=1.1,volume=1000000.))
        signals={times[5]:[dict(symbol='EURUSD',event_timestamp=t,reference_high=1.11999,origin_support=1.09)],times[11]:[dict(symbol='GBPUSD',event_timestamp=times[6],reference_high=1.11999,origin_support=1.09)]}
        strategy=SupportStrategy(signals,{sym:times[-1] for sym in ('EURUSD','GBPUSD')})
        result=engine(pl.DataFrame(rows).sort('timestamp','symbol'),strategy,.00005).run()
        state=strategy.states[1]
        observed.append((state['entry'].filled_quantity,state['entry_equity'],state['concurrent_risk_fraction'],state['gross_leverage_at_entry']))
        assert result.metrics['num_trades']==2
    assert observed[0]==observed[1]
