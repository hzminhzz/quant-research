#!/usr/bin/env python3
"""Run the corrected HK33/JP225 expected-R ML sizing experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.eow_rebuild import EOWRebuildError  # noqa: E402
from src.orb_ml_research import ORBMLResearchError, run_research  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/orb_ml_research.yaml"),
    )
    parser.add_argument("--run-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = args.config if args.config.is_absolute() else ROOT / args.config
    try:
        result = run_research(ROOT, config, run_id=args.run_id)
    except (ORBMLResearchError, EOWRebuildError, OSError, ValueError, KeyError) as exc:
        result = {
            "status": "BLOCKED",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 2

    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
