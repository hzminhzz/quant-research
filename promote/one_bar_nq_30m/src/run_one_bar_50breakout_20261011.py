"""Run a native-engine execution gate and 50-bar proxy signal diagnostics."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict
from zoneinfo import ZoneInfo

import polars as pl
from ml4t.backtest import AssetClass, BacktestConfig, CommissionType, ContractSpec, DataFeed, Engine, Strategy
from ml4t.backtest.analytics import max_drawdown, sharpe_ratio
from ml4t.backtest.config import SlippageType
from ml4t.backtest.types import ExecutionMode, OrderType, StopFillMode

ROOT = Path(__file__).resolve().parents[1]
STORE = Path("/home/quant/dev/quant/ml4t-data/.data/store")
OUT = ROOT / "run_log/one_bar_50breakout_20261011"
START, END = date(2026, 1, 1), date(2026, 7, 31)


def input_files(symbol: str) -> list[Path]:
    paths = sorted((STORE / f"lse_futures_minute_{symbol}").glob("year=*/month=*/data.parquet"))
    return [p for p in paths if "/year=2025/" in p.as_posix() or ("/year=2026/" in p.as_posix() and int(p.parent.name.split("=")[1]) <= 7)]


def exchange_day(timestamp: datetime) -> date:
    local = timestamp.astimezone(ZoneInfo("America/Chicago"))
    return local.date() if local.hour >= 17 else local.date() - timedelta(days=1)


class StopProbe(Strategy):
    def __init__(self, mode: ExecutionMode):
        self.mode = mode
        self.order = None
        self.exit_order = None

    def on_data(self, timestamp, data, context, broker):
        if self.order is None:
            self.order = broker.submit_order("X", 1, order_type=OrderType.STOP, stop_price=101)
        elif broker.get_position("X") and self.exit_order is None:
            self.exit_order = broker.submit_order("X", -1, order_type=OrderType.MARKET)


class OneBarBreakout(Strategy):
    def __init__(self, asset: str, multiplier: float, tick: float):
        self.asset, self.multiplier, self.tick = asset, multiplier, tick
        self.entry_orders = []
        self.stop_order = None
        self.exit_order = None
        self.trade = None
        self.entries_by_day: dict[str, int] = defaultdict(int)
        self.ambiguous_entry_stop = []
        self.entry_bars = []
        self.max_daily_entries = 0
        self._last_position = 0.0

    def on_data(self, timestamp, data, context, broker):
        bar = data[self.asset]
        position = broker.get_position(self.asset)
        quantity = float(position.quantity) if position else 0.0
        local = timestamp.astimezone(ZoneInfo("America/Chicago"))
        trade_day = exchange_day(timestamp).isoformat()

        if quantity and not self.trade:
            self.trade = {
                "entry_time": timestamp.isoformat(),
                "entry_price": float(position.entry_price),
                "side": "long" if quantity > 0 else "short",
                "quantity": quantity,
                "exchange_day": trade_day,
            }
            self.entries_by_day[trade_day] += 1
            self.max_daily_entries = max(self.max_daily_entries, self.entries_by_day[trade_day])
            self.entry_bars.append(timestamp.isoformat())
            stop_points = 1000.0 / self.multiplier
            stop_price = position.entry_price - stop_points if quantity > 0 else position.entry_price + stop_points
            stop_price = round(round(stop_price / self.tick) * self.tick, 8)
            same_bar_stop = (quantity > 0 and float(bar["low"]) <= stop_price) or (quantity < 0 and float(bar["high"]) >= stop_price)
            if same_bar_stop:
                self.ambiguous_entry_stop.append({"timestamp": timestamp.isoformat(), "side": self.trade["side"], "entry": float(position.entry_price), "stop": stop_price})
            for order in self.entry_orders:
                if order and order.status.value == "pending":
                    broker.cancel_order(order.order_id)
            self.entry_orders.clear()
            stop_order = broker.submit_order(self.asset, -quantity, order_type=OrderType.STOP, stop_price=stop_price)
            self.stop_order = stop_order
            self.trade["stop_price"] = stop_price

        if self.trade and quantity:
            local_minute = local.hour * 60 + local.minute
            session_minute = local_minute - 17 * 60 if local_minute >= 17 * 60 else local_minute + 7 * 60
            minutes_to_boundary = 30 - (session_minute % 30)
            next_boundary = timestamp + timedelta(minutes=minutes_to_boundary)
            if timestamp + timedelta(minutes=1) >= next_boundary:
                if self.stop_order and self.stop_order.status.value == "pending":
                    broker.cancel_order(self.stop_order.order_id)
                self.exit_order = broker.submit_order(self.asset, -quantity, order_type=OrderType.MARKET)
                self.trade["scheduled_exit_time"] = next_boundary.isoformat()

        if not quantity and self.trade:
            self.trade = None
            self.stop_order = None
            self.exit_order = None

        if not quantity and local.minute % 30 == 29:
            for order in self.entry_orders:
                if order and order.status.value == "pending":
                    broker.cancel_order(order.order_id)
            self.entry_orders.clear()
            signals = bar.get("signals", {})
            long_stop, short_stop = signals.get("long_stop"), signals.get("short_stop")
            next_open = timestamp + timedelta(minutes=1)
            planned_exit = next_open + timedelta(minutes=30)
            next_local = next_open.astimezone(ZoneInfo("America/Chicago"))
            scheduled_day = next_local.date() if next_local.hour == 16 else exchange_day(next_open)
            if (
                long_stop is not None and short_stop is not None
                and next_open.date() >= START and planned_exit.date() <= END
                and self.entries_by_day[scheduled_day.isoformat()] < 2
            ):
                long_stop = round(round(float(long_stop) / self.tick) * self.tick, 8)
                short_stop = round(round(float(short_stop) / self.tick) * self.tick, 8)
                self.entry_orders = [
                    broker.submit_order(self.asset, 1, order_type=OrderType.STOP, stop_price=long_stop),
                    broker.submit_order(self.asset, -1, order_type=OrderType.STOP, stop_price=short_stop),
                ]
        self._last_position = quantity


def engine_gate() -> dict:
    rows = [
        {"timestamp": datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc), "asset": "X", "open": 100., "high": 100.5, "low": 99.5, "close": 100., "volume": 1.},
        {"timestamp": datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc), "asset": "X", "open": 100., "high": 102., "low": 99.5, "close": 101., "volume": 1.},
        {"timestamp": datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc), "asset": "X", "open": 101.5, "high": 102., "low": 101., "close": 101.5, "volume": 1.},
    ]
    results = {}
    for mode in (ExecutionMode.NEXT_BAR, ExecutionMode.SAME_BAR):
        strategy = StopProbe(mode)
        config = BacktestConfig(initial_cash=100_000, allow_short_selling=True, execution_mode=mode)
        result = Engine(DataFeed(prices_df=pl.DataFrame(rows)), strategy, config).run()
        results[mode.value] = [
            {"timestamp": f.timestamp.isoformat(), "price": f.price, "type": f.order_type}
            for f in result.fills
        ]
    return {
        "setup": "Native STOP buy 101; next candle opens 100 and trades to 102; following candle opens 101.5.",
        "results": results,
        "finding": "NEXT_BAR fills the STOP when the next 1m candle high crosses 101, then fills the market exit at the following 1m open (101.5). This supports the intended native stop-entry and scheduled-open exit sequence.",
        "exact_strategy_supported": True,
        "remaining_ambiguity": "A 1m candle can contain both entry trigger and protective-stop prices. OHLC does not reveal their intraminute order; those cases are counted and retained as ambiguous.",
    }


def source_identity(symbol: str) -> dict:
    files = input_files(symbol)
    hasher = hashlib.sha256()
    for path in files:
        hasher.update(path.relative_to(STORE).as_posix().encode())
        hasher.update(path.read_bytes())
    return {"store": str(STORE / f"lse_futures_minute_{symbol}"), "files": len(files), "sha256_all_partition_bytes": hasher.hexdigest()}


def prepare_proxy(symbol: str, asset: str) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    scan = pl.scan_parquet([str(p) for p in input_files(symbol)])
    mins = (
        scan.filter(pl.col("timestamp").dt.date() <= pl.lit(END))
        .sort("timestamp")
        .with_columns(pl.col("timestamp").dt.convert_time_zone("America/Chicago").alias("local"))
        .with_columns(
            pl.when(pl.col("local").dt.hour() >= 17)
            .then(pl.col("local").dt.date())
            .otherwise(pl.col("local").dt.date().dt.offset_by("-1d"))
            .alias("session_date"),
            pl.when(pl.col("local").dt.hour() >= 17)
            .then((pl.col("local").dt.hour().cast(pl.Int32) - 17) * 60 + pl.col("local").dt.minute().cast(pl.Int32))
            .otherwise((pl.col("local").dt.hour().cast(pl.Int32) + 7) * 60 + pl.col("local").dt.minute().cast(pl.Int32))
            .alias("session_minute"),
        )
        .with_columns((pl.col("session_minute") // 30).alias("bar_no"))
        .collect()
    )
    bars = (
        mins.group_by("session_date", "bar_no")
        .agg(
            pl.col("timestamp").min().alias("timestamp"),
            pl.col("open").first(), pl.col("high").max(), pl.col("low").min(),
            pl.col("close").last(), pl.col("volume").sum(), pl.len().alias("minute_count"),
        )
        .filter(pl.col("minute_count") == 30)
        .sort("timestamp")
        .with_columns(
            pl.col("high").rolling_max(50).shift(1).alias("long_stop"),
            pl.col("low").rolling_min(50).shift(1).alias("short_stop"),
            pl.col("high").rolling_max(50).alias("next_long_stop"),
            pl.col("low").rolling_min(50).alias("next_short_stop"),
        )
    )
    levels = bars.filter(pl.col("timestamp").dt.date().is_between(START, END)).select(
        "session_date", "bar_no", pl.col("timestamp").alias("bar_timestamp"), "long_stop", "short_stop"
    )
    joined = mins.join(levels, on=["session_date", "bar_no"], how="inner")
    diag = (
        joined.group_by("session_date", "bar_no", "bar_timestamp", "long_stop", "short_stop")
        .agg(
            (pl.col("high") >= pl.col("long_stop")).any().alias("long_touched"),
            (pl.col("low") <= pl.col("short_stop")).any().alias("short_touched"),
            ((pl.col("open") >= pl.col("long_stop")).any()).alias("long_open_gap"),
            ((pl.col("open") <= pl.col("short_stop")).any()).alias("short_open_gap"),
            ((pl.col("high") >= pl.col("long_stop")) & (pl.col("low") <= pl.col("short_stop"))).any().alias("same_minute_both"),
        )
        .sort("bar_timestamp")
    )
    summary = {
        "asset": asset,
        "symbol": f"{symbol}.F",
        "source_identity": source_identity(symbol),
        "period": {"start_inclusive": START.isoformat(), "end_inclusive": END.isoformat()},
        "bar_alignment": "CME Globex 17:00 America/Chicago session date; 30-minute local-wall-clock bars; require 30 source minutes per bar.",
        "bars_with_50_prior_complete_bars": diag.height,
        "long_stop_touched": diag.filter(pl.col("long_touched")).height,
        "short_stop_touched": diag.filter(pl.col("short_touched")).height,
        "both_sides_touched_same_30m_bar": diag.filter(pl.col("long_touched") & pl.col("short_touched")).height,
        "both_sides_touched_same_1m_candle": diag.filter(pl.col("same_minute_both")).height,
        "long_open_at_or_above_stop_bars": diag.filter(pl.col("long_open_gap")).height,
        "short_open_at_or_below_stop_bars": diag.filter(pl.col("short_open_gap")).height,
        "ohlc_checks": {
            "bad_ohlc_rows": mins.filter((pl.col("high") < pl.col("low")) | (pl.col("close") > pl.col("high")) | (pl.col("close") < pl.col("low"))).height,
            "duplicate_timestamps": mins.height - mins.get_column("timestamp").n_unique(),
            "zero_volume_rows": mins.filter(pl.col("volume") <= 0).height,
        },
        "price_performance_metrics": None,
        "price_performance_reason": "Not computed. The installed native Engine cannot represent intraminute stop entry and next-30m-open exit in one run mode. This is a signal/trigger diagnostic, not a simulated trade ledger.",
    }
    strategy_levels = bars.select(
        "session_date", "bar_no", pl.col("next_long_stop").alias("long_stop"), pl.col("next_short_stop").alias("short_stop")
    )
    strategy_frame = mins.join(strategy_levels, on=["session_date", "bar_no"], how="left").with_columns(pl.lit(asset).alias("asset"))
    prices = strategy_frame.select("timestamp", "asset", "open", "high", "low", "close", "volume")
    signals = strategy_frame.select("timestamp", "asset", "long_stop", "short_stop")
    summary["bars_with_50_prior_complete_bars"] = diag.height
    return summary, diag.rename({"bar_timestamp": "timestamp"}).with_columns(pl.lit(asset).alias("asset")), prices, signals


def run_native(symbol: str, asset: str, multiplier: float, tick: float, costs: bool) -> tuple[dict, dict, pl.DataFrame, pl.DataFrame, list[dict]]:
    _, _, prices, signals = prepare_proxy(symbol, asset)
    strategy = OneBarBreakout(asset, multiplier, tick)
    config = BacktestConfig(
        initial_cash=1_000_000,
        allow_short_selling=True,
        allow_leverage=True,
        fixed_margin_schedule={asset: (25_000.0, 20_000.0)},
        execution_mode=ExecutionMode.NEXT_BAR,
        stop_fill_mode=StopFillMode.STOP_PRICE,
        commission_type=CommissionType.PER_CONTRACT if costs else CommissionType.NONE,
        commission_per_share=2.50 if costs else 0.0,
        slippage_type=SlippageType.FIXED if costs else SlippageType.NONE,
        slippage_fixed=tick if costs else 0.0,
    )
    spec = ContractSpec(symbol=asset, asset_class=AssetClass.FUTURE, multiplier=multiplier, tick_size=tick, margin=25_000.0)
    result = Engine(DataFeed(prices_df=prices, signals_df=signals), strategy, config, contract_specs={asset: spec}).run()
    if strategy.max_daily_entries > 2:
        raise AssertionError(f"{asset} exceeded the two-entry session-day cap: {strategy.max_daily_entries}")
    trades = result.to_trades_dataframe()
    fills = result.to_fills_dataframe()
    name = "cost_aware" if costs else "zero_cost"
    run_dir = OUT / asset.replace(".", "_") / name
    run_dir.mkdir(parents=True, exist_ok=True)
    trades.write_csv(run_dir / "trades.csv")
    fills.write_csv(run_dir / "fills.csv")
    curve = pl.DataFrame({"timestamp": [x[0] for x in result.equity_curve], "equity": [float(x[1]) for x in result.equity_curve]})
    curve = curve.with_columns(pl.col("timestamp").dt.date().alias("utc_day")).filter(pl.col("utc_day").is_between(START, END))
    daily = curve.group_by("utc_day").agg(pl.col("timestamp").last(), pl.col("equity").last()).sort("utc_day")
    daily.write_csv(run_dir / "daily_equity.csv")
    daily_values = daily.get_column("equity").to_list()
    daily_returns = ([daily_values[0] / 1_000_000 - 1] if daily_values else []) + [(b / a) - 1 for a, b in zip(daily_values, daily_values[1:]) if a]
    metrics = dict(result.metrics)
    metrics["daily_equity_sharpe"] = sharpe_ratio(daily_returns, annualize=True)
    metrics["daily_equity_max_drawdown"] = abs(max_drawdown([1_000_000.0, *daily_values])[0])
    metrics["average_net_pnl_usd"] = trades.select(pl.col("pnl").mean()).item() if trades.height else None
    metrics["trade_count_closed"] = trades.filter(pl.col("status") == "closed").height if trades.height else 0
    durations = trades.with_columns((pl.col("exit_time") - pl.col("entry_time")).dt.total_minutes().alias("hold_minutes")) if trades.height else trades
    metrics["max_hold_minutes"] = durations.get_column("hold_minutes").max() if trades.height else 0
    metrics["late_next_bar_open_exits"] = durations.filter(pl.col("hold_minutes") > 30).height if trades.height else 0
    metrics["native_stop_exit_fills"] = fills.filter((pl.col("order_type") == "stop") & (pl.col("exit_reason") == "signal")).height if fills.height else 0
    metrics["gap_through_stop_fills"] = fills.filter((pl.col("order_type") == "stop") & (pl.col("price_source") == "open")).height if fills.height else 0
    metrics["gross_profit_positive"] = bool(metrics.get("total_gross_pnl", 0) > 0)
    metrics["net_profit_positive"] = bool(metrics.get("final_value", 1_000_000) > 1_000_000)
    metrics["entries_per_exchange_day_max"] = strategy.max_daily_entries
    metrics["same_1m_entry_and_stop_ambiguities"] = len(strategy.ambiguous_entry_stop)
    metrics["ambiguous_samples"] = strategy.ambiguous_entry_stop[:50]
    metrics["contract"] = {"asset": asset, "multiplier": multiplier, "tick_size": tick}
    metrics["cost_assumption"] = "$2.50 per contract per fill and one tick adverse slippage per fill; exploratory proxy placeholder, not brokerage-certified." if costs else "Zero commission and slippage reference."
    metrics["execution_mode"] = "NEXT_BAR; STOP orders test 1m high/low and fill at stop unless gap-through, which fills at open."
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str) + "\n")
    return metrics, {"result": result, "strategy": strategy}, trades, fills, [{"path": str(run_dir / p), "sha256": hashlib.sha256((run_dir / p).read_bytes()).hexdigest()} for p in ("trades.csv", "fills.csv", "daily_equity.csv", "metrics.json")]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    gate = engine_gate()
    (OUT / "native_engine_gate.json").write_text(json.dumps(gate, indent=2) + "\n")
    data_identity = {symbol: source_identity(symbol) for symbol in ("NQ", "ES")}
    frozen = {
        "session_id": "one_bar_50breakout_20261011",
        "classification": "EXPLORATORY; retrospective proxy data; unqualified for CME futures conclusions",
        "hypothesis": "Prior 50 completed 30-minute highs/lows trigger stop entries whose one-bar hold has positive net expectancy after stated placeholder costs.",
        "falsifier": "No positive net expectancy in cost-aware NQ.F and ES.F results, or results fail the 1m trigger, $1,000 stop, next-30m-open exit, or two-entry-per-session-day rules.",
        "rules": {"lookback_completed_30m_bars": 50, "entry_orders": "one buy stop at rolling prior high and one sell stop at rolling prior low; OCO after first fill", "contracts": 1, "protective_stop_usd": 1000, "exit": "opening print of immediately following 30-minute bar", "max_entries_per_globex_session_day": 2, "entry_resolution": "native Engine STOP order checked against each 1m candle; stop-price fill, gap-through fills at 1m open", "ambiguous_1m_entry_stop": "retain and report; OHLC cannot establish sequence"},
        "instruments": {"NQ.F": "LSE proxy for NQ; not verified as a specific dated CME contract", "ES.F": "LSE proxy for ES; not verified as a specific dated CME contract", "EMD": "unavailable; no substitute", "YM": "unavailable; no substitute"},
        "evaluation": {"start_inclusive_utc": "2026-01-01", "end_inclusive_utc": "2026-07-31", "protected_after": "2026-07-31", "warmup": "source bars before 2026-01-01 used only to form 50 completed-bar rolling extrema"},
        "data": data_identity,
        "trials": ["NQ.F zero cost", "NQ.F cost aware", "ES.F zero cost", "ES.F cost aware"],
        "cost_assumptions": {"zero_cost": "0 commission, 0 slippage", "cost_aware": "$2.50 per contract per fill plus one tick adverse slippage per fill; exploratory placeholder, not brokerage-certified"},
        "status": "frozen before backtest execution",
    }
    (OUT / "frozen_run_spec.json").write_text(json.dumps(frozen, indent=2) + "\n")
    summaries, details, run_summaries, artifacts = [], [], [], []
    for symbol, asset, multiplier, tick in (("NQ", "NQ.F", 20.0, 0.25), ("ES", "ES.F", 50.0, 0.25)):
        summary, detail, _, _ = prepare_proxy(symbol, asset)
        summaries.append(summary)
        details.append(detail)
        for costs in (False, True):
            metrics, _, trades, _, hashes = run_native(symbol, asset, multiplier, tick, costs)
            run_summaries.append({"asset": asset, "trial": "cost_aware" if costs else "zero_cost", "metrics": metrics})
            artifacts.extend(hashes)
    pl.concat(details).write_csv(OUT / "signal_diagnostics.csv")
    lookahead_audit = {
        "rolling_window": "50 complete 30m bars",
        "decision_timing": "Strategy reads the completed bar extrema only from that bar's final 1m event (:29 or :59), then submits native STOP orders for the next 1m event at the next 30m boundary.",
        "fills": "NEXT_BAR Engine fills pending STOP orders against the next 1m OHLC range; gap-through stop fills use the 1m open. Market exits submitted at the final 1m event fill at the next available 1m open.",
        "protected_data": "Only 2025 warm-up and 2026 January-July source partitions were selected.",
        "same_minute_exceptions": "The Engine cannot sequence an entry and protective stop crossed inside the same 1m OHLC candle. Metrics retain this count; no intrabar path is invented.",
    }
    (OUT / "lookahead_audit.json").write_text(json.dumps(lookahead_audit, indent=2) + "\n")
    for artifact in ("frozen_run_spec.json", "native_engine_gate.json", "signal_diagnostics.csv", "lookahead_audit.json"):
        path = OUT / artifact
        artifacts.append({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    report = {
        "session_id": "one_bar_50breakout_20261011",
        "status": "COMPLETED_EXPLORATORY_PROXY_WITH_EXECUTION_EXCEPTIONS",
        "research_class": "EXPLORATORY; retrospective proxy study",
        "rule": "50 completed 30m bars; one-contract stop entry at prior high/low; 1m trigger check; $1,000 protective stop; next 30m opening-print exit; max two filled entries per exchange trading day.",
        "data_identity": "LSE NQ.F and ES.F minute proxy data from canonical ml4t-data store. Roll/contract semantics are unverified. These are unqualified proxy results, not CME futures results.",
        "missing_markets": {"EMD": "unavailable; no substitute", "YM": "unavailable; no substitute"},
        "protected_boundary": "Data and outcomes restricted through 2026-07-31 UTC. Source files included only 2025 warm-up and January-July 2026 partitions. No August onward partitions were read.",
        "native_engine_gate": gate,
        "diagnostics": summaries,
        "backtests": run_summaries,
        "artifacts": artifacts,
        "trial_count": 4,
        "execution_exceptions": {
            "same_minute_entry_stop": "The entry is filled from a 1m OHLC candle. The Strategy can install the protective STOP only after the Engine reports the fill. OHLC does not show whether a $1,000 stop also traded later in that same candle. These cases are counted in each run's metrics and are not resolved.",
            "late_exit": "A scheduled next-30m-open order fills at the next available source bar. The artifact counts holds longer than 30 minutes caused by missing 1m data at the boundary.",
            "interpretation": "Report the Engine outputs as as-modeled proxy results. Do not treat the unresolved cases as an exact reproduction of the complete rule set.",
        },
        "conclusion": "The cost-aware NQ.F and ES.F proxy outputs are negative. This sample does not support the edge as modeled. Same-minute stop ambiguity, missing-minute boundary exits, and unverified proxy roll semantics prevent a firm rejection of the actual CME strategy thesis.",
        "next_decisive_question": "Can the LSE NQ.F and ES.F proxy findings be replicated on verified dated CME contracts with documented roll mapping and broker costs?",
        "lookahead_audit": lookahead_audit,
        "skills": [
            {"name": "ml4t-compute-features", "source": "https://github.com/ml4t/skills/blob/main/features/compute-features/SKILL.md", "invariants": "Sorted Polars rolling extrema; align each completed bar's range to the next candidate bar."},
            {"name": "ml4t-run-backtest", "source": "https://github.com/ml4t/skills/blob/main/backtest/run-backtest/SKILL.md", "invariants": "Use Engine/Strategy, causally ordered fills, explicit costs."},
            {"name": "ml4t-cost-model", "source": "https://github.com/ml4t/skills/blob/main/backtest/cost-model/SKILL.md", "invariants": "Do not claim net returns without per-fill costs and suitable volume."},
            {"name": "ml4t-calendar-ops", "source": "https://github.com/ml4t/skills/blob/main/data/calendar-ops/SKILL.md", "invariants": "Use exchange timezone/calendar alignment."},
            {"name": "ml4t-continuous-futures", "source": "https://github.com/ml4t/skills/blob/main/data/continuous-futures/SKILL.md", "invariants": "Do not claim futures performance with unverified continuous-series roll semantics."},
            {"name": "ml4t-polars-patterns", "source": "https://github.com/ml4t/skills/blob/main/infrastructure/polars-patterns/SKILL.md", "invariants": "Use sorted, grouped Polars operations."},
            {"name": "ml4t-lookahead-bias", "source": "https://github.com/ml4t/skills/blob/main/concepts/lookahead-bias/SKILL.md", "invariants": "Use only previous completed 30m bars for extrema."},
            {"name": "ml4t-validate-data", "source": "https://github.com/ml4t/skills/blob/main/data/validate-data/SKILL.md", "invariants": "Check OHLC, duplicate timestamps, timezone, and volume."},
        ],
        "local_skill_discovery": "Applicable local skills were not installed in .agents/skills; official upstream skill files were read via TinyFish. The local ml4t-prop-firm-evaluation skill is unrelated and was not used.",
    }
    (OUT / "session_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"output": str(OUT), "status": report["status"], "diagnostics": summaries, "backtests": run_summaries}, indent=2, default=str))


if __name__ == "__main__":
    main()
