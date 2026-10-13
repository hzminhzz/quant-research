from __future__ import annotations

import json
import math
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest
import yaml
from pydantic import ValidationError

from scripts import research as research_cli
from src.research_control.contracts import ResearchContractV1
from src.research_control.feature_gateway import (
    FeatureComputation,
    FeatureContractError,
    FeatureGateway,
    require_verified_feature_proof,
    verify_feature_proof,
)
from src.research_session import init_session

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts/research.py"


def contract(
    features: list[dict],
    *,
    source_vendor: str = "Dukascopy",
    source_symbol: str = "USATECH.IDX/USD",
    product_class: str = "cfd",
    volume_semantics: str = "broker_tick_or_quote_proxy",
    requested_product: str = "Dukascopy USATECH.IDX/USD CFD price proxy",
    group_columns: list[str] | None = None,
    timeframe: str = "1m",
) -> ResearchContractV1:
    return ResearchContractV1.model_validate(
        {
            "schema_version": 1,
            "session_id": "vwap-m1-m2-test",
            "dataset": {
                "requested_product": requested_product,
                "source_vendor": source_vendor,
                "source_symbol": source_symbol,
                "catalog_dataset_key": None,
                "external_exception_id": "test-proxy-source-v1",
                "authority": "staged_noncanonical",
                "product_class": product_class,
                "role": "price_proxy",
                "volume_semantics": volume_semantics,
                "timeframe": timeframe,
                "timestamp_convention": "bar_start",
                "timezone": "America/Chicago",
                "group_columns": group_columns
                if group_columns is not None
                else ["symbol"],
            },
            "feature_set": features,
            "strategy": {"rule_id": "test-rule", "engine": "ml4t.backtest"},
            "evaluation": {"development": ["2026-01-01", "2026-07-01"]},
        }
    )


def native(feature_id: str = "adx_14") -> dict:
    return {
        "id": feature_id,
        "provider": {
            "kind": "engineer.native",
            "name": "adx",
            "params": {"period": 14},
        },
        "inputs": {"high": "high", "low": "low", "close": "close"},
    }


def bars(symbols: tuple[str, ...] = ("A",), count: int = 80) -> pl.DataFrame:
    rows = []
    start = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    for symbol_index, symbol in enumerate(symbols):
        for i in range(count):
            base = 100 + i * 0.13 + ((i * 7 + symbol_index * 3) % 11) * 0.21
            rows.append(
                {
                    "timestamp": start + timedelta(minutes=i),
                    "symbol": symbol,
                    "open": base - 0.1,
                    "high": base + 0.7 + i % 3 * 0.05,
                    "low": base - 0.6 - i % 4 * 0.03,
                    "close": base + (i % 5 - 2) * 0.17,
                    "volume": float(100 + i % 17),
                }
            )
    return pl.DataFrame(rows)


def freeze_feature_contract(root: Path, request: ResearchContractV1) -> None:
    config = root / "feature-contract.yaml"
    config.write_text(yaml.safe_dump(request.model_dump(mode="json")), encoding="utf-8")
    spec = {
        "session_id": request.session_id,
        "thesis": "Feature proof runtime gate test.",
        "mechanism": "A typed feature contract binds inputs and calculations.",
        "falsifier": "Any changed identity or non-causal feature fails verification.",
        "market": "indices",
        "instruments": [{"symbol": "TEST", "kind": "spot"}],
        "data": [{"id": "bars", "path": "bars.parquet", "role": "prices"}],
        "evaluation": {"scope": "feature proof only"},
        "baseline": "No strategy result.",
        "costs": {"commission_bps": 0, "slippage_bps": 0},
        "trials": [
            {
                "id": "feature-proof",
                "kind": "preregistered",
                "description": "Verify feature provenance.",
            }
        ],
        "config": config.name,
    }
    spec_path = root / "session.yaml"
    spec_path.write_text(yaml.safe_dump(spec), encoding="utf-8")
    init_session(spec_path, root)


