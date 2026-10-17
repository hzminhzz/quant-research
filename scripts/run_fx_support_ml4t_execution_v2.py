"""Frozen v2 FX study. Native Engine owns fills, costs and portfolio accounting."""
from __future__ import annotations
import hashlib
import json
import math
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import polars as pl
from ml4t.backtest import BacktestConfig, DataFeed, Engine, ExecutionMode, OrderType, OrderStatus, Strategy
from ml4t.backtest.types import OrderSide
from ml4t.backtest.accounting.gatekeeper import Gatekeeper
from ml4t.backtest.config import ExecutionPrice, CommissionType, SlippageType, ShareType, FillOrdering, EntryOrderPriority
from ml4t.backtest.core.shared import SubmitOrderOptions
from ml4t.backtest.analytics import EquityCurve
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
SESSION='fx_support_ml4t_execution_20261008_v2'
OUT=ROOT/'run_log'/SESSION
OOF=ROOT/'run_log/fx_support_conditions_20261008_ml_v2/I4_purged_lightgbm_v2/scored_events.parquet'
UTC=timezone.utc
PRAGUE=ZoneInfo('Europe/Prague')

def dump(path, obj):
    path=Path(path)
    if path.exists():
        raise RuntimeError(f'Refuse to overwrite evidence: {path}')
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,indent=2,default=str,allow_nan=False)+'\n')

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def config(slip=.00005):
    return BacktestConfig(initial_cash=100000.,execution_mode=ExecutionMode.NEXT_BAR,
        execution_price=ExecutionPrice.OPEN,allow_leverage=True,allow_short_selling=False,
        initial_margin=1/3,long_maintenance_margin=.25,short_maintenance_margin=.25,
        share_type=ShareType.INTEGER,commission_type=CommissionType.PERCENTAGE,
        commission_rate=.000025,slippage_type=SlippageType.PERCENTAGE,slippage_rate=slip,
        partial_fills_allowed=False,next_bar_simple_cash_check=False,
        next_bar_queue_shadow_validation=False,skip_cash_validation=False,
        buying_power_reservation=False,fill_ordering=FillOrdering.PRIORITY,
        entry_order_priority=EntryOrderPriority.NOTIONAL_DESC)

class OpeningGate(Gatekeeper):
    """Extend native pre-fill validation; never fill or calculate portfolio PnL."""
    def __init__(self,broker,strategy,slip):
        super().__init__(broker.account,broker.commission_model,multiplier_resolver=broker.get_multiplier)
        self.broker=broker
        self.strategy=strategy
        self.slip=slip
    def validate_order_with_code(self,order,price):
        state=self.strategy.by_order.get(order.order_id)
        if state is None:
            return super().validate_order_with_code(order,price)
        entry=state['entry']
        if order is not entry:
            if entry.status is not OrderStatus.FILLED:
                return False,'Parent entry did not fill','parent_not_filled'
            return super().validate_order_with_code(order,price)
        b=self.broker
        b.mark_account_positions(use_open=True)
        # The native engine calls this before fill execution at the current open.
        # Only opening prices and previously held state enter the gate.
        open_price=b._current_opens[order.asset]
        support=state['origin_support']
        target=state['target_price']
        if open_price <= support+.00001 or open_price >= target-.00001:
            self.strategy.rejects['next_open_outside_levels']+=1
            return False,'Opening price outside frozen entry interval','next_open_outside_levels'
        positions=b.account.positions
        if order.asset in positions:
            return False,'One position per pair','pair_already_open'
        equity=b.account.cash+sum(p.quantity*b._current_opens.get(a,p.current_price) for a,p in positions.items())
        executed=open_price*(1+self.slip)
        concurrent=sum(max(0.,p.entry_price-self.strategy.active[a]['origin_support'])*p.quantity for a,p in positions.items())
        gross=sum(abs(p.quantity*b._current_opens.get(a,p.current_price)) for a,p in positions.items())
        risk_budget=min(.005*equity,max(0.,.01*equity-concurrent))
        # Freeze the signal-size upper bound at submission. Never increase it.
        quantity=math.floor(min(state['size_limit'],risk_budget/(executed-support),max(0.,3*equity-gross)/executed)/1000)*1000
        if quantity < 1000:
            self.strategy.rejects['risk_or_leverage_capacity']+=1
            return False,'Risk or leverage capacity below minimum lot','risk_or_leverage_capacity'
        order.quantity=float(quantity)
        state['stop'].quantity=float(quantity)
        state['target'].quantity=float(quantity)
        state['initial_risk_usd']=quantity*(executed-support)
        state['entry_equity']=equity
        state['entry_risk_fraction']=state['initial_risk_usd']/equity
        state['concurrent_risk_fraction']=(concurrent+state['initial_risk_usd'])/equity
        state['gross_leverage_at_entry']=(gross+quantity*executed)/equity
        assert state['entry_risk_fraction'] <= .005+1e-12
        assert state['concurrent_risk_fraction'] <= .01+1e-12
        assert state['gross_leverage_at_entry'] <= 3+1e-12
        return super().validate_order_with_code(order,executed)

