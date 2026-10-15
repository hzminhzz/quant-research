"""Linux development-only worker: no raw store, holdout files or network mount.

This confines a callback process, not the owner's entire notebook/host. Inputs
are explicitly supplied by the parent. A malicious parent can serialize data in
code or alter the worker, so this is not a security claim against the host owner.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import cloudpickle
import polars as pl

from .common import QuantError, beneath, file_hash


class SerializedFeature:
    """An explicit hashed callable artifact, deserialized only inside the worker."""
    def __init__(self, blob: bytes):
        self.blob = blob

    def __call__(self, panel):
        return cloudpickle.loads(self.blob)(panel)


def feature_function(spec):
    from .feature_compiler import FeatureCompiler
    artifact = spec.python_feature_artifact
    if artifact is None:
        return FeatureCompiler(spec)
    path = beneath(spec._base_dir, artifact.path, must_exist=True)
    if file_hash(path) != artifact.sha256:
        raise QuantError('INVALID_EVIDENCE', 'Exported Python feature artifact changed')
    return SerializedFeature(path.read_bytes())


def isolated_features(panel: pl.DataFrame, feature_fn: Callable[[pl.DataFrame], pl.DataFrame],
                      *, timeout: int = 120) -> pl.DataFrame:
    if shutil.which('bwrap') is None:
        raise QuantError('ISOLATION_UNAVAILABLE', 'Bubblewrap is required for an untrusted callback')
    source = Path(__file__).resolve().parents[1]
    prefix = Path(sys.prefix).resolve()
    executable = Path(sys.executable).resolve()
    interpreter_home = executable.parent.parent
    with tempfile.TemporaryDirectory(prefix='quant-worker-') as temporary:
        work = Path(temporary)
        input_dir, output_dir = work / 'input', work / 'output'
        input_dir.mkdir(); output_dir.mkdir()
        panel.write_ipc(input_dir / 'panel.arrow')
        (input_dir / 'callback.pkl').write_bytes(cloudpickle.dumps(feature_fn))
        command = ['bwrap', '--unshare-all', '--die-with-parent', '--new-session',
                   '--clearenv', '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp']
        for system in ('/usr', '/lib', '/lib64'):
            if Path(system).exists():
                command += ['--ro-bind', system, system]
        # Bind only the runtime, not home/project parents or the raw data root.
        roots = sorted({str(prefix), str(interpreter_home)}, key=len)
        bound = []
        for root in roots:
            if not any(Path(root).is_relative_to(p) for p in bound):
                command += ['--ro-bind', root, root]
                bound.append(Path(root))
        python_path = '/workspace:' + ':'.join(str(p) for p in prefix.glob('lib/python*/site-packages'))
        command += ['--dir', '/workspace', '--ro-bind', str(source), '/workspace/src',
                    '--ro-bind', str(input_dir), '/input', '--bind', str(output_dir), '/output',
                    '--setenv', 'PYTHONPATH', python_path, '--setenv', 'PYTHONDONTWRITEBYTECODE', '1',
                    '--setenv', 'POLARS_MAX_THREADS', '2', '--setenv', 'OPENBLAS_NUM_THREADS', '1',
                    '--chdir', '/workspace', str(executable), '-B', '-m', 'src.engine.isolated_worker']
        try:
            run = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise QuantError('INVALID_FEATURE', 'Isolated feature deadline exceeded') from exc
        status_file = output_dir / 'status.json'
        if not status_file.exists():
            raise QuantError('ISOLATION_UNAVAILABLE', f'Worker failed before evidence: {run.stderr[-2000:]}')
        status = json.loads(status_file.read_text())
        if status.get('status') != 'PASS' or run.returncode != 0:
            raise QuantError('INVALID_FEATURE', f"Isolated callback: {status.get('error', run.stderr[-1000:])}")
        result = output_dir / 'result.arrow'
        if result.is_symlink() or not result.is_file() or result.stat().st_size > 2 * 1024**3:
            raise QuantError('INVALID_FEATURE', 'Worker result is missing, escaped or exceeds 2 GiB')
        return pl.read_ipc(result, memory_map=False)
