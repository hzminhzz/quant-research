#!/usr/bin/env python3
"""Materialize the bounded registered LSE NQ.F proxy used by VWAP/ADX phases 2-3.

This is a data preparation and audit script, NOT a strategy backtest.
Only own one output Parquet and one source manifest; never edit the input source.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path("/home/quant/dev/quant/ml4t-data/.artifacts/lse-orb/raw-nq/futures_NQ.F_1m.parquet")
SOURCE_SHA256 = "c12e2aaf9e7a4bbe8224d09a53bc7416f7088a2693d87adf3de0138fbf6a8edd"
TARGET = ROOT / "data/processed/vwap_adx_nqf_2026h1_1m.parquet"
MANIFEST = ROOT / "run_log/vwap_pullback_adx_nq_20261012_proxy_v2/phase2_source_manifest.json"
START = datetime(2025, 12, 15, tzinfo=timezone.utc)
END = datetime(2026, 7, 1, tzinfo=timezone.utc)

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()

def main() -> None:
    assert SOURCE.is_file(), f"source missing: {SOURCE}"
    assert sha(SOURCE) == SOURCE_SHA256, "Source changed: stop and review"
    assert not TARGET.exists(), "Do not overwrite existing prepared evidence"
    assert not MANIFEST.exists(), "Do not overwrite existing manifest"
    frame = (
        pl.scan_parquet(SOURCE)
        .rename({"ts":"timestamp"})
        .filter((pl.col("timestamp") >= START) & (pl.col("timestamp") < END))
        .sort("timestamp")
        .collect()
    )
    assert frame.height > 140000
    assert isinstance(frame.schema["timestamp"], pl.Datetime) and frame.schema["timestamp"].time_zone == "UTC", frame.schema
    assert frame["timestamp"].n_unique() == frame.height
    assert frame["timestamp"].is_sorted()
    assert frame.select(pl.all().null_count()).sum_horizontal().sum() == 0
    assert frame.filter(
        (pl.col("high") < pl.max_horizontal("open","low","close"))
        | (pl.col("low") > pl.min_horizontal("open","high","close"))
        | (pl.col("volume") <= 0)
    ).is_empty()
    TARGET.parent.mkdir(parents=True,exist_ok=True)
    TARGET.with_suffix(".parquet.tmp").unlink(missing_ok=True)
    frame.write_parquet(TARGET,compression="zstd")
    report = {
        "status": "PHASE2_EXPLORATORY_DATA_READY",
        "session_id": "vwap_pullback_adx_nq_20261012_proxy_v2",
        "original_session_id": "vwap_pullback_adx_nq_20261012",
        "source_path": str(SOURCE),
        "source_sha256": SOURCE_SHA256,
        "source_vendor": "London Strategic Edge",
        "source_symbol": "NQ.F",
        "contract_level": False,
        "continuous_roll_semantics_known": False,
        "volume_genuine_cme_exchange": "UNVERIFIED",
        "source_timestamp_timezone": "UTC",
        "bar_time_basis": "BAR_OPEN_ASSUMED_VERIFY_AT_PROVIDER",
        "restricted_analysis": "2026-01-01 to 2026-07-01 UTC only (plus Dec 2025 indicator warmup)",
        "registered_input_path": TARGET.relative_to(ROOT).as_posix(),
        "input_sha256": sha(TARGET),
        "rows": frame.height,
        "first_timestamp": str(frame["timestamp"].min()),
        "last_timestamp": str(frame["timestamp"].max()),
        "unique_timestamps": frame["timestamp"].n_unique(),
        "nonpositive_volume": int(frame.filter(pl.col("volume") <= 0).height),
        "missing_values": 0,
        "invalid_ohlc": 0,
        "research_use": "PROXY_EVENT_DIAGNOSTICS_ONLY",
        "phase4_exact_CME_execution_ready": False,
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps(report,indent=2,sort_keys=True))

if __name__ == "__main__":
    main()
