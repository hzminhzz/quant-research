from pathlib import Path

import pytest

from src.engine.common import QuantError
from src.engine.spec_parser import parse_spec
from src.oracle.research_protocols import (
    EventGates,
    PathDependentGates,
    ProtocolDescriptor,
    cross_sectional_protocol,
    describe_research_protocol,
    gates_for_protocol,
    parse_research_spec,
)

ROOT = Path(__file__).resolve().parents[1]


def test_legacy_candidate_serialization_and_hash_are_unchanged():
    path = ROOT / 'config/candidates/crypto_xs_funding_velocity_dislocation_basket_v1.example.yaml'
    legacy = parse_spec(path)
    selected = parse_research_spec(path)
    assert selected.model_dump(mode='json') == legacy.model_dump(mode='json')
    assert selected.spec_hash == legacy.spec_hash
    assert 'protocol' not in selected.model_dump(mode='json')
    assert cross_sectional_protocol().protocol == 'cross_sectional'
    assert describe_research_protocol(selected).protocol == 'cross_sectional'


def test_protocol_descriptors_keep_distinct_gate_sets():
    assert EventGates().exact_clock_and_signal
    assert not hasattr(EventGates(), 'dollar_neutrality')
    assert PathDependentGates().stop_target_semantics_qualified is False
    assert ProtocolDescriptor(protocol='path_dependent').protocol == 'path_dependent'
    assert gates_for_protocol(ProtocolDescriptor(protocol='path_dependent')).stop_target_semantics_qualified is False


@pytest.mark.parametrize('payload', [
    'protocol: surprise\nstrategy_id: m8_n8_cash_session_v7\n',
    'protocol: event\nstrategy_id: another_strategy\n',
    'protocol: event\nstrategy_id: m8_n8_cash_session_v7\ncommission_bps: 0\n',
    'protocol: path_dependent\nstrategy_id: m8_n8_cash_session_v7\n',
])
def test_unknown_protocol_strategy_or_override_fails_closed(tmp_path, payload):
    path = tmp_path / 'spec.yaml'
    path.write_text(payload)
    with pytest.raises((QuantError, ValueError)):
        parse_research_spec(path)


def test_event_config_is_explicit_strict_and_hash_stable():
    path = ROOT / 'config/candidates/ats4_m8_n8_cash.yaml'
    spec = parse_research_spec(path)
    assert spec.protocol == 'event'
    assert spec.strategy_id == 'm8_n8_cash_session_v7'
    assert spec.spec_hash == parse_research_spec(path).spec_hash


def test_typed_event_specs_are_revalidated_and_forged_updates_fail_closed():
    spec = parse_research_spec(ROOT / 'config/candidates/ats4_m8_n8_cash.yaml')
    assert parse_research_spec(spec) == spec
    for forged in (
        spec.model_copy(update={'strategy_id': 'unapproved'}),
        spec.model_copy(update={'commission_bps': 0}),
        type(spec).model_construct(protocol='surprise', strategy_id=spec.strategy_id),
    ):
        with pytest.raises(QuantError) as error:
            parse_research_spec(forged)
        assert error.value.status == 'INVALID_SPEC'
