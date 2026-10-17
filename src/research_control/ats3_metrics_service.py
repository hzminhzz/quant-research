"""Standalone, read-only Prometheus exporter for ATS-3 qualification state."""
from __future__ import annotations

import argparse
import json
import signal
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

DEFAULT_STATE_DIR = Path("/home/quant/.local/state/quant-research")
EVENTS = (
    "order_submitted", "order_rejected", "shadow_order_filled",
    "kill_switch_activated", "reconciliation_mismatch",
    "reconciliation_blocked_startup",
)
STATES = ("stopped", "preflight", "connecting_broker", "reconciling", "starting_feed", "ready", "starting_strategy", "running", "degraded", "recovering", "stopping", "failed")
HEALTH = ("ok", "ready", "stopped", "failed", "waiting_for_data", "idle_market_closed", "feed_silent", "broker_disconnected")


def render_metrics(state_dir: Path, state: str = "stopped") -> str:
    """Project bounded local health/evidence files into Prometheus text format."""
    health_path = state_dir / "bybit-demo-native-health.json"
    journal_path = state_dir / "bybit-demo-account-593641111-journal.jsonl"
    lines: list[str] = []

    def metric(name: str, value: float, labels: dict[str, str] | None = None) -> None:
        suffix = "" if not labels else "{" + ",".join(f'{k}="{v}"' for k, v in labels.items()) + "}"
        lines.append(f"ml4t_live_{name}{suffix} {value}")

    try:
        health: dict[str, Any] = json.loads(health_path.read_text(encoding="utf-8"))
        engine, persistence = health["engine"], health["persistence"]
        reconciliation = health["reconciliation"]
        if not all(isinstance(x, dict) for x in (engine, persistence, reconciliation)):
            raise ValueError("invalid state shape")
    except (OSError, ValueError, TypeError, KeyError):
        health = {}
        engine = persistence = reconciliation = {}

    metric("snapshot_ok", int(bool(health)))
    reported_state = state if state in STATES else "stopped"
    for item in STATES:
        metric("engine_state", int(item == reported_state), {"state": item})
    reported_health = "ready" if reported_state == "ready" else "stopped"
    for item in HEALTH:
        metric("engine_health", int(item == reported_health), {"health": item})
    metric("state_known", int(bool(health and engine)))
    metric("health_known", int(bool(health and engine and engine.get("health") in HEALTH)))
    metric("broker_connection_known", int(bool(health and isinstance(engine.get("broker_connected"), bool))))
    metric("broker_connected", int(reported_state == "ready" and engine.get("broker_connected") is True))
    metric("reconciliation_known", int(bool(reconciliation)))
    metric("reconciliation_clean", int(bool(reconciliation and reconciliation.get("clean") is True)))
    for key in ("missing_positions", "unexpected_positions", "missing_pending_orders", "unexpected_pending_orders"):
        value = reconciliation.get(key, 0)
        metric("reconciliation_" + key, len(value) if isinstance(value, (dict, list)) else int(value) if isinstance(value, (int, float)) else 0)
    metric("recovery_exhausted", 0)
    metric("state_error", int(bool(persistence and persistence.get("state_error") is not None)))
    metric("journal_error", int(bool(persistence and persistence.get("journal_error") is not None)))
    metric("identity_verified", int(bool(persistence and persistence.get("execution_identity_validated") is True)))

    paper_filled = 0
    counts = dict.fromkeys(EVENTS, 0)
    journal_ok = False
    journal_lines = 0
    try:
        with journal_path.open(encoding="utf-8") as journal:
            for line in journal:
                entry = json.loads(line)
                if not isinstance(entry, dict) or not isinstance(
                    entry.get("event"), str
                ):
                    raise TypeError("invalid journal entry")
                journal_lines += 1
                if entry["event"] in counts:
                    counts[entry["event"]] += 1
                if entry["event"] == "paper_order_filled":
                    paper_filled += 1
        journal_ok = True
    except (OSError, ValueError, UnicodeError):
        pass
    if not journal_ok:
        journal_lines = 0
    for event, count in counts.items():
        metric("audit_event_count", count, {"event": event})
    metric("audit_evidence_available", int(journal_ok))
    metric("audit_paper_filled_count", paper_filled)
    metric("native_bar_count", 0)
    metric("native_event_count", journal_lines)
    metric("audit_mode", 1)
    metric("historical_archive", 1)
    checked_at = health.get("checked_at")
    try:
        snapshot_time = datetime.fromisoformat(
            checked_at.replace("Z", "+00:00")
            if isinstance(checked_at, str)
            else ""
        )
        if snapshot_time.tzinfo is None:
            snapshot_time = snapshot_time.replace(tzinfo=UTC)
    except (AttributeError, TypeError, ValueError):
        try:
            snapshot_time = datetime.fromtimestamp(health_path.stat().st_mtime, UTC)
        except OSError:
            snapshot_time = datetime.now(UTC)
    metric("audit_snapshot_age_seconds", max(0.0, (datetime.now(UTC) - snapshot_time).total_seconds()))
    return "\n".join(lines) + "\n"


def create_ats3_metrics_server(
    port: int = 19147, state_dir: Path | None = None, state: str = "stopped"
) -> HTTPServer:
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port must be 1..65535")
    directory = Path(state_dir) if state_dir is not None else DEFAULT_STATE_DIR

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/metrics":
                self.send_error(404)
                return
            body = render_metrics(directory, state).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            self.send_error(405)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return HTTPServer(("127.0.0.1", port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=19147)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    parser.add_argument("--state", choices=("stopped", "ready"), default="stopped")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.once:
        print(render_metrics(args.state_dir, args.state))
        return
    server = create_ats3_metrics_server(args.port, args.state_dir, args.state)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt))
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
