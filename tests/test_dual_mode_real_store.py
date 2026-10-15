"""Explicit seven-day 2025 runtime regression, never a strategy qualification."""
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.data_vault import DataVault
from src.engine.backtest_runner import run_native
from src.engine.common import runtime_identity, write_json
from src.engine.feature_compiler import FeatureCompiler
from src.engine.spec_parser import CandidateSpec
from src.oracle.causal_truncation import CausalTruncationOracle
from tests.dual_mode_fixtures import manual_targets
from tests.dual_mode_fixtures import test_spec as spec_fixture


@pytest.mark.data
def test_real_btc_eth_development_only_native_smoke():
    root = Path(__file__).resolve().parents[1]
    panel_root = root / 'data/vault/runtime_smoke_20261015_v2'
    if not (panel_root / 'manifest.json').exists():
        pytest.skip('Run the explicit 2025 BTC/ETH canonical build first')
    vault = DataVault(panel_root)
    panel = vault.load('2025-01-01', '2025-01-08')
    funding = vault.load_funding('2025-01-01', '2025-01-08')
    assert panel.height == 336 and panel['symbol'].n_unique() == 2
    assert funding.height == 42
    assert panel['is_tradable'].all()
    assert panel['timestamp'].max() < datetime(2026, 1, 1, tzinfo=UTC)
    raw = spec_fixture(panel_root, start=datetime(2025, 1, 1, tzinfo=UTC)).model_dump(mode='json')
    raw['universe'] = {'top_n': 2, 'minimum_assets': 2, 'lookback_bars': 24, 'minimum_history_bars': 24}
    raw['costs'] = {'commission_bps_one_way': 5., 'slippage_bps_one_way': 4.}
    spec = CandidateSpec.model_validate(raw)
    proof = CausalTruncationOracle(seed=42).verify(panel, FeatureCompiler(spec))
    native = run_native(panel, manual_targets(panel, when=(25,)), spec, funding=funding)
    assert native.metrics['independent_accounting']['status'] == 'PASS'
    assert all(r['available_at'] == r['fill_at'] for r in native.timing)
    assert len(vault.opened_files) == 4
    assert all('/development/' in p for p in vault.opened_files)
    output = root / 'run_log/dual_mode_runtime_smoke' / datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')
    output.mkdir(parents=True)
    native.fills.write_parquet(output / 'fills.parquet')
    native.funding.write_parquet(output / 'funding.parquet')
    native.equity.write_parquet(output / 'equity.parquet')
    write_json(output / 'verification.json', {
        'status': 'PASS', 'purpose': 'historical runtime regression, not alpha research or promotion',
        'code_hash': runtime_identity(), 'panel_hash': vault.manifest_hash,
        'window': ['2025-01-01', '2025-01-08'], 'bar_rows': panel.height,
        'funding_events': funding.height, 'source_symbols': panel['symbol'].unique().sort().to_list(),
        'causality': proof.to_dict(), 'accounting': native.metrics['independent_accounting'],
        'native_fill_count': native.fills.height, 'holdout_access': False,
        'costs_bps_one_way': {'commission': 5, 'slippage': 4},
        'funding_mark_policy': 'trade_open_proxy; historical settlement mark unavailable in this slice',
        'funding_boundary_policy': 'source-event millisecond jitter retained in sidecar; modeled pre-open settlement within 1000ms tolerance',
    })
    print('runtime_smoke_artifact=' + str(output / 'verification.json'))
