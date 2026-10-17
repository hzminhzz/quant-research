"""Frozen, identical event path for three feasible ATS-6 allocation policies."""
from __future__ import annotations

from collections import Counter
from datetime import timedelta

from scripts.ats6_fixtures import (
    START,
    create_fixture,
    fill,
    intent,
    observe,
    publish,
    signed,
)

# Fixed before any comparison is run. These are potential shadow events, not
# generated prices, backtest fills or realized profit.
STREAM = [
    {"second": 1, "kind": "intent", "id": "t1", "lots": 4, "family": "trend"},
    {"second": 2, "kind": "intent", "id": "t2", "lots": 4, "family": "reversion"},
    {"second": 3, "kind": "intent", "id": "t3", "lots": 5, "family": "trend"},
    {"second": 4, "kind": "open", "id": "t1", "lots": 2},
    {"second": 5, "kind": "cancel", "id": "t1"},
    {"second": 6, "kind": "reconcile", "id": "t1"},
    {"second": 7, "kind": "intent", "id": "t4", "lots": 3, "family": "carry"},
    {"second": 8, "kind": "open", "id": "t2", "lots": 4},
    {"second": 9, "kind": "unknown", "id": "t3"},
    {"second": 10, "kind": "intent", "id": "t5", "lots": 2, "family": "trend"},
    {"second": 11, "kind": "close", "id": "t1", "lots": 2},
    {"second": 12, "kind": "reconcile", "id": "t1"},
    {"second": 13, "kind": "intent", "id": "t6", "lots": 4, "family": "reversion"},
    {"second": 14, "kind": "cancel", "id": "t4"},
    {"second": 15, "kind": "reconcile", "id": "t4"},
    {"second": 16, "kind": "intent", "id": "t7", "lots": 5, "family": "carry"},
    {"second": 17, "kind": "open", "id": "t5", "lots": 1},
    {"second": 18, "kind": "reconcile", "id": "t5"},
    {"second": 19, "kind": "intent", "id": "t8", "lots": 3, "family": "trend"},
    {"second": 20, "kind": "intent", "id": "t9", "lots": 1, "family": "carry"},
]


def run_policy(folder, policy_name, save):
    router, key, epoch = create_fixture(
        folder / "router.db", shared=1400, caps=(700, 1000), costs=(0, 5), policy_name=policy_name)
    sequences, executions, observations = Counter(), {}, []
    for event in STREAM:
        item_id, kind = event["id"], event["kind"]
        now = START + timedelta(seconds=event["second"])
        if kind == "intent":
            item = intent(item_id, event["lots"], family=event["family"])
            a, g = signed(router, key, item)
            result = router.admit(a, g, epoch, now=now)
            if result["status"] == "ADMITTED":
                publish(router, item_id, epoch, now=now)
                router.confirm_publication(item_id, epoch, now=now)
            observations.append({"source_event": event, "result": result})
            continue
        route = router.snapshot()["routes"][item_id]
        if route["account_id"] is None:
            observations.append({"source_event": event, "result": "ORIGINAL_INTENT_SKIPPED"})
            continue
        sequences[item_id] += 1
        seq = sequences[item_id]
        history = executions.setdefault(item_id, [])
        if kind in ("open", "close"):
            e = fill(item_id + "-" + kind + "-" + str(seq), event["lots"], role=kind)
            history.append(e)
            result = observe(router, item_id, epoch, seq, "fill", executions=(e,), now=now)
        elif kind == "reconcile":
            result = observe(router, item_id, epoch, seq, kind, executions=history,
                             terminal="canceled", complete=True, now=now)
        else:
            result = observe(router, item_id, epoch, seq, kind, now=now)
        observations.append({"source_event": event, "result": result})
    save(folder / "source_observations.json", observations)
    return router, {}


def compare(folder, qualify_case, save):
    folder.mkdir()
    save(folder / "frozen_stream.json", {
        "events": STREAM, "units_per_USD": 100, "shared_limit": 1400,
        "account_limits": {"shadow:a": 700, "shadow:b": 1000},
        "cost_allowance_units_per_lot": {"shadow:a": 0, "shadow:b": 5},
        "cost_scope": "conditional synthetic round-trip cost allowance",
        "same_constraints_source_and_timing": True,
        "objective": "safe, explained allocation; no occupancy or PnL optimization",
    })
    reports = {}
    for name in ("cushion", "first_fit", "least_used"):
        case = folder / name
        case.mkdir()
        report = qualify_case(case, lambda p, name=name: run_policy(p, name, save))
        trace = report["trace"]
        account_peaks = {account: max(t["accounts"].get(account, {}).get("used", 0) for t in trace)
                         for account in report["accounts"]}
        families = {family for t in trace for family in t["family_risk"]}
        family_peaks = {family: max(t["family_risk"].get(family, 0) for t in trace) for family in families}
        reports[name] = {
            "accepted": report["accepted"], "skipped": report["skipped"],
            "peak_reserved_plus_recognized_units": report["peak_reserved_plus_recognized"],
            "peak_shared_utilization": report["peak_reserved_plus_recognized"] / 1400,
            "account_peak_risk_units": account_peaks,
            "account_peak_utilization": {k: v / (700 if k == "shadow:a" else 1000)
                                         for k, v in account_peaks.items()},
            "simultaneous_loss_scenario_units_by_family": family_peaks,
            "peak_execution_uncertainty_units": report["peak_unknown"],
            "final_reserved_units": report["shared"]["reserved"],
            "final_recognized_units": report["shared"]["recognized"],
            "conditional_modeled_cost_units": report["conditional_modeled_cost_units"],
            "skip_reasons": report["skip_reasons"],
            "account_rule_impacts": {
                "source_scope": "synthetic static floors and identical account permissions",
                "intraday_barrier_survival": "NOT_CLAIMED",
                "shared_limit_breaches": sum(t["used"] > 1400 for t in trace),
            },
            "incremental_portfolio_return_effect": "INSUFFICIENT_REAL_EXECUTION_SOURCE",
            "realized_profit": None, "oracle_status": report["status"],
        }
    return {
        "status": "FROZEN_FEASIBLE_COMPARISON_COMPLETE",
        "policies": reports,
        "interpretation": "Three predeclared policies on identical synthetic input timing, risk and cost constraints. No winner selected for live use.",
        "co_loss_scope": "Conservative same-family simultaneous stress; no empirical correlation or probability estimate.",
        "source_limitation": "No claim of real fills, realized PnL, costs, portfolio alpha or account-barrier qualification.",
    }
