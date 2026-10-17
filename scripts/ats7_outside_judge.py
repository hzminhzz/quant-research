"""Outside-process ATS-7 local economics judge; no broker or release runtime imports."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from src.research_control.ats3_audit import AuditEvent, reconcile


def judge(run: Path) -> dict:
    manifest = json.loads((run / "manifest.json").read_text())
    terminal = json.loads((run / "terminal.json").read_text())
    con = sqlite3.connect(f"file:{run / 'state' / manifest['risk_domain'] / 'release.sqlite'}?mode=ro", uri=True)
    try:
        rows = [(at, kind, json.loads(raw)) for at, kind, raw in
                con.execute("SELECT at,kind,payload FROM events ORDER BY seq")]
    finally:
        con.close()
    decisions = {p["identity"]: p["request"] for _, kind, p in rows if kind == "decision_committed"}
    observed = [(at, p) for at, kind, p in rows if kind == "decision_observed"]
    events, fills = [], []
    account = manifest["account_ref"]
    def event(kind, identity, at, payload, order=""):
        stamp = datetime.fromisoformat(at)
        events.append(AuditEvent("ML4T_NATIVE_LOCAL_SIMULATION", "LOCAL_PAPER", account,
                                 manifest["name"], "BTC/USDT:USDT", identity, kind, stamp, stamp, stamp,
                                 payload, execution_id=order))
    cash = Decimal(str(manifest["risk"]["capital"]))
    positions = {}
    problems = []
    for at, payload in observed:
        if payload["state"] != "LOCAL_FILLED":
            problems.append("NONTERMINAL_LOCAL_DECISION:" + payload["identity"])
            continue
        original = payload["evidence"]
        decision = decisions[payload["identity"]]
        order = payload["order_id"]
        if (original["asset"] != decision["asset"] or original["side"] != decision["side"]
                or Decimal(str(original["filled_quantity"])) != Decimal(str(decision["quantity"]))):
            problems.append("INTENT_FILL_MISMATCH:" + order)
        qty, price = Decimal(str(original["filled_quantity"])), Decimal(str(original["filled_price"]))
        signed = qty if original["side"] == "buy" else -qty
        cash -= signed * price
        positions[original["asset"]] = positions.get(original["asset"], Decimal(0)) + signed
        event("intent", "intent:" + order, at, decision, order)
        event("order", "order:" + order, at, {"quantity": original["quantity"]}, order)
        event("ack", "ack:" + order, at, {"authority": "native simulated returned Order"}, order)
        event("fill", "fill:" + order, at, {"quantity": str(qty), "price": str(price), "side": original["side"]}, order)
        event("commission", "fee:" + order, at, {"amount": "0", "fill_event_id": "fill:" + order,
              "authority": "native simulator cost model; not observed provider commission"}, order)
        fills.append({"order_id": order, "quantity": str(qty), "price": str(price), "side": original["side"]})
    stamp = terminal["observed_at"]
    event("financing", "financing-model", stamp, {"amount": "0",
          "authority": "native simulator excludes financing; no claim about provider funding"})
    for asset in set(positions) | set(terminal["positions"]):
        value = terminal["positions"].get(asset, {}).get("quantity", 0)
        event("position", "terminal-position:" + asset, stamp, {"quantity": value})
    projection = reconcile(events, initial_cash=str(manifest["risk"]["capital"]))
    nonzero = {k: str(v) for k, v in positions.items() if v}
    if abs(cash - Decimal(str(terminal["cash"]))) > Decimal("0.000001"):
        problems.append("NATIVE_CASH_MISMATCH")
    if terminal["positions"] or nonzero:
        problems.append("EXPECTED_CLOSED_ENGINEERING_CYCLE")
    if terminal["pending_count"] != 0:
        problems.append("PENDING_LOCAL_ORDER")
    if projection["status"] != "VERIFIED":
        problems.append("ATS3_PROJECTION:" + projection["status"])
    if Decimal(projection["cash"]) != cash:
        problems.append("INDEPENDENT_ATS3_ARITHMETIC_MISMATCH")
    return {
        "status": "PASS" if not problems and len(fills) == 4 else "FAIL",
        "authority": "ACTUAL_NATIVE_LOCAL_SIMULATOR_EVENTS_NOT_PROVIDER",
        "problems": problems, "fills": fills, "cash_decimal": str(cash),
        "native_cash": terminal["cash"], "positions": nonzero, "ats3_projection": projection,
        "source_hashes": {name: hashlib.sha256((run / name).read_bytes()).hexdigest()
                          for name in ("manifest.json", "terminal.json")},
        "normalized_events": [{**asdict(e), "event_at": e.event_at.isoformat(),
                               "available_at": e.available_at.isoformat(), "observed_at": e.observed_at.isoformat()}
                              for e in events],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = judge(args.run)
    if args.output:
        with args.output.open("x") as out:
            json.dump(result, out, sort_keys=True, indent=2)
    print(json.dumps({k: v for k, v in result.items() if k not in {"normalized_events", "fills", "ats3_projection"}}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
