"""Frozen B0 cross-index native ML4T Engine replay on synthetic index units.

This is a RESEARCH signal transfer diagnostic, not executable futures PnL.
"""
from __future__ import annotations

import argparse
import gc
import json
import subprocess
import sys
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
from ml4t.backtest import Strategy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from audit_one_bar_b0_cross_indices_20261012 import STORE, scan_index
import run_one_bar_dukascopy_phase567_20261011 as native
import run_one_bar_practical_yearly_20261012 as prior

OUT = ROOT / "run_log/one_bar_b0_cross_indices_20261012"
CHICAGO = ZoneInfo("America/Chicago")
END_DATE = date(2026, 7, 14)
SYNTHETIC_MULTIPLIER = 20.0
SYNTHETIC_TICK = 0.25
CORE_STRATEGY = native.CausalOneBar
NAMES = ("ES", "DAX", "NIKKEI225")
TRIALS = (
    ("ZERO", "native_zero", 0.0, 0.0),
    ("COST", "native_costed_synthetic", 2.5, 0.25),
)
LABEL = "NQ_PROXY"


def store_paths(symbol: str, year: int) -> list[Path]:
    root = STORE / ("index_minute_" + symbol)
    paths = []
    for f in root.glob("year=*/month=*/data.parquet"):
        yr = int(f.parent.parent.name.split("=")[1])
        mo = int(f.parent.name.split("=")[1])
        if (yr == year or (yr == year - 1 and (mo >= 11 or (symbol == 'NIKKEI225' and year == 2014 and mo >= 7)))
            or (yr == year + 1 and mo == 1)) and (
                yr < 2026 or (yr == 2026 and mo <= 7)):
            paths.append(f)
    return sorted(paths)


def chicago_day(ts: datetime) -> date:
    return prior.chicago_session_day(ts)


def next_boundary(ts: datetime) -> datetime:
    return prior.next_30m_boundary(ts)


