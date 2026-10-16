"""Kernel-enforced per-attempt memory containment for ATS-2 native workers.

Linux cgroup v2 / systemd user scopes are mandatory. There is no RSS-only
fallback: all processes in a scope share memory.max and memory.swap.max.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

_CGROUP_ROOT = Path("/sys/fs/cgroup")
_TASKS = 128
_PROPS = (
    "LoadState", "ActiveState", "Result", "ControlGroup", "MemoryMax",
    "MemorySwapMax", "MemoryPeak", "TasksMax",
)


def supported() -> bool:
    """Preflight only. Admission still needs an observed matching live scope."""
    try:
        controllers = (_CGROUP_ROOT / "cgroup.controllers").read_text().split()
        return (os.name == "posix" and "memory" in controllers and
                shutil.which("systemd-run") is not None and
                shutil.which("systemctl") is not None and
                (_CGROUP_ROOT / "cgroup.procs").is_file())
    except OSError:
        return False


def unit_for_attempt(attempt_id: str) -> str:
    if not re.fullmatch(r"[0-9a-f-]{36}", attempt_id):
        raise ValueError("INVALID_RESOURCE_ATTEMPT_ID")
    return "ats2-" + attempt_id.replace("-", "") + ".scope"


def scoped_command(unit: str, memory_mb: int, command: list[str]) -> list[str]:
    if not supported():
        raise RuntimeError("HARD_MEMORY_ISOLATION_UNAVAILABLE")
    if not re.fullmatch(r"ats2-[0-9a-f]{32}\.scope", unit):
        raise ValueError("RESOURCE_SCOPE_NAME_INVALID")
    if isinstance(memory_mb, bool) or not isinstance(memory_mb, int) or memory_mb <= 0:
        raise ValueError("RESOURCE_MEMORY_INVALID")
    if not command or any(not part for part in command):
        raise ValueError("RESOURCE_COMMAND_INVALID")
    return [
        "systemd-run", "--user", "--scope", "--quiet", "--unit=" + unit,
        "-p", "MemoryAccounting=yes",
        "-p", f"MemoryMax={memory_mb}M", "-p", "MemorySwapMax=0",
        "-p", f"TasksMax={_TASKS}", "-p", "OOMPolicy=kill",
        "--", *command,
    ]


def unit_properties(unit: str) -> dict[str, str] | None:
    if not re.fullmatch(r"ats2-[0-9a-f]{32}\.scope", unit):
        return None
    try:
        query = ["systemctl", "--user", "show", unit]
        for prop in _PROPS:
            query += ["-p", prop]
        result = subprocess.run(
            query, capture_output=True, text=True, timeout=4, check=False,
        )
        if result.returncode:
            return None
        return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def sample_scope(unit: str, memory_mb: int) -> dict[str, Any] | None:
    """Require the actual kernel cgroup limit and zero swap, not unit arguments."""
    props = unit_properties(unit)
    if not props or props.get("LoadState") != "loaded" or props.get("ActiveState") != "active":
        return None
    group = props.get("ControlGroup", "")
    if not group.startswith("/") or ".." in Path(group).parts or not group.endswith("/" + unit):
        return None
    if f"user-{os.getuid()}.slice" not in group.split("/"):
        return None
    path = _CGROUP_ROOT / group.lstrip("/")
    try:
        if (path.is_symlink() or path.resolve().parent != path.parent.resolve() or
            _CGROUP_ROOT not in path.resolve().parents):
            return None
        max_bytes = int((path / "memory.max").read_text().strip())
        swap_bytes = int((path / "memory.swap.max").read_text().strip())
        tasks = int((path / "pids.max").read_text().strip())
        events = dict(row.split() for row in (path / "memory.events").read_text().splitlines())
        peak = int((path / "memory.peak").read_text().strip())
        current = int((path / "memory.current").read_text().strip())
        cpu = dict(row.split() for row in (path / "cpu.stat").read_text().splitlines())
        if (max_bytes != memory_mb * 1024 * 1024 or swap_bytes != 0 or
            tasks != _TASKS or int(props.get("MemoryMax", "-1")) != max_bytes or
            int(props.get("MemorySwapMax", "-1")) != 0 or
            int(props.get("TasksMax", "-1")) != _TASKS):
            return None
        return {
            "unit": unit, "cgroup": group, "memory_max_bytes": max_bytes,
            "memory_swap_max_bytes": swap_bytes, "pids_max": tasks,
            "memory_current_bytes": current, "memory_peak_bytes": peak,
            "memory_events": {k: int(v) for k, v in events.items()},
            "cpu_usage_usec": int(cpu.get("usage_usec", "0")),
            "kernel_enforced": True,
        }
    except (OSError, TypeError, ValueError):
        return None


def final_scope(unit: str) -> dict[str, Any]:
    """A dead OOM scope remains queryable as Result=oom-kill on this host."""
    props = unit_properties(unit)
    if not props:
        return {"unit": unit, "result": "UNKNOWN", "active_state": "UNKNOWN"}
    if props.get("LoadState") == "not-found":
        # A collected unit is not, by itself, proof that the worker ever ran.
        # The ATS caller also requires a previously sampled live kernel cgroup
        # and a clean systemd-run exit before accepting native output.
        return {"unit": unit, "result": "COLLECTED", "active_state": "inactive",
                "load_state": "not-found"}
    if props.get("LoadState") != "loaded":
        return {"unit": unit, "result": "UNKNOWN", "active_state": "UNKNOWN"}
    return {
        "unit": unit, "result": props.get("Result", "UNKNOWN"),
        "active_state": props.get("ActiveState", "UNKNOWN"),
        "load_state": props["LoadState"],
        "memory_max": props.get("MemoryMax", "UNKNOWN"),
        "memory_swap_max": props.get("MemorySwapMax", "UNKNOWN"),
        "memory_peak": props.get("MemoryPeak", "UNKNOWN"),
    }


def wait_terminal(unit: str, *, timeout: float = 4.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        state = final_scope(unit)
        if state["active_state"] in ("inactive", "failed"):
            return state
        if time.monotonic() >= deadline:
            return state
        time.sleep(0.05)


def kill_scope(unit: str) -> bool:
    """Kill the whole transient scope, including descendants and swapped tasks."""
    if not re.fullmatch(r"ats2-[0-9a-f]{32}\.scope", unit):
        return False
    try:
        result = subprocess.run(
            ["systemctl", "--user", "kill", "--kill-whom=all",
             "--signal=SIGKILL", unit],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