def wilder_adx_reference(
    high: list[float], low: list[float], close: list[float], period: int
) -> list[float]:
    """Small independent Wilder recurrence used only as a numerical oracle."""
    size = len(high)
    true_range = [math.nan] * size
    plus_dm = [math.nan] * size
    minus_dm = [math.nan] * size
    for index in range(1, size):
        up = high[index] - high[index - 1]
        down = low[index - 1] - low[index]
        true_range[index] = max(
            high[index] - low[index],
            abs(high[index] - close[index - 1]),
            abs(low[index] - close[index - 1]),
        )
        plus_dm[index] = up if up > down and up > 0 else 0.0
        minus_dm[index] = down if down > up and down > 0 else 0.0
    smoothed_tr = sum(true_range[1 : period + 1])
    smoothed_plus = sum(plus_dm[1 : period + 1])
    smoothed_minus = sum(minus_dm[1 : period + 1])
    dx = [math.nan] * size
    for index in range(period, size):
        if index > period:
            smoothed_tr += true_range[index] - smoothed_tr / period
            smoothed_plus += plus_dm[index] - smoothed_plus / period
            smoothed_minus += minus_dm[index] - smoothed_minus / period
        plus_di = 100 * smoothed_plus / smoothed_tr
        minus_di = 100 * smoothed_minus / smoothed_tr
        denominator = plus_di + minus_di
        dx[index] = 100 * abs(plus_di - minus_di) / denominator if denominator else 0.0
    result = [math.nan] * size
    first = 2 * period - 1
    result[first] = sum(dx[period : first + 1]) / period
    for index in range(first + 1, size):
        result[index] = (result[index - 1] * (period - 1) + dx[index]) / period
    return result


def test_native_adx_uses_engineer_and_matches_independent_wilder_oracle(monkeypatch):
    from ml4t import engineer

    from src.research_control import feature_gateway

    actual_compute = engineer.compute_features
    calls = []

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return actual_compute(*args, **kwargs)

    monkeypatch.setattr(feature_gateway, "compute_features", spy)
    data = bars()
    request = contract([native()])

    result = FeatureGateway().compute(data, request)
    expected = wilder_adx_reference(
        data["high"].to_list(), data["low"].to_list(), data["close"].to_list(), 14
    )

    actual = result.data["adx_14"].to_numpy()
    assert len(calls) == 1
    assert calls[0][0][0].equals(data)
    assert calls[0][0][1] == [
        {"name": "adx", "params": {"period": 14}, "output": "adx_14"}
    ]
    assert calls[0][1] == {"group_col": ["symbol"], "timestamp_col": "timestamp"}
    assert result.proof.checks["native_execution_through_engineer"]
    assert result.proof.resolved_features[0]["provider"] == "engineer.native"
    assert actual == pytest.approx(expected, nan_ok=True, abs=0.1)
    assert (
        result.proof.output_sha256
        == FeatureGateway().compute(data, request).proof.output_sha256
    )
    changed_future = data.with_columns(
        pl.when(pl.col("timestamp") == data["timestamp"][-1])
        .then(pl.col("high") * 3)
        .otherwise(pl.col("high"))
        .alias("high")
    )
    changed = FeatureGateway().compute(changed_future, request).data
    assert result.data["adx_14"][:-1].to_list() == pytest.approx(
        changed["adx_14"][:-1].to_list(), nan_ok=True
    )
    assert result.data["available_at"][10] == result.data["timestamp"][10] + timedelta(
        minutes=1
    )


