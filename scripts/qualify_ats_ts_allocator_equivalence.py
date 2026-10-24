"""Independent differential qualification for the ATS time-series allocator.

``src.engine.ts_allocator.allocate_ts`` is compared against the **actual original
implementation**, extracted verbatim from a pinned git ref (the branch base
``9771b73``). The original is never re-implemented here: its source bytes are read
from git, its blob object id and sha256 are asserted against recorded constants,
and exactly three package-relative imports are rewritten so the module can be
imported from outside its package. Every other source line must stay
byte-identical; any other textual change is a hard error.

Every case compares, in this order:

* exception type, then ``QuantError.status`` and ``QuantError.reason``,
* ordered ``(name, dtype)`` schema,
* row count,
* exact column values, with Float64 columns compared as raw IEEE-754 bit
  patterns (``uint64`` views), timestamps compared as exact integer ticks plus
  dtype, and strings compared verbatim.

The case matrix is synthetic and in memory. It covers all four risk methods,
loose/binding/multi-round/impossible per-instrument caps, the warm-up hold-flat
branch, forecast/stop/volatility extremes (null, NaN, infinities, subnormals,
stop-distance boundaries), gross exposure scaling, several declared market-class
sizes, off-cadence and empty schedules, timestamp units/naive truncation, Float32
and Int64 inputs, physical row order, duplicate ``(timestamp, symbol)`` rows and
cross-timestamp error precedence, plus seeded fuzz panels.

Every case must be bit-identical. There is no accepted-divergence list: the
refactor assigns weights to every row of a rebalance (so a repeated
``(timestamp, symbol)`` row keeps its twin's assignment) and walks rebalances in
first-appearance order, both matching the pinned loop exactly.

This harness is development-only: it opens no vault, reads no protected data,
writes no casefile/ledger/run log, and touches no broker.

Usage:

    PY=/home/quant/dev/quant/quant-research/.venv/bin/python
    PYTHONPATH=$PWD $PY -B scripts/qualify_ats_ts_allocator_equivalence.py \
        --json .workspace/ats_ts_allocator/oracle.json
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import subprocess
import sys
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.engine.ts_allocator import allocate_ts as optimized_allocate  # noqa: E402
from src.engine.ts_spec import TimeSeriesSpec  # noqa: E402

#: Branch base for the allocator refactor (``git rev-parse <ref>:<path>``).
DEFAULT_REF = '9771b7372e9be950193c121708e1fd65fada6142'
ORIGINAL_PATH = 'src/engine/ts_allocator.py'
ORIGINAL_BLOB = 'eeb7042ea8c1cc5d5a8db5b962135057974ee6d6'
ORIGINAL_SHA256 = '11a1598c06203558e131ae646d1204891ba83c26123183fc526919538e0c1f1c'

#: The only permitted textual adaptation of the original source.
IMPORT_REWRITES = (
    ('from .common import QuantError', 'from src.engine.common import QuantError'),
    ('from .signal_allocator import TARGET_COLUMNS',
     'from src.engine.signal_allocator import TARGET_COLUMNS'),
    ('from .ts_spec import MarketClass, TimeSeriesSpec',
     'from src.engine.ts_spec import MarketClass, TimeSeriesSpec'),
)

START = datetime(2020, 1, 1, tzinfo=UTC)

# --------------------------------------------------------------------------- #
# Original implementation: read from git, verify identity, import unchanged
# --------------------------------------------------------------------------- #
def _git(*args: str) -> bytes:
    return subprocess.run(['git', '-C', str(ROOT), *args], check=True,
                          capture_output=True).stdout


def extract_original(ref: str, dest: Path) -> tuple[Any, dict[str, Any]]:
    blob = _git('rev-parse', f'{ref}:{ORIGINAL_PATH}').decode().strip()
    if blob != ORIGINAL_BLOB:
        raise SystemExit(f'original blob drifted: {blob} != {ORIGINAL_BLOB} at {ref}')
    raw = _git('show', f'{ref}:{ORIGINAL_PATH}')
    digest = hashlib.sha256(raw).hexdigest()
    if digest != ORIGINAL_SHA256:
        raise SystemExit(f'original source drifted: {digest} != {ORIGINAL_SHA256}')

    text = raw.decode('utf-8')
    rewritten = text
    for old, new in IMPORT_REWRITES:
        if rewritten.count(old) != 1:
            raise SystemExit(f'import rewrite is not unique: {old!r}')
        rewritten = rewritten.replace(old, new)

    # Nothing but the three import lines may differ from the pinned original.
    before, after = text.splitlines(), rewritten.splitlines()
    if len(before) != len(after):
        raise SystemExit(f'adaptation changed the line count: {len(before)} -> {len(after)}')
    changed = [(left, right) for left, right in zip(before, after, strict=True)
               if left != right]
    if len(changed) != len(IMPORT_REWRITES) or set(changed) != set(IMPORT_REWRITES):
        raise SystemExit(f'unexpected adaptation of the original source: {changed}')

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(rewritten, encoding='utf-8')
    spec = importlib.util.spec_from_file_location('_ats_original_ts_allocator', dest)
    if spec is None or spec.loader is None:
        raise SystemExit('could not build an import spec for the pinned original')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.allocate_ts, {
        'ref': ref, 'blob': blob, 'sha256': digest, 'path': ORIGINAL_PATH,
        'adaptation': 'three relative imports', 'rewritten_lines': changed,
    }


# --------------------------------------------------------------------------- #
# Synthetic fixtures (in memory only)
# --------------------------------------------------------------------------- #
BASE_SCHEMA: dict[str, Any] = {
    'timestamp': pl.Datetime('us', 'UTC'),
    'symbol': pl.String,
    'close': pl.Float64,
    'in_pit_universe': pl.Boolean,
    'is_tradable': pl.Boolean,
    'forecast': pl.Float64,
    'atr_14': pl.Float64,
    'vol_20': pl.Float64,
}


def frame(rows: list[dict[str, Any]], *, unit: str = 'us', tz: str | None = 'UTC',
          overrides: dict[str, Any] | None = None,
          ticks: list[int] | None = None) -> pl.DataFrame:
    """Typed synthetic feature panel; empty panels stay typed like production."""
    schema = dict(BASE_SCHEMA)
    schema['timestamp'] = pl.Datetime(unit, tz)
    schema.update(overrides or {})
    if ticks is not None:
        if len(ticks) != len(rows):
            raise ValueError('ticks must match the row count')
        schema['timestamp'] = pl.Datetime(unit, tz)
    if not rows:
        return pl.DataFrame({name: [] for name in schema}, schema=schema)

    names = list(schema)
    for entry in rows:
        for name in entry:
            if name not in names:
                names.append(name)
    out = pl.DataFrame({name: [entry.get(name) for entry in rows] for name in names})
    if ticks is not None:
        stamp = pl.Series('timestamp', ticks, dtype=pl.Int64).cast(pl.Datetime(unit, tz))
        out = out.with_columns(stamp)
    else:
        out = out.with_columns(pl.col('timestamp').cast(pl.Datetime(unit, tz)))
    return out.cast({name: dtype for name, dtype in schema.items() if name in out.columns})


def row(ts: datetime, symbol: str, forecast: float = 0.0, *,
        stop: float | None = 0.01, close: float | None = 100.0,
        vol: float | None = 0.2, pit: bool | None = True,
        tradable: bool | None = True, **extra: Any) -> dict[str, Any]:
    return {'timestamp': ts, 'symbol': symbol, 'close': close,
            'in_pit_universe': pit, 'is_tradable': tradable,
            'forecast': forecast, 'atr_14': stop, 'vol_20': vol, **extra}


def build_spec(*, symbols: tuple[str, ...] = ('A', 'B', 'C', 'D', 'E', 'F'),
               method: str = 'inverse_volatility', per_instrument_cap: float = 0.5,
               gross_exposure: float = 1.0, volatility_feature: str | None = 'vol_20',
               weights: dict[str, float] | None = None, bar_seconds: int = 3600,
               rebalance_bars: int = 1, multiple: float = 3.0,
               stop_feature: str = 'atr_14', forecast_feature: str = 'f',
               feature_names: tuple[str, ...] = ('f', 'atr_14', 'vol_20'),
               extra_class_symbols: tuple[str, ...] = (),
               train_start: datetime = START) -> TimeSeriesSpec:
    if method not in ('inverse_volatility', 'forecast_weighted'):
        volatility_feature = None
    risk: dict[str, Any] = {'method': method,
                            'per_instrument_cap': per_instrument_cap,
                            'gross_exposure': gross_exposure}
    if volatility_feature is not None:
        risk['volatility_feature'] = volatility_feature
    if weights is not None:
        risk['weights'] = dict(weights)
    classes = [{'name': 'indices', 'symbols': list(symbols),
                'panel_root': 'unused-synthetic', 'bar_seconds': bar_seconds,
                'periods_per_year': 252}]
    if extra_class_symbols:
        classes.append({'name': 'metals', 'symbols': list(extra_class_symbols),
                        'panel_root': 'unused-synthetic', 'bar_seconds': bar_seconds,
                        'periods_per_year': 252})
    return TimeSeriesSpec.model_validate({
        'spec_kind': 'time_series',
        'sleeve_id': 'ats_ts_allocator_oracle',
        'selection_family_id': 'ats_ts_allocator_oracle',
        'book_strategy': 6,
        'thesis': 'Differential allocator qualification fixture; never market evidence.',
        'market_classes': classes,
        'windows': {
            'train': {'start': train_start.isoformat(), 'end': '2026-01-01T00:00:00Z'},
            'validation': {'start': '2026-01-01T00:00:00Z',
                           'end': '2026-04-01T00:00:00Z'},
            'protected': {'start': '2026-04-01T00:00:00Z',
                          'end': '2026-10-01T00:00:00Z'},
        },
        'features': [{'name': name, 'expr': {'op': 'col', 'name': 'close'}}
                     for name in feature_names],
        'forecast': {'feature': forecast_feature, 'horizon_bars': 1,
                     'scaling': {'kind': 'bounded_linear', 'scale': 10.0, 'cap': 2.0}},
        'risk_allocation': risk,
        'stops': {'feature': stop_feature, 'multiple': multiple},
        'rebalance_bars': rebalance_bars,
        'costs': {'commission_bps_one_way': 1.0, 'slippage_bps_one_way': 1.0,
                  'spread_bps': 0.0, 'spread_included_in_slippage': True},
    })


# --------------------------------------------------------------------------- #
# Comparison
# --------------------------------------------------------------------------- #
def _exception(exc: BaseException) -> dict[str, Any]:
    return {'type': type(exc).__name__,
            'status': getattr(exc, 'status', None),
            'reason': getattr(exc, 'reason', None),
            'text': str(exc)}


def _column_bits(series: pl.Series) -> Any:
    if series.dtype == pl.String:
        return series.to_list()
    if series.dtype == pl.Datetime:
        return ('ticks', str(series.dtype),
                series.to_numpy().astype('int64').tolist())
    if series.dtype == pl.Float64:
        return ('bits', str(series.dtype),
                np.ascontiguousarray(series.to_numpy()).view('uint64').tolist())
    return ('value', str(series.dtype), series.to_numpy().tolist())


def _frame_view(data: pl.DataFrame) -> dict[str, Any]:
    return {'schema': [(name, str(dtype)) for name, dtype in data.schema.items()],
            'height': data.height,
            'columns': {name: _column_bits(data[name]) for name in data.columns}}


def _gross_findings(data: pl.DataFrame, gross: float) -> list[dict[str, str]]:
    """Built-in ``sum`` invariant on sections that actually allocate."""
    findings: list[dict[str, str]] = []
    for block in data.partition_by('timestamp', maintain_order=True):
        total = sum(abs(weight) for weight in block['target_weight'].to_list())
        if total == 0.0:
            continue
        if abs(total - gross) > 1e-9:
            findings.append({'kind': 'ORACLE_INVARIANT',
                             'detail': f'gross {total!r} != declared {gross!r}'})
    return findings


def _first_diff(left: list[Any], right: list[Any]) -> str:
    for index, (a, b) in enumerate(zip(left, right, strict=False)):
        if a != b:
            return f'index {index}: {a!r} != {b!r}'
    return f'length {len(left)} != {len(right)}'


def compare(case: dict[str, Any]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for key, fn in (('original', case['original']), ('optimized', case['optimized'])):
        try:
            emitted = fn()
            results[key] = {'frame': _frame_view(emitted), 'exception': None}
            if key == 'original' and case.get('expected_gross') is not None:
                results[key]['invariant'] = _gross_findings(
                    emitted, case['expected_gross'])
            else:
                results[key]['invariant'] = []
        except BaseException as exc:  # noqa: BLE001  # exception parity is the subject
            results[key] = {'frame': None, 'exception': _exception(exc), 'invariant': []}

    findings: list[dict[str, str]] = list(results['original'].get('invariant') or [])
    left, right = results['original'], results['optimized']
    if (left['exception'] is None) != (right['exception'] is None):
        findings.append({'kind': 'EXC_PRESENCE',
                         'detail': f"original={left['exception']} optimized={right['exception']}"})
    elif left['exception'] is not None:
        if left['exception']['type'] != right['exception']['type']:
            findings.append({'kind': 'EXC_TYPE',
                             'detail': f"{left['exception']['type']} -> "
                                       f"{right['exception']['type']}"})
        elif left['exception']['status'] != right['exception']['status']:
            findings.append({'kind': 'EXC_STATUS',
                             'detail': f"{left['exception']['status']} -> "
                                       f"{right['exception']['status']}"})
        elif left['exception']['reason'] != right['exception']['reason']:
            findings.append({'kind': 'EXC_MESSAGE',
                             'detail': f"{left['exception']['reason']!r} -> "
                                       f"{right['exception']['reason']!r}"})
    else:
        a, b = left['frame'], right['frame']
        if a['schema'] != b['schema']:
            findings.append({'kind': 'SCHEMA', 'detail': f"{a['schema']} -> {b['schema']}"})
        if a['height'] != b['height']:
            findings.append({'kind': 'HEIGHT',
                             'detail': f"{a['height']} -> {b['height']}"})
        for name in a['columns']:
            if name not in b['columns']:
                findings.append({'kind': 'COLUMN_MISSING', 'detail': name})
                continue
            left_col, right_col = a['columns'][name], b['columns'][name]
            if left_col == right_col:
                continue
            kind = 'COLUMN_DTYPE' if left_col[:2] != right_col[:2] else 'COLUMN_VALUES'
            detail = f'{name}: {left_col[:2]} -> {right_col[:2]}'
            if kind == 'COLUMN_VALUES':
                detail += f'; first diff at {_first_diff(left_col[2], right_col[2])}'
            findings.append({'kind': kind, 'detail': detail})

    expected = case.get('divergence')
    if not findings:
        status = 'PASS'
    elif expected and {finding['kind'] for finding in findings} == set(
            expected['exact_kinds']):
        status = 'EXPECTED_DIFF'
    elif expected:
        status = 'FAIL'  # a documented divergence changed shape: re-qualify it
        findings.append({'kind': 'UNDOCUMENTED_SHAPE',
                         'detail': f"expected exactly {sorted(expected['exact_kinds'])}, "
                                   f"observed {sorted({f['kind'] for f in findings})}"})
    else:
        status = 'FAIL'
    return {'name': case['name'], 'group': case.get('group', 'single'),
            'original': left, 'optimized': right, 'findings': findings,
            'divergence': expected, 'status': status}


# --------------------------------------------------------------------------- #
# Case matrix
# --------------------------------------------------------------------------- #
def cases() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def add(name: str, features: pl.DataFrame, spec: TimeSeriesSpec, *,
            market_index: int = 0, group: str = 'single',
            divergence: dict[str, Any] | None = None,
            expected_gross: float | None = None) -> None:
        market_class = spec.market_classes[market_index]
        out.append({
            'name': name, 'group': group, 'divergence': divergence,
            'expected_gross': expected_gross,
            'original': lambda f=features, s=spec, m=market_class: original(f, s, m),
            'optimized': lambda f=features, s=spec, m=market_class: optimized_allocate(
                f, s, m),
        })

    # --- risk methods -------------------------------------------------------
    six = ('A', 'B', 'C', 'D', 'E', 'F')
    inverse_rows = [row(START, symbol, 1.0, vol=0.1 * (index + 1))
                    for index, symbol in enumerate(six)]
    add('risk_inverse_volatility', frame(inverse_rows),
        build_spec(symbols=six, per_instrument_cap=0.5), expected_gross=1.0)
    add('risk_equal_weight', frame([row(START, symbol, 1.0) for symbol in six]),
        build_spec(symbols=six, method='equal_weight', per_instrument_cap=0.5),
        expected_gross=1.0)
    add('risk_forecast_weighted',
        frame([row(START, symbol, float(index + 1), vol=0.1 * (index + 1))
               for index, symbol in enumerate(six)]),
        build_spec(symbols=six, method='forecast_weighted', per_instrument_cap=0.5),
        expected_gross=1.0)
    manual_weights = {'A': 0.10, 'B': 0.20, 'C': 0.30, 'D': 0.15, 'E': 0.25}
    add('risk_manual',
        frame([row(START, symbol, 1.0) for symbol in manual_weights]),
        build_spec(symbols=tuple(manual_weights), method='manual',
                   per_instrument_cap=0.6, weights=manual_weights),
        expected_gross=1.0)
    add('risk_manual_weights_not_normalized',
        frame([row(START, symbol, 1.0) for symbol in ('A', 'B', 'C', 'D')]),
        build_spec(symbols=('A', 'B', 'C', 'D'), method='manual',
                   per_instrument_cap=0.5,
                   weights={'A': 0.1, 'B': 0.1, 'C': 0.1, 'D': 0.1}),
        expected_gross=1.0)
    manual_subset = {'A': 0.20, 'B': 0.20, 'C': 0.20, 'D': 0.20, 'E': 0.20}
    add('risk_manual_with_ineligible_names',
        frame([row(START, 'A', 1.0, vol=0.2),
               row(START, 'B', -1.0, vol=0.2),
               row(START, 'C', 1.0, vol=0.2, pit=False),
               row(START, 'D', 1.0, vol=0.2, tradable=False),
               row(START, 'E', 1.0, vol=0.2)]),
        build_spec(symbols=tuple(manual_subset), method='manual',
                   per_instrument_cap=0.6, weights=manual_subset))

    # --- caps ---------------------------------------------------------------
    add('cap_not_binding',
        frame([row(START, symbol, 1.0, vol=vol) for symbol, vol in
               zip(('A', 'B', 'C', 'D'), (0.1, 0.2, 0.3, 0.4), strict=True)]),
        build_spec(symbols=('A', 'B', 'C', 'D'), per_instrument_cap=0.9))
    add('cap_binding_one_name',
        frame([row(START, symbol, 1.0, vol=vol) for symbol, vol in
               zip(('A', 'B', 'C', 'D'), (0.01, 0.2, 0.3, 0.4), strict=True)]),
        build_spec(symbols=('A', 'B', 'C', 'D'), per_instrument_cap=0.45))
    add('cap_multi_round_water_filling',
        frame([row(START, symbol, 1.0, vol=vol) for symbol, vol in
               zip(('A', 'B', 'C', 'D', 'E', 'F'),
                   (0.01, 0.02, 0.05, 0.5, 0.9, 2.0), strict=True)]),
        build_spec(symbols=six, per_instrument_cap=0.3))
    add('cap_exactly_saturated',
        frame([row(START, symbol, 1.0) for symbol in ('A', 'B', 'C', 'D')]),
        build_spec(symbols=('A', 'B', 'C', 'D'), method='equal_weight',
                   per_instrument_cap=0.25), expected_gross=1.0)
    add('cap_just_below_saturated_holds_flat',
        frame([row(START, symbol, 1.0) for symbol in ('A', 'B', 'C', 'D')]),
        build_spec(symbols=six, method='equal_weight', per_instrument_cap=0.249999))
    add('cap_unreachable_for_declared_universe',
        frame([row(START, symbol, 1.0) for symbol in ('A', 'B', 'C')]),
        build_spec(symbols=('A', 'B', 'C'), per_instrument_cap=0.3))
    add('cap_unreachable_but_no_scheduled_timestamp',
        frame([row(START + timedelta(minutes=30), symbol, 1.0)
               for symbol in ('A', 'B', 'C')]),
        build_spec(symbols=('A', 'B', 'C'), per_instrument_cap=0.3),
        group='precedence')
    add('cap_unreachable_after_eligibility',
        frame([row(START, symbol, 1.0) for symbol in ('A', 'B', 'C', 'D')]),
        build_spec(symbols=six, method='equal_weight', per_instrument_cap=0.2))

    # --- declared-vs-panel universes ---------------------------------------
    add('declared_symbols_absent_from_panel',
        frame([row(START, symbol, 1.0) for symbol in six]),
        build_spec(symbols=(*six, 'G', 'H'), method='equal_weight',
                   per_instrument_cap=0.2))
    add('panel_symbol_absent_from_declared_class',
        frame([row(START, symbol, float(index + 1)) for index, symbol in
               enumerate(('A', 'B', 'ZZZ'))]),
        build_spec(symbols=('A', 'B'), method='equal_weight',
                   per_instrument_cap=0.5), expected_gross=1.0)
    add('declared_symbols_ineligible',
        frame([row(START, symbol, 1.0, pit=index < 5)
               for index, symbol in enumerate((*six, 'G', 'H'))]),
        build_spec(symbols=(*six, 'G', 'H'), method='equal_weight',
                   per_instrument_cap=0.2), expected_gross=1.0)
    add('warm_up_holds_flat_then_allocates',
        frame([row(START, 'A', 1.0), row(START, 'B', 1.0)]
              + [row(START + timedelta(hours=1), symbol, 1.0) for symbol in six]),
        build_spec(symbols=six, method='equal_weight', per_instrument_cap=0.2))
    add('second_market_class_declared_count',
        frame([row(START, symbol, 1.0) for symbol in ('X', 'Y', 'Z')]),
        build_spec(symbols=('A', 'B'), method='equal_weight',
                   per_instrument_cap=0.4, extra_class_symbols=('X', 'Y', 'Z')),
        market_index=1)

    # --- forecast extremes --------------------------------------------------
    forecast_edges = [
        row(START, 'NULL_F', None), row(START, 'NAN_F', math.nan),
        row(START, 'INF_F', math.inf), row(START, 'NEG_INF_F', -math.inf),
        row(START, 'ZERO_F', 0.0), row(START, 'TINY_POS', 5e-324),
        row(START, 'TINY_NEG', -5e-324),
        row(START, 'OK1', 1.0), row(START, 'OK2', -2.0),
    ]
    add('forecast_nulls_nonfinite_zero_subnormal', frame(forecast_edges),
        build_spec(symbols=tuple(entry['symbol'] for entry in forecast_edges),
                   per_instrument_cap=0.5))
    add('forecast_ties_equal_weight',
        frame([row(START, symbol, 1.0) for symbol in six]),
        build_spec(symbols=six, method='equal_weight', per_instrument_cap=0.5))
    add('forecast_ties_mixed_sign',
        frame([row(START, symbol, 2.0 if index % 2 else -2.0)
               for index, symbol in enumerate(six)]),
        build_spec(symbols=six, method='equal_weight', per_instrument_cap=0.5))
    add('forecast_overflow_forecast_weighted',
        frame([row(START, 'HUGE', 1e308, vol=1e-3), row(START, 'OK', 1.0, vol=0.2)]),
        build_spec(symbols=('HUGE', 'OK'), method='forecast_weighted',
                   per_instrument_cap=0.5))
    add('subnormal_volatility_overflows_inverse',
        frame([row(START, 'TINY_VOL', 1.0, vol=5e-324),
               row(START, 'OK', 1.0, vol=0.2)]),
        build_spec(symbols=('TINY_VOL', 'OK'), per_instrument_cap=0.5))

    # --- stop feature extremes ---------------------------------------------
    stop_edges = [
        row(START, 'NULL_S', 9.0, stop=None), row(START, 'NAN_S', 8.0, stop=math.nan),
        row(START, 'INF_S', 7.0, stop=math.inf), row(START, 'NEG_S', 6.0, stop=-0.01),
        row(START, 'ZERO_S', 5.0, stop=0.0), row(START, 'SUBNORMAL_S', 4.0,
                                                  stop=5e-324),
        row(START, 'NORMAL_S', 3.0, stop=0.01),
    ]
    add('stop_nulls_nonfinite_nonpositive_subnormal', frame(stop_edges),
        build_spec(symbols=tuple(entry['symbol'] for entry in stop_edges),
                   per_instrument_cap=0.5))
    below = math.nextafter(100.0, 0.0)
    above = math.nextafter(100.0, math.inf)
    add('stop_distance_boundary_multiple_one',
        frame([row(START, 'EQ', 5.0, stop=100.0, close=100.0),
               row(START, 'BELOW', 4.0, stop=below, close=100.0),
               row(START, 'ABOVE', 3.0, stop=above, close=100.0),
               row(START, 'NEAR', 2.0, stop=99.99999999999997, close=100.0),
               row(START, 'NORMAL', 1.0, stop=0.01)]),
        build_spec(symbols=('EQ', 'BELOW', 'ABOVE', 'NEAR', 'NORMAL'),
                   multiple=1.0, per_instrument_cap=0.5))
    add('stop_distance_boundary_multiple_three',
        frame([row(START, 'EQ', 5.0, stop=100.0, close=300.0),
               row(START, 'BELOW', 4.0, stop=below, close=300.0),
               row(START, 'ABOVE', 3.0, stop=above, close=300.0),
               row(START, 'NORMAL', 1.0, stop=1.0, close=300.0)]),
        build_spec(symbols=('EQ', 'BELOW', 'ABOVE', 'NORMAL'), multiple=3.0,
                   per_instrument_cap=0.5))
    add('stop_subnormal_distance',
        frame([row(START, 'SUB', 1.0, stop=5e-324, close=1.0),
               row(START, 'OK', 1.0, stop=0.01, close=1.0)]),
        build_spec(symbols=('SUB', 'OK'), multiple=1.0, per_instrument_cap=1.0))

    # --- volatility extremes ------------------------------------------------
    vol_edges = [
        row(START, 'NULL_V', 1.0, vol=None), row(START, 'NAN_V', 1.0, vol=math.nan),
        row(START, 'INF_V', 1.0, vol=math.inf), row(START, 'NEG_V', 1.0, vol=-0.2),
        row(START, 'ZERO_V', 1.0, vol=0.0), row(START, 'OK_V', 1.0, vol=0.2),
    ]
    add('vol_nulls_nonfinite_nonpositive_inverse', frame(vol_edges),
        build_spec(symbols=tuple(entry['symbol'] for entry in vol_edges),
                   per_instrument_cap=0.5))
    add('vol_nulls_nonfinite_nonpositive_forecast_weighted', frame(vol_edges),
        build_spec(symbols=tuple(entry['symbol'] for entry in vol_edges),
                   method='forecast_weighted', per_instrument_cap=0.5))

    # --- gross exposure -----------------------------------------------------
    for gross in (0.5, 2.0):
        add(f'gross_exposure_{str(gross).replace(".", "p")}',
            frame([row(START, symbol, 1.0, vol=0.1 * (index + 1))
                   for index, symbol in enumerate(six)]),
            build_spec(symbols=six, per_instrument_cap=0.5, gross_exposure=gross),
            expected_gross=gross, group='gross')

    # --- cadence ------------------------------------------------------------
    hourly = [row(START + timedelta(hours=bar), symbol, float(6 - index + bar))
              for bar in range(6) for index, symbol in enumerate(six)]
    add('cadence_hourly', frame(hourly), build_spec(symbols=six))
    daily = [row(START + timedelta(hours=bar), symbol, float(6 - index + bar % 3))
             for bar in range(72) for index, symbol in enumerate(six)]
    add('cadence_daily_24_bars', frame(daily),
        build_spec(symbols=six, bar_seconds=3600, rebalance_bars=24))
    add('cadence_rebalance_3_bars',
        frame([row(START + timedelta(hours=bar), symbol, float(6 - index + bar))
               for bar in range(12) for index, symbol in enumerate(six)]),
        build_spec(symbols=six, rebalance_bars=3))
    add('cadence_anchor_not_aligned', frame(hourly),
        build_spec(symbols=six, train_start=datetime(2019, 1, 1, 0, 17, tzinfo=UTC)),
        group='cadence')
    add('cadence_no_scheduled_timestamp',
        frame([row(START + timedelta(minutes=30 * step), symbol, float(6 - index))
               for step in range(3) for index, symbol in enumerate(six)]),
        build_spec(symbols=six), group='cadence')
    add('empty_frame', frame([]), build_spec(symbols=six), group='cadence')

    # --- timestamp units and precision -------------------------------------
    three_bars = [row(START + timedelta(hours=bar), symbol, float(6 - index - bar))
                  for bar in range(3) for index, symbol in enumerate(six)]
    add('timestamp_microseconds', frame(three_bars, unit='us'), build_spec(symbols=six))
    add('timestamp_nanoseconds', frame(three_bars, unit='ns'), build_spec(symbols=six))
    add('timestamp_naive', frame(three_bars, unit='us', tz=None), build_spec(symbols=six))
    base_us = int(START.timestamp()) * 1_000_000
    submicro_rows = [row(START, symbol, float(index + 1))
                     for _offset in (0, 1)
                     for index, symbol in enumerate(('A', 'B', 'C'))]
    submicro_rows += [row(START, symbol, float(index + 1))
                      for _offset in (1000, 1001)
                      for index, symbol in enumerate(('D', 'E', 'F'))]
    submicro_ticks = [base_us * 1000 + 0] * 3 + [base_us * 1000 + 1] * 3 \
        + [base_us * 1000 + 1000] * 3 + [base_us * 1000 + 1001] * 3
    add('timestamp_submicrosecond_truncation',
        frame(submicro_rows, unit='ns', ticks=submicro_ticks),
        build_spec(symbols=six, method='equal_weight', per_instrument_cap=0.4))

    # --- input dtypes -------------------------------------------------------
    dtype_rows = [row(START, symbol, float(index + 1), stop=1.0, close=100.0,
                      vol=float(index + 1)) for index, symbol in enumerate(six)]
    add('dtype_float32',
        frame(dtype_rows, overrides={'forecast': pl.Float32, 'atr_14': pl.Float32,
                                     'vol_20': pl.Float32, 'close': pl.Float32}),
        build_spec(symbols=six, per_instrument_cap=0.5))
    add('dtype_int64',
        frame(dtype_rows, overrides={'forecast': pl.Int64, 'atr_14': pl.Int64,
                                     'vol_20': pl.Int64, 'close': pl.Int64}),
        build_spec(symbols=six, per_instrument_cap=0.5))
    add('dtype_mixed',
        frame(dtype_rows, overrides={'forecast': pl.Int64, 'atr_14': pl.Int64,
                                     'vol_20': pl.Float32, 'close': pl.Float32}),
        build_spec(symbols=six, method='forecast_weighted', per_instrument_cap=0.5))

    # --- physical row order -------------------------------------------------
    canonical = [row(START + timedelta(hours=bar), symbol, float(6 - index + bar))
                 for bar in range(2) for index, symbol in enumerate(six)]
    add('order_canonical_timestamp_symbol', frame(canonical), build_spec(symbols=six))
    add('order_shuffled', frame(list(reversed(canonical))), build_spec(symbols=six))
    add('order_symbol_major',
        frame(sorted(canonical, key=lambda entry: (entry['symbol'], entry['timestamp']))),
        build_spec(symbols=six))

    # --- duplicate (timestamp, symbol) rows ---------------------------------
    duplicate_equal = [row(START, 'DUP', 9.0), row(START, 'DUP', 9.0)]
    duplicate_equal += [row(START, symbol, float(index))
                        for index, symbol in enumerate(('A', 'B', 'C', 'D', 'E', 'F'))]
    add('duplicate_identical_rows', frame(duplicate_equal),
        build_spec(symbols=('DUP', 'A', 'B', 'C', 'D', 'E', 'F'),
                   method='equal_weight', per_instrument_cap=0.5))
    duplicate_eligible = [row(START, 'DUP', 9.0, stop=0.01),
                          row(START, 'DUP', 8.0, stop=0.02)]
    duplicate_eligible += [row(START, symbol, float(index))
                           for index, symbol in enumerate(('A', 'B', 'C', 'D', 'E', 'F'))]
    add('duplicate_both_eligible_conflicting_values', frame(duplicate_eligible),
        build_spec(symbols=('DUP', 'A', 'B', 'C', 'D', 'E', 'F'),
                   method='equal_weight', per_instrument_cap=0.5))
    duplicate_twin = [row(START, 'DUP', 9.0, stop=0.01)]
    duplicate_twin += [row(START, 'DUP', 9.0, stop=0.01, pit=False)]
    duplicate_twin += [row(START, symbol, float(index))
                       for index, symbol in enumerate(('A', 'B', 'C', 'D', 'E', 'F'))]
    add('duplicate_ineligible_twin', frame(duplicate_twin),
        build_spec(symbols=('DUP', 'A', 'B', 'C', 'D', 'E', 'F'),
                   method='equal_weight', per_instrument_cap=0.5),
        group='duplicate')
    duplicate_stop_twin = [row(START, 'DUP', 9.0, stop=0.01)]
    duplicate_stop_twin += [row(START, 'DUP', 9.0, stop=100.0)]
    duplicate_stop_twin += [row(START, symbol, float(index))
                            for index, symbol in enumerate(('A', 'B', 'C', 'D', 'E', 'F'))]
    add('duplicate_conflicting_stop_mixed_eligibility', frame(duplicate_stop_twin),
        build_spec(symbols=('DUP', 'A', 'B', 'C', 'D', 'E', 'F'),
                   method='equal_weight', per_instrument_cap=0.5),
        group='duplicate')
    duplicate_neutral = [row(START, 'DUP', None), row(START, 'DUP', 0.0)]
    duplicate_neutral += [row(START, symbol, float(index))
                          for index, symbol in enumerate(('A', 'B', 'C', 'D', 'E', 'F'))]
    add('duplicate_both_ineligible', frame(duplicate_neutral),
        build_spec(symbols=('DUP', 'A', 'B', 'C', 'D', 'E', 'F'),
                   method='equal_weight', per_instrument_cap=0.5))

    # --- manual input error and error precedence ---------------------------
    add('manual_absent_symbol_raises_keyerror',
        frame([row(START, 'A', 1.0), row(START, 'B', 1.0), row(START, 'ZZZ', 1.0)]),
        build_spec(symbols=('A', 'B'), method='manual', per_instrument_cap=0.6,
                   weights={'A': 0.5, 'B': 0.5}), group='input_error')
    zero_pool_rows = [row(START, 'X', 1e10, vol=1.0),
                      row(START, 'Y', 5e-324, vol=1e308),
                      row(START, 'Z', 5e-324, vol=1e308)]
    overflow_rows = [row(START + timedelta(hours=1), 'A', 1e308, vol=1e-3),
                     row(START + timedelta(hours=1), 'B', 1.0, vol=0.2),
                     row(START + timedelta(hours=1), 'C', 1.0, vol=0.2)]
    add('error_precedence_timestamp_sorted',
        frame(zero_pool_rows + overflow_rows),
        build_spec(symbols=('X', 'Y', 'Z', 'A', 'B', 'C'),
                   method='forecast_weighted', per_instrument_cap=0.4),
        group='precedence')
    add('error_precedence_timestamp_row_unsorted',
        frame(overflow_rows + zero_pool_rows),
        build_spec(symbols=('X', 'Y', 'Z', 'A', 'B', 'C'),
                   method='forecast_weighted', per_instrument_cap=0.4),
        group='precedence')

    # --- multiple timestamps with varying eligibility ----------------------
    mixed: list[dict[str, Any]] = []
    for bar in range(4):
        eligible = bar != 2
        mixed += [row(START + timedelta(hours=bar), symbol,
                      float(6 - index + bar), pit=eligible)
                  for index, symbol in enumerate(six)]
    add('multi_timestamp_eligibility_varies', frame(mixed),
        build_spec(symbols=six, method='equal_weight', per_instrument_cap=0.2))

    temp_name_rows = [
        row(START, symbol, float(index + 1), _row=index,
            _ats_row_index=index + 10, _ats_eligible=index % 2 == 0)
        for index, symbol in enumerate(('A', 'B', 'C', 'D'))
    ]
    add('temporary_column_names_do_not_collide',
        frame(temp_name_rows, overrides={
            '_row': pl.Int64, '_ats_row_index': pl.Int64, '_ats_eligible': pl.Boolean,
        }),
        build_spec(symbols=('A', 'B', 'C', 'D'), method='equal_weight',
                   per_instrument_cap=0.34, volatility_feature=None),
        expected_gross=1.0)

    out.extend(fuzz_cases())
    return out


def _pick(rng: np.random.Generator, pool: list[Any]) -> Any:
    value = rng.choice(pool)
    return None if value is None else float(value)


def fuzz_cases(count: int = 24) -> list[dict[str, Any]]:
    """Seeded random panels: ties, nulls, ineligibility, dtypes and parameters."""
    out: list[dict[str, Any]] = []
    forecast_pool = [0.0, 1.0, 1.0, 2.0, -1.0, -2.0, 5e-324, math.nan, math.inf, -math.inf,
                     None]
    stop_pool = [0.01, 0.02, 0.01, 0.0, -0.01, 5e-324, math.nan, math.inf, None]
    vol_pool = [0.1, 0.2, 0.4, 0.0, -0.2, 5e-324, math.nan, math.inf, None]
    for seed in range(count):
        rng = np.random.default_rng(20_000 + seed)
        method = str(rng.choice(['inverse_volatility', 'equal_weight',
                                 'forecast_weighted', 'manual']))
        size = int(rng.integers(3, 9))
        symbols = [f'S{index:02d}' for index in range(size)]
        cap = float(rng.choice([0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 1.0]))
        gross = float(rng.choice([0.5, 1.0, 2.0]))
        multiple = float(rng.choice([1.0, 2.0, 3.0]))
        rebalance = int(rng.integers(1, 4))
        bar_seconds = int(rng.choice([3600, 3600, 900]))
        bars = int(rng.integers(1, 4))
        weights = None
        if method == 'manual':
            raw = rng.uniform(0.1, 1.0, size=size)
            raw = raw / raw.max() * cap * 0.95
            weights = {symbol: float(value) for symbol, value in zip(symbols, raw,
                                                                     strict=True)}
        panel_symbols = list(symbols)
        if rng.random() < 0.35:
            panel_symbols.append('ZZZ')
        if rng.random() < 0.3:
            panel_symbols = [symbol for symbol in panel_symbols
                             if rng.random() > 0.3] or symbols[:1]

        rows: list[dict[str, Any]] = []
        for bar_index in range(bars):
            ts = START + timedelta(hours=bar_index)
            names = list(panel_symbols)
            if rng.random() < 0.3:
                rng.shuffle(names)
            for symbol in names:
                entry = row(
                    ts, symbol,
                    _pick(rng, forecast_pool),
                    stop=_pick(rng, stop_pool),
                    close=float(rng.choice([100.0, 100.0, 50.0, 1.0])),
                    vol=_pick(rng, vol_pool),
                    pit=None if rng.random() < 0.05 else bool(rng.random() > 0.15),
                    tradable=None if rng.random() < 0.05 else bool(rng.random() > 0.15),
                )
                rows.append(entry)
                if rng.random() < 0.12:
                    rows.append(dict(entry))  # identical twin: no upstream repair

        overrides: dict[str, Any] = {}
        if rng.random() < 0.25:
            overrides = {'forecast': pl.Float32, 'atr_14': pl.Float32,
                         'vol_20': pl.Float32, 'close': pl.Float32}
        unit = 'ns' if rng.random() < 0.2 else 'us'
        features = frame(rows, unit=unit, overrides=overrides)
        spec = build_spec(symbols=tuple(symbols), method=method,
                          per_instrument_cap=cap, gross_exposure=gross,
                          weights=weights, bar_seconds=bar_seconds,
                          rebalance_bars=rebalance, multiple=multiple)
        market_class = spec.market_classes[0]
        out.append({
            'name': f'fuzz_{seed:02d}', 'group': 'fuzz', 'divergence': None,
            'expected_gross': None,
            'original': lambda f=features, s=spec, m=market_class: original(f, s, m),
            'optimized': lambda f=features, s=spec, m=market_class:
                optimized_allocate(f, s, m),
        })
    return out


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
original: Callable[..., pl.DataFrame]


def main() -> int:
    global original
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--ref', default=DEFAULT_REF,
                        help=f'git ref holding the pinned original (default {DEFAULT_REF})')
    parser.add_argument('--json', type=Path, default=None,
                        help='write the full comparison report here')
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        original, identity = extract_original(args.ref, Path(tmp) / 'original_ts_allocator.py')
        results = [compare(case) for case in cases()]

    failed = [item for item in results if item['status'] == 'FAIL']
    expected = [item for item in results if item['status'] == 'EXPECTED_DIFF']
    print(f"oracle ref={identity['ref']} blob={identity['blob']} sha256={identity['sha256']}")
    for item in results:
        if item['status'] == 'EXPECTED_DIFF':
            kinds = ','.join(sorted({finding['kind'] for finding in item['findings']}))
            print(f"DIFF {item['name']:<48} {item['group']:<12} [{kinds}] documented: "
                  f"{item['divergence']['expected']}")
        elif item['status'] == 'FAIL':
            kinds = ','.join(sorted({finding['kind'] for finding in item['findings']}))
            print(f"FAIL {item['name']:<48} {item['group']:<12} [{kinds}]")
            for finding in item['findings']:
                print(f"       {finding['kind']}: {finding['detail']}")
            if item['original']['exception'] or item['optimized']['exception']:
                print(f"       original={item['original']['exception']}")
                print(f"       optimized={item['optimized']['exception']}")
        else:
            expectation = 'rejected' if item['original']['exception'] else 'emitted'
            print(f"PASS {item['name']:<48} {item['group']:<12} {expectation}")

    total = len(results)
    identical = total - len(failed) - len(expected)
    print(f'\n{identical}/{total} cases identical to the pinned original; '
          f'{len(expected)} documented divergence(s); {len(failed)} unexplained failure(s)')
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        harness = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        args.json.write_text(json.dumps({
            'original': identity,
            'results': results,
            'identical': identical,
            'documented_divergences': len(expected),
            'unexplained_failures': len(failed),
            'total': total,
            'harness_sha256': harness,
        }, indent=2, sort_keys=True) + '\n')
        print(f'report: {args.json}')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
