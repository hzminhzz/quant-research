"""Independent differential qualification for the ATS cross-sectional allocator.

The optimized ``src.engine.signal_allocator.allocate`` is compared against the
**actual original implementation**, extracted verbatim from a pinned git ref (the
PR merge-base). The original is never re-implemented here: its source bytes are
read from git, its blob object id and sha256 are asserted against recorded
constants, and only the two package-relative imports are rewritten so the module
can be imported from outside its package. Any other textual change is a hard
error.

Every case compares, in this order:

* exception type and ``QuantError`` status/reason (message-only drift is reported
  separately from type drift),
* schema (column order and dtype strings),
* row count,
* exact column values, with Float64 columns compared as raw IEEE-754 bit
  patterns (``uint64`` views), strings compared verbatim, and timestamps compared
  as exact integer ticks plus dtype.

This harness is development-only: it builds synthetic panels in memory, opens no
vault, and touches no protected window, casefile, ledger or broker.

Usage:

    PY=/home/quant/dev/quant/quant-research/.venv/bin/python
    PYTHONPATH=$PWD $PY -B scripts/qualify_ats_allocator_equivalence.py \
        --json .workspace/pr89/oracle.json
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

from src.engine.signal_allocator import allocate as optimized_allocate
from src.engine.spec_parser import CandidateSpec

#: PR #89 merge-base (``origin/main`` at review time).
DEFAULT_REF = '1e8d0cc33f5f3469eb83a78fcc2b79505bff8e9b'
ORIGINAL_PATH = 'src/engine/signal_allocator.py'
#: ``git rev-parse <ref>:src/engine/signal_allocator.py``
ORIGINAL_BLOB = '956fd849cf6b7b70ff49caf46167c7fdbfe9fb7e'
ORIGINAL_SHA256 = '820a2abfae50d9a29d0a05665b746bd36a1ced6d04870e09f4ad1d53f4c00c5f'

#: The only permitted textual adaptation of the original source.
IMPORT_REWRITES = (
    ('from .common import QuantError', 'from src.engine.common import QuantError'),
    ('from .spec_parser import CandidateSpec', 'from src.engine.spec_parser import CandidateSpec'),
)

START = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)


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
    # Nothing but the two import lines may differ from the pinned original.
    changed = [(a, b) for a, b in zip(text.splitlines(), rewritten.splitlines(), strict=True) if a != b]
    if len(changed) != len(IMPORT_REWRITES):
        raise SystemExit(f'unexpected adaptation of the original source: {changed}')
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(rewritten, encoding='utf-8')
    spec = importlib.util.spec_from_file_location('_pr89_original_signal_allocator', dest)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.allocate, {'ref': ref, 'blob': blob, 'sha256': digest,
                             'path': ORIGINAL_PATH, 'adaptation': 'two relative imports'}


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
FEATURES = ('candidate', 'baseline', 'atr_24h')
COLUMNS = ('timestamp', 'symbol', 'open', 'high', 'low', 'close', 'volume',
           'in_pit_universe', 'is_tradable', *FEATURES)


def build_spec(*, long_count: int = 2, short_count: int = 2, gross_exposure: float = 1.0,
               rebalance_bars: int = 1, atr_multiple: float = 3.0,
               minimum_assets: int | None = None, bar_seconds: int = 3600,
               train_start: datetime = START, atr_feature: str = 'atr_24h',
               signal: str = 'candidate', baseline: str = 'baseline',
               top_n: int = 5000, feature_names: tuple[str, ...] = FEATURES,
               ) -> CandidateSpec:
    minimum = long_count + short_count if minimum_assets is None else minimum_assets
    spec = CandidateSpec.model_validate({
        'candidate_id': 'oracle_case', 'selection_family_id': 'oracle',
        'source_spec_status': 'synthetic_test',
        'thesis': 'Differential allocator qualification fixture; never market evidence.',
        'panel_root': 'unused-synthetic',
        'bar_seconds': bar_seconds,
        'windows': {
            'train': {'start': train_start.isoformat(), 'end': '2025-07-01T00:00:00Z'},
            'validation': {'start': '2025-07-01T00:00:00Z', 'end': '2026-01-01T00:00:00Z'},
            'protected': {'start': '2026-01-01T00:00:00Z', 'end': '2026-04-01T00:00:00Z'},
        },
        'features': [{'name': name, 'expr': {'op': 'col', 'name': 'close'}}
                     for name in feature_names],
        'signal': signal, 'baseline': baseline,
        'universe': {'top_n': max(top_n, long_count + short_count),
                     'minimum_assets': long_count + short_count,
                     'lookback_bars': 1, 'minimum_history_bars': 1},
        'allocation': {'long_count': long_count, 'short_count': short_count,
                       'gross_exposure': gross_exposure, 'rebalance_bars': rebalance_bars,
                       'atr_feature': atr_feature, 'atr_multiple': atr_multiple},
        'costs': {'commission_bps_one_way': 1.0, 'slippage_bps_one_way': 1.0},
        'gates': {'minimum_ic_observations': 3, 'minimum_daily_observations': 10,
                  'minimum_completed_trades': 1},
        'label_horizon_bars': 1,
    })
    if minimum != long_count + short_count:
        # Direct-call equivalence: a smaller minimum is rejected by spec
        # validation, so bypass the validator deliberately to exercise allocate().
        spec = spec.model_copy(update={'universe': spec.universe.model_copy(
            update={'minimum_assets': minimum})})
    return spec


def frame(rows: list[dict[str, Any]], *, unit: str = 'us', tz: str | None = 'UTC',
          overrides: dict[str, Any] | None = None) -> pl.DataFrame:
    if not rows:
        # A production feature panel is always typed, even when it has no rows.
        empty = {'timestamp': pl.Datetime(unit, tz), 'symbol': pl.String,
                 'open': pl.Float64, 'high': pl.Float64, 'low': pl.Float64,
                 'close': pl.Float64, 'volume': pl.Float64,
                 'in_pit_universe': pl.Boolean, 'is_tradable': pl.Boolean,
                 'candidate': pl.Float64, 'baseline': pl.Float64, 'atr_24h': pl.Float64}
        empty.update(overrides or {})
        return pl.DataFrame({name: [] for name in empty}, schema=empty)
    columns: dict[str, Any] = {name: [row.get(name) for row in rows] for name in COLUMNS}
    for row in rows:
        for key in row:
            if key not in columns:
                columns[key] = [other.get(key) for other in rows]
    out = pl.DataFrame(columns)
    schema: dict[str, Any] = {'timestamp': pl.Datetime(unit, tz), 'symbol': pl.String}
    schema.update(overrides or {})
    return out.with_columns(pl.col('timestamp').cast(pl.Datetime(unit, tz))).cast(schema)


def row(ts: datetime, symbol: str, signal: float | None = 0.0, *,
        atr: float | None = 0.01, close: float | None = 100.0,
        pit: bool | None = True, tradable: bool | None = True,
        baseline: float = 0.0, **extra: Any) -> dict[str, Any]:
    return {'timestamp': ts, 'symbol': symbol, 'open': close, 'high': close, 'low': close,
            'close': close, 'volume': 1000.0, 'in_pit_universe': pit,
            'is_tradable': tradable, 'candidate': signal, 'baseline': baseline,
            'atr_24h': atr, **extra}


def cross_section(ts: datetime, specs: list[tuple[str, float, float]],
                  **kwargs: Any) -> list[dict[str, Any]]:
    """``specs`` entries are ``(symbol, signal, atr)``; close stays representative."""
    return [row(ts, symbol, signal, atr=atr, **kwargs) for symbol, signal, atr in specs]


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
        return ('ticks', str(series.dtype), series.to_numpy().astype('int64').tolist())
    if series.dtype == pl.Float64:
        return ('bits', str(series.dtype),
                np.ascontiguousarray(series.to_numpy()).view('uint64').tolist())
    return ('value', str(series.dtype), series.to_numpy().tolist())


def _frame_view(frame: pl.DataFrame) -> dict[str, Any]:
    return {'schema': [(name, str(dtype)) for name, dtype in frame.schema.items()],
            'height': frame.height,
            'columns': {name: _column_bits(frame[name]) for name in frame.columns}}


def compare(case: dict[str, Any]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for key, fn in (('original', case['original']), ('optimized', case['optimized'])):
        try:
            results[key] = {'frame': _frame_view(fn()), 'exception': None}
        except BaseException as exc:  # noqa: BLE001  # exception parity is the subject
            results[key] = {'frame': None, 'exception': _exception(exc)}

    findings: list[dict[str, str]] = []
    left, right = results['original'], results['optimized']
    if (left['exception'] is None) != (right['exception'] is None):
        findings.append({'kind': 'EXC_PRESENCE',
                         'detail': f"original={left['exception']} optimized={right['exception']}"})
    elif left['exception'] is not None:
        if left['exception']['type'] != right['exception']['type']:
            findings.append({'kind': 'EXC_TYPE',
                             'detail': f"{left['exception']['type']} -> {right['exception']['type']}"})
        elif left['exception']['status'] != right['exception']['status']:
            findings.append({'kind': 'EXC_STATUS',
                             'detail': f"{left['exception']['status']} -> {right['exception']['status']}"})
        elif left['exception']['reason'] != right['exception']['reason']:
            findings.append({'kind': 'EXC_MESSAGE',
                             'detail': f"{left['exception']['reason']!r} -> {right['exception']['reason']!r}"})
    else:
        a, b = left['frame'], right['frame']
        if a['schema'] != b['schema']:
            findings.append({'kind': 'SCHEMA', 'detail': f"{a['schema']} -> {b['schema']}"})
        if a['height'] != b['height']:
            findings.append({'kind': 'HEIGHT', 'detail': f"{a['height']} -> {b['height']}"})
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


def _first_diff(left: list[Any], right: list[Any]) -> str:
    for index, (a, b) in enumerate(zip(left, right, strict=False)):
        if a != b:
            return f'index {index}: {a!r} != {b!r}'
    return f'length {len(left)} != {len(right)}'


# --------------------------------------------------------------------------- #
# Cases
# --------------------------------------------------------------------------- #
def cases() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def case(name: str, features: pl.DataFrame, spec: CandidateSpec, *,
             group: str = 'single', divergence: str | None = None,
             **kwargs: Any) -> None:
        out.append({'name': name, 'group': group, 'divergence': divergence,
                    'original': lambda: original(features, spec, **kwargs),
                    'optimized': lambda: optimized_allocate(features, spec, **kwargs)})

    # --- ranking and basket construction -----------------------------------
    t0 = START
    spread = [(f'S{i:02d}', float(20 - i), 0.01) for i in range(12)]
    case('balanced_distinct_signals', frame(cross_section(t0, spread)), build_spec())

    tied_head = [(f'S{i:02d}', 5.0 if i < 4 else float(4 - i), 0.01) for i in range(12)]
    case('head_tie_symbol_ascending', frame(cross_section(t0, tied_head)),
         build_spec(long_count=2, short_count=2))

    tied_tail = [(f'S{i:02d}', float(20 - i) if i < 8 else -5.0, 0.01) for i in range(12)]
    case('tail_tie_symbol_ascending', frame(cross_section(t0, tied_tail)),
         build_spec(long_count=2, short_count=2))

    all_equal = [(f'S{i:02d}', 1.0, 0.01) for i in range(6)]
    case('all_tied_head_and_tail', frame(cross_section(t0, all_equal)),
         build_spec(long_count=2, short_count=3))

    # long+short > minimum_assets is rejected upstream; compare allocate directly.
    case('head_tail_overlap_direct_call', frame(cross_section(t0, all_equal)),
         build_spec(long_count=3, short_count=3, minimum_assets=5),
         group='upstream_rejected')

    case('unequal_counts_long3_short7',
         frame(cross_section(t0, [(f'S{i:02d}', float(20 - i), 0.01) for i in range(20)])),
         build_spec(long_count=3, short_count=7))

    case('gross_exposure_1p5',
         frame(cross_section(t0, [(f'S{i:02d}', float(20 - i), 0.01) for i in range(20)])),
         build_spec(long_count=3, short_count=4, gross_exposure=1.5))

    case('insufficient_eligibility',
         frame([row(t0, f'S{i:02d}', float(i), pit=(i < 3)) for i in range(12)]),
         build_spec(long_count=2, short_count=2))

    case('exactly_minimum_assets',
         frame(cross_section(t0, [(f'S{i:02d}', float(i), 0.01) for i in range(4)])),
         build_spec(long_count=2, short_count=2))

    # --- boolean nulls ------------------------------------------------------
    boolean_null_rows = [row(t0, f'S{i:02d}', float(20 - i)) for i in range(12)]
    boolean_null_rows[0]['is_tradable'] = None
    boolean_null_rows[1]['in_pit_universe'] = None
    boolean_null_rows[2]['is_tradable'] = False
    boolean_null_rows[3]['in_pit_universe'] = False
    case('boolean_nulls', frame(boolean_null_rows), build_spec())

    # --- signal / ATR extremes ---------------------------------------------
    extremes = [row(t0, 'NULL_SIGNAL', None), row(t0, 'NAN_SIGNAL', math.nan),
                row(t0, 'INF_SIGNAL', math.inf), row(t0, 'NEG_INF_SIGNAL', -math.inf),
                row(t0, 'ZERO_SIGNAL', 0.0)]
    extremes += [row(t0, f'OK{i}', float(i)) for i in range(1, 6)]
    case('signal_nulls_and_nonfinite', frame(extremes), build_spec())

    atr_extremes = [row(t0, 'NULL_ATR', 10.0, atr=None), row(t0, 'NAN_ATR', 9.0, atr=math.nan),
                    row(t0, 'INF_ATR', 8.0, atr=math.inf), row(t0, 'NEG_ATR', 7.0, atr=-0.01),
                    row(t0, 'ZERO_ATR', 6.0, atr=0.0), row(t0, 'TINY_ATR', 5.0, atr=1e-300)]
    atr_extremes += [row(t0, f'OK{i}', float(i), atr=0.01) for i in range(1, 7)]
    case('atr_nulls_and_nonpositive', frame(atr_extremes), build_spec())

    # Stop must stay strictly inside (0, 1) for weighted rows.
    spec_1x = build_spec(long_count=1, short_count=1, atr_multiple=1.0)
    case('stop_distance_boundary',
         frame([row(t0, 'AT_LIMIT', 5.0, atr=100.0, close=100.0),
                row(t0, 'JUST_BELOW', 4.0, atr=99.0, close=100.0),
                row(t0, 'JUST_ABOVE', 3.0, atr=101.0, close=100.0),
                row(t0, 'NORMAL', 2.0, atr=10.0, close=100.0),
                row(t0, 'FAR', 1.0, atr=0.5, close=100.0)]),
         spec_1x)

    case('stop_distance_at_or_above_one_raises',
         frame([row(t0, 'AT_LIMIT', 5.0, atr=100.0, close=100.0),
                row(t0, 'NORMAL', 2.0, atr=10.0, close=100.0),
                row(t0, 'FAR', 1.0, atr=0.5, close=100.0)]),
         build_spec(long_count=1, short_count=1, atr_multiple=3.0))

    # --- close edge values --------------------------------------------------
    close_edges = [row(t0, 'ZERO_CLOSE', 5.0, atr=0.01, close=0.0),
                   row(t0, 'NEG_CLOSE', 4.0, atr=0.01, close=-1.0),
                   row(t0, 'NULL_CLOSE', 3.0, atr=0.01, close=None),
                   row(t0, 'TINY_CLOSE', 2.0, atr=1e-320, close=1e-300)]
    close_edges += [row(t0, f'OK{i}', float(i), atr=0.01, close=100.0) for i in range(4)]
    case('close_nonpositive_and_null', frame(close_edges), build_spec())

    # --- empty / unscheduled ------------------------------------------------
    case('empty_frame', frame([]), build_spec())
    case('no_scheduled_timestamps',
         frame([row(t0 + timedelta(minutes=30), f'S{i:02d}', float(i), atr=0.01)
                for i in range(6)]), build_spec(bar_seconds=3600, rebalance_bars=1))

    # --- cadence ------------------------------------------------------------
    hourly = [row(t0 + timedelta(hours=h), f'S{i:02d}', float(100 - i - h), atr=0.01)
              for h in range(6) for i in range(6)]
    case('cadence_1h_aligned', frame(hourly), build_spec(bar_seconds=3600, rebalance_bars=1))
    case('cadence_daily_24', frame([row(t0 + timedelta(hours=h), f'S{i:02d}',
                                        float(100 - i - (h % 3)), atr=0.01)
                                    for h in range(72) for i in range(6)]),
         build_spec(bar_seconds=3600, rebalance_bars=24))
    case('cadence_offset_start_15m',
         frame([row(t0 + timedelta(minutes=15 * step), f'S{i:02d}',
                    float(100 - i - (step % 2)), atr=0.01)
                for step in range(12) for i in range(6)]),
         build_spec(bar_seconds=900, rebalance_bars=4))
    case('cadence_anchor_before_data',
         frame([row(t0 + timedelta(hours=h), f'S{i:02d}', float(100 - i - h), atr=0.01)
                for h in range(6) for i in range(6)]),
         build_spec(bar_seconds=3600, rebalance_bars=2))

    # --- timezone and time-unit precision ----------------------------------
    berlin = [row((t0 + timedelta(hours=h)).astimezone(
        datetime(2025, 1, 1, tzinfo=UTC).tzinfo), f'S{i:02d}', float(100 - i), atr=0.01)
        for h in range(3) for i in range(6)]
    case('timezone_utc_micro', frame(berlin, unit='us'), build_spec())
    case('timezone_utc_nanoseconds', frame(berlin, unit='ns'), build_spec())
    case('timezone_naive_rejected', frame(berlin, unit='us', tz=None), build_spec())
    case('sub_microsecond_timestamps',
         frame([row(t0 + timedelta(microseconds=1), f'S{i:02d}', float(i), atr=0.01)
                for i in range(6)], unit='ns'), build_spec())

    # --- signal override ----------------------------------------------------
    override_rows = [row(t0, f'S{i:02d}', float(20 - i), baseline=float(i), atr=0.01)
                     for i in range(12)]
    case('signal_override', frame(override_rows), build_spec(), signal='baseline')

    # --- duplicate symbols --------------------------------------------------
    duplicate_same_signal = [row(t0, 'DUP', 9.0, atr=0.01), row(t0, 'DUP', 9.0, atr=0.02)]
    duplicate_same_signal += [row(t0, f'S{i:02d}', float(i), atr=0.01) for i in range(8)]
    case('duplicate_symbol_equal_signal', frame(duplicate_same_signal), build_spec())

    duplicate_diff_signal = [row(t0, 'DUP', 9.0, atr=0.01), row(t0, 'DUP', 1.0, atr=0.02)]
    duplicate_diff_signal += [row(t0, f'S{i:02d}', float(i), atr=0.01) for i in range(8)]
    case('duplicate_symbol_unequal_signal', frame(duplicate_diff_signal), build_spec())

    duplicate_split = [row(t0, 'DUP', 30.0, atr=0.01), row(t0, 'DUP', -30.0, atr=0.02)]
    duplicate_split += [row(t0, f'S{i:02d}', float(i), atr=0.01) for i in range(8)]
    case('duplicate_symbol_head_and_tail', frame(duplicate_split),
         build_spec(long_count=1, short_count=1))

    duplicate_ineligible_twin = [row(t0, 'DUP', 9.0, atr=0.01),
                                 row(t0, 'DUP', 9.0, atr=None)]
    duplicate_ineligible_twin += [row(t0, f'S{i:02d}', float(i), atr=0.01) for i in range(8)]
    case('duplicate_symbol_ineligible_twin', frame(duplicate_ineligible_twin),
         build_spec(long_count=1, short_count=1),
         divergence={'exact_kinds': ('EXC_TYPE',),
                     'expected': 'TypeError -> QuantError(INVALID_ALLOCATION)',
                     'why': 'the former loop raised TypeError on a None ATR for a '
                            'weighted row; the pipeline raises the module contract. '
                            'Both abort; only the exit class differs.'})

    duplicate_all = [row(t0, 'DUP', 9.0, atr=0.01), row(t0, 'DUP', 8.0, atr=0.01)]
    duplicate_all += [row(t0, f'S{i:02d}', float(i), atr=0.01) for i in range(2)]
    case('duplicate_symbol_neutrality', frame(duplicate_all),
         build_spec(long_count=2, short_count=2, minimum_assets=4))

    # --- input dtypes -------------------------------------------------------
    int_rows = cross_section(t0, [(f'S{i:02d}', float(20 - i), 0.01) for i in range(12)])
    for name in ('candidate', 'atr_24h', 'close'):
        for entry in int_rows:
            entry[name] = round(entry[name] * 1000)
    case('dtype_int64', frame(int_rows, overrides={'candidate': pl.Int64,
                                                  'atr_24h': pl.Int64, 'close': pl.Int64}),
         build_spec())
    case('dtype_float32', frame(cross_section(t0, [(f'S{i:02d}', float(20 - i), 0.01)
                                                   for i in range(12)]),
                                overrides={'candidate': pl.Float32, 'atr_24h': pl.Float32,
                                           'close': pl.Float32}),
         build_spec())
    case('dtype_float32_near_boundary',
         frame([row(t0, 'NEAR', 5.0, atr=33.333334, close=100.0),
                row(t0, 'OK', 4.0, atr=0.01, close=100.0),
                row(t0, 'OK2', 3.0, atr=0.01, close=100.0),
                row(t0, 'OK3', 2.0, atr=0.01, close=100.0)],
               overrides={'candidate': pl.Float32, 'atr_24h': pl.Float32, 'close': pl.Float32}),
         build_spec(long_count=1, short_count=1))

    # --- feature-name aliases ----------------------------------------------
    alias_rows = [row(t0, f'S{i:02d}', float(20 - i), atr=0.01) for i in range(8)]
    case('alias_atr_equals_signal', frame(alias_rows),
         build_spec(atr_feature='candidate', long_count=1, short_count=1))
    case('alias_atr_equals_close',
         frame([row(t0, f'S{i:02d}', float(20 - i), atr=100.0) for i in range(8)]),
         build_spec(atr_feature='close', long_count=1, short_count=1,
                    feature_names=(*FEATURES, 'close')))
    case('alias_signal_equals_close',
         frame([row(t0, f'S{i:02d}', None, atr=0.01) for i in range(8)]),
         build_spec(signal='close', long_count=1, short_count=1,
                    feature_names=(*FEATURES, 'close')))

    # --- error precedence ---------------------------------------------------
    precedence = cross_section(t0, [(f'S{i:02d}', float(20 - i), 0.01) for i in range(8)])
    precedence += [row(t0 + timedelta(hours=1), 'BAD_STOP', 99.0, atr=100.0, close=100.0)]
    precedence += [row(t0 + timedelta(hours=1), f'T{i:02d}', float(i), atr=0.01)
                   for i in range(8)]
    case('error_precedence_stop_vs_neutrality', frame(precedence),
         build_spec(long_count=2, short_count=2))

    # --- multi-timestamp mixture -------------------------------------------
    mixed: list[dict[str, Any]] = []
    for h in range(4):
        pit = h != 2
        mixed += [row(t0 + timedelta(hours=h), f'S{i:02d}', float(20 - i + h), atr=0.01,
                      pit=pit) for i in range(8)]
    case('multi_timestamp_with_empty_section', frame(mixed), build_spec())

    # --- shuffled physical row order ---------------------------------------
    shuffled = list(reversed(cross_section(t0, [(f'S{i:02d}', float(20 - i), 0.01)
                                                for i in range(12)])))
    case('shuffled_row_order', frame(shuffled), build_spec())
    case('shuffled_row_order_two_timestamps',
         frame(list(reversed([row(t0 + timedelta(hours=h), f'S{i:02d}',
                                  float(20 - i + h), atr=0.01)
                              for h in range(2) for i in range(8)]))), build_spec())

    # --- weighted rows reached only through duplicate symbols -----------------
    bad_stop_twin = [row(t0, 'DUP', 9.0, atr=0.01), row(t0, 'DUP', 9.0, atr=100.0)]
    bad_stop_twin += [row(t0, f'S{i:02d}', float(i), atr=0.01) for i in range(8)]
    case('duplicate_symbol_stop_above_one', frame(bad_stop_twin),
         build_spec(long_count=1, short_count=1))

    null_close_twin = [row(t0, 'DUP', 9.0, atr=0.01), row(t0, 'DUP', 9.0, atr=0.01,
                                                           close=None)]
    null_close_twin += [row(t0, f'S{i:02d}', float(i), atr=0.01) for i in range(8)]
    case('duplicate_symbol_weighted_null_close', frame(null_close_twin),
         build_spec(long_count=1, short_count=1),
         divergence={'exact_kinds': ('EXC_TYPE',),
                     'expected': 'TypeError -> QuantError(INVALID_ALLOCATION)',
                     'why': 'same class change as the ATR twin; the former loop divided '
                            'a float by a None close.'})

    # Cross-timestamp ordering of the two rejection paths.
    cross = [row(t0, 'DUP', 9.0, atr=0.01), row(t0, 'DUP', 9.0, atr=100.0)]
    cross += [row(t0, f'S{i:02d}', float(i), atr=0.01) for i in range(8)]
    later = t0 + timedelta(hours=1)
    cross += [row(later, 'NEUT', 9.0), row(later, 'NEUT', -9.0)]
    cross += [row(later, f'T{i:02d}', float(i), atr=0.01) for i in range(8)]
    case('error_precedence_across_timestamps', frame(cross),
         build_spec(long_count=1, short_count=1),
         divergence={'exact_kinds': ('EXC_MESSAGE',),
                     'expected': 'Non-positive or unrepresentable ATR stop -> '
                                 'Market-neutral target failed (same status)',
                     'why': 'the former loop interleaved the stop check with the '
                            'neutrality check per timestamp; the pipeline checks '
                            'neutrality globally first. Both are '
                            'QuantError/INVALID_ALLOCATION.'})

    out.extend(fuzz_cases())
    return out


def _pick(rng: np.random.Generator, pool: list[Any]) -> Any:
    value = rng.choice(pool)
    return None if value is None else float(value)


def fuzz_cases(count: int = 40) -> list[dict[str, Any]]:
    """Seeded random panels: ties, duplicates, nulls, ineligibility, mixed params."""
    out: list[dict[str, Any]] = []
    pool = [0.0, 1.0, 1.0, 2.0, 2.0, -1.0, -2.0, math.nan, math.inf, -math.inf, None]
    atr_pool = [0.01, 0.02, 0.01, None, math.nan, 0.0, -0.01, math.inf, 100.0]
    for seed in range(count):
        rng = np.random.default_rng(10_000 + seed)
        symbols = int(rng.integers(4, 11))
        bars = int(rng.integers(1, 5))
        long_count = int(rng.integers(1, 4))
        short_count = int(rng.integers(1, 4))
        minimum = max(long_count + short_count, int(rng.integers(1, symbols + 1)))
        gross = float(rng.choice([1.0, 0.5, 1.5]))
        atr_multiple = float(rng.choice([1.0, 2.0, 3.0]))
        rebalance = int(rng.integers(1, 3))
        rows: list[dict[str, Any]] = []
        for bar in range(bars):
            ts = START + timedelta(hours=bar * 3600)
            names = [f'S{index:02d}' for index in range(symbols)]
            if rng.random() < 0.25:
                names.append(str(rng.choice(names)))
            for name in names:
                rows.append(row(
                    ts, name,
                    None if rng.random() < 0.08 else _pick(rng, pool),
                    atr=(None if rng.random() < 0.08 else _pick(rng, atr_pool)),
                    close=float(rng.choice([100.0, 100.0, 50.0, 1e-6])),
                    pit=None if rng.random() < 0.05 else bool(rng.random() > 0.1),
                    tradable=None if rng.random() < 0.05 else bool(rng.random() > 0.1),
                    baseline=_pick(rng, pool[:6]),
                ))
        spec = build_spec(long_count=long_count, short_count=short_count,
                          gross_exposure=gross, atr_multiple=atr_multiple,
                          minimum_assets=minimum, rebalance_bars=rebalance,
                          top_n=max(symbols, minimum))
        features = frame(rows)
        out.append({'name': f'fuzz_{seed:02d}', 'group': 'fuzz',
                    'original': lambda f=features, s=spec: original(f, s),
                    'optimized': lambda f=features, s=spec: optimized_allocate(f, s)})
    return out


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
original: Callable[..., pl.DataFrame]


def main() -> int:
    global original
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', default=DEFAULT_REF)
    parser.add_argument('--json', type=Path, default=None)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        original, identity = extract_original(args.ref, Path(tmp) / 'legacy_allocator.py')
        results = [compare(case) for case in cases()]

    failed = [item for item in results if item['status'] == 'FAIL']
    expected = [item for item in results if item['status'] == 'EXPECTED_DIFF']
    for item in results:
        if item['status'] == 'EXPECTED_DIFF':
            kinds = ','.join(sorted({finding['kind'] for finding in item['findings']}))
            print(f"DIFF {item['name']:<40} [{kinds}] documented: "
                  f"{item['divergence']['expected']}")
        if item['status'] == 'FAIL':
            kinds = ','.join(sorted({finding['kind'] for finding in item['findings']}))
            print(f"FAIL {item['name']:<40} [{kinds}]")
            for finding in item['findings']:
                print(f"       {finding['kind']}: {finding['detail']}")
            original_exc = item['original']['exception']
            optimized_exc = item['optimized']['exception']
            if original_exc or optimized_exc:
                print(f'       original={original_exc}')
                print(f'       optimized={optimized_exc}')
        else:
            expectation = 'rejected' if item['original']['exception'] else 'emitted'
            print(f"PASS {item['name']:<40} {expectation}")
    total = len(results)
    identical = total - len(failed) - len(expected)
    print(f'\n{identical}/{total} cases identical to the pinned original; '
          f'{len(expected)} documented divergence(s); {len(failed)} unexplained failure(s)')
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({'original': identity, 'results': results,
                                         'identical': identical,
                                         'documented_divergences': len(expected),
                                         'unexplained_failures': len(failed),
                                         'total': total},
                                        indent=2, sort_keys=True) + '\n')
        print(f'report: {args.json}')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
