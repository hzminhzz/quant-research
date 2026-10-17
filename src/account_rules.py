"""ATS-5: pure, version-bound account-rule replay.

No broker clients, orders, network, mutable registry, wall-clock reads or financial
simulation. Inputs are complete explicit ledger events and explicit account-term
assignments. An observed PASS is not proof of continuous intraday survival unless
the supplied event/mark coverage has been independently certified.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Any, Literal
from zoneinfo import ZoneInfo

D = Decimal
ZERO = D("0")


class RuleError(ValueError):
    """Invalid evidence, ambiguous clock, unauthorized transition, or replay order."""


def money(value: Decimal | str | int) -> Decimal:
    if isinstance(value, (float, bool)):
        raise RuleError("Money and rule ratios must not be binary floating-point")
    try:
        item = D(value)
    except Exception as exc:
        raise RuleError(f"Invalid decimal: {value!r}") from exc
    if not item.is_finite():
        raise RuleError("Nonfinite monetary amount")
    return item


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RuleError("UTC-offset-aware timestamp required")
    return value.astimezone(UTC)


def timestamp(value: str) -> datetime:
    return aware(datetime.fromisoformat(value))


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return aware(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value):
        return {f.name: _plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in sorted(value.items())}
    if isinstance(value, (set, frozenset)):
        return sorted(_plain(v) for v in value)
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    return value


def digest(value: Any) -> str:
    return sha256(json.dumps(_plain(value), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class RuleSource:
    source_id: str
    url: str
    captured_at: datetime
    evidence_type: Literal["published", "account_agreement", "synthetic"]
    published_at: datetime | None = None
    stated_effective_at: datetime | None = None
    raw_page_sha256: str | None = None
    extraction_sha256: str | None = None

    def __post_init__(self) -> None:
        aware(self.captured_at)
        if self.published_at is not None:
            aware(self.published_at)
        if self.stated_effective_at is not None:
            aware(self.stated_effective_at)
        if not self.source_id or not self.url:
            raise RuleError("RuleSource requires stable identity and locator")


@dataclass(frozen=True)
class PhaseRule:
    name: str
    role: Literal["evaluation", "funded"]
    target_fraction: Decimal | None
    min_open_days: int | None
    next_phase: str | None = None
    payout_fraction: Decimal | None = None
    payout_wait_calendar_days: int | None = None

    def __post_init__(self) -> None:
        for field_name in ("target_fraction", "payout_fraction"):
            val = getattr(self, field_name)
            if val is not None and not ZERO <= money(val) <= D("1"):
                raise RuleError(f"{field_name} must be between 0 and 1")
        for field_name in ("min_open_days", "payout_wait_calendar_days"):
            val = getattr(self, field_name)
            if val is not None and val < 0:
                raise RuleError(f"{field_name} cannot be negative")
        if self.role == "funded" and self.next_phase is not None:
            raise RuleError("Funded phases cannot auto-advance")


@dataclass(frozen=True)
class RuleVersion:
    version_id: str
    program_id: str
    source: RuleSource
    phases: tuple[PhaseRule, ...]
    timezone_name: str
    reset_hour: int
    daily_loss_fraction: Decimal | None
    max_loss_fraction: Decimal | None
    max_loss_mode: Literal["static", "trailing"] = "static"
    trailing_basis: Literal["balance", "equity"] = "balance"
    trailing_update: Literal["event", "reset"] = "event"
    trailing_cap_at_initial: bool = False
    breach_on_touch: bool = False
    mark_max_age_seconds: int = 0
    unknown_rules: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.version_id or not self.program_id or not self.phases:
            raise RuleError("Missing rulebook identity or phases")
        try:
            ZoneInfo(self.timezone_name)
        except Exception as exc:
            raise RuleError(f"Unknown reset timezone {self.timezone_name}") from exc
        if not 0 <= self.reset_hour <= 23 or self.mark_max_age_seconds < 0:
            raise RuleError("Invalid reset hour or mark age")
        for val in (self.daily_loss_fraction, self.max_loss_fraction):
            if val is not None and not ZERO < money(val) < D("1"):
                raise RuleError("Loss fractions must be strictly between zero and one")
        names = [p.name for p in self.phases]
        if len(set(names)) != len(names):
            raise RuleError("Duplicate phase name")
        if any(p.next_phase is not None and p.next_phase not in names for p in self.phases):
            raise RuleError("Unknown next phase")
        if self.trailing_update == "reset" and self.trailing_basis == "equity":
            raise RuleError("Reset-based equity trailing needs an explicit boundary mark protocol")

    def phase(self, name: str) -> PhaseRule:
        for phase in self.phases:
            if phase.name == name:
                return phase
        raise RuleError(f"Unknown phase {name}")


@dataclass(frozen=True)
class TermAssignment:
    at: datetime
    version_id: str
    applicability_reference: str
    grandfathered: bool = False

    def __post_init__(self) -> None:
        aware(self.at)
        if not self.version_id or not self.applicability_reference:
            raise RuleError("Account-specific term assignment requires reference")


@dataclass(frozen=True)
class ObservationCoverage:
    start: datetime
    end: datetime
    events_complete: bool
    marks_complete: bool

    def __post_init__(self) -> None:
        if aware(self.start) >= aware(self.end):
            raise RuleError("Invalid observation interval")


@dataclass(frozen=True)
class AccountBinding:
    account_id: str
    program_id: str
    created_at: datetime
    initial_capital: Decimal
    first_phase: str
    assignments: tuple[TermAssignment, ...]
    coverage: tuple[ObservationCoverage, ...] = ()
    agreement_verified: bool = False

    def __post_init__(self) -> None:
        aware(self.created_at)
        if money(self.initial_capital) <= ZERO or not self.account_id:
            raise RuleError("Invalid account identity or capital")
        if not self.assignments or aware(self.assignments[0].at) != aware(self.created_at):
            raise RuleError("Initial terms must bind at account creation")
        times = [aware(item.at) for item in self.assignments]
        if times != sorted(set(times)):
            raise RuleError("Assignments must have distinct increasing effective instants")
        for left, right in zip(self.coverage, self.coverage[1:]):
            if aware(left.end) > aware(right.start):
                raise RuleError("Overlapping coverage intervals are ambiguous")


EventKind = Literal[
    "mark", "position_opened", "position_closed", "realized_pnl",
    "commission", "swap", "deposit", "withdrawal", "owner_fee_paid",
    "owner_fee_refund_received", "reward_requested", "reward_approved",
    "reward_debited", "reward_received", "phase_advanced", "observation",
]


@dataclass(frozen=True)
class AccountEvent:
    event_id: str
    at: datetime
    sequence: int
    kind: EventKind
    amount: Decimal = ZERO
    reference: str | None = None

    def __post_init__(self) -> None:
        aware(self.at)
        money(self.amount)
        if not self.event_id or self.sequence < 0:
            raise RuleError("Event requires ID and nonnegative event sequence")


@dataclass(frozen=True)
class RewardClaim:
    claim_id: str
    gross_simulated: Decimal
    approved: bool = False
    debited: bool = False
    cash_received: Decimal = ZERO


@dataclass(frozen=True)
class AccountState:
    at: datetime
    terms_index: int
    phase_name: str
    balance: Decimal
    floating_pnl: Decimal | None
    mark_at: datetime | None
    open_positions: int
    day: date
    day_start_balance: Decimal
    high_water: Decimal
    trailing_floor: Decimal | None
    trading_days: tuple[str, ...]
    first_trade_at: datetime | None
    breached_at: datetime | None
    breach_codes: tuple[str, ...]
    evidence_gaps: tuple[str, ...]
    pending_mark_at: datetime | None
    cash_paid: Decimal
    cash_received: Decimal
    reward_cash_received: Decimal
    claims: tuple[RewardClaim, ...]
    last_reset_at: datetime


@dataclass(frozen=True)
class AccountDecision:
    at: datetime
    event_id: str
    kind: str
    account_id: str
    program_id: str
    version_id: str
    source_id: str
    terms_applicability_ref: str
    phase: str
    state: Literal["OBSERVED_CLEAR", "BREACHED", "INCONCLUSIVE"]
    eligible_for_shadow: bool
    phase_eligible: bool
    daily_floor: Decimal | None
    maximum_floor: Decimal | None
    balance: Decimal
    floating_pnl: Decimal | None
    equity: Decimal | None
    minimum_headroom: Decimal | None
    positions_open: int
    opened_trading_days: int
    cash_paid: Decimal
    cash_received: Decimal
    owner_net_cash: Decimal
    hypothetical_payout_due: Decimal
    breach_codes: tuple[str, ...]
    reason_codes: tuple[str, ...]
    uncertainty: tuple[str, ...]
    evidence_gaps: tuple[str, ...]


@dataclass(frozen=True)
class ReplayCursor:
    account_digest: str
    version_digests: tuple[tuple[str, str], ...]
    state: AccountState
    last_event_key: tuple[datetime, int] | None
    seen_event_digests: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ReplayResult:
    decisions: tuple[AccountDecision, ...]
    cursor: ReplayCursor

    @property
    def last(self) -> AccountDecision:
        return self.decisions[-1]


def _local_midnight(day: date, rule: RuleVersion) -> datetime:
    wall = datetime.combine(day, time(hour=rule.reset_hour))
    zone = ZoneInfo(rule.timezone_name)
    candidates = []
    for fold in (0, 1):
        candidate = wall.replace(tzinfo=zone, fold=fold)
        if candidate.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == wall:
            candidates.append(candidate)
    if not candidates or candidates[0].utcoffset() != candidates[-1].utcoffset():
        raise RuleError(f"Nonexistent or ambiguous reset boundary: {wall} {rule.timezone_name}")
    return aware(candidates[0])


def _local_day(at: datetime, rule: RuleVersion) -> date:
    return aware(at).astimezone(ZoneInfo(rule.timezone_name)).date()


def _coverage(at: datetime, account: AccountBinding) -> tuple[bool, bool]:
    matching = [
        c for c in account.coverage if aware(c.start) <= at < aware(c.end)
    ]
    if not matching:
        return False, False
    return matching[0].events_complete, matching[0].marks_complete


def _claimed_amount(state: AccountState) -> Decimal:
    return sum(
        (claim.gross_simulated for claim in state.claims if claim.debited),
        ZERO,
    )


def _evaluate(
    account: AccountBinding,
    state: AccountState,
    rule: RuleVersion,
    event_id: str,
    kind: str,
) -> tuple[AccountState, AccountDecision]:
    now = aware(state.at)
    unknown: list[str] = []
    reasons: list[str] = []
    events_complete, marks_complete = _coverage(now, account)
    if not events_complete:
        unknown.append("EVENT_STREAM_INCOMPLETE")
    if state.open_positions > 0 and not marks_complete:
        unknown.append("MARK_STREAM_INCOMPLETE")
    fresh_mark = (
        state.open_positions == 0
        or (
            state.floating_pnl is not None and state.mark_at is not None
            and timedelta(0) <= now - aware(state.mark_at)
            <= timedelta(seconds=rule.mark_max_age_seconds)
        )
    )
    if not fresh_mark:
        unknown.append("FRESH_EQUITY_MARK_MISSING")
        if state.pending_mark_at is None:
            state = replace(state, pending_mark_at=now)
    else:
        if state.pending_mark_at is not None and now > state.pending_mark_at:
            gaps = state.evidence_gaps + ("UNOBSERVED_MARK_INTERVAL",)
            state = replace(state, evidence_gaps=tuple(dict.fromkeys(gaps)))
        state = replace(state, pending_mark_at=None)
    if not events_complete or (state.open_positions > 0 and not marks_complete):
        gaps = state.evidence_gaps + ("INCOMPLETE_COVERAGE",)
        state = replace(state, evidence_gaps=tuple(dict.fromkeys(gaps)))

    equity = state.balance + (
        state.floating_pnl if state.open_positions > 0 and fresh_mark else ZERO
    ) if fresh_mark else None
    if rule.max_loss_mode == "trailing" and rule.trailing_update == "event":
        basis_value = equity if rule.trailing_basis == "equity" else state.balance
        if basis_value is not None:
            state = replace(state, high_water=max(state.high_water, basis_value))

    daily_floor = (
        state.day_start_balance - money(account.initial_capital) * money(rule.daily_loss_fraction)
        if rule.daily_loss_fraction is not None else None
    )
    maximum_floor: Decimal | None = None
    if rule.max_loss_fraction is not None:
        allowance = money(account.initial_capital) * money(rule.max_loss_fraction)
        if rule.max_loss_mode == "static":
            maximum_floor = money(account.initial_capital) - allowance
        else:
            candidate = state.high_water - allowance
            if rule.trailing_cap_at_initial:
                candidate = min(candidate, money(account.initial_capital))
            maximum_floor = max(candidate, state.trailing_floor or candidate)
            state = replace(state, trailing_floor=maximum_floor)
    if rule.daily_loss_fraction is None or "daily_loss" in rule.unknown_rules:
        unknown.append("DAILY_RULE_UNKNOWN")
    if rule.max_loss_fraction is None or "maximum_loss" in rule.unknown_rules:
        unknown.append("MAXIMUM_RULE_UNKNOWN")

    codes = list(state.breach_codes)
    if equity is not None:
        for label, floor in (("DAILY_LOSS", daily_floor), ("MAXIMUM_LOSS", maximum_floor)):
            if floor is not None and (
                equity <= floor if rule.breach_on_touch else equity < floor
            ) and label not in codes:
                codes.append(label)
    if codes and state.breached_at is None:
        state = replace(state, breached_at=now, breach_codes=tuple(codes))
    elif codes != list(state.breach_codes):
        state = replace(state, breach_codes=tuple(codes))
    if state.breached_at is not None:
        reasons.append("BREACH_LATCHED")
    phase = rule.phase(state.phase_name)
    days = len(state.trading_days)
    qualified = (
        phase.role == "evaluation"
        and phase.target_fraction is not None
        and phase.min_open_days is not None
        and state.balance >= money(account.initial_capital) * (D("1") + money(phase.target_fraction))
        and days >= phase.min_open_days
        and state.open_positions == 0
    )
    if phase.role == "evaluation" and (
        phase.target_fraction is None or phase.min_open_days is None
        or "phase_objectives" in rule.unknown_rules
    ):
        unknown.append("PHASE_REQUIREMENTS_UNKNOWN")
        qualified = False
    if not qualified and phase.role == "evaluation":
        reasons.append("PHASE_NOT_YET_QUALIFIED")
    if not account.agreement_verified or rule.source.evidence_type != "account_agreement":
        reasons.append("ACCOUNT_SPECIFIC_TERMS_NOT_VERIFIED")
    if "trading_permissions" in rule.unknown_rules:
        reasons.append("TRADING_PERMISSIONS_UNKNOWN")
    if state.evidence_gaps:
        unknown.extend(state.evidence_gaps)
    unknown = list(dict.fromkeys(unknown))
    state_label: Literal["OBSERVED_CLEAR", "BREACHED", "INCONCLUSIVE"]
    if state.breached_at is not None:
        state_label = "BREACHED"
    elif unknown:
        state_label = "INCONCLUSIVE"
    else:
        state_label = "OBSERVED_CLEAR"
    can_shadow = (
        state_label == "OBSERVED_CLEAR"
        and account.agreement_verified
        and rule.source.evidence_type == "account_agreement"
        and "trading_permissions" not in rule.unknown_rules
    )
    if state.breached_at:
        can_shadow = False
    available = [x for x in (daily_floor, maximum_floor) if x is not None]
    headroom = min((equity - floor for floor in available), default=None) if equity is not None else None
    hypothetical_due = sum(
        (c.gross_simulated * (phase.payout_fraction or ZERO) - c.cash_received
         for c in state.claims if c.debited),
        ZERO,
    )
    assignment = account.assignments[state.terms_index]
    return state, AccountDecision(
        at=now,
        event_id=event_id,
        kind=kind,
        account_id=account.account_id,
        program_id=account.program_id,
        version_id=rule.version_id,
        source_id=rule.source.source_id,
        terms_applicability_ref=assignment.applicability_reference,
        phase=state.phase_name,
        state=state_label,
        eligible_for_shadow=can_shadow,
        phase_eligible=qualified and state_label == "OBSERVED_CLEAR",
        daily_floor=daily_floor,
        maximum_floor=maximum_floor,
        balance=state.balance,
        floating_pnl=state.floating_pnl if fresh_mark else None,
        equity=equity,
        minimum_headroom=headroom,
        positions_open=state.open_positions,
        opened_trading_days=days,
        cash_paid=state.cash_paid,
        cash_received=state.cash_received,
        owner_net_cash=state.cash_received - state.cash_paid,
        hypothetical_payout_due=hypothetical_due,
        breach_codes=state.breach_codes,
        reason_codes=tuple(dict.fromkeys(reasons)),
        uncertainty=tuple(unknown),
        evidence_gaps=state.evidence_gaps,
    )


def _claim_index(state: AccountState, reference: str | None) -> int:
    if not reference:
        raise RuleError("Reward event must reference claim identity")
    for i, claim in enumerate(state.claims):
        if claim.claim_id == reference:
            return i
    raise RuleError(f"Unknown reward claim {reference}")


def _with_claim(state: AccountState, index: int, claim: RewardClaim) -> AccountState:
    new_claims = list(state.claims)
    new_claims[index] = claim
    return replace(state, claims=tuple(new_claims))


def _apply_event(
    state: AccountState,
    event: AccountEvent,
    account: AccountBinding,
    rule: RuleVersion,
) -> AccountState:
    amount = money(event.amount)
    state = replace(state, at=aware(event.at))
    kind = event.kind
    if kind == "mark":
        if state.open_positions == 0 and amount != ZERO:
            raise RuleError("Nonzero floating PnL without open positions")
        return replace(state, floating_pnl=amount, mark_at=aware(event.at))
    if kind == "position_opened":
        if amount != ZERO:
            raise RuleError("Position opening cannot carry PnL; book separate commissions")
        open_day = _local_day(event.at, rule).isoformat()
        trading_days = tuple(dict.fromkeys((*state.trading_days, open_day)))
        return replace(
            state, open_positions=state.open_positions + 1, floating_pnl=None,
            mark_at=None, trading_days=trading_days,
            first_trade_at=state.first_trade_at or aware(event.at),
        )
    if kind == "position_closed":
        if state.open_positions < 1:
            raise RuleError("Closing an unopened position")
        remaining = state.open_positions - 1
        return replace(
            state, balance=state.balance + amount, open_positions=remaining,
            floating_pnl=ZERO if remaining == 0 else None,
            mark_at=aware(event.at) if remaining == 0 else None,
        )
    if kind in ("realized_pnl", "swap"):
        return replace(state, balance=state.balance + amount,
                       floating_pnl=None if state.open_positions else ZERO,
                       mark_at=None if state.open_positions else aware(event.at))
    if kind == "commission":
        if amount < ZERO:
            raise RuleError("Commission must be nonnegative")
        return replace(state, balance=state.balance - amount,
                       floating_pnl=None if state.open_positions else ZERO,
                       mark_at=None if state.open_positions else aware(event.at))
    if kind in ("deposit", "withdrawal"):
        if amount <= ZERO:
            raise RuleError("Transfers must be positive")
        delta = amount if kind == "deposit" else -amount
        return replace(state, balance=state.balance + delta,
                       floating_pnl=None if state.open_positions else ZERO,
                       mark_at=None if state.open_positions else aware(event.at))
    if kind == "owner_fee_paid":
        if amount <= ZERO:
            raise RuleError("Owner fee must be positive")
        return replace(state, cash_paid=state.cash_paid + amount)
    if kind == "owner_fee_refund_received":
        if amount <= ZERO:
            raise RuleError("Refund receipt must be positive")
        return replace(state, cash_received=state.cash_received + amount)
    if kind == "reward_requested":
        phase = rule.phase(state.phase_name)
        if phase.role != "funded" or "payout_conditions" in rule.unknown_rules:
            raise RuleError("Payout eligibility not established")
        if phase.payout_fraction is None or phase.payout_wait_calendar_days is None:
            raise RuleError("Payout terms are unknown")
        if state.open_positions or state.first_trade_at is None:
            raise RuleError("Payout requires closed positions and known first trade")
        if (aware(event.at).date() - aware(state.first_trade_at).date()).days < phase.payout_wait_calendar_days:
            raise RuleError("Payout waiting period not met")
        if not event.reference or any(c.claim_id == event.reference for c in state.claims):
            raise RuleError("Reward claim requires new unique reference")
        if amount <= ZERO or amount > state.balance - money(account.initial_capital):
            raise RuleError("Requested gross exceeds available simulated profit")
        if any(not c.debited for c in state.claims):
            raise RuleError("Another payout is still pending")
        return replace(state, claims=state.claims + (RewardClaim(event.reference, amount),))
    if kind in ("reward_approved", "reward_debited", "reward_received"):
        idx = _claim_index(state, event.reference)
        claim = state.claims[idx]
        if kind == "reward_approved":
            if claim.approved or amount != ZERO:
                raise RuleError("Reward approval must be new and amount-free")
            return _with_claim(state, idx, replace(claim, approved=True))
        if kind == "reward_debited":
            if not claim.approved or claim.debited or amount != claim.gross_simulated:
                raise RuleError("Debited amount must equal approved gross")
            state = replace(state, balance=state.balance - amount,
                            floating_pnl=ZERO, mark_at=aware(event.at))
            return _with_claim(state, idx, replace(claim, debited=True))
        if not claim.debited or amount <= ZERO:
            raise RuleError("Cash reward receipt requires prior simulated debit")
        if rule.phase(state.phase_name).payout_fraction is None:
            raise RuleError("Unknown reward fraction")
        expected = claim.gross_simulated * money(rule.phase(state.phase_name).payout_fraction)
        if claim.cash_received + amount > expected:
            raise RuleError("Received reward exceeds modeled gross entitlement; reconcile manually")
        state = replace(state, cash_received=state.cash_received + amount,
                        reward_cash_received=state.reward_cash_received + amount)
        return _with_claim(state, idx, replace(claim, cash_received=claim.cash_received + amount))
    if kind == "phase_advanced":
        phase = rule.phase(state.phase_name)
        _, pre = _evaluate(account, state, rule, event.event_id, "pre_phase_gate")
        if not pre.phase_eligible or phase.next_phase is None or not event.reference:
            raise RuleError("Phase advance requires satisfied objective and external confirmation")
        if amount != ZERO:
            raise RuleError("Phase advance amount must be zero")
        return replace(
            state, phase_name=phase.next_phase, balance=money(account.initial_capital),
            floating_pnl=ZERO, mark_at=aware(event.at), open_positions=0,
            day_start_balance=money(account.initial_capital),
            high_water=money(account.initial_capital), trailing_floor=None,
            trading_days=(), first_trade_at=None, pending_mark_at=None,
            claims=(),
        )
    if kind == "observation":
        if amount != ZERO:
            raise RuleError("Observation cannot carry a monetary amount")
        return state
    raise RuleError(f"Unsupported event kind {kind}")


def _validate_inputs(
    account: AccountBinding, versions: Mapping[str, RuleVersion],
) -> tuple[tuple[str, str], ...]:
    if not versions:
        raise RuleError("No account terms supplied")
    ids = []
    for assignment in account.assignments:
        if assignment.version_id not in versions:
            raise RuleError(f"Missing immutable version {assignment.version_id}")
        rule = versions[assignment.version_id]
        if rule.program_id != account.program_id:
            raise RuleError("Cross-program rule binding forbidden")
        if not ids and account.first_phase not in (p.name for p in rule.phases):
            raise RuleError("Initial phase not present in bound rulebook")
        if ids:
            previous = versions[ids[-1]]
            if (previous.timezone_name, previous.reset_hour) != (rule.timezone_name, rule.reset_hour):
                raise RuleError("Reset-clock amendments require a new explicit account epoch")
            if any(p.name == account.first_phase for p in rule.phases) is False:
                raise RuleError("Amended phase schema no longer represents original account")
        ids.append(assignment.version_id)
    return tuple(sorted((version_id, digest(versions[version_id])) for version_id in set(ids)))


def replay_chunk(
    account: AccountBinding,
    versions: Mapping[str, RuleVersion],
    events: tuple[AccountEvent, ...] | list[AccountEvent],
    *,
    cursor: ReplayCursor | None = None,
) -> ReplayResult:
    """Pure, incremental replay. Concatenated chunks equal one-shot decisions.

    Events must be ordered by (UTC timestamp, source sequence). Exact duplicate
    deliveries by event ID are idempotent; conflicting IDs/out-of-order new events
    are errors. Assignments and midnight resets are generated in UTC event time.
    """
    versions_identity = _validate_inputs(account, versions)
    account_identity = digest(account)
    emitted: list[AccountDecision] = []
    if cursor is None:
        rule = versions[account.assignments[0].version_id]
        opening = aware(account.created_at)
        capital = money(account.initial_capital)
        first_day = _local_day(opening, rule)
        state = AccountState(
            at=opening, terms_index=0, phase_name=account.first_phase,
            balance=capital, floating_pnl=ZERO, mark_at=opening, open_positions=0,
            day=first_day, day_start_balance=capital, high_water=capital,
            trailing_floor=None, trading_days=(), first_trade_at=None,
            breached_at=None, breach_codes=(), evidence_gaps=(),
            pending_mark_at=None, cash_paid=ZERO, cash_received=ZERO,
            reward_cash_received=ZERO, claims=(),
            last_reset_at=_local_midnight(first_day, rule),
        )
        state, snap = _evaluate(account, state, rule, "account_open", "account_open")
        emitted.append(snap)
        last_key = None
        seen: dict[str, str] = {}
    else:
        if cursor.account_digest != account_identity or cursor.version_digests != versions_identity:
            raise RuleError("Checkpoint input identity changed; replay from immutable start")
        state, last_key = cursor.state, cursor.last_event_key
        seen = dict(cursor.seen_event_digests)

    for event in events:
        at = aware(event.at)
        fingerprint = digest(event)
        if event.event_id in seen:
            if seen[event.event_id] != fingerprint:
                raise RuleError(f"Conflicting event identity: {event.event_id}")
            continue
        key = (at, event.sequence)
        if at < aware(account.created_at) or (last_key is not None and key <= last_key):
            raise RuleError(f"Out-of-order event {event.event_id}; never silently sort account evidence")

        # Advance virtual boundaries before the incoming event. At a coincident
        # boundary, term assignment and reset are evaluated before input sequence.
        while True:
            rule = versions[account.assignments[state.terms_index].version_id]
            next_assignment = (
                aware(account.assignments[state.terms_index + 1].at)
                if state.terms_index + 1 < len(account.assignments) else None
            )
            next_day = _local_day(state.last_reset_at, rule) + timedelta(days=1)
            next_reset = _local_midnight(next_day, rule)
            candidates = [
                (when, priority, kind)
                for when, priority, kind in (
                    (next_assignment, 0, "terms_amended"),
                    (next_reset, 1, "daily_reset"),
                ) if when is not None and when <= at
            ]
            if not candidates:
                break
            boundary, _, boundary_kind = min(candidates)
            if boundary_kind == "terms_amended":
                state = replace(state, at=boundary, terms_index=state.terms_index + 1,
                                trailing_floor=None)
                rule = versions[account.assignments[state.terms_index].version_id]
                state, snap = _evaluate(
                    account, state, rule, f"terms:{rule.version_id}:{boundary.isoformat()}",
                    "terms_amended",
                )
            else:
                top = state.high_water
                if rule.max_loss_mode == "trailing" and rule.trailing_update == "reset":
                    top = max(top, state.balance)
                state = replace(
                    state, at=boundary, last_reset_at=boundary,
                    day=_local_day(boundary, rule), day_start_balance=state.balance,
                    high_water=top,
                )
                state, snap = _evaluate(
                    account, state, rule, f"reset:{boundary.isoformat()}",
                    "daily_reset",
                )
            emitted.append(snap)

        rule = versions[account.assignments[state.terms_index].version_id]
        if state.pending_mark_at is not None and at > state.pending_mark_at:
            state = replace(
                state, evidence_gaps=tuple(dict.fromkeys(
                    state.evidence_gaps + ("UNOBSERVED_MARK_INTERVAL",)
                )),
            )
        state = _apply_event(state, event, account, rule)
        state, snap = _evaluate(account, state, rule, event.event_id, event.kind)
        emitted.append(snap)
        seen[event.event_id] = fingerprint
        last_key = key

    checkpoint = ReplayCursor(
        account_digest=account_identity, version_digests=versions_identity,
        state=state, last_event_key=last_key,
        seen_event_digests=tuple(sorted(seen.items())),
    )
    return ReplayResult(decisions=tuple(emitted), cursor=checkpoint)


def replay(
    account: AccountBinding,
    versions: Mapping[str, RuleVersion],
    events: tuple[AccountEvent, ...] | list[AccountEvent],
) -> ReplayResult:
    return replay_chunk(account, versions, events)


@dataclass(frozen=True)
class RuleChangeImpact:
    changed_fields: tuple[str, ...]
    impacted_decisions: tuple[str, ...]
    affected_accounts_from: tuple[tuple[str, datetime], ...]


def semantic_diff(
    old: RuleVersion, new: RuleVersion,
    accounts: tuple[AccountBinding, ...] = (),
) -> RuleChangeImpact:
    """Semantic fields, not publication metadata, decide what to recompute.

    An account is invalidated only where an explicit assignment moves it from
    the old version to the new one. Previously emitted account states remain
    frozen under the old rule identity.
    """
    if old.program_id != new.program_id:
        raise RuleError("Semantic diff across programs is invalid")
    groups = {
        "clock": ("timezone_name", "reset_hour"),
        "risk": (
            "daily_loss_fraction", "max_loss_fraction", "max_loss_mode",
            "trailing_basis", "trailing_update", "trailing_cap_at_initial",
            "breach_on_touch", "mark_max_age_seconds",
        ),
        "phase": ("phases",),
        "uncertainty": ("unknown_rules",),
    }
    affected = {
        "clock": {"intraday_replay", "phase_qualification", "payout_eligibility", "shadow_eligibility"},
        "risk": {"intraday_replay", "shadow_eligibility"},
        "phase": {"phase_qualification", "payout_eligibility"},
        "uncertainty": {"intraday_replay", "phase_qualification", "payout_eligibility", "shadow_eligibility"},
    }
    changed = []
    decisions: set[str] = set()
    for group, names in groups.items():
        for name in names:
            if getattr(old, name) != getattr(new, name):
                changed.append(name)
                if name == "phases":
                    old_map = {p.name: p for p in old.phases}
                    new_map = {p.name: p for p in new.phases}
                    for phase_name in old_map.keys() | new_map.keys():
                        op, np = old_map.get(phase_name), new_map.get(phase_name)
                        if op is None or np is None:
                            decisions.update(affected[group])
                        elif (op.target_fraction, op.min_open_days, op.next_phase) != (
                            np.target_fraction, np.min_open_days, np.next_phase
                        ):
                            decisions.add("phase_qualification")
                        elif (op.payout_fraction, op.payout_wait_calendar_days) != (
                            np.payout_fraction, np.payout_wait_calendar_days
                        ):
                            decisions.add("payout_eligibility")
                else:
                    decisions.update(affected[group])
    affected_accounts = []
    if changed:
        for account in accounts:
            pairs = list(zip(account.assignments, account.assignments[1:]))
            for prior, later in pairs:
                if prior.version_id == old.version_id and later.version_id == new.version_id:
                    affected_accounts.append((account.account_id, aware(later.at)))
    return RuleChangeImpact(
        changed_fields=tuple(sorted(changed)), impacted_decisions=tuple(sorted(decisions)),
        affected_accounts_from=tuple(sorted(affected_accounts)),
    )


def rule_from_dict(data: Mapping[str, Any]) -> RuleVersion:
    """Parse explicit structured source capture; never infer omitted rule limits."""
    src = data["source"]
    source = RuleSource(
        source_id=src["source_id"], url=src["url"],
        captured_at=timestamp(src["captured_at"]),
        evidence_type=src["evidence_type"],
        published_at=timestamp(src["published_at"]) if src.get("published_at") else None,
        stated_effective_at=timestamp(src["stated_effective_at"]) if src.get("stated_effective_at") else None,
        raw_page_sha256=src.get("raw_page_sha256"),
        extraction_sha256=src.get("extraction_sha256"),
    )
    return RuleVersion(
        version_id=data["version_id"], program_id=data["program_id"],
        source=source,
        phases=tuple(
            PhaseRule(
                name=p["name"], role=p["role"],
                target_fraction=money(p["target_fraction"]) if p.get("target_fraction") is not None else None,
                min_open_days=p.get("min_open_days"), next_phase=p.get("next_phase"),
                payout_fraction=money(p["payout_fraction"]) if p.get("payout_fraction") is not None else None,
                payout_wait_calendar_days=p.get("payout_wait_calendar_days"),
            ) for p in data["phases"]
        ),
        timezone_name=data["timezone_name"], reset_hour=data["reset_hour"],
        daily_loss_fraction=money(data["daily_loss_fraction"])
        if data.get("daily_loss_fraction") is not None else None,
        max_loss_fraction=money(data["max_loss_fraction"])
        if data.get("max_loss_fraction") is not None else None,
        max_loss_mode=data.get("max_loss_mode", "static"),
        trailing_basis=data.get("trailing_basis", "balance"),
        trailing_update=data.get("trailing_update", "event"),
        trailing_cap_at_initial=data.get("trailing_cap_at_initial", False),
        breach_on_touch=data.get("breach_on_touch", False),
        mark_max_age_seconds=data.get("mark_max_age_seconds", 0),
        unknown_rules=frozenset(data.get("unknown_rules", ())),
    )
