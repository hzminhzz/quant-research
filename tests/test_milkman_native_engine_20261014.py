"""Focused native Engine integration checks for approved Milkman CFD adapters.

Uses synthetic market events and the real installed ML4T Engine/Broker, never
a custom fill simulator. Separate from feature checks and real-data MVP.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
from ml4t.backtest import DataFeed, Engine

from scripts.run_milkman_native_cfd_20261014 import config
from src.strategies.milkman_native_broker import BuyDayOvernight, SwingGateShort


def feed(rows: list[tuple], signals: list[dict], symbol: str = "ES") -> DataFeed:
    prices = pl.DataFrame({
        "timestamp": [r[0] for r in rows],
        "open": [float(r[1]) for r in rows],
        "high": [float(r[2]) for r in rows],
        "low": [float(r[3]) for r in rows],
        "close": [float(r[4]) for r in rows],
        "volume": [1000.0 for _ in rows],
        "asset": [symbol for _ in rows],
    })
    sig = pl.DataFrame([
        {"timestamp": row[0], "asset": symbol, **s}
        for row, s in zip(rows, signals)
    ])
    return DataFeed(prices_df=prices, signals_df=sig)


def test_buy_day_uses_real_engine_next_bar_open_fills():
    t = datetime(2022, 1, 3, 22, tzinfo=UTC)
    rows = [
        (t + timedelta(minutes=i), v, v + 1, v - 1, v)
        for i, v in enumerate([100., 103., 105., 102., 101.])
    ]
    flags = [
        {"entry_at_reopen": True, "exit_at_0930": False},
        {"entry_at_reopen": False, "exit_at_0930": False},
        {"entry_at_reopen": False, "exit_at_0930": True},
        {"entry_at_reopen": False, "exit_at_0930": False},
        {"entry_at_reopen": False, "exit_at_0930": False},
    ]
    r = Engine(feed(rows, flags), BuyDayOvernight("ES"), config()).run()
    assert len(r.fills) == 2
    assert r.fills[0].timestamp == rows[1][0]
    assert r.fills[1].timestamp == rows[3][0]
    assert r.fills[0].price > rows[1][1]
    assert r.fills[1].price < rows[3][1]
    assert len(r.trades) == 1


def test_swing_month_end_moc_closes_with_native_broker():
    t = datetime(2022, 1, 27, 22, tzinfo=UTC)
    rows = [
        (t, 102., 105., 99., 102.),
        (t + timedelta(days=1), 100., 103., 97., 100.),
        (t + timedelta(days=4), 100., 101., 99., 100.),
    ]
    flags = [
        {"down_gate_open": 101., "down_gate_complete": 98.,
         "short_target": 90., "short_stop": 110.,
         "prev_close_above_ema21": True, "last_month_session": False},
        {"down_gate_open": 101., "down_gate_complete": 98.,
         "short_target": 90., "short_stop": 110.,
         "prev_close_above_ema21": True, "last_month_session": True},
        {"down_gate_open": 101., "down_gate_complete": 98.,
         "short_target": 90., "short_stop": 110.,
         "prev_close_above_ema21": False, "last_month_session": False},
    ]
    r = Engine(feed(rows, flags), SwingGateShort("ES"), config()).run()
    assert len(r.fills) == 2
    assert r.fills[0].order_type == "stop"
    assert r.fills[1].order_type == "moc"
    assert len([x for x in r.trades if x.status == "closed"]) == 1
