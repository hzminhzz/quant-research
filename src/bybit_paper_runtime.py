"""Issue #45: validated paper-risk configuration and native runtime wiring only.

No broker credentials, order commands or independent trading state are created here.
Account ownership uses ML4T's exclusive state writer: all strategies for the
same Demo account MUST point at the same canonical account state file.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

from connectors.bybit.broker import BybitLiveBroker
from connectors.bybit.config import Environment, Mode
from ml4t.backtest.strategy import Strategy
from ml4t.live import LiveEngine, LiveRiskConfig

from src.research_control.ats3_audit_broker import AuditSafeBroker


class PaperConfigBlocked(ValueError):
    """Deployment configuration is incomplete or fails the paper safety contract."""


@dataclass(frozen=True)
class ReviewedPaperAccount:
    account_uid: str
    strategy_id: str
    allowed_assets: frozenset[str]
    max_order_shares: float
    max_order_value: float
    max_position_shares: float
    max_position_value: float
    max_total_exposure: float
    max_positions: int
    max_orders_per_minute: int
    max_daily_loss: float
    max_drawdown_pct: float
    max_price_deviation_pct: float
    max_data_staleness_seconds: float
    dedup_window_seconds: float
    feed_silence_seconds: float
    max_event_age_seconds: float
    max_recovery_attempts: int
    recovery_cooldown_seconds: float
    state_dir: Path
    reviewed: bool = False


def make_native_risk(account: ReviewedPaperAccount) -> LiveRiskConfig:
    """Do not inherit financial or safety defaults from LiveRiskConfig."""
    if version("ml4t-live") != "0.1.2":
        raise PaperConfigBlocked("ml4t-live==0.1.2 required")
    if not account.reviewed or not account.account_uid or not account.strategy_id:
        raise PaperConfigBlocked("explicitly reviewed Demo account and strategy required")
    if not account.account_uid.isdecimal() or not account.allowed_assets:
        raise PaperConfigBlocked("verified numeric Demo UID and assets required")
    if any(not isinstance(a, str) or not a.strip() or ":" not in a for a in account.allowed_assets):
        raise PaperConfigBlocked("venue-qualified asset symbols required")
    path = Path(account.state_dir).resolve()
    repo = Path(__file__).resolve().parents[1]
    connector = Path(__import__("connectors.bybit", fromlist=["__file__"]).__file__).resolve().parents[2]
    if not path.is_absolute() or path.is_relative_to(repo) or path.is_relative_to(connector):
        raise PaperConfigBlocked("account state directory must be outside repositories")
    if not path.exists() or not path.is_dir():
        raise PaperConfigBlocked("existing protected account state directory required")
    if path.stat().st_mode & 0o077:
        raise PaperConfigBlocked("account state directory must be private (0700)")
    required_positive = (
        "max_order_shares", "max_order_value", "max_position_shares",
        "max_position_value", "max_total_exposure", "max_positions",
        "max_orders_per_minute", "max_daily_loss", "max_drawdown_pct",
        "max_price_deviation_pct", "max_data_staleness_seconds",
        "dedup_window_seconds", "feed_silence_seconds", "max_event_age_seconds",
        "max_recovery_attempts", "recovery_cooldown_seconds",
    )
    import math
    for key in required_positive:
        val = getattr(account, key)
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val) or val <= 0:
            raise PaperConfigBlocked(f"explicit positive {key} required")
    if isinstance(account.max_recovery_attempts, bool) or not isinstance(account.max_recovery_attempts, int):
        raise PaperConfigBlocked("max_recovery_attempts must be a finite integer")
    if account.max_drawdown_pct > 1 or account.max_price_deviation_pct > 1:
        raise PaperConfigBlocked("risk percentages must be <= 1")
    if account.max_order_value > account.max_position_value or account.max_position_value > account.max_total_exposure:
        raise PaperConfigBlocked("order/position/exposure caps inconsistent")
    if account.max_order_shares > account.max_position_shares:
        raise PaperConfigBlocked("order quantity exceeds position quantity cap")

    # Deliberately account-scoped, NEVER strategy-scoped. ML4T's single-writer
    # state lock prevents a second independently owned runtime on this account.
    state_path = path / f"bybit-demo-account-{account.account_uid}.json"
    return LiveRiskConfig(
        execution_mode="paper",
        allowed_assets=set(account.allowed_assets),
        max_order_shares=account.max_order_shares,
        max_order_value=account.max_order_value,
        max_position_shares=account.max_position_shares,
        max_position_value=account.max_position_value,
        max_total_exposure=account.max_total_exposure,
        max_positions=account.max_positions,
        max_orders_per_minute=account.max_orders_per_minute,
        max_daily_loss=account.max_daily_loss,
        max_drawdown_pct=account.max_drawdown_pct,
        max_price_deviation_pct=account.max_price_deviation_pct,
        max_data_staleness_seconds=account.max_data_staleness_seconds,
        dedup_window_seconds=account.dedup_window_seconds,
        fail_on_reconciliation_mismatch=True,
        fail_on_journal_error=True,
        state_file=str(state_path),
    )


def build_native_paper_engine(
    strategy: Strategy, broker: BybitLiveBroker, feed: object, account: ReviewedPaperAccount,
) -> LiveEngine:
    """Construct native engine without connecting or submitting any orders."""
    if not isinstance(strategy, Strategy):
        raise PaperConfigBlocked("native ml4t.backtest.Strategy required")
    cfg = broker.client.config
    if (
        cfg.environment is not Environment.DEMO
        or cfg.mode is not Mode.EXECUTION
        or not cfg.api_key or not cfg.api_secret
        or cfg.expected_demo_uid != account.account_uid
        or cfg.subaccount_id not in (None, account.account_uid)
    ):
        raise PaperConfigBlocked("dedicated, explicitly selected Demo execution identity required")
    risk = make_native_risk(account)
    # Bar-based watchdog must allow a whole completed bar before declaring silence.
    # The Bybit kline feed declares its cadence in timeframe, e.g. "1m".
    timeframe = getattr(feed, "timeframe", None)
    if timeframe is not None:
        import re

        match = re.fullmatch(r"([1-9][0-9]*)([mhd])", str(timeframe))
        if match is None:
            raise PaperConfigBlocked("feed cadence must be an explicit m/h/d timeframe")
        interval_seconds = int(match.group(1)) * {"m": 60, "h": 3600, "d": 86400}[match.group(2)]
        if account.feed_silence_seconds <= interval_seconds:
            raise PaperConfigBlocked("feed_silence_seconds must exceed the completed-bar cadence")
    # Validate config before taking the exclusive native state writer.
    safe = AuditSafeBroker(broker, risk)
    try:
        return LiveEngine(
            strategy=strategy,
            broker=safe,
            feed=feed,
            feed_silence_seconds=account.feed_silence_seconds,
            max_event_age_seconds=account.max_event_age_seconds,
            halt_on_unhealthy=True,
            auto_recover=True,
            max_recovery_attempts=account.max_recovery_attempts,
            recovery_cooldown_seconds=account.recovery_cooldown_seconds,
        )
    except BaseException:
        safe.close_persistence()
        raise
