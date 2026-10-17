"""VOLT BREAK native ML4T entry-bar lifecycle audit."""
from datetime import datetime,timedelta,timezone
import polars as pl
import pytest
from ml4t.backtest import AssetClass, BacktestConfig, ContractSpec, DataFeed, ExecutionMode, StopFillMode, Strategy
from scripts.volt_break_native_adapter_20261012 import FixedPointStopFirst, VoltBreakNativeEngine

ASSET="USATECH.IDX/USD"
class EnterOnce(Strategy):
    asset=ASSET
    def __init__(self):
        self.sent=False
    def on_start(self,broker):
        broker.set_position_rules(FixedPointStopFirst(),asset=self.asset)
    def on_data(self,timestamp,data,context,broker):
        if not self.sent:
            broker.submit_order(self.asset,1)
            self.sent=True

def fixture(rows):
    start=datetime(2024,1,8,15,59,tzinfo=timezone.utc)
    data=pl.DataFrame(dict(timestamp=[start+timedelta(minutes=i) for i in range(len(rows))],
             asset=[ASSET]*len(rows),open=[r[0] for r in rows],
             high=[r[1] for r in rows],low=[r[2] for r in rows],
             close=[r[3] for r in rows],volume=[1.]*len(rows)))
    cfg=BacktestConfig(initial_cash=1_000_000,allow_short_selling=True,allow_leverage=True,
       fixed_margin_schedule={ASSET:(25000.,20000.)},
       execution_mode=ExecutionMode.NEXT_BAR,stop_fill_mode=StopFillMode.STOP_PRICE)
    e=VoltBreakNativeEngine(DataFeed(prices_df=data),EnterOnce(),cfg,
       contract_specs={ASSET:ContractSpec(symbol=ASSET,asset_class=AssetClass.FUTURE,multiplier=20,
                                         tick_size=.25,margin=25000)})
    r=e.run()
    return e,r

@pytest.mark.parametrize("entry_bar,expected,reason",[
 ((100,145,20,100),25,"both-touch stop-first"),
 ((100,150,99,140),140,"target"),
 ((100,101,20,50),25,"stop"),
 ((20,30,15,25),None,"entry OPEN sets new stop at -55; no old-price stop"),
 ((160,170,155,165),None,"entry OPEN sets target at 200; no old-price target"),
 ((100,101,99,100),None,"no exit")
])
def test_entry_minute_native_risk(entry_bar,expected,reason):
    engine,result=fixture([(100,101,99,100),entry_bar])
    fills=result.to_fills_dataframe()
    exits=fills.filter(pl.col("side")=="sell")
    assert engine.adapter_entry_rule_evaluations==1,(reason,engine.adapter_entry_rule_evaluations)
    if expected is None:
        assert exits.height==0 and engine.broker.get_position(ASSET)
    else:
        assert exits.height==1,(reason,fills)
        assert exits["price"][0]==expected,(reason,exits)
        assert engine.broker.get_position(ASSET) is None,(reason,result.to_trades_dataframe())
        closed=result.to_trades_dataframe().filter(pl.col("status")=="closed")
        assert closed.height==1
        assert abs(closed["pnl"][0]-(expected-100)*20)<1e-7
        assert abs(result.metrics["final_value"]-1_000_000-(expected-100)*20)<1e-7
    assert fills["timestamp"][0].replace(tzinfo=timezone.utc)==datetime(2024,1,8,16,0,tzinfo=timezone.utc)
