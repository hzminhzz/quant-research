"""Fixed ATS-6 worker and namespace launcher. No broker operations are available."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import sysconfig
from pathlib import Path

from src.shadow_contracts import clock
from src.shadow_router import ShadowRouter


def isolated_command(state_dir: Path):
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise RuntimeError("BUBBLEWRAP_REQUIRED")
    root = Path(__file__).resolve().parents[1]
    prefix, exe = Path(sys.prefix).resolve(), Path(sys.executable).resolve()
    stdlib = Path(sysconfig.get_paths()["stdlib"]).resolve()
    cmd = [bwrap, "--unshare-all", "--die-with-parent", "--new-session", "--clearenv",
           "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    for system in ("/usr", "/lib", "/lib64"):
        if Path(system).exists():
            cmd += ["--ro-bind", system, system]
    for location in dict.fromkeys((prefix, exe.parent, stdlib)):
        cmd += ["--ro-bind", str(location), str(location)]
    # Keep the exact interpreter SQLite/zlib dependencies. Otherwise the loader
    # falls back to /usr/lib and changes the signed runtime identity.
    native_libs = Path(sys.base_prefix).resolve() / "lib"
    for pattern in ("libsqlite3.so*", "libz.so*"):
        for library in sorted(native_libs.glob(pattern)):
            cmd += ["--ro-bind", str(library), str(library)]
    cmd += [
        "--ro-bind", str(root / "src"), "/workspace/src",
        "--ro-bind", str(Path(__file__).resolve()), "/workspace/worker.py",
        "--bind", str(state_dir.resolve()), "/state",
        "--setenv", "PYTHONPATH", "/workspace:" + os.pathsep.join(
            str(p) for p in prefix.glob("lib/python*/site-packages")),
        "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
        "--setenv", "OPENBLAS_NUM_THREADS", "1", "--setenv", "POLARS_MAX_THREADS", "1",
        "--chdir", "/workspace", str(exe), "-B", "/workspace/worker.py", "--request", "/state/request.json",
    ]
    return cmd


def run_request(path: Path):
    request = json.loads(path.read_text())
    if set(request) != {"action", "grant", "epoch", "now", "canary_path", "parent_net_namespace"}:
        raise ValueError("FIXED_WORKER_REQUEST_SCHEMA")
    router = ShadowRouter(path.parent / "router.db")
    now = clock(request["now"])
    admitted = router.admit(request["action"], request["grant"], request["epoch"], now=now)
    route = request["action"]["intent"]["intent_id"]
    dispatched = router.publish(route, admitted["route_revision"], request["epoch"], now=now)
    secret_blocked = False
    try:
        Path(request["canary_path"]).read_bytes()
    except (FileNotFoundError, PermissionError):
        secret_blocked = True
    network_blocked = False
    try:
        with socket.create_connection(("192.0.2.1", 443), timeout=0.1):
            pass
    except OSError:
        network_blocked = True
    proof = {
        "admission": admitted, "publication": dispatched,
        "host_file_inaccessible": secret_blocked, "network_unreachable": network_blocked,
        "inherited_credential_env_absent": "ATS6_ORDER_SECRET_SENTINEL" not in os.environ,
        "separate_network_namespace": os.readlink("/proc/self/ns/net") != request["parent_net_namespace"],
        "broker_imports": sorted(k for k in sys.modules if k.startswith(("connectors", "ccxt"))),
        "recovery": router.recover(),
    }
    (path.parent / "isolation_result.json").write_text(json.dumps(proof, sort_keys=True, indent=2))
    assert admitted["status"] == "ADMITTED" and dispatched["status"] == "SHADOW_DISPATCHED"
    assert secret_blocked and network_blocked and proof["inherited_credential_env_absent"]
    assert proof["separate_network_namespace"] and not proof["broker_imports"]


def main():
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--request", type=Path)
    g.add_argument("--isolated-state", type=Path)
    a = p.parse_args()
    if a.request:
        run_request(a.request)
        return 0
    return subprocess.run(isolated_command(a.isolated_state), check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
