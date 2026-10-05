"""Canonical, fail-closed ORB development and one-shot final-OOS runner."""

from __future__ import annotations

import hashlib
import fcntl
import json
import os
import pickle
import subprocess
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import polars as pl

from src.labeling import MetaLabelingORBDatasetBuilder, ORBTradeEvent
from src.market_time import BarTimestampSpec, SessionSpec
from src.models import train_meta_classifier_cpcv
from src.validation import (
    ValidationContractError,
    event_interval,
    order_events,
    stable_event_id,
)

UTC = timezone.utc
SCHEMA_VERSION = "validated_orb_run/v1"
DEFAULT_FEATURES = (
    "rvol_1h",
    "vwap_alignment",
    "wick_exhaustion",
    "range_to_atr20",
    "garman_klass_norm",
    "nr7_flag",
    "breakout_bar_range_ratio",
)
SYMBOL_FILES = {
    "DE30/EUR": "DE30_EUR_5m_2017_2026.parquet",
    "JP225/USD": "JP225_USD_5m_2017_2026.parquet",
}
SESSION_KEYS = {"DE30/EUR": "DE30_cash_open", "JP225/USD": "JP225_cash_open"}
STRATEGY_SPEC: dict[str, Any] = {
    "strategy_id": "validated-orb-de30-jp225",
    "target_multiple": 3.0,
    "stop_multiple": 1.0,
    "max_holding_bars": 1500,
    "stretch_k": 0.15,
    "holding_mode": "multi_day_eow",
    "threshold_candidates": [round(value, 2) for value in np.arange(0.30, 0.81, 0.05)],
    "threshold_objective": "mean_net_return",
    "threshold_tie_break": "higher_threshold_then_more_selections",
    "bootstrap_block_lengths": [5, 10, 20],
    "bootstrap_samples": 1000,
    "random_state": 42,
}


class RunnerContractError(RuntimeError):
    """Raised before an unsafe or non-reproducible runner action."""


@dataclass(frozen=True)
class EventSplit:
    development: list[ORBTradeEvent]
    censored: list[ORBTradeEvent]
    final_oos: list[ORBTradeEvent]


@dataclass(frozen=True)
class ThresholdTrial:
    threshold: float
    selection_count: int
    objective_value: float | None
    eligible: bool


@dataclass(frozen=True)
class ThresholdSelection:
    threshold: float
    objective: str
    tie_break: str
    minimum_selection_count: int
    trials: list[ThresholdTrial]


