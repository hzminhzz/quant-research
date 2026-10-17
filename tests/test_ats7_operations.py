"""Operational regressions with causal failures, not provider success substitutes."""
import asyncio
import json
import shutil
import sqlite3
from types import SimpleNamespace

import pytest
import requests

from scripts import ats7_notify
from scripts.ats7_acceptance import lifecycle
from scripts.ats7_fixtures import FixtureFeed, cycle_rows, local_manifest
from scripts.ats7_outside_judge import judge
from src import ml4t_native_metrics as metrics
from src.release_contracts import ReleaseBlocked
from src.release_probe import SyntheticCycle
from src.release_runtime import build_release_engine


def test_mutated_strategy_parameter_cannot_submit(tmp_path):
    manifest = local_manifest()
    strategy = SyntheticCycle()
    engine = build_release_engine(strategy, FixtureFeed(cycle_rows()), manifest, tmp_path)
    async def run():
        await engine.connect()
        strategy.quantity = 0.002
        with pytest.raises(ReleaseBlocked, match="STRATEGY_PARAMETER_MISMATCH"):
            await engine.broker._require("open")
    try:
        asyncio.run(run())
        assert not engine.broker.positions
    finally:
        engine.broker.close_persistence()


def test_feed_substitution_fails_before_connect(tmp_path):
    class DifferentFeed(FixtureFeed):
        pass
    with pytest.raises(ReleaseBlocked, match="FEED_IDENTITY"):
        build_release_engine(SyntheticCycle(), DifferentFeed(cycle_rows()), local_manifest(), tmp_path)


def test_incremental_native_metrics_catches_up_without_double_count(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics, "MAX_AUDIT_BYTES", 100)
    journal = tmp_path / "journal.jsonl"
    row = json.dumps({"event": "shadow_order_filled"}) + "\n"
    journal.write_text(row * 7)
    safe = SimpleNamespace(config=SimpleNamespace(journal_file=str(journal)))
    assert metrics._native_audit_counts(safe) is None
    result = None
    for _ in range(10):
        result = metrics._native_audit_counts(safe)
        if result is not None:
            break
    assert result is not None and result["shadow_order_filled"] == 7
    assert metrics._native_audit_counts(safe)["shadow_order_filled"] == 7
    journal.write_text(row)
    assert metrics._native_audit_counts(safe)["shadow_order_filled"] == 1


def test_notification_failure_cannot_create_delivery_receipt(tmp_path, monkeypatch):
    cfg = tmp_path / "notify.yml"
    cfg.write_text("route: {receiver: existing}\nreceivers:\n- name: existing\n  telegram_configs:\n  - chat_id: 1334687629\n    bot_token: fixture-not-secret\n")
    monkeypatch.setattr(ats7_notify, "CONFIG", cfg)
    def fail(*args, **kwargs):
        raise requests.ConnectionError("fixture network failure")
    monkeypatch.setattr(requests.Session, "post", fail)
    receipt = tmp_path / "receipt.json"
    with pytest.raises(RuntimeError, match="redacted"):
        ats7_notify.notify(receipt, send=True)
    assert not receipt.exists()


def test_actual_lifecycle_outside_judge_detects_repriced_fill(tmp_path):
    run = tmp_path / "actual"
    run.mkdir(mode=0o700)
    asyncio.run(lifecycle(run))
    before = {str(p): p.stat().st_mtime_ns for p in run.rglob("*") if p.is_file()}
    assert judge(run)["status"] == "PASS"
    assert before == {str(p): p.stat().st_mtime_ns for p in run.rglob("*") if p.is_file()}
    corrupt = tmp_path / "repriced"
    shutil.copytree(run, corrupt)
    manifest = json.loads((corrupt / "manifest.json").read_text())
    db = sqlite3.connect(corrupt / "state" / manifest["risk_domain"] / "release.sqlite")
    seq, raw = db.execute("SELECT seq,payload FROM events WHERE kind='decision_observed' ORDER BY seq LIMIT 1").fetchone()
    payload = json.loads(raw)
    payload["evidence"]["filled_price"] += 100
    db.execute("UPDATE events SET payload=? WHERE seq=?", (json.dumps(payload), seq))
    db.commit()
    db.close()
    assert "NATIVE_CASH_MISMATCH" in judge(corrupt)["problems"]


def test_changed_terms_halt_and_exact_rollback_still_requires_resume(tmp_path):
    import hashlib
    from pathlib import Path

    from src.release_contracts import SourceBinding
    from src.release_runtime import LocalNoEffectsBroker, ReleaseSafeBroker

    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    manifest = local_manifest()
    source = next(s for s in manifest.sources if s.role == "terms")
    original = Path(source.path).read_bytes()
    terms = tmp_path / "terms.md"
    terms.write_bytes(original)
    replacement = SourceBinding(role="terms", path=str(terms), sha256=hashlib.sha256(original).hexdigest())
    manifest = manifest.model_copy(update={"sources": tuple(replacement if s.role == "terms" else s for s in manifest.sources),
                                           "account_terms_source": str(terms)})
    safe = ReleaseSafeBroker(LocalNoEffectsBroker(), manifest, state)
    async def run():
        await safe.connect()
        terms.write_bytes(original + b"\nChanged rules")
        with pytest.raises(ReleaseBlocked, match="SOURCE_DRIFT"):
            await safe._require("open")
        assert safe.release_journal.halted
        terms.write_bytes(original)
        with pytest.raises(ReleaseBlocked, match="HALTED"):
            await safe._require("open")
        await safe.resume("independent fixture check: exact original rule bytes restored")
        assert not safe.release_journal.halted
    try:
        asyncio.run(run())
    finally:
        safe.close_persistence()


def test_halted_market_callbacks_preserve_native_lifecycle_counts(tmp_path):
    manifest = local_manifest()
    engine = build_release_engine(SyntheticCycle(), FixtureFeed(cycle_rows()), manifest, tmp_path)
    async def run():
        await engine.connect()
        engine.broker.enable_kill_switch("native lifecycle halt regression")
        await engine.run()
    asyncio.run(run())
    assert not engine.broker.positions
    assert engine.runtime_status()["callback_counts"]["market_event"] == 4
    con = sqlite3.connect(tmp_path / manifest.risk_domain / "release.sqlite")
    assert con.execute("SELECT count(*) FROM decisions").fetchone()[0] == 0
    con.close()


def test_replayed_journal_bar_preserves_native_lifecycle_counts(tmp_path):
    from src.release_runtime import LocalNoEffectsBroker, ReleaseSafeBroker

    manifest = local_manifest()
    tmp_path.chmod(0o700)
    row = cycle_rows()[0]
    previous = ReleaseSafeBroker(LocalNoEffectsBroker(), manifest, tmp_path)
    previous._record_market_data(*row)
    previous.close_persistence()
    engine = build_release_engine(SyntheticCycle(), FixtureFeed([row]), manifest, tmp_path)
    async def run():
        await engine.connect()
        await engine.run()
    asyncio.run(run())
    assert not engine.broker.positions
    assert engine.runtime_status()["callback_counts"]["market_event"] == 1
