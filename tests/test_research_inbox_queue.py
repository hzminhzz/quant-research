"""Fail-closed research inbox queue acceptance, recovery and idempotence tests."""
from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path

import pytest
import yaml

from src.research_control.research_inbox_queue import InboxQueue, _semantic_id, classify

ROOT = Path(__file__).resolve().parents[1]
HANDOFF = ROOT / "research_inbox" / "audusd_policy_carry_cfd_v1"
PUBLISHED_EVENT_HANDOFFS = (
    "audusd_policy_carry_cfd_v1",
    "dax_monthend_liquidity_rebound_cfd_20261015_v1",
    "fomc_overnight_uncertainty_premium_us500_cfd_20261015_v1",
    "gbpusd_weekend_gap_reversal_cfd_20261015_v1",
    "hanna_spy_bear_gap_fade_us500_cfd_20261017_1600_v1",
    "oil_to_cad_daily_delayed_adjustment_20261015_v1",
    "us500_european_open_uncertainty_resolution_cfd_v1",
)


def _copy_handoff(tmp_path: Path, name: str = "audusd_policy_carry_cfd_v1") -> Path:
    target = tmp_path / "inbox" / name
    shutil.copytree(HANDOFF, target)
    if name != HANDOFF.name:
        text = (target / "thesis.yaml").read_text()
        doc = yaml.safe_load(text)
        doc["candidate_id"] = name
        (target / "thesis.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
        brief = (target / "brief.md").read_text()
        (target / "brief.md").write_text(brief.replace(HANDOFF.name, name), encoding="utf-8")
    return target


def _queue(tmp_path: Path) -> InboxQueue:
    _copy_handoff(tmp_path)
    return InboxQueue(tmp_path / "inbox", tmp_path / "log", vault_root=tmp_path / "vault",
                       store=tmp_path / "absent-store")


def test_real_handoffs_are_valid_and_blocked_without_backtest(tmp_path, monkeypatch):
    import subprocess

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("native runner must not execute"))
    for name in PUBLISHED_EVENT_HANDOFFS:
        shutil.copytree(ROOT / "research_inbox" / name, tmp_path / "inbox" / name)
    # The seven historical event candidates are a fixed regression corpus.
    # Adding future executable handoffs must not break this safety test.
    queue = InboxQueue(tmp_path / "inbox", tmp_path / "log", vault_root=tmp_path / "vault",
                       store=tmp_path / "absent-store")
    first = queue.run()
    assert first["counts"]["total"] == first["counts"]["captured"] == 7
    assert first["counts"]["admitted"] == 7
    assert first["counts"]["native_runs"] == first["counts"]["trial_started"] == 0
    assert first["counts"]["stage1"] == first["counts"]["stage2"] == 0
    assert first["counts"]["stage3"] == first["counts"]["stage4"] == 0
    assert first["counts"]["blocked"] == 7
    assert all(c["status"] == "BLOCKED_PROTOCOL" for c in first["cases"])
    before = {p.name: len(list((queue._folder(p.name) / "events").glob("*.json")))
              for p in queue._candidates()}
    assert queue.run() == first
    after = {p.name: len(list((queue._folder(p.name) / "events").glob("*.json")))
             for p in queue._candidates()}
    assert before == after


def test_explicit_structural_protocols():
    assert classify({
        "entry_and_basket_construction_rules": {"universe": {}, "allocation": {}},
        "signal": "candidate"
    }) == "cross_sectional"
    assert classify({"strategy_rules": {"entry": "time", "stop": "none"}}) == "single_instrument_event"
    assert classify({"strategy_rules": {
        "entry": "time", "trailing_stop": {"enabled": True, "multiple": 1.5}
    }}) == "path_dependent"
    assert classify({"strategy_rules": {"source_rules": {
        "stop": "author's published historical stop"}, "entry": "time"
    }}) == "single_instrument_event"


def test_bad_candidate_directory_is_blocked_without_aborting_queue(tmp_path):
    queue = _queue(tmp_path)
    shutil.copytree(HANDOFF, tmp_path / "inbox" / "bad-name!")
    report = queue.run()
    assert report["counts"]["total"] == 2
    assert report["counts"]["blocked"] == 2
    invalid = next(c for c in report["cases"] if c["candidate_id"] == "bad-name!")
    assert invalid["status"] == "BLOCKED_HANDOFF"
    assert queue._folder("bad-name!").is_relative_to(queue.root / "candidates")
    assert queue.run() == report


