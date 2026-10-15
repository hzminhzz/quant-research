"""Parallel Matrix Sweep with Volatility & Relative Strength Filters.

Filters Added:
1. Opening Range Volatility Filter: Range >= 1.2 * ATR20 (avoids low-volatility chop days)
2. Relative Strength Conditioning: S&P 500 futures > VWAP for Longs, < VWAP for Shorts

Evaluates all 32 combinations:
- 2 Assets: Germany 40 (DE30/EUR) & Nikkei 225 (JP225/USD)
- 2 Architectures: 1H OR -> 5m Entry vs 15m OR -> 1m Entry
- 2 Directions: Long Only vs Long & Short
- 4 TP Architectures: Breakeven Runner, Fixed 1.5x, Fixed 2.0x, Pure Session Close
- Stop Loss: Full Opening Range Opposite
- Friction: 0.0 bps commission + 2.0 bps slippage per leg (4.0 bps roundtrip)
"""

import json
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import polars as pl
import talib
from ml4t.diagnostic.evaluation.stats import deflated_sharpe_ratio_from_statistics
import ml4t.diagnostic.metrics as diag_metrics


def prepare_spx_vwap() -> pl.DataFrame:
    """Prepare S&P 500 15m dataset with intraday session VWAP."""
    df_spx = pl.read_parquet("data/processed/SPX500_USD_15m_2019_2026.parquet").sort("timestamp")
    df_spx = df_spx.with_columns([
        pl.col("timestamp").dt.date().alias("date"),
        ((pl.col("high") + pl.col("low") + pl.col("close")) / 3.0).alias("tp"),
        pl.when(pl.col("volume") > 0).then(pl.col("volume")).otherwise(1.0).alias("eff_vol")
    ]).with_columns([
        (pl.col("tp") * pl.col("eff_vol")).alias("pv")
    ]).with_columns([
        (pl.col("pv").cum_sum().over("date") / pl.col("eff_vol").cum_sum().over("date")).alias("spx_vwap")
    ])
    return df_spx.select(["timestamp", pl.col("close").alias("spx_close"), "spx_vwap"])


def evaluate_single_config(
    df: pl.DataFrame,
    asset_sym: str,
    open_hour: int,
    or_bars: int,
    entry_cutoff_bars: int,
    max_eval_bars: int,
    direction: str,  # 'long_only' or 'both'
    tp_mode: str,    # 'be_runner', 'fixed_1.5x', 'fixed_2.0x', 'pure_eod'
    use_atr_filter: bool = True,
    use_spx_filter: bool = True,
    slippage_bps: float = 2.0,
    commission_bps: float = 0.0,
) -> Dict[str, Any]:
    friction = 2.0 * (commission_bps + slippage_bps) / 10_000.0  # 4 bps roundtrip
    allow_short = direction == "both"

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
        atr20 = or_df["atr20_bar"].first()

        if or_range is None or or_close is None or or_range <= 0:
            continue

        # Filter 1: Opening Range Volatility Filter: Range >= 1.2 * ATR20
        if use_atr_filter:
            if atr20 is None or np.isnan(atr20) or or_range < 1.2 * atr20:
                continue

        rest_df = session_df.slice(or_bars)
        in_trade = False
        trade_side = 0
        entry_p = 0.0
        sl_p = 0.0
        tp_p = 0.0
        max_bars = min(len(rest_df), max_eval_bars)

        for i in range(max_bars):
            bar = rest_df[i]
            c = bar["close"][0]
            h = bar["high"][0]
            l = bar["low"][0]
            spx_c = bar["spx_close"][0]
            spx_v = bar["spx_vwap"][0]

            if not in_trade:
                if i < entry_cutoff_bars:
                    long_sig = c > or_high and (ema200 is None or c > ema200)
                    short_sig = (c < or_low) and allow_short and (ema200 is None or c < ema200)

                    # Filter 2: S&P 500 VWAP Relative Strength
                    if use_spx_filter:
                        if long_sig and spx_c is not None and spx_v is not None and spx_c <= spx_v:
                            long_sig = False
                        if short_sig and spx_c is not None and spx_v is not None and spx_c >= spx_v:
                            short_sig = False

                    if long_sig:
                        in_trade = True
                        trade_side = 1
                        entry_p = c
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

    gross_gains = sum(t["ret"] for t in trades if t["ret"] > 0)
    gross_losses = abs(sum(t["ret"] for t in trades if t["ret"] < 0))
    pf = (gross_gains / gross_losses) if gross_losses > 0 else (99.0 if gross_gains > 0 else 0.0)

    n_samples = len(rets_arr)
    if n_samples > 10 and np.std(rets_arr) > 1e-8:
        sr_ci = diag_metrics.sharpe_ratio_with_ci(rets_arr, periods_per_year=252, random_state=42)
        sortino = diag_metrics.sortino_ratio(rets_arr, periods_per_year=252)
        sharpe = float(sr_ci["sharpe"])
        sortino_val = float(sortino)
    else:
        sharpe, sortino_val = 0.0, 0.0

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


