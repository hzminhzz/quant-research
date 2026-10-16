"""Read-only ATS-3 projection from existing ML4T native Parquet evidence.

Historical simulation evidence only: never claim it is a broker execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC
from pathlib import Path

import polars as pl

from src.research_control.ats3_audit import AuditEvent, reconcile


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_native(directory: Path) -> dict:
    directory = directory.resolve(strict=True)
    inputs = {name: directory / (name + ".parquet") for name in ("fills", "funding", "equity")}
    if any(not p.is_file() or p.is_symlink() for p in inputs.values()):
        raise ValueError("NATIVE_AUTHORITY_MISSING")
    frames = {name: pl.read_parquet(path) for name, path in inputs.items()}
    fills, funding, equity = (frames[name] for name in ("fills", "funding", "equity"))
    if equity.is_empty():
        raise ValueError("NATIVE_EQUITY_EMPTY")
    if not {"order_id", "asset", "side", "quantity", "price", "commission", "timestamp"}.issubset(fills.columns):
        raise ValueError("NATIVE_FILL_SCHEMA_UNSUPPORTED")
    first, last = equity.row(0, named=True), equity.row(-1, named=True)
    if first["timestamp"] > last["timestamp"]:
        raise ValueError("NATIVE_EQUITY_CLOCK_INVALID")
    source = "native:" + _sha(inputs["fills"])[:16]
    events: list[AuditEvent] = []

    def add(kind, identity, timestamp, instrument, payload, execution_id=""):
        when = timestamp.replace(tzinfo=UTC) if timestamp.tzinfo is None else timestamp.astimezone(UTC)
        events.append(AuditEvent(source, "simulation", "native-account", "native-unattributed",
                                 instrument, identity, kind, when, when, when, payload, execution_id))

    for index, fill in enumerate(fills.to_dicts()):
        oid = fill["order_id"]
        if not oid:
            raise ValueError("NATIVE_ORDER_ID_MISSING")
        # Native outputs have fill IDs only when provided; row identity is explicitly
        # a source-record ordinal tied to the immutable fills file checksum.
        ref = f"{oid}:{index}"
        add("order", "order:" + oid, fill["timestamp"], fill["asset"], {}, oid)
        # Native fill exports do not prove a transport acknowledgment.
        add("fill", "fill:" + ref, fill["timestamp"], fill["asset"],
            {"quantity": fill["quantity"], "price": fill["price"], "side": fill["side"]}, oid)
        add("commission", "fee:" + ref, fill["timestamp"], fill["asset"],
            {"amount": fill["commission"]}, oid)
    for index, row in enumerate(funding.to_dicts()):
        add("financing", f"funding:{index}", row["timestamp"], row["symbol"],
            {"amount": row["cashflow"]})

    result = reconcile(events, initial_cash=str(first["equity"]))
    # Funding records include native zero-position rows, which remain real evidence.
    expected = float(last["equity"])
    actual = float(result["cash"]) if result["cash"] is not None else None
    tolerance = max(1e-6, abs(expected) * 1e-9)
    flat = all(abs(float(q)) < 1e-9 for q in result["positions"].values())
    difference = actual - expected if actual is not None and flat else None
    result.update({
        "provenance": {name: {"path": str(path), "sha256": _sha(path),
                              "rows": frames[name].height} for name, path in inputs.items()},
        "authority": "ML4T_NATIVE_SIMULATION_NOT_BROKER",
        "comparison": {"native_final_equity": expected, "reconstructed_final_cash": actual,
                       "final_flat": flat, "difference": difference, "tolerance": tolerance},
    })
    if not flat:
        result["unknowns"].append("ENDING_MARKS_NOT_AVAILABLE_IN_NATIVE_EXPORT")
        result["status"] = "INSUFFICIENT_EVIDENCE"
    elif difference is not None and abs(difference) > tolerance:
        result["conflicts"].append("NATIVE_END_EQUITY_MISMATCH")
        result["status"] = "CONFLICTING_EVIDENCE"
    elif difference is not None:
        result["comparison"]["numerical_status"] = "PASS"
    # No native export contains transport ACKs, intent/reject/skip history,
    # real broker mark or external cash-movement receipts.
    result["unknowns"] = sorted(set(result["unknowns"]) |
        {"ROUTE_AND_INTENT_NOT_IN_NATIVE_EXPORT", "BROKER_EXECUTION_NOT_OBSERVED"})
    if result["status"] == "VERIFIED":
        result["status"] = "INSUFFICIENT_EVIDENCE"
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only audit of existing native execution")
    parser.add_argument("native_directory", type=Path)
    args = parser.parse_args(argv)
    report = audit_native(args.native_directory)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "VERIFIED" else 3


if __name__ == "__main__":
    raise SystemExit(main())