def test_runtime_feature_proof_accepts_native_adx_and_approved_vwap(tmp_path):
    request = contract(
        [
            native(),
            {
                "id": "cash_vwap",
                "provider": {
                    "kind": "extension.approved",
                    "extension_id": "cash_open_vwap",
                    "version": "1.0.0",
                    "session_open": "08:30",
                    "timezone": "America/Chicago",
                },
                "inputs": {
                    "high": "high",
                    "low": "low",
                    "close": "close",
                    "volume": "volume",
                },
            },
        ]
    )
    freeze_feature_contract(tmp_path, request)
    input_data = bars(("A", "B"), count=80)
    frozen_path = (
        tmp_path / "run_log/research_sessions/vwap-m1-m2-test/frozen_spec.json"
    )
    frozen_before = frozen_path.read_bytes()

    computation = FeatureGateway().compute(input_data, request)
    verified = verify_feature_proof(computation, input_data, request, tmp_path)

    assert require_verified_feature_proof(verified).proof is computation.proof
    assert frozen_path.read_bytes() == frozen_before


def test_runtime_feature_proof_rejects_forgery_input_output_and_config_drift(tmp_path):
    request = contract([native()])
    freeze_feature_contract(tmp_path, request)
    input_data = bars()
    computation = FeatureGateway().compute(input_data, request)

    forged = FeatureComputation(
        computation.data,
        replace(computation.proof, output_sha256="0" * 64),
    )
    with pytest.raises(FeatureContractError) as error:
        verify_feature_proof(forged, input_data, request, tmp_path)
    assert error.value.reason_code == "FEATURE_PROOF_FORGED"

    changed_input = input_data.with_columns((pl.col("close") + 0.01).alias("close"))
    with pytest.raises(FeatureContractError) as error:
        verify_feature_proof(computation, changed_input, request, tmp_path)
    assert error.value.reason_code == "FEATURE_INPUT_IDENTITY_DRIFT"

    changed_output = computation.data.with_columns(
        (pl.col("adx_14") + 1).alias("adx_14")
    )
    with pytest.raises(FeatureContractError) as error:
        verify_feature_proof(
            FeatureComputation(changed_output, computation.proof),
            input_data,
            request,
            tmp_path,
        )
    assert error.value.reason_code == "FEATURE_OUTPUT_IDENTITY_DRIFT"

    (tmp_path / "feature-contract.yaml").write_text(
        "schema_version: 1\n", encoding="utf-8"
    )
    with pytest.raises(FeatureContractError) as error:
        verify_feature_proof(computation, input_data, request, tmp_path)
    assert error.value.reason_code == "FEATURE_CONFIG_IDENTITY_DRIFT"


def test_runtime_feature_proof_rejects_custom_adx_and_provider_code_drift(
    tmp_path, monkeypatch
):
    request = contract([native()])
    freeze_feature_contract(tmp_path, request)
    input_data = bars()
    from src.research_control import feature_gateway

    installed_compute = feature_gateway.compute_features

    def custom_adx(data, features, **kwargs):
        result = installed_compute(data, features, **kwargs)
        return result.with_columns((pl.col("adx_14") + 1).alias("adx_14"))

    monkeypatch.setattr(feature_gateway, "compute_features", custom_adx)
    computation = FeatureGateway().compute(input_data, request)
    with pytest.raises(FeatureContractError) as error:
        verify_feature_proof(computation, input_data, request, tmp_path)
    assert error.value.reason_code == "FEATURE_PROVIDER_IDENTITY_DRIFT"


def test_runtime_feature_gateway_rejects_native_dispatch_bypass(monkeypatch):
    from src.research_control import feature_gateway

    def custom_native(data, feature_id, request, groups, **kwargs):
        return data.with_columns(pl.lit(42.0).alias(feature_id)), {
            "id": feature_id,
            "provider": "engineer.native",
            "name": request.name,
            "params": dict(request.params),
        }

    monkeypatch.setattr(feature_gateway, "_native", custom_native)
    with pytest.raises(FeatureContractError) as error:
        FeatureGateway().compute(bars(), contract([native()]))
    assert error.value.reason_code == "FEATURE_NATIVE_EXECUTION_BYPASS"


