"""ATS first-correct-action benchmark: old multi-source triage versus ATS read API.

Paired deterministic synthetic cases, independent baseline source parsing.
No brokers, protected market outcomes, provider fetches or live worker launches.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.engine.common import append_trial, digest, file_hash, write_json
from src.research_control.agent_interface import inspect_case
from src.research_control.job_inspector import observe_jobs

CASES: dict[str, str] = {
    "clean_rejection": "review_research",
    "large_casefile": "review_research",
    "conflicting_old_docs": "review_research",
    "missing_artifact": "inspect_evidence",
    "corrupt_artifact": "inspect_evidence",
    "contradictory_stage": "inspect_evidence",
    "stale_source": "inspect_evidence",
    "stale_worker_checkpoint": "inspect_evidence",
    "worker_done_without_completion": "inspect_evidence",
    "holdout_redaction": "review_research",
}


def _payload(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _make_fixture(root: Path, name: str) -> dict[str, Any]:
    """Create trusted synthetic ground truth before running either operator."""
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    (root / "AGENTS.md").write_text("Authority: read-only. No broker or holdout grants.\n")
    (root / "README.md").write_text("Old archival success claims are NOT current.")
    if name == "conflicting_old_docs":
        (root / "README.md").write_text("SUCCESS. All strategies approved for live deployment.")
    subprocess.run(["git", "-C", str(root), "add", "--", "AGENTS.md", "README.md"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=ATS Fixture",
                    "-c", "user.email=fixture@example.invalid", "commit",
                    "-qm", "fixture"], check=True, capture_output=True)
    folder = root / "run_log/dual_mode/candidate-ats/attempt-ats"
    folder.mkdir(parents=True)
    live = name != "worker_done_without_completion"
    protected = name == "holdout_redaction"
    state = "RUNNING" if not live else (
        "HOLDOUT_EVALUATED" if protected else "FALSIFIED_STAGE_2")
    if not protected and live:
        casefile = folder / "casefile.json"
        write_json(casefile, {
            "candidate_id": "candidate-ats", "attempt_id": "attempt-ats",
            "status": state, "stages": {"1": {"status": "PASS"},
                                      "2": {"status": "FALSIFIED_STAGE_2"}},
            "bulk": ["a" * 350_000] if name == "large_casefile" else [],
        })
        for stage, stage_state in ((1, "PASS"), (2, "FALSIFIED_STAGE_2")):
            evidence = folder / f"stage{stage}_evidence.json"
            write_json(evidence, {"status": stage_state})
            receipt = {"stage": stage, "status": stage_state, "candidate_id": "candidate-ats",
                       "spec_hash": "a" * 64, "code_hash": "b" * 64, "panel_hash": "c" * 64,
                       "artifacts": {evidence.name: file_hash(evidence)}}
            receipt["receipt_hash"] = digest(receipt)
            write_json(folder / f"stage{stage}.json", receipt)
        if name == "missing_artifact":
            casefile.unlink()
        elif name == "stale_source":
            future = datetime.now(UTC).timestamp() + 180
            os.utime(casefile, (future, future))
        elif name == "contradictory_stage":
            receipt_path = folder / "stage2.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["status"] = "PASS"
            receipt["receipt_hash"] = digest({k: v for k, v in receipt.items()
                                             if k != "receipt_hash"})
            write_json(receipt_path, receipt)
    key = {"candidate_id": "candidate-ats", "attempt_id": "attempt-ats",
           "spec_hash": "a" * 64, "code_hash": "b" * 64}
    append_trial(root / "run_log", {**key, "event": "registered", "status": "RUNNING"})
    if live:
        relative = "dual_mode/candidate-ats/attempt-ats/casefile.json"
        append_trial(root / "run_log", {
            **key, "event": "completed", "status": state, "holdout_access": protected,
            "casefile": {"path": relative,
                         "sha256": file_hash(folder / "casefile.json")
                         if (folder / "casefile.json").exists() else "missing"},
        })
    if name == "corrupt_artifact":
        casefile.write_bytes(casefile.read_bytes() + b"corruption")
    jobs: dict[str, Any] = {
        "visibility": "OBSERVED", "source_observed_at": datetime.now(UTC).isoformat(),
        "jobs": [], "total": 0,
    }
    if name in {"stale_worker_checkpoint", "worker_done_without_completion"}:
        jobs["jobs"] = [{
            "name": "ml4t-ats-synthetic", "panes": [
                {"pane_state": "VISIBLE",
                 "process": {"status": "PROCESS_PRESENT", "pid": 4311,
                             "start_ticks": 123456, "same_uid": True}}],
            "binding": {"authority": "V1_JOB_NAME_MATCH_ONLY",
                        "pid_start_ticks_bound_by_attempt": False,
                        "lease_status": "CURRENT"},
            "checkpoint": {"state": "INTEGRITY_VERIFIED",
                           "freshness": "STALE" if name == "stale_worker_checkpoint" else "UNKNOWN"},
            "completion_verified": False,
            "worker_status": "UNVERIFIED",
        }]
        jobs["total"] = 1
    return jobs


def _verify_native_json_hash(data: dict[str, Any], expected: str) -> bool:
    return hashlib.sha256((
        json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n").encode("utf-8")).hexdigest() == expected


def _old_source_operator(root: Path, jobs: dict[str, Any]) -> dict[str, Any]:
    """Comparable pre-ATS manual triage. Uses raw independent source reads.

    API/tool calls are model-visible information queries, not internal syscalls.
    A raw-file query exposes its whole nonprotected content to the decision-maker.
    """
    calls = 0
    context_bytes = 0

    def collect(raw: bytes) -> bytes:
        nonlocal calls, context_bytes
        calls += 1
        context_bytes += len(raw)
        return raw

    git = subprocess.run(["git", "-C", str(root), "status", "--porcelain=v1", "-uall"],
                         capture_output=True, check=False, timeout=6)
    collect(git.stdout)
    doc = collect((root / "AGENTS.md").read_bytes())
    # Absence of an externally scoped grant never supplies order authority.
    broker_allowed = False
    assert doc
    raw_ledger = collect((root / "run_log/trial_ledger.jsonl").read_bytes())
    previous, rows = "0" * 64, []
    invalid = False
    for line in raw_ledger.splitlines():
        record = json.loads(line)
        actual = record.pop("record_hash", None)
        if record.get("previous_hash") != previous or not _verify_native_json_hash(record, actual):
            invalid = True
            break
        previous = actual
        rows.append(record)
    collect(_payload(jobs))
    status = "BLOCKED" if invalid else "REVIEW"
    # Compare exactly the same latest-attempt scope as the ATS first page.
    latest = {}
    for row in rows:
        if row.get("candidate_id") and row.get("attempt_id"):
            latest[(row["candidate_id"], row["attempt_id"])] = row
    first_page = sorted(latest.values(), key=lambda item: (
        item.get("recorded_at") or "", item["attempt_id"]), reverse=True)[:10]
    if not first_page:
        status = "BLOCKED"
    for row in first_page:
        if row["event"] != "completed":
            status = "BLOCKED"
            continue
        if row["status"] == "HOLDOUT_EVALUATED" or row.get("holdout_access"):
            # Never open protected outcomes even in the old-path comparator.
            continue
        try:
            reference = row["casefile"]
            expected = (f"dual_mode/{row['candidate_id']}/"
                        f"{row['attempt_id']}/casefile.json")
            if reference["path"] != expected:
                raise ValueError("UNSAFE_BASELINE_REFERENCE")
            path = root / "run_log" / expected
            if path.is_symlink() or any(p.is_symlink() for p in path.parents):
                raise ValueError("SYMLINKED_BASELINE_REFERENCE")
            raw_casefile = collect(path.read_bytes())
            if hashlib.sha256(raw_casefile).hexdigest() != reference["sha256"]:
                status = "BLOCKED"
                continue
            case = json.loads(raw_casefile)
            if case["status"] != row["status"]:
                status = "BLOCKED"
            required = {"FALSIFIED_STAGE_2": 2, "FALSIFIED_STAGE_3": 3}.get(
                row["status"], 0)
            for stage in (1, 2, 3):
                receipt_path = path.parent / f"stage{stage}.json"
                if not receipt_path.is_file():
                    if stage <= required:
                        status = "BLOCKED"
                    continue
                receipt_bytes = collect(receipt_path.read_bytes())
                receipt = json.loads(receipt_bytes)
                checksum = receipt.pop("receipt_hash")
                if not _verify_native_json_hash(receipt, checksum):
                    status = "BLOCKED"
                if (stage < required and receipt["status"] != "PASS"
                    or stage == required and receipt["status"] != row["status"]
                    or stage > required and required):
                    status = "BLOCKED"
                source = path.parent / f"stage{stage}_evidence.json"
                evidence = collect(source.read_bytes())
                if hashlib.sha256(evidence).hexdigest() != receipt["artifacts"][source.name]:
                    status = "BLOCKED"
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            status = "BLOCKED"
    if any(job.get("checkpoint", {}).get("freshness") in ("STALE", "CLOCK_CONFLICT")
           for job in jobs.get("jobs", [])):
        status = "BLOCKED"
    if broker_allowed:
        status = "BLOCKED"
    return {"action": "inspect_evidence" if status == "BLOCKED" else "review_research",
            "status": status, "tool_calls": calls, "context_bytes": context_bytes,
            "broker_orders_allowed": broker_allowed}


def _new_operator(root: Path, jobs: dict[str, Any]) -> dict[str, Any]:
    view = inspect_case(root, job_probe=lambda _: jobs)
    return {"action": view["next_action"]["kind"], "status": view["status"],
            "tool_calls": 1,
            "context_bytes": len(_payload(view)),
            "broker_orders_allowed": view["permissions"]["broker_orders"],
            "view": view}


def _timed(callback):
    start = time.perf_counter_ns()
    result = callback()
    return round((time.perf_counter_ns() - start) / 1e6, 4), result


def benchmark_corpus(*, samples: int = 5) -> dict[str, Any]:
    """Independent gold decisions fixed before timing either implementation."""
    if not 3 <= samples <= 30:
        raise ValueError("INVALID_SAMPLES")
    cases, all_correct, baseline_correct, timings = [], True, 0, {"baseline": [], "managed": []}
    for name, oracle in CASES.items():
        with tempfile.TemporaryDirectory(prefix="ats-cold-start-") as directory:
            root = Path(directory)
            jobs = _make_fixture(root, name)
            traces = []
            for i in range(samples):
                results = {}
                ordered = ["baseline", "managed"] if i % 2 == 0 else ["managed", "baseline"]
                for approach in ordered:
                    function = _old_source_operator if approach == "baseline" else _new_operator
                    latency, result = _timed(lambda fn=function, r=root, j=jobs: fn(r, j))
                    timings[approach].append(latency)
                    results[approach] = {"latency_ms": latency,
                                         "action": result["action"],
                                         "correct": result["action"] == oracle and
                                                    result["broker_orders_allowed"] is False,
                                         "context_bytes": result["context_bytes"],
                                         "tool_calls": result["tool_calls"]}
                traces.append(results)
            correct = all(trace["managed"]["correct"] for trace in traces)
            all_correct &= correct
            baseline_correct += all(trace["baseline"]["correct"] for trace in traces)
            cases.append({"fixture": name, "expected_action": oracle,
                          "baseline": {
                              "correct": all(t["baseline"]["correct"] for t in traces),
                              "median_ms": round(statistics.median(t["baseline"]["latency_ms"]
                                                                   for t in traces), 4),
                              "tool_calls": traces[0]["baseline"]["tool_calls"],
                              "context_bytes": traces[0]["baseline"]["context_bytes"]},
                          "managed": {
                              "correct": all(t["managed"]["correct"] for t in traces),
                              "median_ms": round(statistics.median(t["managed"]["latency_ms"]
                                                                   for t in traces), 4),
                              "tool_calls": traces[0]["managed"]["tool_calls"],
                              "context_bytes": traces[0]["managed"]["context_bytes"]},
                          "raw_pairs": traces})
    return {
        "benchmark": "ats-first-correct-action-v2",
        "scope": "synthetic metadata-only pre-ATS manual workflow vs ATS read API",
        "fixture_count": len(cases), "samples_per_fixture": samples,
        "gold_defined_before_execution": True, "all_critical_correct": all_correct,
        "managed_correct_fixtures": sum(c["managed"]["correct"] for c in cases),
        "baseline_correct_fixtures": baseline_correct,
        "baseline": {"description": "Raw Git + policy + ledger + individual casefile/receipt reads",
                     "overall_median_ms": round(statistics.median(timings["baseline"]), 4)},
        "managed": {"description": "One bounded inspect_case API result",
                    "overall_median_ms": round(statistics.median(timings["managed"]), 4)},
        "cases": cases, "effects": ["SYNTHETIC_TEMP_FILES_ONLY"],
        "limits": ["Tool calls count model-visible source queries, not process syscalls",
                   "Context effort is UTF-8 source/result bytes, not billed model tokens",
                   "Latency measures deterministic Python source triage, not a human/LLM decision",
                   "Fixture labels are synthetic and not live trading outcomes",
                   "No numerical strategy evaluation or protected outcomes opened"],
    }


def benchmark(root: Path, *, samples: int = 5) -> dict[str, Any]:
    """Same live metadata identity, with no ex-ante gold decision claim."""
    if not 3 <= samples <= 30:
        raise ValueError("INVALID_SAMPLES")
    root = root.resolve()
    jobs = observe_jobs(root)
    traces = []
    for i in range(samples):
        results = {}
        order = ["baseline", "managed"] if i % 2 == 0 else ["managed", "baseline"]
        for branch in order:
            fn = _old_source_operator if branch == "baseline" else _new_operator
            latency, output = _timed(lambda f=fn: f(root, jobs))
            results[branch] = {"latency_ms": latency,
                               "action": output["action"],
                               "tool_calls": output["tool_calls"],
                               "context_bytes": output["context_bytes"]}
        traces.append(results)
    return {"benchmark": "ats-real-metadata-comparison-v2",
            "head": subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                                   capture_output=True, text=True, check=False).stdout.strip(),
            "samples": samples, "raw_pairs": traces,
            "gold_correctness": "UNKNOWN_WITHOUT_INDEPENDENT_ORACLE",
            "protected_outcomes": "NOT_OPENED", "effects": ["READ_ONLY"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--fixture-corpus", action="store_true")
    args = parser.parse_args(argv)
    result = (benchmark_corpus(samples=args.samples) if args.fixture_corpus
              else benchmark(args.root, samples=args.samples))
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result.get("all_critical_correct", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
