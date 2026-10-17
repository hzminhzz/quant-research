"""Issue #47: metric projection, fixed labels, read-only endpoint and alert rules."""
from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from src.ml4t_native_metrics import (
    AUDIT_EVENTS,
    MAX_AUDIT_BYTES,
    STATES,
    create_readonly_metrics_server,
    render_native_metrics,
)

ROOT = Path(__file__).resolve().parents[1]
OPS = ROOT / "ops" / "ml4t_monitoring"


def sample(*, state="running", health="ok", connected=True, recon=True,
           state_error=None, journal_error=None, event_count=0, age=5.0):
    runtime = {
        "runtime_state": state,
        "health": health,
        "broker_connected": connected,
        "last_bar_received_at": "2026-01-01T00:00:00Z" if age is not None else None,
        "last_bar_age_seconds": age,
        "recovery_attempts": 2 if state == "recovering" else 0,
        "terminal_failure_reason": "recovery_exhausted:feed_silent" if state == "failed" else None,
        "event_count": event_count, "bar_count": 7, "error_count": 0,
        "continuity": {
            "accepted_count": 7, "duplicate_count": 1,
            "violation_count": 2, "tracked_streams": 1,
            "last_sequences": {"account-SECRET": 4321},
        },
    }
    engine = MagicMock()
    engine.runtime_status.return_value = runtime
    engine.operational_events = ({"event": "engine_recovery_attempt", "order_id": "ORDER-SECRET"},)
    engine.feed_silence_seconds = 120.0
    safe = MagicMock()
    safe.persistence_status = {
        "state_error": state_error, "journal_error": journal_error,
        "execution_identity_validated": True,
    }
    safe.reconciliation_report = (
        None if recon is None else {
            "clean": recon, "unexpected_positions": {"PRIVATE-ASSET": 0.5} if not recon else {},
            "missing_positions": {}, "quantity_mismatches": {},
            "missing_pending_orders": [], "unexpected_pending_orders": [],
            "unresolved_replacement_gaps": {},
        }
    )
    safe.config.kill_switch_enabled = False
    safe.config.journal_file = None
    safe.config.state_file = "/tmp/nonexistent-unique-monitoring-fixture.json"
    safe.submit_order_async.side_effect = AssertionError("metrics may not execute orders")
    safe.cancel_order_async.side_effect = AssertionError("metrics may not cancel orders")
    safe.close_position_async.side_effect = AssertionError("metrics may not flatten")
    return engine, safe


def metric_value(output, name, labels=""):
    prefix = f"ml4t_live_{name}{labels} "
    values = [float(line[len(prefix):]) for line in output.splitlines() if line.startswith(prefix)]
    assert len(values) == 1, (prefix, values)
    return values[0]


@pytest.mark.parametrize("state", STATES)
def test_native_runtime_states_are_fixed_and_mutually_exclusive(state):
    engine, safe = sample(state=state)
    output = render_native_metrics(engine, safe)
    assert metric_value(output, "snapshot_ok") == 1
    for candidate in STATES:
        assert metric_value(output, "engine_state", f'{{state="{candidate}"}}') == int(candidate == state)
    assert metric_value(output, "state_known") == 1
    assert "account-SECRET" not in output
    assert "PRIVATE-ASSET" not in output
    assert "ORDER-SECRET" not in output
    safe.submit_order_async.assert_not_called()
    safe.cancel_order_async.assert_not_called()
    safe.close_position_async.assert_not_called()


@pytest.mark.parametrize(("state", "health", "connected", "metric", "label"), [
    ("degraded", "feed_silent", True, "engine_health", '{health="feed_silent"}'),
    ("recovering", "broker_disconnected", False, "engine_health", '{health="broker_disconnected"}'),
    ("failed", "failed", False, "recovery_exhausted", ""),
])
def test_synthetic_failure_statuses_map_to_alert_input(state, health, connected, metric, label):
    engine, safe = sample(state=state, health=health, connected=connected)
    output = render_native_metrics(engine, safe)
    assert metric_value(output, metric, label) == 1
    assert metric_value(output, "broker_connected") == int(connected)
    assert metric_value(output, "feed_silence_threshold_seconds") == 120


def test_old_exhaustion_event_does_not_stick_after_recovered_session():
    engine, safe = sample(state="running")
    engine.operational_events = ({"event": "engine_recovery_exhausted"},)
    assert metric_value(render_native_metrics(engine, safe), "recovery_exhausted") == 0
    engine.runtime_status.return_value["runtime_state"] = "failed"
    assert metric_value(render_native_metrics(engine, safe), "recovery_exhausted") == 1


def test_continuity_reconciliation_persistence_and_missing_data_are_not_optimistic():
    engine, safe = sample(recon=False, state_error="PersistenceSafetyError", journal_error="AuditJournalError")
    output = render_native_metrics(engine, safe)
    assert metric_value(output, "reconciliation_known") == 1
    assert metric_value(output, "reconciliation_clean") == 0
    assert metric_value(output, "reconciliation_unexpected_positions") == 1
    assert metric_value(output, "state_error") == 1
    assert metric_value(output, "journal_error") == 1
    assert metric_value(output, "continuity_violation_count") == 2
    assert metric_value(output, "continuity_duplicate_count") == 1
    assert metric_value(output, "audit_evidence_available") == 0
    safe.reconciliation_report = None
    no_report = render_native_metrics(engine, safe)
    assert metric_value(no_report, "reconciliation_known") == 0
    assert "ml4t_live_reconciliation_clean " not in no_report
    engine.runtime_status.side_effect = RuntimeError("API-SECRET - bad state")
    broken = render_native_metrics(engine, safe)
    assert metric_value(broken, "snapshot_ok") == 0
    assert "API-SECRET" not in broken


