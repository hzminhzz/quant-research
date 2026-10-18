"""Fixed ATS-7 regression gate with durable logs, never an agent or research run."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from src.connectors_bootstrap import ensure_connectors

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = (
    "test_ats*.py", "test_dual_mode_*.py", "test_m8*.py",
    "test_native_execution.py", "test_run_permit.py", "test_attempts.py",
    "test_research_control.py", "test_agent_efficiency.py", "test_market_scope_policy.py",
    "test_managed_feature_policy.py", "test_managed_rebuild.py",
    "test_rebuild_qualification_guard.py", "test_phase3_signal_evidence_policy.py",
    "test_legacy_archive_safety.py", "test_point_in_time_alignment.py", "test_market_time.py",
)
TASK_FILES = (
    "src/release_contracts.py", "src/release_journal.py", "src/release_runtime.py",
    "src/release_probe.py", "src/ml4t_native_metrics.py", "src/research_control/ats3_bybit_archive.py",
)


def save(path, data):
    with path.open("x") as out:
        json.dump(data, out, sort_keys=True, indent=2)
        out.flush()
        os.fsync(out.fileno())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--detach", action="store_true")
    parser.add_argument("--output-root", type=Path, default=ROOT / "run_log/ats7/regressions")
    args = parser.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    connector_path = ensure_connectors()
    extra_pp = f":{connector_path}" if connector_path else ""
    env = {"PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin",
           "PYTHONPATH": str(ROOT) + extra_pp,
           "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "POLARS_MAX_THREADS": "2"}
    # ATS-2 tests exercise existing systemd user scopes. Preserve only these
    # session prerequisites; the separate ATS-6 shadow worker still clears all.
    env.update({k: os.environ[k] for k in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")
                if k in os.environ})
    if args.detach:
        path = args.output_root / (datetime.now(UTC).strftime("launch-%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8] + ".log")
        with path.open("x") as out:
            child = subprocess.Popen([sys.executable, "-m", "scripts.ats7_regression",
                                      "--output-root", str(args.output_root.resolve())],
                                     cwd=ROOT, env=env, start_new_session=True,
                                     stdout=out, stderr=subprocess.STDOUT)
        print(json.dumps({"pid": child.pid, "log": str(path)}, sort_keys=True))
        return 0
    run = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8])
    run.mkdir(exist_ok=False)
    tests = sorted({str(p.relative_to(ROOT)) for pattern in PATTERNS
                    for p in (ROOT / "tests").glob(pattern)})
    lint = sorted(set(TASK_FILES) | {str(p.relative_to(ROOT)) for pattern in
                  ("scripts/ats7_*.py", "tests/test_ats7*.py") for p in ROOT.glob(pattern)})
    commands = {
        "pytest": [sys.executable, "-m", "pytest", "-v", "-n", "0", "-rs", *tests,
                   "--junitxml=" + str(run / "pytest.xml")],
        "managed_ruff": [sys.executable, "-m", "ruff", "check", "--config",
                         "scripts/ruff-managed.toml", "src/managed_strategies"],
        "managed_policy": [sys.executable, "scripts/check_managed_features.py"],
        "task_ruff": [sys.executable, "-m", "ruff", "check", *lint],
        "diff_check": ["git", "diff", "--check"],
    }
    save(run / "plan.json", {"commands": commands, "environment": env,
                             "source_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
                                               for p in lint}})
    result = {}
    print("evidence=" + str(run), flush=True)
    for name, command in commands.items():
        with (run / (name + ".log")).open("x") as out:
            completed = subprocess.run(command, cwd=ROOT, env=env, stdout=out,
                                       stderr=subprocess.STDOUT, check=False)
        result[name] = {"exitcode": completed.returncode,
                        "status": "PASS" if completed.returncode == 0 else "FAIL"}
        print(name + ": " + result[name]["status"], flush=True)
    save(run / "result.json", result)
    return 0 if all(r["exitcode"] == 0 for r in result.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