def test_yaml_alias_cycle_is_rejected_as_invalid_source(tmp_path):
    candidate = tmp_path / "inbox" / "cyclic_source"
    candidate.mkdir(parents=True)
    (candidate / "thesis.yaml").write_text("cycle: &cycle [*cycle]\n", encoding="utf-8")
    (candidate / "brief.md").write_text("cyclic_source\n", encoding="utf-8")
    queue = InboxQueue(tmp_path / "inbox", tmp_path / "log", store=tmp_path / "absent-store")
    report = queue.run()
    assert report["cases"][0]["status"] == "BLOCKED_HANDOFF"
    assert "cyclic values" in report["cases"][0]["reason"]
    assert report["counts"]["trial_started"] == 0


def test_source_revision_during_admission_blocks_without_native_execution(tmp_path, monkeypatch):
    queue = _queue(tmp_path)
    import src.research_control.research_inbox_queue as module

    original = module.validate_handoff

    def mutation_after_validation(directory):
        validated = original(directory)
        brief = directory / "brief.md"
        brief.write_text(brief.read_text() + "\nUnexpected concurrent revision.\n")
        return validated

    monkeypatch.setattr(module, "validate_handoff", mutation_after_validation)
    report = queue.run()
    assert report["cases"][0]["status"] == "BLOCKED_HANDOFF"
    assert "changed during admission" in report["cases"][0]["reason"]
    assert not (queue.run_log / "trial_ledger.jsonl").exists()


def test_full_source_corpus_is_captured_without_schema_blocking(tmp_path):
    inbox = ROOT / "research_inbox"
    documents = [yaml.safe_load(path.read_text(encoding="utf-8"))
                 for path in sorted(inbox.glob("*/thesis.yaml"))]
    expected_nested = sum("identity" in doc for doc in documents)
    expected_strict = sum("identity" not in doc and
                          doc.get("status") == "THESIS_READY_UNVERIFIED" for doc in documents)
    expected_flat = sum("identity" not in doc and
                        doc.get("status") in {"THESIS_CAPTURED", "DRAFT_UNVERIFIED"}
                        for doc in documents)
    assert len(documents) == expected_nested + expected_strict + expected_flat
    assert expected_nested >= 62 and expected_strict == 8 and expected_flat >= 5
    target = tmp_path / "inbox"
    shutil.copytree(inbox, target)
    queue = InboxQueue(target, tmp_path / "log", vault_root=tmp_path / "vault",
                       store=tmp_path / "absent-store")
    report = queue.run()
    assert report["counts"]["total"] == report["counts"]["captured"] == len(documents)
    # One published abstract cites its DOI only in the brief and a different
    # publisher URL in YAML. Keep it source-visible but fail closed on linkage.
    blocked_handoff = [case for case in report["cases"] if not case.get("admitted")]
    assert {case["candidate_id"] for case in blocked_handoff} == {
        "crypto_ml_fieberg_ctrend_price_volume_factor_2025_v1"}
    assert all("brief lacks candidate or exact source URL anchor" in case["reason"]
               for case in blocked_handoff)
    assert report["counts"]["admitted"] == len(documents) - len(blocked_handoff)
    status_counts = Counter(case["status"] for case in report["cases"])
    assert status_counts["BLOCKED_HANDOFF"] == len(blocked_handoff)
    assert status_counts["BLOCKED_PROTOCOL"] >= expected_strict
    assert sum(status_counts.values()) == len(documents)
    print("ISOLATED_SOURCE_TRIAGE_COUNTS", json.dumps(dict(sorted(status_counts.items()))))
    assert report["counts"]["native_runs"] == report["counts"]["trial_started"] == 0
    assert report["counts"]["stage1"] == report["counts"]["stage2"] == 0
    assert report["counts"]["stage3"] == report["counts"]["stage4"] == 0
    assert sum(case.get("source_format") == "nested_descriptive" for case in report["cases"]) == expected_nested
    assert sum(case.get("source_format") == "legacy_flat_handoff" for case in report["cases"]) == expected_strict
    assert sum(case.get("source_format") == "flat_descriptive" for case in report["cases"]) == expected_flat - len(blocked_handoff)
    nested = [case for case in report["cases"] if case.get("source_format") == "nested_descriptive"]
    flat = [case for case in report["cases"] if case.get("source_format") == "legacy_flat_handoff"]
    flat_captures = [case for case in report["cases"] if case.get("source_format") == "flat_descriptive"]
    assert all(case["source_hash"] and case["field_evidence"] and case["reason_codes"]
               for case in nested)
    assert all(set(case["source_files_sha256"]) == {"thesis.yaml", "brief.md"}
               and len(case["source_anchor_sha256"]) == 64 for case in nested)
    assert all(case["status"] == "BLOCKED_PROTOCOL" for case in flat)
    assert all(case["status"] == "BLOCKED_SPEC" and case["handoff_status"] == "SOURCE_ADMITTED"
               and case["triage_status"] == "BLOCKED" for case in flat_captures)
    assert sum(case["source_declared_status"] == "DRAFT_UNVERIFIED" for case in flat_captures) == sum(
        "identity" not in doc and doc.get("status") == "DRAFT_UNVERIFIED" for doc in documents)
    assert all("UNVERIFIED_EXECUTABLE_SPEC" in case["reason_codes"] for case in flat_captures)
    assert all(case["handoff_status"] == "SOURCE_ADMITTED"
               and case["triage_status"] == "BLOCKED" for case in nested)
    assert all(case["handoff_status"] == "SOURCE_ADMITTED"
               and case["triage_status"] == "BLOCKED" for case in nested)
    bta = next(case for case in flat if case["candidate_id"] == "bta_nq_monday_bb10_atr5_cfd_v1")
    assert bta["required_adaptations"]
    assert all(case["status"] != "BLOCKED_HANDOFF" for case in nested)
    for code in ("UNRESOLVED_SOURCE", "UNAVAILABLE_DATA", "UNQUALIFIED_PROTOCOL"):
        assert report["reason_counts"][code] == sum(
            code in case.get("reason_codes", []) for case in report["cases"])
    assert report["reason_counts"]["UNVERIFIED_EXECUTABLE_SPEC"] == expected_flat - len(blocked_handoff)
    assert any("CONTRADICTORY_RULES" in case.get("reason_codes", []) for case in nested)
    assert queue.run() == report


