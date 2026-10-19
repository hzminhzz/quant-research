"""Declarative time-series sleeve contract; v1 CandidateSpec stays frozen.

This module only defines and validates the specification. It performs no market
data access: `parse_ts_spec` reads exactly one YAML document and rejects it
before any panel, vault or engine object exists.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, PrivateAttr, field_validator, model_validator

from .common import QuantError, digest, safe_name
from .spec_parser import Costs, Feature, Model, PythonFeatureArtifact, Windows


class CarryPolicy(Model):
    """Declared carry semantics; never a zero placeholder for unknown financing."""
    mode: Literal['modeled', 'observed', 'unknown']
    curve: str | None = None
    tenor: str | None = None
    sign_convention: Literal['positive_rate_charges_longs'] = 'positive_rate_charges_longs'
    stress_carry_multiple: float = Field(default=2.0, ge=1)
    stress_curve_shift_bps: float = Field(default=100.0, ge=0)

    @model_validator(mode='after')
    def declared_source(self):
        if self.mode == 'modeled' and not (self.curve and self.tenor):
            raise ValueError('Modeled carry requires a named curve and tenor')
        if self.mode == 'unknown' and self.curve is not None:
            raise ValueError('Unknown carry cannot name a curve')
        return self


class MarketClass(Model):
    """One asset class, with its own panel, calendar and cost/carry semantics."""
    name: Literal['indices', 'metals', 'crypto']
    symbols: list[str] = Field(min_length=1)
    panel_root: str
    bar_seconds: int = Field(default=3600, ge=60)
    periods_per_year: int = Field(default=365, ge=1)
    carry: CarryPolicy = Field(default_factory=lambda: CarryPolicy(mode='unknown'))

    @field_validator('symbols')
    @classmethod
    def unique_symbols(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError('Market class symbols must be unique')
        for symbol in value:
            safe_name(symbol)
        return value

    @field_validator('panel_root')
    @classmethod
    def declared_root(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('panel_root must name a materialized vault')
        return value


class ForecastScaling(Model):
    """Bounded forecast transform: linear clip or tanh, both divided by `scale`."""
    kind: Literal['bounded_linear', 'bounded_tanh']
    scale: float = Field(gt=0)
    cap: float = Field(gt=0)


class Forecast(Model):
    """The per-instrument forecast and its bounded scaling."""
    feature: str
    horizon_bars: int = Field(default=1, ge=1)
    scaling: ForecastScaling


class RiskAllocation(Model):
    """Instrument risk budgets, scaled to the declared gross exposure."""
    method: Literal['equal_weight', 'inverse_volatility', 'forecast_weighted', 'manual'] = 'equal_weight'
    per_instrument_cap: float = Field(default=1.0, gt=0, le=1)
    gross_exposure: float = Field(default=1.0, gt=0, le=2)
    volatility_feature: str | None = None
    weights: dict[str, float] | None = None

    @model_validator(mode='after')
    def manual_weights(self):
        needs_vol = self.method in ('inverse_volatility', 'forecast_weighted')
        if needs_vol and not self.volatility_feature:
            raise ValueError(f'{self.method} allocation requires a volatility feature')
        if not needs_vol and self.volatility_feature is not None:
            raise ValueError('A volatility feature is only meaningful for volatility-weighted allocation')
        if self.method == 'manual':
            if not self.weights:
                raise ValueError('Manual risk allocation requires explicit weights')
            for symbol, weight in self.weights.items():
                safe_name(symbol)
                if not 0 < weight <= self.per_instrument_cap:
                    raise ValueError(f'Manual weight for {symbol} violates per_instrument_cap')
        elif self.weights is not None:
            raise ValueError('Explicit weights are only valid for manual allocation')
        return self


class Stops(Model):
    """Frozen protective distance: multiple x declared stop feature over price."""
    feature: str
    multiple: float = Field(gt=0)


class SleeveCosts(Costs):
    """Costs must be explicitly declared, never left as zero-shaped defaults."""
    @model_validator(mode='after')
    def nonzero(self):
        if self.commission_bps_one_way <= 0:
            raise ValueError('Commission must be declared nonzero')
        if self.slippage_bps_one_way <= 0:
            raise ValueError('Slippage must be declared nonzero')
        if self.spread_bps <= 0 and not self.spread_included_in_slippage:
            raise ValueError('Spread must be declared or explicitly included in slippage')
        return self


class SleeveGates(Model):
    """Declared qualification bar; changing one after outcomes is a new trial."""
    require_positive_train_sharpe: Literal[True] = True
    minimum_validation_net_sharpe: float = Field(default=0.30, ge=0)
    minimum_validation_to_train_ratio: float = Field(default=0.5, ge=0)
    minimum_forecast_return_t: float = Field(default=2.0)
    maximum_validation_drawdown: float = Field(default=0.25, gt=0, le=1)
    dsr_probability: float = Field(default=0.95, gt=0, lt=1)
    cost_stress_multiple: float = Field(default=2.0, ge=1)


class TimeSeriesSpec(Model):
    """Strictly additive sibling of `CandidateSpec`; selected by `spec_kind`."""
    _base_dir: Path = PrivateAttr(default_factory=Path.cwd)
    schema_version: Literal[1] = 1
    spec_kind: Literal['time_series']
    sleeve_id: str
    selection_family_id: str
    book_strategy: int = Field(ge=1, le=30)
    thesis: str
    market_classes: list[MarketClass] = Field(min_length=1)
    windows: Windows
    features: list[Feature] = Field(min_length=1)
    cross_sectional: bool = False
    forecast: Forecast
    volatility_target: float = Field(default=0.10, gt=0, le=0.5)
    risk_allocation: RiskAllocation = Field(default_factory=RiskAllocation)
    stops: Stops
    rebalance_bars: int = Field(default=1, ge=1)
    costs: SleeveCosts
    gates: SleeveGates = Field(default_factory=SleeveGates)
    label_horizon_bars: int = Field(default=1, ge=1)
    seed: int = Field(default=42, ge=0)
    cutoff_checks: int = Field(default=3, ge=3, le=1000)
    assumptions: list[str] = Field(default_factory=list)
    prior_trial_ids: list[str] = Field(default_factory=list)
    python_feature_artifact: PythonFeatureArtifact | None = None

    @field_validator('sleeve_id', 'selection_family_id')
    @classmethod
    def valid_identifier(cls, value):
        return safe_name(value)

    @field_validator('thesis')
    @classmethod
    def nonempty_thesis(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('Thesis must state the tested mechanism')
        return value

    @model_validator(mode='after')
    def surface(self):
        names = [f.name for f in self.features]
        if len(names) != len(set(names)):
            raise ValueError('Feature output names must be unique')
        if 'forecast' in names:
            raise ValueError('`forecast` is reserved for the scaled projection')
        if self.forecast.feature not in names:
            raise ValueError('Forecast must name a declared feature output')
        if self.stops.feature not in names:
            raise ValueError('Stop distance must name a declared feature output')
        vol = self.risk_allocation.volatility_feature
        if vol is not None and vol not in names:
            raise ValueError('Volatility feature must name a declared feature output')
        classes = [c.name for c in self.market_classes]
        if len(classes) != len(set(classes)):
            raise ValueError('Each market class may be declared once')
        symbols = [s for c in self.market_classes for s in c.symbols]
        if len(symbols) != len(set(symbols)):
            raise ValueError('A symbol may belong to exactly one market class')
        if self.label_horizon_bars < self.forecast.horizon_bars:
            raise ValueError('Forecast horizon cannot exceed the label horizon')
        if self.risk_allocation.method == 'manual':
            declared = set(symbols)
            if set(self.risk_allocation.weights or {}) != declared:
                raise ValueError('Manual weights must cover exactly the declared symbols')
        return self

    @property
    def spec_hash(self) -> str:
        return digest(self.model_dump(mode='json'))


def parse_ts_spec(path: str | Path) -> TimeSeriesSpec:
    try:
        with Path(path).open(encoding='utf-8') as handle:
            payload: Any = yaml.safe_load(handle)
        spec = TimeSeriesSpec.model_validate(payload)
        spec._base_dir = Path(path).resolve().parent
        return spec
    except (OSError, yaml.YAMLError, ValueError, TypeError) as exc:
        raise QuantError('INVALID_SPEC', str(exc)) from exc


def export_ts_spec(spec: TimeSeriesSpec, path: str | Path) -> Path:
    """Serialize, prove the round-trip hash, then write; never leave a bad file."""
    text = yaml.safe_dump(spec.model_dump(mode='json'), sort_keys=False)
    try:
        reparsed = TimeSeriesSpec.model_validate(yaml.safe_load(text))
    except (yaml.YAMLError, ValueError, TypeError) as exc:
        raise QuantError(
            'INVALID_SPEC', f'Export produced an unparseable specification: {exc}'
        ) from exc
    if reparsed.spec_hash != spec.spec_hash:
        raise QuantError('INVALID_SPEC', 'Export/reimport changed the time-series specification')
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding='utf-8')
    return target
