"""Fail-closed research inbox queue acceptance, recovery and idempotence tests."""
from __future__ import annotations

import json
import shutil
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
    return InboxQueue(tmp_path / "inbox", tmp_path / "log")


def test_real_handoffs_are_valid_and_blocked_without_backtest(tmp_path, monkeypatch):
    import subprocess

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("native runner must not execute"))
    for name in PUBLISHED_EVENT_HANDOFFS:
        shutil.copytree(ROOT / "research_inbox" / name, tmp_path / "inbox" / name)
    # The seven historical event candidates are a fixed regression corpus.
    # Adding future executable handoffs must not break this safety test.
    queue = InboxQueue(tmp_path / "inbox", tmp_path / "log")
    first = queue.run()
    assert first["counts"] == {
        "total": 7, "admitted": 7, "executable": 0, "falsified": 0,
        "inconclusive": 0, "blocked": 7, "independently_verified": 0,
        "duplicates": 0, "pending": 0,
    }
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
    queue = InboxQueue(tmp_path / "inbox", tmp_path / "log")
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
    queue = InboxQueue(tmp_path / "inbox", tmp_path / "log")
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
