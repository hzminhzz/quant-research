"""Parallel Matrix Sweep: Opening Candle Breakout on DAX and Nikkei.

Evaluates 32 configurations:
- 2 Assets: Germany 40 (DE30/EUR) & Nikkei 225 (JP225/USD)
- 2 Execution Architectures: 1H OR -> 5m Entry vs 15m OR -> 1m Entry
- 2 Directions: Long Only vs Long & Short
- 4 TP Architectures: Breakeven Runner, Fixed 1.5x, Fixed 2.0x, Pure Session Close
- SL: Full Opening Range Opposite
- Friction: Commission = 0.0 bps, Slippage = 2.0 bps per leg (4.0 bps roundtrip)
"""

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Dict, List

from ml4t.diagnostic.evaluation.stats import deflated_sharpe_ratio_from_statistics
import ml4t.diagnostic.metrics as diag_metrics
import numpy as np
import polars as pl


def evaluate_single_config(
    df: pl.DataFrame,
    asset_sym: str,
    open_hour: int,
    or_bars: int,
    entry_cutoff_bars: int,
    max_eval_bars: int,
    direction: str,  # 'long_only' or 'both'
    tp_mode: str,    # 'be_runner', 'fixed_1.5x', 'fixed_2.0x', 'pure_eod'
    slippage_bps: float = 2.0,
    commission_bps: float = 0.0,
    min_range_pct: float = 0.15,
) -> Dict[str, Any]:
    friction = 2.0 * (commission_bps + slippage_bps) / 10_000.0  # 4 bps roundtrip
    allow_short = direction == "both"

    df = df.with_columns([
        pl.col("timestamp").dt.date().alias("date"),
        pl.col("timestamp").dt.hour().alias("hour"),
        pl.col("close").ewm_mean(span=200).alias("ema_200"),
    ]).sort("timestamp")

    dates = df["date"].unique().sort().to_list()
    daily_pnl = {d: 0.0 for d in dates}
    trades = []

    for d in dates:
        day_df = df.filter(pl.col("date") == d)
        session_df = day_df.filter(pl.col("hour") >= open_hour)
        if len(session_df) < or_bars + 4:
            continue

        or_df = session_df.slice(0, or_bars)
        or_high = or_df["high"].max()
        or_low = or_df["low"].min()
        or_close = or_df["close"].last()
        or_range = or_high - or_low
        ema200 = or_df["ema_200"].last()

        if or_range is None or or_close is None or or_range <= 0:
            continue
        if (or_range / or_close) * 100.0 < min_range_pct:
            continue

        rest_df = session_df.slice(or_bars)
        in_trade = False
        trade_side = 0
        entry_p = 0.0
        entry_idx = 0
        sl_p = 0.0
        tp_p = 0.0
        max_bars = min(len(rest_df), max_eval_bars)

        for i in range(max_bars):
            bar = rest_df[i]
            c = bar["close"][0]
            h = bar["high"][0]
            l = bar["low"][0]

            if not in_trade:
                if i < entry_cutoff_bars:
                    long_sig = c > or_high and (ema200 is None or c > ema200)
                    short_sig = (c < or_low) and allow_short and (ema200 is None or c < ema200)

                    if long_sig:
                        in_trade = True
                        trade_side = 1
                        entry_p = c
                        entry_idx = i
                        sl_p = or_low
                        if tp_mode == "fixed_1.5x":
                            tp_p = entry_p + 1.5 * or_range
                        elif tp_mode == "fixed_2.0x":
                            tp_p = entry_p + 2.0 * or_range
                        else:
                            tp_p = 999999.0
                    elif short_sig:
                        in_trade = True
                        trade_side = -1
                        entry_p = c
                        entry_idx = i
                        sl_p = or_high
                        if tp_mode == "fixed_1.5x":
                            tp_p = entry_p - 1.5 * or_range
                        elif tp_mode == "fixed_2.0x":
                            tp_p = entry_p - 2.0 * or_range
                        else:
                            tp_p = -999999.0
            else:
                if trade_side == 1:
                    if tp_mode == "be_runner" and h >= entry_p + 1.0 * or_range:
                        sl_p = max(sl_p, entry_p)

                    hit_tp = h >= tp_p
                    hit_sl = l <= sl_p

                    if hit_tp and hit_sl:
                        ret = (sl_p - entry_p) / entry_p - friction
                        trades.append({"ret": ret, "reason": "SL_CONFLICT"})
                        daily_pnl[d] += ret
                        break
                    elif hit_tp:
                        ret = (tp_p - entry_p) / entry_p - friction
                        trades.append({"ret": ret, "reason": "TP"})
                        daily_pnl[d] += ret
                        break
                    elif hit_sl:
                        ret = (sl_p - entry_p) / entry_p - friction
                        trades.append({"ret": ret, "reason": "SL"})
                        daily_pnl[d] += ret
                        break
                    elif i == max_bars - 1:
                        ret = (c - entry_p) / entry_p - friction
                        trades.append({"ret": ret, "reason": "EOD"})
                        daily_pnl[d] += ret
                        break
                elif trade_side == -1:
                    if tp_mode == "be_runner" and l <= entry_p - 1.0 * or_range:
                        sl_p = min(sl_p, entry_p)

                    hit_tp = l <= tp_p
                    hit_sl = h >= sl_p

                    if hit_tp and hit_sl:
                        ret = (entry_p - sl_p) / entry_p - friction
                        trades.append({"ret": ret, "reason": "SL_CONFLICT"})
                        daily_pnl[d] += ret
                        break
                    elif hit_tp:
                        ret = (entry_p - tp_p) / entry_p - friction
                        trades.append({"ret": ret, "reason": "TP"})
                        daily_pnl[d] += ret
                        break
                    elif hit_sl:
                        ret = (entry_p - sl_p) / entry_p - friction
                        trades.append({"ret": ret, "reason": "SL"})
                        daily_pnl[d] += ret
                        break
                    elif i == max_bars - 1:
                        ret = (entry_p - c) / entry_p - friction
                        trades.append({"ret": ret, "reason": "EOD"})
                        daily_pnl[d] += ret
                        break

    dates_list = sorted(daily_pnl.keys())
    rets_arr = np.array([daily_pnl[d] for d in dates_list])
    cum_equity = 100_000.0 * np.cumprod(1.0 + rets_arr)

    peaks = np.maximum.accumulate(cum_equity)
    dd_arr = (cum_equity - peaks) / peaks
    max_dd_pct = float(np.min(dd_arr)) * -100.0 if len(dd_arr) > 0 else 0.0

    total_trades = len(trades)
    win_trades = sum(1 for t in trades if t["ret"] > 0)
    win_rate = (win_trades / total_trades * 100.0) if total_trades > 0 else 0.0
    tot_ret_pct = float((cum_equity[-1] / 100_000.0 - 1.0) * 100.0) if len(cum_equity) > 0 else 0.0

    # Profit Factor
    gross_gains = sum(t["ret"] for t in trades if t["ret"] > 0)
    gross_losses = abs(sum(t["ret"] for t in trades if t["ret"] < 0))
    pf = (gross_gains / gross_losses) if gross_losses > 0 else (99.0 if gross_gains > 0 else 0.0)

    n_samples = len(rets_arr)
    if n_samples > 10 and np.std(rets_arr) > 1e-8:
        sr_ci = diag_metrics.sharpe_ratio_with_ci(rets_arr, periods_per_year=252, random_state=42)
        sortino = diag_metrics.sortino_ratio(rets_arr, periods_per_year=252)
        dsr = deflated_sharpe_ratio_from_statistics(
            observed_sharpe=float(sr_ci["sharpe"]),
            n_samples=n_samples,
            n_trials=32,
            variance_trials=0.20,
        )
        sharpe = float(sr_ci["sharpe"])
        sortino_val = float(sortino)
        dsr_prob = float(dsr.probability) * 100.0
        dsr_haircut = float(dsr.deflated_sharpe)
    else:
        sharpe, sortino_val, dsr_prob, dsr_haircut = 0.0, 0.0, 0.0, 0.0

    avg_bps = (np.mean([t["ret"] for t in trades]) * 10_000.0) if trades else 0.0

    tp_count = sum(1 for t in trades if t["reason"] == "TP")
    sl_count = sum(1 for t in trades if "SL" in t["reason"])
    eod_count = sum(1 for t in trades if t["reason"] == "EOD")

    return {
        "asset": asset_sym,
        "direction": direction,
        "tp_mode": tp_mode,
        "sharpe": sharpe,
        "sortino": sortino_val,
        "dsr_prob": dsr_prob,
        "dsr_haircut": dsr_haircut,
        "tot_ret_pct": tot_ret_pct,
        "max_dd_pct": max_dd_pct,
        "win_rate_pct": win_rate,
        "profit_factor": pf,
        "trades": total_trades,
        "avg_trade_bps": avg_bps,
        "tp_count": tp_count,
        "sl_count": sl_count,
        "eod_count": eod_count,
    }


