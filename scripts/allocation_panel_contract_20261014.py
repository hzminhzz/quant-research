"""Strict, development-only source panel contract for allocation research.

This module validates observed source equity rows. It does not create returns,
fit a model, or inspect the reserved retrospective holdout.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

DEV_START = pd.Timestamp("2019-09-09T00:00:00Z")
DEV_END = pd.Timestamp("2025-01-01T00:00:00Z")
LOCKED_START = DEV_END
LOCKED_END = pd.Timestamp("2026-07-15T00:00:00Z")

SOURCES = (
    "b0_nq_cfd",
    "c3_us500_us100_cfd",
    "donchian_btc_binance_perp",
    "rsi_es_cfd",
)

REQUIRED = (
    "timestamp",
    "available_at",
    "valuation_at",
    "currency",
    "native_nav_unit",
    "nav_denominator",
    "capital_basis",
    "position_basis",
    "capital_contract_id",
    "capital_contract_certified",
    "capital_contract_evidence_id",
    "sizing_contract_id",
    "sizing_contract_certified",
    "sizing_contract_evidence_id",
    "sizing_method",
    "leverage_profile_id",
    "max_leverage",
    "gross_notional",
    "gross_notional_currency",
    "gross_leverage",
    "allocator_capital_unit_id",
    "allocator_return_unit_id",
    "allocator_base_currency",
    "allocator_conversion_contract_id",
    "allocator_conversion_certified",
    "allocator_conversion_rate",
    "allocator_conversion_rate_unit",
    "costs_included",
    "funding_included",
    "observation_status",
    "position_exposure",
    "equity",
    "previous_equity",
    "net_return",
    "external_cash_flow",
    "allocator_equity",
    "previous_allocator_equity",
    "allocator_unit_return",
    "provenance_id",
)

CERTIFICATION_FLAGS = (
    "capital_contract_certified",
    "sizing_contract_certified",
    "allocator_conversion_certified",
)
RETURN_TOLERANCE = 1e-8


class PanelContractError(ValueError):
    """Raised when source data does not satisfy the strict panel contract."""


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    instrument_id: str
    expected_timestamps: tuple[pd.Timestamp, ...]
    provenance: str
    native_currency: str
    native_nav_unit: str
    certified_initial_nav: float
    capital_basis: str
    position_basis: str
    capital_contract_id: str
    capital_contract_evidence_id: str
    capital_contract_certified: bool
    sizing_contract_id: str
    sizing_contract_evidence_id: str
    sizing_contract_certified: bool
    sizing_method: str
    leverage_profile_id: str
    certified_max_leverage: float
    allocator_capital_unit_id: str
    allocator_return_unit_id: str
    allocator_base_currency: str
    allocator_conversion_contract_id: str
    allocator_conversion_certified: bool


def _utc_series(values: pd.Series, name: str) -> pd.Series:
    for value in values:
        if pd.isna(value):
            raise PanelContractError(f"{name} contains null or invalid timestamps")
        try:
            if pd.Timestamp(value).tzinfo is None:
                raise PanelContractError(f"{name} must be timezone-aware")
        except (TypeError, ValueError) as exc:
            if isinstance(exc, PanelContractError):
                raise
            raise PanelContractError(
                f"{name} contains null or invalid timestamps"
            ) from exc
    parsed = pd.to_datetime(values, utc=True, errors="coerce")
    if parsed.isna().any():
        raise PanelContractError(f"{name} contains null or invalid timestamps")
    return parsed


def validate_source(
    frame: pd.DataFrame,
    spec: SourceSpec,
) -> pd.DataFrame:
    """Validate a single source against its explicit trading calendar."""
    missing = sorted(set(REQUIRED) - set(frame.columns))
    if missing:
        raise PanelContractError(
            f"{spec.source_id}: missing required columns: {missing}"
        )
    if frame.empty:
        raise PanelContractError(f"{spec.source_id}: no source rows")

    out = frame.copy()
    out["source_id"] = spec.source_id
    out["instrument_id"] = spec.instrument_id
    out["timestamp"] = _utc_series(out["timestamp"], "timestamp")
    out["available_at"] = _utc_series(out["available_at"], "available_at")
    out["valuation_at"] = _utc_series(out["valuation_at"], "valuation_at")

    if (out["timestamp"] < DEV_START).any():
        raise PanelContractError(f"{spec.source_id}: row precedes development start")
    if (out["timestamp"] >= DEV_END).any():
        raise PanelContractError(
            f"{spec.source_id}: non-development row supplied; locked holdout is not opened"
        )
    if (out["available_at"] > out["valuation_at"]).any():
        raise PanelContractError(
            f"{spec.source_id}: value was unavailable at valuation time"
        )
    if (out["valuation_at"] < out["timestamp"]).any():
        raise PanelContractError(
            f"{spec.source_id}: valuation precedes panel timestamp"
        )

    if out["timestamp"].duplicated().any():
        raise PanelContractError(f"{spec.source_id}: duplicate timestamps")
    out = out.sort_values("timestamp", kind="stable").reset_index(drop=True)

    expected_values = _utc_series(
        pd.Series(spec.expected_timestamps), "expected_timestamps"
    )
    expected = pd.DatetimeIndex(expected_values)
    expected = expected[(expected >= DEV_START) & (expected < DEV_END)]
    if expected.has_duplicates:
        raise PanelContractError(
            f"{spec.source_id}: expected calendar contains duplicates"
        )
    observed = pd.DatetimeIndex(out["timestamp"])
    missing_dates = expected.difference(observed)
    extra_dates = observed.difference(expected)
    if len(missing_dates) or len(extra_dates):
        raise PanelContractError(
            f"{spec.source_id}: calendar mismatch; missing={len(missing_dates)}, "
            f"unexpected={len(extra_dates)}; no fill or zero imputation is allowed"
        )

    descriptor_columns = (
        "currency",
        "gross_notional_currency",
        "native_nav_unit",
        "capital_basis",
        "position_basis",
        "capital_contract_id",
        "capital_contract_evidence_id",
        "sizing_contract_id",
        "sizing_contract_evidence_id",
        "sizing_method",
        "leverage_profile_id",
        "allocator_capital_unit_id",
        "allocator_return_unit_id",
        "allocator_base_currency",
        "allocator_conversion_contract_id",
        "allocator_conversion_rate_unit",
        "provenance_id",
    )
    for name in descriptor_columns:
        if out[name].isna().any() or (out[name].astype(str).str.strip() == "").any():
            raise PanelContractError(f"{spec.source_id}: {name} is missing")
    if (
        out["provenance_id"].nunique() != 1
        or out["provenance_id"].iloc[0] != spec.provenance
    ):
        raise PanelContractError(
            f"{spec.source_id}: provenance does not match declared source"
        )
    certified_values = {
        "currency": spec.native_currency,
        "native_nav_unit": spec.native_nav_unit,
        "capital_basis": spec.capital_basis,
        "position_basis": spec.position_basis,
        "capital_contract_id": spec.capital_contract_id,
        "capital_contract_evidence_id": spec.capital_contract_evidence_id,
        "sizing_contract_id": spec.sizing_contract_id,
        "sizing_contract_evidence_id": spec.sizing_contract_evidence_id,
        "sizing_method": spec.sizing_method,
        "leverage_profile_id": spec.leverage_profile_id,
        "allocator_capital_unit_id": spec.allocator_capital_unit_id,
        "allocator_return_unit_id": spec.allocator_return_unit_id,
        "allocator_base_currency": spec.allocator_base_currency,
        "allocator_conversion_contract_id": spec.allocator_conversion_contract_id,
    }
    spec_certifications = (
        spec.capital_contract_certified,
        spec.sizing_contract_certified,
        spec.allocator_conversion_certified,
    )
    if any(
        not isinstance(flag, (bool, np.bool_)) or not flag
        for flag in spec_certifications
    ):
        raise PanelContractError(
            f"{spec.source_id}: SourceSpec contracts are not certified"
        )
    for column, certified_value in certified_values.items():
        if out[column].nunique() != 1 or out[column].iloc[0] != certified_value:
            raise PanelContractError(
                f"{spec.source_id}: row {column} does not match certified SourceSpec"
            )
    invariant_columns = descriptor_columns
    for name in invariant_columns:
        if out[name].nunique() != 1:
            raise PanelContractError(f"{spec.source_id}: {name} changes within source")
    if out["nav_denominator"].nunique() != 1:
        raise PanelContractError(f"{spec.source_id}: native NAV denominator changes")
    if out[["costs_included", "funding_included"]].isna().any().any():
        raise PanelContractError(
            f"{spec.source_id}: cost/funding inclusion flags are required"
        )
    for col in (*CERTIFICATION_FLAGS, "costs_included", "funding_included"):
        if not out[col].map(lambda value: isinstance(value, (bool, np.bool_))).all():
            raise PanelContractError(
                f"{spec.source_id}: {col} must contain explicit booleans"
            )
        if col in CERTIFICATION_FLAGS and not out[col].all():
            raise PanelContractError(
                f"{spec.source_id}: {col} must be certified for every row"
            )

    if not out["observation_status"].isin(("initial", "active", "idle_zero")).all():
        raise PanelContractError(
            f"{spec.source_id}: observation_status must be initial, active, or idle_zero"
        )
    numeric_columns = (
        "nav_denominator",
        "position_exposure",
        "max_leverage",
        "gross_notional",
        "gross_leverage",
        "allocator_conversion_rate",
        "equity",
        "previous_equity",
        "net_return",
        "external_cash_flow",
        "allocator_equity",
        "previous_allocator_equity",
        "allocator_unit_return",
    )
    initial = out["observation_status"].eq("initial")
    if int(initial.sum()) != 1 or not bool(initial.iloc[0]):
        raise PanelContractError(
            f"{spec.source_id}: exactly the first row must be initial"
        )
    nullable_initial_columns = (
        "previous_equity",
        "net_return",
        "external_cash_flow",
        "previous_allocator_equity",
        "allocator_unit_return",
    )
    for col in numeric_columns:
        values = pd.to_numeric(out[col], errors="coerce")
        allowed_null = (
            initial
            if col in nullable_initial_columns
            else pd.Series(False, index=out.index)
        )
        if (values.isna() & ~allowed_null).any() or not np.isfinite(
            values.dropna().to_numpy(dtype=float)
        ).all():
            raise PanelContractError(
                f"{spec.source_id}: {col} must be finite and observed"
            )
        out[col] = values
    positive_columns = (
        "nav_denominator",
        "equity",
        "allocator_equity",
        "allocator_conversion_rate",
        "max_leverage",
    )
    for col in positive_columns:
        if (out[col] <= 0).any():
            raise PanelContractError(f"{spec.source_id}: {col} must be positive")
    if not np.isclose(
        out["nav_denominator"].iloc[0],
        spec.certified_initial_nav,
        rtol=0,
        atol=RETURN_TOLERANCE,
    ) or not np.isclose(
        out["equity"].iloc[0],
        spec.certified_initial_nav,
        rtol=0,
        atol=RETURN_TOLERANCE,
    ):
        raise PanelContractError(
            f"{spec.source_id}: native NAV denominator and initial equity must match certified NAV"
        )
    for row in out.itertuples(index=False):
        rate_unit_expected = f"{row.allocator_base_currency}_per_{row.currency}"
        if row.allocator_conversion_rate_unit != rate_unit_expected:
            raise PanelContractError(
                f"{spec.source_id}: allocator conversion rate unit mismatch"
            )
        if row.gross_notional_currency != row.currency:
            raise PanelContractError(
                f"{spec.source_id}: gross notional currency differs from native equity"
            )
        if row.currency == row.allocator_base_currency and not np.isclose(
            row.allocator_conversion_rate, 1.0, rtol=0, atol=RETURN_TOLERANCE
        ):
            raise PanelContractError(
                f"{spec.source_id}: same-currency allocator conversion must be exactly one"
            )
        mapped_equity = row.equity * row.allocator_conversion_rate
        if not np.isclose(
            row.allocator_equity,
            mapped_equity,
            rtol=RETURN_TOLERANCE,
            atol=RETURN_TOLERANCE,
        ):
            raise PanelContractError(
                f"{spec.source_id}: allocator equity does not match certified conversion"
            )

    if (out["max_leverage"] <= 0).any():
        raise PanelContractError(
            f"{spec.source_id}: certified positive leverage limit is required"
        )
    if not np.isclose(
        out["max_leverage"].to_numpy(dtype=float),
        spec.certified_max_leverage,
        rtol=0,
        atol=RETURN_TOLERANCE,
    ).all():
        raise PanelContractError(
            f"{spec.source_id}: max leverage does not match certified contract"
        )
    expected_gross_leverage = out["gross_notional"].to_numpy(dtype=float) / out[
        "equity"
    ].to_numpy(dtype=float)
    if (out["gross_notional"] < 0).any() or (out["gross_leverage"] < 0).any():
        raise PanelContractError(f"{spec.source_id}: gross exposure cannot be negative")
    if not np.allclose(
        out["gross_leverage"].to_numpy(dtype=float),
        expected_gross_leverage,
        rtol=RETURN_TOLERANCE,
        atol=RETURN_TOLERANCE,
    ):
        raise PanelContractError(
            f"{spec.source_id}: gross leverage does not reconcile to equity"
        )
    if (out["gross_leverage"] > out["max_leverage"] + RETURN_TOLERANCE).any():
        raise PanelContractError(
            f"{spec.source_id}: observed gross leverage exceeds certified limit"
        )
    if (
        out.loc[
            initial,
            [
                "previous_equity",
                "net_return",
                "external_cash_flow",
                "previous_allocator_equity",
                "allocator_unit_return",
            ],
        ]
        .notna()
        .any()
        .any()
    ):
        raise PanelContractError(
            f"{spec.source_id}: initial row must not contain a fabricated interval return"
        )
    if (
        out.loc[initial, "position_exposure"].iloc[0] != 0
        or out.loc[initial, "gross_notional"].iloc[0] != 0
    ):
        raise PanelContractError(
            f"{spec.source_id}: initial row must have zero exposure"
        )
    if out["external_cash_flow"].dropna().ne(0).any():
        raise PanelContractError(
            f"{spec.source_id}: nonzero external cash flows need a separate certified return method"
        )

    previous = out.iloc[:-1]
    current = out.iloc[1:]
    if len(current):
        if not np.allclose(
            current["previous_equity"].to_numpy(dtype=float),
            previous["equity"].to_numpy(dtype=float),
            rtol=RETURN_TOLERANCE,
            atol=RETURN_TOLERANCE,
        ):
            raise PanelContractError(
                f"{spec.source_id}: previous_equity does not match prior observed mark"
            )
        expected_native_return = (
            current["equity"].to_numpy(dtype=float)
            / previous["equity"].to_numpy(dtype=float)
            - 1.0
        )
        if not np.allclose(
            current["net_return"].to_numpy(dtype=float),
            expected_native_return,
            rtol=RETURN_TOLERANCE,
            atol=RETURN_TOLERANCE,
        ):
            raise PanelContractError(
                f"{spec.source_id}: net_return does not reconcile to actual native equity"
            )
        if not np.allclose(
            current["previous_allocator_equity"].to_numpy(dtype=float),
            previous["allocator_equity"].to_numpy(dtype=float),
            rtol=RETURN_TOLERANCE,
            atol=RETURN_TOLERANCE,
        ):
            raise PanelContractError(
                f"{spec.source_id}: previous allocator mark does not match prior mapped equity"
            )
        expected_allocator_return = (
            current["allocator_equity"].to_numpy(dtype=float)
            / previous["allocator_equity"].to_numpy(dtype=float)
            - 1.0
        )
        if not np.allclose(
            current["allocator_unit_return"].to_numpy(dtype=float),
            expected_allocator_return,
            rtol=RETURN_TOLERANCE,
            atol=RETURN_TOLERANCE,
        ):
            raise PanelContractError(
                f"{spec.source_id}: allocator_unit_return does not reconcile to mapped equity"
            )

    idle = out["observation_status"].eq("idle_zero")
    if (
        (out.loc[idle, "position_exposure"] != 0).any()
        or (out.loc[idle, "gross_notional"] != 0).any()
        or (out.loc[idle, "net_return"] != 0).any()
    ):
        raise PanelContractError(
            f"{spec.source_id}: idle_zero requires observed zero exposure and zero native return"
        )
    active = out["observation_status"].eq("active")
    if (
        active
        & out["position_exposure"].eq(0)
        & out["gross_notional"].eq(0)
        & out["net_return"].eq(0)
    ).any():
        raise PanelContractError(
            f"{spec.source_id}: zero-exposure zero-return rows must be marked idle_zero"
        )

    # The source's declared calendar defines non-trading dates. The validator
    # does not infer a calendar or insert rows for those dates.
    return out


def build_development_panel(
    sources: Mapping[str, tuple[pd.DataFrame, SourceSpec]],
) -> pd.DataFrame:
    """Return observed, validated development rows in long form."""
    if set(sources) != set(SOURCES):
        raise PanelContractError(f"source set must be exactly {SOURCES}")
    for source_id, (_, spec) in sources.items():
        if source_id != spec.source_id:
            raise PanelContractError(
                f"source mapping key {source_id!r} does not match spec {spec.source_id!r}"
            )
    validated = [validate_source(frame, spec) for frame, spec in sources.values()]
    panel = (
        pd.concat(validated, ignore_index=True)
        .sort_values(["timestamp", "source_id"], kind="stable")
        .reset_index(drop=True)
    )
    # Native NAV values, currencies, position sizing, and leverage may differ.
    # A common normalized return is allowed only under an explicit certified
    # allocator-unit and return-unit contract for every source.
    for col in (
        "allocator_capital_unit_id",
        "allocator_return_unit_id",
        "allocator_base_currency",
    ):
        if panel[col].nunique() != 1:
            raise PanelContractError(f"sources have incompatible {col} contracts")
    if panel.duplicated(["source_id", "timestamp"]).any():
        raise PanelContractError("duplicate source/timestamp rows")
    return panel


def to_portfolio_sequence_batch(
    panel: pd.DataFrame,
    *,
    source_specs: Mapping[str, SourceSpec],
    feature_columns: Iterable[str],
    observed_return_column: str,
):
    """Create ML4T's linear batch only when every source/date cell exists.

    No feature or return is derived here. The supplied return column must be
    an observed source field. Missing cells fail; they are never filled.
    """
    from ml4t.models import PortfolioSequenceBatch

    if set(source_specs) != set(SOURCES):
        raise PanelContractError(f"source_specs must be exactly {SOURCES}")
    if "source_id" not in panel:
        raise PanelContractError("panel has no source_id column")
    if set(panel["source_id"].unique()) != set(SOURCES):
        raise PanelContractError(f"panel source set must be exactly {SOURCES}")
    source_frames: dict[str, tuple[pd.DataFrame, SourceSpec]] = {}
    for source_id, spec in source_specs.items():
        if source_id != spec.source_id:
            raise PanelContractError(f"source spec key mismatch for {source_id}")
        source_frame = panel.loc[panel["source_id"] == source_id].copy()
        if source_frame.empty:
            raise PanelContractError(f"panel missing source {source_id}")
        source_frames[source_id] = (source_frame, spec)
    panel = build_development_panel(source_frames)

    features = tuple(feature_columns)
    if not features or observed_return_column != "allocator_unit_return":
        raise PanelContractError(
            "explicit features and allocator_unit_return are required for common-capital inputs"
        )
    required = {
        "timestamp",
        "source_id",
        "observation_status",
        *features,
        observed_return_column,
    }
    missing_columns = sorted(required - set(panel.columns))
    if missing_columns:
        raise PanelContractError(
            f"panel missing tensor input columns: {missing_columns}"
        )
    assets = tuple(sorted(panel["source_id"].unique()))
    returns_panel = panel.loc[panel["observation_status"] != "initial"].copy()
    times = tuple(sorted(pd.DatetimeIndex(returns_panel["timestamp"].unique())))
    expected = len(times) * len(assets)
    if (
        len(returns_panel) != expected
        or returns_panel.duplicated(["timestamp", "source_id"]).any()
    ):
        raise PanelContractError(
            "panel is not rectangular; no calendar alignment or imputation"
        )
    ordered = returns_panel.sort_values(["timestamp", "source_id"], kind="stable")
    x = (
        ordered.loc[:, features]
        .apply(pd.to_numeric, errors="coerce")
        .to_numpy(dtype=float)
    )
    y = pd.to_numeric(ordered[observed_return_column], errors="coerce").to_numpy(
        dtype=float
    )
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise PanelContractError(
            "tensor inputs contain missing or non-finite observations"
        )
    x = x.reshape(1, len(times), len(assets), len(features))
    y = y.reshape(1, len(times), len(assets))
    return PortfolioSequenceBatch(
        features=x,
        returns=y,
        timestamps=times,
        asset_ids=assets,
        metadata={"purpose": "development_panel_contract", "fit_performed": False},
    )


def main() -> int:
    raise SystemExit(
        "Provide canonical source frames and explicit calendars through the Python API; "
        "this module does not guess source files or calendars."
    )


if __name__ == "__main__":
    main()