def parse_utc(value: str | datetime) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset() is None:
        raise RunnerContractError("timestamp must be timezone-aware")
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
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _manifest_entries(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    files = manifest.get("files", [])
    return {
        str(entry.get("file")): entry
        for entry in files
        if isinstance(entry, dict) and entry.get("file")
    }


REQUIRED_MANIFEST_FIELDS = {
    "row_count", "file_sha256", "content_fingerprint", "source_timezone", "schema",
    "null_counts", "min_timestamp", "max_timestamp", "bar_duration_seconds", "dev_rows",
    "oos_rows", "bar_open_assumption",
}


def _content_fingerprint(frame: pl.DataFrame) -> str:
    timestamps = frame.get_column("timestamp").sort().to_list()
    payload = "\n".join(value.isoformat() for value in timestamps)
    payload += f"\n{frame.get_column('close').sum()!r}"
    return hashlib.sha256(payload.encode()).hexdigest()


def _is_open_semantics(value: Any) -> bool:
    return isinstance(value, str) and "bar open" in value.lower()


def _audit_file(path: Path, entry: dict[str, Any], boundary: datetime) -> tuple[dict[str, Any], list[str]]:
    reasons: list[str] = []
    name = path.name
    for field in sorted(REQUIRED_MANIFEST_FIELDS):
        if field not in entry or entry[field] is None:
            reasons.append(f"manifest_field_missing_{name}_{field}")
    actual_hash = sha256_file(path)
    expected_hash = entry.get("file_sha256")
    if not expected_hash or actual_hash != expected_hash:
        reasons.append(f"manifest_sha256_mismatch_{name}")

    frame = pl.read_parquet(path)
    required_columns = {"timestamp", "open", "high", "low", "close", "volume"}
    missing = sorted(required_columns - set(frame.columns))
    if missing:
        reasons.append(f"schema_missing_{name}_{'_'.join(missing)}")
        return {"file": name, "sha256_verified": False}, reasons

    timestamps = frame.get_column("timestamp")
    dtype = timestamps.dtype
    tz = getattr(dtype, "time_zone", None)
    if tz != "UTC":
        reasons.append(f"timestamps_not_utc_aware_{name}")
    ts_values = timestamps.to_list()
    ordered = all(ts_values[index] < ts_values[index + 1] for index in range(len(ts_values) - 1))
    unique = timestamps.n_unique() == len(frame)
    if not ordered:
        reasons.append(f"timestamps_not_strictly_ordered_{name}")
    if not unique:
        reasons.append(f"duplicate_timestamps_{name}")

    actual_nulls = {column: int(count) for column, count in zip(frame.columns, frame.null_count().row(0))}
    if any(actual_nulls.values()):
        reasons.append(f"nulls_present_{name}")
    if int(entry.get("row_count", -1)) != len(frame):
        reasons.append(f"manifest_row_count_mismatch_{name}")
    if entry.get("null_counts") != actual_nulls:
        reasons.append(f"manifest_null_counts_mismatch_{name}")
    actual_schema = {column: str(dtype) for column, dtype in frame.schema.items()}
    if entry.get("schema") != actual_schema:
        reasons.append(f"manifest_schema_mismatch_{name}")
    actual_fingerprint = _content_fingerprint(frame)
    if entry.get("content_fingerprint") != actual_fingerprint:
        reasons.append(f"manifest_content_fingerprint_mismatch_{name}")
    if not _is_open_semantics(entry.get("bar_open_assumption")):
        reasons.append(f"manifest_timestamp_semantics_not_open_{name}")
    if entry.get("source_timezone") != "UTC":
        reasons.append(f"manifest_source_timezone_mismatch_{name}")

    valid_ohlc = frame.select(
        (
            (pl.col("high") >= pl.max_horizontal("open", "close", "low"))
            & (pl.col("low") <= pl.min_horizontal("open", "close", "high"))
            & (pl.col("high") >= pl.col("low"))
        ).all()
    ).item()
    if not valid_ohlc:
        reasons.append(f"ohlc_inconsistent_{name}")

    duration = float(entry.get("bar_duration_seconds") or 0)
    if duration <= 0:
        reasons.append(f"bar_duration_missing_{name}")
    elif ts_values:
        epoch_seconds = [int(value.timestamp()) for value in ts_values]
        if any(value % int(duration) for value in epoch_seconds):
            reasons.append(f"bar_duration_alignment_failed_{name}")
        positive_deltas = [
            (ts_values[index + 1] - ts_values[index]).total_seconds()
            for index in range(len(ts_values) - 1)
            if ts_values[index + 1] > ts_values[index]
        ]
        if positive_deltas and min(positive_deltas) != duration:
            reasons.append(f"manifest_bar_duration_mismatch_{name}")

    dev_rows = sum(value < boundary for value in ts_values)
    oos_rows = sum(value >= boundary for value in ts_values)
    if entry.get("dev_rows") is not None and int(entry["dev_rows"]) != dev_rows:
        reasons.append(f"manifest_dev_coverage_mismatch_{name}")
    if entry.get("oos_rows") is not None and int(entry["oos_rows"]) != oos_rows:
        reasons.append(f"manifest_oos_coverage_mismatch_{name}")
    if ts_values:
        if entry.get("min_timestamp") != min(ts_values).isoformat():
            reasons.append(f"manifest_min_timestamp_mismatch_{name}")
        if entry.get("max_timestamp") != max(ts_values).isoformat():
            reasons.append(f"manifest_max_timestamp_mismatch_{name}")

    return {
        "file": name,
        "row_count": len(frame),
        "sha256": actual_hash,
        "sha256_verified": actual_hash == expected_hash,
        "content_fingerprint": actual_fingerprint,
        "content_fingerprint_verified": entry.get("content_fingerprint") == actual_fingerprint,
        "timestamps_utc_aware": tz == "UTC",
        "timestamps_ordered": ordered,
        "timestamps_unique": unique,
        "null_counts": actual_nulls,
        "ohlc_consistent": bool(valid_ohlc),
        "bar_duration_seconds": duration,
        "timestamp_convention": "open" if _is_open_semantics(entry.get("bar_open_assumption")) else None,
        "source_timezone": entry.get("source_timezone"),
        "schema": actual_schema,
        "min_timestamp": min(ts_values).isoformat() if ts_values else None,
        "max_timestamp": max(ts_values).isoformat() if ts_values else None,
        "development_rows": dev_rows,
        "final_oos_rows": oos_rows,
    }, reasons


def audit_manifest(
    manifest_path: Path,
    required_files: set[str],
    boundary: datetime,
    expected_timestamp_semantics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reopen and verify only strategy inputs; retain other warnings as evidence."""
    boundary = parse_utc(boundary)
    reasons: list[str] = []
    audited: list[dict[str, Any]] = []
    warnings: list[str] = []
    if not manifest_path.exists():
        return {
            "data_code_readiness": "BLOCKED",
            "blocking_reasons": ["manifest_missing"],
            "nonblocking_warnings": [],
            "files": [],
        }
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError):
        return {
            "data_code_readiness": "BLOCKED",
            "blocking_reasons": ["manifest_invalid"],
            "nonblocking_warnings": [],
            "files": [],
        }
    if not isinstance(manifest, dict):
        raise RunnerContractError("manifest must be a JSON object")
    semantics = expected_timestamp_semantics or {}
    if semantics.get("status") != "verified":
        reasons.append("config_timestamp_semantics_unverified")
    if semantics.get("convention") != "open":
        reasons.append("config_timestamp_semantics_not_open")
    if semantics.get("timezone") != "UTC":
        reasons.append("config_timestamp_timezone_not_utc")
    vendor = manifest.get("vendor_semantics", {})
    if not isinstance(vendor, dict) or not _is_open_semantics(vendor.get("bar_open_assumption")):
        reasons.append("timestamp_semantics_unverified")
    if not isinstance(vendor, dict) or "utc" not in str(vendor.get("timezone_rule", "")).lower():
        reasons.append("source_timezone_rule_missing")

    entries = _manifest_entries(manifest)
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list):
        reasons.append("manifest_files_malformed")
        raw_files = []
    names = [entry.get("file") for entry in raw_files if isinstance(entry, dict)]
    if len(names) != len(set(names)):
        reasons.append("manifest_duplicate_file_entries")
    for name in sorted(required_files):
        entry = entries.get(name)
        if entry is None:
            reasons.append(f"manifest_file_missing_{name}")
            continue
        path = manifest_path.parent / name
        if not path.exists():
            reasons.append(f"input_file_missing_{name}")
            continue
        file_audit, file_reasons = _audit_file(path, entry, boundary)
        audited.append(file_audit)
        reasons.extend(file_reasons)

    in_scope = set(required_files)
    warning_details = manifest.get("data_quality_warning_details", [])
    all_warnings_raw = manifest.get("data_quality_warnings", [])
    if not isinstance(all_warnings_raw, list) or not isinstance(warning_details, list):
        reasons.append("data_quality_warnings_malformed")
        all_warnings_raw = []
        warning_details = []
    all_warnings = [str(value) for value in all_warnings_raw]
    details_structured = all(
        isinstance(detail, dict) and bool(detail.get("file")) and bool(detail.get("strategy_scope"))
        for detail in warning_details
    )
    if len(all_warnings) != len(warning_details) or not details_structured:
        reasons.append("unmatched_data_quality_warnings")
    scoped_warning_files = {
        str(detail.get("file"))
        for detail in warning_details
        if isinstance(detail, dict) and detail.get("file") in in_scope
    }
    if scoped_warning_files:
        reasons.extend(f"in_scope_data_quality_warning_{name}" for name in sorted(scoped_warning_files))
    elif len(all_warnings) == len(warning_details) and details_structured:
        warnings.extend(all_warnings)

    return {
        "data_code_readiness": "READY" if not reasons else "BLOCKED",
        "blocking_reasons": sorted(set(reasons)),
        "nonblocking_warnings": warnings,
        "files": audited,
    }


def split_development_and_final_oos(
    events: Sequence[ORBTradeEvent], boundary: datetime
) -> EventSplit:
    """Use decision time for OOS and censor any development label touching the boundary."""
    boundary = parse_utc(boundary)
    development: list[ORBTradeEvent] = []
    censored: list[ORBTradeEvent] = []
    final_oos: list[ORBTradeEvent] = []
    for event in order_events(events):
        interval = event_interval(event)
        if interval.decision_time >= boundary:
            final_oos.append(event)
        elif interval.exit_time >= boundary:
            censored.append(event)
        else:
            development.append(event)
    return EventSplit(development, censored, final_oos)


def select_development_threshold(
    scores: np.ndarray,
    net_returns: np.ndarray,
    *,
    candidates: Sequence[float],
    minimum_selection_count: int,
) -> ThresholdSelection:
    """Select on development OOF scores with a fully enumerated deterministic grid."""
    if len(scores) != len(net_returns) or not np.all(np.isfinite(scores)):
        raise RunnerContractError("threshold inputs must be finite and aligned")
    if minimum_selection_count < 1 or not candidates:
        raise RunnerContractError("threshold grid and positive minimum selection count are required")
    trials: list[ThresholdTrial] = []
    for candidate in candidates:
        selected = scores >= float(candidate)
        count = int(selected.sum())
        eligible = count >= minimum_selection_count
        value = float(np.mean(net_returns[selected])) if eligible else None
        trials.append(ThresholdTrial(float(candidate), count, value, eligible))
    eligible_trials = [trial for trial in trials if trial.eligible and trial.objective_value is not None]
    if not eligible_trials:
        raise RunnerContractError("no threshold candidate meets minimum selection count")
    winner = max(
        eligible_trials,
        key=lambda trial: (float(trial.objective_value), trial.threshold, trial.selection_count),
    )
    return ThresholdSelection(
        threshold=winner.threshold,
        objective="mean_net_return",
        tie_break="higher_threshold_then_more_selections",
        minimum_selection_count=minimum_selection_count,
        trials=trials,
    )


class FinalOOSGuard:
    """Repository-global exclusive claim that deliberately remains after a crash."""

    def __init__(self, registry_dir: Path, strategy_id: str, boundary: datetime):
        self.registry_dir = registry_dir
        boundary = parse_utc(boundary)
        stable_key = canonical_hash({
            "strategy_id": strategy_id,
            "final_oos_start": boundary.isoformat(),
        })
        self.claim_path = registry_dir / f"{stable_key}.claim.json"
        self.completion_path = registry_dir / f"{stable_key}.complete.json"

    def claim(self, payload: dict[str, Any]) -> Path:
        if self.completion_path.exists():
            raise RunnerContractError("final OOS already claimed or completed")
        required = {"run_id", "frozen_hash", "data_provenance"}
        if not required.issubset(payload):
            raise RunnerContractError("final OOS claim provenance is incomplete")
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.claim_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise RunnerContractError("final OOS already claimed; manual audit required") from exc
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_directory(self.registry_dir)
        return self.claim_path

    def complete(self, payload: dict[str, Any]) -> Path:
        if not self.claim_path.exists():
            raise RunnerContractError("final OOS completion requires a claim")
        if self.completion_path.exists():
            raise RunnerContractError("final OOS already completed")
        atomic_write_json(self.completion_path, payload)
        return self.completion_path


def _max_drawdown(returns: np.ndarray) -> float:
    if not len(returns):
        return 0.0
    equity = np.cumprod(1.0 + returns)
    peaks = np.maximum.accumulate(np.concatenate(([1.0], equity)))
    path = np.concatenate(([1.0], equity))
    return float(np.min(path / peaks - 1.0))


def _block_bootstrap(
    returns: np.ndarray, block: int, samples: int, seed: int, scenario: str
) -> dict[str, Any]:
    if not len(returns):
        return {
            "scenario": scenario,
            "block_length": block,
            "samples": samples,
            "return_p05": 0.0,
            "max_drawdown_p95": 0.0,
        }
    rng = np.random.default_rng(seed + block)
    outcomes: list[float] = []
    drawdowns: list[float] = []
    for _ in range(samples):
        sampled: list[float] = []
        while len(sampled) < len(returns):
            start = int(rng.integers(0, len(returns)))
            sampled.extend(returns[(start + offset) % len(returns)] for offset in range(block))
        path = np.asarray(sampled[: len(returns)])
        outcomes.append(float(np.prod(1.0 + path) - 1.0))
        drawdowns.append(abs(_max_drawdown(path)))
    return {
        "scenario": scenario,
        "block_length": block,
        "samples": samples,
        "return_p05": float(np.quantile(outcomes, 0.05)),
        "max_drawdown_p95": float(np.quantile(drawdowns, 0.95)),
    }


def compute_performance_report(
    events: Sequence[ORBTradeEvent],
    selected: np.ndarray,
    *,
    roundtrip_cost_bps: float,
    bootstrap_block_lengths: Sequence[int],
    bootstrap_samples: int,
    random_state: int,
) -> dict[str, Any]:
    if len(events) != len(selected):
        raise RunnerContractError("selection mask must align with events")
    chosen = [event for event, use in zip(events, selected) if bool(use)]
    cost = roundtrip_cost_bps / 10_000.0
    by_day: dict[str, float] = {}
    gross = 0.0
    for event in chosen:
        # Event returns already include builder friction. Reconstruct gross, then apply frozen cost once.
        event_net = float(event.realized_return)
        gross += event_net + cost
        day = event_interval(event).exit_time.date().isoformat()
        by_day[day] = (1.0 + by_day.get(day, 0.0)) * (1.0 + event_net) - 1.0
    daily_by_day: dict[str, float] = {}
    if by_day:
        current = date.fromisoformat(min(by_day))
        last = date.fromisoformat(max(by_day))
        while current <= last:
            if current.weekday() < 5:
                key = current.isoformat()
                daily_by_day[key] = by_day.get(key, 0.0)
            current += timedelta(days=1)
    daily = np.asarray([daily_by_day[day] for day in sorted(daily_by_day)], dtype=float)
    annual: dict[str, dict[str, Any]] = {}
    for day, value in sorted(daily_by_day.items()):
        year = day[:4]
        bucket = annual.setdefault(year, {"days": 0, "return": 0.0})
        bucket["days"] += 1
        bucket["return"] = (1.0 + float(bucket["return"])) * (1.0 + value) - 1.0
    std = float(daily.std(ddof=1)) if len(daily) > 1 else 0.0
    sharpe = float(daily.mean() / std * np.sqrt(252.0)) if std > 0 else 0.0
    return {
        "trade_count": len(chosen),
        "gross_return_sum": gross,
        "net_return_sum": float(sum(event.realized_return for event in chosen)),
        "costs": {"roundtrip_bps": float(roundtrip_cost_bps), "total_cost": cost * len(chosen)},
        "daily_returns": [
            {"date": day, "return": daily_by_day[day]} for day in sorted(daily_by_day)
        ],
        "annual_breakdown": annual,
        "annualized_sharpe": sharpe,
        "max_drawdown": _max_drawdown(daily),
        "bootstrap_stress": [
            _block_bootstrap(
                daily,
                int(block),
                bootstrap_samples,
                random_state,
                ("shorter" if index == 0 else "baseline" if index == 1 else "longer"),
            )
            for index, block in enumerate(bootstrap_block_lengths)
        ],
        "dsr_status": "DSR_UNREPRODUCIBLE",
        "verdict": "NOT_APPROVED",
    }


def _parse_duration(value: str) -> timedelta:
    unit = value[-1].lower()
    amount = float(value[:-1])
    if unit == "d":
        return timedelta(days=amount)
    if unit == "h":
        return timedelta(hours=amount)
    if unit == "m":
        return timedelta(minutes=amount)
    raise RunnerContractError(f"unsupported duration: {value}")


def _session_spec(name: str, config: dict[str, Any]) -> SessionSpec:
    local_hour, local_minute = (int(part) for part in str(config["local_open"]).split(":"))
    return SessionSpec(
        name=name,
        timezone=str(config["timezone"]),
        local_open=time(local_hour, local_minute),
        opening_range=_parse_duration(str(config.get("opening_range", "1h"))),
        candidate_window=_parse_duration(str(config.get("candidate_window", "90m"))),
    )


def _add_canonical_features(frame: pl.DataFrame, bar_duration: timedelta) -> pl.DataFrame:
    """Create close-confirmed features and availability-join hourly ATR."""
    frame = frame.sort("timestamp")
    hourly = frame.group_by_dynamic("timestamp", every="1h", closed="left").agg(
        pl.col("open").first(),
        pl.col("high").max(),
        pl.col("low").min(),
        pl.col("close").last(),
    )
    prior_hour_close = pl.col("close").shift(1)
    hourly_true_range = pl.max_horizontal(
        pl.col("high") - pl.col("low"),
        (pl.col("high") - prior_hour_close).abs(),
        (pl.col("low") - prior_hour_close).abs(),
    )
    hourly = hourly.with_columns(
        hourly_true_range.ewm_mean(alpha=1.0 / 20.0, adjust=False).alias("atr20_bar"),
        (pl.col("timestamp") + timedelta(hours=1)).alias("_atr_available"),
    ).select("_atr_available", "atr20_bar")

    log_hl = (pl.col("high") / pl.col("low")).log()
    log_co = (pl.col("close") / pl.col("open")).log()
    gk_variance = 0.5 * log_hl**2 - (2.0 * np.log(2.0) - 1.0) * log_co**2
    bar_range = pl.col("high") - pl.col("low")
    featured = frame.with_columns(
        (pl.col("timestamp") + bar_duration).alias("_bar_available"),
        pl.col("close").ewm_mean(span=200, adjust=False).alias("ema_200"),
        pl.col("volume").rolling_mean(window_size=12).alias("avg_1h_volume"),
        gk_variance.clip(lower_bound=0.0).sqrt().alias("garman_klass"),
        (bar_range < bar_range.shift(1).rolling_min(window_size=6)).fill_null(False).alias("nr7"),
    )
    return featured.join_asof(
        hourly,
        left_on="_bar_available",
        right_on="_atr_available",
        strategy="backward",
        allow_exact_matches=True,
    ).drop("_bar_available", "_atr_available")


def _extract_symbol_events(
    frame: pl.DataFrame,
    *,
    builder: MetaLabelingORBDatasetBuilder,
    symbol: str,
    session: SessionSpec,
    bar_spec: BarTimestampSpec,
) -> list[ORBTradeEvent]:
    """Bound the quadratic session scan while retaining forward label context."""
    chunk_rows = 5000
    context_rows = builder.max_holding_bars + 24
    extracted: list[ORBTradeEvent] = []
    for start in range(0, len(frame), chunk_rows):
        stop = min(len(frame), start + chunk_rows)
        chunk_start = max(0, start - 24)
        chunk_stop = min(len(frame), stop + context_rows)
        chunk = frame.slice(chunk_start, chunk_stop - chunk_start)
        lower = parse_utc(frame["timestamp"][start])
        upper = (
            parse_utc(frame["timestamp"][stop])
            if stop < len(frame)
            else datetime.max.replace(tzinfo=UTC)
        )
        candidates = builder.extract_events_and_labels(
            chunk,
            symbol=symbol,
            sessions=[session],
            bar_spec=bar_spec,
        )
        extracted.extend(
            event for event in candidates if lower <= parse_utc(event.decision_time) < upper
        )

    # The builder prevents overlapping positions inside a chunk; enforce the same
    # portfolio rule across chunk boundaries deterministically.
    non_overlapping: list[ORBTradeEvent] = []
    previous_exit: datetime | None = None
    for event in order_events(extracted):
        interval = event_interval(event)
        if previous_exit is not None and interval.entry_time <= previous_exit:
            continue
        non_overlapping.append(event)
        previous_exit = interval.exit_time
    return non_overlapping


def build_canonical_events(
    config: dict[str, Any], manifest_path: Path, boundary: datetime, *, include_final_oos: bool,
    validated_files: dict[str, dict[str, Any]],
) -> list[ORBTradeEvent]:
    """Build the only validated ORB path, without any fixed-hour legacy API."""
    boundary = parse_utc(boundary)

    builder = MetaLabelingORBDatasetBuilder(
        target_multiple=float(STRATEGY_SPEC["target_multiple"]),
        stop_multiple=float(STRATEGY_SPEC["stop_multiple"]),
        max_holding_bars=int(STRATEGY_SPEC["max_holding_bars"]),
        stretch_k=float(STRATEGY_SPEC["stretch_k"]),
        friction_bps=float(config.get("execution", {}).get("roundtrip_friction_bps", 6.0)),
        holding_mode=str(STRATEGY_SPEC["holding_mode"]),
    )
    events: list[ORBTradeEvent] = []
    for symbol in config.get("universe", {}).get("symbols", []):
        if symbol not in SYMBOL_FILES:
            raise RunnerContractError(f"unsupported validated universe symbol: {symbol}")
        filename = SYMBOL_FILES[symbol]
        entry = validated_files.get(filename)
        if not entry:
            raise RunnerContractError(f"validated manifest metadata missing for {filename}")
        if entry.get("timestamp_convention") != "open" or entry.get("source_timezone") != "UTC":
            raise RunnerContractError(f"validated timestamp metadata invalid for {filename}")
        frame = pl.read_parquet(manifest_path.parent / filename)
        if not include_final_oos:
            # Labels cannot touch holdout bars. A conservative horizon cutoff avoids truncated labels.
            cutoff = boundary - timedelta(seconds=float(entry["bar_duration_seconds"]) * builder.max_holding_bars)
            frame = frame.filter(pl.col("timestamp") < cutoff)
        duration = timedelta(seconds=float(entry["bar_duration_seconds"]))
        frame = _add_canonical_features(frame, duration)
        session_name = SESSION_KEYS[symbol]
        session = _session_spec(session_name, config["sessions"][session_name])
        bar_spec = BarTimestampSpec(
            convention=str(entry["timestamp_convention"]),
            duration=duration,
            source_timezone=str(entry["source_timezone"]),
        )
        events.extend(
            _extract_symbol_events(
                frame,
                builder=builder,
                symbol=symbol,
                session=session,
                bar_spec=bar_spec,
            )
        )
    return order_events(events)


def _git_state(root: Path) -> dict[str, Any]:
    def command(*args: str) -> str:
        try:
            return subprocess.check_output(["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError):
            return "UNAVAILABLE"
    diff = command("diff", "--binary", "HEAD")
    source_paths = [
        "scripts/run_validated_orb.py",
        "src/features.py",
        "src/labeling.py",
        "src/market_time.py",
        "src/models.py",
        "src/validated_orb_pipeline.py",
        "src/validation.py",
    ]
    source_hashes = {
        relative: sha256_file(root / relative)
        for relative in source_paths
        if (root / relative).is_file()
    }
    return {
        "commit": command("rev-parse", "HEAD"),
        "dirty_diff_sha256": hashlib.sha256(diff.encode()).hexdigest(),
        "source_files": source_hashes,
        "source_fingerprint": canonical_hash(source_hashes),
    }


def _event_rows(events: Sequence[ORBTradeEvent], scores: np.ndarray) -> pl.DataFrame:
    return pl.DataFrame({
        "event_id": [stable_event_id(event) for event in events],
        "symbol": [event.symbol for event in events],
        "decision_time": [parse_utc(event.decision_time) for event in events],
        "entry_time": [parse_utc(event.entry_time) for event in events],
        "exit_time": [parse_utc(event.exit_time) for event in events],
        "label": [event.label for event in events],
        "realized_return": [event.realized_return for event in events],
        "raw_model_score": scores,
    })


def atomic_write_parquet(path: Path, frame: pl.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    frame.write_parquet(temporary)
    descriptor = os.open(temporary, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    _fsync_directory(path.parent)


class ValidatedORBRunner:
    """Coordinates audited development, freeze, and optional one-shot OOS."""

    def __init__(
        self,
        *,
        root: Path,
        config_path: Path,
        manifest_path: Path,
        run_id: str,
        output_dir: Path | None = None,
        validation_status_path: Path | None = None,
    ):
        if not run_id or run_id in {".", ".."} or Path(run_id).name != run_id:
            raise RunnerContractError("run-id must be one non-empty path component")
        self.root = root.resolve()
        self.config_path = config_path.resolve()
        self.manifest_path = manifest_path.resolve()
        self.run_id = run_id
        expected = (self.root / "run_log" / "validated" / run_id).resolve()
        self.output_dir = (output_dir or expected).resolve()
        if self.output_dir != expected:
            raise RunnerContractError(f"output-dir must be exactly {expected}")
        self.validation_status_path = validation_status_path or self.root / "run_log" / "validation_status.json"

    def _load_config(self) -> dict[str, Any]:
        import yaml
        payload = yaml.safe_load(self.config_path.read_text())
        if not isinstance(payload, dict):
            raise RunnerContractError("config must be a mapping")
        return payload

    def preflight(self) -> dict[str, Any]:
        config = self._load_config()
        symbols = list(config.get("universe", {}).get("symbols", []))
        if len(symbols) != 2 or set(symbols) != {"DE30/EUR", "JP225/USD"}:
            config_reasons = ["validated_universe_must_be_DE30_EUR_and_JP225_USD"]
        else:
            config_reasons = []
        boundary_raw = config.get("validation", {}).get("final_oos_start")
        if not boundary_raw:
            config_reasons.append("final_oos_boundary_missing")
            boundary = datetime.max.replace(tzinfo=UTC)
        else:
            boundary = parse_utc(boundary_raw)
        required = {SYMBOL_FILES[symbol] for symbol in symbols if symbol in SYMBOL_FILES}
        timestamp_semantics = config.get("data_contracts", {}).get("timestamp_semantics", {})
        if not isinstance(timestamp_semantics, dict):
            timestamp_semantics = {}
        audit = audit_manifest(
            self.manifest_path,
            required,
            boundary,
            expected_timestamp_semantics=timestamp_semantics,
        )
        audit["blocking_reasons"] = sorted(set(audit["blocking_reasons"] + config_reasons))
        audit["data_code_readiness"] = "READY" if not audit["blocking_reasons"] else "BLOCKED"
        try:
            status_payload = json.loads(self.validation_status_path.read_text())
        except (OSError, json.JSONDecodeError):
            status_payload = {"status": "NOT_APPROVED", "blocking_gates": ["status_missing"]}
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "data_code": audit,
            "strategy_approval": {
                "status": status_payload.get("status", "NOT_APPROVED"),
                "blocking_gates": status_payload.get("blocking_gates", []),
                "blocks_development_execution": False,
            },
            "verdict": "PRECHECK_PASS" if audit["data_code_readiness"] == "READY" else "BLOCKED",
            "final_verdict": "NOT_APPROVED",
        }

    def reserve_output(self) -> None:
        try:
            self.output_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise RunnerContractError("run-id/output directory already exists; overwrite refused") from exc

    def run(self, *, evaluate_final_oos: bool, append_trial: bool) -> dict[str, Any]:
        preflight = self.preflight()
        if preflight["verdict"] != "PRECHECK_PASS":
            return preflight
        self.reserve_output()
        atomic_write_json(self.output_dir / "preflight.json", preflight)
        atomic_write_bytes(self.output_dir / "config.snapshot.yaml", self.config_path.read_bytes())
        config = self._load_config()
        boundary = parse_utc(config["validation"]["final_oos_start"])
        validated_files = {
            item["file"]: item for item in preflight["data_code"]["files"]
        }
        events = build_canonical_events(
            config, self.manifest_path, boundary, include_final_oos=False,
            validated_files=validated_files,
        )
        split = split_development_and_final_oos(events, boundary)
        if len(split.development) < 40:
            gate = {
                "schema_version": "validated_orb_development_gate/v1",
                "passed": False,
                "checks": {"minimum_event_support": False},
                "event_count": len(split.development),
                "blocking_reasons": ["minimum_event_support"],
            }
            atomic_write_json(self.output_dir / "development_gate.json", gate)
            return self._finalize_result({
                "schema_version": SCHEMA_VERSION,
                "run_id": self.run_id,
                "status": "NOT_APPROVED",
                "verdict": "BLOCKED",
                "failure_reason": "insufficient development events",
                "development_gate": gate,
                "final_oos_status": "BLOCKED_BY_DEVELOPMENT_GATE",
                "dsr_status": "DSR_UNREPRODUCIBLE",
                "config_sha256": sha256_file(self.config_path),
                "data_fingerprints": self._data_fingerprints(preflight),
                "development_period": {"end": config["validation"].get("development_end")},
                "final_period": {"start": boundary.isoformat()},
            }, append_trial=append_trial)
        cpcv = config["validation"]["cpcv"]
        embargo = _parse_duration(str(cpcv["embargo_duration"]))
        try:
            model_result = train_meta_classifier_cpcv(
                split.development,
                feature_cols=list(DEFAULT_FEATURES),
                n_groups=int(cpcv["n_groups"]),
                n_test_groups=int(cpcv["n_test_groups"]),
                embargo_duration=embargo,
                require_temporal_contract=True,
            )
        except ValidationContractError as exc:
            diagnostics = getattr(exc, "fold_diagnostics", [])
            gate = {
                "schema_version": "validated_orb_development_gate/v1",
                "passed": False,
                "checks": {"zero_failed_folds": False},
                "blocking_reasons": [str(exc)],
            }
            failure = {
                "schema_version": SCHEMA_VERSION,
                "run_id": self.run_id,
                "status": "NOT_APPROVED",
                "verdict": "BLOCKED",
                "failure_reason": str(exc),
                "fold_diagnostics": diagnostics,
                "development_gate": gate,
                "final_oos_status": "BLOCKED_BY_DEVELOPMENT_GATE",
                "dsr_status": "DSR_UNREPRODUCIBLE",
                "config_sha256": sha256_file(self.config_path),
                "data_fingerprints": self._data_fingerprints(preflight),
                "development_period": {"end": config["validation"].get("development_end")},
                "final_period": {"start": boundary.isoformat()},
            }
            atomic_write_json(self.output_dir / "cpcv_failure.json", failure)
            atomic_write_json(self.output_dir / "development_gate.json", gate)
            return self._finalize_result(failure, append_trial=append_trial)

        try:
            threshold = select_development_threshold(
                model_result.oof_scores,
                np.asarray([event.realized_return for event in split.development]),
                candidates=STRATEGY_SPEC["threshold_candidates"],
                minimum_selection_count=max(10, len(split.development) // 100),
            )
        except RunnerContractError as exc:
            gate = {
                "schema_version": "validated_orb_development_gate/v1",
                "passed": False,
                "checks": {"finite_threshold_results": False},
                "blocking_reasons": ["finite_threshold_results"],
            }
            atomic_write_json(self.output_dir / "development_gate.json", gate)
            return self._finalize_result({
                "schema_version": SCHEMA_VERSION,
                "run_id": self.run_id,
                "status": "NOT_APPROVED",
                "verdict": "BLOCKED",
                "failure_reason": str(exc),
                "development_gate": gate,
                "final_oos_status": "BLOCKED_BY_DEVELOPMENT_GATE",
                "dsr_status": "DSR_UNREPRODUCIBLE",
                "config_sha256": sha256_file(self.config_path),
                "data_fingerprints": self._data_fingerprints(preflight),
                "development_period": {"end": config["validation"].get("development_end")},
                "final_period": {"start": boundary.isoformat()},
            }, append_trial=append_trial)
        diagnostics = list(getattr(model_result, "fold_diagnostics", []) or [])
        coverage = np.asarray(getattr(model_result, "oof_coverage", []))
        scores = np.asarray(model_result.oof_scores, dtype=float)
        failed_fold_count = sum(item.get("status") != "FIT" for item in diagnostics)
        evidence = {
            "schema_version": "validated_orb_development_evidence/v1",
            "auc_distribution": {
                "mean": float(model_result.mean_auc),
                "std": float(getattr(model_result, "std_auc", 0.0)),
                "min": float(getattr(model_result, "min_auc", model_result.mean_auc)),
                "max": float(getattr(model_result, "max_auc", model_result.mean_auc)),
            },
            "fold_diagnostics": diagnostics,
            "failed_fold_count": failed_fold_count,
            "oof_coverage": {
                "event_count": len(split.development),
                "covered_count": int(np.sum(coverage > 0)) if len(coverage) else 0,
                "minimum_fold_coverage": int(coverage.min()) if len(coverage) else 0,
                "complete": bool(len(coverage) == len(split.development) and np.all(coverage > 0)),
            },
        }
        selected_count = int(np.sum(scores >= threshold.threshold))
        finite_threshold_results = bool(
            np.isfinite(threshold.threshold)
            and all(
                trial.objective_value is None or np.isfinite(trial.objective_value)
                for trial in threshold.trials
            )
        )
        checks = {
            "minimum_event_support": len(split.development) >= 40,
            "minimum_trade_support": selected_count >= threshold.minimum_selection_count,
            "complete_oof_coverage": evidence["oof_coverage"]["complete"],
            "zero_failed_folds": failed_fold_count == 0 and bool(diagnostics),
            "finite_oof_scores": bool(len(scores) == len(split.development) and np.all(np.isfinite(scores))),
            "finite_threshold_results": finite_threshold_results,
            "model_quality_gate": bool(model_result.passed_quality_gate),
        }
        gate = {
            "schema_version": "validated_orb_development_gate/v1",
            "passed": all(checks.values()),
            "checks": checks,
            "event_count": len(split.development),
            "selected_trade_count": selected_count,
            "minimum_selected_trade_count": threshold.minimum_selection_count,
            "blocking_reasons": sorted(name for name, passed in checks.items() if not passed),
        }
        atomic_write_json(self.output_dir / "development_evidence.json", evidence)
        atomic_write_json(self.output_dir / "development_gate.json", gate)

        development_metrics = compute_performance_report(
            split.development,
            scores >= threshold.threshold,
            roundtrip_cost_bps=float(config["execution"]["roundtrip_friction_bps"]),
            bootstrap_block_lengths=STRATEGY_SPEC["bootstrap_block_lengths"],
            bootstrap_samples=int(STRATEGY_SPEC["bootstrap_samples"]),
            random_state=int(STRATEGY_SPEC["random_state"]),
        )
        development_metrics["cpcv_evidence"] = evidence
        source_state = _git_state(self.root)
        model_bytes = pickle.dumps(model_result.model)
        frozen = {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "config_sha256": sha256_file(self.config_path),
            "manifest_sha256": sha256_file(self.manifest_path),
            "data_files": preflight["data_code"]["files"],
            "source_state": source_state,
            "environment_lock_sha256": (
                sha256_file(self.root / "uv.lock") if (self.root / "uv.lock").is_file() else None
            ),
            "strategy_spec": STRATEGY_SPEC,
            "features": list(DEFAULT_FEATURES),
            "feature_dependencies": sorted(SYMBOL_FILES[s] for s in config["universe"]["symbols"]),
            "spx_dependency": False,
            "model": "LightGBM binary raw_model_score",
            "model_sha256": hashlib.sha256(model_bytes).hexdigest(),
            "threshold": asdict(threshold),
            "final_oos_start": boundary.isoformat(),
            "development_count": len(split.development),
            "censored_count": len(split.censored),
            "development_gate": gate,
            "cpcv_evidence": evidence,
        }
        frozen["frozen_hash"] = canonical_hash(frozen)
        atomic_write_json(self.output_dir / "frozen_spec.json", frozen)
        atomic_write_json(self.output_dir / "development_metrics.json", development_metrics)
        atomic_write_json(self.output_dir / "threshold_trials.json", asdict(threshold))
        atomic_write_parquet(
            self.output_dir / "development_oof.parquet",
            _event_rows(split.development, scores),
        )
        atomic_write_bytes(self.output_dir / "model.pkl", model_bytes)

        common_result = {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "status": "NOT_APPROVED",
            "dsr_status": "DSR_UNREPRODUCIBLE",
            "frozen_hash": frozen["frozen_hash"],
            "config_sha256": frozen["config_sha256"],
            "data_fingerprints": self._data_fingerprints(preflight),
            "development_period": {"end": config["validation"].get("development_end")},
            "final_period": {"start": boundary.isoformat()},
            "return_series_reference": str(
                (self.output_dir / "development_oof.parquet").relative_to(self.root)
            ),
            "development_gate": gate,
            "development_metrics": development_metrics,
            "threshold_trials": asdict(threshold),
        }
        if not gate["passed"]:
            return self._finalize_result({
                **common_result,
                "verdict": "BLOCKED",
                "failure_reason": "development gate failed: " + ", ".join(gate["blocking_reasons"]),
                "final_oos_status": "BLOCKED_BY_DEVELOPMENT_GATE",
                "final_oos_metrics": None,
            }, append_trial=append_trial)

        final_metrics = None
        final_status = "FINAL_OOS_NOT_OPENED"
        if evaluate_final_oos:
            guard = FinalOOSGuard(
                self.root / "run_log" / "validated" / "_final_oos_claims",
                str(STRATEGY_SPEC["strategy_id"]),
                boundary,
            )
            guard.claim({
                "run_id": self.run_id,
                "strategy_id": STRATEGY_SPEC["strategy_id"],
                "final_oos_start": boundary.isoformat(),
                "frozen_hash": frozen["frozen_hash"],
                "config_sha256": frozen["config_sha256"],
                "manifest_sha256": frozen["manifest_sha256"],
                "data_provenance": preflight["data_code"]["files"],
            })
            all_events = build_canonical_events(
                config, self.manifest_path, boundary, include_final_oos=True,
                validated_files=validated_files,
            )
            final_events = split_development_and_final_oos(all_events, boundary).final_oos
            if not final_events:
                final_status = "FINAL_OOS_PENDING_DATA"
            else:
                X = np.asarray(
                    [[event.features.get(name, 0.0) for name in DEFAULT_FEATURES] for event in final_events],
                    dtype=np.float32,
                )
                final_scores = model_result.model.predict_proba(X)[:, 1]
                final_metrics = compute_performance_report(
                    final_events,
                    final_scores >= threshold.threshold,
                    roundtrip_cost_bps=float(config["execution"]["roundtrip_friction_bps"]),
                    bootstrap_block_lengths=STRATEGY_SPEC["bootstrap_block_lengths"],
                    bootstrap_samples=int(STRATEGY_SPEC["bootstrap_samples"]),
                    random_state=int(STRATEGY_SPEC["random_state"]),
                )
                atomic_write_parquet(
                    self.output_dir / "final_oos_scores.parquet",
                    _event_rows(final_events, final_scores),
                )
                atomic_write_json(self.output_dir / "final_oos_metrics.json", final_metrics)
                final_status = "FINAL_OOS_COMPLETE"
            guard.complete({
                "run_id": self.run_id,
                "frozen_hash": frozen["frozen_hash"],
                "status": final_status,
            })

        return self._finalize_result({
            **common_result,
            "verdict": "NOT_APPROVED",
            "final_oos_status": final_status,
            "final_oos_metrics": final_metrics,
        }, append_trial=append_trial)

    def resume_final_oos(self) -> dict[str, Any]:
        """Score the locked holdout from a verified, committed development run."""
        if not self.output_dir.is_dir():
            raise RunnerContractError("development run directory is missing")
        required = ("result.json", "run.commit.json", "ledger_status.json", "frozen_spec.json", "model.pkl")
        if any(not (self.output_dir / name).is_file() for name in required):
            raise RunnerContractError("committed development artifacts are incomplete")
        result_path = self.output_dir / "result.json"
        commit_path = self.output_dir / "run.commit.json"
        ledger_path = self.output_dir / "ledger_status.json"
        result = json.loads(result_path.read_text())
        commit = json.loads(commit_path.read_text())
        ledger = json.loads(ledger_path.read_text())
        frozen = json.loads((self.output_dir / "frozen_spec.json").read_text())
        development_commit_sha = sha256_file(commit_path)
        if result.get("run_id") != self.run_id or commit.get("run_id") != self.run_id:
            raise RunnerContractError("run identity mismatch in development artifacts")
        if result.get("run_completion") != "COMPLETE":
            raise RunnerContractError("development run is not durably complete")
        if commit.get("result_sha256") != sha256_file(result_path):
            raise RunnerContractError("development result does not match commit evidence")
        if commit.get("ledger_status_sha256") != sha256_file(ledger_path) or ledger.get("status") != "DURABLE":
            raise RunnerContractError("development ledger is not durable or committed")
        if result.get("final_oos_status") != "FINAL_OOS_NOT_OPENED":
            raise RunnerContractError("development run has already attempted final OOS")
        gate = frozen.get("development_gate")
        if not isinstance(gate, dict) or gate.get("passed") is not True or result.get("development_gate", {}).get("passed") is not True:
            raise RunnerContractError("development gate did not pass")
        frozen_hash = frozen.get("frozen_hash")
        frozen_payload = dict(frozen)
        frozen_payload.pop("frozen_hash", None)
        if not frozen_hash or canonical_hash(frozen_payload) != frozen_hash or result.get("frozen_hash") != frozen_hash:
            raise RunnerContractError("frozen development specification hash is invalid")
        if sha256_file(self.config_path) != frozen.get("config_sha256"):
            raise RunnerContractError("current config differs from frozen development config")
        if sha256_file(self.manifest_path) != frozen.get("manifest_sha256"):
            raise RunnerContractError("current manifest differs from frozen development manifest")
        model_path = self.output_dir / "model.pkl"
        if sha256_file(model_path) != frozen.get("model_sha256"):
            raise RunnerContractError("frozen model hash mismatch")
        if any((self.output_dir / name).exists() for name in ("final_oos_resume.json", "final_oos_metrics.json", "final_oos_scores.parquet")):
            raise RunnerContractError("final-OOS resume artifacts already exist; manual audit required")

        preflight = self.preflight()
        if preflight.get("verdict") != "PRECHECK_PASS":
            raise RunnerContractError("current data preflight failed; final OOS remains unopened")
        current_fingerprints = self._data_fingerprints(preflight)
        frozen_fingerprints = {
            item["file"]: item["content_fingerprint"] for item in frozen.get("data_files", [])
        }
        if current_fingerprints != frozen_fingerprints:
            raise RunnerContractError("current data fingerprints differ from frozen development data")
        config = self._load_config()
        boundary = parse_utc(config["validation"]["final_oos_start"])
        if boundary.isoformat() != frozen.get("final_oos_start"):
            raise RunnerContractError("final-OOS boundary differs from frozen development spec")
        validated_files = {item["file"]: item for item in preflight["data_code"]["files"]}
        guard = FinalOOSGuard(
            self.root / "run_log" / "validated" / "_final_oos_claims",
            str(STRATEGY_SPEC["strategy_id"]), boundary,
        )
        claim_path = guard.claim({
            "run_id": self.run_id,
            "strategy_id": STRATEGY_SPEC["strategy_id"],
            "final_oos_start": boundary.isoformat(),
            "frozen_hash": frozen_hash,
            "development_commit_sha256": development_commit_sha,
            "config_sha256": frozen["config_sha256"],
            "manifest_sha256": frozen["manifest_sha256"],
            "data_provenance": preflight["data_code"]["files"],
        })
        with model_path.open("rb") as handle:
            model = pickle.load(handle)
        all_events = build_canonical_events(
            config, self.manifest_path, boundary, include_final_oos=True,
            validated_files=validated_files,
        )
        final_events = split_development_and_final_oos(all_events, boundary).final_oos
        final_metrics = None
        final_status = "FINAL_OOS_PENDING_DATA"
        artifact_hashes: dict[str, str] = {}
        if final_events:
            X = np.asarray(
                [[event.features.get(name, 0.0) for name in DEFAULT_FEATURES] for event in final_events],
                dtype=np.float32,
            )
            final_scores = model.predict_proba(X)[:, 1]
            final_metrics = compute_performance_report(
                final_events,
                final_scores >= float(frozen["threshold"]["threshold"]),
                roundtrip_cost_bps=float(config["execution"]["roundtrip_friction_bps"]),
                bootstrap_block_lengths=STRATEGY_SPEC["bootstrap_block_lengths"],
                bootstrap_samples=int(STRATEGY_SPEC["bootstrap_samples"]),
                random_state=int(STRATEGY_SPEC["random_state"]),
            )
            scores_path = self.output_dir / "final_oos_scores.parquet"
            metrics_path = self.output_dir / "final_oos_metrics.json"
            atomic_write_parquet(scores_path, _event_rows(final_events, final_scores))
            atomic_write_json(metrics_path, final_metrics)
            artifact_hashes = {"scores_sha256": sha256_file(scores_path), "metrics_sha256": sha256_file(metrics_path)}
            final_status = "FINAL_OOS_COMPLETE"
        completion_path = guard.complete({
            "run_id": self.run_id,
            "frozen_hash": frozen_hash,
            "development_commit_sha256": development_commit_sha,
            "status": final_status,
            "event_count": len(final_events),
        })
        atomic_write_json(self.output_dir / "final_oos_resume.json", {
            "schema_version": "validated_orb_final_oos_resume/v1",
            "run_id": self.run_id,
            "status": final_status,
            "frozen_hash": frozen_hash,
            "development_commit_sha256": development_commit_sha,
            "claim_sha256": sha256_file(claim_path),
            "completion_sha256": sha256_file(completion_path),
            "artifacts": artifact_hashes,
            "event_count": len(final_events),
        })
        result["final_oos_status"] = final_status
        result["final_oos_metrics"] = final_metrics
        result["final_oos_resume_receipt"] = "final_oos_resume.json"
        result["verdict"] = "NOT_APPROVED"
        atomic_write_json(result_path, result)
        atomic_write_json(commit_path, {
            "schema_version": "validated_orb_commit/v2",
            "run_id": self.run_id,
            "development_commit_sha256": development_commit_sha,
            "result_sha256": sha256_file(result_path),
            "ledger_status_sha256": sha256_file(ledger_path),
            "final_oos_resume_sha256": sha256_file(self.output_dir / "final_oos_resume.json"),
        })
        return result

    @staticmethod
    def _data_fingerprints(preflight: dict[str, Any]) -> dict[str, str]:
        return {
            item["file"]: item["content_fingerprint"]
            for item in preflight["data_code"]["files"]
        }

    def _finalize_result(self, result: dict[str, Any], *, append_trial: bool) -> dict[str, Any]:
        result["run_completion"] = "INCOMPLETE"
        atomic_write_json(self.output_dir / "result.json", result)
        if append_trial:
            try:
                self._append_trial(result)
            except Exception as exc:
                atomic_write_json(self.output_dir / "ledger_status.json", {
                    "schema_version": "validated_orb_ledger_status/v1",
                    "status": "FAILED",
                    "run_id": self.run_id,
                    "error": f"{type(exc).__name__}: {exc}",
                    "retry_policy": "Do not reuse the run-id; manual ledger audit required",
                })
                raise
            atomic_write_json(self.output_dir / "ledger_status.json", {
                "schema_version": "validated_orb_ledger_status/v1",
                "status": "DURABLE",
                "run_id": self.run_id,
                "ledger": "run_log/validated/trials.jsonl",
            })
        else:
            atomic_write_json(self.output_dir / "ledger_status.json", {
                "schema_version": "validated_orb_ledger_status/v1",
                "status": "SKIPPED",
                "run_id": self.run_id,
            })
        result["run_completion"] = "COMPLETE"
        atomic_write_json(self.output_dir / "result.json", result)
        atomic_write_json(self.output_dir / "run.commit.json", {
            "schema_version": "validated_orb_commit/v1",
            "run_id": self.run_id,
            "result_sha256": sha256_file(self.output_dir / "result.json"),
            "ledger_status_sha256": sha256_file(self.output_dir / "ledger_status.json"),
        })
        return result

    def _append_trial(self, result: dict[str, Any]) -> None:
        ledger = self.root / "run_log" / "validated" / "trials.jsonl"
        lock_path = ledger.with_suffix(".lock")
        ledger.parent.mkdir(parents=True, exist_ok=True)
        threshold_payload = result.get("threshold_trials", {})
        candidates = threshold_payload.get("trials", []) if isinstance(threshold_payload, dict) else []
        common = {
            "schema_version": "validated_orb_trial/v1",
            "run_id": self.run_id,
            "status": result["status"],
            "verdict": result.get("verdict"),
            "failure_reason": result.get("failure_reason"),
            "frozen_hash": result.get("frozen_hash"),
            "config_sha256": result.get("config_sha256"),
            "data_fingerprints": result.get("data_fingerprints", {}),
            "development_period": result.get("development_period"),
            "final_period": result.get("final_period"),
            "return_series_reference": result.get("return_series_reference"),
            "result": str((self.output_dir / "result.json").relative_to(self.root)),
        }
        records = [
            {**common, "trial_id": f"{self.run_id}/threshold/{candidate['threshold']}", "candidate": candidate}
            for candidate in candidates
        ] or [{**common, "trial_id": f"{self.run_id}/run"}]
        lock_descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
            descriptor = os.open(ledger, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
                for record in records:
                    handle.write(json.dumps(record, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            _fsync_directory(ledger.parent)
        finally:
            fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            os.close(lock_descriptor)
