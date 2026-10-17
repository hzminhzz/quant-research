"""Frozen one-rule aggressive taker-flow exhaustion MVP (no model fitting or search).

The data represent COMPLETE bars indexed by BAR START. Submit one full
additional bar after the completed signal; fill NEXT_BAR OPEN.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
from typing import Any

import polars as pl
from ml4t.backtest import Strategy, Engine, DataFeed, BacktestConfig
from ml4t.backtest.config import ShareType, CommissionType, SlippageType, ExecutionPrice
from ml4t.backtest.types import ExecutionMode
from ml4t.backtest.analytics.equity import EquityCurve

ROOT = Path(__file__).resolve().parents[1]
SESSION = "taker_flow_exhaustion_mvp_20261011_v1"
OUT = ROOT / "run_log" / SESSION
SYMBOLS = ("BTCUSDT", "ETHUSDT")
WARMUP = datetime(2025, 11, 1, tzinfo=UTC)
START = datetime(2026, 1, 1, tzinfo=UTC)
END = datetime(2026, 8, 1, tzinfo=UTC)
INITIAL_CASH = 500.0
PRICE_PATHS = {
    sym: ROOT / f"data/processed/crypto_tsmom_flow_inputs_20261008/{sym.lower()}_1h.parquet"
    for sym in SYMBOLS
}
FUNDING_PATHS = {
    sym: ROOT / f"data/processed/crypto_tsmom_flow_inputs_20261008_v4/{sym.lower()}_funding.parquet"
    for sym in SYMBOLS
}


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def to_utc(value: datetime) -> datetime:
    """ml4t trade ledgers report UTC-naive timestamps."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def crosses_observed_settlement(
    entry: datetime, exit_: datetime, settlements: list[datetime]
) -> bool:
    start, end = to_utc(entry), to_utc(exit_)
    return any(start <= time < end for time in settlements)


def overlaps_scheduled_funding(entry: datetime, exit_: datetime) -> bool:
    """Known fixed 00/08/16 UTC settlement schedule, without future observations."""
    start, end = to_utc(entry), to_utc(exit_)
    first = start.replace(minute=0, second=0, microsecond=0)
    while first.hour % 8 != 0:
        first += timedelta(hours=1)
    return first < end  # if entry is exactly settlement hour, skip


def compute_flow_panel(raw: pl.DataFrame) -> pl.DataFrame:
    """Grouped native Polars expressions, with prior-only 720h/24h baselines."""
    return (
        raw.sort(["symbol", "timestamp"])
        .with_columns(
            flow_imbalance=pl.when(pl.col("quote_volume") > 0)
            .then(2 * pl.col("taker_buy_quote_volume") / pl.col("quote_volume") - 1)
            .otherwise(None),
            candle_return=pl.col("close") / pl.col("open") - 1,
        )
        .with_columns(
            prior_abs_flow_p95=pl.col("flow_imbalance")
            .abs()
            .rolling_quantile(quantile=0.95, window_size=720, min_samples=720)
            .shift(1).over("symbol"),
            prior_24h_avg_quote=pl.col("quote_volume")
            .rolling_mean(window_size=24, min_samples=24)
            .shift(1).over("symbol"),
        )
        .with_columns(
            signal=pl.when(
                pl.col("flow_imbalance").is_not_null()
                & pl.col("prior_abs_flow_p95").is_not_null()
                & (pl.col("flow_imbalance").abs() >= pl.col("prior_abs_flow_p95"))
                & (pl.col("quote_volume") >= pl.col("prior_24h_avg_quote"))
                & (pl.col("flow_imbalance") * pl.col("candle_return") > 0)
            )
            .then(-pl.col("flow_imbalance").sign())
            .otherwise(0)
            .cast(pl.Int8),
        )
    )


