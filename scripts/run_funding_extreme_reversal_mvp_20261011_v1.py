"""Run the preregistered funding-extreme reversal MVP."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
from ml4t.backtest import BacktestConfig, DataFeed, Engine, Strategy
from ml4t.backtest.analytics.equity import EquityCurve
from ml4t.backtest.config import (
    CommissionType,
    ExecutionPrice,
    ShareType,
    SlippageType,
)
from ml4t.backtest.types import ExecutionMode

ROOT = Path(__file__).resolve().parents[1]
SESSION = "funding_extreme_reversal_mvp_20261011_v1"
OUT = ROOT / "run_log" / SESSION
START = datetime(2026, 1, 1, tzinfo=UTC)
END = datetime(2026, 8, 1, tzinfo=UTC)
WARMUP = datetime(2025, 10, 1, tzinfo=UTC)
SYMBOLS = ("BTCUSDT", "ETHUSDT")
INITIAL_CASH = 500.0

PRICE_PATHS = {
    "BTCUSDT": "data/processed/crypto_tsmom_flow_inputs_20261008/btcusdt_1h.parquet",
    "ETHUSDT": "data/processed/crypto_tsmom_flow_inputs_20261008/ethusdt_1h.parquet",
}
FUNDING_PATHS = {
    "BTCUSDT": "data/processed/crypto_tsmom_flow_inputs_20261008_v4/btcusdt_funding.parquet",
    "ETHUSDT": "data/processed/crypto_tsmom_flow_inputs_20261008_v4/ethusdt_funding.parquet",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_development_prices(symbols: tuple[str, ...] = SYMBOLS) -> pl.DataFrame:
    frames = []
    for symbol in symbols:
        frame = (
            pl.scan_parquet(ROOT / PRICE_PATHS[symbol])
            .filter((pl.col("timestamp") >= START) & (pl.col("timestamp") < END))
            .select("timestamp", "symbol", "open", "high", "low", "close", "volume")
            .collect()
            .sort("timestamp")
        )
        if frame.is_empty() or frame["timestamp"].null_count():
            raise ValueError(f"Missing development prices for {symbol}")
        if frame["timestamp"].n_unique() != frame.height:
            raise ValueError(f"Duplicate development timestamps for {symbol}")
        if frame.filter(
            pl.any_horizontal(
                pl.col("open").is_finite().not_(),
                pl.col("high").is_finite().not_(),
                pl.col("low").is_finite().not_(),
                pl.col("close").is_finite().not_(),
                pl.col("volume").is_finite().not_(),
            )
        ).height:
            raise ValueError(f"Non-finite values in development prices for {symbol}")
        bad_ohlc = frame.filter(
            (pl.col("high") < pl.col("low"))
            | (pl.col("close") < pl.col("low"))
            | (pl.col("close") > pl.col("high"))
            | (pl.col("open") <= 0)
            | (pl.col("close") <= 0)
        )
        if bad_ohlc.height:
            raise ValueError(f"Invalid OHLC rows for {symbol}: {bad_ohlc.height}")
        expected = pl.datetime_range(START, END - timedelta(hours=1), interval="1h", eager=True)
        if frame["timestamp"].to_list() != expected.to_list():
            raise ValueError(f"Development price bars are not a complete hourly grid for {symbol}")
        frames.append(frame)
    return pl.concat(frames).sort("timestamp", "symbol")


def add_prior_event_thresholds(funding: pl.DataFrame) -> pl.DataFrame:
    return (
        funding.sort("timestamp")
        .with_columns(
            prior_p90=pl.col("funding_rate").abs().rolling_quantile(
                quantile=0.9, window_size=90, min_samples=90
            ).shift(1)
        )
    )


def crosses_settlement(entry_time: datetime, exit_time: datetime, settlements: list[datetime]) -> bool:
    # ml4t.backtest reports UTC bar times without a tzinfo in its trade ledger.
    # The source feed is UTC-aware. Normalize only the documented engine output.
    entry = entry_time.replace(tzinfo=UTC) if entry_time.tzinfo is None else entry_time.astimezone(UTC)
    exit_ = exit_time.replace(tzinfo=UTC) if exit_time.tzinfo is None else exit_time.astimezone(UTC)
    return any(entry <= settled_at < exit_ for settled_at in settlements)


def build_event_table() -> tuple[pl.DataFrame, dict[str, list[datetime]], dict[str, int]]:
    """Compute the fixed prior-event threshold and skip ineligible positions."""
    accepted: list[dict[str, Any]] = []
    funding_times: dict[str, list[datetime]] = {}
    counts = {"events_seen": 0, "warmup_or_insufficient_history": 0,
              "below_threshold": 0, "settlement_crossing": 0,
              "outside_development_or_missing_bars": 0, "accepted": 0}
    price_times: dict[str, set[datetime]] = {}
    for symbol in SYMBOLS:
        prices = pl.scan_parquet(ROOT / PRICE_PATHS[symbol])
        price_times[symbol] = set(
            prices.filter((pl.col("timestamp") >= START) & (pl.col("timestamp") < END))
            .select("timestamp").collect().to_series().to_list()
        )
        funding = (
            pl.scan_parquet(ROOT / FUNDING_PATHS[symbol])
            .filter((pl.col("timestamp") >= WARMUP) & (pl.col("timestamp") < END))
            .select("timestamp", "funding_rate", "funding_interval_hours")
            .collect()
        )
        if funding.filter(pl.col("funding_interval_hours") != 8).height:
            raise ValueError(f"BTC/ETH funding cadence changed for {symbol}; cannot assume next +8h")
        funding = add_prior_event_thresholds(funding)
        if funding["timestamp"].n_unique() != funding.height:
            raise ValueError(f"Duplicate funding timestamps for {symbol}")
        if funding.filter(
            pl.col("timestamp").is_null()
            | pl.col("funding_rate").is_null()
            | ~pl.col("funding_rate").is_finite()
        ).height:
            raise ValueError(f"Invalid funding observations for {symbol}")
        funding_times[symbol] = funding["timestamp"].to_list()
        in_development = funding.filter(
            (pl.col("timestamp") >= START) & (pl.col("timestamp") < END)
        )
        counts["events_seen"] += in_development.height
        counts["warmup_or_insufficient_history"] += in_development.filter(
            pl.col("prior_p90").is_null()
        ).height
        for event in in_development.iter_rows(named=True):
            rate = float(event["funding_rate"])
            threshold = event["prior_p90"]
            if threshold is None:
                continue
            if abs(rate) < float(threshold):
                counts["below_threshold"] += 1
                continue
            event_time = event["timestamp"]
            bar_time = event_time.replace(minute=0, second=0, microsecond=0)
            decision_time = bar_time + timedelta(hours=1)
            entry_time = decision_time
            exit_time = entry_time + timedelta(hours=4)
            if (
                bar_time not in price_times[symbol]
                or entry_time not in price_times[symbol]
                or exit_time not in price_times[symbol]
                or exit_time >= END
            ):
                counts["outside_development_or_missing_bars"] += 1
                continue
            # The intended BTC/ETH funding cadence is 8 hours. Do not
            # examine *future realized* settlement timestamps when deciding.
            # The full historical settlement stream is used only for the
            # independent post-trade crossing audit below.
            expected_next_settlement = event_time + timedelta(hours=8)
            if entry_time <= expected_next_settlement < exit_time:
                counts["settlement_crossing"] += 1
                continue
            accepted.append(
                {
                    "symbol": symbol,
                    "event_timestamp": event_time,
                    "signal_bar_timestamp": bar_time,
                    "decision_available_timestamp": event_time,
                    "completed_bar_timestamp": decision_time,
                    "entry_timestamp": entry_time,
                    "exit_timestamp": exit_time,
                    "funding_rate": rate,
                    "prior_90_event_abs_rate_p90": float(threshold),
                    "signal": -1 if rate > 0 else 1,
                }
            )
            counts["accepted"] += 1
    return pl.DataFrame(accepted).sort("signal_bar_timestamp", "symbol"), funding_times, counts


class FundingReversal(Strategy):
    def __init__(self, event_table: pl.DataFrame, *, symbols: tuple[str, ...], sizing: float = 0.4):
        self.symbols = symbols
        self.sizing = sizing
        self.entries: dict[datetime, list[tuple[str, int]]] = {}
        self.exits: dict[datetime, list[str]] = {}
        self.pending: set[str] = set()
        self.filled_exit_schedule: dict[str, datetime] = {}
        for row in event_table.filter(pl.col("symbol").is_in(symbols)).iter_rows(named=True):
            signal_bar = row["signal_bar_timestamp"]
            self.entries.setdefault(signal_bar, []).append((row["symbol"], row["signal"]))
            self.exits.setdefault(signal_bar + timedelta(hours=4), []).append(row["symbol"])

    def on_data(self, timestamp, data, context, broker) -> None:
        for symbol in tuple(self.pending):
            if broker.get_position(symbol) is not None:
                self.pending.remove(symbol)
        for symbol in self.exits.get(timestamp, []):
            if broker.get_position(symbol) is not None:
                broker.order_target_value(symbol, 0.0)
        for symbol, direction in self.entries.get(timestamp, []):
            if symbol not in data or symbol in self.pending or broker.get_position(symbol) is not None:
                continue
            if len(broker.get_positions()) + len(self.pending) >= 2:
                continue
            target = broker.get_account_value() * self.sizing * direction
            if broker.order_target_value(symbol, target) is not None:
                self.pending.add(symbol)


class EqualWeightBuyHold(Strategy):
    def __init__(self, symbols: tuple[str, ...]):
        self.symbols = symbols
        self.started = False

    def on_data(self, timestamp, data, context, broker) -> None:
        if self.started:
            return
        self.started = True
        for symbol in self.symbols:
            if symbol in data:
                broker.order_target_value(symbol, broker.get_account_value() / len(self.symbols))


def _config(*, costs: bool) -> BacktestConfig:
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


def _run(prices: pl.DataFrame, strategy: Strategy, *, costs: bool):
    feed = DataFeed(prices_df=prices, entity_col="symbol", timestamp_col="timestamp")
    return Engine(feed, strategy, _config(costs=costs)).run()


def _daily_metrics(result) -> tuple[dict[str, float], list[dict[str, Any]]]:
    daily = (
        result.to_equity_dataframe()
        .with_columns(pl.col("timestamp").dt.date().alias("date"))
        .group_by("date")
        .agg(pl.col("equity").last().alias("equity"))
        .sort("date")
    )
    curve = EquityCurve(periods_per_year_override=365.0)
    if daily.height:
        first = daily.row(0, named=True)
        first_day = datetime.combine(first["date"], datetime.min.time(), UTC) - timedelta(days=1)
        curve.append(first_day, INITIAL_CASH)
        for row in daily.iter_rows(named=True):
            curve.append(datetime.combine(row["date"], datetime.min.time(), UTC), float(row["equity"]))
    metrics = {
        "initial_equity": curve.initial_value,
        "final_equity": curve.final_value,
        "total_return": curve.total_return,
        "daily_annualized_sharpe": curve.sharpe,
        "daily_max_drawdown": curve.max_dd,
        "daily_observations": max(0, len(curve) - 1),
    }
    return metrics, daily.to_dicts()


def _result_payload(result) -> dict[str, Any]:
    metrics, daily = _daily_metrics(result)
    return {
        **metrics,
        "fills": result.to_fills_dataframe().to_dicts(),
        "trades": result.to_trades_dataframe().to_dicts(),
        "rejected_orders": result.to_rejected_orders_dataframe().to_dicts(),
        "daily_equity": daily,
        "library_hourly_metrics": result.metrics,
        "max_positions": max((state[5] for state in result.portfolio_state), default=0),
        "max_marked_gross_to_equity": max(
            (state[3] / state[1] for state in result.portfolio_state if state[1] > 0),
            default=0.0,
        ),
    }


def run() -> dict[str, Any]:
    # Research trials are immutable: do not overwrite the completed result.
    if OUT.exists() and any(OUT.iterdir()):
        raise FileExistsError(f"Trial artifacts already exist: {OUT}; create a new versioned run")
    OUT.mkdir(parents=True, exist_ok=True)
    prices = load_development_prices()
    events, funding_times, counts = build_event_table()
    signal_path = OUT / "signal_ledger.parquet"
    events.write_parquet(signal_path)

    combined_net = _run(prices, FundingReversal(events, symbols=SYMBOLS), costs=True)
    combined_gross = _run(prices, FundingReversal(events, symbols=SYMBOLS), costs=False)
    if combined_net.to_rejected_orders_dataframe().height:
        raise RuntimeError("Net candidate run contains rejected orders")
    for state in combined_net.portfolio_state:
        if state[5] > 2:
            raise RuntimeError("More than two simultaneous positions")
        if state[1] > 0 and state[3] / state[1] > 1.0 + 1e-9:
            raise RuntimeError("Marked gross exposure exceeded 1.0x equity")
    trades = combined_net.to_trades_dataframe()
    for trade in trades.iter_rows(named=True):
        if trade["status"] != "closed":
            raise RuntimeError("Candidate has an unclosed position at the end of development")
        symbol = trade["symbol"]
        if crosses_settlement(trade["entry_time"], trade["exit_time"], funding_times[symbol]):
            raise RuntimeError("A candidate position crossed a funding settlement")

    per_symbol = {}
    for symbol in SYMBOLS:
        result = _run(
            prices.filter(pl.col("symbol") == symbol),
            FundingReversal(events, symbols=(symbol,)),
            costs=True,
        )
        if result.to_rejected_orders_dataframe().height:
            raise RuntimeError(f"Net per-symbol run has rejected orders: {symbol}")
        per_symbol[symbol] = _result_payload(result)

    baseline = _run(prices, EqualWeightBuyHold(SYMBOLS), costs=True)
    payload = {
        "schema_version": 1,
        "session_id": SESSION,
        "classification": "EXPLORATORY",
        "approval_status": "NOT_APPROVED",
        "trial_id": "extreme_funding_contrarian_4h",
        "trial_count": 1,
        "hypothesis_result": "",
        "window": {"start_inclusive_utc": START.isoformat(), "end_exclusive_utc": END.isoformat()},
        "warmup_start_utc": WARMUP.isoformat(),
        "instruments": list(SYMBOLS),
        "data": [
            {
                "path": path,
                "sha256": _sha256(ROOT / path),
                "rows_used": int(prices.filter(pl.col("symbol") == symbol).height),
            }
            for symbol, path in PRICE_PATHS.items()
        ]
        + [
            {
                "path": path,
                "sha256": _sha256(ROOT / path),
                "rows_used_through_cutoff": int(
                    pl.scan_parquet(ROOT / path)
                    .filter((pl.col("timestamp") >= WARMUP) & (pl.col("timestamp") < END))
                    .select(pl.len()).collect().item()
                ),
            }
            for path in FUNDING_PATHS.values()
        ],
        "coverage": {
            symbol: {
                "rows": prices.filter(pl.col("symbol") == symbol).height,
                "first_bar_utc": prices.filter(pl.col("symbol") == symbol)["timestamp"][0].isoformat(),
                "last_bar_utc": prices.filter(pl.col("symbol") == symbol)["timestamp"][-1].isoformat(),
            }
            for symbol in SYMBOLS
        },
        "signal_counts": counts,
        "costs_bps_per_fill": {"commission": 4.5, "slippage": 1.5, "spread_added_separately": False},
        "funding_cashflow": "zero by eligibility rule; verified no held trade overlaps a settlement",
        "candidate_combined_net": _result_payload(combined_net),
        "candidate_combined_gross": _result_payload(combined_gross),
        "per_symbol_net": per_symbol,
        "baseline_equal_weight_long_only_net": _result_payload(baseline),
        "baseline_no_trade": {
            "initial_equity": INITIAL_CASH,
            "final_equity": INITIAL_CASH,
            "total_return": 0.0,
            "daily_annualized_sharpe": 0.0,
            "daily_max_drawdown": 0.0,
        },
        "engine": {
            "library": "ml4t.backtest",
            "version": "0.1.7",
            "execution_mode": "NEXT_BAR",
            "execution_price": "OPEN",
            "allow_short_selling": True,
            "allow_leverage": False,
            "share_type": "FRACTIONAL",
        },
        "limitations": [
            "All evaluated observations end before 2026-08-01; this is historical development evidence.",
            "Funding publication time is not separately supplied; the event timestamp is the earliest assumed availability.",
            "No bid/ask quotes are supplied. The 1.5 bps per-side slippage assumption is used without an additional spread charge.",
            "The backtest engine has no funding ledger. Accepted positions are constrained to avoid settlements, and the run fails on any crossing.",
            "No explicit liquidation or maintenance-margin model is active. Gross exposure is capped and verified below 1.0x equity.",
        ],
    }
    payload["hypothesis_result"] = (
        "supported by this exploratory sample" if payload["candidate_combined_net"]["total_return"] > 0
        else "not supported by this exploratory sample"
    )
    path = OUT / "trial_result.json"
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    combined_net.to_fills_dataframe().write_csv(OUT / "transaction_ledger.csv")
    combined_net.to_rejected_orders_dataframe().write_csv(OUT / "rejected_orders.csv")
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
