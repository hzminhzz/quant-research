"""Source-bound 2026-10-22 development adaptations: provenance and formula wiring.

These tests read no market data. They pin the immutable source hashes, the declared
window/clock contract, and the two formula chains whose algebra is not trivially
visible from the YAML (variance ratio denominator floor and downside/upside Amihud
asymmetry), plus exact prefix invariance on a synthetic panel.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from src.engine.feature_compiler import FeatureCompiler
from src.engine.spec_parser import parse_spec

ROOT = Path(__file__).parents[1]
CANDIDATES = ROOT / 'config/candidates'

ADAPTATIONS = {
    'crypto_xs_variance_ratio_basket_v1_dev_adaptation_20261022.yaml': (
        'crypto_xs_variance_ratio_basket_v1',
        '9469e931cdab9487560951d9799e71dcd3286966874d35d4f89a9c94e974e15e',
        'variance_ratio_24',
    ),
    'crypto_xs_volume_return_correlation_basket_v1_dev_adaptation_20261022.yaml': (
        'crypto_xs_volume_return_correlation_basket_v1',
        'f3f8935f36a381b147efb65077495954a728b1c010e454888e9fee029edffae8',
        'volume_return_correlation_336h',
    ),
    'crypto_xs_amihud_asymmetry_basket_v1_dev_adaptation_20261022.yaml': (
        'crypto_xs_amihud_asymmetry_basket_v1',
        '52810af61b6c1e729d34ed7bbc0eb162074e7fb44680959d334795c5b61a8fe3',
        'amihud_downside_asymmetry_168h',
    ),
}


def _synthetic_panel(symbols=('AAA_PERP', 'BBB_PERP', 'CCC_PERP'), bars=900):
    start = datetime(2020, 4, 1, tzinfo=UTC)
    rows = []
    for offset, symbol in enumerate(symbols):
        level = 100.0 + 10 * offset
        for hour in range(bars):
            # Deterministic, non-degenerate path: alternating drift plus a slow cycle.
            step = 0.004 * ((hour * (offset + 3)) % 7 - 3) / 3 + 0.001 * ((hour // 11) % 5 - 2)
            open_ = level
            close = level * (1 + step)
            high = max(open_, close) * 1.001
            low = min(open_, close) * 0.999
            rows.append({
                'timestamp': start + timedelta(hours=hour), 'symbol': symbol,
                'open': open_, 'high': high, 'low': low, 'close': close,
                'volume': 1_000_000.0 + 10_000.0 * ((hour * (offset + 2)) % 23),
                'carry_rate': 0.0, 'spread_bps': 0.0,
                'session_id': '24x7', 'bar_in_session': hour, 'is_tradable': True,
            })
            level = close
    return pl.DataFrame(rows).sort('symbol', 'timestamp'), start


def _small_universe(spec):
    return spec.model_copy(update={
        'universe': spec.universe.model_copy(update={
            'top_n': 3, 'minimum_assets': 3,
            'lookback_bars': 168, 'minimum_history_bars': 168,
        }),
    })


@pytest.mark.parametrize('filename', sorted(ADAPTATIONS))
def test_adaptation_is_source_bound_and_development_only(filename):
    source_dir, source_sha, signal = ADAPTATIONS[filename]
    source = ROOT / 'research_inbox' / source_dir / 'thesis.yaml'
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    assert digest == source_sha, 'immutable source thesis changed'

    spec = parse_spec(CANDIDATES / filename)
    assumptions = ' '.join(spec.assumptions)
    assert spec.source_spec_status == 'local_adaptation'
    assert f'SOURCE_ID=research_inbox/{source_dir}/thesis.yaml' in assumptions
    assert f'SHA256={source_sha}' in assumptions
    assert spec.signal == signal
    assert spec.baseline != spec.signal
    # 00:00 decision bar fills at the next bar open; the source's same-bar 00:01
    # clock must not reappear.
    assert spec.allocation.timing_lag == 1
    assert spec.bar_seconds == 3600
    assert spec.allocation.rebalance_bars == 72
    assert spec.label_horizon_bars == 72
    # Protected evaluation must start exactly at the canonical cutoff and end within
    # the declared protected window; train/validation stop before it.
    assert spec.windows.validation.end == datetime(2026, 1, 1, tzinfo=UTC)
    assert spec.windows.protected.start == datetime(2026, 1, 1, tzinfo=UTC)
    # One-way costs stay explicit and spread is not double charged.
    assert spec.costs.spread_included_in_slippage is True
    assert spec.costs.commission_bps_one_way == 5.0
    assert spec.costs.slippage_bps_one_way == 4.0


def test_variance_ratio_matches_its_declared_algebra_and_is_prefix_invariant():
    spec = _small_universe(parse_spec(
        CANDIDATES / 'crypto_xs_variance_ratio_basket_v1_dev_adaptation_20261022.yaml'))
    panel, start = _synthetic_panel()
    features = FeatureCompiler(spec)(panel)

    recomputed = (features.with_columns(
        pl.col('close').pct_change(1).over('symbol').alias('_r1'),
        pl.col('close').pct_change(24).over('symbol').alias('_r24'),
    ).with_columns(
        (pl.col('_r1').rolling_std(336, min_samples=336).over('symbol') ** 2).alias('_v1'),
        (pl.col('_r24').rolling_std(336, min_samples=336).over('symbol') ** 2).alias('_v24'),
    ))
    expected = recomputed.select(
        (pl.col('_v24') / pl.max_horizontal(pl.col('_v1') * 24.0, pl.lit(1e-8))).alias('_expected'),
        pl.col('variance_ratio_24'), pl.col('timestamp'), pl.col('symbol'),
    ).filter(pl.col('variance_ratio_24').is_not_null() & pl.col('_expected').is_not_null())
    assert expected.height > 0
    assert expected.select(
        (pl.col('variance_ratio_24') - pl.col('_expected')).abs().max()).item() < 1e-12

    cutoff = start + timedelta(hours=760)
    truncated = FeatureCompiler(spec)(panel.filter(pl.col('timestamp') <= cutoff))
    full_at_cutoff = features.filter(pl.col('timestamp') == cutoff).sort('symbol')
    cut_at_cutoff = truncated.filter(pl.col('timestamp') == cutoff).sort('symbol')
    assert full_at_cutoff['symbol'].to_list() == cut_at_cutoff['symbol'].to_list()
    assert full_at_cutoff['variance_ratio_24'].to_list() == cut_at_cutoff['variance_ratio_24'].to_list()


def test_amihud_asymmetry_ranks_thin_downside_impact_higher():
    """Same return path, thinner sell-side notional: only that symbol gains asymmetry."""
    spec = _small_universe(parse_spec(
        CANDIDATES / 'crypto_xs_amihud_asymmetry_basket_v1_dev_adaptation_20261022.yaml'))
    start = datetime(2020, 4, 1, tzinfo=UTC)
    rows = []
    for symbol, down_volume in (('ASYM_PERP', 1.0e5), ('FLAT_PERP', 1.0e8)):
        level = 100.0
        for hour in range(600):
            down = hour % 2 == 0
            # Multiplicatively symmetric so the level does not drift below the
            # dollar-volume floor over 600 bars.
            close = level * (0.95 if down else 1.0 / 0.95)
            volume = down_volume if down else 1.0e8
            rows.append({
                'timestamp': start + timedelta(hours=hour), 'symbol': symbol,
                'open': level, 'high': max(level, close), 'low': min(level, close),
                'close': close, 'volume': volume, 'carry_rate': 0.0, 'spread_bps': 0.0,
                'session_id': '24x7', 'bar_in_session': hour, 'is_tradable': True,
            })
            level = close
    features = FeatureCompiler(spec)(pl.DataFrame(rows).sort('symbol', 'timestamp'))
    last = features.filter(pl.col('timestamp') == start + timedelta(hours=599)).sort('symbol')

    assert last['symbol'].to_list() == ['ASYM_PERP', 'FLAT_PERP']
    asym, flat = last['amihud_downside_asymmetry_168h'].to_list()
    assert asym > 0 and flat > 0
    # Identical return pattern; ASYM pays 1000x less notional on down bars only, so
    # its down/up impact ratio is exactly 1000x the symmetric symbol's ratio.
    assert asym / flat == pytest.approx(1.0e3, rel=1e-6)
