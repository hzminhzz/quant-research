"""Typed scientific protocols; CandidateSpec remains the frozen XS contract."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict


class ProtocolDescriptor(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    protocol: Literal['cross_sectional', 'event', 'path_dependent']


@dataclass(frozen=True)
class CrossSectionalGates:
    feature_causality: bool = True
    train_only_ic_hac: bool = True
    baseline_increment: bool = True
    dollar_neutrality: bool = True
    aligned_selection_dsr: bool = True
    daily_net_beta: bool = True
    short_stop_fraction: bool = True


@dataclass(frozen=True)
class EventGates:
    exact_clock_and_signal: bool = True
    full_expected_order_sequence: bool = True
    native_fill_and_cash_reconciliation: bool = True
    cost_status: Literal['qualified', 'assumed', 'missing'] = 'missing'
    mark_status: Literal['qualified', 'daily_only', 'missing'] = 'missing'


@dataclass(frozen=True)
class PathDependentGates:
    causal_state_transitions: bool = True
    native_execution_reconciliation: bool = True
    stop_target_semantics_qualified: bool = False
    intraday_marks_qualified: bool = False


type ScientificProtocol = CrossSectionalGates | EventGates | PathDependentGates


def cross_sectional_protocol() -> ProtocolDescriptor:
    """Legacy CandidateSpec payloads select this without changing their hash."""
    return ProtocolDescriptor(protocol='cross_sectional')


def describe_research_protocol(spec) -> ProtocolDescriptor:
    """Legacy specs default to cross-sectional without gaining a serialized field."""
    return ProtocolDescriptor(protocol=getattr(spec, 'protocol', 'cross_sectional'))


def gates_for_protocol(protocol: ProtocolDescriptor, **overrides) -> ScientificProtocol:
    gate_type = {
        'cross_sectional': CrossSectionalGates,
        'event': EventGates,
        'path_dependent': PathDependentGates,
    }[protocol.protocol]
    return gate_type(**overrides)


def parse_research_spec(source):
    """Select the strict sibling event schema only when an explicit discriminator exists."""
    from src.engine.spec_parser import CandidateSpec, parse_spec

    if isinstance(source, CandidateSpec):
        return source
    if not isinstance(source, (str, Path)):
        from src.engine.event_protocol import (
            BtaNqMondayEventSpec,
            M8N8EventSpec,
            validate_event_spec,
        )
        if isinstance(source, (M8N8EventSpec, BtaNqMondayEventSpec)):
            return validate_event_spec(source)
        from src.engine.common import QuantError
        raise QuantError('INVALID_SPEC', f'Unsupported specification object: {type(source).__name__}')
    path = Path(source)
    try:
        payload = yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError, yaml.YAMLError) as exc:
        from src.engine.common import QuantError
        raise QuantError('INVALID_SPEC', str(exc)) from exc
    if isinstance(payload, dict) and 'protocol' in payload:
        from src.engine.event_protocol import parse_event_spec
        return parse_event_spec(path)
    return parse_spec(path)
