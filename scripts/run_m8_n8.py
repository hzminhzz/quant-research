"""Identity-bound M8 N8 pilot controller and native executor."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import polars as pl
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.research_control.attempts import AttemptLedger, tmux_sessions
from src.research_control.casefile import build_casefile
from src.research_control.contracts import ResearchContractV1
from src.research_control.feature_gateway import FeatureGateway
from src.research_control.m8_n8 import run_permitted_n8
from src.research_control.run_permit import RunIntentV1, preflight_run
from src.research_session import record_trial, session_status

SESSION = "m8_n8_dukascopy_nas100_cfd_30m_v2"
TRIAL = "N8_primary_3cost_stress"
JOB = "ml4t-m8-n8-pilot-exec-20261013"
COMMAND = "uv run python scripts/run_m8_n8.py execute --attempt-id {attempt_id}"
SPEC_PATH = ROOT / "run_log/research_sessions" / SESSION / "frozen_spec.json"
DATA_PATH = ROOT / "data/research_sessions/m8_n8_dukascopy_nas100_cfd_30m_v1/prices_30m.parquet"
CONFIG_PATH = ROOT / "config/research_contract_m8_n8_v2.yaml"
INTENT_PATH = ROOT / "run_log/m8/n8/run_intent_v2.json"


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
    )
    if decision.status in ("RESUME", "REUSE"):
        print(json.dumps(decision.__dict__, indent=2, sort_keys=True))
        return 0
    if decision.status != "LAUNCH" or not decision.attempt_id:
        print(json.dumps(decision.__dict__, indent=2, sort_keys=True))
        return 2
    command = [
        "tmux", "new-session", "-d", "-s", JOB,
        "cd " + shlex.quote(str(ROOT)) + " && uv run python scripts/run_m8_n8.py execute --attempt-id "
        + shlex.quote(decision.attempt_id),
    ]
    started = subprocess.run(command, capture_output=True, text=True, check=False)
    if started.returncode:
        ledger.transition(
            decision.attempt_id,
            "FAILED",
            detail=f"tmux launch failed: {started.stderr.strip()}",
        )
        print(json.dumps({"status": "FAILED", "reason_code": "JOB_LAUNCH_FAILED", "detail": started.stderr.strip()}))
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


def _restore_completed_artifact(
    output: Path, *, attempt_id: str, permit: Any
) -> dict[str, Any] | None:
    report_path = output / "report.json"
    manifest_path = output / "manifest.json"
    if not report_path.exists() and not manifest_path.exists():
        return None
    if not report_path.is_file() or not manifest_path.is_file():
        raise RuntimeError("ARTIFACT_PARTIAL: report or manifest is missing")
    manifest = json.loads(manifest_path.read_text())
    identity = permit.identity.model_dump(mode="json")
    expected_identity = {
        "permit_sha256": permit.permit_sha256,
        "session_id": permit.session_id,
        "trial_id": permit.trial_id,
        "identity": identity,
        "scenarios": ["1x", "2x", "3x"],
    }
    if (
        manifest.get("schema_version") != 1
        or manifest.get("attempt_id") != attempt_id
        or any(manifest.get(key) != value for key, value in expected_identity.items())
        or "report.json" not in manifest.get("files", {})
    ):
        raise RuntimeError("ARTIFACT_IDENTITY_DRIFT: manifest does not match current attempt and permit")
    required = {"report.json"} | {
        f"{kind}_{scenario}.parquet"
        for scenario in expected_identity["scenarios"]
        for kind in ("fills", "equity")
    }
    if set(manifest["files"]) != required:
        raise RuntimeError("ARTIFACT_PARTIAL: expected exactly report and all six scenario tables")
    for relative, digest in manifest["files"].items():
        path = output / relative
        if not path.is_file():
            raise RuntimeError(f"ARTIFACT_PARTIAL: {relative} is missing")
        if _hash(path) != digest:
            raise RuntimeError(f"ARTIFACT_IDENTITY_DRIFT: {relative}")
    report = json.loads(report_path.read_text())
    if report.get("status") != "COMPLETED" or any(
        report.get(key) != value for key, value in expected_identity.items()
    ):
        raise RuntimeError("ARTIFACT_IDENTITY_DRIFT: report identity/status mismatch")
    if len(report.get("cost_scenarios", [])) != 3:
        raise RuntimeError("ARTIFACT_PARTIAL: three completed cost scenarios are required")
    for scenario in report["cost_scenarios"]:
        name = scenario.get("scenario")
        if name not in expected_identity["scenarios"] or scenario.get("audit", {}).get("status") != "PASS":
            raise RuntimeError("ARTIFACT_AUDIT_INVALID: missing independent audit PASS")
        try:
            fills = pl.read_parquet(output / f"fills_{name}.parquet")
            equity = pl.read_parquet(output / f"equity_{name}.parquet")
        except pl.exceptions.PolarsError as exc:
            raise RuntimeError("ARTIFACT_PARQUET_INVALID: unreadable native table") from exc
        if not {"timestamp", "side", "quantity", "price", "commission"}.issubset(fills.columns):
            raise RuntimeError("ARTIFACT_SCHEMA_INVALID: native fills schema mismatch")
        if not {"timestamp", "equity"}.issubset(equity.columns) or equity.is_empty():
            raise RuntimeError("ARTIFACT_SCHEMA_INVALID: native equity schema mismatch")
        if fills.height != scenario["audit"].get("fill_count") or equity.height != scenario["audit"].get("cash_position_ledger_rows"):
            raise RuntimeError("ARTIFACT_AUDIT_INVALID: stored audit row counts mismatch")
    return report


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
    output = ROOT / "run_log/m8/n8/results" / attempt_id
    try:
        contract, intent, data, computation, gate = _inputs()
        if gate.status != "PASS" or gate.permit is None:
            raise RuntimeError(f"PERMIT_REJECTED: {gate.reason_code}")
        # Re-entry is safe only when the complete artifact matches this exact permit.
        restored = None
        generations = [output] + sorted(
            (path for path in output.glob("replay_*") if path.is_dir()),
            key=lambda path: path.name,
        ) if output.exists() else []
        for candidate in generations:
            if any((candidate / name).exists() for name in ("report.json", "manifest.json")):
                restored = _restore_completed_artifact(
                    candidate, attempt_id=attempt_id, permit=gate.permit
                )
                output = candidate
                break
        if restored is None and output.exists():
            # Preserve tables left by a hard interruption. Replay is written
            # to a new immutable generation under the same attempt.
            generation = 1 + len([p for p in output.glob("replay_*") if p.is_dir()])
            output = output / f"replay_{generation}"
        if restored is None:
            running = ledger.transition(attempt_id, "RUNNING", detail="native worker started")
            if running.reason_code != "ATTEMPT_STATE_RECORDED":
                print(json.dumps(running.__dict__, indent=2, sort_keys=True))
                return 2
            result = run_permitted_n8(
                str(ROOT), intent, data, computation, contract,
                start=intent.evaluation_start, end=intent.evaluation_end,
            )
            if result.get("status") != "COMPLETED":
                raise RuntimeError(f"N8_RUN_{result.get('status')}: {result.get('reason_code')}")
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
                    "data_sha256": _hash(DATA_PATH),
                    "feature_proof_sha256": computation.proof.output_sha256,
                    "engine_version": importlib.metadata.version("ml4t-backtest"),
                    "recovery_policy": "Complete hash-verified result artifacts may be recorded on re-entry. Partial artifacts fail closed; ambiguous jobs are never duplicated.",
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


def main() -> int:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("prepare")
    executor = subcommands.add_parser("execute")
    executor.add_argument("--attempt-id", required=True)
    args = parser.parse_args()
    return prepare() if args.command == "prepare" else execute(args.attempt_id)


if __name__ == "__main__":
    raise SystemExit(main())
