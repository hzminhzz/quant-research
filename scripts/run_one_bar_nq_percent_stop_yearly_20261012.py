"""Run one annual shard of the frozen fixed-percent-stop NQ counterfactual."""
from __future__ import annotations

import gc
import json
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_one_bar_practical_yearly_20261012 as base
import run_one_bar_dukascopy_phase567_20261011 as phase
from ml4t.backtest import Strategy
from ml4t.backtest.types import OrderType

OUT = ROOT / "run_log/one_bar_nq_percent_stop_20261012"
ASSET, MULTIPLIER, TICK = "NQ_PROXY", 20.0, 0.25
STOP_FRACTION = 50 / 14598.25
TZ = ZoneInfo("America/Chicago")


def percent_stop_price(entry_price: float, direction: str) -> float:
    """Return a fixed-fraction stop rounded one tick away from entry."""
    entry = Decimal(str(entry_price))
    fraction = Decimal(str(STOP_FRACTION))
    tick = Decimal("0.25")
    if direction == "long":
        raw = entry * (Decimal(1) - fraction)
        units = (raw / tick).to_integral_value(rounding=ROUND_FLOOR)
    elif direction == "short":
        raw = entry * (Decimal(1) + fraction)
        units = (raw / tick).to_integral_value(rounding=ROUND_CEILING)
    else:
        raise ValueError(f"direction must be 'long' or 'short', got {direction!r}")
    return float(units * tick)


def chicago_session_day(ts: datetime) -> date:
    local = ts.astimezone(TZ)
    return local.date() if local.hour >= 17 else local.date() - timedelta(days=1)


