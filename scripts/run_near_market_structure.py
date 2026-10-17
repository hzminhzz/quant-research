#!/usr/bin/env python3
"""Run the single preregistered NEARUSDT 1h market-structure experiment."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.market_structure import build_signals


INPUT = Path("/home/quant/dev/quant/ml4t-data/data/crypto/market/ohlcv_1h/symbol=NEARUSDT/data.parquet")
OUT = ROOT / "run_log/near_market_structure_20261005"
START = datetime(2024, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _metrics(equity: pl.DataFrame, trades: list[dict], period: str, per_side_bps: float) -> dict:
    f = equity.filter(pl.col("timestamp").dt.strftime("%Y").is_in([period] if period != "full" else ["2024", "2025"]))
    if f.is_empty():
        return {"period": period, "n_days": 0, "n_trades": 0}
    vals = f["equity"].to_numpy()
    if period == "2025":
        previous = equity.filter(pl.col("timestamp") < datetime(2025, 1, 1, tzinfo=timezone.utc))
        base_equity = float(previous["equity"][-1]) if previous.height else 1.0
    else:
        base_equity = 1.0
    path = np.r_[base_equity, vals]
    rets = np.diff(path) / path[:-1]
    sharpe = float(np.mean(rets) / np.std(rets, ddof=1) * math.sqrt(365)) if len(rets) > 1 and np.std(rets, ddof=1) > 0 else 0.0
    dd = path / np.maximum.accumulate(path) - 1.0
    trs = [t for t in trades if period == "full" or str(t["entry_time"])[:4] == period]
    pnls = np.array([t["net_return"] for t in trs], dtype=float)
    gross_wins = float(pnls[pnls > 0].sum())
    gross_losses = float(-pnls[pnls < 0].sum())
    return {
        "period": period, "n_days": int(len(f)), "n_trades": int(len(trs)),
        "total_net_return": float(vals[-1] / base_equity - 1.0),
        "annualized_daily_sharpe": sharpe, "max_drawdown": float(dd.min()),
        "win_rate": float((pnls > 0).mean()) if len(pnls) else 0.0,
        "profit_factor": gross_wins / gross_losses if gross_losses else (None if not gross_wins else "inf"),
        "average_trade_return": float(pnls.mean()) if len(pnls) else None,
        "median_trade_return": float(np.median(pnls)) if len(pnls) else None,
        "exposure_fraction": float(f["exposure"].mean()),
        "average_holding_bars": float(np.mean([t["holding_bars"] for t in trs])) if trs else None,
        "cost_bps_per_side": per_side_bps,
    }


def simulate(bars: pl.DataFrame, per_side_bps: float) -> tuple[pl.DataFrame, list[dict]]:
    cost = per_side_bps / 10000.0
    n = bars.height
    ts = bars["timestamp"].to_list()
    opens, closes = bars["open"].to_numpy(), bars["close"].to_numpy()
    entry_signal = bars["entry_signal"].to_numpy()
    signal_invalidation_level = bars["entry_invalidation_level"].to_numpy()
    confirmed_swing_low = bars["confirmed_swing_low"].to_numpy()
    equity = 1.0
    in_pos = False
    entry_i = -1
    entry_px = 0.0
    qty = 0.0
    exit_reason = None
    held = 0
    trades: list[dict] = []
    eq_rows: list[dict] = []
    queued_entry = False
    queued_entry_level = math.nan
    position_invalidation_level = math.nan
    queued_exit = False
    for i in range(n):
        if i and queued_exit and in_pos:
            px = float(opens[i])
            equity = qty * px * (1.0 - cost)
            trades.append({"entry_time": ts[entry_i].isoformat(), "exit_time": ts[i].isoformat(), "entry_index": entry_i,
                           "exit_index": i, "entry_price": entry_px, "exit_price": px,
                           "holding_bars": held, "exit_reason": exit_reason,
                           "net_return": equity / trades[-1]["_equity_before"] if False else 0.0})
            trade = trades[-1]
            # Store per-trade compounding independently from portfolio path.
            trade["net_return"] = (px / entry_px) * (1.0 - cost) ** 2 - 1.0
            trade.pop("_equity_before", None)
            in_pos = False
            qty = 0.0
            queued_exit = False
        if i and queued_entry and not in_pos:
            px = float(opens[i])
            equity *= 1.0 - cost
            qty = equity / px
            entry_i, entry_px, held = i, px, 0
            position_invalidation_level = queued_entry_level
            in_pos = True
            queued_entry = False
            queued_entry_level = math.nan
        if in_pos:
            held += 1
            equity = qty * float(closes[i])
            if np.isfinite(confirmed_swing_low[i]) and confirmed_swing_low[i] < position_invalidation_level:
                queued_exit, exit_reason = True, "structure_invalidation"
            elif held >= 48:
                queued_exit, exit_reason = True, "maximum_holding_time_48_bars"
        if not in_pos and not queued_entry and entry_signal[i] and i < n - 1:
            queued_entry = True
            queued_entry_level = float(signal_invalidation_level[i])
        eq_rows.append({"timestamp": ts[i], "equity": equity, "exposure": float(in_pos)})
    if in_pos:
        px = float(closes[-1])
        equity = qty * px * (1.0 - cost)
        trades.append({"entry_time": ts[entry_i].isoformat(), "exit_time": ts[-1].isoformat(), "entry_index": entry_i,
                       "exit_index": n - 1, "entry_price": entry_px, "exit_price": px, "holding_bars": held,
                       "exit_reason": "end_of_sample_liquidation",
                       "net_return": (px / entry_px) * (1.0 - cost) ** 2 - 1.0})
        eq_rows[-1]["equity"] = equity
        eq_rows[-1]["exposure"] = 0.0
    hourly = pl.DataFrame(eq_rows)
    daily = hourly.group_by_dynamic("timestamp", every="1d", closed="left").agg(
        pl.col("equity").last(), pl.col("exposure").mean()
    ).sort("timestamp")
    return daily, trades


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    raw = pl.read_parquet(INPUT)
    filtered = raw.filter((pl.col("timestamp") >= START) & (pl.col("timestamp") < END)).sort("timestamp")
    # Warm up the causal feature state with earlier observations, then retain only the target period.
    warm = raw.filter(pl.col("timestamp") < END).sort("timestamp")
    with_signals, pivots = build_signals(warm)
    bars = with_signals.filter((pl.col("timestamp") >= START) & (pl.col("timestamp") < END))
    step = pl.duration(hours=1)
    gaps = filtered.select((pl.col("timestamp") - pl.col("timestamp").shift(1)).alias("delta")).filter(pl.col("delta") != step).height
    duplicates = filtered.height - filtered["timestamp"].n_unique()
    if filtered.height and (filtered["timestamp"].min() != START or filtered["timestamp"].max() != END.replace(hour=0) - __import__("datetime").timedelta(hours=1)):
        coverage_warning = "requested interval endpoints are not both present"
    else:
        coverage_warning = None
    # Outcomes are now computed only after the frozen specification was written.
    all_trades = {}
    summaries = {}
    for bps in (10, 20, 30):
        daily, trades = simulate(bars, bps)
        all_trades[str(bps)] = trades
        summaries[str(bps)] = [_metrics(daily, trades, p, bps) for p in ("full", "2024", "2025")]
        if bps == 10:
            daily.write_csv(OUT / "daily_equity_10bps.csv")
    # Event-study returns are close at signal bar to close at the requested future bar.
    sig_idx = np.flatnonzero(bars["entry_signal"].to_numpy())
    closes = bars["close"].to_numpy()
    event = {}
    for h in (5, 10, 20, 40):
        values = np.array([closes[i + h] / closes[i] - 1 for i in sig_idx if i + h < len(closes)], dtype=float)
        event[str(h)] = {
            "n": int(len(values)),
            "mean": float(values.mean()) if len(values) else None,
            "median": float(np.median(values)) if len(values) else None,
            "p_return_gt_0": float((values > 0).mean()) if len(values) else None,
        }
    bh = (float(filtered["close"][-1]) / float(filtered["open"][0]))
    cost = .001
    result = {
        "trial": "single-frozen-rule-10bps-base", "status": "completed", "classification": "EXPLORATORY",
        "approval_status": "NOT_APPROVED", "input": str(INPUT), "input_sha256": hashlib.sha256(INPUT.read_bytes()).hexdigest(),
        "interval": [START.isoformat(), END.isoformat()], "schema": {k: str(v) for k, v in raw.schema.items()},
        "input_rows_total": raw.height, "rows_in_interval": filtered.height,
        "expected_hourly_rows": 17544, "gaps": gaps, "duplicate_timestamps": duplicates,
        "sorted_unique": filtered["timestamp"].is_sorted() and duplicates == 0,
        "coverage_warning": coverage_warning, "signals": int(len(sig_idx)),
        "confirmed_pivots_in_interval": sum(START <= warm["timestamp"][p["confirmation_index"]] < END for p in pivots),
        "buy_and_hold_return_before_costs": bh - 1,
        "buy_and_hold_return_10bps_per_side": bh * (1 - cost) ** 2 - 1,
        "funding_included": False, "funding_note": "Perpetual funding omitted; returns are before funding.",
        "event_study_close_to_close": event, "metrics_by_cost_bps_per_side": summaries,
        "trades_by_cost_bps_per_side": all_trades,
        "limitations": ["10/20/30 bps per-side costs are exploratory all-in placeholders, not historical NEAR execution evidence.",
                        "Funding is omitted.", "One instrument and one two-year period; no inferential significance or robustness claim.",
                        "Annualized Sharpe uses daily close equity returns and sqrt(365)."],
        "next_decisive_question": "Does the sequence retain positive net expectancy with aligned historical funding and venue-specific execution evidence on a separate untouched period?"
    }
    (OUT / "result.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    (OUT / "pivots.json").write_text(json.dumps(pivots, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("rows_in_interval", "gaps", "signals", "buy_and_hold_return_10bps_per_side", "metrics_by_cost_bps_per_side", "event_study_close_to_close")}, indent=2))


if __name__ == "__main__":
    main()
