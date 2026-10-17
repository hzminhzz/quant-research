"""Bridge reconciled M8 native runs into reusable daily sleeve evidence."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import polars as pl

from src.portfolio_evidence import (
    BudgetUnit,
    MarkCadence,
    PortfolioComparison,
    ReturnUnit,
    RiskBudgetPlan,
    SleeveEvidence,
    SleeveIdentity,
    TrialDisclosure,
    compare_sleeves,
    summarize_daily_returns,
)

INITIAL_EQUITY = 100_000.0
START = date(2020, 1, 1)
END_EXCLUSIVE = date(2025, 1, 1)
SESSION_BAR = timedelta(minutes=30)
CAPITAL_WEIGHTS = (0.0, 0.25, 0.5, 1.0)
RESAMPLE_SAMPLES = 100
RESAMPLE_SEED = 42
RESAMPLE_BLOCK_SIZE = 5
_REQUIRED_AUTHORITIES = {"source_sha256", "cost_authority_sha256", "calendar_authority_sha256"}


@dataclass(frozen=True)
class NativeScenario:
    """One cost scenario's native result and independent full-mark reconciliation."""

    scenario: str
    result: Any
    reconciliation_report: Mapping[str, Any]


def _utc(value: datetime | str, *, native_clock: bool = False) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime):
        raise TypeError("timestamps must be datetime or ISO datetime values")
    if value.tzinfo is None:
        if not native_clock:
            raise ValueError("source and oracle timestamps must be timezone-aware")
        # Pinned ML4T 0.1.7 frames strip the timezone from their UTC clock labels.
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _frozen_xnas_sessions() -> tuple[tuple[date, datetime, datetime], ...]:
    from src.research_control.m8_cash_calendar import _xnas_schedule, cash_session_dates

    start, end = datetime(2020, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC)
    sessions = []
    for day in cash_session_dates(start, end):
        schedule = _xnas_schedule(day)
        if schedule is None:
            raise ValueError(f"frozen XNAS session lacks schedule: {day.isoformat()}")
        opens, closes = (_utc(value) for value in schedule)
        sessions.append((day, opens, closes))
    return tuple(sessions)


def _native_frame(result: Any, method: str, required: set[str]) -> list[dict[str, Any]]:
    frame = getattr(result, method)()
    if not isinstance(frame, pl.DataFrame) or not required <= set(frame.columns):
        raise ValueError(f"native {method} is missing required columns: {sorted(required)}")
    rows = frame.to_dicts()
    stamps = [_utc(row["timestamp"], native_clock=True) for row in rows]
    if len(set(stamps)) != len(stamps):
        raise ValueError(f"native {method} contains duplicate timestamps")
    return [dict(row, timestamp=stamp) for row, stamp in zip(rows, stamps, strict=True)]


def _reconciliation_rows(scenario: NativeScenario) -> list[dict[str, Any]]:
    report = scenario.reconciliation_report
    if report.get("status") != "PASS":
        raise ValueError(f"{scenario.scenario} independent reconciliation did not PASS")
    ledger = report.get("ledger")
    if isinstance(ledger, pl.DataFrame):
        rows = ledger.to_dicts()
    elif isinstance(ledger, Sequence) and not isinstance(ledger, (str, bytes)):
        rows = list(ledger)
    else:
        raise TypeError(f"{scenario.scenario} reconciliation must contain a full ledger")
    required = {"timestamp", "cash", "position"}
    if not rows or any(not required <= set(row) for row in rows):
        raise ValueError(f"{scenario.scenario} reconciliation ledger lacks timestamp/cash/position")
    normalized = []
    for row in rows:
        equity = row.get("equity", row.get("marked_equity", row.get("native_equity")))
        if equity is None:
            raise ValueError(f"{scenario.scenario} reconciliation ledger lacks equity")
        if "marked_equity" in row and "native_equity" in row and not math.isclose(
            float(row["marked_equity"]), float(row["native_equity"]), rel_tol=1e-10, abs_tol=1e-7
        ):
            raise ValueError(f"{scenario.scenario} independent/native equity differ in reconciliation")
        normalized.append({**row, "timestamp": _utc(row["timestamp"]), "equity": float(equity)})
    stamps = [row["timestamp"] for row in normalized]
    if len(set(stamps)) != len(stamps):
        raise ValueError(f"{scenario.scenario} reconciliation ledger has duplicate timestamps")
    return normalized