def build_feed(symbol: str, year: int) -> tuple[pl.DataFrame, dict]:
    paths = store_paths(symbol, year)
    if not paths:
        raise ValueError(f"No source partitions for {symbol} {year}")
    first = date(year, 1, 1) if year == 2013 else date(year, 1, 1) - timedelta(days=(180 if symbol == 'NIKKEI225' and year == 2014 else 60))
    last_eval = END_DATE if year == 2026 else date(year, 12, 31)
    last = min(END_DATE, last_eval + timedelta(days=7))
    raw = scan_index(paths).filter(
        pl.col("timestamp").dt.date().is_between(first, last)
    ).select("timestamp", "open", "high", "low", "close", "volume")
    if raw.is_empty():
        raise ValueError(f"No in-scope rows: {symbol}, {year}")
    local = pl.col("timestamp").dt.convert_time_zone("America/Chicago")
    raw = raw.with_columns(
        local.alias("local"),
        pl.when(local.dt.hour() >= 17).then(local.dt.date())
        .otherwise(local.dt.date().dt.offset_by("-1d")).alias("session_date"))
    sessions = raw["session_date"].unique().sort().to_list()
    starts = pl.DataFrame({
        "session_date": sessions,
        "start_utc": [
            datetime(d.year, d.month, d.day, 17, tzinfo=CHICAGO).astimezone(timezone.utc)
            for d in sessions],
    })
    frame = raw.join(starts, on="session_date", how="left").with_columns(
        ((pl.col("timestamp") - pl.col("start_utc")).dt.total_minutes() // 30)
        .cast(pl.Int32).alias("slot"))
    bars = (
        frame.group_by("session_date", "slot").agg(
            pl.col("timestamp").min().alias("first"),
            pl.col("timestamp").max().alias("last"),
            pl.col("high").max().alias("bar_high"),
            pl.col("low").min().alias("bar_low"),
            pl.len().alias("n"),
            pl.col("timestamp").n_unique().alias("unique_n"),
            pl.col("start_utc").first().alias("session_start"))
        .with_columns(
            (pl.col("session_start") +
             pl.duration(minutes=30) * pl.col("slot")).alias("bar_start"))
        .filter(
            (pl.col("n") == 30) &
            (pl.col("unique_n") == 30) &
            (pl.col("first") == pl.col("bar_start")) &
            (pl.col("last") == pl.col("bar_start") + pl.duration(minutes=29)))
        .sort("bar_start")
        .with_columns(
            pl.col("bar_high").rolling_max(50).alias("next_long_stop"),
            pl.col("bar_low").rolling_min(50).alias("next_short_stop"),
            ((pl.col("bar_high") - pl.col("bar_low")) / pl.col("bar_high")).alias("range_proxy"),
            (pl.col("bar_start") + pl.duration(minutes=30)).alias("available_at"))
        .filter(pl.col("next_long_stop").is_not_null()))
    levels = bars.select(
        (pl.col("available_at") - pl.duration(minutes=1)).alias("decision_at"),
        "next_long_stop", "next_short_stop", "range_proxy")
    feed = frame.sort("timestamp").join_asof(
        levels.sort("decision_at"), left_on="timestamp",
        right_on="decision_at", strategy="backward").with_columns(
        pl.lit(LABEL).alias("asset"))
    evaluation_rows = feed.filter(pl.col("session_date").dt.year() == year)
    eligible = evaluation_rows["timestamp"].min() if not evaluation_rows.is_empty() else None
    warm_count = int(bars.filter(pl.col("available_at") <= eligible).height) if eligible else 0
    if year > 2013 and warm_count < 50:
        raise ValueError(f"{symbol}-{year}: only {warm_count} causal warmup bars")
    quality = {
        "instrument": symbol, "year": year, "raw_minutes": raw.height,
        "retained_execution_minutes": feed.height, "complete_30m_bars": bars.height,
        "warmup_complete_30m_bars": warm_count,
        "missing_decision_levels_at_minute_count": feed["next_long_stop"].null_count(),
        "evaluation_session_minutes": evaluation_rows.height,
        "first": str(raw["timestamp"].min()), "last": str(raw["timestamp"].max()),
        "market_data": "index price / CFD proxy, not exchange dated futures",
        "assumed_UTC": True,
        "partial_execution_minutes_retained": True,
    }
    assert feed.height == raw.height
    return feed, quality


def run_year(symbol: str, year: int) -> dict:
    year_dir = OUT / "phase34" / symbol / str(year)
    year_dir.mkdir(parents=True, exist_ok=True)
    feed, quality = build_feed(symbol, year)
    (year_dir / "source_quality.json").write_text(json.dumps(quality, indent=2) + "\n")
    eval_end = END_DATE if year == 2026 else date(year, 12, 31)

    class FrozenB0Bounded(CORE_STRATEGY):
        def on_data(self, timestamp, data, context, broker):
            if chicago_day(timestamp) > eval_end:
                position = broker.get_position(LABEL)
                active = bool(position or self.trade or any(
                    order and order.status.value == "pending"
                    for order in self.entry_orders))
                if not active:
                    return
                item = dict(data[LABEL])
                item["signals"] = {}
                return super().on_data(timestamp, {**data, LABEL: item}, context, broker)
            return super().on_data(timestamp, data, context, broker)

    native.CausalOneBar = FrozenB0Bounded
    native.OUT = year_dir
    native.ASSET = LABEL
    native.MULTIPLIER = SYNTHETIC_MULTIPLIER
    native.NQ_TICK = SYNTHETIC_TICK
    native.STOP_POINTS = 50.0
    metrics = []
    for code, name, commission, slippage in TRIALS:
        print(f"NATIVE_START {symbol} {year} {name}", flush=True)
        native.run_native(feed, name, commission, slippage)
        path = year_dir / name
        trades = pl.read_csv(path / "trades.csv", try_parse_dates=True)
        fills = pl.read_csv(path / "fills.csv", try_parse_dates=True)
        if trades.height:
            trade_eval = trades.with_columns(
                pl.col("entry_time").map_elements(
                    chicago_day, return_dtype=pl.Date).alias("session_day"))
            trade_eval = trade_eval.filter(pl.col("session_day").dt.year() == year)
        else:
            trade_eval = trades
        trade_eval.write_csv(path / "evaluation_trades.csv")
        closed = trade_eval.filter(pl.col("status") == "closed")
        pnl = float(closed["pnl"].sum()) if closed.height else 0.0
        n = closed.height
        positive = float(closed.filter(pl.col("pnl") > 0)["pnl"].sum()) if n else 0.0
        negative = -float(closed.filter(pl.col("pnl") < 0)["pnl"].sum()) if n else 0.0
        entries = fills.filter(
            (pl.col("order_type") == "stop") & (pl.col("exit_reason") == ""))
        exits = fills.filter(
            (pl.col("order_type") == "stop") & (pl.col("exit_reason") == "signal"))
        if entries.height:
            day_count = (
                entries.with_columns(pl.col("timestamp").map_elements(
                    chicago_day, return_dtype=pl.Date).alias("day"))
                .filter(pl.col("day").dt.year() == year).group_by("day").len())
            max_day = int(day_count["len"].max()) if day_count.height else 0
            both_fills = int(entries.group_by("timestamp").len().filter(
                pl.col("len") > 1).height)
        else:
            max_day = both_fills = 0
        if max_day > 2:
            raise ValueError(f"{symbol}/{year}/{name}: >2 filled entries in Chicago session")
        result = {
            "instrument": symbol, "year": year, "trial": name, "status": "completed",
            "engine": "native ml4t.backtest.Engine",
            "closed_trades": n, "net_synthetic_accounting_usd": pnl,
            "net_index_points": pnl / SYNTHETIC_MULTIPLIER,
            "total_R": pnl / (50 * SYNTHETIC_MULTIPLIER),
            "mean_R_per_trade": pnl / (50 * SYNTHETIC_MULTIPLIER * n) if n else None,
            "win_rate": float((closed["pnl"] > 0).mean()) if n else None,
            "profit_factor": positive / negative if negative else None,
            "stop_exit_fills_including_warmup": exits.height,
            "same_timestamp_entry_conflicts": both_fills,
            "max_entry_fills_per_chicago_day": max_day,
            "illustrative_commission_per_synthetic_fill": commission,
            "adverse_slippage_index_points_per_fill": slippage,
            "non_executable_USD": True,
            "note": "Synthetic 20 USD/point for native engine; interpret only index points and R.",
        }
        (path / "evaluation_metrics.json").write_text(json.dumps(result, indent=2) + "\n")
        metrics.append(result)
        print(f"NATIVE_DONE {symbol} {year} {name} n={n} points={result['net_index_points']:.1f}", flush=True)
        gc.collect()
    return {"instrument": symbol, "year": year, "status": "completed", "quality": quality, "trials": metrics}


def batch(symbol: str) -> None:
    if symbol not in NAMES:
        raise ValueError(symbol)
    target = OUT / "phase34" / symbol
    target.mkdir(parents=True, exist_ok=True)
    results = []
    for year in range(2013, 2027):
        dst = target / str(year)
        summary = dst / "year_summary.json"
        if summary.exists() and json.loads(summary.read_text()).get("status") == "completed":
            print("SKIP_COMPLETE", symbol, year, flush=True)
        else:
            dst.mkdir(parents=True, exist_ok=True)
            command = [sys.executable, str(Path(__file__).resolve()), "--symbol", symbol,
                       "--year", str(year)]
            completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            (dst / "worker.log").write_text(completed.stdout + completed.stderr)
            if completed.returncode == 0:
                result = json.loads((dst / "worker_summary.json").read_text())
            else:
                result = {"instrument": symbol, "year": year, "status": "failed",
                          "exit_code": completed.returncode,
                          "error_tail": (completed.stderr or completed.stdout)[-2300:]}
            summary.write_text(json.dumps(result, indent=2) + "\n")
        results.append(json.loads(summary.read_text()))
        print("YEAR_STATE", symbol, year, results[-1]["status"], flush=True)
    done = [x for x in results if x["status"] == "completed"]
    summary = {
        "status": "completed" if len(done) == 14 else "partial_failed",
        "instrument": symbol, "completed_years": len(done), "expected": 14,
        "failure_years": [x["year"] for x in results if x["status"] != "completed"],
        "results": {
            name: {"closed_trades": sum(next(t for t in x["trials"] if t["trial"] == name)["closed_trades"] for x in done),
                   "index_points": sum(next(t for t in x["trials"] if t["trial"] == name)["net_index_points"] for x in done),
                   "ambiguities": sum(next(t for t in x["trials"] if t["trial"] == name)["same_timestamp_entry_conflicts"] for x in done)}
            for _, name, _, _ in TRIALS
        },
    }
    (target / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("BATCH_END", symbol, summary["status"], flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True, choices=NAMES)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--year", type=int)
    group.add_argument("--batch", action="store_true")
    a = parser.parse_args()
    if a.batch:
        batch(a.symbol)
    else:
        if not 2013 <= a.year <= 2026:
            raise ValueError("Year must be in scope")
        year_dir = OUT / "phase34" / a.symbol / str(a.year)
        year_dir.mkdir(parents=True, exist_ok=True)
        result = run_year(a.symbol, a.year)
        (year_dir / "worker_summary.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
