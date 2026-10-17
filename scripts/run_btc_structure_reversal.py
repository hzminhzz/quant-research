"""Execute the frozen BTCUSDT 1h structure-reversal baseline exactly once."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path

import polars as pl
import yaml

from src.btc_structure_reversal import build_signal_frame, simulate_period


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "btc_structure_reversal_20261006.yaml"
OUT = ROOT / "run_log" / "btc_structure_reversal_20261006"


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _files_for_years(root: Path, years: tuple[int, ...]) -> list[Path]:
    files: list[Path] = []
    for year in years:
        files.extend(sorted((root / f"year={year}").glob("month=*/data.parquet")))
    if not files:
        raise RuntimeError(f"no parquet files under {root}")
    return files


def _combined_identity(files: list[Path]) -> dict[str, object]:
    digest = sha256()
    rows = []
    for path in sorted(files):
        h = sha256(path.read_bytes()).hexdigest()
        rel = str(path)
        rows.append({"path": rel, "sha256": h, "bytes": path.stat().st_size})
        digest.update(rel.encode())
        digest.update(h.encode())
    return {"combined_sha256": digest.hexdigest(), "files": rows}


def _load_prices(path: Path, start: datetime, end: datetime) -> tuple[pl.DataFrame, dict[str, object]]:
    files = _files_for_years(path, (2024, 2025))
    frame = (
        pl.concat([pl.read_parquet(p) for p in files], how="vertical_relaxed")
        .sort("timestamp")
        .filter((pl.col("timestamp") >= start) & (pl.col("timestamp") < end))
        .select("timestamp", "symbol", "open", "high", "low", "close", "volume", "quote_volume")
    )
    if frame.height == 0:
        raise RuntimeError("empty price frame")
    if frame["symbol"].n_unique() != 1 or frame["symbol"][0] != "BTCUSDT":
        raise RuntimeError("price data is not BTCUSDT-only")
    if frame["timestamp"].n_unique() != frame.height:
        raise RuntimeError("duplicate price timestamps")
    diffs = frame["timestamp"].diff().dt.total_seconds().drop_nulls()
    missing = int((diffs != 3600).sum())
    if missing:
        raise RuntimeError(f"price data has {missing} non-hourly gaps")
    expected = int((end - start).total_seconds() // 3600)
    if frame.height != expected:
        raise RuntimeError(f"expected {expected} hourly rows, got {frame.height}")
    audit = {
        "rows": frame.height,
        "first": frame["timestamp"][0].isoformat(),
        "last": frame["timestamp"][-1].isoformat(),
        "expected_rows": expected,
        "non_hourly_gaps": missing,
        "identity": _combined_identity(files),
    }
    return frame, audit


def _load_funding(path: Path, start: datetime, end: datetime) -> tuple[pl.DataFrame, dict[str, object]]:
    files = _files_for_years(path, (2024, 2025))
    frame = (
        pl.concat([pl.read_parquet(p) for p in files], how="vertical_relaxed")
        .sort("timestamp")
        .filter((pl.col("timestamp") >= start) & (pl.col("timestamp") < end))
    )
    keep = [name for name in ("timestamp", "symbol", "funding_rate") if name in frame.columns]
    frame = frame.select(keep)
    if "symbol" in frame.columns:
        frame = frame.filter(pl.col("symbol") == "BTCUSDT")
    if frame.height == 0:
        raise RuntimeError("empty BTCUSDT funding frame")
    if frame["timestamp"].n_unique() != frame.height:
        raise RuntimeError("duplicate funding timestamps")
    audit = {
        "rows": frame.height,
        "first": frame["timestamp"][0].isoformat(),
        "last": frame["timestamp"][-1].isoformat(),
        "identity": _combined_identity(files),
    }
    return frame, audit


def _json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def main() -> None:
    cfg = yaml.safe_load(CONFIG.read_text())
    start = _parse_utc(cfg["data"]["start"])
    end = _parse_utc(cfg["data"]["end_exclusive"])

    prices, price_audit = _load_prices(Path(cfg["data"]["price_path"]), start, end)
    funding, funding_audit = _load_funding(Path(cfg["data"]["funding_path"]), start, end)
    signals, pivots = build_signal_frame(
        prices,
        atr_period=int(cfg["signal"]["atr"]["period"]),
        buffer_atr=float(cfg["signal"]["entry"]["buffer_atr"]),
    )

    dev_start = _parse_utc(cfg["evaluation"]["development"]["start"])
    dev_end = _parse_utc(cfg["evaluation"]["development"]["end_exclusive"])
    oos_start = _parse_utc(cfg["evaluation"]["oos"]["start"])
    oos_end = _parse_utc(cfg["evaluation"]["oos"]["end_exclusive"])

    kwargs = {
        "execution_bps_per_side": float(cfg["costs"]["execution_bps_per_side"]),
        "target_r": float(cfg["exit"]["target_r_multiple"]),
        "max_holding_bars": int(cfg["exit"]["max_holding_bars"]),
    }
    dev_metrics, dev_trades, dev_equity = simulate_period(
        signals, funding, start=dev_start, end_exclusive=dev_end, **kwargs
    )
    oos_metrics, oos_trades, oos_equity = simulate_period(
        signals, funding, start=oos_start, end_exclusive=oos_end, **kwargs
    )

    OUT.mkdir(parents=True, exist_ok=True)
    dev_trades.write_parquet(OUT / "development_trades.parquet")
    oos_trades.write_parquet(OUT / "oos_trades.parquet")
    dev_equity.write_parquet(OUT / "development_equity.parquet")
    oos_equity.write_parquet(OUT / "oos_equity.parquet")
    pl.DataFrame(
        [
            {
                "kind": p.kind,
                "pivot_index": p.pivot_index,
                "confirmation_index": p.confirmation_index,
                "pivot_time": prices["timestamp"][p.pivot_index],
                "confirmation_time": prices["timestamp"][p.confirmation_index],
                "price": p.price,
            }
            for p in pivots
        ]
    ).write_parquet(OUT / "confirmed_pivots.parquet")

    config_hash = sha256(CONFIG.read_bytes()).hexdigest()
    result = {
        "schema_version": "btc_structure_reversal/v1",
        "session_id": cfg["session_id"],
        "status": "EXPLORATORY",
        "approval_status": "NOT_APPROVED",
        "trial_count": 1,
        "config_path": str(CONFIG.relative_to(ROOT)),
        "config_sha256": config_hash,
        "data_audit": {
            "prices": price_audit,
            "funding": funding_audit,
        },
        "signal_audit": {
            "confirmed_pivots": len(pivots),
            "entry_signals_total": int(signals["entry_signal"].sum()),
            "decision_semantics": "signal at completed 1h close; fill next 1h open",
            "pivot_semantics": "2-left/2-right fractal; available only at pivot_index+2",
        },
        "development_2024": dev_metrics,
        "oos_2025": oos_metrics,
        "interpretation_rule": cfg["falsifier"],
        "limitations": [
            "Single exploratory trial; no multiple-testing claim is required yet, but later variants must increase the trial count.",
            "5 bps per side is an exploratory all-in execution proxy, not fill-calibrated TCA.",
            "No market-impact or capacity claim.",
            "Funding is charged from canonical settlement observations; same-hour entry/exit handling is conservative.",
            "Fractal pivots confirm two bars late by construction; the delay is part of the live-usable signal.",
        ],
    }
    (OUT / "result.json").write_text(json.dumps(_json_safe(result), indent=2, sort_keys=True) + "\n")
    print(json.dumps(_json_safe(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