class SupportStrategy(Strategy):
    def __init__(self,signals,final_by_symbol,slip=.00005,daily_flat=False):
        self.signals=signals
        self.final=final_by_symbol
        self.slip=slip
        self.daily_flat=daily_flat
        self.active={}
        self.states=[]
        self.by_order={}
        self.rejects=Counter()
        self.seen=0
    def on_start(self,broker):
        pass
    def on_end(self,broker):
        assert not broker.account.positions,'Terminal position remains open'
    def on_data(self,timestamp,data,context,broker):
        self.seen+=1
        for symbol,state in list(self.active.items()):
            entry=state['entry']
            if entry.status is OrderStatus.REJECTED:
                for child in (state['stop'],state['target']):
                    broker.cancel_order(child.order_id)
                del self.active[symbol]
                continue
            if self.daily_flat and entry.status is OrderStatus.FILLED and state.get('last_observed_date',timestamp.astimezone(PRAGUE).date()) != timestamp.astimezone(PRAGUE).date():
                raise RuntimeError(f'E3 daily-flat invariant failed: {symbol} entry={entry.filled_at}, prior date={state.get("last_observed_date")}, next observed={timestamp}; cutoff bar absent')
            if not broker.get_position(symbol) and entry.status is OrderStatus.FILLED:
                del self.active[symbol]
                continue
            if symbol not in data or entry.status is not OrderStatus.FILLED:
                continue
            if self.daily_flat and state.get('last_observed_date',timestamp.astimezone(PRAGUE).date()) != timestamp.astimezone(PRAGUE).date():
                raise RuntimeError('E3 daily-flat invariant failed: no observed cutoff bar before Prague reset')
            state['last_observed_date']=timestamp.astimezone(PRAGUE).date()
            # Count only complete 30m market bars. Gaps do not count as bars.
            state['components'].add(timestamp)
            bucket=timestamp.replace(minute=timestamp.minute//30*30,second=0,microsecond=0)
            if timestamp.minute%30 == 25 and all(bucket+timedelta(minutes=i) in state['components'] for i in range(0,30,5)):
                state['holding_30m_bars']+=1
                state['components'].clear()
            close_time=timestamp+timedelta(minutes=5)
            daily_cut=self.daily_flat and (close_time+timedelta(minutes=5)).astimezone(PRAGUE).date()!=timestamp.astimezone(PRAGUE).date()
            reason='terminal' if timestamp==self.final[symbol] else ('daily_flat' if daily_cut else ('time_expiry' if state['holding_30m_bars']>=240 else None))
            if reason:
                for child in (state['stop'],state['target']):
                    broker.cancel_order(child.order_id)
                state['close']=broker.close_position(symbol,order_type=OrderType.MOC)
                state['close_reason']=reason
        for event in self.signals.get(timestamp,[]):
            symbol=event['symbol']
            if symbol not in data:
                self.rejects['missing_final_component']+=1
                continue
            if symbol in self.active or broker.get_position(symbol):
                self.rejects['pair_already_open']+=1
                continue
            if timestamp >= self.final[symbol]:
                self.rejects['terminal_signal']+=1
                continue
            if self.daily_flat and (timestamp+timedelta(minutes=10)).astimezone(PRAGUE).date()!=timestamp.astimezone(PRAGUE).date():
                self.rejects['daily_reset_signal']+=1
                continue
            close=data[symbol]['close']
            distance=close*(1+self.slip)-event['origin_support']
            if distance<=0:
                self.rejects['invalid_signal_distance']+=1
                continue
            size=math.floor(min(.005*broker.get_account_value()/distance,3*broker.get_account_value()/close)/1000)*1000
            if size<1000:
                self.rejects['signal_size_below_lot']+=1
                continue
            state=dict(event,target_price=event['reference_high']+.00001,size_limit=size,holding_30m_bars=0,components=set(),initial_risk_usd=None)
            # Submit all children before entry fills. Stop precedes target.
            entry=broker.submit_order(symbol,size,_options=SubmitOrderOptions(priority_notional=1e30))
            stop=broker.submit_order(symbol,-size,order_type=OrderType.STOP,stop_price=event['origin_support'],_options=SubmitOrderOptions(priority_notional=1e20))
            target=broker.submit_order(symbol,-size,order_type=OrderType.LIMIT,limit_price=state['target_price'],_options=SubmitOrderOptions(priority_notional=1e10))
            assert entry and stop and target
            stop.parent_id=entry.order_id
            target.parent_id=entry.order_id
            state.update(entry=entry,stop=stop,target=target)
            self.states.append(state)
            self.active[symbol]=state
            for order in (entry,stop,target):
                self.by_order[order.order_id]=state

def engine(prices,strategy,slip):
    e=Engine(DataFeed(prices_df=prices),strategy,config(slip))
    e.broker.gatekeeper=OpeningGate(e.broker,strategy,slip)
    return e

def signal_map(frame):
    result={}
    # Strict allowlist: outcome and label columns never reach the strategy.
    for row in frame.select('symbol','event_timestamp','reference_high','origin_support').to_dicts():
        result.setdefault(row['event_timestamp']+timedelta(minutes=25),[]).append(row)
    return result

def p0():
    t=datetime(2024,1,2,tzinfo=UTC)
    times=[t+timedelta(minutes=5*i) for i in range(10)]
    results=[]
    for mode in ('entry_bar_tie','gap_below_support','gap_above_target','cash_and_risk'):
        opens=[1.1]*10; highs=[1.101]*10; lows=[1.099]*10
        if mode=='entry_bar_tie': highs[6]=1.12; lows[6]=1.08
        if mode=='gap_below_support': opens[6]=1.08; lows[6]=1.07
        if mode=='gap_above_target': opens[6]=1.12; highs[6]=1.13
        prices=pl.DataFrame(dict(timestamp=times,symbol=['EURUSD']*10,open=opens,high=highs,low=lows,close=[1.1]*10,volume=[1000000.]*10))
        event=dict(symbol='EURUSD',event_timestamp=t,reference_high=1.10999,origin_support=1.09)
        s=SupportStrategy({times[5]:[event]},{'EURUSD':times[-1]})
        e=engine(prices,s,.00005); r=e.run(); state=s.states[0]
        entry=state['entry']
        if mode.startswith('gap_'):
            assert entry.status is OrderStatus.REJECTED
            assert len(r.trades)==0
            assert not e.broker.account.positions
        else:
            assert entry.filled_at==times[6]
            assert entry.created_at==times[5]
            assert state['entry_risk_fraction']<=.005+1e-12
            if mode=='entry_bar_tie':
                assert state['stop'].filled_at==times[6]
                assert state['target'].status is OrderStatus.CANCELLED
                assert state['stop'].filled_price<=1.09
        results.append(dict(mode=mode,entry_status=entry.status.value,created_at=entry.created_at,filled_at=entry.filled_at,stop_status=state['stop'].status.value,target_status=state['target'].status.value,trades=len(r.trades),metrics=r.metrics))
    return results


def run_arm(trial,prices,oof,slip,flat):
    arm=OUT/(trial+'_attempt2' if trial=='E0_unfiltered_oof_cohort' and (OUT/trial/'failure.json').exists() else trial)
    arm.mkdir(exist_ok=False)
    signals=signal_map(oof)
    final={r['symbol']:r['timestamp'] for r in prices.group_by('symbol').agg(pl.col('timestamp').max()).to_dicts()}
    s=SupportStrategy(signals,final,slip,flat)
    e=engine(prices,s,slip)
    print(f'{trial}: native Engine start; {prices.height} price rows; {oof.height} signals',flush=True)
    r=e.run()
    # Save native artifacts before independent accounting verification.
    eq=r.to_equity_dataframe()
    native=r.to_trades_dataframe().with_columns(pl.col('entry_time').dt.replace_time_zone('UTC'),pl.col('exit_time').dt.replace_time_zone('UTC'))
    r.to_fills_dataframe().write_parquet(arm/'native_fills.parquet')
    r.to_rejected_orders_dataframe().write_parquet(arm/'native_rejected_orders.parquet')
    native.write_parquet(arm/'native_trades.parquet')
    eq.write_parquet(arm/'native_equity.parquet')
    r.to_portfolio_state_dataframe().write_parquet(arm/'native_portfolio_state.parquet')
    order_rows=[]; metadata=[]
    for state in s.states:
        for name in ('entry','stop','target','close'):
            order=state.get(name)
            if order:
                order_rows.append(dict(symbol=order.asset,role=name,order_id=order.order_id,parent_id=order.parent_id,quantity=order.quantity,status=order.status.value,created_at=order.created_at,filled_at=order.filled_at,filled_price=order.filled_price,filled_quantity=order.filled_quantity,rejection_code=order.rejection_code))
        entry=state['entry']
        if entry.status is OrderStatus.FILLED:
            assert entry.created_at==state['event_timestamp']+timedelta(minutes=25)
            assert entry.filled_at>=state['event_timestamp']+timedelta(minutes=30)
            reason='stop' if state['stop'].status is OrderStatus.FILLED else ('target' if state['target'].status is OrderStatus.FILLED else state.get('close_reason'))
            metadata.append(dict(symbol=entry.asset,entry_time=entry.filled_at,event_timestamp=state['event_timestamp'],origin_support=state['origin_support'],target_price=state['target_price'],initial_risk_usd=state['initial_risk_usd'],entry_equity=state['entry_equity'],entry_risk_fraction=state['entry_risk_fraction'],concurrent_risk_fraction=state['concurrent_risk_fraction'],gross_leverage_at_entry=state['gross_leverage_at_entry'],close_reason=reason,holding_30m_bars=state['holding_30m_bars']))
    dump(arm/'orders.json',order_rows)
    ledger=native.join(pl.DataFrame(metadata),on=['symbol','entry_time'],how='left').with_columns((pl.col('pnl')/pl.col('initial_risk_usd')).alias('net_R'))
    ledger.write_parquet(arm/'trade_ledger.parquet')
    assert native.height==len(metadata)
    assert all(t.status=='closed' for t in r.trades)
    assert not ledger['initial_risk_usd'].has_nulls()
    assert abs(ledger['pnl'].sum()-(r.metrics['final_value']-100000))<1e-6,'Native ledger/equity reconciliation failed'
    # Independent arithmetic oracle checks executed-price PnL and native fees.
    assert all(abs(t.pnl-((t.exit_price-t.entry_price)*t.quantity-t.fees))<1e-7 for t in r.trades)
    assert all(abs(t.fees-(t.entry_price+t.exit_price)*t.quantity*.000025)<1e-7 for t in r.trades)
    daily=eq.select('timestamp','equity').with_columns(pl.col('timestamp').dt.truncate('1d')).group_by('timestamp').agg(pl.col('equity').last()).sort('timestamp')
    calendar=pl.DataFrame({'timestamp':pl.datetime_range(datetime(2017,1,1,tzinfo=UTC),datetime(2024,12,31,tzinfo=UTC),interval='1d',eager=True)})
    daily=calendar.join(daily,on='timestamp',how='left').with_columns(pl.col('equity').forward_fill().fill_null(100000.))
    daily.write_parquet(arm/'daily_equity.parquet')
    dc=EquityCurve(timestamps=daily['timestamp'].to_list(),values=daily['equity'].to_list(),periods_per_year_override=365.25)
    from ml4t.backtest.sessions import compute_session_pnl,SessionConfig
    # Native equity is stamped by bar open; equity reflects its completed close.
    prague=compute_session_pnl([(ts+timedelta(minutes=5),v) for ts,v in r.equity_curve],SessionConfig(calendar='FX_PROXY',timezone='Europe/Prague'))
    prague.write_parquet(arm/'prague_sessions.parquet')
    by_pair=ledger.group_by('symbol').agg(pl.len().alias('trades'),pl.col('pnl').sum().alias('net_usd'),pl.col('net_R').mean().alias('mean_net_R')).sort('symbol').to_dicts()
    by_year=ledger.with_columns(pl.col('exit_time').dt.year().alias('year')).group_by('year').agg(pl.len().alias('trades'),pl.col('pnl').sum().alias('net_usd'),pl.col('net_R').mean().alias('mean_net_R')).sort('year').to_dicts()
    wins=ledger.filter(pl.col('pnl')>0); losses=ledger.filter(pl.col('pnl')<=0)
    metrics=dict(session_id=SESSION,trial_id=trial,status='completed',approval_status='NOT_APPROVED',classification='EXPLORATORY',signals=oof.height,orders=len(order_rows),signal_rejections=dict(s.rejects),actual_entries=len(metadata),completed_trades=native.height,partial_fills=0,unclosed_positions=0,net_usd=float(ledger['pnl'].sum()),mean_net_R=float(ledger['net_R'].mean()),win_rate=wins.height/native.height,average_win_R=wins['net_R'].mean(),average_loss_R=losses['net_R'].mean(),daily_equity_sharpe=dc.sharpe,continuous_max_drawdown=float(eq['drawdown'].min()),daily_max_drawdown=dc.max_dd,worst_prague_daily_return=float(prague['return_pct'].min()),worst_prague_day=prague.sort('return_pct').head(1).to_dicts(),prague_5_percent_day_breaches=prague.filter(pl.col('return_pct')<=-.05).height,total_10_percent_loss_breached=bool(eq['equity'].min()<90000),close_reasons=dict(Counter(x['close_reason'] for x in metadata)),max_entry_risk_fraction=max(x['entry_risk_fraction'] for x in metadata),max_concurrent_stop_risk_fraction=max(x['concurrent_risk_fraction'] for x in metadata),max_entry_gross_leverage=max(x['gross_leverage_at_entry'] for x in metadata),per_pair=by_pair,per_exit_year=by_year,reconciliation='PASS: closed native trade PnL equals final equity less initial cash; fees and executed-price PnL checked',native_metrics=r.metrics,limitations=['Unverified overnight swaps in E0/E1/E2.','Price proxy lacks exact historical FTMO spread, depth, lot commissions and rollover.','Prague session statistics use observed 5m close equity; exact midnight equity across data gaps is unavailable.'])
    dump(arm/'result.json',metrics)
    print(f'{trial}: completed; {native.height} trades; net USD {metrics["net_usd"]:.2f}',flush=True)
    return metrics

def execute():
    import subprocess,importlib.metadata,os,traceback
    from src.research_session import record_trial,report_session
    OUT.mkdir(exist_ok=True)
    dump(OUT/'run_metadata.json',dict(session_id=SESSION,pid=os.getpid(),started_at=datetime.now(UTC),engine_version=importlib.metadata.version('ml4t-backtest'),source_sha256=digest(__file__),config_sha256=digest(ROOT/'config/research_sessions'/f'{SESSION}.yaml'),process_mode='managed foreground process; tmux socket denied with Operation not permitted',attempts=['Initial v2 fixture used nonexistent get_equity; corrected to inspected get_account_value before economic runs.'],economic_mechanism='Support reclaim can indicate resumed demand; frozen OOF gate may select better net payoff paths.',baseline='730 OOF events; candidate 112 selected events; EURUSD GBPUSD AUDUSD FTMO USD-quote CFDs via LSE proxy; 2017-2024 only',falsifier='Positive E1 net USD and mean net R; >=80 trades; >=2 profitable pairs; daily Sharpe >0; DD <6%; expectancy improves E0 without greater leverage; E2 remains profitable.'))
    record_trial(SESSION,'H0_initial_timing_gate_failure','completed',Path('run_log/research_sessions/fx_support_ml4t_execution_20261008/diagnostics/P0_engine_execution_gate.json'),ROOT)
    record_trial(SESSION,'H0_oof_predictive_parent','completed',Path('run_log/fx_support_conditions_20261008_ml_v2/I4_purged_lightgbm_v2/result.json'),ROOT)
    proc=subprocess.run([sys.executable,'-m','pytest','tests/test_fx_support_ml4t_boundary_v2.py','tests/test_fx_support_ml4t_execution_20261008.py','tests/test_fx_support_ml4t_execution_v2.py','-q'],cwd=ROOT,capture_output=True,text=True)
    (OUT/'P0_pytest.log').write_text(proc.stdout+proc.stderr)
    assert proc.returncode==0,proc.stdout+proc.stderr
    fixtures=p0()
    integrity=json.loads((ROOT/'run_log/fx_support_ml4t_execution_20261008/feature_integrity_v1.json').read_text())
    assert integrity['status']=='PASS'
    checks=[(ROOT/'data/features/fx_support_conditions_20261008.parquet',integrity['frozen_panel_sha256']),(OOF,integrity['oof_probability_sha256'])]
    checks += [(ROOT/item['path'],item['sha256']) for item in integrity['development_inputs']]
    assert all(digest(path)==expected for path,expected in checks)
    dump(OUT/'feature_integrity_link.json',dict(status='PASS',prior_artifact='run_log/fx_support_ml4t_execution_20261008/feature_integrity_v1.json',prior_sha256=digest(ROOT/'run_log/fx_support_ml4t_execution_20261008/feature_integrity_v1.json'),identity_checks=[str(p.relative_to(ROOT)) for p,_ in checks],feature_rows=1395,oof_rows=730,selected_rows=112,holdout_opened=False,regeneration='Reused previously independent installed ml4t.engineer.compute_features parity verification. No retraining.'))
    skills=['run-backtest','compute-features','lookahead-bias','purging-embargo','cost-model','polars-patterns','transaction-costs']
    dump(OUT/'P0_engine_execution_gate.json',dict(status='completed',gate_disposition='PASS',corrected_timing='t+25 completed final component callback creates entry; native NEXT_BAR fills at t+30',fixtures=fixtures,pytest=proc.stdout,feature_gate='feature_integrity_link.json',extension='Task-owned OpeningGate extends native Gatekeeper pre-fill validation only; native Engine retains fills and accounting',skills=[dict(name='ml4t-'+name,path='.agents/skills/ml4t-'+name+'/SKILL.md',sha256=digest(ROOT/'.agents/skills'/('ml4t-'+name)/'SKILL.md')) for name in skills],holdout_opened=False))
    record_trial(SESSION,'P0_engine_execution_gate','completed',Path(f'run_log/{SESSION}/P0_engine_execution_gate.json'),ROOT)
    oof=pl.read_parquet(OOF)
    assert oof.height==730 and oof.filter(pl.col('selected')).height==112
    frames=[]
    for symbol in ('EURUSD','GBPUSD','AUDUSD'):
        paths=[ROOT/f'data/processed/ftmo_fx_reversion_202610/{symbol}_dev_{era}_5m.parquet' for era in ('2010_2017','2018_2024')]
        assert all('holdout' not in p.name for p in paths)
        frames.append(pl.concat([pl.scan_parquet(p).filter(pl.col('timestamp')>=datetime(2017,1,1,tzinfo=UTC)).select('timestamp','open','high','low','close','volume').with_columns(pl.lit(symbol).alias('symbol')).collect() for p in paths]))
    prices=pl.concat(frames).sort('timestamp','symbol')
    assert prices['timestamp'].max().year==2024
    assert prices.select('timestamp','symbol').n_unique()==prices.height
    results=[]
    for trial,selected,slip,flat in [('E0_unfiltered_oof_cohort',False,.00005,False),('E1_lightgbm_oof_capped_risk',True,.00005,False),('E2_lightgbm_cost_stress',True,.00010,False),('E3_lightgbm_flat_before_daily_reset',True,.00005,True)]:
        try:
            result=run_arm(trial,prices,oof.filter(pl.col('selected')) if selected else oof,slip,flat)
            record_trial(SESSION,trial,'completed',Path(f'run_log/{SESSION}/{trial}/result.json'),ROOT)
            results.append(result)
        except Exception as exc:
            artifact=OUT/trial/'failure.json'
            dump(artifact,dict(status='failed',gate_disposition='BLOCKED',error=repr(exc),traceback=traceback.format_exc(),holdout_opened=False))
            record_trial(SESSION,trial,'failed',artifact.relative_to(ROOT),ROOT)
            print(traceback.format_exc(),flush=True)
            break
    dump(OUT/'session_report.json',report_session(SESSION,ROOT))
    dump(OUT/'summary.json',dict(session_id=SESSION,arms=[{k:v for k,v in r.items() if k!='native_metrics'} for r in results],holdout_opened=False,approval_status='NOT_APPROVED'))

if __name__=='__main__' and '--execute' in sys.argv:
    execute()

def resume():
    import subprocess,traceback
    from src.research_session import record_trial,report_session
    log=subprocess.run([sys.executable,'-m','pytest','tests/test_fx_support_ml4t_boundary_v2.py','tests/test_fx_support_ml4t_execution_20261008.py','tests/test_fx_support_ml4t_execution_v2.py','-q'],capture_output=True,text=True,cwd=ROOT)
    (OUT/'P0_causal_ordering_pytest.log').write_text(log.stdout+log.stderr)
    assert log.returncode==0,log.stdout+log.stderr
    dump(OUT/'P0_causal_ordering_gate.json',dict(status='PASS',pytest=log.stdout,source_sha256=digest(__file__),fixtures=p0(),reason='Native PRIORITY submits all opening entries before intrabar exits. STOP priority exceeds LIMIT priority. Two-pair fixture proves changing future intrabar low cannot change another pair opening size, equity, risk or leverage.',supersedes_execution_acceptance='Initial P0 single-position gate did not test portfolio intrabar exit ordering. Initial E0 retained as failed attempt. No economic parameter or filter changed.',deviations=['tmux Unix sockets denied; managed foreground process retained logs instead.','Initial E0 Engine finished, but timezone report failed. Immutable E0 terminal failed record is preserved; attempt2 result is linked in supplemental attempt ledger.','Synthetic report smoke attempt2 exposed unsupported explicit midnight calendar override; corrected to native timezone fallback midnight with no override.'],holdout_opened=False))
    oof=pl.read_parquet(OOF)
    frames=[]
    for symbol in ('EURUSD','GBPUSD','AUDUSD'):
        frames.extend([pl.scan_parquet(ROOT/f'data/processed/ftmo_fx_reversion_202610/{symbol}_dev_{era}_5m.parquet').filter(pl.col('timestamp')>=datetime(2017,1,1,tzinfo=UTC)).select('timestamp','open','high','low','close','volume').with_columns(pl.lit(symbol).alias('symbol')).collect() for era in ('2010_2017','2018_2024')])
    prices=pl.concat(frames).sort('timestamp','symbol')
    results=[]; attempts=[]
    for trial,selected,slip,flat in [('E0_unfiltered_oof_cohort',False,.00005,False),('E1_lightgbm_oof_capped_risk',True,.00005,False),('E2_lightgbm_cost_stress',True,.00010,False),('E3_lightgbm_flat_before_daily_reset',True,.00005,True)]:
        try:
            r=run_arm(trial,prices,oof.filter(pl.col('selected')) if selected else oof,slip,flat)
            relative=Path(f'run_log/{SESSION}/{trial}{"_attempt2" if trial.startswith("E0_") else ""}/result.json')
            if not trial.startswith('E0_'):
                record_trial(SESSION,trial,'completed',relative,ROOT)
            attempts.append(dict(trial_id=trial,status='completed',artifact=str(relative),sha256=digest(ROOT/relative),registry_note='Original failed terminal record preserved; this is recovered baseline attempt2.' if trial.startswith('E0_') else 'Recorded with research_session.record_trial'))
            results.append(r)
        except Exception as exc:
            artifact=OUT/trial/'failure.json'
            dump(artifact,dict(status='failed',gate_disposition='BLOCKED',error=repr(exc),traceback=traceback.format_exc(),holdout_opened=False,source_sha256=digest(__file__)))
            record_trial(SESSION,trial,'failed',artifact.relative_to(ROOT),ROOT)
            attempts.append(dict(trial_id=trial,status='failed',artifact=str(artifact.relative_to(ROOT)),sha256=digest(artifact),error=repr(exc)))
            print(traceback.format_exc(),flush=True)
    dump(OUT/'attempt_ledger.json',dict(attempts=attempts,prior_failed_E0='E0_unfiltered_oof_cohort/failure.json',p0_supplement='P0_causal_ordering_gate.json',rule_changes='No outcome-driven economic tuning. Corrected native scheduling and report compatibility only.'))
    dump(OUT/'final_session_report.json',report_session(SESSION,ROOT))
    dump(OUT/'final_summary.json',dict(session_id=SESSION,arms=[{k:v for k,v in r.items() if k!='native_metrics'} for r in results],attempts=attempts,holdout_opened=False,approval_status='NOT_APPROVED'))

if __name__=='__main__' and '--resume' in sys.argv:
    resume()
