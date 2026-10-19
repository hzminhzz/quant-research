"""Time-series sleeve compilation on the shared expression grammar and oracle.

Per-instrument operations are applied within each symbol group. Cross-sectional
operations (`xs_rank`, `xs_mean`) are legal only when the sleeve declares
`cross_sectional: true`, and they see the declared class membership mask.
"""
from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any

import polars as pl

from src.data_vault.panel_builder import validate_panel
from src.oracle.causal_truncation import CausalTruncationOracle

from .common import QuantError, beneath, file_hash
from .feature_compiler import apply_declared_features
from .isolation import SerializedFeature, isolated_features
from .ts_spec import MarketClass, TimeSeriesSpec

CROSS_SECTIONAL_OPS = {'xs_rank', 'xs_mean'}
FORECAST_COLUMN = 'forecast'


def forecast_expression(spec: TimeSeriesSpec) -> pl.Expr:
    """Bounded projection of the declared forecast feature; null stays null."""
    scaling = spec.forecast.scaling
    value = pl.col(spec.forecast.feature)
    scaled = value / scaling.scale
    if scaling.kind == 'bounded_linear':
        bounded = (pl.when(scaled > scaling.cap).then(pl.lit(scaling.cap))
                   .when(scaled < -scaling.cap).then(pl.lit(-scaling.cap))
                   .otherwise(scaled))
    else:
        bounded = pl.lit(scaling.cap) * scaled.tanh()
    return pl.when(value.is_finite()).then(bounded).otherwise(None).alias(FORECAST_COLUMN)


def uses_cross_sectional(node: Any, depth: int = 0) -> bool:
    if depth > 60:
        raise QuantError('INVALID_SPEC', 'Feature expression is too deeply nested')
    if isinstance(node, dict):
        if node.get('op') in CROSS_SECTIONAL_OPS:
            return True
        return any(uses_cross_sectional(value, depth + 1) for value in node.values())
    if isinstance(node, list):
        return any(uses_cross_sectional(value, depth + 1) for value in node)
    return False


def declared_symbols(frame: pl.DataFrame, market_class: MarketClass) -> pl.DataFrame:
    """Keep every source row; only the declared, tradable members are eligible."""
    if 'in_pit_universe' in frame.columns:
        raise QuantError('INVALID_SPEC', 'Input panel must not pre-declare in_pit_universe')
    return frame.with_columns(
        (pl.col('is_tradable') & pl.col('symbol').is_in(market_class.symbols))
        .fill_null(False).alias('in_pit_universe'))


class TimeSeriesFeatureCompiler:
    """Declarative sleeve compiler: class membership mask, features, forecast."""

    def __init__(self, spec: TimeSeriesSpec, market_class: MarketClass):
        self.spec = spec
        self.market_class = market_class

    def __call__(self, panel: pl.DataFrame) -> pl.DataFrame:
        if not self.spec.cross_sectional:
            for feature in self.spec.features:
                if feature.expr is not None and uses_cross_sectional(feature.expr):
                    raise QuantError(
                        'INVALID_SPEC',
                        f'Feature {feature.name} uses a cross-sectional operation but '
                        'the sleeve does not declare cross_sectional: true',
                    )
        frame = declared_symbols(validate_panel(panel), self.market_class)
        frame = apply_declared_features(frame, self.spec.features)
        return frame.with_columns(forecast_expression(self.spec)).sort('symbol', 'timestamp')


def ts_feature_function(spec: TimeSeriesSpec,
                        market_class: MarketClass) -> Callable[[pl.DataFrame], pl.DataFrame]:
    artifact = spec.python_feature_artifact
    if artifact is None:
        return TimeSeriesFeatureCompiler(spec, market_class)
    path = beneath(spec._base_dir, artifact.path, must_exist=True)
    if file_hash(path) != artifact.sha256:
        raise QuantError('INVALID_EVIDENCE', 'Exported Python feature artifact changed')
    return SerializedFeature(path.read_bytes())


def compile_ts_and_verify(panel: pl.DataFrame, spec: TimeSeriesSpec,
                          market_class: MarketClass, *, isolate: bool = True):
    """Compile one class panel and prove exact prefix invariance at the cutoffs."""
    if spec.python_feature_artifact is not None and not isolate:
        raise QuantError('ISOLATION_UNAVAILABLE', 'Serialized Python features require isolation')
    artifact = spec.python_feature_artifact is not None
    function = ts_feature_function(spec, market_class)
    execute = partial(isolated_features, feature_fn=function) if isolate else function
    full = None

    def observed(frame):
        nonlocal full
        result = execute(frame)
        if artifact:
            result = result.with_columns(forecast_expression(spec))
        if frame.height == panel.height:
            full = result
        return result

    proof = CausalTruncationOracle(seed=spec.seed, checks=spec.cutoff_checks).verify(panel, observed)
    if full is None:
        raise QuantError('INVALID_CAUSALITY', 'Full-panel feature result was not produced')
    return full, proof
