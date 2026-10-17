"""Native C3 continuous account replay, with a 2024 development cutoff."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl

from scripts.mechanicalpremia_us2_2013_2026_v1 import build_signals, run_native

ROOT = Path(__file__).resolve().parents[1]
START = datetime(2013, 1, 1, tzinfo=timezone.utc)
WARMUP = datetime(2012, 7, 1, tzinfo=timezone.utc)
END = datetime(2025, 1, 1, tzinfo=timezone.utc)
STORE = Path("/home/quant/dev/quant/ml4t-data/.data/store")
FILES = {"US500": STORE / "index_minute_ES", "US100": STORE / "index_minute_NQ"}
SYMBOLS = {"US500": "ES", "US100": "NQ"}
SOURCE = ROOT / "promote/mechanicalpremia_us500_us100/src/mechanicalpremia_us2_2013_2026_v1.py"
RUN_SOURCE = ROOT / "scripts/mechanicalpremia_us2_2013_2026_v1.py"
OUTPUT = ROOT / "run_log/allocation_prerequisites_20261014/c3"
ARTIFACT_EVENT_TIMESTAMPS = {
    "continuous_equity.parquet": ("timestamp",),
    "fills.parquet": ("timestamp",),
    "trades.parquet": ("entry_time", "exit_time"),
    "year_end_equity.parquet": ("as_of",),
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_development() -> tuple[pl.DataFrame, dict[str, Any]]:
    """Read the frozen canonical store from warmup through 2024 only."""
    frames = []
    coverage = []
    for asset, root in FILES.items():
        # Deliberately enumerate years 2012-2024 only. No later partition is read.
        paths = [p for year in range(2012, 2025)
                 for p in sorted((root / f"year={year}").glob("month=*/day=*/data.parquet"))]
        if not paths:
            raise FileNotFoundError(f"No canonical partitions for {asset}")
        prices = (
            pl.scan_parquet([str(p) for p in paths], hive_partitioning=False)
            .filter((pl.col("timestamp") >= pl.lit(WARMUP))
                    & (pl.col("timestamp") < pl.lit(END)))
            .select("timestamp", "symbol", "open", "high", "low", "close", "volume")
            .sort("timestamp").collect()
        )
        if prices.is_empty() or prices["symbol"].n_unique() != 1 or prices["symbol"][0] != SYMBOLS[asset]:
            raise ValueError(f"Canonical symbol mismatch or empty data: {asset}")
        if prices["timestamp"].n_unique() != prices.height:
            raise ValueError(f"Duplicate canonical timestamps: {asset}")
        bad = prices.filter(
            (pl.col("high") < pl.col("low")) | (pl.col("open") < pl.col("low"))
            | (pl.col("open") > pl.col("high")) | (pl.col("close") < pl.col("low"))
            | (pl.col("close") > pl.col("high")) | (pl.col("open") <= 0)
        )
        if bad.height:
            raise ValueError(f"Malformed OHLC data: {asset} ({bad.height} rows)")
        features = build_signals(prices.drop("symbol").with_columns(asset=pl.lit(asset)))
        features = features.filter(pl.col("timestamp") >= pl.lit(START))
        if features["timestamp"].max() >= END:
            raise AssertionError("Development cutoff violated")
        coverage.append({"asset": asset, "rows": features.height,
                         "first": str(features["timestamp"].min()),
                         "last": str(features["timestamp"].max())})
        frames.append(features)
    frame = pl.concat(frames).sort("timestamp", "asset")
    return frame, {"assets": coverage, "rows": frame.height}


def boundary_carry(trades: pl.DataFrame) -> list[dict[str, Any]]:
    """Count native trade lifecycles that span each Jan 1 boundary."""
    needed = {"symbol", "entry_time", "exit_time"}
    if not needed.issubset(trades.columns):
        raise ValueError(f"Native trade ledger lacks {sorted(needed - set(trades.columns))}")
    out = []
    for year in range(2013, 2024):
        boundary = datetime(year + 1, 1, 1)
        rows = trades.filter(
            (pl.col("entry_time") < pl.lit(boundary))
            & (pl.col("exit_time").is_null() | (pl.col("exit_time") >= pl.lit(boundary)))
        )
        out.append({"boundary": boundary.isoformat() + "Z", "open_trade_count": rows.height,
                    "symbols": sorted(rows["symbol"].unique().to_list())})
    return out


def validate_artifact_cutoffs(output: Path = OUTPUT) -> dict[str, Any]:
    """Check all event timestamps with projected scans before reading outcomes.

    Polars reads only the timestamp columns in this pass. Any missing,
    non-datetime, null, pre-development, or post-cutoff event blocks all full
    artifact reads.
    """
    evidence: dict[str, Any] = {}
    for filename, columns in ARTIFACT_EVENT_TIMESTAMPS.items():
        path = output / filename
        if not path.is_file():
            raise FileNotFoundError(f"Required saved artifact is missing: {path}")
        schema = pl.read_parquet_schema(path)
        missing = [column for column in columns if column not in schema]
        if missing:
            raise ValueError(f"Artifact {filename} is missing required event timestamp column(s): {missing}")
        for column in columns:
            dtype = schema[column]
            if dtype.base_type() != pl.Datetime:
                raise TypeError(f"Artifact {filename}.{column} must be Datetime, found {dtype}")

        # Projection is deliberate: no PnL, prices, quantities, or other outcome
        # columns are read until every artifact passes this timestamp-only gate.
        timestamps = pl.scan_parquet(path).select(*columns).collect()
        checked = {}
        for column in columns:
            series = timestamps[column]
            if series.null_count():
                raise ValueError(f"Artifact {filename}.{column} contains null event timestamps")
            dtype = schema[column]
            start = START if dtype.time_zone else START.replace(tzinfo=None)
            end = END if dtype.time_zone else END.replace(tzinfo=None)
            minimum, maximum = series.min(), series.max()
            if minimum < start:
                raise ValueError(
                    f"Artifact {filename}.{column} has event before development start: {minimum} < {start}"
                )
            # Event times are inclusive at their recorded instant. The scored
            # interval is half-open, so an event at END is outside the period.
            if maximum >= end:
                raise ValueError(
                    f"Artifact {filename}.{column} has event at/after exclusive cutoff: {maximum} >= {end}"
                )
            checked[column] = {
                "rows": len(series),
                "minimum": str(minimum),
                "maximum": str(maximum),
                "cutoff_semantics": "all event instants must satisfy START <= t < END",
            }
        evidence[filename] = checked
    return evidence


def _validate_fill_sides(fills: pl.DataFrame) -> None:
    if "side" not in fills.columns:
        raise ValueError("Native fill ledger is missing side")
    invalid = fills.filter(pl.col("side").is_null() | ~pl.col("side").is_in(["buy", "sell"]))
    if invalid.height:
        values = invalid["side"].unique().to_list()
        raise ValueError(f"Native fill ledger has unrecognized side value(s): {values}")


def _validate_trade_directions(trades: pl.DataFrame) -> None:
    if "direction" not in trades.columns:
        raise ValueError("Native trade ledger is missing direction")
    invalid = trades.filter(
        pl.col("direction").is_null() | ~pl.col("direction").is_in(["long", "short"])
    )
    if invalid.height:
        values = invalid["direction"].unique().to_list()
        raise ValueError(f"Native trade ledger has unrecognized direction value(s): {values}")


def reconcile_native_artifacts(output: Path = OUTPUT) -> dict[str, Any]:
    """Fail closed on all timestamps before reading saved outcome columns."""
    timestamp_preflight = validate_artifact_cutoffs(output)
    fills = pl.read_parquet(output / "fills.parquet")
    trades = pl.read_parquet(output / "trades.parquet")
    curve = pl.read_parquet(output / "continuous_equity.parquet")
    year_end = pl.read_parquet(output / "year_end_equity.parquet")
    _validate_fill_sides(fills)
    _validate_trade_directions(trades)
    if curve.is_empty():
        raise ValueError("Native equity curve is empty")
    signed = pl.when(pl.col("side") == "sell").then(1.0).otherwise(-1.0)
    fills = fills.with_columns(
        (signed * pl.col("quantity") * pl.col("price") - pl.col("commission")).alias("_cashflow")
    )
    cash = 100_000.0 + float(fills["_cashflow"].sum())
    open_trades = trades.filter(pl.col("status") == "open")
    position_sign = pl.when(pl.col("direction") == "short").then(-1.0).otherwise(1.0)
    open_trades = open_trades.with_columns(
        (position_sign * pl.col("quantity") * pl.col("exit_price") * pl.col("multiplier")).alias("_mark")
    )
    marked = float(open_trades["_mark"].sum() or 0.0)
    final_equity = float(curve.tail(1)["equity"][0])
    delta = final_equity - cash - marked
    if abs(delta) >= 0.01:
        raise AssertionError(f"Fill cash plus open-position marks do not reconcile: {delta}")
    return {
        "initial_cash": 100_000.0,
        "ending_cash_reconstructed_from_native_fills": cash,
        "ending_marked_positions_from_native_open_trades": marked,
        "ending_equity_from_native_engine_curve": final_equity,
        "reconciliation_delta": delta,
        "open_positions": open_trades.select(
            "symbol", "direction", "quantity", "exit_price", "multiplier", "entry_time", "exit_time"
        ).to_dicts(),
        "native_fill_count": fills.height,
        "native_trade_count": trades.height,
        "equity_rows": curve.height,
        "first_equity_timestamp": str(curve["timestamp"].min()),
        "last_equity_timestamp": str(curve["timestamp"].max()),
        "annual_equity": year_end.to_dicts(),
        "annual_boundary_carry": boundary_carry(trades),
        "timestamp_preflight": timestamp_preflight,
    }


def report_from_artifacts(output: Path = OUTPUT) -> dict[str, Any]:
    """Write a concise audit report from already-written native Engine artifacts."""
    account = reconcile_native_artifacts(output)
    artifacts = {}
    for name in ("fills.parquet", "trades.parquet", "continuous_equity.parquet", "year_end_equity.parquet"):
        path = output / name
        artifacts[name] = {"sha256": _sha256(path), "bytes": path.stat().st_size}
    report = {
        "status": "VERIFIED",
        "classification": "EXPLORATORY_PREREQUISITE",
        "development_start": START.isoformat(),
        "development_end_exclusive": END.isoformat(),
        "reserved_2025_2026_accessed": False,
        "engine": "ml4t.backtest.Engine via frozen C3 run_native",
        "strategy": {"trial": "SOURCE-US2", "h1_weight": 0.2336, "d1_weight": 0.7664,
                     "risk_budget_fraction": 0.01, "gross_notional_cap": 1.90,
                     "commission_bps_per_side": 1.0, "slippage_bps_per_side": 2.0,
                     "execution": "NEXT_BAR", "daily_clock": "17:00 America/New_York"},
        "data_coverage": {
            "canonical_assets": ["US500", "US100"],
            "first_scored_timestamp": str(START),
            "last_scored_timestamp": account["last_equity_timestamp"],
            "canonical_partition_years_enumerated": "2012-2024 only",
        },
        "account_reconciliation": account,
        "source": {
            "promoted_snapshot": {"path": str(SOURCE.relative_to(ROOT)), "sha256": _sha256(SOURCE)},
            "root_run_module": {"path": str(RUN_SOURCE.relative_to(ROOT)), "sha256": _sha256(RUN_SOURCE)},
            "canonical_store": {"US500": str(FILES["US500"]), "US100": str(FILES["US100"]),
                                 "enumerated_years": "2012-2024 only"},
        },
        "artifacts": artifacts,
        "limitations": [
            "Synthetic CFD price units; multiplier and lot mapping are not verified.",
            "Direct costs are frozen assumptions. Overnight financing is not modeled.",
            "BID-only quotes omit observed ASK spread and broker parity.",
            "H1 stop attaches after entry fill confirmation; the first-minute gap remains.",
            "The final 2024 open position is marked at cutoff; no 2025 behavior is evaluated.",
        ],
    }
    (output / "report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    return report


def run(output: Path = OUTPUT) -> dict[str, Any]:
    frame, coverage = load_development()
    strategy, result = run_native(frame, "PORTFOLIO-SOURCE-RISK",
                                  commission_bps=1.0, slippage_bps=2.0)
    output.mkdir(parents=True, exist_ok=True)
    fills, trades = result.to_fills_dataframe(), result.to_trades_dataframe()
    curve = pl.DataFrame({"timestamp": [t for t, _ in result.equity_curve],
                          "equity": [float(v) for _, v in result.equity_curve]}).sort("timestamp")
    if curve.is_empty() or curve["timestamp"].max() >= END:
        raise AssertionError("Native curve is empty or exceeds the cutoff")
    fills.write_parquet(output / "fills.parquet")
    trades.write_parquet(output / "trades.parquet")
    curve.write_parquet(output / "continuous_equity.parquet")
    year_end = (curve.with_columns(year=pl.col("timestamp").dt.year())
                .group_by("year").agg(pl.col("timestamp").max().alias("as_of"),
                                       pl.col("equity").last().alias("equity"))
                .sort("year"))
    year_end.write_parquet(output / "year_end_equity.parquet")
    marked = sum(p["quantity"] * p["current_price"] * p["multiplier"]
                 for p in strategy.end_positions.values())
    delta = float(strategy.end_equity) - float(strategy.end_cash) - marked
    if abs(delta) >= 0.01:
        raise AssertionError(f"Ending native equity reconciliation failed: {delta}")
    report = report_from_artifacts(output)
    account = report["account_reconciliation"]
    if (abs(account["ending_cash_reconstructed_from_native_fills"] - strategy.end_cash) >= 0.01
            or abs(account["ending_equity_from_native_engine_curve"] - strategy.end_equity) >= 0.01
            or abs(account["ending_marked_positions_from_native_open_trades"] - marked) >= 0.01):
        raise AssertionError("Persisted native artifacts do not reconcile to the live Engine state")
    account["ending_cash_from_native_broker"] = float(strategy.end_cash)
    account["ending_positions_from_native_broker"] = strategy.end_positions
    report["native_engine_metrics"] = result.metrics
    (output / "report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--from-artifacts", action="store_true",
                        help="Audit existing native artifacts without rerunning the engine")
    args = parser.parse_args()
    report = report_from_artifacts(args.output) if args.from_artifacts else run(args.output)
    ending = report.get("account_reconciliation", report.get("ending_account", {}))
    print(json.dumps({"status": report["status"], "ending_account": ending,
                      "output": str(args.output)}, default=str))


if __name__ == "__main__":
    main()
