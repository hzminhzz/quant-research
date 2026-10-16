"""Comprehensive tests for ATS-8 continuous learning and operating benchmark.

Adheres to ml4t-agent-state-memory, ml4t-agent-tool-contracts, and ml4t-agent-governance.
Verifies fail-closed protocol gates, scope gates, numeric semver, code/data drift,
and real historical regression execution.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.benchmark_ats8_learning import benchmark_corpus
from scripts.benchmark_ats8_learning import main as benchmark_main
from src.engine.common import beneath
from src.research_control.learning import (
    AgentLearningState,
    LessonRecordV1,
    LessonStore,
    _parse_semver,
    create_lesson,
)
from src.research_control.learning import (
    main as learning_main,
)


@pytest.fixture
def store_root(tmp_path: Path) -> Path:
    """Fixture providing a temporary repository root with initialized lesson store."""
    lessons_dir = tmp_path / "docs/lessons"
    lessons_dir.mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_semver_parsing_and_numeric_comparison():
    assert _parse_semver("1.10.0") > _parse_semver("1.9.0")
    assert _parse_semver("0.1.4") < _parse_semver("0.1.5")
    assert _parse_semver("2.0") == (2, 0)
    with pytest.raises(ValueError, match="INVALID_VERSION_STRING"):
        _parse_semver("unversioned")


def test_lesson_creation_and_cryptographic_digest(store_root: Path):
    lesson = create_lesson(
        lesson_id="LSN-20261015-TEST-LESSON",
        knowledge_class="implementation_recipe",
        trigger="Test trigger failure",
        error_codes=("TEST_ERROR_CODE",),
        affected_scope=("src/test.py",),
        protocol="test_protocol",
        evidence_ref="commit test",
        root_cause="Test root cause explanation.",
        verified_remedy="Test verified remedy action.",
        regression_test="tests/test_ats8_learning.py::test_lesson_creation_and_cryptographic_digest",
        reviewer="test_reviewer",
    )
    assert lesson.lesson_id == "LSN-20261015-TEST-LESSON"
    assert len(lesson.digest) == 64

    # Digest mismatch must fail validation
    tampered = lesson.model_dump(mode="json")
    tampered["trigger"] = "Tampered trigger string"
    with pytest.raises(ValueError, match="LESSON_DIGEST_MISMATCH"):
        LessonRecordV1.model_validate(tampered)


def test_protocol_and_scope_mismatch_fail_closed_before_scoring(store_root: Path):
    """Same error code must NOT match if protocol or scope conflicts."""
    store = LessonStore(store_root)
    lesson = create_lesson(
        lesson_id="LSN-20261016-BRACKET-SPECIFIC-ERROR",
        knowledge_class="implementation_recipe",
        trigger="Bracket execution failure",
        error_codes=("SHARED_ERROR_CODE",),
        affected_scope=("src/research_control/action_worker.py",),
        protocol="native_bracket_v1",
        evidence_ref="commit 123456",
        root_cause="Specific to bracket protocol.",
        verified_remedy="Apply bracket remedy.",
        regression_test="tests/test_bracket.py",
        reviewer="hzminhzz",
    )
    store.save(lesson)

    # 1. Matching error code but conflicting protocol -> PROTOCOL_MISMATCH (rejected)
    query_conflict = store.query(
        error_code="SHARED_ERROR_CODE",
        protocol="cross_sectional_factor_v1",
        include_invalid=False,
    )
    assert len(query_conflict) == 0

    query_conflict_all = store.query(
        error_code="SHARED_ERROR_CODE",
        protocol="cross_sectional_factor_v1",
        include_invalid=True,
    )
    assert len(query_conflict_all) == 1
    assert query_conflict_all[0].validity == "PROTOCOL_MISMATCH"

    # 2. Matching error code but conflicting scope -> SCOPE_MISMATCH (rejected)
    query_scope = store.query(
        error_code="SHARED_ERROR_CODE",
        scope_path="src/unrelated/pipeline.py",
        include_invalid=False,
    )
    assert len(query_scope) == 0

    query_scope_all = store.query(
        error_code="SHARED_ERROR_CODE",
        scope_path="src/unrelated/pipeline.py",
        include_invalid=True,
    )
    assert len(query_scope_all) == 1
    assert query_scope_all[0].validity == "SCOPE_MISMATCH"


def test_version_numeric_comparison_and_missing_version_fail_closed(store_root: Path):
    store = LessonStore(store_root)
    lesson = create_lesson(
        lesson_id="LSN-20261016-NUMERIC-BOUND-LESSON",
        knowledge_class="implementation_recipe",
        trigger="Feature requiring engine 1.10.0",
        error_codes=("BOUND_TEST",),
        affected_scope=("src/engine.py",),
        protocol="dual_mode_v1",
        version_bounds={"ml4t-engineer": "1.10.0"},
        evidence_ref="commit 789abc",
        root_cause="Requires semver >= 1.10.0.",
        verified_remedy="Upgrade engine.",
        regression_test="tests/test_engine.py",
        reviewer="hzminhzz",
    )
    store.save(lesson)

    # Missing versions dictionary -> fails closed as VERSION_INCOMPATIBLE
    status, reason = store.evaluate_validity(lesson, current_versions=None)
    assert status == "VERSION_INCOMPATIBLE"
    assert "missing" in (reason or "")

    # Lexically 1.9 > 1.10, but numerically 1.9 < 1.10 -> must be rejected as INCOMPATIBLE
    status, reason = store.evaluate_validity(lesson, current_versions={"ml4t-engineer": "1.9.0"})
    assert status == "VERSION_INCOMPATIBLE"
    assert "1.9.0 < required 1.10.0" in (reason or "")

    # Numerically 1.10.0 or 1.11.0 -> VALID
    status, _ = store.evaluate_validity(lesson, current_versions={"ml4t-engineer": "1.10.0"})
    assert status == "VALID"
    status, _ = store.evaluate_validity(lesson, current_versions={"ml4t-engineer": "1.11.0"})
    assert status == "VALID"


def test_code_and_data_drift_fail_closed(store_root: Path):
    store = LessonStore(store_root)
    lesson = create_lesson(
        lesson_id="LSN-20261016-DRIFT-TEST-LESSON",
        knowledge_class="implementation_recipe",
        trigger="Failure with bound code/data digest",
        error_codes=("DRIFT_TEST",),
        affected_scope=("src/code.py",),
        protocol="any",
        bound_code_hashes={"src/code.py": "a" * 64},
        bound_data_hashes={"data/bars.parquet": "b" * 64},
        evidence_ref="commit 111222",
        root_cause="Bound to specific source snapshot.",
        verified_remedy="Fix drift.",
        regression_test="tests/test_drift.py",
        reviewer="hzminhzz",
    )
    store.save(lesson)

    # Missing hashes -> fails closed
    status, _ = store.evaluate_validity(lesson)
    assert status == "CODE_DRIFT"

    # Mismatched code hash -> fails closed
    status, reason = store.evaluate_validity(lesson, code_hashes={"src/code.py": "f" * 64})
    assert status == "CODE_DRIFT"
    assert "Code drift" in (reason or "")

    # Correct code hash but mismatched data hash -> fails closed
    status, reason = store.evaluate_validity(
        lesson,
        code_hashes={"src/code.py": "a" * 64},
        data_hashes={"data/bars.parquet": "f" * 64},
    )
    assert status == "DATA_DRIFT"
    assert "Data drift" in (reason or "")

    # Both matching -> VALID
    status, _ = store.evaluate_validity(
        lesson,
        code_hashes={"src/code.py": "a" * 64},
        data_hashes={"data/bars.parquet": "b" * 64},
    )
    assert status == "VALID"


def test_agent_learning_state_checkpoint_serialization(tmp_path: Path):
    """Test checkpointable state object conforming to ml4t-agent-state-memory."""
    state = AgentLearningState(
        task="Triage blocked research attempt candidate-1",
        session_id="session-ats8-01",
        observed_at="2026-10-16T10:00:00Z",
        applied_lessons=("LSN-20261015-OVERSIZE-CASEFILE-STREAM",),
        rejected_lessons=("LSN-20261010-LEGACY-V1-PERMIT-OVERRIDE",),
        tool_trace=(
            {"tool": "inspect_case", "status": "BLOCKED", "reason_code": "EVIDENCE_TOO_LARGE"},
            {"tool": "query_lessons", "matches": 1, "lesson_id": "LSN-20261015-OVERSIZE-CASEFILE-STREAM"},
        ),
        quality_gates={"read_relevant_skills": True, "remedy_verified": True},
    )
    serialized = state.model_dump_json(indent=2)
    checkpoint_file = tmp_path / "learning_state.json"
    checkpoint_file.write_text(serialized, encoding="utf-8")

    loaded = AgentLearningState.model_validate(json.loads(checkpoint_file.read_text(encoding="utf-8")))
    assert loaded.session_id == state.session_id
    assert loaded.applied_lessons == state.applied_lessons
    assert loaded.quality_gates["read_relevant_skills"] is True


def test_learning_cli_interface(store_root: Path, capsys: pytest.CaptureFixture):
    store = LessonStore(store_root)
    lesson = create_lesson(
        lesson_id="LSN-20261015-OVERSIZE-CASEFILE-STREAM",
        knowledge_class="implementation_recipe",
        trigger="EVIDENCE_TOO_LARGE when reading casefile",
        error_codes=("EVIDENCE_TOO_LARGE",),
        affected_scope=("src/research_control/agent_interface.py",),
        protocol="dual_mode_v1",
        evidence_ref="commit 260b14e",
        root_cause="Eager JSON parsing of bulk arrays.",
        verified_remedy="Stream SHA-256 byte digest against ledger.",
        regression_test="tests/test_ats_qualification.py::test_large_casefile_stream_hash_and_receipts_without_json_decode",
        reviewer="hzminhzz",
    )
    store.save(lesson)

    # 1. validate command
    ret = learning_main(["validate", "--root", str(store_root)])
    assert ret == 0
    captured = json.loads(capsys.readouterr().out)
    assert captured["status"] == "ALL_DIGESTS_VERIFIED"
    assert captured["validated"] == 1

    # 2. list command
    ret = learning_main(["list", "--root", str(store_root)])
    assert ret == 0
    captured = json.loads(capsys.readouterr().out)
    assert captured["total"] == 1
    assert captured["lessons"][0]["lesson_id"] == "LSN-20261015-OVERSIZE-CASEFILE-STREAM"

    # 3. query command
    ret = learning_main(["query", "--root", str(store_root), "--error-code", "EVIDENCE_TOO_LARGE"])
    assert ret == 0
    captured = json.loads(capsys.readouterr().out)
    assert captured["matched"] == 1
    assert captured["results"][0]["lesson"]["lesson_id"] == "LSN-20261015-OVERSIZE-CASEFILE-STREAM"


def test_real_historical_failure_and_verified_remedy_cycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Demonstrate the full lifecycle:
    1. Original failure accurately reproduced (eager decode fails when forbidden or oversized).
    2. Relevant lesson queried and retrieved based on trigger/error.
    3. Prescribed remedy applied (streaming hash verification without full decode).
    4. Workflow completes with verified recovery.
    5. Prescribed regression test executes and passes.
    """
    from scripts.benchmark_ats8_learning import _populate_lessons
    from src.research_control.agent_interface import inspect_case, read_evidence
    from tests.test_ats_read_interface import fixture

    casefile_path = fixture(tmp_path, large=True)

    # 1. Historical pre-fix implementation from commit 407e6e6 (_safe_json):
    def historical_commit_407e6e6_safe_json(root: Path, rel: str, *, max_bytes: int = 256_000) -> dict:
        path = beneath(root, rel, must_exist=True)
        if path.stat().st_size > max_bytes:
            raise ValueError("EVIDENCE_TOO_LARGE")
        return json.loads(path.read_text(encoding="utf-8"))

    rel = str(casefile_path.relative_to(tmp_path))
    # Exact historical implementation raises EVIDENCE_TOO_LARGE on the oversized file:
    with pytest.raises(ValueError, match="EVIDENCE_TOO_LARGE"):
        historical_commit_407e6e6_safe_json(tmp_path, rel)

    # 1b. If size check is bypassed to attempt non-streaming read, eager decode triggers the regression guard:
    original_read = Path.read_text
    def forbid_full_casefile_decode(self, *args, **kwargs):
        if self == casefile_path:
            raise AssertionError("full casefile JSON decoded! Historical eager decode triggered.")
        return original_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", forbid_full_casefile_decode)
    with pytest.raises(AssertionError, match="full casefile JSON decoded"):
        historical_commit_407e6e6_safe_json(tmp_path, rel, max_bytes=10_000_000)

    # 2. Retrieve lesson from store using observed error and environment version
    _populate_lessons(tmp_path)
    store = LessonStore(tmp_path)

    matches = store.query(
        error_code="EVIDENCE_TOO_LARGE",
        protocol="dual_mode_v1",
        current_versions={"ml4t-engineer": "0.1.4"},
    )
    assert len(matches) == 1
    lesson_match = matches[0]
    assert lesson_match.validity == "VALID"
    assert lesson_match.lesson.lesson_id == "LSN-20261015-OVERSIZE-CASEFILE-STREAM"
    assert "Stream SHA-256 byte digest" in lesson_match.lesson.verified_remedy

    # 3. Current remedied implementation passes the exact same regression guard
    view = inspect_case(tmp_path, list_jobs=lambda: set())
    assert view["status"] == "REVIEW"
    assert view["research"][0]["source_bytes"] > 256_000
    assert view["research"][0]["evidence_access"] == "INTEGRITY_VERIFIED"
    assert view["next_action"]["kind"] == "review_research"

    # 4. read_evidence also succeeds without decoding full casefile
    evidence = read_evidence(tmp_path, view["research"][0]["source_ref"])
    assert evidence["digest"] == view["research"][0]["source_sha256"]
    assert evidence["status"] == "FALSIFIED_STAGE_2"

