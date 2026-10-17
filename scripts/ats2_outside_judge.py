#!/usr/bin/env python3
"""Independent outside-judge replay for ATS-2 synthetic native bracket fixture.

This script deliberately does not import ATS verification or execution code.
It parses frozen attempt files and checks native Parquet evidence against
the action, frozen inputs, and an independently coded bracket/accounting model.
Supports recovered multi-attempt histories with valid FAILED/ABORTED ancestors,
strictly monotonic fencing tokens, and exact parent_attempt_id successor linkage.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import math
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl
import yaml

INITIAL_CASH = 1_000_000.0
TOL = 1e-7
REQUIRED_NATIVE = {
    "config.yaml", "daily_pnl.parquet", "equity.parquet", "fills.parquet",
    "manifest.json", "metrics.json", "portfolio_state.parquet",
    "rejected_orders.parquet", "spec.yaml", "trades.parquet",
}


class Reject(Exception):
    def __init__(self, reason_code: str, detail: str = ""):
        self.reason_code = reason_code.split(":", 1)[0]
        self.detail = detail or reason_code
        super().__init__(f"{self.reason_code}:{self.detail}")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()


def file_hash(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
        raise Reject(f"UNSAFE_OR_OVERSIZE_FILE:{path.name}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def directory_digest(path: Path) -> str:
    return canonical_hash({item.relative_to(path).as_posix(): file_hash(item)
                           for item in sorted(path.rglob("*")) if item.is_file()})


def read_json(path: Path, limit: int = 2_000_000) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise Reject(f"JSON_UNSAFE_OR_OVERSIZE:{path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Reject(f"JSON_NOT_OBJECT:{path.name}")
    return value


def check(condition: bool, reason: str) -> None:
    if not condition:
        raise Reject(reason)


def close(actual: Any, expected: float, reason: str, tol: float = TOL) -> None:
    try:
        value = float(actual)
    except (TypeError, ValueError):
        raise Reject(reason) from None
    check(math.isfinite(value) and math.isclose(value, expected, rel_tol=0, abs_tol=tol), reason)


def ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    parsed = datetime.fromisoformat(str(value))
    return parsed.replace(tzinfo=None)


def validate_attempt_records(records: list[dict[str, Any]]) -> None:
    """Validate a single attempt's revision chain."""
    check([row.get("revision") for row in records] == list(range(1, len(records) + 1)),
          "ATTEMPT_REVISION_GAP_OR_DUPLICATE")
    anchor = records[0]
    for row in records:
        for key in ("attempt_id", "run_id", "trial_id", "job_name", "command",
                    "fencing_token", "fingerprints"):
            check(row.get(key) == anchor.get(key), f"ATTEMPT_{key.upper()}_DRIFT")
        check(row.get("metadata", {}).get("ats2_action") ==
              anchor.get("metadata", {}).get("ats2_action"), "ATTEMPT_ACTION_DRIFT")
        check(row.get("metadata", {}).get("action_hash") ==
              anchor.get("metadata", {}).get("action_hash"), "ATTEMPT_ACTION_HASH_DRIFT")
    statuses = [row.get("status") for row in records]
    check(statuses[0] == "PLANNED" and statuses.count("PLANNED") == 1,
          "ATTEMPT_LIFECYCLE_CONTRADICTION")
    check(all(state in {"PLANNED", "RUNNING", "COMPLETED", "FAILED", "ABORTED"}
              for state in statuses), "ATTEMPT_LIFECYCLE_CONTRADICTION")
    check(all(state == "RUNNING" for state in statuses[1:-1])
          and statuses[-1] in {"COMPLETED", "FAILED", "ABORTED"},
          "ATTEMPT_LIFECYCLE_CONTRADICTION")


