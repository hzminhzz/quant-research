"""Internal development feature worker, launched only in a restricted namespace."""
from __future__ import annotations

import json
import resource
import sys
from pathlib import Path

import cloudpickle
import polars as pl


def main() -> int:
    # CPU seconds accumulate over every Polars worker thread. Parent owns a
    # 600-second WALL-CLOCK deadline and terminates bwrap on expiry.
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    # Virtual address reservations can exceed RSS by a large factor in Arrow.
    # 64 GiB protects gross address exhaustion without an 8-GiB false OOM.
    resource.setrlimit(resource.RLIMIT_AS, (64 * 1024**3, 64 * 1024**3))
    try:
        frame = pl.read_ipc('/input/panel.arrow', memory_map=False)
        callback = cloudpickle.loads(Path('/input/callback.pkl').read_bytes())
        result = callback(frame)
        if not isinstance(result, pl.DataFrame):
            raise TypeError('Feature callback must return a Polars DataFrame')
        result.write_ipc('/output/result.arrow')
        Path('/output/status.json').write_text(json.dumps({'status': 'PASS'}))
        return 0
    except BaseException as exc:  # noqa: BLE001 - subprocess boundary must also record a callback's SystemExit
        Path('/output/status.json').write_text(json.dumps({'status': 'ERROR', 'error': f'{type(exc).__name__}: {exc}'}))
        return 2


if __name__ == '__main__':
    sys.exit(main())
