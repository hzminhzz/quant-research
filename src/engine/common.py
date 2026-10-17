"""Small shared evidence/IO primitives; one append-only ledger for both modes."""
from __future__ import annotations

import fcntl
import hashlib
import importlib.metadata
import json
import math
import os
import re
import sys
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any


class QuantError(ValueError):
    def __init__(self, status: str, reason: str):
        super().__init__(reason)
        self.status, self.reason = status, reason


def utc(value: str | date | datetime) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, datetime.min.time(), UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def safe_name(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,159}', value):
        raise QuantError('INVALID_SPEC', 'Identifier must be a safe, nonempty basename')
    return value


def json_bytes(value: Any) -> bytes:
    def default(x: Any) -> Any:
        if isinstance(x, (datetime, date)):
            return x.isoformat()
        if isinstance(x, Path):
            return str(x)
        if hasattr(x, 'item'):
            return x.item()
        raise TypeError(f'Not JSON serializable: {type(x).__name__}')
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), default=default,
                       allow_nan=False) + '\n').encode()


def digest(value: Any) -> str:
    return hashlib.sha256(json_bytes(value)).hexdigest()


def file_hash(path: str | Path) -> str:
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def beneath(root: Path, relative: str | Path, *, must_exist: bool = False) -> Path:
    root = root.resolve()
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts:
        raise QuantError('INVALID_PATH', 'Paths must stay inside their declared root')
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise QuantError('INVALID_PATH', f'Symlink is not allowed: {rel}')
    resolved = current.resolve(strict=must_exist)
    if not resolved.is_relative_to(root):
        raise QuantError('INVALID_PATH', 'Path escaped its root')
    return resolved


def write_json(path: Path, value: Any, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise QuantError('INVALID_PATH', 'Refusing a symlink output')
    data = json_bytes(value)
    if exclusive:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    else:
        fd, temporary = tempfile.mkstemp(prefix='.quant-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def read_json(path: Path) -> Any:
    with path.open(encoding='utf-8') as handle:
        return json.load(handle)


def append_trial(root: Path, event: dict[str, Any]) -> dict[str, Any]:
    """Serialize concurrent writers and retain failures, exposures and retries."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / 'trial_ledger.jsonl'
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a+b') as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        previous = '0' * 64
        for line in handle:
            prior = json.loads(line)
            prior_hash = prior.pop('record_hash')
            if prior.get('previous_hash') != previous or digest(prior) != prior_hash:
                raise QuantError('INVALID_EVIDENCE', 'Trial ledger hash chain is broken')
            previous = prior_hash
        record = {**event, 'recorded_at': datetime.now(UTC).isoformat(), 'previous_hash': previous}
        record['record_hash'] = digest(record)
        handle.write(json_bytes(record))
        handle.flush()
        os.fsync(handle.fileno())
    return record


def runtime_identity() -> str:
    source = Path(__file__).resolve().parents[1]
    paths = sorted(p for folder in ('engine', 'oracle', 'data_vault', 'portfolio')
                   for p in (source / folder).glob('*.py'))
    if (source / 'workbench.py').exists():
        paths.append(source / 'workbench.py')
    versions = {}
    for name in ('polars', 'ml4t-engineer', 'ml4t-diagnostic', 'ml4t-backtest',
                 'cloudpickle', 'numpy', 'scipy', 'pandas', 'pyarrow', 'pydantic', 'exchange-calendars'):
        versions[name] = importlib.metadata.version(name)
    return digest({'code': {str(p.relative_to(source)): file_hash(p) for p in paths},
                   'versions': versions, 'python': sys.version})


def finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise QuantError('INVALID_SPEC', f'{name} must be finite numeric data')
    return float(value)