def prepare_inputs() -> tuple[pl.DataFrame, pl.DataFrame, dict, dict]:
    frames = []
    fund_events: dict[str, list[datetime]] = {}
    stats: dict[str, Any] = {}
    for sym in SYMBOLS:
        raw = (
            pl.scan_parquet(PRICE_PATHS[sym])
            .filter((pl.col("timestamp") >= WARMUP) & (pl.col("timestamp") < END))
            .collect()
        )
        if raw.is_empty() or raw["timestamp"].n_unique() != raw.height:
            raise ValueError(f"{sym}: empty/duplicate source bars")
        if raw["timestamp"].dtype.time_zone != "UTC":
            raise ValueError(f"{sym}: timestamps must be UTC aware")
        if raw.filter(
            (pl.col("open") <= 0)
            | (pl.col("high") < pl.col("low"))
            | (pl.col("close") > pl.col("high"))
            | (pl.col("close") < pl.col("low"))
            | (pl.col("quote_volume") < 0)
            | (pl.col("taker_buy_quote_volume") < 0)
            | (pl.col("taker_buy_quote_volume") > pl.col("quote_volume"))
            | (pl.col("minute_count") != 60)
            | (~pl.col("close").is_finite())
            | (~pl.col("quote_volume").is_finite())
        ).height:
            raise ValueError(f"{sym}: invalid price/volume or incomplete 60-minute candles")
        valid_hours = raw.filter(pl.col("timestamp") >= START).sort("timestamp")
        expected = pl.datetime_range(START, END - timedelta(hours=1), interval="1h", eager=True)
        if valid_hours["timestamp"].to_list() != expected.to_list():
            raise ValueError(f"{sym}: incomplete development hourly grid")
        frames.append(raw)
        f = (
            pl.scan_parquet(FUNDING_PATHS[sym])
            .filter((pl.col("timestamp") >= START) & (pl.col("timestamp") < END))
            .select("timestamp", "funding_rate", "funding_interval_hours")
            .collect().sort("timestamp")
        )
        if f.is_empty() or f["timestamp"].n_unique() != f.height:
            raise ValueError(f"{sym}: invalid funding event schedule")
        if f.filter(
            (pl.col("funding_interval_hours") != 8)
            | (~pl.col("funding_rate").is_finite())
        ).height:
            raise ValueError(f"{sym}: varying funding cadence or missing funding rates")
        # Verified 8h schedule: align each event at 0/8/16 UTC with millisecond offset.
        if any(t.hour not in (0, 8, 16) or t.minute != 0 for t in f["timestamp"].to_list()):
            raise ValueError(f"{sym}: unexpected funding event wall-clock time")
        fund_events[sym] = f["timestamp"].to_list()
        stats[sym] = {
            "development_bars": valid_hours.height,
            "first_bar": str(valid_hours["timestamp"][0]),
            "last_bar": str(valid_hours["timestamp"][-1]),
            "funding_events": f.height,
        }
    panel = compute_flow_panel(pl.concat(frames))
    candidates = panel.filter(
        (pl.col("timestamp") >= START)
        & (pl.col("timestamp") < END)
        & (pl.col("signal") != 0)
    ).sort("timestamp", "symbol")
    cand_rows = []
    skipped = {"settlement_schedule": 0, "last_hours": 0}
    for r in candidates.iter_rows(named=True):
        signal_hour = r["timestamp"]
        submit = signal_hour + timedelta(hours=1)
        entry = signal_hour + timedelta(hours=2)
        exit_ = entry + timedelta(hours=4)
        if exit_ >= END:
            skipped["last_hours"] += 1
            continue
        if overlaps_scheduled_funding(entry, exit_):
            skipped["settlement_schedule"] += 1
            continue
        cand_rows.append({
            "symbol": r["symbol"],
            "signal_bar_timestamp": signal_hour,
            "submit_timestamp": submit,
            "entry_timestamp": entry,
            "exit_timestamp": exit_,
            "imbalance": float(r["flow_imbalance"]),
            "prior_abs_flow_p95": float(r["prior_abs_flow_p95"]),
            "quote_volume": float(r["quote_volume"]),
            "prior_24h_avg_quote": float(r["prior_24h_avg_quote"]),
            "candle_return": float(r["candle_return"]),
            "signal": int(r["signal"]),
        })
    schema = {
        "symbol": pl.String, "signal_bar_timestamp": pl.Datetime("us", "UTC"),
        "submit_timestamp": pl.Datetime("us", "UTC"),
        "entry_timestamp": pl.Datetime("us", "UTC"), "exit_timestamp": pl.Datetime("us", "UTC"),
        "imbalance": pl.Float64, "prior_abs_flow_p95": pl.Float64,
        "quote_volume": pl.Float64, "prior_24h_avg_quote": pl.Float64,
        "candle_return": pl.Float64, "signal": pl.Int8,
    }
    events = pl.DataFrame(cand_rows, schema=schema).sort("submit_timestamp", "symbol")
    prices = panel.filter((pl.col("timestamp") >= START) & (pl.col("timestamp") < END)).select(
        "timestamp", "symbol", "open", "high", "low", "close", "volume"
    )
    return prices, events, fund_events, {
        "candidate_extreme_flow_count": candidates.height,
        "eligible_candidates_after_funding_gate": events.height,
        "skipped": skipped,
        "by_symbol": stats,
    }


