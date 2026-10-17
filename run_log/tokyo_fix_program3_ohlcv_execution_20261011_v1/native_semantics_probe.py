from datetime import datetime, timedelta
import inspect, json, hashlib
from pathlib import Path
import polars as pl
from ml4t.backtest import Engine, Strategy, DataFeed, BacktestConfig
from ml4t.backtest.types import OrderType, ExecutionMode
from ml4t.backtest.execution.limits import PositiveVolumeLimit
from ml4t.backtest.config import ExecutionPrice, SlippageType
from ml4t.backtest.core.fill_engine import FillEngine
from ml4t.backtest.core.order_book import OrderBook

class Probe(Strategy):
    def __init__(self, ttl): self.ttl=ttl; self.order=None; self.cancel=None
    def on_data(self,timestamp,data,context,broker):
        minute=(timestamp.hour*60+timestamp.minute)-(9*60+55)
        if minute==0:
            self.order=broker.submit_order('USDJPY',-10000,order_type=OrderType.LIMIT,limit_price=150.0)
        if minute==self.ttl and self.order:
            self.cancel=broker.cancel_order(self.order.order_id)
        if minute==14 and broker.get_position('USDJPY'):
            broker.close_position('USDJPY')

def run(highs,vols,ttl=1,slip=0):
    start=datetime(2020,1,2,9,55)
    rows=[dict(timestamp=start+timedelta(minutes=i),asset='USDJPY',open=149.95,high=highs.get(i,149.98),low=149.90,close=149.95,volume=float(vols.get(i,0))) for i in range(17)]
    config=BacktestConfig(initial_cash=1500000,allow_short_selling=True,execution_mode=ExecutionMode.NEXT_BAR,execution_price=ExecutionPrice.OPEN,slippage_type=SlippageType.FIXED if slip else SlippageType.NONE,slippage_fixed=slip)
    strategy=Probe(ttl)
    result=Engine(DataFeed(prices_df=pl.DataFrame(rows)),strategy,config,execution_limits=PositiveVolumeLimit()).run()
    return {'fills':[{'timestamp':f.timestamp.isoformat(),'price':f.price,'side':f.side.value,'type':f.order_type,'quantity':f.quantity} for f in result.fills], 'cancel_return':strategy.cancel,'order_status':strategy.order.status.value}

cases={
'native_touch_inclusive':run({1:150.0},{1:1,15:1}),
'strict_gate_rejects_touch':run({1:150.0},{1:0,15:1}),
'no_same_bar_fill':run({0:150.1},{0:1,15:1}),
'strict_cross_allowed':run({1:150.006},{1:1,15:1}),
'TTL1_cancels_before_late_cross':run({2:150.1},{2:1,15:1}),
'TTL3_last_bar_allowed':run({3:150.1},{3:1,15:1},3),
'TTL3_late_bar_cancelled':run({4:150.1},{4:1,15:1},3),
'limit_slippage_violation':run({1:150.1},{1:1,15:1},slip=.005),
}
print(json.dumps(cases,indent=2))
assert len(cases['native_touch_inclusive']['fills'])==2
assert cases['strict_gate_rejects_touch']['fills']==[]
assert cases['no_same_bar_fill']['fills']==[]
assert cases['strict_cross_allowed']['fills'][0]['timestamp'].endswith('09:56:00')
assert cases['strict_cross_allowed']['fills'][1]['timestamp'].endswith('10:10:00')
assert cases['strict_cross_allowed']['fills'][0]['price']==150.0
assert cases['TTL1_cancels_before_late_cross']['fills']==[]
assert cases['TTL3_last_bar_allowed']['fills'][0]['timestamp'].endswith('09:58:00')
assert cases['TTL3_late_bar_cancelled']['fills']==[]
assert cases['limit_slippage_violation']['fills'][0]['price']<150
source_objs={'limit_matching':FillEngine.check_limit_fill,'cancel':OrderBook.cancel_order,'positive_volume_gate':PositiveVolumeLimit.calculate,'engine_constructor':Engine.__init__}
source={name:{'path':inspect.getsourcefile(obj),'line':inspect.getsourcelines(obj)[1],'signature':str(inspect.signature(obj)),'source_sha256':hashlib.sha256(Path(inspect.getsourcefile(obj)).read_bytes()).hexdigest()} for name,obj in source_objs.items()}
out=Path('run_log/tokyo_fix_program3_ohlcv_execution_20261011_v1/native_semantics_review.json')
out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps({'role':'VERIFIED','review_scope':'synthetic native execution only; no market outcomes read','library_version':'0.1.7','cases':cases,'source':source,'recommendation':'Native NEXT_BAR LIMIT with PositiveVolumeLimit synthetic 0/1 bar eligibility, unchanged OHLC, exact limit price and zero native slippage. Gate entries on strict high>limit+buffer inside TTL, permit scheduled exit. Explicit quote-currency roundtrip cost overlay converted at raw exit. Cancel after last permitted matching cycle.','timing':'09:54 close available at09:55; submit at09:55; first match09:56; TTL1 cancel after09:56 cycle; TTL3 cancel after09:58 cycle; submit exit10:09 for10:10 open.','limitations':['Gate volume is synthetic eligibility, not executable FX volume','Native inclusive touch is inadequate alone','Native slippage applies to limit fills and can violate limit','No native expiry/TTL order field found; cancellation is strategy-managed','FX quote account requires independent USD conversion','Within-bar crossing time/queue position/fill probability unknown']},indent=2)+'\n')
print(json.dumps({'output':str(out),'cases':cases},indent=2))
