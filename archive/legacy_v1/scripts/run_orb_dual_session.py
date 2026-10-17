"""Dual-Session Opening Candle Breakout on Germany 40 and Nikkei 225.

Evaluates:
- Session 1: Morning Cash Open (07:00 UTC for DAX, 00:00 UTC for Nikkei)
- Session 2: US Overlap / Afternoon (13:00 UTC for DAX, 03:00 UTC for Nikkei)
- Dual-Session: Combined portfolio trading both institutional liquidity windows
- All 4 Take-Profit Architectures (Breakeven Runner, Fixed 1.5x, Fixed 2.0x, Pure Session Close)
- Friction: 0.0 bps commission + 2.0 bps slippage per leg (4.0 bps roundtrip)
"""

import json
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import polars as pl
import talib
from ml4t.diagnostic.evaluation.stats import deflated_sharpe_ratio_from_statistics


def prepare_spx_vwap() -> pl.DataFrame:
    df_spx = pl.read_parquet("data/processed/SPX500_USD_15m_2019_2026.parquet").sort("timestamp")
    df_spx = df_spx.with_columns([
        pl.col("timestamp").dt.date().alias("date"),
        ((pl.col("high") + pl.col("low") + pl.col("close")) / 3.0).alias("tp"),
        pl.when(pl.col("volume") > 0).then(pl.col("volume")).otherwise(1.0).alias("eff_vol"),
    ]).with_columns([
        (pl.col("tp") * pl.col("eff_vol")).alias("pv")
    ]).with_columns([
        (pl.col("pv").cum_sum().over("date") / pl.col("eff_vol").cum_sum().over("date")).alias("spx_vwap")
    ])
    return df_spx.select(["timestamp", pl.col("close").alias("spx_close"), "spx_vwap"])


def run_session_backtest(
    df: pl.DataFrame,
    asset_name: str,
    session_hours: List[int],
    session_label: str,
    tp_mode: str = "fixed_2.0x",
    max_hold_bars: int = 36,
    slippage_bps: float = 2.0,
    commission_bps: float = 0.0,
) -> Dict[str, Any]:
    friction = 2.0 * (commission_bps + slippage_bps) / 10_000.0  # 4 bps roundtrip
    dates = df["date"].unique().sort().to_list()
    daily_pnl = {d: 0.0 for d in dates}
    all_trades = []

    for d in dates:
        day_df = df.filter(pl.col("date") == d)

        for s_idx, open_h in enumerate(session_hours):
            session_df = day_df.filter((pl.col("hour") >= open_h) & (pl.col("hour") < open_h + 6))
            if len(session_df) < 12 + 4:
                continue

            or_df = session_df.slice(0, 12)
            or_h = or_df["high"].max()
            or_l = or_df["low"].min()
            or_rng = or_h - or_l
            atr20 = or_df["atr20_bar"].first()
            ema200 = or_df["ema_200"].last()

            if not or_rng or or_rng <= 0:
                continue
            if atr20 and or_rng < 1.2 * atr20:
                continue

            rest_df = session_df.slice(12)
            in_trade = False
            entry_p = 0.0
            sl_p = 0.0
            tp_p = 0.0
            max_bars = min(len(rest_df), max_hold_bars)

            for i in range(max_bars):
                bar = rest_df[i]
                c = bar["close"][0]
                h = bar["high"][0]
                l = bar["low"][0]
                spx_c = bar["spx_close"][0]
                spx_v = bar["spx_vwap"][0]

                if not in_trade:
                    if i < 12:  # 1-hour entry cutoff
                        sig = c > or_h and (ema200 is None or c > ema200)
                        if spx_c is not None and spx_v is not None and spx_c <= spx_v:
                            sig = False

                        if sig:
                            in_trade = True
                            entry_p = c
                            sl_p = or_l
                            if tp_mode == "fixed_1.5x":
                                tp_p = entry_p + 1.5 * or_rng
                            elif tp_mode == "fixed_2.0x":
                                tp_p = entry_p + 2.0 * or_rng
                            else:
                                tp_p = 999999.0
                else:
                    if tp_mode == "be_runner" and h >= entry_p + 1.0 * or_rng:
                        sl_p = max(sl_p, entry_p)

                    hit_tp = h >= tp_p
                    hit_sl = l <= sl_p

                    if hit_tp and hit_sl:
                        ret = (sl_p - entry_p) / entry_p - friction
                        all_trades.append({"ret": ret, "session": f"S{s_idx+1}"})
                        daily_pnl[d] += ret
                        break
                    elif hit_tp:
                        ret = (tp_p - entry_p) / entry_p - friction
                        all_trades.append({"ret": ret, "session": f"S{s_idx+1}"})
                        daily_pnl[d] += ret
                        break
                    elif hit_sl:
                        ret = (sl_p - entry_p) / entry_p - friction
                        all_trades.append({"ret": ret, "session": f"S{s_idx+1}"})
                        daily_pnl[d] += ret
                        break
                    elif i == max_bars - 1:
                        ret = (c - entry_p) / entry_p - friction
                        all_trades.append({"ret": ret, "session": f"S{s_idx+1}"})
                        daily_pnl[d] += ret
                        break

    rets = np.array([daily_pnl[d] for d in sorted(daily_pnl.keys())])
    sr = (np.mean(rets) / np.std(rets) * np.sqrt(252)) if np.std(rets) > 0 else 0
    cum_ret = (np.prod(1.0 + rets) - 1.0) * 100.0
    peaks = np.maximum.accumulate(np.cumprod(1.0 + rets))
    dd = (np.cumprod(1.0 + rets) - peaks) / peaks
    max_dd = float(np.min(dd)) * -100.0 if len(dd) > 0 else 0
    win_rate = (sum(1 for t in all_trades if t["ret"] > 0) / len(all_trades) * 100.0) if all_trades else 0
    avg_bps = np.mean([t["ret"] for t in all_trades]) * 10_000.0 if all_trades else 0
    gross_gains = sum(t["ret"] for t in all_trades if t["ret"] > 0)
    gross_losses = abs(sum(t["ret"] for t in all_trades if t["ret"] < 0))
    pf = (gross_gains / gross_losses) if gross_losses > 0 else 0.0

    return {
        "asset": asset_name,
        "session_mode": session_label,
        "tp_mode": tp_mode,
        "total_trades": len(all_trades),
        "trades_per_year": round(len(all_trades) / 3.0, 1),
        "win_rate_pct": round(win_rate, 1),
        "total_return_pct": round(cum_ret, 2),
        "max_dd_pct": round(max_dd, 2),
        "sharpe": round(float(sr), 3),
        "profit_factor": round(float(pf), 2),
        "avg_trade_bps": round(float(avg_bps), 1),
        "daily_pnl": daily_pnl,
    }