@pytest.mark.parametrize("name", [
    "alvarez_sp500_ibs_filtered_oversold_v1",
    "alvarez_sector_etf_middle_rank_1m_rotation_v1",
])
@pytest.mark.parametrize("field,value", [
    ("not_execution_approved", False),
    ("research_mode", "EXECUTABLE"),
    ("source_references", [{"source_id": "fake", "url": "https://example.com/invalid"}]),
])
def test_flat_capture_rejects_unsafe_authority_or_source(tmp_path, monkeypatch, name, field, value):
    import subprocess

    target = tmp_path / "inbox" / name
    shutil.copytree(ROOT / "research_inbox" / name, target)
    doc = yaml.safe_load((target / "thesis.yaml").read_text(encoding="utf-8"))
    doc[field] = value
    (target / "thesis.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: pytest.fail("native runner must not execute"))
    queue = InboxQueue(tmp_path / "inbox", tmp_path / "log", store=tmp_path / "absent-store")
    report = queue.run()
    assert report["cases"][0]["status"] == "BLOCKED_HANDOFF"
    assert report["counts"]["admitted"] == report["counts"]["trial_started"] == 0
    assert report["counts"]["stage4"] == 0


@pytest.mark.parametrize("candidate_id", [
    "crypto_ml_alessandretti_pooled_xgboost_2018_v1",
    "crypto_pairs_copula_stationary_spread_20261018_v1",
])
def test_descriptive_source_without_brief_anchor_fails_closed(tmp_path, monkeypatch, candidate_id):
    import subprocess

    target = tmp_path / "inbox" / candidate_id
    shutil.copytree(ROOT / "research_inbox" / candidate_id, target)
    (target / "brief.md").write_text("Unrelated note about a different paper.\n", encoding="utf-8")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("No native run authorized"))
    queue = InboxQueue(tmp_path / "inbox", tmp_path / "log", store=tmp_path / "absent-store")
    result = queue.run()
    assert result["cases"][0]["status"] == "BLOCKED_HANDOFF"
    assert result["counts"]["admitted"] == result["counts"]["trial_started"] == 0
    assert result["counts"]["stage4"] == 0


