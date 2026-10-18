"""Independent promoted-source hash judge; imports no qualification code."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("registration", type=Path)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("producer_output", type=Path)
    args = parser.parse_args(argv)
    registration = json.loads(args.registration.read_text())
    producer = json.loads(args.producer_output.read_text())
    failures = []
    expected = registration.get("source_files", [])
    if not expected:
        failures.append("EMPTY_SOURCE_REGISTRATION")
    paths = [item.get("path") for item in expected]
    if len(paths) != len(set(paths)):
        failures.append("DUPLICATE_SOURCE_PATH")
    independently_checked = []
    root = args.source_root.resolve(strict=True)
    for item in expected:
        lexical = root / item["path"]
        path = lexical.resolve()
        try:
            path.relative_to(root)
        except ValueError:
            failures.append("PATH_ESCAPE:" + item["path"])
            continue
        if not path.is_file() or lexical.is_symlink():
            failures.append("MISSING_OR_SYMLINK:" + item["path"])
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        independently_checked.append({"path": item["path"], "sha256": actual})
        if actual != item["sha256"]:
            failures.append("HASH_MISMATCH:" + item["path"])
    if producer.get("candidate_id") != registration.get("candidate_id"):
        failures.append("PRODUCER_CANDIDATE_MISMATCH")
    if producer.get("checked") != independently_checked:
        failures.append("PRODUCER_HASH_SET_MISMATCH")
    if producer.get("source_identity") != ("VERIFIED" if not failures else "REJECTED"):
        failures.append("PRODUCER_STATUS_MISMATCH")
    report = {
        "judge": "INDEPENDENT_SOURCE_HASH_JUDGE",
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "checked": independently_checked,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not failures else 3


if __name__ == "__main__":
    raise SystemExit(main())
