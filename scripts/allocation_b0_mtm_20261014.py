"""Reconcile B0 native daily equity to actual fills and source close marks.

This is an accounting adapter. It does not replay decisions or simulate trades.
It is bounded to development data through 2024-12-31.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "run_log/one_bar_practical_1m_20261012"
SOURCE = Path("/home/quant/dev/quant/ml4t-data/.data/store/index_minute_NQ")
OUT = ROOT / "run_log/allocation_prerequisites_20261014/b0"
INITIAL_CASH = 1_000_000.0
MULTIPLIER = 20.0
START = date(2013, 1, 1)
END = date(2024, 12, 31)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def read_rows(path: Path, timestamp_columns: tuple[str, ...]) -> list[dict]:
    """Skip post-cutoff rows before parsing any outcome or price fields."""
    rows = []
    with path.open(newline="") as stream:
        for row in csv.DictReader(stream):
            times = {column: utc(row[column]) for column in timestamp_columns if row.get(column)}
            if not times or any(value.date() > END for value in times.values()):
                continue
            row.update(times)
            rows.append(row)
    return rows


def frame(rows: list[dict], timestamp: str, other_schema: dict[str, pl.DataType]) -> pl.DataFrame:
    schema = {timestamp: pl.Datetime("us", "UTC"), **other_schema}
    if not rows:
        return pl.DataFrame(schema=schema)
    normalized = []
    for row in rows:
        value = dict(row)
        if isinstance(value[timestamp], datetime):
            value[timestamp] = value[timestamp].astimezone(timezone.utc).replace(tzinfo=None)
        normalized.append(value)
    return pl.DataFrame(normalized).with_columns(
        pl.col(timestamp).cast(pl.Datetime("us")).dt.replace_time_zone("UTC")
    )


def account_at_marks(fills: pl.DataFrame, marks: pl.DataFrame) -> pl.DataFrame:
    """Compute native accounting: cash plus signed position value at close marks."""
    if marks.is_empty():
        return marks.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("cash_balance"),
            pl.lit(None, dtype=pl.Float64).alias("position_quantity"),
            pl.lit(None, dtype=pl.Float64).alias("position_market_value"),
            pl.lit(None, dtype=pl.Float64).alias("ledger_equity"),
        )
    if fills.is_empty():
        return marks.sort("timestamp").with_columns(
            pl.lit(INITIAL_CASH).alias("cash_balance"),
            pl.lit(0.0).alias("position_quantity"),
            pl.lit(0.0).alias("position_market_value"),
            pl.lit(INITIAL_CASH).alias("ledger_equity"),
        )
    events = (
        fills.with_columns(
            pl.when(pl.col("side").str.to_lowercase() == "buy")
            .then(pl.col("quantity")).otherwise(-pl.col("quantity")).alias("signed_quantity")
        )
        .group_by("timestamp")
        .agg(
            pl.col("signed_quantity").sum(),
            (-pl.col("signed_quantity") * pl.col("price") * MULTIPLIER - pl.col("commission")).sum().alias("cash_delta"),
        )
        .sort("timestamp")
        .with_columns(
            pl.col("signed_quantity").cum_sum().alias("position_quantity"),
            pl.col("cash_delta").cum_sum().alias("cumulative_cash_delta"),
        )
        .select("timestamp", "position_quantity", "cumulative_cash_delta")
    )
    return (
        marks.sort("timestamp").join_asof(events, on="timestamp", strategy="backward")
        .with_columns(
            (pl.lit(INITIAL_CASH) + pl.col("cumulative_cash_delta").fill_null(0.0)).alias("cash_balance"),
            pl.col("position_quantity").fill_null(0.0),
        )
        .with_columns((pl.col("position_quantity") * pl.col("mark_price") * MULTIPLIER).alias("position_market_value"))
        .with_columns((pl.col("cash_balance") + pl.col("position_market_value")).alias("ledger_equity"))
    )


def read_source_marks(timestamps: list[datetime]) -> pl.DataFrame:
    if not timestamps:
        return pl.DataFrame(schema={"timestamp": pl.Datetime("us", "UTC"), "mark_price": pl.Float64})
    paths = sorted(
        path for path in SOURCE.glob("year=*/month=*/day=*/data.parquet")
        if 2013 <= int(path.parts[-4].split("=")[1]) <= 2024
    )
    return (
        pl.scan_parquet([str(path) for path in paths])
        .filter(pl.col("timestamp").is_in(timestamps))
        .select(
            pl.col("timestamp").dt.replace_time_zone("UTC").alias("timestamp"),
            pl.col("close").cast(pl.Float64).alias("mark_price"),
        ).collect().unique(subset=["timestamp"], keep="last").sort("timestamp")
    )


def signed_fill_rows(year: int) -> list[dict]:
    path = RUN / "by_year" / str(year) / "native_full_tick_cost" / "fills.csv"
    rows = read_rows(path, ("timestamp",))
    return [{"timestamp": row["timestamp"], "side": row["side"].lower(),
             "quantity": float(row["quantity"]), "price": float(row["price"]),
             "commission": float(row["commission"])} for row in rows]


def quantity_at(fills: list[dict], timestamp: datetime) -> float:
    return sum((1.0 if row["side"] == "buy" else -1.0) * row["quantity"]
               for row in fills if row["timestamp"] <= timestamp)


def audit_year_boundaries() -> dict:
    """Audit annual workers' flat boundaries and native fill continuity.

    This compares stored broker outputs only. It does not simulate decisions or fills.
    Rows after 2024-12-31 are discarded by read_rows before numeric fields are parsed.
    """
    workers: dict[int, dict] = {}
    for year in range(2013, 2025):
        base = RUN / "by_year" / str(year) / "native_full_tick_cost"
        daily = read_rows(base / "daily_equity.csv", ("timestamp",))
        daily = [{"timestamp": row["timestamp"], "equity": float(row["equity"])} for row in daily]
        workers[year] = {"daily": daily, "fills": signed_fill_rows(year)}

    boundaries = []
    for year in range(2013, 2024):
        next_year = year + 1
        left, right = workers[year], workers[next_year]

        def at_year(rows: list[dict], y: int, last: bool) -> dict | None:
            candidates = [row for row in rows if row["timestamp"].year == y]
            if not candidates:
                return None
            return (max if last else min)(candidates, key=lambda row: row["timestamp"])

        checkpoints = []
        for worker_year, worker in ((year, left), (next_year, right)):
            dec = at_year(worker["daily"], year, True)
            jan = at_year(worker["daily"], next_year, False)
            for label, row in (("last_december_snapshot", dec), ("first_january_snapshot", jan)):
                checkpoints.append({
                    "worker_year": worker_year,
                    "checkpoint": label,
                    "timestamp_utc": row["timestamp"].isoformat() if row else None,
                    "native_equity_usd": row["equity"] if row else None,
                    "position_quantity_from_native_fills": quantity_at(worker["fills"], row["timestamp"]) if row else None,
                    "flat": abs(quantity_at(worker["fills"], row["timestamp"])) < 1e-12 if row else None,
                })

        common = sorted(set(row["timestamp"] for row in left["daily"]) &
                        set(row["timestamp"] for row in right["daily"]))
        if common:
            lo, hi = common[0], common[-1]
            left_fills = [row for row in left["fills"] if lo <= row["timestamp"] <= hi]
            right_fills = [row for row in right["fills"] if lo <= row["timestamp"] <= hi]
            def signature(row: dict) -> tuple:
                return (row["timestamp"], row["side"], row["quantity"], row["price"], row["commission"])
            left_sig = [signature(row) for row in left_fills]
            right_sig = [signature(row) for row in right_fills]
            left_eq = {row["timestamp"]: row["equity"] for row in left["daily"] if lo <= row["timestamp"] <= hi}
            right_eq = {row["timestamp"]: row["equity"] for row in right["daily"] if lo <= row["timestamp"] <= hi}
            offsets = [left_eq[ts] - right_eq[ts] for ts in common if ts in left_eq and ts in right_eq]
            first_mismatch = next((i for i, (a, b) in enumerate(zip(left_sig, right_sig)) if a != b), None)
            if first_mismatch is None and len(left_sig) != len(right_sig):
                first_mismatch = min(len(left_sig), len(right_sig))
            fills_match = left_sig == right_sig
            offset_constant = bool(offsets) and max(offsets) - min(offsets) <= 0.02
            overlap = {
                "common_daily_snapshot_count": len(common),
                "common_first_timestamp_utc": lo.isoformat(),
                "common_last_timestamp_utc": hi.isoformat(),
                "worker_fill_count_in_common_window": {str(year): len(left_sig), str(next_year): len(right_sig)},
                "fill_sequences_identical_in_common_window": fills_match,
                "first_fill_mismatch_index": first_mismatch,
                "equity_offset_worker_minus_next_min_usd": min(offsets) if offsets else None,
                "equity_offset_worker_minus_next_max_usd": max(offsets) if offsets else None,
                "equity_offset_constant_within_2c": offset_constant,
                "continuity_proven_for_overlap": fills_match and offset_constant,
            }
        else:
            overlap = {"common_daily_snapshot_count": 0, "continuity_proven_for_overlap": False}

        boundaries.append({"calendar_boundary": f"{year}-12-31/{next_year}-01", "checkpoints": checkpoints,
                           "all_available_checkpoints_flat": bool(checkpoints) and all(item["flat"] is True for item in checkpoints),
                           "overlap": overlap})

    all_flat = all(row["all_available_checkpoints_flat"] for row in boundaries)
    all_overlap_continuous = all(row["overlap"].get("continuity_proven_for_overlap", False) for row in boundaries)
    return {
        "status": "VERIFIED_FLAT_BUT_CONTINUITY_BLOCKED" if all_flat and not all_overlap_continuous else
                  "VERIFIED_CONTINUOUS" if all_flat and all_overlap_continuous else "BLOCKED",
        "tested_internal_boundaries": "2013-12/2014-01 through 2023-12/2024-01",
        "excluded_boundary": "2024-12/2025-01; no 2025 data read by authorization",
        "boundary_snapshots_all_flat": all_flat,
        "all_year_worker_overlap_fill_and_equity_continuity_proven": all_overlap_continuous,
        "boundary_details": boundaries,
        "continuous_nav_created": False,
        "blocker": None if all_overlap_continuous else (
            "Year workers have distinct native fill sequences and non-constant equity offsets in their shared daily-snapshot windows. "
            "Flat boundary snapshots do not establish a single continuous frozen-fill account; yearly rebasing or compounding annual returns would fabricate continuity."
        ),
    }
    return (
        pl.scan_parquet([str(path) for path in paths])
        .filter(pl.col("timestamp").is_in(timestamps))
        .select(
            pl.col("timestamp").dt.replace_time_zone("UTC").alias("timestamp"),
            pl.col("close").cast(pl.Float64).alias("mark_price"),
        ).collect().unique(subset=["timestamp"], keep="last").sort("timestamp")
    )


def build_nav() -> tuple[pl.DataFrame, dict]:
    snapshots: list[dict] = []
    year_fills: dict[int, tuple[list[dict], list[dict]]] = {}
    for year in range(2013, 2025):
        root = RUN / "by_year" / str(year) / "native_full_tick_cost"
        daily_rows = read_rows(root / "daily_equity.csv", ("timestamp",))
        # Keep prior December for the annual opening anchor; never score beyond the run year.
        for row in daily_rows:
            row_year = row["timestamp"].date().year
            if (year == 2013 and row_year == 2013) or row_year in (year - 1, year):
                snapshots.append({"run_year": year, "timestamp": row["timestamp"], "native_equity": float(row["equity"])})
        fill_rows = read_rows(root / "fills.csv", ("timestamp",))
        fills = [
            {"timestamp": row["timestamp"], "side": row["side"], "quantity": float(row["quantity"]),
             "price": float(row["price"]), "commission": float(row["commission"])}
            for row in fill_rows if row["timestamp"].date().year <= year
        ]
        trades = read_rows(root / "trades.csv", ("entry_time", "exit_time"))
        closed = [
            {"timestamp": row["exit_time"], "pnl": float(row["pnl"])}
            for row in trades if row.get("status") == "closed" and row["exit_time"].date().year <= year
        ]
        year_fills[year] = (fills, closed)

    source = read_source_marks([row["timestamp"] for row in snapshots])
    mark_by_time = dict(zip(source["timestamp"].to_list(), source["mark_price"].to_list(), strict=True))
    missing_marks = [row["timestamp"].isoformat() for row in snapshots if row["timestamp"] not in mark_by_time]
    observed_rows = []
    for year in range(2013, 2025):
        rows = [row for row in snapshots if row["run_year"] == year]
        mark_rows = [
            {"timestamp": row["timestamp"], "mark_price": mark_by_time.get(row["timestamp"]), "native_equity": row["native_equity"]}
            for row in rows
        ]
        marks = frame(mark_rows, "timestamp", {"mark_price": pl.Float64, "native_equity": pl.Float64})
        fill_rows, trade_rows = year_fills[year]
        fills = frame(fill_rows, "timestamp", {"side": pl.String, "quantity": pl.Float64, "price": pl.Float64, "commission": pl.Float64})
        account = account_at_marks(fills, marks)
        if account.filter(pl.col("mark_price").is_null()).height:
            continue
        trade_events = frame(trade_rows, "timestamp", {"pnl": pl.Float64})
        if trade_events.is_empty():
            account = account.with_columns(pl.lit(0.0).alias("realized_pnl_cumulative"))
        else:
            realized = trade_events.group_by("timestamp").agg(pl.col("pnl").sum()).sort("timestamp") \
                .with_columns(pl.col("pnl").cum_sum().alias("realized_pnl_cumulative")).select("timestamp", "realized_pnl_cumulative")
            account = account.join_asof(realized, on="timestamp", strategy="backward") \
                .with_columns(pl.col("realized_pnl_cumulative").fill_null(0.0))
        account = account.with_columns(
            (pl.col("ledger_equity") - INITIAL_CASH - pl.col("realized_pnl_cumulative")).alias("open_mtm_contribution")
        )
        prior = [row for row in rows if row["timestamp"].date().year < year]
        anchor_native = prior[-1]["native_equity"] if prior else INITIAL_CASH
        anchor_time = prior[-1]["timestamp"] if prior else None
        anchor_realized = anchor_open = 0.0
        if anchor_time:
            anchor = account.filter(pl.col("timestamp") == anchor_time)
            if anchor.height:
                anchor_realized = float(anchor["realized_pnl_cumulative"][0])
                anchor_open = float(anchor["open_mtm_contribution"][0])
        for row in account.filter(pl.col("timestamp").dt.year() == year).iter_rows(named=True):
            realized_annual = row["realized_pnl_cumulative"] - anchor_realized
            open_annual = row["open_mtm_contribution"] - anchor_open
            observed_rows.append({
                "utc_day": row["timestamp"].date().isoformat(),
                "mark_timestamp_utc": row["timestamp"].isoformat(),
                "native_equity_raw": row["native_equity"],
                "account_ledger_equity_raw": row["ledger_equity"],
                "cash_balance_raw": row["cash_balance"],
                "position_quantity": row["position_quantity"],
                "mark_price": row["mark_price"],
                "realized_pnl_net_annual": realized_annual,
                "open_mtm_net_annual": open_annual,
                "nav_native_annual_reset": INITIAL_CASH + row["native_equity"] - anchor_native,
                "nav_ledger_annual_reset": INITIAL_CASH + realized_annual + open_annual,
                "annual_anchor_timestamp_utc": anchor_time.isoformat() if anchor_time else "initial_cash",
                "status": "OBSERVED_SOURCE_MARK",
            })

    observed = pl.DataFrame(observed_rows).sort("utc_day")
    days = []
    day = START
    while day <= END:
        days.append(day.isoformat())
        day += timedelta(days=1)
    output = pl.DataFrame({"utc_day": days}).join(observed, on="utc_day", how="left").with_columns(
        pl.when(pl.col("status").is_null()).then(pl.lit("NO_SOURCE_OBSERVATION")).otherwise(pl.col("status")).alias("status")
    ).sort("utc_day")
    observed = output.filter(pl.col("status") == "OBSERVED_SOURCE_MARK")
    difference = (pl.col("nav_ledger_annual_reset") - pl.col("nav_native_annual_reset")).abs()
    max_difference = observed.select(difference.max()).item()
    diagnostics = {
        "status": "VERIFIED" if not missing_marks and max_difference <= 0.02 else "BLOCKED",
        "period": {"start_inclusive": START.isoformat(), "end_inclusive": END.isoformat()},
        "calendar_days": output.height,
        "observed_source_mark_days": observed.height,
        "no_source_observation_days": output.filter(pl.col("status") == "NO_SOURCE_OBSERVATION").height,
        "source_mark_missing_snapshot_count": len(missing_marks),
        "source_mark_missing_snapshot_examples": missing_marks[:20],
        "max_abs_ledger_vs_native_nav_difference_usd": max_difference,
        "mismatch_count_over_2c": observed.filter(difference > 0.02).height,
        "position_size_check": {"max_abs_contract_quantity": float(observed["position_quantity"].abs().max()),
                                 "rows_over_one_contract": observed.filter(pl.col("position_quantity").abs() > 1.0).height},
        "no_observation_policy": "Calendar rows have null mark/NAV and status NO_SOURCE_OBSERVATION. Do not forward-fill. Use observed dates only.",
        "open_position_policy": "Signed fills define position. Source close at the exact native daily snapshot timestamp marks open quantity.",
        "cost_policy": "Subtract fill commission once. Actual fill prices already include adverse slippage; do not subtract the slippage column again.",
        "annual_boundary_policy": "Each yearly worker is isolated. Rebase to its last pre-Jan-1 native snapshot. 2013 uses initial cash.",
        "continuity_limit": "This is not one continuous multi-year broker account.",
    }
    return output, diagnostics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    nav, diagnostics = build_nav()
    args.output.mkdir(parents=True, exist_ok=True)
    nav.write_csv(args.output / "b0_daily_mtm_nav_2013_2024.csv")
    frozen = json.loads((RUN / "frozen_spec.json").read_text())
    source_manifest = ROOT / frozen["data"]["source_manifest"]
    boundary_audit = audit_year_boundaries()
    (args.output / "b0_year_boundary_audit.json").write_text(json.dumps(boundary_audit, indent=2) + "\n")
    result = {
        **diagnostics,
        "continuous_reference_nav_status": boundary_audit["status"],
        "continuous_reference_nav_created": boundary_audit["continuous_nav_created"],
        "classification": "EXPLORATORY allocation prerequisite only; not allocator training, paper, or live",
        "instrument": "Dukascopy USATECH.IDX/USD BID CFD proxy; illustrative one NQ-equivalent contract; 20 USD/point",
        "frozen_strategy": "B0; 50 completed 30m bars; fixed 50-point/$1,000 stop; one contract; Chicago 17:00 session anchor; existing native fees/slippage",
        "inputs": {
            "practical_run": "run_log/one_bar_practical_1m_20261012/",
            "run_manifest_sha256": sha256(RUN / "manifest.json"),
            "frozen_source_manifest": frozen["data"]["source_manifest"],
            "frozen_source_manifest_sha256": frozen["data"]["source_manifest_sha256"],
            "frozen_source_manifest_hash_matches": sha256(source_manifest) == frozen["data"]["source_manifest_sha256"],
            "source_root": str(SOURCE),
            "source_partitions_used": "year=2013 through year=2024 only",
        },
        "native_engine_semantics": "ml4t-backtest Engine._record_portfolio_state records cash plus signed marked position value. BacktestConfig mark_price defaults to PRICE; DataFeed defaults its price column to close.",
    }
    (args.output / "b0_daily_mtm_reconciliation.json").write_text(json.dumps(result, indent=2) + "\n")
    return 0 if diagnostics["status"] == "VERIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
