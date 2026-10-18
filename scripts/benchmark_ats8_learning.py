"""ATS-8 operating benchmark: measure decision accuracy, effort, and learning.

Reuses the ATS-0/ATS-1 baseline and fixtures, adding verified lesson retrieval
and invalidation. Measures tool calls, context bytes, latency, unsupported
claims, remedy discovery, and rejection of stale or incompatible advice.
Persists raw traces, source hashes, and 3-way operator comparisons.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.benchmark_ats_cold_start import (
    _make_fixture,
    _old_source_operator,
    _payload,
)
from src.engine.common import append_trial, file_hash
from src.research_control.agent_interface import inspect_case, read_evidence
from src.research_control.learning import LessonStore, create_lesson

BENCHMARK_SCHEMA = "ats8-benchmark-v1"

CASES: dict[str, dict[str, Any]] = {
    "clean_rejection": {
        "expected_action": "review_research",
        "description": "Clean falsified Stage 2 attempt; scientific rejection",
        "expected_remedy": None,
    },
    "large_casefile": {
        "expected_action": "review_research",
        "description": "Large casefile (>350KB); streaming SHA verification succeeds",
        "expected_remedy": None,
    },
    "conflicting_old_docs": {
        "expected_action": "review_research",
        "description": "Stale README claim contradicted by trial ledger",
        "expected_remedy": None,
    },
    "missing_artifact": {
        "expected_action": "inspect_evidence",
        "description": "Casefile deleted; fails closed",
        "expected_remedy": None,
    },
    "corrupt_artifact": {
        "expected_action": "inspect_evidence",
        "description": "Casefile hash mismatch; fails closed without false remedy",
        "expected_remedy": None,
    },
    "contradictory_stage": {
        "expected_action": "inspect_evidence",
        "description": "Stage 2 receipt claims PASS contradicting ledger",
        "expected_remedy": None,
    },
    "stale_source": {
        "expected_action": "inspect_evidence",
        "description": "Artifact mtime in future compared to ledger",
        "expected_remedy": None,
    },
    "stale_worker_checkpoint": {
        "expected_action": "inspect_evidence",
        "description": "Tmux pane active but checkpoint >1800s stale",
        "expected_remedy": None,
    },
    "worker_done_without_completion": {
        "expected_action": "inspect_evidence",
        "description": "Worker pane active but no completion in ledger",
        "expected_remedy": None,
    },
    "holdout_redaction": {
        "expected_action": "review_research",
        "description": "Holdout outcome evaluated; protected read redacted",
        "expected_remedy": None,
    },
    "superseded_lesson_rejection": {
        "expected_action": "inspect_evidence",
        "description": "INVALID_SPEC error with superseded lesson; obsolete advice filtered out",
        "expected_remedy": None,
    },
    "version_incompatible_rejection": {
        "expected_action": "inspect_evidence",
        "description": "ISOLATION_UNAVAILABLE with future lesson; incompatible advice filtered out",
        "expected_remedy": None,
    },
    "changed_input_data_or_code": {
        "expected_action": "inspect_evidence",
        "description": "Code hash in stage receipt drifts from ledger registration (STAGE_IDENTITY_CONFLICT)",
        "expected_remedy": None,
    },
    "incorrect_protocol_selection": {
        "expected_action": "inspect_evidence",
        "description": "Event strategy protocol mismatch rejected; no fabricated IC approval",
        "expected_remedy": None,
    },
    "remedy_eligible_isolation_unavailable": {
        "expected_action": "inspect_evidence",
        "description": "ISOLATION_UNAVAILABLE error with verified environment remedy discovered",
        "expected_remedy": "LSN-20261016-ISOLATION-UNAVAILABLE-REMEDY",
    },
}


def _timed(callback: Any) -> tuple[float, Any]:
    start = time.perf_counter_ns()
    result = callback()
    return round((time.perf_counter_ns() - start) / 1e6, 4), result


def _populate_lessons(root: Path) -> LessonStore:
    """Populate canonical verified lessons into the test fixture."""
    store = LessonStore(root)

    # 1. Oversize Casefile Streaming
    l1 = create_lesson(
        lesson_id="LSN-20261015-OVERSIZE-CASEFILE-STREAM",
        knowledge_class="implementation_recipe",
        trigger="EVIDENCE_TOO_LARGE when reading large factory Casefile JSON (>256KB)",
        error_codes=("EVIDENCE_TOO_LARGE",),
        affected_scope=("src/research_control/agent_interface.py",),
        protocol="dual_mode_v1",
        version_bounds={"ml4t-engineer": "0.1.4"},
        evidence_ref="commit 260b14e (src/research_control/agent_interface.py)",
        root_cause="Eager JSON parsing of high-volume bulk exclusion arrays (>350KB) overflows memory budgets.",
        verified_remedy="Stream SHA-256 byte digest (_integrity) against trial ledger hash without decoding full JSON; inspect small stage receipts.",
        regression_test="tests/test_ats_qualification.py::test_large_casefile_stream_hash_and_receipts_without_json_decode",
        reviewer="hzminhzz",
        created_at="2026-10-15T19:30:00Z",
    )
    store.save(l1)

    # 2. Kernel Cgroup Memory Containment
    l2 = create_lesson(
        lesson_id="LSN-20261016-CGROUP-V2-MEMORY-CONTAINMENT",
        knowledge_class="implementation_recipe",
        trigger="Kernel-enforced resident memory capping for isolated native research workers",
        error_codes=("RESOURCE_LIMIT", "HARD_MEMORY_ISOLATION_UNAVAILABLE"),
        affected_scope=("src/research_control/resource_cgroup.py",),
        protocol="native_bracket_v1",
        version_bounds={"cgroup": "v2"},
        evidence_ref="commit 368d8f0 (src/research_control/resource_cgroup.py)",
        root_cause="In-process RLIMIT_AS panics jemalloc arena thread creation. Parent RSS polling allows burst spikes.",
        verified_remedy="Use Linux cgroup v2 / systemd user scopes to enforce hard resident limits at kernel level.",
        regression_test="tests/test_ats2_resource_limits.py::test_unavailable_cgroup_does_not_consume_admission",
        reviewer="hzminhzz",
        created_at="2026-10-16T09:23:00Z",
    )
    store.save(l2)

    # 3. Superseded Legacy Permit Override
    l3 = create_lesson(
        lesson_id="LSN-20261010-LEGACY-V1-PERMIT-OVERRIDE",
        knowledge_class="implementation_recipe",
        trigger="Feature permit manual override for v1 research contracts",
        error_codes=("INVALID_SPEC", "PERMIT_OVERRIDE_DEPRECATED"),
        affected_scope=("src/research_control/run_permit.py",),
        protocol="legacy_v1",
        evidence_ref="commit df516b8",
        root_cause="Manual permit overrides caused schema drift.",
        verified_remedy="Superseded by dual-mode factory and ActionContractV1 cryptographic permits.",
        regression_test="tests/test_run_permit.py",
        reviewer="hzminhzz",
        superseded_by="LSN-20261015-DUAL-MODE-RUNTIME",
        created_at="2026-10-10T10:00:00Z",
    )
    store.save(l3)

    # 4. Incompatible Future Protocol Lesson (requires engine 9.9.9)
    l4 = create_lesson(
        lesson_id="LSN-20261016-FUTURE-ENGINE-PROTOCOL",
        knowledge_class="implementation_recipe",
        trigger="Hypothetical engine protocol feature",
        error_codes=("FUTURE_PROTOCOL_ERROR",),
        affected_scope=("src/engine/future.py",),
        protocol="future_v9",
        version_bounds={"ml4t-engineer": "9.9.9"},
        evidence_ref="hypothetical",
        root_cause="Future version requirement.",
        verified_remedy="Upgrade to engine 9.9.9.",
        regression_test="tests/test_future.py",
        reviewer="hzminhzz",
        created_at="2026-10-16T12:00:00Z",
    )
    store.save(l4)

    # 5. Verified Remedy Lesson: Bubblewrap isolation unavailable
    l5 = create_lesson(
        lesson_id="LSN-20261016-ISOLATION-UNAVAILABLE-REMEDY",
        knowledge_class="implementation_recipe",
        trigger="Bubblewrap unprivileged user namespace unavailable in worker environment",
        error_codes=("ISOLATION_UNAVAILABLE",),
        affected_scope=("src/engine/isolation.py",),
        protocol="dual_mode_v1",
        version_bounds={"ml4t-engineer": "0.1.4"},
        evidence_ref="docs/audit/ats_native_inbox_admission_20261018.md",
        root_cause="Container runtime restricts unshare(CLONE_NEWUSER) syscall.",
        verified_remedy="Run worker with host user namespace or configure kernel.unprivileged_userns_clone=1.",
        regression_test="tests/test_dual_mode_isolation.py",
        reviewer="hzminhzz",
        created_at="2026-10-16T10:00:00Z",
    )
    store.save(l5)

    return store


def _managed_with_learning_operator(
    root: Path,
    jobs: dict[str, Any],
    case_name: str,
    *,
    mutant_disable_filtering: bool = False,
) -> dict[str, Any]:
    """ATS-8 operator: inspect_case + read_evidence + lesson query from real observed tool results."""
    view = inspect_case(root, job_probe=lambda _: jobs)
    tool_calls = 1
    context_bytes = len(_payload(view))

    observed_errors: list[str] = []
    for unknown in view.get("unknowns", []):
        if unknown.get("reason_code"):
            observed_errors.append(unknown["reason_code"])
        if "statuses" in unknown:
            observed_errors.extend(unknown["statuses"])

    # If evidence reference is present, attempt read_evidence with standard bounded budget
    if view.get("research") and view["research"][0].get("source_ref"):
        ref = view["research"][0]["source_ref"]
        tool_calls += 1
        try:
            ev = read_evidence(root, ref, max_bytes=16_384)
            context_bytes += len(_payload(ev))
        except ValueError as exc:
            code = str(exc).split(":", 1)[0]
            observed_errors.append(code)

    store = LessonStore(root)
    current_versions = {"ml4t-engineer": "0.1.4", "cgroup": "v2"}
    matched_remedy = None
    stale_advice_used = False
    incompatible_advice_used = False
    stale_opportunities_seen = 0
    incompatible_opportunities_seen = 0

    # Query LessonStore uniquely per observed error code
    for err in sorted(set(observed_errors)):
        tool_calls += 1
        if mutant_disable_filtering:
            matches = store.query(
                error_code=err,
                current_versions=current_versions,
                include_superseded=True,
                include_invalid=True,
            )
            for m in matches:
                if m.validity == "SUPERSEDED":
                    stale_advice_used = True
                    stale_opportunities_seen += 1
                if m.validity == "VERSION_INCOMPATIBLE":
                    incompatible_advice_used = True
                    incompatible_opportunities_seen += 1
            if matches and matched_remedy is None:
                matched_remedy = matches[0].lesson.lesson_id
        else:
            matches = store.query(error_code=err, current_versions=current_versions)
            valid = [m for m in matches if m.validity == "VALID"]
            if valid and matched_remedy is None:
                matched_remedy = valid[0].lesson.lesson_id
                context_bytes += len(_payload(valid[0].lesson.model_dump(mode="json")))

            all_matches = store.query(
                error_code=err,
                current_versions=current_versions,
                include_superseded=True,
                include_invalid=True,
            )
            for m in all_matches:
                if m.validity == "SUPERSEDED":
                    stale_opportunities_seen += 1
                if m.validity == "VERSION_INCOMPATIBLE":
                    incompatible_opportunities_seen += 1

    unsupported_claims = 0
    if view["permissions"]["broker_orders"] is not False:
        unsupported_claims += 1
    if view["dimensions"]["approval"] != "NOT_GRANTED":
        unsupported_claims += 1
    if view["status"] == "REVIEW" and any(u["reason_code"] == "STAGE_RECEIPT_TAMPERED" for u in view.get("unknowns", [])):
        unsupported_claims += 1

    return {
        "action": view["next_action"]["kind"],
        "status": view["status"],
        "tool_calls": tool_calls,
        "context_bytes": context_bytes,
        "broker_orders_allowed": view["permissions"]["broker_orders"],
        "matched_remedy": matched_remedy,
        "stale_advice_used": stale_advice_used,
        "incompatible_advice_used": incompatible_advice_used,
        "stale_opportunities_seen": stale_opportunities_seen,
        "incompatible_opportunities_seen": incompatible_opportunities_seen,
        "unsupported_claims": unsupported_claims,
    }


def _managed_without_learning_operator(root: Path, jobs: dict[str, Any], case_name: str) -> dict[str, Any]:
    """Operator with learning OFF (inspect_case + read_evidence without lesson store)."""
    view = inspect_case(root, job_probe=lambda _: jobs)
    tool_calls = 1
    context_bytes = len(_payload(view))

    if view.get("research") and view["research"][0].get("source_ref"):
        ref = view["research"][0]["source_ref"]
        tool_calls += 1
        try:
            ev = read_evidence(root, ref, max_bytes=16_384)
            context_bytes += len(_payload(ev))
        except ValueError:
            pass

    unsupported_claims = 0
    if view["permissions"]["broker_orders"] is not False:
        unsupported_claims += 1
    if view["dimensions"]["approval"] != "NOT_GRANTED":
        unsupported_claims += 1

    return {
        "action": view["next_action"]["kind"],
        "status": view["status"],
        "tool_calls": tool_calls,
        "context_bytes": context_bytes,
        "broker_orders_allowed": view["permissions"]["broker_orders"],
        "matched_remedy": None,
        "stale_advice_used": False,
        "incompatible_advice_used": False,
        "unsupported_claims": unsupported_claims,
    }


def _make_ats8_fixture(root: Path, name: str) -> dict[str, Any]:
    """Create genuine fixture with real recorded error statuses."""
    if name == "superseded_lesson_rejection":
        jobs = _make_fixture(root, "clean_rejection")
        append_trial(root / "run_log", {
            "candidate_id": "candidate-ats", "attempt_id": "attempt-ats-spec",
            "event": "registered", "status": "RUNNING",
            "spec_hash": "a" * 64, "code_hash": "b" * 64,
        })
        append_trial(root / "run_log", {
            "candidate_id": "candidate-ats", "attempt_id": "attempt-ats-spec",
            "event": "completed", "status": "INVALID_SPEC",
            "spec_hash": "a" * 64, "code_hash": "b" * 64,
            "casefile": {"path": "dual_mode/candidate-ats/attempt-ats/casefile.json", "sha256": "missing"},
        })
        return jobs
    if name == "version_incompatible_rejection":
        jobs = _make_fixture(root, "clean_rejection")
        append_trial(root / "run_log", {
            "candidate_id": "candidate-ats", "attempt_id": "attempt-ats-iso",
            "event": "registered", "status": "RUNNING",
            "spec_hash": "a" * 64, "code_hash": "b" * 64,
        })
        append_trial(root / "run_log", {
            "candidate_id": "candidate-ats", "attempt_id": "attempt-ats-iso",
            "event": "completed", "status": "FUTURE_PROTOCOL_ERROR",
            "spec_hash": "a" * 64, "code_hash": "b" * 64,
            "casefile": {"path": "dual_mode/candidate-ats/attempt-ats/casefile.json", "sha256": "missing"},
        })
        return jobs

    if name == "changed_input_data_or_code":
        jobs = _make_fixture(root, "clean_rejection")
        # Write real source code file and mutate it to cause verified code drift
        strategy_file = root / "src/strategy.py"
        strategy_file.parent.mkdir(parents=True, exist_ok=True)
        strategy_file.write_text("def run(): return 1\n", encoding="utf-8")
        receipt_path = root / "run_log/dual_mode/candidate-ats/attempt-ats/stage1.json"
        r = json.loads(receipt_path.read_text(encoding="utf-8"))
        r["code_hash"] = file_hash(strategy_file)
        from src.engine.common import digest, write_json
        r["receipt_hash"] = digest({k: v for k, v in r.items() if k != "receipt_hash"})
        write_json(receipt_path, r)
        # Now mutate the source file on disk to create actual code drift
        strategy_file.write_text("def run(): return 2  # mutated\n", encoding="utf-8")
        return jobs
    if name == "incorrect_protocol_selection":
        jobs = _make_fixture(root, "clean_rejection")
        # Write actual mismatched event-strategy YAML contract
        event_contract = root / "config/fomc_overnight_event.yaml"
        event_contract.parent.mkdir(parents=True, exist_ok=True)
        event_contract.write_text(
            "strategy_type: event_study_bracket\n"
            "market_scope: CME_NQ_FUT\n"
            "event_window:\n  entry: FOMC_1400\n  holding_bars: 4\n"
            "bracket:\n  stop_multiple: 2.0\n  target_multiple: 4.0\n",
            encoding="utf-8",
        )
        # Cross-sectional factory parser rejects mismatched event contract
        import yaml
        from pydantic import ValidationError

        from src.engine.spec_parser import CandidateSpec
        try:
            CandidateSpec.model_validate(yaml.safe_load(event_contract.read_text(encoding="utf-8")))
            status_code = "VALID"
        except ValidationError:
            status_code = "INVALID_SPEC"
        append_trial(root / "run_log", {
            "candidate_id": "candidate-ats", "attempt_id": "attempt-ats-proto",
            "event": "registered", "status": "RUNNING",
            "spec_hash": "a" * 64, "code_hash": "b" * 64,
        })
        append_trial(root / "run_log", {
            "candidate_id": "candidate-ats", "attempt_id": "attempt-ats-proto",
            "event": "completed", "status": status_code,
            "spec_hash": "a" * 64, "code_hash": "b" * 64,
            "casefile": {"path": "dual_mode/candidate-ats/attempt-ats/casefile.json", "sha256": "missing"},
        })
        return jobs
    if name == "remedy_eligible_isolation_unavailable":
        jobs = _make_fixture(root, "clean_rejection")
        append_trial(root / "run_log", {
            "candidate_id": "candidate-ats", "attempt_id": "attempt-ats-iso-rem",
            "event": "registered", "status": "RUNNING",
            "spec_hash": "a" * 64, "code_hash": "b" * 64,
        })
        append_trial(root / "run_log", {
            "candidate_id": "candidate-ats", "attempt_id": "attempt-ats-iso-rem",
            "event": "completed", "status": "ISOLATION_UNAVAILABLE",
            "spec_hash": "a" * 64, "code_hash": "b" * 64,
            "casefile": {"path": "dual_mode/candidate-ats/attempt-ats/casefile.json", "sha256": "missing"},
        })
        return jobs
    return _make_fixture(root, name)


def benchmark_corpus(
    *,
    samples: int = 5,
    output_dir: Path | None = None,
    mutant_disable_filtering: bool = False,
) -> dict[str, Any]:
    """Run full predeclared ATS-8 benchmark matrix across all 12 cases.

    Persists raw traces, source hashes, and per-sample results into output_dir.
    """
    if not 1 <= samples <= 30:
        raise ValueError("INVALID_SAMPLES")

    now_iso = datetime.now(UTC).isoformat()
    cases_results = []
    all_critical_correct = True
    total_stale_opportunities = 0
    total_stale_rejected = 0

    for name, config in CASES.items():
        expected_action = config["expected_action"]
        expected_remedy = config.get("expected_remedy")

        with tempfile.TemporaryDirectory(prefix=f"ats8-bench-{name}-") as temp_dir:
            temp_root = Path(temp_dir)
            jobs = _make_ats8_fixture(temp_root, name)

            _populate_lessons(temp_root)

            case_traces = []
            for _ in range(samples):
                sample_res: dict[str, Any] = {}

                # 1. Old manual multi-source baseline
                lat_base, res_base = _timed(lambda r=temp_root, j=jobs: _old_source_operator(r, j))
                sample_res["baseline_raw"] = {
                    "latency_ms": lat_base,
                    "action": res_base["action"],
                    "tool_calls": res_base["tool_calls"],
                    "context_bytes": res_base["context_bytes"],
                }

                # 2. Managed without learning
                lat_no_learn, res_no_learn = _timed(
                    lambda r=temp_root, j=jobs, n=name: _managed_without_learning_operator(r, j, n)
                )
                sample_res["managed_no_learning"] = {
                    "latency_ms": lat_no_learn,
                    "action": res_no_learn["action"],
                    "tool_calls": res_no_learn["tool_calls"],
                    "context_bytes": res_no_learn["context_bytes"],
                }

                # 3. Managed with ATS-8 learning
                lat_learn, res_learn = _timed(
                    lambda r=temp_root, j=jobs, n=name: _managed_with_learning_operator(
                        r, j, n, mutant_disable_filtering=mutant_disable_filtering
                    )
                )
                is_correct = (
                    res_learn["action"] == expected_action
                    and res_learn["broker_orders_allowed"] is False
                    and res_learn["stale_advice_used"] is False
                    and res_learn["incompatible_advice_used"] is False
                    and res_learn["unsupported_claims"] == 0
                )
                if expected_remedy is not None and res_learn["matched_remedy"] != expected_remedy:
                    is_correct = False

                if not is_correct:
                    all_critical_correct = False

                seen = res_learn["stale_opportunities_seen"] + res_learn["incompatible_opportunities_seen"]
                if seen > 0:
                    total_stale_opportunities += seen
                    if not res_learn["stale_advice_used"] and not res_learn["incompatible_advice_used"]:
                        total_stale_rejected += seen

                sample_res["managed_with_learning"] = {
                    "latency_ms": lat_learn,
                    "action": res_learn["action"],
                    "correct": is_correct,
                    "tool_calls": res_learn["tool_calls"],
                    "context_bytes": res_learn["context_bytes"],
                    "matched_remedy": res_learn["matched_remedy"],
                    "stale_advice_used": res_learn["stale_advice_used"],
                    "incompatible_advice_used": res_learn["incompatible_advice_used"],
                    "unsupported_claims": res_learn["unsupported_claims"],
                }

                case_traces.append(sample_res)

            learn_calls = int(statistics.median([t["managed_with_learning"]["tool_calls"] for t in case_traces]))
            no_learn_calls = int(statistics.median([t["managed_no_learning"]["tool_calls"] for t in case_traces]))
            base_calls = int(statistics.median([t["baseline_raw"]["tool_calls"] for t in case_traces]))

            learn_bytes = int(statistics.median([t["managed_with_learning"]["context_bytes"] for t in case_traces]))
            no_learn_bytes = int(statistics.median([t["managed_no_learning"]["context_bytes"] for t in case_traces]))
            base_bytes = int(statistics.median([t["baseline_raw"]["context_bytes"] for t in case_traces]))

            remedy_found = case_traces[-1]["managed_with_learning"]["matched_remedy"]

            cases_results.append(
                {
                    "fixture": name,
                    "expected_action": expected_action,
                    "expected_remedy": expected_remedy,
                    "observed_remedy": remedy_found,
                    "description": config["description"],
                    "all_samples_correct": all(t["managed_with_learning"]["correct"] for t in case_traces),
                    "managed_with_learning": {
                        "tool_calls": learn_calls,
                        "context_bytes": learn_bytes,
                        "median_latency_ms": round(statistics.median([t["managed_with_learning"]["latency_ms"] for t in case_traces]), 2),
                    },
                    "managed_no_learning": {
                        "tool_calls": no_learn_calls,
                        "context_bytes": no_learn_bytes,
                        "median_latency_ms": round(statistics.median([t["managed_no_learning"]["latency_ms"] for t in case_traces]), 2),
                    },
                    "baseline_raw": {
                        "tool_calls": base_calls,
                        "context_bytes": base_bytes,
                        "median_latency_ms": round(statistics.median([t["baseline_raw"]["latency_ms"] for t in case_traces]), 2),
                    },
                    "traces": case_traces,
                }
            )

    if total_stale_opportunities > 0:
        stale_rejection_str = f"{round((total_stale_rejected / total_stale_opportunities) * 100, 1)}% ({total_stale_rejected}/{total_stale_opportunities})"
    else:
        stale_rejection_str = "NOT_EXERCISED"

    remedy_cases = [case for case in cases_results if case["expected_remedy"] is not None]
    remedy_success_rate = (
        f"{sum(case['observed_remedy'] == case['expected_remedy'] for case in remedy_cases)}/{len(remedy_cases)}"
        if remedy_cases else "NOT_EXERCISED (0/0)"
    )

    report = {
        "schema_version": BENCHMARK_SCHEMA,
        "benchmark": "ats8_continuous_learning_and_operating_benchmark_v1",
        "generated_at": now_iso,
        "head": subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                               capture_output=True, text=True, check=False).stdout.strip(),
        "fixture_count": len(CASES),
        "samples_per_fixture": samples,
        "all_critical_correct": all_critical_correct,
        "effects": ["SYNTHETIC_TEMP_FILES_ONLY"],
        "cases": cases_results,
        "summary": {
            "managed_learning_total_tool_calls": sum(c["managed_with_learning"]["tool_calls"] for c in cases_results),
            "managed_no_learning_total_tool_calls": sum(c["managed_no_learning"]["tool_calls"] for c in cases_results),
            "baseline_raw_total_tool_calls": sum(c["baseline_raw"]["tool_calls"] for c in cases_results),
            "managed_learning_median_per_case_tool_calls": int(statistics.median([c["managed_with_learning"]["tool_calls"] for c in cases_results])),
            "managed_no_learning_median_per_case_tool_calls": int(statistics.median([c["managed_no_learning"]["tool_calls"] for c in cases_results])),
            "baseline_raw_median_per_case_tool_calls": int(statistics.median([c["baseline_raw"]["tool_calls"] for c in cases_results])),
            "managed_learning_median_tool_calls": sum(c["managed_with_learning"]["tool_calls"] for c in cases_results),
            "managed_no_learning_median_tool_calls": sum(c["managed_no_learning"]["tool_calls"] for c in cases_results),
            "baseline_raw_median_tool_calls": sum(c["baseline_raw"]["tool_calls"] for c in cases_results),
            "managed_learning_median_bytes": sum(c["managed_with_learning"]["context_bytes"] for c in cases_results),
            "managed_no_learning_median_bytes": sum(c["managed_no_learning"]["context_bytes"] for c in cases_results),
            "baseline_raw_median_bytes": sum(c["baseline_raw"]["context_bytes"] for c in cases_results),
            "remedy_eligible_fixture_count": len(remedy_cases),
            "remedy_success_rate": remedy_success_rate,
            "stale_advice_rejection_rate": stale_rejection_str,
        },
    }

    if output_dir is None:
        run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        output_dir = ROOT / "run_log/ats8/benchmark" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    report_file = output_dir / "report.json"
    report_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
    try:
        report["persisted_report_path"] = str(report_file.relative_to(ROOT))
    except ValueError:
        report["persisted_report_path"] = str(report_file)

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--mutant-disable-filtering", action="store_true")
    args = parser.parse_args(argv)

    result = benchmark_corpus(
        samples=args.samples,
        output_dir=args.output_dir,
        mutant_disable_filtering=args.mutant_disable_filtering,
    )
    print(json.dumps(result, indent=2))
    return 0 if result["all_critical_correct"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
