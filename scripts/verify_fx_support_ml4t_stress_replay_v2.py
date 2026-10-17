"""Native diagnostic for identical E1 quantities under E2 current-equity caps."""
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import polars as pl
from run_fx_support_ml4t_execution_v2 import ROOT,OUT,OOF,SupportStrategy,OpeningGate,engine,signal_map,dump,digest
from ml4t.backtest import OrderStatus
UTC=timezone.utc
baseline=pl.read_parquet(OUT/'E1_lightgbm_oof_capped_risk/trade_ledger.parquet').sort('entry_time').head(2)
required={(r['symbol'],r['event_timestamp']):r['quantity'] for r in baseline.to_dicts()}
oof=pl.read_parquet(OOF).join(baseline.select('symbol','event_timestamp'),on=['symbol','event_timestamp'],how='inner')
end=baseline['entry_time'].max()+timedelta(minutes=10)
frames=[]
for sym in ('EURUSD','GBPUSD','AUDUSD'):
    p=ROOT/f'data/processed/ftmo_fx_reversion_202610/{sym}_dev_2010_2017_5m.parquet'
    frames.append(pl.scan_parquet(p).filter((pl.col('timestamp')>=datetime(2017,1,1,tzinfo=UTC))&(pl.col('timestamp')<=end)).select('timestamp','open','high','low','close','volume').with_columns(pl.lit(sym).alias('symbol')).collect())
prices=pl.concat(frames).sort('timestamp','symbol')
final={r['symbol']:r['timestamp'] for r in prices.group_by('symbol').agg(pl.col('timestamp').max()).to_dicts()}
class ExactRequests(SupportStrategy):
    def on_data(self,timestamp,data,context,broker):
        prior=len(self.states)
        super().on_data(timestamp,data,context,broker)
        for state in self.states[prior:]:
            q=required[(state['symbol'],state['event_timestamp'])]
            state['required_quantity']=q
            state['size_limit']=q
            for name in ('entry','stop','target'):
                state[name].quantity=q
class ExactGate(OpeningGate):
    def validate_order_with_code(self,order,price):
        valid,reason,code=super().validate_order_with_code(order,price)
        state=self.strategy.by_order.get(order.order_id)
        if valid and state and order is state['entry'] and order.quantity!=state['required_quantity']:
            state['risk_capped_quantity']=order.quantity
            return False,'Identical E1 quantity exceeds E2 opening risk or leverage cap','matched_order_risk_conflict'
        return valid,reason,code
strategy=ExactRequests(signal_map(oof),final,slip=.0001)
e=engine(prices,strategy,.0001)
e.broker.gatekeeper=ExactGate(e.broker,strategy,.0001)
r=e.run()
rows=[]
for s in strategy.states:
    entry=s['entry']
    rows.append(dict(symbol=s['symbol'],event_timestamp=s['event_timestamp'],required_E1_quantity=s['required_quantity'],E2_risk_capped_quantity=entry.quantity,status=entry.status.value,rejection_code=entry.rejection_code,opening_equity=s['entry_equity']))
assert rows[0]['status']=='filled'
assert rows[1]['status']=='rejected' and rows[1]['rejection_code']=='matched_order_risk_conflict'
report=dict(status='BLOCKED',contract='Exact E1-order replay with E2 costs and unchanged current-equity risk/leverage caps',native_Engine_run=True,rows=rows,reason='The second E1 quantity must shrink under E2 current-equity caps. Keeping identical E1 orders violates a frozen cap; shrinking them changes the matched-order cohort.',holdout_opened=False,source_sha256=digest(__file__),economic_variant='Diagnostic only. No parameters, filter or threshold were tuned.')
dump(OUT/'E2_identical_order_replay_blocker.json',report)
r.to_fills_dataframe().write_parquet(OUT/'E2_replay_diagnostic_native_fills.parquet')
r.to_trades_dataframe().write_parquet(OUT/'E2_replay_diagnostic_native_trades.parquet')
print(json.dumps(report,indent=2,default=str))
