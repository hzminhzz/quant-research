"""CLI for a resumable ATS research inbox. No holdout or broker operations."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.research_control.research_inbox_queue import InboxQueue


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["inspect", "start", "resume", "report"])
    parser.add_argument("--inbox", default=str(ROOT / "research_inbox"))
    parser.add_argument("--run-log", default=str(ROOT / "run_log"))
    parser.add_argument("--max-runtime-seconds", type=int, default=3600,
                        help="bound each qualified native development trial")
    parser.add_argument("--max-candidates", type=int, default=None,
                        help="optional bounded intake per call; resumes on later invocation")
    args = parser.parse_args(argv)
    queue = InboxQueue(args.inbox, args.run_log)
    try:
        result = (queue.run(max_runtime_seconds=args.max_runtime_seconds,
                            max_candidates=args.max_candidates)
                  if args.command in {"start", "resume"} else queue.report())
        if args.command == "inspect":
            for case in result["cases"]:
                print(json.dumps(case, ensure_ascii=False, sort_keys=True))
            return 0
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 2 if result["counts"]["total"] == 0 else 0
    except (RuntimeError, ValueError, OSError) as exc:
        print(json.dumps({"status": "BLOCKED_QUEUE", "reason": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
