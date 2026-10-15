"""Real native integration and adversarial tests for the dual-mode runtime."""
import polars as pl
import pytest

from src.data_vault import DataVault, PanelBuilder
from src.engine.backtest_runner import run_native
from src.engine.common import QuantError
from src.engine.feature_compiler import FeatureCompiler
from src.engine.signal_allocator import allocate
from src.oracle.causal_truncation import CausalTruncationOracle
from src.oracle.stage2_diagnostic import stage2
from tests.dual_mode_fixtures import make_panel, manual_targets, zero_carry
from tests.dual_mode_fixtures import test_spec as spec_fixture


def test_native_features_custom_expression_and_exact_prefixes():
    panel = make_panel(hours=80, dynamic=True)
    spec = spec_fixture()
    compiler = FeatureCompiler(spec)
    features = compiler(panel)
    assert {'atr_24h', 'candidate', 'baseline', 'in_pit_universe'} <= set(features.columns)
    assert features['in_pit_universe'].sum() > 0
    proof = CausalTruncationOracle(seed=8).verify(panel, compiler)
    assert proof.status == 'PASS' and len(proof.cutoffs) == 3
    shuffled = compiler(panel.sample(fraction=1., shuffle=True, seed=8))
    assert features.equals(shuffled)
    targets = allocate(features, spec)
    assert targets.group_by('timestamp').agg(pl.col('target_weight').sum())['target_weight'].abs().max() < 1e-12


def test_unrepresentable_three_atr_long_stop_is_excluded_before_rank():
    panel = make_panel(hours=80, dynamic=True)
    original = spec_fixture()
    spec = original.model_copy(update={
        'universe': original.universe.model_copy(update={'minimum_assets': 2}),
    })
    features = FeatureCompiler(spec)(panel)
    # This asset's stop would be at or below zero for a long entry.
    features = features.with_columns(
        pl.when(pl.col('symbol') == 'A_PERP').then(pl.col('close'))
        .otherwise(pl.col('atr_24h')).alias('atr_24h'))
    targets = allocate(features, spec)
    invalid = targets.filter(pl.col('symbol') == 'A_PERP')
    assert invalid.height > 0
    assert invalid['target_weight'].abs().max() == 0
    assert targets['target_weight'].abs().sum() > 0
    assert targets.group_by('timestamp').agg(pl.col('target_weight').sum())['target_weight'].abs().max() < 1e-12


@pytest.mark.parametrize('leak', ['negative_shift', 'global_normalization', 'future_membership'])
def test_causal_oracle_rejects_future_dependence(leak):
    panel = make_panel(hours=40, dynamic=True)
    compiler = FeatureCompiler(spec_fixture())
    def bad(source):
        out = compiler(source)
        if leak == 'negative_shift':
            return out.with_columns(pl.col('close').shift(-1).over('symbol').alias('candidate'))
        if leak == 'global_normalization':
            return out.with_columns((pl.col('close') / pl.col('close').max().over('symbol')).alias('candidate'))
        return out.with_columns((pl.col('timestamp').max().over('symbol') == panel['timestamp'].max()).alias('in_pit_universe'))
    with pytest.raises(QuantError, match='Prefix changed'):
        CausalTruncationOracle(seed=9).verify(panel, bad)


def test_vault_never_opens_protected_partition(tmp_path):
    panel = make_panel(hours=24 * 16)
    builder = PanelBuilder(tmp_path / 'raw', tmp_path / 'vault')
    builder.publish(panel, provenance={'source_spec_status': 'synthetic_test'})
    vault = DataVault(tmp_path / 'vault', run_log=tmp_path / 'logs')
    loaded = vault.load(end='2026-10-01')
    assert loaded['timestamp'].max() < vault.protected_test_start
    assert all('/development/' in path for path in vault.opened_files)
    assert vault.load(start='2026-01-01').is_empty()
    with pytest.raises(QuantError, match='Workbench'):
        vault.unlock_holdout('synthetic_funding', 'a' * 64)


def test_native_next_open_netting_and_flat_end():
    panel = zero_carry(make_panel(hours=24 * 4))
    spec = spec_fixture()
    result = run_native(panel, manual_targets(panel, when=(1, 25, 49)), spec)
    assert result.metrics['fill_count'] == 4
    assert result.metrics['completed_trades'] == 2
    assert result.metrics['final_equity'] == pytest.approx(spec.initial_cash)
    assert all(row['available_at'] == row['fill_at'] for row in result.timing)


def test_native_settlement_charges_prior_holders_once():
    panel = zero_carry(make_panel(hours=24 * 4))
    spec = spec_fixture()
    times = panel['timestamp'].unique().sort().to_list()
    events = pl.DataFrame([{'timestamp': times[index], 'symbol': symbol,
                           'funding_rate': .001, 'mark_price': mark}
                          for index in (2, 8, 16)
                          for symbol, mark in [('BTCUSDT_PERP', 100.), ('ETHUSDT_PERP', 120.)]])
    result = run_native(panel, manual_targets(panel), spec, funding=events)
    assert result.funding.filter(pl.col('timestamp') == times[2])['cashflow'].sum() == 0
    late = result.funding.filter(pl.col('timestamp') > times[2])
    assert late.filter(pl.col('symbol') == 'BTCUSDT_PERP')['cashflow'].sum() == pytest.approx(-100.)
    assert late.filter(pl.col('symbol') == 'ETHUSDT_PERP')['cashflow'].sum() == pytest.approx(100.)
    assert result.metrics['final_equity'] == pytest.approx(spec.initial_cash)


def test_native_entry_bar_stop_is_active_and_fixed():
    panel = zero_carry(make_panel(hours=60))
    times = panel['timestamp'].unique().sort().to_list()
    panel = panel.with_columns(pl.when((pl.col('symbol') == 'ETHUSDT_PERP') & (pl.col('timestamp') == times[2]))
                              .then(132.).otherwise(pl.col('high')).alias('high'))
    result = run_native(panel, manual_targets(panel), spec_fixture())
    assert result.metrics['short_entries'] == 1
    assert result.metrics['short_stops'] == 1
    assert result.metrics['final_equity'] == pytest.approx(97500.)


def test_native_diagnostic_constant_baseline_does_not_pass():
    panel = make_panel(hours=240)
    features = FeatureCompiler(spec_fixture())(panel)
    report, _ic = stage2(features, spec_fixture())
    assert report['status'] in ('FALSIFIED_STAGE_2', 'INCONCLUSIVE_STAGE_2')
