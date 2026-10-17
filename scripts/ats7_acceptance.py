"""Reproducible synthetic native lifecycle and separately evaluated ATS-6 shadow."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from scripts import ats6_fixtures as shadow
from scripts.ats7_fixtures import FixtureFeed, cycle_rows, local_manifest
from src.portfolio_evidence import SleeveIdentity
from src.release_probe import SyntheticCycle
from src.release_runtime import build_release_engine
from src.shadow_contracts import Intent, Leg, PortfolioSnapshot

ROOT = Path(__file__).resolve().parents[1]


def save(path, value):
    with path.open("x") as out:
        json.dump(value, out, sort_keys=True, indent=2, default=str)
        out.flush()
        os.fsync(out.fileno())


def compare_shadow(run, manifest):
    """Map original committed local opening intents into the frozen synthetic domain.

    This replay compares admission and quantity, not execution-price parity. It is
    not a live gate, provider event source, or conversion of an ATS-6 grant.
    """
    con = sqlite3.connect(run / "state" / manifest.risk_domain / "release.sqlite")
    decisions = [json.loads(p) for (p,) in con.execute("SELECT request FROM decisions ORDER BY rowid")]
    con.close()
    results = []
    native_source = next(s.sha256 for s in manifest.sources if s.role == "strategy")
    for index, request in enumerate(d for d in decisions if d["action"] == "open"):
        router, private, token = shadow.create_fixture(run / f"shadow-{index}.sqlite", caps=(800,), costs=(0,))
        sl = SleeveIdentity("ats7-cycle", "synthetic-v1", manifest.identity, native_source,
                            "ats7-frozen-fixture", "native-no-cost-simulation", "UTC", "ATS7_SYNTHETIC_ONLY")
        snapshot = PortfolioSnapshot(revision=2, at=shadow.START, valid_until=shadow.END,
                                      evidence_ref="fixture://ats7/" + manifest.identity, sleeves=(sl,))
        assert router.update_portfolio(snapshot, token, now=shadow.START)["status"] == "UPDATED"
        lots = Decimal(str(request["quantity"])) / Decimal(".001")
        assert lots == lots.to_integral_value()
        item = Intent(intent_id=f"native-{index}", sleeve=sl, family="ats7-synthetic",
                      source_ref="fixture://ats7/original-decision/" + str(index),
                      created_at=shadow.START, valid_until=shadow.END,
                      legs=(Leg(leg_id="leg-0", instrument=shadow.SYMBOL, side=request["side"],
                                quantity_lots=int(lots), lot_size=".001",
                                stress_units_per_lot=100, margin_units_per_lot=20),))
        action, grant = shadow.signed(router, private, item)
        admitted = router.admit(action, grant, token, now=shadow.START)
        assert admitted["status"] == "ADMITTED", admitted
        publication = shadow.publish(router, item.intent_id, token)
        route = router.snapshot()["routes"][item.intent_id]
        granted = sum(leg["quantity_lots"] for leg in route["legs"].values())
        results.append({"native_decision": request, "shadow_status": publication["status"],
                        "quantity_match": granted == int(lots), "native_quantity": request["quantity"],
                        "shadow_quantity_lots": granted, "shadow_lot_size": ".001",
                        "account_scope": "SYNTHETIC_SHADOW_ONLY", "real_account_permission": False,
                        "mapping": {"BTC/USDT:USDT": shadow.SYMBOL},
                        "clock_mapping": "causal fixture order mapped to frozen ATS6 START; no historical provider claim",
                        "shadow_action": action, "grant": grant})
    assert len(results) == 2 and all(r["quantity_match"] for r in results)
    save(run / "shadow-comparison.json", {"status": "PASS", "opening_intents": results,
         "reduction_comparison": "ATS6 has no executable reduction command; actual native close lifecycle is audited separately",
         "fill_parity": "not asserted; ATS6 is a shadow admission reference"})
    return results


async def lifecycle(run):
    manifest = local_manifest()
    save(run / "manifest.json", manifest.model_dump(mode="json"))
    rows = cycle_rows()
    save(run / "original-bars.json", rows)
    (run / "state").mkdir(mode=0o700)
    engine = build_release_engine(SyntheticCycle(), FixtureFeed(rows), manifest, run / "state")
    await engine.connect()
    await engine.run()
    safe = engine.broker
    terminal = {"observed_at": datetime.now(UTC).isoformat(), "cash": safe._virtual_portfolio.cash,
                "positions": {k: {"quantity": p.quantity, "price": p.current_price}
                              for k, p in safe.positions.items()}, "pending_count": len(safe.pending_orders),
                "engine": engine.runtime_status(), "persistence": safe.persistence_status}
    save(run / "terminal.json", terminal)
    compare_shadow(run, manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=ROOT / "run_log/ats7/acceptance")
    args = parser.parse_args()
    run = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8])
    run.mkdir(parents=True, mode=0o700)
    print("evidence=" + str(run), flush=True)
    manifest = asyncio.run(lifecycle(run))
    result = subprocess.run([sys.executable, "-m", "scripts.ats7_outside_judge", str(run),
                             "--output", str(run / "outside-judge.json")], cwd=ROOT, check=False)
    save(run / "artifact-hashes.json", {str(p.relative_to(run)): hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in sorted(run.rglob("*")) if p.is_file()})
    save(run / "result.json", {"status": "PASS" if result.returncode == 0 else "FAIL",
                              "release_identity": manifest.identity,
                              "scope": "native synthetic local paper + ATS6 synthetic admission comparison",
                              "provider_execution": "NOT_AUTHORIZED_NOT_RUN",
                              "observation": "NOT_SATISFIED_BY_THIS_REPLAY"})
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