def test_runnable_cross_sectional_handoff_gets_bounded_queue_priority(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    (inbox / "a_event").mkdir(parents=True)
    (inbox / "z_cross_sectional").mkdir()
    queue = InboxQueue(inbox, tmp_path / "log", store=tmp_path / "absent-store")

    def admit(directory):
        protocol = "cross_sectional" if directory.name == "z_cross_sectional" else "single_instrument_event"
        return ({"candidate_id": directory.name, "source_hash": directory.name,
                 "semantic_id": directory.name, "admitted": True,
                 "source_format": "legacy_flat_handoff", "protocol": protocol,
                 "required_adaptations": [], "holdout_access": False},
                {"economic_thesis": directory.name})

    monkeypatch.setattr(queue, "_admit", admit)
    monkeypatch.setattr(queue, "_preflight", lambda info, doc, directory: (
        {**info, "status": "BLOCKED_SPEC", "reason": "test preflight"}, None))
    report = queue.run(max_candidates=1)
    states = {case["candidate_id"]: case["status"] for case in report["cases"]}
    assert states == {"a_event": "PENDING", "z_cross_sectional": "BLOCKED_SPEC"}
    assert report["counts"]["trial_started"] == report["counts"]["native_runs"] == 0


def test_source_revision_after_failed_envelope_is_append_only_and_retriaged(tmp_path):
    target = tmp_path / "inbox" / "crypto_xs_funding_innovation_shock_basket_v1"
    target.mkdir(parents=True)
    (target / "thesis.yaml").write_text("candidate_id: invalid\n")
    (target / "brief.md").write_text("invalid source")
    queue = InboxQueue(tmp_path / "inbox", tmp_path / "log", store=tmp_path / "absent-store")
    first = queue.run()
    assert first["cases"][0]["status"] == "BLOCKED_HANDOFF"
    old_event = queue._folder(target.name) / "events" / "000001.json"
    old_bytes = old_event.read_bytes()
    source = ROOT / "research_inbox" / target.name
    (target / "thesis.yaml").write_bytes((source / "thesis.yaml").read_bytes())
    (target / "brief.md").write_bytes((source / "brief.md").read_bytes())
    report = queue.run()
    state = queue._load(target.name)
    assert state["status"] in {"BLOCKED_SPEC", "BLOCKED_DATA", "BLOCKED_PROTOCOL"}
    assert state["source_revision_of"] == first["cases"][0]["source_hash"]
    assert old_event.read_bytes() == old_bytes
    assert report["counts"]["admitted"] == 1


def test_deduplication_preserves_distinct_experiment_windows_and_falsifiers():
    experiment = {
        "economic_thesis": {"statement": "test edge"},
        "strategy_rules": {"entry": "10:00 UTC"},
        "development_evaluation": {"windows": {"train": "2020", "validation": "2021"}},
        "primary_falsifier": {"threshold": 0.1},
        "data_requirements": {"panel_root": "canonical_v1"},
        "source_references": [{"id": "first_paper"}],
    }
    reference = _semantic_id(experiment)
    # Citation differences must not manufacture another economic trial.
    assert _semantic_id({**experiment, "source_references": [{"id": "second_paper"}]}) == reference
    assert _semantic_id({**experiment, "development_evaluation": {
        "windows": {"train": "2020", "validation": "2022"}}}) != reference
    assert _semantic_id({**experiment, "primary_falsifier": {"threshold": 0.2}}) != reference
    assert _semantic_id({**experiment, "data_requirements": {
        "panel_root": "canonical_v2"}}) != reference
    assert _semantic_id({**experiment, "unresolved_blockers": ["costs unknown"]}) != reference


def test_semantic_duplicate_preserves_one_trial_identity(tmp_path):
    _copy_handoff(tmp_path)
    _copy_handoff(tmp_path, "audusd_policy_carry_cfd_v2")
    queue = InboxQueue(tmp_path / "inbox", tmp_path / "log", vault_root=tmp_path / "vault",
                       store=tmp_path / "absent-store")
    report = queue.run()
    assert report["counts"]["total"] == 2
    assert report["counts"]["duplicates"] == 1
    assert report["counts"]["blocked"] == 1
    assert queue._load("audusd_policy_carry_cfd_v2")["duplicate_of"] == HANDOFF.name


def test_journal_replay_recovers_projection_crash(tmp_path):
    queue = _queue(tmp_path)
    queue.run()
    name = HANDOFF.name
    state = queue._load(name)
    assert state["status"] == "BLOCKED_PROTOCOL"
    projection = queue._folder(name) / "state.json"
    projection.write_text('{"status":"RUNNING","candidate_id":"wrong"}\n')
    assert queue._load(name) == state
    assert queue.run()["cases"][0]["status"] == "BLOCKED_PROTOCOL"
    assert state["revision"] == queue._load(name)["revision"]


def test_tampered_append_only_event_stops_resume(tmp_path):
    queue = _queue(tmp_path)
    queue.run()
    event = queue._folder(HANDOFF.name) / "events" / "000002.json"
    payload = json.loads(event.read_text())
    payload["state"]["status"] = "DEVELOPMENT_QUALIFIED"
    event.write_text(json.dumps(payload))
    with pytest.raises(RuntimeError, match="BROKEN_EVIDENCE"):
        queue.run()
    assert queue.report()["counts"]["blocked"] == 1
    assert queue.report()["cases"][0]["status"] == "BROKEN_EVIDENCE"


def test_interrupted_running_never_restarts_automatically(tmp_path, monkeypatch):
    import subprocess

    queue = _queue(tmp_path)
    queue.run()
    prior = queue._load(HANDOFF.name)
    queue._save({**prior, "status": "RUNNING", "attempt_id": "interrupted-native"})
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("unsafe retry"))
    report = queue.run()
    assert report["cases"][0]["status"] == "BLOCKED_RECOVERY"
    assert "reconcile" in report["cases"][0]["reason"]
    assert queue.run()["cases"][0]["status"] == "BLOCKED_RECOVERY"


