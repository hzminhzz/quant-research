"""Six development-only Milkman CFD adapters to the native ML4T broker.

All PnL/positions/cash/fills belong to ml4t.backtest.Engine. Intra-bar order
priority on 1m/5m/daily OHLC cannot reproduce tick futures/option executions.
These state machines cannot be described as source-equivalent replications.
"""
from __future__ import annotations

import math
from zoneinfo import ZoneInfo

from ml4t.backtest import OrderType, Strategy

ET = ZoneInfo("America/New_York")


def positive(value: object) -> bool:
    try:
        return math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False


class CFDStrategy(Strategy):
    def __init__(self, asset: str, *, capital_fraction: float = .10):
        self.asset = asset
        self.capital_fraction = capital_fraction
        self.decisions = 0

    def qty(self, broker, close: float) -> float:
        return max(0.0, float(broker.equity()) * self.capital_fraction / close)

    def position(self, broker) -> float:
        p = broker.get_position(self.asset)
        return float(p.quantity) if p else 0.0

    def submit(self, broker, qty: float, *, order_type=OrderType.MARKET,
               limit_price=None, stop_price=None):
        if not qty:
            return None
        o = broker.submit_order(self.asset, qty, order_type=order_type,
                                limit_price=limit_price, stop_price=stop_price)
        if o is not None:
            self.decisions += 1
        return o


class MorningDipLimit(CFDStrategy):
    """Native LIMIT entry; 1m completed-bar stop-first exit, no 1s fill claims."""
    def __init__(self, asset):
        super().__init__(asset)
        self.pending = None
        self.armed_at = None
        self.filled_at = None
        self.target = self.stop = None

    def cancel(self, broker):
        if self.pending is not None:
            o = broker.get_order(self.pending)
            if o is not None:
                broker.cancel_order(self.pending)
            self.pending = None

    def on_data(self, timestamp, data, context, broker):
        b = data.get(self.asset)
        if not b:
            return
        s = b.get("signals") or {}
        et = timestamp.astimezone(ET)
        q = self.position(broker)
        if q > 0:
            if self.filled_at is None:
                self.filled_at = timestamp
                self.pending = None
            elapsed = (timestamp - self.filled_at).total_seconds() / 60
            # Entry price may gap relative to resting limit. Levels are the
            # author's immutable signal levels; exit at NEXT 1m open.
            if (float(b["low"]) <= self.stop or float(b["high"]) >= self.target or
                    elapsed >= 15 or et.hour >= 12):
                # Stop-first only determines reason; native market order executes.
                self.submit(broker, -q)
                self.filled_at = None
                self.target = self.stop = None
            return
        if (self.pending is not None and self.armed_at is not None and (
            (timestamp - self.armed_at).total_seconds() >= 9 * 60 or et.hour >= 12
        )):
            self.cancel(broker)
        if self.pending is None and positive(s.get("entry_limit")) and (
                et.weekday() < 5 and 10 <= et.hour < 12):
            limit = float(s["entry_limit"])
            if limit >= float(b["close"]):
                return
            o = self.submit(broker, self.qty(broker, float(b["close"])),
                            order_type=OrderType.LIMIT, limit_price=limit)
            if o:
                self.pending = o.order_id
                self.armed_at = timestamp
                self.target = float(s["entry_target"])
                self.stop = float(s["entry_stop"])


class BuyDayOvernight(CFDStrategy):
    """Globex session-day setup; native next available minute fills."""
    def on_data(self, timestamp, data, context, broker):
        b = data.get(self.asset)
        if not b:
            return
        s = b.get("signals") or {}
        q = self.position(broker)
        if q > 0:
            if bool(s.get("exit_at_0930")):
                self.submit(broker, -q)
        elif bool(s.get("entry_at_reopen")):
            self.submit(broker, self.qty(broker, float(b["close"])))


class EmaNextDayReversion(CFDStrategy):
    """Next-open direction observable only after 09:30 minute; ~1m entry lag."""
    def __init__(self, asset):
        super().__init__(asset)
        self.entry_date = None
        self.in_flight = False

    def on_data(self, timestamp, data, context, broker):
        b = data.get(self.asset)
        if not b:
            return
        s = b.get("signals") or {}
        et = timestamp.astimezone(ET)
        q = self.position(broker)
        if q != 0:
            self.in_flight = False
            ema = s.get("prior_completed_ema")
            # Exit triggered only by observed completed minute close.
            hit = positive(ema) and (
                (q > 0 and float(b["close"]) >= float(ema))
                or (q < 0 and float(b["close"]) <= float(ema))
            )
            if hit or (et.hour, et.minute) >= (15, 59):
                self.submit(broker, -q)
            return
        if et.weekday() >= 5 or (et.hour, et.minute) != (9, 31):
            return
        if not bool(s.get("prior_setup")) or not positive(s.get("prior_completed_ema")):
            return
        if self.entry_date == et.date():
            return
        ref = float(s["prior_completed_ema"])
        opening_price = float(b["open"])
        side = 1 if opening_price < ref else -1 if opening_price > ref else 0
        if side:
            self.submit(broker, side * self.qty(broker, float(b["close"])))
            self.entry_date = et.date()


