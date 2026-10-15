"""Typed executable YAML. Narrative requirements are never silently compiled."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    field_validator,
    model_validator,
)

from .common import QuantError, digest, safe_name, utc


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Window(Model):
    start: datetime
    end: datetime

    @field_validator('start', 'end', mode='before')
    @classmethod
    def normalize(cls, value: Any) -> datetime:
        return utc(value)

    @model_validator(mode='after')
    def ordered(self):
        if self.start >= self.end:
            raise ValueError('Windows are half-open [start,end), with start < end')
        return self


class Windows(Model):
    train: Window
    validation: Window
    protected: Window

    @model_validator(mode='after')
    def chronological(self):
        if self.train.end > self.validation.start or self.validation.end > self.protected.start:
            raise ValueError('Train, validation and protected windows must not overlap')
        return self


class Feature(Model):
    name: str
    native: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    expr: dict[str, Any] | None = None
    native_status: str | None = None  # descriptive, never a name-based execution veto

    @field_validator('name')
    @classmethod
    def valid_name(cls, value):
        return safe_name(value)

    @model_validator(mode='after')
    def one_implementation(self):
        if (self.native is None) == (self.expr is None):
            raise ValueError('A feature declares exactly one native primitive or Polars expression')
        return self


class Universe(Model):
    top_n: int = Field(default=40, ge=2, le=5000)
    lookback_bars: int = Field(default=720, ge=1)
    minimum_assets: int = Field(default=40, ge=2)
    minimum_history_bars: int = Field(default=720, ge=1)
    minimum_dollar_volume: float = Field(default=0, ge=0)

    @model_validator(mode='after')
    def bounds(self):
        if self.minimum_assets > self.top_n:
            raise ValueError('minimum_assets must be <= top_n')
        return self


class Allocation(Model):
    long_count: int = Field(default=5, ge=1)
    short_count: int = Field(default=5, ge=1)
    gross_exposure: float = Field(default=1.0, gt=0, le=2)
    rebalance_bars: int = Field(default=48, ge=1)
    atr_feature: str = 'atr_24h'
    atr_multiple: float = Field(default=3.0, gt=0)
    netting_rule: Literal['weight_delta'] = 'weight_delta'
    timing_lag: Literal[1] = 1


class Costs(Model):
    commission_bps_one_way: float = Field(default=5, ge=0, le=1000)
    slippage_bps_one_way: float = Field(default=4, ge=0, le=1000)
    spread_bps: float = Field(default=0, ge=0, le=1000)
    spread_included_in_slippage: bool = True


class Gates(Model):
    minimum_ic: float = Field(default=0.015, ge=-1, le=1)
    minimum_hac_t: float = 2.0
    minimum_ic_observations: int = Field(default=30, ge=3)
    require_baseline_ic_improvement: bool = True
    dsr_probability: float = Field(default=0.95, gt=0, lt=1)
    maximum_abs_beta: float = Field(default=0.15, ge=0)
    maximum_short_stop_fraction: float = Field(default=0.20, ge=0, le=1)
    minimum_completed_trades: int = Field(default=10, ge=1)
    require_baseline_sharpe_improvement: bool = True
    minimum_daily_observations: int = Field(default=60, ge=10)


class PythonFeatureArtifact(Model):
    path: str
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class CandidateSpec(Model):
    _base_dir: Path = PrivateAttr(default_factory=Path.cwd)
    schema_version: Literal[1] = 1
    candidate_id: str
    selection_family_id: str
    source_spec_status: Literal['exact', 'prompt_derived_example', 'synthetic_test'] = 'exact'
    thesis: str
    panel_root: str
    windows: Windows
    features: list[Feature]
    signal: str
    baseline: str
    universe: Universe = Field(default_factory=Universe)
    allocation: Allocation = Field(default_factory=Allocation)
    costs: Costs = Field(default_factory=Costs)
    gates: Gates = Field(default_factory=Gates)
    label_horizon_bars: int = Field(default=48, ge=1)
    bar_seconds: int = Field(default=3600, ge=60)
    periods_per_year: int = Field(default=365, ge=1)
    benchmark: str = 'BTCUSDT_PERP'
    initial_cash: float = Field(default=100000, gt=0)
    seed: int = Field(default=42, ge=0)
    cutoff_checks: int = Field(default=3, ge=3, le=1000)
    assumptions: list[str] = Field(default_factory=list)
    prior_trial_ids: list[str] = Field(default_factory=list)
    python_feature_artifact: PythonFeatureArtifact | None = None

    @field_validator('candidate_id', 'selection_family_id')
    @classmethod
    def valid_identifier(cls, value):
        return safe_name(value)

    @model_validator(mode='after')
    def feature_surface(self):
        names = [f.name for f in self.features]
        if len(names) != len(set(names)):
            raise ValueError('Feature output names must be unique')
        if any(name not in names for name in (self.signal, self.baseline, self.allocation.atr_feature)):
            raise ValueError('Signal, baseline and ATR must name declared feature outputs')
        if self.signal == self.baseline:
            raise ValueError('Candidate and baseline must be distinct declared features')
        if self.universe.minimum_assets < self.allocation.long_count + self.allocation.short_count:
            raise ValueError('Universe must support disjoint long and short baskets')
        return self

    @property
    def spec_hash(self) -> str:
        return digest(self.model_dump(mode='json'))


def parse_spec(path: str | Path) -> CandidateSpec:
    try:
        with Path(path).open(encoding='utf-8') as handle:
            payload = yaml.safe_load(handle)
        spec = CandidateSpec.model_validate(payload)
        spec._base_dir = Path(path).resolve().parent
        return spec
    except (OSError, yaml.YAMLError, ValueError, TypeError) as exc:
        raise QuantError('INVALID_SPEC', str(exc)) from exc


def export_spec(spec: CandidateSpec, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Preserve canonical explicit exclusive endpoints on every export.
    target.write_text(yaml.safe_dump(spec.model_dump(mode='json'), sort_keys=False), encoding='utf-8')
    if parse_spec(target).spec_hash != spec.spec_hash:
        raise QuantError('INVALID_SPEC', 'Export/reimport changed the specification')
    return target
