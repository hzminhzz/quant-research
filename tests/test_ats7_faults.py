"""Additional cross-process and native-risk failure drills for ATS-7."""
import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from ml4t.live.safety import RiskLimitError

from scripts.ats7_fixtures import bar, local_manifest
from src.release_contracts import ReleaseBlocked
from src.release_journal import ReleaseJournal
from tests.test_ats7_release import emit, safe_for


def test_concurrent_strategy_intents_share_native_global_cap(tmp_path):
    manifest = local_manifest()
    risk = manifest.risk.model_copy(update={"max_order_value": 800.0,
                                          "max_position_value": 800.0, "max_total_exposure": 800.0})
    manifest = manifest.model_copy(update={"risk": risk})
    safe = safe_for(tmp_path, manifest)
    async def run():
        await safe.connect()
        emit(safe)
        results = await asyncio.gather(safe.submit_order_async("BTC/USDT:USDT", 0.006),
                                       safe.submit_order_async("BTC/USDT:USDT", 0.006),
                                       return_exceptions=True)
        assert sum(isinstance(x, RiskLimitError) for x in results) == 1
        assert safe.get_position("BTC/USDT:USDT").quantity == 0.006
    try:
        asyncio.run(run())
    finally:
        safe.close_persistence()


@pytest.mark.parametrize("limit", ["daily", "drawdown"])
def test_native_financial_breach_latches_before_second_effect(tmp_path, limit):
    manifest = local_manifest()
    changes = {"max_daily_loss": 0.05} if limit == "daily" else {"max_drawdown_pct": 0.0000005}
    manifest = manifest.model_copy(update={"risk": manifest.risk.model_copy(update=changes)})
    safe = safe_for(tmp_path, manifest)
    async def run():
        await safe.connect()
        emit(safe)
        await safe.submit_order_async("BTC/USDT:USDT", 0.001)
        emit(safe, price=79900.0)
        with pytest.raises(RiskLimitError):
            await safe.submit_order_async("BTC/USDT:USDT", 0.001)
        assert safe._state.kill_switch_activated
        assert safe.get_position("BTC/USDT:USDT").quantity == 0.001
    try:
        asyncio.run(run())
    finally:
        safe.close_persistence()


def test_halt_blocks_risk_during_provider_disconnect(tmp_path):
    safe = safe_for(tmp_path)
    async def run():
        await safe.connect()
        emit(safe)
        safe.enable_kill_switch("outage")
        await safe._broker.disconnect()
        with pytest.raises(ReleaseBlocked):
            await safe.submit_order_async("BTC/USDT:USDT", 0.001)
        assert not safe.positions
    try:
        asyncio.run(run())
    finally:
        safe.close_persistence()


def test_account_query_failure_cannot_admit_order(tmp_path, monkeypatch):
    safe = safe_for(tmp_path)
    async def fail():
        raise RuntimeError("snapshot unavailable")
    async def run():
        await safe.connect()
        emit(safe)
        monkeypatch.setattr(safe, "get_account_value_async", fail)
        with pytest.raises(RuntimeError):
            await safe.submit_order_async("BTC/USDT:USDT", 0.001)
        assert not safe.positions
    try:
        asyncio.run(run())
    finally:
        safe.close_persistence()


def test_insufficient_margin_cannot_admit_order(tmp_path, monkeypatch):
    safe = safe_for(tmp_path)
    async def zero_cash():
        return 0.0
    async def run():
        await safe.connect()
        emit(safe)
        monkeypatch.setattr(safe, "get_cash_async", zero_cash)
        with pytest.raises(ReleaseBlocked, match="INSUFFICIENT_MARGIN"):
            await safe.submit_order_async("BTC/USDT:USDT", 0.001)
        assert not safe.positions
    try:
        asyncio.run(run())
    finally:
        safe.close_persistence()


def test_incorrect_instrument_is_not_silently_mapped(tmp_path):
    safe = safe_for(tmp_path)
    try:
        bad = {"BTCUSDT": bar()["BTC/USDT:USDT"]}
        with pytest.raises(ReleaseBlocked, match="INSTRUMENT_MAPPING"):
            safe._record_market_data(datetime.now(UTC), bad, {})
    finally:
        safe.close_persistence()


