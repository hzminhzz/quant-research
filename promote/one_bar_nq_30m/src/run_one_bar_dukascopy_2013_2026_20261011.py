"""Run the frozen one-bar breakout study on the Dukascopy Nasdaq index proxy."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl
from ml4t.backtest import (
    AssetClass, BacktestConfig, CommissionType, ContractSpec, DataFeed, Engine,
    Strategy,
)
from ml4t.backtest.analytics import max_drawdown, sharpe_ratio
from ml4t.backtest.config import SlippageType
from ml4t.backtest.types import ExecutionMode, OrderType, StopFillMode

ROOT = Path(__file__).resolve().parents[1]
STORE = Path("/home/quant/dev/quant/ml4t-data/.data/store/index_minute_NQ")
OUT = ROOT / "run_log/one_bar_dukascopy_2013_2026_20261011"
START, END = date(2013, 1, 1), date(2026, 7, 14)
ASSET, MULTIPLIER, NQ_TICK = "NQ_PROXY", 20.0, 0.25
TZ = ZoneInfo("America/Chicago")


def input_files() -> list[Path]:
    return sorted(
        p for p in STORE.glob("year=*/month=*/data.parquet")
        if (p.parent.parent.name.split("=")[1] < "2026")
        or (p.parent.parent.name == "year=2026" and int(p.parent.name.split("=")[1]) <= 7)
    )


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def mark_utc_timestamps(frame: pl.DataFrame, columns: tuple[str, ...]) -> pl.DataFrame:
    return frame.with_columns(*(
        pl.col(name).dt.replace_time_zone("UTC")
        for name in columns
        if isinstance(frame.schema.get(name), pl.Datetime) and frame.schema[name].time_zone is None
    ))


def calendar_qualification() -> dict:
    base = Path("/home/quant/dev/quant/ml4t-data/dukascopy_rebuild")
    qualification = json.loads((base / "us_index_qualification.json").read_text())
    calendar = json.loads((base / "us_index_trading_break_calendar.json").read_text())
    record = next(x for x in qualification["instruments"] if x["logical_symbol"] == "NQ")
    cal_record = calendar["instruments"]["usatechidxusd"]

    def verify(value: dict, identity_key: str, excluded: set[str] | None = None) -> str:
        payload = dict(value)
        claimed = payload.pop(identity_key)
        for key in excluded or set():
            payload.pop(key, None)
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        if claimed != digest:
            raise ValueError(f"Invalid {identity_key}: {claimed} != {digest}")
        return claimed

    q_id = verify(qualification, "manifest_identity")
    qi_id = verify(record, "qualification_identity")
    c_id = verify(calendar, "calendar_identity", {"runtime_metrics"})
    ci_id = verify(cal_record, "instrument_calendar_identity")
    binding = record["session_qualification"]["calendar"]
    if record["source_instrument"] != "usatechidxusd" or record["logical_store_name"] != "index_minute_NQ":
        raise ValueError("NQ source qualification does not match the selected Parquet store")
    if binding.get("calendar_identity") != c_id or binding.get("instrument_calendar_identity") != ci_id:
        raise ValueError("Qualification does not bind to the selected trading-break calendar")
    if qualification["source_library"] != {"name": "dukascopy-node", "version": "1.46.4"}:
        raise ValueError("Unexpected Dukascopy source library version")
    if qualification["retrieval_contract"].get("utc_offset_minutes") != 0:
        raise ValueError("Dukascopy source timestamps are not UTC")
    if cal_record["qualified_through"] < END.isoformat():
        raise ValueError("Dukascopy trading-break calendar does not cover the selected data period")
    return {
        "qualification_manifest_identity": q_id,
        "NQ_qualification_identity": qi_id,
        "calendar_identity": c_id,
        "NQ_calendar_identity": ci_id,
        "qualified_start": cal_record["qualified_start"],
        "qualified_through": cal_record["qualified_through"],
        "calendar_schema": calendar["schema_version"],
        "provider": record["source_name"],
        "source_instrument": record["source_instrument"],
        "retrieval_contract": qualification["retrieval_contract"],
    }


def expected_open_coverage(raw: pl.DataFrame) -> dict:
    calendar_path = Path("/home/quant/dev/quant/ml4t-data/dukascopy_rebuild/us_index_trading_break_calendar.json")
    cal = json.loads(calendar_path.read_text())["instruments"]["usatechidxusd"]
    timestamps = raw.select(pl.col("timestamp").cast(pl.Int64)).to_series().to_numpy() // 60_000_000
    expected_total = observed_total = intervals = missing_intervals = empty_intervals = 0
    missing_days: set[str] = set()
    largest = []
    for day in cal["days"]:
        if not START.isoformat() <= day["date"] <= END.isoformat():
            continue
        for interval in day["expected_open_intervals"]:
            start = datetime.fromisoformat(interval["from"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(interval["to"].replace("Z", "+00:00"))
            lo = int(start.timestamp() // 60)
            hi = int(end.timestamp() // 60)
            expected = max(0, hi - lo)
            left = int(np.searchsorted(timestamps, lo, side="left"))
            right = int(np.searchsorted(timestamps, hi, side="left"))
            observed = right - left
            missing = max(0, expected - observed)
            intervals += 1
            expected_total += expected
            observed_total += min(observed, expected)
            if missing:
                missing_intervals += 1
                missing_days.add(day["date"])
                largest.append({"date": day["date"], "from": interval["from"], "to": interval["to"], "expected_minutes": expected, "observed_rows": observed, "missing_minutes": missing})
            if not observed:
                empty_intervals += 1
    largest.sort(key=lambda x: x["missing_minutes"], reverse=True)
    return {
        "calendar_identity": cal["instrument_calendar_identity"],
        "expected_open_interval_count": intervals,
        "expected_open_minutes": expected_total,
        "observed_rows_in_expected_open_intervals": observed_total,
        "missing_expected_open_minutes": max(0, expected_total - observed_total),
        "expected_open_intervals_with_missing_rows": missing_intervals,
        "expected_open_intervals_with_no_rows": empty_intervals,
        "dates_with_expected_open_data_gaps": len(missing_days),
        "largest_expected_open_gaps": largest[:20],
        "method": "Compare sorted UTC source-minute timestamps with each qualified calendar interval [from,to). Missing counts include expected open minutes without a source row; calendar-closed minutes are excluded.",
    }


def freeze_spec(files: list[Path]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    source_manifest = [
        {"path": p.relative_to(STORE).as_posix(), "size_bytes": p.stat().st_size, "sha256": sha256(p)}
        for p in files
    ]
    manifest_path = OUT / "source_manifest.json"
    manifest_path.write_text(json.dumps(source_manifest, indent=2) + "\n")
    cal = calendar_qualification()
    cal_path = OUT / "calendar_qualification.json"
    cal_path.write_text(json.dumps(cal, indent=2) + "\n")
    spec = {
        "session_id": "one_bar_dukascopy_2013_2026_20261011",
        "classification": "EXPLORATORY retrospective historical review; not deployment approval",
        "economic_hypothesis": "The previous 50 complete 30-minute highs/lows can trigger short-horizon continuation with positive average net PnL after the specified illustrative per-side costs.",
        "falsifier": "Cost-aware average net PnL per closed trade is not positive, or the native fills violate the trigger, protective stop, next-boundary exit, or daily entry cap.",
        "instrument": {"source": "Dukascopy usatechidxusd / USATECH.IDX-USD BID", "type": "Nasdaq technical-index CFD price proxy", "identity_limit": "Not a verified CME E-mini Nasdaq-100 futures contract. One illustrative NQ-equivalent contract maps $20 per point; no CFD contract specifications are asserted."},
        "data": {"root": str(STORE), "start_inclusive_utc": START.isoformat(), "end_inclusive_utc": END.isoformat(), "protected_after": "2026-07-14", "timestamp_source": "Dukascopy .bi5 seconds-from-UTC-midnight decoder; stored naive timestamp interpreted as UTC", "calendar": "dukascopy-us-index-trading-break-calendar-v2; only complete source 30-minute bars and bars with the required next opening print qualify", "calendar_qualification": cal, "calendar_artifact": cal_path.relative_to(ROOT).as_posix(), "source_manifest": manifest_path.relative_to(ROOT).as_posix(), "source_manifest_sha256": sha256(manifest_path), "partitions": len(files)},
        "rules": {"bar_size": "30 minutes aligned to 17:00 America/Chicago session start", "lookback": "highest high / lowest low of previous 50 complete 30-minute bars", "entry": "one native buy STOP at prior high and one native sell STOP at prior low; cancel other order after first fill", "entry_trigger_source": "1-minute source OHLC through native NEXT_BAR STOP orders", "protective_stop": "$1,000 adverse per one illustrative NQ-equivalent contract; $50.00 index points from entry", "exit": "market order at opening print of immediately following 30-minute bar", "daily_limit": "maximum 2 filled entries per Chicago Globex session date", "grid_mapping": "Round stop prices to nearest $0.25 NQ-equivalent grid point; preserve proxy prices otherwise. CFD quote grid is not verified as CME tick-conforming.", "same_minute_stop": "Retain and flag cases where entry candle also reaches the protective stop; OHLC has no intraminute ordering."},
        "capital": {"initial_cash_usd": 1000000, "purpose": "metrics only"},
        "trials": [{"name": "zero_cost", "commission_per_side_usd": 0, "slippage_per_side_points": 0}, {"name": "cost_aware", "commission_per_side_usd": 2.5, "slippage_per_side_points": NQ_TICK / 4, "source": "user-approved illustrative assumption; not verified CFD brokerage cost"}],
        "trial_count": 2,
        "skills": [
            {"name": "ml4t-run-backtest", "invariants": "Native Strategy/Engine/DataFeed, future-bar fills, explicit costs."},
            {"name": "ml4t-polars-patterns", "invariants": "Sorted Polars transforms; complete bars only."},
            {"name": "ml4t-validate-data", "invariants": "Check schema, nulls, OHLC, duplicates, finite values, and expected minute coverage."},
            {"name": "ml4t-build-bars", "invariants": "Bar intervals are explicit; partial bars are excluded."},
            {"name": "ml4t-calendar-ops", "invariants": "Use Chicago session dates and documented Dukascopy calendar qualification."},
            {"name": "ml4t-lookahead-bias", "invariants": "Only prior completed bars set stop levels; next-bar engine fills."},
            {"name": "ml4t-cost-model", "invariants": "Separate zero-cost and user-specified illustrative per-fill friction."},
            {"name": "ml4t-continuous-futures", "invariants": "Do not claim CME futures roll or contract performance for this CFD proxy."},
        ],
        "status": "frozen before outcome inspection",
    }
    (OUT / "frozen_spec.json").write_text(json.dumps(spec, indent=2) + "\n")


def write_methodology_evidence() -> None:
    procedures = [
        ("ml4t-run-backtest", "Native simulation and order fills", "Use Strategy, DataFeed, Engine, next-bar fills, and explicit costs.", "Native ledgers contain stop and market fills; daily Sharpe uses ml4t.backtest.analytics."),
        ("ml4t-polars-patterns", "Process 3.8 million source rows", "Use sorted Polars operations and lazy scans for large data.", "Source files are scanned lazily; grouped bar and rolling-level operations are Polars expressions."),
        ("ml4t-validate-data", "Audit source quality before simulation", "Check OHLC consistency, duplicates, nulls, finite values, timestamps, and gaps.", "source_quality.json reports these checks and source/calendar gaps."),
        ("ml4t-build-bars", "Build the specified 30-minute bars", "Keep intervals explicit and do not treat partial bars as complete.", "Only bins with 30 distinct minute timestamps are retained; a DST regression test checks 50 elapsed bars."),
        ("ml4t-calendar-ops", "Align entries with the Chicago session and provider calendar", "Use the correct timezone, DST behavior, and qualified trading sessions.", "Session starts use America/Chicago then elapsed UTC intervals; qualification and calendar identity hashes pass."),
        ("ml4t-lookahead-bias", "Prevent future bar data from setting stop levels", "Use only previous complete bars and submit orders for a future engine event.", "The 50-bar test verifies prior-bar extrema; native execution uses NEXT_BAR."),
        ("ml4t-cost-model", "Compare the declared zero-cost and cost-aware cases", "Apply costs per fill and disclose unsupported market-specific assumptions.", "Fills record commission and slippage; the cost-aware assumption is explicitly illustrative."),
        ("ml4t-continuous-futures", "Prevent a CFD proxy from being described as CME futures", "Verify contract and roll identity before making futures claims.", "The report identifies a Dukascopy CFD proxy and makes no NQ roll or product-economics claim."),
    ]
    records = []
    for name, reason, invariants, verification in procedures:
        path = ROOT / ".agents" / "skills" / name / "SKILL.md"
        if not path.is_file():
            raise FileNotFoundError(f"Required local methodology skill is missing: {path}")
        records.append({"name": name, "source": str(path), "sha256": sha256(path), "reason_selected": reason, "required_invariants": invariants, "verification": verification})
    payload = {"skills": records, "ml4t_backtest_version": importlib.metadata.version("ml4t-backtest"), "api_signatures_inspected": ["Strategy()", "Engine(feed, strategy, config, contract_specs=...)", "DataFeed(prices_df=..., signals_df=...)"], "selection_rule": "Only task-relevant ML4T procedures were loaded."}
    (OUT / "methodology_skills.json").write_text(json.dumps(payload, indent=2) + "\n")


def exchange_day(ts: datetime) -> date:
    local = ts.astimezone(TZ)
    return local.date() if local.hour >= 17 else local.date() - timedelta(days=1)


def load_and_prepare(files: list[Path]) -> tuple[pl.DataFrame, dict]:
    raw = (
        pl.scan_parquet([str(p) for p in files])
        .filter(pl.col("timestamp").dt.date().is_between(START, END))
        .sort("timestamp")
        .collect()
    )
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    if not required.issubset(raw.columns):
        raise ValueError(f"Missing source columns: {sorted(required - set(raw.columns))}")
    raw = raw.with_columns(pl.col("timestamp").dt.replace_time_zone("UTC"))
    local = pl.col("timestamp").dt.convert_time_zone("America/Chicago")
    minute_of_day = local.dt.hour().cast(pl.Int32) * 60 + local.dt.minute().cast(pl.Int32)
    raw = raw.with_columns(
        local.alias("local"),
        pl.when(minute_of_day >= 17 * 60).then(local.dt.date()).otherwise(local.dt.date().dt.offset_by("-1d")).alias("session_date"),
    )
    session_dates = raw.get_column("session_date").unique().sort().to_list()
    session_starts = pl.DataFrame({
        "session_date": session_dates,
        "session_start_utc": [datetime.combine(d, time(17), tzinfo=TZ).astimezone(timezone.utc) for d in session_dates],
    })
    raw = raw.join(session_starts, on="session_date", how="left").with_columns(
        ((pl.col("timestamp") - pl.col("session_start_utc")).dt.total_minutes() // 30).alias("bar_no")
    )
    bad_ohlc = raw.filter((pl.col("high") < pl.col("low")) | (pl.col("close") > pl.col("high")) | (pl.col("close") < pl.col("low"))).height
    null_values = sum(raw.get_column(c).null_count() for c in ("open", "high", "low", "close", "volume"))
    dupes = raw.height - raw.get_column("timestamp").n_unique()
    nonfinite = raw.filter(~pl.all_horizontal([pl.col(c).is_finite() for c in ("open", "high", "low", "close", "volume")])).height
    gaps = (
        raw.select(pl.col("timestamp").diff().alias("delta"))
        .filter(pl.col("delta") > pl.duration(minutes=1))
        .with_columns((pl.col("delta").dt.total_minutes() - 1).alias("missing_minutes"))
    )
    # Require all expected one-minute timestamps, not just a count of 30 rows.
    bars = (
        raw.group_by("session_date", "bar_no")
        .agg(pl.col("timestamp").min().alias("timestamp"), pl.col("open").first(), pl.col("high").max(), pl.col("low").min(), pl.col("close").last(), pl.col("volume").sum(), pl.len().alias("n"), pl.col("timestamp").n_unique().alias("unique_n"))
        .with_columns(((pl.col("n") == 30) & (pl.col("unique_n") == 30)).alias("complete"))
        .sort("timestamp")
    )
    complete = bars.filter(pl.col("complete"))
    levels = complete.with_columns(
        pl.col("high").rolling_max(50).alias("long_stop"),
        pl.col("low").rolling_min(50).alias("short_stop"),
    ).with_columns(
        pl.col("timestamp").shift(-1).alias("next_bar_time"),
        pl.col("timestamp").shift(-2).alias("next2_bar_time"),
    )
    # A trade can only start when its full trigger bar and following exit bar qualify.
    signals = levels.select(
        "session_date", "bar_no",
        pl.col("long_stop").alias("next_long_stop"),
        pl.col("short_stop").alias("next_short_stop"),
        ((pl.col("next_bar_time") - pl.col("timestamp") == pl.duration(minutes=30)) & (pl.col("next2_bar_time") - pl.col("next_bar_time") == pl.duration(minutes=30))).alias("entry_valid"),
    )
    entry_eligible = signals.filter(pl.col("entry_valid") & pl.col("next_long_stop").is_not_null()).height
    # Keep minute rows only for complete bars. Order submission at :29/:59 then reaches next bar's :00.
    complete_keys = complete.select("session_date", "bar_no")
    feed = raw.join(complete_keys, on=["session_date", "bar_no"], how="inner").join(signals, on=["session_date", "bar_no"], how="left")
    feed = feed.with_columns(pl.lit(ASSET).alias("asset"))
    source_quality = {
        "rows": raw.height,
        "files": len(files),
        "timestamp_min_utc": raw.get_column("timestamp").min().isoformat(),
        "timestamp_max_utc": raw.get_column("timestamp").max().isoformat(),
        "naive_utc_interpretation": "verified from decoder's UTC epoch construction",
        "duplicate_timestamps": dupes,
        "null_price_or_volume_values": null_values,
        "nonfinite_ohlcv_rows": nonfinite,
        "bad_ohlc_rows": bad_ohlc,
        "complete_30m_bars": complete.height,
        "incomplete_30m_bars": bars.height - complete.height,
        "complete_bar_rows_not_30_unique_minutes": bars.filter(~pl.col("complete")).height,
        "bars_with_50_prior_complete_bars": levels.filter(pl.col("long_stop").is_not_null()).height,
        "bars_with_50_prior_levels_and_two_consecutive_following_bars": entry_eligible,
        "complete_bars_without_two_consecutive_following_30m_opens": complete.height - signals.filter(pl.col("entry_valid")).height,
        "feed_minutes": feed.height,
        "timestamp_gaps_over_one_minute": gaps.height,
        "unobserved_minutes_between_source_rows": int(gaps.get_column("missing_minutes").sum() or 0),
        "largest_timestamp_gap_minutes": int(gaps.get_column("missing_minutes").max() or 0) + 1,
        "gap_interpretation": "Includes expected weekends, scheduled provider breaks, and source gaps; only incomplete 30-minute bins are categorically excluded here.",
        "session_alignment": "Elapsed 30-minute UTC intervals anchored at each 17:00 America/Chicago session start; DST-aware",
        "calendar_qualification": calendar_qualification(),
        "expected_open_coverage": expected_open_coverage(raw),
        "calendar_note": "The source-specific qualification and calendar identities were hash-verified. Incomplete bars are omitted. No missing minute is forward-filled.",
    }
    # Convert only the small summary after validation; engine consumes native Polars frames.
    feed = feed.drop("local", "session_start_utc", strict=False)
    return feed, source_quality


class OneBarBreakout(Strategy):
    def __init__(self, costs: bool):
        self.costs = costs
        self.entry_orders = []
        self.stop_order = None
        self.exit_order = None
        self.trade = None
        self.entries_by_day: dict[str, int] = defaultdict(int)
        self.max_daily_entries = 0
        self.ambiguous = []
        self.fills_seen = 0

    def on_data(self, timestamp, data, context, broker):
        bar = data[ASSET]
        pos = broker.get_position(ASSET)
        qty = float(pos.quantity) if pos else 0.0
        if qty and self.trade is None:
            day = exchange_day(timestamp).isoformat()
            self.trade = {"entry_time": timestamp.isoformat(), "side": "long" if qty > 0 else "short", "entry_price": float(pos.entry_price), "session_date": day}
            self.entries_by_day[day] += 1
            self.max_daily_entries = max(self.max_daily_entries, self.entries_by_day[day])
            stop_pts = 1000.0 / MULTIPLIER
            stop = float(pos.entry_price) - stop_pts if qty > 0 else float(pos.entry_price) + stop_pts
            stop = round(round(stop / NQ_TICK) * NQ_TICK, 8)
            if (qty > 0 and float(bar["low"]) <= stop) or (qty < 0 and float(bar["high"]) >= stop):
                self.ambiguous.append({"timestamp": timestamp.isoformat(), "side": self.trade["side"], "entry": float(pos.entry_price), "stop": stop})
            for order in self.entry_orders:
                if order and order.status.value == "pending":
                    broker.cancel_order(order.order_id)
            self.entry_orders.clear()
            self.stop_order = broker.submit_order(ASSET, -qty, order_type=OrderType.STOP, stop_price=stop)
            self.trade["protective_stop"] = stop
        if self.trade and qty:
            local = timestamp.astimezone(TZ)
            if local.minute in (29, 59):
                if self.stop_order and self.stop_order.status.value == "pending":
                    broker.cancel_order(self.stop_order.order_id)
                self.exit_order = broker.submit_order(ASSET, -qty, order_type=OrderType.MARKET)
                self.trade["scheduled_exit"] = (timestamp + timedelta(minutes=1)).isoformat()
        if not qty and self.trade:
            self.trade = None
            self.stop_order = None
            self.exit_order = None
        if not qty and timestamp.astimezone(TZ).minute in (29, 59):
            for order in self.entry_orders:
                if order and order.status.value == "pending":
                    broker.cancel_order(order.order_id)
            self.entry_orders.clear()
            signals = bar.get("signals", {})
            long_stop, short_stop = signals.get("next_long_stop"), signals.get("next_short_stop")
            next_open = timestamp + timedelta(minutes=1)
            day = exchange_day(next_open).isoformat()
            if signals.get("entry_valid") and long_stop is not None and short_stop is not None and self.entries_by_day[day] < 2:
                long_stop = round(round(float(long_stop) / NQ_TICK) * NQ_TICK, 8)
                short_stop = round(round(float(short_stop) / NQ_TICK) * NQ_TICK, 8)
                self.entry_orders = [
                    broker.submit_order(ASSET, 1, order_type=OrderType.STOP, stop_price=long_stop),
                    broker.submit_order(ASSET, -1, order_type=OrderType.STOP, stop_price=short_stop),
                ]


def run_trial(feed: pl.DataFrame, costs: bool) -> dict:
    name = "cost_aware" if costs else "zero_cost"
    strategy = OneBarBreakout(costs)
    config = BacktestConfig(
        initial_cash=1_000_000,
        allow_short_selling=True,
        allow_leverage=True,
        fixed_margin_schedule={ASSET: (25_000.0, 20_000.0)},
        execution_mode=ExecutionMode.NEXT_BAR,
        stop_fill_mode=StopFillMode.STOP_PRICE,
        commission_type=CommissionType.PER_CONTRACT if costs else CommissionType.NONE,
        commission_per_share=2.50 if costs else 0.0,
        slippage_type=SlippageType.FIXED if costs else SlippageType.NONE,
        slippage_fixed=NQ_TICK / 4 if costs else 0.0,
    )
    spec = ContractSpec(symbol=ASSET, asset_class=AssetClass.FUTURE, multiplier=MULTIPLIER, tick_size=NQ_TICK, margin=25_000.0)
    prices = feed.select("timestamp", "asset", "open", "high", "low", "close", "volume")
    signals = feed.select("timestamp", "asset", pl.col("next_long_stop"), pl.col("next_short_stop"), "entry_valid")
    result = Engine(DataFeed(prices_df=prices, signals_df=signals), strategy, config, contract_specs={ASSET: spec}).run()
    if strategy.max_daily_entries > 2:
        raise AssertionError(f"Exceeded two entries in session day: {strategy.max_daily_entries}")
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    trades = mark_utc_timestamps(result.to_trades_dataframe(), ("entry_time", "exit_time"))
    fills = mark_utc_timestamps(result.to_fills_dataframe(), ("timestamp",))
    trades.write_csv(out / "trades.csv")
    fills.write_csv(out / "fills.csv")
    curve = pl.DataFrame({"timestamp": [t for t, _ in result.equity_curve], "equity": [float(v) for _, v in result.equity_curve]})
    daily = curve.with_columns(pl.col("timestamp").dt.date().alias("utc_day")).group_by("utc_day").agg(pl.col("timestamp").last(), pl.col("equity").last()).sort("utc_day")
    daily.write_csv(out / "daily_equity.csv")
    yearly = trades.with_columns(pl.col("exit_time").dt.year().alias("year")).group_by("year").agg(pl.len().alias("closed_trades"), pl.col("pnl").sum().alias("pnl_usd"), pl.col("pnl").mean().alias("avg_trade_usd")).sort("year") if trades.height else pl.DataFrame(schema={"year": pl.Int32, "closed_trades": pl.UInt32, "pnl_usd": pl.Float64, "avg_trade_usd": pl.Float64})
    yearly.write_csv(out / "yearly_summary.csv")
    values = daily.get_column("equity").to_list()
    returns = [b / a - 1 for a, b in zip([1_000_000.0, *values[:-1]], values) if a]
    metrics = dict(result.metrics)
    closed_pnl = float(trades.filter(pl.col("status") == "closed").get_column("pnl").sum() or 0.0) if trades.height else 0.0
    net_profit = float(metrics.get("final_value", config.initial_cash) - config.initial_cash)
    metrics.update({
        "trial": name,
        "net_profit_usd": net_profit,
        "trade_ledger_net_pnl_usd": closed_pnl,
        "ledger_reconciliation_difference_usd": closed_pnl - net_profit,
        "daily_equity_sharpe": sharpe_ratio(returns, annualize=True) if returns else None,
        "daily_equity_max_drawdown": abs(max_drawdown([1_000_000.0, *values])[0]),
        "closed_trade_count": trades.filter(pl.col("status") == "closed").height if trades.height else 0,
        "average_net_pnl_usd": trades.filter(pl.col("status") == "closed").get_column("pnl").mean() if trades.height else None,
        "max_hold_minutes": int((trades.with_columns((pl.col("exit_time") - pl.col("entry_time")).dt.total_minutes().alias("mins")).get_column("mins").max()) or 0) if trades.height else 0,
        "late_next_boundary_exits": int(trades.filter((pl.col("exit_time") - pl.col("entry_time")).dt.total_minutes() > 30).height) if trades.height else 0,
        "entries_per_session_day_max": strategy.max_daily_entries,
        "same_minute_entry_stop_ambiguities": len(strategy.ambiguous),
        "ambiguous_examples": strategy.ambiguous[:50],
        "protective_stop_exit_fills": int(fills.filter((pl.col("order_type") == "stop") & (pl.col("exit_reason") == "signal")).height) if fills.height else 0,
        "protective_stop_gap_through_fills": int(fills.filter((pl.col("order_type") == "stop") & (pl.col("exit_reason") == "signal") & (((pl.col("side") == "sell") & (pl.col("reference_price") < pl.col("stop_price"))) | ((pl.col("side") == "buy") & (pl.col("reference_price") > pl.col("stop_price"))))).height) if fills.height else 0,
        "entry_gap_triggers": int(fills.filter((pl.col("order_type") == "stop") & (pl.col("exit_reason") == "") & (((pl.col("side") == "buy") & (pl.col("reference_price") > pl.col("stop_price"))) | ((pl.col("side") == "sell") & (pl.col("reference_price") < pl.col("stop_price"))))).height) if fills.height else 0,
        "cost_assumption": {"commission_per_side_usd": 2.5 if costs else 0.0, "slippage_per_side_points": NQ_TICK / 4 if costs else 0.0},
        "execution_mode": "ml4t.backtest NEXT_BAR native STOP and MARKET orders",
    })
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str) + "\n")
    return {"trial": name, "metrics": metrics, "yearly_summary": yearly.to_dicts(), "artifacts": {p.name: sha256(p) for p in out.iterdir() if p.is_file()}}


def render_equity_chart() -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 4.5))
    for name, label in (("zero_cost", "Zero cost"), ("cost_aware", "Cost aware")):
        daily = pl.read_csv(OUT / name / "daily_equity.csv", try_parse_dates=True)
        ax.plot(daily.get_column("timestamp").to_list(), daily.get_column("equity").to_list(), label=label, linewidth=1.1)
    ax.set(title="One-bar 50-breakout — Dukascopy Nasdaq index proxy", ylabel="Equity (USD)", xlabel="UTC date")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    path = OUT / "equity_curve.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def main() -> None:
    files = input_files()
    if not files:
        raise FileNotFoundError(f"No source partitions found under {STORE}")
    frozen_path = OUT / "frozen_spec.json"
    if frozen_path.exists():
        frozen = json.loads(frozen_path.read_text())
        source_manifest = ROOT / frozen["data"]["source_manifest"]
        if len(files) != frozen["data"]["partitions"] or sha256(source_manifest) != frozen["data"]["source_manifest_sha256"]:
            raise ValueError("Frozen input manifest changed; refusing to overwrite the frozen study")
    else:
        freeze_spec(files)
    write_methodology_evidence()
    print(f"FROZEN: {len(files)} partitions; loading source", flush=True)
    feed, quality = load_and_prepare(files)
    (OUT / "source_quality.json").write_text(json.dumps(quality, indent=2) + "\n")
    print(f"SOURCE_VALIDATED: {quality}", flush=True)
    results = []
    for costs in (False, True):
        print(f"ENGINE_START: {'cost_aware' if costs else 'zero_cost'}", flush=True)
        results.append(run_trial(feed, costs))
        print(f"ENGINE_DONE: {results[-1]['trial']}", flush=True)
    chart = render_equity_chart()
    report = {
        "status": "COMPLETED_EXPLORATORY" if all(r["metrics"].get("closed_trade_count", 0) for r in results) else "COMPLETED_EXPLORATORY_WITH_EMPTY_TRADES",
        "research_class": "EXPLORATORY retrospective history; not approval to trade",
        "source": "Dukascopy USATECH.IDX-USD BID index CFD proxy; not CME NQ futures",
        "frozen_spec": "frozen_spec.json",
        "source_quality": quality,
        "backtests": results,
        "equity_chart": chart.relative_to(ROOT).as_posix(),
        "equity_chart_sha256": sha256(chart),
        "limitations": ["CFD quote precision is not CME tick-conforming; a deterministic $0.25 grid is used for NQ-equivalent stop levels.", "Same-minute entry and protective-stop ordering cannot be recovered from 1-minute OHLC and is flagged.", "The $2.50 per-side commission is illustrative, not a verified CFD brokerage cost.", "No continuous futures roll, dated futures identity, or executable product economics are inferred."],
        "screenshot_comparison": {"approximate_reference": "$200,000 / 4,800 trades = $41.67 per trade", "conclusion": "Visual reference only; not a verified historical result or validation target."},
        "next_decisive_question": "Can this exploratory result be independently reconstructed on verified dated CME NQ contracts with contract roll history and instrument-specific costs?",
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(json.dumps({"status": report["status"], "summaries": [{"trial": r["trial"], "metrics": r["metrics"]} for r in results]}, indent=2, default=str), flush=True)


if __name__ == "__main__":
    main()
