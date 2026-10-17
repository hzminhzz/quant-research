"""ATS-3 runtime integration hook: SafeBroker lifecycle outcome persistence.

Guarantees that every order submission intent is followed by a recorded terminal
disposition (order_submitted, order_rejected, order_submission_rejected) or an
explicitly classified unknown outcome (order_submission_unknown for transport/unverified
exceptions, or order_accepted_unpersisted for accepted-but-unpersisted orders).
"""
from __future__ import annotations

import asyncio
from typing import Any

from ml4t.backtest.types import Order, OrderSide, OrderType
from ml4t.live.persistence import AcceptedOrderPersistenceError
from ml4t.live.safety import RiskLimitError, SafeBroker


class AuditSafeBroker(SafeBroker):
    """Runtime wrapper around SafeBroker enforcing complete lifecycle journaling."""

    async def _submit_order_unlocked(
        self,
        asset: str,
        quantity: float,
        side: OrderSide | None = None,
        order_type: OrderType = OrderType.MARKET,
        limit_price: float | None = None,
        stop_price: float | None = None,
        **kwargs: Any,
    ) -> Order:
        try:
            return await super()._submit_order_unlocked(
                asset,
                quantity,
                side=side,
                order_type=order_type,
                limit_price=limit_price,
                stop_price=stop_price,
                **kwargs,
            )
        except AcceptedOrderPersistenceError as exc:
            # Venue already accepted the order, but persistence confirmation failed.
            # Must NOT be marked rejection; must be preserved as do-not-retry.
            self.record_event(
                "order_accepted_unpersisted",
                asset=asset,
                quantity=quantity,
                error=str(exc)[:200],
                classification="ACCEPTED_BUT_UNPERSISTED_DO_NOT_RETRY",
            )
            raise
        except (RiskLimitError, PermissionError) as exc:
            # Authoritative pre-send rejection where order definitely never executed
            self.record_event(
                "order_submission_rejected",
                asset=asset,
                quantity=quantity,
                error=str(exc)[:200],
                classification="TERMINAL_REJECTION",
            )
            raise
        except (asyncio.CancelledError, Exception, BaseException) as exc:
            # Default all other exceptions (transport, timeouts, post-acceptance validation,
            # or task cancellation) to UNKNOWN_OUTCOME because order may have executed on venue.
            exc_name = type(exc).__name__
            self.record_event(
                "order_submission_unknown",
                asset=asset,
                quantity=quantity,
                error=f"{exc_name}:{str(exc)[:180]}",
                classification="UNKNOWN_OUTCOME",
            )
            raise
