"""Prepare bounded 2024-2025 decay-validation inputs for plain funding.

Preparation is outcome-blind:
- materialize only 2023-12 warmup plus 2024-2025 prices/funding;
- construct the unchanged point-in-time signal/universe without forward labels;
- derive frozen basket funding-event and mark-price requirements;
- materialize official mark evidence after the ml4t-data acquisition step.

No IC, forward return, portfolio PnL, or 2026 observation is computed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_crypto_xs_plain_funding_mvp_20261015 import (
    FUNDING_PREFIX,
    HISTORY_HOURS,
    MIN_UNIVERSE,
    REBALANCE_HOURS,
    STORE_ROOT,
    TARGET_UNIVERSE,
    PRICE_STORE,
    attach_funding_24h,
    build_baskets,
    matched_funding_symbols,
    price_features,
    required_funding_events,
)

SESSION = "crypto_xs_plain_funding_decay_validation_20261015_v1"
DATA = ROOT / "data" / "processed" / SESSION
VALID_START = datetime(2024, 1, 1, tzinfo=UTC)
VALID_END = datetime(2026, 1, 1, tzinfo=UTC)
ORIGINAL_ANCHOR = datetime(2020, 6, 1, tzinfo=UTC)
WARMUP_START = datetime(2023, 12, 1, tzinfo=UTC)
YEARS = (2024, 2025)

MARK_STORE = Path(
    "/home/quant/dev/quant/ml4t-data/.data/store/"
    "crypto_futures_mark_price_1m_BINANCE_UM_PERP"
)


def sha256(path: Path) -> str:
    with path.open("rb") as fp:
        return hashlib.file_digest(fp, "sha256").hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def _price_paths(year: int) -> list[str]:
    return [
        str(path)
        for path in PRICE_STORE.glob(f"symbol=*/year={year}/month=*/data.parquet")
    ]


def _funding_paths(symbols: list[str], year: int) -> list[str]:
    out: list[str] = []
    for symbol in symbols:
        out.extend(
            str(path)
            for path in (
                STORE_ROOT / f"{FUNDING_PREFIX}{symbol}_PERP" / f"year={year}"
            ).glob("month=*/data.parquet")
        )
    return out


def _validate_prices(frame: pl.DataFrame, label: str) -> dict[str, Any]:
    if frame.is_empty():
        raise RuntimeError(f"{label}: empty prices")
    if frame.schema["timestamp"].time_zone != "UTC":
        raise RuntimeError(f"{label}: prices not UTC-aware")
    if frame.filter(pl.col("timestamp") >= VALID_END).height:
        raise AssertionError(f"{label}: protected 2026+ price row accessed")
    if frame.group_by("symbol", "timestamp").len().filter(pl.col("len") > 1).height:
        raise RuntimeError(f"{label}: duplicate symbol/timestamp prices")
    bad = frame.filter(
        (~pl.col("open").is_finite())
        | (~pl.col("high").is_finite())
        | (~pl.col("low").is_finite())
        | (~pl.col("close").is_finite())
        | (~pl.col("volume").is_finite())
        | (pl.col("low") <= 0)
        | (pl.col("high") < pl.col("low"))
        | (pl.col("open") < pl.col("low"))
        | (pl.col("open") > pl.col("high"))
        | (pl.col("close") < pl.col("low"))
        | (pl.col("close") > pl.col("high"))
        | (pl.col("volume") < 0)
    ).height
    if bad:
        raise RuntimeError(f"{label}: invalid OHLCV rows={bad}")
    return {
        "rows": frame.height,
        "symbols": frame["symbol"].n_unique(),
        "first": str(frame["timestamp"].min()),
        "last": str(frame["timestamp"].max()),
    }


def _validate_funding(frame: pl.DataFrame, label: str) -> dict[str, Any]:
    if frame.is_empty():
        raise RuntimeError(f"{label}: empty funding")
    if frame.schema["timestamp"].time_zone != "UTC":
        raise RuntimeError(f"{label}: funding not UTC-aware")
    if frame.filter(pl.col("timestamp") >= VALID_END).height:
        raise AssertionError(f"{label}: protected 2026+ funding row accessed")
    if frame.group_by("symbol", "timestamp").len().filter(pl.col("len") > 1).height:
        raise RuntimeError(f"{label}: duplicate funding symbol/timestamp")
    bad = frame.filter(
        pl.col("funding_rate").is_null()
        | (~pl.col("funding_rate").is_finite())
        | (pl.col("funding_interval_hours") <= 0)
    ).height
    if bad:
        raise RuntimeError(f"{label}: invalid funding rows={bad}")
    return {
        "rows": frame.height,
        "symbols": frame["symbol"].n_unique(),
        "first": str(frame["timestamp"].min()),
        "last": str(frame["timestamp"].max()),
        "non_8h_events": frame.filter(pl.col("funding_interval_hours") != 8).height,
    }


def _write_stable(path: Path, frame: pl.DataFrame) -> None:
    if path.exists():
        prior = pl.read_parquet(path)
        if not prior.equals(frame):
            raise FileExistsError(f"prepared file differs from existing evidence: {path}")
        return
    frame.write_parquet(path)


def prepare_source() -> dict[str, Any]:
    DATA.mkdir(parents=True, exist_ok=True)
    funding_symbols = matched_funding_symbols()
    if len(funding_symbols) < MIN_UNIVERSE:
        raise RuntimeError("insufficient matched funding symbols")

    previous_prices = (
        ROOT
        / "data"
        / "processed"
        / "crypto_xs_plain_funding_mvp_20261015_v1"
        / "prices_2023.parquet"
    )
    previous_funding = (
        ROOT
        / "data"
        / "processed"
        / "crypto_xs_plain_funding_mvp_20261015_v1"
        / "funding_2023.parquet"
    )
    if not previous_prices.exists() or not previous_funding.exists():
        raise FileNotFoundError("frozen 2023 development source files unavailable")

    warm_prices = (
        pl.read_parquet(previous_prices)
        .filter(pl.col("timestamp") >= WARMUP_START)
        .sort("symbol", "timestamp")
    )
    warm_funding = (
        pl.read_parquet(previous_funding)
        .filter(pl.col("timestamp") >= WARMUP_START)
        .sort("symbol", "timestamp")
    )
    warm_price_stats = _validate_prices(warm_prices, "warmup_prices_2023")
    warm_funding_stats = _validate_funding(warm_funding, "warmup_funding_2023")
    _write_stable(DATA / "warmup_prices_2023.parquet", warm_prices)
    _write_stable(DATA / "warmup_funding_2023.parquet", warm_funding)

    manifest: dict[str, Any] = {
        "session": SESSION,
        "validation_start": VALID_START.isoformat(),
        "validation_end_exclusive": VALID_END.isoformat(),
        "protected_2026_plus_accessed": False,
        "matched_funding_symbols": len(funding_symbols),
        "warmup": {
            "prices": {
                **warm_price_stats,
                "sha256": sha256(DATA / "warmup_prices_2023.parquet"),
            },
            "funding": {
                **warm_funding_stats,
                "sha256": sha256(DATA / "warmup_funding_2023.parquet"),
            },
        },
        "years": {},
    }

    for year in YEARS:
        ppaths = _price_paths(year)
        if not ppaths:
            raise FileNotFoundError(f"no canonical 1h price partitions for {year}")
        prices = (
            pl.scan_parquet(ppaths, hive_partitioning=True)
            .filter(pl.col("symbol").is_in(funding_symbols))
            .select("timestamp", "symbol", "open", "high", "low", "close", "volume")
            .sort("symbol", "timestamp")
            .collect()
        )
        pstats = _validate_prices(prices, f"prices_{year}")
        ptarget = DATA / f"prices_{year}.parquet"
        _write_stable(ptarget, prices)

        fpaths = _funding_paths(funding_symbols, year)
        if not fpaths:
            raise FileNotFoundError(f"no canonical funding partitions for {year}")
        funding = (
            pl.scan_parquet(fpaths, hive_partitioning=True)
            .select(
                "timestamp",
                "symbol",
                "funding_interval_hours",
                "funding_rate",
                "mark_price",
            )
            .sort("symbol", "timestamp")
            .collect()
        )
        fstats = _validate_funding(funding, f"funding_{year}")
        ftarget = DATA / f"funding_{year}.parquet"
        _write_stable(ftarget, funding)

        manifest["years"][str(year)] = {
            "prices": {**pstats, "sha256": sha256(ptarget)},
            "funding": {**fstats, "sha256": sha256(ftarget)},
        }
        print("PREPARED", year, pstats, fstats, flush=True)

    write_json(DATA / "source_manifest.json", manifest)
    return manifest


def load_bounded() -> tuple[pl.DataFrame, pl.DataFrame]:
    price_paths = [
        DATA / "warmup_prices_2023.parquet",
        DATA / "prices_2024.parquet",
        DATA / "prices_2025.parquet",
    ]
    funding_paths = [
        DATA / "warmup_funding_2023.parquet",
        DATA / "funding_2024.parquet",
        DATA / "funding_2025.parquet",
    ]
    if not all(path.exists() for path in price_paths + funding_paths):
        raise FileNotFoundError("bounded validation source files incomplete")
    prices = pl.concat([pl.read_parquet(path) for path in price_paths]).sort(
        "symbol", "timestamp"
    )
    funding = pl.concat([pl.read_parquet(path) for path in funding_paths]).sort(
        "symbol", "timestamp"
    )
    if prices.filter(pl.col("timestamp") >= VALID_END).height:
        raise AssertionError("2026+ price observation loaded")
    if funding.filter(pl.col("timestamp") >= VALID_END).height:
        raise AssertionError("2026+ funding observation loaded")
    return prices, funding


def build_signal_panel(
    prices: pl.DataFrame, funding: pl.DataFrame
) -> tuple[pl.DataFrame, pl.DataFrame]:
    features = price_features(prices)
    decisions = (
        features.filter(pl.col("timestamp").dt.hour() == 23)
        .with_columns((pl.col("timestamp") + pl.duration(hours=1)).alias("decision_ts"))
    )
    anchor_seconds = int(ORIGINAL_ANCHOR.timestamp())
    decisions = decisions.filter(
        (pl.col("decision_ts") >= VALID_START)
        & (pl.col("decision_ts") < VALID_END)
        & (
            (((pl.col("decision_ts").dt.epoch("s") - anchor_seconds) / 3600).cast(pl.Int64))
            % REBALANCE_HOURS
            == 0
        )
        & (
            pl.col("decision_ts") + pl.duration(hours=49)
            < VALID_END
        )
        & pl.col("dollar_volume_720h").is_not_null()
        & pl.col("atr24").is_not_null()
        & pl.col("trail_start").is_not_null()
        & (
            (pl.col("timestamp") - pl.col("trail_start"))
            == pl.duration(hours=HISTORY_HOURS - 1)
        )
    )
    decisions = attach_funding_24h(decisions, funding)
    counts = decisions.group_by("decision_ts").agg(pl.len().alias("eligible_count"))
    decisions = decisions.join(counts, on="decision_ts", how="left").filter(
        pl.col("eligible_count") >= MIN_UNIVERSE
    )
    panel = (
        decisions.with_columns(
            pl.col("dollar_volume_720h")
            .rank(method="ordinal", descending=True)
            .over("decision_ts")
            .alias("liq_rank")
        )
        .filter(pl.col("liq_rank") <= TARGET_UNIVERSE)
        .with_columns((-pl.col("cum_funding_24h")).alias("prediction"))
        .sort("decision_ts", "symbol")
    )
    cycle = (
        panel.group_by("decision_ts")
        .agg(
            pl.len().alias("universe_size"),
            pl.col("eligible_count").first().alias("eligible_before_topn"),
        )
        .sort("decision_ts")
    )
    return panel, cycle


def derive_signal_requirements() -> dict[str, Any]:
    prices, funding = load_bounded()
    signal, cycles = build_signal_panel(prices, funding)
    if signal.is_empty() or cycles.is_empty():
        raise RuntimeError("no validation signal cycles")
    if signal.filter(pl.col("decision_ts") >= VALID_END).height:
        raise AssertionError("2026 validation decision created")

    signal.write_parquet(DATA / "signal_panel_preoutcome.parquet")
    cycles.write_csv(DATA / "cycle_breadth_preoutcome.csv")
    baskets = build_baskets(signal)
    required = required_funding_events(funding, baskets)
    if required.is_empty():
        raise RuntimeError("no validation held-position funding events")
    if required.filter(pl.col("timestamp") >= VALID_END).height:
        raise AssertionError("2026 funding event required")

    required.write_parquet(DATA / "required_funding_events.parquet")
    months: set[tuple[str, int, int]] = set()
    for symbol, timestamp in required.select("symbol", "timestamp").iter_rows():
        minute = timestamp.replace(second=0, microsecond=0)
        prior = minute - timedelta(minutes=1)
        months.add((symbol, minute.year, minute.month))
        months.add((symbol, prior.year, prior.month))
    if any(year >= 2026 for _, year, _ in months):
        raise AssertionError("mark requirements cross protected 2026 boundary")

    requirements = [
        {"symbol": symbol, "year": year, "month": month}
        for symbol, year, month in sorted(months)
    ]
    payload = {
        "session": SESSION,
        "basket_cycles": len(baskets),
        "signal_rows": signal.height,
        "selected_symbols": required["symbol"].n_unique(),
        "required_funding_events": required.height,
        "requirements_count": len(requirements),
        "min_universe": int(cycles["universe_size"].min()),
        "median_universe": float(cycles["universe_size"].median()),
        "max_universe": int(cycles["universe_size"].max()),
        "first_decision": str(signal["decision_ts"].min()),
        "last_decision": str(signal["decision_ts"].max()),
        "protected_2026_plus_accessed": False,
        "requirements": requirements,
    }
    write_json(DATA / "mark_requirements.json", payload)
    return payload


def _mark_partition(symbol: str, year: int, month: int) -> Path:
    return (
        MARK_STORE
        / f"symbol={symbol}"
        / f"year={year:04d}"
        / f"month={month}"
        / "data.parquet"
    )


def materialize_marks() -> dict[str, Any]:
    required_path = DATA / "required_funding_events.parquet"
    manifest_path = DATA / "mark_requirements.json"
    if not required_path.exists() or not manifest_path.exists():
        raise FileNotFoundError("derive signal requirements first")
    required = pl.read_parquet(required_path).sort("symbol", "timestamp")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    event_keys = required.select("symbol", "timestamp").with_columns(
        pl.col("timestamp").dt.truncate("1m").alias("mark_minute"),
        (pl.col("timestamp").dt.truncate("1m") - pl.duration(minutes=1)).alias(
            "prior_minute"
        ),
    )
    needed: dict[tuple[str, int, int], set[datetime]] = {}
    for row in event_keys.select(
        "symbol", "mark_minute", "prior_minute"
    ).iter_rows(named=True):
        for key in ("mark_minute", "prior_minute"):
            timestamp = row[key]
            bucket = (row["symbol"], timestamp.year, timestamp.month)
            needed.setdefault(bucket, set()).add(timestamp)

    pieces: list[pl.DataFrame] = []
    partitions: list[Path] = []
    for (symbol, year, month), timestamps in sorted(needed.items()):
        path = _mark_partition(symbol, year, month)
        if not path.exists():
            raise FileNotFoundError(f"missing official mark partition: {path}")
        partitions.append(path)
        needed_times = pl.Series(
            "needed_times", sorted(timestamps), dtype=pl.Datetime("ms", "UTC")
        )
        pieces.append(
            pl.scan_parquet(path)
            .filter(pl.col("timestamp").is_in(needed_times.implode()))
            .select("timestamp", "symbol", "open", "high", "low", "close")
            .collect()
        )

    marks = pl.concat(pieces).sort("symbol", "timestamp")
    if marks.group_by("symbol", "timestamp").len().filter(pl.col("len") > 1).height:
        raise RuntimeError("duplicate official mark rows")
    bad = marks.filter(
        (~pl.col("open").is_finite())
        | (~pl.col("high").is_finite())
        | (~pl.col("low").is_finite())
        | (~pl.col("close").is_finite())
        | (pl.col("low") <= 0)
        | (pl.col("high") < pl.col("low"))
        | (pl.col("open") < pl.col("low"))
        | (pl.col("open") > pl.col("high"))
        | (pl.col("close") < pl.col("low"))
        | (pl.col("close") > pl.col("high"))
    ).height
    if bad:
        raise RuntimeError(f"invalid official mark rows={bad}")

    current = marks.rename({"timestamp": "mark_minute"})
    prior = marks.select(
        "symbol",
        pl.col("timestamp").alias("prior_minute"),
        pl.col("close").alias("prior_mark_close"),
    )
    joined = (
        required.join(event_keys, on=["symbol", "timestamp"], how="left")
        .join(current, on=["symbol", "mark_minute"], how="left")
        .join(prior, on=["symbol", "prior_minute"], how="left")
        .sort("timestamp", "symbol")
    )
    missing_prior = joined.filter(pl.col("prior_mark_close").is_null())
    missing_event = joined.filter(pl.col("open").is_null())

    candidates = {
        "missing_prior_count": missing_prior.height,
        "missing_event_minute_count": missing_event.height,
        "event_minute_fallback_candidates": [
            {
                "timestamp": row["timestamp"].isoformat(),
                "symbol": row["symbol"],
                "prior_minute": row["prior_minute"].isoformat(),
                "prior_mark_close": row["prior_mark_close"],
            }
            for row in missing_event.select(
                "timestamp", "symbol", "prior_minute", "prior_mark_close"
            ).iter_rows(named=True)
        ],
    }
    write_json(DATA / "mark_gap_candidates.json", candidates)
    if missing_prior.height:
        raise RuntimeError(
            f"missing prior-minute official marks={missing_prior.height}; "
            "cannot continue"
        )

    approved_path = DATA / "approved_mark_fallbacks.json"
    approved: list[dict[str, str]] = []
    if approved_path.exists():
        raw = json.loads(approved_path.read_text(encoding="utf-8"))
        approved = raw.get("fallbacks", []) if isinstance(raw, dict) else []
    candidate_keys = {
        (row["symbol"], row["timestamp"].isoformat())
        for row in missing_event.select("symbol", "timestamp").iter_rows(named=True)
    }
    approved_keys = {
        (str(item["symbol"]), str(item["timestamp"]))
        for item in approved
    }
    if candidate_keys != approved_keys:
        raise RuntimeError(
            "event-minute mark fallback set is not frozen/approved; "
            f"candidates={len(candidate_keys)} approved={len(approved_keys)}"
        )

    joined = joined.with_columns(
        pl.coalesce(["open", "prior_mark_close"]).alias("mark_proxy"),
        pl.when(pl.col("open").is_not_null())
        .then(pl.lit("EVENT_MINUTE_OPEN"))
        .otherwise(pl.lit("PRIOR_MINUTE_CLOSE_FALLBACK"))
        .alias("mark_quality"),
    )
    if joined.filter(
        (~pl.col("mark_proxy").is_finite()) | (pl.col("mark_proxy") <= 0)
    ).height:
        raise RuntimeError("unresolved funding mark proxy")

    mark_panel = marks.unique(
        subset=["symbol", "timestamp"], maintain_order=True
    ).sort("symbol", "timestamp")
    mark_panel.write_parquet(DATA / "required_funding_mark_1m.parquet")
    joined.write_parquet(DATA / "required_funding_events_with_marks.parquet")

    source_manifest: dict[str, Any] = {
        "mark_store": str(MARK_STORE),
        "archive_importer": {},
        "rest_gap_filler": {},
        "partitions": [],
    }
    for label, path in (
        (
            "archive_importer",
            Path("/home/quant/dev/quant/ml4t-data/scripts/fetch_binance_mark_price_1m.py"),
        ),
        (
            "rest_gap_filler",
            Path("/home/quant/dev/quant/ml4t-data/scripts/fill_binance_mark_price_1m_gaps.py"),
        ),
    ):
        if not path.exists():
            raise FileNotFoundError(path)
        source_manifest[label] = {"path": str(path), "sha256": sha256(path)}
    for partition in sorted(set(partitions)):
        source_json = partition.parent / "source.json"
        rest_json = partition.parent / "rest_gap_sources.json"
        if not source_json.exists():
            raise FileNotFoundError(f"missing source lineage: {source_json}")
        entry: dict[str, Any] = {
            "partition": str(partition),
            "archive_source": json.loads(source_json.read_text(encoding="utf-8")),
            "archive_source_sidecar_sha256": sha256(source_json),
        }
        if rest_json.exists():
            entry["rest_gap_sources"] = json.loads(rest_json.read_text(encoding="utf-8"))
            entry["rest_gap_sidecar_sha256"] = sha256(rest_json)
        source_manifest["partitions"].append(entry)
    write_json(DATA / "mark_source_manifest.json", source_manifest)

    deltas = joined.with_columns(
        (pl.col("mark_proxy") / pl.col("prior_mark_close") - 1).alias(
            "proxy_vs_prior_close"
        )
    )
    result = {
        "required_funding_events": joined.height,
        "symbols": joined["symbol"].n_unique(),
        "mark_partitions": len(set(partitions)),
        "event_minute_open_count": joined.filter(
            pl.col("mark_quality") == "EVENT_MINUTE_OPEN"
        ).height,
        "prior_minute_fallback_count": joined.filter(
            pl.col("mark_quality") == "PRIOR_MINUTE_CLOSE_FALLBACK"
        ).height,
        "fallback_events": candidates["event_minute_fallback_candidates"],
        "all_required_mark_proxies_resolved": True,
        "all_prior_minute_closes_present": True,
        "max_abs_proxy_vs_prior_close": float(
            deltas["proxy_vs_prior_close"].abs().max()
        ),
        "p99_abs_proxy_vs_prior_close": float(
            deltas["proxy_vs_prior_close"].abs().quantile(0.99)
        ),
        "mark_panel_sha256": sha256(DATA / "required_funding_mark_1m.parquet"),
        "event_marks_sha256": sha256(
            DATA / "required_funding_events_with_marks.parquet"
        ),
        "mark_source_manifest_sha256": sha256(DATA / "mark_source_manifest.json"),
        "protected_2026_plus_accessed": False,
    }
    write_json(DATA / "mark_materialization_audit.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-source", action="store_true")
    parser.add_argument("--derive-signal", action="store_true")
    parser.add_argument("--materialize-marks", action="store_true")
    args = parser.parse_args()
    chosen = sum(
        int(value)
        for value in (args.prepare_source, args.derive_signal, args.materialize_marks)
    )
    if chosen != 1:
        parser.error("choose exactly one operation")
    if args.prepare_source:
        result = prepare_source()
    elif args.derive_signal:
        result = derive_signal_requirements()
    else:
        result = materialize_marks()
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
