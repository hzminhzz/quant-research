"""Supervised credential-free native local paper; never constructs a provider broker."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import signal
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.connectors_bootstrap import ensure_connectors

ensure_connectors()
from connectors.bybit.feed import BybitKlineFeed

from scripts.ats7_fixtures import local_manifest
from src.ml4t_native_metrics import create_readonly_metrics_server
from src.release_contracts import ReleaseBlocked, ReleaseManifest
from src.release_probe import SyntheticCycle
from src.release_runtime import build_release_engine

ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "OpenAI File Downloader, XaiImageApiFetch/1.0"


def save(path, value, *, replace=False):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = path.with_suffix(path.suffix + ".new") if replace else path
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if replace else os.O_EXCL), 0o600)
    with os.fdopen(fd, "w") as out:
        json.dump(value, out, indent=2, sort_keys=True, default=str)
        out.flush()
        os.fsync(out.fileno())
    if replace:
        target.replace(path)


def freeze(run, evidence=()):
    run.mkdir(parents=True, mode=0o700, exist_ok=False)
    manifest = local_manifest(name="ats7-public-feed-synthetic-soak-v1", public_feed=True)
    raw = manifest.model_dump(mode="json")
    raw["qualification_evidence"] = [{"role": "independent_engineering_evidence",
        "path": str(path.resolve(strict=True)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in evidence]
    for name in ("scripts/ats7_paper.py", "scripts/ats7_sandbox.py", "src/ml4t_native_metrics.py",
                 "ops/ats7-local-paper@.service"):
        path = ROOT / name
        raw["sources"].append({"role": "operating_runtime", "path": str(path),
                               "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    manifest = ReleaseManifest.model_validate_json(json.dumps(raw))
    save(run / "manifest.json", manifest.model_dump(mode="json"))
    save(run / "observation-policy.json", {
        "frozen_at": datetime.now(UTC).isoformat(), "minimum_real_elapsed_days": 28,
        "minimum_completed_cycles": 1, "minimum_bar_coverage": 0.99,
        "maximum_unknown_orders": 0, "maximum_unauthorized_effects": 0,
        "maximum_unreviewed_loss_breaches": 0, "notification_receipt_required": True,
        "purpose": "synthetic engineering operational soak only",
        "qualified_strategy_observation": "BLOCKED_NO_ELIGIBLE_STRATEGY",
        "provider_execution": "NONE", "capital": "100000 native simulated units; no real money"})
    print(json.dumps({"release_identity": manifest.identity, "run": str(run), "status": "FROZEN"}))


async def run_paper(run, port):
    import ccxt.pro as ccxtpro

    manifest = ReleaseManifest.model_validate_json((run / "manifest.json").read_text())
    if manifest.environment != "LOCAL_PAPER" or manifest.strategy.scientific_status != "SYNTHETIC_ENGINEERING":
        raise ReleaseBlocked("THIS_SERVICE_ONLY_SUPPORTS_SYNTHETIC_LOCAL_PAPER")
    if any(k.startswith(("BYBIT_", "TELEGRAM_", "AWS_", "OPENAI_")) for k in os.environ):
        raise ReleaseBlocked("CREDENTIAL_FREE_ENVIRONMENT_REQUIRED")
    exchange = ccxtpro.bybit({"enableRateLimit": True, "userAgent": USER_AGENT,
                             "options": {"defaultType": "swap"}})
    feed = BybitKlineFeed(asset="BTC/USDT:USDT", exchange=exchange)
    engine = build_release_engine(SyntheticCycle(), feed, manifest, run / "state")
    safe = engine.broker
    last_service = safe.release_journal.connection.execute(
        "SELECT kind FROM events WHERE kind IN ('service_started','service_stopped') ORDER BY seq DESC LIMIT 1").fetchone()
    if last_service:
        safe.enable_kill_switch("SERVICE_RESTART_REQUIRES_SEPARATE_REVIEW")
        if last_service[0] == "service_started":
            safe.release_journal.record("service_failed", {"reason": "unclean_previous_process_exit"})
    safe.release_journal.record("service_started", {"pid": os.getpid(), "source_verified": True})
    if not (run / "observation-start.json").exists():
        started = datetime.now(UTC)
        save(run / "observation-start.json", {"started_at": started.isoformat(),
             "earliest_completion": (started + timedelta(days=28)).isoformat(),
             "release_identity": manifest.identity, "scope": "SYNTHETIC_ENGINEERING"})
    observation = json.loads((run / "observation-start.json").read_text())
    server = create_readonly_metrics_server(engine, safe, port=port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    stop_requested = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_requested.set)

    async def supervise():
        while not stop_requested.is_set():
            control = run / "control.json"
            if control.exists():
                command = json.loads(control.read_text())
                receipt = {"requested": command, "observed_at": datetime.now(UTC).isoformat()}
                try:
                    if command["action"] == "halt":
                        safe.enable_kill_switch(command["reason"])
                    elif command["action"] == "resume":
                        await safe.resume(command["reason"])
                    elif command["action"] == "stop":
                        stop_requested.set()
                    else:
                        raise ReleaseBlocked("UNKNOWN_CONTROL")
                    receipt["status"] = "APPLIED"
                except Exception as exc:  # noqa: BLE001 - redacted control failure
                    receipt.update(status="DENIED", reason=type(exc).__name__)
                save(run / ("control-receipt-" + command["id"] + ".json"), receipt)
                control.unlink()
            try:
                account = await safe.refresh_account(record=False)
                reconciliation = await safe.preview_reconciliation_async()
                if not reconciliation["clean"]:
                    safe.enable_kill_switch("CURRENT_RECONCILIATION_MISMATCH")
                con = safe.release_journal.connection
                bars = con.execute("SELECT count(*) FROM events WHERE kind='bar'").fetchone()[0]
                cycles = con.execute("SELECT count(*) FROM decisions WHERE state='LOCAL_FILLED' "
                                     "AND json_extract(request,'$.action')='reduce'").fetchone()[0]
                failures = con.execute("SELECT count(*) FROM events WHERE kind='service_failed'").fetchone()[0]
                values = {
                    "release_halted": int(safe.release_journal.halted),
                    "unknown_orders": safe.release_journal.unknown,
                    "pending_orders": account["pending_count"],
                    "gross_exposure": sum(abs(p["quantity"] * p["price"]) for p in account["positions"].values()),
                    "account_observed_epoch": safe._account_observed_at.timestamp(),
                    "reconciliation_observed_epoch": datetime.now(UTC).timestamp(),
                    "reconciliation_clean": int(reconciliation["clean"]),
                    "service_failures": failures, "observed_bars": bars, "completed_cycles": cycles,
                    "observation_started_epoch": datetime.fromisoformat(observation["started_at"]).timestamp(),
                    "observation_minimum_seconds": 28 * 86400,
                    "notification_drill": int((run / "notification-drill.active").exists()),
                }
                engine.ats7_metrics = values
                save(run / "health.json", {"observed_at": datetime.now(UTC).isoformat(),
                     "release_identity": manifest.identity, "engine": engine.runtime_status(),
                     "persistence": safe.persistence_status, "reconciliation": reconciliation,
                     "account": account, "metrics": values, "scope": "SYNTHETIC_LOCAL_PAPER",
                     "status": "HALTED" if values["release_halted"] else "PAPER_RUNNING"}, replace=True)
            except Exception as exc:  # noqa: BLE001 - preserve redacted operational failures
                safe.enable_kill_switch("SUPERVISOR_SNAPSHOT_FAILED:" + type(exc).__name__)
                safe.release_journal.record("service_failed", {"reason": type(exc).__name__})
                stop_requested.set()
                break
            try:
                await asyncio.wait_for(stop_requested.wait(), timeout=5)
            except TimeoutError:
                pass

    watcher = None
    native = None
    code = 0
    try:
        await engine.connect()
        native = asyncio.create_task(engine.run())
        watcher = asyncio.create_task(supervise())
        stopped = asyncio.create_task(stop_requested.wait())
        done, _ = await asyncio.wait({native, stopped, watcher}, return_when=asyncio.FIRST_COMPLETED)
        if native in done and not stop_requested.is_set():
            code = 1
        stop_requested.set()
        if watcher:
            await watcher
        if not native.done():
            safe.release_journal.record("service_stopped", {"reason": "operator_service_stop"})
            await engine.stop()
        await native
    except Exception as exc:  # noqa: BLE001 - service logs exclude provider exception text
        print(json.dumps({"status": "FAILED", "reason": type(exc).__name__}), flush=True)
        code = 1
    finally:
        stop_requested.set()
        if watcher and not watcher.done():
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        await exchange.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        safe.close_persistence()
        save(run / "stopped.json", {"stopped_at": datetime.now(UTC).isoformat(),
             "release_identity": manifest.identity, "returncode": code}, replace=True)
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "run", "status", "halt", "resume", "stop"))
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--port", type=int, default=19149)
    parser.add_argument("--reason")
    parser.add_argument("--evidence", type=Path, action="append", default=[])
    parser.add_argument("--systemd-stop", action="store_true")
    args = parser.parse_args()
    run = args.run_root.resolve()
    if args.action == "freeze":
        freeze(run, args.evidence)
        return 0
    if args.action == "status":
        print((run / "health.json").read_text())
        return 0
    if args.action in {"halt", "resume", "stop"}:
        if args.action == "stop" and args.systemd_stop:
            # systemd also invokes ExecStop after the main process has died.
            # Do not leave a stale stop request for the supervised restart.
            pid = os.environ.get("MAINPID")
            if not pid:
                return 0
            try:
                os.kill(int(pid), 0)
            except ProcessLookupError:
                return 0
        if not args.reason or not args.reason.strip():
            parser.error("--reason is required for a control")
        requested = datetime.now(UTC)
        save(run / "control.json", {"action": args.action, "reason": args.reason,
             "id": requested.strftime("%Y%m%dT%H%M%S%f"), "requested_at": requested.isoformat()},
             replace=args.action == "stop")
        if args.action == "stop":
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                stopped = run / "stopped.json"
                if stopped.exists():
                    receipt = json.loads(stopped.read_text())
                    if datetime.fromisoformat(receipt["stopped_at"]) >= requested:
                        return receipt["returncode"]
                time.sleep(0.25)
            raise TimeoutError("native graceful shutdown was not confirmed")
        return 0
    return asyncio.run(run_paper(run, args.port))


if __name__ == "__main__":
    sys.exit(main())
