from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import polars as pl

from src.data_vault.panel_builder import validate_panel
from src.engine.sleeve_runner import (
    EVIDENCE_ROOT,
    SleeveLoaders,
    load_products,
    run_sleeve,
)
from src.engine.ts_casefile import read_trials
from src.engine.ts_spec import parse_ts_spec

SPEC_DIR = Path(__file__).parents[1] / 'config/sleeves/advanced_futures_30'
HASH = 'a' * 64


def synthetic_loaders(spec, market_class, requests, *, products=None) -> SleeveLoaders:
    anchor = spec.windows.train.start
    bar = market_class.bar_seconds
    bars = 800 if bar == 3600 else 3 * 24 * 60
    warmup_bars = 86400 // bar
    start = anchor - timedelta(seconds=bar * warmup_bars)
    bars += warmup_bars

    def panel_loader(mc, requested_start, requested_end):
        requests.append((mc.name, requested_start, requested_end))
        rows = []
        for symbol_index, symbol in enumerate(mc.symbols):
            price = 100.0 + symbol_index
            for index in range(bars):
                price *= 1.0 + 0.0002 * ((index + symbol_index) % 7 - 3)
                rows.append({
                    'timestamp': start + timedelta(seconds=bar * index),
                    'symbol': symbol,
                    'open': price, 'high': price * 1.001, 'low': price * 0.999, 'close': price,
                    'volume': 1000.0, 'carry_rate': 0.0, 'spread_bps': 0.0,
                    'session_id': '24x7', 'bar_in_session': index, 'is_tradable': True,
                })
        return validate_panel(pl.DataFrame(rows))

    def funding_loader(mc, requested_start, requested_end):
        first = start
        events = []
        for day in range(bars * bar // 86400):
            instant = first + timedelta(days=day)
            for symbol in mc.symbols:
                events.append({'timestamp': instant, 'symbol': symbol,
                               'funding_rate': 0.0001, 'mark_price': 100.0})
        return pl.DataFrame(events)

    def curve_loader(name, requested_start, requested_end):
        first = start - timedelta(days=1)
        last = start + timedelta(seconds=bar * bars)
        grid = []
        instant = first
        while instant <= last:
            grid.append({'timestamp': instant, 'rate_pct': 4.5})
            instant += timedelta(days=1)
        return pl.DataFrame(grid)

    if products is None:
        products = {}
        for symbol in market_class.symbols:
            if market_class.name == 'indices':
                products[symbol] = __import__('src.engine.carry_model', fromlist=['CarryProduct']).CarryProduct(
                    symbol=symbol, class_name='indices', kind='spot_cfd', income_yield_bps=0.0)
            elif market_class.name == 'metals':
                products[symbol] = __import__('src.engine.carry_model', fromlist=['CarryProduct']).CarryProduct(
                    symbol=symbol, class_name='metals', kind='spot_cfd', lease_rate_bps=0.0)

    return SleeveLoaders(panel=panel_loader, funding=funding_loader, curve=curve_loader,
                         manifest=lambda mc: {'quality_summary': {'execution_qualified': False},
                                              'manifest_hash': HASH},
                         products=products)


def all_specs() -> list[Path]:
    return sorted(SPEC_DIR.glob('af30_s*.yaml'))


def test_every_variant_has_a_disposition_and_dsr_inputs_match_the_ledger(tmp_path: Path):
    log = tmp_path / 'run_log'
    requests = []
    results = []
    for path in all_specs():
        spec = parse_ts_spec(path)
        market_class = spec.market_classes[0]
        loaders = synthetic_loaders(spec, market_class, requests)
        results.append(run_sleeve(path, market_class.name, run_log=log, loaders=loaders))
    assert len(results) == 25
    assert all(result['status'] for result in results)

    entries = read_trials(log)
    outcomes = [e for e in entries if e.get('event') == 'outcome']
    assert {e['sleeve_id'] for e in outcomes} == {r['sleeve_id'] for r in results}

    for name, requested_start, requested_end in requests:
        assert requested_end <= parse_ts_spec(all_specs()[0]).windows.protected.start

    inputs = sorted((log / EVIDENCE_ROOT / 'indices').glob('*/dsr_inputs.parquet'),
                    key=lambda p: p.stat().st_mtime)
    matrix = pl.read_parquet(inputs[-1])
    ledger_trials = [e['sleeve_id'] for e in entries
                     if e.get('event') == 'trial_returns' and e.get('market_class') == 'indices']
    assert sorted(matrix.columns[1:]) == sorted(ledger_trials)
    assert matrix['timestamp'].n_unique() == matrix.height


def test_a_spec_runs_every_declared_class(tmp_path: Path):
    path = SPEC_DIR / 'af30_s01_buy_hold_single.yaml'
    spec = parse_ts_spec(path)
    run_dirs = []
    for market_class in spec.market_classes:
        loaders = synthetic_loaders(spec, market_class, run_dirs)
        result = run_sleeve(path, market_class.name, run_log=tmp_path / 'log', loaders=loaders)
        assert result['sleeve_id'] == spec.sleeve_id
        assert result['status']
    outcomes = [e for e in read_trials(tmp_path / 'log') if e.get('event') == 'outcome']
    assert {e['market_class'] for e in outcomes} == {'indices', 'metals', 'crypto'}


def test_metal_without_lease_is_blocked_with_a_reason(tmp_path: Path):
    path = SPEC_DIR / 'af30_s06_slow_trend_long_short.yaml'
    spec = parse_ts_spec(path)
    metals = next(c for c in spec.market_classes if c.name == 'metals')
    loaders = synthetic_loaders(spec, metals, [], products=load_products())
    result = run_sleeve(path, 'metals', run_log=tmp_path / 'log', loaders=loaders)
    assert result['status'] == 'BLOCKED_DATA'
    assert 'lease' in result['reason']
    outcome = [e for e in read_trials(tmp_path / 'log') if e.get('event') == 'outcome'][-1]
    assert outcome['status'] == 'BLOCKED_DATA'
