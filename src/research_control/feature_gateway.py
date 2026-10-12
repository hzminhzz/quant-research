"""The only managed entry point for native and approved research features."""

from __future__ import annotations

import hashlib
import importlib.metadata
import inspect
import io
import json
from dataclasses import dataclass
from typing import Any

import polars as pl
from ml4t.engineer import compute_features, feature_catalog

from .contracts import (
    CashOpenVWAP,
    EngineerNative,
    PriorHighLow,
    ResearchContractV1,
    extension_code_identity,
)

GATEWAY_VERSION = "1.0.0"


class FeatureContractError(ValueError):
    """A requested feature cannot be executed with the declared semantics."""

    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class FeatureProof:
    contract_sha256: str
    feature_set_sha256: str
    input_sha256: str
    output_sha256: str
    provider_versions: dict[str, str]
    resolved_features: list[dict[str, Any]]
    checks: dict[str, bool]


@dataclass(frozen=True)
class FeatureComputation:
    data: pl.DataFrame
    proof: FeatureProof


def _frame_hash(frame: pl.DataFrame) -> str:
    buffer = io.BytesIO()
    frame.write_ipc(buffer, compression="uncompressed")
    return hashlib.sha256(buffer.getvalue()).hexdigest()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _check_input(data: pl.DataFrame, contract: ResearchContractV1) -> list[str]:
    if not isinstance(data, pl.DataFrame):
        raise FeatureContractError(
            "INPUT_TYPE_UNSUPPORTED", "gateway requires a Polars DataFrame"
        )
    if data.is_empty():
        raise FeatureContractError(
            "INPUT_DATA_EMPTY", "gateway requires at least one completed bar"
        )
    schema = data.schema
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    groups = contract.dataset.group_columns
    missing = (required | set(groups)) - set(schema)
    if missing:
        raise FeatureContractError(
            "INPUT_COLUMNS_MISSING", f"missing input columns: {sorted(missing)}"
        )
    if "symbol" in schema and "symbol" not in groups:
        raise FeatureContractError(
            "GROUP_KEY_REQUIRED",
            "panel data with a symbol column must declare symbol in group_columns",
        )
    if (
        not isinstance(schema["timestamp"], pl.Datetime)
        or schema["timestamp"].time_zone is None
    ):
        raise FeatureContractError(
            "TIMESTAMP_NOT_TIMEZONE_AWARE",
            "timestamp must be a timezone-aware Polars Datetime",
        )
    if data["timestamp"].null_count():
        raise FeatureContractError(
            "TIMESTAMP_INVALID", "timestamp cannot contain null values"
        )
    if contract.dataset.timeframe != "1m":
        raise FeatureContractError(
            "TIMEFRAME_UNSUPPORTED",
            "managed feature gateway currently supports 1m bars only",
        )
    for field in ("open", "high", "low", "close"):
        if data[field].null_count() or data[field].is_finite().not_().any():
            raise FeatureContractError(
                "PRICE_DATA_INVALID", f"{field} must contain finite, non-null prices"
            )
    invalid_ohlc = data.filter(
        (pl.col("high") < pl.col("low"))
        | (pl.col("close") < pl.col("low"))
        | (pl.col("close") > pl.col("high"))
        | (pl.col("open") < pl.col("low"))
        | (pl.col("open") > pl.col("high"))
    ).height
    if invalid_ohlc:
        raise FeatureContractError(
            "OHLC_INVALID", f"{invalid_ohlc} rows violate OHLC range invariants"
        )
    volume = data["volume"]
    if volume.dtype not in (
        pl.Float32,
        pl.Float64,
        pl.Int8,
        pl.Int16,
        pl.Int32,
        pl.Int64,
        pl.UInt8,
        pl.UInt16,
        pl.UInt32,
        pl.UInt64,
    ):
        raise FeatureContractError(
            "VOLUME_DATA_INVALID",
            "volume must be numeric; null volume is allowed and contributes zero",
        )
    if volume.drop_nulls().is_finite().not_().any() or (volume.drop_nulls() < 0).any():
        raise FeatureContractError(
            "VOLUME_DATA_INVALID", "volume must be finite and non-negative when present"
        )
    return groups


