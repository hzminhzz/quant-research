import hashlib
import json
import shutil
from pathlib import Path

import pytest

import src.engine.ats4_authority as authority

ROOT = Path(__file__).resolve().parents[1]


def _copy_history(tmp_path):
    manifest_path = ROOT / authority.HISTORY_MANIFEST
    manifest = json.loads(manifest_path.read_text())
    for item in manifest["authorities"]:
        source = ROOT / item["path"]
        target = tmp_path / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    target_manifest = tmp_path / authority.HISTORY_MANIFEST
    target_manifest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(manifest_path, target_manifest)
    return manifest


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _runtime_fixture(tmp_path):
    source = ROOT / "src"
    target = tmp_path / "src"
    for folder in ("engine", "oracle", "data_vault", "portfolio", "research_control"):
        (target / folder).mkdir(parents=True, exist_ok=True)
        for path in (source / folder).glob("*.py"):
            shutil.copyfile(path, target / folder / path.name)
    shutil.copyfile(source / "workbench.py", target / "workbench.py")
    shutil.copyfile(source / "portfolio_evidence.py", target / "portfolio_evidence.py")
    (tmp_path / "scripts").mkdir()
    shutil.copyfile(ROOT / "scripts/quant.py", tmp_path / "scripts/quant.py")
    shutil.copyfile(ROOT / "uv.lock", tmp_path / "uv.lock")
    nested = target / "research_control/nested"
    nested.mkdir()
    (nested / "clock.py").write_text("CLOCK = 'pinned'\n", encoding="utf-8")


def test_event_runtime_identity_is_stable_and_binds_event_dependencies(tmp_path):
    _runtime_fixture(tmp_path)
    first = authority.event_runtime_identity(tmp_path)
    second = authority.event_runtime_identity(tmp_path)
    assert first == second
    assert "src/research_control/m8_n8.py" in first["source_hashes"]
    assert "src/research_control/nested/clock.py" in first["source_hashes"]
    assert "src/portfolio_evidence.py" in first["source_hashes"]
    assert "scripts/quant.py" in first["source_hashes"]
    assert "uv.lock" in first["source_hashes"]
    assert first["versions"] == authority.PINNED_VERSIONS
    (tmp_path / "src/research_control/nested/clock.py").write_text("CLOCK = 'changed'\n", encoding="utf-8")
    changed = authority.event_runtime_identity(tmp_path)
    assert changed["identity_digest"] != first["identity_digest"]


def test_event_identity_embeds_unchanged_common_identity():
    from src.engine.common import runtime_identity

    assert authority._common_runtime_identity(ROOT) == runtime_identity()


def test_runtime_version_drift_blocks(monkeypatch):
    monkeypatch.setattr(authority.importlib.metadata, "version", lambda _name: "0.0.0")
    with pytest.raises(Exception) as error:
        authority._installed_versions()
    assert error.value.status == "BLOCKED_RUNTIME"


def test_verified_history_has_every_attempt_and_no_global_dsr():
    history = authority.verified_known_history(ROOT, current_attempts=({"attempt_id": "new"},))
    disclosure = history["trial_disclosure"]
    assert len(disclosure["known_trial_ids"]) == 9
    assert len(disclosure["outcomes"]) == 9
    assert "preflight:m8_n8_dukascopy_us_cash_30m_v1" in disclosure["known_trial_ids"]
    assert "preflight:m8_n8_dukascopy_us_cash_30m_v6" in disclosure["known_trial_ids"]
    assert "70841083-b113-4319-8981-dfaef88c13ab" in disclosure["known_trial_ids"]
    freeze_only = "freeze-only:m8_n8_dukascopy_nas100_cfd_30m_v1"
    assert disclosure["outcomes"][disclosure["known_trial_ids"].index(freeze_only)] is None
    assert disclosure["missing_outcome_ids"] == [freeze_only]
    frozen = next(item for item in history["known_attempts"] if item["history_id"] == freeze_only)
    assert frozen["kind"] == "freeze_only" and frozen["attempt_id"] is None
    session = next(item for item in history["frozen_sessions"]
                   if item["session_id"] == "m8_n8_dukascopy_nas100_cfd_30m_v1")
    assert session["frozen_sha256"] == "9ef110c423b4d41d1be1a85eff0d1e4adb65e72778379541cf1b76e8bb8b9a1a"
    assert session["classification"] == "EXPLORATORY"
    assert session["artifact_generation_verified"] is False
    assert history["scope_counts"] == {
        "tracked_frozen_session_count": 9,
        "freeze_only_record_count": 1,
        "preflight_only_record_count": 2,
        "native_attempt_count": 6,
        "trial_record_count": 6,
        "lifecycle_event_count": 17,
        "missing_outcome_slot_count": 1,
    }
    assert history["qualification"] == {
        "wider_model_selection_history": "INCOMPLETE",
        "unknown_count": None,
        "dsr_status": "UNAVAILABLE",
        "oos_status": "UNAVAILABLE",
        "global_selection_adjustment_allowed": False,
    }
    assert history["current_attempt_lineage"]["records"] == [{"attempt_id": "new"}]
    assert history["current_attempt_lineage"]["merge_into_frozen_history"] is False
    from src.portfolio_evidence import TrialDisclosure

    assert not TrialDisclosure(**disclosure).selection_adjustment_allowed


def test_missing_or_modified_history_authority_fails_closed(tmp_path):
    manifest = _copy_history(tmp_path)
    record = next(item for item in manifest["authorities"] if item["role"] == "technical_failure")
    target = tmp_path / record["path"]
    target.unlink()
    with pytest.raises(Exception) as missing:
        authority._verify_manifest(tmp_path, expected_manifest_sha256=authority.HISTORY_MANIFEST_SHA256)
    assert missing.value.status == "BLOCKED_HISTORY"

    _copy_history(tmp_path)
    target = tmp_path / record["path"]
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(Exception) as changed:
        authority._verify_manifest(tmp_path, expected_manifest_sha256=authority.HISTORY_MANIFEST_SHA256)
    assert changed.value.status == "INVALID_EVIDENCE"


def test_attempt_cardinality_and_unrecorded_attempts_fail_closed(tmp_path):
    manifest = _copy_history(tmp_path)
    manifest["known_attempts"].pop()
    raw = json.dumps(manifest, sort_keys=True, indent=2).encode() + b"\n"
    path = tmp_path / authority.HISTORY_MANIFEST
    path.write_bytes(raw)
    with pytest.raises(Exception) as cardinality:
        authority._verify_manifest(tmp_path, expected_manifest_sha256=hashlib.sha256(raw).hexdigest())
    assert cardinality.value.status == "BLOCKED_HISTORY"

    _copy_history(tmp_path)
    unexpected = tmp_path / "run_log/research_sessions/m8_n8_dukascopy_us_cash_30m_v7/attempts/unrecorded.json"
    unexpected.write_text("{}", encoding="utf-8")
    with pytest.raises(Exception) as hidden:
        authority._verify_manifest(tmp_path, expected_manifest_sha256=authority.HISTORY_MANIFEST_SHA256)
    assert hidden.value.status == "BLOCKED_HISTORY"


def test_history_manifest_hash_is_pinned():
    assert _hash(ROOT / authority.HISTORY_MANIFEST) == authority.HISTORY_MANIFEST_SHA256
