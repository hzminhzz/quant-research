"""Behavioral ATS-7 tests: native execution, exact identity, control and recovery."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from ml4t.backtest.types import OrderType
from ml4t.live.persistence import ConcurrentStateWriterError
from pydantic import ValidationError

from scripts.ats7_fixtures import FixtureFeed, bar, cycle_rows, local_manifest
from src.release_contracts import (
    Attestation,
    ReleaseBlocked,
    ReleaseManifest,
    ReleaseTrust,
    verify_attestation,
)
from src.release_journal import ReleaseJournal
from src.release_probe import SyntheticCycle
from src.release_runtime import (
    LocalNoEffectsBroker,
    ReleaseSafeBroker,
    build_release_engine,
)
from src.research_control.action_authorization import sha256_json


def safe_for(tmp_path, manifest=None):
    tmp_path.chmod(0o700)
    return ReleaseSafeBroker(LocalNoEffectsBroker(), manifest or local_manifest(), tmp_path)


def emit(safe, offset=0, price=80000.0):
    at = datetime.now(UTC) + timedelta(seconds=offset)
    safe._record_market_data(at, bar(price), {})
    return at


def test_exact_native_strategy_completes_local_cycle(tmp_path):
    manifest = local_manifest()
    engine = build_release_engine(SyntheticCycle(), FixtureFeed(cycle_rows()), manifest, tmp_path)
    async def run():
        await engine.connect()
        await engine.run()
    asyncio.run(run())
    db = sqlite3.connect(tmp_path / manifest.risk_domain / "release.sqlite")
    rows = db.execute("SELECT state FROM decisions").fetchall()
    assert len(rows) == 4 and all(r[0] == "LOCAL_FILLED" for r in rows)
    assert engine.broker.positions == {}
    assert engine.broker._virtual_portfolio.cash == pytest.approx(100000.2)
    db.close()


def test_duplicate_delivery_cannot_make_a_second_order(tmp_path):
    safe = safe_for(tmp_path)
    async def run():
        await safe.connect()
        stamp = emit(safe)
        await safe.submit_order_async("BTC/USDT:USDT", 0.001)
        safe._decision_time = stamp.isoformat()
        safe._ordinal = 0
        with pytest.raises(ReleaseBlocked, match="DUPLICATE_DECISION"):
            await safe.submit_order_async("BTC/USDT:USDT", 0.001)
        assert safe.get_position("BTC/USDT:USDT").quantity == 0.001
    try:
        asyncio.run(run())
    finally:
        safe.close_persistence()


def test_halt_restart_preserves_exposure_and_allows_verified_reduction(tmp_path):
    manifest = local_manifest()
    safe = safe_for(tmp_path, manifest)
    async def open_then_halt():
        await safe.connect()
        emit(safe)
        await safe.submit_order_async("BTC/USDT:USDT", 0.001)
        safe.enable_kill_switch("manual drill")
    asyncio.run(open_then_halt())
    safe.close_persistence()
    resumed = safe_for(tmp_path, manifest)
    async def run():
        await resumed.connect()
        emit(resumed, price=80100.0)
        assert resumed.get_position("BTC/USDT:USDT").quantity == 0.001
        with pytest.raises(ReleaseBlocked, match="HALTED"):
            await resumed.submit_order_async("BTC/USDT:USDT", 0.001)
        order = await resumed.reduce_position_async("BTC/USDT:USDT", 0.001, reason="protective",
                                                     idempotency_key="authorized-local-drill")
        assert order.filled_quantity == 0.001
        assert not resumed.positions
        assert resumed.release_journal.halted
    try:
        asyncio.run(run())
    finally:
        resumed.close_persistence()


def test_competing_native_account_writer_is_denied(tmp_path):
    manifest = local_manifest()
    first = safe_for(tmp_path, manifest)
    try:
        with pytest.raises(ConcurrentStateWriterError):
            safe_for(tmp_path, manifest)
    finally:
        first.close_persistence()


def test_account_or_release_cannot_replace_risk_domain(tmp_path):
    manifest = local_manifest()
    first = safe_for(tmp_path, manifest)
    first.close_persistence()
    other = manifest.model_copy(update={"account_ref": "local:another"})
    with pytest.raises(ReleaseBlocked, match="ALREADY_BOUND"):
        safe_for(tmp_path, other)


@pytest.mark.parametrize("field,value", [
    ("max_daily_loss", 5000.0), ("max_total_exposure", 1000000.0),
    ("max_order_shares", 100.0), ("fail_on_reconciliation_mismatch", False),
])
def test_runtime_cannot_mutate_frozen_risk(tmp_path, field, value):
    safe = safe_for(tmp_path)
    async def run():
        await safe.connect()
        emit(safe)
        setattr(safe.config, field, value)
        with pytest.raises(ReleaseBlocked, match="RISK_POLICY_CHANGED"):
            await safe.submit_order_async("BTC/USDT:USDT", 0.001)
        assert not safe.positions
    try:
        asyncio.run(run())
    finally:
        safe.close_persistence()


@pytest.mark.parametrize("changes", [
    {"endpoint": "https://api-testnet.bybit.com"},
    {"account_ref": "sha256:" + "0" * 64},
    {"unexpected_authority": True},
])
def test_manifest_rejects_environment_or_schema_substitution(changes):
    data = local_manifest().model_dump(mode="json")
    data.update(changes)
    with pytest.raises(ValidationError):
        ReleaseManifest.model_validate_json(json.dumps(data))


def test_observation_cannot_be_shortened():
    data = local_manifest().model_dump(mode="json")
    data["operations"]["observation_days"] = 27
    with pytest.raises(ValidationError):
        ReleaseManifest.model_validate_json(json.dumps(data))


@pytest.mark.parametrize("offset", [-301, 6])
def test_stale_and_future_bars_latch(tmp_path, offset):
    safe = safe_for(tmp_path)
    try:
        with pytest.raises(ReleaseBlocked, match="CLOCK_OR_STALENESS"):
            emit(safe, offset)
        assert safe.release_journal.halted
    finally:
        safe.close_persistence()


def test_repeated_bar_is_skipped_and_conflict_halts(tmp_path):
    safe = safe_for(tmp_path)
    try:
        stamp = emit(safe)
        safe._record_market_data(stamp, bar(), {})
        assert safe._duplicate_bar
        with pytest.raises(ReleaseBlocked, match="CONFLICTING"):
            safe._record_market_data(stamp, bar(80100.0), {})
        assert safe.release_journal.halted
    finally:
        safe.close_persistence()


@pytest.mark.parametrize("quantity,order_type,price,reason", [
    (0.0015, OrderType.MARKET, None, "LOT_SIZE"),
    (0.001, OrderType.LIMIT, 80000.05, "PRICE_TICK"),
    (0.001, OrderType.STOP, None, "UNQUALIFIED"),
])
def test_provider_precision_and_capability_fail_before_effect(tmp_path, quantity, order_type, price, reason):
    safe = safe_for(tmp_path)
    async def run():
        await safe.connect()
        emit(safe)
        with pytest.raises((ReleaseBlocked, ValueError), match=reason + "|stop_price"):
            await safe.submit_order_async("BTC/USDT:USDT", quantity, order_type=order_type,
                                           limit_price=price)
        assert not safe.positions
    try:
        asyncio.run(run())
    finally:
        safe.close_persistence()


def test_expired_release_retains_owned_obligations(tmp_path):
    manifest = local_manifest()
    safe = safe_for(tmp_path, manifest)
    async def run():
        await safe.connect()
        emit(safe)
        await safe.submit_order_async("BTC/USDT:USDT", 0.001)
        # Expiry is tested by an independent wall-clock patch, not altered manifest.
        class Later(datetime):
            @classmethod
            def now(cls, tz=None):
                return manifest.expires_at + timedelta(seconds=1)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("src.release_runtime.datetime", Later)
            with pytest.raises(ReleaseBlocked, match="EXPIRED"):
                await safe.submit_order_async("BTC/USDT:USDT", 0.001)
        assert safe.get_position("BTC/USDT:USDT").quantity == 0.001
    try:
        asyncio.run(run())
    finally:
        safe.close_persistence()


def test_reduction_cannot_cross_zero_and_unowned_cancel_denied(tmp_path):
    safe = safe_for(tmp_path)
    async def run():
        await safe.connect()
        emit(safe)
        await safe.submit_order_async("BTC/USDT:USDT", 0.001)
        with pytest.raises(ReleaseBlocked, match="CROSS_EXPOSURE"):
            await safe.reduce_position_async("BTC/USDT:USDT", 0.002, reason="test", idempotency_key="a")
        with pytest.raises(ReleaseBlocked, match="NOT_OWNED"):
            await safe.cancel_order_async("someone-elses-order")
        with pytest.raises(ReleaseBlocked, match="USE_VERIFIED"):
            await safe.submit_order_async("BTC/USDT:USDT", -0.002, reduce_only=True)
        assert safe.get_position("BTC/USDT:USDT").quantity == 0.001
    try:
        asyncio.run(run())
    finally:
        safe.close_persistence()


def test_direct_resume_is_denied(tmp_path):
    safe = safe_for(tmp_path)
    try:
        safe.enable_kill_switch("manual")
        with pytest.raises(ReleaseBlocked, match="AUTHORIZED_RESUME"):
            safe.disable_kill_switch()
    finally:
        safe.close_persistence()


def test_process_death_after_admission_preserves_unknown(tmp_path):
    manifest = local_manifest()
    path = tmp_path / "release.sqlite"
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(manifest.model_dump_json())
    code = (
        "import os,sys; from pathlib import Path; "
        "from src.release_contracts import ReleaseManifest; from src.release_journal import ReleaseJournal; "
        "m=ReleaseManifest.model_validate_json(Path(sys.argv[1]).read_bytes()); "
        "j=ReleaseJournal(Path(sys.argv[2]),m); "
        "j.stage('fixed-identity',{'action':'open','asset':'BTC/USDT:USDT','quantity':0.001}); os._exit(91)"
    )
    result = subprocess.run([sys.executable, "-c", code, str(manifest_file), str(path)],
                            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
                            capture_output=True, timeout=30, check=False)
    assert result.returncode == 91, result.stderr.decode()
    journal = ReleaseJournal(path, manifest)
    try:
        assert journal.unknown == 1 and journal.halted
        with pytest.raises(ReleaseBlocked, match="DUPLICATE"):
            journal.stage("fixed-identity", {"action": "open", "asset": "BTC/USDT:USDT", "quantity": 0.001})
        with pytest.raises(ReleaseBlocked, match="HALTED"):
            journal.stage("another", {"action": "open"})
    finally:
        journal.close()


def test_projection_tampering_is_detected(tmp_path):
    manifest = local_manifest()
    path = tmp_path / "release.sqlite"
    journal = ReleaseJournal(path, manifest)
    journal.stage("fixed", {"action": "open"})
    journal.connection.execute("UPDATE decisions SET state='ACKNOWLEDGED'")
    with pytest.raises(ReleaseBlocked, match="PROJECTION"):
        journal.verify()
    journal.close()


def test_local_manifest_cannot_activate_external_broker(tmp_path):
    with pytest.raises(ReleaseBlocked, match="SUBSTITUTION"):
        build_release_engine(SyntheticCycle(), FixtureFeed([]), local_manifest(), tmp_path,
                             broker=object())


def test_external_path_requires_independent_authority(tmp_path):
    data = local_manifest().model_dump(mode="json")
    data.update(environment="PROVIDER_DEMO", endpoint="https://api-demo.bybit.com",
                account_ref="sha256:" + "1" * 64)
    manifest = ReleaseManifest.model_validate_json(json.dumps(data))
    with pytest.raises(ReleaseBlocked, match="EXTERNAL_AUTHORIZATION"):
        ReleaseSafeBroker(object(), manifest, tmp_path)


def signed_fixture(manifest):
    key = Ed25519PrivateKey.generate()
    now = datetime.now(UTC)
    public = base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    trust = ReleaseTrust.model_validate_json(json.dumps({
        "revision": 1, "signers": [{"issuer_id": "operator", "public_key_b64": public,
                                   "role": "AUTHORIZATION", "environments": ["PROVIDER_DEMO"]}],
        "revoked_nonces": [], "expires_at": (now + timedelta(days=1)).isoformat(),
    }))
    values = {"purpose": "AUTHORIZATION", "issuer_id": "operator", "manifest_sha256": manifest.identity,
              "environment": manifest.environment, "account_ref": manifest.account_ref,
              "risk_sha256": sha256_json(manifest.risk.model_dump(mode="json")),
              "actions": ["open", "reduce", "cancel", "resume"], "issued_at": (now - timedelta(minutes=1)).isoformat(),
              "expires_at": (now + timedelta(hours=1)).isoformat(),
              "recovery_until": (now + timedelta(hours=2)).isoformat(), "evidence_sha256": "a" * 64,
              "nonce": "unique-approved-release", "signature_b64": ""}
    receipt = Attestation.model_validate_json(json.dumps(values))
    return receipt.model_copy(update={"signature_b64": base64.b64encode(key.sign(receipt.signed_payload())).decode()}), trust


@pytest.mark.parametrize("attack", ["scope", "risk", "signature", "revoked", "expired", "role", "environment"])
def test_forged_or_stale_authorization_rejected(attack):
    data = local_manifest().model_dump(mode="json")
    data.update(environment="PROVIDER_DEMO", endpoint="https://api-demo.bybit.com", account_ref="sha256:" + "2" * 64)
    manifest = ReleaseManifest.model_validate_json(json.dumps(data))
    receipt, trust = signed_fixture(manifest)
    now = datetime.now(UTC)
    verify_attestation(receipt, trust, manifest, purpose="AUTHORIZATION", action="open", now=now)
    if attack == "scope":
        receipt = receipt.model_copy(update={"manifest_sha256": "0" * 64})
    elif attack == "risk":
        receipt = receipt.model_copy(update={"risk_sha256": "0" * 64})
    elif attack == "signature":
        receipt = receipt.model_copy(update={"signature_b64": base64.b64encode(b"0" * 64).decode()})
    elif attack == "revoked":
        trust = trust.model_copy(update={"revoked_nonces": (receipt.nonce,)})
    elif attack == "expired":
        now = receipt.expires_at
    elif attack == "role":
        receipt = receipt.model_copy(update={"purpose": "QUALIFICATION"})
    else:
        receipt = receipt.model_copy(update={"environment": "LIVE"})
    with pytest.raises(ReleaseBlocked):
        verify_attestation(receipt, trust, manifest, purpose="AUTHORIZATION", action="open", now=now)


def test_worker_owned_trust_is_rejected(tmp_path):
    path = tmp_path / "trust.json"
    path.write_text("{}")
    with pytest.raises(ReleaseBlocked, match="TRUST_WRITABLE"):
        ReleaseTrust.load_external(path)
