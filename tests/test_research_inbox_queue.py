"""Fail-closed research inbox queue acceptance, recovery and idempotence tests."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from src.research_control.research_inbox_queue import InboxQueue, classify

ROOT = Path(__file__).resolve().parents[1]
HANDOFF = ROOT / "research_inbox" / "audusd_policy_carry_cfd_v1"


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
    queue = InboxQueue(ROOT / "research_inbox", tmp_path / "log")
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
