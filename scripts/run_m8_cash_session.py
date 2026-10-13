"""Identity-bound M8 N8 pilot controller and native executor."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path

import polars as pl
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_m8_n8 import _restore_completed_artifact
from src.research_control.attempts import (
    AttemptLedger,
    launch_managed_worker,
    tmux_sessions,
)
from src.research_control.casefile import build_casefile
from src.research_control.contracts import ResearchContractV1
from src.research_control.feature_gateway import FeatureGateway
from src.research_control.m8_n8 import run_permitted_n8
from src.research_control.run_permit import RunIntentV1, preflight_run
from src.research_session import record_trial, session_status

SESSION = "m8_n8_dukascopy_us_cash_30m_v7"
TRIAL = "N8_cash_session_primary_3cost_stress"
JOB = "ml4t-m8-cash-pilot"
COMMAND = "uv run python scripts/run_m8_cash_session.py execute --attempt-id {attempt_id}"
SPEC_PATH = ROOT / "run_log/research_sessions" / SESSION / "frozen_spec.json"
DATA_PATH = ROOT / "data/research_sessions/m8_n8_dukascopy_nas100_cfd_30m_v1/prices_30m.parquet"
CONFIG_PATH = ROOT / "config/research_contract_m8_n8_cash_v7.yaml"
INTENT_PATH = ROOT / "run_log/m8/n8/cash_session_run_intent_v7.json"


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inputs():
    contract = ResearchContractV1.model_validate(yaml.safe_load(CONFIG_PATH.read_text()))
    intent = RunIntentV1.model_validate_json(INTENT_PATH.read_text())
    data = pl.read_parquet(DATA_PATH)
    computation = FeatureGateway().compute(data, contract)
    gate = preflight_run(str(ROOT), intent, computation, data, contract)
    return contract, intent, data, computation, gate


def prepare() -> int:
    contract, _intent, data, computation, gate = _inputs()
    if gate.status != "PASS" or gate.permit is None:
        print(json.dumps(gate.model_dump(mode="json"), indent=2, sort_keys=True))
        return 2
    if importlib.metadata.version("ml4t-backtest") != "0.1.7":
        print(json.dumps({"status": "BLOCKED", "reason_code": "ENGINE_VERSION_UNKNOWN"}))
        return 2
    frozen = session_status(SESSION, ROOT)
    trial = next(
        item for item in frozen["trials"] if item["declaration"]["id"] == TRIAL
    )
    if trial["status"] in {"failed", "completed"}:
        print(json.dumps({"status": "BLOCKED", "reason_code": "TRIAL_TERMINAL"}))
        return 2
    ledger = AttemptLedger(ROOT, SESSION, list_jobs=tmux_sessions)
    decision = ledger.claim(
        gate,
        job_name=JOB,
        command=COMMAND,
        lease_seconds=7200,
        managed_worker=True,
    )
    if decision.status in ("RESUME", "REUSE"):
        if decision.status == "REUSE" and decision.attempt_id:
            result = run_permitted_n8(
                str(ROOT), _intent, data, computation, contract,
                start=_intent.evaluation_start, end=_intent.evaluation_end,
                cash_session_only=True,
            )
            if result.get("status") != "COMPLETED":
                print(json.dumps({"status": "BLOCKED", "reason_code": "ARTIFACT_NATIVE_REPLAY_FAILED"}))
                return 2
            replay = {
                item["scenario"]: {"fills": item["fills"], "equity": item["equity"], "audit": item["audit"]}
                for item in result["cost_scenarios"]
            }
            artifact = ROOT / "run_log/m8/n8/cash_session/results" / decision.attempt_id
            try:
                _restore_completed_artifact(
                    artifact, attempt_id=decision.attempt_id, permit=gate.permit,
                    native_replay=replay,
                    parent_attempt_id=ledger.latest()[decision.attempt_id].get("parent_attempt_id"),
                )
            except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
                print(json.dumps({"status": "BLOCKED", "reason_code": "ARTIFACT_REUSE_REJECTED", "detail": str(exc)}))
                return 2
        print(json.dumps(decision.__dict__, indent=2, sort_keys=True))
        return 0
    if decision.status != "LAUNCH" or not decision.attempt_id:
        print(json.dumps(decision.__dict__, indent=2, sort_keys=True))
        return 2
    launched = launch_managed_worker(
        JOB,
        ROOT,
        ["uv", "run", "python", "scripts/run_m8_cash_session.py", "execute",
         "--attempt-id", decision.attempt_id],
        log_path=ledger.path / f"{decision.attempt_id}.worker.log",
    )
    if launched.reason_code != "JOB_LAUNCHED":
        if launched.reason_code == "JOB_LAUNCH_FAILED":
            ledger.transition(
                decision.attempt_id,
                "FAILED",
                detail=f"tmux launch failed: {launched.detail}",
            )
        print(json.dumps({
            "status": "FAILED" if launched.reason_code == "JOB_LAUNCH_FAILED" else "BLOCKED",
            "reason_code": launched.reason_code,
            "detail": launched.detail,
        }))
        return 2
    print(
        json.dumps(
            {
                "status": "LAUNCHED",
                "attempt_id": decision.attempt_id,
                "job_name": JOB,
                "permit_sha256": gate.permit.permit_sha256,
                "data_rows": data.height,
                "feature_rows": computation.data.height,
                "command": COMMAND,
                "frozen_session": contract.session_id,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def preflight() -> int:
    """Report identity and feature-proof gate only; do not inspect outcomes."""
    _contract, _intent, data, computation, gate = _inputs()
    print(json.dumps({
        "status": gate.status,
        "reason_code": gate.reason_code,
        "summary": gate.summary,
        "session_id": SESSION,
        "trial_id": TRIAL,
        "data_rows": data.height,
        "data_sha256": _hash(DATA_PATH),
        "feature_proof_sha256": computation.proof.output_sha256,
        "engine_version": importlib.metadata.version("ml4t-backtest"),
        "holdout_accessed": False,
        "outcomes_computed": False,
        "live_order_authority": False,
    }, indent=2, sort_keys=True, default=str))
    return 0 if gate.status == "PASS" else 2


def execute(attempt_id: str) -> int:
    ledger = AttemptLedger(ROOT, SESSION, list_jobs=tmux_sessions)
    jobs = tmux_sessions()
    if jobs is None or JOB not in jobs:
        print(json.dumps({"status": "BLOCKED", "reason_code": "JOB_VISIBILITY_UNKNOWN_OR_ABSENT"}))
        return 2
    current = ledger.latest().get(attempt_id)
    if current is None or current["job_name"] != JOB:
        print(json.dumps({"status": "BLOCKED", "reason_code": "ATTEMPT_UNKNOWN"}))
        return 2
    worker_context = ledger.worker_lease(attempt_id)
    try:
        worker_context.__enter__()
    except RuntimeError as exc:
        print(json.dumps({"status": "BLOCKED", "reason_code": str(exc)}))
        return 2
    output = ROOT / "run_log/m8/n8/cash_session/results" / attempt_id
    try:
        contract, intent, data, computation, gate = _inputs()
        if gate.status != "PASS" or gate.permit is None:
            raise RuntimeError(f"PERMIT_REJECTED: {gate.reason_code}")
        if current.get("fingerprints") != gate.permit.identity.model_dump(mode="json"):
            raise RuntimeError("ATTEMPT_IDENTITY_DRIFT: permit or frozen identity changed")
        latest = ledger.latest().get(attempt_id, {})
        if latest.get("status") == "PLANNED":
            transition = ledger.transition(attempt_id, "RUNNING", detail="native worker started")
            if transition.reason_code != "ATTEMPT_STATE_RECORDED":
                raise RuntimeError("ATTEMPT_STATE_INVALID: could not enter RUNNING")
            ledger.record_checkpoint(attempt_id, progress=0, artifacts={})
        # Recovery compares stored outputs with a fresh native execution and its audit.
        native_result = run_permitted_n8(
            str(ROOT), intent, data, computation, contract,
            start=intent.evaluation_start, end=intent.evaluation_end, cash_session_only=True,
        )
        if native_result.get("status") != "COMPLETED":
            raise RuntimeError(f"N8_RUN_{native_result.get('status')}: {native_result.get('reason_code')}")
        native_replay = {
            item["scenario"]: {"fills": item["fills"], "equity": item["equity"], "audit": item["audit"]}
            for item in native_result["cost_scenarios"]
        }
        restored = None
        generations = [output] + sorted(
            (path for path in output.glob("replay_*") if path.is_dir()),
            key=lambda path: path.name,
        ) if output.exists() else []
        for candidate in generations:
            if any((candidate / name).exists() for name in ("report.json", "manifest.json")):
                restored = _restore_completed_artifact(
                    candidate, attempt_id=attempt_id, permit=gate.permit,
                    native_replay=native_replay,
                    parent_attempt_id=ledger.latest()[attempt_id].get("parent_attempt_id"),
                )
                output = candidate
                break
        if restored is None and output.exists():
            # Preserve tables left by a hard interruption. Replay is written
            # to a new immutable generation under the same attempt.
            generation = 1 + len([p for p in output.glob("replay_*") if p.is_dir()])
            output = output / f"replay_{generation}"
        if restored is None:
            result = native_result
            output.mkdir(parents=True, exist_ok=False)
            summaries = []
            files: dict[str, str] = {}
            for scenario in result["cost_scenarios"]:
                name = scenario["scenario"]
                fills_path = output / f"fills_{name}.parquet"
                equity_path = output / f"equity_{name}.parquet"
                scenario["fills"].write_parquet(fills_path)
                scenario["equity"].write_parquet(equity_path)
                files[fills_path.name] = _hash(fills_path)
                files[equity_path.name] = _hash(equity_path)
                ledger.record_checkpoint(
                    attempt_id,
                    progress=len(files),
                    artifacts={
                        (output / filename).relative_to(ROOT).as_posix(): digest
                        for filename, digest in files.items()
                    },
                )
                summaries.append(
                    {"scenario": name, "audit": scenario["audit"], "metrics": scenario["metrics"]}
                )
            report = {
                key: value for key, value in result.items() if key != "cost_scenarios"
            }
            report.update(
                {
                    "attempt_id": attempt_id,
                    "permit_sha256": gate.permit.permit_sha256,
                    "session_id": gate.permit.session_id,
                    "trial_id": gate.permit.trial_id,
                    "identity": gate.permit.identity.model_dump(mode="json"),
                    "scenarios": ["1x", "2x", "3x"],
                    "cost_scenarios": summaries,
                    "source_fingerprint_sha256": _hash(ROOT / "run_log/m8/n8/source_fingerprints_recovery.json"),
                    "cash_session_only": True,
                    "data_sha256": _hash(DATA_PATH),
                    "feature_proof_sha256": computation.proof.output_sha256,
                    "engine_version": importlib.metadata.version("ml4t-backtest"),
                    "recovery_policy": "An expired worker is appended as ABORTED only after its OS lock is released and its immutable checkpoint matches the permit identity. Recovery creates a successor attempt with a new ID. It retains the parent artifacts and reruns the native calculation from the beginning. It does not claim same-attempt continuation.",
                    "parent_attempt_id": ledger.latest()[attempt_id].get("parent_attempt_id"),
                }
            )
            report_path = output / "report.json"
            report_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
            files[report_path.name] = _hash(report_path)
            manifest = {
                "schema_version": 1,
                "attempt_id": attempt_id,
                "permit_sha256": gate.permit.permit_sha256,
                "session_id": gate.permit.session_id,
                "trial_id": gate.permit.trial_id,
                "identity": gate.permit.identity.model_dump(mode="json"),
                "scenarios": ["1x", "2x", "3x"],
                "files": files,
            }
            parent_attempt_id = ledger.latest()[attempt_id].get("parent_attempt_id")
            if parent_attempt_id is not None:
                manifest["parent_attempt_id"] = parent_attempt_id
            manifest_path = output / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            restored = report
        trial_status = restored.get("status", "FAILED").lower()
        session = session_status(SESSION, ROOT)
        trial = next(
            item
            for item in session["trials"]
            if item["declaration"]["id"] == TRIAL
        )
        report_path = output / "report.json"
        report_relative = report_path.relative_to(ROOT).as_posix()
        if trial["status"] == "pending":
            record_trial(SESSION, TRIAL, trial_status, report_path, ROOT)
        elif (
            trial["record"] is None
            or trial["record"]["artifact"]["path"] != report_relative
            or trial["record"]["artifact"]["sha256"] != _hash(report_path)
        ):
            raise RuntimeError(
                "TRIAL_RECORD_IDENTITY_DRIFT: recorded trial differs from artifact"
            )
        if ledger.latest()[attempt_id]["status"] == "RUNNING":
            ledger.transition(
                attempt_id,
                "COMPLETED",
                detail="native fills and independent audit recorded",
            )
        casefile = build_casefile(ROOT, SESSION, list_jobs=tmux_sessions)
        casefile_path = output / "casefile.json"
        casefile_path.write_text(json.dumps(casefile, indent=2, sort_keys=True, default=str) + "\n")
        print(json.dumps({"status": "COMPLETED", "attempt_id": attempt_id, "artifact": str(output.relative_to(ROOT)), "casefile_status": casefile["status"]}, indent=2))
        return 0
    except (
        OSError,
        RuntimeError,
        ValueError,
        TypeError,
        KeyError,
        subprocess.SubprocessError,
        pl.exceptions.PolarsError,
    ) as exc:
        latest = ledger.latest().get(attempt_id, {})
        if latest.get("status") not in {"COMPLETED", "FAILED", "BLOCKED", "ABORTED"}:
            output.mkdir(parents=True, exist_ok=True)
            report_path = output / "report.json"
            if not report_path.exists():
                report_path.write_text(
                    json.dumps(
                        {
                            "status": "FAILED",
                            "classification": "EXPLORATORY_HISTORICAL_CFD_PRICE_RESEARCH",
                            "approval_status": "NOT_APPROVED",
                            "live_order_authority": False,
                            "reason_code": str(exc),
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n"
                )
            manifest_path = output / "manifest.json"
            if not manifest_path.exists():
                files = {
                    path.name: _hash(path)
                    for path in output.iterdir()
                    if path.is_file() and path.name != "manifest.json"
                }
                manifest_path.write_text(
                    json.dumps(
                        {"schema_version": 1, "attempt_id": attempt_id, "files": files},
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n"
                )
            session = session_status(SESSION, ROOT)
            trial = next(
                item
                for item in session["trials"]
                if item["declaration"]["id"] == TRIAL
            )
            if trial["status"] == "pending":
                record_trial(SESSION, TRIAL, "failed", report_path, ROOT)
            ledger.transition(attempt_id, "FAILED", detail=f"{type(exc).__name__}: {exc}")
        print(json.dumps({"status": "FAILED", "attempt_id": attempt_id, "reason_code": str(exc)}, indent=2))
        return 2
    finally:
        worker_context.__exit__(None, None, None)


def main() -> int:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("prepare")
    subcommands.add_parser("preflight")
    executor = subcommands.add_parser("execute")
    executor.add_argument("--attempt-id", required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        return prepare()
    if args.command == "preflight":
        return preflight()
    return execute(args.attempt_id)


if __name__ == "__main__":
    raise SystemExit(main())