def test_fingerprint_drift_freezes_prior_outcome(tmp_path):
    queue = _queue(tmp_path)
    queue.run()
    doc = HANDOFF.name
    original = queue._load(doc)
    brief = tmp_path / "inbox" / doc / "brief.md"
    brief.write_text(brief.read_text() + "\nAdditional source review pending.\n")
    report = queue.run()
    assert report["cases"][0]["status"] == "BLOCKED_DRIFT"
    assert queue._load(doc)["prior_status"] == original["status"]
    assert len(list((queue._folder(doc) / "events").glob("*.json"))) == 3


def test_concurrent_owner_fails_without_duplication(tmp_path):
    queue = _queue(tmp_path)
    with queue._owner(), pytest.raises(RuntimeError, match="QUEUE_BUSY"):
        queue.run()
    assert queue.report()["counts"]["pending"] == 1


@pytest.mark.parametrize("tamper", [
    {"holdout_access": True},
    {"holdout_claim": "fabricated_claim"},
    {"stages": {"4": {"status": "EVALUATED_ONCE"}}},
    {"development_only": False},
])
def test_native_verifier_rejects_holdout_or_misleading_evidence(tmp_path, tamper):
    queue = _queue(tmp_path)
    casefile = tmp_path / "casefile.json"
    payload = {
        "candidate_id": HANDOFF.name, "spec_hash": "test_spec",
        "development_only": True, "holdout_access": False,
        "status": "BLOCKED_DATA", "stages": {}, "attempt_id": "test_attempt",
    }
    payload.update(tamper)
    casefile.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="protected|development-only"):
        queue._native_verify(casefile, {"candidate_id": HANDOFF.name, "spec_hash": "test_spec"})


def test_bounded_resume_advances_past_terminal_entries(tmp_path):
    _copy_handoff(tmp_path)
    _copy_handoff(tmp_path, "audusd_policy_carry_cfd_v2")
    queue = InboxQueue(tmp_path / "inbox", tmp_path / "log", vault_root=tmp_path / "vault",
                       store=tmp_path / "absent-store")
    first = queue.run(max_candidates=1)
    assert first["counts"]["admitted"] == 1
    assert first["counts"]["pending"] == 1
    second = queue.run(max_candidates=1)
    assert second["counts"]["admitted"] == 2
    assert second["counts"]["pending"] == 0
    assert second["counts"]["duplicates"] == 1


def test_path_dependent_cannot_disguise_itself_as_cross_sectional():
    assert classify({"entry_and_basket_construction_rules": {
        "universe": {}, "allocation": {}}, "signal": "candidate",
        "strategy_rules": {"exit": "dynamic", "stop_loss": {"multiple": 1.0}}
    }) == "path_dependent"


def test_repeated_drift_does_not_create_endless_new_events(tmp_path):
    queue = _queue(tmp_path)
    queue.run()
    brief = tmp_path / "inbox" / HANDOFF.name / "brief.md"
    brief.write_text(brief.read_text() + "\nSource revision without new ID.\n")
    queue.run()
    count = len(list((queue._folder(HANDOFF.name) / "events").glob("*.json")))
    assert queue.run()["cases"][0]["status"] == "BLOCKED_DRIFT"
    assert len(list((queue._folder(HANDOFF.name) / "events").glob("*.json"))) == count


