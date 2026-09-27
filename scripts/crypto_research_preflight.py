#!/usr/bin/env python3
"""Read-only readiness check for the recurring crypto research operator."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import polars as pl
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "config" / "crypto_research.yaml"


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=REPO_ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def resolve_data_root(cfg: dict[str, Any]) -> Path:
    env_name = cfg["data"]["env_override"]
    configured = cfg["data"]["root"]
    return Path(os.environ.get(env_name, configured)).expanduser().resolve()


def parquet_summary(path: Path, holdout_start: str) -> dict[str, Any]:
    ts_col = "timestamp"
    scan = pl.scan_parquet(path)
    schema = scan.collect_schema()
    if ts_col not in schema:
        return {
            "file": path.name,
            "status": "SKIP_NO_TIMESTAMP",
            "schema_columns": list(schema.names()),
        }

    cutoff = pl.lit(holdout_start).str.to_datetime(time_zone="UTC")
    stats = (
        scan.select(
            pl.len().alias("rows"),
            pl.col(ts_col).min().alias("min_ts"),
            pl.col(ts_col).max().alias("max_ts"),
            (pl.col(ts_col) < cutoff).sum().alias("exploration_rows"),
            (pl.col(ts_col) >= cutoff).sum().alias("sealed_rows"),
        )
        .collect()
        .row(0, named=True)
    )
    return {
        "file": path.name,
        "status": "OK",
        "rows": int(stats["rows"]),
        "exploration_rows": int(stats["exploration_rows"]),
        "sealed_rows": int(stats["sealed_rows"]),
        "min_ts": stats["min_ts"].isoformat() if stats["min_ts"] else None,
        "max_ts": stats["max_ts"].isoformat() if stats["max_ts"] else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Permit setup-time verification while scaffolding is uncommitted.",
    )
    args = parser.parse_args()

    cfg = load_config()
    expected_branch = cfg["automation"]["branch"]
    branch = git("branch", "--show-current")
    porcelain = git("status", "--porcelain")
    data_root = resolve_data_root(cfg)
    glob_pattern = cfg["data"]["discover_glob"]
    holdout_start = cfg["holdout"]["sealed_confirmation_start"]

    checks = {
        "config_exists": CONFIG_PATH.exists(),
        "branch_ok": branch == expected_branch,
        "clean_start": not porcelain,
        "data_root_exists": data_root.is_dir(),
    }

    files: list[dict[str, Any]] = []
    if data_root.is_dir():
        for path in sorted(data_root.glob(glob_pattern)):
            try:
                files.append(parquet_summary(path, holdout_start))
            except Exception as exc:  # readiness should report, not hide, bad files
                files.append(
                    {"file": path.name, "status": "ERROR", "error": str(exc)}
                )

    checks["parquet_available"] = any(f.get("status") == "OK" for f in files)
    if args.allow_dirty:
        checks["clean_start"] = True

    payload = {
        "status": "READY" if all(checks.values()) else "NOT_READY",
        "repo_root": str(REPO_ROOT),
        "branch": branch,
        "expected_branch": expected_branch,
        "data_root": str(data_root),
        "sealed_confirmation_start": holdout_start,
        "checks": checks,
        "datasets": files,
    }
    print(json.dumps(payload, indent=2, default=str))
    return 0 if payload["status"] == "READY" else 1


if __name__ == "__main__":
    sys.exit(main())
