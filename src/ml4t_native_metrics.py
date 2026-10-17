"""Read-only, bounded Prometheus projection of native ml4t-live==0.1.2 state.

This module owns no trading state, no risk logic and no broker methods. Use in
the same *already authorized* LiveEngine process; importing it starts nothing.
"""
from __future__ import annotations

import json
import math
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

STATES = (
    "stopped", "preflight", "connecting_broker", "reconciling",
    "starting_feed", "ready", "starting_strategy", "running",
    "degraded", "recovering", "stopping", "failed",
)
HEALTH = (
    "ok", "ready", "stopped", "failed", "waiting_for_data",
    "idle_market_closed", "feed_silent", "broker_disconnected",
)
AUDIT_EVENTS = (
    "order_submitted", "order_rejected", "shadow_order_filled",
    "kill_switch_activated", "reconciliation_mismatch",
    "reconciliation_blocked_startup",
)
MAX_AUDIT_BYTES = 1_048_576


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _metric(name: str, value: float, *, labels: dict[str, str] | None = None) -> str:
    suffix = ""
    if labels:
        # Only hard-coded enumerations flow into labels. No IDs/symbols/strings from providers.
        suffix = "{" + ",".join(f'{key}="{val}"' for key, val in labels.items()) + "}"
    return f"ml4t_live_{name}{suffix} {value:g}"


def _journal_path(safe: Any) -> Path:
    cfg = safe.config
    if cfg.journal_file is not None:
        return Path(cfg.journal_file)
    state = Path(cfg.state_file)
    return state.with_name(f"{state.stem}-journal{state.suffix or '.json'}l")


_AUDIT_CACHE: dict[str, dict] = {}


def _native_audit_counts(safe: Any) -> dict[str, int] | None:
    """Incremental read-only count of complete native records; unknown until caught up.

    The cache is expendable telemetry, never order/risk authority. At most 1 MiB
    is read per scrape. Restart/backlog remains explicitly unknown until replayed.
    """
    path = _journal_path(safe)
    key = str(path)
    try:
        stat = path.stat()
        cached = _AUDIT_CACHE.get(key)
        identity = (stat.st_dev, stat.st_ino)
        if cached is None or cached["identity"] != identity or stat.st_size < cached["offset"]:
            cached = {"identity": identity, "offset": 0,
                      "counts": {**dict.fromkeys(AUDIT_EVENTS, 0), "paper_order_filled": 0}}
            _AUDIT_CACHE[key] = cached
        with path.open("rb") as stream:
            stream.seek(cached["offset"])
            raw = stream.read(MAX_AUDIT_BYTES)
        complete = raw.rfind(b"\n") + 1
        if raw and not complete:
            return None
        counts = dict(cached["counts"])
        for line in raw[:complete].splitlines():
            row = json.loads(line)
            entry = row.get("entry", row)
            if not isinstance(entry, dict) or not isinstance(entry.get("event"), str):
                return None
            kind = entry["event"]
            if kind in counts:
                counts[kind] += 1
            if kind == "order_submitted" and entry.get("payload", {}).get("status") == "filled":
                counts["paper_order_filled"] += 1
        cached["counts"] = counts
        cached["offset"] += complete
        return counts if cached["offset"] == stat.st_size else None
    except (OSError, ValueError, UnicodeError, TypeError, AttributeError):
        _AUDIT_CACHE.pop(key, None)
        return None


