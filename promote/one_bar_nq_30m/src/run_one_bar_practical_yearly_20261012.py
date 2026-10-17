"""Run the frozen one-bar strategy in isolated annual ML4T Engine processes."""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
from ml4t.engineer import compute_features



ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "run_log/one_bar_practical_1m_20261012"
BASE = ROOT / "run_log/one_bar_dukascopy_2013_2026_20261011"
STORE = Path("/home/quant/dev/quant/ml4t-data/.data/store/index_minute_NQ")
ASSET = "NQ_PROXY"
TZ = ZoneInfo("America/Chicago")
FIRST_YEAR, LAST_YEAR = 2013, 2026
DATA_END = date(2026, 7, 14)
MULTIPLIER = 20.0
DONCHIAN_PERIOD = 50

sys.path.insert(0, str(ROOT / "scripts"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def eligible_years() -> list[int]:
    return list(range(FIRST_YEAR, LAST_YEAR + 1))


def chicago_session_day(ts: datetime) -> date:
    local = ts.astimezone(TZ)
    return local.date() if local.hour >= 17 else local.date() - timedelta(days=1)


def with_session_day(frame: pl.DataFrame) -> pl.DataFrame:
    local = pl.col("timestamp").dt.convert_time_zone("America/Chicago")
    return frame.with_columns(local.alias("local"),
        pl.when(local.dt.hour() >= 17).then(local.dt.date())
        .otherwise(local.dt.date().dt.offset_by("-1d")).alias("session_date"))


def source_files() -> list[Path]:
    return sorted(
        p for p in STORE.glob("year=*/month=*/data.parquet")
        if int(p.parent.parent.name.split("=")[1]) < 2026
        or (int(p.parent.parent.name.split("=")[1]) == 2026
            and int(p.parent.name.split("=")[1]) <= 7)
    )


def verify_source() -> dict:
    manifest_path = BASE / "source_manifest.json"
    frozen = json.loads((BASE / "frozen_spec.json").read_text())
    records = json.loads(manifest_path.read_text())
    paths = source_files()
    if sha256(manifest_path) != frozen["data"]["source_manifest_sha256"]:
        raise ValueError("Frozen source manifest hash mismatch")
    if len(paths) != frozen["data"]["partitions"] or len(paths) != len(records):
        raise ValueError("Frozen source partition count mismatch")
    checked_bytes = 0
    for path, row in zip(paths, records, strict=True):
        if path.relative_to(STORE).as_posix() != row["path"] or sha256(path) != row["sha256"]:
            raise ValueError(f"Frozen source partition mismatch: {path}")
        checked_bytes += path.stat().st_size
    return {"manifest": str(manifest_path.relative_to(ROOT)),
            "manifest_sha256": sha256(manifest_path), "partition_count": len(paths),
            "verified_bytes": checked_bytes, "protected_after": str(DATA_END),
            "all_partition_hashes_match": True}


def files_for_year(year: int) -> list[Path]:
    # December provides at least two full Chicago sessions of prior context.
    return [p for p in source_files()
            if (int(p.parent.parent.name.split("=")[1]) == year
                or (int(p.parent.parent.name.split("=")[1]) == year - 1
                    and int(p.parent.name.split("=")[1]) == 12)
                or (int(p.parent.parent.name.split("=")[1]) == year + 1
                    and int(p.parent.name.split("=")[1]) == 1))]


def add_breakout_features(bars: pl.DataFrame) -> pl.DataFrame:
    """Add ML4T Engineer's rolling Donchian upper/lower levels to 30m bars."""
    feature_input = bars.select(
        pl.col("bar_start").alias("timestamp"),
        pl.col("bar_open").alias("open"),
        pl.col("bar_high").alias("high"),
        pl.col("bar_low").alias("low"),
        pl.col("bar_close").alias("close"),
        pl.col("bar_volume").alias("volume"),
    )
    channels = compute_features(
        feature_input,
        [{"name": "donchian_channels", "params": {"period": DONCHIAN_PERIOD}}],
        timestamp_col="timestamp",
        assume_sorted=True,
    )
    if not isinstance(channels, pl.DataFrame):
        raise TypeError("ML4T Engineer must return a DataFrame for DataFrame input")

    levels = channels.select(
        pl.col("timestamp").alias("bar_start"),
        pl.col("donchian_channels_0").alias("next_long_stop"),
        pl.col("donchian_channels_1").alias("next_short_stop"),
    )
    return bars.join(levels, on="bar_start", how="left")


def build_year_feed(year: int) -> tuple[pl.DataFrame, dict]:
    """Build one year plus 14 days of warmup and up to 7 days of close-out."""
    from run_one_bar_dukascopy_phase567_20261011 import ASSET as _PHASE_ASSET

    if year == FIRST_YEAR:
        warm_start = date(year, 1, 1)
    else:
        warm_start = date(year, 1, 1) - timedelta(days=14)
    eval_end = DATA_END if year == LAST_YEAR else date(year, 12, 31)
    source_end = min(DATA_END, eval_end + timedelta(days=7))
    raw = (
        pl.scan_parquet([str(p) for p in files_for_year(year)])
        .filter(pl.col("timestamp").dt.date().is_between(warm_start, source_end))
        .select("timestamp", "open", "high", "low", "close", "volume")
        .sort("timestamp").collect()
        .with_columns(pl.col("timestamp").dt.replace_time_zone("UTC"))
    )
    if raw.is_empty():
        raise ValueError(f"No source rows for {year}")
    raw = with_session_day(raw)
    sessions = raw["session_date"].unique().sort().to_list()
    starts = pl.DataFrame({"session_date": sessions,
        "session_start_utc": [datetime(d.year, d.month, d.day, 17, tzinfo=TZ)
            .astimezone(timezone.utc) for d in sessions]})
    source = raw.join(starts, on="session_date", how="left").with_columns(
        ((pl.col("timestamp") - pl.col("session_start_utc")).dt.total_minutes() // 30).alias("bar_no"))
    bars = (source.group_by("session_date", "bar_no").agg(
        pl.col("timestamp").min().alias("bar_start"),
        pl.col("open").first().alias("bar_open"),
        pl.col("high").max().alias("bar_high"),
        pl.col("low").min().alias("bar_low"),
        pl.col("close").last().alias("bar_close"),
        pl.col("volume").sum().alias("bar_volume"),
        pl.len().alias("n"), pl.col("timestamp").n_unique().alias("unique_n"))
        .filter((pl.col("n") == 30) & (pl.col("unique_n") == 30)).sort("bar_start"))
    bars = add_breakout_features(bars).with_columns(
        ((pl.col("bar_high") - pl.col("bar_low")) / pl.col("bar_high")).alias("range_proxy"),
        (pl.col("bar_start") + pl.duration(minutes=30)).alias("available_at"))
    bars = bars.filter(pl.col("next_long_stop").is_not_null())

    levels = bars.select(
        (pl.col("available_at") - pl.duration(minutes=1)).alias("release_decision_at"),
        "next_long_stop", "next_short_stop", "range_proxy")
    feed = (source.sort("timestamp").join_asof(levels.sort("release_decision_at"),
        left_on="timestamp", right_on="release_decision_at", strategy="backward")
        .with_columns(pl.lit(_PHASE_ASSET).alias("asset")))
    eval_start_rows = feed.filter(pl.col("session_date") >= date(year, 1, 1))
    eligible_start = eval_start_rows["timestamp"].min() if eval_start_rows.height else None
    warmup_bars = bars.filter(pl.col("available_at") <= eligible_start).height if eligible_start else 0
    if year > FIRST_YEAR and warmup_bars < 80:
        raise ValueError(f"{year} has only {warmup_bars} complete warmup bars; need at least 80")
    quality = {
        "year": year, "warmup_start_utc_date": str(warm_start),
        "evaluation_session_start": str(date(year, 1, 1)),
        "evaluation_session_end": str(eval_end), "source_timestamp_end": str(source_end),
        "eligible_start_timestamp": str(eligible_start), "warmup_complete_30m_bars": warmup_bars,
        "raw_source_rows": raw.height, "execution_rows_retained": feed.height,
        "evaluation_session_rows": feed.filter((pl.col("session_date").dt.year() == year)
            & (pl.col("session_date") <= eval_end)).height,
        "complete_30m_bars": bars.height,
        "incomplete_30m_bins": int(source.select(pl.struct("session_date", "bar_no").n_unique()).item()) - bars.height,
        "source_duplicate_timestamps": raw.height - raw["timestamp"].n_unique(),
        "null_ohlc": sum(raw[c].null_count() for c in ("open", "high", "low", "close")),
        "invalid_ohlc": raw.filter((pl.col("high") < pl.col("low")) |
            (pl.col("close") > pl.col("high")) | (pl.col("close") < pl.col("low"))).height,
        "first_timestamp": str(raw["timestamp"].min()), "last_timestamp": str(raw["timestamp"].max()),
        "level_release": "complete 30m levels become available on the final minute; native order fills on the next source bar",
        "partial_30m_execution_rows_preserved": True,
    }
    if quality["source_duplicate_timestamps"] or quality["null_ohlc"] or quality["invalid_ohlc"]:
        raise ValueError(f"Source quality failed for {year}: {quality}")
    return feed, quality


def _entry_year(ts: datetime) -> int:
    return chicago_session_day(ts).year


def next_30m_boundary(ts: datetime) -> datetime:
    return datetime.fromtimestamp((int(ts.timestamp()) // 1800 + 1) * 1800, timezone.utc)


def ambiguous_loss_bound(net_pnl: float, event_kinds: list[str], commission: float,
                         slippage_points: float, multiplier: float = MULTIPLIER) -> float:
    contracts_per_event = [2 if kind == "both_entry_stops_filled" else 1 for kind in event_kinds]
    penalty = sum(count * 1000.0 + 2 * count * commission
                  + 2 * count * slippage_points * multiplier for count in contracts_per_event)
    return net_pnl - penalty


def calendar_bin_parity() -> dict:
    """Check that the former Int8 hour arithmetic did not move any 30m bin."""
    paths = source_files()
    base = (pl.scan_parquet([str(p) for p in paths])
        .filter(pl.col("timestamp").dt.date().is_between(date(2013, 1, 1), DATA_END))
        .select(pl.col("timestamp").dt.replace_time_zone("UTC").alias("timestamp"))
        .with_columns(pl.col("timestamp").dt.convert_time_zone("America/Chicago").alias("local")))
    dates = base.select(pl.col("local").dt.date().unique()).collect().to_series().to_list()
    session_dates = sorted({d for day in dates for d in (day, day - timedelta(days=1))})
    starts = pl.DataFrame({"session_date": session_dates,
        "session_start_utc": [datetime(d.year, d.month, d.day, 17, tzinfo=TZ).astimezone(timezone.utc)
                              for d in session_dates]})
    local = pl.col("local")
    old_minute_of_day = local.dt.hour() * 60 + local.dt.minute()
    rows = (base.with_columns(
            pl.when(local.dt.hour() >= 17).then(local.dt.date())
            .otherwise(local.dt.date().dt.offset_by("-1d")).alias("correct_date"),
            pl.when(old_minute_of_day >= 17 * 60).then(local.dt.date())
            .otherwise(local.dt.date().dt.offset_by("-1d")).alias("former_date"))
        .join(starts.lazy().rename({"session_date": "correct_date", "session_start_utc": "correct_start"}),
              on="correct_date", how="left")
        .join(starts.lazy().rename({"session_date": "former_date", "session_start_utc": "former_start"}),
              on="former_date", how="left")
        .with_columns(
            ((pl.col("timestamp") - pl.col("correct_start")).dt.total_minutes() // 30).alias("correct_no"),
            ((pl.col("timestamp") - pl.col("former_start")).dt.total_minutes() // 30).alias("former_no"))
        .with_columns(
            (pl.col("correct_start") + pl.duration(minutes=30) * pl.col("correct_no")).alias("correct_bar_start"),
            (pl.col("former_start") + pl.duration(minutes=30) * pl.col("former_no")).alias("former_bar_start"))
        .select("timestamp", "correct_bar_start", "former_bar_start")
        .filter(pl.col("correct_bar_start") != pl.col("former_bar_start"))
        .collect(engine="streaming"))
    return {"checked_source_rows": int(base.select(pl.len()).collect().item()),
        "former_vs_correct_30m_bin_mismatches": rows.height,
        "mismatch_examples": rows.head(20).to_dicts(),
        "former_expression": "Polars Int8 hour * 60 + minute >= 1020",
        "impact_if_zero": "All source minutes remain in the same absolute 30m bins; rolling levels and native trades are unchanged. Only the session-date label was wrong."}


def run_year(year: int) -> dict:
    import run_one_bar_dukascopy_phase567_20261011 as phase
    from ml4t.backtest.analytics import max_drawdown, sharpe_ratio

    year_dir = OUT / "by_year" / str(year)
    year_dir.mkdir(parents=True, exist_ok=True)
    feed, quality = build_year_feed(year)
    (year_dir / "source_quality.json").write_text(json.dumps(quality, indent=2) + "\n")
    eval_end = DATA_END if year == LAST_YEAR else date(year, 12, 31)

    class BoundedWarmupStrategy(phase.CausalOneBar):
        def on_data(self, timestamp, data, context, broker):
            # Replay prior sessions to reconstruct live strategy state. After
            # the evaluation end, process active orders only and suppress entries.
            if chicago_session_day(timestamp) > eval_end:
                position = broker.get_position(ASSET)
                active = bool(position or self.trade or any(
                    order and order.status.value == "pending" for order in self.entry_orders))
                if not active:
                    return
                item = dict(data[ASSET])
                item["signals"] = {}
                return super().on_data(timestamp, {**data, ASSET: item}, context, broker)
            return super().on_data(timestamp, data, context, broker)

    state: dict = {}
    def strategy_factory():
        state["strategy"] = BoundedWarmupStrategy()
        return state["strategy"]

    phase.CausalOneBar = strategy_factory
    phase.OUT = year_dir
    trials = []
    for code, name, commission, slippage in (
        ("A", "native_zero_cost", 0.0, 0.0),
        ("B", "native_full_tick_cost", 2.5, 0.25),
    ):
        print(f"YEAR={year} ENGINE_START {name} {datetime.now(timezone.utc).isoformat()}", flush=True)
        phase.run_native(feed, name, commission, slippage)
        trial_dir = year_dir / name
        trades = pl.read_csv(trial_dir / "trades.csv", try_parse_dates=True)
        fills = pl.read_csv(trial_dir / "fills.csv", try_parse_dates=True)
        native_metrics = json.loads((trial_dir / "metrics.json").read_text())
        if trades.height:
            eval_trades = trades.with_columns(pl.col("entry_time").map_elements(
                _entry_year, return_dtype=pl.Int32).alias("entry_session_year"))
            eval_trades = eval_trades.filter(pl.col("entry_session_year") == year)
            eval_trades.write_csv(trial_dir / "evaluation_trades.csv")
        else:
            eval_trades = trades.with_columns(pl.lit(None, dtype=pl.Int32).alias("entry_session_year"))
            eval_trades.write_csv(trial_dir / "evaluation_trades.csv")
        annual_pnl = float(eval_trades.filter(pl.col("status") == "closed")["pnl"].sum() or 0.0)
        annual_closed = eval_trades.filter(pl.col("status") == "closed")
        entry_fills = fills.filter((pl.col("order_type") == "stop") & (pl.col("exit_reason") == ""))
        if entry_fills.height:
            entry_fills = entry_fills.with_columns(pl.col("timestamp").map_elements(
                chicago_session_day, return_dtype=pl.Date).alias("entry_session_day"))
            evaluation_entries = entry_fills.filter(pl.col("entry_session_day").dt.year() == year)
            entries_per_day = evaluation_entries.group_by("entry_session_day").len()
            daily_entry_max = int(entries_per_day["len"].max()) if entries_per_day.height else 0
            dual_fill_times = evaluation_entries.group_by("timestamp").len().filter(
                pl.col("len") > 1)["timestamp"].to_list()
        else:
            daily_entry_max, dual_fill_times = 0, []
        dailies = pl.read_csv(trial_dir / "daily_equity.csv", try_parse_dates=True).sort("timestamp")
        if dailies.height:
            dailies = dailies.with_columns(pl.col("equity").shift(1).fill_null(1_000_000.0).alias("prior_equity"))
            dailies = dailies.with_columns((pl.col("equity") / pl.col("prior_equity") - 1).alias("daily_return"))
            # Annual risk metrics use the native Engine equity series for UTC calendar dates.
            annual_days = dailies.filter(pl.col("timestamp").dt.year() == year)
            daily_returns = annual_days["daily_return"].to_list()
            equity_values = annual_days["equity"].to_list()
            annual_sharpe = sharpe_ratio(daily_returns, annualize=True) if daily_returns else None
            annual_dd = max_drawdown(equity_values)[0] if equity_values else None
        else:
            annual_sharpe = annual_dd = None
        # All native warmup fills stay in fills.csv. Evaluation files use trades
        # opened in the target Chicago session year.
        ambiguous = state["strategy"].ambiguous
        event_kinds = {}
        for row in ambiguous:
            timestamp = datetime.fromisoformat(row["timestamp"])
            if _entry_year(timestamp) == year:
                event_kinds[timestamp] = row.get("kind", "inconclusive")
        for timestamp in dual_fill_times:
            event_kinds[timestamp] = "both_entry_stops_filled"
        event_kinds = {ts: event_kinds[ts] for ts in sorted(event_kinds)}
        ambiguous_times = [ts.isoformat() for ts in event_kinds]
        base_metrics = native_metrics
        year_metrics = {
            "trial_id": code, "name": name, "status": "completed",
            "closed_trades": annual_closed.height, "open_evaluation_trades": eval_trades.filter(
                pl.col("status") != "closed").height,
            "net_pnl_usd": annual_pnl,
            "average_trade_pnl_usd": float(annual_closed["pnl"].mean()) if annual_closed.height else None,
            "native_daily_equity_sharpe_utc": annual_sharpe,
            "native_daily_equity_max_drawdown_utc": annual_dd,
            "native_engine_final_value_including_warmup": base_metrics.get("native_engine_metrics", {}).get("final_value"),
            "all_native_engine_closed_trades_including_warmup": base_metrics.get("closed_trades"),
            "same_minute_ambiguity_examples": ambiguous_times,
            "ending_native_open_trades": base_metrics.get("open_trades_at_end"),
            "max_entries_per_chicago_session_day": daily_entry_max,
            "simultaneous_opposing_stop_fill_events": len(dual_fill_times),
            "commission_per_fill_usd": commission, "adverse_slippage_points_per_fill": slippage,
        }
        if name == "native_full_tick_cost":
            # One adverse event replacement per ambiguous event. This is a
            # separate bound, not an ML4T Engine replay.
            year_metrics["conservative_ambiguous_bound_usd"] = ambiguous_loss_bound(
                annual_pnl, list(event_kinds.values()), commission, slippage)
        (trial_dir / "evaluation_metrics.json").write_text(json.dumps(year_metrics, indent=2) + "\n")
        trials.append(year_metrics)
        if name == "native_full_tick_cost":
            ambiguity_path = year_dir / "ambiguity_report.json"
            ambiguity_path.write_text(json.dumps({"year": year,
                "events": [{"timestamp": ts.isoformat(), "kind": kind,
                            "classification": "INCONCLUSIVE_SAME_MINUTE_OHLC"}
                           for ts, kind in event_kinds.items()],
                "native_engine_fills_retained": True,
                "conservative_bound_is_non_native": True}, indent=2) + "\n")
        print(f"YEAR={year} ENGINE_DONE {name} trades={annual_closed.height} pnl={annual_pnl:.2f}", flush=True)
        del trades, fills, dailies, eval_trades, annual_closed
        gc.collect()
    del feed
    return {"year": year, "status": "completed", "quality": quality, "trials": trials,
            "ending_strategy_state": {
                "open_entry_orders": sum(bool(o and o.status.value == "pending") for o in state["strategy"].entry_orders),
                "open_protective_order": bool(state["strategy"].stop_order and state["strategy"].stop_order.status.value == "pending"),
                "tracked_trade": state["strategy"].trade is not None,
            }}


def run_batch() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_status = verify_source()
    (OUT / "validation").mkdir(exist_ok=True)
    (OUT / "validation/source_manifest_audit.json").write_text(json.dumps(manifest_status, indent=2) + "\n")
    ledger_path = OUT / "trial_ledger.json"
    prior = json.loads(ledger_path.read_text()) if ledger_path.exists() else {"attempts": []}
    attempts = prior.setdefault("attempts", [])
    recovery = {"trial_id": "RESHARD-ANNUAL-20261012", "strategy": "unchanged 50-bar one-bar breakout",
        "source_manifest_sha256": manifest_status["manifest_sha256"], "engine": "native ml4t.backtest Engine",
        "status": "RUNNING", "years": []}
    attempts.append(recovery)
    prior["status"] = "RUNNING"
    ledger_path.write_text(json.dumps(prior, indent=2) + "\n")
    for year in eligible_years():
        year_dir = OUT / "by_year" / str(year)
        result_path = year_dir / "year_summary.json"
        if result_path.exists() and json.loads(result_path.read_text()).get("status") == "completed":
            result = json.loads(result_path.read_text())
            print(f"YEAR={year} SKIP durable completed summary", flush=True)
        else:
            env = os.environ.copy()
            env["UV_CACHE_DIR"] = "/tmp/uv-cache"
            cmd = [sys.executable, str(Path(__file__).resolve()), "--year", str(year)]
            proc = subprocess.run(cmd, cwd=ROOT, env=env, text=True, capture_output=True)
            log_path = year_dir / "worker.log"
            year_dir.mkdir(parents=True, exist_ok=True)
            log_path.write_text(proc.stdout + proc.stderr)
            if proc.returncode:
                result = {"year": year, "status": "failed", "exit_code": proc.returncode,
                          "log": str(log_path.relative_to(ROOT))}
                (year_dir / "year_summary.json").write_text(json.dumps(result, indent=2) + "\n")
                recovery["years"].append(result)
                ledger_path.write_text(json.dumps(prior, indent=2) + "\n")
                print(f"YEAR={year} FAILED rc={proc.returncode}; continuing", flush=True)
                continue
            result = json.loads((year_dir / "worker_summary.json").read_text())
            (year_dir / "year_summary.json").write_text(json.dumps(result, indent=2) + "\n")
        recovery["years"] = [x for x in recovery["years"] if x.get("year") != year] + [result]
        ledger_path.write_text(json.dumps(prior, indent=2) + "\n")
    recovery["status"] = "completed" if all(x["status"] == "completed" for x in recovery["years"]) else "partial_failed"
    prior["status"] = recovery["status"]
    ledger_path.write_text(json.dumps(prior, indent=2) + "\n")
    write_final(recovery, manifest_status)


def write_final(recovery: dict, manifest_status: dict) -> None:
    rows = []
    for item in recovery["years"]:
        for trial in item.get("trials", []):
            rows.append({"year": item["year"], **trial})
    completed = [row for row in rows if row["status"] == "completed"]
    summary = {}
    for name in ("native_zero_cost", "native_full_tick_cost"):
        selected = [x for x in completed if x["name"] == name]
        pnl = sum(x["net_pnl_usd"] for x in selected)
        count = sum(x["closed_trades"] for x in selected)
        summary[name] = {"closed_trades": count, "net_pnl_usd": pnl,
            "average_trade_pnl_usd": pnl / count if count else None,
            "conservative_ambiguous_bound_usd": sum(x.get("conservative_ambiguous_bound_usd", x["net_pnl_usd"]) for x in selected)
                if name == "native_full_tick_cost" else None,
            "annual_results": [{k: x.get(k) for k in ("year", "closed_trades", "net_pnl_usd",
                "average_trade_pnl_usd", "native_daily_equity_sharpe_utc",
                "native_daily_equity_max_drawdown_utc", "conservative_ambiguous_bound_usd")} for x in selected]}
    failed = [x for x in recovery["years"] if x["status"] != "completed"]
    final = {"status": recovery["status"], "classification": "EXPLORATORY retrospective; not approval",
        "source": "Dukascopy USATECH.IDX/USD BID index CFD proxy; not CME NQ futures",
        "period": {"start": "2013-01-01", "end": str(DATA_END), "years_expected": eligible_years(),
                   "years_completed": [x["year"] for x in recovery["years"] if x["status"] == "completed"],
                   "failed_years": failed}, "source_audit": manifest_status,
        "trial_results": summary, "annual_trade_results": rows,
        "manager_reference_usd_per_trade": {"value": 41, "comparison": "descriptive only"},
        "full_period_sharpe": None,
        "full_period_sharpe_reason": "Annual Engine processes reset cash. Annual daily Sharpe values are native Engine equity metrics; a continuous account path is not established.",
        "limitations": ["NQ-equivalent multiplier and tick are illustrative for a BID CFD proxy.",
            "1-minute OHLC cannot establish intraminute event order.",
            "Installed native broker has no atomic OCO. Ambiguity bounds are diagnostic, not native replays.",
            "Warmup state is reconstructed by native strategy replay, and yearly accounts reset to $1,000,000.",
            "No protected out-of-sample period is present."],
        "attempt_id": recovery["trial_id"]}
    (OUT / "final_report.json").write_text(json.dumps(final, indent=2, default=str) + "\n")
    (OUT / "yearly_summary.json").write_text(json.dumps({"trials": summary}, indent=2, default=str) + "\n")
    (OUT / "manifest.json").write_text(json.dumps({"attempt_id": recovery["trial_id"],
        "source_manifest_sha256": manifest_status["manifest_sha256"],
        "year_summary_hashes": {str(x["year"]): sha256(OUT / "by_year" / str(x["year"]) / "year_summary.json")
            for x in recovery["years"] if (OUT / "by_year" / str(x["year"]) / "year_summary.json").exists()}}, indent=2) + "\n")


def audit_completed() -> dict:
    """Reconcile yearly engine artifacts without changing or simulating fills."""
    from ml4t.backtest.analytics import max_drawdown, sharpe_ratio

    audit = {"status": "passed", "years": [], "boundary_overlaps": [], "errors": []}
    bin_parity = calendar_bin_parity()
    (OUT / "validation/calendar_bin_parity.json").write_text(json.dumps(bin_parity, indent=2) + "\n")
    if bin_parity["former_vs_correct_30m_bin_mismatches"]:
        audit["errors"].append("Former session-date overflow moved one or more 30-minute bins")
    paths = source_files()
    raw_source = (pl.scan_parquet([str(p) for p in paths])
        .filter(pl.col("timestamp").dt.date().is_between(date(2013, 1, 1), DATA_END))
        .select(pl.col("timestamp").dt.replace_time_zone("UTC").alias("timestamp"))
        .with_columns(pl.col("timestamp").dt.convert_time_zone("America/Chicago").alias("local"))
        .with_columns(pl.when(pl.col("local").dt.hour() >= 17).then(pl.col("local").dt.date())
            .otherwise(pl.col("local").dt.date().dt.offset_by("-1d")).alias("session_date"))
        .group_by(pl.col("session_date").dt.year().alias("session_year"))
        .agg(pl.len().alias("source_rows"),
            pl.col("timestamp").filter(pl.col("session_date") <= DATA_END).len().alias("evaluation_rows"))
        .collect(engine="streaming"))
    expected_rows = {int(row["session_year"]): int(row["source_rows"]) for row in raw_source.to_dicts()}
    expected_evaluation_rows = {int(row["session_year"]): int(row["evaluation_rows"])
                                for row in raw_source.to_dicts()}
    coverage = {"timestamp_date_filter": ["2013-01-01", str(DATA_END)],
        "source_rows": sum(expected_rows.values()), "rows_by_chicago_session_year": expected_rows,
        "evaluation_rows_by_chicago_session_year": expected_evaluation_rows,
        "annual_feed_matches": {}, "calendar_bin_parity": bin_parity}
    old_quality_path = OUT / "validation/source_quality.json"
    if old_quality_path.exists():
        old_quality = json.loads(old_quality_path.read_text())
        if coverage["source_rows"] != old_quality["source_rows"]:
            audit["errors"].append("Full source row count differs from the frozen pre-engine source audit")
    for year in eligible_years():
        annual_feed, _ = build_year_feed(year)
        actual = annual_feed.filter(pl.col("session_date").dt.year() == year).height
        eval_end = DATA_END if year == LAST_YEAR else date(year, 12, 31)
        actual_eval = annual_feed.filter((pl.col("session_date").dt.year() == year)
            & (pl.col("session_date") <= eval_end)).height
        expected = expected_rows.get(year, 0)
        expected_eval = expected_evaluation_rows.get(year, 0)
        coverage["annual_feed_matches"][str(year)] = {"expected_source_rows": expected,
            "annual_feed_rows": actual, "full_session_year_matches": expected == actual,
            "expected_evaluation_rows": expected_eval, "evaluation_feed_rows": actual_eval,
            "evaluation_period_matches": expected_eval == actual_eval}
        if actual != expected or actual_eval != expected_eval:
            audit["errors"].append(f"{year}: annual feed does not cover all source session rows")
        del annual_feed
        import gc
        gc.collect()
    (OUT / "validation/source_coverage.json").write_text(json.dumps(coverage, indent=2) + "\n")
    for year in eligible_years():
        year_dir = OUT / "by_year" / str(year)
        summary_path = year_dir / "year_summary.json"
        if not summary_path.exists():
            audit["errors"].append(f"{year}: summary missing")
            continue
        summary = json.loads(summary_path.read_text())
        if summary.get("status") != "completed":
            audit["errors"].append(f"{year}: worker status {summary.get('status')}")
            continue
        year_checks = {"year": year, "status": "passed", "trials": []}
        for trial in summary["trials"]:
            name = trial["name"]
            path = year_dir / name
            closed = pl.read_csv(path / "evaluation_trades.csv", try_parse_dates=True).filter(
                pl.col("status") == "closed")
            trades = pl.read_csv(path / "trades.csv", try_parse_dates=True)
            fills = pl.read_csv(path / "fills.csv", try_parse_dates=True)
            dailies = pl.read_csv(path / "daily_equity.csv", try_parse_dates=True).sort("timestamp")
            dailies = dailies.with_columns(pl.col("equity").shift(1).fill_null(1_000_000.0).alias("prior_equity"))
            dailies = dailies.with_columns((pl.col("equity") / pl.col("prior_equity") - 1).alias("daily_return"))
            annual_days = dailies.filter(pl.col("timestamp").dt.year() == year)
            prior_days = dailies.filter(pl.col("timestamp").dt.year() < year)
            annual_returns = annual_days["daily_return"].to_list()
            annual_equity = annual_days["equity"].to_list()
            opening_equity = float(prior_days["equity"][-1]) if prior_days.height else 1_000_000.0
            annual_sharpe = sharpe_ratio(annual_returns, annualize=True) if annual_returns else None
            annual_max_dd = max_drawdown([opening_equity, *annual_equity])[0] if annual_equity else None
            ending_equity = float(annual_equity[-1]) if annual_equity else None
            equity_change = ending_equity - opening_equity if ending_equity is not None else None
            pnl = float(closed["pnl"].sum() or 0.0)
            gross_pnl = float(closed["gross_pnl"].sum() or 0.0)
            trade_fees = float(closed["fees"].sum() or 0.0)
            trade_slippage = float(closed["total_slippage_cost"].sum() or 0.0)
            protective_times = fills.filter((pl.col("order_type") == "stop")
                & (pl.col("exit_reason") == "signal"))["timestamp"].to_list()
            if closed.height:
                exit_check = closed.with_columns(
                    pl.col("entry_time").map_elements(next_30m_boundary,
                        return_dtype=pl.Datetime("us", "UTC")).alias("expected_exit_time"),
                    pl.col("exit_time").is_in(protective_times).alias("protective_stop_exit"))
                scheduled_exit_mismatches = exit_check.filter(
                    ~pl.col("protective_stop_exit") &
                    (pl.col("exit_time") != pl.col("expected_exit_time"))).height
            else:
                scheduled_exit_mismatches = 0
            entry_fills = fills.filter((pl.col("order_type") == "stop") & (pl.col("exit_reason") == ""))
            if entry_fills.height:
                entry_fills = entry_fills.with_columns(pl.col("timestamp").map_elements(
                    chicago_session_day, return_dtype=pl.Date).alias("session_day"))
                entry_fills = entry_fills.filter(pl.col("session_day").dt.year() == year)
                counts = entry_fills.group_by("session_day").len()
                max_daily = int(counts["len"].max()) if counts.height else 0
                opposing_rows = entry_fills.group_by("timestamp").len().filter(pl.col("len") > 1)
                opposing = opposing_rows.height
                opposing_times = opposing_rows["timestamp"].to_list()
            else:
                max_daily = opposing = 0
                opposing_times = []
            summary_pnl = float(trial["net_pnl_usd"])
            if abs(pnl - summary_pnl) > 1e-6:
                audit["errors"].append(f"{year}/{name}: evaluation trade PnL does not reconcile")
            if max_daily > 2:
                audit["errors"].append(f"{year}/{name}: max daily entries {max_daily} exceeds 2")
            if trial["ending_native_open_trades"] != 0:
                audit["errors"].append(f"{year}/{name}: native Engine ended with open trades")
            if trial["open_evaluation_trades"] != 0:
                audit["errors"].append(f"{year}/{name}: evaluation trade remained open")
            year_checks["trials"].append({"name": name, "closed_trade_count": closed.height,
                "trade_pnl_usd": pnl, "summary_pnl_usd": summary_pnl,
                "gross_minus_net_pnl_usd": gross_pnl - pnl,
                "recorded_commission_usd": trade_fees,
                "recorded_slippage_cost_usd": trade_slippage,
                "scheduled_next_boundary_exit_mismatches": scheduled_exit_mismatches,
                "max_entries_per_chicago_session_day": max_daily,
                "simultaneous_opposing_stop_fill_events": opposing,
                "ending_open_trades": trial["ending_native_open_trades"]})
            if name == "native_full_tick_cost":
                native = json.loads((path / "metrics.json").read_text())
                event_kinds = {}
                for row in native.get("ambiguous_examples", []):
                    ts = datetime.fromisoformat(row["timestamp"])
                    if _entry_year(ts) == year:
                        event_kinds[ts] = row.get("kind", "inconclusive")
                for ts in opposing_times:
                    event_kinds[ts] = "both_entry_stops_filled"
                event_kinds = {ts: event_kinds[ts] for ts in sorted(event_kinds)}
                bound = ambiguous_loss_bound(pnl, list(event_kinds.values()), 2.5, 0.25)
                trial["ambiguous_event_count"] = len(event_kinds)
                trial["ambiguous_event_kinds"] = dict(__import__("collections").Counter(event_kinds.values()))
                trial["conservative_ambiguous_bound_usd"] = bound
            trial["native_daily_equity_sharpe_utc"] = annual_sharpe
            trial["native_daily_equity_max_drawdown_utc"] = annual_max_dd
            trial["evaluation_start_equity_usd"] = opening_equity if annual_equity else None
            trial["evaluation_end_equity_usd"] = ending_equity
            trial["evaluation_equity_change_usd"] = equity_change
            trial["initial_margin_per_contract_usd"] = 25_000
            trial["maintenance_margin_per_contract_usd"] = 20_000
            trial["scheduled_next_boundary_exit_mismatches"] = scheduled_exit_mismatches
            evaluation_metrics = json.loads((path / "evaluation_metrics.json").read_text())
            evaluation_metrics["native_daily_equity_sharpe_utc"] = annual_sharpe
            evaluation_metrics["native_daily_equity_max_drawdown_utc"] = annual_max_dd
            evaluation_metrics["evaluation_start_equity_usd"] = trial["evaluation_start_equity_usd"]
            evaluation_metrics["evaluation_end_equity_usd"] = ending_equity
            evaluation_metrics["evaluation_equity_change_usd"] = equity_change
            evaluation_metrics["initial_margin_per_contract_usd"] = 25_000
            evaluation_metrics["maintenance_margin_per_contract_usd"] = 20_000
            evaluation_metrics["scheduled_next_boundary_exit_mismatches"] = scheduled_exit_mismatches
            if name == "native_full_tick_cost":
                evaluation_metrics["ambiguous_event_count"] = len(event_kinds)
                evaluation_metrics["ambiguous_event_kinds"] = trial["ambiguous_event_kinds"]
                evaluation_metrics["same_minute_ambiguity_examples"] = [ts.isoformat() for ts in event_kinds]
                evaluation_metrics["conservative_ambiguous_bound_usd"] = bound
                (year_dir / "ambiguity_report.json").write_text(json.dumps({"year": year,
                    "events": [{"timestamp": ts.isoformat(), "kind": kind,
                        "classification": "INCONCLUSIVE_SAME_MINUTE_OHLC"}
                        for ts, kind in event_kinds.items()],
                    "native_engine_fills_retained": True,
                    "conservative_bound_is_non_native": True}, indent=2) + "\n")
            (path / "evaluation_metrics.json").write_text(json.dumps(evaluation_metrics, indent=2) + "\n")
        zero = next(x for x in summary["trials"] if x["name"] == "native_zero_cost")
        cost = next(x for x in summary["trials"] if x["name"] == "native_full_tick_cost")
        observed_drag = zero["net_pnl_usd"] - cost["net_pnl_usd"]
        year_checks["zero_to_full_tick_pnl_change_usd"] = observed_drag
        cost_audit = next(x for x in year_checks["trials"] if x["name"] == "native_full_tick_cost")
        if abs(cost_audit["gross_minus_net_pnl_usd"] - cost_audit["recorded_commission_usd"]) > 1e-6:
            audit["errors"].append(f"{year}: cost-run trade PnL does not reconcile to recorded commission")
        if year > FIRST_YEAR and summary["quality"]["warmup_complete_30m_bars"] < 80:
            audit["errors"].append(f"{year}: warmup has fewer than 80 complete bars")
        summary_path.write_text(json.dumps(summary, indent=2) + "\n")
        audit["years"].append(year_checks)

    # Compare the final two warmup weeks across adjacent Engine shards. This
    # checks that New Year positions and fills reconstruct from native history.
    for year in range(FIRST_YEAR, LAST_YEAR):
        left = OUT / "by_year" / str(year)
        right = OUT / "by_year" / str(year + 1)
        for name in ("native_zero_cost", "native_full_tick_cost"):
            left_trades = pl.read_csv(left / name / "trades.csv", try_parse_dates=True)
            right_trades = pl.read_csv(right / name / "trades.csv", try_parse_dates=True)
            lower = datetime(year, 12, 22, tzinfo=timezone.utc)
            left_overlap = left_trades.filter(pl.col("entry_time") >= lower).select(
                "entry_time", "exit_time", "pnl").sort("entry_time")
            right_overlap = right_trades.filter(pl.col("entry_time") >= lower).select(
                "entry_time", "exit_time", "pnl").sort("entry_time")
            # The next shard needs 50 bars after its Dec 18 input boundary.
            # Compare only after that warmup has matured.
            upper = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
            left_overlap = left_overlap.filter(pl.col("entry_time") < upper)
            right_overlap = right_overlap.filter(pl.col("entry_time") < upper)
            same = left_overlap.equals(right_overlap, null_equal=True)
            boundary = {"from_year": year, "to_year": year + 1, "trial": name,
                "warmup_trade_rows_left": left_overlap.height,
                "warmup_trade_rows_right": right_overlap.height, "reconciled": same}
            audit["boundary_overlaps"].append(boundary)
            if not same:
                audit["errors"].append(f"{year}/{name}: adjacent-year warmup trades differ")
    audit["status"] = "passed" if not audit["errors"] else "failed"
    path = OUT / "validation/recovery_audit.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(audit, indent=2) + "\n")
    final_path = OUT / "final_report.json"
    if final_path.exists():
        final = json.loads(final_path.read_text())
        all_annual = []
        for item in audit["years"]:
            year_summary = json.loads((OUT / "by_year" / str(item["year"]) / "year_summary.json").read_text())
            all_annual.extend({"year": item["year"], **trial} for trial in year_summary["trials"])
        results = {}
        for name in ("native_zero_cost", "native_full_tick_cost"):
            selected = [row for row in all_annual if row["name"] == name]
            pnl = sum(row["net_pnl_usd"] for row in selected)
            trades = sum(row["closed_trades"] for row in selected)
            results[name] = {"closed_trades": trades, "net_pnl_usd": pnl,
                "average_trade_pnl_usd": pnl / trades if trades else None,
                "conservative_ambiguous_bound_usd": sum(row.get("conservative_ambiguous_bound_usd", row["net_pnl_usd"])
                    for row in selected) if name == "native_full_tick_cost" else None,
                "annual_results": [{k: row.get(k) for k in ("year", "closed_trades", "net_pnl_usd",
                    "average_trade_pnl_usd", "native_daily_equity_sharpe_utc",
                    "native_daily_equity_max_drawdown_utc", "conservative_ambiguous_bound_usd",
                    "ambiguous_event_count", "ambiguous_event_kinds")} for row in selected]}
        final["trial_results"] = results
        final["annual_trade_results"] = all_annual
        all_events = [event for year in eligible_years()
            for event in json.loads((OUT / "by_year" / str(year) / "ambiguity_report.json").read_text()).get("events", [])]
        final["ambiguity_summary"] = {"event_count": len(all_events),
            "event_kinds": dict(__import__("collections").Counter(x["kind"] for x in all_events)),
            "events": all_events, "bound_is_native_replay": False}
        final["independent_reconciliation"] = audit
        final["status"] = "completed" if audit["status"] == "passed" else "completed_with_audit_errors"
        final_path.write_text(json.dumps(final, indent=2, default=str) + "\n")
        ledger_path = OUT / "trial_ledger.json"
        ledger = json.loads(ledger_path.read_text())
        attempt = next(x for x in ledger["attempts"] if x.get("trial_id") == "RESHARD-ANNUAL-20261012")
        attempt["years"] = [json.loads((OUT / "by_year" / str(y) / "year_summary.json").read_text())
                            for y in eligible_years()]
        ledger_path.write_text(json.dumps(ledger, indent=2) + "\n")
        manifest_path = OUT / "manifest.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        manifest["year_summary_hashes"] = {str(y): sha256(OUT / "by_year" / str(y) / "year_summary.json")
                                           for y in eligible_years()}
        manifest["independent_reconciliation"] = audit["status"]
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int)
    parser.add_argument("--audit", action="store_true")
    args = parser.parse_args()
    if args.audit:
        print(json.dumps(audit_completed(), indent=2))
    elif args.year is None:
        run_batch()
    else:
        # Ensure local repository scripts are importable in this isolated process.
        sys.path.insert(0, str(ROOT / "scripts"))
        result = run_year(args.year)
        (OUT / "by_year" / str(args.year) / "worker_summary.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
        print(json.dumps(result, default=str), flush=True)


if __name__ == "__main__":
    main()
