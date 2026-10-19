import json
import subprocess
import sys
from dataclasses import replace
from datetime import datetime
from decimal import Decimal as D
from pathlib import Path
from typing import Literal

import pytest

from src.account_rules import (
    AccountBinding,
    ObservationCoverage,
    PhaseRule,
    RuleSource,
    RuleVersion,
    TermAssignment,
    replay,
)
from src.promoted_evidence import (
    NativeAccountRecord,
    PromotedEvidenceError,
    account_events_from_native,
    load_registration,
    verify_registration,
)

ROOT = Path(__file__).resolve().parents[1] / "promote" / "one_bar_nq_30m"
START = datetime.fromisoformat("2026-03-28T22:59:00Z")
END = datetime.fromisoformat("2026-03-30T23:00:00Z")
SOURCE = "a" * 64


def record(n, at, kind, amount="0", certainty: Literal["observed", "uncertain"] = "observed"):
    return NativeAccountRecord(
        str(n), datetime.fromisoformat(at), n, kind, D(amount), SOURCE, certainty,
    )


def rule():
    return RuleVersion(
        "fixture", "fixture", RuleSource("synthetic", "fixture://one-bar", START, "synthetic"),
        (PhaseRule("evaluation", "evaluation", D(".10"), 1),),
        "Europe/Prague", 0, D(".05"), D(".10"), mark_max_age_seconds=60,
    )


def account(coverage=()):
    return AccountBinding(
        "fixture", "fixture", START, D(100000), "evaluation",
        (TermAssignment(START, "fixture", "synthetic-only"),), coverage,
    )


@pytest.mark.skipif(not ROOT.is_dir(), reason="external frozen source not present")
def test_frozen_b0_source_registration_and_fail_closed_cross_gates(tmp_path):
    registration = load_registration(Path("config/promoted_qualification/one_bar_nq_30m.json"))
    result = verify_registration(registration, ROOT)
    assert result["source_identity"] == "VERIFIED"
    assert result["verdict"] == "INCONCLUSIVE"
    assert result["cross_gates"]["ATS7"].startswith("BLOCKED")
    assert "NO_B0_SPECIFIC_ATS7_STRATEGY_ADAPTER" in result["barriers"]
    output = tmp_path / "producer.json"
    output.write_text(json.dumps(result))
    judged = subprocess.run(
        [sys.executable, "scripts/promoted_outside_judge.py",
         "config/promoted_qualification/one_bar_nq_30m.json", str(ROOT), str(output)],
        check=False, capture_output=True, text=True,
    )
    assert judged.returncode == 0, judged.stdout + judged.stderr


def test_clean_ci_registration_fixture_and_positive_mint_denied(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "identity.txt").write_text("frozen\n")
    digest = __import__("hashlib").sha256((source / "identity.txt").read_bytes()).hexdigest()
    registration_path = tmp_path / "registration.json"
    registration_path.write_text(json.dumps({
        "schema_version": 1, "candidate_id": "fixture", "verdict": "INCONCLUSIVE",
        "source_files": [{"path": "identity.txt", "sha256": digest}],
    }))
    result = verify_registration(load_registration(registration_path), source)
    assert result["source_identity"] == "VERIFIED"
    value = json.loads(registration_path.read_text())
    value["verdict"] = "VERIFIED"
    registration_path.write_text(json.dumps(value))
    with pytest.raises(PromotedEvidenceError, match="CANNOT_MINT"):
        load_registration(registration_path)
    with pytest.raises(PromotedEvidenceError, match="CANNOT_MINT"):
        verify_registration(value, source)


def test_empty_source_registration_denied(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text(json.dumps({
        "schema_version": 1, "candidate_id": "empty", "verdict": "INCONCLUSIVE",
        "source_files": [],
    }))
    with pytest.raises(PromotedEvidenceError, match="EMPTY_SOURCE"):
        load_registration(path)
    result = verify_registration(json.loads(path.read_text()), tmp_path)
    assert result["source_identity"] == "REJECTED"


def test_native_records_reconcile_cash_fees_swap_and_floating_breach():
    records = [
        record(1, "2026-03-28T22:59:01Z", "position_opened"),
        record(2, "2026-03-28T22:59:02Z", "commission", "10"),
        record(3, "2026-03-28T22:59:03Z", "swap", "-5"),
        record(4, "2026-03-28T22:59:04Z", "mark", "-5000"),
        record(5, "2026-03-28T22:59:05Z", "mark", "100"),
    ]
    coverage = (ObservationCoverage(START, END, True, True),)
    result = replay(account(coverage), {"fixture": rule()}, account_events_from_native(records))
    assert result.decisions[4].state == "BREACHED"
    assert result.last.state == "BREACHED"
    assert result.last.balance == D(99985)
    assert result.last.equity == D(100085)


def test_missing_independent_coverage_is_inconclusive_even_with_marks_and_dst_reset():
    records = [
        record(1, "2026-03-28T23:00:00Z", "position_opened"),
        record(2, "2026-03-28T23:00:01Z", "mark", "0"),
        record(3, "2026-03-29T22:00:00Z", "mark", "0"),
    ]
    result = replay(account(), {"fixture": rule()}, account_events_from_native(records))
    resets = [decision.at for decision in result.decisions if decision.kind == "daily_reset"]
    assert resets == [
        datetime.fromisoformat("2026-03-28T23:00:00Z"),
        datetime.fromisoformat("2026-03-29T22:00:00Z"),
    ]
    assert result.last.state == "INCONCLUSIVE"
    assert "INCOMPLETE_COVERAGE" in result.last.evidence_gaps


def test_uncertain_gap_or_ambiguous_fill_and_duplicate_are_refused():
    uncertain = record(1, "2026-03-28T22:59:01Z", "position_opened", certainty="uncertain")
    with pytest.raises(PromotedEvidenceError, match="UNCERTAIN_NATIVE_EVENT"):
        account_events_from_native([uncertain])
    duplicate = record(1, "2026-03-28T22:59:02Z", "mark")
    with pytest.raises(PromotedEvidenceError, match="DUPLICATE_NATIVE_EVENT_ID"):
        account_events_from_native([duplicate, replace(duplicate, sequence=2,
            at=datetime.fromisoformat("2026-03-28T22:59:03Z"))])


def test_source_drift_blocks_registered_verdict(tmp_path):
    registration = {
        "schema_version": 1, "candidate_id": "x", "verdict": "INCONCLUSIVE",
        "source_files": [{"path": "source", "sha256": "0" * 64}],
    }
    (tmp_path / "source").write_text("changed")
    result = verify_registration(registration, tmp_path)
    assert result["verdict"] == "BLOCKED_SOURCE_DRIFT"
    assert result["failures"] == ["HASH_MISMATCH:source"]


def test_symlink_path_escape_and_duplicate_registration_fail_closed(tmp_path):
    outside = tmp_path.parent / "outside-promoted-source"
    outside.write_text("outside")
    (tmp_path / "linked").symlink_to(outside)
    base = {
        "schema_version": 1, "candidate_id": "x", "verdict": "INCONCLUSIVE",
        "source_files": [{"path": "linked", "sha256": "0" * 64}],
    }
    result = verify_registration(base, tmp_path)
    assert any(reason.startswith(("PATH_ESCAPE", "MISSING_OR_SYMLINK"))
               for reason in result["failures"])
    base["source_files"] *= 2
    result = verify_registration(base, tmp_path)
    assert "DUPLICATE_SOURCE_PATH" in result["failures"]
