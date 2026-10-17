"""Causal follow-up audit for the frozen one-bar Dukascopy proxy study."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
from ml4t.backtest import (
    AssetClass, BacktestConfig, CommissionType, ContractSpec, DataFeed, Engine, Strategy,
)
from ml4t.backtest.analytics import max_drawdown, sharpe_ratio
from ml4t.backtest.config import SlippageType
from ml4t.backtest.types import ExecutionMode, OrderType, StopFillMode

ROOT = Path(__file__).resolve().parents[1]
STORE = Path("/home/quant/dev/quant/ml4t-data/.data/store/index_minute_NQ")
START, END = date(2013, 1, 1), date(2026, 7, 14)
ASSET, MULTIPLIER, NQ_TICK = "NQ_PROXY", 20.0, 0.25
TZ = ZoneInfo("America/Chicago")
OUT = ROOT / "run_log/one_bar_dukascopy_phase567_20261011"
BASE = ROOT / "run_log/one_bar_dukascopy_2013_2026_20261011"
INITIAL_CASH = 1_000_000.0
STOP_POINTS = 1000.0 / MULTIPLIER
SESSION_BLOCKS = {
    "2013-2017": (2013, 2017), "2018-2020": (2018, 2020),
    "2021-2023": (2021, 2023), "2024-2025": (2024, 2025),
    "2026-01-Jul14": (2026, 2026),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def input_files() -> list[Path]:
    return sorted(
        p for p in STORE.glob("year=*/month=*/data.parquet")
        if p.parent.parent.name.split("=")[1] < "2026"
        or (p.parent.parent.name == "year=2026" and int(p.parent.name.split("=")[1]) <= 7)
    )


def prepare_causal_feed(files: list[Path]) -> tuple[pl.DataFrame, dict]:
    """Build session-anchored complete bars without future-availability fields."""
    raw = (
        pl.scan_parquet([str(p) for p in files])
        .filter(pl.col("timestamp").dt.date().is_between(START, END))
        .select("timestamp", "open", "high", "low", "close", "volume")
        .sort("timestamp")
        .collect()
        .with_columns(pl.col("timestamp").dt.replace_time_zone("UTC"))
    )
    local = pl.col("timestamp").dt.convert_time_zone("America/Chicago")
    minute = local.dt.hour() * 60 + local.dt.minute()
    raw = raw.with_columns(
        local.alias("local"),
        pl.when(minute >= 17 * 60).then(local.dt.date())
        .otherwise(local.dt.date().dt.offset_by("-1d")).alias("session_date"),
    )
    session_dates = raw["session_date"].unique().sort().to_list()
    starts = pl.DataFrame({
        "session_date": session_dates,
        "session_start_utc": [datetime(d.year, d.month, d.day, 17, tzinfo=TZ).astimezone(timezone.utc) for d in session_dates],
    })
    raw = raw.join(starts, on="session_date", how="left").with_columns(
        ((pl.col("timestamp") - pl.col("session_start_utc")).dt.total_minutes() // 30).alias("bar_no")
    )
    bars = (
        raw.group_by("session_date", "bar_no")
        .agg(
            pl.col("timestamp").min().alias("bar_start"),
            pl.col("open").first().alias("bar_open"),
            pl.col("high").max().alias("bar_high"),
            pl.col("low").min().alias("bar_low"),
            pl.col("close").last().alias("bar_close"),
            pl.len().alias("n"), pl.col("timestamp").n_unique().alias("unique_n"),
        )
        .with_columns(((pl.col("n") == 30) & (pl.col("unique_n") == 30)).alias("complete"))
        .filter(pl.col("complete"))
        .sort("bar_start")
        .with_columns(
            pl.col("bar_high").rolling_max(50).alias("next_long_stop"),
            pl.col("bar_low").rolling_min(50).alias("next_short_stop"),
        )
        .with_columns(
            ((pl.col("bar_high") - pl.col("bar_low")) / pl.col("bar_close")).alias("range_proxy")
        )
    )
    feed = (
        raw.join(bars.select("session_date", "bar_no", "next_long_stop", "next_short_stop", "range_proxy"),
                 on=["session_date", "bar_no"], how="inner")
        .with_columns(pl.lit(ASSET).alias("asset"))
        .drop("local", "session_start_utc", strict=False)
        .sort("timestamp")
    )
    time_links = feed.select(pl.col("timestamp"), pl.col("timestamp").shift(-1).alias("observed_next_timestamp"))
    boundary_orders = feed.filter(
        pl.col("timestamp").dt.convert_time_zone("America/Chicago").dt.minute().is_in([29, 59])
        & pl.col("next_long_stop").is_not_null()
    ).join(time_links, on="timestamp", how="left")
    missing_next = boundary_orders.filter(
        pl.col("observed_next_timestamp") != pl.col("timestamp") + pl.duration(minutes=1)
    )
    return feed, {
        "rows": raw.height,
        "complete_30m_bars": bars.height,
        "incomplete_30m_bars_excluded": int(raw.select(pl.struct("session_date", "bar_no").n_unique()).item()) - bars.height,
        "bar_boundary_order_decisions": boundary_orders.height,
        "decisions_without_immediate_next_minute_data": missing_next.height,
        "missing_next_minute_examples": missing_next.select("timestamp", "observed_next_timestamp").head(100).to_dicts(),
        "future_availability_gate": "removed; decisions use current completed history only",
        "ohlcv_validation": {
            "duplicate_timestamps": raw.height - raw["timestamp"].n_unique(),
            "null_price_values": sum(raw[c].null_count() for c in ("open", "high", "low", "close")),
            "invalid_ohlc_rows": raw.filter((pl.col("high") < pl.col("low")) | (pl.col("close") > pl.col("high")) | (pl.col("close") < pl.col("low"))).height,
        },
        "source_timestamps": {"first": feed["timestamp"].min().isoformat(), "last": feed["timestamp"].max().isoformat()},
    }


def session_date(ts: datetime) -> date:
    local = ts.astimezone(TZ)
    return local.date() if local.hour >= 17 else local.date() - timedelta(days=1)


def next_boundary(ts: datetime) -> datetime:
    epoch = int(ts.timestamp())
    return datetime.fromtimestamp((epoch // 1800 + 1) * 1800, tz=timezone.utc)


class CausalOneBar(Strategy):
    def __init__(self):
        self.entries_by_day: dict[str, int] = defaultdict(int)
        self.entry_orders = []
        self.stop_order = None
        self.trade = None
        self.max_daily_entries = 0
        self.ambiguous = []
        self.trade_metadata = []

    def on_data(self, timestamp, data, context, broker):
        bar = data[ASSET]
        pos = broker.get_position(ASSET)
        qty = float(pos.quantity) if pos else 0.0
        filled_entry_orders = [order for order in self.entry_orders if order and order.status.value == "filled"]
        if filled_entry_orders:
            day = session_date(timestamp).isoformat()
            self.entries_by_day[day] += len(filled_entry_orders)
            self.max_daily_entries = max(self.max_daily_entries, self.entries_by_day[day])
            if len(filled_entry_orders) > 1:
                self.ambiguous.append({"timestamp": timestamp.isoformat(), "kind": "both_entry_stops_filled",
                                       "fills": len(filled_entry_orders)})
            self.entry_orders = [order for order in self.entry_orders if order and order.status.value == "pending"]
        if qty and self.trade is None:
            key = session_date(timestamp).isoformat()
            if not filled_entry_orders:
                self.entries_by_day[key] += 1
                self.max_daily_entries = max(self.max_daily_entries, self.entries_by_day[key])
            direction = "long" if qty > 0 else "short"
            stop = float(pos.entry_price) - STOP_POINTS if qty > 0 else float(pos.entry_price) + STOP_POINTS
            stop = round(round(stop / NQ_TICK) * NQ_TICK, 8)
            if (qty > 0 and float(bar["low"]) <= stop) or (qty < 0 and float(bar["high"]) >= stop):
                self.ambiguous.append({"timestamp": timestamp.isoformat(), "kind": "entry_and_protective_stop_same_candle", "side": direction,
                                       "entry_price": float(pos.entry_price), "stop_price": stop})
            self.trade = {"entry_time": timestamp, "side": direction, "stop": stop,
                          "scheduled_exit": next_boundary(timestamp),
                          "volatility_proxy": bar.get("signals", {}).get("range_proxy")}
            self.trade_metadata.append({"entry_time": timestamp.isoformat(), "side": direction,
                                        "volatility_proxy": self.trade["volatility_proxy"]})
            for order in self.entry_orders:
                if order and order.status.value == "pending":
                    broker.cancel_order(order.order_id)
            self.entry_orders.clear()
            self.stop_order = broker.submit_order(ASSET, -qty, order_type=OrderType.STOP, stop_price=stop)

        if qty and self.trade:
            submit_at = self.trade["scheduled_exit"] - timedelta(minutes=1)
            if timestamp >= submit_at:
                if self.stop_order and self.stop_order.status.value == "pending":
                    broker.cancel_order(self.stop_order.order_id)
                broker.submit_order(ASSET, -qty, order_type=OrderType.MARKET)
                self.trade["exit_submitted_at"] = timestamp

        if not qty and self.trade:
            self.trade = None
            self.stop_order = None

        local = timestamp.astimezone(TZ)
        decision_time = local.minute in (29, 59)
        if not qty and decision_time:
            for order in self.entry_orders:
                if order and order.status.value == "pending":
                    broker.cancel_order(order.order_id)
            self.entry_orders.clear()
            values = bar.get("signals", {})
            long_stop, short_stop = values.get("next_long_stop"), values.get("next_short_stop")
            day = session_date(timestamp + timedelta(minutes=1)).isoformat()
            if long_stop is not None and short_stop is not None and self.entries_by_day[day] < 2:
                long_stop = round(round(float(long_stop) / NQ_TICK) * NQ_TICK, 8)
                short_stop = round(round(float(short_stop) / NQ_TICK) * NQ_TICK, 8)
                self.entry_orders = [
                    broker.submit_order(ASSET, 1, order_type=OrderType.STOP, stop_price=long_stop),
                    broker.submit_order(ASSET, -1, order_type=OrderType.STOP, stop_price=short_stop),
                ]


def run_native(feed: pl.DataFrame, trial: str, commission: float, slippage_points: float) -> dict:
    strategy = CausalOneBar()
    prices = feed.select("timestamp", "asset", "open", "high", "low", "close", "volume")
    signals = feed.select("timestamp", "asset", "next_long_stop", "next_short_stop", "range_proxy")
    config = BacktestConfig(
        initial_cash=INITIAL_CASH, allow_short_selling=True, allow_leverage=True,
        fixed_margin_schedule={ASSET: (25_000.0, 20_000.0)}, execution_mode=ExecutionMode.NEXT_BAR,
        stop_fill_mode=StopFillMode.STOP_PRICE,
        commission_type=CommissionType.PER_SHARE if commission else CommissionType.NONE,
        commission_per_share=commission,
        slippage_type=SlippageType.FIXED if slippage_points else SlippageType.NONE,
        slippage_fixed=slippage_points,
    )
    spec = ContractSpec(symbol=ASSET, asset_class=AssetClass.FUTURE, multiplier=MULTIPLIER,
                        tick_size=NQ_TICK, margin=25_000.0)
    result = Engine(DataFeed(prices_df=prices, signals_df=signals), strategy, config,
                    contract_specs={ASSET: spec}).run()
    path = OUT / trial
    path.mkdir(parents=True, exist_ok=True)
    trades, fills = result.to_trades_dataframe(), result.to_fills_dataframe()
    trades = mark_utc(trades, ("entry_time", "exit_time"))
    fills = mark_utc(fills, ("timestamp",))
    trades.write_csv(path / "trades.csv")
    fills.write_csv(path / "fills.csv")
    equity = pl.DataFrame({"timestamp": [t for t, _ in result.equity_curve],
                           "equity": [float(v) for _, v in result.equity_curve]})
    daily = equity.with_columns(pl.col("timestamp").dt.date().alias("utc_day")) \
        .group_by("utc_day").agg(pl.col("timestamp").last(), pl.col("equity").last()).sort("utc_day")
    daily.write_csv(path / "daily_equity.csv")
    closed = trades.filter(pl.col("status") == "closed") if trades.height else trades
    gross = float(closed["gross_pnl"].sum() or 0.0) if closed.height else 0.0
    pnl = float(closed["pnl"].sum() or 0.0) if closed.height else 0.0
    final_value = float(result.metrics.get("final_value", INITIAL_CASH))
    daily_values = daily["equity"].to_list()
    returns = [b / a - 1 for a, b in zip([INITIAL_CASH, *daily_values[:-1]], daily_values) if a]
    ambiguous = len(strategy.ambiguous)
    ambiguous_times = [datetime.fromisoformat(row["timestamp"]) for row in strategy.ambiguous]
    ambiguous_pnl = float(closed.filter(pl.col("entry_time").is_in(ambiguous_times))["pnl"].sum() or 0.0) if closed.height else 0.0
    conservative = pnl - ambiguous_pnl + ambiguous * (-1000.0 - 2 * commission - 2 * slippage_points * MULTIPLIER)
    entry_gap = fills.filter(
        (pl.col("order_type") == "stop") & (pl.col("exit_reason") == "") &
        (((pl.col("side") == "buy") & (pl.col("reference_price") > pl.col("stop_price"))) |
         ((pl.col("side") == "sell") & (pl.col("reference_price") < pl.col("stop_price"))))
    ).height if fills.height else 0
    stop_gap = fills.filter(
        (pl.col("order_type") == "stop") & (pl.col("exit_reason") == "signal") &
        (((pl.col("side") == "sell") & (pl.col("reference_price") < pl.col("stop_price"))) |
         ((pl.col("side") == "buy") & (pl.col("reference_price") > pl.col("stop_price"))))
    ).height if fills.height else 0
    entry_gap_usd = float(fills.filter(
        (pl.col("order_type") == "stop") & (pl.col("exit_reason") == "") &
        (((pl.col("side") == "buy") & (pl.col("reference_price") > pl.col("stop_price"))) |
         ((pl.col("side") == "sell") & (pl.col("reference_price") < pl.col("stop_price"))))
    ).select(((pl.col("reference_price") - pl.col("stop_price")).abs() * pl.col("quantity").abs() * MULTIPLIER).sum()).item() or 0.0) if fills.height else 0.0
    stop_gap_usd = float(fills.filter(
        (pl.col("order_type") == "stop") & (pl.col("exit_reason") == "signal") &
        (((pl.col("side") == "sell") & (pl.col("reference_price") < pl.col("stop_price"))) |
         ((pl.col("side") == "buy") & (pl.col("reference_price") > pl.col("stop_price"))))
    ).select(((pl.col("reference_price") - pl.col("stop_price")).abs() * pl.col("quantity").abs() * MULTIPLIER).sum()).item() or 0.0) if fills.height else 0.0
    stop_exit_times = fills.filter((pl.col("order_type") == "stop") & (pl.col("exit_reason") == "signal"))["timestamp"].to_list() if fills.height else []
    expected = closed.with_columns(
        pl.col("entry_time").map_elements(next_boundary, return_dtype=pl.Datetime("us", "UTC")).alias("expected_exit_time")
    ).with_columns(pl.col("exit_time").is_in(stop_exit_times).alias("protective_stop_exit")) if closed.height else closed
    late_exits = expected.filter(~pl.col("protective_stop_exit") & (pl.col("exit_time") != pl.col("expected_exit_time"))).height if expected.height else 0
    entry_fills_frame = fills.filter(pl.col("order_type") == "stop") if fills.height else fills
    multi_entry_timestamps = entry_fills_frame.group_by("timestamp").len().filter(pl.col("len") > 1).height if entry_fills_frame.height else 0
    library_metrics = {key: result.metrics.get(key) for key in (
        "initial_cash", "final_value", "total_return", "num_trades", "win_rate", "profit_factor",
        "total_commission", "total_slippage", "total_costs", "num_fills", "num_rejected_orders",
    )}
    metrics = {
        "trial": trial, "engine": "ml4t.backtest Engine, NEXT_BAR native STOP/MARKET",
        "native_engine_metrics": library_metrics, "closed_trades": closed.height,
        "open_trades_at_end": trades.filter(pl.col("status") != "closed").height if trades.height else 0,
        "sum_trade_pnl_usd": pnl, "equity_change_usd": final_value - INITIAL_CASH,
        "ledger_equity_difference_usd": pnl - (final_value - INITIAL_CASH),
        "gross_pnl_usd": gross, "commissions_usd": float(fills["commission"].sum() or 0.0) if fills.height else 0.0,
        "slippage_points_sum": float(fills["slippage"].sum() or 0.0) if fills.height else 0.0,
        "slippage_cost_usd": float((fills.select((pl.col("slippage") * pl.col("quantity").abs() * MULTIPLIER).sum()).item() or 0.0)) if fills.height else 0.0,
        "fees_and_slippage_usd": float((fills["commission"].sum() or 0.0) + (fills.select((pl.col("slippage") * pl.col("quantity").abs() * MULTIPLIER).sum()).item() or 0.0)) if fills.height else 0.0,
        "trade_ledger_slippage_cost_usd": float(closed["total_slippage_cost"].sum() or 0.0) if closed.height else 0.0,
        "fill_trade_slippage_reconciliation_difference_usd": (float((fills.select((pl.col("slippage") * pl.col("quantity").abs() * MULTIPLIER).sum()).item() or 0.0) - (closed["total_slippage_cost"].sum() or 0.0)) if fills.height and closed.height else 0.0),
        "gross_minus_net_pnl_usd": gross - pnl,
        "commission_reconciliation_difference_usd": gross - pnl - (fills["commission"].sum() or 0.0) if fills.height else gross - pnl,
        "entry_fills": int(fills.filter((pl.col("order_type") == "stop") & (pl.col("exit_reason") == "")).height) if fills.height else 0,
        "multiple_entry_fills_same_minute": multi_entry_timestamps,
        "fill_count": fills.height,
        "max_entries_per_chicago_session_day": strategy.max_daily_entries,
        "same_minute_entry_stop_ambiguities": ambiguous,
        "worst_case_same_minute_pnl_usd": conservative,
        "expected_next_boundary_exit_mismatches": late_exits,
        "daily_equity_sharpe_library": sharpe_ratio(returns, annualize=True),
        "daily_equity_max_drawdown_library": max_drawdown([INITIAL_CASH, *daily_values])[0],
        "commission_per_fill_usd": commission,
        "adverse_slippage_points_per_fill": slippage_points,
        "entry_gap_triggers": entry_gap,
        "entry_gap_conservative_price_improvement_usd": entry_gap_usd,
        "protective_stop_gap_through_fills": stop_gap,
        "protective_stop_gap_loss_beyond_trigger_usd": stop_gap_usd,
        "ambiguous_examples": strategy.ambiguous[:100],
    }
    pl.DataFrame(strategy.trade_metadata).write_csv(path / "entry_context.csv")
    (path / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str) + "\n")
    return metrics


def mark_utc(frame: pl.DataFrame, columns: tuple[str, ...]) -> pl.DataFrame:
    return frame.with_columns(*(pl.col(c).dt.replace_time_zone("UTC") for c in columns
        if c in frame.columns and isinstance(frame.schema[c], pl.Datetime) and frame.schema[c].time_zone is None))


def audit_saved_trial(trial: str, commission: float, slippage_points: float) -> dict:
    path = OUT / trial
    trades = pl.read_csv(path / "trades.csv", try_parse_dates=True)
    fills = pl.read_csv(path / "fills.csv", try_parse_dates=True)
    daily = pl.read_csv(path / "daily_equity.csv", try_parse_dates=True)
    metrics = json.loads((path / "metrics.json").read_text())
    native = metrics.get("native_engine_metrics", {})
    metrics["native_engine_metrics"] = {key: native.get(key) for key in (
        "initial_cash", "final_value", "total_return", "num_trades", "win_rate",
        "profit_factor", "total_commission", "total_slippage", "total_costs",
        "num_fills", "num_rejected_orders",
    )}
    metrics.pop("cost_reconciliation_difference_usd", None)
    metadata = metrics.pop("trade_metadata", None)
    if metadata is not None:
        pl.DataFrame(metadata).write_csv(path / "entry_context.csv")
    closed = trades.filter(pl.col("status") == "closed")
    base_entries = fills.filter((pl.col("order_type") == "stop") & (pl.col("exit_reason") == ""))
    stop_events = fills.filter(pl.col("order_type") == "stop").group_by("timestamp").len()
    double_events = stop_events.filter(pl.col("len") > 1)
    extra_entries = int((double_events["len"] - 1).sum() or 0)
    event_times = base_entries["timestamp"].to_list() + [ts for ts, count in zip(double_events["timestamp"], double_events["len"], strict=True) for _ in range(int(count) - 1)]
    entry_days = pl.DataFrame({"timestamp": event_times}).with_columns(
        pl.col("timestamp").dt.convert_time_zone("America/Chicago").alias("local")
    ).with_columns(pl.when(pl.col("local").dt.hour() >= 17).then(pl.col("local").dt.date())
        .otherwise(pl.col("local").dt.date().dt.offset_by("-1d")).alias("session_date")) \
        .group_by("session_date").len() if event_times else pl.DataFrame(schema={"session_date": pl.Date, "len": pl.UInt32})
    entry_by_day_max = int(entry_days["len"].max() or 0) if entry_days.height else 0
    stop_exit_times = fills.filter((pl.col("order_type") == "stop") & (pl.col("exit_reason") == "signal"))["timestamp"].to_list()
    expected = closed.with_columns(pl.col("entry_time").map_elements(next_boundary,
        return_dtype=pl.Datetime("us", "UTC")).alias("expected_exit_time")) \
        .with_columns(pl.col("exit_time").is_in(stop_exit_times).alias("protective_stop_exit")) if closed.height else closed
    late = expected.filter(~pl.col("protective_stop_exit") & (pl.col("exit_time") != pl.col("expected_exit_time"))).height if expected.height else 0
    ambiguity_rows = metrics.get("ambiguous_examples", [])
    ambiguity_times = {datetime.fromisoformat(row["timestamp"]) for row in ambiguity_rows}
    ambiguity_times.update(ts for ts in double_events["timestamp"].to_list())
    ambiguous_pnl = float(closed.filter(pl.col("entry_time").is_in(list(ambiguity_times)))["pnl"].sum() or 0.0) if closed.height else 0.0
    ambiguous_count = len(ambiguity_times)
    full_tick_adverse_bound = float(closed["pnl"].sum() or 0.0) - ambiguous_pnl + ambiguous_count * (-1000.0 - 2 * commission - 2 * slippage_points * MULTIPLIER)
    slip_usd = float(fills.select((pl.col("slippage") * pl.col("quantity").abs() * MULTIPLIER).sum()).item() or 0.0) if fills.height else 0.0
    commission_usd = float(fills["commission"].sum() or 0.0) if fills.height else 0.0
    metrics.update({
        "actual_entry_order_fills": base_entries.height + extra_entries,
        "simultaneous_opposite_stop_fill_events": double_events.height,
        "simultaneous_opposite_stop_fill_examples": double_events.head(100).to_dicts(),
        "extra_stop_fills_beyond_one_oco_entry": extra_entries,
        "max_actual_entry_fills_per_chicago_session_day": entry_by_day_max,
        "max_entries_per_chicago_session_day": entry_by_day_max,
        "session_days_over_two_entry_fill_limit": int(entry_days.filter(pl.col("len") > 2).height) if entry_days.height else 0,
        "same_minute_ambiguous_event_count_including_oco": ambiguous_count,
        "worst_case_same_minute_pnl_usd": full_tick_adverse_bound,
        "expected_next_boundary_exit_mismatches_excluding_protective_stops": late,
        "commissions_usd": commission_usd,
        "slippage_cost_usd": slip_usd,
        "fees_and_slippage_usd": commission_usd + slip_usd,
        "trade_ledger_slippage_cost_usd": float(closed["total_slippage_cost"].sum() or 0.0) if closed.height else 0.0,
        "commission_reconciliation_difference_usd": float(closed["fees"].sum() or 0.0) - commission_usd if closed.height else -commission_usd,
        "fill_trade_slippage_reconciliation_difference_usd": slip_usd - (float(closed["total_slippage_cost"].sum() or 0.0) if closed.height else 0.0),
        "daily_equity_sharpe_library": sharpe_ratio([
            b / a - 1 for a, b in zip([INITIAL_CASH, *daily["equity"].to_list()[:-1]], daily["equity"].to_list()) if a
        ], annualize=True),
        "daily_equity_max_drawdown_library": max_drawdown([INITIAL_CASH, *daily["equity"].to_list()])[0],
        "actual_entry_fills_per_day_audit": entry_days.sort("session_date").to_dicts(),
    })
    (path / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str) + "\n")
    return metrics


def summarize_blocks(trades: pl.DataFrame, daily: pl.DataFrame, trial: str) -> dict:
    closed = trades.filter(pl.col("status") == "closed")
    if closed.is_empty():
        return {"trial": trial, "blocks": {}, "by_year": []}
    stamped = closed.with_columns(pl.col("exit_time").dt.year().alias("year"))
    annual = stamped.group_by("year").agg(pl.len().alias("trades"), pl.col("pnl").sum().alias("pnl_usd"),
        pl.col("pnl").mean().alias("avg_trade_usd"), pl.col("pnl").median().alias("median_trade_usd"))
    days = stamped.with_columns(pl.col("exit_time").dt.date().alias("exit_day")) \
        .group_by("exit_day").agg(pl.col("pnl").sum().alias("day_pnl"))
    top_trade_share = float(stamped.sort("pnl", descending=True).head(10)["pnl"].sum() / stamped["pnl"].sum()) if stamped["pnl"].sum() else None
    top_day_share = float(days.sort("day_pnl", descending=True).head(10)["day_pnl"].sum() / days["day_pnl"].sum()) if days["day_pnl"].sum() else None
    daily = daily.sort("timestamp").with_columns(
        pl.col("equity").shift(1).fill_null(INITIAL_CASH).alias("prior_equity")
    ).with_columns((pl.col("equity") / pl.col("prior_equity") - 1).alias("daily_return"))
    blocks = {}
    for label, (lo, hi) in SESSION_BLOCKS.items():
        part = stamped.filter(pl.col("year").is_between(lo, hi))
        daily_part = daily.filter(pl.col("timestamp").dt.year().is_between(lo, hi))
        daily_returns = daily_part["daily_return"].to_list()
        period_equity = ([float(daily_part["prior_equity"][0])] + daily_part["equity"].to_list()) if daily_part.height else []
        blocks[label] = {"trades": part.height, "pnl_usd": float(part["pnl"].sum() or 0.0),
                         "avg_trade_usd": float(part["pnl"].mean()) if part.height else None,
                         "average_entry_index_level": float(part["entry_price"].mean()) if part.height else None,
                         "avg_trade_bps_of_entry_notional": float((part["pnl"] / (part["entry_price"] * MULTIPLIER)).mean() * 10000) if part.height else None,
                         "daily_equity_sharpe": sharpe_ratio(daily_returns, annualize=True),
                         "daily_equity_max_drawdown": max_drawdown(period_equity)[0] if period_equity else 0.0}
    local = stamped.with_columns(pl.col("entry_time").dt.convert_time_zone("America/Chicago").alias("local_entry"))
    local = local.with_columns(pl.when((pl.col("local_entry").dt.weekday() <= 5) &
        (pl.col("local_entry").dt.hour().cast(pl.Int32) * 60 + pl.col("local_entry").dt.minute()).is_between(8 * 60 + 30, 15 * 60))
        .then(pl.lit("Chicago_RTH_proxy")).otherwise(pl.lit("overnight_or_weekend")).alias("session_bucket"))
    by_side = stamped.group_by("direction").agg(pl.len().alias("trades"), pl.col("pnl").sum().alias("pnl_usd"), pl.col("pnl").mean().alias("avg_trade_usd"))
    by_session = local.group_by("session_bucket").agg(pl.len().alias("trades"), pl.col("pnl").sum().alias("pnl_usd"), pl.col("pnl").mean().alias("avg_trade_usd"))
    vol_path = OUT / trial / "entry_context.csv"
    vol = pl.read_csv(vol_path, try_parse_dates=True) if vol_path.exists() else pl.DataFrame()
    volatility = []
    if vol.height and "volatility_proxy" in vol.columns:
        if vol.schema.get("entry_time") == pl.String:
            vol = vol.with_columns(pl.col("entry_time").str.to_datetime(time_zone="UTC", strict=False))
        q = vol["volatility_proxy"].quantile(1/3), vol["volatility_proxy"].quantile(2/3)
        vol = vol.with_columns(pl.when(pl.col("volatility_proxy") <= q[0]).then(pl.lit("low"))
            .when(pl.col("volatility_proxy") <= q[1]).then(pl.lit("mid")).otherwise(pl.lit("high")).alias("range_tercile"))
        volatility = vol.join(stamped.select("entry_time", "pnl"), on="entry_time", how="inner").group_by("range_tercile").agg(
            pl.len().alias("trades"), pl.col("pnl").sum().alias("pnl_usd"), pl.col("pnl").mean().alias("avg_trade_usd")
        ).to_dicts()
    yearly_daily = []
    for year in sorted(annual["year"].to_list()):
        part = daily.filter(pl.col("timestamp").dt.year() == year)
        yearly_daily.append({"year": year, "daily_equity_sharpe": sharpe_ratio(part["daily_return"].to_list(), annualize=True),
            "daily_equity_max_drawdown": max_drawdown([float(part["prior_equity"][0]), *part["equity"].to_list()])[0] if part.height else 0.0})
    annual = annual.join(pl.DataFrame(yearly_daily), on="year", how="left")
    return {"trial": trial, "blocks": blocks, "by_year": annual.sort("year").to_dicts(),
            "long_short": by_side.to_dicts(), "session_descriptive": by_session.to_dicts(),
            "posthoc_volatility_range_terciles": volatility,
            "confidence_intervals": "Not calculated. No session-cluster bootstrap implementation was available and trade independence is not assumed.",
            "concentration": {"top_10_trade_pnl_share": top_trade_share, "top_10_session_day_pnl_share": top_day_share,
                              "worst_trade_usd": float(stamped["pnl"].min()), "worst_session_day_usd": float(days["day_pnl"].min())}}


def render_tearsheet() -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(3, 1, figsize=(11, 10), constrained_layout=True)
    for name, label in (("causal_zero_cost", "Zero cost"), ("causal_full_tick", "Full tick + commission")):
        daily = pl.read_csv(OUT / name / "daily_equity.csv", try_parse_dates=True).sort("timestamp")
        equity = [INITIAL_CASH, *daily["equity"].to_list()]
        timestamps = [daily["timestamp"][0] - timedelta(days=1), *daily["timestamp"].to_list()]
        axes[0].plot(timestamps, equity, linewidth=1.0, label=label)
        peak = []
        high = equity[0]
        for value in equity:
            high = max(high, value)
            peak.append((value / high) - 1)
        axes[1].plot(timestamps, peak, linewidth=0.9, label=label)
    blocks = json.loads((OUT / "phase567_results.json").read_text())["phase5_full_tick"]["blocks"]
    axes[2].bar(list(blocks), [value["pnl_usd"] for value in blocks.values()], color=["#b44" if value["pnl_usd"] < 0 else "#287a52" for value in blocks.values()])
    axes[0].set(title="One-bar breakout — Dukascopy Nasdaq CFD proxy", ylabel="Equity (USD)")
    axes[1].set(ylabel="Drawdown", title="Daily equity drawdown")
    axes[2].set(ylabel="Net PnL (USD)", title="Frozen chronological blocks — full-tick causal replay")
    for ax in axes:
        ax.grid(True, alpha=0.25)
    axes[0].legend()
    path = OUT / "phase567_tearsheet.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def reconcile_historical_baseline() -> dict:
    results = {}
    for name in ("zero_cost", "cost_aware"):
        path = BASE / name
        trades = pl.read_csv(path / "trades.csv", try_parse_dates=True)
        fills = pl.read_csv(path / "fills.csv", try_parse_dates=True)
        metrics = json.loads((path / "metrics.json").read_text())
        status = (BASE / "exit_code").read_text().strip()
        results[name] = {"closed_trades": trades.filter(pl.col("status") == "closed").height,
            "sum_trade_pnl_usd": float(trades.filter(pl.col("status") == "closed")["pnl"].sum()),
            "metrics_net_profit_usd": metrics.get("net_profit_usd"),
            "ledger_difference_usd": metrics.get("ledger_reconciliation_difference_usd"),
            "fill_count": fills.height, "fees_usd": float(fills["commission"].sum()),
            "slippage_points_sum": float(fills["slippage"].sum()),
            "slippage_cost_usd": float(fills.select((pl.col("slippage") * pl.col("quantity").abs() * MULTIPLIER).sum()).item() or 0.0),
            "reported_cost_assumption": metrics.get("cost_assumption"),
            "wrapper_exit_code": status}
    return results


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    spec = {
        "status": "frozen_before_new_results", "source": "baseline frozen Dukascopy BID CFD proxy, through 2026-07-14 only",
        "rule_changes": "none; remove future entry_valid filter; exit at next observed event if boundary missing and record mismatch",
        "trials": [
            {"id": "T1", "name": "historical_zero_cost_reference", "status": "completed_reference_only", "source_artifact": "run_log/one_bar_dukascopy_2013_2026_20261011/zero_cost"},
            {"id": "T2", "name": "historical_quarter_tick_reference", "status": "completed_reference_only", "source_artifact": "run_log/one_bar_dukascopy_2013_2026_20261011/cost_aware"},
            {"id": "T3", "name": "causal_zero_cost", "status": "planned", "commission_per_fill": 0, "slippage_points_per_fill": 0},
            {"id": "T4", "name": "causal_full_tick", "status": "planned", "commission_per_fill_usd": 2.5, "slippage_points_per_fill": 0.25},
            {"id": "T5", "name": "same_minute_adverse_bound", "status": "diagnostic_from_T4", "method": "replace each ambiguous trade result by -$1,000 plus per-fill T4 costs; no tick path inference"},
            {"id": "T6", "name": "delayed_fill_1m", "status": "not_run", "reason": "lower priority; no trading-time data supports resolving source outages"},
        ],
        "protected_holdout": "No data after 2026-07-14 read by the analysis or strategy run.",
    }
    (OUT / "frozen_trial_matrix.json").write_text(json.dumps(spec, indent=2) + "\n")
    baseline = reconcile_historical_baseline()
    files = input_files()
    source_manifest_path = BASE / "source_manifest.json"
    source_identity = sha256(source_manifest_path)
    frozen = json.loads((BASE / "frozen_spec.json").read_text())
    if source_identity != frozen["data"]["source_manifest_sha256"] or len(files) != frozen["data"]["partitions"]:
        raise ValueError("Source manifest identity or partition count differs from the frozen baseline")
    manifest = json.loads(source_manifest_path.read_text())
    for file, record in zip(files, manifest, strict=True):
        if file.relative_to(STORE).as_posix() != record["path"] or sha256(file) != record["sha256"]:
            raise ValueError(f"Source partition changed after the baseline freeze: {file}")
    feed, quality = prepare_causal_feed(files)
    quality["source_manifest_sha256"] = source_identity
    quality["source_partitions"] = len(files)
    quality["baseline_status"] = baseline
    (OUT / "causal_source_quality.json").write_text(json.dumps(quality, indent=2, default=str) + "\n")
    (OUT / "causal_zero_cost_started.json").write_text(json.dumps({"pid": __import__("os").getpid(), "started_utc": datetime.now(timezone.utc).isoformat()}))
    print("ENGINE_START causal_zero_cost", flush=True)
    zero = run_native(feed, "causal_zero_cost", 0.0, 0.0)
    zero = audit_saved_trial("causal_zero_cost", 0.0, 0.0)
    spec["trials"][2]["status"] = "completed"
    print("ENGINE_DONE causal_zero_cost", flush=True)
    print("ENGINE_START causal_full_tick", flush=True)
    full = run_native(feed, "causal_full_tick", 2.50, NQ_TICK)
    full = audit_saved_trial("causal_full_tick", 2.50, NQ_TICK)
    spec["trials"][3]["status"] = "completed"
    print("ENGINE_DONE causal_full_tick", flush=True)
    (OUT / "frozen_trial_matrix.json").write_text(json.dumps(spec, indent=2) + "\n")
    results = {"historical_reference": baseline, "causal_zero_cost": zero, "causal_full_tick": full,
               "phase5_zero_cost": summarize_blocks(pl.read_csv(OUT / "causal_zero_cost/trades.csv", try_parse_dates=True), pl.read_csv(OUT / "causal_zero_cost/daily_equity.csv", try_parse_dates=True), "causal_zero_cost"),
               "phase5_full_tick": summarize_blocks(pl.read_csv(OUT / "causal_full_tick/trades.csv", try_parse_dates=True), pl.read_csv(OUT / "causal_full_tick/daily_equity.csv", try_parse_dates=True), "causal_full_tick")}
    (OUT / "phase567_results.json").write_text(json.dumps(results, indent=2, default=str) + "\n")
    render_tearsheet()
    hashes = {p.relative_to(ROOT).as_posix(): sha256(p) for p in sorted(OUT.rglob("*")) if p.is_file()}
    (OUT / "artifact_hashes.json").write_text(json.dumps(hashes, indent=2) + "\n")
    print(json.dumps({"status": "COMPLETED_EXPLORATORY", "causal_zero_cost_pnl": zero["sum_trade_pnl_usd"],
        "causal_full_tick_pnl": full["sum_trade_pnl_usd"], "trades": full["closed_trades"],
        "entry_valid_removed": True, "phase5_blocks": results["phase5_full_tick"]["blocks"]}, indent=2), flush=True)


if __name__ == "__main__":
    main()
