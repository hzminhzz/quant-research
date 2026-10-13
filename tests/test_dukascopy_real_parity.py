"""VPS-only pinned Dukascopy full-source migration parity.

Run explicitly with -m data on the canonical VPS. Does not modify historical
artifacts; all generated files stay inside pytest tmp_path.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest
import yaml

from src.research_control.dukascopy_migration import (
    SOURCE_SHA256,
    checked_source,
    dukascopy_feature_contract,
    features_for_legacy_rules,
    strict_sessions,
)
from src.research_control.dukascopy_native import _execute_registered_dukascopy
from src.research_control.run_permit import preflight_run
from src.research_session import init_session

CANONICAL = Path("/home/quant/dev/quant/quant-research")
ORIGINAL = CANONICAL / "data/processed/vwap_adx_dukascopy_2026_1m.parquet"
HIST = CANONICAL / "run_log/vwap_pullback_adx_dukascopy_20261012_v1/development"


@pytest.mark.data
def test_pinned_source_managed_native_b1_b2_b3_signal_and_fill_parity(tmp_path):
    if not ORIGINAL.is_file() or not HIST.is_dir():
        pytest.skip("VPS-local Dukascopy original and historical artifacts required")
    root = tmp_path
    (root / "src").mkdir()
    (root / "src/strategy.py").write_text("FROZEN_MANAGED_DUK_V2 = True\n")
    (root / "data").mkdir()
    source_path = root / "data/dukascopy.parquet"
    shutil.copyfile(ORIGINAL, source_path)
    source = checked_source(source_path)
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == SOURCE_SHA256

    session_id = "dukascopy-managed-v2-parity-test"
    contract = dukascopy_feature_contract(session_id)
    (root / "features.yaml").write_text(yaml.safe_dump(contract.model_dump(mode="json")))
    records = (
        ("costs.json", {"commission_bps": 0, "slippage_bps": 0}),
        ("multiplier.json", {"value": 20.0, "unit": "hypothetical USD/point",
                             "source_symbol": "USATECH.IDX/USD"}),
        ("audit.py", None),
    )
    for name, payload in records:
        (root / name).write_text(
            "Independent historical comparison to frozen ledger"
            if payload is None else json.dumps(payload)
        )
    trial_names = [f"{mode}_{case}_development"
                   for mode in ("B1", "B2", "B3")
                   for case in ("gross", "cost", "stress")]
    spec = {
        "session_id": session_id,
        "thesis": "Already-observed Dukascopy B1/B2/B3 engineering parity.",
        "mechanism": "Same source and signals with a managed feature gateway.",
        "falsifier": "Any changed signal, fill, source or clock is a migration failure.",
        "market": "indices",
        "instruments": [{"symbol": "DUK_USATECH", "kind": "cfd",
                         "identity": "Dukascopy price proxy, no CME claim",
                         "session": "08:30-15:14 Chicago",
                         "timezone": "America/Chicago"}],
        "data": [{"id": "dukas", "path": "data/dukascopy.parquet", "role": "prices"}],
        "evaluation": {"development_start": "2026-01-01T00:00:00Z",
                       "development_end": "2026-07-01T00:00:00Z",
                       "holdout_start": "2026-11-01T00:00:00Z"},
        "baseline": "B0 cash; NOT new OOS.",
        "costs": {"commission_bps": 0, "slippage_bps": 0},
        "trials": [{"id": t, "kind": "preregistered",
                    "description": "Migration parity of previously observed outcome"}
                   for t in trial_names],
        "config": "features.yaml",
        "evidence": [name for name, _ in records],
    }
    (root / "session.yaml").write_text(yaml.safe_dump(spec))
    init_session(root / "session.yaml", root)

    features, computation = features_for_legacy_rules(source, contract)
    prepared, qa = strict_sessions(features, date(2026, 1, 1), date(2026, 6, 30))
    assert prepared.height == 41715 and len(qa["accepted_days"]) == 103
    assert len(qa["excluded_days"]) == 20
    last_exit = prepared["timestamp"][-1]
    first_start = prepared["timestamp"][0]
    def identity(name):
        return hashlib.sha256((root / name).read_bytes()).hexdigest()

    for mode in ("B1", "B2", "B3"):
      for case in ("gross", "cost", "stress"):
        cost = {"commission_bps": 0, "slippage_bps": 0, "source": "frozen",
                "evidence_path": "costs.json", "source_sha256": identity("costs.json")}
        multiplier = {"value": 20.0, "unit": "hypothetical USD/point",
                      "instrument_symbol": "USATECH.IDX/USD", "source": "illustrative",
                      "evidence_path": "multiplier.json", "source_sha256": identity("multiplier.json")}
        recipe = {"method": "separate historical signals and ledger", "implementation": "audit.py",
                  "version": "1", "evidence_path": "audit.py", "source_sha256": identity("audit.py"),
                  "checks": ["signals", "native fills", "clock", "source"]}
        budget = {"max_wall_seconds": 300, "max_cpu_seconds": 300,
                  "max_memory_mb": 2048, "max_trials": 1}
        intent = {
            "schema_version": 1, "session_id": session_id,
            "trial_id": f"{mode}_{case}_development",
            "evaluation_start": first_start.isoformat(),
            "evaluation_end": (last_exit + timedelta(minutes=1)).isoformat(),
            "decision_at": (last_exit - timedelta(minutes=1)).isoformat(),
            "exit_at": last_exit.isoformat(),
            "required_exit_available_at": last_exit.isoformat(),
            "expected_source_vendor": "Dukascopy",
            "expected_source_symbol": "USATECH.IDX/USD",
            "expected_catalog_dataset_key": None,
            "costs": cost, "multiplier": multiplier,
            "effects": ["READ_ONLY", "EVIDENCE_APPEND"],
            "budget": budget,
            "requested_compute": {**budget, "max_wall_seconds": 299},
            "independent_audit": recipe,
        }
        gate = preflight_run(str(root), intent, computation, source, contract)
        assert gate.status == "PASS", (gate.reason_code, gate.observed)
        new = _execute_registered_dukascopy(
            prepared, mode=mode, case=case, permit_gate=gate
        )
        original = json.loads((HIST / f"{mode}_{case}/signals.json").read_text())
        assert len(new.signals) == len(original), (mode, len(new.signals), len(original))
        for observed, expected in zip(new.signals, original, strict=True):
            for key in ("signal_at", "expected_entry_at", "take_profit", "stop_loss",
                        "adx", "adx_prev", "vwap", "decision_close"):
                if isinstance(expected[key], (int, float)):
                    assert observed[key] == pytest.approx(expected[key], abs=1e-8)
                else:
                    assert observed[key] == expected[key]
        historical_fills = pl.read_parquet(HIST / f"{mode}_{case}/fills.parquet")
        historical_trades = pl.read_parquet(HIST / f"{mode}_{case}/trades.parquet")
        assert new.fills.height == historical_fills.height, mode
        assert new.trades.height == historical_trades.height, mode
        for newer, older in zip(new.fills.iter_rows(named=True), historical_fills.iter_rows(named=True), strict=True):
            for name in ("side", "order_type", "timestamp", "quantity"):
                assert newer[name] == older[name], (mode, name)
            for name in ("price", "commission", "slippage"):
                assert newer[name] == pytest.approx(older[name], abs=1e-8), (mode, name)
        for newer, older in zip(new.trades.iter_rows(named=True), historical_trades.iter_rows(named=True), strict=True):
            for name in ("entry_time", "exit_time", "status"):
                assert newer[name] == older[name], (mode, name)
            for name in ("entry_price", "exit_price", "pnl"):
                assert newer[name] == pytest.approx(older[name], abs=1e-7), (mode, name)
        assert new.status == "SIMULATED_NOT_LIVE_QUALIFIED"
