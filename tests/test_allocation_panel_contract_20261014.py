"""Synthetic contract checks for the allocation development panel."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

MODULE_PATH = (
    Path(__file__).parents[1] / "scripts" / "allocation_panel_contract_20261014.py"
)
SPEC = importlib.util.spec_from_file_location(
    "allocation_panel_contract_20261014", MODULE_PATH
)
contract = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = contract
SPEC.loader.exec_module(contract)


def make_source(
    source_id: str, dates: tuple[pd.Timestamp, ...], *, nav: float = 100_000
):
    currency = "USDT" if source_id == "donchian_btc_binance_perp" else "USD"
    rows = []
    for i, date in enumerate(dates):
        equity = nav + (10.0 if i >= 2 else 0.0)
        rows.append(
            {
                "timestamp": date,
                "available_at": date,
                "valuation_at": date,
                "currency": currency,
                "native_nav_unit": f"account_{currency}",
                "nav_denominator": nav,
                "capital_basis": "USD_100K_SYNTHETIC_NAV",
                "position_basis": "native_marked_equity",
                "capital_contract_id": f"capital:{source_id}:v1",
                "capital_contract_certified": True,
                "capital_contract_evidence_id": f"cert:capital:{source_id}:v1",
                "sizing_contract_id": f"sizing:{source_id}:v1",
                "sizing_contract_certified": True,
                "sizing_contract_evidence_id": f"cert:sizing:{source_id}:v1",
                "sizing_method": "source_native_equity_sizing",
                "leverage_profile_id": f"leverage:{source_id}:v1",
                "max_leverage": 2.0,
                "gross_notional": 0.0 if i < 2 else 20_000.0,
                "gross_notional_currency": currency,
                "gross_leverage": 0.0 if i < 2 else 20_000.0 / equity,
                "allocator_capital_unit_id": "USD_ALLOCATOR_CAPITAL_UNIT_V1",
                "allocator_return_unit_id": "RETURN_PER_ACTUAL_ALLOCATOR_CAPITAL_V1",
                "allocator_base_currency": "USD",
                "allocator_conversion_contract_id": f"conversion:{source_id}:v1",
                "allocator_conversion_certified": True,
                "allocator_conversion_rate": 1.0,
                "allocator_conversion_rate_unit": f"USD_per_{currency}",
                "costs_included": True,
                "funding_included": source_id == "donchian_btc_binance_perp",
                "observation_status": "initial"
                if i == 0
                else ("idle_zero" if i == 1 else "active"),
                "position_exposure": 0.0 if i < 2 else 1.0,
                "equity": equity,
                "previous_equity": None if i == 0 else nav + (10.0 if i >= 3 else 0.0),
                "net_return": None if i == 0 else (0.0 if i == 1 else 10.0 / nav),
                "external_cash_flow": None if i == 0 else 0.0,
                "allocator_equity": equity,
                "previous_allocator_equity": None
                if i == 0
                else nav + (10.0 if i >= 3 else 0.0),
                "allocator_unit_return": None
                if i == 0
                else (0.0 if i == 1 else 10.0 / nav),
                "provenance_id": f"synthetic:{source_id}:v1",
                "feature_a": float(i),
            }
        )
    frame = pd.DataFrame(rows)
    first = frame.iloc[0]
    spec = contract.SourceSpec(
        source_id=source_id,
        instrument_id=f"{source_id}:instrument",
        expected_timestamps=dates,
        provenance=f"synthetic:{source_id}:v1",
        native_currency=first["currency"],
        native_nav_unit=first["native_nav_unit"],
        certified_initial_nav=nav,
        capital_basis=first["capital_basis"],
        position_basis=first["position_basis"],
        capital_contract_id=first["capital_contract_id"],
        capital_contract_evidence_id=first["capital_contract_evidence_id"],
        capital_contract_certified=True,
        sizing_contract_id=first["sizing_contract_id"],
        sizing_contract_evidence_id=first["sizing_contract_evidence_id"],
        sizing_contract_certified=True,
        sizing_method=first["sizing_method"],
        leverage_profile_id=first["leverage_profile_id"],
        certified_max_leverage=2.0,
        allocator_capital_unit_id=first["allocator_capital_unit_id"],
        allocator_return_unit_id=first["allocator_return_unit_id"],
        allocator_base_currency=first["allocator_base_currency"],
        allocator_conversion_contract_id=first["allocator_conversion_contract_id"],
        allocator_conversion_certified=True,
    )
    return frame, spec


@pytest.fixture
def rectangular_inputs():
    dates = tuple(pd.date_range("2020-01-01", periods=3, tz="UTC"))
    return {
        source: make_source(
            source, dates, nav=50_000 if source == "rsi_es_cfd" else 100_000
        )
        for source in contract.SOURCES
    }


def test_builds_dev_only_long_panel_without_inference(rectangular_inputs):
    panel = contract.build_development_panel(rectangular_inputs)
    assert len(panel) == len(contract.SOURCES) * 3
    assert set(panel["source_id"]) == set(contract.SOURCES)
    assert panel["timestamp"].max() < contract.DEV_END
    assert (
        panel.loc[panel["observation_status"] == "idle_zero", "net_return"].eq(0).all()
    )
    assert (
        panel.loc[panel["source_id"] == "rsi_es_cfd", "nav_denominator"]
        .eq(50_000)
        .all()
    )


def test_missing_calendar_session_fails_without_fill(rectangular_inputs):
    _, (frame, spec) = next(iter(rectangular_inputs.items()))
    with pytest.raises(contract.PanelContractError, match="calendar mismatch"):
        contract.validate_source(frame.iloc[:1], spec)


def test_missing_row_is_not_treated_as_idle_zero(rectangular_inputs):
    _, (frame, spec) = next(iter(rectangular_inputs.items()))
    frame = frame.drop(columns=["observation_status"])
    with pytest.raises(contract.PanelContractError, match="missing required columns"):
        contract.validate_source(frame, spec)


def test_unavailable_value_fails(rectangular_inputs):
    _, (frame, spec) = next(iter(rectangular_inputs.items()))
    frame.loc[0, "available_at"] = pd.Timestamp("2020-01-02T00:00:00Z")
    with pytest.raises(contract.PanelContractError, match="unavailable"):
        contract.validate_source(frame, spec)


def test_naive_timestamp_fails(rectangular_inputs):
    _, (frame, spec) = next(iter(rectangular_inputs.items()))
    frame["timestamp"] = frame["timestamp"].dt.tz_localize(None)
    with pytest.raises(contract.PanelContractError, match="timezone-aware"):
        contract.validate_source(frame, spec)


def test_native_denominators_may_differ_when_certified(rectangular_inputs):
    panel = contract.build_development_panel(rectangular_inputs)
    denominators = panel.groupby("source_id")["nav_denominator"].first()
    assert denominators.nunique() == 2


def test_mismatched_native_denominator_and_initial_equity_fail(rectangular_inputs):
    source = contract.SOURCES[-1]
    frame, spec = rectangular_inputs[source]
    rectangular_inputs[source] = (frame.assign(nav_denominator=75_000), spec)
    with pytest.raises(contract.PanelContractError, match="must match certified NAV"):
        contract.build_development_panel(rectangular_inputs)


def test_native_return_must_reconcile_to_actual_equity(rectangular_inputs):
    source = contract.SOURCES[0]
    frame, spec = rectangular_inputs[source]
    frame.loc[2, "net_return"] = 0.25
    rectangular_inputs[source] = (frame, spec)
    with pytest.raises(
        contract.PanelContractError, match="net_return does not reconcile"
    ):
        contract.build_development_panel(rectangular_inputs)


def test_allocator_return_must_reconcile_to_mapped_equity(rectangular_inputs):
    source = contract.SOURCES[0]
    frame, spec = rectangular_inputs[source]
    frame.loc[2, "allocator_unit_return"] = 0.5
    rectangular_inputs[source] = (frame, spec)
    with pytest.raises(
        contract.PanelContractError, match="allocator_unit_return does not reconcile"
    ):
        contract.build_development_panel(rectangular_inputs)


def test_certified_conversion_rate_must_reconcile_to_allocator_equity(
    rectangular_inputs,
):
    source = contract.SOURCES[2]
    frame, spec = rectangular_inputs[source]
    frame.loc[2, "allocator_conversion_rate"] = 0.9
    rectangular_inputs[source] = (frame, spec)
    with pytest.raises(
        contract.PanelContractError, match="does not match certified conversion"
    ):
        contract.build_development_panel(rectangular_inputs)


def test_uncertified_sizing_or_conversion_fails(rectangular_inputs):
    source = contract.SOURCES[0]
    frame, spec = rectangular_inputs[source]
    frame.loc[1, "sizing_contract_certified"] = False
    rectangular_inputs[source] = (frame, spec)
    with pytest.raises(
        contract.PanelContractError, match="sizing_contract_certified must be certified"
    ):
        contract.build_development_panel(rectangular_inputs)


def test_allocator_unit_mismatch_fails(rectangular_inputs):
    source = contract.SOURCES[-1]
    frame, spec = rectangular_inputs[source]
    frame = frame.assign(allocator_return_unit_id="OTHER_RETURN_UNIT")
    spec = replace(spec, allocator_return_unit_id="OTHER_RETURN_UNIT")
    rectangular_inputs[source] = (
        frame,
        spec,
    )
    with pytest.raises(
        contract.PanelContractError, match="incompatible allocator_return_unit_id"
    ):
        contract.build_development_panel(rectangular_inputs)


def test_locked_holdout_row_is_rejected_without_scoring(rectangular_inputs):
    _, (frame, spec) = next(iter(rectangular_inputs.items()))
    holdout = frame.iloc[[0]].copy()
    holdout["timestamp"] = contract.LOCKED_START
    holdout["available_at"] = contract.LOCKED_START
    holdout["valuation_at"] = contract.LOCKED_START
    spec = replace(spec, expected_timestamps=(contract.LOCKED_START,))
    with pytest.raises(
        contract.PanelContractError, match="locked holdout is not opened"
    ):
        contract.validate_source(holdout, spec)


def test_batch_adapter_requires_rectangular_observed_inputs(rectangular_inputs):
    panel = contract.build_development_panel(rectangular_inputs)
    source_specs = {
        source_id: spec for source_id, (_, spec) in rectangular_inputs.items()
    }
    batch = contract.to_portfolio_sequence_batch(
        panel,
        source_specs=source_specs,
        feature_columns=("feature_a",),
        observed_return_column="allocator_unit_return",
    )
    assert batch.features.shape == (1, 2, 4, 1)
    assert batch.returns.shape == (1, 2, 4)
    assert batch.asset_ids == tuple(sorted(contract.SOURCES))

    sparse = panel.iloc[:-1]
    with pytest.raises(contract.PanelContractError, match="calendar mismatch"):
        contract.to_portfolio_sequence_batch(
            sparse,
            source_specs=source_specs,
            feature_columns=("feature_a",),
            observed_return_column="allocator_unit_return",
        )

    with pytest.raises(
        contract.PanelContractError, match="allocator_unit_return are required"
    ):
        contract.to_portfolio_sequence_batch(
            panel,
            source_specs=source_specs,
            feature_columns=("feature_a",),
            observed_return_column="net_return",
        )


def test_ml4t_mask_does_not_fill_missing_values():
    from ml4t.models import PortfolioSequenceBatch

    features = np.array([[[[np.nan]]]], dtype=float)
    returns = np.array([[[np.nan]]], dtype=float)
    mask = np.zeros((1, 1, 1), dtype=bool)
    batch = PortfolioSequenceBatch(
        features=features,
        returns=returns,
        mask=mask,
        timestamps=(pd.Timestamp("2020-01-01T00:00:00Z"),),
        asset_ids=("synthetic",),
    )
    assert np.isnan(batch.features[0, 0, 0, 0])
    assert np.isnan(batch.returns[0, 0, 0])
    assert not batch.mask[0, 0, 0]