def test_runtime_feature_gateway_rejects_native_dispatch_result_substitution(
    monkeypatch,
):
    from src.research_control import feature_gateway

    def substituted_native(data, feature_id, request, groups, *, dispatch):
        dispatch(
            data,
            [
                {
                    "name": request.name,
                    "params": dict(request.params),
                    "output": feature_id,
                }
            ],
            group_col=groups or None,
            timestamp_col="timestamp",
        )
        return data.with_columns(pl.lit(42.0).alias(feature_id)), {
            "id": feature_id,
            "provider": "engineer.native",
            "name": request.name,
            "params": dict(request.params),
        }

    monkeypatch.setattr(feature_gateway, "_native", substituted_native)
    with pytest.raises(FeatureContractError) as error:
        FeatureGateway().compute(bars(), contract([native()]))
    assert error.value.reason_code == "FEATURE_NATIVE_EXECUTION_BYPASS"


def test_runtime_feature_proof_rejects_changed_gateway_code_hash(tmp_path, monkeypatch):
    request = contract([native()])
    freeze_feature_contract(tmp_path, request)
    input_data = bars()
    computation = FeatureGateway().compute(input_data, request)
    from src.research_control import feature_gateway

    monkeypatch.setattr(feature_gateway, "extension_code_identity", lambda: "0" * 64)
    with pytest.raises(FeatureContractError) as error:
        verify_feature_proof(computation, input_data, request, tmp_path)
    assert error.value.reason_code == "FEATURE_PROVIDER_IDENTITY_DRIFT"


def test_runtime_feature_proof_rejects_changed_engineer_version(tmp_path, monkeypatch):
    request = contract([native()])
    freeze_feature_contract(tmp_path, request)
    input_data = bars()
    computation = FeatureGateway().compute(input_data, request)
    from src.research_control import feature_gateway

    installed_version = feature_gateway.importlib.metadata.version
    monkeypatch.setattr(
        feature_gateway.importlib.metadata,
        "version",
        lambda name: "drifted" if name == "ml4t-engineer" else installed_version(name),
    )
    with pytest.raises(FeatureContractError) as error:
        verify_feature_proof(computation, input_data, request, tmp_path)
    assert error.value.reason_code == "FEATURE_PROVIDER_IDENTITY_DRIFT"


def test_runtime_gate_rejects_missing_or_asserted_verified_proof():
    with pytest.raises(FeatureContractError) as error:
        verify_feature_proof(None, bars(), contract([native()]), Path("."))
    assert error.value.reason_code == "FEATURE_PROOF_MISSING"
    with pytest.raises(FeatureContractError) as error:
        require_verified_feature_proof(object())
    assert error.value.reason_code == "FEATURE_PROOF_FORGED"


def test_contract_rejects_unknown_runtime_extension():
    raw = contract([native()]).model_dump(mode="python")
    raw["feature_set"] = [
        {
            "id": "unknown_vwap",
            "provider": {
                "kind": "extension.approved",
                "extension_id": "unknown_vwap",
                "version": "1.0.0",
                "session_open": "08:30",
                "timezone": "America/Chicago",
            },
            "inputs": {
                "high": "high",
                "low": "low",
                "close": "close",
                "volume": "volume",
            },
        }
    ]
    with pytest.raises(ValidationError):
        ResearchContractV1.model_validate(raw)


def test_native_typical_price_uses_engineer_fields():
    data = bars(count=3)
    request = contract(
        [
            {
                "id": "typical_price",
                "provider": {
                    "kind": "engineer.native",
                    "name": "typprice",
                    "params": {},
                },
                "inputs": {"high": "high", "low": "low", "close": "close"},
            }
        ]
    )

    result = FeatureGateway().compute(data, request).data
    expected = (data["high"] + data["low"] + data["close"]) / 3
    assert result["typical_price"].to_list() == pytest.approx(expected.to_list())