class FlowReversalStrategy(Strategy):
    def __init__(self, events: pl.DataFrame, symbols: tuple[str, ...] = SYMBOLS):
        self.entries = defaultdict(list)
        for r in events.filter(pl.col("symbol").is_in(symbols)).iter_rows(named=True):
            self.entries[r["submit_timestamp"]].append(r)
        self.active = {}  # symbol -> submission for exit (bar start)
        self.closing = set()
        self.sizing = 0.4

    def on_data(self, timestamp, data, context, broker):
        timestamp = to_utc(timestamp)
        for sym in tuple(self.closing):
            position = broker.get_position(sym)
            if position is None or position.quantity == 0:
                self.closing.discard(sym)
                self.active.pop(sym, None)
        for sym, planned_exit in tuple(self.active.items()):
            if timestamp >= planned_exit and sym not in self.closing:
                if broker.get_position(sym) is None:
                    raise RuntimeError("Expected position missing before scheduled close")
                broker.order_target_value(sym, 0)
                self.closing.add(sym)
        for e in self.entries.get(timestamp, []):
            sym = e["symbol"]
            if sym not in data or sym in self.active:
                continue
            if len(self.active) >= 2:
                continue
            # Never introduce a new position while this symbol has a pending close.
            if broker.get_position(sym) is not None:
                continue
            target = broker.get_account_value() * self.sizing * e["signal"]
            order = broker.order_target_value(sym, target)
            if order is not None:
                self.active[sym] = e["exit_timestamp"] - timedelta(hours=1)


def config(costs: bool) -> BacktestConfig:
    return BacktestConfig(
        initial_cash=INITIAL_CASH,
        allow_short_selling=True,
        allow_leverage=False,
        execution_mode=ExecutionMode.NEXT_BAR,
        execution_price=ExecutionPrice.OPEN,
        share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.PERCENTAGE if costs else CommissionType.NONE,
        commission_rate=0.00045 if costs else 0.0,
        slippage_type=SlippageType.PERCENTAGE if costs else SlippageType.NONE,
        slippage_rate=0.00015 if costs else 0.0,
    )


def engine_run(prices: pl.DataFrame, events: pl.DataFrame, costs: bool, symbols=SYMBOLS):
    feed = DataFeed(prices_df=prices, entity_col="symbol", timestamp_col="timestamp")
    return Engine(feed, FlowReversalStrategy(events, symbols), config(costs)).run()


def result_summary(result) -> dict:
    daily = (
        result.to_equity_dataframe()
        .with_columns(pl.col("timestamp").dt.date().alias("date"))
        .group_by("date").agg(pl.col("equity").last().alias("equity")).sort("date")
    )
    ec = EquityCurve(periods_per_year_override=365.0)
    if daily.height:
        ec.append(datetime.combine(daily["date"][0], datetime.min.time(), UTC) - timedelta(days=1), INITIAL_CASH)
        for r in daily.iter_rows(named=True):
            ec.append(datetime.combine(r["date"], datetime.min.time(), UTC), float(r["equity"]))
    trades = result.to_trades_dataframe()
    fills = result.to_fills_dataframe()
    return {
        "initial_equity": INITIAL_CASH, "final_equity": ec.final_value,
        "total_return": ec.total_return, "daily_sharpe": ec.sharpe,
        "max_drawdown": ec.max_dd, "daily_observations": max(0, len(ec) - 1),
        "trades": trades.height, "fills": fills.height,
        "wins": trades.filter(pl.col("pnl") > 0).height if trades.height else 0,
        "gross_closed_pnl": float(trades["gross_pnl"].sum()) if trades.height else 0.0,
        "net_closed_pnl": float(trades["pnl"].sum()) if trades.height else 0.0,
        "trade_fee_total": float(trades["fees"].sum()) if trades.height else 0.0,
        "trade_slippage_total": float(trades["total_slippage_cost"].sum()) if trades.height else 0.0,
        "rejected_orders": result.to_rejected_orders_dataframe().height,
        "max_positions": max((s[5] for s in result.portfolio_state), default=0),
        "max_gross_to_equity": max((s[3] / s[1] for s in result.portfolio_state if s[1] > 0), default=0.0),
    }