def _validate_ledger(
    scenario: NativeScenario,
    source: Mapping[datetime, Mapping[str, Any]],
) -> tuple[dict[datetime, dict[str, Any]], dict[datetime, dict[str, Any]], dict[datetime, dict[str, Any]]]:
    equity_rows = _native_frame(scenario.result, "to_equity_dataframe", {"timestamp", "equity"})
    portfolio_rows = _native_frame(
        scenario.result, "to_portfolio_state_dataframe", {"timestamp", "cash", "open_positions", "net_exposure"}
    )
    expected_times = set(source)
    equity = {row["timestamp"]: row for row in equity_rows}
    portfolio = {row["timestamp"]: row for row in portfolio_rows}
    reconciliation = {row["timestamp"]: row for row in _reconciliation_rows(scenario)}
    if set(equity) != expected_times or set(portfolio) != expected_times or set(reconciliation) != expected_times:
        raise ValueError(f"{scenario.scenario} native/reconciliation marks must cover every source row exactly")
    for stamp, bar in source.items():
        state, independent, mark = portfolio[stamp], reconciliation[stamp], equity[stamp]
        values = (state["cash"], independent["cash"], independent["equity"], mark["equity"])
        if any(not math.isfinite(float(value)) for value in values):
            raise ValueError(f"{scenario.scenario} has nonfinite cash/equity at {stamp.isoformat()}")
        if not math.isclose(float(state["cash"]), float(independent["cash"]), rel_tol=1e-10, abs_tol=1e-7):
            raise ValueError(f"{scenario.scenario} native cash does not match reconciliation at {stamp.isoformat()}")
        if not math.isclose(float(mark["equity"]), independent["equity"], rel_tol=1e-10, abs_tol=1e-6):
            raise ValueError(f"{scenario.scenario} native equity does not match reconciliation at {stamp.isoformat()}")
        position = float(independent["position"])
        expected_exposure = position * float(bar["close"])
        if not math.isclose(float(state["net_exposure"]), expected_exposure, rel_tol=1e-10, abs_tol=1e-6):
            raise ValueError(f"{scenario.scenario} native position/exposure does not match reconciliation at {stamp.isoformat()}")
        if int(state["open_positions"]) != int(position != 0.0):
            raise ValueError(f"{scenario.scenario} native open positions do not match reconciliation at {stamp.isoformat()}")
        if "equity" in independent and not math.isclose(
            float(state["cash"]) + expected_exposure, independent["equity"], rel_tol=1e-10, abs_tol=1e-6
        ):
            raise ValueError(f"{scenario.scenario} reconciled cash/position does not sum to equity at {stamp.isoformat()}")
    warmup = [stamp for stamp in expected_times if stamp.date() < START]
    if not warmup:
        raise ValueError("native warmup marks before 2020-01-01 are required")
    for stamp in warmup:
        state, independent, mark = portfolio[stamp], reconciliation[stamp], equity[stamp]
        if (not math.isclose(float(mark["equity"]), INITIAL_EQUITY, abs_tol=1e-7)
                or not math.isclose(float(state["cash"]), INITIAL_EQUITY, abs_tol=1e-7)
                or float(independent["position"]) != 0.0
                or int(state["open_positions"]) != 0):
            raise ValueError("native pre-2020 warmup must remain flat at initial 100000 equity")
    return equity, portfolio, reconciliation