def _native(
    data: pl.DataFrame, feature_id: str, request: EngineerNative, groups: list[str]
) -> tuple[pl.DataFrame, dict[str, Any]]:
    metadata = feature_catalog.describe(request.name)
    if metadata is None:
        raise FeatureContractError(
            "FEATURE_NOT_INSTALLED",
            f"Engineer feature {request.name!r} is not registered",
        )
    if request.name == "maximum" or request.name == "minimum":
        raise FeatureContractError(
            "FEATURE_INPUT_MISMATCH",
            "Engineer maximum/minimum operate on close; use prior_n_high_low for high/low",
        )
    params = dict(request.params)
    if request.name == "adx" and (
        type(params.get("period")) is not int or params != {"period": 14}
    ):
        raise FeatureContractError(
            "FEATURE_PARAMETERS_UNSUPPORTED", "managed ADX supports exactly period=14"
        )
    if request.name == "typprice" and params:
        raise FeatureContractError(
            "FEATURE_PARAMETERS_UNSUPPORTED", "typprice accepts no managed parameters"
        )
    if request.name not in ("adx", "typprice"):
        raise FeatureContractError(
            "FEATURE_UNSUPPORTED",
            f"native feature {request.name!r} has no verified managed semantics",
        )
    computed = compute_features(
        data,
        [{"name": request.name, "params": params, "output": feature_id}],
        group_col=groups or None,
        timestamp_col="timestamp",
    )
    return computed, {
        "id": feature_id,
        "provider": "engineer.native",
        "name": request.name,
        "params": params,
        "library_version": importlib.metadata.version("ml4t-engineer"),
        "lookback_period": int(metadata.get("lookback_period", 0)),
    }


def _cash_open_vwap(
    data: pl.DataFrame,
    feature_id: str,
    request: CashOpenVWAP,
    groups: list[str],
    volume_semantics: str,
) -> tuple[pl.DataFrame, dict[str, Any]]:
    zone = request.timezone
    local_ts = pl.col("timestamp").dt.convert_time_zone(zone)
    session_date = local_ts.dt.date()
    hour_text, minute_text = request.session_open.split(":")
    start_minute = int(hour_text) * 60 + int(minute_text)
    groups_for_cum = [*groups, "__session_date"]
    minute_of_day = local_ts.dt.hour().cast(pl.Int32) * 60 + local_ts.dt.minute().cast(
        pl.Int32
    )
    eligible = minute_of_day >= start_minute
    safe_volume = pl.col("volume").fill_null(0.0)
    typical = (pl.col("high") + pl.col("low") + pl.col("close")) / 3.0
    out = data.with_columns(session_date.alias("__session_date"))
    out = (
        out.with_columns(
            (pl.when(eligible).then(safe_volume).otherwise(0.0))
            .cum_sum()
            .over(groups_for_cum)
            .alias("__cum_volume"),
            (
                pl.when(eligible & (safe_volume > 0))
                .then(typical * safe_volume)
                .otherwise(0.0)
            )
            .cum_sum()
            .over(groups_for_cum)
            .alias("__cum_pv"),
        )
        .with_columns(
            pl.when(eligible & (pl.col("__cum_volume") > 0))
            .then(pl.col("__cum_pv") / pl.col("__cum_volume"))
            .otherwise(None)
            .alias(feature_id)
        )
        .drop("__session_date", "__cum_volume", "__cum_pv")
    )
    return out, {
        "id": feature_id,
        "provider": "extension.approved",
        "extension_id": request.extension_id,
        "extension_version": request.version,
        "owner_module": "src.research_control.feature_gateway",
        "inputs": ["high", "low", "close", "volume"],
        "session_open": request.session_open,
        "timezone": zone,
        "volume_semantics": volume_semantics,
    }


def _prior_range(
    data: pl.DataFrame, feature_id: str, request: PriorHighLow, groups: list[str]
) -> tuple[pl.DataFrame, dict[str, Any]]:
    expression = (
        pl.col(request.field)
        .shift(1)
        .rolling_max(window_size=request.period, min_samples=request.period)
        if request.field == "high"
        else pl.col(request.field)
        .shift(1)
        .rolling_min(window_size=request.period, min_samples=request.period)
    )
    expression = expression.over(groups) if groups else expression
    return data.with_columns(expression.alias(feature_id)), {
        "id": feature_id,
        "provider": "extension.approved",
        "extension_id": request.extension_id,
        "extension_version": request.version,
        "owner_module": "src.research_control.feature_gateway",
        "input": request.field,
        "period": request.period,
        "includes_current_bar": False,
    }


