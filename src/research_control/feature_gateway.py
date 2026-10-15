"""The only managed entry point for native and approved research features."""

from __future__ import annotations

import base64
import hashlib
import hmac
import importlib.metadata
import inspect
import io
import json
import math
import secrets
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl
import yaml
from ml4t.engineer import compute_features, feature_catalog

from .contracts import (
    CashOpenVWAP,
    EngineerNative,
    PriorHighLow,
    ResearchContractV1,
    extension_code_identity,
)

GATEWAY_VERSION = "1.1.0"
_PROOF_KEY = secrets.token_bytes(32)


class FeatureContractError(ValueError):
    """A requested feature cannot be executed with the declared semantics."""

    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class FeatureProof:
    config_sha256: str
    contract_sha256: str
    feature_set_sha256: str
    input_sha256: str
    output_sha256: str
    provider_versions: dict[str, str]
    resolved_features: list[dict[str, Any]]
    native_dispatch_trace: list[dict[str, Any]]
    checks: dict[str, bool]
    _seal: str | None = dataclass_field(
        default=None, init=False, repr=False, compare=False
    )


@dataclass(frozen=True)
class FeatureComputation:
    data: pl.DataFrame
    proof: FeatureProof


@dataclass(frozen=True)
class VerifiedFeatureProof:
    """A proof accepted by the runtime verifier for one frozen session."""

    proof: FeatureProof
    _seal: str | None = dataclass_field(
        default=None, init=False, repr=False, compare=False
    )


def _frame_hash(frame: pl.DataFrame) -> str:
    buffer = io.BytesIO()
    frame.write_ipc(buffer, compression="uncompressed")
    return hashlib.sha256(buffer.getvalue()).hexdigest()


def _series_hash(series: pl.Series) -> str:
    return _frame_hash(series.to_frame())


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _timeframe_delta(value: str) -> timedelta:
    supported = {"1m": timedelta(minutes=1), "30m": timedelta(minutes=30)}
    if value not in supported:
        raise FeatureContractError(
            "TIMEFRAME_UNSUPPORTED",
            f"timeframe {value!r} is unsupported; use 1m or 30m",
        )
    return supported[value]


def _proof_payload(proof: FeatureProof) -> dict[str, Any]:
    return {
        "config_sha256": proof.config_sha256,
        "contract_sha256": proof.contract_sha256,
        "feature_set_sha256": proof.feature_set_sha256,
        "input_sha256": proof.input_sha256,
        "output_sha256": proof.output_sha256,
        "provider_versions": proof.provider_versions,
        "resolved_features": proof.resolved_features,
        "native_dispatch_trace": proof.native_dispatch_trace,
        "checks": proof.checks,
    }


def _seal_proof(proof: FeatureProof) -> str:
    return hmac.new(
        _PROOF_KEY,
        json.dumps(
            _proof_payload(proof), sort_keys=True, separators=(",", ":")
        ).encode(),
        hashlib.sha256,
    ).hexdigest()


def require_verified_feature_proof(value: Any) -> VerifiedFeatureProof:
    """Reject asserted or reconstructed verified-proof objects."""
    if (
        not isinstance(value, VerifiedFeatureProof)
        or value._seal is None
        or value.proof._seal is None
        or not hmac.compare_digest(value.proof._seal, _seal_proof(value.proof))
        or not hmac.compare_digest(
            value._seal,
            hmac.new(
                _PROOF_KEY, value.proof._seal.encode(), hashlib.sha256
            ).hexdigest(),
        )
    ):
        raise FeatureContractError(
            "FEATURE_PROOF_FORGED",
            "verified feature proof was not issued by the runtime gate",
        )
    return value


