"""ATS-2 independent post-run source/authorization/recovery qualification judge.

Does not import ATS-2 implementation, grant validator, execution engine, or
its acceptance-harness code. Works only on saved synthetic evidence.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from datetime import datetime
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise AssertionError(f"UNSAFE_FILE:{path}")
    return sha_bytes(path.read_bytes())


def digest(obj: object) -> str:
    return sha_bytes(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                          allow_nan=False, ensure_ascii=True).encode())


def load(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise AssertionError(f"EVIDENCE_MISSING:{path}")
    doc = json.loads(path.read_bytes())
    if not isinstance(doc, dict):
        raise TypeError(f"EVIDENCE_NOT_OBJECT:{path}")
    return doc


def expect(value: bool, reason: str) -> None:
    if not value:
        raise AssertionError(reason)


def check_authorization(root: Path, manifest: dict, cases: list[str]) -> None:
    relative = root / "synthetic_protected"
    auth = manifest["synthetic_protected_authorization"]
    action = load(relative / auth["action_path"])
    grant = load(relative / auth["grant_path"])
    trust = load(relative / auth["policy_path"])
    claim = load(relative / auth["claim_path"])
    proof = load(relative / auth["proof_path"])
    payload = (relative / "synthetic_only" / "synthetic_protected_fixture.bin").read_bytes()
    private = relative / auth["issuer_private_path"]
    expect(sha_file(private) == auth["issuer_private_sha256"], "ISSUER_KEY_DRIFT")
    expect(sha_file(relative / auth["policy_path"]) == auth["policy_sha256"], "TRUST_POLICY_DRIFT")
    expect(sha_file(relative / auth["claim_path"]) == auth["claim_sha256"], "CLAIM_DRIFT")
    expect(sha_file(relative / auth["proof_path"]) == auth["proof_sha256"], "PROOF_DRIFT")
    expect(action["contract_sha256"] == digest({k: v for k, v in action.items()
                                               if k != "contract_sha256"}), "ACTION_DIGEST_INVALID")
    expect(action["operation"] == "synthetic_protected_fixture_read"
           and action["read_scope"] == "synthetic_fixture_bytes_only"
           and action["trading"] is False
           and action["protected_fixture_only"] is True, "ACTION_NOT_SYNTHETIC")
    expect(grant["scope"]["action_sha256"] == digest(action), "SIGNED_ACTION_MISMATCH")
    for k in ("session_id", "trial_id", "operation"):
        expect(grant["scope"][k] == action[k], "SIGNED_ACTION_SCOPE_DRIFT:" + k)
    for k in ("source_sha256", "data_sha256", "spec_sha256", "config_sha256"):
        expect(grant["scope"][k] == action["identity"][k], "SIGNED_INPUT_DRIFT:" + k)
    expect(grant["scope"]["selection_sha256"] == action["selection_sha256"],
           "SIGNED_SELECTION_DRIFT")
    expect(grant["scope_sha256"] == digest(grant["scope"]), "SIGNED_SCOPE_HASH_INVALID")
    expect(grant["allowed_effect"] == "synthetic_protected_fixture_read"
           and grant["protected_data"] is True and grant["trading"] is False,
           "GRANT_EFFECT_UNSAFE")
    expect(trust["trust_domain"] == "SYNTHETIC_ONLY", "TRUST_DOMAIN_NOT_SYNTHETIC")
    issuers = [i for i in trust["issuers"] if i["issuer_id"] == grant["issuer_id"]]
    expect(len(issuers) == 1 and issuers[0]["enabled"] is True,
           "EXTERNAL_ISSUER_NOT_TRUSTED")
    Ed25519PublicKey.from_public_bytes(base64.b64decode(issuers[0]["public_key_b64"])).verify(
        base64.b64decode(grant["signature_b64"]),
        json.dumps({k: v for k, v in grant.items() if k != "signature_b64"},
                   sort_keys=True, separators=(",", ":"), allow_nan=False,
                   ensure_ascii=True).encode(),
    )
    expect(len(payload) == action["max_read_bytes"]
           and payload.startswith(b"ATS2_SYNTHETIC_PROTECTED_V1:"),
           "NOT_SYNTHETIC_BYTES")
    expect(sha_bytes(payload) == action["identity"]["data_sha256"]
           == auth["input_sha256"], "PROTECTED_INPUT_DIGEST_DRIFT")
    expect(grant["grant_id"] == auth["grant_id"] == claim["grant_id"]
           == proof["grant_id"], "CONSUMED_GRANT_ID_DRIFT")
    expect(claim["status"] == "CONSUMED" and claim["attempts"] == 1
           and claim["retry_policy"] == "NO_AUTOMATIC_RETRY", "GRANT_NOT_ONE_SHOT")
    expect(claim["scope_sha256"] == grant["scope_sha256"] and
           claim["action_sha256"] == action["contract_sha256"],
           "CONSUMED_CLAIM_SCOPE_DRIFT")
    issued = datetime.fromisoformat(grant["issued_at"])
    expires = datetime.fromisoformat(grant["expires_at"])
    consumed = datetime.fromisoformat(claim["consumed_at"])
    verified = datetime.fromisoformat(proof["verified_at"])
    expect(issued <= consumed <= verified < expires, "CONSUMPTION_OUTSIDE_SIGNED_WINDOW")
    receipt_dir = relative / "synthetic_only" / "protected_receipts" / grant["grant_id"]
    digest_doc = load(receipt_dir / "digest.json")
    expect(digest_doc["sha256"] == auth["input_sha256"]
           and digest_doc["bytes_read"] == len(payload)
           and digest_doc["issuer_key_visible"] is False
           and digest_doc["trust_policy_visible"] is False,
           "WORKER_PROTECTED_RECEIPT_INVALID")
    expect(proof["output_sha256"] == sha_file(receipt_dir / "digest.json"),
           "ACCEPTED_PROOF_OUTPUT_MISMATCH")
    expect(proof["synthetic_only"] is True and proof["live_order_authority"] is False
           and proof["external_issuer_private_key_not_mounted"] is True
           and proof["trusted_policy_not_mounted"] is True
           and proof["network_namespace_unshared"] is True,
           "PROTECTED_WORKER_BOUNDARY_UNVERIFIED")
    expect(auth["replay_denial"] == "PROTECTED_GRANT_CONSUMED", "GRANT_REPLAY_NOT_DENIED")
    expect(len(list((relative / "synthetic_only" / "consumed_claims").glob("*.json"))) == 1
           and len(list((relative / "synthetic_only" / "protected_receipts").glob("*/accepted.json"))) == 1,
           "PROTECTED_READ_DUPLICATED")
    for name, case in auth["negative_cases"].items():
        expect(case["status"] == "BLOCKED", "NEGATIVE_AUTHORIZATION_ACCEPTED:" + name)
    cases.append("external_ed25519_fixture_positive_signature_scope_and_one_use")
    cases.append("synthetic_protected_bytes_mounted_only_after_authorization")
    cases.append("fixture_negative_authorization_and_no_duplicate_read")


def check_recovery(root: Path, manifest: dict, cases: list[str]) -> None:
    report = manifest["public_native_crash_recovery"]
    base = root / "public_native_recovery"
    judge = load(base / report["outside_judge_path"])
    expect(sha_file(base / report["outside_judge_path"]) == report["outside_judge_sha256"],
           "RECOVERY_JUDGE_FILE_DRIFT")
    expect(judge["state"] == "PASS"
           and judge["recovered"]["state"] == "RAW_EVIDENCE_REPLAY_PASSED"
           and judge["control"]["state"] == "RAW_EVIDENCE_REPLAY_PASSED",
           "INDEPENDENT_NATIVE_REPLAY_FAILED")
    event_dir = (base / "crashed" / "run_log" / "research_sessions" /
                 "permit-synthetic" / "attempts")
    events = [load(p) for p in event_dir.glob("*.json")]
    latest = {}
    for event in sorted(events, key=lambda e: (e["attempt_id"], e["revision"])):
        latest[event["attempt_id"]] = event
    expect(set(latest) == {report["aborted_attempt"], report["recovered_attempt"]},
           "RECOVERY_ATTEMPT_COUNT_INCORRECT")
    old = latest[report["aborted_attempt"]]
    new = latest[report["recovered_attempt"]]
    expect(old["status"] == "ABORTED" and new["status"] == "COMPLETED",
           "RECOVERY_TERMINAL_STATES_INVALID")
    expect(new["parent_attempt_id"] == old["attempt_id"]
           and new["fencing_token"] > old["fencing_token"]
           and new["metadata"]["authorization"]["grant_id"] ==
           old["metadata"]["authorization"]["grant_id"] ==
           report["original_grant_id"]
           and new["metadata"]["ats2_action"] == old["metadata"]["ats2_action"],
           "RECOVERY_SIGNED_ORIGINAL_AUTHORITY_NOT_PRESERVED")
    cases.append("actual_native_public_api_sigkill_recovery_and_attempt_fencing")
    cases.append("independent_native_raw_replay_matches_clean_control")


def check_budget(root: Path, manifest: dict, cases: list[str]) -> None:
    memory = manifest["hard_memory_cgroup"]
    path = Path(memory["resource_path"])
    expect(path.is_relative_to(root), "MEMORY_REPORT_OUTSIDE_ACCEPTANCE")
    report = load(path)
    expect(sha_file(path) == memory["resource_sha256"], "MEMORY_EVIDENCE_TAMPER")
    expect(report["last_verified_scope"]["memory_max_bytes"] == 128 * 1024 * 1024,
           "MEMORY_MAX_NOT_ENFORCED")
    expect(report["last_verified_scope"]["memory_swap_max_bytes"] == 0
           and report["scope_verified"] is True, "MEMORY_OR_SWAP_ENFORCEMENT_UNVERIFIED")
    expect(report["terminal_scope"]["result"] == "oom-kill"
           and report["process_returncode"] != 0
           and memory["replay_denial"] == "TERMINAL_ATTEMPT_RETAINED",
           "KERNEL_OOM_OR_REPLAY_NOT_PROVEN")
    event_dir = root / "memory_exhaustion" / "run_log" / "research_sessions" / "permit-synthetic" / "attempts"
    events = [load(p) for p in event_dir.glob("*.json")]
    expect(sum(r["status"] == "PLANNED" for r in events) == 1
           and any(r["status"] == "FAILED" for r in events), "OOM_ATTEMPT_NOT_DURABLE")
    cases.append("kernel_cgroup_v2_128m_oom_no_swap_and_terminal_grant_consumption")


def check_concurrency_and_boundaries(manifest: dict, cases: list[str]) -> None:
    for name in ("clean_control", "concurrent_control"):
        case = manifest[name]
        expect(case["verification"]["state"] == "VERIFIED", "NATIVE_VERIFICATION_NOT_PASS:" + name)
        attempts = {row["attempt_id"] for row in case["ledger_raw"] if row["status"] == "PLANNED"}
        expect(len(attempts) == 1, "DUPLICATE_NATIVE_ADMISSION:" + name)
    auth = manifest["authorization_boundary"]["cases"]
    expect(auth["valid"]["decision"] == "ALLOW"
           and auth["valid"]["private_key_denied"]
           and auth["valid"]["policy_write_denied"], "LANDLOCK_POSITIVE_FAILED")
    for name, row in auth.items():
        if name == "valid":
            continue
        expect(row["decision"] == "DENY"
               and row["private_key_denied"]
               and row["policy_write_denied"], "LANDLOCK_NEGATIVE_FAILED:" + name)
    recovery = manifest["crash_recovery"]
    expect(recovery["uncertain_reason"] == "LEASE_UNCERTAIN"
           and recovery["worker_exit"] == -9
           and {row["kind"] for row in recovery["rejected_late"]} >= {"write", "completion"},
           "FENCED_LATE_WRITE_OR_COMPLETION_NOT_REJECTED")
    cases.append("concurrent_one_admission_stale_authority_negative_landlock_corpus")
    cases.append("expired_lease_reclaim_late_write_and_completion_rejected")


def check_acceptance(root: Path, repo: Path) -> dict:
    manifest = load(root / "acceptance.json")
    expect(manifest["outcome"] == "QUALIFIED"
           and manifest["qualification_scope"] == "ATS2_SYNTHETIC_ONLY",
           "UNQUALIFIED_OR_WRONG_SCOPE")
    for relative, expected in manifest["raw_file_hashes"].items():
        expect(sha_file(root / relative) == expected, "RAW_ACCEPTANCE_FILE_DRIFT:" + relative)
    for name, expected in manifest["code_identity"].items():
        path = Path(name)
        if not path.is_absolute():
            path = repo / path
        expect(sha_file(path) == expected, "SOURCE_IDENTITY_DRIFT:" + name)
    cases = ["all_saved_raw_files_sha256_verified", "source_hashes_match_active_code"]
    check_authorization(root, manifest, cases)
    check_recovery(root, manifest, cases)
    check_budget(root, manifest, cases)
    check_concurrency_and_boundaries(manifest, cases)
    return {"schema_version": 1, "state": "PASS", "qualification_scope": "ATS2_SYNTHETIC_ONLY",
            "acceptance": str(root / "acceptance.json"), "acceptance_sha256":
            sha_file(root / "acceptance.json"),
            "independent_judge_sha256": sha_file(Path(__file__)),
            "checks": cases, "count": len(cases),
            "limitations": [
                "Synthetic protected bytes only. This does not grant production protected-history reads.",
                "Same-UID host owner is outside issuer custody and evidence tamper-resistance proof.",
                "No broker credentials, real account marks, live trading, or production deployment qualified.",
            ]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acceptance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        root = args.acceptance.resolve()
        if args.output.exists():
            raise AssertionError("OUTPUT_ALREADY_EXISTS")
        report = check_acceptance(root, Path(__file__).resolve().parents[1])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as file:
            file.write(json.dumps(report, sort_keys=True, indent=2) + "\n")
        print(json.dumps({"state": "PASS", "checks": len(report["checks"]),
                          "report": str(args.output)}, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, AssertionError, IndexError,
            InvalidSignature) as exc:
        print(json.dumps({"state": "FAILED", "error": f"{type(exc).__name__}: {exc}"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
