"""One Chicago-session-year B2 replay, launched by run_one_bar_nq_b2_20261012.py."""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
from ml4t.engineer import compute_features

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from run_one_bar_nq_b2_20261012 import BASE, END, OUT, STORE, can_enter, protective_stop, sha, write, source_files

ASSET = "MNQ_PROXY"
TZ = ZoneInfo("America/Chicago")
MULTIPLIER, TICK = 2.0, 0.25
INITIAL_CASH = 1_000_000.0
INITIAL_MARGIN, MAINTENANCE_MARGIN = 2500.0, 2000.0


def files_for_year(year: int) -> list[Path]:
    return [p for p in source_files() if int(p.parent.parent.name.split("=")[1]) in (year - 1, year, year + 1)]


def build_bars(raw: pl.DataFrame) -> pl.DataFrame:
    local = pl.col("timestamp").dt.convert_time_zone("America/Chicago")
    raw = raw.with_columns(local.alias("local"),
        pl.when(local.dt.hour() >= 17).then(local.dt.date())
        .otherwise(local.dt.date().dt.offset_by("-1d")).alias("session_date"))
    dates = raw["session_date"].unique().sort().to_list()
    starts = pl.DataFrame({"session_date": dates,
        "session_start_utc": [datetime(d.year, d.month, d.day, 17, tzinfo=TZ).astimezone(timezone.utc) for d in dates]})
    source = raw.join(starts, on="session_date").with_columns(
        ((pl.col("timestamp") - pl.col("session_start_utc")).dt.total_minutes() // 30).alias("bar_no"))
    bars = (source.group_by("session_date", "bar_no").agg(
        pl.col("timestamp").min().alias("bar_start"), pl.col("open").first().alias("open"),
        pl.col("high").max().alias("high"), pl.col("low").min().alias("low"),
        pl.col("close").last().alias("close"), pl.col("volume").sum().alias("volume"),
        pl.len().alias("n"), pl.col("timestamp").n_unique().alias("unique_n"))
        .filter((pl.col("n") == 30) & (pl.col("unique_n") == 30)).sort("bar_start"))
    # Installed ML4T implementation uses TA-Lib-compatible ATR (Wilder RMA).
    bars = compute_features(bars.select("bar_start", "open", "high", "low", "close", "volume")
                            .rename({"bar_start": "timestamp"}),
                            [{"name": "atr", "params": {"period": 20}}], timestamp_col="timestamp")
    return (bars.rename({"timestamp": "bar_start", "atr": "atr20"})
        .with_columns((pl.col("bar_start") + pl.duration(minutes=30)).alias("available_at"),
            pl.col("high").rolling_max(50).alias("next_long_stop"),
            pl.col("low").rolling_min(50).alias("next_short_stop"))
        .with_columns((pl.col("available_at") - pl.duration(minutes=1)).alias("release_decision_at"),
            pl.when(pl.col("atr20").is_finite()).then(((1.5 * pl.col("atr20") / TICK).ceil() * TICK)).otherwise(None).alias("stop_points"))
        .with_columns(pl.when(pl.col("stop_points").is_not_null() & (pl.col("stop_points") > 0))
            .then((1000 / (MULTIPLIER * pl.col("stop_points"))).floor().cast(pl.Int64))
            .otherwise(None).alias("mnq_qty")))


def attach_signals(raw: pl.DataFrame, bars: pl.DataFrame) -> pl.DataFrame:
    return raw.sort("timestamp").join_asof(
        bars.select("release_decision_at", "next_long_stop", "next_short_stop", "atr20", "stop_points", "mnq_qty").sort("release_decision_at"),
        left_on="timestamp", right_on="release_decision_at", strategy="backward")


def build_year_feed(year: int) -> tuple[pl.DataFrame, dict]:
    warm_start = date(year, 1, 1) if year == 2013 else date(year, 1, 1) - timedelta(days=14)
    eval_end = END if year == 2026 else date(year, 12, 31)
    source_end = min(END, eval_end + timedelta(days=7))
    paths = files_for_year(year)
    raw = (pl.scan_parquet([str(p) for p in paths])
        .filter(pl.col("timestamp").dt.date().is_between(warm_start, source_end))
        .select("timestamp", "open", "high", "low", "close", "volume").sort("timestamp").collect()
        .with_columns(pl.col("timestamp").dt.replace_time_zone("UTC")))
    if raw.is_empty(): raise ValueError(f"No rows for {year}")
    bars = build_bars(raw)
    local = pl.col("timestamp").dt.convert_time_zone("America/Chicago")
    source = raw.with_columns(local.alias("local"),
        pl.when(local.dt.hour() >= 17).then(local.dt.date())
        .otherwise(local.dt.date().dt.offset_by("-1d")).alias("session_date"))
    feed = attach_signals(source, bars).with_columns(pl.lit(ASSET).alias("asset"))
    eval_rows = feed.filter(pl.col("session_date").dt.year() == year)
    warm = bars.filter(pl.col("available_at") <= eval_rows["timestamp"].min()).height if eval_rows.height else 0
    all_bins = (source.with_columns(((pl.col("timestamp") - pl.col("session_date").map_elements(
        lambda d: datetime(d.year, d.month, d.day, 17, tzinfo=TZ).astimezone(timezone.utc),
        return_dtype=pl.Datetime("us", "UTC"))).dt.total_minutes() // 30).alias("bar_no"))
        .group_by("session_date", "bar_no").len().height)
    quality = {"year": year, "raw_rows": raw.height, "execution_rows_retained": feed.height,
        "complete_30m_bars": bars.height, "warmup_complete_bars": warm,
        "duplicate_timestamps": raw.height - raw["timestamp"].n_unique(),
        "null_ohlc": sum(raw[c].null_count() for c in ("open", "high", "low", "close")),
        "invalid_ohlc": raw.filter((pl.col("high") < pl.col("low")) |
            (pl.col("close") > pl.col("high")) | (pl.col("close") < pl.col("low"))).height,
        "incomplete_bins": all_bins - bars.height,
        "source_start": raw["timestamp"].min().isoformat(), "source_end": raw["timestamp"].max().isoformat(),
        "partial_30m_execution_rows_preserved": True, "atr_release": "available on final minute of completed bar; first fill event is next source minute"}
    if year > 2013 and warm < 80: raise ValueError(f"Insufficient prior context for year {year}: {warm} bars")
    if quality["duplicate_timestamps"] or quality["null_ohlc"] or quality["invalid_ohlc"]: raise ValueError(str(quality))
    return feed, quality


def chicago_day(ts: datetime) -> date:
    local = ts.astimezone(TZ)
    return local.date() if local.hour >= 17 else local.date() - timedelta(days=1)


def is_evaluation_session_year(ts: datetime, year: int) -> bool:
    return chicago_day(ts).year >= year


def is_evaluation_session_day(day: date, year: int, end: date) -> bool:
    return date(year, 1, 1) <= day <= end


def next_boundary(ts: datetime) -> datetime:
    return datetime.fromtimestamp((int(ts.timestamp()) // 1800 + 1) * 1800, timezone.utc)


def metadata_for_filled_entry(orders, metadata_by_order_id, position_quantity):
    """Return the frozen signal metadata for the order that opened this position."""
    filled = [metadata_by_order_id[o.order_id] for o in orders
              if o and o.status.value == "filled" and o.order_id in metadata_by_order_id
              and metadata_by_order_id[o.order_id]["signed_quantity"] * position_quantity > 0]
    if len(filled) != 1:
        raise ValueError(f"Expected one filled entry metadata record, found {len(filled)}")
    return filled[0]


def run(year: int) -> dict:
    from ml4t.backtest import AssetClass, BacktestConfig, CommissionType, ContractSpec, DataFeed, Engine, Strategy
    from ml4t.backtest.config import SlippageType
    from ml4t.backtest.types import ExecutionMode, OrderType, StopFillMode

    feed, quality = build_year_feed(year)
    ydir = OUT / "by_year" / str(year)
    ydir.mkdir(parents=True, exist_ok=True)
    write(ydir / "source_quality.json", quality)
    prices = feed.select("timestamp", "asset", "open", "high", "low", "close", "volume")
    signals = feed.select("timestamp", "asset", "next_long_stop", "next_short_stop", "atr20", "stop_points", "mnq_qty")
    yearsummaries = []

    class B2(Strategy):
        def __init__(self):
            self.counts = defaultdict(int); self.entries = []; self.entry_orders = []
            self.entry_metadata = {}; self.order_metadata = {}; self.filled_metadata = None
            self.stop_order = None; self.trade = None; self.ambiguous = []; self.skipped = 0
        def on_data(self, timestamp, data, context, broker):
            if not is_evaluation_session_year(timestamp, year):
                return  # Warmup bars build causal features; they are not part of this annual account.
            bar = data[ASSET]; pos = broker.get_position(ASSET); qty = float(pos.quantity) if pos else 0.0
            newly_filled = [o for o in self.entry_orders if o and o.status.value == "filled"]
            if newly_filled:
                if len(newly_filled) > 1: self.ambiguous.append({"timestamp": timestamp.isoformat(), "kind": "both_entry_stops_filled"})
                self.counts[chicago_day(timestamp)] += len(newly_filled)
                if qty:
                    self.filled_metadata = metadata_for_filled_entry(newly_filled, self.entry_metadata, qty)
                self.entry_orders = [o for o in self.entry_orders if o and o.status.value == "pending"]
            if qty and self.trade is None:
                side = "long" if qty > 0 else "short"
                if self.filled_metadata is None:
                    raise ValueError("Filled position has no matching captured entry signal metadata")
                distance = self.filled_metadata["distance"]
                stop_price = protective_stop(float(pos.entry_price), distance, qty)
                touched = (float(bar["low"]) <= stop_price) if qty > 0 else (float(bar["high"]) >= stop_price)
                if touched: self.ambiguous.append({"timestamp": timestamp.isoformat(), "kind": "entry_and_stop_same_minute", "entry": float(pos.entry_price), "stop": stop_price})
                self.trade = {"side": side, "distance": distance, "entry_time": timestamp,
                    "scheduled_exit": next_boundary(timestamp), "qty": abs(qty), "entry_price": float(pos.entry_price)}
                self.entries.append({**self.trade, "atr20": self.filled_metadata["atr20"], "nominal_risk_usd": abs(qty)*distance*MULTIPLIER,
                    "planned_quantity": abs(int(self.filled_metadata["signed_quantity"]))})
                for order in self.entry_orders:
                    if order and order.status.value == "pending": broker.cancel_order(order.order_id)
                self.entry_orders.clear()
                self.stop_order = broker.submit_order(ASSET, -qty, order_type=OrderType.STOP, stop_price=stop_price)
            if qty and self.trade and timestamp >= self.trade["scheduled_exit"] - timedelta(minutes=1):
                if self.stop_order and self.stop_order.status.value == "pending": broker.cancel_order(self.stop_order.order_id)
                broker.submit_order(ASSET, -qty, order_type=OrderType.MARKET)
            if not qty and self.trade:
                self.trade = None; self.stop_order = None; self.filled_metadata = None
            eval_end = END if year == 2026 else date(year, 12, 31)
            if chicago_day(timestamp) > eval_end: return
            local = timestamp.astimezone(TZ)
            if local.minute not in (29, 59) or qty: return
            for order in self.entry_orders:
                if order and order.status.value == "pending": broker.cancel_order(order.order_id)
            self.entry_orders.clear()
            s = bar.get("signals", {})
            long_level, short_level = s.get("next_long_stop"), s.get("next_short_stop")
            dist, n = s.get("stop_points"), s.get("mnq_qty")
            day = chicago_day(timestamp + timedelta(minutes=1))
            if long_level is None or short_level is None or dist is None or n is None: return
            n = int(n)
            if n < 1: self.skipped += 1; return
            if not is_evaluation_session_day(day, year, eval_end): return
            if not can_enter(self.counts, day): return
            self.entry_orders = [broker.submit_order(ASSET, n, order_type=OrderType.STOP, stop_price=round(round(float(long_level)/TICK)*TICK,8)),
                broker.submit_order(ASSET, -n, order_type=OrderType.STOP, stop_price=round(round(float(short_level)/TICK)*TICK,8))]
            for order, signed_qty in zip(self.entry_orders, (n, -n), strict=True):
                self.entry_metadata[order.order_id] = {"distance": float(dist), "atr20": float(s["atr20"]),
                    "signed_quantity": signed_qty}
                self.order_metadata[order.order_id] = {**self.entry_metadata[order.order_id],
                    "signal_time": timestamp.isoformat(), "trigger_price": float(order.stop_price)}

    for label, commission, slip in (("B2_zero_cost", 0.0, 0.0), ("B2_costed", 1.25, 0.25)):
        strategy = B2()
        config = BacktestConfig(initial_cash=INITIAL_CASH, allow_short_selling=True, allow_leverage=True,
            fixed_margin_schedule={ASSET: (INITIAL_MARGIN, MAINTENANCE_MARGIN)},
            execution_mode=ExecutionMode.NEXT_BAR, stop_fill_mode=StopFillMode.NEXT_BAR_OPEN,
            commission_type=CommissionType.PER_SHARE if commission else CommissionType.NONE,
            commission_per_share=commission,
            slippage_type=SlippageType.FIXED if slip else SlippageType.NONE, slippage_fixed=slip,
            reject_on_insufficient_cash=True)
        spec = ContractSpec(symbol=ASSET, asset_class=AssetClass.FUTURE, multiplier=MULTIPLIER, tick_size=TICK, margin=INITIAL_MARGIN)
        result = Engine(DataFeed(prices_df=prices, signals_df=signals), strategy, config,
            contract_specs={ASSET: spec}).run()
        path = ydir / label; path.mkdir(parents=True, exist_ok=True)
        trades, fills = result.to_trades_dataframe(), result.to_fills_dataframe()
        for frame, cols in ((trades, ("entry_time", "exit_time")), (fills, ("timestamp",))):
            for col in cols:
                if frame.height and frame[col].dtype == pl.Datetime and frame[col].dtype.time_zone is None:
                    frame.replace_column(frame.columns.index(col), frame[col].dt.replace_time_zone("UTC"))
        trades.write_csv(path / "trades.csv"); fills.write_csv(path / "fills.csv")
        entry_fills = fills.filter((pl.col("order_type") == "stop") & (pl.col("exit_reason") == ""))
        entries = []
        for fill in entry_fills.to_dicts():
            meta = strategy.order_metadata.get(fill["order_id"])
            if meta is None:
                raise ValueError(f"No captured signal metadata for filled entry order {fill['order_id']}")
            signed_qty = float(fill["quantity"]) * (1 if fill["side"] == "buy" else -1)
            entries.append({"order_id": fill["order_id"], "entry_time": fill["timestamp"],
                "entry_price": float(fill["price"]), "side": "long" if signed_qty > 0 else "short",
                "qty": abs(signed_qty), "signed_quantity": signed_qty, "distance": meta["distance"],
                "atr20": meta["atr20"], "signal_time": meta["signal_time"],
                "trigger_price": meta["trigger_price"], "nominal_risk_usd": abs(signed_qty)*meta["distance"]*MULTIPLIER})
        pl.DataFrame(entries).write_csv(path / "entry_context.csv")
        eq = pl.DataFrame({"timestamp": [t for t, _ in result.equity_curve], "equity": [float(v) for _, v in result.equity_curve]})
        daily = eq.with_columns(pl.col("timestamp").dt.date().alias("date")).group_by("date").agg(pl.col("timestamp").last(), pl.col("equity").last()).sort("date")
        daily.write_csv(path / "daily_equity.csv")
        closed = trades.filter(pl.col("status") == "closed") if trades.height else trades
        # Attribute by actual entry timestamp's Chicago session year; final partial year uses the fixed cutoff.
        if closed.height:
            closed = closed.with_columns(pl.col("entry_time").map_elements(chicago_day, return_dtype=pl.Date).alias("session_day"))
            closed = closed.filter(pl.col("session_day").dt.year() == year)
        if closed.height:
            trade_rows = []
            candidate_entries = [e for e in entries if chicago_day(e["entry_time"]).year == year]
            for trade in closed.to_dicts():
                candidates = [e for e in candidate_entries if e["entry_time"] == trade["entry_time"]
                    and e["side"] == str(trade["direction"]).lower() and e["qty"] == abs(float(trade["quantity"]))]
                if len(candidates) != 1:
                    raise ValueError(f"Expected one native entry fill match for trade {trade['entry_time']}; found {len(candidates)}")
                entry = candidates[0]
                candidate_entries.remove(entry)
                direction = str(trade["direction"]).lower()
                stop_price = protective_stop(float(trade["entry_price"]), float(entry["distance"]),
                                             float(trade["quantity"]) if direction == "long" else -float(trade["quantity"]))
                exit_matches = fills.filter((pl.col("timestamp") == trade["exit_time"]) &
                    (pl.col("side") == ("sell" if direction == "long" else "buy")))
                exit_fill = exit_matches.row(0, named=True) if exit_matches.height else None
                trade["stop_distance"] = float(entry["distance"])
                trade["planned_quantity"] = int(entry["qty"])
                trade["stop_price"] = stop_price
                trade["nominal_risk_usd"] = abs(float(trade["quantity"])) * abs(float(trade["entry_price"]) - stop_price) * MULTIPLIER
                trade["r_multiple"] = float(trade["pnl"]) / trade["nominal_risk_usd"]
                trade["exit_order_type"] = exit_fill["order_type"] if exit_fill else None
                reference = float(exit_fill["reference_price"]) if exit_fill and exit_fill["reference_price"] is not None else (float(exit_fill["price"]) if exit_fill else 0.0)
                trade["gap_overshoot_points"] = (max(0.0, stop_price - reference) if direction == "long"
                    else max(0.0, reference - stop_price)) if exit_fill and exit_fill["order_type"] == "stop" else 0.0
                trade["gap_overshoot_usd"] = trade["gap_overshoot_points"] * abs(float(trade["quantity"])) * MULTIPLIER
                boundary = next_boundary(trade["entry_time"])
                trade["late_market_exit_minutes"] = (max(0.0, (trade["exit_time"] - boundary).total_seconds() / 60)
                    if trade["exit_order_type"] == "market" else 0.0)
                trade_rows.append(trade)
            closed = pl.DataFrame(trade_rows)
            closed.write_csv(path / "evaluation_trades.csv")
        gross = float(closed["gross_pnl"].sum() or 0) if closed.height else 0.0
        net = float(closed["pnl"].sum() or 0) if closed.height else 0.0
        fees = float(closed["fees"].sum() or 0) if closed.height else 0.0
        slip_cost = float(closed["total_slippage_cost"].sum() or 0) if closed.height else 0.0
        exit_stops = closed.filter(pl.col("exit_order_type") == "stop").height if closed.height else 0
        entries = [e for e in entries if chicago_day(e["entry_time"]).year == year]
        nominal = sum(e["nominal_risk_usd"] for e in entries)
        qtys = [e["qty"] for e in entries]
        rsum = float(closed["r_multiple"].sum()) if closed.height else 0.0
        daily_entries = defaultdict(int)
        for e in entries: daily_entries[chicago_day(e["entry_time"])] += 1
        metrics = {"trial_id": label, "status": "completed", "closed_trades": closed.height,
            "gross_pnl_usd": gross, "net_pnl_usd": net, "fees_usd": fees, "slippage_usd": slip_cost,
            "actual_nominal_risk_usd": float(closed["nominal_risk_usd"].sum()) if closed.height else 0.0,
            "actual_nominal_risk_usd_max": float(closed["nominal_risk_usd"].max()) if closed.height else 0.0,
            "trades_over_1000_actual_tick_rounded_trigger_risk": closed.filter(pl.col("nominal_risk_usd") > 1000).height if closed.height else 0,
            "risk_budget_deployment_utilization": (float(closed["nominal_risk_usd"].mean()) / 1000 if closed.height else 0.0),
            "r_sum": rsum, "expectancy_r": rsum / closed.height if closed.height else None,
            "worst_trade_r": float(closed["r_multiple"].min()) if closed.height else None,
            "stop_exit_count_actual_order_type": exit_stops,
            "gap_overshoot_points_max": float(closed["gap_overshoot_points"].max()) if closed.height else 0.0,
            "gap_overshoot_usd_total": float(closed["gap_overshoot_usd"].sum()) if closed.height else 0.0,
            "late_scheduled_market_exits": closed.filter(pl.col("late_market_exit_minutes") > 0).height if closed.height else 0,
            "max_late_market_exit_minutes": float(closed["late_market_exit_minutes"].max()) if closed.height else 0.0,
            "long_short": {side: {"trades": closed.filter(pl.col("direction").str.to_lowercase() == side).height,
                "net_pnl_usd": float(closed.filter(pl.col("direction").str.to_lowercase() == side)["pnl"].sum() or 0)}
                for side in ("long", "short")},
            "gross_minus_net_equals_fees": abs((gross - net) - fees) < 1e-6,
            "native_margin_rejected_orders": result.metrics.get("num_rejected_orders"),
            "ambiguous_events": len([e for e in strategy.ambiguous if chicago_day(datetime.fromisoformat(e["timestamp"])).year == year]),
            "ambiguity_kinds": {k: sum(1 for e in strategy.ambiguous if e["kind"] == k and chicago_day(datetime.fromisoformat(e["timestamp"])).year == year)
                for k in {e["kind"] for e in strategy.ambiguous}},
            "qty_distribution": {str(q): qtys.count(q) for q in sorted(set(qtys))}, "skipped_qty_lt_1": strategy.skipped,
            "entry_contract_sides": sum(qtys), "round_trip_contract_sides_for_closed_trades": 2 * sum(abs(float(x)) for x in closed["quantity"].to_list()) if closed.height else 0,
            "max_entries_per_chicago_session_day": max(daily_entries.values(), default=0),
            "commission_per_contract_per_fill_usd": commission, "slippage_points_per_fill": slip,
            "initial_margin_per_contract_usd": INITIAL_MARGIN, "maintenance_margin_per_contract_usd": MAINTENANCE_MARGIN,
            "native_engine_final_value": result.metrics.get("final_value"),
            "native_engine_open_trades": trades.filter(pl.col("status") != "closed").height if trades.height else 0,
            "strategy_entries": len(entries), "initial_cash_usd": INITIAL_CASH}
        write(path / "metrics.json", metrics); yearsummaries.append(metrics)
        print(f"{year} {label} trades={closed.height} net={net:.2f}", flush=True)
    from importlib.metadata import version
    summary = {"year": year, "status": "completed", "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": [sys.executable, *sys.argv], "runner_sha256": sha(Path(__file__)),
        "frozen_spec_sha256": sha(OUT / "frozen_spec.json"), "source_manifest_sha256": sha(BASE / "source_manifest.json"),
        "quality": quality, "trials": yearsummaries,
        "engine_versions": {"ml4t_backtest": version("ml4t-backtest"), "ml4t_engineer": version("ml4t-engineer")},
        "git_head": __import__("subprocess").check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
        "ending_cash_resets_each_year": True}
    write(ydir / "year_summary.json", summary)
    return summary


if __name__ == "__main__":
    year = int(sys.argv[sys.argv.index("--year") + 1])
    run(year)