def run() -> dict:
    if OUT.exists() and any(OUT.iterdir()):
        raise FileExistsError(f"Frozen trial output exists; cannot overwrite {OUT}")
    prices, events, funding, stats = prepare_inputs()
    net = engine_run(prices, events, True)
    gross = engine_run(prices, events, False)
    net_summary, gross_summary = result_summary(net), result_summary(gross)
    if net_summary["rejected_orders"]:
        raise RuntimeError(f"Net orders rejected: {net_summary['rejected_orders']}")
    if net_summary["max_positions"] > 2 or net_summary["max_gross_to_equity"] > 1 + 1e-9:
        raise RuntimeError("Exposure exceeded fixed risk limit")
    trades = net.to_trades_dataframe()
    observed = {}
    for row in events.iter_rows(named=True):
        observed[(row["symbol"], row["entry_timestamp"])] = row
    for t in trades.iter_rows(named=True):
        if t["status"] != "closed":
            raise RuntimeError("An unclosed trade remains")
        start, end = to_utc(t["entry_time"]), to_utc(t["exit_time"])
        if end - start != timedelta(hours=4):
            raise RuntimeError("Actual holding period differed from 4 hours")
        if crosses_observed_settlement(start, end, funding[t["symbol"]]):
            raise RuntimeError("Observed funding settlement crossed a trade")
        signal_row = observed.get((t["symbol"], start))
        if signal_row is None or end != signal_row["exit_timestamp"]:
            raise RuntimeError("Trade timing does not match causal signal")
        if (t["direction"] == "short") != (signal_row["signal"] == -1):
            raise RuntimeError("Trade direction does not match causal signal")
    per_symbol = {}
    for sym in SYMBOLS:
        one = engine_run(prices.filter(pl.col("symbol") == sym), events, True, (sym,))
        per_symbol[sym] = result_summary(one)
    output = {
        "schema_version": 1, "session": SESSION, "trial": "fixed_95th_flow_exhaustion_reversal_4h",
        "classification": "EXPLORATORY", "approval_status": "NOT_APPROVED",
        "window_start": START.isoformat(), "window_end_exclusive": END.isoformat(),
        "sources_sha256": {
            str(p.relative_to(ROOT)): hash_file(p)
            for p in (*PRICE_PATHS.values(), *FUNDING_PATHS.values())
        },
        "stats": stats, "combined_net": net_summary, "combined_gross": gross_summary,
        "by_symbol_net": per_symbol,
        "no_trade_return": 0.0,
        "trade_signal_matches": trades.height,
        "strategy_supported": bool(net_summary["total_return"] > 0 and all(
            x["trades"] > 0 for x in per_symbol.values()
        ) and net_summary["max_drawdown"] >= -0.10),
        "costs": {"commission_bps_per_fill": 4.5, "slippage_bps_per_fill": 1.5,
                  "funding_cashflow": 0.0, "explicit_spread_model": False},
        "execution": {"library": "ml4t.backtest", "mode": "NEXT_BAR",
                      "fill_price": "OPEN", "signal_delay_hours": 2, "hold_hours": 4},
        "limitations": [
            "The 2026 development outcomes were previously observable; this is not independent OOS.",
            "No historical L1 spread, true quote availability or impact calibration.",
            "Eight-hour funding schedule is assumed from validated BTC/ETH event intervals.",
            "The engine is not a perpetual contract-accurate liquidation simulator.",
        ],
    }
    OUT.mkdir(parents=True)
    events.write_parquet(OUT / "signal_ledger.parquet", compression="zstd")
    net.to_fills_dataframe().write_csv(OUT / "transaction_ledger.csv")
    net.to_rejected_orders_dataframe().write_csv(OUT / "rejected_orders.csv")
    (OUT / "trial_result.json").write_text(json.dumps(output, indent=2, default=str) + "\n")
    return output


if __name__ == "__main__":
    r = run()
    print(json.dumps({
        "status": "EXPLORATORY",
        "net": r["combined_net"], "gross": r["combined_gross"],
        "candidates": r["stats"],
    }, indent=2, default=str))
