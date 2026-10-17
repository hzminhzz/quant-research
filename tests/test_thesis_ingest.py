import pytest
import yaml

from scripts.quant import main
from src.engine.common import QuantError
from src.engine.spec_parser import parse_spec
from src.engine.thesis_ingest import convert_thesis
from tests.dual_mode_fixtures import test_spec as synthetic_spec


def write_thesis(path, **fields):
    path.write_text(yaml.safe_dump(fields, sort_keys=False), encoding='utf-8')


def raw_semantic_thesis():
    spec = synthetic_spec().model_dump(mode='json')
    features = []
    for item in spec['features']:
        item = dict(item)
        if 'expr' in item:
            item['calculation'] = item.pop('expr')
        features.append(item)
    return {
        'candidate_id': spec['candidate_id'],
        'selection_family_id': spec['selection_family_id'],
        'economic_thesis': {'statement': spec['thesis']},
        'market': spec['benchmark'],
        'bar_seconds': spec['bar_seconds'],
        'data_requirements': {'panel_root': spec['panel_root']},
        'feature_contracts': features,
        'entry_and_basket_construction_rules': {
            'universe': spec['universe'], 'allocation': spec['allocation']},
        'signal': spec['signal'],
        'baseline': spec['baseline'],
        'development_evaluation': {'interval': '[start,end)', 'windows': spec['windows']},
        'cost_assumptions': spec['costs'],
        'primary_falsifier': {'gates': {'minimum_ic': spec['gates']['minimum_ic'],
                                        'minimum_hac_t': spec['gates']['minimum_hac_t']}},
        'acceptance_and_stop_rules': {'gates': {
            'minimum_ic_observations': spec['gates']['minimum_ic_observations'],
            'minimum_daily_observations': spec['gates']['minimum_daily_observations'],
            'minimum_completed_trades': spec['gates']['minimum_completed_trades']}},
    }


def test_fully_structured_semantic_mapping_converts_to_strict_candidate_yaml(tmp_path):
    source, output = tmp_path / 'thesis_candidate.yaml', tmp_path / 'candidate.yaml'
    spec = synthetic_spec().model_dump(mode='json')
    write_thesis(source, candidate_id='synthetic_funding', economic_thesis={
        'statement': 'Synthetic fixture only', 'direction': 'long_short', 'horizon_bars': 2,
        'falsifier': {'minimum_ic': 0.015, 'minimum_hac_t': 2.0}}, candidate_spec=spec)

    converted = convert_thesis(source, output)

    assert parse_spec(output).spec_hash == converted.spec_hash
    assert converted.signal == 'candidate'
    assert converted.features[1].expr['op'] == 'neg'


def test_unmapped_prose_field_has_actionable_error(tmp_path):
    source = tmp_path / 'thesis.yaml'
    write_thesis(source, candidate_spec=synthetic_spec().model_dump(mode='json'),
                 clever_formula='Buy when it feels cheap')

    with pytest.raises(QuantError, match='Unmapped thesis fields: clever_formula'):
        convert_thesis(source, tmp_path / 'out.yaml')


def test_ambiguous_thesis_without_explicit_executable_mapping_is_rejected(tmp_path):
    source = tmp_path / 'thesis.yaml'
    write_thesis(source, economic_thesis={'statement': 'Buy around an event.'},
                 strategy_rules={'entry': 'before event', 'exit': 'after event'})

    with pytest.raises(QuantError, match='Raw thesis is missing explicit fields:'):
        convert_thesis(source, tmp_path / 'out.yaml')


def test_raw_semi_structured_handoff_maps_all_explicit_semantics(tmp_path):
    source, output = tmp_path / 'thesis_candidate.yaml', tmp_path / 'candidate.yaml'
    write_thesis(source, **raw_semantic_thesis())

    converted = convert_thesis(source, output)

    assert parse_spec(output).spec_hash == converted.spec_hash
    assert converted.features[1].expr['op'] == 'neg'
    assert converted.costs.commission_bps_one_way == 0
    assert converted.windows.validation.start.isoformat().startswith('2025-12-25')


def test_raw_prose_only_choices_fail_with_all_missing_fields_and_no_output(tmp_path):
    source, output = tmp_path / 'thesis_candidate.yaml', tmp_path / 'candidate.yaml'
    fields = raw_semantic_thesis()
    fields['feature_contracts'][1] = {'name': 'candidate', 'calculation': 'momentum-like behavior'}
    write_thesis(source, **fields)

    with pytest.raises(QuantError, match=r'feature_contracts\[1\].*structured operation tree'):
        convert_thesis(source, output)
    assert not output.exists()


def test_raw_handoff_rejects_missing_market_time_and_cost_choices(tmp_path):
    source, output = tmp_path / 'thesis_candidate.yaml', tmp_path / 'candidate.yaml'
    fields = raw_semantic_thesis()
    del fields['development_evaluation']['interval']
    del fields['cost_assumptions']['commission_bps_one_way']
    write_thesis(source, **fields)

    with pytest.raises(QuantError) as error:
        convert_thesis(source, output)
    assert 'development_evaluation.interval' in str(error.value)
    assert not output.exists()


def test_ingest_cli_only_converts_and_does_not_run_research(tmp_path, capsys):
    source, output = tmp_path / 'thesis.yaml', tmp_path / 'candidate.yaml'
    write_thesis(source, candidate_spec=synthetic_spec().model_dump(mode='json'))

    assert main(['ingest', str(source), '-o', str(output)]) == 0
    assert 'CONVERTED' in capsys.readouterr().out
    assert output.exists()