def _daily_gross_and_drag(
    scenario: NativeScenario,
    source: Mapping[datetime, Mapping[str, Any]],
    sessions: Sequence[tuple[date, datetime, datetime]],
) -> tuple[dict[date, float], dict[date, float]]:
    fills = _native_frame(scenario.result, "to_fills_dataframe", {"timestamp", "side", "quantity", "price", "commission"})
    fills.sort(key=lambda row: row["timestamp"])
    gross: dict[date, float] = {}
    drag: dict[date, float] = {}
    session_by_day = {day: (opens, closes) for day, opens, closes in sessions}
    open_trade: dict[str, float] | None = None
    for fill in fills:
        stamp, side = fill["timestamp"], str(fill["side"]).lower()
        if stamp not in source or side not in {"buy", "sell"}:
            raise ValueError(f"{scenario.scenario} fill lacks source open or is not a long-only fill")
        if stamp.date() not in session_by_day or not session_by_day[stamp.date()][0] <= stamp < session_by_day[stamp.date()][1]:
            raise ValueError(f"{scenario.scenario} fill is outside a frozen XNAS cash session")
        quantity, native_price, commission = (float(fill[key]) for key in ("quantity", "price", "commission"))
        raw_open = float(source[stamp]["open"])
        if (not all(math.isfinite(value) for value in (quantity, native_price, commission, raw_open))
                or quantity <= 0 or native_price <= 0 or raw_open <= 0 or commission < 0):
            raise ValueError(f"{scenario.scenario} has invalid native fill values")
        slip_per_unit = native_price - raw_open if side == "buy" else raw_open - native_price
        if slip_per_unit < -1e-8:
            raise ValueError(f"{scenario.scenario} contains favorable-price fill; adverse drag is not nonnegative")
        drag[stamp.date()] = drag.get(stamp.date(), 0.0) + max(0.0, slip_per_unit) * quantity + commission
        if side == "buy":
            if open_trade is not None:
                raise ValueError(f"{scenario.scenario} contains overlapping M8 entries")
            open_trade = {"timestamp": stamp, "price": raw_open, "quantity": quantity}
        else:
            if (open_trade is None or stamp.date() != open_trade["timestamp"].date()
                    or stamp - open_trade["timestamp"] != SESSION_BAR or not math.isclose(
                quantity, open_trade["quantity"], rel_tol=0.0, abs_tol=1e-12
            )):
                raise ValueError(f"{scenario.scenario} M8 exit does not pair same-day with its entry")
            day = stamp.date()
            gross[day] = gross.get(day, 0.0) + quantity * (raw_open - open_trade["price"])
            open_trade = None
    if open_trade is not None:
        raise ValueError(f"{scenario.scenario} ends with an unmatched M8 entry")
    return gross, drag


def _json_native_metrics(result: Any) -> dict[str, int | float | str | bool | None]:
    metrics = getattr(result, "metrics", {})
    if not isinstance(metrics, Mapping):
        return {}
    allowed = {"num_trades", "total_pnl", "final_value", "initial_cash", "win_rate", "expectancy", "total_gross_pnl"}
    return {
        key: (value.item() if hasattr(value, "item") else value)
        for key, value in metrics.items()
        if key in allowed and (value is None or isinstance(value, (int, float, str, bool)) or hasattr(value, "item"))
    }


def _identity_dict(identity: SleeveIdentity) -> dict[str, str]:
    return asdict(identity)


def _comparison_summary(comparison: PortfolioComparison) -> dict[str, Any]:
    native = dict(comparison.native_statistics)
    undefined = sorted(key for key, value in native.items() if not math.isfinite(value))
    return {
        "candidate_daily_audit": dict(comparison.summaries),
        "native_statistics": {key: None if key in undefined else value for key, value in native.items()},
        "undefined_native_statistics": undefined,
        "native_statistics_status": comparison.native_statistics_status,
        "pairwise_co_losses": [asdict(item) for item in comparison.pairwise_co_losses],
        "sleeve_loss_summaries": [asdict(item) for item in comparison.sleeve_loss_summaries],
        "selection_adjustment_allowed": comparison.selection_adjustment_allowed,
        "barrier_claim_allowed": comparison.barrier_claim_allowed,
        "unsupported_claim_reasons": list(comparison.unsupported_claim_reasons),
    }


