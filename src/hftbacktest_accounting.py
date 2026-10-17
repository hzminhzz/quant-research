"""Auditable execution-accounting helpers for the BTC/ETH hftbacktest."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class ExecutionCost:
    """Execution shortfall in quote currency.

    Positive values reduce PnL. Negative values are execution benefits.
    """

    maker_adverse_selection: float = 0.0
    repeg_cost: float = 0.0
    taker_timing_cost: float = 0.0
    taker_crossing_cost: float = 0.0

    @property
    def total(self) -> float:
        return (
            self.maker_adverse_selection
            + self.repeg_cost
            + self.taker_timing_cost
            + self.taker_crossing_cost
        )


@dataclass(frozen=True)
class TradeAttribution:
    """Flat-to-flat trade PnL decomposition in quote currency."""

    gross_alpha: float
    maker_adverse_selection: float
    repeg_cost: float
    taker_timing_cost: float
    taker_crossing_cost: float
    taker_fee: float
    net_pnl: float
    reconciliation_residual: float

    @property
    def taker_cost(self) -> float:
        return self.taker_timing_cost + self.taker_crossing_cost + self.taker_fee

    def to_dict(self) -> dict[str, float]:
        payload = asdict(self)
        payload["taker_cost"] = self.taker_cost
        return payload


def execution_cost(
    *,
    signed_order_qty: float,
    exec_price: float,
    reference_mid: float,
    style: str,
    original_quote: float | None = None,
    taker_submit_mid: float | None = None,
) -> ExecutionCost:
    """Decompose one fill shortfall without double counting.

    signed_order_qty is positive for a buy and negative for a sell.
    For maker fills, maker_adverse_selection is the original passive quote
    versus the reference midpoint. It can be negative when spread capture is
    favorable. A re-peg is measured separately from the original passive quote
    to the final executed quote.

    For taker fills, timing is the move from the decision/reference midpoint
    to the midpoint when the market order was submitted. Crossing is the move
    from that submit midpoint to the executed market price.
    """

    values = (signed_order_qty, exec_price, reference_mid)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("execution inputs must be finite")

    if style == "maker_original":
        return ExecutionCost(
            maker_adverse_selection=signed_order_qty * (exec_price - reference_mid)
        )

    if style == "maker_repeg":
        if original_quote is None or not math.isfinite(original_quote):
            raise ValueError("maker_repeg requires a finite original_quote")
        return ExecutionCost(
            maker_adverse_selection=signed_order_qty * (original_quote - reference_mid),
            repeg_cost=signed_order_qty * (exec_price - original_quote),
        )

    if style == "taker":
        if taker_submit_mid is None or not math.isfinite(taker_submit_mid):
            raise ValueError("taker fill requires a finite taker_submit_mid")
        return ExecutionCost(
            taker_timing_cost=signed_order_qty * (taker_submit_mid - reference_mid),
            taker_crossing_cost=signed_order_qty * (exec_price - taker_submit_mid),
        )

    raise ValueError(f"unknown execution style: {style}")


def attribute_trade(
    *,
    gross_alpha: float,
    net_pnl: float,
    maker_adverse_selection: float = 0.0,
    repeg_cost: float = 0.0,
    taker_timing_cost: float = 0.0,
    taker_crossing_cost: float = 0.0,
    taker_fee: float = 0.0,
) -> TradeAttribution:
    """Return an explicit PnL bridge with positive costs reducing PnL."""

    values = (
        gross_alpha,
        net_pnl,
        maker_adverse_selection,
        repeg_cost,
        taker_timing_cost,
        taker_crossing_cost,
        taker_fee,
    )
    if not all(math.isfinite(value) for value in values):
        raise ValueError("trade attribution values must be finite")

    explained = (
        gross_alpha
        - maker_adverse_selection
        - repeg_cost
        - taker_timing_cost
        - taker_crossing_cost
        - taker_fee
    )
    residual = net_pnl - explained
    return TradeAttribution(
        gross_alpha=gross_alpha,
        maker_adverse_selection=maker_adverse_selection,
        repeg_cost=repeg_cost,
        taker_timing_cost=taker_timing_cost,
        taker_crossing_cost=taker_crossing_cost,
        taker_fee=taker_fee,
        net_pnl=net_pnl,
        reconciliation_residual=residual,
    )


def entry_fully_confirmed(
    btc_filled: bool,
    eth_filled: bool,
    btc_position: float,
    eth_position: float,
) -> bool:
    """Pair state opens only after both legs fill and both positions exist."""
    return btc_filled and eth_filled and btc_position != 0.0 and eth_position != 0.0


def exit_fully_confirmed(
    btc_filled: bool,
    eth_filled: bool,
    btc_position: float,
    eth_position: float,
    *,
    tolerance: float = 1e-12,
) -> bool:
    """Pair state closes only after both exit legs fill and positions are flat."""
    return (
        btc_filled
        and eth_filled
        and abs(btc_position) <= tolerance
        and abs(eth_position) <= tolerance
    )


def assert_trade_reconciliation(
    trade_pnls: list[float],
    realized_pnl: float,
    *,
    unclosed_realized_component: float = 0.0,
    tolerance: float = 1e-7,
) -> float:
    """Verify completed plus explicitly unclosed realized PnL equals engine PnL."""
    residual = float(sum(trade_pnls) + unclosed_realized_component - realized_pnl)
    if abs(residual) > tolerance:
        raise AssertionError(f"trade PnL does not reconcile: {residual}")
    return residual
