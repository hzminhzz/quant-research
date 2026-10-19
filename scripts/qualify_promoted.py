"""Verify immutable promoted-candidate registrations; never submit orders."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.promoted_evidence import load_registration, verify_registration


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("registration", type=Path)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = verify_registration(load_registration(args.registration), args.source_root)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered)
    else:
        print(rendered, end="")
    return 0 if result["source_identity"] == "VERIFIED" else 3


if __name__ == "__main__":
    raise SystemExit(main())
