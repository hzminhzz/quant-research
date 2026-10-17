"""Frozen Program4A native execution and event-level research. No holdout access."""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import inspect
import json
import math
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import numpy as np
import polars as pl
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests
import yaml
from ml4t.engineer import compute_features, labeling
from ml4t.diagnostic import analyze_signal, Evaluator
from ml4t.backtest import Engine, Strategy, DataFeed, BacktestConfig, ExecutionMode, OrderStatus
from ml4t.backtest.config import ExecutionPrice, CommissionType, SlippageType, ShareType
from ml4t.backtest.analytics import EquityCurve, TradeAnalyzer

ROOT = Path(__file__).resolve().parents[1]
SID = 'tokyo_fix_prefx_0700_0830_20261011_v1'
OUT = ROOT / 'run_log' / SID
SPEC = ROOT / 'config/research_sessions' / (SID + '.yaml')
JST = ZoneInfo('Asia/Tokyo')
UTC = ZoneInfo('UTC')
SEAL = datetime(2026, 9, 1, tzinfo=JST)
CAL = ROOT / 'run_log/tokyo_fix_alpha_map_program1_20261010/execution_v1/calendar_event_registry.parquet'
SOURCES = [ROOT / f'data/processed/tokyo_alpha_map_program1_v1/USDJPY_03_12_JST_{y}.parquet' for y in range(2020, 2027)]
SKILLS = ['validate-data', 'polars-patterns', 'point-in-time', 'calendar-ops', 'compute-features', 'evaluate-factor', 'run-backtest', 'transaction-costs', 'cost-model', 'non-stationarity', 'regime-awareness', 'lookahead-bias', 'sensitivity-analysis', 'backtest-overfitting']


def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def save(p, obj):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(obj, indent=2, default=str, allow_nan=False) + '\n'
    if p.exists():
        if json.loads(p.read_text()) != json.loads(encoded):
            raise RuntimeError(f'Immutable evidence differs: {p}')
        return
    with p.open('x') as f:
        f.write(encoded)


def frame(p, data):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        if not pl.read_parquet(p).equals(data):
            raise RuntimeError(f'Immutable frame differs: {p}')
        return
    data.write_parquet(p)


def cli(*args):
    proc = subprocess.run([sys.executable, str(ROOT / 'scripts/research_session.py'), *args, '--root', str(ROOT)], capture_output=True, text=True, cwd=ROOT)
    if proc.returncode:
        raise RuntimeError(proc.stdout + proc.stderr)
    return json.loads(proc.stdout)