def test_cli_preflight_does_not_read_data_or_make_trades(tmp_path):
    queue = _queue(tmp_path)
    report = queue.run()
    assert report["cases"][0]["status"] == "BLOCKED_PROTOCOL"
    assert not (tmp_path / "log" / "trial_ledger.jsonl").exists()
    assert not (tmp_path / "log" / "_holdout_claims").exists()


def test_persisted_blocked_protocol_triggers_development_materialization(tmp_path, monkeypatch):
    handoff_name = "dax_monthend_liquidity_rebound_cfd_20261015_v1"
    target_inbox = tmp_path / "inbox" / handoff_name
    shutil.copytree(ROOT / "research_inbox" / handoff_name, target_inbox)

    vault_root = tmp_path / "vaults"
    vault_root.mkdir()
    fake_store = tmp_path / "store"
    fake_store.mkdir()

    queue = InboxQueue(tmp_path / "inbox", tmp_path / "log", vault_root=vault_root, store=fake_store)
    info, _doc = queue._admit(target_inbox)
    assert info is not None
    queue._save({**info, "status": "BLOCKED_PROTOCOL", "attempts": [], "holdout_access": False})

    events_folder = queue._folder(handoff_name) / "events"
    assert len(list(events_folder.glob("*.json"))) == 1

    materialized_calls = []

    def fake_materialize(_store, output, *, category, granularity, **_kwargs):
        manifest_file = Path(output) / "manifest.json"
        manifest_file.parent.mkdir(parents=True, exist_ok=True)
        manifest_file.write_text('{"status": "MOCK_COMPILED"}', encoding="utf-8")
        materialized_calls.append(f"{category}_{granularity}")
        return {"manifest_hash": "a" * 64}

    import src.data_vault.market_materializer as mm
    monkeypatch.setattr(mm, "materialize_price_markets", fake_materialize)

    report = queue.run()
    assert report["cases"][0]["status"] == "BLOCKED_PROTOCOL"
    assert len(list(events_folder.glob("*.json"))) == 2
    assert "index_1h" in materialized_calls
    assert "index_1m" in materialized_calls

    state = queue._load(handoff_name)
    assert state is not None
    assert state["status"] == "BLOCKED_PROTOCOL"
    assert state["revision"] == 2
    assert "materialized_development_vaults" in state
    assert "index_1h" in state["materialized_development_vaults"]
    assert "index_1m" in state["materialized_development_vaults"]


def test_version_aware_reconsideration_transitions_blocked_candidate(tmp_path, monkeypatch):
    handoff_name = "oil_to_cad_daily_delayed_adjustment_20261015_v1"
    target_inbox = tmp_path / "inbox" / handoff_name
    shutil.copytree(ROOT / "research_inbox" / handoff_name, target_inbox)
    queue = InboxQueue(tmp_path / "inbox", tmp_path / "log", vault_root=tmp_path / "vaults", store=tmp_path / "store")
    info, _doc = queue._admit(target_inbox)
    assert info is not None
    # Save prior blocked state with an outdated code_version
    queue._save({**info, "status": "BLOCKED_SPEC", "code_version": "stale_hash_00000000",
                 "attempts": [], "holdout_access": False})
    # Running queue reconsiders the candidate under the new code version
    queue.run()
    state = queue._load(handoff_name)
    assert state is not None
    assert state["status"] in {"BLOCKED_PROTOCOL", "BLOCKED_SPEC"}
    assert state.get("reconsidered_utc") is not None


def test_blocked_execution_is_terminal_and_ledger_verified(tmp_path):
    from src.research_control.research_inbox_queue import TERMINAL, TRIAL_TERMINAL
    assert "BLOCKED_EXECUTION" in TERMINAL
    assert "BLOCKED_EXECUTION" in TRIAL_TERMINAL
    queue = InboxQueue(tmp_path / "inbox", tmp_path / "log")
    (tmp_path / "inbox" / "test_cand").mkdir(parents=True, exist_ok=True)
    queue._save({"candidate_id": "test_cand", "status": "BLOCKED_EXECUTION",
                 "admitted": True, "attempts": ["att-1"], "holdout_access": False})
    report = queue.report()
    assert report["counts"]["blocked_execution"] == 1