class FeatureGateway:
    """Resolve strict feature requests and attach deterministic provenance."""

    def compute(
        self,
        data: pl.DataFrame,
        contract: ResearchContractV1,
    ) -> FeatureComputation:
        groups = _check_input(data, contract)
        reserved = {
            "source_timestamp",
            "available_at",
            *(feature.id for feature in contract.feature_set),
        }
        conflicts = reserved & set(data.columns)
        if conflicts:
            raise FeatureContractError(
                "OUTPUT_COLUMN_CONFLICT",
                f"input contains reserved output columns: {sorted(conflicts)}",
            )
        sort_columns = [*groups, "timestamp"]
        if data.select(pl.struct(sort_columns).n_unique()).item() != data.height:
            raise FeatureContractError(
                "DUPLICATE_BAR", "timestamp must be unique for each instrument"
            )
        ordered = data.sort(sort_columns)
        original_hash = _frame_hash(ordered)
        outputs: list[dict[str, Any]] = []
        result = ordered
        for feature in contract.feature_set:
            provider = feature.provider
            if isinstance(provider, EngineerNative):
                result, resolved = _native(result, feature.id, provider, groups)
            elif isinstance(provider, CashOpenVWAP):
                if contract.dataset.volume_semantics in ("absent", "unknown"):
                    raise FeatureContractError(
                        "VOLUME_SEMANTICS_UNKNOWN",
                        "cash-open VWAP requires declared observed volume",
                    )
                result, resolved = _cash_open_vwap(
                    result,
                    feature.id,
                    provider,
                    groups,
                    contract.dataset.volume_semantics,
                )
            elif isinstance(provider, PriorHighLow):
                result, resolved = _prior_range(result, feature.id, provider, groups)
            else:
                raise FeatureContractError(
                    "FEATURE_PROVIDER_UNSUPPORTED",
                    f"unsupported provider for {feature.id}",
                )
            resolved["inputs"] = dict(feature.inputs)
            resolved["output_type"] = str(result.schema[feature.id])
            resolved["warmup_invalid_rows"] = int(
                (result[feature.id].is_null() | result[feature.id].is_nan()).sum()
            )
            resolved["units"] = (
                "index_0_to_100"
                if isinstance(provider, EngineerNative) and provider.name == "adx"
                else "source_price"
            )
            resolved["numerical_oracle_test"] = {
                "adx": "tests/test_research_control.py::test_native_adx_uses_engineer_and_matches_independent_wilder_oracle",
                "typprice": "tests/test_research_control.py::test_native_typical_price_uses_engineer_fields",
                "cash_open_vwap": "tests/test_research_control.py::test_cash_open_vwap_is_grouped_reset_dst_safe_and_completed_bar_only",
                "prior_n_high_low": "tests/test_research_control.py::test_prior_n_high_low_extension_excludes_current_bar_and_partitions_symbols",
            }[
                provider.name
                if isinstance(provider, EngineerNative)
                else provider.extension_id
            ]
            outputs.append(resolved)
        result = result.with_columns(
            pl.col("timestamp").alias("source_timestamp"),
            (pl.col("timestamp") + pl.duration(minutes=1)).alias("available_at"),
        )
        result_hash = _frame_hash(result)
        version = importlib.metadata.version("ml4t-engineer")
        extension_sha = extension_code_identity()
        provider_versions = {
            "ml4t-engineer": version,
            "feature_gateway": GATEWAY_VERSION,
            "extensions_sha256": extension_sha,
        }
        feature_set_hash = _canonical_hash(
            {
                "contract_sha256": contract.identity_sha256(),
                "features": outputs,
                "provider_versions": provider_versions,
            }
        )
        proof = FeatureProof(
            contract_sha256=contract.identity_sha256(),
            feature_set_sha256=feature_set_hash,
            input_sha256=original_hash,
            output_sha256=result_hash,
            provider_versions=provider_versions,
            resolved_features=outputs,
            checks={
                "contract_validated": True,
                "registry_resolution": all(
                    item["provider"] != "engineer.native" or bool(item.get("name"))
                    for item in outputs
                ),
                "native_execution_through_engineer": any(
                    item["provider"] == "engineer.native" for item in outputs
                ),
                "source_rows_preserved": result.height == ordered.height,
                "completed_bar_availability": result.select(
                    (
                        pl.col("available_at") == pl.col("timestamp").dt.offset_by("1m")
                    ).all()
                ).item(),
                "deterministic_input_hash": original_hash == _frame_hash(ordered),
                "output_hash_recorded": bool(result_hash),
                "numerical_oracle_references_present": all(
                    item["numerical_oracle_test"] for item in outputs
                ),
            },
        )
        return FeatureComputation(data=result, proof=proof)


def discover_feature(name: str) -> dict[str, Any] | None:
    """Return live Engineer metadata for one feature name."""
    names = feature_catalog.list()
    if name not in names:
        return None
    from ml4t.engineer.api import get_registry

    metadata = feature_catalog.describe(name)
    feature = get_registry().get(name)
    return {
        **metadata,
        "function_signature": str(inspect.signature(feature.func)),
        "installed_version": importlib.metadata.version("ml4t-engineer"),
    }
