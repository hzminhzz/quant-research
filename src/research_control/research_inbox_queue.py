"""Fail-closed, append-only development research inbox queue.

This is an admission/coordination layer. ATS factory owns the science, native
execution, canonical data, trial ledger and Casefiles. No broker or holdout API
is reachable from this module.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import yaml

from src.engine.common import (
    QuantError,
    digest,
    file_hash,
    json_bytes,
    runtime_identity,
)
from src.engine.research_handoff import validate_handoff
from src.engine.spec_parser import parse_spec
from src.engine.thesis_ingest import convert_thesis
from src.oracle.research_protocols import parse_research_spec

REPO = Path(__file__).resolve().parents[2]
TERMINAL = frozenset({
    "DUPLICATE", "BLOCKED_HANDOFF", "BLOCKED_SPEC", "BLOCKED_PROTOCOL",
    "BLOCKED_DATA", "BLOCKED_EVIDENCE", "BLOCKED_SECURITY", "BLOCKED_DRIFT",
    "BLOCKED_RECOVERY", "ENGINEERING_ERROR", "FALSIFIED", "INCONCLUSIVE",
    "DEVELOPMENT_QUALIFIED",
})
TRIAL_TERMINAL = frozenset({"FALSIFIED", "INCONCLUSIVE", "DEVELOPMENT_QUALIFIED"})
UNSUPPORTED_EVENT = (
    "General single-instrument event execution is not a qualified ATS-4 factory "
    "protocol. Add and qualify a typed event spec, session/DST clock, causal next-fill "
    "orders, instrument/cost model and independent native fill/cash oracle. "
    "The frozen M8 N8 implementation cannot be repurposed for this rule."
)
UNSUPPORTED_PATH = (
    "General path-dependent execution is not a qualified ATS-4 factory protocol. "
    "Qualify a typed state/stop/exit adapter on the native ML4T Engine, including "
    "gap/intrabar precedence, realistic costs, causal timing and independent "
    "state/fill/cash reconciliation. Do not substitute a vector backtest."
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sha(path: Path) -> str:
    return file_hash(path)


def _source_hash(directory: Path) -> str:
    return digest({
        name: _sha(directory / name)
        for name in ("thesis.yaml", "brief.md")
    })


def _clean_keys(val: object) -> object:
    if isinstance(val, dict):
        return {str(k) if k is not None else "null": _clean_keys(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_clean_keys(v) for v in val]
    return val


def _semantic_id(doc: dict) -> str:
    """Deduplicate the frozen *experiment*, not its citation list or filename.

    Different development windows, data, gates, clocks or cost models are
    separate trials even when a paper and entry formula are identical.
    Multiple source references to the same experiment are not extra trials;
    every candidate still retains its own provenance in the admission journal.
    """
    return digest({
        key: _clean_keys(doc.get(key)) for key in (
            "economic_thesis", "mechanism", "instruments", "market",
            "data_requirements", "feature_contracts", "strategy_rules",
            "entry_and_basket_construction_rules", "signal_and_execution_clock",
            "bar_seconds", "sizing", "cost_assumptions", "baseline", "signal",
            "development_evaluation", "primary_falsifier",
            "acceptance_and_stop_rules", "parity_and_causality_tests",
            "known_adaptations", "assumptions", "unresolved_blockers",
        )
    })


def _path_rule(rule: dict) -> bool:
    """Only explicit active contingent exit/stop rules establish path dependence."""
    inactive = {None, "", "none", "no", "disabled", "not_applicable", "false"}
    for key in ("stop", "stop_loss", "trailing_stop", "take_profit", "profit_target",
                "trailing_exit", "intrabar_barrier", "dynamic_stop"):
        if key in rule:
            val = rule[key]
            if isinstance(val, dict) and (val.get("enabled") is False or val.get("active") is False):
                continue
            if isinstance(val, str) and val.lower().strip() in inactive:
                continue
            if val not in (None, False):
                return True
    for key, value in rule.items():
        if key in {"original", "author_source_rule_fidelity", "source_rules",
                   "source_exact_rules", "source_testing", "source_selection_bias",
                   "source_metadata", "ORIGINAL_AUTHOR_RULES", "SOURCE_TEST_EVIDENCE"}:
            continue  # original paper rules are not necessarily proposed execution
        if isinstance(value, dict) and _path_rule(value):
            return True
    return False


def classify(doc: dict) -> str:
    """Conservative structural classification, never a permission to execute."""
    rule = doc.get("strategy_rules")
    if isinstance(rule, dict) and _path_rule(rule):
        return "path_dependent"
    basket = doc.get("entry_and_basket_construction_rules")
    event_keys = {"entry", "exit", "entry_order", "exit_conditions", "position_state",
                  "entry_conditions_all", "states", "reentry", "forced_exit_if_unavailable"}
    if (isinstance(basket, dict)
            and isinstance(basket.get("universe"), dict)
            and isinstance(basket.get("allocation"), dict)
            and doc.get("signal") is not None
            and not (isinstance(rule, dict) and event_keys.intersection(rule))):
        return "cross_sectional"
    return "single_instrument_event"


def _declared_blockers(doc: dict) -> list[str]:
    """Quote source-authoritative blockers; never infer market facts from a title."""
    declared = doc.get("unresolved_blockers") or []
    if isinstance(declared, dict):
        declared = [declared]
    if not isinstance(declared, list):
        return [str(declared)]
    return [str(item.get("question") or item.get("id") or item)
            if isinstance(item, dict) else str(item) for item in declared]


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json_bytes(document)
    fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
        _fsync_dir(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _exclusive_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json_bytes(document)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(payload)
        out.flush()
        os.fsync(out.fileno())
    _fsync_dir(path.parent)


class InboxQueue:
    """Single integration owner; verified terminal work is never executed twice."""

    def __init__(self, inbox: str | Path = REPO / "research_inbox",
                 run_log: str | Path = REPO / "run_log",
                 vault_root: str | Path | None = None,
                 store: str | Path | None = None):
        self.inbox = Path(inbox).resolve()
        self.run_log = Path(run_log).resolve()
        self.root = self.run_log / "inbox_factory"
        self.vault_root = Path(vault_root).resolve() if vault_root else (REPO / "data" / "vault" / "markets_20261015")
        self.store = Path(store).resolve() if store else Path("/home/quant/dev/quant/ml4t-data/.data/store")
    def _folder(self, candidate_id: str) -> Path:
        if not isinstance(candidate_id, str) or not candidate_id:
            raise ValueError("candidate_id must be a nonempty string")
        # Malformed inbox names are evidence to reject, not a reason to abort
        # the entire batch or allow a directory traversal in the state store.
        if (not candidate_id.isascii()
                or not all(c.islower() or c.isdigit() or c == "_" for c in candidate_id)):
            key = "invalid_" + hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()[:24]
        else:
            key = candidate_id
        return self.root / "candidates" / key

    def _load(self, candidate_id: str) -> dict | None:
        folder = self._folder(candidate_id)
        events = sorted((folder / "events").glob("*.json"))
        if not events:
            if (folder / "state.json").exists():
                raise ValueError("state exists without durable journal")
            return None
        preceding = "0" * 64
        current = None
        for i, file in enumerate(events, 1):
            record = json.loads(file.read_text(encoding="utf-8"))
            stored = record.pop("record_hash", None)
            if (file.name != f"{i:06d}.json" or record.get("sequence") != i
                    or record.get("previous_hash") != preceding or digest(record) != stored):
                raise ValueError(f"broken append-only queue journal: {file}")
            preceding = stored
            current = record["state"]
            if not isinstance(current, dict) or current.get("candidate_id") != candidate_id:
                raise ValueError(f"queue state identity mismatch: {file}")
        # A crash between event fsync and projection rename is safe:
        # replay the journal, never trust the stale projection.
        return current

    def _save(self, state: dict) -> dict:
        folder = self._folder(state["candidate_id"])
        events = folder / "events"
        events.mkdir(parents=True, exist_ok=True)
        existing = sorted(events.glob("*.json"))
        seq = len(existing) + 1
        prev = "0" * 64
        if existing:
            record = json.loads(existing[-1].read_text(encoding="utf-8"))
            prev = record["record_hash"]
        fresh = {**state, "revision": seq, "updated_utc": _now()}
        event = {"sequence": seq, "previous_hash": prev, "state": fresh}
        event["record_hash"] = digest(event)
        _exclusive_json(events / f"{seq:06d}.json", event)
        _atomic_json(folder / "state.json", fresh)
        return fresh

    @contextmanager
    def _owner(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / ".owner.lock").open("a+") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("QUEUE_BUSY: another owner is active; do not start a second worker") from exc
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _candidates(self) -> list[Path]:
        if not self.inbox.is_dir():
            return []
        return sorted(path for path in self.inbox.iterdir()
                      if not path.name.startswith(".") and path.is_dir())

    def _auto_materialize_for_document(self, document: dict) -> list[str]:
        """Auto-materialize development vaults required by the candidate if missing."""
        import json
        from typing import cast

        from src.data_vault.market_materializer import (
            Granularity,
            MarketGroup,
            materialize_price_markets,
        )

        if not self.store.is_dir():
            return []
        text = json.dumps(document)
        targets: list[tuple[MarketGroup, Granularity]] = []
        if "index_minute_" in text or "index_1" in text:
            targets.extend([("index", "1h"), ("index", "1m")])
        if "forex_minute_" in text or "forex_1" in text:
            targets.extend([("forex", "1h"), ("forex", "1m")])
        if "metals_minute_" in text or "metals_1" in text:
            targets.extend([("metals", "1h"), ("metals", "1m")])
        materialized: list[str] = []
        for category, granularity in targets:
            vault_dir = self.vault_root / f"{category}_{granularity}"
            manifest_file = vault_dir / "manifest.json"
            if not manifest_file.is_file():
                try:
                    materialize_price_markets(
                        self.store, vault_dir,
                        category=cast(MarketGroup, category),
                        granularity=cast(Granularity, granularity),
                        start="2012-01-01T00:00:00Z", end="2025-01-01T00:00:00Z",
                        protected_test_start="2025-01-01T00:00:00Z",
                        trusted_partitioning=False,
                    )
                    materialized.append(f"{category}_{granularity}")
                except Exception:  # noqa: BLE001, S110
                    pass
            else:
                materialized.append(f"{category}_{granularity}")
        return sorted(set(materialized))

    def _auto_materialize_development(self, panel_root: Path) -> None:
        """Automatically compile development partitions from local store if available."""
        from typing import cast

        from src.data_vault.market_materializer import (
            Granularity,
            MarketGroup,
            materialize_price_markets,
        )

        name = panel_root.name
        if "_" not in name:
            return
        parts = name.split("_")
        category, granularity = parts[0], parts[1]
        if category not in ("index", "forex", "metals") or granularity not in ("1s", "1m", "1h", "1d"):
            return
        if not self.store.is_dir():
            return
        materialize_price_markets(
            self.store, panel_root,
            category=cast(MarketGroup, category),
            granularity=cast(Granularity, granularity),
            start="2012-01-01T00:00:00Z", end="2025-01-01T00:00:00Z",
            protected_test_start="2025-01-01T00:00:00Z",
            trusted_partitioning=False,
        )

    def _admit(self, directory: Path) -> tuple[dict, dict | None]:
        candidate_id = directory.name
        # The exact function used by quant.py validate-handoff.
        try:
            source_hash = _source_hash(directory)
            admitted = validate_handoff(directory)
            document = yaml.safe_load((directory / "thesis.yaml").read_text(encoding="utf-8"))
            if _source_hash(directory) != source_hash:
                raise QuantError('INVALID_HANDOFF', 'Source changed during admission; no trial registered')
            return {
                "candidate_id": candidate_id, "source_hash": source_hash,
                "semantic_id": _semantic_id(document), "source_references": document["source_references"],
                "handoff_status": admitted["status"], "protocol": classify(document),
                "source_path": str(directory), "admitted": True,
                "required_adaptations": _declared_blockers(document),
                "authority": "DEVELOPMENT_RESEARCH_ONLY",
            }, document
        except (QuantError, OSError, ValueError, yaml.YAMLError) as exc:
            return {"candidate_id": candidate_id, "admitted": False, "protocol": "unknown",
                    "source_path": str(directory), "status": "BLOCKED_HANDOFF",
                    "reason": str(exc), "holdout_access": False}, None

    def _preflight(self, info: dict, document: dict, directory: Path) -> tuple[dict, Path | None]:
        materialized = self._auto_materialize_for_document(document)
        if materialized:
            info = {**info, "materialized_development_vaults": materialized}

        protocol = info["protocol"]
        if protocol != "cross_sectional":
            return {**info, "status": "BLOCKED_PROTOCOL",
                    "reason": UNSUPPORTED_EVENT if protocol == "single_instrument_event" else UNSUPPORTED_PATH,
                    "holdout_access": False}, None

        if info.get("required_adaptations"):
            return {**info, "status": "BLOCKED_SPEC",
                    "reason": "Source declares unresolved prerequisites; resolve and revalidate before freezing",
                    "holdout_access": False}, None

        # Reject absent economic requirements instead of allowing CandidateSpec
        # defaults to invent fees, baseline, sizing, decision time or trial gates.
        required = ("entry_and_basket_construction_rules", "signal", "baseline",
                    "cost_assumptions", "data_requirements", "development_evaluation",
                    "primary_falsifier", "acceptance_and_stop_rules")
        absent = [name for name in required if not document.get(name)]
        if absent:
            return {**info, "status": "BLOCKED_SPEC",
                    "reason": "Cross-sectional contract lacks explicit: " + ", ".join(absent),
                    "holdout_access": False}, None
        target = self._folder(info["candidate_id"]) / "frozen_candidate.yaml"
        try:
            if target.exists():
                # Frozen output may only be reused when it matches the
                # source-bound hash recorded in existing queue state.
                previous = self._load(info["candidate_id"])
                if not previous or previous.get("source_hash") != info["source_hash"]:
                    raise ValueError("Existing frozen candidate has no matching source identity")
                spec = parse_spec(target)
            else:
                spec = convert_thesis(directory / "thesis.yaml", target)
            prior = self._load(info["candidate_id"])
            if prior and prior.get("spec_hash") and prior["spec_hash"] != spec.spec_hash:
                raise ValueError("Saved frozen candidate spec hash changed across attempts")
            if _source_hash(directory) != info["source_hash"]:
                raise ValueError("Source changed during frozen specification conversion")
            if spec.python_feature_artifact is not None:
                raise ValueError("Serialized Python feature artifact needs a verified immutable relocation; not admitted by this thin queue")
            if spec.candidate_id != info["candidate_id"] or spec.source_spec_status != "exact":
                raise ValueError("Executable specification identity is not an exact current source")
            if parse_spec(target).spec_hash != spec.spec_hash:
                raise ValueError("Frozen spec changed on reload")
            details = {
                "spec_hash": spec.spec_hash, "spec_path": str(target),
                "spec_file_sha256": _sha(target),
                "development_window": {
                    "train": spec.windows.train.model_dump(mode="json"),
                    "validation": spec.windows.validation.model_dump(mode="json"),
                },
                "protected_start_metadata_only": spec.windows.protected.start.isoformat(),
                "trial_budget": 1, "causal_timing_lag": spec.allocation.timing_lag,
                "costs": spec.costs.model_dump(mode="json"),
                "baseline_feature": spec.baseline, "falsifier": document["primary_falsifier"],
            }
            return {**info, **details, "status": "EXECUTABLE",
                    "holdout_access": False}, target
        except (QuantError, OSError, ValueError, TypeError) as exc:
            return {**info, "status": "BLOCKED_SPEC", "reason": str(exc),
                    "holdout_access": False}, None

    def _native_verify(self, path: Path, expected: dict) -> dict:
        """Independent identity/receipt/ledger checks, not independent financial proof."""
        case = json.loads(path.read_text(encoding="utf-8"))
        if (case.get("candidate_id") != expected["candidate_id"]
                or case.get("spec_hash") != expected["spec_hash"]):
            raise ValueError("Native Casefile candidate/spec identity differs")
        if (expected.get("frozen_code_sha256") is not None
                and case.get("code_hash") != expected["frozen_code_sha256"]):
            raise ValueError("Native Casefile runtime code differs from frozen identity")
        if case.get("development_only") is not True:
            raise ValueError("Native Casefile lacks the mandatory development-only flag")
        if (case.get("holdout_access") is not False or case.get("holdout_claim") is not None
                or "4" in case.get("stages", {})):
            raise ValueError("Native Casefile reports forbidden protected access")
        if (not case.get("status", "").startswith("BLOCKED_")
                and case.get("stages", {}).get("1", {}).get("status") != "PASS"):
            raise ValueError("Native causal Stage 1 proof is absent")
        for stage in ("1", "2", "3"):
            if stage not in case.get("stages", {}):
                continue
            output = path.parent
            receipt = json.loads((output / f"stage{stage}.json").read_text(encoding="utf-8"))
            claimed_hash = receipt.pop("receipt_hash", "")
            if digest(receipt) != claimed_hash or receipt.get("spec_hash") != expected["spec_hash"]:
                raise ValueError(f"Stage {stage} receipt identity/digest differs")
            for artifact, fingerprint in receipt["artifacts"].items():
                part = (output / artifact).resolve()
                if not part.is_relative_to(output.resolve()) or _sha(part) != fingerprint:
                    raise ValueError(f"Stage {stage} artifact drift: {artifact}")
        if "3" in case.get("stages", {}):
            for split in case["stages"]["3"].get("splits", {}).values():
                for arm in ("candidate", "baseline"):
                    metrics = split.get(arm)
                    if metrics is not None and metrics.get("independent_accounting", {}).get("status") != "PASS":
                        raise ValueError("Independent native cash/equity accounting did not pass")
        ledger = self.run_log / "trial_ledger.jsonl"
        found = False
        previous_hash = "0" * 64
        for line in ledger.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            received_hash = record.pop("record_hash", None)
            if record.get("previous_hash") != previous_hash or digest(record) != received_hash:
                raise ValueError("ATS trial ledger hash chain is broken")
            previous_hash = received_hash
            if (record.get("event") == "completed"
                    and record.get("attempt_id") == case["attempt_id"]
                    and record.get("spec_hash") == expected["spec_hash"]
                    and record.get("casefile", {}).get("sha256") == _sha(path)
                    and record.get("holdout_access") is False):
                found = True
        if not found:
            raise ValueError("Native ATS terminal trial/Casefile evidence is absent")
        return case

    def _execute(self, state: dict, spec_file: Path, seconds: int) -> dict:
        candidate_id = state["candidate_id"]
        attempt = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
        folder = self._folder(candidate_id) / "attempts" / attempt
        folder.mkdir(parents=True, exist_ok=False)
        out = folder / "stdout.log"
        err = folder / "stderr.log"
        state = self._save({**state, "status": "RUNNING", "attempt_id": attempt,
                            "attempts": [*state.get("attempts", []), attempt],
                            "stdout": str(out), "stderr": str(err),
                            "started_utc": _now(), "holdout_access": False})
        if (runtime_identity() != state["frozen_code_sha256"]
                or _sha(spec_file) != state["spec_file_sha256"]
                or _source_hash(Path(state["source_path"])) != state["source_hash"]
                or _sha(Path(state["data_manifest_path"])) != state["data_manifest_sha256"]):
            return self._save({**state, "status": "BLOCKED_DRIFT",
                               "reason": "Code or canonical data manifest changed before native execution"})
        argv = [sys.executable, "-B", str(REPO / "scripts" / "quant.py"),
                "run", str(spec_file), "--development-only",
                "--run-log", str(self.run_log)]
        env = {**os.environ, "PYTHONPATH": str(REPO), "PYTHONDONTWRITEBYTECODE": "1"}
        try:
            with out.open("x", encoding="utf-8") as output, err.open("x", encoding="utf-8") as errors:
                result = subprocess.run(argv, cwd=REPO, env=env, stdin=subprocess.DEVNULL,
                                        stdout=output, stderr=errors, timeout=seconds, check=False)
            outputs = out.read_text(encoding="utf-8").splitlines()
            report = json.loads(outputs[-1]) if outputs else {}
            casefile = Path(report["casefile"]).resolve()
            if not casefile.is_relative_to(self.run_log):
                raise ValueError("Native Casefile is outside the declared run-log root")
            if (runtime_identity() != state["frozen_code_sha256"]
                    or _sha(spec_file) != state["spec_file_sha256"]
                    or _source_hash(Path(state["source_path"])) != state["source_hash"]
                    or _sha(Path(state["data_manifest_path"])) != state["data_manifest_sha256"]):
                raise ValueError("Code or source manifest changed during native execution")
            case = self._native_verify(casefile, state)
            if report.get("holdout_access") is not False or report.get("status") != case["status"]:
                raise ValueError("Native CLI and saved Casefile disagree")
            if result.returncode not in {0, 3}:
                raise ValueError(f"Native process exit {result.returncode} inconsistent with terminal evidence")
            raw = case["status"]
            if raw.startswith("FALSIFIED_"):
                disposition = "FALSIFIED"
            elif raw == "DEVELOPMENT_QUALIFIED":
                disposition = "DEVELOPMENT_QUALIFIED"
            elif raw.startswith(("INCONCLUSIVE", "PARTIALLY_")):
                disposition = "INCONCLUSIVE"
            elif raw.startswith("BLOCKED"):
                disposition = "BLOCKED_DATA"
            else:
                raise ValueError(f"Unsupported native research decision: {raw}")
            return self._save({**state, "status": disposition,
                               "native_status": raw, "casefile": str(casefile),
                               "casefile_sha256": _sha(casefile), "returncode": result.returncode,
                               "native_evidence_verified": True,
                               "independently_verified": False,
                               "reason": case.get("reason", "Native development decision recorded"),
                               "holdout_access": False})
        except subprocess.TimeoutExpired:
            return self._save({**state, "status": "BLOCKED_RECOVERY",
                               "reason": "Native timeout; child side effects and partial ATS attempts require manual reconciliation",
                               "holdout_access": False})
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            # Never turn a broken engineering run into an economic falsification.
            return self._save({**state, "status": "BLOCKED_EVIDENCE",
                               "reason": f"Native evidence or invocation not verified: {exc}",
                               "holdout_access": False})

    def run(self, *, max_runtime_seconds: int = 3600, max_candidates: int | None = None) -> dict:
        if max_runtime_seconds < 1:
            raise ValueError("max_runtime_seconds must be positive")
        processed = 0
        with self._owner():
            seen = {}
            for candidate in self._candidates():
                if max_candidates is not None and processed >= max_candidates:
                    break
                info, doc = self._admit(candidate)
                name = info["candidate_id"]
                try:
                    previous = self._load(name)
                except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                    raise RuntimeError(f"BROKEN_EVIDENCE {name}: {exc}") from exc
                if doc is not None:
                    semantic = info["semantic_id"]
                    # Dedup across all entries, even previously terminal entries.
                    duplicate_of = seen.setdefault(semantic, name)
                else:
                    duplicate_of = name
                if previous:
                    if (info.get("source_hash") and
                            info["source_hash"] != previous.get("source_hash")):
                        if previous["status"] != "BLOCKED_DRIFT":
                            self._save({**previous, "status": "BLOCKED_DRIFT",
                                        "reason": "Source bytes changed after admission; prior trial untouched",
                                        "prior_status": previous["status"]})
                        processed += 1
                        continue
                    if (doc is not None and "required_adaptations" not in previous):
                        previous = self._save({**previous,
                                               "required_adaptations": info["required_adaptations"]})
                    if previous["status"] == "RUNNING":
                        self._save({**previous, "status": "BLOCKED_RECOVERY",
                                    "reason": "Interrupted native trial; reconcile ATS ledger, Casefile and worker before replay"})
                        processed += 1
                        continue
                    if previous["status"] in TERMINAL:
                        if previous["status"] in TRIAL_TERMINAL:
                            try:
                                source = Path(previous["casefile"])
                                if _sha(source) != previous["casefile_sha256"]:
                                    raise ValueError("Casefile bytes changed after terminal verification")
                                self._native_verify(source, previous)
                            except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                                self._save({**previous, "status": "BLOCKED_EVIDENCE",
                                            "prior_status": previous["status"],
                                            "reason": f"Saved terminal evidence drift: {exc}"})
                        elif doc is not None and previous["status"] in {"BLOCKED_PROTOCOL", "BLOCKED_SPEC", "BLOCKED_DATA"}:
                            materialized = self._auto_materialize_for_document(doc)
                            if materialized and "materialized_development_vaults" not in previous:
                                self._save({**previous, "materialized_development_vaults": materialized})
                        continue  # terminal items do not consume the bounded actionable quota
                else:
                    previous = self._save({**info, "status": "ADMITTED" if doc else "BLOCKED_HANDOFF",
                                           "attempts": [], "holdout_access": False})
                if doc is None:
                    processed += 1
                    continue
                if duplicate_of != name:
                    self._save({**previous, "status": "DUPLICATE", "duplicate_of": duplicate_of,
                                "reason": "Identical source/logic/instrument/clock/cost identity; no second trial"})
                    processed += 1
                    continue
                ready, spec_path = self._preflight(info, doc, candidate)
                next_state = self._save({**previous, **ready, "attempts": previous.get("attempts", [])})
                if spec_path is None:
                    processed += 1
                    continue
                spec = parse_research_spec(spec_path)
                panel_root = Path(getattr(spec, "panel_root", REPO / "data/vault/markets_20261015/index_1h"))
                manifest = panel_root / "manifest.json"
                if not manifest.is_file():
                    try:
                        self._auto_materialize_development(panel_root)
                    except Exception as exc:  # noqa: BLE001
                        self._save({**next_state, "status": "BLOCKED_DATA",
                                    "reason": f"Auto-materialization failed: {exc}"})
                        processed += 1
                        continue
                if not manifest.is_file():
                    self._save({**next_state, "status": "BLOCKED_DATA",
                                "reason": "Frozen canonical panel manifest missing; do not download or substitute prices"})
                    processed += 1
                    continue
                next_state = self._save({**next_state, "data_manifest_path": str(manifest),
                                         "data_manifest_sha256": _sha(manifest),
                                         "frozen_code_sha256": runtime_identity()})
                self._execute(next_state, spec_path, max_runtime_seconds)
                processed += 1
        return self.report()

    def report(self) -> dict:
        cases = []
        counts = {
            "total": 0, "admitted": 0, "executable": 0, "falsified": 0,
            "inconclusive": 0, "blocked": 0, "independently_verified": 0,
            "duplicates": 0, "pending": 0,
        }
        for folder in self._candidates():
            try:
                state = self._load(folder.name)
            except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
                state = {"candidate_id": folder.name, "status": "BROKEN_EVIDENCE", "reason": str(exc)}
            if state is None:
                state = {"candidate_id": folder.name, "status": "PENDING"}
            status = state["status"]
            counts["total"] += 1
            counts["admitted"] += int(bool(state.get("admitted")))
            counts["executable"] += int(bool(state.get("spec_hash")))
            counts["falsified"] += int(status == "FALSIFIED")
            counts["inconclusive"] += int(status == "INCONCLUSIVE")
            counts["blocked"] += int(status.startswith("BLOCKED") or status in {"BROKEN_EVIDENCE", "ENGINEERING_ERROR"})
            counts["independently_verified"] += int(state.get("independently_verified") is True)
            counts["duplicates"] += int(status == "DUPLICATE")
            counts["pending"] += int(status == "PENDING")
            cases.append({
                key: state.get(key) for key in (
                    "candidate_id", "status", "protocol", "reason", "attempt_id",
                    "casefile", "source_hash", "spec_hash", "duplicate_of", "revision",
                    "native_evidence_verified", "independently_verified",
                    "required_adaptations",
                ) if key in state
            })
        return {
            "schema_version": 1, "scope": "DEVELOPMENT_ONLY_NO_PROTECTED_NO_ORDERS",
            "inbox": str(self.inbox), "state_root": str(self.root),
            "counts": counts, "cases": cases,
        }