def next_30m_boundary(ts: datetime) -> datetime:
    epoch = int(ts.timestamp())
    return datetime.fromtimestamp((epoch // 1800 + 1) * 1800, tz=timezone.utc)


class PercentStopStrategy(Strategy):
    """B0 entry/exit behavior with only the protective stop changed."""

    def __init__(self, evaluation_end: date):
        self.evaluation_end = evaluation_end
        self.entries_by_day: dict[str, int] = {}
        self.entry_orders = []
        self.stop_order = None
        self.trade = None
        self.max_daily_entries = 0
        self.ambiguous = []
        self.trade_metadata = []

    def on_data(self, timestamp, data, context, broker):
        if chicago_session_day(timestamp) > self.evaluation_end:
            pos = broker.get_position(ASSET)
            active = bool(pos or self.trade or any(
                order and order.status.value == "pending" for order in self.entry_orders))
            if not active:
                return
            item = dict(data[ASSET])
            item["signals"] = {}
            data = {**data, ASSET: item}

        bar = data[ASSET]
        pos = broker.get_position(ASSET)
        qty = float(pos.quantity) if pos else 0.0
        filled_entry_orders = [order for order in self.entry_orders
            if order and order.status.value == "filled"]
        if filled_entry_orders:
            day = chicago_session_day(timestamp).isoformat()
            self.entries_by_day[day] = self.entries_by_day.get(day, 0) + len(filled_entry_orders)
            self.max_daily_entries = max(self.max_daily_entries, self.entries_by_day[day])
            if len(filled_entry_orders) > 1:
                self.ambiguous.append({"timestamp": timestamp.isoformat(),
                    "kind": "both_entry_stops_filled", "fills": len(filled_entry_orders)})
            self.entry_orders = [o for o in self.entry_orders if o and o.status.value == "pending"]

        if qty and self.trade is None:
            day = chicago_session_day(timestamp).isoformat()
            if not filled_entry_orders:
                self.entries_by_day[day] = self.entries_by_day.get(day, 0) + 1
                self.max_daily_entries = max(self.max_daily_entries, self.entries_by_day[day])
            direction = "long" if qty > 0 else "short"
            entry_price = float(pos.entry_price)
            stop = percent_stop_price(entry_price, direction)
            if (qty > 0 and float(bar["low"]) <= stop) or (qty < 0 and float(bar["high"]) >= stop):
                self.ambiguous.append({"timestamp": timestamp.isoformat(),
                    "kind": "entry_and_protective_stop_same_candle", "side": direction,
                    "entry_price": entry_price, "stop_price": stop})
            self.trade = {"entry_time": timestamp, "entry_price": entry_price,
                "side": direction, "stop": stop, "scheduled_exit": next_30m_boundary(timestamp)}
            self.trade_metadata.append({"entry_time": timestamp.isoformat(), "side": direction,
                "quantity": abs(qty), "entry_price": entry_price, "stop_price": stop,
                "stop_fraction": STOP_FRACTION, "stop_gap_points": abs(entry_price - stop)})
            for order in self.entry_orders:
                if order and order.status.value == "pending":
                    broker.cancel_order(order.order_id)
            self.entry_orders.clear()
            self.stop_order = broker.submit_order(ASSET, -qty,
                order_type=OrderType.STOP, stop_price=stop)

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
        if not qty and local.minute in (29, 59):
            for order in self.entry_orders:
                if order and order.status.value == "pending":
                    broker.cancel_order(order.order_id)
            self.entry_orders.clear()
            values = bar.get("signals", {})
            long_stop, short_stop = values.get("next_long_stop"), values.get("next_short_stop")
            entry_day = chicago_session_day(timestamp + timedelta(minutes=1)).isoformat()
            if long_stop is not None and short_stop is not None and self.entries_by_day.get(entry_day, 0) < 2:
                long_stop = round(round(float(long_stop) / TICK) * TICK, 8)
                short_stop = round(round(float(short_stop) / TICK) * TICK, 8)
                self.entry_orders = [
                    broker.submit_order(ASSET, 1, order_type=OrderType.STOP, stop_price=long_stop),
                    broker.submit_order(ASSET, -1, order_type=OrderType.STOP, stop_price=short_stop),
                ]


def run_year(year: int) -> dict:
    from ml4t.backtest.analytics import max_drawdown, sharpe_ratio

    year_dir = OUT / "by_year" / str(year)
    year_dir.mkdir(parents=True, exist_ok=True)
    feed, quality = base.build_year_feed(year)
    (year_dir / "source_quality.json").write_text(json.dumps(quality, indent=2) + "\n")
    eval_end = base.DATA_END if year == base.LAST_YEAR else date(year, 12, 31)
    state: dict = {}

    def strategy_factory():
        state["strategy"] = PercentStopStrategy(eval_end)
        return state["strategy"]

    phase.CausalOneBar = strategy_factory
    phase.OUT = year_dir
    trials = []
    for code, name, commission, slippage in (
        ("PZ", "percent_zero_cost", 0.0, 0.0),
        ("PC", "percent_costed", 2.5, 0.25),
    ):
        print(f"YEAR={year} ENGINE_START {name} {datetime.now(timezone.utc).isoformat()}", flush=True)
        phase.run_native(feed, name, commission, slippage)
        trial_dir = year_dir / name
        trades = pl.read_csv(trial_dir / "trades.csv", try_parse_dates=True)
        fills = pl.read_csv(trial_dir / "fills.csv", try_parse_dates=True)
        native_metrics = json.loads((trial_dir / "metrics.json").read_text())
        if trades.height:
            evaluation = trades.with_columns(pl.col("entry_time").map_elements(
                base._entry_year, return_dtype=pl.Int32).alias("entry_session_year"))
            evaluation = evaluation.filter(pl.col("entry_session_year") == year)
        else:
            evaluation = trades.with_columns(pl.lit(None, dtype=pl.Int32).alias("entry_session_year"))
        evaluation.write_csv(trial_dir / "evaluation_trades.csv")
        pl.DataFrame(state["strategy"].trade_metadata, schema={
            "entry_time": pl.String, "side": pl.String, "quantity": pl.Float64,
            "entry_price": pl.Float64, "stop_price": pl.Float64,
            "stop_fraction": pl.Float64, "stop_gap_points": pl.Float64,
        }, orient="row").write_csv(trial_dir / "entry_context.csv")
        closed = evaluation.filter(pl.col("status") == "closed")
        annual_pnl = float(closed["pnl"].sum() or 0.0)
        stop_exit_times = fills.filter((pl.col("order_type") == "stop") &
            (pl.col("exit_reason") == "signal"))["timestamp"].to_list()
        if closed.height:
            stop_count = closed.filter(pl.col("exit_time").is_in(stop_exit_times)).height
        else:
            stop_count = 0
        dailies = pl.read_csv(trial_dir / "daily_equity.csv", try_parse_dates=True).sort("timestamp")
        if dailies.height:
            dailies = dailies.with_columns(pl.col("equity").shift(1)
                .fill_null(1_000_000.0).alias("prior_equity"))
            dailies = dailies.with_columns((pl.col("equity") / pl.col("prior_equity") - 1)
                .alias("daily_return"))
            annual_days = dailies.filter(pl.col("timestamp").dt.year() == year)
            daily_returns, equity_values = annual_days["daily_return"].to_list(), annual_days["equity"].to_list()
            annual_sharpe = sharpe_ratio(daily_returns, annualize=True) if daily_returns else None
            annual_dd = max_drawdown(equity_values)[0] if equity_values else None
        else:
            annual_sharpe = annual_dd = None
        ambiguity = []
        for event in state["strategy"].ambiguous:
            if base._entry_year(datetime.fromisoformat(event["timestamp"])) == year:
                ambiguity.append(event)
        year_metrics = {
            "trial_id": code, "name": name, "status": "completed",
            "closed_trades": closed.height, "net_pnl_usd": annual_pnl,
            "average_trade_pnl_usd": float(closed["pnl"].mean()) if closed.height else None,
            "protective_stop_exits": stop_count,
            "protective_stop_rate": stop_count / closed.height if closed.height else None,
            "native_daily_equity_sharpe_utc": annual_sharpe,
            "native_daily_equity_max_drawdown_utc": annual_dd,
            "native_engine_final_value_including_warmup": native_metrics.get("native_engine_metrics", {}).get("final_value"),
            "ending_native_open_trades": native_metrics.get("open_trades_at_end"),
            "same_minute_ambiguity_count": len(ambiguity),
            "max_entries_per_chicago_session_day": state["strategy"].max_daily_entries,
            "commission_per_fill_usd": commission,
            "adverse_slippage_points_per_fill": slippage,
            "one_contract_each_entry": True,
        }
        (trial_dir / "evaluation_metrics.json").write_text(json.dumps(year_metrics, indent=2) + "\n")
        if name == "percent_costed":
            (year_dir / "ambiguity_report.json").write_text(json.dumps({
                "year": year, "events": ambiguity,
                "classification": "INCONCLUSIVE_SAME_MINUTE_OHLC",
                "native_engine_fills_retained": True,
            }, indent=2, default=str) + "\n")
        trials.append(year_metrics)
        print(f"YEAR={year} ENGINE_DONE {name} trades={closed.height} pnl={annual_pnl:.2f}", flush=True)
        del trades, fills, dailies, evaluation, closed
        gc.collect()

    del feed
    return {"year": year, "status": "completed", "quality": quality, "trials": trials,
        "ending_strategy_state": {"open_entry_orders": sum(bool(o and o.status.value == "pending")
            for o in state["strategy"].entry_orders),
            "open_protective_order": bool(state["strategy"].stop_order and
                state["strategy"].stop_order.status.value == "pending"),
            "tracked_trade": state["strategy"].trade is not None}}


if __name__ == "__main__":
    year = int(sys.argv[1])
    if year not in base.eligible_years():
        raise SystemExit(f"unsupported year {year}")
    summary = run_year(year)
    target = OUT / "by_year" / str(year) / "worker_summary.json"
    target.write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(json.dumps(summary, default=str), flush=True)
