"""Native Engineer plus an allowlisted Polars expression tree; never eval YAML."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import polars as pl
from ml4t.engineer import compute_features

from src.data_vault.panel_builder import CANONICAL_COLUMNS, validate_panel

from .common import QuantError
from .spec_parser import CandidateSpec


def point_in_time_universe(panel: pl.DataFrame, spec: CandidateSpec) -> pl.DataFrame:
    frame = validate_panel(panel)
    u, step = spec.universe, spec.bar_seconds
    frame = frame.with_columns((pl.col('close') * pl.col('volume')).alias('__dollar_volume'))
    frame = frame.with_columns(
        pl.col('__dollar_volume').rolling_mean(u.lookback_bars, min_samples=u.lookback_bars)
        .over('symbol').alias('__liquidity'),
        pl.col('is_tradable').cast(pl.Int32).rolling_sum(u.lookback_bars, min_samples=u.lookback_bars)
        .over('symbol').alias('__valid'),
        pl.col('timestamp').shift(u.lookback_bars - 1).over('symbol').alias('__first'),
        pl.col('timestamp').cum_count().over('symbol').alias('__age'))
    frame = frame.with_columns(
        (pl.col('is_tradable') & (pl.col('__valid') == u.lookback_bars)
         & (pl.col('__age') >= u.minimum_history_bars)
         & (pl.col('__liquidity') >= u.minimum_dollar_volume)
         & ((pl.col('timestamp') - pl.col('__first')) == timedelta(seconds=(u.lookback_bars - 1) * step)))
        .fill_null(False).alias('__eligible'))
    frame = frame.with_columns(pl.when(pl.col('__eligible')).then(pl.col('__liquidity')).otherwise(None).alias('__sort'))
    frame = frame.sort(['timestamp', '__sort', 'symbol'], descending=[False, True, False], nulls_last=True)
    frame = frame.with_columns(pl.col('__eligible').cast(pl.Int32).cum_sum().over('timestamp').alias('__rank'),
                               pl.col('__eligible').sum().over('timestamp').alias('__breadth'))
    frame = frame.with_columns((pl.col('__eligible') & (pl.col('__rank') <= u.top_n)
                                 & (pl.col('__breadth') >= u.minimum_assets)).alias('in_pit_universe'))
    return frame.select(*CANONICAL_COLUMNS, 'in_pit_universe').sort('symbol', 'timestamp')


def compile_and_verify(panel: pl.DataFrame, spec: CandidateSpec, *, isolate: bool = True):
    """Shared runtime gate for factory, Workbench and the legacy gateway adapter."""
    from functools import partial

    from src.oracle.causal_truncation import CausalTruncationOracle

    from .isolation import feature_function, isolated_features
    if spec.python_feature_artifact is not None and not isolate:
        raise QuantError('ISOLATION_UNAVAILABLE', 'Serialized Python features require isolation')
    function = feature_function(spec)
    execute = partial(isolated_features, feature_fn=function) if isolate else function
    full = None
    def observed(frame):
        nonlocal full
        result = execute(frame)
        if frame.height == panel.height:
            full = result
        return result
    proof = CausalTruncationOracle(seed=spec.seed, checks=spec.cutoff_checks).verify(panel, observed)
    return full, proof


class _ExpressionCompiler:
    """Each operation becomes one intermediate column; nested window expressions work."""
    def __init__(self):
        self._counter = 0

    def compile(self, frame: pl.DataFrame, node: dict[str, Any], depth: int = 0):
        if not isinstance(node, dict) or depth > 30:
            raise QuantError('INVALID_SPEC', 'Expression must be a bounded operation tree')
        op = node.get('op')
        if op == 'col':
            if set(node) != {'op', 'name'} or node['name'] not in frame.columns or str(node['name']).startswith('__'):
                raise QuantError('INVALID_SPEC', f'Unknown or private feature input: {node}')
            return frame, pl.col(node['name'])
        if op == 'lit':
            value = node.get('value')
            if set(node) != {'op', 'value'} or not isinstance(value, (float, int, bool)):
                raise QuantError('INVALID_SPEC', 'Literal must be numeric or boolean')
            import math
            if not math.isfinite(value):
                raise QuantError('INVALID_SPEC', 'Literal must be finite')
            return frame, pl.lit(value)
        allowed = {'op', 'args', 'window', 'periods', 'min_samples'}
        if set(node) - allowed:
            raise QuantError('INVALID_SPEC', f'Unknown expression arguments: {set(node) - allowed}')
        args = []
        for arg in node.get('args', []):
            frame, expr = self.compile(frame, arg, depth + 1)
            args.append(expr)
        binary = {'add': lambda a,b:a+b, 'sub': lambda a,b:a-b, 'mul': lambda a,b:a*b,
                  'div': lambda a,b:pl.when(b != 0).then(a/b).otherwise(None),
                  'gt': lambda a,b:a>b, 'ge':lambda a,b:a>=b, 'lt':lambda a,b:a<b,
                  'le':lambda a,b:a<=b, 'and':lambda a,b:a&b, 'or':lambda a,b:a|b}
        if op in binary and len(args) == 2:
            result = binary[op](*args)
        elif op == 'where' and len(args) == 3:
            result = pl.when(args[0]).then(args[1]).otherwise(args[2])
        elif op in {'neg', 'abs'} and len(args) == 1:
            result = -args[0] if op == 'neg' else args[0].abs()
        elif op in {'shift', 'diff', 'pct_change'} and len(args) == 1:
            periods = node.get('periods', 1)
            if not isinstance(periods, int) or periods < 0:
                raise QuantError('INVALID_SPEC', 'Feature lags cannot read future rows')
            result = getattr(args[0], op)(periods).over('symbol')
        elif op in {'rolling_sum', 'rolling_mean', 'rolling_std', 'rolling_min', 'rolling_max'} and len(args) == 1:
            window = node.get('window')
            minimum = node.get('min_samples', window)
            if not isinstance(window, int) or window < 1 or not isinstance(minimum, int) or not 1 <= minimum <= window:
                raise QuantError('INVALID_SPEC', 'Rolling window/min_samples must be positive integers')
            result = getattr(args[0], op)(window, min_samples=minimum).over('symbol')
        elif op in {'xs_rank', 'xs_mean'} and len(args) == 1:
            active = pl.when(pl.col('in_pit_universe')).then(args[0]).otherwise(None)
            result = (active.rank(method='average') if op == 'xs_rank' else active.mean()).over('timestamp')
        else:
            raise QuantError('INVALID_SPEC', f'Unsupported operation/arity: {op}/{len(args)}')
        self._counter += 1
        name = f'__expr_{self._counter}'
        return frame.with_columns(result.alias(name)), pl.col(name)


def apply_declared_features(frame: pl.DataFrame, features) -> pl.DataFrame:
    """Compile a declared feature list onto a frame that already exposes `in_pit_universe`."""
    reserved = set(frame.columns)
    compiler = _ExpressionCompiler()
    for feature in features:
        if feature.name in reserved or feature.name.startswith('__'):
            raise QuantError('INVALID_SPEC', f'Feature shadows protected field: {feature.name}')
        if feature.native is not None:
            try:
                frame = compute_features(frame, [{'name': feature.native, 'params': feature.params,
                                                   'output': feature.name}],
                                         group_col='symbol', timestamp_col='timestamp')
            except Exception as exc:
                raise QuantError('INVALID_FEATURE', f'Native {feature.native}: {exc}') from exc
        else:
            frame, expression = compiler.compile(frame, feature.expr)
            frame = frame.with_columns(expression.alias(feature.name))
        reserved.add(feature.name)
    return frame.select(*CANONICAL_COLUMNS, 'in_pit_universe',
                        *[f.name for f in features]).sort('symbol', 'timestamp')


class FeatureCompiler:
    """Point-in-time cross-sectional universe plus the declared feature list."""
    def __init__(self, spec: CandidateSpec):
        self.spec = spec

    def __call__(self, panel: pl.DataFrame) -> pl.DataFrame:
        return self.apply_features(point_in_time_universe(panel, self.spec))

    def apply_features(self, frame: pl.DataFrame) -> pl.DataFrame:
        return apply_declared_features(frame, self.spec.features)
