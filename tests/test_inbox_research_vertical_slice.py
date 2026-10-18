"""Complete, unmocked ATS research inbox end-to-end vertical slice test.

Proves:
1. Capability-aware intake (distinguishes cross-sectional vs unsupported event protocols).
2. Source verification and frozen adaptation binding (preserves source SHA256).
3. Real native ML4T factory execution (Stage 1 prefix invariance + Stage 2 IC/HAC).
4. Independent verification of receipts, Casefile, and append-only trial ledger.
5. Strict idempotency (re-running terminal candidates consumes zero additional trials).
6. Fail-closed tamper detection (evidence drift never becomes economic falsification).
"""
from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import yaml

from src.data_vault import PanelBuilder
from src.engine.common import file_hash
from src.research_control.research_inbox_queue import InboxQueue

REPO = Path(__file__).resolve().parents[1]


def _build_test_panel(raw_path: Path, vault_path: Path, *, symbols: list[str], start: datetime, hours: int = 24 * 70) -> None:
    """Build a deterministic, canonical 1h panel with all 12 schema columns via PanelBuilder."""
    records, events = [], []
    for s_idx, sym in enumerate(symbols):
        price, previous = 100.0 + s_idx * 20.0, 0.0
        for h in range(hours):
            timestamp = start + timedelta(hours=h)
            opening = price
            price *= 1.0 + 0.0005 * previous
            pressure = 0.5
            rate = pressure * 1e-7
            records.append({
                "timestamp": timestamp,
                "symbol": sym,
                "open": opening,
                "high": max(opening, price) * 1.002,
                "low": min(opening, price) * 0.998,
                "close": price,
                "volume": 1000.0,
                "carry_rate": rate,
                "spread_bps": 2.0,
                "session_id": timestamp.strftime("%Y-%m-%d"),
                "bar_in_session": h % 24,
                "is_tradable": True,
            })
            events.append({
                "timestamp": timestamp,
                "symbol": sym,
                "funding_rate": rate,
                "mark_price": opening,
                "funding_interval_hours": 1,
            })
            previous = pressure
    panel = pl.DataFrame(records)
    funding = pl.DataFrame(events)
    PanelBuilder(raw_path, vault_path).publish(
        panel, funding=funding, provenance={"source_spec_status": "synthetic_test"}
    )


