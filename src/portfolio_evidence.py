"""Immutable daily sleeve evidence and explicit fixed-weight return overlays."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import Enum
from math import isfinite
from numbers import Real

import numpy as np


class ReturnUnit(str, Enum):
    CAPITAL = "capital_return"
    RISK = "risk_R"


class BudgetUnit(str, Enum):
    CAPITAL = "capital_fraction"
    RISK = "risk_fraction"


class MarkCadence(str, Enum):
    DAILY = "daily"
    INTRADAY = "intraday"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SleeveIdentity:
    strategy_id: str
    strategy_version: str
    spec_hash: str
    code_hash: str
    data_snapshot_id: str
    cost_model_id: str
    calendar_id: str
    selection_family_id: str

    def __post_init__(self) -> None:
        if any(not value.strip() for value in self.__dict__.values()):
            raise ValueError("all sleeve identity fields are required")


@dataclass(frozen=True)
class SleeveEvidence:
    identity: SleeveIdentity
    unit: ReturnUnit
    dates: tuple[str, ...]
    gross: tuple[float, ...]
    execution_drag: tuple[float, ...]
    carry: tuple[float, ...]
    net: tuple[float, ...]
    return_basis_id: str
    denominator_id: str
    period_capital_denominator: float | tuple[float, ...]
    risk_fraction: float | None
    costs_qualified: bool
    carry_qualified: bool
    mark_cadence: MarkCadence
    marks_qualified: bool

    def __post_init__(self) -> None:
        for name in ("dates", "gross", "execution_drag", "carry", "net"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if isinstance(self.period_capital_denominator, Real) and not isinstance(self.period_capital_denominator, bool):
            denominators = (float(self.period_capital_denominator),) * len(self.dates)
        else:
            denominators = tuple(self.period_capital_denominator)
        object.__setattr__(self, "period_capital_denominator", denominators)
        if not isinstance(self.unit, ReturnUnit) or not isinstance(self.mark_cadence, MarkCadence):
            raise TypeError("unit and mark_cadence must use their declared enums")
        if any(type(value) is not bool for value in (self.costs_qualified, self.carry_qualified, self.marks_qualified)):
            raise TypeError("qualification fields must be bool values")
        if not self.return_basis_id.strip() or not self.denominator_id.strip():
            raise ValueError("return basis and denominator identities are required")
        if len(self.period_capital_denominator) != len(self.dates) or any(
            not isfinite(value) or value <= 0 for value in self.period_capital_denominator
        ):
            raise ValueError("period capital denominator must be finite and positive")
        if self.risk_fraction is not None and (not isfinite(self.risk_fraction) or self.risk_fraction <= 0):
            raise ValueError("risk_fraction must be finite and positive when declared")
        try:
            for value in self.dates:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError("dates must use canonical YYYY-MM-DD form")
        except (TypeError, ValueError) as exc:
            raise ValueError("dates must be ISO calendar dates") from exc
        if not self.dates or len(set(self.dates)) != len(self.dates) or tuple(sorted(self.dates)) != self.dates:
            raise ValueError("dates must be nonempty, unique, and sorted")
        series = (self.gross, self.execution_drag, self.carry, self.net)
        if any(len(values) != len(self.dates) for values in series):
            raise ValueError("gross, drag, carry, and net must align exactly to dates")
        if any(not isfinite(value) for values in series for value in values):
            raise ValueError("returns and cost components must be finite; missing values cannot be filled")
        if any(value < 0 for value in self.execution_drag):
            raise ValueError("execution drag must be nonnegative")
        if any(abs(n - (g - d + c)) > 1e-10 for g, d, c, n in zip(*series)):
            raise ValueError("net must equal gross - execution_drag + carry on the declared denominator")

    def capital_returns(self, values: Sequence[float]) -> tuple[float, ...]:
        if self.unit is ReturnUnit.CAPITAL:
            return tuple(values)
        if self.risk_fraction is None:
            raise ValueError("R-to-capital conversion requires an explicit risk_fraction")
        return tuple(value * self.risk_fraction for value in values)

    def risk_returns(self, values: Sequence[float]) -> tuple[float, ...]:
        if self.unit is ReturnUnit.RISK:
            return tuple(values)
        if self.risk_fraction is None:
            raise ValueError("capital-to-R conversion requires an explicit risk_fraction")
        return tuple(value / self.risk_fraction for value in values)


@dataclass(frozen=True)
class TrialDisclosure:
    known_trial_ids: tuple[str, ...]
    outcomes: tuple[str | None, ...]
    unknown_count: int | None
    missing_outcome_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("known_trial_ids", "outcomes", "missing_outcome_ids"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if not self.known_trial_ids or len(set(self.known_trial_ids)) != len(self.known_trial_ids) or any(not x.strip() for x in self.known_trial_ids):
            raise ValueError("known trial IDs must be distinct and nonempty")
        if len(self.outcomes) != len(self.known_trial_ids):
            raise ValueError("retain one outcome slot for every known attempt")
        for outcome in self.outcomes:
            if outcome is not None and not outcome.strip():
                raise ValueError("blank trial outcomes cannot count as complete")
        if self.unknown_count is not None and self.unknown_count < 0:
            raise ValueError("unknown_count must be nonnegative or None")
        if len(set(self.missing_outcome_ids)) != len(self.missing_outcome_ids):
            raise ValueError("missing outcome IDs must be distinct")
        if not set(self.missing_outcome_ids) <= set(self.known_trial_ids):
            raise ValueError("missing outcomes must refer to known trials")
        none_ids = {key for key, outcome in zip(self.known_trial_ids, self.outcomes) if outcome is None}
        if none_ids != set(self.missing_outcome_ids):
            raise ValueError("missing outcome IDs must identify exactly the unknown known-trial outcomes")

    @property
    def selection_adjustment_allowed(self) -> bool:
        return self.unknown_count == 0 and not self.missing_outcome_ids


@dataclass(frozen=True)
class RiskBudgetPlan:
    baseline_weights: tuple[tuple[str, float], ...]
    candidate_weights: tuple[tuple[str, float], ...]
    budget_unit: BudgetUnit
    total_budget: float
    periods_per_year: int
    trial_disclosure: TrialDisclosure

    def __post_init__(self) -> None:
        for name in ("baseline_weights", "candidate_weights"):
            object.__setattr__(self, name, tuple(tuple(item) for item in getattr(self, name)))
        if not isinstance(self.budget_unit, BudgetUnit):
            raise TypeError("budget_unit must be declared")
        if not isfinite(self.total_budget) or self.total_budget <= 0:
            raise ValueError("total_budget must be finite and positive")
        if not isinstance(self.periods_per_year, int) or self.periods_per_year <= 0:
            raise ValueError("periods_per_year must be an explicit positive integer")
        if self.budget_unit is BudgetUnit.CAPITAL and self.total_budget > 1:
            raise ValueError("capital allocation budget cannot exceed 100%")
        for weights in (self.baseline_weights, self.candidate_weights):
            ids = [key for key, _ in weights]
            if len(ids) != len(set(ids)) or any(not key for key in ids):
                raise ValueError("plan sleeve identities must be distinct and nonempty")
            if any(not isfinite(weight) or weight < 0 for _, weight in weights):
                raise ValueError("weights must be finite and nonnegative")
            if sum(weight for _, weight in weights) > self.total_budget + 1e-12:
                raise ValueError("weights exceed frozen budget")


@dataclass(frozen=True)
class PairwiseCoLoss:
    sleeve_ids: tuple[str, str]
    simultaneous_loss_days: int
    joint_loss_severity: float


@dataclass(frozen=True)
class SleeveLossSummary:
    sleeve_id: str
    sleeve_down_days: int
    sleeve_loss_severity: float


@dataclass(frozen=True)
class PortfolioComparison:
    dates: tuple[str, ...]
    sleeve_evidence: tuple[SleeveEvidence, ...]
    plan: RiskBudgetPlan
    budget_unit: BudgetUnit
    baseline_gross: tuple[float, ...]
    baseline_net: tuple[float, ...]
    candidate_gross: tuple[float, ...]
    candidate_net: tuple[float, ...]
    summaries: tuple[tuple[str, float], ...]
    native_statistics: tuple[tuple[str, float], ...]
    native_statistics_status: str
    sleeve_loss_summaries: tuple[SleeveLossSummary, ...]
    pairwise_co_losses: tuple[PairwiseCoLoss, ...]
    cost_stress_net: tuple[tuple[str, tuple[float, ...]], ...]
    evidence_status: tuple[str, ...]
    selection_adjustment_allowed: bool
    barrier_claim_allowed: bool
    unsupported_claim_reasons: tuple[str, ...]
    trial_disclosure: TrialDisclosure
    resampled_indices: tuple[tuple[int, ...], ...]
    resampled_candidate_net: tuple[tuple[float, ...], ...]
    resampled_baseline_net: tuple[tuple[float, ...], ...]
    resampling_seed: int
    resampling_block_size: int


def _validate_capital_path(values: Sequence[float]) -> np.ndarray:
    result = np.asarray(values, dtype=float)
    if not np.all(np.isfinite(result)) or np.any(result <= -1):
        raise ValueError("capital returns must be finite and greater than -100%")
    wealth = np.cumprod(1.0 + result)
    if not np.all(np.isfinite(wealth)) or np.any(wealth <= 0):
        raise ValueError("capital return path must preserve positive finite equity")
    return result


def _finite_returns(values: Sequence[float]) -> np.ndarray:
    result = np.asarray(values, dtype=float)
    if not np.all(np.isfinite(result)):
        raise ValueError("return contributions must be finite")
    return result


def _summary(values: Sequence[float]) -> dict[str, float]:
    returns = _validate_capital_path(values)
    wealth = np.concatenate(([1.0], np.cumprod(1.0 + returns)))
    peaks = np.maximum.accumulate(wealth)
    tail = returns[returns <= np.quantile(returns, 0.05)]
    loss_days = returns < 0
    return {
        "total_return": float(wealth[-1] - 1.0),
        "audit_max_drawdown_initial_wealth": float(np.min(wealth / peaks - 1.0)),
        "empirical_5pct_tail_loss": float(-np.mean(tail)),
        "overlay_down_days": float(np.sum(loss_days)),
        "overlay_loss_severity": float(-np.sum(returns[loss_days])),
    }


def summarize_daily_returns(values: Sequence[float]) -> dict[str, float]:
    """Audit a net daily return path from initial wealth 1.0."""
    return _summary(values)


def _native_statistics(values: Sequence[float], periods_per_year: int) -> tuple[tuple[tuple[str, float], ...], str]:
    try:
        from ml4t.diagnostic.api import PortfolioAnalysis

        result = PortfolioAnalysis(
            returns=np.asarray(values, dtype=float), periods_per_year=periods_per_year
        ).compute_summary_stats()
        fields = ("total_return", "annual_return", "annual_volatility", "sharpe_ratio", "sortino_ratio", "max_drawdown", "var_95", "cvar_95")
        return tuple((key, float(getattr(result, key))) for key in fields), "available: ml4t.diagnostic.api.PortfolioAnalysis"
    except (ImportError, RuntimeError, ValueError, ZeroDivisionError) as exc:
        return (), f"unavailable: {type(exc).__name__}: {exc}"


def compare_sleeves(
    sleeves: Sequence[SleeveEvidence],
    plan: RiskBudgetPlan,
    *,
    samples: int = 0,
    block_size: int = 1,
    seed: int = 0,
) -> PortfolioComparison:
    """Compare frozen fixed-weight daily return overlays with joint block samples."""
    sleeves = tuple(sleeves)
    by_id = {s.identity.strategy_id: s for s in sleeves}
    if len(by_id) != len(sleeves):
        raise ValueError("sleeve strategy identities must be distinct")
    all_weight_ids = {key for key, _ in plan.baseline_weights + plan.candidate_weights}
    if all_weight_ids - set(by_id):
        raise ValueError("plan references missing sleeve evidence")
    if not sleeves:
        raise ValueError("at least one sleeve is required")
    dates = sleeves[0].dates
    if any(s.dates != dates for s in sleeves):
        raise ValueError("sleeve dates must align exactly; intersection/drop is forbidden")
    if not isinstance(samples, int) or samples < 0 or not isinstance(block_size, int) or not 1 <= block_size <= len(dates):
        raise ValueError("resampling block_size must be within [1, number of dates]")
    if not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a nonnegative integer")

    def capital_component(sleeve: SleeveEvidence, values: Sequence[float]) -> np.ndarray:
        result = np.asarray(sleeve.capital_returns(values), dtype=float)
        if not np.all(np.isfinite(result)):
            raise ValueError("converted capital returns and components must be finite")
        return result

    arrays = {
        s.identity.strategy_id: {
            "gross": _finite_returns(capital_component(s, s.gross)),
            "drag": capital_component(s, s.execution_drag),
            "carry": capital_component(s, s.carry),
            "net": _validate_capital_path(capital_component(s, s.net)),
        }
        for s in sleeves
    }
    candidate_weights, baseline_weights = dict(plan.candidate_weights), dict(plan.baseline_weights)
    for weights in (baseline_weights, candidate_weights):
        for key, weight in weights.items():
            if weight and plan.budget_unit is BudgetUnit.RISK and by_id[key].risk_fraction is None:
                raise ValueError(f"risk budget conversion for {key} requires explicit risk_fraction")

    def overlay(weights: dict[str, float], column: str, stress: float = 1.0) -> tuple[float, ...]:
        total = np.zeros(len(dates), dtype=float)
        for key, weight in weights.items():
            if weight == 0:
                continue
            sleeve, values = by_id[key], arrays[key]
            if column == "gross":
                source = values["gross"]
            else:
                source = values["gross"] - stress * values["drag"] + values["carry"]
            contribution = weight * source if plan.budget_unit is BudgetUnit.CAPITAL else weight * source / sleeve.risk_fraction
            total += contribution
        return tuple(map(float, _finite_returns(total) if column == "gross" else _validate_capital_path(total)))

    bg, bn = overlay(baseline_weights, "gross"), overlay(baseline_weights, "net")
    cg, cn = overlay(candidate_weights, "gross"), overlay(candidate_weights, "net")
    stresses = tuple((f"{multiple}x_execution_drag_fixed_exposure", overlay(candidate_weights, "net", multiple)) for multiple in (1, 2, 3))
    for _, path in stresses:
        _validate_capital_path(path)
    loss_summaries = []
    for sleeve in sleeves:
        returns = arrays[sleeve.identity.strategy_id]["net"]
        losses = returns < 0
        loss_summaries.append(SleeveLossSummary(
            sleeve.identity.strategy_id,
            int(np.sum(losses)),
            float(-np.sum(returns[losses])),
        ))
    co_losses = []
    for i, left in enumerate(sleeves):
        left_returns = arrays[left.identity.strategy_id]["net"]
        for right in sleeves[i + 1:]:
            right_returns = arrays[right.identity.strategy_id]["net"]
            joint = (left_returns < 0) & (right_returns < 0)
            co_losses.append(PairwiseCoLoss(
                (left.identity.strategy_id, right.identity.strategy_id),
                int(np.sum(joint)),
                float(-np.sum(left_returns[joint] + right_returns[joint])),
            ))
    summaries = _summary(cn)
    summaries.update({f"baseline_{key}": value for key, value in _summary(bn).items()})
    native, native_status = _native_statistics(cn, plan.periods_per_year)

    rng = np.random.default_rng(seed)
    sampled_indices, candidate_draws, baseline_draws = [], [], []
    if samples:
        starts = np.arange(0, len(dates) - block_size + 1)
        for _ in range(samples):
            indices: list[int] = []
            while len(indices) < len(dates):
                start = int(rng.choice(starts))
                indices.extend(range(start, start + block_size))
            idx = tuple(indices[:len(dates)])
            sampled_indices.append(idx)
            selected = {key: {col: values[col][list(idx)] for col in values} for key, values in arrays.items()}
            def sampled_overlay(weights: dict[str, float], net: bool, selected=selected) -> tuple[float, ...]:
                result = np.zeros(len(dates))
                for key, weight in weights.items():
                    if weight == 0:
                        continue
                    sleeve = by_id[key]
                    item = selected[key]
                    values = item["gross"] - item["drag"] + item["carry"] if net else item["gross"]
                    result += weight * values if plan.budget_unit is BudgetUnit.CAPITAL else weight * values / sleeve.risk_fraction
                return tuple(map(float, _validate_capital_path(result)))
            candidate_draws.append(sampled_overlay(candidate_weights, True))
            baseline_draws.append(sampled_overlay(baseline_weights, True))

    reasons = ("daily_return_overlay_has_no_raw_intraday_path", "no_combined_native_account_simulation")
    evidence_status = []
    evidence_status.append("intraday_path_evidence_missing_for_daily_overlay")
    if any(not s.costs_qualified for s in sleeves):
        evidence_status.append("execution_costs_unqualified")
    if any(not s.carry_qualified for s in sleeves):
        evidence_status.append("carry_unqualified")
    if not plan.trial_disclosure.selection_adjustment_allowed:
        evidence_status.append("selection_history_incomplete_or_unknown")
    if len(evidence_status) == 1:
        evidence_status.append("daily_inputs_qualified_within_declared_scope")
    return PortfolioComparison(
        dates, sleeves, plan, plan.budget_unit, bg, bn, cg, cn, tuple(sorted(summaries.items())),
        native, native_status, tuple(loss_summaries), tuple(co_losses), stresses, tuple(evidence_status),
        plan.trial_disclosure.selection_adjustment_allowed, False, reasons, plan.trial_disclosure,
        tuple(sampled_indices), tuple(candidate_draws), tuple(baseline_draws), seed, block_size,
    )
