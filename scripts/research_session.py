#!/usr/bin/env python3
"""Freeze thesis declarations, audit inputs, and link exploratory trial evidence."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.research_session import (
    ResearchSessionError,
    check_session,
    diagnose_trial,
    init_session,
    record_trial,
    report_session,
)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest="command", required=True)
    for name in ("init", "check", "record", "report", "diagnose"):
        command = commands.add_parser(name)
        command.add_argument("--root", type=Path, required=True)
        if name == "init":
            command.add_argument("--spec", type=Path, required=True)
        else:
            command.add_argument("--session", required=True)
        if name in ("record", "diagnose"):
            command.add_argument("--trial", required=True)
        if name == "record":
            command.add_argument("--status", choices=("completed", "failed"), required=True)
            command.add_argument("--artifact", type=Path, required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "init":
            result = init_session(args.spec, args.root)
        elif args.command == "check":
            result = check_session(args.session, args.root)
        elif args.command == "record":
            result = record_trial(args.session, args.trial, args.status, args.artifact, args.root)
        elif args.command == "report":
            result = report_session(args.session, args.root)
        elif args.command == "diagnose":
            result = diagnose_trial(args.session, args.trial, args.root)
        else:
            raise ResearchSessionError("unknown command")
    except (ResearchSessionError, OSError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(json.dumps({
            "schema_version": 1, "status": "ERROR", "error": str(exc),
            "classification": "EXPLORATORY", "approval_status": "NOT_APPROVED",
        }, sort_keys=True))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 2 if result["status"] == "BLOCKED" or (
        args.command == "diagnose" and result["status"] == "failed"
    ) else 0


if __name__ == "__main__":
    raise SystemExit(main())