def test_native_audit_projection_has_fixed_labels_and_evidence_contract(tmp_path):
    engine, safe = sample()
    file = tmp_path / "real-native-journal.jsonl"
    entries = [
        {"event": "order_submitted", "payload": {"status": "filled", "order_id": "PRIVATE-ORDER"}},
        {"event": "order_submitted", "payload": {"status": "pending", "asset": "PRIVATE-ASSET"}},
        {"event": "order_rejected", "payload": {"reason": "PRIVATE-REASON"}},
        {"event": "reconciliation_blocked_startup", "payload": {"uid": "PRIVATE-UID"}},
    ]
    file.write_text("".join(json.dumps(e) + "\n" for e in entries))
    safe.config.journal_file = str(file)
    output = render_native_metrics(engine, safe)
    assert metric_value(output, "audit_evidence_available") == 1
    assert metric_value(output, "audit_event_count", '{event="order_submitted"}') == 2
    assert metric_value(output, "audit_event_count", '{event="order_rejected"}') == 1
    assert metric_value(output, "audit_paper_filled_count") == 1
    for forbidden in ("PRIVATE-ORDER", "PRIVATE-ASSET", "PRIVATE-UID", "PRIVATE-REASON"):
        assert forbidden not in output
    assert sum('ml4t_live_audit_event_count{event="' in l for l in output.splitlines()) == len(AUDIT_EVENTS)
    file.write_bytes(b"{" + b"x" * MAX_AUDIT_BYTES + b"}\n")
    blocked = render_native_metrics(engine, safe)
    assert metric_value(blocked, "audit_evidence_available") == 0
    assert "ml4t_live_audit_event_count{" not in blocked


def test_http_endpoint_is_loopback_read_only_and_never_changes_broker_state():
    engine, safe = sample()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = create_readonly_metrics_server(engine, safe, port=port)
    assert server.server_address[0] == "127.0.0.1"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{port}"
        with urllib.request.urlopen(base + "/metrics", timeout=2) as res:
            assert res.status == 200
            assert b"ml4t_live_engine_state" in res.read()
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(
                urllib.request.Request(base + "/metrics", method="POST"), timeout=2,
            )
        assert err.value.code == 405
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(base + "/submit", timeout=2)
        assert err.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    safe.submit_order_async.assert_not_called()
    safe.cancel_order_async.assert_not_called()
    safe.close_position_async.assert_not_called()


def test_real_native_ml4t_objects_are_projected_without_broker_mutation(tmp_path):
    """Real 0.1.2 SafeBroker + LiveEngine, synthetic Bybit client, no orders."""
    import asyncio

    from tests.test_bybit_native_recovery import FaultFeed, build, finish

    feed = FaultFeed(kind="silent")
    engine, broker, client, _ = build(tmp_path, feed)
    async def inspect():
        await engine.connect()
        try:
            output = render_native_metrics(engine, engine.broker)
            assert metric_value(output, "snapshot_ok") == 1
            assert metric_value(output, "engine_state", '{state="ready"}') == 1
            assert metric_value(output, "identity_verified") == 1
            assert metric_value(output, "reconciliation_clean") == 1
            assert metric_value(output, "audit_evidence_available") == 1
            assert metric_value(output, "audit_event_count", '{event="order_submitted"}') == 0
        finally:
            await engine.stop()

    try:
        asyncio.run(inspect())
    finally:
        finish(engine, broker)
    client.create_order.assert_not_awaited()
    client.cancel_order.assert_not_awaited()
    client.edit_order.assert_not_awaited()


def test_alert_rule_coverage_and_dashboard_promql_use_projected_metrics():
    rules = yaml.safe_load((OPS / "prometheus" / "alerts.yml").read_text())
    alerts = {a["alert"]: a for group in rules["groups"] for a in group["rules"]}
    assert {
        "ML4TExporterDown", "ML4TFeedSilent", "ML4TBrokerDisconnected",
        "ML4TRecoveryExhausted", "ML4TReconciliationBlocked",
        "ML4TPersistenceOrJournalFailed", "ML4TNodeExporterDown",
        "ML4TVPSMemoryStress", "ML4TVPSDiskStress", "ML4TVPSCPUStress",
    } <= alerts.keys()
    assert 'ml4t_live_engine_health{health="feed_silent"} == 1' in alerts["ML4TFeedSilent"]["expr"]
    assert "ml4t_live_recovery_exhausted == 1" == alerts["ML4TRecoveryExhausted"]["expr"]
    assert "ml4t_live_journal_error == 1" in alerts["ML4TPersistenceOrJournalFailed"]["expr"]
    assert "node_memory_MemAvailable_bytes" in alerts["ML4TVPSMemoryStress"]["expr"]
    for a in alerts.values():
        assert a["annotations"]["action"] and a["labels"]["severity"] in {"critical", "warning"}
    dashboard = json.loads((OPS / "grafana" / "native_safety_dashboard.json").read_text())
    assert len(dashboard["panels"]) >= 15
    exprs = [p["targets"][0]["expr"] for p in dashboard["panels"]]
    for target in ("ml4t_live_engine_state", "ml4t_live_broker_connected",
                   "ml4t_live_reconciliation_clean", "ml4t_live_audit_event_count"):
        assert target in exprs
    assert all("PRIVATE" not in str(p) for p in dashboard["panels"])