def preservation():
    state = subprocess.check_output(['git', 'status', '--porcelain=v1', '--untracked-files=all'], cwd=ROOT, text=True)
    paths = set(SOURCES + [CAL])
    for line in state.splitlines():
        p = ROOT / line[3:]
        if p.is_file() and SID not in str(p) and p.stat().st_size < 100 * 1024 * 1024:
            paths.add(p)
    return {'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(), 'git_status': state, 'hashes': {str(p.relative_to(ROOT)): sha(p) for p in sorted(paths)}, 'scope': 'All original dirty files below100MB and canonical sources/calendar. Larger unrelated data inventoried only.'}


def minute(t):
    local = t.astimezone(JST)
    return local.hour * 60 + local.minute


def finite(x):
    return float(x) if math.isfinite(float(x)) else None


def prepare():
    if SPEC.exists() or (ROOT / 'run_log/research_sessions' / SID).exists():
        raise RuntimeError('Session already exists; use run to resume, never re-freeze.')
    OUT.mkdir(parents=True, exist_ok=True)
    save(OUT / 'preservation_before.json', preservation())
    save(OUT / 'source_manifest.json', {'sources': [{'path': str(p.relative_to(ROOT)), 'bytes': p.stat().st_size, 'sha256': sha(p)} for p in SOURCES], 'calendar': {'path': str(CAL.relative_to(ROOT)), 'sha256': sha(CAL)}, 'holdout_read': False, 'seal': SEAL.isoformat(), 'bar_semantics': 'UTC minute OPEN; close available timestamp+1min (inference). No protected store paths accessed.'})
    save(OUT / 'methodology.json', {'skills': [{'name': 'ml4t-' + n, 'path': f'.agents/skills/ml4t-{n}/SKILL.md', 'sha256': sha(ROOT / f'.agents/skills/ml4t-{n}/SKILL.md'), 'invariants': 'Contiguous valid minutes; prior-only features; train-only cutoffs; native next-open orders; currency reconciliation; bounded family; preserved sources and holdout.'} for n in SKILLS], 'catalog': 'https://github.com/ml4t/skills (read with TinyFish before freeze)', 'versions': {p: importlib.metadata.version(p) for p in ['ml4t-backtest', 'ml4t-engineer', 'ml4t-diagnostic', 'polars']}, 'signatures': {x.__name__: str(inspect.signature(x)) for x in [Engine, DataFeed, BacktestConfig, compute_features, EquityCurve, TradeAnalyzer]}, 'conflicts': 'Mission prohibits commits and protected holdout scoring; use immutable CLI freeze instead of skill commit/holdout guidance. Fixed notional equals initial equity; after losses notional/current equity can exceed1. Disclose that ratio; do not claim a current-NAV1x cap. Native JPY margin0.5 is bookkeeping support for quote-currency account; not economic2x sizing or verified broker margin.', 'statistics': 'Event-level statsmodels OLS HAC5 and month cluster; not cross-sectional IC. EquityCurve/TradeAnalyzer metrics. Holm8 current family only; complete historical search unknown, DSR/PBO unreproducible.', 'runtime': 'Shared and private tmux sockets denied by sandbox. Use supervised process and saved logs; no duplicate mission job found in visible process namespace.'})
    trials = [('T0_data_gate', 'Contiguous execution/features/placebo gates and missingness'), ('T1_native_gotobi', 'Native long07:00-08:30 Gotobi, 1pip'), ('T2_native_ordinary', 'Same native long on ordinary dates, 1pip'), ('T3_cost_sensitivity', 'Native0/.8/1/1.4/2/3pip Gotobi and native07:01/07:02 delay stress1pip'), ('T4_regimes', 'Past rv/drift, development2020-23 terciles, retrospective2024-25 and2026 stress'), ('T5_refutation', 'Native90min10:00-11:30 placebo; calendar premium/control and matched difference; Holm8'), ('T6_independent_oracle', 'Original source every-order, gate, feature and native cash oracle'), ('T7_final_audit', 'Tests, preservation, ledger hashes, final report and seal')]
    spec = {'session_id': SID, 'market': 'fx', 'thesis': 'Calendar-only Gotobi USDJPY long07:00-08:30 has positive net mean and exceeds ordinary Tokyo drift.', 'mechanism': 'HYPOTHESIS: corporate USD settlement demand creates early Tokyo buying pressure; prices do not observe flow.', 'falsifier': 'Reject economic robustness if1pip Gotobi net USD full sample or either2024-25 or2026Jan-Aug is nonpositive; calendar-specific evidence requires positive controlled premium with Holm8p<.05. Placebo non-difference limits timing specificity. No live approval.', 'instruments': [{'symbol': 'USDJPY', 'kind': 'cfd', 'venue': 'UNSPECIFIED_RETAIL_FX_BROKER', 'identity': 'LSE composite research proxy JPY/USD; USD10000 base units, no compounding; actual broker bid/ask, lots, margin and financing UNKNOWN.', 'timezone': 'Asia/Tokyo', 'session': 'Tokyo bank calendar'}], 'data': [{'id': f'year{y}', 'path': str(p.relative_to(ROOT)), 'role': 'prices', 'symbol': 'USDJPY'} for y, p in zip(range(2020, 2027), SOURCES)], 'evaluation': {'development_start': '2020-01-01T00:00:00Z', 'development_end': '2026-08-31T15:00:00Z', 'holdout_start': '2026-08-31T15:00:00Z', 'holdout_end': '2026-10-31T15:00:00Z', 'holdout': 'SEALED NEVER READ', 'chronology': '2020-23 cutoff fit;2024-25 retrospective validation;2026Jan-Aug observed stress. All history previously inspected.', 'initial_usd': 10000, 'notional_usd': 10000, 'entry': 420, 'exit': 510, 'execution_gate': [418, 510], 'feature_gate': [388, 418], 'feature': '30 one-minute log returns from06:28 close through06:58 close; 06:58 close available06:59. Drift same endpoints. No06:59 close.', 'placebo': [600, 690], 'placebo_gate': [598, 690], 'costs_pips': [0, .8, 1, 1.4, 2, 3], 'delays': [1, 2], 'cutoff_fit': 'Both terciles fit on ALL complete bank dates2020-23; frozen before native outcomes. No filter strategy.', 'tests': ['Gotobi net1pip mean vs0', 'weekday/year controlled net calendar premium', 'placebo controlled net calendar premium', 'matched fix-minus-placebo controlled premium', '2024-25 rv high-minus-low Gotobi net', '2026 rv high-minus-low Gotobi net', '2024-25 drift high-minus-low Gotobi net', '2026 drift high-minus-low Gotobi net'], 'multiplicity': 'One Holm8 family over listed contrasts, two-sided HAC5; month-cluster sensitivity for calendar contrasts. All other yearly/cost/slice summaries descriptive. Does not erase prior126/18/16/640 and other known historical tests.', 'stop_rule': 'Execute fixed variants once; repair implementation failures with retained attempt logs; no minute or feature search.'}, 'baseline': 'Ordinary bank dates same eligibility and clock; flat bank days in portfolio; preserved original08:30-09:54 long and09:56-10:10 short benchmarks on distinct samples.', 'costs': {'commission_bps': 0, 'slippage_bps': 0, 'roundtrip_pips': [0, .8, 1, 1.4, 2, 3], 'method': 'Native fixed adverse JPY .01*cost/2 per fill; zero is gross reference only. USD translation at executed adverse exit. Not broker-calibrated.', 'financing': 'No overnight. Actual same-day financing UNKNOWN.', 'impact': 'Not calibrated; no executable volume/bid/ask. No capacity claim.'}, 'trials': [{'id': n, 'kind': 'diagnostic' if n not in ['T1_native_gotobi', 'T2_native_ordinary'] else 'preregistered', 'description': d} for n, d in trials], 'evidence': [str((OUT / n).relative_to(ROOT)) for n in ['source_manifest.json', 'methodology.json', 'preservation_before.json']]}
    with SPEC.open('x') as f:
        yaml.safe_dump(spec, f, sort_keys=False)
    save(OUT / 'freeze_init.json', cli('init', '--spec', str(SPEC.relative_to(ROOT))))
    save(OUT / 'freeze_check.json', cli('check', '--session', SID))
    print('FROZEN_BEFORE_OUTCOMES', flush=True)


def quality_gate(raw, calendar, windows):
    good = pl.all_horizontal([pl.col(c).is_finite() & pl.col(c).is_not_null() & (pl.col(c) > 0) for c in ['open', 'high', 'low', 'close']]) & (pl.col('high') >= pl.max_horizontal('open', 'close')) & (pl.col('low') <= pl.min_horizontal('open', 'close')) & (pl.col('high') >= pl.col('low'))
    raw = raw.with_columns(good.fill_null(False).alias('valid'))
    gates = calendar
    for label, (start, end) in windows.items():
        obs = raw.filter(pl.col('minute').is_between(start, end)).group_by('session').agg(pl.len().alias(label + '_observed'), pl.col('minute').n_unique().alias(label + '_unique'), pl.col('valid').sum().alias(label + '_valid'))
        gates = gates.join(obs, on='session', how='left').with_columns(pl.col(label + '_observed', label + '_unique', label + '_valid').fill_null(0)).with_columns(((pl.col(label + '_observed') == end - start + 1) & (pl.col(label + '_unique') == end - start + 1) & (pl.col(label + '_valid') == end - start + 1)).alias(label + '_complete'))
    return raw, gates


def load_data(spec):
    raw = pl.scan_parquet(SOURCES).filter(pl.col('timestamp') < SEAL.astimezone(UTC)).with_columns(pl.col('timestamp').dt.convert_time_zone('Asia/Tokyo').alias('jst')).with_columns(pl.col('jst').dt.date().alias('session'), (pl.col('jst').dt.hour().cast(pl.Int32) * 60 + pl.col('jst').dt.minute()).alias('minute')).sort('timestamp').collect()
    assert raw['timestamp'].max() < SEAL
    calendar = pl.scan_parquet(CAL).filter(pl.col('session') < SEAL.date()).select('session', 'gotobi', 'ordinary', 'weekday', 'year').sort('session').collect()
    windows = {'execution': spec['evaluation']['execution_gate'], 'features': spec['evaluation']['feature_gate'], 'placebo': spec['evaluation']['placebo_gate'], 'old0700': [420, 510]}
    raw, gates = quality_gate(raw, calendar, windows)
    frame(OUT / 'window_gates.parquet', gates)
    summary = {'bank_dates': calendar.height, 'windows': windows, 'coverage': {n: gates.group_by('year', 'weekday', 'gotobi', n + '_complete').len().sort('year', 'weekday', 'gotobi', n + '_complete').to_dicts() for n in windows}, 'new_eligible': gates.filter(pl.col('execution_complete')).height, 'old91min_eligible': gates.filter(pl.col('old0700_complete')).height, 'old_1418_difference': gates.filter(pl.col('execution_complete')).height - 1418, 'newly_excluded_vs91min': gates.filter(pl.col('old0700_complete') & ~pl.col('execution_complete')).select('session', 'year', 'weekday', 'gotobi').to_dicts(), 'duplicate_timestamps': int(raw['timestamp'].is_duplicated().sum()), 'quality': raw.group_by(pl.col('session').dt.year().alias('year')).agg(pl.len().alias('rows'), (~pl.col('valid')).sum().alias('invalid_ohlc'), (pl.col('volume') == 0).sum().alias('zero_volume'), (pl.col('close').pct_change().over('session').abs() > .5).sum().alias('extreme_returns'), ((pl.col('close') == pl.col('close').shift(1).over('session')).cast(pl.Int32).rolling_sum(5).over('session') >= 5).sum().alias('stale5')).sort('year').to_dicts(), 'interpolation': False, 'holdout_read': False, 'stale_policy': 'Reported only; composite unchanged closes do not establish unavailable executable quotes.'}
    save(OUT / 'T0_data_gate/result.json', summary)
    return raw, calendar, gates


def features(raw, gates, spec):
    eligible = gates.filter(pl.col('features_complete'))['session']
    feature_bars = raw.filter(pl.col('session').is_in(eligible.implode()) & pl.col('minute').is_between(*spec['evaluation']['feature_gate']))
    computed = compute_features(feature_bars, [{'name': 'multi_horizon_returns', 'params': {'horizons': [1, 30], 'log_returns': True}}], group_col='session', timestamp_col='timestamp', assume_sorted=True)
    computed = computed.with_columns(pl.col('multi_horizon_returns_log_ret_1m').rolling_std(30).over('session').alias('rv'))
    events = computed.filter(pl.col('minute') == 418).select('session', 'rv', pl.col('multi_horizon_returns_log_ret_30m').alias('drift'), pl.col('timestamp').alias('feature_bar'), (pl.col('timestamp') + pl.duration(minutes=1)).alias('available_at')).join(gates.select('session', 'gotobi', 'ordinary', 'weekday', 'year', 'execution_complete'), on='session').sort('session')
    cutoff = {}
    for name in ['rv', 'drift']:
        training = events.filter(pl.col('year') <= 2023)[name].drop_nulls().to_numpy()
        assert np.isfinite(training).all()
        cutoff[name] = np.quantile(training, [1/3, 2/3]).tolist()
    save(OUT / 'regime_cutoffs_frozen.json', {'cutoffs': cutoff, 'fit_scope': 'All complete prior-feature bank dates2020-23; no returns or native outcomes used.', 'fit_n': events.filter(pl.col('year') <= 2023).height, 'frozen_utc': datetime.now(UTC).isoformat()} if not (OUT / 'regime_cutoffs_frozen.json').exists() else {**json.loads((OUT / 'regime_cutoffs_frozen.json').read_text()), 'cutoffs': cutoff})
    for name, (a, b) in cutoff.items():
        events = events.with_columns(pl.when(pl.col(name) <= a).then(pl.lit('low')).when(pl.col(name) <= b).then(pl.lit('mid')).otherwise(pl.lit('high')).alias(name + '_regime'))
    assert events['available_at'].dt.convert_time_zone('Asia/Tokyo').dt.strftime('%H:%M').unique().to_list() == ['06:59']
    frame(OUT / 'prior_features.parquet', events)
    return events


class CalendarLong(Strategy):
    def __init__(self, dates, entry, exit_minute, notional):
        self.dates, self.entry, self.exit, self.notional = set(dates), entry, exit_minute, notional
        self.events = []
    def on_start(self, broker):
        pass
    def on_data(self, timestamp, data, context, broker):
        day, clock = timestamp.astimezone(JST).date(), minute(timestamp)
        if day not in self.dates:
            assert broker.get_position('USDJPY') is None
            return
        if clock == self.entry - 1:
            assert broker.get_position('USDJPY') is None
            order = broker.submit_order('USDJPY', self.notional)
            if order is None:
                raise RuntimeError('Rejected entry')
            self.events.append((day, 'entry', timestamp, order))
        if clock == self.exit - 1:
            assert broker.get_position('USDJPY') is not None
            order = broker.close_position('USDJPY')
            self.events.append((day, 'exit', timestamp, order))
        if clock >= self.exit:
            assert broker.get_position('USDJPY') is None
    def on_end(self, broker):
        assert broker.get_position('USDJPY') is None


def metrics(trades, calendar):
    daily = calendar.select('session').join(trades.select('session', 'pnl_usd'), on='session', how='left', validate='1:1').with_columns(pl.col('pnl_usd').fill_null(0)).with_columns((10000 + pl.col('pnl_usd').cum_sum()).alias('equity_usd'))
    times = [datetime.combine(calendar['session'][0] - timedelta(days=1), datetime.min.time(), JST)] + [datetime.combine(d, datetime.min.time(), JST) for d in daily['session']]
    eq = EquityCurve(times, [10000] + daily['equity_usd'].to_list(), periods_per_year_override=252)
    analyzer = TradeAnalyzer([SimpleNamespace(pnl=p, pnl_percent=p / 10000, status='closed') for p in trades['pnl_usd']])
    p = trades['pnl_usd']
    loss = p.filter(p < 0)
    totals = {'n': trades.height, 'gross_pips_mean': finite(trades['gross_pips'].mean()) if trades.height else None, 'net_pips_mean': finite(trades['net_pips'].mean()) if trades.height else None, 'net_pips_total': float(trades['net_pips'].sum()), 'net_usd': float(p.sum()), 'end_balance_usd': float(daily['equity_usd'][-1]), 'win_rate': finite(analyzer.win_rate), 'profit_factor': finite(analyzer.profit_factor), 'daily_sharpe': finite(eq.sharpe), 'closed_drawdown_pct': finite(eq.max_dd * 100), 'closed_drawdown_usd': float((daily['equity_usd'] - daily['equity_usd'].cum_max().clip(lower_bound=10000)).min()), 'worst_trade_usd': finite(p.min()) if len(p) else None, 'p05_trade_usd': finite(p.quantile(.05)) if len(p) else None, 'worst5_loss_share': float(-loss.sort().head(5).sum() / -loss.sum()) if loss.sum() < 0 else None, 'bank_days_in_equity': calendar.height}
    return totals, daily


def native(name, raw, calendar, gates, group, cost, entry=420, end=510, placebo=False):
    dest = OUT / 'runs' / name
    if (dest / 'result.json').exists():
        return json.loads((dest / 'result.json').read_text())
    dates = gates.filter(pl.col('placebo_complete' if placebo else 'execution_complete') & pl.col(group))['session']
    start = 598 if placebo else 418
    bars = raw.filter(pl.col('session').is_in(dates.implode()) & pl.col('minute').is_between(start, end))
    prices = bars.select('timestamp', 'symbol', 'open', 'high', 'low', 'close', 'volume')
    initial_jpy = 10000 * float(prices['open'][0])
    strategy = CalendarLong(dates.to_list(), entry, end, 10000)
    cfg = BacktestConfig(initial_cash=initial_jpy, allow_leverage=True, initial_margin=.5, execution_mode=ExecutionMode.NEXT_BAR, execution_price=ExecutionPrice.OPEN, share_type=ShareType.FRACTIONAL, commission_type=CommissionType.NONE, slippage_type=SlippageType.FIXED, slippage_fixed=cost * .01 / 2, partial_fills_allowed=False)
    engine = Engine(DataFeed(prices_df=prices), strategy, cfg)
    result = engine.run()
    orders = pl.DataFrame([{'session': day, 'role': role, 'submitted_at': timestamp, 'filled_at': order.filled_at, 'price': order.filled_price, 'quantity': order.quantity, 'status': order.status.value, 'order_id': order.order_id} for day, role, timestamp, order in strategy.events]).sort('submitted_at')
    assert orders.height == 2 * len(dates) and orders.filter(pl.col('status') != 'filled').height == 0
    a = orders.filter(pl.col('role') == 'entry').select('session', pl.col('filled_at').alias('entry_time'), pl.col('price').alias('entry_price'))
    z = orders.filter(pl.col('role') == 'exit').select('session', pl.col('filled_at').alias('exit_time'), pl.col('price').alias('exit_price'))
    source = bars.group_by('session').agg(pl.col('open').filter(pl.col('minute') == entry).first().alias('source_entry'), pl.col('open').filter(pl.col('minute') == end).first().alias('source_exit'))
    trades = a.join(z, on='session', validate='1:1').join(source, on='session', validate='1:1').join(calendar, on='session', validate='1:1').sort('session').with_columns(((pl.col('exit_price') - pl.col('entry_price')) * 10000).alias('pnl_jpy'), ((pl.col('source_exit') - pl.col('source_entry')) / .01).alias('gross_pips'), ((pl.col('exit_price') - pl.col('entry_price')) / .01).alias('net_pips')).with_columns((pl.col('pnl_jpy') / pl.col('exit_price')).alias('pnl_usd'))
    quote_delta = float(result.metrics['final_value']) - initial_jpy
    assert np.isclose(quote_delta, trades['pnl_jpy'].sum(), atol=1e-5, rtol=0)
    main, daily = metrics(trades, calendar)
    years = []
    for year in range(2020, 2027):
        sub, _ = metrics(trades.filter(pl.col('year') == year), calendar.filter(pl.col('year') == year))
        years.append({'year': year, **sub})
    conditional = []
    for weekday in range(5):
        sub = trades.filter(pl.col('weekday') == weekday)
        conditional.append({'weekday': weekday, 'n': sub.height, 'gross_pips_mean': finite(sub['gross_pips'].mean()) if sub.height else None, 'net_pips_mean': finite(sub['net_pips'].mean()) if sub.height else None, 'net_usd': float(sub['pnl_usd'].sum())})
    # Account mark reconstruction uses native executions only, not a second simulator.
    prior = daily.select('session', pl.col('pnl_usd').cum_sum().shift(1).fill_null(0).alias('prior'))
    marks = raw.filter(pl.col('session').is_in(gates.filter(pl.col('placebo_complete' if placebo else 'execution_complete'))['session'].implode()) & pl.col('minute').is_between(start, end)).join(prior, on='session').join(trades.select('session', 'entry_time', 'exit_time', 'entry_price', 'pnl_usd'), on='session', how='left').with_columns((10000 + pl.col('prior') + pl.when(pl.col('timestamp') >= pl.col('exit_time')).then(pl.col('pnl_usd')).when(pl.col('timestamp') >= pl.col('entry_time')).then(10000 * (pl.col('close') - pl.col('entry_price') - cost * .01 / 2) / (pl.col('close') - cost * .01 / 2)).otherwise(0)).alias('equity_usd')).sort('timestamp')
    curve = EquityCurve([marks['timestamp'][0] - timedelta(minutes=1)] + marks['timestamp'].to_list(), [10000] + marks['equity_usd'].to_list())
    prior_trade_equity = trades.join(prior, on='session')['prior'] + 10000
    main.update({'minute_close_mtm_drawdown_pct': finite(curve.max_dd * 100), 'max_notional_over_current_equity': finite((10000 / prior_trade_equity).max()), 'notional_over_initial_equity': 1.0, 'intratrade_caveat': 'Native fills marked at minute closes; assumed exit halfcost reserved. No tick extremes or broker margin model.'})
    output = {'run': name, 'group': group, 'cost_pips': cost, 'entry_minute': entry, 'exit_minute': end, 'metrics': main, 'years': years, 'weekday': conditional, 'native_initial_jpy': initial_jpy, 'native_final_jpy': float(result.metrics['final_value']), 'native_pnl_jpy': quote_delta, 'account_reconciliation_error_jpy': abs(quote_delta - float(trades['pnl_jpy'].sum())), 'orders': orders.height, 'no_carry': True, 'cost_method': 'Native fixed adverse price each fill; conversion at executed exit.'}
    frame(dest / 'orders.parquet', orders)
    frame(dest / 'trades.parquet', trades)
    frame(dest / 'daily.parquet', daily)
    frame(dest / 'marks.parquet', marks.select('timestamp', 'session', 'equity_usd'))
    save(dest / 'result.json', output)
    print(json.dumps({'native': name, **main}), flush=True)
    return output


def estimate(y, design, index=0, clusters=None):
    y, design = np.asarray(y, dtype=float), np.asarray(design, dtype=float)
    if len(y) < 10 or np.linalg.matrix_rank(design) < design.shape[1]:
        return {'n': len(y), 'status': 'INSUFFICIENT', 'p': 1.0}
    fit = sm.OLS(y, design).fit(cov_type='HAC', cov_kwds={'maxlags': 5}, use_t=True)
    out = {'n': len(y), 'coef': float(fit.params[index]), 'ci95': fit.conf_int()[index].tolist(), 'p': float(fit.pvalues[index]), 'status': 'ESTIMATED'}
    if clusters is not None:
        other = sm.OLS(y, design).fit(cov_type='cluster', cov_kwds={'groups': clusters}, use_t=True)
        out.update({'month_cluster_ci95': other.conf_int()[index].tolist(), 'month_cluster_p': float(other.pvalues[index])})
    return out


def controls(data):
    # Calendar variation is observational; no settlement-flow identification.
    columns = [np.ones(data.height)]
    for name in ['weekday', 'year']:
        levels = sorted(data[name].unique().to_list())
        columns += [(data[name] == value).cast(pl.Float64).to_numpy() for value in levels[1:]]
    return columns


def controlled(data, y):
    return estimate(data[y].to_numpy(), np.column_stack([data['gotobi'].cast(pl.Float64).to_numpy(), *controls(data)]), clusters=data['session'].dt.strftime('%Y-%m').to_numpy())


def analysis(events, calendar):
    load = lambda n: pl.read_parquet(OUT / 'runs' / n / 'trades.parquet')
    gotobi, ordinary = load('gotobi_c1'), load('ordinary_c1')
    panel = pl.concat([gotobi, ordinary]).sort('session')
    tests = [{'id': 'gotobi_net_mean', **estimate(gotobi['pnl_usd'], np.ones((gotobi.height, 1)))}, {'id': 'calendar_net_premium', **controlled(panel, 'pnl_usd')}]
    placebo = pl.concat([load('placebo_gotobi_c1'), load('placebo_ordinary_c1')]).sort('session')
    tests.append({'id': 'placebo_calendar_net_premium', **controlled(placebo, 'pnl_usd')})
    matched = panel.join(placebo.select('session', pl.col('pnl_usd').alias('placebo_usd')), on='session', validate='1:1').with_columns((pl.col('pnl_usd') - pl.col('placebo_usd')).alias('difference'))
    tests.append({'id': 'matched_fix_minus_placebo_premium', **controlled(matched, 'difference')})
    enriched = gotobi.join(events.drop('gotobi', 'ordinary', 'year', 'weekday'), on='session', how='inner').sort('session')
    slices = []
    for feature in ['rv', 'drift']:
        for period, mask in [('development2020_23', pl.col('year') <= 2023), ('retrospective2024_25', pl.col('year').is_between(2024, 2025)), ('stress2026', pl.col('year') == 2026)]:
            period_data = enriched.filter(mask)
            for label in ['low', 'mid', 'high']:
                sub = period_data.filter(pl.col(feature + '_regime') == label)
                report, _ = metrics(sub, calendar.filter(pl.col('year').is_in(period_data['year'].unique().implode())))
                mean = estimate(sub['pnl_usd'], np.ones((sub.height, 1)))
                slices.append({'feature': feature, 'period': period, 'regime': label, **report, 'net_mean_hac': mean})
                for year in sorted(sub['year'].unique()):
                    yy = sub.filter(pl.col('year') == year)
                    slices.append({'feature': feature, 'period': 'yearly_descriptive', 'year': year, 'regime': label, 'n': yy.height, 'gross_pips_mean': finite(yy['gross_pips'].mean()), 'net_pips_mean': finite(yy['net_pips'].mean()), 'net_usd': float(yy['pnl_usd'].sum())})
            if period != 'development2020_23':
                extremes = period_data.filter(pl.col(feature + '_regime').is_in(['low', 'high']))
                tests.append({'id': period + '_' + feature + '_high_minus_low', **estimate(extremes['pnl_usd'], np.column_stack([(extremes[feature + '_regime'] == 'high').cast(pl.Float64).to_numpy(), np.ones(extremes.height)]))})
    assert len(tests) == 8
    ps = multipletests([t['p'] for t in tests], method='holm')[1]
    for test, p in zip(tests, ps):
        test['holm8_p'] = float(p)
    frame(OUT / 'event_panel.parquet', panel)
    frame(OUT / 'regime_event_panel.parquet', enriched)
    frame(OUT / 'matched_placebo_panel.parquet', matched)
    regimes = {'cutoffs': json.loads((OUT / 'regime_cutoffs_frozen.json').read_text()), 'slices': slices, 'feature_missing_gotobi': gotobi.height - enriched.height, 'no_filter_strategy': True, 'risk_shift': [{'period': name, 'feature_n': events.filter(mask).height, 'rv_median': finite(events.filter(mask)['rv'].median()), 'drift_median': finite(events.filter(mask)['drift'].median())} for name, mask in [('development', pl.col('year') <= 2023), ('validation', pl.col('year').is_between(2024, 2025)), ('stress', pl.col('year') == 2026)]], '2026_monthly': enriched.filter(pl.col('year') == 2026).group_by(pl.col('session').dt.month().alias('month')).agg(pl.len().alias('n'), pl.col('gross_pips').mean(), pl.col('net_pips').mean(), pl.col('pnl_usd').sum()).sort('month').to_dicts()}
    save(OUT / 'T4_regimes/result.json', regimes)
    refutation = {'tests': tests, 'units': 'USD per fixedUSD10000 trade; two-sided inference', 'matched_n': matched.height, 'matched_gotobi_n': matched.filter(pl.col('gotobi')).height, 'main_n': panel.height, 'placebo_n': placebo.height, 'placebo_window': '10:00-11:30JST native next-bar open', 'month_cluster_and_hac': True, 'historical_multiplicity': 'Prior126,18,16,640 plus other trials already inspected; full count incomplete. Holm8 is supplementary only. DSR/PBO not reproducible.', 'gross_pip_premium': controlled(panel, 'gross_pips'), 'matched_date_exclusions': {'main_without_placebo': panel.join(placebo.select('session'), on='session', how='anti')['session'].to_list(), 'placebo_without_main': placebo.join(panel.select('session'), on='session', how='anti')['session'].to_list()}}
    save(OUT / 'T5_refutation/result.json', refutation)
    return regimes, refutation


def record(trial):
    path = OUT / trial / 'result.json'
    terminal = ROOT / 'run_log/research_sessions' / SID / 'trials' / (trial + '.json')
    if terminal.exists():
        return
    cli('record', '--session', SID, '--trial', trial, '--status', 'completed', '--artifact', str(path.relative_to(ROOT)))


def run():
    frozen = cli('check', '--session', SID)
    if frozen['status'] != 'PASS':
        raise RuntimeError('Freeze audit blocked: ' + str(frozen))
    spec = yaml.safe_load(SPEC.read_text())
    raw, calendar, gates = load_data(spec)
    events = features(raw, gates, spec)
    record('T0_data_gate')
    primary = native('gotobi_c1', raw, calendar, gates, 'gotobi', 1)
    save(OUT / 'T1_native_gotobi/result.json', primary)
    record('T1_native_gotobi')
    control = native('ordinary_c1', raw, calendar, gates, 'ordinary', 1)
    save(OUT / 'T2_native_ordinary/result.json', control)
    record('T2_native_ordinary')
    cost_runs = []
    for cost in spec['evaluation']['costs_pips']:
        cost_runs.append(native('gotobi_c' + str(cost), raw, calendar, gates, 'gotobi', cost))
    delays = [native('gotobi_delay' + str(d), raw, calendar, gates, 'gotobi', 1, entry=420 + d) for d in spec['evaluation']['delays']]
    gross = pl.read_parquet(OUT / 'runs/gotobi_c0/trades.parquet')
    # Breakeven in USD includes cost-dependent executed-exit denominator.
    from scipy.optimize import brentq
    fn = lambda c: np.sum(10000 * (gross['source_exit'].to_numpy() - gross['source_entry'].to_numpy() - c * .01) / (gross['source_exit'].to_numpy() - c * .005))
    root = brentq(fn, -100, 100)
    save(OUT / 'T3_cost_sensitivity/result.json', {'native_cost_runs': cost_runs, 'native_delay_stress': delays, 'usd_breakeven_roundtrip_pips': root, 'method': 'All ladder and delay arms native Engine, including gross0 and3x; root is deterministic accounting diagnostic, not a new economic trial.'})
    record('T3_cost_sensitivity')
    for group in ['gotobi', 'ordinary']:
        native('placebo_' + group + '_c1', raw, calendar, gates, group, 1, entry=600, end=690, placebo=True)
    analysis(events, calendar)
    record('T4_regimes')
    record('T5_refutation')
    save(OUT / 'execution_complete.json', {'status': 'NATIVE_EXECUTION_AND_ANALYSIS_COMPLETE', 'holdout_read': False, 'native_runs': sorted(p.parent.name for p in (OUT / 'runs').glob('*/result.json'))})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['prepare', 'run'])
    args = parser.parse_args()
    prepare() if args.mode == 'prepare' else run()


if __name__ == '__main__':
    main()