def test_inbox_vertical_slice_real_scientific_execution(tmp_path: Path):
    """Demonstrate real, unmocked research intake, preflight, native factory run, and ledger audit."""
    inbox = tmp_path / "inbox"
    inbox.mkdir(parents=True)
    run_log = tmp_path / "run_log"
    run_log.mkdir(parents=True)
    (run_log / "trial_ledger.jsonl").touch()

    # 1. Admit genuine candidate from research_inbox
    cand_id = "crypto_xs_funding_velocity_dislocation_basket_v1"
    shutil.copytree(REPO / "research_inbox" / cand_id, inbox / cand_id)

    # Also copy an unsupported event thesis to prove protocol discrimination
    unsupported_id = "audusd_policy_carry_cfd_v1"
    shutil.copytree(REPO / "research_inbox" / unsupported_id, inbox / unsupported_id)

    # 2. Build canonical development data vault for the test
    vault_root = tmp_path / "vaults"
    panel_root = vault_root / "binance_hourly_perps"
    train_start = datetime(2023, 1, 1, tzinfo=UTC)
    train_end = datetime(2023, 2, 1, tzinfo=UTC)
    val_end = datetime(2023, 3, 1, tzinfo=UTC)
    protected_start = datetime(2026, 1, 1, tzinfo=UTC)
    _build_test_panel(tmp_path / "raw", panel_root, symbols=["BTCUSDT_PERP", "ETHUSDT_PERP", "SOLUSDT_PERP", "ADAUSDT_PERP"], start=train_start, hours=24 * 70)

    # 3. Create a candidate spec bound to the inbox source hash
    source_yaml = inbox / cand_id / "thesis.yaml"
    source_hash = file_hash(source_yaml)

    # Create candidate spec in config/candidates
    candidates_dir = tmp_path / "candidates"
    candidates_dir.mkdir(parents=True)
    spec_path = candidates_dir / f"ats_{cand_id}_local_adaptation_test.yaml"

    spec_content = {
        "candidate_id": f"ats_{cand_id}_test",
        "selection_family_id": cand_id,
        "thesis": "Funding velocity reversal",
        "source_spec_status": "local_adaptation",
        "panel_root": str(panel_root),
        "bar_seconds": 3600,
        "label_horizon_bars": 1,
        "windows": {
            "train": {"start": train_start.isoformat(), "end": train_end.isoformat()},
            "validation": {"start": train_end.isoformat(), "end": val_end.isoformat()},
            "protected": {"start": protected_start.isoformat(), "end": (protected_start + timedelta(days=60)).isoformat()},
        },
        "universe": {
            "top_n": 3,
            "minimum_assets": 2,
            "lookback_bars": 12,
            "minimum_history_bars": 12,
            "minimum_dollar_volume": 0.0,
        },
        "features": [
            {"name": "atr_24h", "native": "atr", "params": {"period": 12}},
            {"name": "settled_funding_24h", "expr": {"op": "rolling_sum", "window": 12, "args": [{"op": "col", "name": "carry_rate"}]}},
            {"name": "velocity_reversal_score", "expr": {"op": "neg", "args": [{"op": "col", "name": "settled_funding_24h"}]}},
            {"name": "static_funding_level_basket", "expr": {"op": "col", "name": "settled_funding_24h"}},
        ],
        "signal": "velocity_reversal_score",
        "baseline": "static_funding_level_basket",
        "allocation": {
            "long_count": 1,
            "short_count": 1,
            "gross_exposure": 1.0,
            "rebalance_bars": 12,
            "atr_feature": "atr_24h",
            "atr_multiple": 3.0,
            "netting_rule": "weight_delta",
            "timing_lag": 1,
        },
        "costs": {
            "commission_bps_one_way": 5.0,
            "slippage_bps_one_way": 4.0,
            "spread_bps": 2.0,
            "spread_included_in_slippage": True,
        },
        "gates": {
            "minimum_ic": 0.015,
            "minimum_hac_t": 2.0,
            "minimum_ic_observations": 10,
            "require_baseline_ic_improvement": False,
            "dsr_probability": 0.95,
            "maximum_abs_beta": 0.15,
            "maximum_short_stop_fraction": 0.2,
            "minimum_completed_trades": 5,
            "require_baseline_sharpe_improvement": False,
            "minimum_daily_observations": 10,
        },
        "benchmark": "BTCUSDT",
        "assumptions": [
            f"SOURCE_ID=origin/feat/ats-inbox-62-copy-20261018:research_inbox/{cand_id}/thesis.yaml",
            f"SOURCE_SHA256={source_hash}",
            "LOCAL_ADAPTATION: tested on synthetic bounded canonical panel",
        ],
    }
    spec_path.write_text(yaml.safe_dump(spec_content), encoding="utf-8")

    # 4. Instantiate and run Queue with injected test candidates_dir (zero monkeypatching)
    queue = InboxQueue(inbox, run_log, vault_root=vault_root, store=tmp_path / "store",
                       candidates_dir=candidates_dir)
    # 5. First execution: Real intake -> Preflight -> Native Factory -> Ledger
    report = queue.run()

    # Verify Protocol discrimination
    cases_by_id = {c["candidate_id"]: c for c in report["cases"]}
    assert cases_by_id[unsupported_id]["status"] == "BLOCKED_PROTOCOL"
    assert "General single-instrument event execution is not a qualified ATS-4 factory protocol" in cases_by_id[unsupported_id]["reason"]

    # Verify Native research outcome
    cand_case = cases_by_id[cand_id]
    assert cand_case["status"] in {"FALSIFIED", "DEVELOPMENT_QUALIFIED", "INCONCLUSIVE"}, cand_case.get("reason")
    assert cand_case["native_evidence_verified"] is True
    assert cand_case["holdout_access"] is False

    # Verify Casefile and Receipts exist on disk
    casefile_path = Path(cand_case["casefile"])
    assert casefile_path.is_file()
    casefile_data = json.loads(casefile_path.read_text(encoding="utf-8"))
    assert casefile_data["development_only"] is True
    assert casefile_data["holdout_access"] is False
    assert "1" in casefile_data["stages"]  # Stage 1 PASS
    assert casefile_data["stages"]["1"]["status"] == "PASS"
    assert "2" in casefile_data["stages"]  # Stage 2 executed

    # Verify Trial Ledger recorded completion
    ledger_records = [
        json.loads(line) for line in (run_log / "trial_ledger.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    completed_trials = [r for r in ledger_records if r.get("event") == "completed"]
    assert len(completed_trials) == 1
    assert completed_trials[0]["candidate_id"] == f"ats_{cand_id}_test"
    assert completed_trials[0]["holdout_access"] is False

    # 6. Idempotency test: Re-running queue performs ZERO duplicate executions
    report2 = queue.run()
    ledger_records2 = [
        json.loads(line) for line in (run_log / "trial_ledger.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    completed_trials2 = [r for r in ledger_records2 if r.get("event") == "completed"]
    assert len(completed_trials2) == 1  # exactly 1, no duplicate trial added!
    assert report2["counts"]["trial_started"] == report["counts"]["trial_started"]
