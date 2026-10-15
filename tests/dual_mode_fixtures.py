"""Explicitly synthetic dual-mode fixtures; no historical data or market claim."""
from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl

from src.data_vault.panel_builder import CANONICAL_COLUMNS, SCHEMA
from src.engine.spec_parser import CandidateSpec


def make_panel(hours=240, symbols=('BTCUSDT_PERP', 'ETHUSDT_PERP', 'A_PERP', 'B_PERP'),
               start=datetime(2025, 12, 20, tzinfo=UTC), dynamic=False):
    rng = np.random.default_rng(174)
    records = []
    for i, symbol in enumerate(symbols):
        price = 100.0 + i * 20
        prior_pressure = 0.0
        for hour in range(hours):
            timestamp = start + timedelta(hours=hour)
            opening = price
            pressure = float(rng.normal())
            price = opening * (1 + (0.001 * prior_pressure + rng.normal(0, .00015) if dynamic else 0))
            records.append({'timestamp': timestamp, 'symbol': symbol, 'open': opening,
                            'high': max(price, opening) * 1.002, 'low': min(price, opening) * .998,
                            'close': price, 'volume': 1000. + i,
                            'carry_rate': pressure * .0001 if hour % 8 == 0 else 0.,
                            'spread_bps': 0., 'session_id': timestamp.strftime('%Y-%m-%d'),
                            'bar_in_session': hour % 24, 'is_tradable': True})
            prior_pressure = pressure
    return pl.DataFrame(records, schema=SCHEMA).select(CANONICAL_COLUMNS).sort('symbol', 'timestamp')


def test_spec(panel_root='unused', start=datetime(2025, 12, 20, tzinfo=UTC)):
    return CandidateSpec.model_validate({
        'candidate_id': 'synthetic_funding', 'selection_family_id': 'synthetic-family',
        'source_spec_status': 'synthetic_test', 'thesis': 'Synthetic integration fixture, not a market thesis.',
        'panel_root': str(panel_root),
        'windows': {'train': {'start': start.isoformat(), 'end': (start + timedelta(days=5)).isoformat()},
                    'validation': {'start': (start + timedelta(days=5)).isoformat(),
                                   'end': '2026-01-01T00:00:00Z'},
                    'protected': {'start': '2026-01-01T00:00:00Z', 'end': '2026-01-04T00:00:00Z'}},
        'features': [
            {'name': 'atr_24h', 'native': 'atr', 'params': {'period': 3}},
            {'name': 'candidate', 'native_status': 'EXTENSION_REQUIRED',
             'expr': {'op': 'neg', 'args': [{'op': 'rolling_sum', 'window': 8,
                                          'args': [{'op': 'col', 'name': 'carry_rate'}]}]}},
            {'name': 'baseline', 'expr': {'op': 'pct_change', 'periods': 2,
                                        'args': [{'op': 'col', 'name': 'close'}]}}],
        'signal': 'candidate', 'baseline': 'baseline',
        'universe': {'top_n': 4, 'minimum_assets': 4, 'lookback_bars': 3, 'minimum_history_bars': 3},
        'allocation': {'long_count': 1, 'short_count': 1, 'rebalance_bars': 24,
                       'atr_feature': 'atr_24h', 'atr_multiple': 3},
        'costs': {'commission_bps_one_way': 0, 'slippage_bps_one_way': 0},
        'gates': {'minimum_ic_observations': 3, 'minimum_daily_observations': 10,
                  'minimum_completed_trades': 1},
        'label_horizon_bars': 2,
    })


def manual_targets(panel, *, when=(1,), weights=None, distance=.05):
    weights = weights or {'BTCUSDT_PERP': .5, 'ETHUSDT_PERP': -.5}
    times = panel['timestamp'].unique().sort().to_list()
    return pl.DataFrame([{'timestamp': times[i], 'symbol': symbol, 'target_weight': weight,
                         'stop_loss_dist_pct': distance if weight else 0.}
                        for i in when for symbol, weight in weights.items()],
                       schema={'timestamp': pl.Datetime('us', 'UTC'), 'symbol': pl.String,
                               'target_weight': pl.Float64, 'stop_loss_dist_pct': pl.Float64})


def zero_carry(panel):
    return panel.with_columns(pl.lit(0.).alias('carry_rate'))
