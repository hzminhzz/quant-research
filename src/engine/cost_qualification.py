"""Qualification gate for running a sleeve on a price-only index or metal vault.

The v1 gate in `funnel.py` and `workbench.py` stays as it is. This is the
time-series entry point: a vault that does not declare `execution_qualified`
must refuse the run, and a price-only vault (`False`) may run only with
explicitly declared costs and a bound carry sidecar whose financing is modeled
or observed. Everything the run assumes is returned as a hashed record; nothing
is written here, so a refusal leaves no partial evidence.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import polars as pl

from .backtest_runner import NativeRun
from .common import QuantError, digest
from .ts_runner import run_native_ts
from .ts_spec import MarketClass, TimeSeriesSpec

ACCEPTED_FINANCING = ('MODELED', 'OBSERVED')


@dataclass(frozen=True)
class CostQualification:
    status: str
    spec_hash: str
    market_class: str
    carry_status: str
    costs: dict
    assumptions: tuple[str, ...]
    sha256: str

    def to_dict(self) -> dict:
        return asdict(self)


def qualify_costs(spec: TimeSeriesSpec, market_class: MarketClass, *,
                  vault_manifest: dict[str, Any] | None,
                  carry_metadata: dict[str, Any] | None = None) -> CostQualification:
    """Return a hashed assumption record or refuse with a named reason."""
    costs = spec.costs
    if not (costs.commission_bps_one_way > 0 and costs.slippage_bps_one_way > 0):
        raise QuantError('INVALID_SPEC', 'Commission and slippage must both be declared nonzero')
    if costs.spread_bps <= 0 and not costs.spread_included_in_slippage:
        raise QuantError('INVALID_SPEC', 'Spread must be declared or explicitly included in slippage')
    quality = (vault_manifest or {}).get('quality_summary', {})
    declared = quality.get('execution_qualified')
    carry_status = (carry_metadata or {}).get('status')
    if declared is True:
        status = 'EXECUTION_QUALIFIED'
        carry_status = carry_status or 'NOT_APPLIED'
    elif declared is False:
        if carry_status not in ACCEPTED_FINANCING:
            raise QuantError(
                'BLOCKED_DATA',
                f'{market_class.name} vault is price-only and financing is '
                f'{carry_status or "UNKNOWN_NOT_MODELLED"}; qualification refused',
            )
        status = 'DECLARED_ASSUMPTIONS'
    else:
        raise QuantError('BLOCKED_DATA',
                         'Vault manifest does not declare execution qualification')
    spread = (f'spread_bps={costs.spread_bps} declared'
              if costs.spread_bps > 0 else 'spread included in declared slippage')
    assumptions = (
        f'commission_bps_one_way={costs.commission_bps_one_way}: declared assumption, not venue data',
        f'slippage_bps_one_way={costs.slippage_bps_one_way}: declared assumption, not venue data',
        spread,
        f'financing={carry_status}',
        'price-only source: no certified venue spread, swap or contract identity',
        'research qualification only; deployment remains NOT_APPROVED',
    )
    record = {
        'status': status,
        'spec_hash': spec.spec_hash,
        'market_class': market_class.name,
        'carry_status': carry_status,
        'costs': costs.model_dump(mode='json'),
        'assumptions': list(assumptions),
        'source_quality': quality,
    }
    return CostQualification(status=status, spec_hash=spec.spec_hash,
                             market_class=market_class.name, carry_status=carry_status,
                             costs=costs.model_dump(mode='json'),
                             assumptions=assumptions, sha256=digest(record))


def run_qualified_ts(panel: pl.DataFrame, targets: pl.DataFrame, spec: TimeSeriesSpec,
                     market_class: MarketClass, *,
                     vault_manifest: dict[str, Any] | None,
                     carry_events: pl.DataFrame | None = None,
                     carry_metadata: dict[str, Any] | None = None) -> NativeRun:
    """Qualify first; only then construct and run the native engine."""
    qualification = qualify_costs(spec, market_class, vault_manifest=vault_manifest,
                                  carry_metadata=carry_metadata)
    result = run_native_ts(panel, targets, spec, market_class,
                           carry_events=carry_events, carry_metadata=carry_metadata)
    result.metrics['cost_qualification'] = qualification.to_dict()
    return result