def _sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _installed_callable_identity(function: Any) -> dict[str, str]:
    source = inspect.getsourcefile(function)
    distribution = importlib.metadata.distribution("ml4t-engineer")
    if source is None:
        raise FeatureContractError(
            "FEATURE_LIBRARY_IDENTITY_UNAVAILABLE",
            "installed Engineer implementation source is unavailable",
        )
    source_path = Path(source).resolve()
    package_file = next(
        (
            item
            for item in distribution.files or ()
            if Path(distribution.locate_file(item)).resolve() == source_path
        ),
        None,
    )
    if (
        package_file is None
        or package_file.hash is None
        or package_file.hash.mode != "sha256"
    ):
        raise FeatureContractError(
            "FEATURE_LIBRARY_IDENTITY_UNAVAILABLE",
            "Engineer callable is not bound to an installed distribution file",
        )
    digest = hashlib.sha256(source_path.read_bytes()).digest()
    installed_digest = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    if installed_digest != package_file.hash.value:
        raise FeatureContractError(
            "FEATURE_LIBRARY_IDENTITY_DRIFT",
            "installed Engineer source differs from its distribution identity",
        )
    return {
        "module": function.__module__,
        "name": function.__qualname__,
        "source_sha256": digest.hex(),
    }


def _called_callable_identity(function: Any) -> dict[str, str]:
    source = inspect.getsourcefile(function)
    if source is None:
        raise FeatureContractError(
            "FEATURE_LIBRARY_IDENTITY_UNAVAILABLE",
            "called Engineer API source is unavailable",
        )
    return {
        "module": function.__module__,
        "name": function.__qualname__,
        "source_sha256": _sha256_file(source),
    }


def _engineer_identity(contract: ResearchContractV1) -> tuple[str, str, str]:
    """Bind proof to the installed API and registry implementation files."""
    from ml4t import engineer
    from ml4t.engineer.api import get_registry

    functions = [engineer.compute_features]
    if any(
        isinstance(feature.provider, EngineerNative) for feature in contract.feature_set
    ):
        functions.extend(
            get_registry().get(feature.provider.name).func
            for feature in contract.feature_set
            if isinstance(feature.provider, EngineerNative)
        )
    identities = [_installed_callable_identity(function) for function in functions]
    api = _canonical_hash(identities)
    call = _canonical_hash(_called_callable_identity(compute_features))
    expected_call = _canonical_hash(
        _installed_callable_identity(engineer.compute_features)
    )
    return api, call, expected_call


def _session_contract_identity(
    session_root: str | Path, contract: ResearchContractV1
) -> str:
    """Resolve the frozen v1 config through its existing session authority."""
    from src.research_session import _load, _path, _root

    try:
        root = _root(session_root)
        _, frozen = _load(root, contract.session_id)
    except Exception as exc:
        raise FeatureContractError(
            "FEATURE_SESSION_IDENTITY_INVALID",
            "frozen research session identity could not be verified",
        ) from exc
    reference = frozen["identity"].get("config")
    if not reference or not reference.get("exists"):
        raise FeatureContractError(
            "FEATURE_CONFIG_IDENTITY_MISSING",
            "frozen session must link an existing feature contract config",
        )
    config_path = _path(root, reference["path"])
    config_bytes = config_path.read_bytes()
    if hashlib.sha256(config_bytes).hexdigest() != reference.get("sha256"):
        raise FeatureContractError(
            "FEATURE_CONFIG_IDENTITY_DRIFT",
            "frozen session config hash does not match its current file",
        )
    try:
        configured = ResearchContractV1.model_validate(yaml.safe_load(config_bytes))
    except Exception as exc:
        raise FeatureContractError(
            "FEATURE_CONFIG_IDENTITY_INVALID",
            "frozen session config is not a valid feature contract",
        ) from exc
    if configured.identity_sha256() != contract.identity_sha256():
        raise FeatureContractError(
            "FEATURE_CONFIG_IDENTITY_DRIFT",
            "runtime feature contract differs from frozen session config",
        )
    return hashlib.sha256(config_bytes).hexdigest()


