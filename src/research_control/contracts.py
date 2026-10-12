"""Strict versioned declarations for managed Engineer feature computation."""

from __future__ import annotations

import hashlib
import json
from datetime import time
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


InputMap = dict[StrictStr, StrictStr]
Scalar = StrictInt | StrictFloat | StrictStr | bool


class EngineerNative(StrictModel):
    kind: Literal["engineer.native"]
    name: StrictStr
    params: dict[StrictStr, Scalar] = Field(default_factory=dict)


class CashOpenVWAP(StrictModel):
    kind: Literal["extension.approved"]
    extension_id: Literal["cash_open_vwap"]
    version: Literal["1.0.0"]
    session_open: StrictStr
    timezone: StrictStr

    @field_validator("session_open")
    @classmethod
    def valid_open(cls, value: str) -> str:
        try:
            time.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("session_open must be an ISO local time") from exc
        if len(value) != 5:
            raise ValueError("session_open must use HH:MM")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA zone") from exc
        return value


class PriorHighLow(StrictModel):
    kind: Literal["extension.approved"]
    extension_id: Literal["prior_n_high_low"]
    version: Literal["1.0.0"]
    field: Literal["high", "low"]
    period: Annotated[StrictInt, Field(ge=1, le=10000)]


ApprovedExtension = Annotated[
    CashOpenVWAP | PriorHighLow,
    Field(discriminator="extension_id"),
]
Provider = Annotated[
    EngineerNative | ApprovedExtension,
    Field(discriminator="kind"),
]


class FeatureRequest(StrictModel):
    id: Annotated[StrictStr, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    provider: Provider
    inputs: InputMap

    @model_validator(mode="after")
    def exact_feature_contract(self) -> FeatureRequest:
        provider = self.provider
        if isinstance(provider, EngineerNative):
            if provider.name in ("maximum", "minimum"):
                if self.inputs != {"close": "close"}:
                    raise ValueError(
                        "FEATURE_INPUT_MISMATCH: Engineer maximum/minimum accept close, not high/low"
                    )
                raise ValueError(
                    "FEATURE_UNSUPPORTED: use prior_n_high_low for prior-bar high/low"
                )
            if provider.name not in ("adx", "typprice"):
                raise ValueError(
                    f"FEATURE_UNSUPPORTED: native {provider.name!r} has no verified managed contract"
                )
            expected = {
                "adx": {"high": "high", "low": "low", "close": "close"},
                "typprice": {"high": "high", "low": "low", "close": "close"},
            }[provider.name]
            if self.inputs != expected:
                raise ValueError(f"{provider.name} requires exact inputs {expected}")
            if provider.name == "adx" and (
                provider.params.keys() != {"period"}
                or type(provider.params.get("period")) is not int
                or provider.params["period"] != 14
            ):
                raise ValueError("managed native ADX supports exactly period=14")
            if provider.name == "typprice" and provider.params:
                raise ValueError("typprice has no supported parameters")
        elif isinstance(provider, CashOpenVWAP):
            expected = {
                "high": "high",
                "low": "low",
                "close": "close",
                "volume": "volume",
            }
            if self.inputs != expected:
                raise ValueError(f"cash_open_vwap requires exact inputs {expected}")
        elif isinstance(provider, PriorHighLow):
            expected = {provider.field: provider.field}
            if self.inputs != expected:
                raise ValueError(f"prior_n_high_low requires exact input {expected}")
        return self


class DatasetContract(StrictModel):
    requested_product: StrictStr
    source_vendor: StrictStr
    source_symbol: StrictStr
    catalog_dataset_key: StrictStr | None
    external_exception_id: StrictStr | None
    authority: Literal["canonical", "secondary", "staged_noncanonical"]
    product_class: Literal[
        "spot", "perpetual", "dated_future", "continuous_future", "cfd", "index"
    ]
    role: Literal["price_proxy", "tradable_contract"]
    volume_semantics: Literal[
        "genuine_exchange_traded", "broker_tick_or_quote_proxy", "absent", "unknown"
    ]
    timeframe: Annotated[StrictStr, Field(pattern=r"^[1-9][0-9]*[smhd]$")]
    timestamp_convention: Literal["bar_start"]
    timezone: StrictStr
    group_columns: Annotated[list[StrictStr], Field(max_length=8)]

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA zone") from exc
        return value

    @model_validator(mode="after")
    def truthful_source_and_volume(self) -> DatasetContract:
        if len(self.group_columns) != len(set(self.group_columns)):
            raise ValueError("group_columns must be unique")
        if (
            self.catalog_dataset_key is None or self.authority != "canonical"
        ) and not self.external_exception_id:
            raise ValueError(
                "a non-canonical or uncatalogued source requires external_exception_id"
            )
        if self.authority == "canonical" and self.catalog_dataset_key is None:
            raise ValueError("canonical authority requires a catalog_dataset_key")
        if (
            self.product_class == "cfd"
            and self.volume_semantics == "genuine_exchange_traded"
        ):
            raise ValueError(
                "CFD volume cannot be claimed as genuine exchange-traded volume"
            )
        if "dukascopy" in self.source_vendor.lower() and (
            self.product_class != "cfd"
            or self.volume_semantics == "genuine_exchange_traded"
        ):
            raise ValueError(
                "Dukascopy USATECH data is a CFD proxy and cannot claim exchange-traded volume"
            )
        if "usatech" in self.source_symbol.lower() and self.product_class != "cfd":
            raise ValueError(
                "USATECH.IDX/USD is a CFD source, not a dated futures contract"
            )
        if "dukascopy" in self.requested_product.lower() and (
            self.source_symbol.upper() == "NQ.F"
            or "lse_futures" in (self.catalog_dataset_key or "").lower()
        ):
            raise ValueError("LSE NQ.F is not Dukascopy USATECH.IDX/USD")
        if "CME" in self.requested_product.upper() and (
            self.product_class != "dated_future"
            or self.volume_semantics != "genuine_exchange_traded"
        ):
            raise ValueError(
                "CME traded-volume claims require a dated future and genuine exchange volume"
            )
        if self.role == "tradable_contract" and self.product_class in (
            "cfd",
            "index",
            "continuous_future",
        ):
            raise ValueError(
                "a CFD, index, or continuous future cannot claim a dated tradable contract"
            )
        return self


class StrategyContract(StrictModel):
    rule_id: Annotated[StrictStr, Field(min_length=1, max_length=120)]
    engine: Literal["ml4t.backtest"]


class EvaluationContract(StrictModel):
    development: Annotated[list[StrictStr], Field(min_length=2, max_length=2)]
    retrospective_validation: (
        Annotated[list[StrictStr], Field(min_length=2, max_length=2)] | None
    ) = None
    holdout_start: StrictStr | None = None


class ResearchContractV1(StrictModel):
    schema_version: Literal[1]
    session_id: Annotated[StrictStr, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")]
    dataset: DatasetContract
    feature_set: Annotated[list[FeatureRequest], Field(min_length=1, max_length=32)]
    strategy: StrategyContract
    evaluation: EvaluationContract

    @model_validator(mode="after")
    def unique_feature_ids(self) -> ResearchContractV1:
        ids = [feature.id for feature in self.feature_set]
        if len(ids) != len(set(ids)):
            raise ValueError("feature IDs must be unique")
        return self

    def identity_sha256(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


def extension_code_identity() -> str:
    """Return a stable identity for this gateway's approved extension code."""
    from . import feature_gateway

    return hashlib.sha256(Path(feature_gateway.__file__).read_bytes()).hexdigest()
