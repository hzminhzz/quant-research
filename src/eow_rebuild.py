"""Auditable rebuild of the historical 4-index EOW + meta-gated ORB study.

This module deliberately keeps two lanes:
- legacy_parity: fixed UTC session hours, signal-close execution, the historical
  Friday >=20 UTC / observed-bar expiry behavior, and legacy point-in-time joins.
- corrected: local strategy clocks, next-bar execution, close-confirmed features,
  exchange-calendar EOW expiry, globally chronological validation, and explicit
  transaction-cost scenarios.

The legacy runner remains untouched and is treated as an oracle/reference only.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import pickle
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import polars as pl
import talib
import yaml
from scipy import stats
from sklearn.metrics import roc_auc_score

from ml4t.diagnostic.splitters import CombinatorialCV

from src.features import extract_breakout_feature_vector
from src.labeling import ORBTradeEvent, compute_sample_uniqueness_weights
from src.models import train_meta_classifier_cpcv
from src.session_calendar import (
    StrategyAnchor,
    anchor_window,
    calendar_sessions,
    last_exchange_session_of_week,
    parse_clock,
)


UTC = timezone.utc
FEATURES = (
    "rvol_1h",
    "vwap_alignment",
    "wick_exhaustion",
    "range_to_atr20",
    "garman_klass_norm",
    "spx_alignment",
    "nr7_flag",
    "breakout_bar_range_ratio",
)


class EOWRebuildError(RuntimeError):
    """Fail-closed rebuild contract error."""


@dataclass(frozen=True)
class InstrumentSpec:
    symbol: str
    file: str
    bar_duration: timedelta
    market_timezone: str
    exchange_calendar: str
    anchor: StrategyAnchor
    legacy_fixed_utc_hour: int


@dataclass
class PreparedMarket:
    spec: InstrumentSpec
    frame: pl.DataFrame
    timestamps: list[datetime]
    available_at: list[datetime]
    utc_dates: list[date]
    market_dates: list[date]
    opens: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    closes: np.ndarray
    volumes: np.ndarray
    atr20: np.ndarray
    ema200: np.ndarray
    legacy_spx_close: np.ndarray
    legacy_spx_vwap: np.ndarray
    canonical_spx_close: np.ndarray
    canonical_spx_vwap: np.ndarray
    canonical_spx_available_at: list[datetime | None]
    utc_date_indices: dict[date, list[int]]
    market_date_indices: dict[date, list[int]]
    scheduled_sessions: set[date]


@dataclass
class EventBuildResult:
    variant: str
    roundtrip_cost_bps: float
    events: list[ORBTradeEvent]
    ledger: pl.DataFrame
    diagnostics: dict[str, Any]


@dataclass
class LegacyModelResult:
    model: Any
    oof_scores: np.ndarray
    oof_coverage: np.ndarray
    mean_auc: float


def parse_utc(value: str | datetime) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset() is None:
        raise EOWRebuildError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    os.replace(temporary, path)


def atomic_write_parquet(path: Path, frame: pl.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    frame.write_parquet(temporary)
    os.replace(temporary, path)


def load_config(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text())
    if not isinstance(payload, dict):
        raise EOWRebuildError("rebuild config must be a mapping")
    return payload


def _duration(value: str) -> timedelta:
    unit = value[-1].lower()
    amount = float(value[:-1])
    if unit == "d":
        return timedelta(days=amount)
    if unit == "h":
        return timedelta(hours=amount)
    if unit == "m":
        return timedelta(minutes=amount)
    raise EOWRebuildError(f"unsupported duration {value}")


def instrument_specs(config: dict[str, Any]) -> list[InstrumentSpec]:
    strategy = config["strategy"]
    opening_range = timedelta(minutes=int(strategy["opening_range_minutes"]))
    candidate_window = timedelta(minutes=int(strategy["candidate_window_minutes"]))
    specs: list[InstrumentSpec] = []
    for raw in config["data"]["instruments"]:
        anchor_raw = raw["strategy_anchor"]
        specs.append(
            InstrumentSpec(
                symbol=str(raw["symbol"]),
                file=str(raw["file"]),
                bar_duration=timedelta(minutes=int(raw["bar_duration_minutes"])),
                market_timezone=str(raw["market_timezone"]),
                exchange_calendar=str(raw["exchange_calendar"]),
                anchor=StrategyAnchor(
                    name=str(anchor_raw["name"]),
                    timezone=str(anchor_raw["timezone"]),
                    local_time=parse_clock(str(anchor_raw["local_time"])),
                    opening_range=opening_range,
                    candidate_window=candidate_window,
                ),
                legacy_fixed_utc_hour=int(raw["legacy_fixed_utc_hour"]),
            )
        )
    return specs


def audit_dataset(path: Path, *, expected_timezone: str = "UTC") -> dict[str, Any]:
    if not path.is_file():
        return {"file": str(path), "status": "BLOCKED", "reason": "missing_file"}
    frame = pl.read_parquet(path)
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    missing = sorted(required - set(frame.columns))
    if missing:
        return {
            "file": str(path),
            "status": "BLOCKED",
            "reason": "missing_columns",
            "missing_columns": missing,
        }

    timestamps = frame.get_column("timestamp")
    dtype = timestamps.dtype
    timezone_name = getattr(dtype, "time_zone", None)
    values = timestamps.to_list()
    ordered = all(values[i] < values[i + 1] for i in range(len(values) - 1))
    unique = timestamps.n_unique() == len(frame)
    null_counts = {
        column: int(count)
        for column, count in zip(frame.columns, frame.null_count().row(0))
    }
    reasons: list[str] = []
    if timezone_name != expected_timezone:
        reasons.append(f"timestamp_timezone_{timezone_name!r}_expected_{expected_timezone}")
    if not ordered:
        reasons.append("timestamps_not_strictly_sorted")
    if not unique:
        reasons.append("duplicate_timestamps")
    if any(null_counts.get(column, 0) for column in required):
        reasons.append("required_nulls_present")
    valid_ohlc = bool(
        frame.select(
            (
                (pl.col("high") >= pl.max_horizontal("open", "close", "low"))
                & (pl.col("low") <= pl.min_horizontal("open", "close", "high"))
                & (pl.col("high") >= pl.col("low"))
            ).all()
        ).item()
    )
    if not valid_ohlc:
        reasons.append("ohlc_inconsistent")
    return {
        "file": str(path),
        "status": "READY" if not reasons else "BLOCKED",
        "blocking_reasons": reasons,
        "rows": len(frame),
        "sha256": sha256_file(path),
        "timestamp_dtype": str(dtype),
        "source_timezone": timezone_name,
        "min_timestamp": values[0].isoformat() if values else None,
        "max_timestamp": values[-1].isoformat() if values else None,
        "strictly_sorted": ordered,
        "unique": unique,
        "null_counts": null_counts,
        "ohlc_consistent": valid_ohlc,
    }


def preflight(root: Path, config_path: Path) -> dict[str, Any]:
    config = load_config(config_path)
    contracts = config["data"]["timestamp_semantics"]
    expected_tz = str(contracts["source_timezone"])
    files = [
        audit_dataset(root / spec.file, expected_timezone=expected_tz)
        for spec in instrument_specs(config)
    ]
    benchmark = config["data"]["benchmark"]
    files.append(
        audit_dataset(root / str(benchmark["file"]), expected_timezone=expected_tz)
    )

    de30 = next(spec for spec in instrument_specs(config) if spec.symbol == "DE30")
    de_winter = anchor_window(date(2024, 1, 15), de30.anchor).anchor_utc
    de_summer = anchor_window(date(2024, 7, 15), de30.anchor).anchor_utc
    de_contract_ok = de_winter.hour == 14 and de_summer.hour == 13

    readiness = all(item["status"] == "READY" for item in files) and de_contract_ok
    return {
        "schema_version": "eow_rebuild_preflight/v1",
        "status": "READY" if readiness else "BLOCKED",
        "config_sha256": sha256_file(config_path),
        "timestamp_semantics": contracts,
        "files": files,
        "de30_new_york_overlap_contract": {
            "anchor_timezone": de30.anchor.timezone,
            "anchor_local_time": de30.anchor.local_time.isoformat(),
            "winter_utc": de_winter.isoformat(),
            "summer_utc": de_summer.isoformat(),
            "passed": de_contract_ok,
        },
    }


def _benchmark_frames(
    root: Path,
    config: dict[str, Any],
    *,
    end: datetime,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    raw = config["data"]["benchmark"]
    duration = timedelta(minutes=int(raw["bar_duration_minutes"]))
    frame = (
        pl.read_parquet(root / str(raw["file"]))
        .sort("timestamp")
        .filter(pl.col("timestamp") <= end)
        .with_columns(
            pl.col("timestamp").cast(pl.String).alias("source_timestamp_raw"),
            pl.col("timestamp").dt.date().alias("_utc_date"),
            pl.col("timestamp")
            .dt.convert_time_zone(str(raw["market_timezone"]))
            .dt.date()
            .alias("_market_date"),
            ((pl.col("high") + pl.col("low") + pl.col("close")) / 3.0).alias("_tp"),
            pl.when(pl.col("volume") > 0)
            .then(pl.col("volume"))
            .otherwise(1.0)
            .alias("_eff_vol"),
        )
        .with_columns((pl.col("_tp") * pl.col("_eff_vol")).alias("_pv"))
    )
    frame = frame.with_columns(
        (
            pl.col("_pv").cum_sum().over("_utc_date")
            / pl.col("_eff_vol").cum_sum().over("_utc_date")
        ).alias("legacy_spx_vwap"),
        (
            pl.col("_pv").cum_sum().over("_market_date")
            / pl.col("_eff_vol").cum_sum().over("_market_date")
        ).alias("canonical_spx_vwap"),
        (pl.col("timestamp") + duration).alias("spx_available_at"),
    )

    legacy = frame.select(
        "timestamp",
        pl.col("close").alias("legacy_spx_close"),
        "legacy_spx_vwap",
    )
    canonical = frame.select(
        "spx_available_at",
        pl.col("close").alias("canonical_spx_close"),
        "canonical_spx_vwap",
    )
    return legacy, canonical


def _date_indices(values: Sequence[date]) -> dict[date, list[int]]:
    result: dict[date, list[int]] = {}
    for idx, value in enumerate(values):
        result.setdefault(value, []).append(idx)
    return result


def prepare_market(
    root: Path,
    spec: InstrumentSpec,
    *,
    legacy_spx: pl.DataFrame,
    canonical_spx: pl.DataFrame,
    end: datetime,
) -> PreparedMarket:
    frame = (
        pl.read_parquet(root / spec.file)
        .sort("timestamp")
        .filter(pl.col("timestamp") <= end)
    )
    timezone_name = getattr(frame.schema["timestamp"], "time_zone", None)
    if timezone_name != "UTC":
        raise EOWRebuildError(
            f"{spec.symbol} timestamps must be tz-aware UTC, got {frame.schema['timestamp']}"
        )
    frame = frame.with_columns(
        pl.col("timestamp").cast(pl.String).alias("source_timestamp_raw"),
        (pl.col("timestamp") + spec.bar_duration).alias("available_at"),
        pl.col("timestamp").dt.date().alias("utc_date"),
        pl.col("timestamp")
        .dt.convert_time_zone(spec.market_timezone)
        .dt.date()
        .alias("market_date"),
        pl.col("close").ewm_mean(span=200, adjust=False).alias("ema_200"),
    )

    hourly = frame.group_by_dynamic(
        "timestamp", every="1h", closed="left", label="left"
    ).agg(
        pl.col("open").first(),
        pl.col("high").max(),
        pl.col("low").min(),
        pl.col("close").last(),
    )
    atr_values = talib.ATR(
        hourly["high"].to_numpy(),
        hourly["low"].to_numpy(),
        hourly["close"].to_numpy(),
        timeperiod=20,
    )
    hourly = hourly.with_columns(pl.Series("atr20_bar", atr_values).shift(1))
    frame = frame.join_asof(
        hourly.select("timestamp", "atr20_bar").sort("timestamp"),
        on="timestamp",
        strategy="backward",
    )

    frame = frame.join_asof(
        legacy_spx.sort("timestamp"),
        on="timestamp",
        strategy="backward",
    )
    frame = frame.join_asof(
        canonical_spx.sort("spx_available_at"),
        left_on="available_at",
        right_on="spx_available_at",
        strategy="backward",
    )
    frame = frame.with_columns(
        (
            pl.col("available_at") - pl.col("spx_available_at")
        ).dt.total_seconds().alias("spx_staleness_seconds")
    )

    timestamps = frame["timestamp"].to_list()
    available = frame["available_at"].to_list()
    utc_dates = frame["utc_date"].to_list()
    market_dates = frame["market_date"].to_list()
    min_date = min(market_dates)
    max_date = max(market_dates)
    scheduled = set(calendar_sessions(spec.exchange_calendar, min_date, max_date))

    def floats(column: str) -> np.ndarray:
        return np.asarray(
            [np.nan if value is None else float(value) for value in frame[column].to_list()],
            dtype=float,
        )

    return PreparedMarket(
        spec=spec,
        frame=frame,
        timestamps=timestamps,
        available_at=available,
        utc_dates=utc_dates,
        market_dates=market_dates,
        opens=floats("open"),
        highs=floats("high"),
        lows=floats("low"),
        closes=floats("close"),
        volumes=floats("volume"),
        atr20=floats("atr20_bar"),
        ema200=floats("ema_200"),
        legacy_spx_close=floats("legacy_spx_close"),
        legacy_spx_vwap=floats("legacy_spx_vwap"),
        canonical_spx_close=floats("canonical_spx_close"),
        canonical_spx_vwap=floats("canonical_spx_vwap"),
        canonical_spx_available_at=frame["spx_available_at"].to_list(),
        utc_date_indices=_date_indices(utc_dates),
        market_date_indices=_date_indices(market_dates),
        scheduled_sessions=scheduled,
    )


def prepare_all_markets(
    root: Path,
    config: dict[str, Any],
    *,
    end: datetime,
) -> dict[str, PreparedMarket]:
    legacy_spx, canonical_spx = _benchmark_frames(root, config, end=end)
    return {
        spec.symbol: prepare_market(
            root,
            spec,
            legacy_spx=legacy_spx,
            canonical_spx=canonical_spx,
            end=end,
        )
        for spec in instrument_specs(config)
    }


def _finite(value: float | None) -> bool:
    return value is not None and np.isfinite(float(value))


def _legacy_session(
    market: PreparedMarket,
    trading_date: date,
) -> tuple[list[int], list[int], datetime] | None:
    indices = market.utc_date_indices.get(trading_date, [])
    indices = [
        idx
        for idx in indices
        if market.spec.legacy_fixed_utc_hour
        <= market.timestamps[idx].hour
        < market.spec.legacy_fixed_utc_hour + 6
    ]
    if len(indices) < 16:
        return None
    opening = indices[:12]
    candidates = indices[12:30]
    if not candidates:
        return None
    anchor = market.timestamps[opening[0]]
    return opening, candidates, anchor


def _corrected_session(
    market: PreparedMarket,
    trading_date: date,
) -> tuple[list[int], list[int], datetime] | None:
    if trading_date not in market.scheduled_sessions:
        return None
    window = anchor_window(trading_date, market.spec.anchor)
    indices = market.market_date_indices.get(trading_date, [])
    opening = [
        idx
        for idx in indices
        if window.anchor_utc <= market.timestamps[idx] < window.opening_range_end_utc
    ]
    candidates = [
        idx
        for idx in indices
        if window.opening_range_end_utc
        <= market.timestamps[idx]
        < window.candidate_end_utc
    ]
    expected = int(
        market.spec.anchor.opening_range.total_seconds()
        / market.spec.bar_duration.total_seconds()
    )
    if len(opening) != expected:
        return None
    if not candidates:
        return None
    return opening, candidates, window.anchor_utc


def _eow_index(
    market: PreparedMarket,
    session_date: date,
) -> tuple[int | None, date | None, str | None]:
    scheduled = last_exchange_session_of_week(
        market.spec.exchange_calendar, session_date
    )
    indices = market.market_date_indices.get(scheduled)
    if indices:
        return indices[-1], scheduled, None

    monday = session_date - timedelta(days=session_date.weekday())
    observed = sorted(
        day
        for day in market.market_date_indices
        if monday <= day <= scheduled and day in market.scheduled_sessions
    )
    if not observed:
        return None, scheduled, "no_observed_session_in_week"
    substitute = observed[-1]
    return (
        market.market_date_indices[substitute][-1],
        scheduled,
        f"missing_scheduled_session_used_{substitute.isoformat()}",
    )


def _feature_snapshot(
    market: PreparedMarket,
    opening: list[int],
    candidate_idx: int,
    *,
    canonical: bool,
    direction: int,
    or_high: float,
    or_low: float,
    or_range: float,
    atr20: float,
) -> dict[str, float]:
    or_df = market.frame[opening]
    current = market.frame.slice(candidate_idx, 1)
    if canonical:
        spx_c = market.canonical_spx_close[candidate_idx]
        spx_v = market.canonical_spx_vwap[candidate_idx]
    else:
        spx_c = market.legacy_spx_close[candidate_idx]
        spx_v = market.legacy_spx_vwap[candidate_idx]
    return extract_breakout_feature_vector(
        or_df=or_df,
        current_bar=current,
        or_high=or_high,
        or_low=or_low,
        or_range=or_range,
        atr20=atr20,
        direction=direction,
        baseline_volume_1h=1.0,
        gk_vol=0.0,
        is_nr7=False,
        spx_c=float(spx_c) if _finite(spx_c) else None,
        spx_v=float(spx_v) if _finite(spx_v) else None,
        is_crypto=False,
    )


def _legacy_exit(
    market: PreparedMarket,
    *,
    signal_idx: int,
    direction: int,
    entry_price: float,
    delta: float,
    target_multiple: float,
    stop_multiple: float,
    breakeven_trigger_r: float,
    breakeven_offset_r: float,
    trailing_distance_r: float,
) -> tuple[int, float, str, float]:
    target = entry_price + direction * target_multiple * delta
    stop = entry_price - direction * stop_multiple * delta
    be_price = entry_price + direction * breakeven_offset_r * delta
    be_activated = False
    favorable = entry_price
    max_fwd = min(len(market.timestamps), signal_idx + 1500)
    exit_idx = signal_idx
    exit_price = entry_price
    reason = "truncated"

    for idx in range(signal_idx + 1, max_fwd):
        high = market.highs[idx]
        low = market.lows[idx]
        close = market.closes[idx]
        timestamp = market.timestamps[idx]

        if direction == 1:
            favorable = max(favorable, high)
            if not be_activated and high >= entry_price + breakeven_trigger_r * delta:
                be_activated = True
                stop = be_price
            if be_activated:
                stop = max(stop, favorable - trailing_distance_r * delta)
            hit_target = high >= target
            hit_stop = low <= stop
        else:
            favorable = min(favorable, low)
            if not be_activated and low <= entry_price - breakeven_trigger_r * delta:
                be_activated = True
                stop = be_price
            if be_activated:
                stop = min(stop, favorable + trailing_distance_r * delta)
            hit_target = low <= target
            hit_stop = high >= stop

        is_friday_close = timestamp.weekday() == 4 and timestamp.hour >= 20
        is_expired = idx == max_fwd - 1 or is_friday_close
        exit_idx = idx
        if hit_target:
            exit_price = target
            reason = "profit_target"
            break
        if hit_stop:
            exit_price = stop
            reason = "stop_loss"
            break
        if is_expired:
            exit_price = close
            reason = "time_expiry"
            break

    return exit_idx, float(exit_price), reason, float(stop)


def _canonical_exit(
    market: PreparedMarket,
    *,
    entry_idx: int,
    session_date: date,
    direction: int,
    entry_price: float,
    delta: float,
    target_multiple: float,
    stop_multiple: float,
    breakeven_trigger_r: float,
    breakeven_offset_r: float,
    trailing_distance_r: float,
) -> tuple[int | None, float | None, str, float, date | None, str | None]:
    eow_idx, scheduled_eow, substitution = _eow_index(market, session_date)
    if eow_idx is None or eow_idx < entry_idx:
        return None, None, "truncated", math.nan, scheduled_eow, substitution

    target = entry_price + direction * target_multiple * delta
    stop = entry_price - direction * stop_multiple * delta
    be_price = entry_price + direction * breakeven_offset_r * delta
    be_activated = False
    favorable = entry_price

    for idx in range(entry_idx, eow_idx + 1):
        high = market.highs[idx]
        low = market.lows[idx]
        close = market.closes[idx]

        hit_target = high >= target if direction == 1 else low <= target
        hit_stop = low <= stop if direction == 1 else high >= stop
        if hit_target and hit_stop:
            return idx, float(stop), "stop_loss_conflict", float(stop), scheduled_eow, substitution
        if hit_stop:
            return idx, float(stop), "stop_loss", float(stop), scheduled_eow, substitution
        if hit_target:
            return idx, float(target), "profit_target", float(stop), scheduled_eow, substitution

        if direction == 1:
            favorable = max(favorable, high)
            if not be_activated and high >= entry_price + breakeven_trigger_r * delta:
                be_activated = True
                stop = max(stop, be_price)
            if be_activated:
                stop = max(stop, favorable - trailing_distance_r * delta)
        else:
            favorable = min(favorable, low)
            if not be_activated and low <= entry_price - breakeven_trigger_r * delta:
                be_activated = True
                stop = min(stop, be_price)
            if be_activated:
                stop = min(stop, favorable + trailing_distance_r * delta)

        if idx == eow_idx:
            return idx, float(close), "eow_calendar_exit", float(stop), scheduled_eow, substitution

    return None, None, "truncated", float(stop), scheduled_eow, substitution


def build_events(
    markets: dict[str, PreparedMarket],
    config: dict[str, Any],
    *,
    variant: str,
    roundtrip_cost_bps: float,
    decision_start: datetime,
    decision_end: datetime,
) -> EventBuildResult:
    if variant not in {"legacy_parity", "timezone_only", "corrected"}:
        raise EOWRebuildError(f"unsupported variant {variant}")

    strategy = config["strategy"]
    target_multiple = float(strategy["target_multiple"])
    stop_multiple = float(strategy["stop_multiple"])
    stretch_k = float(strategy["stretch_k"])
    breakeven_trigger = float(strategy["breakeven"]["trigger_r"])
    breakeven_offset = float(strategy["breakeven"]["offset_r"])
    trailing_distance = float(strategy["trailing"]["distance_r"])
    friction = roundtrip_cost_bps / 10_000.0

    events: list[ORBTradeEvent] = []
    rows: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}

    for spec in instrument_specs(config):
        market = markets[spec.symbol]
        current_exit_idx = -1
        if variant == "legacy_parity":
            trading_dates = sorted(market.utc_date_indices)
        else:
            trading_dates = sorted(market.scheduled_sessions & set(market.market_date_indices))

        for trading_date in trading_dates:
            session = (
                _legacy_session(market, trading_date)
                if variant == "legacy_parity"
                else _corrected_session(market, trading_date)
            )
            if session is None:
                skipped["session_incomplete"] = skipped.get("session_incomplete", 0) + 1
                continue
            opening, candidates, anchor_utc = session
            or_high = float(np.max(market.highs[opening]))
            or_low = float(np.min(market.lows[opening]))
            or_range = or_high - or_low
            atr20 = float(market.atr20[opening[0]])
            ema200 = float(market.ema200[opening[-1]])

            if not np.isfinite(atr20) or or_range <= 0:
                skipped["atr_or_range_invalid"] = skipped.get("atr_or_range_invalid", 0) + 1
                continue
            if or_range < 1.2 * atr20:
                skipped["volatility_gate"] = skipped.get("volatility_gate", 0) + 1
                continue

            delta = max(or_range, 0.5 * atr20)
            stretch = stretch_k * atr20

            for candidate_idx in candidates:
                if candidate_idx <= current_exit_idx:
                    continue
                close = market.closes[candidate_idx]
                if variant == "corrected":
                    decision_time = market.available_at[candidate_idx]
                    spx_c = market.canonical_spx_close[candidate_idx]
                    spx_v = market.canonical_spx_vwap[candidate_idx]
                else:
                    decision_time = market.timestamps[candidate_idx]
                    spx_c = market.legacy_spx_close[candidate_idx]
                    spx_v = market.legacy_spx_vwap[candidate_idx]

                if not (decision_start <= decision_time <= decision_end):
                    continue

                long_sig = close > or_high + stretch and (
                    not np.isfinite(ema200) or close > ema200
                )
                short_sig = close < or_low - stretch and (
                    not np.isfinite(ema200) or close < ema200
                )
                if _finite(spx_c) and _finite(spx_v):
                    long_sig = long_sig and float(spx_c) > float(spx_v)
                    short_sig = short_sig and float(spx_c) < float(spx_v)
                if not (long_sig or short_sig):
                    continue

                direction = 1 if long_sig else -1
                if variant == "corrected":
                    entry_idx = candidate_idx + 1
                    if entry_idx >= len(market.timestamps):
                        skipped["no_next_bar"] = skipped.get("no_next_bar", 0) + 1
                        continue
                    entry_price = float(market.opens[entry_idx])
                    entry_time = market.timestamps[entry_idx]
                    if entry_time < market.available_at[candidate_idx]:
                        raise EOWRebuildError("next-bar entry precedes decision availability")
                    (
                        exit_idx,
                        exit_price,
                        exit_reason,
                        final_stop,
                        scheduled_eow,
                        substitution,
                    ) = _canonical_exit(
                        market,
                        entry_idx=entry_idx,
                        session_date=trading_date,
                        direction=direction,
                        entry_price=entry_price,
                        delta=delta,
                        target_multiple=target_multiple,
                        stop_multiple=stop_multiple,
                        breakeven_trigger_r=breakeven_trigger,
                        breakeven_offset_r=breakeven_offset,
                        trailing_distance_r=trailing_distance,
                    )
                    if exit_idx is None or exit_price is None:
                        skipped["truncated_label"] = skipped.get("truncated_label", 0) + 1
                        continue
                    exit_time = market.available_at[exit_idx]
                    feature_canonical = True
                else:
                    entry_idx = candidate_idx
                    entry_price = float(close)
                    entry_time = market.timestamps[candidate_idx]
                    exit_idx, exit_price, exit_reason, final_stop = _legacy_exit(
                        market,
                        signal_idx=candidate_idx,
                        direction=direction,
                        entry_price=entry_price,
                        delta=delta,
                        target_multiple=target_multiple,
                        stop_multiple=stop_multiple,
                        breakeven_trigger_r=breakeven_trigger,
                        breakeven_offset_r=breakeven_offset,
                        trailing_distance_r=trailing_distance,
                    )
                    if exit_reason == "truncated":
                        skipped["truncated_label"] = skipped.get("truncated_label", 0) + 1
                        continue
                    exit_time = market.timestamps[exit_idx]
                    scheduled_eow = None
                    substitution = None
                    feature_canonical = False

                raw_return = direction * (exit_price - entry_price) / entry_price - friction
                risk_fraction = delta / entry_price
                r_multiple = raw_return / risk_fraction if risk_fraction > 0 else 0.0
                features = _feature_snapshot(
                    market,
                    opening,
                    candidate_idx,
                    canonical=feature_canonical,
                    direction=direction,
                    or_high=or_high,
                    or_low=or_low,
                    or_range=or_range,
                    atr20=atr20,
                )

                event = ORBTradeEvent(
                    entry_time=str(entry_time),
                    exit_time=str(exit_time),
                    decision_time=str(decision_time),
                    session_name=spec.anchor.name,
                    date=trading_date.isoformat(),
                    symbol=spec.symbol,
                    direction=direction,
                    entry_price=entry_price,
                    exit_price=float(exit_price),
                    or_high=or_high,
                    or_low=or_low,
                    or_range=or_range,
                    atr20=atr20,
                    delta=delta,
                    upper_barrier=entry_price + direction * target_multiple * delta,
                    lower_barrier=float(final_stop),
                    holding_bars=max(1, exit_idx - entry_idx + 1),
                    exit_reason=exit_reason,
                    label=1 if r_multiple > 0 else 0,
                    realized_return=float(raw_return),
                    r_multiple=float(r_multiple),
                    features=features,
                )
                events.append(event)
                current_exit_idx = exit_idx

                spx_available = market.canonical_spx_available_at[candidate_idx]
                rows.append(
                    {
                        "event_key": f"{spec.symbol}|{trading_date.isoformat()}",
                        "symbol": spec.symbol,
                        "strategy_date": trading_date.isoformat(),
                        "variant": variant,
                        "anchor_name": spec.anchor.name,
                        "anchor_utc": anchor_utc,
                        "signal_source_timestamp": market.timestamps[candidate_idx],
                        "decision_time": parse_utc(event.decision_time),
                        "entry_time": parse_utc(event.entry_time),
                        "exit_time": parse_utc(event.exit_time),
                        "direction": direction,
                        "entry_price": entry_price,
                        "exit_price": float(exit_price),
                        "or_high": or_high,
                        "or_low": or_low,
                        "or_range": or_range,
                        "atr20": atr20,
                        "delta": delta,
                        "r_multiple": float(r_multiple),
                        "realized_return": float(raw_return),
                        "label": event.label,
                        "exit_reason": exit_reason,
                        "roundtrip_cost_bps": roundtrip_cost_bps,
                        "scheduled_eow_session": (
                            scheduled_eow.isoformat() if scheduled_eow else None
                        ),
                        "eow_substitution": substitution,
                        "spx_available_at": spx_available,
                        "spx_staleness_seconds": (
                            None
                            if spx_available is None
                            else (market.available_at[candidate_idx] - spx_available).total_seconds()
                        ),
                    }
                )
                break

    if variant == "corrected":
        events_and_rows = sorted(
            zip(events, rows),
            key=lambda pair: (
                parse_utc(pair[0].decision_time),
                pair[0].symbol,
                pair[0].date,
            ),
        )
        events = [event for event, _ in events_and_rows]
        rows = [row for _, row in events_and_rows]

    ledger = pl.DataFrame(rows, infer_schema_length=None) if rows else pl.DataFrame()
    return EventBuildResult(
        variant=variant,
        roundtrip_cost_bps=roundtrip_cost_bps,
        events=events,
        ledger=ledger,
        diagnostics={
            "event_count": len(events),
            "skipped": skipped,
            "roundtrip_cost_bps": roundtrip_cost_bps,
        },
    )


def _legacy_meta_model(
    events: list[ORBTradeEvent],
    *,
    sample_weights: np.ndarray,
    n_groups: int,
    n_test_groups: int,
    embargo_size: int,
    random_state: int = 42,
) -> LegacyModelResult:
    import lightgbm as lgb

    X = np.asarray(
        [[event.features.get(name, 0.0) for name in FEATURES] for event in events],
        dtype=np.float32,
    )
    y = np.asarray([event.label for event in events], dtype=np.int32)
    weights = (
        sample_weights.astype(np.float32)
        if len(sample_weights) == len(events)
        else np.ones(len(events), dtype=np.float32)
    )
    mono_map = {
        "rvol_1h": 1,
        "vwap_alignment": 1,
        "wick_exhaustion": -1,
        "breakout_bar_range_ratio": -1,
        "spx_alignment": 1,
    }
    params = {
        "objective": "binary",
        "metric": "binary_logloss",
        "boosting_type": "gbdt",
        "learning_rate": 0.03,
        "num_leaves": 15,
        "max_depth": 4,
        "min_child_samples": 20,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "monotone_constraints": [mono_map.get(name, 0) for name in FEATURES],
        "random_state": random_state,
        "verbose": -1,
        "n_estimators": 80,
    }
    cv = CombinatorialCV(
        n_groups=n_groups,
        n_test_groups=n_test_groups,
        embargo_size=embargo_size,
    )
    score_sum = np.zeros(len(events), dtype=float)
    coverage = np.zeros(len(events), dtype=int)
    aucs: list[float] = []
    for train_idx, test_idx in cv.split(X):
        if len(train_idx) < 30 or len(test_idx) < 5:
            continue
        if len(np.unique(y[train_idx])) < 2:
            continue
        model = lgb.LGBMClassifier(**params)
        model.fit(X[train_idx], y[train_idx], sample_weight=weights[train_idx])
        scores = model.predict_proba(X[test_idx])[:, 1]
        score_sum[test_idx] += scores
        coverage[test_idx] += 1
        if len(np.unique(y[test_idx])) == 2:
            aucs.append(float(roc_auc_score(y[test_idx], scores)))
    oof = np.full(len(events), 0.5, dtype=float)
    evaluated = coverage > 0
    oof[evaluated] = score_sum[evaluated] / coverage[evaluated]
    final = lgb.LGBMClassifier(**params)
    final.fit(X, y, sample_weight=weights)
    return LegacyModelResult(
        model=final,
        oof_scores=oof,
        oof_coverage=coverage,
        mean_auc=float(np.mean(aucs)) if aucs else 0.5,
    )


def legacy_oof_scores(
    result: EventBuildResult,
    markets: dict[str, PreparedMarket],
    config: dict[str, Any],
) -> tuple[np.ndarray, LegacyModelResult]:
    all_timestamps = sorted(
        {
            str(timestamp)
            for market in markets.values()
            for timestamp in market.timestamps
        }
    )
    weights = compute_sample_uniqueness_weights(result.events, all_timestamps)
    cpcv = config["validation"]["cpcv"]
    model = _legacy_meta_model(
        result.events,
        sample_weights=weights,
        n_groups=int(cpcv["n_groups"]),
        n_test_groups=int(cpcv["n_test_groups"]),
        embargo_size=int(cpcv["legacy_embargo_bars"]),
    )
    return model.oof_scores, model


def trade_summary(
    events: Sequence[ORBTradeEvent],
    scores: Sequence[float],
    *,
    threshold: float,
) -> dict[str, Any]:
    selected = [
        event
        for event, score in zip(events, scores)
        if float(score) >= threshold
    ]
    r = np.asarray([event.r_multiple for event in selected], dtype=float)
    yearly: dict[str, dict[str, Any]] = {}
    for event in selected:
        bucket = yearly.setdefault(
            event.date[:4],
            {"trades": 0, "wins": 0, "net_r": 0.0},
        )
        bucket["trades"] += 1
        bucket["wins"] += int(event.r_multiple > 0)
        bucket["net_r"] += float(event.r_multiple)
    for bucket in yearly.values():
        bucket["win_rate_pct"] = (
            100.0 * bucket["wins"] / bucket["trades"] if bucket["trades"] else 0.0
        )

    return {
        "trade_count": len(selected),
        "wins": int(np.sum(r > 0)) if len(r) else 0,
        "win_rate_pct": float(np.mean(r > 0) * 100.0) if len(r) else 0.0,
        "net_r": float(np.sum(r)) if len(r) else 0.0,
        "mean_r": float(np.mean(r)) if len(r) else 0.0,
        "yearly": yearly,
    }


def legacy_reported_sharpe(
    events: Sequence[ORBTradeEvent],
    scores: Sequence[float],
    *,
    threshold: float,
    synthetic_days: int = 2400,
) -> dict[str, Any]:
    selected = [
        event
        for event, score in zip(events, scores)
        if float(score) >= threshold
    ]
    by_date: dict[str, float] = {}
    for event in selected:
        by_date[event.date] = by_date.get(event.date, 0.0) + event.r_multiple * 0.01
    values = np.asarray([by_date[day] for day in sorted(by_date)], dtype=float)
    daily = np.zeros(max(synthetic_days, len(values)), dtype=float)
    daily[: len(values)] = values
    std = float(np.std(daily))
    sharpe = float(np.mean(daily) / std * np.sqrt(252)) if std > 0 else 0.0
    return {
        "annualized_sharpe": sharpe,
        "synthetic_days": int(len(daily)),
        "nonzero_days": int(np.count_nonzero(daily)),
        "skew": float(stats.skew(daily)) if len(daily) > 2 else 0.0,
        "kurtosis": float(stats.kurtosis(daily, fisher=False)) if len(daily) > 3 else 3.0,
    }


def walk_forward_scores(
    events: list[ORBTradeEvent],
    config: dict[str, Any],
) -> tuple[np.ndarray, list[dict[str, Any]], Any]:
    if not events:
        raise EOWRebuildError("cannot validate empty event set")
    threshold = float(config["strategy"]["meta_threshold"])
    cpcv = config["validation"]["cpcv"]
    embargo = _duration(str(cpcv["embargo_duration"]))
    initial_end = parse_utc(config["validation"]["initial_training"]["end"])
    scores = np.full(len(events), np.nan, dtype=float)
    diagnostics: list[dict[str, Any]] = []

    decision_times = np.asarray(
        [parse_utc(event.decision_time).timestamp() for event in events],
        dtype=float,
    )
    initial_idx = np.flatnonzero(
        decision_times <= initial_end.timestamp()
    )
    if len(initial_idx) < 40:
        raise EOWRebuildError("insufficient 2017-2019 initial training events")

    initial_events = [events[i] for i in initial_idx]
    initial_model = train_meta_classifier_cpcv(
        initial_events,
        feature_cols=list(FEATURES),
        n_groups=int(cpcv["n_groups"]),
        n_test_groups=int(cpcv["n_test_groups"]),
        conviction_threshold=threshold,
        require_temporal_contract=True,
        embargo_duration=embargo,
        compute_shap=False,
    )
    scores[initial_idx] = initial_model.oof_scores
    diagnostics.append(
        {
            "phase": "initial_development_oof",
            "start": config["validation"]["initial_training"]["start"],
            "end": config["validation"]["initial_training"]["end"],
            "train_count": len(initial_events),
            "score_count": len(initial_events),
            "mean_auc": float(initial_model.mean_auc),
            "oof_coverage_complete": bool(np.all(initial_model.oof_coverage > 0)),
        }
    )

    for year in config["validation"]["walk_forward_years"]:
        test_start = datetime(int(year), 1, 1, tzinfo=UTC)
        test_end = datetime(int(year), 12, 31, 23, 59, 59, tzinfo=UTC)
        train_idx = np.flatnonzero(decision_times < test_start.timestamp())
        test_idx = np.flatnonzero(
            (decision_times >= test_start.timestamp())
            & (decision_times <= test_end.timestamp())
        )
        if not len(test_idx):
            continue
        training = [events[i] for i in train_idx]
        model_result = train_meta_classifier_cpcv(
            training,
            feature_cols=list(FEATURES),
            n_groups=int(cpcv["n_groups"]),
            n_test_groups=int(cpcv["n_test_groups"]),
            conviction_threshold=threshold,
            require_temporal_contract=True,
            embargo_duration=embargo,
            compute_shap=False,
        )
        X = np.asarray(
            [[events[i].features.get(name, 0.0) for name in FEATURES] for i in test_idx],
            dtype=np.float32,
        )
        scores[test_idx] = model_result.model.predict_proba(X)[:, 1]
        diagnostics.append(
            {
                "phase": "walk_forward_oos",
                "year": int(year),
                "train_count": int(len(train_idx)),
                "test_count": int(len(test_idx)),
                "mean_inner_auc": float(model_result.mean_auc),
                "inner_oof_coverage_complete": bool(
                    np.all(model_result.oof_coverage > 0)
                ),
            }
        )

    if np.any(~np.isfinite(scores)):
        missing = int(np.sum(~np.isfinite(scores)))
        raise EOWRebuildError(f"walk-forward scoring left {missing} events unscored")

    final_model = train_meta_classifier_cpcv(
        events,
        feature_cols=list(FEATURES),
        n_groups=int(cpcv["n_groups"]),
        n_test_groups=int(cpcv["n_test_groups"]),
        conviction_threshold=threshold,
        require_temporal_contract=True,
        embargo_duration=embargo,
        compute_shap=False,
    )
    return scores, diagnostics, final_model


def score_frozen_model(model: Any, events: Sequence[ORBTradeEvent]) -> np.ndarray:
    if not events:
        return np.array([], dtype=float)
    X = np.asarray(
        [[event.features.get(name, 0.0) for name in FEATURES] for event in events],
        dtype=np.float32,
    )
    return np.asarray(model.predict_proba(X)[:, 1], dtype=float)


def portfolio_daily_mtm(
    events: Sequence[ORBTradeEvent],
    scores: Sequence[float],
    markets: dict[str, PreparedMarket],
    *,
    threshold: float,
    risk_unit_pct: float,
    roundtrip_cost_bps: float,
) -> tuple[pl.DataFrame, dict[str, Any]]:
    """Build a daily UTC mark-to-market return series in 1R risk units."""
    daily_r: dict[date, float] = {}
    cost_fraction = roundtrip_cost_bps / 10_000.0

    for event, score in zip(events, scores):
        if float(score) < threshold:
            continue
        market = markets[event.symbol]
        entry_time = parse_utc(event.entry_time)
        exit_time = parse_utc(event.exit_time)
        entry_price = float(event.entry_price)
        direction = int(event.direction)
        delta = float(event.delta)
        if delta <= 0:
            raise EOWRebuildError("non-positive event delta")
        risk_fraction = delta / entry_price
        half_cost_r = (cost_fraction / 2.0) / risk_fraction

        current = entry_time.date()
        end_date = exit_time.date()
        previous_mark_r = -half_cost_r
        daily_r[current] = daily_r.get(current, 0.0) + previous_mark_r

        while current <= end_date:
            day_end = datetime.combine(
                current, time(23, 59, 59, 999999), tzinfo=UTC
            )
            if day_end < entry_time:
                current += timedelta(days=1)
                continue
            right = bisect_right(market.available_at, min(day_end, exit_time))
            left = bisect_left(market.available_at, entry_time)
            if right <= left:
                current += timedelta(days=1)
                continue
            mark_idx = right - 1
            mark_price = (
                float(event.exit_price)
                if market.available_at[mark_idx] >= exit_time
                else float(market.closes[mark_idx])
            )
            mark_r = direction * (mark_price - entry_price) / delta - half_cost_r
            if day_end >= exit_time:
                mark_r -= half_cost_r
            increment = mark_r - previous_mark_r
            daily_r[current] = daily_r.get(current, 0.0) + increment
            previous_mark_r = mark_r
            current += timedelta(days=1)

    if not daily_r:
        return pl.DataFrame({"date": [], "return": [], "r_increment": []}), {
            "annualized_sharpe": 0.0,
            "max_drawdown": 0.0,
            "net_r_reconciled": 0.0,
        }

    first = min(daily_r)
    last = max(daily_r)
    rows: list[dict[str, Any]] = []
    current = first
    while current <= last:
        if current.weekday() < 5:
            r_increment = float(daily_r.get(current, 0.0))
            rows.append(
                {
                    "date": current.isoformat(),
                    "r_increment": r_increment,
                    "return": r_increment * (risk_unit_pct / 100.0),
                }
            )
        current += timedelta(days=1)

    frame = pl.DataFrame(rows)
    returns = frame["return"].to_numpy()
    std = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
    sharpe = float(np.mean(returns) / std * np.sqrt(252)) if std > 0 else 0.0
    equity = np.cumprod(1.0 + returns)
    path = np.concatenate(([1.0], equity))
    peaks = np.maximum.accumulate(path)
    drawdown = path / peaks - 1.0

    selected_net_r = float(
        sum(
            event.r_multiple
            for event, score in zip(events, scores)
            if float(score) >= threshold
        )
    )
    reconciled_r = float(frame["r_increment"].sum())
    return frame, {
        "annualized_sharpe": sharpe,
        "max_drawdown": float(np.min(drawdown)),
        "selected_net_r": selected_net_r,
        "net_r_reconciled": reconciled_r,
        "reconciliation_error_r": reconciled_r - selected_net_r,
        "valuation_timezone": "UTC",
        "risk_unit_pct": risk_unit_pct,
        "risk_unit_fraction": risk_unit_pct / 100.0,
    }


def compare_event_ledgers(
    before: pl.DataFrame,
    after: pl.DataFrame,
) -> pl.DataFrame:
    if before.is_empty() and after.is_empty():
        return pl.DataFrame()
    before_rows = {row["event_key"]: row for row in before.to_dicts()}
    after_rows = {row["event_key"]: row for row in after.to_dicts()}
    rows: list[dict[str, Any]] = []
    for key in sorted(set(before_rows) | set(after_rows)):
        old = before_rows.get(key)
        new = after_rows.get(key)
        if old is None:
            status = "ADDED"
        elif new is None:
            status = "REMOVED"
        else:
            causes: list[str] = []
            if old["signal_source_timestamp"] != new["signal_source_timestamp"]:
                causes.append("SESSION_SHIFTED")
            if old["direction"] != new["direction"]:
                causes.append("DIRECTION_CHANGED")
            if old["entry_time"] != new["entry_time"]:
                causes.append("ENTRY_CHANGED")
            if old["exit_time"] != new["exit_time"]:
                causes.append("EXIT_CHANGED")
            if old["label"] != new["label"]:
                causes.append("LABEL_CHANGED")
            status = "+".join(causes) if causes else "UNCHANGED"
        rows.append(
            {
                "event_key": key,
                "symbol": (new or old)["symbol"],
                "strategy_date": (new or old)["strategy_date"],
                "status": status,
                "old_signal_timestamp": None if old is None else old["signal_source_timestamp"],
                "new_signal_timestamp": None if new is None else new["signal_source_timestamp"],
                "old_entry_time": None if old is None else old["entry_time"],
                "new_entry_time": None if new is None else new["entry_time"],
                "old_exit_time": None if old is None else old["exit_time"],
                "new_exit_time": None if new is None else new["exit_time"],
                "old_r": None if old is None else old["r_multiple"],
                "new_r": None if new is None else new["r_multiple"],
                "delta_r": (
                    None
                    if old is None or new is None
                    else float(new["r_multiple"]) - float(old["r_multiple"])
                ),
            }
        )
    return pl.DataFrame(rows, infer_schema_length=None)


def _git_state(root: Path) -> dict[str, Any]:
    import subprocess

    def command(*args: str) -> str:
        try:
            return subprocess.check_output(
                ["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL
            ).strip()
        except Exception:
            return "UNAVAILABLE"

    diff = command("diff", "--binary", "HEAD")
    return {
        "head": command("rev-parse", "HEAD"),
        "branch": command("branch", "--show-current"),
        "dirty_diff_sha256": hashlib.sha256(diff.encode()).hexdigest(),
    }


def _append_trial(root: Path, config: dict[str, Any], record: dict[str, Any]) -> None:
    path = root / str(config["artifacts"]["trial_ledger"])
    lock = path.with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(lock, os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def development_run(
    root: Path,
    config_path: Path,
    *,
    run_id: str,
) -> dict[str, Any]:
    config = load_config(config_path)
    pre = preflight(root, config_path)
    if pre["status"] != "READY":
        return {"status": "BLOCKED", "preflight": pre}

    output = root / str(config["artifacts"]["root"]) / run_id
    if output.exists():
        raise EOWRebuildError(f"run output already exists: {output}")
    output.mkdir(parents=True)
    atomic_write_json(output / "preflight.json", pre)
    (output / "config.snapshot.yaml").write_bytes(config_path.read_bytes())

    dev_end = datetime(2024, 12, 31, 23, 59, 59, tzinfo=UTC)
    dev_start = parse_utc(config["validation"]["initial_training"]["start"])
    markets = prepare_all_markets(root, config, end=dev_end)

    legacy = build_events(
        markets,
        config,
        variant="legacy_parity",
        roundtrip_cost_bps=float(config["execution"]["legacy_roundtrip_bps"]),
        decision_start=dev_start,
        decision_end=dev_end,
    )
    timezone_only = build_events(
        markets,
        config,
        variant="timezone_only",
        roundtrip_cost_bps=float(config["execution"]["legacy_roundtrip_bps"]),
        decision_start=dev_start,
        decision_end=dev_end,
    )
    canonical_4 = build_events(
        markets,
        config,
        variant="corrected",
        roundtrip_cost_bps=float(config["execution"]["legacy_roundtrip_bps"]),
        decision_start=dev_start,
        decision_end=dev_end,
    )
    canonical_6 = build_events(
        markets,
        config,
        variant="corrected",
        roundtrip_cost_bps=float(config["execution"]["authoritative_roundtrip_bps"]),
        decision_start=dev_start,
        decision_end=dev_end,
    )

    for name, result in (
        ("legacy_events.parquet", legacy),
        ("timezone_only_events.parquet", timezone_only),
        ("canonical_4bps_events.parquet", canonical_4),
        ("canonical_6bps_events.parquet", canonical_6),
    ):
        atomic_write_parquet(output / name, result.ledger)

    tz_diff = compare_event_ledgers(legacy.ledger, timezone_only.ledger)
    canonical_diff = compare_event_ledgers(timezone_only.ledger, canonical_4.ledger)
    atomic_write_parquet(output / "timezone_event_diff.parquet", tz_diff)
    atomic_write_parquet(output / "canonical_event_diff.parquet", canonical_diff)

    legacy_scores, legacy_model = legacy_oof_scores(legacy, markets, config)
    timezone_scores, timezone_model = legacy_oof_scores(timezone_only, markets, config)
    canonical_scores, wf_diagnostics, final_model = walk_forward_scores(
        canonical_6.events, config
    )

    threshold = float(config["strategy"]["meta_threshold"])
    risk_unit = float(config["validation"]["risk_unit_pct"])
    canonical_daily, canonical_portfolio = portfolio_daily_mtm(
        canonical_6.events,
        canonical_scores,
        markets,
        threshold=threshold,
        risk_unit_pct=risk_unit,
        roundtrip_cost_bps=float(config["execution"]["authoritative_roundtrip_bps"]),
    )
    atomic_write_parquet(output / "development_daily_mtm.parquet", canonical_daily)

    legacy_summary = trade_summary(legacy.events, legacy_scores, threshold=threshold)
    legacy_summary["legacy_reported_sharpe"] = legacy_reported_sharpe(
        legacy.events, legacy_scores, threshold=threshold
    )
    timezone_summary = trade_summary(
        timezone_only.events, timezone_scores, threshold=threshold
    )
    timezone_summary["legacy_reported_sharpe"] = legacy_reported_sharpe(
        timezone_only.events, timezone_scores, threshold=threshold
    )
    canonical_summary = trade_summary(
        canonical_6.events, canonical_scores, threshold=threshold
    )
    canonical_summary["portfolio"] = canonical_portfolio

    model_path = output / "frozen_model.pkl"
    model_bytes = pickle.dumps(final_model.model)
    model_path.write_bytes(model_bytes)

    data_fingerprints = {item["file"]: item["sha256"] for item in pre["files"]}
    frozen = {
        "schema_version": "eow_rebuild_frozen/v1",
        "run_id": run_id,
        "strategy_id": config["research"]["strategy_id"],
        "config_sha256": sha256_file(config_path),
        "data_fingerprints": data_fingerprints,
        "git_state": _git_state(root),
        "feature_set": list(FEATURES),
        "meta_threshold": threshold,
        "authoritative_roundtrip_bps": float(
            config["execution"]["authoritative_roundtrip_bps"]
        ),
        "development_end": dev_end.isoformat(),
        "final_holdout": config["validation"]["final_holdout"],
        "model_sha256": hashlib.sha256(model_bytes).hexdigest(),
        "walk_forward_diagnostics": wf_diagnostics,
    }
    frozen["frozen_hash"] = canonical_hash(frozen)
    atomic_write_json(output / "frozen_spec.json", frozen)

    result = {
        "schema_version": "eow_rebuild_development/v1",
        "run_id": run_id,
        "status": "DEVELOPMENT_COMPLETE",
        "dsr_status": "DSR_UNREPRODUCIBLE_LEGACY_TRIAL_UNIVERSE",
        "legacy": legacy_summary,
        "timezone_only": timezone_summary,
        "canonical_authoritative": canonical_summary,
        "legacy_mean_auc": legacy_model.mean_auc,
        "timezone_only_mean_auc": timezone_model.mean_auc,
        "walk_forward": wf_diagnostics,
        "event_counts": {
            "legacy": len(legacy.events),
            "timezone_only": len(timezone_only.events),
            "canonical_4bps": len(canonical_4.events),
            "canonical_6bps": len(canonical_6.events),
        },
        "timezone_diff_counts": (
            tz_diff.group_by("status").len().to_dicts() if not tz_diff.is_empty() else []
        ),
        "canonical_diff_counts": (
            canonical_diff.group_by("status").len().to_dicts()
            if not canonical_diff.is_empty()
            else []
        ),
        "frozen_hash": frozen["frozen_hash"],
    }
    atomic_write_json(output / "development_result.json", result)

    _append_trial(
        root,
        config,
        {
            "schema_version": "eow_rebuild_trial/v1",
            "trial_id": f"{run_id}/development/canonical_6bps",
            "selection_trial": False,
            "status": "DEVELOPMENT_COMPLETE",
            "config_sha256": frozen["config_sha256"],
            "data_fingerprints": data_fingerprints,
            "frozen_hash": frozen["frozen_hash"],
            "return_series_ref": str(
                (output / "development_daily_mtm.parquet").relative_to(root)
            ),
            "result_ref": str(
                (output / "development_result.json").relative_to(root)
            ),
        },
    )
    return result


def _holdout_claim_path(
    root: Path, config: dict[str, Any], frozen_hash: str
) -> Path:
    directory = root / str(config["artifacts"]["final_holdout_claims"])
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{frozen_hash}.claim.json"


def final_holdout_run(
    root: Path,
    config_path: Path,
    *,
    run_id: str,
) -> dict[str, Any]:
    config = load_config(config_path)
    output = root / str(config["artifacts"]["root"]) / run_id
    frozen_path = output / "frozen_spec.json"
    model_path = output / "frozen_model.pkl"
    if not frozen_path.is_file() or not model_path.is_file():
        raise EOWRebuildError("development freeze/model missing")
    frozen = json.loads(frozen_path.read_text())
    if frozen.get("config_sha256") != sha256_file(config_path):
        raise EOWRebuildError("config changed since development freeze")
    if frozen.get("model_sha256") != sha256_file(model_path):
        raise EOWRebuildError("model changed since development freeze")

    pre = preflight(root, config_path)
    current_fingerprints = {item["file"]: item["sha256"] for item in pre["files"]}
    if current_fingerprints != frozen.get("data_fingerprints"):
        raise EOWRebuildError("data fingerprints changed since development freeze")

    claim = _holdout_claim_path(root, config, frozen["frozen_hash"])
    try:
        descriptor = os.open(claim, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise EOWRebuildError(
            "final holdout already claimed; manual audit required"
        ) from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "run_id": run_id,
                "frozen_hash": frozen["frozen_hash"],
                "claimed_at": datetime.now(UTC).isoformat(),
            },
            handle,
            indent=2,
            sort_keys=True,
        )
        handle.write("\n")

    holdout = config["validation"]["final_holdout"]
    start = parse_utc(holdout["start"])
    end = parse_utc(holdout["end"])
    markets = prepare_all_markets(root, config, end=end)
    canonical = build_events(
        markets,
        config,
        variant="corrected",
        roundtrip_cost_bps=float(config["execution"]["authoritative_roundtrip_bps"]),
        decision_start=start,
        decision_end=end,
    )
    with model_path.open("rb") as handle:
        model = pickle.load(handle)
    scores = score_frozen_model(model, canonical.events)
    threshold = float(config["strategy"]["meta_threshold"])
    summary = trade_summary(canonical.events, scores, threshold=threshold)
    daily, portfolio = portfolio_daily_mtm(
        canonical.events,
        scores,
        markets,
        threshold=threshold,
        risk_unit_pct=float(config["validation"]["risk_unit_pct"]),
        roundtrip_cost_bps=float(config["execution"]["authoritative_roundtrip_bps"]),
    )
    summary["portfolio"] = portfolio
    atomic_write_parquet(output / "final_holdout_events.parquet", canonical.ledger)
    atomic_write_parquet(output / "final_holdout_daily_mtm.parquet", daily)
    atomic_write_parquet(
        output / "final_holdout_scores.parquet",
        pl.DataFrame(
            {
                "event_key": (
                    canonical.ledger["event_key"]
                    if not canonical.ledger.is_empty()
                    else []
                ),
                "score": scores,
            }
        ),
    )
    result = {
        "schema_version": "eow_rebuild_final_holdout/v1",
        "run_id": run_id,
        "status": "FINAL_HOLDOUT_COMPLETE",
        "period": holdout,
        "summary": summary,
        "event_count": len(canonical.events),
        "frozen_hash": frozen["frozen_hash"],
        "dsr_status": "DSR_UNREPRODUCIBLE_LEGACY_TRIAL_UNIVERSE",
    }
    atomic_write_json(output / "final_holdout_result.json", result)
    atomic_write_json(
        claim.with_suffix(".complete.json"),
        {
            "run_id": run_id,
            "frozen_hash": frozen["frozen_hash"],
            "status": "FINAL_HOLDOUT_COMPLETE",
            "result_sha256": sha256_file(output / "final_holdout_result.json"),
        },
    )
    _append_trial(
        root,
        config,
        {
            "schema_version": "eow_rebuild_trial/v1",
            "trial_id": f"{run_id}/final_holdout/canonical_6bps",
            "selection_trial": False,
            "status": "FINAL_HOLDOUT_COMPLETE",
            "config_sha256": frozen["config_sha256"],
            "data_fingerprints": current_fingerprints,
            "frozen_hash": frozen["frozen_hash"],
            "return_series_ref": str(
                (output / "final_holdout_daily_mtm.parquet").relative_to(root)
            ),
            "result_ref": str(
                (output / "final_holdout_result.json").relative_to(root)
            ),
        },
    )
    return result


def micro_dst_audit(root: Path, config_path: Path) -> dict[str, Any]:
    config = load_config(config_path)
    specs = {spec.symbol: spec for spec in instrument_specs(config)}
    de = specs["DE30"]
    nas = specs["NAS100"]
    cases = {
        "de_winter": anchor_window(date(2024, 1, 15), de.anchor).anchor_utc,
        "de_us_dst_eu_standard": anchor_window(date(2024, 3, 11), de.anchor).anchor_utc,
        "de_summer": anchor_window(date(2024, 7, 15), de.anchor).anchor_utc,
        "de_eu_standard_us_dst": anchor_window(date(2024, 10, 28), de.anchor).anchor_utc,
        "de_winter_after_us_fallback": anchor_window(date(2024, 11, 4), de.anchor).anchor_utc,
        "nas_before_us_dst": anchor_window(date(2024, 3, 8), nas.anchor).anchor_utc,
        "nas_after_us_dst": anchor_window(date(2024, 3, 11), nas.anchor).anchor_utc,
        "nas_before_us_fallback": anchor_window(date(2024, 11, 1), nas.anchor).anchor_utc,
        "nas_after_us_fallback": anchor_window(date(2024, 11, 4), nas.anchor).anchor_utc,
    }
    expected = {
        "de_winter": (14, 0),
        "de_us_dst_eu_standard": (13, 0),
        "de_summer": (13, 0),
        "de_eu_standard_us_dst": (13, 0),
        "de_winter_after_us_fallback": (14, 0),
        "nas_before_us_dst": (14, 30),
        "nas_after_us_dst": (13, 30),
        "nas_before_us_fallback": (13, 30),
        "nas_after_us_fallback": (14, 30),
    }
    checks = {
        name: {
            "actual": value.isoformat(),
            "expected_hour": expected[name][0],
            "expected_minute": expected[name][1],
            "passed": (value.hour, value.minute) == expected[name],
        }
        for name, value in cases.items()
    }

    end = datetime(2024, 11, 5, tzinfo=UTC)
    legacy_spx, canonical_spx = _benchmark_frames(root, config, end=end)
    observed: dict[str, Any] = {}
    for symbol, day in (
        ("DE30", date(2024, 3, 11)),
        ("DE30", date(2024, 10, 28)),
        ("NAS100", date(2024, 3, 11)),
        ("NAS100", date(2024, 11, 4)),
    ):
        market = prepare_market(
            root,
            specs[symbol],
            legacy_spx=legacy_spx,
            canonical_spx=canonical_spx,
            end=end,
        )
        indices = market.market_date_indices.get(day, [])
        key = f"{symbol}_{day.isoformat()}"
        observed[key] = {
            "first_bar_utc": market.timestamps[indices[0]].isoformat() if indices else None,
            "last_bar_utc": market.timestamps[indices[-1]].isoformat() if indices else None,
            "bar_count": len(indices),
        }

    passed = all(item["passed"] for item in checks.values())
    return {
        "schema_version": "eow_rebuild_dst_audit/v1",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "observed_sessions": observed,
    }
