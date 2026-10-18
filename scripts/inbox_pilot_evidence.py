"""Read-only independent verifier for inbox-driven research pilots.

Re-derives, from recorded bytes only, the evidence an operator needs before
accepting an inbox terminal decision as real:

  source identity -> frozen spec -> canonical data manifest -> runtime code hash
  -> Stage 1/2 receipts and artifacts -> Casefile -> append-only trial ledger
  -> independent recomputation of the Stage 2 mean IC and Newey-West HAC t.

It never executes a strategy, never writes into the run log, never reads a
protected partition, and never issues a research or trading decision. Any
mismatch exits non-zero: an unverifiable pilot is not evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.engine.common import digest, runtime_identity
from src.oracle.research_protocols import parse_research_spec

TERMINAL_WITH_CASEFILE = {"FALSIFIED", "DEVELOPMENT_QUALIFIED", "INCONCLUSIVE", "BLOCKED_EXECUTION"}


class VerificationError(RuntimeError):
    """Raised when recorded evidence does not reproduce."""


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def newey_west_t(values: np.ndarray, lags: int) -> tuple[float, float, float]:
    """Mean, Newey-West (Bartlett) standard error and t of a return/IC series.

    Uses the sample (n-1) covariance and the Bartlett taper 1 - l/(L+1), which is
    the convention the native Stage 2 diagnostic reports; the reconstruction is
    therefore expected to agree to floating-point precision, not approximately.
    """
    values = np.asarray(values, dtype=float)
    values = values[~np.isnan(values)]
    n = values.size
    _require(n > 2, "series too short for a HAC statistic")
    mean = float(values.mean())
    deviation = values - mean
    dof = n - 1
    gamma0 = float(np.dot(deviation, deviation) / dof)
    long_run = gamma0
    for lag in range(1, min(lags, n - 1) + 1):
        weight = 1.0 - lag / (lags + 1.0)
        long_run += 2.0 * weight * float(np.dot(deviation[lag:], deviation[:-lag]) / dof)
    _require(long_run > 0, "non-positive long-run variance")
    se = math.sqrt(long_run / n)
    return mean, se, mean / se


def verify_ledger(ledger: Path) -> tuple[int, dict[str, list[dict]]]:
    """Walk the append-only hash chain; return record count and completed-by-spec."""
    _require(ledger.is_file(), f"missing trial ledger: {ledger}")
    previous = "0" * 64
    count = 0
    completed: dict[str, list[dict]] = {}
    for line in ledger.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        stored = record.pop("record_hash")
        _require(record.get("previous_hash") == previous, f"ledger chain broken at record {count + 1}")
        _require(digest(record) == stored, f"ledger record {count + 1} digest mismatch")
        previous = stored
        count += 1
        if record.get("event") == "completed" and record.get("casefile", {}).get("path"):
            completed.setdefault(record["spec_hash"], []).append(record)
    return count, completed


def verify_case(state_path: Path, run_log: Path, completed: dict[str, list[dict]]) -> dict:
    """Verify one inbox candidate's terminal evidence and recompute Stage 2."""
    state = json.loads(state_path.read_text(encoding="utf-8"))
    candidate_id = state["candidate_id"]
    _require(state.get("status") in TERMINAL_WITH_CASEFILE,
             f"{candidate_id}: state status {state.get('status')} is not a terminal decision")
    _require(state.get("holdout_access") is False, f"{candidate_id}: holdout access is not False")
    _require(state.get("native_evidence_verified") is True, f"{candidate_id}: native evidence not verified")

    casefile = Path(state["casefile"])
    _require(casefile.is_file(), f"{candidate_id}: Casefile missing at {casefile}")
    casefile_sha = _sha(casefile)
    _require(casefile_sha == state["casefile_sha256"], f"{candidate_id}: Casefile bytes differ from state hash")
    case = json.loads(casefile.read_text(encoding="utf-8"))

    _require(case.get("development_only") is True or case.get("protocol") == "event",
             f"{candidate_id}: development-only flag absent")
    _require(case.get("holdout_access") is False, f"{candidate_id}: Casefile reports holdout access")
    _require(case.get("holdout_claim") in (None, ""), f"{candidate_id}: Casefile carries a holdout claim")
    _require("4" not in case.get("stages", {}), f"{candidate_id}: Casefile contains a protected Stage 4")
    _require(case.get("code_hash") == state.get("frozen_code_sha256"),
             f"{candidate_id}: Casefile code hash differs from the frozen runtime identity")
    _require(case.get("spec_hash") == state["spec_hash"], f"{candidate_id}: Casefile spec identity differs")

    output = casefile.parent
    manifest_path = Path(state["data_manifest_path"])
    _require(manifest_path.is_file(), f"{candidate_id}: canonical manifest missing")
    _require(_sha(manifest_path) == state["data_manifest_sha256"],
             f"{candidate_id}: canonical manifest bytes changed since execution")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    recorded = manifest.pop("manifest_hash", None)
    _require(recorded is not None and digest(manifest) == recorded,
             f"{candidate_id}: canonical manifest identity digest does not reproduce")
    # `panel_hash` is the manifest identity digest, not the manifest file's byte hash.
    _require(case.get("panel_hash") == recorded,
             f"{candidate_id}: Casefile panel identity differs from the verified manifest")
    spec_file = Path(state["spec_path"])
    _require(_sha(spec_file) == state["spec_file_sha256"], f"{candidate_id}: frozen spec bytes changed")
    # Re-derive the specification identity from its bytes instead of trusting state.
    reparsed = parse_research_spec(spec_file)
    _require(reparsed.spec_hash == state["spec_hash"],
             f"{candidate_id}: frozen spec does not re-derive the recorded spec identity")
    _require(reparsed.spec_hash == case.get("spec_hash"),
             f"{candidate_id}: re-derived spec identity differs from the Casefile")
    source_dir = Path(state["source_path"])
    for name, recorded_source_hash in state.get("source_files_sha256", {}).items():
        _require(_sha(source_dir / name) == recorded_source_hash,
                 f"{candidate_id}: inbox source {name} bytes changed since admission")

    stage1 = case.get("stages", {}).get("1", {})
    _require(stage1.get("status") == "PASS", f"{candidate_id}: Stage 1 causal proof is not PASS")

    receipts = {}
    for stage in ("1", "2"):
        _require(stage in case.get("stages", {}), f"{candidate_id}: Stage {stage} absent from Casefile")
        receipt = json.loads((output / f"stage{stage}.json").read_text(encoding="utf-8"))
        claimed = receipt.pop("receipt_hash", "")
        _require(digest(receipt) == claimed, f"{candidate_id}: Stage {stage} receipt digest mismatch")
        _require(receipt.get("spec_hash") == state["spec_hash"],
                 f"{candidate_id}: Stage {stage} receipt spec identity differs")
        for artifact, fingerprint in receipt.get("artifacts", {}).items():
            artifact_path = output / artifact
            _require(not Path(artifact).is_absolute() and not artifact_path.is_symlink(),
                     f"{candidate_id}: Stage {stage} artifact path escapes the attempt directory")
            _require(artifact_path.resolve().is_relative_to(output.resolve()),
                     f"{candidate_id}: Stage {stage} artifact path escapes the attempt directory")
            _require(_sha(artifact_path) == fingerprint,
                     f"{candidate_id}: Stage {stage} artifact drift in {artifact}")
        receipts[stage] = claimed

    diagnostics = case.get("stages", {}).get("2", {}).get("diagnostics", {})
    ic = pl.read_parquet(output / "stage2_ic.parquet")
    lags = int(case["stages"]["2"].get("hac_lags") or 0)
    recomputed = {}
    for column in ic.columns:
        if column in {"timestamp", "incremental_ic"} or column not in diagnostics:
            continue
        mean, se, t_stat = newey_west_t(ic[column].to_numpy(), lags)
        reported = diagnostics[column]
        _require(abs(mean - reported["mean_ic"]) <= 1e-12,
                 f"{candidate_id}: {column} mean IC does not reproduce")
        _require(abs(se - reported["hac_se"]) <= 1e-12,
                 f"{candidate_id}: {column} HAC standard error does not reproduce")
        _require(abs(t_stat - reported["t_stat"]) <= 1e-12,
                 f"{candidate_id}: {column} HAC t-statistic does not reproduce")
        recomputed[column] = {"mean_ic": mean, "hac_se": se, "t_stat": t_stat,
                              "reported_mean_ic": reported["mean_ic"],
                              "reported_t_stat": reported["t_stat"]}

    records = completed.get(state["spec_hash"], [])
    matching = [r for r in records
                if r["attempt_id"] == case.get("attempt_id")
                and r["casefile"]["sha256"] == casefile_sha
                and r.get("holdout_access") is False]
    _require(bool(matching), f"{candidate_id}: no ledger completion binds this Casefile to this attempt")

    return {
        "candidate_id": candidate_id,
        "inbox_status": state["status"],
        "native_status": case.get("status"),
        "spec_candidate_id": case.get("candidate_id"),
        "spec_hash": state["spec_hash"],
        "native_attempt_id": case.get("attempt_id"),
        "code_hash": case.get("code_hash"),
        "code_identity_is_current_runtime": case.get("code_hash") == runtime_identity(),
        "panel_hash": case.get("panel_hash"),
        "data_manifest_sha256": state["data_manifest_sha256"],
        "source_files_sha256": state.get("source_files_sha256", {}),
        "casefile": str(casefile),
        "casefile_sha256": casefile_sha,
        "receipt_sha256": receipts,
        "stage1_status": stage1.get("status"),
        "stage2_status": case["stages"]["2"].get("status"),
        "holdout_access": case.get("holdout_access"),
        "recomputed_stage2": recomputed,
    }


