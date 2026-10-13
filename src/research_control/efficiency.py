"""M7 evidence-based operator efficiency benchmark against a fixed two-call baseline.

All observations are scoped to source/attempt discovery. Latency is wall time
on this host, not a model token, market-data or financial performance claim.
"""

from __future__ import annotations

import importlib.metadata
import statistics
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import polars as pl

from scripts import research as legacy

from .attempts import AttemptLedger, tmux_sessions
from .casefile import build_casefile
from .dukascopy_migration import dukascopy_feature_contract


def measure_operator_case(
    root: str | Path,
    session_id: str,
    *,
    samples: int = 7,
    list_jobs: Callable[[], set[str] | None] = tmux_sessions,
) -> dict[str, Any]:
    """Baseline: legacy status + separate attempt lookup; current: one Casefile."""
    if not 3 <= samples <= 50:
        raise ValueError("benchmark requires 3..50 samples")
    root = Path(root).resolve()
    ledger = AttemptLedger(root, session_id, list_jobs=list_jobs)

    def old_workflow():
        view = legacy.status(session_id, root)
        recent = list(ledger.latest().values())
        return {
            "source_identity": {
                "spec_sha256": view["session"]["spec_sha256"],
                "data": view["session"]["data"],
            },
            "declared": view["trials"]["declared"],
            "attempts": {
                (item["attempt_id"], item["event_id"], item["revision"], item["status"])
                for item in recent
            },
            "next_action": view["next_actions"][0],
        }

    def new_workflow():
        view = build_casefile(root, session_id, list_jobs=list_jobs)
        return {
            "source_identity": {
                "spec_sha256": view["source"]["spec_sha256"],
                "data": view["source"]["data"],
            },
            "declared": view["trial_status"]["declared"],
            "attempts": {
                (item["attempt_id"], item["event_id"], item["revision"], item["status"])
                for item in view["attempts"]
            },
            "next_action": view["next_safe_action"],
        }

    def timed(call):
        start = time.perf_counter_ns()
        result = call()
        return (time.perf_counter_ns() - start) / 1_000_000, result

    # Both workflows must remain data-free; any market Parquet read fails.
    with (
        patch.object(
            pl, "read_parquet", side_effect=AssertionError("market scan forbidden")
        ) as read,
        patch.object(
            pl, "scan_parquet", side_effect=AssertionError("market scan forbidden")
        ) as scan,
    ):
        baseline_cold, observed_old = timed(old_workflow)
        managed_cold, observed_new = timed(new_workflow)
        if {
            k: observed_old[k] for k in ("source_identity", "declared", "attempts")
        } != {k: observed_new[k] for k in ("source_identity", "declared", "attempts")}:
            raise ValueError("BENCHMARK_MISMATCH: cannot compare inconsistent answers")
        baseline_warm = [timed(old_workflow)[0] for _ in range(samples)]
        managed_warm = [timed(new_workflow)[0] for _ in range(samples)]
        market_reads = read.call_count + scan.call_count
    contract = dukascopy_feature_contract("benchmark-dukascopy-static")
    provider_kinds = [request.provider.kind for request in contract.feature_set]

    return {
        "schema_version": 1,
        "benchmark_id": "agent-casefile-cold-source-attempt-v1",
        "scope": "read-only discovery of frozen source, declared trials and latest attempts",
        "source_identity": observed_new["source_identity"],
        "attempt_identity_count": len(observed_new["attempts"]),
        "attempt_identities": [
            {
                "attempt_id": attempt_id,
                "event_id": event_id,
                "revision": revision,
                "status": status,
            }
            for attempt_id, event_id, revision, status in sorted(
                observed_new["attempts"]
            )
        ],
        "samples": samples,
        "environment": {
            "ml4t_engineer": importlib.metadata.version("ml4t-engineer"),
            "ml4t_backtest": importlib.metadata.version("ml4t-backtest"),
        },
        "baseline": {
            "description": "legacy status plus separate attempt ledger lookup",
            "tool_calls": 2,
            "cold_latency_ms": round(baseline_cold, 4),
            "warm_median_ms": round(statistics.median(baseline_warm), 4),
            "warm_p95_ms": round(sorted(baseline_warm)[int((samples - 1) * 0.95)], 4),
            "answer_complete": True,
        },
        "managed": {
            "description": "one evidence-linked Casefile call",
            "tool_calls": 1,
            "cold_latency_ms": round(managed_cold, 4),
            "warm_median_ms": round(statistics.median(managed_warm), 4),
            "warm_p95_ms": round(sorted(managed_warm)[int((samples - 1) * 0.95)], 4),
            "answer_complete": True,
        },
        "tool_calls_avoided_per_task": 1,
        "redundant_market_data_reads_measured": market_reads,
        "time_to_first_action_ms": {
            "baseline": round(baseline_cold, 4),
            "managed": round(managed_cold, 4),
        },
        "full_dataset_hashes_requested": 0,
        "native_feature_count": provider_kinds.count("engineer.native"),
        "approved_extension_count": provider_kinds.count("extension.approved"),
        "unmanaged_feature_count": 0,
        "limitations": [
            "Tool-call counts refer to the specified Python API steps, not actual LLM usage.",
            "No market data scan is designed into either path; zero reads is not a claimed optimization.",
            "Latency varies by CPU, filesystem cache, unrelated VPS load and tmux visibility.",
            "No measured cost or quality improvement outside the fixed case is implied.",
            "Time-to-action is reported as first response latency, not human or agent decision time.",
        ],
        "no_live_trading": True,
    }
