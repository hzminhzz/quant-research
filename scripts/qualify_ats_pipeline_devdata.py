"""Development-only end-to-end timing of the ATS cross-sectional pipeline.

Measures the phases a cross-sectional ATS candidate actually pays for, in the
order the shared Workbench/factory code pays them:

    vault load -> feature compile + prefix-invariance checks -> stage-2
    diagnostics -> cross-sectional allocation

and repeats only the allocation phase in both implementations (head worktree vs
the pinned pre-change source) inside one process, interleaved, so the comparison
differs in nothing but the allocator.

Scope and honest limits:

* Only certified development partitions are opened. ``DataVault.load`` clips its
  upper endpoint at ``protected_test_start`` and never opens a protected file.
* No holdout claim is reserved, no Stage-4 path runs, and no factory gate is
  touched.
* Native order simulation is **not** measured here: these vaults carry no
  execution-qualified cost/carry adapter, and the repository forbids a native
  backtest on a price-only source. Repository throughput per hour is therefore
  not established by this script, and allocator speedup must not be extrapolated
  into candidates or strategies per hour.

Usage:

    PY=/home/quant/dev/quant/quant-research/.venv/bin/python
    PYTHONPATH=$PWD $PY -B scripts/qualify_ats_pipeline_devdata.py \
        --panel-root /path/to/dev/vault \
        --start 2023-10-01T00:00:00Z --end 2024-04-01T00:00:00Z \
        --json .workspace/pr89/pipeline_devdata.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from qualify_ats_allocator_equivalence import DEFAULT_REF, extract_original

from src.engine.signal_allocator import allocate as head_allocate
from src.engine.spec_parser import CandidateSpec
from src.workbench import Workbench

DEFAULT_CANDIDATE = ROOT / 'config/candidates/crypto_xs_funding_velocity_dislocation_basket_v1.example.yaml'


def _code_identity() -> dict[str, Any]:
    import hashlib
    import subprocess

    sys.path.insert(0, str(ROOT))
    from src.engine.common import runtime_identity

    def git(*args: str) -> str:
        return subprocess.run(['git', '-C', str(ROOT), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    return {'head_sha': git('rev-parse', 'HEAD'),
            'branch': git('rev-parse', '--abbrev-ref', 'HEAD'),
            'dirty': bool(git('status', '--porcelain')),
            'code_hash': runtime_identity(),
            'uv_lock_sha256': hashlib.sha256((ROOT / 'uv.lock').read_bytes()).hexdigest(),
            'allocator_sha256': hashlib.sha256(
                (ROOT / 'src/engine/signal_allocator.py').read_bytes()).hexdigest()}


def _environment() -> dict[str, Any]:
    import os
    import platform

    import numpy as np

    cpu = 'unknown'
    try:
        with open('/proc/cpuinfo', encoding='utf-8') as handle:
            cpu = next(line.split(':', 1)[1].strip() for line in handle
                       if line.startswith('model name'))
    except (OSError, StopIteration):
        pass
    return {'python': platform.python_version(), 'polars': pl.__version__,
            'numpy': np.__version__, 'platform': platform.platform(), 'cpu_model': cpu,
            'polars_threads': pl.thread_pool_size(), 'cpu_count': os.cpu_count(),
            'polars_max_threads_env': os.environ.get('POLARS_MAX_THREADS'),
            'loadavg_1_5_15': os.getloadavg()}


def _timed(fn, *args, **kwargs) -> tuple[Any, float]:
    start = time.perf_counter()
    value = fn(*args, **kwargs)
    return value, (time.perf_counter() - start) * 1e3


def _fingerprint(frame: pl.DataFrame) -> str:
    import hashlib

    digest = hashlib.sha256()
    digest.update(repr([(name, str(dtype)) for name, dtype in frame.schema.items()]).encode())
    digest.update(str(frame.height).encode())
    for name in frame.columns:
        series = frame[name]
        digest.update(name.encode())
        if series.dtype == pl.String:
            for value in series.to_list():
                encoded = value.encode('utf-8')
                digest.update(len(encoded).to_bytes(8, 'big'))
                digest.update(encoded)
        elif series.dtype == pl.Datetime:
            digest.update(series.to_numpy().astype('int64').tobytes())
        elif series.dtype == pl.Float64:
            import numpy as np

            digest.update(np.ascontiguousarray(series.to_numpy()).view('uint64').tobytes())
        else:
            digest.update(series.to_numpy().tobytes())
    return digest.hexdigest()


def load_spec(candidate: Path, panel_root: Path) -> CandidateSpec:
    payload = yaml.safe_load(candidate.read_text(encoding='utf-8'))
    payload['panel_root'] = str(panel_root)
    return CandidateSpec.model_validate(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--panel-root', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument('--start', default='2023-10-01T00:00:00Z')
    parser.add_argument('--end', default='2024-04-01T00:00:00Z')
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--original-ref', default=DEFAULT_REF)
    parser.add_argument('--run-log', type=Path, default=ROOT / '.workspace/pr89/run_log')
    parser.add_argument('--json', type=Path, default=None)
    args = parser.parse_args()

    spec = load_spec(args.candidate, args.panel_root)
    report: dict[str, Any] = {
        'scope': 'certified development partitions only; no holdout claim; no native simulation',
        'candidate': str(args.candidate), 'panel_root': str(args.panel_root),
        'window': {'start': args.start, 'end': args.end},
        'spec_hash': spec.spec_hash,
        'allocation': spec.allocation.model_dump(mode='json'),
        'universe': spec.universe.model_dump(mode='json'),
        'generated_at': datetime.now(UTC).isoformat(),
        'code_identity': _code_identity(),
        'environment': _environment(),
    }

    workbench = Workbench(spec, run_log=args.run_log)
    report['vault'] = {'protected_test_start': workbench._vault.protected_test_start.isoformat(),
                       'manifest_hash': workbench._vault.manifest_hash,
                       'quality_summary': workbench._vault.manifest.get('quality_summary')}

    panel, load_ms = _timed(workbench.load, start=args.start, end=args.end)
    report['phases_ms'] = {'vault_load': load_ms}
    report['panel'] = {'rows': panel.height, 'symbols': panel['symbol'].n_unique(),
                       'first': panel['timestamp'].min().isoformat(),
                       'last': panel['timestamp'].max().isoformat()}

    features, features_ms = _timed(workbench.features)
    report['phases_ms']['features_including_prefix_checks'] = features_ms
    report['features'] = {'rows': features.height, 'columns': features.width,
                          'sha256': _fingerprint(features),
                          'input_panel_sha256': _fingerprint(panel)}

    diagnostics, diagnostics_ms = _timed(workbench.ic)
    report['phases_ms']['stage2_diagnostics'] = diagnostics_ms
    report['stage2'] = {'status': diagnostics['report'].get('status')}

    # Interleaved allocator comparison on the real feature panel. Every repeat of
    # every implementation is fingerprinted: a stable median over unstable outputs
    # is not evidence.
    with tempfile.TemporaryDirectory() as tmp:
        original, identity = extract_original(args.original_ref,
                                              Path(tmp) / 'legacy_allocator.py')
        report['original_identity'] = identity
        timings: dict[str, list[float]] = {'original': [], 'head': []}
        digests: dict[str, list[str]] = {'original': [], 'head': []}
        for _ in range(args.repeats):
            for name, fn in (('original', original), ('head', head_allocate)):
                targets, elapsed = _timed(fn, features, spec)
                timings[name].append(elapsed)
                digests[name].append(_fingerprint(targets))
        deterministic = {name: len(set(values)) == 1 for name, values in digests.items()}
        identical = digests['original'][0] == digests['head'][0]
        report['allocate'] = {
            name: {'times_ms': [round(value, 3) for value in values],
                   'median_ms': round(statistics.median(values), 3),
                   'min_ms': round(min(values), 3),
                   'stdev_ms': round(statistics.stdev(values), 3) if len(values) > 1 else 0.0,
                   'repeat_sha256': values, 'repeats_identical': deterministic[name]}
            for name, values in timings.items()}
        for name in ('original', 'head'):
            report['allocate'][name]['repeat_sha256'] = digests[name]
        report['allocate']['outputs_identical'] = identical
        report['allocate']['stable'] = all(deterministic.values()) and identical

    targets = head_allocate(features, spec)
    report['targets'] = {
        'rows': targets.height,
        'scheduled_sections': targets['timestamp'].n_unique(),
        'weighted_rows': int((targets['target_weight'] != 0).sum()),
        'symbols_weighted': targets.filter(pl.col('target_weight') != 0)['symbol'].n_unique(),
        'max_abs_section_sum': float(targets.group_by('timestamp')
                                     .agg(pl.col('target_weight').sum())['target_weight']
                                     .abs().max() or 0.0),
    }

    # These are NOT a measured end-to-end run and NOT a throughput figure: they add
    # the once-measured phases to the allocator median of the corresponding
    # implementation. Load/features/diagnostics are measured once, so their share
    # carries a single-run sampling error.
    for name in ('original', 'head'):
        phases = dict(report['phases_ms'])
        phases['allocation'] = report['allocate'][name]['median_ms']
        report[f'composed_estimate_ms_{name}'] = {
            'value': round(sum(phases.values()), 3),
            'basis': 'sum of once-measured phases + allocator median; not a measured run',
            'allocation_share_pct': round(100 * phases['allocation'] / sum(phases.values()), 3),
        }

    for key, value in report.items():
        if key.startswith(('phases_ms', 'allocate', 'targets', 'composed')):
            print(f'{key}: {json.dumps(value, default=str)}')
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + '\n')
        print(f'report: {args.json}')
    if not report['allocate']['outputs_identical']:
        print('REJECT: original and head allocator outputs differ on real features', file=sys.stderr)
        return 1
    if not report['allocate']['stable']:
        print('REJECT: allocator output is not repeat-deterministic on real features',
              file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