def _adx_reference(
    high: list[float], low: list[float], close: list[float], period: int
) -> list[float]:
    size = len(high)
    true_range = [0.0] * size
    plus_dm = [0.0] * size
    minus_dm = [0.0] * size
    for index in range(1, size):
        up, down = high[index] - high[index - 1], low[index - 1] - low[index]
        true_range[index] = max(
            high[index] - low[index],
            abs(high[index] - close[index - 1]),
            abs(low[index] - close[index - 1]),
        )
        plus_dm[index] = up if up > down and up > 0 else 0.0
        minus_dm[index] = down if down > up and down > 0 else 0.0
    result = [math.nan] * size
    if size <= 2 * period - 1:
        return result
    # Seed with period-1 movements, then Wilder-smooth on index period.
    # This matches TA-Lib/installed Engineer's DX initialization exactly.
    smooth_tr = sum(true_range[1:period])
    smooth_plus = sum(plus_dm[1:period])
    smooth_minus = sum(minus_dm[1:period])
    dx = [math.nan] * size
    for index in range(period, size):
        smooth_tr += true_range[index] - smooth_tr / period
        smooth_plus += plus_dm[index] - smooth_plus / period
        smooth_minus += minus_dm[index] - smooth_minus / period
        plus_di = 100 * smooth_plus / smooth_tr if smooth_tr else 0.0
        minus_di = 100 * smooth_minus / smooth_tr if smooth_tr else 0.0
        total = plus_di + minus_di
        dx[index] = 100 * abs(plus_di - minus_di) / total if total else 0.0
    first = 2 * period - 1
    result[first] = sum(dx[period : first + 1]) / period
    for index in range(first + 1, size):
        result[index] = (result[index - 1] * (period - 1) + dx[index]) / period
    return result


def _expected_feature(
    data: pl.DataFrame, feature: Any, groups: list[str]
) -> list[float | None]:
    provider = feature.provider
    if isinstance(provider, EngineerNative) and provider.name == "adx":
        result: list[float | None] = [None] * data.height
        partitions = (
            data.partition_by(groups, maintain_order=True) if groups else [data]
        )
        cursor = 0
        for part in partitions:
            values = _adx_reference(
                part["high"].to_list(),
                part["low"].to_list(),
                part["close"].to_list(),
                14,
            )
            result[cursor : cursor + len(values)] = values
            cursor += len(values)
        return result
    if isinstance(provider, EngineerNative):
        return [
            (high + low + close) / 3
            for high, low, close in zip(
                data["high"].to_list(),
                data["low"].to_list(),
                data["close"].to_list(),
                strict=True,
            )
        ]
    if isinstance(provider, PriorHighLow):
        result = [None] * data.height
        partitions = (
            data.partition_by(groups, maintain_order=True) if groups else [data]
        )
        cursor = 0
        for part in partitions:
            values = part[provider.field].to_list()
            for index in range(provider.period, len(values)):
                window = values[index - provider.period : index]
                result[cursor + index] = (
                    max(window) if provider.field == "high" else min(window)
                )
            cursor += len(values)
        return result
    assert isinstance(provider, CashOpenVWAP)
    zone = ZoneInfo(provider.timezone)
    start_hour, start_minute = map(int, provider.session_open.split(":"))
    result = [None] * data.height
    groups_for_rows: dict[tuple[Any, ...], list[int]] = {}
    for index, row in enumerate(
        data.select([*groups, "timestamp"]).iter_rows(named=True)
    ):
        local = row["timestamp"].astimezone(zone)
        key = tuple(row[column] for column in groups) + (local.date(),)
        groups_for_rows.setdefault(key, []).append(index)
    highs, lows, closes, volumes = (
        data[column].to_list() for column in ("high", "low", "close", "volume")
    )
    for indices in groups_for_rows.values():
        total_volume = total_value = 0.0
        for index in indices:
            local = data["timestamp"][index].astimezone(zone)
            if (local.hour, local.minute) < (start_hour, start_minute):
                continue
            volume = float(volumes[index] or 0.0)
            total_volume += volume
            total_value += ((highs[index] + lows[index] + closes[index]) / 3) * volume
            if total_volume:
                result[index] = total_value / total_volume
    return result


