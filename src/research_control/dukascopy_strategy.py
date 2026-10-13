"""Historical B1/B2/B3 state machine copied verbatim from frozen Phase4 source.

Only the 15:14 Chicago exit is source-specific. Native order execution remains
in ml4t-backtest; stop is submitted before target. NOT live CFD approval.
"""
from __future__ import annotations

import math
from collections import Counter
from datetime import timedelta
from zoneinfo import ZoneInfo

from ml4t.backtest import OrderType, Strategy

SYM = "DUK_USATECH"
TICK = 0.25

def high_tick(v:float)->float:
    return math.ceil((v-1e-9)/TICK)*TICK


def low_tick(v:float)->float:
    return math.floor((v+1e-9)/TICK)*TICK


def order_status(order)->str:
    return order.status.value if order is not None else "missing"


class VwapPullback(Strategy):
    """State transitions evaluated on completed minute t; native fills at t+1 open."""

    def __init__(self, mode:str):
        self.mode=mode
        self.day=None
        self.state="IDLE"
        self.armed_at=None
        self.pending=None
        self.active=False
        self.tp_order=None
        self.sl_order=None
        self.metrics=Counter()
        self.signal_log=[]
        self.fill_windows=[]

    def cancel_children(self,broker):
        for order in [self.tp_order,self.sl_order]:
            if order is not None and order_status(order)=="pending":
                broker.cancel_order(order.order_id)
        self.tp_order=None
        self.sl_order=None

    def signal(self, timestamp, bar, broker):
        tp=high_tick(float(bar["signals"]["next_tp"]))
        sl=low_tick(float(bar["signals"]["next_sl"]))
        if not (tp>sl>0):
            self.metrics["bad_entry_levels"]+=1
            return
        # Submit entry first. Submit protective STOP ahead of LIMIT, making
        # stop-first queue ordering on an OHLC-both-hit bar when EXIT_FIRST
        # processes eligible native orders in submission order.
        entry=broker.submit_order(SYM,1,order_type=OrderType.MARKET)
        if entry is None or order_status(entry)!="pending":
            self.metrics["entry_submit_failure"]+=1
            return
        stop=broker.submit_order(SYM,-1,order_type=OrderType.STOP,stop_price=sl)
        take=broker.submit_order(SYM,-1,order_type=OrderType.LIMIT,limit_price=tp)
        if stop is None or take is None or order_status(stop)!="pending" or order_status(take)!="pending":
            self.metrics["child_submit_failure"]+=1
            for order in (stop,take,entry):
                if order is not None and order_status(order)=="pending":
                    broker.cancel_order(order.order_id)
            return
        # The parent property is descriptive; ml4t-backtest v0.1.7 is not
        # an atomic broker OCO engine. Engine results must be audited.
        stop.parent_id=entry.order_id
        take.parent_id=entry.order_id
        self.sl_order=stop
        self.tp_order=take
        self.pending=entry
        self.state="CONSUMED"
        self.signal_log.append({
            "mode":self.mode,"signal_at":timestamp.isoformat(),
            "expected_entry_at":(timestamp+timedelta(minutes=1)).isoformat(),
            "take_profit":tp,"stop_loss":sl,
            "adx":float(bar["signals"]["adx"]),
            "adx_prev":float(bar["signals"]["prior_adx"]),
            "vwap":float(bar["signals"]["vwap"]),
            "decision_close":float(bar["close"]),
        })
        self.metrics["signals"]+=1

    def on_data(self,timestamp,data,context,broker):
        bar=data[SYM]
        local=timestamp.astimezone(__import__("zoneinfo").ZoneInfo("America/Chicago"))
        day=local.date()
        clock=local.strftime("%H:%M")
        if self.day!=day:
            if self.day is not None and (self.pending is not None or broker.get_position(SYM)):
                raise RuntimeError("Overnight inventory or entry remained pending")
            self.cancel_children(broker)
            self.day=day
            self.state="IDLE"
            self.armed_at=None
            self.active=False
        pos=broker.get_position(SYM)
        qty=float(pos.quantity) if pos else 0
        if qty<0 or qty>1:
            raise RuntimeError(f"Reversal/overfill: {qty} at {timestamp}")
        # If our pending entry filled, it can also exit on the same entry bar.
        if self.pending is not None:
            entry_status=order_status(self.pending)
            if entry_status=="filled":
                self.pending=None
                self.metrics["filled_entries"]+=1
                if qty==0:
                    self.cancel_children(broker)
                    self.active=False
                    self.state="IDLE"
                    self.metrics["entry_bar_exits"]+=1
                    return
                self.active=True
            elif entry_status in ("cancelled","rejected"):
                self.cancel_children(broker)
                self.pending=None
                self.state="IDLE"
                self.metrics["rejected_entry"]+=1
                return
            else:
                # Entry is submitted at t close. It must fill at t+1 open.
                return
        if self.active and qty==0:
            self.cancel_children(broker)
            self.active=False
            self.state="IDLE"
            self.armed_at=None
            self.metrics["closed_trades"]+=1
            # Never re-arm based on the ambiguous bar that just exited.
            return
        if clock=="15:54":
            if qty:
                self.cancel_children(broker)
                exit_order=broker.submit_order(SYM,-1,order_type=OrderType.MARKET)
                if exit_order is None:
                    raise RuntimeError("Failed to queue 15:55 market flat")
                self.metrics["hard_exits_queued"]+=1
            return
        if clock>="15:55":
            if qty:
                self.metrics["late_inventory"]+=1
                raise RuntimeError("Not flat at 15:55 CT")
            self.cancel_children(broker)
            return
        if qty or self.active:
            return
        if clock<"09:00" or clock>="15:54":
            return
        signal=bar.get("signals",{})
        if (not signal or signal.get("or_high") is None
            or signal.get("next_tp") is None or signal.get("next_sl") is None
            or signal.get("vwap") is None or signal.get("adx") is None
            or signal.get("prior_adx") is None or signal.get("prior_close") is None):
            return
        close=float(bar["close"])
        high=float(bar["high"])
        low=float(bar["low"])
        or_high=float(signal["or_high"])
        vwap=float(signal["vwap"])
        adx=float(signal["adx"])
        prev_adx=float(signal["prior_adx"])
        if self.state=="IDLE":
            if float(signal["prior_close"])<=or_high and high>or_high and close>or_high:
                self.metrics["g1_breakouts"]+=1
                if self.mode=="B1":
                    self.signal(timestamp,bar,broker)
                else:
                    self.state="ARMED"
                    self.armed_at=timestamp
            return
        if self.state=="ARMED":
            if timestamp<=self.armed_at:
                return
            if low<=vwap:
                self.state="TOUCHED"
                self.metrics["g2_touches"]+=1
            else:
                return
        if self.state=="RETOUCH":
            if low<=vwap:
                self.state="TOUCHED"
                self.metrics["g2_touches"]+=1
            else:
                return
        if self.state=="TOUCHED":
            if close<=vwap:
                return
            self.metrics["g3_reclaims"]+=1
            if self.mode=="B2":
                self.signal(timestamp,bar,broker)
            elif adx>20 and adx<=prev_adx:
                self.metrics["g4_adx"]+=1
                self.signal(timestamp,bar,broker)
            elif adx>20:
                self.state="WAIT_ADX"
                self.metrics["wait_adx"]+=1
            else:
                self.state="RETOUCH"
            return
        if self.state=="WAIT_ADX":
            if close<=vwap:
                self.state="TOUCHED"
            elif adx<=20:
                self.state="RETOUCH"
            elif adx<=prev_adx:
                self.metrics["g4_adx"]+=1
                self.signal(timestamp,bar,broker)

    def on_end(self,broker):
        pos=broker.get_position(SYM)
        if pos and pos.quantity:
            raise RuntimeError("Native backtest ended with open inventory")




class DukascopyClockStrategy(VwapPullback):
    """The vendor has a real 15:14 bar open, not a 15:55 futures bar."""

    def on_data(self, timestamp, data, context, broker):
        clock = timestamp.astimezone(ZoneInfo("America/Chicago")).strftime("%H:%M")
        if clock == "15:13":
            if self.pending is not None:
                state = order_status(self.pending)
                if state == "pending":
                    raise RuntimeError("unfilled order at CFD forced close")
                if state == "filled":
                    self.metrics["filled_entries"] += 1
                self.pending = None
            self.cancel_children(broker)
            position = broker.get_position(SYM)
            if position and position.quantity:
                order = broker.submit_order(
                    SYM, -int(position.quantity), order_type=OrderType.MARKET
                )
                if order is None:
                    raise RuntimeError("CFD 15:14 liquidation order rejected")
                self.metrics["cfd_close_1514_queued"] += 1
            self.state = "CONSUMED"
            return
        if clock == "15:14":
            pos = broker.get_position(SYM)
            if pos and pos.quantity:
                raise RuntimeError("CFD not flat at 15:14 bar open")
            self.cancel_children(broker)
            self.pending = None
            self.active = False
            self.state = "IDLE"
            return
        return super().on_data(timestamp, data, context, broker)