def test_unreviewed_provider_order_parameters_are_denied(tmp_path):
    safe = safe_for(tmp_path)
    async def run():
        await safe.connect()
        emit(safe)
        with pytest.raises(ReleaseBlocked, match="ORDER_PARAMETERS"):
            await safe.submit_order_async("BTC/USDT:USDT", 0.001, params={"positionIdx": 2})
    try:
        asyncio.run(run())
    finally:
        safe.close_persistence()


@pytest.mark.parametrize("crash", ["before_commit", "after_native_fill"])
def test_actual_process_death_at_effect_boundaries(tmp_path, crash):
    manifest = local_manifest()
    mf = tmp_path / "manifest.json"
    mf.write_text(manifest.model_dump_json())
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    prefix = (
        "import os,sys,asyncio; from pathlib import Path; "
        "from datetime import datetime,UTC; "
        "from src.release_contracts import ReleaseManifest; "
        "from src.release_journal import ReleaseJournal; "
        "from src.release_runtime import ReleaseSafeBroker,LocalNoEffectsBroker; "
        "m=ReleaseManifest.model_validate_json(Path(sys.argv[1]).read_bytes());\n"
    )
    if crash == "before_commit":
        code = prefix + """
original = ReleaseJournal._append
def crash_append(self, kind, payload):
    original(self, kind, payload)
    if kind == 'decision_committed': os._exit(92)
ReleaseJournal._append = crash_append
j=ReleaseJournal(Path(sys.argv[2])/'release.sqlite',m)
j.stage('one',{'action':'open'})
"""
    else:
        code = prefix + """
s=ReleaseSafeBroker(LocalNoEffectsBroker(),m,Path(sys.argv[2]))
def die(*args,**kwargs): os._exit(93)
s.release_journal.finish=die
async def run():
    await s.connect()
    s._record_market_data(datetime.now(UTC),{'BTC/USDT:USDT':{'open':80000.,'high':80010.,'low':79990.,'close':80000.,'volume':1.}}, {})
    await s.submit_order_async('BTC/USDT:USDT',0.001)
asyncio.run(run())
"""
    child = subprocess.run([sys.executable, "-c", code, str(mf), str(tmp_path)],
                           env=env, capture_output=True, timeout=30, check=False)
    assert child.returncode == (92 if crash == "before_commit" else 93), child.stderr.decode()
    if crash == "before_commit":
        journal = ReleaseJournal(tmp_path / "release.sqlite", manifest)
        assert journal.unknown == 0
        assert journal.connection.execute("SELECT count(*) FROM decisions").fetchone()[0] == 0
        journal.close()
    else:
        safe = safe_for(tmp_path, manifest)
        async def check():
            await safe.connect()
            assert safe.release_journal.unknown == 1
            assert safe.get_position("BTC/USDT:USDT").quantity == 0.001
            with pytest.raises(ReleaseBlocked):
                await safe.resume("must remain blocked")
        try:
            asyncio.run(check())
        finally:
            safe.close_persistence()


def test_journal_before_effect_and_original_lifecycle_are_linked(tmp_path):
    safe = safe_for(tmp_path)
    async def run():
        await safe.connect()
        emit(safe)
        await safe.submit_order_async("BTC/USDT:USDT", 0.001)
    try:
        asyncio.run(run())
        events = safe.release_journal.events()
        committed = next(e for e in events if e["kind"] == "decision_committed")
        observed = next(e for e in events if e["kind"] == "decision_observed")
        assert committed["seq"] < observed["seq"]
        assert committed["payload"]["identity"] == observed["payload"]["identity"]
        assert observed["payload"]["evidence"]["filled_quantity"] == 0.001
        safe.release_journal.verify_native_references(safe._journal_path())
    finally:
        safe.close_persistence()


def test_stale_release_journal_detects_newer_native_identity(tmp_path):
    manifest = local_manifest()
    journal = ReleaseJournal(tmp_path / "release.sqlite", manifest)
    native = tmp_path / "native.jsonl"
    native.write_text(json.dumps({"entry": {"event": "ats7_decision_committed",
                                          "payload": {"execution_identity": "missing"}}}) + "\n")
    try:
        with pytest.raises(ReleaseBlocked, match="STALE_RELEASE"):
            journal.verify_native_references(native)
    finally:
        journal.close()
