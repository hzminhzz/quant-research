"""Storage/identity adversaries; numerical Stage 1..4 integration is tested separately."""
from concurrent.futures import ThreadPoolExecutor

import polars as pl
import pytest

from src.data_vault import DataVault, PanelBuilder
from src.engine.common import (
    QuantError,
    digest,
    read_json,
    runtime_identity,
    write_json,
)
from src.engine.feature_compiler import FeatureCompiler
from src.engine.funnel import ResearchFunnel
from tests.dual_mode_fixtures import make_panel
from tests.dual_mode_fixtures import test_spec as spec_fixture


def receipts_fixture(tmp_path):
    root = tmp_path / 'vault'
    PanelBuilder(tmp_path / 'raw', root).publish(make_panel(hours=24 * 16),
                                               provenance={'scope': 'synthetic storage fixture'})
    spec = spec_fixture(root)
    output = tmp_path / 'receipts'
    output.mkdir()
    write_json(output / 'spec.json', spec.model_dump(mode='json'))
    vault = DataVault(root, run_log=tmp_path / 'logs', receipt_dir=output)
    funnel = ResearchFunnel(run_log=tmp_path / 'logs')
    code = runtime_identity()
    # These receipts exercise claim serialization, not numerical qualification.
    funnel._receipt(output, spec, vault.manifest_hash, code, 1,
                    {'status': 'PASS', 'scope': 'synthetic receipt fixture'})
    funnel._receipt(output, spec, vault.manifest_hash, code, 2,
                    {'status': 'PASS', 'checks': {'synthetic_storage_fixture': True}})
    funnel._receipt(output, spec, vault.manifest_hash, code, 3,
                    {'status': 'PASS', 'splits': {name: {'status': 'PASS', 'checks': {'synthetic_storage_fixture': True}}
                                               for name in ('train', 'validation')}})
    return spec, vault, output


def test_concurrent_holdout_reservations_have_one_winner(tmp_path):
    spec, vault, _ = receipts_fixture(tmp_path)
    def reserve(_):
        try:
            return vault.unlock_holdout(spec.candidate_id, spec.spec_hash)['claim_id']
        except QuantError as exc:
            return exc.status
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(reserve, range(4)))
    assert results.count('HOLDOUT_ALREADY_CLAIMED') == 3
    assert len([x for x in results if len(x) == 64]) == 1


def test_missing_stage_or_false_check_cannot_unlock(tmp_path):
    spec, vault, output = receipts_fixture(tmp_path)
    evidence = read_json(output / 'stage3_evidence.json')
    evidence['splits']['validation']['checks']['synthetic_storage_fixture'] = False
    write_json(output / 'stage3_evidence.json', evidence)
    with pytest.raises(QuantError, match='did not all pass'):
        vault.unlock_holdout(spec.candidate_id, spec.spec_hash)
    assert not (tmp_path / 'logs/_holdout_claims').exists()


def test_claim_is_consumed_even_if_protected_file_was_lost(tmp_path):
    spec, vault, _ = receipts_fixture(tmp_path)
    claim = vault.unlock_holdout(spec.candidate_id, spec.spec_hash)
    protected = next(e for e in vault.manifest['entries'] if e['kind'] == 'protected')
    (vault.root / protected['path']).unlink()
    with pytest.raises(FileNotFoundError):
        vault.load_holdout(claim)
    with pytest.raises(QuantError, match='already released'):
        vault.load_holdout(claim)


def test_manifest_cannot_redirect_development_read_into_protected(tmp_path):
    _, vault, _ = receipts_fixture(tmp_path)
    manifest = read_json(vault.root / 'manifest.json')
    first = next(e for e in manifest['entries'] if e['kind'] == 'development')
    heldout = next(e for e in manifest['entries'] if e['kind'] == 'protected')
    first['path'] = heldout['path']
    manifest.pop('manifest_hash')
    manifest['manifest_hash'] = digest(manifest)
    write_json(vault.root / 'manifest.json', manifest)
    altered = DataVault(vault.root)
    with pytest.raises(QuantError, match='outside its physical split'):
        altered.load()
    assert not altered.opened_files


def test_feature_yaml_has_no_eval_escape_hatch():
    spec = spec_fixture()
    feature = spec.features[1].model_copy(update={'expr': {'op': 'eval', 'args': []}})
    spec = spec.model_copy(update={'features': [spec.features[0], feature, spec.features[2]]})
    with pytest.raises(QuantError, match='Unsupported operation'):
        FeatureCompiler(spec)(make_panel(hours=20))


def test_mutated_canonical_rows_cannot_reuse_manifest_hash(tmp_path):
    _, vault, _ = receipts_fixture(tmp_path)
    first = next(e for e in vault.manifest['entries'] if e['kind'] == 'development')
    path = vault.root / first['path']
    panel = pl.read_parquet(path).with_columns((pl.col('volume') + 1).alias('volume'))
    panel.write_parquet(path)
    with pytest.raises(QuantError, match='content changed'):
        vault.load()


def test_missing_manifest_is_a_data_limitation_not_engineering_crash(tmp_path):
    with pytest.raises(QuantError) as result:
        DataVault(tmp_path / 'not-built')
    assert result.value.status == 'BLOCKED_DATA'
