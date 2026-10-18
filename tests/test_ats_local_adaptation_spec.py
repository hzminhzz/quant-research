from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl

from src.engine.feature_compiler import FeatureCompiler
from src.engine.spec_parser import parse_spec

SPEC = Path(__file__).parents[1] / 'config/candidates/ats_crypto_xs_90d_high_anchoring_local_adaptation_20261018.yaml'
SOURCE_SHA256 = '0a64270bef0c43e4f11caeeb3c116d19205a1e52ae668c18a78479f06f4b4e6c'


def test_local_adaptation_is_labeled_and_hwa_formula_is_causal():
    spec = parse_spec(SPEC)
    assert spec.source_spec_status == 'local_adaptation'
    assert f'SOURCE_SHA256={SOURCE_SHA256}' in ' '.join(spec.assumptions)

    rows = []
    start = datetime(2020, 1, 1, tzinfo=UTC)
    for symbol, high in (('A', 101.0), ('B', 102.0), ('C', 103.0)):
        for hour in range(2165):
            rows.append({
                'timestamp': start + timedelta(hours=hour), 'symbol': symbol,
                'open': 100.0, 'high': high, 'low': 99.0, 'close': 100.0,
                'volume': 1000.0, 'carry_rate': 0.0, 'spread_bps': 0.0,
                'session_id': '24x7', 'bar_in_session': hour, 'is_tradable': True,
            })
    panel = pl.DataFrame(rows).sort('symbol', 'timestamp')
    test_spec = spec.model_copy(update={
        'universe': spec.universe.model_copy(update={'top_n': 3, 'minimum_assets': 3}),
    })
    features = FeatureCompiler(test_spec)(panel)
    last = features.filter(pl.col('timestamp') == start + timedelta(hours=2164))

    assert last['in_pit_universe'].all()
    assert last.sort('symbol')['high_watermark_ratio'].to_list() == [100 / 101, 100 / 102, 100 / 103]
    assert last.sort('symbol')['high_watermark_rank'].to_list() == [3.0, 2.0, 1.0]
