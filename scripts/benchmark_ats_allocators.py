"""Synthetic, development-only throughput benchmark for the ATS allocators.

This harness is deliberately isolated from any vault, protected window, casefile,
ledger, broker or live order path. It generates deterministic synthetic panels,
runs ``allocate`` / ``allocate_ts`` repeatedly, and reports:

* wall-clock timings (warm-up + fixed repeats, min/median/mean/stdev),
* an exact output fingerprint (schema + bit pattern of every value),
* optional coarse phase timings when the allocator exposes ``phase_timings``.

The fingerprint is the equivalence contract: a refactor may only merge if the
before and after fingerprints are identical for every case.

Usage (installed interpreter, this worktree on PYTHONPATH):

    PY=/home/quant/dev/quant/quant-research/.venv/bin/python
    PYTHONPATH=$PWD $PY -B scripts/benchmark_ats_allocators.py \
        --repeats 5 --json .workspace/perf/after.json

No file outside this worktree is written unless ``--json`` names a path.
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import platform
import statistics
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.engine.signal_allocator import allocate
from src.engine.spec_parser import CandidateSpec
from src.engine.ts_allocator import allocate_ts
from src.engine.ts_spec import TimeSeriesSpec

START = datetime(2025, 1, 1, tzinfo=UTC)
FORBIDDEN_ROOTS = ('/',)


def _panel(symbols: list[str], bars: int, seed: int) -> pl.DataFrame:
    """Deterministic synthetic cross-section; explicitly not market evidence."""
    rng = np.random.default_rng(seed)
    n = len(symbols)
    # Timestamp-major layout, the natural feature-compiler output order.
    timestamps = np.repeat(np.arange(bars, dtype=np.int64) * 3_600_000_000_000,
                           n).astype('datetime64[ns]')
    symbol_index = np.tile(np.arange(n), bars)
    log_returns = rng.normal(0.0, 0.0015, size=(bars, n))
    close = 100.0 * np.exp(np.cumsum(log_returns, axis=0))
    close = close.reshape(-1)  # timestamp-major flatten
    atr = close * rng.uniform(0.002, 0.02, size=bars * n)
    vol = rng.uniform(0.05, 0.8, size=bars * n)
    forecast = rng.normal(0.0, 1.0, size=bars * n)
    candidate = forecast + rng.normal(0.0, 0.4, size=bars * n)
    baseline = rng.normal(0.0, 1.0, size=bars * n)
    tradable = rng.random(bars * n) > 0.02
    in_pit = rng.random(bars * n) > 0.03
    # Exercise the eligibility edge cases without changing the workload shape.
    candidate[rng.random(bars * n) < 0.01] = np.nan
    forecast[rng.random(bars * n) < 0.01] = np.nan
    atr[rng.random(bars * n) < 0.01] = 0.0
    vol[rng.random(bars * n) < 0.01] = -1.0
    # A few rows carry an unrepresentable stop for a 3x ATR protective stop.
    unrepresentable = rng.random(bars * n) < 0.005
    atr[unrepresentable] = close[unrepresentable] * 10.0
    frame = pl.DataFrame({
        'timestamp': pl.Series(timestamps, dtype=pl.Datetime('ns', 'UTC')),
        'symbol': pl.Series([symbols[i] for i in symbol_index], dtype=pl.String),
        'open': close, 'high': close * 1.002, 'low': close * 0.998,
        'close': close, 'volume': 1000.0 + symbol_index,
        'in_pit_universe': in_pit, 'is_tradable': tradable,
        'candidate': candidate, 'baseline': baseline,
        'atr_24h': atr, 'vol_20': vol, 'forecast': forecast,
    })
    return frame.sort('timestamp', 'symbol')


def signal_spec(rebalance_bars: int = 1) -> CandidateSpec:
    return CandidateSpec.model_validate({
        'candidate_id': 'synthetic_perf_signal', 'selection_family_id': 'synthetic_perf',
        'source_spec_status': 'synthetic_test',
        'thesis': 'Synthetic allocator throughput fixture; never market evidence.',
        'panel_root': 'unused-synthetic',
        'windows': {'train': {'start': START.isoformat(), 'end': '2025-07-01T00:00:00Z'},
                    'validation': {'start': '2025-07-01T00:00:00Z', 'end': '2026-01-01T00:00:00Z'},
                    'protected': {'start': '2026-01-01T00:00:00Z', 'end': '2026-04-01T00:00:00Z'}},
        'features': [{'name': name, 'expr': {'op': 'col', 'name': 'close'}}
                     for name in ('candidate', 'baseline', 'atr_24h')],
        'signal': 'candidate', 'baseline': 'baseline',
        'universe': {'top_n': 5000, 'minimum_assets': 10, 'lookback_bars': 1,
                     'minimum_history_bars': 1},
        'allocation': {'long_count': 5, 'short_count': 5, 'gross_exposure': 1.0,
                       'rebalance_bars': rebalance_bars, 'atr_feature': 'atr_24h',
                       'atr_multiple': 3.0},
        'costs': {'commission_bps_one_way': 1.0, 'slippage_bps_one_way': 1.0},
        'gates': {'minimum_ic_observations': 3, 'minimum_daily_observations': 10,
                  'minimum_completed_trades': 1},
        'label_horizon_bars': 1,
    })


def ts_spec(symbols: list[str], rebalance_bars: int = 1) -> TimeSeriesSpec:
    return TimeSeriesSpec.model_validate({
        'spec_kind': 'time_series', 'sleeve_id': 'synthetic_perf_ts',
        'selection_family_id': 'synthetic_perf', 'book_strategy': 6,
        'thesis': 'Synthetic allocator throughput fixture; never market evidence.',
        'market_classes': [{'name': 'indices', 'symbols': symbols,
                            'panel_root': 'unused-synthetic', 'bar_seconds': 3600,
                            'periods_per_year': 252}],
        'windows': {'train': {'start': START.isoformat(), 'end': '2025-07-01T00:00:00Z'},
                    'validation': {'start': '2025-07-01T00:00:00Z', 'end': '2026-01-01T00:00:00Z'},
                    'protected': {'start': '2026-01-01T00:00:00Z', 'end': '2026-04-01T00:00:00Z'}},
        'features': [{'name': name, 'expr': {'op': 'col', 'name': 'close'}}
                     for name in ('forecast_source', 'atr_24h', 'vol_20')],
        'forecast': {'feature': 'forecast_source', 'horizon_bars': 1,
                     'scaling': {'kind': 'bounded_linear', 'scale': 10.0, 'cap': 2.0}},
        'risk_allocation': {'method': 'inverse_volatility', 'per_instrument_cap': 0.2,
                            'gross_exposure': 1.0, 'volatility_feature': 'vol_20'},
        'stops': {'feature': 'atr_24h', 'multiple': 3.0},
        'rebalance_bars': rebalance_bars,
        'costs': {'commission_bps_one_way': 1.0, 'slippage_bps_one_way': 1.0,
                  'spread_bps': 0.5, 'spread_included_in_slippage': True},
        'gates': {'minimum_validation_net_sharpe': 0.0},
    })


def fingerprint(frame: pl.DataFrame) -> dict[str, Any]:
    """Exact bytes: schema identity plus bit patterns, never a rounded digest."""
    digest = hashlib.sha256()
    digest.update(repr([(name, str(dtype)) for name, dtype in frame.schema.items()]).encode())
    digest.update(str(frame.height).encode())
    for name in frame.columns:
        series = frame[name]
        digest.update(name.encode())
        digest.update(str(series.dtype).encode())
        if series.dtype == pl.String:
            for value in series.to_list():
                encoded = value.encode('utf-8')
                digest.update(len(encoded).to_bytes(8, 'big'))
                digest.update(encoded)
        else:
            array = np.ascontiguousarray(series.to_numpy())
            digest.update(str(array.dtype).encode())
            digest.update(array.tobytes())
    return {'sha256': digest.hexdigest(), 'rows': frame.height,
            'columns': list(frame.columns),
            'schema': {name: str(dtype) for name, dtype in frame.schema.items()},
            'timestamp_min': frame['timestamp'].min().isoformat() if frame.height else None,
            'timestamp_max': frame['timestamp'].max().isoformat() if frame.height else None}


def _run(fn: Callable[[dict[str, float] | None], pl.DataFrame], repeats: int,
         warmup: int, timing: bool) -> dict[str, Any]:
    for _ in range(warmup):
        fn(None)
    times: list[float] = []
    phases: list[dict[str, float]] = []
    result: pl.DataFrame | None = None
    for _ in range(repeats):
        timings: dict[str, float] | None = {} if timing else None
        start = time.perf_counter_ns()
        result = fn(timings)
        times.append((time.perf_counter_ns() - start) / 1e6)
        if timings:
            phases.append({key: value * 1e3 for key, value in timings.items()})
    assert result is not None
    digest = fingerprint(result)
    return {
        **digest,
        'repeats': repeats,
        'times_ms': [round(value, 4) for value in times],
        'min_ms': round(min(times), 4),
        'median_ms': round(statistics.median(times), 4),
        'mean_ms': round(statistics.fmean(times), 4),
        'stdev_ms': round(statistics.stdev(times), 4) if len(times) > 1 else 0.0,
        'phase_timings_ms': [dict(sorted(item.items())) for item in phases],
    }


CASES: dict[str, tuple[int, int, int]] = {
    # name: (symbols, bars, rebalance_bars)
    'small': (16, 400, 1),
    'medium': (64, 1500, 1),
    'large': (192, 3000, 1),
    'medium_daily': (64, 1500, 24),
}


def _supports_timing(fn: Callable[..., Any]) -> bool:
    return 'phase_timings' in inspect.signature(fn).parameters


def build_cases(names: list[str]) -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {}
    for name in names:
        symbols_count, bars, cadence = CASES[name]
        symbols = [f'SYMBOL_{index:04d}' for index in range(symbols_count)]
        seed = 17_000 + symbols_count * 101 + bars
        panel = _panel(symbols, bars, seed)
        signal = signal_spec(cadence)
        ts = ts_spec(symbols, cadence)
        signal_timing = _supports_timing(allocate)
        ts_timing = _supports_timing(allocate_ts)

        def run_signal(timings, panel=panel, signal=signal, supported=signal_timing):
            if timings is not None and supported:
                return allocate(panel, signal, phase_timings=timings)
            return allocate(panel, signal)

        def run_ts(timings, panel=panel, ts=ts, supported=ts_timing):
            if timings is not None and supported:
                return allocate_ts(panel, ts, ts.market_classes[0], phase_timings=timings)
            return allocate_ts(panel, ts, ts.market_classes[0])

        cases[f'signal_{name}'] = {
            'fn': run_signal, 'timing_supported': signal_timing,
            'input_rows': panel.height, 'symbols': symbols_count, 'bars': bars,
            'rebalance_bars': cadence,
        }
        cases[f'ts_{name}'] = {
            'fn': run_ts, 'timing_supported': ts_timing,
            'input_rows': panel.height, 'symbols': symbols_count, 'bars': bars,
            'rebalance_bars': cadence,
        }
    return cases


def git_state() -> dict[str, Any]:
    import subprocess
    try:
        sha = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'],
                             check=True, capture_output=True, text=True).stdout.strip()
        dirty = bool(subprocess.run(['git', '-C', str(ROOT), 'status', '--porcelain'],
                                    check=True, capture_output=True, text=True).stdout.strip())
    except Exception:  # noqa: BLE001  # pragma: no cover - diagnostic only
        sha, dirty = 'unknown', None
    return {'sha': sha, 'dirty': dirty}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', default='all',
                        help="comma separated: small,medium,large,medium_daily or 'all'")
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--warmup', type=int, default=1)
    parser.add_argument('--timing', action='store_true',
                        help='request allocator phase timings when exposed')
    parser.add_argument('--json', type=Path, default=None)
    parser.add_argument('--label', default='')
    args = parser.parse_args()
    names = list(CASES) if args.cases == 'all' else args.cases.split(',')
    unknown = [name for name in names if name not in CASES]
    if unknown:
        parser.error(f'unknown cases: {unknown}')

    report: dict[str, Any] = {
        'label': args.label,
        'generated_at': datetime.now(UTC).isoformat(),
        'scope': 'synthetic development-only; no vault, protected window, casefile or broker',
        'git': git_state(),
        'environment': {'python': platform.python_version(), 'polars': pl.__version__,
                        'numpy': np.__version__, 'platform': platform.platform()},
        'repeats': args.repeats, 'warmup': args.warmup, 'timing': args.timing,
        'cases': {},
    }
    failures = 0
    for name, case in build_cases(names).items():
        try:
            result = _run(case['fn'], args.repeats, args.warmup, args.timing and case['timing_supported'])
            result.update({'input_rows': case['input_rows'], 'symbols': case['symbols'],
                           'bars': case['bars'],
                           'rebalance_bars': case['rebalance_bars'],
                           'timing_supported': case['timing_supported']})
            report['cases'][name] = result
            print(f'{name}: input_rows={case["input_rows"]} output_rows={result["rows"]} '
                  f'median={result["median_ms"]:.2f}ms '
                  f'min={result["min_ms"]:.2f}ms fp={result["sha256"][:16]}')
        except Exception as exc:  # noqa: BLE001  # report honestly, continue other cases
            failures += 1
            report['cases'][name] = {'error': f'{type(exc).__name__}: {exc}'}
            print(f'{name}: ERROR {type(exc).__name__}: {exc}', file=sys.stderr)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
        print(f'report: {args.json}')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