def demonstration(
    data: pl.DataFrame,
    scenarios: Sequence[NativeScenario],
    *,
    identity: SleeveIdentity,
    cash_identity: SleeveIdentity,
    authorities: Mapping[str, str],
    trial_disclosure: TrialDisclosure,
    periods_per_year: int,
    include_sleeves: bool = False,
) -> dict[str, Any]:
    """Build JSON-safe daily overlays from reconciled native M8 1x/2x/3x runs.

    No engine is invoked. Scenario names identify native cost runs, not sleeves.
    The optional ``sleeves`` result member contains immutable evidence records;
    the always-JSON-safe ``report`` member remains compact.
    """
    if identity.strategy_id != "m8_n8_cash_session_v7":
        raise ValueError("M8 sleeve identity must be m8_n8_cash_session_v7")
    if identity.strategy_id == cash_identity.strategy_id:
        raise ValueError("M8 and cash baseline identities must differ")
    if identity.calendar_id != cash_identity.calendar_id:
        raise ValueError("M8 and cash baseline must use the same declared session calendar")
    if not _REQUIRED_AUTHORITIES <= set(authorities) or any(not isinstance(value, str) or not value.strip() for value in authorities.values()):
        raise ValueError(f"authorities must include nonempty {_REQUIRED_AUTHORITIES}")
    if type(periods_per_year) is not int or periods_per_year <= 0:
        raise ValueError("periods_per_year must be explicit and positive")
    if not isinstance(trial_disclosure, TrialDisclosure):
        raise TypeError("exact TrialDisclosure is required")
    if not isinstance(data, pl.DataFrame) or not {"timestamp", "open", "close"} <= set(data.columns) or data.is_empty():
        raise ValueError("M8 raw bars require timestamp, open, and close columns")
    rows = data.sort("timestamp").to_dicts()
    source_rows: dict[datetime, dict[str, Any]] = {}
    for row in rows:
        stamp = _utc(row["timestamp"])
        if stamp in source_rows:
            raise ValueError("raw M8 source timestamps must be unique")
        if stamp.date() >= END_EXCLUSIVE:
            raise ValueError("raw M8 bars cross the frozen 2020-2024 sample boundary")
        if not math.isfinite(float(row["open"])) or not math.isfinite(float(row["close"])) or min(float(row["open"]), float(row["close"])) <= 0:
            raise ValueError(f"raw M8 prices must be finite and positive at {stamp.isoformat()}")
        source_rows[stamp] = row
    names = [scenario.scenario for scenario in scenarios]
    if len(names) != 3 or set(names) != {"1x", "2x", "3x"}:
        raise ValueError("exactly one reconciled native 1x, 2x, and 3x scenario is required")
    by_name = {scenario.scenario: scenario for scenario in scenarios}
    sessions = _frozen_xnas_sessions()
    if not sessions:
        raise ValueError("frozen XNAS 2020-2024 session calendar is empty")
    expected_days = [day for day, _, _ in sessions]
    if expected_days[0] < START or expected_days[-1] >= END_EXCLUSIVE:
        raise ValueError("frozen XNAS sessions fall outside 2020-2024")

    # Preserve the frozen study's valuation policy: the last actual native
    # mark on each scheduled UTC date, not a new exact exchange-close tick.
    # No price/cash interpolation or synthetic zero-return dates are allowed.
    last_source_mark_by_day: dict[date, datetime] = {}
    for stamp in source_rows:
        last_source_mark_by_day[stamp.date()] = stamp
    for day in expected_days:
        if day not in last_source_mark_by_day:
            raise ValueError(f"missing native equity mark on scheduled open date {day.isoformat()}")

    dates = tuple(day.isoformat() for day in expected_days)
    cash_sleeve = SleeveEvidence(
        cash_identity, ReturnUnit.CAPITAL, dates,
        (0.0,) * len(sessions), (0.0,) * len(sessions), (0.0,) * len(sessions), (0.0,) * len(sessions),
        "daily-prior-net-equity-v1", "cash-baseline-equity", INITIAL_EQUITY, None,
        False, False, MarkCadence.DAILY, True,
    )
    native_scenario_reports = []
    portfolio_sleeves: dict[str, SleeveEvidence] = {}
    comparison_inputs: dict[tuple[str, float], PortfolioComparison] = {}
    for scenario_name in ("1x", "2x", "3x"):
        scenario = by_name[scenario_name]
        if scenario.reconciliation_report.get("status") != "PASS":
            raise ValueError(f"{scenario_name} independent reconciliation did not PASS")
        if scenario.reconciliation_report.get("cost_multiple") != int(scenario_name[0]):
            raise ValueError(f"{scenario_name} reconciliation must bind its native cost multiple")
        equity_rows, portfolio_rows, reconciliation_rows = _validate_ledger(scenario, source_rows)
        gross_pnl, execution_drag = _daily_gross_and_drag(scenario, source_rows, sessions)
        daily_equity = []
        close_times = []
        for day in expected_days:
            mark_at = last_source_mark_by_day[day]
            if mark_at not in equity_rows or mark_at not in portfolio_rows or mark_at not in reconciliation_rows:
                raise ValueError(f"missing native daily equity/cash/position mark for {day.isoformat()}")
            state = portfolio_rows[mark_at]
            independent = reconciliation_rows[mark_at]
            if (int(state["open_positions"]) != 0 or not math.isclose(float(state["net_exposure"]), 0.0, abs_tol=1e-8)
                    or float(independent["position"]) != 0.0):
                raise ValueError(f"M8 must be terminally flat at every daily valuation mark: {day.isoformat()}")
            daily_equity.append(float(equity_rows[mark_at]["equity"]))
            close_times.append(mark_at)
        denominators = []
        gross_returns, drag_returns, carry_returns, net_returns = [], [], [], []
        prior_equity = INITIAL_EQUITY
        for day, equity in zip(expected_days, daily_equity, strict=True):
            if not math.isfinite(equity) or prior_equity <= 0:
                raise ValueError(f"invalid prior net equity for {day.isoformat()}")
            denominator = prior_equity
            gross_return = gross_pnl.get(day, 0.0) / denominator
            drag_return = execution_drag.get(day, 0.0) / denominator
            net_return = (equity - prior_equity) / denominator
            if not math.isclose(net_return, gross_return - drag_return, rel_tol=1e-10, abs_tol=1e-12):
                raise ValueError(f"price-gross less native slippage/commission does not reconcile on {day.isoformat()}")
            denominators.append(denominator)
            gross_returns.append(gross_return)
            drag_returns.append(drag_return)
            carry_returns.append(0.0)
            net_returns.append(net_return)
            prior_equity = equity
        scenario_identity = replace(identity, cost_model_id=f"{identity.cost_model_id}:{scenario_name}")
        evidence = SleeveEvidence(
            scenario_identity, ReturnUnit.CAPITAL, dates,
            tuple(gross_returns), tuple(drag_returns), tuple(carry_returns), tuple(net_returns),
            "daily-prior-net-equity-v1", "native-prior-net-equity", tuple(denominators), None,
            False, False, MarkCadence.DAILY, True,
        )
        portfolio_sleeves[scenario_name] = evidence
        comparisons = []
        for allocation in CAPITAL_WEIGHTS:
            plan = RiskBudgetPlan(
                ((cash_sleeve.identity.strategy_id, 1.0),),
                ((scenario_identity.strategy_id, allocation), (cash_sleeve.identity.strategy_id, 1.0 - allocation)),
                BudgetUnit.CAPITAL, 1.0, periods_per_year, trial_disclosure,
            )
            comparison = compare_sleeves(
                (evidence, cash_sleeve), plan, samples=RESAMPLE_SAMPLES,
                block_size=RESAMPLE_BLOCK_SIZE, seed=RESAMPLE_SEED,
            )
            comparison_inputs[(scenario_name, allocation)] = comparison
            comparisons.append({
                "m8_capital_weight": allocation,
                "cash_capital_weight": 1.0 - allocation,
                "risk_budget_plan": {
                    "budget_unit": "capital_fraction",
                    "total_budget": 1.0,
                    "baseline_weights": [[cash_sleeve.identity.strategy_id, 1.0]],
                    "candidate_weights": [[scenario_identity.strategy_id, allocation],
                                           [cash_sleeve.identity.strategy_id, 1.0 - allocation]],
                    "periods_per_year": periods_per_year,
                },
                "comparison": _comparison_summary(comparison),
                "paired_resampling": {
                    "seed": RESAMPLE_SEED,
                    "block_size": RESAMPLE_BLOCK_SIZE,
                    "samples": RESAMPLE_SAMPLES,
                    "shared_index_sha256": hashlib.sha256(json.dumps(comparison.resampled_indices, separators=(",", ":")).encode()).hexdigest(),
                },
            })
        standalone = comparison_inputs[(scenario_name, 1.0)]
        native_scenario_reports.append({
            "scenario": scenario_name,
            "identity": _identity_dict(scenario_identity),
            "native_backtest_metrics": _json_native_metrics(scenario.result),
            "standalone_daily_risk_audit": _comparison_summary(standalone),
            "daily_sessions": len(expected_days),
            "native_daily_marks": len(close_times),
            "allocation_comparisons": comparisons,
        })

    bootstrap_hashes = {
        row["paired_resampling"]["shared_index_sha256"]
        for scenario in native_scenario_reports for row in scenario["allocation_comparisons"]
    }
    if len(bootstrap_hashes) != 1:
        raise ValueError("paired M8/cash comparisons did not use identical shared block indices")
    cost_stresses = []
    for allocation in CAPITAL_WEIGHTS:
        comparison = comparison_inputs[("1x", allocation)]
        cost_stresses.append({
            "m8_capital_weight": allocation,
            "cash_capital_weight": 1.0 - allocation,
            "source_native_scenario": "1x",
            "fixed_exposure_overlays": [
                {"stress": name, "daily_audit": summarize_daily_returns(values)}
                for name, values in comparison.cost_stress_net
            ],
            "caveat": "These scale 1x execution drag at fixed exposure; they are not equivalent to native 2x/3x re-execution.",
        })
    report = {
        "status": "DAILY_SLEEVE_BRIDGE_COMPLETE",
        "strategy_id": identity.strategy_id,
        "authorities": dict(sorted(authorities.items())),
        "m8_identity": _identity_dict(identity),
        "cash_identity": _identity_dict(cash_identity),
        "trial_disclosure": asdict(trial_disclosure),
        "selection_adjustment": "UNAVAILABLE_NOT_COMPUTED",
        "selection_history_complete_as_disclosed": trial_disclosure.selection_adjustment_allowed,
        "sample": {
            "calendar": identity.calendar_id,
            "start_inclusive": START.isoformat(),
            "end_exclusive": END_EXCLUSIVE.isoformat(),
            "session_count": len(sessions),
            "periods_per_year": periods_per_year,
            "annualization_unit": "XNAS cash sessions; weekends and holidays are not return periods",
            "warmup": "pre-2020 native marks required flat at 100000; excluded from economic sample",
            "denominators": "prior daily NET equity, initial value 100000",
            "valuation_policy": "last actual native equity mark per scheduled UTC date; frozen m8_n8.summarize_n8_scenario policy",
            "native_daily_mark_timestamps": [last_source_mark_by_day[day].isoformat() for day in expected_days],
            "interpolated_marks": False,
        },
        "assumptions_and_limits": {
            "price_gross": "raw source opens and native fill quantities; denominator is prior net equity, not a separately compounded no-cost equity path",
            "execution_drag": "nonnegative adverse native fill slippage versus source open plus actual native commission",
            "carry": "zero because this M8 strategy is required flat each session; a no-overnight model assumption, not observed free financing",
            "cash_baseline": "modeled zero yield and zero fee; not an observed cash rate",
            "market_cost_authority": "UNAVAILABLE; native fills apply assumed costs, not verified executable market costs",
            "intraday_barrier_claim": "UNAVAILABLE; daily marks do not provide raw intraday barrier evidence",
            "diversification_claim": "M8-versus-cash paired resampling is not multi-strategy diversification evidence; cost scenarios are one strategy",
        },
        "resampling": {
            "seed": RESAMPLE_SEED,
            "block_size": RESAMPLE_BLOCK_SIZE,
            "samples": RESAMPLE_SAMPLES,
            "same_indices_for_all_m8_cash_and_cost_cases": True,
            "shared_index_sha256": next(iter(bootstrap_hashes)),
        },
        "native_scenarios": native_scenario_reports,
        "fixed_exposure_cost_stress": cost_stresses,
    }
    json.dumps(report, allow_nan=False)
    result: dict[str, Any] = {"report": report}
    if include_sleeves:
        result["sleeves"] = (cash_sleeve, *(portfolio_sleeves[name] for name in ("1x", "2x", "3x")))
    return result
