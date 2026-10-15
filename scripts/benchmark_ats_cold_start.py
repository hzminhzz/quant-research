"""ATS cold-start effort benchmark: measure real calls and answer completeness.

Synthetic research fixtures only; no broker, data, model or protected reads.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from src.research_control.agent_interface import inspect_case


def benchmark(root: Path, *, samples: int = 5, list_jobs=lambda: set()) -> dict:
    if not 3 <= samples <= 50:
        raise ValueError("INVALID_SAMPLES")
    # Legacy operator must separately inspect git, ledger and tmux, and then
    # reason about the results. Those three sources do not provide permissions.
    durations, views = [], []
    for _ in range(samples):
        start = time.perf_counter_ns()
        view = inspect_case(root, list_jobs=list_jobs)
        durations.append((time.perf_counter_ns() - start) / 1e6)
        views.append(view)
    actions = [(v["status"], v["next_action"]["kind"], v["permissions"]["broker_orders"])
               for v in views]
    if len(set(actions)) != 1:
        raise RuntimeError("NONDETERMINISTIC_DECISION")
    return {"benchmark": "ats-first-correct-action-v1", "fixture": "supplied metadata root",
            "scope": "cold-start authority discovery, not end-to-end decision latency",
            "baseline": {"minimum_source_queries": 3,
                         "sources": ["git", "trial_ledger", "tmux"],
                         "approval_completeness": False,
                         "first_correct_action": "NOT_DETERMINED_WITHOUT_PERMISSION_LOOKUP"},
            "new": {"source_queries": 1, "decision": actions[0][1],
                    "status": actions[0][0], "broker_authorized": actions[0][2],
                    "median_ms": round(statistics.median(durations), 3),
                    "samples": samples, "source_integrity_enforced": True},
            "measured": {"new_query_latency_ms": durations,
                         "baseline_latency_ms": None, "human_or_agent_tokens": None},
            "no_claim": "Baseline was not timed; no speed-up or decision-quality uplift is asserted",
            "effects": ["READ_ONLY"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--samples", type=int, default=5)
    args = parser.parse_args()
    print(json.dumps(benchmark(args.root, samples=args.samples), indent=2))


if __name__ == "__main__":
    main()
