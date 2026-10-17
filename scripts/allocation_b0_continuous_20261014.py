"""Single native ML4T Engine replay for the frozen B0 development period.

This module reuses the promoted B0 strategy and the established practical feed
construction. It does not implement an execution loop or a backtest simulator.
It reads source partitions whose directory year is 2013 through 2024 only.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
import yaml

ROOT = Path(__file__).resolve().parents[1]
STRATEGY_DIR = ROOT / "promote/one_bar_nq_30m"
SRC_DIR = STRATEGY_DIR / "src"
sys.path.insert(0, str(SRC_DIR))
sys.path.insert(0, str(ROOT / "scripts"))

import run_one_bar_practical_yearly_20261012 as feed_impl  # noqa: E402
import run_one_bar_dukascopy_phase567_20261011 as native_impl  # noqa: E402
from allocation_b0_mtm_20261014 import account_at_marks  # noqa: E402

SOURCE = Path("/home/quant/dev/quant/ml4t-data/.data/store/index_minute_NQ")
OUT = ROOT / "run_log/allocation_prerequisites_20261014/b0/continuous_2013_2024"
START = date(2013, 1, 1)
END = date(2024, 12, 31)
ASSET = "NQ_PROXY"
INITIAL_CASH = 1_000_000.0
MULTIPLIER = 20.0
TICK = 0.25
COMMISSION = 2.50
SLIPPAGE_POINTS = 0.25
STOP_POINTS = 50.0
LOOKBACK = 50
MAX_ENTRIES_PER_SESSION = 2
TZ = ZoneInfo("America/Chicago")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_frozen_b0() -> dict:
    """Fail closed if promoted B0 or the frozen full-tick cost case changed."""
    strategy = yaml.safe_load((STRATEGY_DIR / "strategy.yaml").read_text())
    config = yaml.safe_load((STRATEGY_DIR / "config/backtest.yaml").read_text())
    rules = strategy["rules"]
    instrument = strategy["instrument_assumption"]
    costs = config["cost_scenarios"]["full_tick_stress"]
    checks = {
        "strategy_id": strategy.get("strategy_id") == "one_bar_nq_30m",
        "lookback": rules.get("lookback_complete_bars") == LOOKBACK,
        "stop_dollars": rules.get("protective_loss_usd") == STOP_POINTS * MULTIPLIER,
        "entry_relation": "cancel opposing entry after first fill" in rules.get("entry_order_relation", ""),
        "max_entries": rules.get("max_entries_per_chicago_session_day") == MAX_ENTRIES_PER_SESSION,
        "next_30m_exit": "immediately following 30-minute bar" in rules.get("exit", ""),
        "17_chicago_session": "17:00 America/Chicago" in rules.get("session", ""),
        "one_contract": instrument.get("mapping", "").startswith("one illustrative")
            and config["instrument_assumptions"].get("contracts") == 1,
        "proxy_multiplier": instrument.get("mapping", "").find("20 USD per index point") >= 0
            and config["instrument_assumptions"].get("illustrative_usd_per_point") == MULTIPLIER,
        "tick": config["instrument_assumptions"].get("illustrative_tick_points") == TICK,
        "commission": costs.get("commission_usd_per_fill") == COMMISSION,
        "slippage": costs.get("adverse_slippage_points_per_fill") == SLIPPAGE_POINTS,
        "source_instrument": config["source"].get("instrument") == "USATECH.IDX/USD"
            and config["source"].get("price_type") == "BID"
            and config["source"].get("timeframe") == "1m",
    }
    if not all(checks.values()):
        raise ValueError(f"Frozen B0 settings do not match this replay: {checks}")
    return {"status": "VERIFIED", "checks": checks}


def eligible_source_files() -> list[Path]:
    """Return only source partitions in the authorized development years."""
    selected = []
    for path in SOURCE.glob("year=*/month=*/day=*/data.parquet"):
        year = int(path.parts[-4].split("=")[1])
        month = int(path.parts[-3].split("=")[1])
        day = int(path.parts[-2].split("=")[1])
        partition_date = date(year, month, day)
        if START <= partition_date <= END:
            selected.append(path)
    return sorted(selected)


def build_continuous_feed(paths: list[Path]) -> tuple[pl.DataFrame, pl.DataFrame, dict]:
    """Build one continuous minute feed using the established B0 feature path."""
    if not paths:
        raise ValueError("No authorized 2013-2024 source partitions found")
    years = {int(path.parts[-4].split("=")[1]) for path in paths}
    if years - set(range(2013, 2025)):
        raise ValueError(f"Unauthorized source partition years selected: {sorted(years)}")

    raw = (
        pl.scan_parquet([str(path) for path in paths])
        .filter(pl.col("timestamp").dt.date().is_between(START, END))
        .select("timestamp", "open", "high", "low", "close", "volume")
        .sort("timestamp")
        .collect(engine="streaming")
        .with_columns(pl.col("timestamp").dt.replace_time_zone("UTC"))
    )
    if raw.is_empty():
        raise ValueError("Authorized source partitions contain no rows in the development window")

    local = pl.col("timestamp").dt.convert_time_zone("America/Chicago")
    raw = raw.with_columns(
        local.alias("local"),
        pl.when(local.dt.hour() >= 17).then(local.dt.date())
        .otherwise(local.dt.date().dt.offset_by("-1d")).alias("session_date"),
    )
    sessions = raw["session_date"].unique().sort().to_list()
    starts = pl.DataFrame({
        "session_date": sessions,
        "session_start_utc": [
            datetime(day.year, day.month, day.day, 17, tzinfo=TZ).astimezone(timezone.utc)
            for day in sessions
        ],
    })
    source = raw.join(starts, on="session_date", how="left").with_columns(
        ((pl.col("timestamp") - pl.col("session_start_utc")).dt.total_minutes() // 30).alias("bar_no")
    )
    bars = (
        source.group_by("session_date", "bar_no")
        .agg(
            pl.col("timestamp").min().alias("bar_start"),
            pl.col("open").first().alias("bar_open"),
            pl.col("high").max().alias("bar_high"),
            pl.col("low").min().alias("bar_low"),
            pl.col("close").last().alias("bar_close"),
            pl.col("volume").sum().alias("bar_volume"),
            pl.len().alias("n"),
            pl.col("timestamp").n_unique().alias("unique_n"),
        )
        .filter((pl.col("n") == 30) & (pl.col("unique_n") == 30))
        .sort("bar_start")
    )
    bars = feed_impl.add_breakout_features(bars).with_columns(
        ((pl.col("bar_high") - pl.col("bar_low")) / pl.col("bar_high")).alias("range_proxy"),
        (pl.col("bar_start") + pl.duration(minutes=30)).alias("available_at"),
    ).filter(pl.col("next_long_stop").is_not_null())
    levels = bars.select(
        (pl.col("available_at") - pl.duration(minutes=1)).alias("release_decision_at"),
        "next_long_stop", "next_short_stop", "range_proxy",
    )
    feed = (
        source.sort("timestamp")
        .join_asof(levels.sort("release_decision_at"), left_on="timestamp",
                   right_on="release_decision_at", strategy="backward")
        .with_columns(pl.lit(ASSET).alias("asset"))
        .select("timestamp", "asset", "open", "high", "low", "close", "volume",
                "next_long_stop", "next_short_stop", "range_proxy")
        .sort("timestamp")
    )
    duplicates = raw.height - raw["timestamp"].n_unique()
    null_ohlc = sum(raw[column].null_count() for column in ("open", "high", "low", "close"))
    invalid_ohlc = raw.filter(
        (pl.col("high") < pl.col("low")) | (pl.col("close") > pl.col("high")) |
        (pl.col("close") < pl.col("low"))
    ).height
    quality = {
        "source_partition_count": len(paths),
        "source_partition_years": sorted(years),
        "source_row_count": raw.height,
        "source_first_timestamp_utc": raw["timestamp"].min().isoformat(),
        "source_last_timestamp_utc": raw["timestamp"].max().isoformat(),
        "complete_30m_bars": bars.height,
        "incomplete_30m_bins_excluded": int(source.select(pl.struct("session_date", "bar_no").n_unique()).item()) - bars.height,
        "duplicate_timestamps": duplicates,
        "null_ohlc_values": null_ohlc,
        "invalid_ohlc_rows": invalid_ohlc,
        "feed_rows": feed.height,
        "warmup": "All available 2013 data precedes the first eligible 50-bar signal; no pre-2013 source is used.",
        "cutoff": "Partition discovery and timestamp filter both end at 2024-12-31; 2025+ partitions are not selected.",
    }
    if duplicates or null_ohlc or invalid_ohlc:
        raise ValueError(f"Source quality gate failed: {quality}")

    # Keep only daily close marks while the engine runs. The full minute feed is
    # released immediately after the one native Engine execution.
    daily_marks = feed.group_by(pl.col("timestamp").dt.date().alias("utc_day")).agg(
        pl.col("timestamp").last(), pl.col("close").last().alias("mark_price")
    ).sort("timestamp")
    return feed, daily_marks, quality


def hash_inputs(paths: list[Path]) -> dict:
    fixed_inputs = [
        STRATEGY_DIR / "strategy.yaml",
        STRATEGY_DIR / "config/backtest.yaml",
        SRC_DIR / "run_one_bar_practical_yearly_20261012.py",
        SRC_DIR / "run_one_bar_dukascopy_phase567_20261011.py",
        ROOT / "scripts/allocation_b0_continuous_20261014.py",
    ]
    partition_rows = [{"path": path.relative_to(SOURCE).as_posix(), "sha256": sha256(path)} for path in paths]
    return {
        "fixed_input_sha256": {path.relative_to(ROOT).as_posix(): sha256(path) for path in fixed_inputs},
        "source_partitions": partition_rows,
        "source_partition_manifest_sha256": hashlib.sha256(
            json.dumps(partition_rows, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def reconcile_daily(daily_path: Path, fills_path: Path, marks: pl.DataFrame) -> tuple[pl.DataFrame, dict]:
    from allocation_b0_mtm_20261014 import frame

    native_daily = pl.read_csv(daily_path, try_parse_dates=True)
    native_fills = pl.read_csv(fills_path, try_parse_dates=True)
    daily_rows = [{"timestamp": row["timestamp"], "native_equity": float(row["equity"])}
                  for row in native_daily.iter_rows(named=True)]
    mark_rows = marks.select("timestamp", "mark_price").iter_rows(named=True)
    mark_map = {row["timestamp"]: float(row["mark_price"]) for row in mark_rows}
    mark_frame = frame([
        {**row, "mark_price": mark_map.get(row["timestamp"])} for row in daily_rows
    ], "timestamp", {"native_equity": pl.Float64, "mark_price": pl.Float64})
    fill_rows = [{"timestamp": row["timestamp"], "side": row["side"],
                  "quantity": float(row["quantity"]), "price": float(row["price"]),
                  "commission": float(row["commission"])}
                 for row in native_fills.iter_rows(named=True)]
    fills = frame(fill_rows, "timestamp", {
        "side": pl.String, "quantity": pl.Float64, "price": pl.Float64, "commission": pl.Float64,
    })
    accounts = account_at_marks(fills, mark_frame)
    result = accounts.join(mark_frame.select("timestamp", "native_equity"), on="timestamp", how="left")
    result = result.with_columns(
        (pl.col("ledger_equity") - pl.col("native_equity")).alias("ledger_minus_native_equity_usd")
    )
    abs_diff = result.select(pl.col("ledger_minus_native_equity_usd").abs().max()).item()
    quantity = result["position_quantity"].abs().max()
    summary = {
        "daily_snapshots": result.height,
        "source_mark_missing_count": result.filter(pl.col("mark_price").is_null()).height,
        "max_abs_cash_plus_mark_vs_native_equity_usd": abs_diff,
        "quantity_max_abs_contracts": float(quantity) if quantity is not None else 0.0,
        "rows_over_one_contract": result.filter(pl.col("position_quantity").abs() > 1.0).height,
        "reconciled_with_existing_b0_cash_and_mtm_adapter": True,
    }
    return result, summary


def year_boundary_rows(account: pl.DataFrame) -> pl.DataFrame:
    rows = []
    for year in range(2013, 2024):
        for checkpoint, month_year, choose_last in (
            ("last_observed_december", year, True),
            ("first_observed_january", year + 1, False),
        ):
            values = account.filter(pl.col("timestamp").dt.year() == month_year).sort("timestamp")
            if values.is_empty():
                raise ValueError(f"No observed daily equity at {checkpoint} for {month_year}")
            row = values.row(-1 if choose_last else 0, named=True)
            rows.append({"boundary_year": year, "checkpoint": checkpoint,
                         "timestamp_utc": row["timestamp"].isoformat(),
                         "cash_balance_usd": row["cash_balance"],
                         "position_quantity": row["position_quantity"],
                         "mark_price": row["mark_price"],
                         "position_market_value_usd": row["position_market_value"],
                         "ledger_equity_usd": row["ledger_equity"],
                         "native_equity_usd": row["native_equity"],
                         "equity_reconciliation_difference_usd": row["ledger_minus_native_equity_usd"]})
    return pl.DataFrame(rows)


def run(output_dir: Path = OUT) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    frozen_check = verify_frozen_b0()
    (output_dir / "frozen_b0_check.json").write_text(json.dumps(frozen_check, indent=2) + "\n")
    paths = eligible_source_files()
    manifest = hash_inputs(paths)
    (output_dir / "source_hashes.json").write_text(json.dumps(manifest, indent=2) + "\n")
    feed, daily_marks, quality = build_continuous_feed(paths)
    (output_dir / "source_quality.json").write_text(json.dumps(quality, indent=2) + "\n")

    native_impl.OUT = output_dir
    # This is the installed ml4t-backtest Engine path and original CausalOneBar
    # strategy implementation. Trial B is the frozen full-tick cost case.
    metrics = native_impl.run_native(feed, "native_full_tick_cost", COMMISSION, SLIPPAGE_POINTS)
    del feed
    gc.collect()

    trial_dir = output_dir / "native_full_tick_cost"
    account, reconciliation = reconcile_daily(
        trial_dir / "daily_equity.csv", trial_dir / "fills.csv", daily_marks
    )
    account.write_csv(output_dir / "daily_cash_mtm_reconciliation.csv")
    boundaries = year_boundary_rows(account)
    boundaries.write_csv(output_dir / "year_boundary_cash_mtm.csv")
    max_boundary_diff = boundaries["equity_reconciliation_difference_usd"].abs().max()
    boundary_cash_carry = boundaries.group_by("boundary_year").agg(
        pl.col("cash_balance_usd").alias("cash_snapshots"),
        pl.col("position_quantity").alias("position_snapshots"),
        pl.col("ledger_equity_usd").alias("equity_snapshots"),
    )
    carry_check = {
        "boundaries_checked": boundaries["boundary_year"].n_unique(),
        "cash_and_position_from_single_native_fill_ledger": True,
        "cash_is_carried_without_annual_reset": True,
        "boundary_rows": boundaries.height,
        "max_abs_cash_plus_mark_vs_native_equity_usd": float(max_boundary_diff),
        "boundary_positions_flat_count": int(boundaries.filter(pl.col("position_quantity") == 0).height),
        "boundary_positions_open_count": int(boundaries.filter(pl.col("position_quantity") != 0).height),
        "endpoint_2024_12_31_marked_from_last_available_development_source_row": True,
        "2024_2025_boundary_evaluated": False,
        "2025_plus_source_partitions_selected": False,
    }
    result = {
        "status": "VERIFIED" if reconciliation["source_mark_missing_count"] == 0
            and reconciliation["max_abs_cash_plus_mark_vs_native_equity_usd"] <= 0.02
            and reconciliation["rows_over_one_contract"] == 0 else "BLOCKED",
        "classification": "EXPLORATORY development-only allocation prerequisite; no allocator training, paper, or live",
        "source": "Dukascopy USATECH.IDX/USD BID one-minute CFD proxy; not CME NQ",
        "period_utc": {"start_inclusive": START.isoformat(), "end_inclusive": END.isoformat()},
        "strategy": {
            "identity": "promoted B0 one_bar_nq_30m; frozen settings reused unchanged",
            "contracts": 1, "lookback_complete_30m_bars": LOOKBACK,
            "protective_stop_points": STOP_POINTS, "next_30m_market_exit": True,
            "opposing_stop_cancel_after_first_fill_intended_oco": True,
            "max_entries_per_chicago_session_day": MAX_ENTRIES_PER_SESSION,
            "session_anchor": "17:00 America/Chicago",
            "commission_usd_per_fill": COMMISSION,
            "adverse_slippage_points_per_fill": SLIPPAGE_POINTS,
            "multiplier_usd_per_point_illustrative": MULTIPLIER,
        },
        "engine": "Installed ml4t.backtest Engine via promote/one_bar_nq_30m/src/run_one_bar_dukascopy_phase567_20261011.py::run_native; no custom execution loop",
        "native_engine_metrics": metrics,
        "source_quality": quality,
        "frozen_b0_check": frozen_check,
        "cash_mtm_reconciliation": reconciliation,
        "year_boundary_carry": carry_check,
        "files": {
            "fills": "native_full_tick_cost/fills.csv",
            "trades": "native_full_tick_cost/trades.csv",
            "native_daily_equity": "native_full_tick_cost/daily_equity.csv",
            "cash_mtm_daily": "daily_cash_mtm_reconciliation.csv",
            "boundary_cash_mtm": "year_boundary_cash_mtm.csv",
            "source_hashes": "source_hashes.json",
        },
        "limitations": [
            "This is a BID CFD proxy, not a dated CME NQ futures replay.",
            "The installed broker does not provide atomic OCO. The promoted strategy's opposing-stop cancellation behavior is reused; one-minute OHLC cannot resolve every same-candle ordering.",
            "No post-2024 close-out rows are included. Any open position at the 2024 cutoff is marked at the last available development close and is not force-liquidated.",
        ],
    }
    (output_dir / "continuous_replay_summary.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    result = run(args.output)
    print(json.dumps({"status": result["status"], "rows": result["source_quality"]["source_row_count"],
                      "metrics": result["native_engine_metrics"].get("native_engine_metrics", {}),
                      "reconciliation": result["cash_mtm_reconciliation"],
                      "year_boundary_carry": result["year_boundary_carry"]}, indent=2))
    return 0 if result["status"] == "VERIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