def run_filtered_sweeps():
    df_spx = prepare_spx_vwap()
    matrix_results = []

    print("\n==================================================================")
    print("RUNNING FILTERED ARCHITECTURE 1: 1-Hour Opening Candle -> 5m Entry")
    print("Filters: Range >= 1.2*ATR20(1h) + S&P 500 VWAP Relative Strength")
    print("==================================================================")

    arch1_setups = [
        ("Germany 40 (DAX)", "DE30_EUR", "data/processed/DE30_EUR_5m_2023_2026.parquet", 7),
        ("Nikkei 225", "JP225_USD", "data/processed/JP225_USD_5m_2023_2026.parquet", 0),
    ]

    for asset_name, sym, fpath, open_h in arch1_setups:
        raw_df = pl.read_parquet(fpath).sort("timestamp")
        # Join SPX
        df = raw_df.join_asof(df_spx, on="timestamp", strategy="backward")

        # Compute 1H bars for rolling 1H ATR20 (shifted by 1 bar for zero lookahead)
        df_1h = df.group_by_dynamic("timestamp", every="1h").agg([
            pl.col("open").first(),
            pl.col("high").max(),
            pl.col("low").min(),
            pl.col("close").last(),
        ]).drop_nulls()

        h_1h = df_1h["high"].to_numpy()
        l_1h = df_1h["low"].to_numpy()
        c_1h = df_1h["close"].to_numpy()
        atr_1h = talib.ATR(h_1h, l_1h, c_1h, timeperiod=20)
        df_1h = df_1h.with_columns(pl.Series("atr20_bar", atr_1h).shift(1))

        df = df.join_asof(df_1h.select(["timestamp", "atr20_bar"]), on="timestamp", strategy="backward")
        df = df.with_columns([
            pl.col("timestamp").dt.date().alias("date"),
            pl.col("timestamp").dt.hour().alias("hour"),
            pl.col("close").ewm_mean(span=200).alias("ema_200"),
        ])

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
                    use_atr_filter=True,
                    use_spx_filter=True,
                    slippage_bps=2.0,
                    commission_bps=0.0,
                )
                res["architecture"] = "1H OR -> 5m Entry"
                matrix_results.append(res)
                print(f"[{res['architecture']}] {asset_name:16s} | Dir: {direction:9s} | TP: {tp_mode:10s} -> Sharpe: {res['sharpe']:+.2f} | Ret: {res['tot_ret_pct']:+6.1f}% | DD: {res['max_dd_pct']:4.1f}% | Win: {res['win_rate_pct']:4.1f}% | N: {res['trades']:3d}")

    print("\n==================================================================")
    print("RUNNING FILTERED ARCHITECTURE 2: 15-Minute Opening Candle -> 1m Entry")
    print("Filters: Range >= 1.2*ATR20(15m) + S&P 500 VWAP Relative Strength")
    print("==================================================================")

    arch2_setups = [
        ("Germany 40 (DAX)", "DE30_EUR", "data/processed/DE30_EUR_1m_2024_2026.parquet", 7),
        ("Nikkei 225", "JP225_USD", "data/processed/JP225_USD_1m_2024_2026.parquet", 0),
    ]

    for asset_name, sym, fpath, open_h in arch2_setups:
        raw_df = pl.read_parquet(fpath).sort("timestamp")
        df = raw_df.join_asof(df_spx, on="timestamp", strategy="backward")

        # Compute 15m bars for rolling 15m ATR20 (shifted by 1 bar for zero lookahead)
        df_15m = df.group_by_dynamic("timestamp", every="15m").agg([
            pl.col("open").first(),
            pl.col("high").max(),
            pl.col("low").min(),
            pl.col("close").last(),
        ]).drop_nulls()

        h_15m = df_15m["high"].to_numpy()
        l_15m = df_15m["low"].to_numpy()
        c_15m = df_15m["close"].to_numpy()
        atr_15m = talib.ATR(h_15m, l_15m, c_15m, timeperiod=20)
        df_15m = df_15m.with_columns(pl.Series("atr20_bar", atr_15m).shift(1))

        df = df.join_asof(df_15m.select(["timestamp", "atr20_bar"]), on="timestamp", strategy="backward")
        df = df.with_columns([
            pl.col("timestamp").dt.date().alias("date"),
            pl.col("timestamp").dt.hour().alias("hour"),
            pl.col("close").ewm_mean(span=200).alias("ema_200"),
        ])

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
                    use_atr_filter=True,
                    use_spx_filter=True,
                    slippage_bps=2.0,
                    commission_bps=0.0,
                )
                res["architecture"] = "15m OR -> 1m Entry"
                matrix_results.append(res)
                print(f"[{res['architecture']}] {asset_name:16s} | Dir: {direction:9s} | TP: {tp_mode:10s} -> Sharpe: {res['sharpe']:+.2f} | Ret: {res['tot_ret_pct']:+6.1f}% | DD: {res['max_dd_pct']:4.1f}% | Win: {res['win_rate_pct']:4.1f}% | N: {res['trades']:3d}")

    # Compute DSR across the 32 filtered runs
    all_sharpes = np.array([r["sharpe"] for r in matrix_results])
    n_trials = len(matrix_results)
    var_trials = float(np.var(all_sharpes)) if len(all_sharpes) > 0 else 0.20

    for r in matrix_results:
        dsr = deflated_sharpe_ratio_from_statistics(
            observed_sharpe=float(r["sharpe"]),
            n_samples=773,
            n_trials=n_trials,
            variance_trials=var_trials,
        )
        r["dsr_prob"] = float(dsr.probability) * 100.0
        r["dsr_haircut"] = float(dsr.deflated_sharpe)

    out_json = Path("run_log/orb_filtered_matrix.json")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    with out_json.open("w", encoding="utf-8") as f:
        json.dump(matrix_results, f, indent=2)
    print(f"\nSaved filtered matrix results to {out_json}")


if __name__ == "__main__":
    run_filtered_sweeps()
