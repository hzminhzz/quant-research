"""ATS-7 release boundary around the installed native ML4T runtime.

No matcher, broker position book, provider transport or approval issuer lives here.
The first qualified risk domain supports exactly one account and one native writer.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import math
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from ml4t.backtest import Strategy
from ml4t.backtest.types import OrderSide, OrderStatus, OrderType
from ml4t.live import LiveEngine, LiveRiskConfig
from ml4t.live.orders import CanonicalOrderRequest
from ml4t.live.protocols import ExecutionCapability
from ml4t.live.safety import RiskLimitError

from src.release_contracts import ExternalAuthority, ReleaseBlocked, ReleaseManifest
from src.release_journal import ReleaseJournal, execution_identity
from src.research_control.action_authorization import sha256_json
from src.research_control.ats3_audit_broker import AuditSafeBroker


class LocalNoEffectsBroker:
    """Read-only placeholder for native VirtualPortfolio; cannot submit anywhere."""
    execution_capabilities = frozenset({ExecutionCapability.LIMIT})

    def __init__(self):
        self.positions: dict = {}
        self.pending_orders: list = []
        self.is_connected = False

    async def connect(self):
        self.is_connected = True

    async def disconnect(self):
        self.is_connected = False

    async def is_connected_async(self):
        return self.is_connected

    async def get_account_value_async(self):
        return 100_000.0

    async def get_cash_async(self):
        return 100_000.0

    async def get_positions_async(self):
        return {}

    async def get_pending_orders_async(self, asset=None):
        return []

    async def get_position_async(self, asset):
        return None

    async def submit_order_async(self, *args, **kwargs):
        raise ReleaseBlocked("LOCAL_BROKER_HAS_NO_EXTERNAL_EFFECTS")

    async def cancel_order_async(self, *args, **kwargs):
        raise ReleaseBlocked("LOCAL_BROKER_HAS_NO_EXTERNAL_EFFECTS")

    async def close_position_async(self, *args, **kwargs):
        raise ReleaseBlocked("LOCAL_BROKER_HAS_NO_EXTERNAL_EFFECTS")


def _risk_identity(config: LiveRiskConfig) -> str:
    values = asdict(config)
    values.pop("kill_switch_enabled", None)  # Native automatic/manual latch is mutable.
    values["allowed_assets"] = sorted(values["allowed_assets"])
    values["blocked_assets"] = sorted(values["blocked_assets"])
    return sha256_json(values)


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(v) for v in value]
    return value


class ReleaseSafeBroker(AuditSafeBroker):
    def __init__(self, broker, manifest: ReleaseManifest, state_root: Path,
                 authority: ExternalAuthority | None = None):
        if type(manifest) is not ReleaseManifest:
            raise ReleaseBlocked("EXACT_RELEASE_MANIFEST_REQUIRED")
        manifest = ReleaseManifest.model_validate_json(manifest.model_dump_json())
        self.manifest = manifest
        self.release_identity = manifest.identity
        self.authority = authority
        self._decision_time: str | None = None
        self._ordinal = 0
        self._active_identity: str | None = None
        self._native_intent_emitted = False
        self._duplicate_bar = False
        self._account_observed_at: datetime | None = None
        self._last_account: dict | None = None
        self._closed = False
        manifest.verify_sources()
        state_root = state_root.resolve()
        state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if state_root.stat().st_mode & 0o077:
            raise ReleaseBlocked("PRIVATE_RUNTIME_DIRECTORY_REQUIRED")
        self.domain_dir = state_root / manifest.risk_domain
        self.domain_dir.mkdir(exist_ok=True, mode=0o700)
        if manifest.environment == "LOCAL_PAPER":
            if type(broker) is not LocalNoEffectsBroker or manifest.risk.capital != 100_000.0:
                raise ReleaseBlocked("NATIVE_LOCAL_SIMULATION_BINDING_REQUIRED")
            mode = "shadow"
        else:
            if manifest.environment == "LIVE":
                raise ReleaseBlocked("LIVE_PROVIDER_QUALIFICATION_NOT_AVAILABLE")
            if type(authority) is not ExternalAuthority:
                raise ReleaseBlocked("EXTERNAL_AUTHORIZATION_REQUIRED")
            if state_root != Path("/var/lib/quant-research/ats7"):
                raise ReleaseBlocked("CANONICAL_EXTERNAL_RISK_DOMAIN_REQUIRED")
            # A single external account uses the same native writer across all
            # strategies/releases. Additional accounts cannot bypass global limits.
            self.domain_dir = state_root / "single-external-account"
            self.domain_dir.mkdir(exist_ok=True, mode=0o700)
            authority.require(manifest, "open", datetime.now(UTC))
            from connectors.bybit.broker import BybitLiveBroker
            from connectors.bybit.client import BybitClient
            if type(broker) is not BybitLiveBroker or type(broker.client) is not BybitClient:
                raise ReleaseBlocked("EXACT_QUALIFIED_PROVIDER_REQUIRED")
            cfg = broker.client.config
            expected_env = "demo" if manifest.environment == "PROVIDER_DEMO" else "mainnet"
            uid = cfg.expected_demo_uid if expected_env == "demo" else cfg.subaccount_id
            if (cfg.environment.value != expected_env or cfg.mode.value != "execution"
                    or not uid or manifest.account_ref != "sha256:" + hashlib.sha256(uid.encode()).hexdigest()):
                raise ReleaseBlocked("PROVIDER_ACCOUNT_IDENTITY_MISMATCH")
            mode = "paper" if expected_env == "demo" else "live"
        values = manifest.risk.model_dump()
        values.pop("capital")
        config = LiveRiskConfig(**values, execution_mode=mode,
                                allowed_assets={p.asset for p in manifest.products},
                                fail_on_reconciliation_mismatch=True,
                                fail_on_journal_error=True,
                                allow_reducing_risk_when_killed=True,
                                halt_on_reducing_risk_failure=True,
                                state_file=str(self.domain_dir / "native-risk.json"))
        # Acquire the native exclusive writer before opening/recovering our journal.
        super().__init__(broker, config)
        self._bound_risk_identity = _risk_identity(config)
        try:
            self.release_journal = ReleaseJournal(self.domain_dir / "release.sqlite", manifest)
            self.release_journal.verify_native_references(self._journal_path())
            if self.release_journal.halted:
                super().enable_kill_switch("ATS7 persisted release halt")
        except BaseException:
            super().close_persistence()
            raise

    def record_event(self, event: str, **payload: Any) -> None:
        if event == "order_submission_intent":
            self._native_intent_emitted = True
        if event == "kill_switch_activated" and hasattr(self, "release_journal") and not self.release_journal.halted:
            self.release_journal.halt(str(payload.get("reason", "native automatic halt")))
        payload["release_identity"] = self.release_identity
        if self._active_identity is not None:
            payload["execution_identity"] = self._active_identity
        super().record_event(event, **payload)

    def _record_market_data(self, timestamp, data, context):
        now = datetime.now(UTC)
        if timestamp.tzinfo is None:
            self.enable_kill_switch("NAIVE_FEED_CLOCK")
            raise ReleaseBlocked("NAIVE_FEED_CLOCK")
        lag = (now - timestamp).total_seconds()
        if lag < -self.manifest.operations.max_clock_skew_seconds or lag > self.manifest.risk.max_data_staleness_seconds:
            self.enable_kill_switch("FEED_CLOCK_OR_STALENESS")
            raise ReleaseBlocked("FEED_CLOCK_OR_STALENESS")
        if set(data) != {p.asset for p in self.manifest.products}:
            self.enable_kill_switch("INSTRUMENT_MAPPING_MISMATCH")
            raise ReleaseBlocked("INSTRUMENT_MAPPING_MISMATCH")
        for item in data.values():
            if not isinstance(item, dict) or any(
                not isinstance(item.get(k), (int, float)) or not math.isfinite(item[k]) or item[k] <= 0
                for k in ("open", "high", "low", "close")
            ):
                self.enable_kill_switch("INVALID_BAR")
                raise ReleaseBlocked("INVALID_BAR")
            if item["low"] > min(item["open"], item["close"]) or item["high"] < max(item["open"], item["close"]):
                self.enable_kill_switch("INVALID_BAR_RANGE")
                raise ReleaseBlocked("INVALID_BAR_RANGE")
        stamp = timestamp.astimezone(UTC).isoformat()
        digest = sha256_json(_jsonable([data, context]))
        last = self.release_journal.connection.execute(
            "SELECT payload FROM events WHERE kind='bar' ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        self._duplicate_bar = False
        if last:
            prior = json.loads(last[0])
            if stamp == prior["timestamp"] and digest == prior["data_sha256"]:
                self._duplicate_bar = True
                self._decision_time = None
                return
            if stamp <= prior["timestamp"]:
                self.enable_kill_switch("CONFLICTING_OR_REORDERED_BAR")
                raise ReleaseBlocked("CONFLICTING_OR_REORDERED_BAR")
        self._decision_time, self._ordinal = stamp, 0
        self.release_journal.record("bar", {"timestamp": stamp, "data_sha256": digest,
                                           "data": _jsonable(data), "context": _jsonable(context)})
        super()._record_market_data(timestamp, data, context)

    async def refresh_account(self, *, record=True):
        started = datetime.now(UTC)
        equity = await self.get_account_value_async()
        cash = await self.get_cash_async()
        positions, pending = await self._capture_runtime_snapshot_async()
        ended = datetime.now(UTC)
        if ((ended - started).total_seconds() > self.manifest.operations.max_account_age_seconds
                or not all(math.isfinite(v) for v in (equity, cash)) or equity <= 0 or cash < 0):
            self.enable_kill_switch("INVALID_OR_STALE_ACCOUNT")
            raise ReleaseBlocked("INVALID_OR_STALE_ACCOUNT")
        self._account_observed_at = ended
        self._last_account = {"equity": equity, "cash": cash, "positions": {
            k: {"quantity": p.quantity, "price": p.current_price, "entry_price": p.entry_price}
            for k, p in positions.items()}, "pending_count": len(pending)}
        if record:
            self.release_journal.record("account_snapshot", self._last_account)
        return self._last_account

    async def connect(self):
        await super().connect()
        await self.refresh_account()
        self.release_journal.verify_native_references(self._journal_path())
        if self.manifest.environment != "LOCAL_PAPER":
            count = self.release_journal.connection.execute("SELECT count(*) FROM decisions").fetchone()[0]
            if count == 0 and (self.positions or self.pending_orders):
                self.enable_kill_switch("PREEXISTING_EXPOSURE_NOT_OWNED")
                raise ReleaseBlocked("PREEXISTING_EXPOSURE_NOT_OWNED")
        self.release_journal.record("connected", {"native_reconciliation": self.reconciliation_report})

    async def _require(self, action: str):
        now = datetime.now(UTC)
        if self.manifest.identity != self.release_identity:
            raise ReleaseBlocked("MANIFEST_CHANGED")
        try:
            self.manifest.verify_sources()
        except ReleaseBlocked:
            self.enable_kill_switch("SOURCE_IDENTITY_CHANGED")
            raise
        if _risk_identity(self.config) != self._bound_risk_identity:
            self.enable_kill_switch("RISK_POLICY_CHANGED")
            raise ReleaseBlocked("RISK_POLICY_CHANGED")
        if now < self.manifest.account_terms_effective_at:
            raise ReleaseBlocked("ACCOUNT_TERMS_NOT_EFFECTIVE")
        if action in {"open", "resume"} and not self.manifest.not_before <= now < self.manifest.expires_at:
            raise ReleaseBlocked("RELEASE_EXPIRED")
        if self.manifest.environment != "LOCAL_PAPER":
            if self.authority is None:
                raise ReleaseBlocked("EXTERNAL_AUTHORIZATION_REQUIRED")
            self.authority.require(self.manifest, action, now)
            cfg = self._broker.client.config
            uid = cfg.expected_demo_uid if self.manifest.environment == "PROVIDER_DEMO" else cfg.subaccount_id
            expected_env = "demo" if self.manifest.environment == "PROVIDER_DEMO" else "mainnet"
            if (cfg.environment.value != expected_env or cfg.mode.value != "execution"
                    or not uid or "sha256:" + hashlib.sha256(uid.encode()).hexdigest() != self.manifest.account_ref):
                raise ReleaseBlocked("PROVIDER_ACCOUNT_IDENTITY_MISMATCH")
            if expected_env == "demo":
                self._broker.client._require_demo_endpoint()
                if not self._broker.client.demo_identity_verified:
                    raise ReleaseBlocked("AUTHENTICATED_PROVIDER_IDENTITY_REQUIRED")
        if hasattr(self, "_bound_strategy"):
            try:
                _verify_parameters(self._bound_strategy, self.manifest)
            except ReleaseBlocked:
                self.enable_kill_switch("STRATEGY_PARAMETERS_CHANGED")
                raise
        if action == "open" and (self.release_journal.halted or self.release_journal.unknown):
            raise ReleaseBlocked("HALTED_OR_UNKNOWN_EXPOSURE")
        if not await self._broker.is_connected_async():
            raise ReleaseBlocked("BROKER_DISCONNECTED")
        await self.refresh_account()
        if self._account_observed_at is None or (datetime.now(UTC) - self._account_observed_at).total_seconds() > self.manifest.operations.max_account_age_seconds:
            raise ReleaseBlocked("STALE_ACCOUNT")
        if action == "open" and self._last_account["cash"] <= 0:
            raise ReleaseBlocked("INSUFFICIENT_MARGIN")

    def _product_check(self, request):
        products = [p for p in self.manifest.products if p.asset == request.asset]
        if len(products) != 1 or request.order_type not in {OrderType.MARKET, OrderType.LIMIT} or request.stop_price is not None:
            raise ReleaseBlocked("UNQUALIFIED_PRODUCT_OR_ORDER_TYPE")
        product = products[0]
        qty = Decimal(str(request.quantity))
        if qty < Decimal(product.minimum_quantity) or qty % Decimal(product.quantity_step):
            raise ReleaseBlocked("LOT_SIZE_MISMATCH")
        price = request.limit_price
        if price is not None and Decimal(str(price)) % Decimal(product.price_tick):
            raise ReleaseBlocked("PRICE_TICK_MISMATCH")
        snap = self._get_market_snapshot(request.asset)
        if snap is None:
            raise ReleaseBlocked("MARKET_REFERENCE_MISSING")
        if qty * Decimal(str(price or snap.price)) < Decimal(product.minimum_notional):
            raise ReleaseBlocked("MINIMUM_NOTIONAL")

    def _stage(self, action: str, request: dict, *, control_key: str | None = None):
        stamp = control_key or self._decision_time
        if stamp is None:
            raise ReleaseBlocked("NO_FROZEN_CAUSAL_DECISION")
        self._ordinal += 1
        ordinal = 0 if control_key else self._ordinal
        identity = execution_identity(self.release_identity, stamp, ordinal, action)
        self.release_journal.stage(identity, {**request, "action": action, "decision_time": stamp})
        self._active_identity = identity
        self.record_event("ats7_decision_committed", execution_identity=identity,
                          action=action, decision_time=stamp, request=request)
        return identity

    async def _submit_order_unlocked(self, asset, quantity, side=None, order_type=OrderType.MARKET,
                                     limit_price=None, stop_price=None, **kwargs):
        if kwargs.get("reduce_only") or kwargs.get("reducing_risk"):
            raise ReleaseBlocked("USE_VERIFIED_NATIVE_REDUCTION_PATH")
        if order_type not in {OrderType.MARKET, OrderType.LIMIT} or stop_price is not None:
            raise ReleaseBlocked("UNQUALIFIED_ORDER_TYPE")
        if set(kwargs) - {"target_intent_id", "child_intent_id", "intent_idempotency_key"}:
            raise ReleaseBlocked("UNQUALIFIED_ORDER_PARAMETERS")
        await self._require("open")
        request = CanonicalOrderRequest.from_input(asset, quantity, side, order_type, limit_price,
                                                   stop_price, capabilities=self.execution_capabilities)
        self._product_check(request)
        identity = self._stage("open", {"asset": request.asset, "quantity": request.quantity,
                                        "side": request.side.value, "order_type": request.order_type.value,
                                        "limit_price": request.limit_price})
        self._native_intent_emitted = False
        try:
            order = await super()._submit_order_unlocked(
                asset, quantity, side, order_type, limit_price, stop_price,
                **{**kwargs, "intent_idempotency_key": identity})
            state = "LOCAL_FILLED" if self.config.shadow_mode and order.status == OrderStatus.FILLED else "ACKNOWLEDGED"
            self.release_journal.finish(identity, state, order.order_id, self._order_event_payload(order))
            return order
        except (RiskLimitError, PermissionError) as exc:
            state = "UNKNOWN" if self._native_intent_emitted else "REJECTED_BEFORE_EFFECT"
            self.release_journal.finish(identity, state, None, {"error": type(exc).__name__})
            if state == "UNKNOWN":
                super().enable_kill_switch("ATS7 uncertain post-dispatch refusal")
            raise
        except BaseException as exc:
            self.release_journal.finish(identity, "UNKNOWN", None, {"error": type(exc).__name__})
            super().enable_kill_switch("ATS7 unknown execution")
            raise
        finally:
            self._active_identity = None

    async def _reduce_position_unlocked(self, asset, quantity, *, reason, idempotency_key, fill_price=None):
        if fill_price is not None:
            raise ReleaseBlocked("EXPLICIT_FILL_PRICE_NOT_QUALIFIED")
        await self._require("reduce")
        position = self.get_position(asset)
        if position is None or not 0 < quantity <= abs(position.quantity):
            raise ReleaseBlocked("REDUCTION_WOULD_INCREASE_OR_CROSS_EXPOSURE")
        side = OrderSide.SELL if position.quantity > 0 else OrderSide.BUY
        request = CanonicalOrderRequest.from_input(asset, quantity, side, OrderType.MARKET,
                                                   capabilities=self.execution_capabilities)
        self._product_check(request)
        identity = self._stage("reduce", {"asset": asset, "quantity": quantity, "side": side.value},
                               control_key=None if self._decision_time else "reduce:" + idempotency_key)
        try:
            # Avoid native close_position's broker-wide close shortcut so the
            # deterministic client identity reaches the provider reduction call.
            order = await super()._reduce_position_unlocked(
                asset, quantity, reason="ats7:" + reason, idempotency_key=identity, fill_price=fill_price)
            state = "LOCAL_FILLED" if self.config.shadow_mode and order.status == OrderStatus.FILLED else "ACKNOWLEDGED"
            self.release_journal.finish(identity, state, order.order_id, self._order_event_payload(order))
            return order
        except BaseException as exc:
            self.release_journal.finish(identity, "UNKNOWN", None, {"error": type(exc).__name__})
            super().enable_kill_switch("ATS7 uncertain reduction")
            raise
        finally:
            self._active_identity = None

    async def _cancel_order_unlocked(self, order_id):
        await self._require("cancel")
        own = self.release_journal.connection.execute(
            "SELECT 1 FROM decisions WHERE order_id=?", (order_id,)).fetchone()
        if not own:
            raise ReleaseBlocked("ORDER_NOT_OWNED_BY_RELEASE")
        identity = self._stage("cancel", {"order_id": order_id}, control_key="cancel:" + order_id)
        try:
            result = await super()._cancel_order_unlocked(order_id)
            self.release_journal.finish(identity, "ACKNOWLEDGED", order_id,
                                        {"cancel_request_acknowledged": result, "terminal_fill_proven": False})
            return result
        except BaseException as exc:
            self.release_journal.finish(identity, "UNKNOWN", order_id, {"error": type(exc).__name__})
            raise
        finally:
            self._active_identity = None

    async def _replace_order_unlocked(self, *args, **kwargs):
        raise ReleaseBlocked("REPLACE_NOT_QUALIFIED_FOR_THIS_RELEASE")

    def enable_kill_switch(self, reason="Manual"):
        if hasattr(self, "release_journal"):
            self.release_journal.halt(reason)
        super().enable_kill_switch(reason)

    def disable_kill_switch(self):
        raise ReleaseBlocked("USE_AUTHORIZED_RESUME")

    async def resume(self, operator_reason: str):
        if not operator_reason.strip():
            raise ReleaseBlocked("OPERATOR_RESUME_REASON_REQUIRED")
        await self._require("resume")
        if self.release_journal.unknown:
            raise ReleaseBlocked("UNKNOWN_EXPOSURE_CANNOT_RESUME")
        report = await self.preview_reconciliation_async()
        if not report["clean"]:
            raise ReleaseBlocked("RECONCILIATION_REQUIRED")
        self.release_journal.record("resume", {"reason": operator_reason, "reconciliation": report})
        super().disable_kill_switch()

    def close_persistence(self):
        if self._closed:
            return
        self._closed = True
        super().close_persistence()
        if hasattr(self, "release_journal"):
            self.release_journal.close()


def _verify_parameters(strategy, manifest):
    for key, expected in json.loads(manifest.strategy.parameters_json).items():
        if getattr(strategy, key, object()) != expected:
            raise ReleaseBlocked("STRATEGY_PARAMETER_MISMATCH:" + key)


def _verify_feed(feed, manifest):
    binding = json.loads(manifest.data_cost_calendar_execution_json)
    if type(feed).__module__ + "." + type(feed).__name__ != binding["feed_class"]:
        raise ReleaseBlocked("FEED_IDENTITY_MISMATCH")
    for key, expected in binding["feed_parameters"].items():
        if getattr(feed, key, object()) != expected:
            raise ReleaseBlocked("FEED_PARAMETER_MISMATCH:" + key)


class _ReleaseCallbackGate:
    """Delegate the unchanged Strategy through native lifecycle bookkeeping."""
    def __init__(self, strategy):
        self.strategy = strategy
        self.blocked = False

    def __getattr__(self, name):
        callback = getattr(self.strategy, name)
        if self.blocked:
            return lambda *args: None
        return callback


class ReleaseLiveEngine(LiveEngine):
    async def _dispatch_strategy(self, phase, *args, event_time=None):
        try:
            _verify_parameters(self.broker._bound_strategy, self.broker.manifest)
            _verify_feed(self.broker._bound_feed, self.broker.manifest)
        except ReleaseBlocked:
            self.broker.enable_kill_switch("STRATEGY_PARAMETERS_CHANGED")
            raise
        gate = self.lifecycle_dispatcher.strategy
        gate.blocked = event_time is not None and (self.broker._duplicate_bar or self.broker.release_journal.halted)
        if gate.blocked:
            self.broker.release_journal.record("callback_suppressed",
                {"phase": phase.value, "event_time": event_time.isoformat(),
                 "reason": "duplicate_bar" if self.broker._duplicate_bar else "release_halted"})
        if event_time is None:
            self.broker._decision_time = None
        try:
            # Native dispatch must still own phase counts, worker timing and
            # shutdown validation, even when business callbacks are suppressed.
            return await super()._dispatch_strategy(phase, *args, event_time=event_time)
        finally:
            gate.blocked = False


def build_release_engine(strategy: Strategy, feed, manifest: ReleaseManifest,
                         state_root: Path, *, broker=None, authority=None) -> ReleaseLiveEngine:
    if not isinstance(strategy, Strategy):
        raise ReleaseBlocked("NATIVE_STRATEGY_REQUIRED")
    if (type(strategy).__module__ != manifest.strategy.module
            or type(strategy).__name__ != manifest.strategy.class_name):
        raise ReleaseBlocked("STRATEGY_IDENTITY_MISMATCH")
    source = Path(inspect.getfile(type(strategy))).resolve()
    if not any(s.role == "strategy" and Path(s.path).resolve() == source for s in manifest.sources):
        raise ReleaseBlocked("STRATEGY_SOURCE_NOT_BOUND")
    _verify_parameters(strategy, manifest)
    _verify_feed(feed, manifest)
    if manifest.environment == "LOCAL_PAPER":
        if broker is not None:
            raise ReleaseBlocked("LOCAL_PROVIDER_SUBSTITUTION_DENIED")
        broker = LocalNoEffectsBroker()
    if broker is None:
        raise ReleaseBlocked("EXPLICIT_PROVIDER_REQUIRED")
    safe = ReleaseSafeBroker(broker, manifest, state_root, authority)
    safe._bound_strategy = strategy
    safe._bound_feed = feed
    try:
        engine = ReleaseLiveEngine(strategy, safe, feed,
                                   feed_silence_seconds=manifest.operations.feed_silence_seconds,
                                   max_event_age_seconds=manifest.risk.max_data_staleness_seconds,
                                   halt_on_unhealthy=True, auto_recover=False)
        engine.lifecycle_dispatcher.strategy = _ReleaseCallbackGate(strategy)
        return engine
    except BaseException:
        safe.close_persistence()
        raise
