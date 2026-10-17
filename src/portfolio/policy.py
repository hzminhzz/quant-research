"""Pure evaluation barrier and proposed-risk policy. Never routes orders.

Values are in account currency. A caller must source audited current marks and
midnight balance; this function does not reconstruct missing intraday marks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from zoneinfo import ZoneInfo

PRAGUE = ZoneInfo("Europe/Prague")


def barrier_leverage_scale(*, equity: float, initial_balance: float,
                           midnight_balance: float | None, marks_available: bool,
                           daily_loss_fraction: float = 0.05,
                           overall_loss_fraction: float = 0.10,
                           target_fraction: float = 0.10) -> float:
    """Conservatively taper target leverage near prop barriers; never guarantees no gap breach."""
    values = (equity, initial_balance, daily_loss_fraction, overall_loss_fraction, target_fraction)
    if not marks_available or midnight_balance is None or any(not isfinite(x) for x in values + (midnight_balance,)):
        return 0.0
    if initial_balance <= 0 or midnight_balance <= 0:
        return 0.0
    daily_floor = midnight_balance - daily_loss_fraction * initial_balance
    overall_floor = initial_balance * (1 - overall_loss_fraction)
    target = initial_balance * (1 + target_fraction)
    tolerance = 1e-12 * initial_balance
    if equity <= max(daily_floor, overall_floor) + tolerance or equity >= target - tolerance:
        return 0.0
    cushion = min(equity - daily_floor, equity - overall_floor, target - equity)
    return max(0.0, min(1.0, cushion / (0.02 * initial_balance)))


@dataclass(frozen=True)
class RiskSnapshot:
    now: datetime
    mark_time: datetime
    midnight_at: datetime
    initial_balance: float
    midnight_balance: float
    balance: float
    floating_pnl: float
    existing_stop_risk: float
    existing_stress_loss: float
    gap_reserve: float
    slippage_reserve: float
    financing_reserve: float
    next_midnight_balance: float
    gap_detected: bool = False


@dataclass(frozen=True)
class RiskLimits:
    max_mark_age: timedelta = timedelta(minutes=2)
    daily_loss_fraction: float = 0.05
    overall_loss_fraction: float = 0.10
    target_fraction: float = 0.10
    kelly_fraction: float = 0.5
    max_trade_risk_fraction: float = 0.01
    taper_width_fraction: float = 0.02
    target_taper_fraction: float = 0.02
    max_probability_age: timedelta = timedelta(days=30)


@dataclass(frozen=True)
class RiskDecision:
    status: str
    reason: str
    equity: float
    daily_floor: float
    overall_floor: float
    target: float
    proposed_risk_cash: float
    max_notional: float


def evaluate_risk(
    snapshot: RiskSnapshot, *, win_probability: float,
    reward_to_risk: float, probability_at: datetime,
    probability_sha256: str, calibrated: bool, loss_per_unit: float,
    notional_per_unit: float, max_notional: float,
    limits: RiskLimits | None = None,
) -> RiskDecision:
    """Block new risk at or beyond either floor or target.

    Daily floor equals Prague midnight balance minus 5% of initial balance.
    Existing stop risk is reserved against both floors before new sizing.
    Barrier proximity smoothly tapers risk to zero over the stated width.
    Breach is a policy state, not an instruction to liquidate positions.
    """
    if limits is None:
        limits = RiskLimits()
    times = (snapshot.now, snapshot.mark_time, snapshot.midnight_at, probability_at)
    if any(t.tzinfo is None or t.utcoffset() is None for t in times):
        raise ValueError("all timestamps must be timezone-aware")
    numbers = (
        snapshot.initial_balance, snapshot.midnight_balance, snapshot.balance,
        snapshot.floating_pnl, snapshot.existing_stop_risk, snapshot.existing_stress_loss,
        snapshot.gap_reserve, snapshot.slippage_reserve, snapshot.financing_reserve,
        snapshot.next_midnight_balance, loss_per_unit, notional_per_unit,
        max_notional, win_probability,
        reward_to_risk, limits.daily_loss_fraction, limits.overall_loss_fraction,
        limits.target_fraction, limits.kelly_fraction, limits.max_trade_risk_fraction,
        limits.taper_width_fraction, limits.target_taper_fraction,
    )
    if any(not isfinite(x) for x in numbers):
        raise ValueError("risk inputs must be finite")
    if (snapshot.initial_balance <= 0 or snapshot.midnight_balance <= 0
        or min(snapshot.existing_stop_risk, snapshot.existing_stress_loss,
               snapshot.gap_reserve, snapshot.slippage_reserve, snapshot.financing_reserve) < 0
        or snapshot.next_midnight_balance <= 0
        or min(loss_per_unit, notional_per_unit, max_notional) <= 0
        or not 0 <= win_probability <= 1
        or reward_to_risk <= 0 or limits.max_mark_age <= timedelta(0)
        or not 0 < limits.daily_loss_fraction < 1
        or not 0 < limits.overall_loss_fraction < 1
        or limits.target_fraction <= 0 or not 0 < limits.kelly_fraction <= 0.5
        or not 0 < limits.max_trade_risk_fraction < 1
        or not 0 < limits.taper_width_fraction < 1
        or not 0 < limits.target_taper_fraction < 1
        or limits.max_probability_age <= timedelta(0)):
        raise ValueError("invalid risk bounds")
    now_local = snapshot.now.astimezone(PRAGUE)
    midnight_local = snapshot.midnight_at.astimezone(PRAGUE)
    if (midnight_local.date() != now_local.date() or midnight_local.hour != 0
        or midnight_local.minute != 0 or midnight_local.second != 0
        or midnight_local.microsecond != 0):
        raise ValueError("midnight balance must be captured at current Prague midnight")
    equity = snapshot.balance + snapshot.floating_pnl
    daily_floor = snapshot.midnight_balance - limits.daily_loss_fraction * snapshot.initial_balance
    overall_floor = snapshot.initial_balance * (1 - limits.overall_loss_fraction)
    target = snapshot.initial_balance + snapshot.initial_balance * limits.target_fraction

    def decision(status: str, reason: str, risk: float = 0.0, notional: float = 0.0) -> RiskDecision:
        return RiskDecision(status, reason, equity, daily_floor, overall_floor,
                            target, risk, notional)

    if equity <= daily_floor:
        return decision("BLOCK", "daily_floor")
    if equity <= overall_floor:
        return decision("BLOCK", "overall_floor")
    if equity >= target:
        return decision("BLOCK", "TARGET_PROXIMITY_UNREALIZED" if snapshot.balance < target
                        else "TARGET_BALANCE_REVIEW_REQUIRED")
    if (snapshot.gap_detected or snapshot.mark_time > snapshot.now
        or snapshot.now - snapshot.mark_time > limits.max_mark_age):
        return decision("BLOCK", "stale_or_gap")
    if (not calibrated or len(probability_sha256) != 64
        or any(c not in "0123456789abcdef" for c in probability_sha256)
        or probability_at > snapshot.now
        or snapshot.now - probability_at > limits.max_probability_age):
        return decision("BLOCK", "uncalibrated_or_stale_probability")
    next_floor = snapshot.next_midnight_balance - limits.daily_loss_fraction * snapshot.initial_balance
    reserved = (max(snapshot.existing_stop_risk, snapshot.existing_stress_loss)
                + snapshot.gap_reserve + snapshot.slippage_reserve + snapshot.financing_reserve)
    remaining = min(equity - daily_floor, equity - next_floor,
                    equity - overall_floor) - reserved
    if remaining <= 0:
        return decision("BLOCK", "existing_risk_exhausts_cushion")
    full_kelly = (win_probability * (reward_to_risk + 1) - 1) / reward_to_risk
    if full_kelly <= 0:
        return decision("BLOCK", "no_positive_edge")
    width = limits.taper_width_fraction * snapshot.initial_balance
    target_width = limits.target_taper_fraction * snapshot.initial_balance
    taper = min(1.0, remaining / width, (target - equity) / target_width)
    risk = min(
        equity * full_kelly * limits.kelly_fraction,
        equity * limits.max_trade_risk_fraction,
        remaining,
        max_notional / notional_per_unit * loss_per_unit,
    ) * taper
    if risk <= 0 or not isfinite(risk):
        return decision("BLOCK", "no_available_risk")
    # Unit risk is monetary loss including declared stop assumptions. Never
    # round quantities upward. Broker minimum lot checks remain out of scope.
    notional = min(max_notional, risk / loss_per_unit * notional_per_unit)
    risk = min(risk, notional / notional_per_unit * loss_per_unit)
    return decision("ALLOW_RESEARCH_ONLY", "bounded", risk, notional)