def test_cash_open_vwap_is_grouped_reset_dst_safe_and_completed_bar_only():
    rows = []
    # 08:29 through 08:34 local time, with a missing 08:32 bar, on both sides of DST.
    sessions = [
        [
            datetime(2024, 3, 8, 14, 29, tzinfo=UTC),
            datetime(2024, 3, 8, 14, 30, tzinfo=UTC),
            datetime(2024, 3, 8, 14, 31, tzinfo=UTC),
            datetime(2024, 3, 8, 14, 33, tzinfo=UTC),
            datetime(2024, 3, 8, 14, 34, tzinfo=UTC),
        ],
        [
            datetime(2024, 3, 11, 13, 29, tzinfo=UTC),
            datetime(2024, 3, 11, 13, 30, tzinfo=UTC),
            datetime(2024, 3, 11, 13, 31, tzinfo=UTC),
            datetime(2024, 3, 11, 13, 33, tzinfo=UTC),
            datetime(2024, 3, 11, 13, 34, tzinfo=UTC),
        ],
    ]
    for symbol, price in (("A", 10.0), ("B", 100.0)):
        for date_index, timestamps in enumerate(sessions):
            for i, stamp in enumerate(timestamps):
                rows.append(
                    {
                        "timestamp": stamp,
                        "symbol": symbol,
                        "open": price + date_index + i,
                        "high": price + date_index + i + 2,
                        "low": price + date_index + i,
                        "close": price + date_index + i + 1,
                        "volume": [100.0, 100.0, 200.0, 0.0, None][i],
                    }
                )
    data = pl.DataFrame(rows)
    request = contract(
        [
            {
                "id": "cash_vwap",
                "provider": {
                    "kind": "extension.approved",
                    "extension_id": "cash_open_vwap",
                    "version": "1.0.0",
                    "session_open": "08:30",
                    "timezone": "America/Chicago",
                },
                "inputs": {
                    "high": "high",
                    "low": "low",
                    "close": "close",
                    "volume": "volume",
                },
            }
        ]
    )

    result = FeatureGateway().compute(data, request)
    out = result.data
    for symbol, price in (("A", 10.0), ("B", 100.0)):
        first_day = out.filter(
            (pl.col("symbol") == symbol)
            & (pl.col("timestamp").dt.date() == date(2024, 3, 8))
        )
        second_day = out.filter(
            (pl.col("symbol") == symbol)
            & (pl.col("timestamp").dt.date() == date(2024, 3, 11))
        )
        assert first_day["cash_vwap"].to_list()[0] is None
        assert first_day["cash_vwap"].to_list() == [
            None,
            price + 2,
            pytest.approx(price + 8 / 3),
            pytest.approx(price + 8 / 3),
            pytest.approx(price + 8 / 3),
        ]
        assert second_day["cash_vwap"].to_list()[0] is None
        assert second_day["cash_vwap"].to_list() == [
            None,
            price + 3,
            pytest.approx(price + 11 / 3),
            pytest.approx(price + 11 / 3),
            pytest.approx(price + 11 / 3),
        ]
    assert (
        result.proof.resolved_features[0]["volume_semantics"]
        == "broker_tick_or_quote_proxy"
    )
    assert result.proof.checks["completed_bar_availability"]
    changed_future = data.with_columns(
        pl.when(
            (pl.col("symbol") == "A")
            & (pl.col("timestamp") == datetime(2024, 3, 8, 14, 34, tzinfo=UTC))
        )
        .then(pl.col("high") + 10)
        .otherwise(pl.col("high"))
        .alias("high")
    )
    changed = FeatureGateway().compute(changed_future, request).data
    original_a = out.filter(
        (pl.col("symbol") == "A") & (pl.col("timestamp").dt.date() == date(2024, 3, 8))
    )
    changed_a = changed.filter(
        (pl.col("symbol") == "A") & (pl.col("timestamp").dt.date() == date(2024, 3, 8))
    )
    assert (
        original_a["cash_vwap"][:-1].to_list() == changed_a["cash_vwap"][:-1].to_list()
    )


