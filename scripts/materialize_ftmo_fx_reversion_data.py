"""Materialize bounded 5-minute research snapshots from canonical LSE Wave-1 FX stores.

This script does not create a competing canonical data source. It derives immutable,
root-relative research inputs for one quant-research session and records canonical
acceptance identities plus output hashes in a manifest.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = Path("/home/quant/dev/quant/ml4t-data/.data/store")
OUT = ROOT / "data/processed/ftmo_fx_reversion_202610"
SYMBOLS = ("EURUSD", "GBPUSD", "AUDUSD")
WINDOWS = (
    ("dev_2010_2017", "2010-01-04T00:00:00Z", "2018-01-01T00:00:00Z"),
    ("dev_2018_2024", "2018-01-01T00:00:00Z", "2025-01-01T00:00:00Z"),
    ("holdout_2025_20261006", "2025-01-01T00:00:00Z", "2026-10-07T00:00:00Z"),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def materialize(symbol: str, label: str, start: str, end: str) -> dict[str, object]:
    source = DATA_ROOT / f"forex_minute_{symbol}"
    files = sorted(source.rglob("data.parquet"))
    if not files:
        raise RuntimeError(f"missing canonical source: {source}")

    frame = (
        pl.scan_parquet(files)
        .filter(
            (pl.col("timestamp") >= pl.lit(start).str.to_datetime(time_zone="UTC"))
            & (pl.col("timestamp") < pl.lit(end).str.to_datetime(time_zone="UTC"))
        )
        .sort("timestamp")
        .group_by_dynamic(
            "timestamp",
            every="5m",
            period="5m",
            closed="left",
            label="left",
        )
        .agg(
            pl.col("symbol").first().alias("symbol"),
            pl.col("open").first().alias("open"),
            pl.col("high").max().alias("high"),
            pl.col("low").min().alias("low"),
            pl.col("close").last().alias("close"),
            pl.col("volume").sum().alias("volume"),
            pl.len().alias("source_rows"),
        )
        .filter(pl.col("source_rows") == 5)
        .select("timestamp", "symbol", "open", "high", "low", "close", "volume", "source_rows")
        .collect()
    )

    if frame.is_empty():
        raise RuntimeError(f"empty snapshot: {symbol} {label}")
    if frame["timestamp"].n_unique() != frame.height:
        raise RuntimeError(f"duplicate timestamps: {symbol} {label}")
    if not frame["timestamp"].is_sorted():
        raise RuntimeError(f"unsorted timestamps: {symbol} {label}")
    if set(frame["symbol"].to_list()) != {symbol}:
        raise RuntimeError(f"symbol mismatch: {symbol} {label}")
    bad_ohlc = frame.filter(
        (pl.col("low") > pl.col("high"))
        | (pl.col("open") < pl.col("low"))
        | (pl.col("open") > pl.col("high"))
        | (pl.col("close") < pl.col("low"))
        | (pl.col("close") > pl.col("high"))
        | (pl.col("low") <= 0)
    )
    if bad_ohlc.height:
        raise RuntimeError(f"invalid OHLC rows: {symbol} {label}: {bad_ohlc.height}")
    if sum(frame.null_count().row(0)) != 0:
        raise RuntimeError(f"null values: {symbol} {label}")

    OUT.mkdir(parents=True, exist_ok=True)
    output = OUT / f"{symbol}_{label}_5m.parquet"
    frame.write_parquet(output, compression="zstd")

    return {
        "symbol": symbol,
        "window": label,
        "requested_start": start,
        "requested_end_exclusive": end,
        "rows": frame.height,
        "start": str(frame["timestamp"].min()),
        "end": str(frame["timestamp"].max()),
        "output": output.relative_to(ROOT).as_posix(),
        "sha256": sha256_file(output),
        "size_bytes": output.stat().st_size,
        "aggregation": "five complete 1-minute bars -> one 5-minute OHLCV bar",
        "bar_timestamp_semantics": "bar open in UTC",
    }


def main() -> None:
    outputs: list[dict[str, object]] = []
    acceptance: dict[str, object] = {}
    for symbol in SYMBOLS:
        acceptance_path = DATA_ROOT / ".acceptance" / f"forex_minute_{symbol}" / "dataset.json"
        payload = json.loads(acceptance_path.read_text(encoding="utf-8"))
        if payload.get("accepted") is not True:
            raise RuntimeError(f"canonical acceptance failed for {symbol}")
        if payload.get("provider") != "london_strategic_edge":
            raise RuntimeError(f"unexpected provider for {symbol}: {payload.get('provider')}")
        if payload.get("canonical_symbol") != symbol:
            raise RuntimeError(f"acceptance symbol mismatch for {symbol}")
        acceptance[symbol] = {
            "path": str(acceptance_path),
            "sha256": sha256_file(acceptance_path),
            "payload": payload,
        }
        for label, start, end in WINDOWS:
            outputs.append(materialize(symbol, label, start, end))

    manifest = {
        "schema_version": "ftmo-fx-reversion-research-snapshot-v1",
        "purpose": "bounded derived inputs for ftmo_fx_intraday_reversion_202610",
        "canonical_authority": "ml4t-data Wave-1 LSE FX stores",
        "canonical_data_root": str(DATA_ROOT),
        "symbols": list(SYMBOLS),
        "acceptance": acceptance,
        "outputs": outputs,
        "holdout_policy": (
            "2025-01-01 through 2026-10-06 is materialized and hashed for the immutable "
            "data gate but must not be scored or inspected for strategy selection before final freeze."
        ),
    }
    manifest_path = OUT / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "manifest": str(manifest_path), "outputs": outputs}, indent=2))


if __name__ == "__main__":
    main()