class HourlyBilboUnderlying(CFDStrategy):
    """5-minute close-exit index adaptation; no option premium PnL."""
    def __init__(self, asset):
        super().__init__(asset)
        self.box_low = self.daily_atr = self.entry_px = None
        self.peak = None
        self.armed = False
        self.days = 0
        self.last_session_date = None

    def on_data(self, timestamp, data, context, broker):
        b = data.get(self.asset)
        if not b:
            return
        s = b.get("signals") or {}
        q = self.position(broker)
        et = timestamp.astimezone(ET)
        if q > 0:
            pos = broker.get_position(self.asset)
            if self.entry_px is None:
                self.entry_px = float(pos.entry_price)
                self.peak = self.entry_px
            if self.last_session_date != et.date():
                self.days += 1
                self.last_session_date = et.date()
            self.peak = max(self.peak, float(b["high"]))
            self.armed = self.armed or self.peak >= self.entry_px + self.daily_atr
            trail = self.entry_px + .25 * (self.peak - self.entry_px)
            if (float(b["close"]) < self.box_low
                    or (self.armed and float(b["close"]) <= trail)
                    or self.days >= 10):
                self.submit(broker, -q)
                self.entry_px = self.peak = None
                self.armed = False
                self.days = 0
            return
        if bool(s.get("entry_signal")) and positive(s.get("box_low")) and positive(s.get("prior_datr14")):
            self.box_low = float(s["box_low"])
            self.daily_atr = float(s["prior_datr14"])
            self.last_session_date = et.date()
            self.days = 0
            self.submit(broker, self.qty(broker, float(b["close"])))


class SwingGateShort(CFDStrategy):
    """Monthly rails, native resting stop on completed daily gate-open."""
    def __init__(self, asset):
        super().__init__(asset)
        self.month = None
        self.entry_order = None
        self.target = self.stop = None
        self.entry_sent = False

    def on_data(self, timestamp, data, context, broker):
        b = data.get(self.asset)
        if not b:
            return
        s = b.get("signals") or {}
        month = timestamp.astimezone(ET).strftime("%Y-%m")
        q = self.position(broker)
        if month != self.month:
            if self.entry_order:
                broker.cancel_order(self.entry_order)
            self.entry_order = None
            self.entry_sent = False
            self.month = month
        if q < 0:
            self.entry_order = None
            if float(b["high"]) >= self.stop or float(b["low"]) <= self.target:
                self.submit(broker, -q)
            elif bool(s.get("last_month_session")):
                # Scheduled month-end liquidation is calendar-known in advance.
                # Native MOC executes at the closing auction, not next day open.
                self.submit(broker, -q, order_type=OrderType.MOC)
            return
        if self.entry_sent or not positive(s.get("down_gate_open")):
            return
        if (bool(s.get("prev_close_above_ema21"))
                and float(b["low"]) <= float(s["down_gate_open"])):
            self.target = float(s["short_target"])
            self.stop = float(s["short_stop"])
            stop_price = float(s["down_gate_complete"])
            if stop_price >= float(b["close"]):
                # Break already past stop: cannot assume a retrospective fill.
                return
            o = self.submit(broker, -self.qty(broker, float(b["close"])),
                            order_type=OrderType.STOP, stop_price=stop_price)
            if o is not None:
                self.entry_order = o.order_id
                self.entry_sent = True


class DailyBoxCloseConfirmed(CFDStrategy):
    """Price-only close-confirmed variant, NOT original resting-stop entry."""
    def __init__(self, asset):
        super().__init__(asset)
        self.box_stop = None

    def on_data(self, timestamp, data, context, broker):
        b = data.get(self.asset)
        if not b:
            return
        s = b.get("signals") or {}
        q = self.position(broker)
        if q > 0:
            previous_ema50 = s.get("prior_ema50")
            if positive(previous_ema50):
                self.box_stop = max(self.box_stop, float(previous_ema50))
            if float(b["low"]) <= self.box_stop:
                self.submit(broker, -q)
            return
        if bool(s.get("box_close_break")) and positive(s.get("box_low")):
            self.box_stop = float(s["box_low"])
            self.submit(broker, self.qty(broker, float(b["close"])))
