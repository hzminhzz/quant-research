"""Causal BTCUSDT 1h market-structure reversal baseline.

This module implements the single preregistered trial in
config/btc_structure_reversal_20261006.yaml. It deliberately contains no
parameter search, EMA/VWAP/regime filter, or machine-learning layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Iterable

import numpy as np
import polars as pl


@dataclass(frozen=True)
class Pivot:
    kind: str
    pivot_index: int
    confirmation_index: int
    price: float


def wilder_atr(frame: pl.DataFrame, period: int = 14) -> np.ndarray:
    """Return causal Wilder ATR from OHLC bars."""
    if frame.height == 0:
        return np.array([], dtype=float)
    high = frame["high"].to_numpy()
    low = frame["low"].to_numpy()
    close = frame["close"].to_numpy()
    out = np.empty(frame.height, dtype=float)
    prev_close = float(close[0])
    for i in range(frame.height):
        tr = max(
            float(high[i] - low[i]),
            abs(float(high[i]) - prev_close),
            abs(float(low[i]) - prev_close),
        )
        out[i] = tr if i == 0 else (out[i - 1] * (period - 1) + tr) / period
        prev_close = float(close[i])
    return out


def detect_fractal_pivots(
    frame: pl.DataFrame,
    *,
    left: int = 2,
    right: int = 2,
) -> list[Pivot]:
    """Detect 2-left/2-right pivots and expose them only after confirmation."""
    if left < 1 or right < 1:
        raise ValueError("left and right must be positive")
    high = frame["high"].to_numpy()
    low = frame["low"].to_numpy()
    pivots: list[Pivot] = []
    for i in range(left, frame.height - right):
        prior_h = high[i - left : i]
        next_h = high[i + 1 : i + right + 1]
        prior_l = low[i - left : i]
        next_l = low[i + 1 : i + right + 1]
        if np.all(high[i] > prior_h) and np.all(high[i] >= next_h):
            pivots.append(Pivot("H", i, i + right, float(high[i])))
        if np.all(low[i] < prior_l) and np.all(low[i] <= next_l):
            pivots.append(Pivot("L", i, i + right, float(low[i])))
    return sorted(pivots, key=lambda p: (p.confirmation_index, p.pivot_index, p.kind))


def first_crossing(
    bearish: np.ndarray,
    close: np.ndarray,
    threshold: np.ndarray,
) -> np.ndarray:
    """Return only true crosses from below/at the prior threshold to above now."""
    out = np.zeros(len(close), dtype=bool)
    for i in range(1, len(close)):
        if (
            bearish[i]
            and bearish[i - 1]
            and np.isfinite(threshold[i])
            and np.isfinite(threshold[i - 1])
            and close[i] > threshold[i]
            and close[i - 1] <= threshold[i - 1]
        ):
            out[i] = True
    return out


def build_signal_frame(
    frame: pl.DataFrame,
    *,
    atr_period: int = 14,
    buffer_atr: float = 0.10,
) -> tuple[pl.DataFrame, list[Pivot]]:
    """Attach causal swing state and the frozen long-entry event."""
    if frame.height < 6:
        raise ValueError("insufficient bars")
    frame = frame.sort("timestamp")
    atr = wilder_atr(frame, atr_period)
    pivots = detect_fractal_pivots(frame)

    bearish = np.zeros(frame.height, dtype=bool)
    latest_high = np.full(frame.height, np.nan, dtype=float)
    latest_low = np.full(frame.height, np.nan, dtype=float)

    by_confirmation: dict[int, list[Pivot]] = {}
    for pivot in pivots:
        by_confirmation.setdefault(pivot.confirmation_index, []).append(pivot)

    highs: list[float] = []
    lows: list[float] = []
    for i in range(frame.height):
        for pivot in by_confirmation.get(i, []):
            if pivot.kind == "H":
                highs.append(pivot.price)
            else:
                lows.append(pivot.price)
        if highs:
            latest_high[i] = highs[-1]
        if lows:
            latest_low[i] = lows[-1]
        bearish[i] = (
            len(highs) >= 2
            and len(lows) >= 2
            and highs[-1] < highs[-2]
            and lows[-1] < lows[-2]
        )

    threshold = latest_high + buffer_atr * atr
    close = frame["close"].to_numpy().astype(float)
    entry = first_crossing(bearish, close, threshold)

    return (
        frame.with_columns(
            pl.Series("atr14", atr),
            pl.Series("bearish_structure", bearish),
            pl.Series("latest_confirmed_swing_high", latest_high),
            pl.Series("latest_confirmed_swing_low", latest_low),
            pl.Series("break_threshold", threshold),
            pl.Series("entry_signal", entry),
        ),
        pivots,
    )


def _funding_by_hour(funding: pl.DataFrame) -> dict[datetime, float]:
    if funding.height == 0:
        return {}
    grouped = (
        funding.sort("timestamp")
        .with_columns(pl.col("timestamp").dt.truncate("1h").alias("_hour"))
        .group_by("_hour")
        .agg(pl.col("funding_rate").sum().alias("funding_rate"))
    )
    return {
        row["_hour"]: float(row["funding_rate"])
        for row in grouped.iter_rows(named=True)
    }


def _daily_sharpe(equity_frame: pl.DataFrame) -> float:
    if equity_frame.height < 48:
        return float("nan")
    daily = (
        equity_frame.with_columns(pl.col("timestamp").dt.date().alias("_date"))
        .group_by("_date")
        .agg(pl.col("equity").last().alias("equity"))
        .sort("_date")
    )
    e = daily["equity"].to_numpy().astype(float)
    if len(e) < 3:
        return float("nan")
    r = e[1:] / e[:-1] - 1.0
    sd = float(np.std(r, ddof=1))
    return float(np.mean(r) / sd * math.sqrt(365.0)) if sd > 0 else float("nan")


def _max_drawdown(equity: np.ndarray) -> float:
    if len(equity) == 0:
        return float("nan")
    peak = np.maximum.accumulate(equity)
    return float(np.min(equity / peak - 1.0))


def _compound(values: Iterable[float]) -> float:
    arr = np.asarray(list(values), dtype=float)
    return float(np.prod(1.0 + arr) - 1.0) if len(arr) else 0.0


def simulate_period(
    signals: pl.DataFrame,
    funding: pl.DataFrame,
    *,
    start: datetime,
    end_exclusive: datetime,
    execution_bps_per_side: float = 5.0,
    target_r: float = 2.0,
    max_holding_bars: int = 120,
) -> tuple[dict[str, object], pl.DataFrame, pl.DataFrame]:
    """Run the frozen next-open, one-position-at-a-time long-only simulation."""
    timestamps = signals["timestamp"].to_list()
    opens = signals["open"].to_numpy().astype(float)
    highs = signals["high"].to_numpy().astype(float)
    lows = signals["low"].to_numpy().astype(float)
    closes = signals["close"].to_numpy().astype(float)
    entries = signals["entry_signal"].to_numpy()
    swing_lows = signals["latest_confirmed_swing_low"].to_numpy().astype(float)

    eval_idx = [i for i, ts in enumerate(timestamps) if start <= ts < end_exclusive]
    if not eval_idx:
        raise ValueError("empty evaluation interval")
    start_i, end_i = eval_idx[0], eval_idx[-1] + 1

    funding_map = _funding_by_hour(
        funding.filter((pl.col("timestamp") >= start) & (pl.col("timestamp") < end_exclusive))
    )
    fee = execution_bps_per_side / 10_000.0

    equity = 1.0
    position: dict[str, object] | None = None
    pending: dict[str, object] | None = None
    trades: list[dict[str, object]] = []
    curve: list[dict[str, object]] = []

    for i in range(start_i, end_i):
        ts = timestamps[i]

        if pending is not None and position is None:
            fill = float(opens[i])
            stop = float(pending["stop"])
            if np.isfinite(stop) and stop < fill:
                risk = fill - stop
                position = {
                    "signal_index": int(pending["signal_index"]),
                    "signal_time": pending["signal_time"],
                    "entry_index": i,
                    "entry_time": ts,
                    "entry_price": fill,
                    "entry_equity": equity,
                    "stop": stop,
                    "target": fill + target_r * risk,
                    "risk": risk,
                    "funding_cost": 0.0,
                }
            pending = None

        exited_this_bar = False
        if position is not None:
            entry_i = int(position["entry_index"])
            entry_price = float(position["entry_price"])
            entry_equity = float(position["entry_equity"])
            stop = float(position["stop"])
            target = float(position["target"])

            # The time exit is known at the bar open, so execute before using
            # this bar's high/low or charging a same-instant funding settlement.
            if i - entry_i >= max_holding_bars:
                exit_price = float(opens[i])
                exit_reason = "time"
            else:
                position["funding_cost"] = float(position["funding_cost"]) + float(
                    funding_map.get(ts, 0.0)
                )
                hit_stop = lows[i] <= stop
                hit_target = highs[i] >= target
                if hit_stop:
                    exit_price = stop
                    exit_reason = "stop"
                elif hit_target:
                    exit_price = target
                    exit_reason = "target"
                else:
                    exit_price = float("nan")
                    exit_reason = ""

            if exit_reason:
                gross = exit_price / entry_price - 1.0
                funding_cost = float(position["funding_cost"])
                execution_cost = 2.0 * fee
                net = gross - execution_cost - funding_cost
                risk_pct = float(position["risk"]) / entry_price
                r_multiple = gross / risk_pct if risk_pct > 0 else float("nan")
                equity = entry_equity * (1.0 + net)
                trades.append(
                    {
                        "signal_time": position["signal_time"],
                        "entry_time": position["entry_time"],
                        "exit_time": ts,
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                        "stop_price": stop,
                        "target_price": target,
                        "exit_reason": exit_reason,
                        "holding_hours": i - entry_i,
                        "gross_return": gross,
                        "execution_cost": execution_cost,
                        "funding_cost": funding_cost,
                        "net_return": net,
                        "r_multiple": r_multiple,
                    }
                )
                position = None
                exited_this_bar = True
            else:
                gross_mark = closes[i] / entry_price - 1.0
                mark_net = gross_mark - fee - float(position["funding_cost"])
                equity = entry_equity * (1.0 + mark_net)

        curve.append({"timestamp": ts, "equity": equity})

        # A close-t signal can only fill at open t+1, and only inside the same
        # evaluation interval. A position that exited intrabar may re-arm here.
        if position is None and pending is None and i + 1 < end_i and bool(entries[i]):
            stop = float(swing_lows[i])
            if np.isfinite(stop):
                pending = {
                    "signal_index": i,
                    "signal_time": ts,
                    "stop": stop,
                }

    # Exogenous evaluation boundary: liquidate an open trade at the final
    # completed close. This is not a strategy exit rule.
    if position is not None:
        i = end_i - 1
        ts = timestamps[i]
        entry_price = float(position["entry_price"])
        entry_equity = float(position["entry_equity"])
        exit_price = float(closes[i])
        gross = exit_price / entry_price - 1.0
        funding_cost = float(position["funding_cost"])
        execution_cost = 2.0 * fee
        net = gross - execution_cost - funding_cost
        risk_pct = float(position["risk"]) / entry_price
        trades.append(
            {
                "signal_time": position["signal_time"],
                "entry_time": position["entry_time"],
                "exit_time": ts,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "stop_price": float(position["stop"]),
                "target_price": float(position["target"]),
                "exit_reason": "period_end",
                "holding_hours": i - int(position["entry_index"]) + 1,
                "gross_return": gross,
                "execution_cost": execution_cost,
                "funding_cost": funding_cost,
                "net_return": net,
                "r_multiple": gross / risk_pct if risk_pct > 0 else float("nan"),
            }
        )
        equity = entry_equity * (1.0 + net)
        curve[-1]["equity"] = equity

    trade_frame = pl.DataFrame(trades) if trades else pl.DataFrame(
        schema={
            "signal_time": pl.Datetime("ms", "UTC"),
            "entry_time": pl.Datetime("ms", "UTC"),
            "exit_time": pl.Datetime("ms", "UTC"),
            "entry_price": pl.Float64,
            "exit_price": pl.Float64,
            "stop_price": pl.Float64,
            "target_price": pl.Float64,
            "exit_reason": pl.String,
            "holding_hours": pl.Int64,
            "gross_return": pl.Float64,
            "execution_cost": pl.Float64,
            "funding_cost": pl.Float64,
            "net_return": pl.Float64,
            "r_multiple": pl.Float64,
        }
    )
    equity_frame = pl.DataFrame(curve)

    gross_returns = trade_frame["gross_return"].to_list() if trade_frame.height else []
    net_returns = trade_frame["net_return"].to_list() if trade_frame.height else []
    wins = [x > 0 for x in net_returns]
    pos = sum(x for x in net_returns if x > 0)
    neg = -sum(x for x in net_returns if x < 0)
    pf = float(pos / neg) if neg > 0 else (float("inf") if pos > 0 else float("nan"))

    period_prices = signals.slice(start_i, end_i - start_i)
    buy_hold = float(period_prices["close"][-1] / period_prices["open"][0] - 1.0)

    eq_arr = equity_frame["equity"].to_numpy().astype(float)
    metrics: dict[str, object] = {
        "start": start.isoformat(),
        "end_exclusive": end_exclusive.isoformat(),
        "trades": trade_frame.height,
        "win_rate": float(np.mean(wins)) if wins else float("nan"),
        "gross_return": _compound(gross_returns),
        "net_return": float(eq_arr[-1] - 1.0) if len(eq_arr) else 0.0,
        "mean_trade_r": float(np.mean(trade_frame["r_multiple"].to_numpy()))
        if trade_frame.height
        else float("nan"),
        "profit_factor_net": pf,
        "max_drawdown": _max_drawdown(eq_arr),
        "daily_sharpe": _daily_sharpe(equity_frame),
        "average_holding_hours": float(np.mean(trade_frame["holding_hours"].to_numpy()))
        if trade_frame.height
        else float("nan"),
        "funding_cost_sum": float(sum(trade_frame["funding_cost"].to_list()))
        if trade_frame.height
        else 0.0,
        "execution_cost_sum": float(sum(trade_frame["execution_cost"].to_list()))
        if trade_frame.height
        else 0.0,
        "buy_and_hold_return": buy_hold,
        "entry_signals_in_period": int(np.sum(entries[start_i:end_i])),
    }
    return metrics, trade_frame, equity_frame