def _assert_oracle(
    data: pl.DataFrame, contract: ResearchContractV1, output: pl.DataFrame
) -> None:
    groups = contract.dataset.group_columns
    for feature in contract.feature_set:
        expected = _expected_feature(data, feature, groups)
        actual = output[feature.id].to_list()
        tolerance = (
            0.15
            if isinstance(feature.provider, EngineerNative)
            and feature.provider.name == "adx"
            else 1e-9
        )
        if any(
            (
                (want is None or (isinstance(want, float) and math.isnan(want)))
                and got is not None
                and not (isinstance(got, float) and math.isnan(got))
            )
            or (
                want is not None
                and not (isinstance(want, float) and math.isnan(want))
                and (
                    got is None
                    or not math.isclose(
                        float(got), float(want), rel_tol=1e-9, abs_tol=tolerance
                    )
                )
            )
            for want, got in zip(expected, actual, strict=True)
        ):
            raise FeatureContractError(
                "FEATURE_NUMERICAL_MISMATCH",
                f"independent numerical oracle failed for {feature.id}",
            )


def verify_feature_proof(
    computation: FeatureComputation,
    input_data: pl.DataFrame,
    contract: ResearchContractV1,
    session_root: str | Path,
) -> VerifiedFeatureProof:
    """Accept only gateway output bound to a frozen config and independent checks."""
    if not isinstance(computation, FeatureComputation) or not isinstance(
        computation.proof, FeatureProof
    ):
        raise FeatureContractError(
            "FEATURE_PROOF_MISSING", "managed validation requires a FeatureProof"
        )
    proof = computation.proof
    if proof._seal is None or not hmac.compare_digest(proof._seal, _seal_proof(proof)):
        raise FeatureContractError(
            "FEATURE_PROOF_FORGED", "FeatureProof was not issued intact by this gateway"
        )
    groups = _check_input(input_data, contract)
    ordered = input_data.sort([*groups, "timestamp"])
    if proof.input_sha256 != _frame_hash(ordered):
        raise FeatureContractError(
            "FEATURE_INPUT_IDENTITY_DRIFT",
            "feature input hash does not match supplied data",
        )
    contract_identity = contract.identity_sha256()
    if (
        proof.contract_sha256 != contract_identity
        or proof.config_sha256 != contract_identity
    ):
        raise FeatureContractError(
            "FEATURE_CONFIG_IDENTITY_DRIFT",
            "feature proof contract/config identity changed",
        )
    _session_contract_identity(session_root, contract)
    version = importlib.metadata.version("ml4t-engineer")
    api_identity, call_identity, expected_call_identity = _engineer_identity(contract)
    expected_provider_versions = {
        "ml4t-engineer": version,
        "feature_gateway": GATEWAY_VERSION,
        "extensions_sha256": extension_code_identity(),
        "engineer_implementation_sha256": api_identity,
        "engineer_call_sha256": call_identity,
        "engineer_expected_call_sha256": expected_call_identity,
    }
    if proof.provider_versions != expected_provider_versions:
        raise FeatureContractError(
            "FEATURE_PROVIDER_IDENTITY_DRIFT",
            "feature provider/library identity changed",
        )
    if call_identity != expected_call_identity:
        raise FeatureContractError(
            "FEATURE_PROVIDER_IDENTITY_DRIFT",
            "gateway did not call the installed Engineer compute_features API",
        )
    expected_feature_hash = _canonical_hash(
        {
            "contract_sha256": contract_identity,
            "features": proof.resolved_features,
            "native_dispatch_trace": proof.native_dispatch_trace,
            "provider_versions": expected_provider_versions,
        }
    )
    if proof.feature_set_sha256 != expected_feature_hash:
        raise FeatureContractError(
            "FEATURE_SET_IDENTITY_DRIFT", "resolved feature identity changed"
        )
    expected_output = computation.data
    if proof.output_sha256 != _frame_hash(expected_output):
        raise FeatureContractError(
            "FEATURE_OUTPUT_IDENTITY_DRIFT",
            "feature output hash does not match supplied output",
        )
    required_output = {
        *ordered.columns,
        *(feature.id for feature in contract.feature_set),
        "source_timestamp",
        "available_at",
    }
    if not required_output.issubset(expected_output.columns):
        raise FeatureContractError(
            "FEATURE_OUTPUT_IDENTITY_DRIFT",
            "feature output is missing required columns",
        )
    native_features = [
        (feature, resolved)
        for feature, resolved in zip(
            contract.feature_set, proof.resolved_features, strict=True
        )
        if isinstance(feature.provider, EngineerNative)
    ]
    trace = proof.native_dispatch_trace
    if len(trace) != len(native_features):
        raise FeatureContractError(
            "FEATURE_NATIVE_EXECUTION_BYPASS",
            "each native feature must have one observed Engineer dispatch",
        )
    from ml4t import engineer

    expected_dispatcher = _installed_callable_identity(engineer.compute_features)
    for (feature, resolved), call in zip(native_features, trace, strict=True):
        request = feature.provider
        expected_spec = [
            {"name": request.name, "params": dict(request.params), "output": feature.id}
        ]
        if (
            resolved.get("id") != feature.id
            or resolved.get("provider") != "engineer.native"
            or resolved.get("name") != request.name
            or resolved.get("params") != dict(request.params)
            or call.get("specs") != expected_spec
            or call.get("kwargs")
            != {"group_col": groups or None, "timestamp_col": "timestamp"}
            or call.get("dispatcher") != expected_dispatcher
            or call.get("returned_frame_sha256") is None
            or call.get("returned_feature_sha256")
            != _series_hash(expected_output[feature.id])
        ):
            raise FeatureContractError(
                "FEATURE_NATIVE_EXECUTION_BYPASS",
                f"native feature {feature.id!r} was not returned by the installed Engineer dispatcher",
            )
    if expected_output.height != ordered.height or not expected_output.select(
        ordered.columns
    ).equals(ordered):
        raise FeatureContractError(
            "FEATURE_OUTPUT_SOURCE_DRIFT",
            "feature output changed source rows or input columns",
        )
    expected_availability = ordered["timestamp"] + _timeframe_delta(
        contract.dataset.timeframe
    )
    if not expected_output["source_timestamp"].equals(
        ordered["timestamp"]
    ) or not expected_output["available_at"].equals(expected_availability):
        raise FeatureContractError(
            "FEATURE_CAUSALITY_MISMATCH",
            "features must be available after the completed source bar",
        )
    _assert_oracle(ordered, contract, expected_output)
    verified = VerifiedFeatureProof(proof=proof)
    seal = hmac.new(_PROOF_KEY, proof._seal.encode(), hashlib.sha256).hexdigest()
    object.__setattr__(verified, "_seal", seal)
    return verified


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
    _timeframe_delta(contract.dataset.timeframe)
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
    data: pl.DataFrame,
    feature_id: str,
    request: EngineerNative,
    groups: list[str],
    dispatch: Any = None,
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
    computed = (dispatch or compute_features)(
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
    """Frozen v1 compatibility plus the dual-mode runtime feature route."""

    def compute_runtime(self, data: pl.DataFrame, spec: Any, *, isolate: bool = True) -> dict[str, Any]:
        """Check computed behavior without a native-status or feature-name permit.

        Existing compute(data, ResearchContractV1) keeps its frozen v1 semantics.
        New research uses this route or the identical factory/Workbench compiler.
        """
        from src.engine.feature_compiler import compile_and_verify
        features, evidence = compile_and_verify(data, spec, isolate=isolate)
        return {"status": "PASS", "data": features, "evidence": evidence.to_dict()}

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
        native_dispatch_trace: list[dict[str, Any]] = []
        result = ordered

        def dispatch_native(
            frame: pl.DataFrame, specs: list[dict[str, Any]], **kwargs: Any
        ) -> pl.DataFrame:
            called = compute_features
            computed = called(frame, specs, **kwargs)
            if not isinstance(computed, pl.DataFrame):
                raise FeatureContractError(
                    "FEATURE_NATIVE_EXECUTION_BYPASS",
                    "Engineer dispatcher did not return an eager Polars DataFrame",
                )
            native_dispatch_trace.append(
                {
                    "specs": specs,
                    "kwargs": kwargs,
                    "dispatcher": _called_callable_identity(called),
                    "input_sha256": _frame_hash(frame),
                    "returned_frame_sha256": _frame_hash(computed),
                    "returned_feature_sha256": _series_hash(
                        computed[specs[0]["output"]]
                    ),
                }
            )
            return computed

        for feature in contract.feature_set:
            provider = feature.provider
            if isinstance(provider, EngineerNative):
                before_calls = len(native_dispatch_trace)
                try:
                    result, resolved = _native(
                        result, feature.id, provider, groups, dispatch=dispatch_native
                    )
                except TypeError as exc:
                    if len(native_dispatch_trace) == before_calls:
                        raise FeatureContractError(
                            "FEATURE_NATIVE_EXECUTION_BYPASS",
                            f"native feature {feature.id!r} bypassed the observed Engineer dispatcher",
                        ) from exc
                    raise
                if len(native_dispatch_trace) != before_calls + 1:
                    raise FeatureContractError(
                        "FEATURE_NATIVE_EXECUTION_BYPASS",
                        f"native feature {feature.id!r} did not make exactly one Engineer dispatch",
                    )
                call = native_dispatch_trace[-1]
                if (
                    not isinstance(result, pl.DataFrame)
                    or call["returned_frame_sha256"] != _frame_hash(result)
                    or call["returned_feature_sha256"]
                    != _series_hash(result[feature.id])
                ):
                    raise FeatureContractError(
                        "FEATURE_NATIVE_EXECUTION_BYPASS",
                        f"native feature {feature.id!r} substituted the Engineer result",
                    )
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
        bar_delta = _timeframe_delta(contract.dataset.timeframe)
        result = result.with_columns(
            pl.col("timestamp").alias("source_timestamp"),
            (
                pl.col("timestamp")
                + pl.duration(seconds=int(bar_delta.total_seconds()))
            ).alias("available_at"),
        )
        result_hash = _frame_hash(result)
        version = importlib.metadata.version("ml4t-engineer")
        extension_sha = extension_code_identity()
        engineer_identity, engineer_call_identity, expected_engineer_call_identity = (
            _engineer_identity(contract)
        )
        provider_versions = {
            "ml4t-engineer": version,
            "feature_gateway": GATEWAY_VERSION,
            "extensions_sha256": extension_sha,
            "engineer_implementation_sha256": engineer_identity,
            "engineer_call_sha256": engineer_call_identity,
            "engineer_expected_call_sha256": expected_engineer_call_identity,
        }
        feature_set_hash = _canonical_hash(
            {
                "contract_sha256": contract.identity_sha256(),
                "features": outputs,
                "native_dispatch_trace": native_dispatch_trace,
                "provider_versions": provider_versions,
            }
        )
        proof = FeatureProof(
            config_sha256=contract.identity_sha256(),
            contract_sha256=contract.identity_sha256(),
            feature_set_sha256=feature_set_hash,
            input_sha256=original_hash,
            output_sha256=result_hash,
            provider_versions=provider_versions,
            resolved_features=outputs,
            native_dispatch_trace=native_dispatch_trace,
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
                        pl.col("available_at")
                        == pl.col("timestamp").dt.offset_by(
                            f"{int(bar_delta.total_seconds())}s"
                        )
                    ).all()
                ).item(),
                "deterministic_input_hash": original_hash == _frame_hash(ordered),
                "output_hash_recorded": bool(result_hash),
                "numerical_oracle_references_present": all(
                    item["numerical_oracle_test"] for item in outputs
                ),
            },
        )
        object.__setattr__(proof, "_seal", _seal_proof(proof))
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