def test_prior_n_high_low_extension_excludes_current_bar_and_partitions_symbols():
    data = bars(("A", "B"), count=5)
    request = contract(
        [
            {
                "id": "prior_high_2",
                "provider": {
                    "kind": "extension.approved",
                    "extension_id": "prior_n_high_low",
                    "version": "1.0.0",
                    "field": "high",
                    "period": 2,
                },
                "inputs": {"high": "high"},
            }
        ]
    )
    result = FeatureGateway().compute(data, request).data
    first = result.filter(pl.col("symbol") == "A")
    expected = [
        None,
        None,
        max(data["high"][0], data["high"][1]),
        max(data["high"][1], data["high"][2]),
        max(data["high"][2], data["high"][3]),
    ]
    assert first["prior_high_2"].to_list() == expected
    mutated = data.with_columns(
        pl.when(
            (pl.col("symbol") == "A") & (pl.col("timestamp") == data["timestamp"][2])
        )
        .then(pl.col("high") * 100)
        .otherwise(pl.col("high"))
        .alias("high")
    )
    mutated_result = (
        FeatureGateway().compute(mutated, request).data.filter(pl.col("symbol") == "A")
    )
    assert mutated_result["prior_high_2"][2] == first["prior_high_2"][2]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw.update(extra=True),
        lambda raw: raw["feature_set"][0]["provider"].update(params={"period": 20}),
        lambda raw: raw["feature_set"][0].update(
            inputs={"high": "high", "low": "low", "close": "close", "volume": "volume"}
        ),
        lambda raw: raw["feature_set"][0]["provider"].update(name="custom_adx"),
    ],
)
def test_contract_rejects_unknown_keys_custom_adx_and_wrong_inputs(mutate):
    feature = native()
    raw = contract([feature]).model_dump(mode="python")
    mutate(raw)
    with pytest.raises(ValidationError):
        ResearchContractV1.model_validate(raw)


def test_contract_rejects_close_as_prior_high_and_false_cme_volume():
    with pytest.raises(ValidationError, match="FEATURE_INPUT_MISMATCH"):
        contract(
            [
                {
                    "id": "wrong_high",
                    "provider": {
                        "kind": "engineer.native",
                        "name": "maximum",
                        "params": {"timeperiod": 5},
                    },
                    "inputs": {"high": "high"},
                }
            ]
        )
    with pytest.raises(ValidationError, match="genuine exchange volume"):
        contract([native()], requested_product="CME NQ", product_class="cfd")
    with pytest.raises(ValidationError, match="CFD volume"):
        contract([native()], volume_semantics="genuine_exchange_traded")
    with pytest.raises(ValidationError, match="not Dukascopy"):
        raw = contract([native()]).model_dump(mode="python")
        raw["dataset"].update(
            catalog_dataset_key="lse_futures_minute_NQ", source_symbol="NQ.F"
        )
        ResearchContractV1.model_validate(raw)


def test_contract_rejects_unknown_extension_and_unqualified_custom_source():
    with pytest.raises(ValidationError):
        contract(
            [
                {
                    "id": "custom",
                    "provider": {
                        "kind": "extension.approved",
                        "extension_id": "custom_vwap",
                        "version": "1.0.0",
                    },
                    "inputs": {"close": "close"},
                }
            ]
        )
    raw = contract([native()]).model_dump(mode="python")
    raw["dataset"]["external_exception_id"] = None
    with pytest.raises(ValidationError, match="external_exception_id"):
        ResearchContractV1.model_validate(raw)


def test_contract_identity_is_stable_and_changes_with_parameters():
    first = contract([native()])
    same = ResearchContractV1.model_validate(first.model_dump(mode="python"))
    changed = contract([native("adx_14_v2")])
    assert first.identity_sha256() == same.identity_sha256()
    assert first.identity_sha256() != changed.identity_sha256()


