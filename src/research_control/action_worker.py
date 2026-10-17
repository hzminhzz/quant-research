"""Private child entrypoint for one already admitted ATS-2 action."""
from __future__ import annotations

import ctypes
import json
import os
import resource
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PR_SET_PDEATHSIG = 1


def _apply_hard_limits(action_raw: dict[str, Any]) -> None:
    """Apply OS-level limits before any heavy imports. Fails closed."""
    initial_ppid = os.getppid()
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        ret = libc.prctl(PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0)
        if ret != 0:
            raise OSError(ctypes.get_errno(), "prctl PR_SET_PDEATHSIG failed")
        if os.getppid() != initial_ppid:
            os._exit(1)
    except (OSError, AttributeError) as exc:
        raise OSError(f"PARENT_DEATH_SETUP_FAILED: {exc}") from exc

    # Restrict Rust/Tokio/Polars thread count
    os.environ["POLARS_MAX_THREADS"] = "2"
    os.environ["RAYON_NUM_THREADS"] = "2"
    os.environ["TOKIO_WORKER_THREADS"] = "2"

    # 3. Hard CPU limit
    cpu = int(action_raw["max_cpu_seconds"])
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
    # 4. Hard file output limit (64MB)
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024 * 1024, 64 * 1024 * 1024))

    # RLIMIT_AS constrains virtual address space (VmSize), not RSS. 64-bit
    # Polars with jemalloc reserves ~2.3GB virtual arenas while using <55MB
    # RSS. Imposing RLIMIT_AS <= max_memory_mb breaks jemalloc (os error 11).
    # Resident memory is therefore enforced via parent supervisor RSS sampling.


def main(payload_path: str, artifact_dir: str) -> int:
    path = Path(payload_path)
    if path.is_symlink() or not path.is_file():
        return 2
    try:
        request = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return 2
    if not isinstance(request, dict) or set(request) != {"root", "action", "intent"}:
        return 2
    root, action_raw, intent_raw = request["root"], request["action"], request["intent"]

    try:
        _apply_hard_limits(action_raw)
    except (KeyError, ValueError, OSError):
        return 5

    # Heavy imports deferred until AFTER hard resource limits are active
    import polars as pl
    import yaml

    from src.engine.common import beneath
    from src.research_session import _load

    from .ats2 import ActionContractV1
    from .contracts import ResearchContractV1
    from .execution import execute_permitted_native
    from .feature_gateway import FeatureGateway
    from .run_permit import RunIntentV1, preflight_run

    if isinstance(action_raw.get("expected_outputs"), list):
        action_raw["expected_outputs"] = tuple(action_raw["expected_outputs"])
    try:
        action = ActionContractV1.model_validate(action_raw)
    except (ValueError, TypeError, KeyError):
        return 2

    root_path = Path(root).resolve()
    _, frozen = _load(root_path, action.session_id)
    identity_doc = frozen.get("identity", {}) if isinstance(frozen, dict) else {}
    contract_path = identity_doc.get("config", {}).get("path")
    if not contract_path:
        return 6
    contract = ResearchContractV1.model_validate(
        yaml.safe_load(beneath(root_path, contract_path, must_exist=True).read_text())
    )
    data_paths = [item["path"] for item in frozen["spec"]["data"] if item["role"] == "prices"]
    if not data_paths:
        return 6
    data = pl.concat([pl.read_parquet(beneath(root_path, item, must_exist=True))
                      for item in data_paths], how="vertical")
    intent = RunIntentV1.model_validate(intent_raw)
    try:
        params = action.parameters
        computation = FeatureGateway().compute(data, contract)
        gate = preflight_run(str(root_path), intent, computation, data, contract)
        if gate.status != "PASS" or gate.permit is None or gate.permit.permit_sha256 != action.permit_sha256:
            return 7
        audit = execute_permitted_native(
            str(root_path), intent, computation, data, contract,
            signal_at=datetime.fromisoformat(str(params["signal_at"])),
            quantity=float(params["quantity"]), stop_price=float(params["stop_price"]),
            limit_price=float(params["limit_price"]), artifact_dir=artifact_dir,
        )
        return 0 if audit.status == "PASS" else 4
    except (OSError, ValueError, TypeError, KeyError, MemoryError, json.JSONDecodeError):
        return 5


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
