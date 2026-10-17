"""Fixed Linux sandbox for the ATS7 public-feed local simulator only."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONNECTOR = Path("/home/quant/.devspace/worktrees/trading-connector-d0370150")
PYTHON = Path("/home/quant/.devspace/worktrees/quant-research-25440f7a/.venv/bin/python")
VENV = PYTHON.parent.parent


def command(run, port, *, probe=False):
    run = run.resolve(strict=True)
    if not run.is_relative_to(Path("/home/quant/.local/state/quant-research/ats7-local")):
        raise ValueError("private ATS7 local state root required")
    cmd = ["/usr/bin/bwrap", "--unshare-all", "--share-net", "--die-with-parent",
           "--new-session", "--cap-drop", "ALL", "--clearenv", "--proc", "/proc",
           "--dev", "/dev", "--tmpfs", "/tmp"]
    for path in (Path("/usr"), Path("/lib"), Path("/lib64"), Path("/etc/ssl"),
                 Path("/etc/resolv.conf"), Path("/etc/hosts"), Path("/etc/nsswitch.conf"),
                 Path("/home/quant/anaconda3/bin"), Path("/home/quant/anaconda3/lib"),
                 ROOT, CONNECTOR, VENV):
        cmd += ["--ro-bind", str(path), str(path)]
    cmd += ["--symlink", "usr/bin", "/bin", "--bind", str(run), str(run),
            "--chdir", str(ROOT), "--setenv", "PATH", str(PYTHON.parent) + ":/usr/bin:/bin",
            "--setenv", "PYTHONPATH", str(ROOT) + ":" + str(CONNECTOR),
            "--setenv", "PYTHONDONTWRITEBYTECODE", "1", "--setenv", "PYTHON_DOTENV_DISABLED", "1",
            "--setenv", "NUMBA_CACHE_DIR", "/tmp/ats7-numba",
            "--setenv", "MPLCONFIGDIR", "/tmp/ats7-matplotlib",
            "--setenv", "OPENBLAS_NUM_THREADS", "1", "--setenv", "OMP_NUM_THREADS", "1",
            "--setenv", "POLARS_MAX_THREADS", "2", str(PYTHON)]
    if probe:
        cmd += ["-c", ("import json,os; from pathlib import Path; from src.release_runtime import LocalNoEffectsBroker; "
                "print(json.dumps({'demo_credentials_visible':Path('/home/quant/.config/trading-connector/bybit-demo.env').exists(),"
                "'host_ssh_visible':Path('/home/quant/.ssh').exists(),"
                "'credential_environment':[k for k in os.environ if k.startswith(('BYBIT_','TELEGRAM_','AWS_','OPENAI_'))],"
                "'local_broker':LocalNoEffectsBroker.__name__}))")]
    else:
        cmd += ["-m", "scripts.ats7_paper", "run", "--run-root", str(run), "--port", str(port)]
    return cmd


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=19149)
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    cmd = command(args.run_root, args.port, probe=args.probe)
    os.execve(cmd[0], cmd, {"PATH": "/usr/bin:/bin"})


if __name__ == "__main__":
    sys.exit(main())
