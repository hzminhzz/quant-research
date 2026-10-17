"""Read-only real elapsed observation assessment; never issues release approval."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from scripts.ats7_paper import save
from src.release_contracts import ReleaseManifest
from src.research_control.action_authorization import sha256_json


def assess(run):
    manifest = ReleaseManifest.model_validate_json((run / "manifest.json").read_text())
    manifest.verify_sources()
    start = json.loads((run / "observation-start.json").read_text())
    if start["release_identity"] != manifest.identity:
        raise ValueError("observation release identity mismatch")
    started = datetime.fromisoformat(start["started_at"])
    now = datetime.now(UTC)
    con = sqlite3.connect(f"file:{run / 'state' / manifest.risk_domain / 'release.sqlite'}?mode=ro", uri=True)
    bars = []
    first_service = None
    prior = "0" * 64
    count = 0
    for seq, at, kind, payload, previous, digest in con.execute("SELECT * FROM events ORDER BY seq"):
        count += 1
        if seq != count or previous != prior or sha256_json([seq, at, kind, payload, previous]) != digest:
            raise ValueError("observation journal integrity")
        obj = json.loads(payload)
        if kind == "service_started" and first_service is None:
            first_service = datetime.fromisoformat(at)
        if kind == "bar":
            stamp = datetime.fromisoformat(obj["timestamp"])
            if started <= stamp <= now:
                bars.append(stamp)
        prior = digest
    if first_service is None or not 0 <= (started - first_service).total_seconds() < 30:
        raise ValueError("observation start does not match original service evidence")
    unknown = con.execute("SELECT count(*) FROM decisions WHERE state IN ('UNKNOWN','DISPATCHING')").fetchone()[0]
    cycles = con.execute("SELECT count(*) FROM decisions WHERE state='LOCAL_FILLED' "
                         "AND json_extract(request,'$.action')='reduce'").fetchone()[0]
    failures = con.execute("SELECT count(*) FROM events WHERE kind='service_failed'").fetchone()[0]
    con.close()
    elapsed = max(0.0, (now - started).total_seconds())
    expected = int(elapsed // manifest.operations.bar_seconds)
    coverage = min(1.0, len(set(bars)) / expected) if expected else None
    time_met = elapsed >= manifest.operations.observation_days * 86400
    coverage_met = coverage is not None and coverage >= manifest.operations.minimum_bar_coverage
    health = json.loads((run / "health.json").read_text())
    health_age = (now - datetime.fromisoformat(health["observed_at"])).total_seconds()
    stopped_path = run / "stopped.json"
    stopped_after_health = (stopped_path.exists() and
        datetime.fromisoformat(json.loads(stopped_path.read_text())["stopped_at"]) >=
        datetime.fromisoformat(health["observed_at"]))
    running = (health_age < 15 and health["status"] == "PAPER_RUNNING"
               and health["engine"]["runtime_state"] == "running" and not stopped_after_health)
    result = {
        "status": ("PAPER_RUNNING" if not time_met else "OPERATOR_REVIEW_REQUIRED") if running else "BLOCKED",
        "current_health_age_seconds": health_age, "runtime_running": running,
        "scope": "SYNTHETIC_ENGINEERING_ONLY", "strategy_release": "BLOCKED_NO_ELIGIBLE_STRATEGY",
        "live_authorization": "BLOCKED", "release_identity": manifest.identity,
        "assessed_at": now.isoformat(), "started_at": started.isoformat(),
        "earliest_completion": start["earliest_completion"],
        "real_elapsed_seconds": elapsed, "required_seconds": manifest.operations.observation_days * 86400,
        "elapsed_gate_met": time_met, "observed_bars": len(set(bars)), "expected_bars": expected,
        "bar_coverage": coverage, "coverage_gate_met": coverage_met,
        "completed_cycles": cycles, "unknown_orders": unknown, "service_failures": failures,
        "journal_events": count, "journal_head": prior,
        "remaining_review": ["source stability", "all incidents", "loss controls", "actual alert activation", "independent qualification"],
        "source_hashes": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in (run / "manifest.json", run / "observation-start.json", run / "observation-policy.json")},
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = assess(args.run_root)
    if args.output:
        save(args.output, result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
