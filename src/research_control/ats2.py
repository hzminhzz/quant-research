"""Bounded ATS-2 action loop over the native permit and AttemptLedger authorities.

Only the registered development native bracket operation is executable here.
This module does not expose a command string, protected read, or order capability.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import polars as pl
import yaml
from pydantic import Field, StrictFloat, StrictInt, StrictStr, model_validator

from src.engine.common import beneath, json_bytes
from src.research_session import _load

from .action_authorization import SignedGrantV1, build_scope, validate_grant
from .ats2_raw_audit import TOL, audit_native_outputs
from .attempts import AttemptLedger
from .contracts import ResearchContractV1, StrictModel
from .feature_gateway import FeatureComputation, FeatureGateway
from .run_permit import GateReport, RunIntentV1, _identity_hashes, preflight_run


class ActionContractV1(StrictModel):
    schema_version: Literal[1]
    revision: Literal[1]
    contract_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    operation: Literal["development_native_bracket"]
    session_id: StrictStr
    trial_id: StrictStr
    permit_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    selection_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    identity: dict[StrictStr, StrictStr]
    parameters: dict[StrictStr, StrictStr | StrictInt | StrictFloat]
    read_scope: Literal["frozen_development_inputs"]
    write_scope: StrictStr
    max_wall_seconds: StrictInt = Field(ge=1, le=300)
    max_cpu_seconds: StrictInt = Field(ge=1, le=300)
    max_memory_mb: StrictInt = Field(ge=64, le=4096)
    max_trials: Literal[1]
    retry_policy: Literal["NO_AUTOMATIC_RETRY"]
    expected_outputs: tuple[StrictStr, ...]
    verification: Literal["native_fill_cash_and_identity_reconciliation"]
    authorization_ref: StrictStr = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def verify_contract_hash(self) -> ActionContractV1:
        if self.contract_sha256 != _hash(self.model_dump(mode="json", exclude={"contract_sha256"})):
            raise ValueError("ACTION_CONTRACT_HASH_MISMATCH")
        if set(self.parameters) != {"signal_at", "quantity", "stop_price", "limit_price"}:
            raise ValueError("ACTION_PARAMETERS_INVALID")
        signal = self.parameters["signal_at"]
        if not isinstance(signal, str):
            raise TypeError("ACTION_PARAMETERS_INVALID")
        try:
            signal_at = datetime.fromisoformat(signal)
        except ValueError as exc:
            raise ValueError("ACTION_PARAMETERS_INVALID") from exc
        values = [self.parameters[name] for name in ("quantity", "stop_price", "limit_price")]
        if (signal_at.tzinfo is None or any(isinstance(value, bool) or
            not isinstance(value, (int, float)) or not math.isfinite(float(value))
            for value in values)):
            raise ValueError("ACTION_PARAMETERS_INVALID")
        quantity, stop, limit = map(float, values)
        if quantity <= 0 or stop <= 0 or limit <= stop:
            raise ValueError("ACTION_PARAMETERS_INVALID")
        return self


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False, default=str).encode()).hexdigest()


def _ats2_external_jobs() -> set[str]:
    """ATS-2 owns direct child processes and uses its flock, not tmux sessions."""
    return set()


def _contract(value: ActionContractV1 | dict[str, Any]) -> ActionContractV1:
    raw = value.model_dump(mode="json") if isinstance(value, ActionContractV1) else value
    return ActionContractV1.model_validate(
        {**raw, "expected_outputs": tuple(raw["expected_outputs"])}
    )


def _frozen_runtime(root: Path, session_id: str, supplied_data: pl.DataFrame,
                    supplied_contract: ResearchContractV1) -> tuple[pl.DataFrame, ResearchContractV1, FeatureComputation]:
    _, frozen = _load(root, session_id)
    config_path = frozen.get("identity", {}).get("config", {}).get("path")
    if not config_path:
        raise ValueError("FROZEN_FEATURE_CONFIG_MISSING")
    frozen_contract = ResearchContractV1.model_validate(
        yaml.safe_load(beneath(root, config_path, must_exist=True).read_text())
    )
    if supplied_contract.identity_sha256() != frozen_contract.identity_sha256():
        raise ValueError("FEATURE_CONTRACT_DRIFT")
    paths = [item["path"] for item in frozen["spec"]["data"] if item["role"] == "prices"]
    if not paths:
        raise ValueError("FROZEN_DEVELOPMENT_DATA_MISSING")
    canonical = pl.concat([pl.read_parquet(beneath(root, item, must_exist=True))
                           for item in paths], how="vertical")
    groups = frozen_contract.dataset.group_columns
    if not supplied_data.sort([*groups, "timestamp"]).equals(
        canonical.sort([*groups, "timestamp"])
    ):
        raise ValueError("DEVELOPMENT_INPUT_DRIFT")
    return canonical, frozen_contract, FeatureGateway().compute(canonical, frozen_contract)


def prepare_action(root: str | Path, intent: RunIntentV1 | dict[str, Any],
                   computation: FeatureComputation, input_data: pl.DataFrame,
                   contract: ResearchContractV1, *, signal_at: datetime,
                   quantity: float, stop_price: float, limit_price: float) -> ActionContractV1:
    """Return a frozen contract after permit preflight; starts no worker or writes."""
    root_path = Path(root).resolve()
    input_data, contract, computation = _frozen_runtime(
        root_path, RunIntentV1.model_validate(intent).session_id, input_data, contract
    )
    report = preflight_run(str(root_path), intent, computation, input_data, contract)
    if report.status != "PASS" or report.permit is None:
        raise ValueError(f"PREPARE_BLOCKED:{report.reason_code}")
    permit = report.permit
    authorization_ref = f"run_permit:{permit.permit_sha256}"
    output = f"run_log/ats2/accepted/{permit.session_id}/{permit.trial_id}"
    _, frozen = _load(root_path, permit.session_id)
    frozen_trial = next((trial for trial in frozen["spec"]["trials"]
                         if trial["id"] == permit.trial_id), None)
    if frozen_trial is None:
        raise ValueError("FROZEN_TRIAL_MISSING")
    fields = {
        "schema_version": 1, "revision": 1,
        "operation": "development_native_bracket",
        "session_id": permit.session_id, "trial_id": permit.trial_id,
        "permit_sha256": permit.permit_sha256,
        "selection_sha256": _hash(frozen_trial),
        "identity": permit.identity.model_dump(mode="json"),
        "parameters": {"signal_at": signal_at.isoformat(), "quantity": quantity,
                       "stop_price": stop_price, "limit_price": limit_price},
        "read_scope": "frozen_development_inputs", "write_scope": output,
        "max_wall_seconds": permit.compute_budget.max_wall_seconds,
        "max_cpu_seconds": permit.compute_budget.max_cpu_seconds,
        "max_memory_mb": permit.compute_budget.max_memory_mb,
        "max_trials": 1, "retry_policy": "NO_AUTOMATIC_RETRY",
        "expected_outputs": ("execution_audit.json", "native/"),
        "verification": "native_fill_cash_and_identity_reconciliation",
        "authorization_ref": authorization_ref,
    }
    return ActionContractV1.model_validate(
        {**fields, "contract_sha256": _hash(fields)}
    )


def _validated_inputs(root: Path, action: ActionContractV1,
                      intent: RunIntentV1 | dict[str, Any],
                      computation: FeatureComputation, input_data: pl.DataFrame,
                      contract: ResearchContractV1) -> GateReport:
    input_data, contract, computation = _frozen_runtime(
        root, action.session_id, input_data, contract
    )
    report = preflight_run(str(root), intent, computation, input_data, contract)
    if (report.status != "PASS" or report.permit is None or
        report.permit.permit_sha256 != action.permit_sha256 or
        report.permit.identity.model_dump(mode="json") != action.identity or
        report.permit.trial_id != action.trial_id or
        report.permit.session_id != action.session_id):
        raise ValueError("ACTION_IDENTITY_STALE")
    expected_scope = f"run_log/ats2/accepted/{action.session_id}/{action.trial_id}"
    if (action.authorization_ref != f"run_permit:{action.permit_sha256}" or
        action.read_scope != "frozen_development_inputs" or
        action.write_scope != expected_scope or
        action.max_wall_seconds != report.permit.compute_budget.max_wall_seconds or
        action.max_cpu_seconds != report.permit.compute_budget.max_cpu_seconds or
        action.max_memory_mb != report.permit.compute_budget.max_memory_mb or
        action.max_trials != 1 or action.retry_policy != "NO_AUTOMATIC_RETRY" or
        action.expected_outputs != ("execution_audit.json", "native/") or
        action.verification != "native_fill_cash_and_identity_reconciliation"):
        raise ValueError("ACTION_SCOPE_MUTATED")
    return report


def start_action(root: str | Path, action: ActionContractV1 | dict[str, Any],
                 intent: RunIntentV1 | dict[str, Any],
                 computation: FeatureComputation, input_data: pl.DataFrame,
                 contract: ResearchContractV1, *, grant: SignedGrantV1 | dict[str, Any] | None = None,
                 trusted_policy_path: str | Path | None = None,
                 list_jobs=_ats2_external_jobs) -> dict[str, Any]:
    """Admit once, execute only the frozen native operation, retain terminal record."""
    action = _contract(action)
    root_path = Path(root).resolve()
    gate = _validated_inputs(root_path, action, intent, computation, input_data, contract)
    normalized_intent = RunIntentV1.model_validate(intent)
    scope = build_scope(
        action, window_start=normalized_intent.evaluation_start,
        window_end=normalized_intent.evaluation_end,
        selection_sha256=action.selection_sha256,
    )
    authorization = validate_grant(
        grant or {}, action,
        window_start=normalized_intent.evaluation_start,
        window_end=normalized_intent.evaluation_end,
        selection_sha256=action.selection_sha256,
        trusted_policy_path=trusted_policy_path,
    )
    if authorization.status != "AUTHORIZED":
        return {"status": "BLOCKED", "reason_code": authorization.reason_code}
    ledger = AttemptLedger(root_path, action.session_id, list_jobs=list_jobs)
    key = _hash(action.model_dump(mode="json"))
    job_name = f"ml4t-ats2-{key[:12]}"
    command = f"ats2:{key}"
    run_id = hashlib.sha256(json.dumps(
        {"permit_sha256": gate.permit.permit_sha256, "command": command,
         "job_name": job_name}, sort_keys=True).encode()).hexdigest()
    # Budget exhaustion and other terminal outcomes are final under
    # NO_AUTOMATIC_RETRY: a consumed grant must not obtain a second admission.
    for existing in ledger.latest().values():
        if existing["run_id"] == run_id and existing["status"] == "FAILED":
            return {"status": "BLOCKED", "reason_code": "TERMINAL_ATTEMPT_RETAINED",
                    "attempt_id": existing["attempt_id"],
                    "detail": "terminal attempt retained under NO_AUTOMATIC_RETRY; no retry permitted"}
    claim = ledger.claim(
        gate, job_name=job_name, command=command,
        lease_seconds=3, managed_worker=True,
        metadata={"ats2_action": action.model_dump(mode="json"), "action_hash": key,
                  "intent": normalized_intent.model_dump(mode="json"),
                  "authorization": {"grant_id": authorization.grant_id,
                                    "action_sha256": scope.action_sha256,
                                    "scope_sha256": authorization.scope_sha256}},
    )
    if claim.status != "LAUNCH" or claim.attempt_id is None:
        return {"status": claim.status, "reason_code": claim.reason_code,
                "attempt_id": claim.attempt_id, "detail": claim.detail}
    latest = ledger.latest()[claim.attempt_id]
    artifact_rel = f"{action.write_scope}/{claim.attempt_id}"
    stage_rel = f"run_log/ats2/staging/{claim.attempt_id}"
    stage = beneath(root_path, stage_rel)
    stage.mkdir(parents=True, exist_ok=False)
    sandbox = Path(tempfile.mkdtemp(prefix="ats2-snapshot-"))
    _, frozen = _load(root_path, action.session_id)
    _build_worker_snapshot(root_path, frozen, sandbox)
    sandbox_stage = sandbox / stage_rel
    sandbox_stage.parent.mkdir(parents=True, exist_ok=True)
    sandbox_stage.mkdir(exist_ok=True)
    worker_request = sandbox / "worker-request.json"
    request_doc = {"root": "/work", "action": action.model_dump(mode="json"),
                   "intent": normalized_intent.model_dump(mode="json")}
    worker_request.write_text(json.dumps(request_doc, sort_keys=True, separators=(",", ":")),
                              encoding="utf-8")
    worker_request.chmod(0o400)
    with worker_request.open("rb") as request_file:
        os.fsync(request_file.fileno())
    log_path = ledger.path / f"{claim.attempt_id}.worker.log"
    deadline = time.monotonic() + action.max_wall_seconds
    process = None
    exhausted = False
    resource_unknown = False
    try:
        with log_path.open("xb") as log:
            command = _bubblewrap_command(sandbox, worker_request, stage_rel, stage)
            # RSS polling is a soft observation only; see operations limits.
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True, close_fds=True)
            with ledger.worker_lease(claim.attempt_id, owner_pid=process.pid):
                ledger.transition(claim.attempt_id, "RUNNING", detail="isolated worker started")
                # A zero-progress durable checkpoint makes a crash before the
                # first native artifact explicitly recoverable, never complete.
                ledger.record_checkpoint(claim.attempt_id, progress=0, artifacts={})
                while process.poll() is None:
                    if time.monotonic() >= deadline:
                        exhausted = True
                        _kill_worker_group(process)
                        break
                    rss = _rss_bytes(process.pid)
                    cpu = _cpu_seconds(process.pid)
                    if rss is None or cpu is None:
                        if process.poll() is not None:
                            break
                        resource_unknown = True
                        _kill_worker_group(process)
                        break
                    if rss > action.max_memory_mb * 1024**2 or cpu > action.max_cpu_seconds:
                        exhausted = True
                        _kill_worker_group(process)
                        break
                    time.sleep(0.05)
                process.wait(timeout=5)
        if resource_unknown:
            return {"status": "BLOCKED", "reason_code": "RESOURCE_OBSERVATION_UNKNOWN",
                    "attempt_id": claim.attempt_id, "log_path": str(log_path.relative_to(root_path))}
        if exhausted:
            ledger.transition(claim.attempt_id, "FAILED", detail="BUDGET_EXHAUSTED")
            return {"status": "BUDGET_EXHAUSTED", "reason_code": "RESOURCE_LIMIT",
                    "attempt_id": claim.attempt_id, "log_path": str(log_path.relative_to(root_path))}
        if process.returncode:
            ledger.transition(claim.attempt_id, "FAILED", detail=f"WORKER_EXIT:{process.returncode}")
            return {"status": "INCOMPLETE", "reason_code": "WORKER_OR_OUTPUT_UNCERTAIN",
                    "attempt_id": claim.attempt_id, "worker_exit": process.returncode,
                    "log_path": str(log_path.relative_to(root_path))}
        staged = stage
        if not staged.is_dir() or not any(staged.iterdir()):
            ledger.transition(claim.attempt_id, "FAILED", detail="WORKER_OUTPUT_MISSING")
            return {"status": "INCOMPLETE", "reason_code": "WORKER_OUTPUT_MISSING",
                    "attempt_id": claim.attempt_id}
        for item in sorted(staged.rglob("*")):
            if item.is_symlink():
                ledger.transition(claim.attempt_id, "FAILED", detail="WORKER_OUTPUT_SYMLINK")
                return {"status": "INCOMPLETE", "reason_code": "WORKER_OUTPUT_SYMLINK",
                        "attempt_id": claim.attempt_id}
        output_hashes = {}
        for item in sorted(staged.rglob("*")):
            if item.is_file():
                relative = f"{artifact_rel}/{item.relative_to(staged).as_posix()}"
                ledger.publish_fenced(
                    claim.attempt_id, int(latest.get("fencing_token") or 0),
                    relative_path=relative, payload=item.read_bytes(),
                )
                output_hashes[relative] = hashlib.sha256(item.read_bytes()).hexdigest()
        ledger.record_checkpoint(claim.attempt_id, progress=1, artifacts=output_hashes)
        ledger.transition(claim.attempt_id, "COMPLETED", detail="fenced native output published")
        return {"status": "OUTPUT_READY", "attempt_id": claim.attempt_id,
                "run_id": claim.run_id, "fencing_token": latest.get("fencing_token"),
                "artifact_path": artifact_rel,
                "log_path": str(log_path.relative_to(root_path))}
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def _rss_bytes(pid: int) -> int | None:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _cpu_seconds(pid: int) -> float | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        fields = stat[stat.rfind(")") + 2:].split()
        return (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError):
        return None


def _build_worker_snapshot(root: Path, frozen: dict[str, Any], destination: Path) -> None:
    """Copy only frozen development inputs and the frozen spec into the worker view."""
    identity = frozen["identity"]
    allowed = {identity["input_spec"]["path"]}
    allowed.update(item["path"] for item in frozen["spec"]["data"])
    allowed.update(item["path"] for item in identity.get("source", []))
    allowed.update(item["path"] for item in identity.get("evidence", []))
    config = identity.get("config")
    if config:
        allowed.add(config["path"])
    for relative in sorted(allowed):
        source = beneath(root, relative, must_exist=True)
        if source.is_symlink() or not source.is_file():
            raise ValueError("WORKER_SNAPSHOT_SOURCE_UNSAFE")
        target = beneath(destination, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o444)
    frozen_target = destination / "run_log/research_sessions" / frozen["session_id"] / "frozen_spec.json"
    frozen_target.parent.mkdir(parents=True, exist_ok=True)
    frozen_target.write_text(json.dumps(frozen, sort_keys=True, separators=(",", ":")),
                             encoding="utf-8")
    frozen_target.chmod(0o444)


def _bubblewrap_command(snapshot: Path, request: Path, stage_relative: str,
                        stage: Path) -> list[str]:
    bwrap = shutil.which("bwrap")
    if bwrap is None:
        raise RuntimeError("ISOLATION_UNAVAILABLE")
    repository = Path(__file__).resolve().parents[2]
    source = repository / "src"
    runner_script = repository / "scripts/research_session.py"
    prefix = Path(sys.prefix).resolve()
    executable = Path(sys.executable).resolve()
    command = [bwrap, "--unshare-all", "--die-with-parent", "--new-session",
               "--clearenv", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    for system in ("/usr", "/lib", "/lib64"):
        if Path(system).exists():
            command.extend(("--ro-bind", system, system))
    command.extend(("--ro-bind", str(prefix), str(prefix), "--dir", "/workspace",
                    "--ro-bind", str(source), "/workspace/src", "--dir", "/workspace/scripts"))
    # The resolved executable may live outside the venv prefix (e.g. a symlink
    # to anaconda/python). Mount its directory so execvp finds it inside the sandbox.
    exec_dir = executable.parent
    if exec_dir != prefix and exec_dir.exists():
        command.extend(("--ro-bind", str(exec_dir), str(exec_dir)))
    # Mount the Python standard library directory so the interpreter can import
    # core modules (e.g. encodings) inside the sandbox.
    import sysconfig
    stdlib = Path(sysconfig.get_paths()["stdlib"]).resolve()
    if stdlib.exists() and stdlib != prefix and stdlib != exec_dir:
        command.extend(("--ro-bind", str(stdlib), str(stdlib)))
    if runner_script.is_file():
        command.extend(("--ro-bind", str(runner_script), "/workspace/scripts/research_session.py"))
    stage_target = f"/work/{stage_relative}"
    command.extend(("--ro-bind", str(snapshot), "/work", "--bind", str(stage),
                    stage_target, "--ro-bind", str(request), "/worker-request.json",
                    "--setenv", "PYTHONPATH", "/workspace:" + os.pathsep.join(
                        str(path) for path in prefix.glob("lib/python*/site-packages")),
                    "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
                    "--setenv", "POLARS_MAX_THREADS", "4",
                    "--setenv", "OPENBLAS_NUM_THREADS", "1",
                    "--setenv", "HOME", "/tmp", "--setenv", "XDG_CONFIG_HOME", "/tmp",
                    "--setenv", "MPLCONFIGDIR", "/tmp", "--chdir", "/work",
                    str(executable), "-B", "-m", "src.research_control.action_worker",
                    "/worker-request.json", stage_relative))
    return command


def _kill_worker_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, 9)
    except ProcessLookupError:
        pass


def observe_run(root: str | Path, session_id: str, attempt_id: str) -> dict[str, Any]:
    """Rebuild action state from append-only attempt records and output files."""
    ledger = AttemptLedger(root, session_id)
    events = [event for event in ledger.events() if event["attempt_id"] == attempt_id]
    if not events:
        return {"state": "UNKNOWN", "freshness": "NO_DURABLE_RECORD"}
    latest = events[-1]
    action = latest.get("metadata", {}).get("ats2_action")
    output = None
    current_identity = "UNKNOWN"
    if action:
        try:
            _, frozen = _load(Path(root).resolve(), session_id)
            hashes = _identity_hashes(Path(root).resolve(), frozen)
            if isinstance(hashes, GateReport):
                current_identity = "DRIFTED"
            else:
                data_hash, frozen_source_hash, config_hash, current_source_hash = hashes
                code_hash = hashlib.sha256(json.dumps(
                    {"frozen_source_sha256": frozen_source_hash,
                     "current_source_sha256": current_source_hash,
                     "runner": frozen["identity"].get("runner", [])},
                    sort_keys=True, separators=(",", ":"), allow_nan=False
                ).encode()).hexdigest()
                bound = action["identity"]
                current_identity = "CURRENT" if (
                    bound["frozen_session_sha256"] == frozen["frozen_sha256"] and
                    bound["spec_sha256"] == frozen["spec_sha256"] and
                    bound["data_sha256"] == data_hash and
                    bound["config_sha256"] == config_hash and
                    bound["code_sha256"] == code_hash
                ) else "DRIFTED"
        except (OSError, ValueError, KeyError, TypeError):
            current_identity = "UNKNOWN"
        try:
            output_path = beneath(Path(root).resolve(),
                                  f"{action['write_scope']}/{attempt_id}", must_exist=True)
            if output_path.is_dir() and not output_path.is_symlink():
                output = sorted(
                    str(path.relative_to(Path(root).resolve()))
                    for path in output_path.rglob("*")
                    if path.is_file() and not path.is_symlink()
                )
        except (OSError, ValueError):
            output = None
    owner: dict[str, Any] | None = None
    lock_path = ledger.worker_lock_path(attempt_id)
    try:
        if lock_path.is_file() and not lock_path.is_symlink():
            owner_record = json.loads(lock_path.read_text())
            pid = owner_record.get("pid")
            if isinstance(pid, int):
                from .job_inspector import _process_identity
                owner = _process_identity(pid)
                if owner.get("start_ticks") != int(owner_record.get("start_ticks", -1)):
                    owner = {**owner, "identity_match": False}
                else:
                    owner = {**owner, "identity_match": True,
                             "attempt_id": owner_record.get("attempt_id"),
                             "uid_matches": owner_record.get("uid") == os.getuid()}
    except (OSError, ValueError, TypeError):
        owner = None
    checkpoint_ok = ledger._verified_checkpoint(latest) if latest.get("checkpoint_path") else False
    completion = "NOT_VERIFIED"
    if latest["status"] == "COMPLETED" and output:
        if current_identity == "CURRENT" and checkpoint_ok:
            completion = "OUTPUT_READY"
        else:
            completion = "OUTPUT_STALE_OR_UNCERTAIN"
    return {"state": latest["status"], "freshness": "OBSERVED_NOW",
            "observed_at": datetime.now(UTC).isoformat(), "attempt_id": attempt_id,
            "revision": latest["revision"], "fencing_token": latest.get("fencing_token"),
            "worker_status": ledger.worker_lock_status(attempt_id),
            "worker_owner": owner, "identity_freshness": current_identity,
            "checkpoint": "VERIFIED" if checkpoint_ok else "MISSING_OR_INVALID",
            "outputs": output or [],
            "completion": completion,
            "authority": "ATTEMPT_LEDGER_AND_FILESYSTEM"}


def verify_result(root: str | Path, session_id: str, attempt_id: str) -> dict[str, Any]:
    """Independently reconcile saved native artifacts against raw bars + action.

    Reads actual saved native Parquet files (fills, trades, equity, portfolio
    state, daily PnL, metrics) and validates them against the original input
    bars and action parameters. Does not trust the worker manifest status,
    audit evidence hash, or checkpoint checksums for numerical correctness.
    """
    ledger = AttemptLedger(root, session_id)
    current = ledger.latest().get(attempt_id)
    if current is None or current["status"] != "COMPLETED":
        raise ValueError("OUTPUT_NOT_READY")
    meta = current.get("metadata", {})
    action_raw = meta.get("ats2_action")
    if not action_raw or meta.get("action_hash") != _hash(action_raw):
        raise ValueError("ACTION_CONTRACT_INVALID")
    action = _contract(action_raw)
    if not ledger._verified_checkpoint(current):
        raise ValueError("OUTPUT_CHECKPOINT_INVALID")
    root_path = Path(root).resolve()
    base = beneath(root_path, f"{action.write_scope}/{attempt_id}", must_exist=True)
    if base.is_symlink() or not base.is_dir():
        raise ValueError("OUTPUT_MISSING_OR_UNSAFE")
    manifest_path = base / "execution_audit.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("OUTPUT_MANIFEST_MISSING")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    native = base / "native"
    if (not native.is_dir() or native.is_symlink() or
        manifest.get("live_order_authority") is not False or
        manifest.get("permit_sha256") != action.permit_sha256):
        raise ValueError("OUTPUT_AUTHORITY_OR_NATIVE_DATA_INVALID")
    _, frozen = _load(root_path, session_id)
    config_path = frozen.get("identity", {}).get("config", {}).get("path")
    if not config_path:
        raise ValueError("VERIFICATION_CONFIG_MISSING")
    ResearchContractV1.model_validate(
        yaml.safe_load(beneath(root_path, config_path, must_exist=True).read_text())
    )
    data_paths = [item["path"] for item in frozen["spec"]["data"] if item["role"] == "prices"]
    if not data_paths:
        raise ValueError("FROZEN_DEVELOPMENT_DATA_MISSING")
    bars = pl.concat([pl.read_parquet(beneath(root_path, item, must_exist=True))
                      for item in data_paths], how="vertical")
    contract_doc = yaml.safe_load(beneath(root_path, config_path, must_exist=True).read_text())
    # Independent raw numerical audit: interpret actual saved native artifacts
    # against original bars and action parameters. Does not trust the manifest.
    audit = audit_native_outputs(root_path, native, bars, action, contract_doc)
    evidence = {str(path.relative_to(base)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(base.rglob("*")) if path.is_file() and not path.is_symlink()}
    if not evidence:
        raise ValueError("NUMERICAL_AUDIT_FAILED")
    attestation = {"schema_version": 1,
                   "verifier": "src.research_control.ats2.verify_result",
                   "method": "independent_raw_native_artifact_audit_against_bars_and_action",
                   "subject_attempt_id": attempt_id,
                   "action_contract_sha256": action.contract_sha256,
                   "audit_reason": audit["expected"],
                   "assertions": ["AttemptLedger COMPLETED", "permit identity bound",
                                  "native output exists", "live_order_authority=false",
                                  "saved fills match expected bracket fills from raw bars",
                                  "saved trades match expected trade identity and PnL",
                                  "saved portfolio/equity match bar-by-bar cash and mark",
                                  "saved metrics and daily PnL match expected ending values"],
                   "tolerances": f"absolute {TOL}, price 1e-8",
                   "source_identity": action.identity,
                   "output_hashes": evidence,
                   "input_hashes": audit["input_hashes"],
                   "limitations": ["Synthetic/development-only qualification",
                                   "Cooperative filesystem owner can alter local evidence",
                                   "Numerical audit interprets saved native artifacts directly",
                                   "Does not replay the native engine or trust its manifest"],
                   "verified_at": datetime.now(UTC).isoformat()}
    relative = f"run_log/ats2/accepted/{session_id}/{current['run_id']}/verification.json"
    accepted_path = beneath(root_path, relative)
    if accepted_path.exists() or accepted_path.is_symlink():
        if accepted_path.is_symlink() or not accepted_path.is_file():
            raise ValueError("ACCEPTED_VERIFICATION_UNSAFE")
        existing = json.loads(accepted_path.read_text(encoding="utf-8"))
        for field in ("subject_attempt_id", "action_contract_sha256",
                      "output_hashes", "input_hashes"):
            if existing.get(field) != attestation[field]:
                raise ValueError("ACCEPTED_VERIFICATION_CONFLICT")
        return {"state": "VERIFIED", "attestation": relative,
                "sha256": hashlib.sha256(accepted_path.read_bytes()).hexdigest(), **existing}
    publication = ledger.publish_fenced(
        attempt_id, int(current.get("fencing_token") or 0),
        relative_path=relative, payload=json_bytes(attestation),
    )
    return {"state": "VERIFIED", "attestation": relative,
            "sha256": publication["sha256"], **attestation}
