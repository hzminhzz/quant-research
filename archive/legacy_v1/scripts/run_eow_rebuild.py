#!/usr/bin/env python3
"""CLI for the auditable historical EOW + meta-gated ORB rebuild."""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.eow_rebuild import (
    EOWRebuildError,
    development_run,
    final_holdout_run,
    micro_dst_audit,
    preflight,
)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, default=Path("config/eow_rebuild.yaml"))
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--dst-audit", action="store_true")
    mode.add_argument("--development", action="store_true")
    mode.add_argument("--final-holdout", action="store_true")
    p.add_argument("--run-id")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    config = (ROOT / args.config).resolve() if not args.config.is_absolute() else args.config
    try:
        if args.preflight:
            result = preflight(ROOT, config)
        elif args.dst_audit:
            result = micro_dst_audit(ROOT, config)
        elif args.development:
            if not args.run_id:
                raise EOWRebuildError("--run-id is required for development")
            result = development_run(ROOT, config, run_id=args.run_id)
        else:
            if not args.run_id:
                raise EOWRebuildError("--run-id is required for final holdout")
            result = final_holdout_run(ROOT, config, run_id=args.run_id)
    except Exception as exc:
        result = {
            "status": "BLOCKED",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
        if args.run_id:
            failure_dir = ROOT / "run_log" / "eow_rebuild" / args.run_id
            failure_dir.mkdir(parents=True, exist_ok=True)
            (failure_dir / "failure.json").write_text(
                json.dumps(result, indent=2, sort_keys=True, default=str) + "\n"
            )
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 2

    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result.get("status") not in {"BLOCKED", "FAIL"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
