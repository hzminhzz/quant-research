"""Exact prefix-invariance tests, deliberately not advertised as a proof theorem."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass

import numpy as np
import polars as pl

from src.data_vault.panel_builder import CANONICAL_COLUMNS, validate_panel
from src.engine.common import QuantError


def _identical(left: pl.Series, right: pl.Series) -> bool:
    if left.dtype != right.dtype or len(left) != len(right):
        return False
    if not left.is_null().equals(right.is_null()):
        return False
    if left.dtype in (pl.Float32, pl.Float64):
        # Null payload bytes are unspecified; compare validity plus all valid bits.
        a, b = left.drop_nulls().to_numpy(), right.drop_nulls().to_numpy()
        return a.dtype == b.dtype and a.tobytes() == b.tobytes()
    return left.equals(right, null_equal=True)


def _check_output(source: pl.DataFrame, result: pl.DataFrame) -> pl.DataFrame:
    if not isinstance(result, pl.DataFrame) or 'in_pit_universe' not in result.columns:
        raise QuantError('INVALID_CAUSALITY', 'Feature function must retain rows and produce in_pit_universe')
    result = result.sort('symbol', 'timestamp').rechunk()
    if result['in_pit_universe'].dtype != pl.Boolean or result['in_pit_universe'].null_count():
        raise QuantError('INVALID_CAUSALITY', 'PIT mask must be non-null Boolean')
    for col in CANONICAL_COLUMNS:
        if col not in result.columns or not _identical(source[col], result[col]):
            raise QuantError('INVALID_CAUSALITY', f'Feature callback changed source rows or column {col}')
    return result


@dataclass(frozen=True)
class CausalEvidence:
    status: str
    seed: int
    cutoffs: tuple[str, ...]
    feature_columns: tuple[str, ...]
    rows: int
    scope: str = 'Exact prefix invariance at recorded cutoffs; not proof of universal causality or source survivorship completeness'

    def to_dict(self):
        return asdict(self)


class CausalTruncationOracle:
    def __init__(self, *, seed: int = 42, checks: int = 3):
        if checks < 3:
            raise ValueError('At least three cutoff tests are required')
        self.seed, self.checks = seed, checks

    def verify(self, panel_df: pl.DataFrame,
               feature_fn: Callable[[pl.DataFrame], pl.DataFrame], *,
               exhaustive: bool = False) -> CausalEvidence:
        source = validate_panel(panel_df).rechunk()
        timestamps = source['timestamp'].unique().sort().to_list()
        if len(timestamps) < self.checks + 1:
            raise QuantError('INCONCLUSIVE_STAGE_1', 'Not enough distinct timestamps for cutoff checks')
        full = _check_output(source, feature_fn(source.clone()))
        columns = tuple(c for c in full.columns if c not in CANONICAL_COLUMNS)
        if columns == ('in_pit_universe',):
            raise QuantError('INVALID_CAUSALITY', 'No feature columns were returned')
        rng = np.random.default_rng(self.seed)
        indices = (np.arange(len(timestamps) - 1) if exhaustive else
                   np.sort(rng.choice(len(timestamps) - 1, self.checks, replace=False)))
        tested = []
        for index in indices:
            cutoff = timestamps[int(index)]
            prefix = source.filter(pl.col('timestamp') <= cutoff)
            expected = full.filter(pl.col('timestamp') <= cutoff)
            observed = _check_output(prefix, feature_fn(prefix.clone()))
            if observed.columns != full.columns:
                raise QuantError('INVALID_CAUSALITY', 'Feature schema changes with future data')
            for col in columns:
                if not _identical(expected[col], observed[col]):
                    raise QuantError('INVALID_CAUSALITY', f'Prefix changed for {col} at {cutoff.isoformat()}')
            tested.append(cutoff.isoformat())
        return CausalEvidence('PASS', self.seed, tuple(tested), columns, source.height)
