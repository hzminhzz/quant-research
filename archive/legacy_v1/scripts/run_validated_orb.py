#!/usr/bin/env python3
"""Canonical fail-closed ORB validation runner."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.validated_orb_pipeline import RunnerContractError, ValidatedORBRunner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/setup.yaml"))
    parser.add_argument("--data-manifest", type=Path, default=Path("data/processed/_manifest.json"))
    parser.add_argument("--run-id")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument(
        "--evaluate-final-oos",
        action="store_true",
        help="Irreversibly claim and score the frozen final OOS exactly once",
    )
    parser.add_argument(
        "--resume-final-oos",
        action="store_true",
        help="Resume one-shot final OOS from a committed development run without refitting",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.preflight_only and (args.evaluate_final_oos or args.resume_final_oos):
        raise SystemExit("OOS execution cannot be combined with --preflight-only")
    if args.evaluate_final_oos and args.resume_final_oos:
        raise SystemExit("--evaluate-final-oos and --resume-final-oos are mutually exclusive")
    if not args.preflight_only and not args.run_id:
        raise SystemExit("--run-id is required for execution")
    run_id = args.run_id or "preflight-only"
    try:
        runner = ValidatedORBRunner(
            root=PROJECT_ROOT,
            config_path=args.config,
            manifest_path=args.data_manifest,
            run_id=run_id,
            output_dir=args.output_dir,
        )
        if args.preflight_only:
            result = runner.preflight()
        elif args.resume_final_oos:
            result = runner.resume_final_oos()
        else:
            # Ledger writes occur only through this real execution entry point.
            result = runner.run(evaluate_final_oos=args.evaluate_final_oos, append_trial=True)
    except (RunnerContractError, OSError, ValueError, KeyError) as exc:
        result = {
            "schema_version": "validated_orb_run/v1",
            "run_id": run_id,
            "status": "NOT_APPROVED",
            "verdict": "BLOCKED",
            "blocking_reasons": [str(exc)],
            "metrics": None,
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result.get("verdict") in {"PRECHECK_PASS", "NOT_APPROVED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
