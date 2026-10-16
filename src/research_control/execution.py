"""Permit-gated, native-only execution with an independent conservative fill audit.

The audit is an arithmetic oracle, not an alternative execution simulator.
It rejects unproven queue priority or live OCO behavior.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
from ml4t.backtest import BacktestConfig, OrderType, Strategy, run_backtest
from ml4t.backtest.config import CommissionType, FillOrdering, SlippageType
from ml4t.backtest.types import OrderSide, OrderStatus

from .contracts import ResearchContractV1
from .feature_gateway import FeatureComputation
from .run_permit import RunIntentV1, preflight_run


@dataclass(frozen=True)
class ExecutionAudit:
    status: str
    reason_code: str
    expected: Any
    observed: Any
    limitations: tuple[str, ...] = (
        "Historical native simulation is not broker execution or live OCO proof.",
        "Passive queue priority and gap fills are not established by OHLC bars.",
    )
    evidence: dict[str, Any] = field(default_factory=dict)
    live_execution_qualified: bool = False


def blocked(code: str, expected: Any, observed: Any) -> ExecutionAudit:
    return ExecutionAudit("BLOCKED", code, expected, observed)


class StopFirstBracket(Strategy):
    """One native long bracket. Submit stop before target, never use submit_bracket.

    Submit on a completed signal bar; native engine fills at a later open.
    Native parent_id provides simulated OCO on a full exit fill.
    """

    def __init__(self, symbol: str, *, signal_at: datetime, quantity: float,
                 stop_price: float, limit_price: float):
        if not all(math.isfinite(v) for v in (quantity, stop_price, limit_price)):
            raise ValueError("nonfinite bracket parameter")
        if not (quantity > 0 and 0 < stop_price < limit_price):
            raise ValueError("invalid long-only bracket")
        self.symbol = symbol
        self.signal_at = signal_at
        self.quantity = quantity
        self.stop_price = stop_price
        self.limit_price = limit_price
        self.orders: tuple[Any, Any, Any] | None = None
        self.submitted = False

    def on_data(self, timestamp, data, context, broker):
        if timestamp != self.signal_at or self.submitted:
            return
        bar = data.get(self.symbol)
        if bar is None or broker.get_position(self.symbol) is not None:
            return
        self.submitted = True
        entry = broker.submit_order(self.symbol, self.quantity)
        if entry is None:
            return
        stop = broker.submit_order(
            self.symbol, self.quantity, side=OrderSide.SELL,
            order_type=OrderType.STOP, stop_price=self.stop_price
        )
        target = broker.submit_order(
            self.symbol, self.quantity, side=OrderSide.SELL,
            order_type=OrderType.LIMIT, limit_price=self.limit_price
        )
        if stop is None or target is None:
            raise RuntimeError("native broker rejected protective OCO children")
        stop.parent_id = entry.order_id
        target.parent_id = entry.order_id
        self.orders = (entry, stop, target)


def independent_fill_audit(result: Any, strategy: StopFirstBracket,
                           bars: pl.DataFrame, *, initial_cash: float,
                           multiplier: float = 1.0) -> ExecutionAudit:
    """Check native accounting and conservative stop-first, independent of engine metrics."""
    if strategy.orders is None:
        return blocked("ENGINE_EXECUTION_INVALID", "native linked entry/stop/target", "missing OCO")
    entry, stop, target = strategy.orders
    if (
        entry.order_type != OrderType.MARKET
        or stop.order_type != OrderType.STOP
        or target.order_type != OrderType.LIMIT
        or stop.side != OrderSide.SELL
        or target.side != OrderSide.SELL
        or stop.parent_id != entry.order_id
        or target.parent_id != entry.order_id
    ):
        return blocked("ENGINE_EXECUTION_INVALID", "market entry / sell stop / sell limit / OCO", "invalid orders")

    fills = result.to_fills_dataframe().sort("timestamp")
    trades = result.to_trades_dataframe()
    equity = result.to_equity_dataframe()
    if fills.height != 2 or trades.height != 1 or equity.is_empty():
        return blocked("ENGINE_EXECUTION_INVALID", "two fills, one native trade and equity ledger",
                       {"fills": fills.height, "trades": trades.height, "equity": equity.height})
    event = fills.to_dicts()
    bars = bars.sort("timestamp")
    times = bars["timestamp"].to_list()
    try:
        index = times.index(strategy.signal_at)
    except ValueError:
        return blocked("FEATURE_CAUSALITY_FAIL", "signal on a completed native bar", strategy.signal_at)
    if index + 1 >= len(times):
        return blocked("ENGINE_EXECUTION_INVALID", "next executable open", "end of data")
    first = event[0]
    # The installed native fills currently export UTC timestamps without tzinfo.
    normalize = lambda dt: dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    if (normalize(first["timestamp"]) != times[index + 1] or
        not math.isclose(first["price"], bars["open"][index + 1], abs_tol=1e-8) or
        first["side"] != "buy" or first["order_id"] != entry.order_id):
        return blocked("ENGINE_EXECUTION_INVALID", "entry at next bar open", first)

    second = event[1]
    if second["side"] != "sell" or normalize(second["timestamp"]) <= normalize(first["timestamp"]):
        return blocked("ENGINE_EXECUTION_INVALID", "later protective exit", second)
    exit_candidates = bars.filter(pl.col("timestamp") == normalize(second["timestamp"]))
    if exit_candidates.height != 1:
        return blocked("ENGINE_EXECUTION_INVALID", "existing exit bar", second["timestamp"])
    bar = exit_candidates.row(0, named=True)
    both_hit = bar["low"] <= strategy.stop_price and bar["high"] >= strategy.limit_price
    if both_hit and second["order_id"] != stop.order_id:
        return blocked("ENGINE_EXECUTION_INVALID", "dual-hit stop-first", second["order_id"])
    if (second["order_id"] not in {stop.order_id, target.order_id} or
        (stop.status != OrderStatus.CANCELLED and target.status != OrderStatus.CANCELLED)):
        return blocked("ENGINE_EXECUTION_INVALID", "one OCO exit and cancelled sibling",
                       {"exit_id": second["order_id"], "stop": str(stop.status), "target": str(target.status)})
    if (second["order_id"] == stop.order_id
        and bar["open"] >= strategy.stop_price
        and not math.isclose(second["price"], strategy.stop_price, abs_tol=1e-8)):
        return blocked("ENGINE_EXECUTION_INVALID", "stop fill at conservative trigger", second["price"])
    if second["order_id"] == target.order_id and second["price"] < strategy.limit_price:
        return blocked("ENGINE_EXECUTION_INVALID", "legal sell limit >= target", second["price"])

    # Independent cash/position arithmetic from native fills (no backtest loop).
    cash = initial_cash
    shares = 0.0
    for fill in event:
        signed = fill["quantity"] if fill["side"] == "buy" else -fill["quantity"]
        cash -= signed * fill["price"] * multiplier + fill["commission"]
        shares += signed
    last_close = float(bars["close"][-1])
    expected_equity = cash + shares * last_close * multiplier
    actual_equity = float(equity["equity"][-1])
    if (not math.isclose(shares, 0.0, abs_tol=1e-9) or
        not math.isclose(expected_equity, actual_equity, abs_tol=1e-6)):
        return blocked("ENGINE_EXECUTION_INVALID", "cash/position/equity reconciliation",
                       {"cash": cash, "shares": shares, "expected": expected_equity, "native": actual_equity})
    return ExecutionAudit(
        "PASS", "NATIVE_EXECUTION_AUDITED", "native next-open, stop-first, OCO, cash",
        "passed synthetic arithmetic audit",
        evidence={"fills": event, "trade_count": trades.height,
                  "equity_final": actual_equity, "cash_final": cash,
                  "stop_first": both_hit and second["order_id"] == stop.order_id}
    )


def execute_permitted_native(
    root: str, intent: RunIntentV1 | dict[str, Any],
    computation: FeatureComputation, input_data: pl.DataFrame,
    contract: ResearchContractV1, *, signal_at: datetime,
    quantity: float, stop_price: float, limit_price: float,
    initial_cash: float = 1_000_000.0,
    artifact_dir: str | None = None,
) -> ExecutionAudit:
    """Run one permit-bound native trial, never live execution."""
    gate = preflight_run(root, intent, computation, input_data, contract)
    if gate.status != "PASS" or gate.permit is None:
        return blocked(gate.reason_code, gate.expected, gate.observed)
    permit = gate.permit
    if permit.live_order_authority is not False or permit.identity.engine != "ml4t.backtest":
        return blocked("ENGINE_EXECUTION_INVALID", "research-only native permit", permit.model_dump(mode="json"))
    if permit.multiplier.value != 1.0:
        return blocked("ENGINE_EXECUTION_INVALID", "spot synthetic multiplier 1", permit.multiplier.value)
    if not (math.isfinite(initial_cash) and initial_cash > 0):
        return blocked("ENGINE_EXECUTION_INVALID", "positive initial cash", initial_cash)
    available = computation.data.filter(pl.col("timestamp") == signal_at)
    if (available.height != 1 or
        available["available_at"][0] > permit.available_at or
        signal_at >= permit.exit_at):
        return blocked("FEATURE_CAUSALITY_FAIL", "available completed-bar signal before exit", signal_at)
    if contract.dataset.source_symbol not in input_data["symbol"].to_list():
        return blocked("SOURCE_IDENTITY_CONFLICT", contract.dataset.source_symbol, "not in bars")
    strategy = StopFirstBracket(
        contract.dataset.source_symbol, signal_at=signal_at,
        quantity=quantity, stop_price=stop_price, limit_price=limit_price
    )
    config = BacktestConfig(
        initial_cash=initial_cash, fill_ordering=FillOrdering.EXIT_FIRST,
        allow_short_selling=False, allow_leverage=False,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=float(permit.costs.commission_bps) / 10000,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=float(permit.costs.slippage_bps) / 10000,
    )
    result = run_backtest(input_data, strategy, config=config)
    audit = independent_fill_audit(result, strategy, input_data,
                                  initial_cash=initial_cash, multiplier=1.0)
    if audit.status != "PASS" or artifact_dir is None:
        return audit
    root_path = Path(root).resolve()
    destination = (root_path / artifact_dir).resolve()
    if not destination.is_relative_to(root_path / "run_log"):
        return blocked("EVIDENCE_PATH_INVALID", "new path under run_log", artifact_dir)
    if destination.exists() and any(destination.iterdir()):
        return blocked("EVIDENCE_PATH_INVALID", "staging directory not empty", artifact_dir)
    destination.mkdir(parents=True, exist_ok=True)
    result.to_parquet(str(destination / "native"))
    manifest = {
        "schema_version": 1,
        "permit_sha256": permit.permit_sha256,
        "engine_version": permit.identity.engine_version,
        "qualification": "HISTORICAL_SIMULATION_ONLY",
        "live_order_authority": False,
        "audit": {"status": audit.status, "reason_code": audit.reason_code,
                  "evidence": audit.evidence},
    }
    payload = json.dumps(manifest, sort_keys=True, default=str, allow_nan=False).encode()
    (destination / "execution_audit.json").write_bytes(payload)
    return replace(audit, evidence={**audit.evidence,
        "artifact_path": str(destination.relative_to(root_path)),
        "manifest_sha256": hashlib.sha256(payload).hexdigest()})