def main():
    df_spx = prepare_spx_vwap()
    results = []

    assets = [
        ("Germany 40 (DAX)", "data/processed/DE30_EUR_5m_2023_2026.parquet", [7], [13], [7, 13]),
        ("Nikkei 225", "data/processed/JP225_USD_5m_2023_2026.parquet", [0], [3], [0, 3]),
    ]

    for asset_name, fpath, s1_hours, s2_hours, dual_hours in assets:
        raw_df = pl.read_parquet(fpath).sort("timestamp")
        df = raw_df.join_asof(df_spx, on="timestamp", strategy="backward")

        df_1h = df.group_by_dynamic("timestamp", every="1h").agg([
            pl.col("open").first(), pl.col("high").max(), pl.col("low").min(), pl.col("close").last()
        ]).drop_nulls()
        atr_1h = talib.ATR(df_1h["high"].to_numpy(), df_1h["low"].to_numpy(), df_1h["close"].to_numpy(), timeperiod=20)
        df_1h = df_1h.with_columns(pl.Series("atr20_bar", atr_1h).shift(1))
        df = df.join_asof(df_1h.select(["timestamp", "atr20_bar"]), on="timestamp", strategy="backward")

        df = df.with_columns([
            pl.col("timestamp").dt.date().alias("date"),
            pl.col("timestamp").dt.hour().alias("hour"),
            pl.col("close").ewm_mean(span=200).alias("ema_200"),
        ])

        session_configs = [
            ("Session 1: Cash Open Only", s1_hours),
            ("Session 2: US/Afternoon Only", s2_hours),
            ("Dual-Session: Both Sessions", dual_hours),
        ]

        for s_label, hours in session_configs:
            for tp in ["fixed_2.0x", "pure_eod", "fixed_1.5x", "be_runner"]:
                res = run_session_backtest(
                    df=df,
                    asset_name=asset_name,
                    session_hours=hours,
                    session_label=s_label,
                    tp_mode=tp,
                )
                results.append(res)
                print(f"[{asset_name:16s}] {s_label:28s} | TP: {tp:10s} -> Trades: {res['total_trades']:2d} ({res['trades_per_year']:4.1f}/yr) | Sharpe: {res['sharpe']:+.2f} | Ret: {res['total_return_pct']:+5.1f}% | DD: {res['max_dd_pct']:3.1f}% | Win: {res['win_rate_pct']:4.1f}% | PF: {res['profit_factor']:.2f}")

    out_p = Path("run_log/orb_dual_session.json")
    out_p.parent.mkdir(parents=True, exist_ok=True)
    with out_p.open("w", encoding="utf-8") as f:
        # exclude daily_pnl from JSON summary for compactness
        clean_results = [{k: v for k, v in r.items() if k != "daily_pnl"} for r in results]
        json.dump(clean_results, f, indent=2)
    print(f"\nSaved dual-session matrix to {out_p}")


if __name__ == "__main__":
    main()
