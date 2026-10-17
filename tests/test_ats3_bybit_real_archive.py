"""ATS-3 adversarial checks against a captured real Bybit Demo archive.

Input archive stays private outside Git. Each negative case is a separate
temporary copy; rewrite checksum metadata to test semantic checks, not just SHA.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from src.research_control.ats3_bybit_replay import reconcile_archive

SAMPLE = Path("/home/quant/.local/state/quant-research/ats3/demo-archive-20261017-current")


def _private_copy(tmp_path: Path) -> Path:
    if not SAMPLE.is_dir():
        pytest.skip("Real Demo archive is not present on this machine")
    folder = tmp_path / "archive"
    shutil.copytree(SAMPLE, folder)
    os.chmod(folder, 0o700)
    return folder


def _mutate(folder: Path, name: str, change):
    path = folder / (name + ".json")
    records = json.loads(path.read_text())
    change(records)
    raw = (json.dumps(records, sort_keys=True, indent=2) + "\n").encode()
    path.write_bytes(raw)
    os.chmod(path, 0o600)
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][name].update(
        sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw),
        rows=len(records) if isinstance(records, list) else None)
    manifest_path.write_text(json.dumps(manifest, sort_keys=True))
    os.chmod(manifest_path, 0o600)


def test_real_demo_archive_reconciles_provider_accounting():
    if not SAMPLE.is_dir():
        pytest.skip("Real Demo archive is not present on this machine")
    report = reconcile_archive(SAMPLE)
    assert report["input_hashes_verified"] is True
    assert report["provider_economics"] == "RECONCILED"
    assert report["trade_fills"] == 4
    assert report["funding_events"] == 6
    assert report["orders"] == 4
    assert report["realized_pnl_usdt"] == "-0.278"
    assert report["ending_wallet_usdt"] == "9997.38945625"
    assert report["final_position_btc"] == "0.02"
    assert report["status"] == "INSUFFICIENT_EVIDENCE"
    assert "FROZEN_STRATEGY_BASELINE_NOT_LINKED" in report["unknowns"]


def test_exact_duplicate_and_event_reordering_are_idempotent(tmp_path):
    folder = _private_copy(tmp_path)
    good = reconcile_archive(folder)
    _mutate(folder, "executions", lambda data: data.insert(0, data[-1].copy()))
    _mutate(folder, "transactions", lambda data: data.insert(0, data[-1].copy()))
    changed = reconcile_archive(folder)
    assert changed["ending_wallet_usdt"] == good["ending_wallet_usdt"]
    assert changed["final_position_btc"] == good["final_position_btc"]
    assert changed["duplicates_deduplicated"] == good["duplicates_deduplicated"] + 2


def test_conflicting_duplicate_event_fails_closed(tmp_path):
    folder = _private_copy(tmp_path)
    def conflict(items):
        rogue = dict(items[-1])
        rogue["execPrice"] = "1"
        items.append(rogue)
    _mutate(folder, "executions", conflict)
    with pytest.raises(ValueError, match="SOURCE_ID_CONFLICT"):
        reconcile_archive(folder)


def test_missing_trade_fill_fails_order_reconciliation(tmp_path):
    folder = _private_copy(tmp_path)
    _mutate(folder, "executions", lambda items: items.remove(next(
        x for x in items if x["execType"] == "Trade")))
    with pytest.raises(ValueError, match="ORDER_CUM_FILL_MISMATCH"):
        reconcile_archive(folder)


def test_well_hashed_wrong_cashflow_fails_economic_replay(tmp_path):
    folder = _private_copy(tmp_path)
    def corrupt(items):
        first = next(row for row in items if row["type"] == "TRADE")
        first["fee"] = "100"
    _mutate(folder, "transactions", corrupt)
    with pytest.raises(ValueError, match="EXECUTION_TRANSACTION_FEE"):
        reconcile_archive(folder)


def test_source_hash_tamper_detected(tmp_path):
    folder = _private_copy(tmp_path)
    path = folder / "orders.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="SOURCE_HASH_MISMATCH"):
        reconcile_archive(folder)


def test_stale_snapshot_cannot_claim_full_coverage(tmp_path):
    folder = _private_copy(tmp_path)
    path = folder / "manifest.json"
    doc = json.loads(path.read_text())
    doc["interval_end"] = "2026-10-15T00:00:00+00:00"
    path.write_text(json.dumps(doc))
    result = reconcile_archive(folder)
    assert "SNAPSHOT_OUTSIDE_CAPTURE_WINDOW" in result["unknowns"]
    assert result["provider_economics"] == "RECONCILED_WITH_GAPS"



def _journal() -> Path:
    info = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))
    uid = info["account_uid_private"]
    return Path("/home/quant/.local/state/quant-research") / f"bybit-demo-account-{uid}-journal.jsonl"


def test_isolated_journal_without_sqlite_or_drill_reports_all_missing_intents():
    if not SAMPLE.is_dir() or not _journal().is_file():
        pytest.skip("Real Demo journal is not present on this machine")
    empty = Path("/dev/null/nonexistent")
    result = reconcile_archive(SAMPLE, _journal(), sqlite_journal=empty, drill_evidence=empty)
    assert result["provider_economics"] == "RECONCILED"
    source = result["local_intent_evidence"]
    assert source["event_count"] == 115
    assert source["intent_count"] == 9
    assert source["submitted_count"] == 5
    assert source["linked_to_provider_orders"] == 4
    assert source["cancel_confirmations_local"] == 1
    assert source["unmatched_intent_count"] == 4
    assert "INTENT_TERMINAL_REASON_NOT_RECORDED" in result["unknowns"]
    assert "SUBMITTED_ORDER_NOT_IN_CURRENT_PROVIDER_HISTORY" in result["unknowns"]


def test_sqlite_correlation_reconciles_intents_and_drill_leaving_seq7_unknown():
    if not SAMPLE.is_dir() or not _journal().is_file():
        pytest.skip("Real Demo journal is not present on this machine")
    result = reconcile_archive(SAMPLE, _journal(), waive_read_only_key=True)
    assert result["provider_economics"] == "RECONCILED"
    source = result["local_intent_evidence"]
    assert source["event_count"] == 115
    assert source["intent_count"] == 9
    assert source["submitted_count"] == 5
    assert source["linked_to_provider_orders"] == 4
    # 3 intents + 1 drill order reconciled, seq7 left unknown
    assert source["unmatched_intent_count"] == 1
    assert len(source["reconciled_intents"]) == 4
    assert "INTENT_TERMINAL_REASON_NOT_RECORDED" in result["unknowns"]
    assert "SUBMITTED_ORDER_NOT_IN_CURRENT_PROVIDER_HISTORY" not in result["unknowns"]
    assert result["least_privilege_audit_credential"] == "WAIVED_BY_OPERATOR"


def test_causal_timestamp_matching_prevents_false_seq7_resolution():
    """Advisory regression: seq7 (06:16:46) must never match 06:25:35 drill intent."""
    if not SAMPLE.is_dir() or not _journal().is_file():
        pytest.skip("Real Demo journal is not present on this machine")
    result = reconcile_archive(SAMPLE, _journal())
    reconciled_ids = {r.get("intent_id") for r in result["local_intent_evidence"]["reconciled_intents"]}
    # SQLite intent for drill is 01M4Z3SK... at 06:25:35; it must be consumed by submission, not unmatched
    assert "01M4Z3SKVP4KVQBRZFMM3AZY8K" not in reconciled_ids
    # seq 7 must remain unmatched
    assert result["local_intent_evidence"]["unmatched_intent_count"] == 1

def test_corrupted_journal_event_hash_rejected(tmp_path):
    folder = _private_copy(tmp_path)
    original = _journal()
    if not original.is_file():
        pytest.skip("Native journal unavailable")
    copied = tmp_path / original.name
    copied_head = tmp_path / (original.name + ".head")
    shutil.copy2(original, copied)
    shutil.copy2(original.with_name(original.name + ".head"), copied_head)
    lines = copied.read_text().splitlines()
    event = json.loads(lines[0])
    event["timestamp"] = "2025-01-01T00:00:00+00:00"
    lines[0] = json.dumps(event, sort_keys=True)
    copied.write_text("\n".join(lines) + "\n")
    with pytest.raises(ValueError, match="JOURNAL_EVENT_HASH_INVALID"):
        reconcile_archive(folder, copied)


def test_corrupted_journal_head_checksum_rejected(tmp_path):
    folder = _private_copy(tmp_path)
    original = _journal()
    if not original.is_file():
        pytest.skip("Native journal unavailable")
    copied = tmp_path / original.name
    copied_head = tmp_path / (original.name + ".head")
    shutil.copy2(original, copied)
    shutil.copy2(original.with_name(original.name + ".head"), copied_head)
    doc = json.loads(copied_head.read_text())
    doc["head_hash"] = "0" * 64
    copied_head.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="JOURNAL_HEAD_CHECKSUM_OR_CURSOR_INVALID"):
        reconcile_archive(folder, copied)


def test_missing_funding_row_conflicts_with_execution_statement(tmp_path):
    folder = _private_copy(tmp_path)
    _mutate(folder, "transactions", lambda items: items.remove(next(
        x for x in items if x["type"] == "SETTLEMENT")))
    with pytest.raises(ValueError, match="WALLET_TRANSACTION_CHAIN"):
        reconcile_archive(folder)


def test_repriced_open_position_with_rehashed_snapshot_fails(tmp_path):
    folder = _private_copy(tmp_path)
    def corrupt(snapshot):
        snapshot["positions"][0]["markPrice"] = "1"
    _mutate(folder, "snapshot", corrupt)
    with pytest.raises(ValueError, match="UNREALIZED_PNL"):
        reconcile_archive(folder)


def test_different_snapshot_position_size_fails(tmp_path):
    folder = _private_copy(tmp_path)
    _mutate(folder, "snapshot", lambda snap: snap["positions"][0].update(size="0.03"))
    with pytest.raises(ValueError, match="POSITION_SIZE_MISMATCH"):
        reconcile_archive(folder)

def test_mainnet_archive_refused_even_if_checksums_valid(tmp_path):
    folder = _private_copy(tmp_path)
    path = folder / "manifest.json"
    doc = json.loads(path.read_text())
    doc["environment"] = "mainnet"
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="WRONG_ENVIRONMENT"):
        reconcile_archive(folder)
