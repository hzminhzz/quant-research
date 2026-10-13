"""Frozen Model 8 CFD price-proxy adapter and independent native-fill audit."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Any
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import polars as pl
from ml4t.backtest import (
    AssetClass,
    BacktestConfig,
    ContractSpec,
    DataFeed,
    Engine,
    Strategy,
)
from ml4t.backtest.config import (
    CommissionType,
    ExecutionMode,
    FillOrdering,
    SlippageType,
)
from ml4t.backtest.types import OrderStatus
from ml4t.diagnostic.api import PortfolioAnalysis

from .contracts import ResearchContractV1
from .feature_gateway import (
    FeatureComputation,
    FeatureContractError,
)
from .run_permit import RunIntentV1, RunPermitV1, preflight_run

BAR = timedelta(minutes=30)
INITIAL_CASH = 100_000.0
UNIT_MULTIPLIER = 1.0
BASE_COST_BPS_PER_FILL = 3.0
COMMISSION_BPS_PER_FILL = 0.6
COST_MULTIPLIERS = (1, 2, 3)
_BROKER_ZONE = ZoneInfo("Europe/Zurich")
_NASDAQ_SESSIONS = frozenset(
    stamp.date()
    for stamp in xcals.get_calendar("XNAS").sessions_in_range(
        "2019-01-01", "2025-12-31"
    )
)


@dataclass(frozen=True)
class N8Audit:
    status: str
    reason_code: str
    evidence: dict[str, Any]


class N8LongOnly(Strategy):
    """Enter at the next open and exit at the following open, with one unit max."""

    def __init__(self, symbol: str, start: datetime, end: datetime):
        self.symbol = symbol
        self.start = start
        self.end = end
        self.pending_entry: Any | None = None
        self.pending_exit: Any | None = None
        self.entry_signal_at: datetime | None = None
        self.executed_signals: list[datetime] = []
        self.orders: list[dict[str, Any]] = []
        self.started = False

    def on_start(self, broker):
        if broker.get_position(self.symbol) is not None:
            raise RuntimeError("ENGINE_EXECUTION_INVALID: position exists at run start")
        self.started = True

    def on_data(self, timestamp, data, context, broker):
        if not self.started:
            raise RuntimeError("ENGINE_EXECUTION_INVALID: on_start was not called")
        position = broker.get_position(self.symbol)
        quantity = float(position.quantity) if position else 0.0
        if self.pending_entry is not None:
            if self.pending_entry.status == OrderStatus.FILLED:
                if quantity != 1.0:
                    raise RuntimeError(
                        "ENGINE_EXECUTION_INVALID: entry quantity differs from one unit"
                    )
                self.pending_entry = None
                self.pending_exit = broker.submit_order(self.symbol, -1.0)
                if self.pending_exit is None:
                    raise RuntimeError(
                        "ENGINE_EXECUTION_INVALID: native exit order rejected"
                    )
                self.orders[-1]["exit_order"] = self.pending_exit
            elif self.pending_entry.status in (
                OrderStatus.CANCELLED,
                OrderStatus.REJECTED,
            ):
                raise RuntimeError(
                    "ENGINE_EXECUTION_INVALID: native entry was cancelled or rejected"
                )
            else:
                return
        if self.pending_exit is not None:
            if self.pending_exit.status == OrderStatus.FILLED:
                if quantity != 0.0:
                    raise RuntimeError(
                        "ENGINE_EXECUTION_INVALID: exit left an open position"
                    )
                self.pending_exit = None
                self.entry_signal_at = None
            elif self.pending_exit.status in (
                OrderStatus.CANCELLED,
                OrderStatus.REJECTED,
            ):
                raise RuntimeError(
                    "ENGINE_EXECUTION_INVALID: native exit was cancelled or rejected"
                )
            else:
                return
        if quantity != 0.0 or timestamp < self.start or timestamp >= self.end:
            return
        bar = data.get(self.symbol)
        if bar is None:
            return
        signal = bar.get("signals", {})
        if signal.get("m8_n8_long") != 1:
            return
        if self.pending_entry is not None or self.pending_exit is not None:
            return
        order = broker.submit_order(self.symbol, 1.0)
        if order is None:
            raise RuntimeError("ENGINE_EXECUTION_INVALID: native entry order rejected")
        self.pending_entry = order
        self.entry_signal_at = timestamp
        self.executed_signals.append(timestamp)
        self.orders.append(
            {"signal_at": timestamp, "entry_order": order, "exit_order": None}
        )

    def on_end(self, broker):
        position = broker.get_position(self.symbol)
        if position is not None and position.quantity:
            raise RuntimeError(
                "ENGINE_EXECUTION_INVALID: open position at end of source"
            )
        if self.pending_entry is not None or self.pending_exit is not None:
            raise RuntimeError(
                "ENGINE_EXECUTION_INVALID: pending order at end of source"
            )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def expected_signals(
    data: pl.DataFrame, features: pl.DataFrame, start: datetime, end: datetime
) -> list[datetime]:
    """Independent signal oracle; feature values come from the managed gateway."""
    price_rows = data.sort(["symbol", "timestamp"]).to_dicts()
    feature_rows = features.sort(["symbol", "timestamp"]).to_dicts()
    if len(price_rows) != len(feature_rows):
        raise FeatureContractError(
            "FEATURE_INPUT_IDENTITY_DRIFT", "feature rows differ from source rows"
        )
    start, end = _utc(start), _utc(end)
    valid: list[datetime] = []
    previous_highs: list[float] = []
    active_symbol: str | None = None
    for index, (bar, feature) in enumerate(zip(price_rows, feature_rows, strict=True)):
        if bar["symbol"] != active_symbol:
            active_symbol = bar["symbol"]
            previous_highs = []
        stamp = _utc(bar["timestamp"])
        level = max(previous_highs[-50:]) if len(previous_highs) >= 50 else None
        scheduled = all(
            _dukascopy_bar_complete(stamp + offset)
            for offset in (timedelta(0), BAR, 2 * BAR)
        )
        if (
            start <= stamp < end
            and stamp + 2 * BAR < end
            and level is not None
            and bar["close"] > level
            and feature["prior_high_50"] is not None
            and math.isclose(
                float(feature["prior_high_50"]), level, rel_tol=0.0, abs_tol=1e-9
            )
            and scheduled
        ):
            valid.append(stamp)
        previous_highs.append(float(bar["high"]))
    return valid


def _dukascopy_open(timestamp: datetime) -> bool:
    """Frozen Dukascopy weekly schedule with conservative known US market holidays."""
    stamp = _utc(timestamp)
    if stamp.weekday() < 5 and stamp.date() not in _NASDAQ_SESSIONS:
        return False
    season_clock = stamp.astimezone(_BROKER_ZONE)
    minute = stamp.hour * 60 + stamp.minute
    summer = season_clock.dst() is not None and season_clock.dst().total_seconds() != 0
    opening, closing = (22 * 60, 20 * 60 + 15) if summer else (23 * 60, 21 * 60 + 15)
    if stamp.weekday() == 5:
        return False
    if stamp.weekday() == 6:
        return minute >= opening
    if stamp.weekday() == 4:
        return minute < closing
    return minute < closing or minute >= opening


def _dukascopy_bar_complete(timestamp: datetime) -> bool:
    """Require the full 30m interval to end before a scheduled break."""
    return _dukascopy_open(timestamp) and _dukascopy_open(
        _utc(timestamp) + BAR - timedelta(minutes=1)
    )


def _assert_scheduled_fills_present(data: pl.DataFrame, signals: list[datetime]) -> None:
    observed = {_utc(value) for value in data["timestamp"].to_list()}
    missing = [
        {"signal_at": signal.isoformat(), "missing": [
            (signal + offset).isoformat()
            for offset in (BAR, 2 * BAR) if signal + offset not in observed
        ]}
        for signal in signals
        if any(signal + offset not in observed for offset in (BAR, 2 * BAR))
    ]
    if missing:
        raise FeatureContractError(
            "EXECUTION_EXCEPTION", f"scheduled signal has missing actual fill bars: {missing[:10]}"
        )


@cache
def _dukascopy_day_open(day) -> bool:
    return any(
        _dukascopy_bar_complete(datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC))
        for hour in range(24)
        for minute in (0, 30)
    )


def _feed(
    data: pl.DataFrame, computation: FeatureComputation, start: datetime, end: datetime
) -> tuple[DataFeed, list[datetime]]:
    ordered = data.sort(["symbol", "timestamp"])
    signals = expected_signals(ordered, computation.data, start, end)
    signal_set = set(signals)
    prices = ordered.rename({"symbol": "asset"}).select(
        "timestamp", "asset", "open", "high", "low", "close", "volume"
    )
    signal_frame = (
        computation.data.rename({"symbol": "asset"})
        .with_columns(
            pl.col("timestamp")
            .map_elements(
                lambda value: int(_utc(value) in signal_set), return_dtype=pl.Int8
            )
            .alias("m8_n8_long")
        )
        .select("timestamp", "asset", "m8_n8_long")
    )
    return DataFeed(prices_df=prices, signals_df=signal_frame), signals


def _run_one(
    data: pl.DataFrame,
    computation: FeatureComputation,
    contract: ResearchContractV1,
    start: datetime,
    end: datetime,
    cost_multiple: int,
) -> tuple[Any, N8LongOnly, list[datetime]]:
    if cost_multiple not in COST_MULTIPLIERS:
        raise ValueError("TRIAL_UNDECLARED: cost scenario was not preregistered")
    feed, expected = _feed(data, computation, start, end)
    symbol = contract.dataset.source_symbol
    strategy = N8LongOnly(symbol, _utc(start), _utc(end))
    config = BacktestConfig(
        initial_cash=INITIAL_CASH,
        allow_short_selling=False,
        allow_leverage=False,
        execution_mode=ExecutionMode.NEXT_BAR,
        fill_ordering=FillOrdering.EXIT_FIRST,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=COMMISSION_BPS_PER_FILL * cost_multiple / 10_000,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=BASE_COST_BPS_PER_FILL * cost_multiple / 10_000,
    )
    # The engine has no CFD asset class. This uses one normalized $/point unit.
    # The Equity label is an accounting adapter, not a product or multiplier claim.
    contract_spec = ContractSpec(
        symbol=symbol, asset_class=AssetClass.EQUITY, multiplier=UNIT_MULTIPLIER
    )
    result = Engine(
        feed, strategy, config, contract_specs={symbol: contract_spec}
    ).run()
    return result, strategy, expected


def audit_n8_result(
    result: Any,
    strategy: N8LongOnly,
    data: pl.DataFrame,
    expected: list[datetime],
    *,
    cost_multiple: int,
) -> N8Audit:
    fills = result.to_fills_dataframe().sort("timestamp")
    equity = result.to_equity_dataframe().sort("timestamp")
    if fills.height != len(strategy.executed_signals) * 2:
        return N8Audit(
            "FAILED", "ENGINE_EXECUTION_INVALID", {"fill_count": fills.height}
        )
    if strategy.executed_signals != sorted(strategy.executed_signals):
        return N8Audit(
            "FAILED", "ENGINE_EXECUTION_INVALID", {"signals_out_of_order": True}
        )
    if any(signal not in expected for signal in strategy.executed_signals):
        return N8Audit("FAILED", "FEATURE_CAUSALITY_FAIL", {"unexpected_signal": True})
    if equity.is_empty() or "equity" not in equity.columns:
        return N8Audit(
            "FAILED", "ENGINE_EXECUTION_INVALID", {"equity_ledger_missing": True}
        )

    bars = data.sort(["symbol", "timestamp"])
    bars_by_time = {_utc(row["timestamp"]): row for row in bars.to_dicts()}
    fill_rows = fills.to_dicts()
    normalize_fill_times = [_utc(row["timestamp"]) for row in fill_rows]
    paired: list[dict[str, Any]] = []
    for trade_index, signal in enumerate(strategy.executed_signals):
        entry, exit_fill = fill_rows[2 * trade_index : 2 * trade_index + 2]
        expected_entry = signal + BAR
        expected_exit = signal + 2 * BAR
        if (
            normalize_fill_times[2 * trade_index] != expected_entry
            or normalize_fill_times[2 * trade_index + 1] != expected_exit
            or entry["side"] != "buy"
            or exit_fill["side"] != "sell"
            or not math.isclose(float(entry["quantity"]), 1.0, abs_tol=1e-12)
            or not math.isclose(float(exit_fill["quantity"]), 1.0, abs_tol=1e-12)
            or expected_entry not in bars_by_time
            or expected_exit not in bars_by_time
        ):
            return N8Audit(
                "FAILED", "ENGINE_EXECUTION_INVALID", {"trade_index": trade_index}
            )
        expected_entry_price = float(bars_by_time[expected_entry]["open"])
        expected_exit_price = float(bars_by_time[expected_exit]["open"])
        buy_cost_rate = BASE_COST_BPS_PER_FILL * cost_multiple / 10_000
        commission_rate = COMMISSION_BPS_PER_FILL * cost_multiple / 10_000
        if not math.isclose(
            float(entry["price"]),
            expected_entry_price * (1 + buy_cost_rate),
            rel_tol=1e-8,
            abs_tol=1e-6,
        ) or not math.isclose(
            float(exit_fill["price"]),
            expected_exit_price * (1 - buy_cost_rate),
            rel_tol=1e-8,
            abs_tol=1e-6,
        ):
            return N8Audit(
                "FAILED",
                "ENGINE_EXECUTION_INVALID",
                {"fill_price_or_cost_mismatch": trade_index},
            )
        for fill in (entry, exit_fill):
            expected_commission = float(fill["price"]) * commission_rate
            if not math.isclose(
                float(fill["commission"]), expected_commission,
                rel_tol=1e-8, abs_tol=1e-8
            ):
                return N8Audit(
                    "FAILED", "ENGINE_EXECUTION_INVALID",
                    {"commission_mismatch": trade_index,
                     "observed": float(fill["commission"]),
                     "expected": expected_commission},
                )
        paired.append(
            {
                "signal_at": signal.isoformat(),
                "entry_at": expected_entry.isoformat(),
                "exit_at": expected_exit.isoformat(),
                "entry_price": float(entry["price"]),
                "exit_price": float(exit_fill["price"]),
                "pnl_normalized": (float(exit_fill["price"]) - float(entry["price"]))
                * UNIT_MULTIPLIER,
                "pnl_gross_normalized": (
                    float(bars_by_time[expected_exit]["open"])
                    - float(bars_by_time[expected_entry]["open"])
                )
                * UNIT_MULTIPLIER,
            }
        )

    cash = INITIAL_CASH
    position = 0.0
    close_by_time = {
        _utc(row["timestamp"]): float(row["close"]) for row in bars.to_dicts()
    }
    fills_by_time: dict[datetime, list[dict[str, Any]]] = {}
    for row in fill_rows:
        fills_by_time.setdefault(_utc(row["timestamp"]), []).append(row)
    ledger = []
    for row in equity.to_dicts():
        timestamp = _utc(row["timestamp"])
        if timestamp not in close_by_time:
            return N8Audit(
                "FAILED",
                "ENGINE_EXECUTION_INVALID",
                {"equity_timestamp_missing_from_source": timestamp.isoformat()},
            )
        for fill in fills_by_time.get(timestamp, []):
            quantity = float(fill["quantity"])
            if fill["side"] == "buy":
                cash -= quantity * float(fill["price"]) * UNIT_MULTIPLIER + float(
                    fill["commission"]
                )
                position += quantity
            else:
                cash += quantity * float(fill["price"]) * UNIT_MULTIPLIER - float(
                    fill["commission"]
                )
                position -= quantity
        expected_equity = cash + position * close_by_time[timestamp] * UNIT_MULTIPLIER
        observed_equity = float(row["equity"])
        if not math.isclose(
            expected_equity, observed_equity, rel_tol=1e-10, abs_tol=1e-5
        ):
            return N8Audit(
                "FAILED",
                "ENGINE_EXECUTION_INVALID",
                {
                    "timestamp": timestamp.isoformat(),
                    "independent_equity": expected_equity,
                    "native_equity": observed_equity,
                },
            )
        ledger.append({"timestamp": timestamp, "equity": observed_equity})
    if (
        position != 0
        or strategy.pending_entry is not None
        or strategy.pending_exit is not None
    ):
        return N8Audit(
            "FAILED", "ENGINE_EXECUTION_INVALID", {"ending_position": position}
        )
    return N8Audit(
        "PASS",
        "N8_NATIVE_FILLS_RECONCILED",
        {
            "cost_multiple": cost_multiple,
            "slippage_bps_per_fill": BASE_COST_BPS_PER_FILL * cost_multiple,
            "commission_bps_per_fill": COMMISSION_BPS_PER_FILL * cost_multiple,
            "expected_signal_count": len(expected),
            "executed_trade_count": len(paired),
            "fill_count": fills.height,
            "initial_equity_normalized": INITIAL_CASH,
            "final_equity_normalized": float(equity["equity"][-1]),
            "cash_position_ledger_rows": len(ledger),
            "trades": paired,
            "limitations": [
                "Eligibility uses the published Dukascopy weekly schedule; special holiday hours remain a broker-calendar limitation.",
                "Unexpected missing scheduled fill bars block the trial; they are not silently excluded.",
                "Costs are exploratory 3/6/9 bps adverse price impact plus 0.6/1.2/1.8 bps explicit commission per fill, not broker quotes or market-impact estimates.",
                "The normalized $1 per point unit is not a broker contract multiplier or executable CFD PnL.",
            ],
        },
    )


def summarize_n8_scenario(
    result: Any,
    audit: dict[str, Any],
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    """Use native trade metrics and PortfolioAnalysis on a full UTC-day series."""
    equity = result.to_equity_dataframe()
    daily = (
        equity.with_columns(pl.col("timestamp").dt.date().alias("day"))
        .group_by("day")
        .agg(pl.col("equity").last().alias("equity"))
        .sort("day")
    )
    start_day, end_day = _utc(start).date(), _utc(end).date()
    baseline = daily.filter(pl.col("day") < start_day).tail(1)
    previous_equity = float(baseline["equity"][0]) if baseline.height else INITIAL_CASH
    observed = {row["day"]: float(row["equity"]) for row in daily.to_dicts()}
    calendar_days = []
    cursor = start_day
    while cursor < end_day:
        if _dukascopy_day_open(cursor):
            calendar_days.append(cursor)
        cursor += timedelta(days=1)
    equities = []
    for day in calendar_days:
        if day in observed:
            previous_equity = observed[day]
        else:
            raise FeatureContractError(
                "SOURCE_COVERAGE_EXCEPTION",
                f"no native equity mark on scheduled open date {day.isoformat()}",
            )
        equities.append(previous_equity)
    points = pl.DataFrame({"day": calendar_days, "equity": equities})
    returns = points.select(
        (pl.col("equity") / pl.col("equity").shift(1).fill_null(INITIAL_CASH) - 1).alias("return")
    )["return"]
    analysis = PortfolioAnalysis(
        returns=returns,
        dates=points["day"],
        periods_per_year=252,
    )
    portfolio = analysis.compute_summary_stats() if len(returns) >= 2 else None
    if portfolio is not None:
        values = [float(value) for value in returns.to_list()]
        mean = sum(values) / len(values)
        sample_variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
        oracle_sharpe = mean / math.sqrt(sample_variance) * math.sqrt(252) if sample_variance > 0 else None
        wealth = [1.0]
        for value in values:
            wealth.append(wealth[-1] * (1 + value))
        peak = wealth[0]
        drawdowns = []
        for value in wealth[1:]:
            peak = max(peak, value)
            drawdowns.append(value / peak - 1)
        oracle_max_drawdown = min(drawdowns, default=0.0)
        if oracle_sharpe is not None and not math.isclose(
            float(portfolio.sharpe_ratio), oracle_sharpe, rel_tol=1e-8, abs_tol=1e-10
        ):
            raise FeatureContractError("PORTFOLIO_METRIC_MISMATCH", "PortfolioAnalysis Sharpe differs from independent sample-variance oracle")
        if not math.isclose(float(portfolio.max_drawdown), oracle_max_drawdown, rel_tol=1e-8, abs_tol=1e-10):
            raise FeatureContractError("PORTFOLIO_METRIC_MISMATCH", "PortfolioAnalysis max drawdown differs from independent wealth-path oracle")
        if portfolio.max_drawdown < 0 and not math.isclose(
            float(portfolio.calmar_ratio), float(portfolio.annual_return) / abs(float(portfolio.max_drawdown)), rel_tol=1e-8, abs_tol=1e-10
        ):
            raise FeatureContractError("PORTFOLIO_METRIC_MISMATCH", "PortfolioAnalysis Calmar differs from annual-return/drawdown oracle")

    native = result.metrics
    return {
        "trade_count": native["num_trades"],
        "trade_win_rate_native": native["win_rate"],
        "net_trade_expectancy_native": native["expectancy"],
        "total_gross_pnl_normalized_native": native["total_gross_pnl"],
        "total_net_pnl_normalized_native": native["final_value"] - native["initial_cash"],
        "daily_sharpe_252": float(portfolio.sharpe_ratio)
        if portfolio is not None and math.isfinite(float(portfolio.sharpe_ratio))
        else None,
        "annual_return_252": float(portfolio.annual_return)
        if portfolio is not None and math.isfinite(float(portfolio.annual_return))
        else None,
        "calmar_ratio_252": float(portfolio.calmar_ratio)
        if portfolio is not None and math.isfinite(float(portfolio.calmar_ratio))
        else None,
        "max_drawdown": float(portfolio.max_drawdown)
        if portfolio is not None and math.isfinite(float(portfolio.max_drawdown))
        else None,
        "annualization_note": "PortfolioAnalysis uses 252 periods per year on scheduled CFD trading dates, including Sundays; scheduled closed dates are omitted, and open dates require observed marks. The 252 annualization is a convention for this six-day CFD schedule, not a claim that it has exactly 252 sessions per year.",
        "risk_metrics_status": "COMPUTED" if portfolio is not None else "INSUFFICIENT_OBSERVATIONS",
        "independent_metric_sanity": (
            "PASS: sample-variance Sharpe, initial-equity drawdown path, and Calmar arithmetic reconciled to PortfolioAnalysis"
            if portfolio is not None
            else "NOT_RUN: fewer than two scheduled trading-date returns"
        ),
        "daily_risk_metrics_source": "ml4t.diagnostic.api.PortfolioAnalysis",
        "daily_equity_observations": len(calendar_days),
        "daily_return_observations": len(returns),
        "closed_dates_omitted": (end_day - start_day).days - len(calendar_days),
        "daily_zero_return_observations": int((returns == 0).sum()),
        "daily_sampling": "initial cash before first evaluation date; last native equity mark per scheduled UTC CFD trading date; zero return on open dates without trades; scheduled closed dates omitted; missing scheduled-open marks block",
        "native_metrics_note": "Native engine trade expectancy is retained in the engine's return units. Intraday engine Sharpe/CAGR are deliberately omitted.",
    }


def classify_n8_economics(scenarios: list[dict[str, Any]]) -> str:
    """Apply the frozen outcome rule to native metrics; this does not qualify approval."""
    base, stress_2x, stress_3x = scenarios
    metrics = [item["metrics"] for item in (base, stress_2x, stress_3x)]
    if any(item["trade_count"] == 0 for item in metrics):
        return "INCONCLUSIVE_NO_TRADES"
    expectancy = [item["net_trade_expectancy_native"] for item in metrics]
    gross = metrics[0]["total_gross_pnl_normalized_native"]
    if any(value is None or not math.isfinite(float(value)) for value in expectancy):
        return "INCONCLUSIVE_INVALID_NATIVE_METRIC"
    if gross <= 0 or expectancy[0] <= 0:
        return "FALSIFIED_NONPOSITIVE_GROSS_OR_BASE_NET_EXPECTANCY"
    if expectancy[1] <= 0 or expectancy[2] <= 0:
        return "POSITIVE_BASELINE_FRAGILE_TO_COST_STRESS"
    return "NOT_FALSIFIED_IN_RETROSPECTIVE_SAMPLE_ONLY"


def run_permitted_n8(
    root: str,
    intent: RunIntentV1 | dict[str, Any],
    data: pl.DataFrame,
    computation: FeatureComputation,
    contract: ResearchContractV1,
    *,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    checked = preflight_run(root, intent, computation, data, contract)
    if checked.status != "PASS" or checked.permit is None:
        return {"status": "BLOCKED", "reason_code": checked.reason_code}
    permit = RunPermitV1.model_validate(checked.permit.model_dump(mode="json"))
    if (
        permit.live_order_authority
        or permit.identity.engine_version != "0.1.7"
        or permit.identity.engine != "ml4t.backtest"
        or permit.multiplier.value != UNIT_MULTIPLIER
        or permit.costs.commission_bps != COMMISSION_BPS_PER_FILL
        or permit.costs.slippage_bps != BASE_COST_BPS_PER_FILL
    ):
        return {"status": "BLOCKED", "reason_code": "IDENTITY_DRIFT"}
    if _utc(start) != _utc(permit.evaluation_start) or _utc(end) != _utc(
        permit.evaluation_end
    ):
        return {"status": "BLOCKED", "reason_code": "EVALUATION_WINDOW_INVALID"}

    signals = expected_signals(data, computation.data, start, end)
    try:
        _assert_scheduled_fills_present(data, signals)
    except FeatureContractError as exc:
        return {
            "status": "BLOCKED",
            "reason_code": exc.reason_code,
            "detail": str(exc),
        }

    scenarios = []
    for multiple in COST_MULTIPLIERS:
        result, strategy, expected = _run_one(
            data, computation, contract, start, end, multiple
        )
        audit = audit_n8_result(
            result, strategy, data, expected, cost_multiple=multiple
        )
        if audit.status != "PASS":
            return {
                "status": "FAILED",
                "reason_code": audit.reason_code,
                "audit": audit.evidence,
            }
        scenarios.append(
            {
                "scenario": f"{multiple}x",
                "audit": audit.evidence,
                "metrics": summarize_n8_scenario(result, audit.evidence, start, end),
                "fills": result.to_fills_dataframe(),
                "equity": result.to_equity_dataframe(),
            }
        )
    return {
        "status": "COMPLETED",
        "trial_id": permit.trial_id,
        "permit_sha256": permit.permit_sha256,
        "engine_version": permit.identity.engine_version,
        "data_rows": data.height,
        "evaluation_start": _utc(start).isoformat(),
        "evaluation_end_exclusive": _utc(end).isoformat(),
        "cost_scenarios": scenarios,
        "economic_result": classify_n8_economics(scenarios),
        "research_process_status": "QUALIFIED" if all(
            item["audit"]["status"] == "PASS" for item in scenarios
        ) else "UNQUALIFIED",
        "broker_execution_status": "UNQUALIFIED",
        "classification": "EXPLORATORY_HISTORICAL_CFD_PRICE_RESEARCH",
        "approval_status": "NOT_APPROVED",
        "live_order_authority": False,
    }
