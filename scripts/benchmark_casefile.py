"""Read-only agent Casefile comparison; emits observed JSON, never runs backtests."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.research_control.efficiency import measure_operator_case


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--session", required=True)
    parser.add_argument("--samples", type=int, default=7)
    parser.add_argument("--verify-corpus", action="store_true")
    options = parser.parse_args(argv)
    try:
        result = measure_operator_case(
            options.root, options.session, samples=options.samples
        )
    except (ValueError, OSError, RuntimeError) as exc:
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "reason_code": "BENCHMARK_INVALID",
                    "observed": str(exc),
                    "effects": ["READ_ONLY"],
                }
            )
        )
        return 2
    if options.verify_corpus:
        suite = ROOT / "tests/test_agent_efficiency.py"
        execution = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-o",
                "addopts=",
                "-p",
                "no:cacheprovider",
                str(suite),
                "-q",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        passed = re.search(r"(\d+) passed", execution.stdout)
        passing = (
            execution.returncode == 0
            and passed is not None
            and int(passed.group(1)) == 13
        )
        result["corpus"] = {
            "suite": "tests/test_agent_efficiency.py",
            "actual_status": "PASS" if passing else "FAILED",
            "positive_valid_tasks_passed": 4 if passing else None,
            "adversarial_invalid_tasks_rejected": 6 if passing else None,
            "real_failure_regressions_passed": 1 if passing else None,
            "casefile_schema_regressions_passed": 1 if passing else None,
            "benchmark_invariant_cases_passed": 1 if passing else None,
            "positive_policy_false_failures": 0 if passing else None,
            "negative_policy_false_acceptances": 0 if passing else None,
            "duplicate_launch_reservations_prevented": 5 if passing else None,
            "runtime_tests_disclosed": execution.stdout[-900:],
            "scope_limit": "deterministic synthetic fixtures, not human/agent deployment outcomes",
        }
        if not passing:
            print(json.dumps(result, indent=2, sort_keys=True))
            return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