def test_versioned_yaml_example_matches_the_strict_contract():
    example = ROOT / "config/research_contract_v1_example.yaml"
    parsed = ResearchContractV1.model_validate(yaml.safe_load(example.read_text()))
    assert parsed.dataset.source_symbol == "USATECH.IDX/USD"
    assert [feature.id for feature in parsed.feature_set] == [
        "adx_14",
        "typical_price",
        "cash_vwap",
        "prior_high_5",
        "prior_low_20",
    ]


def test_gateway_rejects_naive_timestamps_negative_volume_and_missing_groups():
    data = bars(count=4)
    request = contract([native()])
    with pytest.raises(FeatureContractError, match="at least one"):
        FeatureGateway().compute(data.head(0), request)
    with pytest.raises(FeatureContractError, match="timezone-aware"):
        FeatureGateway().compute(
            data.with_columns(pl.col("timestamp").dt.replace_time_zone(None)), request
        )
    with pytest.raises(FeatureContractError, match="non-negative"):
        FeatureGateway().compute(
            data.with_columns(pl.lit(-1.0).alias("volume")), request
        )
    no_group = contract([native()], group_columns=[])
    with pytest.raises(FeatureContractError, match="declare symbol"):
        FeatureGateway().compute(data, no_group)
    duplicate = pl.concat([data, data.head(1)])
    with pytest.raises(FeatureContractError, match="unique"):
        FeatureGateway().compute(duplicate, request)


def _doctor_fixture(monkeypatch, root: Path) -> dict:
    session_id = "data-free-doctor-fixture"
    _init_status_session(
        root,
        session_id,
        instrument={
            "symbol": "NQ",
            "kind": "cfd",
            "venue": "Dukascopy",
            "session": "15:55",
        },
    )
    monkeypatch.setattr(
        research_cli,
        "load_dataset_catalog",
        lambda: {
            "catalog_identity": "fixture-catalog",
            "entries": [
                {"dataset_key": "lse_futures_minute_NQ", "source_symbol": "NQ.F"}
            ],
            "resolutions": {
                "NQ": {"candidate_dataset_keys": ["lse_futures_minute_NQ"]}
            },
        },
    )
    monkeypatch.setattr(research_cli, "load_readiness_audit", dict)
    monkeypatch.setattr(
        research_cli,
        "_coverage",
        lambda *_args: {
            "path": "bars.parquet",
            "last_bar_available_local": "2026-10-12T15:15:00+02:00",
        },
    )
    monkeypatch.setattr(
        research_cli,
        "_runtime_jobs",
        lambda _root: {"visibility": "available", "active_jobs": []},
    )
    return research_cli.doctor(root, session_id)


