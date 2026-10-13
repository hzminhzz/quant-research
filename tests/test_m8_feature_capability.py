"""M8 feature-plumbing checks. These do not select a PDF strategy or run market data."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest
from ml4t.engineer import feature_catalog
from pydantic import ValidationError

from src.research_control.contracts import ResearchContractV1
from src.research_control.feature_gateway import (
    FeatureContractError,
    FeatureGateway,
    _timeframe_delta,
    verify_feature_proof,
)
from tests.test_research_control import bars, contract, freeze_feature_contract, native


def prior_range_contract(
    *, period: int = 3, timeframe: str = "1m"
) -> ResearchContractV1:
    return contract(
        [
            native(),
            {
                "id": f"prior_high_{period}",
                "provider": {
                    "kind": "extension.approved",
                    "extension_id": "prior_n_high_low",
                    "version": "1.0.0",
                    "field": "high",
                    "period": period,
                },
                "inputs": {"high": "high"},
            },
            {
                "id": f"prior_low_{period}",
                "provider": {
                    "kind": "extension.approved",
                    "extension_id": "prior_n_high_low",
                    "version": "1.0.0",
                    "field": "low",
                    "period": period,
                },
                "inputs": {"low": "low"},
            },
        ],
        timeframe=timeframe,
    )


def test_m8_prior_ranges_have_verified_oracle_and_completed_bar_timing(tmp_path):
    request = prior_range_contract()
    freeze_feature_contract(tmp_path, request)
    source = bars(("A", "B"), count=8)

    computation = FeatureGateway().compute(source, request)
    proof = verify_feature_proof(computation, source, request, tmp_path)

    assert proof.proof.checks["completed_bar_availability"]
    assert proof.proof.checks["numerical_oracle_references_present"]
    assert proof.proof.checks["native_execution_through_engineer"]
    assert all(
        feature["provider"] == "extension.approved"
        and feature["extension_id"] == "prior_n_high_low"
        and feature["includes_current_bar"] is False
        for feature in proof.proof.resolved_features[1:]
    )
    assert computation.data["prior_high_3"].head(3).null_count() == 3
    assert computation.data["prior_low_3"].head(3).null_count() == 3

    # A later bar mutation cannot change levels already available before it.
    changed = source.with_columns(
        pl.when(
            (pl.col("symbol") == "A")
            & (
                pl.col("timestamp")
                == source.filter(pl.col("symbol") == "A")["timestamp"][6]
            )
        )
        .then(pl.col("high") * 100)
        .otherwise(pl.col("high"))
        .alias("high")
    )
    recomputed = FeatureGateway().compute(changed, request).data
    original_a = computation.data.filter(pl.col("symbol") == "A")
    changed_a = recomputed.filter(pl.col("symbol") == "A")
    assert (
        original_a["prior_high_3"][:6].to_list()
        == changed_a["prior_high_3"][:6].to_list()
    )


def test_m8_metadata_only_donchian_is_not_managed_native_feature():
    # Engineer 0.1.4 registers this feature, but its output contract is not the
    # single prior-bar channel required by the managed gateway.
    assert feature_catalog.describe("donchian_channels") is not None
    with pytest.raises(ValidationError, match="FEATURE_UNSUPPORTED"):
        contract(
            [
                {
                    "id": "donchian_upper",
                    "provider": {
                        "kind": "engineer.native",
                        "name": "donchian_channels",
                        "params": {"period": 20},
                    },
                    "inputs": {"high": "high", "low": "low"},
                }
            ]
        )


def test_m8_oracle_rejects_future_dependent_prior_range(tmp_path, monkeypatch):
    from src.research_control import feature_gateway as gateway_module

    request = contract([prior_range_contract().feature_set[1].model_dump(mode="json")])
    freeze_feature_contract(tmp_path, request)
    source = bars(count=8)

    def future_range(data, feature_id, provider, groups):
        value = (
            pl.col(provider.field)
            .shift(-1)
            .rolling_max(window_size=provider.period, min_samples=provider.period)
        )
        if groups:
            value = value.over(groups)
        return data.with_columns(value.alias(feature_id)), {
            "id": feature_id,
            "provider": "extension.approved",
            "extension_id": provider.extension_id,
            "extension_version": provider.version,
            "owner_module": "src.research_control.feature_gateway",
            "input": provider.field,
            "period": provider.period,
            "includes_current_bar": False,
        }

    monkeypatch.setattr(gateway_module, "_prior_range", future_range)
    computation = FeatureGateway().compute(source, request)
    with pytest.raises(FeatureContractError) as error:
        verify_feature_proof(computation, source, request, tmp_path)
    assert error.value.reason_code == "FEATURE_NUMERICAL_MISMATCH"


def test_m8_prior_high_50_is_partition_safe_and_available_after_30m_close(tmp_path):
    request = prior_range_contract(period=50, timeframe="30m")
    freeze_feature_contract(tmp_path, request)
    start = datetime(2020, 1, 2, 14, 30, tzinfo=UTC)
    source = pl.concat(
        [
            bars((symbol,), count=64).with_columns(
                pl.Series(
                    "timestamp",
                    [start + timedelta(minutes=30 * index) for index in range(64)],
                )
            )
            for symbol in ("A", "B")
        ]
    )

    computation = FeatureGateway().compute(source, request)
    proof = verify_feature_proof(computation, source, request, tmp_path)
    assert proof.proof.checks["completed_bar_availability"]
    assert (
        computation.data.filter(pl.col("symbol") == "A")["prior_high_50"]
        .head(50)
        .null_count()
        == 50
    )
    assert computation.data["available_at"][0] == source["timestamp"][0] + timedelta(
        minutes=30
    )

    changed = source.with_columns(
        pl.when(
            (pl.col("symbol") == "A")
            & (
                pl.col("timestamp")
                == source.filter(pl.col("symbol") == "A")["timestamp"][55]
            )
        )
        .then(pl.col("high") * 100)
        .otherwise(pl.col("high"))
        .alias("high")
    )
    recomputed = FeatureGateway().compute(changed, request).data
    original_a = computation.data.filter(pl.col("symbol") == "A")
    changed_a = recomputed.filter(pl.col("symbol") == "A")
    assert (
        original_a["prior_high_50"][:55].to_list()
        == changed_a["prior_high_50"][:55].to_list()
    )
    other_symbol = source.with_columns(
        pl.when(pl.col("symbol") == "B")
        .then(pl.col("high") * 1000)
        .otherwise(pl.col("high"))
        .alias("high")
    )
    partitioned = (
        FeatureGateway()
        .compute(other_symbol, request)
        .data.filter(pl.col("symbol") == "A")
    )
    assert (
        original_a["prior_high_50"].to_list() == partitioned["prior_high_50"].to_list()
    )


def test_feature_gateway_timeframe_support_is_bounded():
    assert _timeframe_delta("1m") == timedelta(minutes=1)
    assert _timeframe_delta("30m") == timedelta(minutes=30)
    for value in ("0m", "1M", "2m", "1h", "30d", "999999999999999999999999999m"):
        with pytest.raises(FeatureContractError) as error:
            _timeframe_delta(value)
        assert error.value.reason_code == "TIMEFRAME_UNSUPPORTED"
    with pytest.raises(ValidationError, match="timeframe"):
        prior_range_contract(timeframe="0m")
