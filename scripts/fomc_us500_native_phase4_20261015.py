"""Frozen post-Phase3 exploratory FOMC overnight: native ML4T broker only.

PREPARE reads historical quote bars but computes no economic outcomes.
FREEZE with scripts/research_session.py init before --run.
RUN uses ml4t.backtest.Engine + native broker; no homemade PnL simulator.
No 2025+ bars, no historical Hyperliquid contract, no qualified funding.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np
import polars as pl
from ml4t.backtest import BacktestConfig, DataFeed, Engine, Strategy
from ml4t.backtest.config import (
    CommissionType,
    DataFrequency,
    ExecutionPrice,
    ShareType,
    SlippageType,
)
from ml4t.backtest.types import ExecutionMode, OrderSide
from ml4t.diagnostic.api import PortfolioAnalysis

ROOT = Path(__file__).resolve().parents[1]
SESSION = "fomc_us500_overnight_native_phase4_20261015_v1"
PHASE3 = "fomc_sp500_overnight_gross_phase3_20261015_v1"
PREFLIGHT = (
    ROOT
    / "docs/audit/fomc_overnight_uncertainty_premium_us500_cfd_20261015_v1_source_preflight_v2.json"
)
EXISTING_PRICES = ROOT / "data/processed" / PHASE3 / "endpoint_bids.parquet"
SOURCE = Path("/home/quant/dev/quant/ml4t-data/.data/store/index_minute_ES")
PRICES = ROOT / "data/processed" / SESSION / "minute_windows_bid.parquet"
REGISTRY = ROOT / "run_log/research_sessions" / SESSION / "frozen_spec.json"
OUT = ROOT / "run_log/diagnostics" / SESSION
ARCHIVE = ROOT / "docs/audit" / SESSION
CUTOFF = datetime(2025, 1, 1, tzinfo=UTC)
INITIAL_EQUITY = 100_000.0
TRIALS = (
    ("fomc_primary_3x_10bps", "fomc", 3.0, 10.0),
    ("ordinary_baseline_3x_10bps", "control", 3.0, 10.0),
    ("fomc_3x_20bps_cost_stress", "fomc", 3.0, 20.0),
    ("fomc_1x_10bps", "fomc", 1.0, 10.0),
    ("fomc_5x_10bps", "fomc", 5.0, 10.0),
    ("fomc_3x_zero_cost_diagnostic", "fomc", 3.0, 0.0),
)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    with path.open("rb") as fp:
        return hashlib.file_digest(fp, "sha256").hexdigest()


def json_write(path: Path, obj: dict) -> None:
    if path.exists():
        raise FileExistsError(f"Cannot overwrite research evidence: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=2, allow_nan=False, default=str) + "\n", encoding="utf-8"
    )


def events() -> list[dict]:
    audit = _json(PREFLIGHT)
    selected = [x for x in audit["events"] if x.get("source_coverage_complete")]
    if len(selected) != 53 or audit["candidate_statement_count"] != 63:
        raise AssertionError("Source eligibility changed from frozen Phase 3")
    return selected


@lru_cache(maxsize=260)
def day_data(day: date) -> pl.DataFrame:
    if not 2017 <= day.year < 2025:
        raise ValueError("Protected 2025+ source reads forbidden")
    path = SOURCE / f"year={day.year}/month={day.month}/day={day.day}/data.parquet"
    if not path.is_file():
        raise FileNotFoundError(path)
    df = pl.read_parquet(
        path, columns=["timestamp", "symbol", "open", "high", "low", "close"]
    )
    if df.schema["timestamp"].time_zone != "UTC":
        raise AssertionError("Quote timezone must be UTC")
    if df["symbol"].unique().to_list() != ["ES"]:
        raise AssertionError("Cross-symbol contamination")
    return df


def minute_range(start: datetime, stop: datetime) -> pl.DataFrame:
    rows = []
    cursor = start.date()
    while cursor <= stop.date():
        rows.append(day_data(cursor))
        cursor += timedelta(days=1)
    out = (
        pl.concat(rows)
        .filter((pl.col("timestamp") >= start) & (pl.col("timestamp") <= stop))
        .sort("timestamp")
    )
    if out.is_empty() or not start < stop < CUTOFF:
        raise AssertionError(f"Absent or invalid time window {start}--{stop}")
    if out["timestamp"][0] != start or out["timestamp"][-1] != stop:
        raise AssertionError(f"Decision/fill timestamp missing in {start}--{stop}")
    if out["timestamp"].n_unique() != out.height:
        raise AssertionError("Duplicate source bar in native window")
    if out.filter(
        (pl.col("open") <= 0)
        | (pl.col("high") < pl.col("low"))
        | (pl.col("low") > pl.col("open"))
        | (pl.col("high") < pl.col("open"))
        | (pl.col("low") > pl.col("close"))
        | (pl.col("high") < pl.col("close"))
    ).height:
        raise AssertionError("Invalid native source OHLC")
    return out


def prepare() -> None:
    if PRICES.exists():
        raise FileExistsError(f"Source already prepared, preserve: {PRICES}")
    original = pl.read_parquet(EXISTING_PRICES)
    original_open = {
        (r["statement_date"], r["leg"], r["action"]): (r["timestamp"], r["open"])
        for r in original.iter_rows(named=True)
    }
    if len(original_open) != 212:
        raise AssertionError("Phase3 endpoint source identity changed")
    windows = []
    gap_summary = []
    for ev in events():
        for leg in ("fomc", "control"):
            entry = ev["quote_checks"][leg + "_entry"]
            exit_ = ev["quote_checks"][leg + "_exit"]
            start = datetime.fromisoformat(entry["decision_utc"])
            last_decision = datetime.fromisoformat(exit_["decision_utc"])
            entry_fill = datetime.fromisoformat(
                entry["required_fill_bar"]["timestamp_utc"]
            )
            exit_fill = datetime.fromisoformat(
                exit_["required_fill_bar"]["timestamp_utc"]
            )
            assert entry_fill == start + timedelta(minutes=1)
            assert exit_fill == last_decision + timedelta(minutes=1)
            frame = minute_range(start, exit_fill)
            idx = {timestamp for timestamp in frame["timestamp"].to_list()}
            if not ({start, entry_fill, last_decision, exit_fill} <= idx):
                raise AssertionError("Missing exact 16:05/16:06/09:35/09:36 bars")
            for action, at in (("entry", entry_fill), ("exit", exit_fill)):
                expected_ts, expected_price = original_open[
                    (ev["statement_date"], leg, action)
                ]
                actual = frame.filter(pl.col("timestamp") == at)["open"][0]
                if expected_ts != at or not np.isclose(
                    actual, expected_price, rtol=0, atol=1e-10
                ):
                    raise AssertionError(
                        "Phase4 endpoint deviates from frozen Phase3 event"
                    )
            gaps = frame["timestamp"].diff().dt.total_minutes().drop_nulls()
            max_gap = int(gaps.max()) if len(gaps) else 0
            if max_gap > 180:
                raise ValueError(
                    f"Unqualified >180m source gap: {ev['statement_date']} {leg} {max_gap}m"
                )
            gap_summary.append(
                {
                    "date": ev["statement_date"],
                    "leg": leg,
                    "bars": frame.height,
                    "max_source_gap_minutes": max_gap,
                    "missing_in_1min_grid": int(
                        (exit_fill - start).total_seconds() / 60 + 1 - frame.height
                    ),
                }
            )
            marked = frame.with_columns(
                pl.lit(ev["statement_date"]).alias("statement_date"),
                pl.lit(leg).alias("leg"),
                pl.when(pl.col("timestamp") == start)
                .then(1)
                .otherwise(0)
                .cast(pl.Int8)
                .alias("enter"),
                pl.when(pl.col("timestamp") == last_decision)
                .then(1)
                .otherwise(0)
                .cast(pl.Int8)
                .alias("exit"),
                pl.when(pl.col("timestamp") == entry_fill)
                .then(1)
                .otherwise(0)
                .cast(pl.Int8)
                .alias("entry_fill_clock"),
                pl.when(pl.col("timestamp") == exit_fill)
                .then(1)
                .otherwise(0)
                .cast(pl.Int8)
                .alias("exit_fill_clock"),
            )
            windows.append(marked)
    data = pl.concat(windows).sort("timestamp")
    if data["timestamp"].n_unique() != data.height:
        raise AssertionError("Window overlap/duplicated native timestamps")
    if (
        data["enter"].sum(),
        data["exit"].sum(),
        data["entry_fill_clock"].sum(),
        data["exit_fill_clock"].sum(),
    ) != (106, 106, 106, 106):
        raise AssertionError("Not exactly 53 candidate and 53 control native events")
    PRICES.parent.mkdir(parents=True, exist_ok=True)
    data.write_parquet(PRICES)
    print(
        json.dumps(
            {
                "status": "PREPARED_WITHOUT_RETURN_INSPECTION",
                "n_event_pairs": 53,
                "bar_rows": data.height,
                "data_sha256": sha(PRICES),
                "input": str(PRICES.relative_to(ROOT)),
                "max_quote_gap_minutes": max(
                    x["max_source_gap_minutes"] for x in gap_summary
                ),
                "gap_summary": gap_summary[:2],
            },
            indent=2,
        ),
        flush=True,
    )


def utc(ts: datetime) -> datetime:
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)


class OvernightCalendarStrategy(Strategy):
    """Calendar intents only; all order fills and cash accounting are native."""

    def __init__(self, leverage: float):
        self.leverage = leverage
        self.entry_decisions = []
        self.exit_decisions = []
        self.entry_fills_seen = []
        self.exit_fills_seen = []
        self.max_open_positions = 0
        self.pending_entry = False
        self.pending_exit = False
        self.last_exit_order_id = None

    def on_data(self, timestamp, data, context, broker) -> None:
        bar = data.get("ES")
        if bar is None:
            raise AssertionError("Missing ES bar in engine clock")
        signal = bar["signals"]
        ts = utc(timestamp)
        pos = broker.get_position("ES")
        self.max_open_positions = max(self.max_open_positions, int(pos is not None))
        if signal.get("entry_fill_clock", 0):
            if pos is None or pos.quantity <= 0:
                raise AssertionError(f"Expected native BUY fill at {ts}")
            self.entry_fills_seen.append(ts.isoformat())
            self.pending_entry = False
        if signal.get("exit_fill_clock", 0):
            if pos is not None:
                order = broker.get_order(self.last_exit_order_id)
                reject = [
                    (o.order_id, o.rejection_reason)
                    for o in broker.get_rejected_orders()
                ]
                raise AssertionError(
                    f"Native SELL close not flat at {ts}: qty={pos.quantity}, "
                    f"entry={pos.entry_price}, cash={broker.get_cash()}, "
                    f"equity={broker.get_account_value()}, order_status={order.status if order else None}, "
                    f"order_id={self.last_exit_order_id}, reject={reject[-4:]}"
                )
            self.exit_fills_seen.append(ts.isoformat())
            self.pending_exit = False
        if signal.get("enter", 0):
            if pos is not None or self.pending_entry or self.pending_exit:
                raise AssertionError("Overlapping position or pending native order")
            if broker.get_account_value() <= 0:
                raise AssertionError("Insolvent native account before scheduled entry")
            order = broker.order_target_percent("ES", self.leverage)
            if order is None:
                raise AssertionError(f"Native broker refused entry intent {ts}")
            self.entry_decisions.append(ts.isoformat())
            self.pending_entry = True
        if signal.get("exit", 0):
            if (
                pos is None
                or pos.quantity <= 0
                or self.pending_exit
                or self.pending_entry
            ):
                raise AssertionError("Missing native open position at scheduled exit")
            # Exact native closing quantity avoids a float over-close/reversal
            # produced by order_target_percent(0) in the installed broker.
            order = broker.submit_order("ES", pos.quantity, OrderSide.SELL)
            if order is None:
                raise AssertionError(f"Native broker refused exit intent {ts}")
            self.exit_decisions.append(ts.isoformat())
            self.pending_exit = True
            self.last_exit_order_id = order.order_id


def config(bps: float) -> BacktestConfig:
    return BacktestConfig(
        initial_cash=INITIAL_EQUITY,
        allow_short_selling=False,
        allow_leverage=True,
        initial_margin=0.10,
        long_maintenance_margin=0.05,
        short_maintenance_margin=0.05,
        share_type=ShareType.FRACTIONAL,
        execution_mode=ExecutionMode.NEXT_BAR,
        execution_price=ExecutionPrice.OPEN,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=bps / 40000,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=bps / 40000,
        data_frequency=DataFrequency.MINUTE_1,
        enforce_sessions=False,
    )


def daily_equity(equity: pl.DataFrame) -> pl.DataFrame:
    if equity.is_empty():
        raise AssertionError("Missing native equity snapshots")
    from_ = equity["timestamp"].min().date()
    through = date(2024, 12, 31)
    if from_ > through:
        raise AssertionError("No historical dates")
    calendar = pl.DataFrame(
        {"date": pl.date_range(from_, through, interval="1d", eager=True)}
    )
    grouped = (
        equity.with_columns(pl.col("timestamp").dt.date().alias("date"))
        .group_by("date")
        .agg(pl.col("equity").last().alias("equity"))
        .sort("date")
    )
    combined = calendar.join(grouped, on="date", how="left").with_columns(
        pl.col("equity").forward_fill().alias("equity")
    )
    if combined["equity"].null_count() > 0:
        raise AssertionError("Insufficient equity marks to build daily curve")
    return combined.with_columns(
        (
            pl.col("equity") / pl.col("equity").shift(1).fill_null(INITIAL_EQUITY) - 1
        ).alias("daily_return")
    )


def risk_stats(daily: pl.DataFrame) -> dict:
    risk = PortfolioAnalysis(
        returns=daily["daily_return"].to_numpy(), periods_per_year=365
    ).compute_summary_stats()
    out = {}
    for k, v in vars(risk).items():
        if isinstance(v, (int, float, np.number)):
            n = float(v)
            out[k] = n if np.isfinite(n) else None
    return out


def backtest_trial(
    name: str, leg: str, lev: float, bps: float, prices: pl.DataFrame
) -> dict:
    dest = OUT / name
    retry = 0
    while (dest / "failure.json").exists():
        retry += 1
        dest = OUT / (name + f"_retry{retry}")
    if (dest / "metrics.json").exists():
        raise FileExistsError(f"Do not overwrite terminal trial: {name}")
    dest.mkdir(parents=True, exist_ok=True)
    selected = prices.filter(pl.col("leg") == leg).sort("timestamp")
    if (
        selected["enter"].sum(),
        selected["exit"].sum(),
        selected["entry_fill_clock"].sum(),
        selected["exit_fill_clock"].sum(),
    ) != (53, 53, 53, 53):
        raise AssertionError("Insufficient native scheduled observations")
    feed = DataFeed(
        prices_df=selected.select(
            "timestamp", "symbol", "open", "high", "low", "close"
        ),
        signals_df=selected.select(
            "timestamp",
            "symbol",
            "enter",
            "exit",
            "entry_fill_clock",
            "exit_fill_clock",
        ),
        entity_col="symbol",
        timestamp_col="timestamp",
    )
    strategy = OvernightCalendarStrategy(lev)
    try:
        result = Engine(feed, strategy, config(bps)).run()
        trades = result.to_trades_dataframe()
        fills = result.to_fills_dataframe()
        rejected = result.to_rejected_orders_dataframe()
        equity = result.to_equity_dataframe()
        states = result.to_portfolio_state_dataframe()
        all_closed = trades.filter(pl.col("status") == "closed")
        if rejected.height or fills.height != 106 or all_closed.height != 53:
            raise AssertionError(
                f"Native broker not reconciled {name}: "
                f"rejected={rejected.height},fills={fills.height},trades={all_closed.height}"
            )
        if any(
            len(series) != 53
            for series in (
                strategy.entry_decisions,
                strategy.exit_decisions,
                strategy.entry_fills_seen,
                strategy.exit_fills_seen,
            )
        ):
            raise AssertionError("Native calendar intent/fill counts mismatch")
        clock_expected = sorted(
            [
                utc(x) + timedelta(minutes=1)
                for x in (
                    [datetime.fromisoformat(a) for a in strategy.entry_decisions]
                    + [datetime.fromisoformat(a) for a in strategy.exit_decisions]
                )
            ]
        )
        observed = sorted(utc(x) for x in fills["timestamp"].to_list())
        if clock_expected != observed:
            raise AssertionError("Native fills not at exact next-bar open")
        expected_ref = selected.filter(
            (pl.col("entry_fill_clock") == 1) | (pl.col("exit_fill_clock") == 1)
        ).select("timestamp", "open")
        ref_map = dict(expected_ref.iter_rows())
        for r in fills.iter_rows(named=True):
            ts = utc(r["timestamp"])
            if r["price_source"] != "open":
                raise AssertionError(f"Native fill price source is not OPEN at {ts}")
            slip = bps / 40000
            expected = ref_map[ts] * (1 + slip if r["side"] == "buy" else 1 - slip)
            if not np.isclose(r["price"], expected, rtol=0, atol=1e-6):
                raise AssertionError(
                    f"Native fill price not OPEN plus/minus slippage: {ts}"
                )
            if not np.isclose(r["slippage"], ref_map[ts] * slip, rtol=0, atol=1e-6):
                raise AssertionError(
                    f"Native slippage amount differs from frozen costs: {ts}"
                )
        pnl = float(all_closed["pnl"].sum())
        final_equity = float(result.metrics["final_value"])
        reconciled = abs(pnl - (final_equity - INITIAL_EQUITY)) <= max(
            0.10, abs(pnl) * 1e-7
        )
        if not reconciled:
            raise AssertionError(
                f"Native trade PnL does not reconcile: {pnl}, {final_equity}"
            )
        if abs(float(equity["equity"][-1]) - final_equity) > 0.1:
            raise AssertionError("Native equity vs result final value mismatch")
        if states["open_positions"][-1] != 0:
            raise AssertionError("Native positions still open at last bar")
        exposure = (
            states.filter(pl.col("equity") > 0)
            .with_columns(
                (pl.col("gross_exposure") / pl.col("equity")).alias("gross_to_equity")
            )["gross_to_equity"]
            .max()
        )
        if exposure is None or not (lev * 0.90 <= float(exposure) <= lev * 1.30):
            raise AssertionError(f"Unexpected native leverage {name}: {exposure}")
        entry_fills = fills.filter(pl.col("side") == "buy")
        if entry_fills.height != 53:
            raise AssertionError("Missing native entry fills")
        winners = all_closed.filter(pl.col("pnl") > 0)
        losers = all_closed.filter(pl.col("pnl") < 0)
        gross_profit = float(winners["pnl"].sum())
        gross_loss = float(losers["pnl"].sum())
        pf = gross_profit / abs(gross_loss) if gross_loss < 0 else None
        daily = daily_equity(equity)
        risk = risk_stats(daily)
        yearly = (
            daily.with_columns(pl.col("date").dt.year().alias("year"))
            .group_by("year")
            .agg(((pl.col("daily_return") + 1).product() - 1).alias("net_return"))
            .sort("year")
        )
        native_costs = float(fills["commission"].sum()) + float(
            (fills["slippage"] * fills["quantity"]).sum()
        )
        out = {
            "trial_id": name,
            "leg": leg,
            "target_notional_leverage": lev,
            "roundtrip_hypothetical_bps": bps,
            "commission_per_side_bps": bps / 4,
            "slippage_per_side_bps": bps / 4,
            "qualified_historical_perp_funding": False,
            "venue_execution_fidelity": "bid-only CFD-index proxy, not Hyperliquid fills",
            "closed_trades": all_closed.height,
            "fills": fills.height,
            "win_rate": float(winners.height / all_closed.height),
            "profit_factor": pf,
            "native_trade_net_pnl": pnl,
            "trade_net_expectancy": pnl / all_closed.height,
            "final_equity": final_equity,
            "net_return": final_equity / INITIAL_EQUITY - 1,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "native_total_cost_estimate_usdt": native_costs,
            "daily_equity_risk_ml4t_diagnostic": risk,
            "yearly_net_returns": {str(a): float(b) for a, b in yearly.iter_rows()},
            "max_gross_to_equity_observed": float(exposure),
            "native_fill_clock_exact": True,
            "native_execution_price_open_slippage_parity": True,
            "native_trade_cash_equity_reconciled": True,
            "rejected_orders": rejected.height,
            "data_sha256": sha(PRICES),
            "start_cash": INITIAL_EQUITY,
            "native_engine_metrics": {
                k: float(v)
                if isinstance(v, (int, float, np.number)) and np.isfinite(v)
                else str(v)
                for k, v in result.metrics.items()
            },
        }
        trades.write_parquet(dest / "native_trades.parquet")
        fills.write_parquet(dest / "native_fills.parquet")
        equity.write_parquet(dest / "native_minute_equity.parquet")
        states.write_parquet(dest / "native_portfolio_state.parquet")
        rejected.write_parquet(dest / "rejected_orders.parquet")
        daily.write_csv(dest / "daily_equity.csv")
        yearly.write_csv(dest / "yearly_returns.csv")
        json_write(dest / "metrics.json", out)
        print(
            json.dumps(
                {
                    "trial": name,
                    "n": all_closed.height,
                    "PF": pf,
                    "net_pnl": pnl,
                    "sharpe": risk.get("sharpe_ratio"),
                    "mdd": risk.get("max_drawdown"),
                    "win": out["win_rate"],
                }
            ),
            flush=True,
        )
        return out
    except Exception as exc:
        fail = dest / "failure.json"
        if not fail.exists():
            json_write(
                fail,
                {"trial": name, "error_type": type(exc).__name__, "message": str(exc)},
            )
        raise


def finish(results: dict) -> None:
    primary = results["fomc_primary_3x_10bps"]
    base = results["ordinary_baseline_3x_10bps"]
    stress = results["fomc_3x_20bps_cost_stress"]
    rp = primary["daily_equity_risk_ml4t_diagnostic"]
    rb = base["daily_equity_risk_ml4t_diagnostic"]
    failures = []
    if primary["native_trade_net_pnl"] <= 0:
        failures.append("Primary net PnL <= 0")
    if primary["profit_factor"] is None or primary["profit_factor"] < 1.30:
        failures.append("Primary PF <1.30 or undefined")
    if rp["sharpe_ratio"] is None or rp["sharpe_ratio"] < 0.50:
        failures.append("Primary daily-equity Sharpe <0.50")
    if rp["max_drawdown"] is None or rp["max_drawdown"] < -0.20:
        failures.append("Primary native-equity max drawdown exceeds 20%")
    if base["profit_factor"] is not None and (
        primary["profit_factor"] is None
        or primary["profit_factor"] <= base["profit_factor"]
    ):
        failures.append("D-7 ordinary baseline PF >= FOMC PF")
    if rb["sharpe_ratio"] is not None and (
        rp["sharpe_ratio"] is None or rp["sharpe_ratio"] <= rb["sharpe_ratio"]
    ):
        failures.append("D-7 ordinary baseline Sharpe >= FOMC Sharpe")
    if stress["native_trade_net_pnl"] <= 0:
        failures.append("Double friction 20bps net PnL <=0")
    verdict = "REJECT" if failures else "INCONCLUSIVE"
    # Even passed exploratory numeric screens are not a historical Hyperliquid qualified VALIDATE.
    if not failures:
        failures.append(
            "All numerical screens passed, but historical perpetual fees/funding and independent validation absent"
        )
    summary = {
        "session_id": SESSION,
        "classification": "EXPLORATORY",
        "approval_status": "NOT_APPROVED",
        "research_verdict": verdict,
        "frozen_trial_count": len(TRIALS),
        "executed_trial_count": len(results),
        "criteria_failures_or_limits": failures,
        "holdout_2025_plus": "SEALED",
        "native_broker": "ml4t-backtest.Engine",
        "funding_modeled": False,
        "phase3_incremental_edge": "INCONCLUSIVE",
        "source": "Dukascopy bid 1m index price proxy only",
        "trial_metrics": [
            {
                "trial": name,
                "closed_trades": v["closed_trades"],
                "net_pnl": v["native_trade_net_pnl"],
                "pf": v["profit_factor"],
                "win_rate": v["win_rate"],
                "sharpe": v["daily_equity_risk_ml4t_diagnostic"]["sharpe_ratio"],
                "max_drawdown": v["daily_equity_risk_ml4t_diagnostic"]["max_drawdown"],
                "annual_return": v["daily_equity_risk_ml4t_diagnostic"][
                    "annual_return"
                ],
            }
            for name, v in results.items()
        ],
    }
    json_write(OUT / "final_decision.json", summary)
    lines = [
        "# FOMC overnight: native ML4T Phase 4 exploratory result",
        "",
        f"**Research decision: {verdict}.**",
        "",
        "**This trial is post-Phase-3 exploratory**, not unseen OOS or historical Hyperliquid performance.",
        (
            "Frozen 53 paired schedules (2018–2024), 16:05 decision/16:06 next-open entry, "
            "09:35 decision/09:36 next-open exit. No stops or signal optimization."
        ),
        (
            "Fractional linear synthetic index units; 3x equity primary, 10bps hypothetical "
            "roundtrip friction, 20bps stress, leverage 1x/5x and zero-cost attribution."
        ),
        "**No real funding, quotes, dividends, liquidation or venue impact are modeled.**",
        "## Trial metrics",
        "",
        "| Native trial | Closed | Net PnL | PF | Win | Daily Sharpe | MaxDD | Annualized return |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["trial_metrics"]:
        fmt = lambda v: "undefined" if v is None else f"{v:.3f}"
        lines.append(
            f"| {row['trial']} | {row['closed_trades']} | {row['net_pnl']:.2f} | "
            f"{fmt(row['pf'])} | {fmt(row['win_rate'])} | {fmt(row['sharpe'])} | "
            f"{fmt(row['max_drawdown'])} | {fmt(row['annual_return'])} |"
        )
    lines += (
        ["", "## Frozen acceptance evaluation", ""]
        + [f"- {reason}" for reason in failures]
        + [
            "",
            "## Verification",
            "- All PnL, trades, fills, prices, equity and cash originate in native ml4t-backtest.Engine/broker.",
            "- Fills match the exact next-minute timestamp and native source bar OPEN.",
            "- Closed trade net sum and native equity are independently reconciled on all trials.",
            "- Equity risk metrics use calendar daily curve incl. flat days and ml4t.diagnostic PortfolioAnalysis.",
            "- Original Phase3 53-event gross proxy results remain untouched; 2025+ protected holdout unread.",
            "- Conditional trial success cannot establish historical Hyperliquid execution or positive net funding-adjusted alpha.",
        ]
    )
    (OUT / "final_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("VERDICT", json.dumps({"verdict": verdict, "reasons": failures}), flush=True)


def run() -> None:
    if not REGISTRY.is_file():
        raise RuntimeError("Session not frozen: use research_session.py init first")
    frozen = _json(REGISTRY)
    if frozen["status"] != "FROZEN" or frozen["session_id"] != SESSION:
        raise AssertionError("Wrong frozen trial session")
    if [x["id"] for x in frozen["spec"]["trials"]] != [x[0] for x in TRIALS]:
        raise AssertionError("Trial list differs from frozen specification")
    if frozen["identity"]["data"][0]["sha256"] != sha(PRICES):
        raise AssertionError("Prepared minute data changed after freeze")
    if (OUT / "final_decision.json").exists():
        raise FileExistsError("Terminal trial already exists; do not rerun")
    prices = pl.read_parquet(PRICES)
    if (
        prices["timestamp"].max() >= CUTOFF
        or prices["timestamp"].n_unique() != prices.height
    ):
        raise AssertionError("Holdout, duplicate or malformed minute feed")
    results = {}
    for name, leg, lev, bps in TRIALS:
        results[name] = backtest_trial(name, leg, lev, bps, prices)
    finish(results)


def main():
    parser = argparse.ArgumentParser()
    p = parser.add_mutually_exclusive_group(required=True)
    p.add_argument("--prepare", action="store_true")
    p.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        prepare()
    else:
        run()


if __name__ == "__main__":
    main()
