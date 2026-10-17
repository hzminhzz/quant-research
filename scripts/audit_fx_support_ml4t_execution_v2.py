"""Independent artifact oracle. No simulation or strategy metrics are calculated."""
import bisect
import hashlib
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
import polars as pl
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'run_log/fx_support_ml4t_execution_20261008_v2'
OOF=ROOT/'run_log/fx_support_conditions_20261008_ml_v2/I4_purged_lightgbm_v2/scored_events.parquet'
UTC=timezone.utc
prices={}; clocks={}; inputs=[]
for symbol in ('EURUSD','GBPUSD','AUDUSD'):
    paths=[ROOT/f'data/processed/ftmo_fx_reversion_202610/{symbol}_dev_{era}_5m.parquet' for era in ('2010_2017','2018_2024')]
    assert all('holdout' not in p.name for p in paths)
    frame=pl.concat([pl.scan_parquet(p).filter(pl.col('timestamp')>=datetime(2017,1,1,tzinfo=UTC)).select('timestamp','open','high','low','close').collect() for p in paths]).sort('timestamp')
    prices[symbol]={r['timestamp']:r for r in frame.to_dicts()}
    clocks[symbol]=frame['timestamp'].to_list()
    inputs.extend({'path':str(p.relative_to(ROOT)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths)
oof=pl.read_parquet(OOF)
assert oof.height==730 and oof.filter(pl.col('selected')).height==112
incomplete=[]
for row in oof.select('symbol','event_timestamp').to_dicts():
    if any(row['event_timestamp']+timedelta(minutes=i) not in prices[row['symbol']] for i in range(0,30,5)):
        incomplete.append({k:str(v) for k,v in row.items()})
reports=[]
for arm,slip in [('E0_unfiltered_oof_cohort_attempt2',.00005),('E1_lightgbm_oof_capped_risk',.00005),('E2_lightgbm_cost_stress',.00010)]:
    base=OUT/arm
    ledger=pl.read_parquet(base/'trade_ledger.parquet')
    native=pl.read_parquet(base/'native_trades.parquet')
    eq=pl.read_parquet(base/'native_equity.parquet')
    orders=json.loads((base/'orders.json').read_text())
    result=json.loads((base/'result.json').read_text())
    ties=0; gaps=0; delayed=0
    for r in ledger.to_dicts():
        symbol=r['symbol']; stamp=r['entry_time']; available=r['event_timestamp']+timedelta(minutes=30)
        expected=clocks[symbol][bisect.bisect_left(clocks[symbol],available)]
        assert stamp==expected,(symbol,stamp,expected)
        delayed+=int(stamp!=available)
        bar=prices[symbol][stamp]
        assert r['origin_support']+.00001<bar['open']<r['target_price']-.00001
        assert abs(r['entry_price']-bar['open']*(1+slip))<1e-12
        assert r['quantity']%1000==0 and r['quantity']>0
        assert abs(r['pnl']-((r['exit_price']-r['entry_price'])*r['quantity']-r['fees']))<1e-7
        assert abs(r['fees']-(r['entry_price']+r['exit_price'])*r['quantity']*.000025)<1e-7
        exitbar=prices[symbol][r['exit_time']]
        if r['close_reason']=='stop':
            expected_stop=min(exitbar['open'],r['origin_support'])*(1-slip)
            assert abs(r['exit_price']-expected_stop)<1e-12
            ties+=int(exitbar['high']>=r['target_price'])
            gaps+=int(exitbar['open']<r['origin_support'])
        if r['close_reason']=='target':
            assert abs(r['exit_price']-r['target_price']*(1-slip))<1e-12
            assert exitbar['low']>r['origin_support']
        assert r['entry_risk_fraction']<=.005+1e-12
        assert r['concurrent_risk_fraction']<=.01+1e-12
        assert r['gross_leverage_at_entry']<=3+1e-12
    assert abs(ledger['pnl'].sum()-(eq['equity'][-1]-100000))<1e-6
    assert ledger.height==native.height
    entry_orders=[r for r in orders if r['role']=='entry']
    rejected=[r for r in entry_orders if r['status']=='rejected']
    assert len(entry_orders)-len(rejected)==ledger.height
    assert all(r['status'] in ('filled','rejected','cancelled') for r in orders)
    reports.append(dict(arm=arm,status='PASS',trades=ledger.height,submitted_entries=len(entry_orders),rejected_entries=len(rejected),unsubmitted_signals=result['signals']-len(entry_orders),same_bar_stop_target_ties=ties,gap_stops=gaps,entries_delayed_by_missing_next_open=delayed,pnl_equity_absolute_error=abs(ledger['pnl'].sum()-(eq['equity'][-1]-100000)),order_statuses={status:sum(r['status']==status for r in orders) for status in ('filled','rejected','cancelled')}))
# Show the E3 gap with timestamp-only evidence and no holdout reads.
cut=datetime(2020,5,25,21,40,tzinfo=UTC)
gap_evidence=[str(ts) for ts in clocks['GBPUSD'] if cut<=ts<=cut+timedelta(minutes=30)]
report=dict(status='PASS',holdout_opened=False,inputs=inputs,oof_sha256=hashlib.sha256(OOF.read_bytes()).hexdigest(),oof_events=730,oof_selected=112,incomplete_retest_components=incomplete,arms=reports,E3_gap_UTC_timestamps=gap_evidence,verification='Independent oracle checked exact first available own-pair open, entry cost fractions, stop-first ties, stop gaps, targets, lot sizes, risk caps, statuses and native equity reconciliation.',limitations=['E2 applies the same signals and risk rules with stress costs. Its quantities and trade cohort differ from E1, so it is not an identical-order replay.','The immutable E0 failed terminal record is retained. The corrected completed baseline is in attempt2 and the supplemental attempt ledger.'])
path=OUT/'independent_execution_audit.json'
assert not path.exists()
path.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