def test_real_historical_regressions_execute_and_pass():
    """Verify that the regression tests cited in canonical lessons actually run and pass."""
    # 1. Regression for LSN-20261015-OVERSIZE-CASEFILE-STREAM
    import subprocess
    proc1 = subprocess.run(
        ["pytest", "tests/test_ats_qualification.py", "-k", "test_large_casefile_stream_hash_and_receipts_without_json_decode"],
        capture_output=True, text=True, check=False,
    )
    assert proc1.returncode == 0, proc1.stdout + proc1.stderr

    # 2. Regression for LSN-20261016-CGROUP-V2-MEMORY-CONTAINMENT
    proc2 = subprocess.run(
        ["pytest", "tests/test_ats2_resource_limits.py", "-k", "test_unavailable_cgroup_does_not_consume_admission"],
        capture_output=True, text=True, check=False,
    )
    assert proc2.returncode == 0, proc2.stdout + proc2.stderr


def test_benchmark_ats8_runs_and_passes(tmp_path: Path):
    """Test full execution of the independent ATS-8 benchmark harness with trace persistence."""
    result = benchmark_corpus(samples=1, output_dir=tmp_path / "bench_run")
    assert result["fixture_count"] == 14
    assert result["all_critical_correct"] is True
    assert (tmp_path / "bench_run/report.json").is_file()

    # CLI main execution
    exit_code = benchmark_main(["--samples", "1", "--output-dir", str(tmp_path / "cli_run")])
    assert exit_code == 0
    assert (tmp_path / "cli_run/report.json").is_file()

def test_benchmark_mutation_disabling_compatibility_filtering_fails(tmp_path: Path):
    """Verify that disabling compatibility filtering causes the benchmark to fail."""
    exit_code = benchmark_main([
        "--samples", "1",
        "--output-dir", str(tmp_path / "mutant_run"),
        "--mutant-disable-filtering",
    ])
    assert exit_code == 1, "Benchmark must fail when compatibility filtering is disabled!"
    report = json.loads((tmp_path / "mutant_run/report.json").read_text(encoding="utf-8"))
    assert report["all_critical_correct"] is False
