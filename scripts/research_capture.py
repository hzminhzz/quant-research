"""Research thesis capture CLI.

Safe, deterministic intake of heterogeneous thesis sources. Produces a
descriptive capture report (THESIS_CAPTURED / RESEARCH_READY), never an
executable CandidateSpec, never holds out or orders data.

Usage:
  python scripts/research_capture.py capture <source> [--out DIR]
  python scripts/research_capture.py verify <report.json>
  python scripts/research_capture.py batch <inbox_dir> [--out DIR]
  python scripts/research_capture.py archive <theses.zip> --out DIR
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.engine.common import QuantError  # noqa: E402 - repository root added above
from src.engine.research_capture import capture_archive, capture_source, verify_capture  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    capture = commands.add_parser("capture", help="capture one thesis source into an immutable evidence record")
    capture.add_argument("source", help="directory (thesis.yaml+brief.md) or md/txt/json/yaml file")
    capture.add_argument("--out", default=None, help="output directory for the capture report")

    verify = commands.add_parser("verify", help="re-verify a previously written capture report (read-only)")
    verify.add_argument("report", help="capture report JSON path")
    verify.add_argument("--expected-report-sha256", default=None,
                        help="externally pinned report hash for authenticated verification")

    batch = commands.add_parser("batch", help="capture every candidate subdirectory in an inbox")
    batch.add_argument("inbox", help="inbox directory containing candidate subdirectories")
    batch.add_argument("--out", default=None, help="output directory for capture reports")

    archive = commands.add_parser("archive", help="safely capture thesis.yaml+brief.md folders from a ZIP")
    archive.add_argument("zip", help="ZIP archive containing paired thesis folders")
    archive.add_argument("--out", required=True, help="immutable archive and report output directory")

    args = parser.parse_args(argv)
    try:
        if args.command == "capture":
            result = capture_source(args.source, args.out)
            print(json.dumps(result.to_dict(), sort_keys=True, indent=2))
            return 0
        if args.command == "verify":
            info = verify_capture(args.report, expected_report_sha256=args.expected_report_sha256)
            print(json.dumps(info, sort_keys=True, indent=2))
            return 0
        if args.command == "batch":
            inbox = Path(args.inbox).resolve()
            if not inbox.is_dir():
                raise QuantError("INVALID_CAPTURE", f"inbox is not a directory: {inbox}")
            out_dir = Path(args.out).resolve() if args.out else None
            results = []
            for child in sorted(p for p in inbox.iterdir() if p.is_dir() and not p.name.startswith(".")):
                try:
                    result = capture_source(child, out_dir)
                    results.append({"candidate_id": result.candidate_id, "status": result.status,
                                    "source_hash": result.source_hash, "report": result.report_path})
                except QuantError as exc:
                    results.append({"candidate_id": child.name, "status": "BLOCKED_CAPTURE",
                                    "reason": exc.reason, "source": str(child)})
            if not results:
                raise QuantError("INVALID_CAPTURE", f"no candidate directories found in {inbox}")
            print(json.dumps({"scope": "DESCRIPTIVE_CAPTURE_ONLY_NEVER_EXECUTABLE",
                              "inbox": str(inbox), "results": results}, sort_keys=True, indent=2))
            return 0
        if args.command == "archive":
            results = capture_archive(args.zip, args.out)
            print(json.dumps({"scope": "DESCRIPTIVE_CAPTURE_ONLY_NEVER_EXECUTABLE",
                              "archive": str(Path(args.zip).resolve()),
                              "captured": len(results),
                              "results": [{"candidate_id": item.candidate_id, "status": item.status,
                                           "source_hash": item.source_hash, "report": item.report_path,
                                           "unresolved": item.unresolved}
                                          for item in results]}, sort_keys=True, indent=2))
            return 0
    except QuantError as exc:
        print(json.dumps({"status": exc.status, "reason": exc.reason}), file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001 - CLI boundary returns a structured nonzero failure
        print(json.dumps({"status": "ENGINEERING_ERROR",
                          "reason": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