def test_requalification_advances_previously_blocked_candidate_through_one_execution(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    target = inbox / "test_requal_candidate"
    target.mkdir(parents=True)
    (target / "thesis.yaml").write_text("candidate_id: test_requal_candidate\n")
    (target / "brief.md").write_text("# Test Requal\nCandidate: `test_requal_candidate`\nhttps://example.com/test\n")

    log_dir = tmp_path / "log"
    vault_dir = tmp_path / "vaults"
    vault_dir.mkdir()
    queue = InboxQueue(inbox, log_dir, vault_root=vault_dir, store=tmp_path / "store")

    # Save a prior BLOCKED_DATA state with stale code version
    queue._save({
        "candidate_id": "test_requal_candidate",
        "status": "BLOCKED_DATA",
        "code_version": "stale_code_000000",
        "source_hash": "mock_source_hash",
        "source_format": "legacy_flat_handoff",
        "attempts": [],
        "holdout_access": False,
    })

    fake_spec_file = tmp_path / "spec.yaml"
    fake_spec_file.write_text("spec_hash: 123\n")

    manifest_file = vault_dir / "index_1h" / "manifest.json"
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    manifest_file.write_text('{"status": "MOCK"}')

    execute_calls = []

    def fake_admit(directory):
        return ({"candidate_id": directory.name, "source_hash": "mock_source_hash",
                 "semantic_id": directory.name, "admitted": True,
                 "source_format": "legacy_flat_handoff", "protocol": "cross_sectional",
                 "required_adaptations": [], "holdout_access": False},
                {"candidate_id": directory.name})

    def fake_preflight(info, doc, directory):
        return ({**info, "status": "EXECUTABLE", "spec_hash": "a" * 64,
                 "spec_file_sha256": "b" * 64, "frozen_code_sha256": "c" * 64},
                fake_spec_file)

    def fake_execute(state, spec_path, seconds):
        execute_calls.append(state["candidate_id"])
        return queue._save({
            **state,
            "status": "DEVELOPMENT_QUALIFIED",
            "casefile": str(tmp_path / "mock_casefile.json"),
            "casefile_sha256": "d" * 64,
            "native_evidence_verified": True,
            "holdout_access": False,
        })

    class MockSpec:
        panel_root = str(vault_dir / "index_1h")

    monkeypatch.setattr(queue, "_admit", fake_admit)
    monkeypatch.setattr(queue, "_preflight", fake_preflight)
    monkeypatch.setattr(queue, "_execute", fake_execute)
    import src.research_control.research_inbox_queue as riq
    monkeypatch.setattr(riq, "parse_research_spec", lambda _: MockSpec())

    # First run: advances previously blocked candidate through execution
    report1 = queue.run()
    assert report1["counts"]["native_runs"] == 1
    assert len(execute_calls) == 1
    state1 = queue._load("test_requal_candidate")
    assert state1["status"] == "DEVELOPMENT_QUALIFIED"
    assert state1["prior_status"] == "BLOCKED_DATA"

    # Second run (idempotency): does NOT re-execute
    monkeypatch.setattr(queue, "_native_verify", lambda *a, **k: {})
    monkeypatch.setattr(riq, "_sha", lambda _: "d" * 64)
    report2 = queue.run()
    assert report2["counts"]["native_runs"] == 1
    assert len(execute_calls) == 1  # exactly one execution, never duplicated


def test_unsupported_event_protocol_remains_blocked(tmp_path):
    inbox = tmp_path / "inbox"
    target = inbox / "audusd_policy_carry_cfd_v1"
    target.mkdir(parents=True)
    (target / "thesis.yaml").write_text("candidate_id: audusd_policy_carry_cfd_v1\n")
    (target / "brief.md").write_text("# AUDUSD\nCandidate: `audusd_policy_carry_cfd_v1`\nhttps://example.com\n")

    queue = InboxQueue(inbox, tmp_path / "log")
    info = {"candidate_id": "audusd_policy_carry_cfd_v1", "protocol": "single_instrument_event",
            "source_path": str(target), "source_hash": "a" * 64, "required_adaptations": []}
    ready, spec_path = queue._preflight(info, {}, target)
    assert spec_path is None
    assert ready["status"] == "BLOCKED_PROTOCOL"
    assert "General single-instrument event execution is not a qualified ATS-4 factory protocol" in ready["reason"]