def _init_status_session(
    root: Path, session_id: str, *, instrument: dict | None = None
) -> Path:
    data_dir = root / "data"
    data_dir.mkdir(exist_ok=True)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    prices = [100.0, 101.0, 102.0]
    pl.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=i) for i in range(3)],
            "open": prices,
            "high": [price + 1 for price in prices],
            "low": [price - 1 for price in prices],
            "close": prices,
        }
    ).write_parquet(data_dir / "prices.parquet")
    spec_path = root / f"{session_id}.yaml"
    spec_path.write_text(
        yaml.safe_dump(
            {
                "session_id": session_id,
                "thesis": "Exercise read-only session status output.",
                "mechanism": "The CLI reads frozen declarations and trial records.",
                "falsifier": "Status changes or omits declared trial outcomes.",
                "market": "indices",
                "instruments": [instrument or {"symbol": "TEST", "kind": "cfd"}],
                "data": [
                    {"id": "prices", "path": "data/prices.parquet", "role": "prices"}
                ],
                "evaluation": {"purpose": "CLI status contract test"},
                "baseline": "No strategy result.",
                "costs": {"commission_bps": 0, "slippage_bps": 0},
                "trials": [
                    {
                        "id": "rule-a",
                        "kind": "preregistered",
                        "description": "First pending rule.",
                    },
                    {
                        "id": "rule-b",
                        "kind": "preregistered",
                        "description": "Second pending rule.",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    init_session(spec_path, root)
    return root / "run_log" / "research_sessions" / session_id / "frozen_spec.json"


def test_cli_discover_doctor_and_status_are_structured_and_read_only(
    monkeypatch, tmp_path
):
    process = subprocess.run(
        [sys.executable, str(CLI), "discover", "--feature", "adx", "--root", str(ROOT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert not process.stderr
    discovered = json.loads(process.stdout)
    doctor = _doctor_fixture(monkeypatch, tmp_path)
    frozen_path = _init_status_session(tmp_path, "status-smoke")
    frozen_before = frozen_path.read_bytes()
    status_process = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "status",
            "--session",
            "status-smoke",
            "--root",
            str(tmp_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert not status_process.stderr
    status = json.loads(status_process.stdout)

    assert discovered["feature"]["name"] == "adx"
    assert status_process.returncode == 0
    assert {
        "status",
        "reason_code",
        "summary",
        "scope",
        "effects",
        "next_actions",
        "trials",
        "approval_status",
    } <= status.keys()
    assert status["scope"] == "research_session_status"
    assert status["trials"]["declared"] == 2
    assert status["trials"]["pending"] == len(status["trials"]["records"]) == 2
    assert status["trials"]["completed"] == status["trials"]["failed"] == 0
    assert status["effects"] == ["READ_ONLY"]
    assert status["approval_status"] == "NOT_APPROVED"
    assert status["audit"]["data_audit_performed"] is False
    assert frozen_path.read_bytes() == frozen_before
    assert doctor["status"] == "BLOCKED"
    assert any(
        item["reason_code"] == "DATA_SESSION_MISMATCH" for item in doctor["findings"]
    )
    assert any(
        item["reason_code"] == "SOURCE_IDENTITY_CONFLICT" for item in doctor["findings"]
    )
    assert doctor["effects"] == ["READ_ONLY"]
    assert doctor["approval_status"] == "NOT_APPROVED"


def test_doctor_exposes_dukascopy_vs_lse_nq_f_source_conflict(monkeypatch, tmp_path):
    result = _doctor_fixture(monkeypatch, tmp_path)
    conflict = next(
        item
        for item in result["findings"]
        if item["reason_code"] == "SOURCE_IDENTITY_CONFLICT"
    )
    assert conflict["requested"] == "Dukascopy USATECH.IDX/USD"
    assert any(
        item["source_symbol"] == "NQ.F"
        for item in conflict["observed_catalog_candidates"]
    )


def test_doctor_reports_missing_catalog_with_safe_next_action(tmp_path, monkeypatch):
    def missing_catalog():
        raise research_cli.CatalogResolutionError("catalog missing")

    monkeypatch.setattr(research_cli, "load_dataset_catalog", missing_catalog)
    monkeypatch.setattr(
        research_cli,
        "_runtime_jobs",
        lambda _root: {"visibility": "available", "active_jobs": []},
    )

    result = research_cli.doctor(tmp_path, None)

    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "DATA_CATALOG_UNAVAILABLE"
    finding = next(
        item
        for item in result["findings"]
        if item["reason_code"] == "DATA_CATALOG_UNAVAILABLE"
    )
    assert finding["summary"] == "catalog missing"
    assert "Restore the canonical ml4t-data catalog" in finding["next_action"]


def test_runtime_inspection_reports_active_tmux_job_and_existing_log(
    monkeypatch, tmp_path
):
    (tmp_path / "run_log/research_sessions/active-nq-job").mkdir(parents=True)
    monkeypatch.setattr(
        research_cli.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="active-nq-job\t/workspace\tpython\t4321\n",
            stderr="",
        ),
    )

    runtime = research_cli._runtime_jobs(tmp_path)

    assert runtime["visibility"] == "available"
    assert runtime["active_jobs"] == [
        {
            "session": "active-nq-job",
            "state": "RUNNING",
            "cwd": "/workspace",
            "command": "python",
            "pid": "4321",
            "log_ref": "run_log/research_sessions/active-nq-job",
        }
    ]