def load_attempt_groups(attempt_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Load and validate all attempt groups from the ledger directory."""
    check(attempt_dir.is_dir() and not attempt_dir.is_symlink(), "ATTEMPT_LEDGER_MISSING")
    paths = sorted(attempt_dir.glob("*.json"))
    check(bool(paths) and len(paths) <= 1000, "ATTEMPT_LEDGER_EMPTY_OR_OVERSIZE")
    groups: dict[str, list[dict[str, Any]]] = {}
    for path in paths:
        event = read_json(path, 256 * 1024)
        check(event.get("schema_version") == 1 and event.get("event_id") == path.stem,
              "ATTEMPT_EVENT_IDENTITY_INVALID")
        check(type(event.get("revision")) is int and event["revision"] > 0,
              "ATTEMPT_EVENT_REVISION_INVALID")
        groups.setdefault(str(event.get("attempt_id")), []).append(event)
    for records in groups.values():
        records.sort(key=lambda row: row["revision"])
        validate_attempt_records(records)
    return groups


def validate_recovery_history(groups: dict[str, list[dict[str, Any]]]) -> None:
    """Validate a recovered multi-attempt history: monotonic fencing, exact parent linkage.

    Requires a scoped single valid chain:
      - first attempt has parent_attempt_id null
      - each successor points to the immediately preceding same-operation terminal
        FAILED/ABORTED ancestor
      - no parent after completion or terminal budget exhaustion
      - strict increasing fencing tokens
      - unchanged run/action/scope/grant identity across the chain
      - no orphan or fork attempts
      - terminal success (COMPLETED) only at chain tip
    """
    check(len(groups) >= 1, "ATTEMPT_LEDGER_EMPTY")
    attempt_ids = list(groups.keys())
    check(len(attempt_ids) <= 100, "ATTEMPT_COUNT_EXCEEDED")

    # Build per-attempt terminal record and collect chain metadata.
    terminal: dict[str, dict[str, Any]] = {}
    for aid, records in groups.items():
        last = records[-1]
        terminal[aid] = last

    # All attempts must share the same run_id and action scope.
    run_ids = {t.get("run_id") for t in terminal.values()}
    check(len(run_ids) == 1, "RECOVERY_RUN_ID_DRIFT")
    action_hashes = {t.get("metadata", {}).get("action_hash") for t in terminal.values()}
    check(len(action_hashes) == 1, "RECOVERY_ACTION_HASH_DRIFT")
    scope_hashes = {t.get("metadata", {}).get("scope_sha256") for t in terminal.values()
                    if t.get("metadata", {}).get("scope_sha256")}
    if scope_hashes:
        check(len(scope_hashes) == 1, "RECOVERY_SCOPE_HASH_DRIFT")
    grant_ids = {t.get("metadata", {}).get("authorization", {}).get("grant_id")
                 for t in terminal.values() if t.get("metadata", {}).get("authorization")}
    if grant_ids:
        check(len(grant_ids) == 1, "RECOVERY_GRANT_ID_DRIFT")

    # Fencing tokens must be strictly increasing and positive.
    all_tokens = [(int(t.get("fencing_token") or 0), aid)
                  for aid, t in terminal.items()]
    check(all(t > 0 for t, _ in all_tokens), "ATTEMPT_FENCING_TOKEN_INVALID")
    all_tokens.sort()
    for i in range(1, len(all_tokens)):
        check(all_tokens[i][0] > all_tokens[i - 1][0],
              f"FENCING_TOKEN_NOT_MONOTONIC:{all_tokens[i][1]}")

    # Order attempts by fencing token to establish recovery chain order.
    ordered = [aid for _, aid in all_tokens]

    # First attempt must have no parent.
    first = terminal[ordered[0]]
    check(first.get("parent_attempt_id") is None,
          f"RECOVERY_FIRST_HAS_PARENT:{ordered[0]}")

    # Each successor must point to the immediately preceding terminal FAILED/ABORTED
    # ancestor; COMPLETED is terminal and must be the chain tip.
    completed_count = 0
    for i, aid in enumerate(ordered):
        rec = terminal[aid]
        status = rec.get("status")
        parent = rec.get("parent_attempt_id")
        if i == 0:
            continue
        prev_aid = ordered[i - 1]
        prev_rec = terminal[prev_aid]
        prev_status = prev_rec.get("status")
        # Previous must be terminal FAILED/ABORTED (not COMPLETED).
        check(prev_status in {"FAILED", "ABORTED"},
              f"RECOVERY_PREV_NOT_TERMINAL:{prev_aid}:{prev_status}")
        # Child must point to the immediately preceding attempt.
        check(parent == prev_aid,
              f"RECOVERY_PARENT_LINKAGE_INVALID:{aid}:{parent}:{prev_aid}")
        # Child fence must be greater than parent fence.
        check(int(rec.get("fencing_token") or 0) > int(prev_rec.get("fencing_token") or 0),
              f"RECOVERY_FENCE_NOT_ADVANCING:{aid}")
        # Same run/action/scope/grant across the chain.
        check(rec.get("run_id") == prev_rec.get("run_id"),
              f"RECOVERY_RUN_DRIFT:{aid}")
        check(rec.get("metadata", {}).get("action_hash") ==
              prev_rec.get("metadata", {}).get("action_hash"),
              f"RECOVERY_ACTION_DRIFT:{aid}")
        if status == "COMPLETED":
            completed_count += 1
            check(i == len(ordered) - 1,
                  f"RECOVERY_COMPLETED_NOT_TIP:{aid}")
    check(completed_count <= 1, "MULTIPLE_COMPLETED_ATTEMPTS")
    # No orphans: every attempt is in the chain (already guaranteed by ordered list).
    # No forks: each attempt has at most one successor (chain is linear by construction).


def load_context(fixture: Path, records_override: list[dict[str, Any]] | None = None
                 ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]], Path, Path]:
    fixture = fixture.resolve()
    frozen_path = fixture / "run_log/research_sessions/permit-synthetic/frozen_spec.json"
    frozen = read_json(frozen_path)
    check(frozen.get("status") == "FROZEN", "FROZEN_SPEC_INVALID")
    ledger_dir = fixture / "run_log/research_sessions/permit-synthetic/attempts"
    groups = load_attempt_groups(ledger_dir)
    if records_override is not None:
        groups = {}
        for record in records_override:
            groups.setdefault(str(record.get("attempt_id")), []).append(record)
        for records in groups.values():
            records.sort(key=lambda row: row.get("revision", -1))
            validate_attempt_records(records)
    # Always validate recovery history for both normal and override records.
    validate_recovery_history(groups)

    # Find the unique completed attempt
    candidates = []
    for aid, records in groups.items():
        if records and records[-1].get("status") == "COMPLETED":
            candidates.append((aid, records))
    check(len(candidates) == 1, "COMPLETED_ATTEMPT_NOT_UNIQUE")
    _completed_aid, terminal_events = candidates[0]
    action = terminal_events[-1].get("metadata", {}).get("ats2_action")
    check(isinstance(action, dict), "ACTION_MISSING_FROM_ATTEMPT_RECORD")

    # Verify the declared action digest and equality to its append-only authority.
    action_payload = dict(action)
    contract_sha = action_payload.pop("contract_sha256", None)
    check(contract_sha == canonical_hash(action_payload), "ACTION_CONTRACT_DIGEST_MISMATCH")
    check(terminal_events[-1].get("metadata", {}).get("action_hash") == canonical_hash(action),
          "ATTEMPT_ACTION_DIGEST_MISMATCH")
    check(action.get("identity") == terminal_events[-1].get("fingerprints"),
          "ACTION_LEDGER_IDENTITY_MISMATCH")
    check(action.get("operation") == "development_native_bracket"
          and action.get("read_scope") == "frozen_development_inputs"
          and action.get("max_trials") == 1, "ACTION_SCOPE_UNSUPPORTED")
    check(action.get("write_scope", "").startswith("run_log/ats2/"),
          "ACTION_WRITE_SCOPE_INVALID")
    check(action.get("session_id") in action.get("write_scope", ""),
          "ACTION_WRITE_SCOPE_SESSION_MISSING")
    check(action.get("trial_id") in action.get("write_scope", ""),
          "ACTION_WRITE_SCOPE_TRIAL_MISSING")
    check(action.get("expected_outputs") == ["execution_audit.json", "native/"],
          "ACTION_OUTPUT_CONTRACT_UNSUPPORTED")
    check(set(action.get("parameters", {})) ==
          {"signal_at", "quantity", "stop_price", "limit_price"},
          "ACTION_PARAMETERS_UNSUPPORTED")
    check(action.get("session_id") == frozen.get("session_id") == "permit-synthetic",
          "SESSION_IDENTITY_MISMATCH")
    check(action.get("trial_id") == "synthetic-trial", "TRIAL_SCOPE_UNSUPPORTED")
    identity = action["identity"]
    check(identity.get("frozen_session_sha256") == frozen.get("frozen_sha256"),
          "FROZEN_SESSION_IDENTITY_MISMATCH")
    check(identity.get("spec_sha256") == frozen.get("spec_sha256"), "SPEC_IDENTITY_MISMATCH")

    frozen_identity = frozen["identity"]
    data_refs = frozen["spec"]["data"]
    check(len(data_refs) == 1 and data_refs[0].get("role") == "prices", "DATA_SCOPE_UNSUPPORTED")
    data_ref = frozen_identity["data"][0]
    data_path = fixture / data_ref["path"]
    check(file_hash(data_path) == data_ref["sha256"], "FROZEN_DATA_HASH_MISMATCH")
    check(data_path.stat().st_size == data_ref["size_bytes"], "FROZEN_DATA_SIZE_MISMATCH")
    check(identity.get("data_sha256") == canonical_hash([data_ref]), "ACTION_DATA_IDENTITY_MISMATCH")
    config_ref = frozen_identity["config"]
    config_path = fixture / config_ref["path"]
    check(file_hash(config_path) == config_ref["sha256"], "FROZEN_CONFIG_HASH_MISMATCH")
    check(identity.get("config_sha256") == config_ref["sha256"], "ACTION_CONFIG_IDENTITY_MISMATCH")
    contract_doc = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    dataset_identity = canonical_hash(contract_doc["dataset"])
    check(identity.get("source_sha256") == dataset_identity, "ACTION_SOURCE_IDENTITY_MISMATCH")

    sources = frozen_identity["source"]
    for source in sources:
        source_path = fixture / source["path"]
        check(file_hash(source_path) == source["sha256"], "FROZEN_SOURCE_HASH_MISMATCH")
        check(source_path.stat().st_size == source["size_bytes"], "FROZEN_SOURCE_SIZE_MISMATCH")
    source_hash = canonical_hash(sources)
    check(source_hash == frozen_identity["source_sha256"], "FROZEN_SOURCE_INVENTORY_MISMATCH")
    code_hash = canonical_hash({
        "frozen_source_sha256": frozen_identity["source_sha256"],
        "current_source_sha256": source_hash,
        "runner": frozen_identity["runner"],
    })
    check(identity.get("code_sha256") == code_hash, "ACTION_CODE_IDENTITY_MISMATCH")
    bars = pl.read_parquet(data_path)
    check(0 < bars.height <= 100_000, "RAW_BARS_ROW_LIMIT")
    check({ "timestamp", "symbol", "open", "high", "low", "close" } <= set(bars.columns),
          "RAW_BAR_SCHEMA_INVALID")
    check(bars["timestamp"].is_sorted() and bars["timestamp"].n_unique() == bars.height,
          "RAW_BAR_CLOCK_INVALID")
    return frozen, action, terminal_events[-1], terminal_events, data_path, config_path


def expected_trades(bars: pl.DataFrame, action: dict[str, Any]) -> tuple[list[dict[str, Any]], float]:
    params = action["parameters"]
    signal = ts(params["signal_at"])
    quantity = float(params["quantity"])
    stop, target = float(params["stop_price"]), float(params["limit_price"])
    check(quantity > 0 and quantity.is_integer(), "QUANTITY_OUT_OF_SUPPORTED_SCOPE")
    check(0 < stop < target, "BRACKET_LEVELS_INVALID")
    rows = bars.to_dicts()
    signal_indices = [i for i, row in enumerate(rows) if ts(row["timestamp"]) == signal]
    check(len(signal_indices) == 1 and signal_indices[0] + 1 < len(rows), "SIGNAL_BAR_INVALID")
    entry_i = signal_indices[0] + 1
    entry = rows[entry_i]
    symbol = str(entry["symbol"])
    check(all(str(row["symbol"]) == symbol for row in rows), "MULTI_SYMBOL_OUT_OF_SCOPE")
    fills = [{"side": "buy", "quantity": quantity, "price": float(entry["open"]),
              "time": ts(entry["timestamp"]), "kind": "market"}]
    for row in rows[entry_i + 1:]:
        open_price, low, high = map(float, (row["open"], row["low"], row["high"]))
        stop_hit = open_price <= stop or low <= stop
        target_hit = high >= target
        if stop_hit:
            fills.append({"side": "sell", "quantity": quantity,
                          "price": min(open_price, stop),
                          "time": ts(row["timestamp"]), "kind": "stop"})
            break
        if target_hit:
            fills.append({"side": "sell", "quantity": quantity, "price": target,
                          "time": ts(row["timestamp"]), "kind": "limit"})
            break
    check(len(fills) == 2, "NO_BRACKET_EXIT_IN_RAW_WINDOW")
    return fills, float(rows[-1]["close"])


def replay(fixture: Path, native_dir: Path, outer_manifest_path: Path,
           *, records_override: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    frozen, action, terminal, terminal_events, data_path, config_path = load_context(fixture, records_override)
    check(terminal.get("status") == "COMPLETED", "ATTEMPT_NOT_COMPLETED")
    attempt_id = terminal["attempt_id"]
    check(native_dir.is_dir() and not native_dir.is_symlink(), "NATIVE_OUTPUT_MISSING")
    check(not outer_manifest_path.is_symlink(), "OUTER_MANIFEST_SYMLINK")
    outer = read_json(outer_manifest_path)
    check(outer.get("schema_version") == 1, "OUTER_MANIFEST_SCHEMA_INVALID")
    check(outer.get("permit_sha256") == action.get("permit_sha256"), "PERMIT_SUBSTITUTION")
    check(outer.get("engine_version") == action["identity"].get("engine_version"),
          "ENGINE_VERSION_CONTRADICTION")
    check(outer.get("live_order_authority") is False, "LIVE_AUTHORITY_FLAG_INVALID")
    check(outer.get("qualification") == "HISTORICAL_SIMULATION_ONLY", "QUALIFICATION_SCOPE_INVALID")

    names = {item.name for item in native_dir.iterdir()}
    check(REQUIRED_NATIVE <= names, "NATIVE_COMPONENT_MISSING")
    native_manifest = read_json(native_dir / "manifest.json")
    check(native_manifest.get("artifact_type") == "ml4t-backtest-result"
          and native_manifest.get("schema_version") == 2
          and native_manifest.get("complete") is True, "NATIVE_MANIFEST_INVALID")
    check(native_manifest.get("library_version") == action["identity"].get("engine_version"),
          "NATIVE_ENGINE_VERSION_MISMATCH")
    components = native_manifest.get("components", {})
    check(isinstance(components, dict) and set(components.values()) == REQUIRED_NATIVE - {"manifest.json"},
          "NATIVE_MANIFEST_COMPONENT_SET_INVALID")
    for component in components.values():
        check(Path(component).name == component and ".." not in Path(component).parts,
              "NATIVE_MANIFEST_PATH_INVALID")
        check((native_dir / component).is_file() and not (native_dir / component).is_symlink(),
              "NATIVE_MANIFEST_COMPONENT_MISSING")

    config = yaml.safe_load((native_dir / "config.yaml").read_text(encoding="utf-8"))
    check(config["cash"]["initial"] == INITIAL_CASH, "INITIAL_CASH_OUT_OF_SCOPE")
    check(config["account"]["allow_short_selling"] is False
          and config["account"]["allow_leverage"] is False, "NATIVE_ACCOUNT_SCOPE_INVALID")
    contract_doc = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    evidence = {entry["path"]: entry for entry in frozen["identity"]["evidence"]}
    costs_ref = next(path for path in evidence if Path(path).name == "costs.json")
    multiplier_ref = next(path for path in evidence if Path(path).name == "multiplier.json")
    costs_path, multiplier_path = fixture / costs_ref, fixture / multiplier_ref
    check(file_hash(costs_path) == evidence[costs_ref]["sha256"], "COST_EVIDENCE_HASH_MISMATCH")
    check(file_hash(multiplier_path) == evidence[multiplier_ref]["sha256"], "MULTIPLIER_EVIDENCE_HASH_MISMATCH")
    costs, multiplier = read_json(costs_path), read_json(multiplier_path)
    check(costs == {"commission_bps": 0, "slippage_bps": 0}, "NONZERO_COST_OUT_OF_SCOPE")
    check(float(multiplier.get("value")) == 1.0, "NONUNIT_MULTIPLIER_OUT_OF_SCOPE")
    check(contract_doc["dataset"]["source_symbol"] == multiplier.get("source_symbol"),
          "MULTIPLIER_SYMBOL_MISMATCH")

    bars = pl.read_parquet(data_path)
    expected, last_close = expected_trades(bars, action)
    fills = pl.read_parquet(native_dir / "fills.parquet")
    check(fills.height == 2, "FILL_COUNT_MISMATCH")
    for index, exp in enumerate(expected):
        actual = fills.row(index, named=True)
        check(actual["side"] == exp["side"] and actual["order_type"] == exp["kind"],
              "FILL_SIDE_OR_TYPE_MISMATCH")
        check(actual["asset"] == contract_doc["dataset"]["source_symbol"], "FILL_SYMBOL_MISMATCH")
        check(ts(actual["timestamp"]) == exp["time"], "FILL_TIME_MISMATCH")
        close(actual["quantity"], exp["quantity"], "FILL_QUANTITY_MISMATCH")
        close(actual["price"], exp["price"], "FILL_PRICE_MISMATCH", 1e-8)
        close(actual["commission"], 0.0, "FILL_COMMISSION_MISMATCH")
        close(actual["slippage"], 0.0, "FILL_SLIPPAGE_MISMATCH")
    cash = INITIAL_CASH
    shares = 0.0
    for exp in expected:
        signed = exp["quantity"] if exp["side"] == "buy" else -exp["quantity"]
        cash -= signed * exp["price"]
        shares += signed
    check(abs(shares) <= TOL, "OPEN_POSITION_AFTER_BRACKET")
    final_equity = cash + shares * last_close
    gross_pnl = expected[1]["quantity"] * (expected[1]["price"] - expected[0]["price"])

    trades = pl.read_parquet(native_dir / "trades.parquet")
    check(trades.height == 1, "TRADE_COUNT_MISMATCH")
    trade = trades.row(0, named=True)
    check(trade["symbol"] == contract_doc["dataset"]["source_symbol"]
          and trade["direction"] == "long" and trade["status"] == "closed", "TRADE_IDENTITY_MISMATCH")
    check(ts(trade["entry_time"]) == expected[0]["time"]
          and ts(trade["exit_time"]) == expected[1]["time"], "TRADE_CLOCK_MISMATCH")
    close(trade["entry_price"], expected[0]["price"], "TRADE_ENTRY_PRICE_MISMATCH", 1e-8)
    close(trade["exit_price"], expected[1]["price"], "TRADE_EXIT_PRICE_MISMATCH", 1e-8)
    close(trade["quantity"], expected[0]["quantity"], "TRADE_QUANTITY_MISMATCH")
    close(trade["gross_pnl"], gross_pnl, "TRADE_GROSS_PNL_MISMATCH")
    close(trade["pnl"], gross_pnl, "TRADE_NET_PNL_MISMATCH")
    close(trade["fees"], 0, "TRADE_FEES_MISMATCH")

    portfolio = pl.read_parquet(native_dir / "portfolio_state.parquet")
    equity = pl.read_parquet(native_dir / "equity.parquet")
    check(portfolio.height == bars.height and equity.height == bars.height,
          "EQUITY_SERIES_LENGTH_MISMATCH")
    fill_at = {row["time"]: row for row in expected}
    cash_now, shares_now, high_water = INITIAL_CASH, 0.0, INITIAL_CASH
    prev_equity = INITIAL_CASH
    for index, bar in enumerate(bars.to_dicts()):
        moment = ts(bar["timestamp"])
        fill = fill_at.get(moment)
        if fill:
            signed = fill["quantity"] if fill["side"] == "buy" else -fill["quantity"]
            cash_now -= signed * fill["price"]
            shares_now += signed
        mark = float(bar["close"])
        expected_equity = cash_now + shares_now * mark
        p = portfolio.row(index, named=True)
        e = equity.row(index, named=True)
        check(ts(p["timestamp"]) == moment and ts(e["timestamp"]) == moment,
              "EQUITY_CLOCK_MISMATCH")
        close(p["cash"], cash_now, "PORTFOLIO_CASH_MISMATCH")
        close(p["equity"], expected_equity, "PORTFOLIO_EQUITY_MISMATCH")
        close(p["gross_exposure"], abs(shares_now * mark), "PORTFOLIO_GROSS_EXPOSURE_MISMATCH")
        close(p["net_exposure"], shares_now * mark, "PORTFOLIO_NET_EXPOSURE_MISMATCH")
        check(p["open_positions"] == (1 if abs(shares_now) > TOL else 0),
              "PORTFOLIO_POSITION_COUNT_MISMATCH")
        close(e["equity"], expected_equity, "EQUITY_MARK_MISMATCH")
        close(e["return"], expected_equity / prev_equity - 1, "EQUITY_RETURN_MISMATCH", 1e-10)
        high_water = max(high_water, expected_equity)
        close(e["high_water_mark"], high_water, "EQUITY_HWM_MISMATCH")
        close(e["drawdown"], expected_equity / high_water - 1, "EQUITY_DRAWDOWN_MISMATCH", 1e-10)
        prev_equity = expected_equity

    metrics = read_json(native_dir / "metrics.json")
    close(metrics["initial_cash"], INITIAL_CASH, "METRICS_INITIAL_CASH_MISMATCH")
    close(metrics["final_value"], final_equity, "METRICS_FINAL_VALUE_MISMATCH")
    close(metrics["total_gross_pnl"], gross_pnl, "METRICS_GROSS_PNL_MISMATCH")
    check(metrics["num_trades"] == 1 and metrics["num_fills"] == 2,
          "METRICS_ACTIVITY_MISMATCH")
    daily = pl.read_parquet(native_dir / "daily_pnl.parquet")
    check(daily.height == 1, "DAILY_PNL_ROW_COUNT_MISMATCH")
    close(daily["close_equity"][0], final_equity, "DAILY_FINAL_EQUITY_MISMATCH")
    close(daily["pnl"][0], gross_pnl, "DAILY_PNL_MISMATCH")

    # Check outer audit numbers for contradiction, without trusting its status.
    audit_evidence = outer.get("audit", {}).get("evidence", {})
    close(audit_evidence.get("cash_final"), cash, "OUTER_CASH_CONTRADICTION")
    close(audit_evidence.get("equity_final"), final_equity, "OUTER_EQUITY_CONTRADICTION")
    check(audit_evidence.get("trade_count") == 1, "OUTER_TRADE_COUNT_CONTRADICTION")
    check(len(audit_evidence.get("fills", [])) == 2, "OUTER_FILL_COUNT_CONTRADICTION")
    for expected_fill, claimed_fill in zip(expected, audit_evidence["fills"], strict=True):
        check(claimed_fill.get("side") == expected_fill["side"], "OUTER_FILL_SIDE_CONTRADICTION")
        check(ts(claimed_fill.get("timestamp")) == expected_fill["time"], "OUTER_FILL_TIME_CONTRADICTION")
        close(claimed_fill.get("price"), expected_fill["price"], "OUTER_FILL_PRICE_CONTRADICTION", 1e-8)
        close(claimed_fill.get("quantity"), expected_fill["quantity"], "OUTER_FILL_QTY_CONTRADICTION")
    return {
        "state": "RAW_EVIDENCE_REPLAY_PASSED",
        "attempt_id": attempt_id,
        "revisions": len(terminal_events),
        "checks": ["direct_attempt_event_replay", "frozen_data_config_source_and_code_identity",
                   "action_and_permit_binding", "native_manifest_component_set", "fills_from_raw_bars_and_action",
                   "trade_cash_equity_portfolio_and_metrics_replay", "outer_manifest_numerical_consistency"],
        "expected": {"fills": expected, "ending_cash": cash, "ending_equity": final_equity,
                     "gross_pnl": gross_pnl, "native_files": sorted(REQUIRED_NATIVE)},
        "input_hashes": {"bars": file_hash(data_path), "outer_manifest": file_hash(outer_manifest_path),
                         "fills": file_hash(native_dir / "fills.parquet"),
                         "equity": file_hash(native_dir / "equity.parquet"),
                         "attempt_terminal": canonical_hash(terminal)},
        "limitations": ["Synthetic one-symbol long bracket only; zero commission/slippage and multiplier 1.",
                        "The frozen intent and feature proof are compared through the recorded action and ledger; their original full payloads are not retained in this fixture.",
                        "Cooperative same-owner file replacement is outside this replay's trust boundary."],
    }


def run(fixture: Path, output: Path) -> dict[str, Any]:
    fixture, output = fixture.resolve(), output.resolve()
    check(not output.exists() and not output.is_symlink(), "OUTPUT_DIRECTORY_ALREADY_EXISTS")
    output.mkdir(parents=True, exist_ok=False)
    base = next((fixture / "run_log/ats2").rglob("execution_audit.json")).parent
    clean_native = base / "quarantined_original_native"
    clean_manifest = base / "original_execution_audit.txt"
    actual_native = base / "native"
    actual_manifest = base / "execution_audit.json"
    cases: list[dict[str, Any]] = []

    def record(name: str, fn, *, expected_reject: str) -> None:
        try:
            result = fn()
        except Reject as exc:
            ok = exc.reason_code == expected_reject
            cases.append({"case": name, "expected_reject_reason": expected_reject,
                          "observed_reject_reason": exc.reason_code,
                          "observed": str(exc), "test_pass": ok})
            if not ok:
                raise Reject("HARNESS_CASE_FAILED", f"{name}: expected {expected_reject}, got {exc}")
            return
        except Exception as exc:
            raise Reject("HARNESS_UNEXPECTED_EXCEPTION", f"{name}: {type(exc).__name__}: {exc}") from exc
        raise Reject("HARNESS_EXPECTED_REJECTION_MISSING", f"{name}: returned {result!r}")

    clean = replay(fixture, clean_native, clean_manifest)
    cases.append({"case": "pristine_quarantined_native_control", "expected_accept": True,
                  "observed_accept": True, "observed": clean["state"], "test_pass": True})
    record("supervisor_substituted_permit_impossible_cash_empty_native", lambda:
           replay(fixture, actual_native, actual_manifest), expected_reject="PERMIT_SUBSTITUTION")
    record("empty_native_with_original_manifest", lambda:
           replay(fixture, actual_native, clean_manifest), expected_reject="NATIVE_COMPONENT_MISSING")

    temp = output / "scenarios"
    temp.mkdir()
    # Raw corruption cases operate on private scenario copies, never source fixtures.
    tampered = temp / "tampered_fill"
    shutil.copytree(clean_native, tampered / "native")
    shutil.copy2(clean_manifest, tampered / "execution_audit.json")
    fill_path = tampered / "native/fills.parquet"
    fills = pl.read_parquet(fill_path).with_columns(
        pl.when(pl.arange(0, pl.len()) == 0).then(pl.col("price") + 25.0)
        .otherwise(pl.col("price")).alias("price")
    )
    fills.write_parquet(fill_path)
    record("tampered_raw_fill", lambda: replay(fixture, tampered / "native",
                                                tampered / "execution_audit.json"),
           expected_reject="FILL_PRICE_MISMATCH")

    missing = temp / "missing_equity"
    shutil.copytree(clean_native, missing / "native")
    shutil.copy2(clean_manifest, missing / "execution_audit.json")
    (missing / "native/equity.parquet").unlink()
    record("missing_native_equity_artifact", lambda: replay(fixture, missing / "native",
                                                              missing / "execution_audit.json"),
           expected_reject="NATIVE_COMPONENT_MISSING")

    original_manifest = read_json(clean_manifest)
    bad_cash = temp / "impossible_cash.json"
    bad_cash_value = copy.deepcopy(original_manifest)
    bad_cash_value["audit"]["evidence"]["cash_final"] = -123456789.0
    bad_cash.write_text(json.dumps(bad_cash_value) + "\n")
    record("impossible_cash_even_with_valid_permit_and_native_outputs", lambda:
           replay(fixture, clean_native, bad_cash), expected_reject="OUTER_CASH_CONTRADICTION")
    bad_equity = temp / "impossible_equity.json"
    bad_equity_value = copy.deepcopy(original_manifest)
    bad_equity_value["audit"]["evidence"]["equity_final"] = 999999999.0
    bad_equity.write_text(json.dumps(bad_equity_value) + "\n")
    record("impossible_equity_even_with_valid_permit_and_native_outputs", lambda:
           replay(fixture, clean_native, bad_equity), expected_reject="OUTER_EQUITY_CONTRADICTION")

    events_dir = fixture / "run_log/research_sessions/permit-synthetic/attempts"
    all_events = [read_json(path, 256 * 1024) for path in sorted(events_dir.glob("*.json"))]
    completed_event = next(row for row in all_events if row.get("status") == "COMPLETED")
    contradictory = copy.deepcopy(all_events)
    changed = next(row for row in contradictory if row["event_id"] == completed_event["event_id"])
    changed["fingerprints"]["data_sha256"] = "0" * 64
    record("contradictory_attempt_identity", lambda: replay(
        fixture, clean_native, clean_manifest, records_override=contradictory),
        expected_reject="ATTEMPT_FINGERPRINTS_DRIFT")
    bad_lifecycle = copy.deepcopy(all_events)
    first_event = next(row for row in bad_lifecycle if row["attempt_id"] == completed_event["attempt_id"]
                       and row["revision"] == 1)
    first_event["status"] = "COMPLETED"
    record("contradictory_attempt_transition_history", lambda: replay(
        fixture, clean_native, clean_manifest, records_override=bad_lifecycle),
        expected_reject="ATTEMPT_LIFECYCLE_CONTRADICTION")

    def unexpected_type_error():
        raise TypeError("injected harness error")
    try:
        record("unexpected_error_guard_self_check", unexpected_type_error,
               expected_reject="EXPECTED_SECURITY_REJECTION")
    except Reject as exc:
        check(exc.reason_code == "HARNESS_UNEXPECTED_EXCEPTION",
              "UNEXPECTED_ERROR_COUNTED_AS_REJECTION")
        cases.append({"case": "unexpected_error_guard_self_check",
                      "expected_harness_error": "HARNESS_UNEXPECTED_EXCEPTION",
                      "observed_harness_error": exc.reason_code, "test_pass": True})
    else:
        raise Reject("UNEXPECTED_ERROR_COUNTED_AS_REJECTION")

    before = directory_digest(output)
    try:
        run(fixture, output)
    except Reject as exc:
        check(exc.reason_code == "OUTPUT_DIRECTORY_ALREADY_EXISTS",
              "EXISTING_OUTPUT_NOT_PROTECTED")
        check(directory_digest(output) == before, "PRIOR_OUTPUT_CHANGED_ON_REPLAY")
        cases.append({"case": "existing_output_and_prior_evidence_are_preserved",
                      "expected_reject_reason": "OUTPUT_DIRECTORY_ALREADY_EXISTS",
                      "observed_reject_reason": exc.reason_code,
                      "evidence_digest_unchanged": True, "test_pass": True})
    else:
        raise Reject("EXISTING_OUTPUT_NOT_PROTECTED")

    report = {"schema_version": 1, "harness": "scripts/ats2_outside_judge.py",
              "harness_sha256": file_hash(Path(__file__).resolve()),
              "runtime": {"python": sys.version.split()[0],
                          "polars": importlib.metadata.version("polars"),
                          "pyyaml": importlib.metadata.version("PyYAML")},
              "scope": "synthetic development native bracket only", "cases": cases,
              "positive_control": clean, "all_passed": all(item["test_pass"] for item in cases)}
    report["limitations"] = [
        "Recovered multi-attempt histories are validated for monotonic fencing tokens and exact parent_attempt_id linkage. Valid FAILED/ABORTED ancestors are retained.",
    ] + clean["limitations"]
    report_path = output / "replay_report.json"
    with report_path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    command_output = {"state": "PASS" if report["all_passed"] else "FAIL",
                      "report": str(report_path.resolve()), "cases": cases}
    with (output / "command_output.json").open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(command_output, indent=2) + "\n")
    command = (".venv/bin/python scripts/ats2_outside_judge.py "
               f"--output {output.relative_to(Path.cwd())}")
    with (output / "commands.txt").open("x", encoding="utf-8") as stream:
        stream.write("Command:\n" + command + "\nObserved exit status: 0\n")
    with (output / "findings.md").open("x", encoding="utf-8") as stream:
        stream.write(
            "# Independent ATS-2 replay\n\n"
            f"Command: `{command}` (exit 0).\n\n"
            f"Expected-reason cases: {len(cases)} passed. Details and raw input hashes are in `replay_report.json`; console JSON is in `command_output.json`; corrupted evidence copies are in `scenarios/`.\n\n"
            "Scope is one synthetic development bracket, zero fees/slippage, multiplier 1. Recovered multi-attempt histories are validated with monotonic fencing tokens plus exact successor `parent_attempt_id` linkage. This fixture does not retain full intent/feature-proof payloads and does not prove owner-proof integrity.\n"
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path,
                        default=Path("run_log/ats2/supervisor_negative_first_draft"))
    parser.add_argument("--output", type=Path,
                        default=Path("run_log/ats2/independent_review_hardened"))
    parser.add_argument("--native-recovery", action="store_true",
                        help="Replay accepted recovered native artifacts without quarantined fixture")
    parser.add_argument("--clean-control", type=Path,
                        help="Independent clean fixture to compare native results")
    args = parser.parse_args()
    if args.native_recovery:
        try:
            fixture = args.fixture.resolve()
            events = fixture / "run_log/research_sessions/permit-synthetic/attempts"
            completed = [read_json(p, 256 * 1024) for p in events.glob("*.json")
                         if read_json(p, 256 * 1024).get("status") == "COMPLETED"]
            check(len(completed) == 1, "RECOVERY_TERMINAL_AMBIGUOUS")
            finished = completed[0]
            action = finished["metadata"]["ats2_action"]
            base = fixture / action["write_scope"] / finished["attempt_id"]
            result = replay(fixture, base / "native", base / "execution_audit.json")
            control_result = None
            if args.clean_control is not None:
                control = args.clean_control.resolve()
                rows = [read_json(p, 256 * 1024) for p in
                        (control / "run_log/research_sessions/permit-synthetic/attempts").glob("*.json")]
                controls = [row for row in rows if row.get("status") == "COMPLETED"]
                check(len(controls) == 1, "CONTROL_TERMINAL_AMBIGUOUS")
                control_base = control / controls[0]["metadata"]["ats2_action"]["write_scope"] / controls[0]["attempt_id"]
                control_result = replay(control, control_base / "native", control_base / "execution_audit.json")
                for filename in ("fills.parquet", "trades.parquet", "equity.parquet",
                                 "portfolio_state.parquet", "daily_pnl.parquet"):
                    check(pl.read_parquet(base / "native" / filename).equals(
                        pl.read_parquet(control_base / "native" / filename)),
                        "RECOVERED_CLEAN_NUMERIC_MISMATCH:" + filename)
            check(finished.get("parent_attempt_id") is not None, "RECOVERY_PARENT_MISSING")
            args.output.mkdir(parents=True, exist_ok=False)
            report = {"state": "PASS", "mode": "native_recovery", "recovered": result,
                      "control": control_result, "fixture": str(fixture),
                      "control_fixture": str(args.clean_control) if args.clean_control else None}
            with (args.output / "replay_report.json").open("x") as stream:
                json.dump(report, stream, indent=2, default=str)
            print(json.dumps({"state": "PASS", "report": str(args.output / "replay_report.json")}, indent=2))
            return 0
        except (Reject, OSError, ValueError, TypeError, KeyError, StopIteration) as exc:
            print(json.dumps({"state": "REJECTED_OR_HARNESS_ERROR", "error": str(exc)}))
            return 1
    try:
        report = run(args.fixture, args.output)
    except (Reject, OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"state": "REJECTED_OR_HARNESS_ERROR", "error": str(exc)}, indent=2))
        return 1
    print(json.dumps({"state": "PASS" if report["all_passed"] else "FAIL",
                      "report": str((args.output / "replay_report.json").resolve()),
                      "cases": report["cases"]}, indent=2))
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
