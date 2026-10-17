"""Program 3: frozen OHLCV execution bounds with native ML4T orders.

The synthetic volume gate is execution eligibility, not observed FX volume.
No price-based trading selection or protected holdout access is permitted.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import importlib.metadata
import numpy as np
import polars as pl
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests
import yaml
from ml4t.engineer import compute_features, labeling
from ml4t.diagnostic import analyze_signal, Evaluator
from ml4t.diagnostic.metrics.ic import information_coefficient
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LinearRegression
from ml4t.diagnostic.splitters.base import BaseSplitter
from ml4t.backtest import BacktestConfig, DataFeed, Engine, ExecutionMode, OrderStatus, OrderType, Strategy
from ml4t.backtest.config import CommissionType, ExecutionPrice, ShareType, SlippageType
from ml4t.backtest.execution.limits import PositiveVolumeLimit
from ml4t.backtest.analytics import EquityCurve, TradeAnalyzer

ROOT=Path(__file__).resolve().parents[1]
SID='tokyo_fix_program3_ohlcv_execution_20261011_v1'
OUT=ROOT/'run_log'/SID
SPEC=ROOT/'config/research_sessions'/f'{SID}.yaml'
JST=ZoneInfo('Asia/Tokyo')
BOUND=datetime(2026,9,1,tzinfo=JST)
CAL=ROOT/'run_log/tokyo_fix_alpha_map_program1_20261010/execution_v1/calendar_event_registry.parquet'
RUNS=OUT/'runs'
COMPARISON=OUT/'T2_comparison'
CORRECTED=False
SOURCES=[ROOT/f'data/processed/tokyo_alpha_map_program1_v1/USDJPY_03_12_JST_{y}.parquet' for y in range(2020,2027)]
SKILLS=['validate-data','polars-patterns','compute-features','evaluate-factor','run-backtest','cost-model','transaction-costs','calendar-ops','causal-identification','lookahead-bias','backtest-overfitting','sensitivity-analysis','fetch-data','point-in-time']

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def save(p,obj):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():
        if json.loads(p.read_text())!=json.loads(json.dumps(obj,default=str,allow_nan=False)):raise RuntimeError(f'Immutable JSON differs: {p}')
        return
    with p.open('x') as f:json.dump(obj,f,indent=2,default=str,allow_nan=False);f.write('\n')

def frame(p,d):
    if Path(p).exists():
        old=pl.read_parquet(p)
        if not old.sort(old.columns).equals(d.sort(d.columns)):raise RuntimeError(f'Immutable frame differs: {p}')
        return
    Path(p).parent.mkdir(parents=True,exist_ok=True);d.write_parquet(p)

def finite(v):return float(v) if math.isfinite(float(v)) else None

def minute(t):
    t=t.astimezone(JST);return t.hour*60+t.minute

def strict_cross(high,low,limit,buffer_pips,side=-1):
    return round(high,8)>round(limit+buffer_pips*.01,8) if side<0 else round(low,8)<round(limit-buffer_pips*.01,8)

def cli(*args):
    r=subprocess.run([sys.executable,str(ROOT/'scripts/research_session.py'),*args,'--root',str(ROOT)],cwd=ROOT,capture_output=True,text=True)
    if r.returncode:raise RuntimeError(r.stdout+r.stderr)
    return json.loads(r.stdout)

def preservation():
    paths=set()
    status=subprocess.check_output(['git','status','--porcelain=v1','--untracked-files=all'],cwd=ROOT,text=True)
    for line in status.splitlines():
        p=ROOT/line[3:]
        if p.is_file() and SID not in str(p) and p.stat().st_size<100*1024*1024:paths.add(p)
    for root in ['run_log/tokyo_alpha_map_program1_closure_v3','run_log/tokyo_alpha_map_program1_native_exploratory_v2','run_log/tokyo_fix_alpha_map_program1_20261010','run_log/tokyo_fix_program2_cross_currency_20261011_v1']:
        paths.update(p for p in (ROOT/root).rglob('*') if p.is_file())
    paths.update(SOURCES+[CAL])
    return {'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'status':status,'hashes':{str(p.relative_to(ROOT)):sha(p) for p in sorted(paths)},'scope':'All original dirty regular files below100MB plus all prior Program1/2 frozen run artifacts and canonical sources. Larger unrelated data inventoried by git status only.'}

def prepare():
    OUT.mkdir(parents=True,exist_ok=True)
    save(OUT/'preservation_before.json',preservation())
    manifest=[]
    for p in SOURCES:
        metadata=pl.scan_parquet(p).select(pl.len().alias('rows'),pl.col('timestamp').min().alias('first'),pl.col('timestamp').max().alias('last')).collect().row(0,named=True)
        assert metadata['last']<BOUND
        manifest.append({'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size,**metadata})
    save(OUT/'source_manifest.json',{'sources':manifest,'calendar':{'path':str(CAL.relative_to(ROOT)),'sha256':sha(CAL)},'holdout_read':False,'timezone':'UTC bar-open; convert Asia/Tokyo. Close available at timestamp+1 minute (interval inference).','volume':'Vendor composite, not verified FX executed volume','inventory':{'USDJPY_tick_quote_depth':False,'USDJPY_legacy_bid_candle_files':8507,'USDJPY_legacy_ask_files':0,'other_tick_assets':'XAUUSD and BTC/ETH only','real_passive_fill_probability':'UNKNOWN'}})
    save(OUT/'methodology.json',{'skills':[{'name':'ml4t-'+n,'path':str((ROOT/f'.agents/skills/ml4t-{n}/SKILL.md').relative_to(ROOT)),'sha256':sha(ROOT/f'.agents/skills/ml4t-{n}/SKILL.md'),'invariants':'No holdout, no forward fill; native fills only; exact minute completeness; frozen small trial ladder; independent raw bar oracle; timing and currency reconciliation'} for n in SKILLS],'official_catalog':'https://github.com/ml4t/skills','versions':{p:importlib.metadata.version(p) for p in ['ml4t-backtest','ml4t-engineer','ml4t-diagnostic','polars']},'conflicts':'Skill recommends git commit and holdout scoring; mission prohibits commits and holdout access. Adopt create-once CLI freeze and holdout seal. No DSR/PBO confidence claim because prior search history incomplete; Holm only for new declared families.','metrics':'Verified EquityCurve and TradeAnalyzer. Statsmodels HAC5/month cluster; no custom performance calculators.'})
    variants=[{'id':f'limit_o{str(o).replace(".","p")}_t{ttl}_b{str(b).replace(".","p")}','offset':o,'ttl':ttl,'buffer':b,'group':'gotobi'} for o in [0,.5,1] for ttl in [1,3] for b in [0,.5]]
    trials=[{'id':'T0_quality','kind':'diagnostic','description':'Window gates and OHLC quality; all bank dates'}, {'id':'T1_proxy','kind':'diagnostic','description':'Five past price proxies x two horizons x Gotobi and ordinary; 20 controlled HAC/interaction tests plus categorical effects, descriptive native signal analysis'}, {'id':'market_gotobi','kind':'preregistered','description':'Native short Gotobi09:56-10:10 unchanged timing USD10000'}, {'id':'market_ordinary','kind':'preregistered','description':'Native same-time ordinary short control'}]
    trials += [{'id':v['id'],'kind':'preregistered','description':f'Native strict-cross limit bound offset{v["offset"]}pip TTL{v["ttl"]}min buffer{v["buffer"]}pip; four fixed cost overlays'} for v in variants]
    trials += [{'id':x,'kind':'diagnostic','description':desc} for x,desc in [('T2_comparison','Matched calendar ordinary/control and09:26-09:40 placebo, paired limit-minus-market HAC, Holm14, yearly/stress'),('T3_oracle','Independent every-order original-source oracle and economic conversion'),('T4_final_audit','Preservation, ledger, tests, source hashes and sealed holdout')]]
    spec={'session_id':SID,'market':'fx','thesis':'Evaluate whether unconditional Gotobi post-fix USDJPY short remains positive under conservative OHLC limit-fill bounds relative to next-open market benchmark. No outcome-based strategy selection.','mechanism':'HYPOTHESIS: settlement-related pre-fix USD demand may unwind after fixing. Price proxies do not measure dealer inventory.','falsifier':'Reject robustness if any conservative bound is nonpositive at1pip full sample, or2024-25 or2026 stress is negative. Report all costs/bounds; economic positivity cannot approve deployment or establish real fill probability.','instruments':[{'symbol':'USDJPY','kind':'cfd','venue':'UNSPECIFIED_RETAIL_FX_BROKER','identity':'LSE composite JPY per USD price proxy. Broker contract/tick/lot/shorting terms unverified; no real orders. Simulated fractional USD10000 base units, tick assumption .001 JPY.','timezone':'Asia/Tokyo','session':'Tokyo bank fix intraday'}],'data':[{'id':f'year{y}','path':str(p.relative_to(ROOT)),'role':'prices','symbol':'USDJPY'} for y,p in zip(range(2020,2027),SOURCES)],'evaluation':{'development_start':'2020-01-01T00:00:00Z','development_end':'2026-08-31T15:00:00Z','holdout_start':'2026-08-31T15:00:00Z','holdout_end':'2026-10-31T15:00:00Z','holdout':'SEALED, never read','development':'2020-23;2024-25 retrospective validation;2026Jan-Aug observed regime stress, all exploratory','initial_usd':10000,'notional_usd':10000,'costs_pips':[.8,1,1.4,2],'variants':variants,'execution_window':[594,630],'proxy_windows':[[510,594],[570,594]],'proxy_features':['extension0830','extension0930','rv','acceleration','range'],'proxy_horizons':[610,630],'placebo_window':[566,580],'reference':'09:54 close available09:55. Submit09:55; first fill09:56; TTL1/3 through09:56/58. Close decision10:09 native MARKET fill10:10. Never use09:55 close.','gating':'Unchanged OHLC; synthetic volume1 only for strict high>limit+buffer within TTL and market exit. PositiveVolumeLimit is execution DATA GATE, not a signal input. Cancel after last eligible bar matching. Filled native limit price=limit, no optimistic open improvement.','multiplicity':'Holm20 proxy controlled contrasts; Holm14 policy/control contrasts. Costs, year and quantiles descriptive. No winner selection. Earlier historical trial count incomplete; DSR/PBO not reproducible.','categorical':'Development2020-23 terciles per feature, applied unchanged; no trading filter','dag':'weekday/year -> Gotobi and returns; settlement -> price and returns; news -> price and returns. Adjust weekday/year only. No causal inventory estimand.','stop_rule':'Execute fixed matrix once; retain runtime failures; no new variants or minute optimization.'},'baseline':'Unconditional Gotobi MARKET09:56-10:10 and ordinary control; old nativev2 preserved with distinct cohort; cash0','costs':{'commission_bps':0,'slippage_bps':0,'roundtrip_pips':[.8,1,1.4,2],'method':'Explicit all-in JPY cash-flow overlay translated at actual raw exit; native raw fills zero slippage to preserve limit price. Applies same assumed costs to market and passive: no rebate/zero-spread claim.','quote_scenarios':'Estimated market .4+.4,.5+.5,.7+.7,1+1pip; passive .2+.6,.3+.7,.5+.9,.8+1.2pip entry/exit budget; aggregate equal. Not broker-calibrated.','financing':'No overnight; no rollover. Actual broker terms UNKNOWN.','impact':'USD10000 small assumed notional; no FX market-volume calibration, capacity UNKNOWN.'},'trials':trials,'evidence':[str((OUT/n).relative_to(ROOT)) for n in ['source_manifest.json','methodology.json','preservation_before.json']]}
    with SPEC.open('x') as f:yaml.safe_dump(spec,f,sort_keys=False)
    save(OUT/'freeze_init.json',cli('init','--spec',str(SPEC.relative_to(ROOT))))
    save(OUT/'freeze_check.json',cli('check','--session',SID))
    print('PREPARED_AND_FROZEN',flush=True)

def load_data(spec):
    raw=pl.scan_parquet([str(p) for p in SOURCES]).filter(pl.col('timestamp')<BOUND.astimezone(ZoneInfo('UTC'))).with_columns(pl.col('timestamp').dt.convert_time_zone('Asia/Tokyo').alias('jst')).with_columns(pl.col('jst').dt.date().alias('session'),(pl.col('jst').dt.hour().cast(pl.Int32)*60+pl.col('jst').dt.minute()).alias('minute')).sort('timestamp').collect()
    assert raw['timestamp'].max()<BOUND and raw['timestamp'].is_duplicated().sum()==0
    good=pl.all_horizontal([pl.col(c).is_finite()&(pl.col(c)>0) for c in ['open','high','low','close']])&(pl.col('high')>=pl.max_horizontal('open','close'))&(pl.col('low')<=pl.min_horizontal('open','close'))&(pl.col('high')>=pl.col('low'))
    raw=raw.with_columns(good.alias('valid')).with_columns(((pl.col('close')==pl.col('close').shift(1)).cast(pl.Int32).rolling_sum(5).over('session')>=5).fill_null(False).alias('stale'))
    reg=pl.read_parquet(CAL).filter(pl.col('session')<date(2026,9,1)).select('session','gotobi','ordinary','weekday','year').sort('session')
    assert reg['session'].max()<date(2026,9,1)
    gates=reg
    windows={'execution':spec['evaluation']['execution_window'],'proxy0830':[510,594],'proxy0930':[570,594],'placebo':[565,580]}
    for name,(a,b) in windows.items():
        count=raw.filter(pl.col('minute').is_between(a,b)).group_by('session').agg(pl.len().alias(name+'_observed'),pl.col('valid').sum().alias(name+'_valid'),pl.col('stale').sum().alias(name+'_stale'))
        gates=gates.join(count,on='session',how='left').with_columns(pl.col(name+'_observed').fill_null(0),pl.col(name+'_valid').fill_null(0)).with_columns((pl.col(name+'_valid')==b-a+1).alias(name+'_complete'))
    frame(OUT/'window_gates.parquet',gates)
    if not (OUT/'T0_quality/result.json').exists():save(OUT/'T0_quality/result.json',{'bank_days':reg.height,'windows':windows,'coverage':{n:gates.group_by('year','weekday','gotobi',n+'_complete').agg(pl.len().alias('n')).sort('year','weekday','gotobi',n+'_complete').to_dicts() for n in windows},'quality':raw.group_by(pl.col('session').dt.year().alias('year')).agg(pl.len().alias('rows'),(~pl.col('valid')).sum().alias('invalid_ohlc'),pl.col('stale').sum().alias('stale_5min'),(pl.col('volume')==0).sum().alias('zero_volume'),(pl.col('close').pct_change().abs()>.5).sum().alias('extreme_return')).to_dicts(),'stale_policy':'Report, do not equate unchanged composite closes with impossible trades; strict crossing/geometry gate; real quote status UNKNOWN','forward_fill':False,'holdout_read':False})
    dates=gates.filter(pl.col('execution_complete'))['session']
    bars=raw.filter(pl.col('session').is_in(dates.implode())&pl.col('minute').is_between(594,630))
    frame(OUT/'execution_bars.parquet',bars)
    panel=reg.join(bars.group_by('session').agg(*[pl.col('close' if m==594 else 'open').filter(pl.col('minute')==m).first().alias(n) for m,n in [(594,'ref'),(596,'market_entry'),(610,'exit'),(630,'exit1030')]]),on='session',how='inner').sort('session')
    frame(OUT/'event_panel.parquet',panel)
    return raw,bars,panel,reg,gates

class LimitStrategy(Strategy):
    def __init__(self, refs, offset=0,ttl=1,is_market=False,notional=10000):
        self.refs=refs;self.offset=offset;self.ttl=ttl;self.is_market=is_market;self.notional=notional;self.events=[];self.pending=None;self.failures=[]
    def on_start(self,broker):pass
    def on_data(self,timestamp,data,context,broker):
        day=timestamp.astimezone(JST).date();m=minute(timestamp)
        if day not in self.refs:return
        if m==595:
            if broker.get_position('USDJPY') or self.pending:raise RuntimeError('Unexpected position/order before entry')
            self.pending=broker.submit_order('USDJPY',-self.notional,order_type=OrderType.MARKET if self.is_market else OrderType.LIMIT,limit_price=None if self.is_market else round(self.refs[day]+self.offset*.01,8))
            if self.pending is None:raise RuntimeError('Rejected submission')
            self.events.append(('entry',day,timestamp,self.pending))
        if self.pending and m==595+self.ttl:
            if self.pending.status is not OrderStatus.FILLED:
                assert broker.cancel_order(self.pending.order_id)
            self.pending=None
        if m==609:
            if self.pending:
                broker.cancel_order(self.pending.order_id);self.pending=None
            if broker.get_position('USDJPY'):
                o=broker.close_position('USDJPY',order_type=OrderType.MARKET)
                self.events.append(('exit',day,timestamp,o))
        if m>=610 and broker.get_position('USDJPY'):raise RuntimeError('Open after scheduled exit')
    def on_end(self,broker):
        if broker.get_position('USDJPY') or self.pending:raise RuntimeError('Overnight/end exposure')

def metric_summary(profits,days,reg):
    trades=[SimpleNamespace(pnl=float(p),pnl_percent=float(p)/10000,status='closed') for p in profits]
    ta=TradeAnalyzer(trades)
    d=reg.select('session').join(pl.DataFrame({'session':days,'pnl':profits},schema={'session':pl.Date,'pnl':pl.Float64}),on='session',how='left').with_columns(pl.col('pnl').fill_null(0)).with_columns((10000+pl.col('pnl').cum_sum()).alias('equity'))
    eq=EquityCurve([datetime.combine(reg['session'][0]-timedelta(days=1),datetime.min.time(),JST)]+[datetime.combine(s,datetime.min.time(),JST) for s in d['session']], [10000]+d['equity'].to_list(),periods_per_year_override=252)
    return {'net_usd':finite(ta.net_profit),'return_pct':finite(eq.total_return*100),'win_rate':finite(ta.win_rate),'profit_factor':finite(ta.profit_factor),'daily_sharpe':finite(eq.sharpe),'max_closed_drawdown_pct':finite(eq.max_dd*100),'n_fills':len(profits),'negative_days':sum(p<0 for p in profits)},d

def native_run(v,bars,panel,reg,spec):
    path=RUNS/v['id'];path.mkdir(parents=True,exist_ok=True)
    if (path/'result.json').exists():return json.loads((path/'result.json').read_text())
    seg=panel.filter(pl.col(v['group']));refs=dict(zip(seg['session'],seg['ref']))
    prices=bars.filter(pl.col('session').is_in(seg['session'].implode())).join(seg.select('session','ref'),on='session')
    market=v['id'].startswith('market')
    if market:elig=pl.lit(1.)
    else:elig=pl.when((pl.col('minute').is_between(596,595+v['ttl']))&(pl.col('high').round(8)>(pl.col('ref').round(8)+v['offset']*.01).round(8).add(v['buffer']*.01).round(8)) | (pl.col('minute')==610)).then(1.).otherwise(0.)
    prices=prices.with_columns(elig.alias('volume')).select('timestamp','symbol','open','high','low','close','volume').sort('timestamp')
    strategy=LimitStrategy(refs,v.get('offset',0),v.get('ttl',1),market,spec['evaluation']['notional_usd'])
    initial=10000*float(prices['open'][0])
    config=BacktestConfig(initial_cash=initial,allow_short_selling=True,allow_leverage=True,initial_margin=.5,execution_mode=ExecutionMode.NEXT_BAR,execution_price=ExecutionPrice.OPEN,share_type=ShareType.FRACTIONAL,commission_type=CommissionType.NONE,slippage_type=SlippageType.NONE,partial_fills_allowed=False)
    result=Engine(DataFeed(prices_df=prices),strategy,config,execution_limits=PositiveVolumeLimit()).run()
    rows=[]
    for role,day,submitted,order in strategy.events:
        rows.append({'session':day,'role':role,'submitted_at':submitted,'fill_at':order.filled_at,'status':order.status.value,'price':order.filled_price,'limit':order.limit_price,'quantity':order.quantity,'order_id':order.order_id})
    orders=pl.DataFrame(rows);frame(path/'orders.parquet',orders)
    a=orders.filter((pl.col('role')=='entry')&(pl.col('status')=='filled')).select('session',pl.col('price').alias('entry'),pl.col('fill_at').alias('entry_time'))
    z=orders.filter((pl.col('role')=='exit')&(pl.col('status')=='filled')).select('session',pl.col('price').alias('exit'),pl.col('fill_at').alias('exit_time'))
    assert a.height==z.height and a.height>0
    trades=a.join(z,on='session',validate='1:1').join(seg.drop('exit'),on='session').sort('session').with_columns(((pl.col('entry')-pl.col('exit'))*10000).alias('pnl_jpy')).with_columns((pl.col('pnl_jpy')/pl.col('exit')).alias('gross_usd'))
    for c in spec['evaluation']['costs_pips']:trades=trades.with_columns(((pl.col('pnl_jpy')-10000*c*.01)/pl.col('exit')).alias(f'net_usd_c{c}'))
    assert np.isclose(float(result.metrics['final_value'])-initial,trades['pnl_jpy'].sum(),atol=1e-5)
    for r in trades.iter_rows(named=True):
        assert minute(r['exit_time'])==610 and r['entry_time']>orders.filter((pl.col('session')==r['session'])&(pl.col('role')=='entry'))['submitted_at'][0]
        assert 596<=minute(r['entry_time'])<=595+v.get('ttl',1)
    frame(path/'trades.parquet',trades)
    scenarios=[]
    for c in spec['evaluation']['costs_pips']:
        col=f'net_usd_c{c}';m,daily=metric_summary(trades[col].to_list(),trades['session'].to_list(),reg)
        frame(path/f'daily_cost{c}.parquet',daily)
        m.update({'cost_pips':c,'per_fill_usd':trades[col].mean(),'per_signal_usd':trades[col].sum()/seg.height,'years':[]})
        for y in range(2020,2027):
            t=trades.filter(pl.col('year')==y);rr=reg.filter(pl.col('year')==y)
            ym,_=metric_summary(t[col].to_list(),t['session'].to_list(),rr)
            ym.update({'year':y,'signals':seg.filter(pl.col('year')==y).height,'per_signal_usd':float(t[col].sum())/seg.filter(pl.col('year')==y).height if seg.filter(pl.col('year')==y).height else None});m['years'].append(ym)
        # Native fill-based MTM reconstruction; this is analytics, not a second simulator.
        closed=trades.select('session',pl.col(col).alias('net')).with_columns(pl.col('net').cum_sum().shift(1).fill_null(0).alias('prior_usd'))
        daily_prior=reg.select('session').join(trades.select('session',pl.col(col).alias('net')),on='session',how='left').with_columns(pl.col('net').fill_null(0)).with_columns(pl.col('net').cum_sum().shift(1).fill_null(0).alias('prior_usd'))
        marks=bars.join(daily_prior.select('session','prior_usd'),on='session').join(trades.select('session','entry','entry_time','exit_time',pl.col(col).alias('net')),on='session',how='left').with_columns((10000+pl.col('prior_usd')+pl.when(pl.col('timestamp')>=pl.col('exit_time')).then(pl.col('net')).when(pl.col('timestamp')>=pl.col('entry_time')).then((10000*(pl.col('entry')-pl.col('close'))-10000*c*.01)/pl.col('close')).otherwise(0.)).alias('equity_usd')).sort('timestamp')
        mtm=EquityCurve(marks['timestamp'].to_list(),marks['equity_usd'].to_list())
        m['minute_close_mtm_drawdown_pct']=finite(mtm.max_dd*100);m['mtm_caveat']='Minute closes only; full cost reserved on entry. No tick/intrabar worst excursion or actual broker margin.'
        scenarios.append(m)
    signal=seg.select('session','gotobi','weekday','year','market_entry','exit').join(trades.select('session','entry','entry_time','gross_usd',*[f'net_usd_c{c}' for c in spec['evaluation']['costs_pips']]),on='session',how='left').with_columns(pl.col('entry').is_not_null().alias('filled'))
    frame(path/'signals.parquet',signal)
    touch=bars.filter(pl.col('session').is_in(seg['session'].implode())).join(seg.select('session','ref'),on='session')
    touched=seg.height if market else touch.filter(pl.col('minute').is_between(596,595+v['ttl'])&(pl.col('high').round(8)>=(pl.col('ref').round(8)+v['offset']*.01).round(8)))['session'].n_unique()
    summary={'id':v['id'],'variant':v,'submitted':seg.height,'touched':touched,'filled':a.height,'missed':seg.height-a.height,'expired':0,'cancelled':seg.height-a.height,'expiry_method':'Explicit broker cancellation after last TTL matching bar; no native expiry field','native_quote_pnl_jpy':float(result.metrics['final_value'])-initial,'native_reconciliation_error_jpy':abs(float(result.metrics['final_value'])-initial-float(trades['pnl_jpy'].sum())),'scenarios':scenarios,'native_actual_fills_within_hypothetical_gate':True,'real_queue_fill_probability':'UNKNOWN'}
    save(path/'result.json',summary)
    if not CORRECTED:cli('record','--session',SID,'--trial',v['id'],'--status','completed','--artifact',str((path/'result.json').relative_to(ROOT)))
    print(json.dumps({'run':v['id'],'submitted':seg.height,'filled':a.height,'net1pip':next(m['net_usd'] for m in scenarios if m['cost_pips']==1)}),flush=True)
    return summary

def estimate(y,x,index=0,clusters=None):
    fit=sm.OLS(np.asarray(y,dtype=float),np.asarray(x,dtype=float)).fit(cov_type='HAC',cov_kwds={'maxlags':5},use_t=True)
    out={'n':len(y),'coef':float(fit.params[index]),'ci95':list(map(float,fit.conf_int()[index])),'p':float(fit.pvalues[index])}
    if clusters is not None:
        cf=sm.OLS(y,x).fit(cov_type='cluster',cov_kwds={'groups':clusters},use_t=True)
        out['month_cluster_ci95']=list(map(float,cf.conf_int()[index]))
    return out

def controls(d):return [np.ones(d.height),*[(d['weekday']==v).cast(pl.Float64).to_numpy() for v in range(1,5)],*[(d['year']==v).cast(pl.Float64).to_numpy() for v in range(2021,2027)]]

def proxy(raw,reg,gates,spec):
    # Library returns on dense minute grid prevent returns shifting over gaps.
    grid=reg.join(pl.DataFrame({'minute':range(510,595)}),how='cross').with_columns((pl.col('session').cast(pl.Datetime('us')).dt.replace_time_zone('Asia/Tokyo')+pl.duration(minutes=pl.col('minute'))).dt.convert_time_zone('UTC').alias('timestamp')).sort('timestamp')
    grid=grid.join(raw.select('timestamp','open','high','low','close','volume'),on='timestamp')
    f=compute_features(grid,[{'name':'multi_horizon_returns','params':{'horizons':[1,12,24,84],'log_returns':True}}],group_col='session',timestamp_col='timestamp',assume_sorted=True)
    f=f.with_columns(pl.col('multi_horizon_returns_log_ret_1m').rolling_std(24).over('session').alias('rv'),((pl.col('high')-pl.col('low'))/.01).rolling_mean(24).over('session').alias('range'))
    e=f.filter(pl.col('minute')==594).select('session',pl.col('timestamp').alias('feature_bar'),(pl.col('timestamp')+pl.duration(minutes=1)).alias('available_at'),pl.col('multi_horizon_returns_log_ret_84m').alias('extension0830'),pl.col('multi_horizon_returns_log_ret_24m').alias('extension0930'),'rv','range',(pl.col('multi_horizon_returns_log_ret_12m')-(pl.col('multi_horizon_returns_log_ret_24m')-pl.col('multi_horizon_returns_log_ret_12m'))).alias('acceleration'))
    # 08:30/09:30 reference is minute close; availability conservatively after that minute.
    e=e.join(reg,on='session').join(gates.select('session','proxy0830_complete','proxy0930_complete'),on='session')
    labels=[]
    for end in [610,630]:
        p=raw.filter(pl.col('minute').is_between(596,end)).group_by('session').agg(pl.col('valid').sum().alias('count'),pl.col('open').filter(pl.col('minute')==596).first().alias('entry'),pl.col('open').filter(pl.col('minute')==end).first().alias('exit'))
        labels.append(p.filter(pl.col('count')==end-595).select('session',((pl.col('entry')-pl.col('exit'))/.01).alias(f'y{end}')))
    for lab in labels:e=e.join(lab,on='session',how='left')
    e=e.with_columns((pl.col('available_at')+pl.duration(minutes=1)).alias('first_fill_time'))
    assert e.select((pl.col('available_at')<pl.col('first_fill_time')).all()).item()
    frame(OUT/'proxy_event_panel.parquet',e)
    tests=[];categories=[];native=[]
    for feature in spec['evaluation']['proxy_features']:
        for end in [610,630]:
            gate='proxy0830_complete' if feature=='extension0830' else 'proxy0930_complete'
            d=e.filter(pl.col(gate)).drop_nulls([feature,f'y{end}']).sort('session')
            scale=d.filter(pl.col('year')<=2023)[feature].std()
            assert scale and scale>0
            x=d[feature].to_numpy()/scale;g=d['gotobi'].cast(pl.Float64).to_numpy();y=d[f'y{end}'].to_numpy()
            for group in ['gotobi','ordinary']:
                sub=d.filter(pl.col(group));xx=sub[feature].to_numpy()/scale
                fit=estimate(sub[f'y{end}'].to_numpy(),np.column_stack([*controls(sub),xx]),len(controls(sub)),np.array([str(s)[:7] for s in sub['session']]))
                tests.append({'feature':feature,'horizon':end,'group':group,**fit})
                # Event-level time-series signal analysis, not cross-sectional IC.
                class AnnualExpanding(BaseSplitter):
                    def split(self,X,y=None,groups=None):
                        years=sub['year'].to_numpy()
                        for year in [2024,2025,2026]:
                            train=np.flatnonzero(years<year);test=np.flatnonzero(years==year)
                            if len(train)>=100 and len(test)>=20:yield train,test
                    def get_n_splits(self,X=None,y=None,groups=None):return sum(1 for _ in self.split(X))
                evaluation=Evaluator(splitter=AnnualExpanding(),metrics=['ic','hit_rate'],statistical_tests=[],tier=3).evaluate(xx.reshape(-1,1),sub[f'y{end}'].to_numpy(),make_pipeline(StandardScaler(),LinearRegression()))
                native.append({'feature':feature,'horizon':end,'group':group,'event_rank_correlation_descriptive':finite(information_coefficient(xx,sub[f'y{end}'].to_numpy())), 'yearly_event_correlations':[{'year':year,'n':ss.height,'correlation':finite(information_coefficient(ss[feature].to_numpy(),ss[f'y{end}'].to_numpy()))} for year in range(2020,2027) if (ss:=sub.filter(pl.col('year')==year)).height>=20], 'native_retrospective_walkforward':evaluation.fold_results, 'api_scope':'analyze_signal requires comparable cross-sectional prices; inappropriate for one asset/day. Evaluator and information_coefficient used for event time-series.'})
            cuts=d.filter(pl.col('year')<=2023)[feature].quantile(1/3),d.filter(pl.col('year')<=2023)[feature].quantile(2/3)
            cat=d.with_columns(pl.when(pl.col(feature)<=cuts[0]).then(pl.lit('low')).when(pl.col(feature)<=cuts[1]).then(pl.lit('middle')).otherwise(pl.lit('high')).alias('category'))
            categories.append({'feature':feature,'horizon':end,'development_cuts':cuts,'effects':cat.group_by('category','gotobi','year').agg(pl.len().alias('n'),pl.col(f'y{end}').mean().alias('mean_short_pips')).sort('category','gotobi','year').to_dicts(),'controlled_gotobi_interaction':estimate(y,np.column_stack([*controls(d),g,x,x*g]),len(controls(d))+2,np.array([str(s)[:7] for s in d['session']]))})
    for r,p in zip(tests,multipletests([r['p'] for r in tests],method='holm')[1]):r['p_holm20']=float(p)
    save(OUT/'T1_proxy/result.json',{'tests':tests,'categories':categories,'native_signal_analysis':native,'interpretation':'HYPOTHESIS price proxies only. Descriptive retrospective association, no observed dealer inventory or causal identification. Categorical and interaction estimates secondary, no corrected discovery claim.'})
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axs=plt.subplots(1,2,figsize=(11,4))
    for ax,end in zip(axs,[610,630]):
        for g in [True,False]:
            d=e.filter(pl.col('gotobi')==g).drop_nulls(['extension0930',f'y{end}'])
            ax.scatter(d['extension0930'].to_numpy()*10000,d[f'y{end}'].to_numpy(),s=8,alpha=.3,label='Gotobi' if g else 'Ordinary')
        ax.set_xlabel('Past09:30-09:54 close extension, log bps');ax.set_ylabel('Future short markout, pips');ax.set_title(f'09:56 to{end//60:02d}:{end%60:02d}');ax.legend()
    fig.suptitle('Price proxies: hypothesis, no inventory measurement');fig.tight_layout();fig.savefig(OUT/'price_proxy_map.png');plt.close(fig)

def comparison(raw,reg,panel,spec,results):
    tests=[];adverse=[]
    group=np.column_stack([*controls(panel),panel['gotobi'].cast(pl.Float64).to_numpy()])
    tests.append({'id':'gotobi_minus_ordinary','units':'pips','estimate':estimate(((panel['market_entry']-panel['exit'])/.01).to_numpy(),group,len(controls(panel)),np.array([str(s)[:7] for s in panel['session']]))})
    pp=raw.filter(pl.col('minute').is_between(566,580)).group_by('session').agg(pl.col('valid').sum().alias('n'),pl.col('open').filter(pl.col('minute')==566).first().alias('entry'),pl.col('open').filter(pl.col('minute')==580).first().alias('exitp')).filter(pl.col('n')==15)
    match=panel.join(pp,on='session');gm=match.filter(pl.col('gotobi')).sort('session')
    vals=(((gm['market_entry']-gm['exit'])-(gm['entry']-gm['exitp']))/.01).to_numpy()
    tests.append({'id':'fix_minus_placebo_gotobi','units':'pips','n_matched':gm.height,'estimate':estimate(vals,np.ones((len(vals),1)))})
    for v in spec['evaluation']['variants']:
        signal=pl.read_parquet(RUNS/v['id']/'signals.parquet').sort('session')
        market=10000*(signal['market_entry']-signal['exit']-.01)/signal['exit']
        own=signal['net_usd_c1'].fill_null(0)
        tests.append({'id':v['id']+'_minus_market','units':'USD per submitted signal','estimate':estimate((own-market).to_numpy(),np.ones((signal.height,1))), 'conditional_market_mean_on_filled':float(market.filter(signal['filled']).mean()),'conditional_market_mean_on_missed':finite(market.filter(~signal['filled']).mean()) if (~signal['filled']).sum() else None})
        tr=pl.read_parquet(RUNS/v['id']/'trades.parquet')
        marks=[]
        for lag in [1,3]:
            t=tr.select('session','entry','entry_time').with_columns((pl.col('entry_time')+pl.duration(minutes=lag)).alias('timestamp')).join(raw.select('timestamp',pl.col('open').alias('mark')),on='timestamp',how='left').with_columns(((pl.col('entry')-pl.col('mark'))/.01).alias('short_pips'))
            frame(RUNS/v['id']/f'adverse_markout{lag}.parquet',t)
            marks.append({'minutes_after_fill':lag,'n_observed':t['short_pips'].count(),'short_markout_pips':t['short_pips'].mean()})
        adverse.append({'id':v['id'],'markouts':marks,'exit_short_pips':((tr['entry']-tr['exit'])/.01).mean(),'missed_market_net_usd':finite(market.filter(~signal['filled']).sum()),'label':'Conditional bar markouts, not actual dealer inventory or queue probability'})
    for r,p in zip(tests,multipletests([r['estimate']['p'] for r in tests],method='holm')[1]):r['estimate']['p_holm14']=float(p)
    save(COMPARISON/'result.json',{'tests':tests,'adverse_selection':adverse,'matched_placebo':{'window':'09:26-09:40','n':gm.height,'cost_policy':'Both same14minute duration; raw pip contrast cancels same assumed cost. No optimized placebo time.'},'earlier_native':'Frozen v2 Gotobi458+$217.14; ordinary1143-$450.95; different08:29-10:10 complete cohort; unchanged artifact. New raw fill + cost overlay conversion differs slightly from old exit slippage conversion.','DSR_PBO':'UNKNOWN/unreproducible historical selection adjustment; no selected winner and no unseen OOS.'})
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(10,5))
    for r in results:
        if r['id'].startswith('limit'):
            ax.plot([s['cost_pips'] for s in r['scenarios']],[s['net_usd'] for s in r['scenarios']],marker='o',label=r['id'])
    ax.axhline(0,color='black');ax.set_xlabel('Assumed roundtrip cost, pip');ax.set_ylabel('NetUSD, fixed$10000 base');ax.legend(fontsize=7,ncol=2);fig.tight_layout();fig.savefig(OUT/('fill_cost_sensitivity_corrected.png' if CORRECTED else 'fill_cost_sensitivity.png'));plt.close(fig)

def record(trial):
    if (ROOT/f'run_log/research_sessions/{SID}/trials/{trial}.json').exists():return
    cli('record','--session',SID,'--trial',trial,'--status','completed','--artifact',str((OUT/trial/'result.json').relative_to(ROOT)))

def run():
    spec=yaml.safe_load(SPEC.read_text())
    assert (ROOT/f'run_log/research_sessions/{SID}/frozen_spec.json').exists()
    assert not (OUT/('analysis_corrected.json' if CORRECTED else 'analysis_complete.json')).exists()
    raw,bars,panel,reg,gates=load_data(spec);record('T0_quality')
    if not (OUT/'T1_proxy/result.json').exists():proxy(raw,reg,gates,spec)
    record('T1_proxy')
    results=[]
    for v in [{'id':'market_gotobi','group':'gotobi'},{'id':'market_ordinary','group':'ordinary'}]+spec['evaluation']['variants']:
        results.append(native_run(v,bars,panel,reg,spec))
    comparison(raw,reg,panel,spec,results)
    if not CORRECTED:record('T2_comparison')
    save(OUT/('analysis_corrected.json' if CORRECTED else 'analysis_complete.json'),{'native_runs':len(results),'cohort_n':panel.height,'gotobi_n':panel['gotobi'].sum(),'ordinary_n':panel['ordinary'].sum(),'holdout':'SEALED','approval_status':'NOT_APPROVED','results':results})

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['prepare','run','run_corrected']);a=ap.parse_args()
    if a.mode=='run_corrected':
        CORRECTED=True;RUNS=OUT/'runs_corrected';COMPARISON=OUT/'T2_comparison_corrected'
    if a.mode=='prepare':prepare()
    else:run()