def verify(inbox_state_root: Path, run_log: Path) -> dict:
    """Verify every terminal inbox candidate that recorded a Casefile."""
    ledger_count, completed = verify_ledger(run_log / "trial_ledger.jsonl")
    verified, failed = [], []
    for state_path in sorted((inbox_state_root / "candidates").glob("*/state.json")):
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if not state.get("casefile"):
            continue
        try:
            verified.append(verify_case(state_path, run_log, completed))
        except VerificationError as exc:
            failed.append({"candidate_id": state.get("candidate_id"), "error": str(exc)})
    _require(bool(verified) or bool(failed), "no terminal inbox Casefile was found to verify")
    return {
        "schema_version": 1,
        "scope": "READ_ONLY_NO_EXECUTION_NO_PROTECTED_NO_ORDERS",
        "inbox_state_root": str(inbox_state_root),
        "ledger_records": ledger_count,
        "verified_count": len(verified),
        "unverifiable_count": len(failed),
        "cases": verified,
        "unverifiable": failed,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inbox-state-root", type=Path, default=ROOT / "run_log/inbox_factory")
    parser.add_argument("--run-log", type=Path, default=ROOT / "run_log")
    parser.add_argument("--output", type=Path, default=None,
                        help="optional path for the verified summary (written atomically)")
    args = parser.parse_args(argv)
    try:
        summary = verify(args.inbox_state_root, args.run_log)
    except VerificationError as exc:
        print(json.dumps({"status": "NOT_VERIFIED", "reason": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    if summary["unverifiable"]:
        print(json.dumps({"status": "PARTIALLY_VERIFIED",
                          "unverifiable": summary["unverifiable"]}, sort_keys=True), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