def render_native_metrics(engine: Any, safe: Any) -> str:
    """Pure read-only projection. Unknown evidence stays unknown (never PASS).

    Only public native status, persistence, reconciliation, retained operational
    events and the native on-disk audit journal are observed. No order method
    may be called from this projection.
    """
    lines = ["# HELP ml4t_live_snapshot_ok Native state could be read for this scrape.",
             "# TYPE ml4t_live_snapshot_ok gauge"]
    try:
        status = engine.runtime_status()
        persistence = safe.persistence_status
        reconciliation = safe.reconciliation_report
        events = engine.operational_events
        if not isinstance(status, dict) or not isinstance(persistence, dict):
            raise TypeError("native runtime status unavailable")
        if reconciliation is not None and not isinstance(reconciliation, dict):
            raise ValueError("reconciliation report unavailable")
    except Exception:  # noqa: BLE001 - monitoring must not crash or leak private exceptions
        return "\n".join([*lines, _metric("snapshot_ok", 0), ""])

    lines.append(_metric("snapshot_ok", 1))
    state = status.get("runtime_state")
    health = status.get("health")
    for item in STATES:
        lines.append(_metric("engine_state", int(state == item), labels={"state": item}))
    for item in HEALTH:
        lines.append(_metric("engine_health", int(health == item), labels={"health": item}))
    lines.append(_metric("state_known", int(state in STATES)))
    lines.append(_metric("health_known", int(health in HEALTH)))

    connected = status.get("broker_connected")
    lines.append(_metric("broker_connection_known", int(isinstance(connected, bool))))
    if isinstance(connected, bool):
        lines.append(_metric("broker_connected", int(connected)))

    for field, out in (
        ("last_bar_age_seconds", "last_bar_age_seconds"),
        ("recovery_attempts", "recovery_attempts"),
        ("event_count", "native_event_count"),
        ("bar_count", "native_bar_count"),
        ("error_count", "native_error_count"),
    ):
        value = _number(status.get(field))
        if value is not None and value >= 0:
            lines.append(_metric(out, value))
    lines.append(_metric("bar_seen", int(status.get("last_bar_received_at") is not None)))
    silence_limit = _number(getattr(engine, "feed_silence_seconds", None))
    if silence_limit is not None and silence_limit > 0:
        lines.append(_metric("feed_silence_threshold_seconds", silence_limit))

    continuity = status.get("continuity")
    if isinstance(continuity, dict):
        for field in ("accepted_count", "duplicate_count", "violation_count", "tracked_streams"):
            value = _number(continuity.get(field))
            if value is not None and value >= 0:
                lines.append(_metric(f"continuity_{field}", value))

    exhausted = str(status.get("terminal_failure_reason", "")).startswith("recovery_exhausted:")
    # Retained events are historical. A new RUNNING session must not inherit
    # an old exhausted alert after an operator-approved successful restart.
    if not exhausted and state == "failed":
        exhausted = any(
            isinstance(e, dict) and e.get("event") == "engine_recovery_exhausted"
            for e in events
        )
    lines.append(_metric("recovery_exhausted", int(exhausted)))
    lines.append(_metric("reconciliation_known", int(reconciliation is not None)))
    if reconciliation is not None:
        lines.append(_metric("reconciliation_clean", int(reconciliation.get("clean") is True)))
        for field in (
            "missing_positions", "unexpected_positions", "quantity_mismatches",
            "missing_pending_orders", "unexpected_pending_orders", "unresolved_replacement_gaps",
        ):
            value = reconciliation.get(field)
            if isinstance(value, (list, dict)):
                lines.append(_metric(f"reconciliation_{field}", len(value)))

    lines.append(_metric("state_error", int(persistence.get("state_error") is not None)))
    lines.append(_metric("journal_error", int(persistence.get("journal_error") is not None)))
    lines.append(_metric("identity_verified", int(persistence.get("execution_identity_validated") is True)))
    # Distinguish the public config flag from the non-public persisted kill switch.
    lines.append(_metric("configured_kill_switch", int(safe.config.kill_switch_enabled is True)))

    counts = _native_audit_counts(safe)
    lines.append(_metric("audit_evidence_available", int(counts is not None)))
    if counts is not None:
        for kind in AUDIT_EVENTS:
            lines.append(_metric("audit_event_count", counts[kind], labels={"event": kind}))
        lines.append(_metric("audit_paper_filled_count", counts["paper_order_filled"]))

    # ATS7 adds only numeric observations from the same native engine loop.
    # This server never reads the decision SQLite connection from another thread.
    for key, value in getattr(engine, "ats7_metrics", {}).items():
        number = _number(value)
        if key in {"release_halted", "unknown_orders", "pending_orders", "gross_exposure",
                   "account_observed_epoch", "service_failures", "observed_bars", "completed_cycles",
                   "observation_started_epoch", "observation_minimum_seconds", "notification_drill",
                   "reconciliation_observed_epoch", "reconciliation_clean"} and number is not None:
            lines.append(f"ats7_{key} {number:.17g}")
    return "\n".join([*lines, ""])


def create_readonly_metrics_server(engine: Any, safe: Any, *, port: int) -> HTTPServer:
    """Create loopback-only GET /metrics endpoint; caller owns server lifecycle.

    This is *not* a second runtime service or remote account controller.
    It does not start a thread, schedule a task, or connect to any broker.
    """
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("explicit TCP port 1..65535 required")

    class MetricsHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/metrics":
                self.send_error(404)
                return
            body = render_native_metrics(engine, safe).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            self.send_error(405)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return HTTPServer(("127.0.0.1", port), MetricsHandler)