def run_all_sweeps():
    matrix_results = []

    # 1. Architecture 1: 1H OR -> 5m Entry (2023-2026 data)
    print("\n=======================================================")
    print("RUNNING ARCHITECTURE 1: 1-Hour Opening Candle -> 5-Minute Entry")
    print("=======================================================")
    
    arch1_setups = [
        ("Germany 40 (DAX)", "DE30_EUR", "data/processed/DE30_EUR_5m_2023_2026.parquet", 7),
        ("Nikkei 225", "JP225_USD", "data/processed/JP225_USD_5m_2023_2026.parquet", 0),
    ]

    for asset_name, sym, fpath, open_h in arch1_setups:
        df = pl.read_parquet(fpath)
        for direction in ["long_only", "both"]:
            for tp_mode in ["be_runner", "fixed_1.5x", "fixed_2.0x", "pure_eod"]:
                res = evaluate_single_config(
                    df=df,
                    asset_sym=asset_name,
                    open_hour=open_h,
                    or_bars=12,  # 12 bars of 5m = 1H
                    entry_cutoff_bars=12,
                    max_eval_bars=72,
                    direction=direction,
                    tp_mode=tp_mode,
                    slippage_bps=2.0,
                    commission_bps=0.0,
                )
                res["architecture"] = "1H OR -> 5m Entry"
                matrix_results.append(res)
                print(f"[{res['architecture']}] {asset_name} | Dir: {direction:9s} | TP: {tp_mode:10s} -> Sharpe: {res['sharpe']:+.2f} | Ret: {res['tot_ret_pct']:+6.1f}% | DD: {res['max_dd_pct']:4.1f}% | Win: {res['win_rate_pct']:4.1f}% | N: {res['trades']:3d}")

    # 2. Architecture 2: 15m OR -> 1m Entry (2024-2026 data)
    print("\n=======================================================")
    print("RUNNING ARCHITECTURE 2: 15-Minute Opening Candle -> 1-Minute Entry")
    print("=======================================================")
    
    arch2_setups = [
        ("Germany 40 (DAX)", "DE30_EUR", "data/processed/DE30_EUR_1m_2024_2026.parquet", 7),
        ("Nikkei 225", "JP225_USD", "data/processed/JP225_USD_1m_2024_2026.parquet", 0),
    ]

    for asset_name, sym, fpath, open_h in arch2_setups:
        df = pl.read_parquet(fpath)
        for direction in ["long_only", "both"]:
            for tp_mode in ["be_runner", "fixed_1.5x", "fixed_2.0x", "pure_eod"]:
                res = evaluate_single_config(
                    df=df,
                    asset_sym=asset_name,
                    open_hour=open_h,
                    or_bars=15,  # 15 bars of 1m = 15m
                    entry_cutoff_bars=30,
                    max_eval_bars=360,
                    direction=direction,
                    tp_mode=tp_mode,
                    slippage_bps=2.0,
                    commission_bps=0.0,
                )
                res["architecture"] = "15m OR -> 1m Entry"
                matrix_results.append(res)
                print(f"[{res['architecture']}] {asset_name} | Dir: {direction:9s} | TP: {tp_mode:10s} -> Sharpe: {res['sharpe']:+.2f} | Ret: {res['tot_ret_pct']:+6.1f}% | DD: {res['max_dd_pct']:4.1f}% | Win: {res['win_rate_pct']:4.1f}% | N: {res['trades']:3d}")

    # Save to run_log
    out_json = Path("run_log/orb_parallel_matrix.json")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    with out_json.open("w", encoding="utf-8") as f:
        json.dump(matrix_results, f, indent=2)
    print(f"\nSaved full matrix results to {out_json}")


if __name__ == "__main__":
    run_all_sweeps()
