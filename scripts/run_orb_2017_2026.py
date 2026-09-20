"""Historical 2017-2026 Backtest for Opening Candle Breakout with Fixed 1% Static Risk.

Evaluates:
- Full 9.3 years (2017 to 2026)
- Germany 40 (07:00 & 13:00 UTC) & Nikkei 225 (00:00 & 03:00 UTC)
- Dual-Session Combined Portfolio
- 1% Static Risk Sizing per trade
- All 4 TP architectures: Fixed 2.0x, Fixed 1.5x, Breakeven Runner, Pure Session Close
- Year-by-year stability analysis (2017 - 2026)
- Deflated Sharpe Ratio (DSR) & Statistical Significance
"""

import json
from pathlib import Path
from typing import Any, Dict, List
import numpy as np
import polars as pl
import talib
from ml4t.diagnostic.evaluation.stats import deflated_sharpe_ratio_from_statistics


def prepare_spx_vwap() -> pl.DataFrame:
    df_spx = pl.read_parquet("data/processed/SPX500_USD_15m_2017_2026.parquet").sort("timestamp")
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
    risk_pct: float = 1.0,
    initial_capital: float = 100_000.0,
) -> Dict[str, Any]:
    friction = 2.0 * (commission_bps + slippage_bps) / 10_000.0  # 4 bps roundtrip
    risk_fraction = risk_pct / 100.0
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
            pos_weight = 0.0
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
                            d_sl = (entry_p - sl_p) / entry_p + friction
                            pos_weight = (risk_fraction / d_sl) if d_sl > 0 else 1.0

                            if tp_mode == "fixed_1.5x":
                                tp_p = entry_p + 1.5 * or_rng
                            elif tp_mode == "fixed_2.0x":
                                tp_p = entry_p + 2.0 * or_rng
                            else:
                                tp_p = 999999.0
                else:
                    # Dynamic Trailing Stop for Breakeven Runner
                    if tp_mode == "be_runner" and (h - entry_p) >= or_rng:
                        sl_p = max(sl_p, entry_p)

                    hit_tp = h >= tp_p
                    hit_sl = l <= sl_p

                    if hit_tp and hit_sl:
                        raw_ret = (sl_p - entry_p) / entry_p - friction
                        pnl_pct = pos_weight * raw_ret
                        pnl_dollar = pnl_pct * initial_capital
                        r_mult = pnl_pct / risk_fraction if risk_fraction > 0 else -1.0
                        all_trades.append({
                            "date": str(d), "year": d.year, "asset": asset_name, "session": session_label,
                            "open_h": open_h, "entry": entry_p, "exit": sl_p, "reason": "Stop Loss",
                            "raw_ret": raw_ret, "pnl_pct": pnl_pct, "pnl_dollar": pnl_dollar,
                            "r_mult": r_mult, "pos_weight": pos_weight
                        })
                        daily_pnl[d] += pnl_pct
                        break
                    elif hit_tp:
                        raw_ret = (tp_p - entry_p) / entry_p - friction
                        pnl_pct = pos_weight * raw_ret
                        pnl_dollar = pnl_pct * initial_capital
                        r_mult = pnl_pct / risk_fraction if risk_fraction > 0 else 2.0
                        all_trades.append({
                            "date": str(d), "year": d.year, "asset": asset_name, "session": session_label,
                            "open_h": open_h, "entry": entry_p, "exit": tp_p, "reason": "Take Profit",
                            "raw_ret": raw_ret, "pnl_pct": pnl_pct, "pnl_dollar": pnl_dollar,
                            "r_mult": r_mult, "pos_weight": pos_weight
                        })
                        daily_pnl[d] += pnl_pct
                        break
                    elif hit_sl:
                        raw_ret = (sl_p - entry_p) / entry_p - friction
                        pnl_pct = pos_weight * raw_ret
                        pnl_dollar = pnl_pct * initial_capital
                        r_mult = pnl_pct / risk_fraction if risk_fraction > 0 else -1.0
                        all_trades.append({
                            "date": str(d), "year": d.year, "asset": asset_name, "session": session_label,
                            "open_h": open_h, "entry": entry_p, "exit": sl_p, "reason": "Stop Loss",
                            "raw_ret": raw_ret, "pnl_pct": pnl_pct, "pnl_dollar": pnl_dollar,
                            "r_mult": r_mult, "pos_weight": pos_weight
                        })
                        daily_pnl[d] += pnl_pct
                        break
                    elif i == max_bars - 1:
                        raw_ret = (c - entry_p) / entry_p - friction
                        pnl_pct = pos_weight * raw_ret
                        pnl_dollar = pnl_pct * initial_capital
                        r_mult = pnl_pct / risk_fraction if risk_fraction > 0 else 0.0
                        all_trades.append({
                            "date": str(d), "year": d.year, "asset": asset_name, "session": session_label,
                            "open_h": open_h, "entry": entry_p, "exit": c, "reason": "Session Close",
                            "raw_ret": raw_ret, "pnl_pct": pnl_pct, "pnl_dollar": pnl_dollar,
                            "r_mult": r_mult, "pos_weight": pos_weight
                        })
                        daily_pnl[d] += pnl_pct
                        break

    rets_arr = np.array([daily_pnl[d] for d in dates])
    cum_equity = np.cumprod(1.0 + rets_arr)
    running_max = np.maximum.accumulate(cum_equity)
    drawdowns = (cum_equity - running_max) / running_max
    max_dd = float(np.abs(drawdowns.min())) if len(drawdowns) > 0 else 0.0

    wins = [t for t in all_trades if t["pnl_dollar"] > 0]
    losses = [t for t in all_trades if t["pnl_dollar"] <= 0]
    gross_profit = sum(t["pnl_dollar"] for t in wins)
    gross_loss = abs(sum(t["pnl_dollar"] for t in losses))
    net_profit_dollar = gross_profit - gross_loss
    net_profit_pct = (cum_equity[-1] - 1.0) * 100.0 if len(cum_equity) > 0 else 0.0
    win_rate = len(wins) / len(all_trades) if all_trades else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 99.0

    mean_ret = float(np.mean(rets_arr)) if len(rets_arr) > 0 else 0.0
    std_ret = float(np.std(rets_arr)) if len(rets_arr) > 0 else 0.0
    sharpe = (mean_ret / std_ret * np.sqrt(252)) if std_ret > 0 else 0.0

    return {
        "asset": asset_name,
        "session": session_label,
        "tp_mode": tp_mode,
        "total_trades": len(all_trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate * 100.0, 1),
        "net_profit_dollar": round(net_profit_dollar, 2),
        "net_profit_pct": round(net_profit_pct, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "max_drawdown_pct": round(max_dd * 100.0, 2),
        "sharpe": round(sharpe, 2),
        "daily_pnl": daily_pnl,
        "trades": all_trades,
    }


def main():
    print("Loading 2017-2026 data...")
    df_spx = prepare_spx_vwap()

    # Load Germany 40 (5m)
    df_de = pl.read_parquet("data/processed/DE30_EUR_5m_2017_2026.parquet").sort("timestamp")
    df_de = df_de.join_asof(df_spx, on="timestamp", strategy="backward")
    df_de_1h = df_de.group_by_dynamic("timestamp", every="1h").agg([
        pl.col("open").first(),
        pl.col("high").max(),
        pl.col("low").min(),
        pl.col("close").last(),
    ]).drop_nulls()
    atr_de = talib.ATR(
        df_de_1h["high"].to_numpy(),
        df_de_1h["low"].to_numpy(),
        df_de_1h["close"].to_numpy(),
        timeperiod=20
    )
    df_de_1h = df_de_1h.with_columns(pl.Series("atr20_bar", atr_de).shift(1))
    df_de = df_de.join_asof(df_de_1h.select(["timestamp", "atr20_bar"]), on="timestamp", strategy="backward")
    df_de = df_de.with_columns([
        pl.col("timestamp").dt.date().alias("date"),
        pl.col("timestamp").dt.hour().alias("hour"),
        pl.col("close").ewm_mean(span=200).alias("ema_200"),
    ])

    # Load Nikkei 225 (5m)
    df_jp = pl.read_parquet("data/processed/JP225_USD_5m_2017_2026.parquet").sort("timestamp")
    df_jp = df_jp.join_asof(df_spx, on="timestamp", strategy="backward")
    df_jp_1h = df_jp.group_by_dynamic("timestamp", every="1h").agg([
        pl.col("open").first(),
        pl.col("high").max(),
        pl.col("low").min(),
        pl.col("close").last(),
    ]).drop_nulls()
    atr_jp = talib.ATR(
        df_jp_1h["high"].to_numpy(),
        df_jp_1h["low"].to_numpy(),
        df_jp_1h["close"].to_numpy(),
        timeperiod=20
    )
    df_jp_1h = df_jp_1h.with_columns(pl.Series("atr20_bar", atr_jp).shift(1))
    df_jp = df_jp.join_asof(df_jp_1h.select(["timestamp", "atr20_bar"]), on="timestamp", strategy="backward")
    df_jp = df_jp.with_columns([
        pl.col("timestamp").dt.date().alias("date"),
        pl.col("timestamp").dt.hour().alias("hour"),
        pl.col("close").ewm_mean(span=200).alias("ema_200"),
    ])

    print(f"Germany 40: {len(df_de):,} bars ({df_de['date'].min()} to {df_de['date'].max()})")
    print(f"Nikkei 225: {len(df_jp):,} bars ({df_jp['date'].min()} to {df_jp['date'].max()})")

    # Run Dual-Session for both
    # DAX: 07:00 & 13:00 UTC
    # Nikkei: 00:00 & 03:00 UTC
    tp_modes = ["fixed_2.0x", "fixed_1.5x", "be_runner", "session_close"]
    results = {}

    for tp in tp_modes:
        res_de = run_session_backtest(df_de, "Germany 40", [7, 13], "Dual (07:00+13:00)", tp_mode=tp)
        res_jp = run_session_backtest(df_jp, "Nikkei 225", [0, 3], "Dual (00:00+03:00)", tp_mode=tp)

        # Combine portfolio
        all_dates = sorted(set(res_de["daily_pnl"].keys()).union(res_jp["daily_pnl"].keys()))
        port_daily = [res_de["daily_pnl"].get(d, 0.0) + res_jp["daily_pnl"].get(d, 0.0) for d in all_dates]
        p_arr = np.array(port_daily)
        p_cum = np.cumprod(1.0 + p_arr)
        p_max = np.maximum.accumulate(p_cum)
        p_dd = (p_cum - p_max) / p_max
        p_max_dd = float(np.abs(p_dd.min())) if len(p_dd) > 0 else 0.0
        p_mean = float(np.mean(p_arr))
        p_std = float(np.std(p_arr))
        p_sharpe = (p_mean / p_std * np.sqrt(252)) if p_std > 0 else 0.0
        p_trades = res_de["trades"] + res_jp["trades"]
        p_wins = [t for t in p_trades if t["pnl_dollar"] > 0]
        p_losses = [t for t in p_trades if t["pnl_dollar"] <= 0]
        p_gp = sum(t["pnl_dollar"] for t in p_wins)
        p_gl = abs(sum(t["pnl_dollar"] for t in p_losses))
        p_pf = (p_gp / p_gl) if p_gl > 0 else 99.0
        p_ret = (p_cum[-1] - 1.0) * 100.0

        # DSR calculation
        try:
            dsr_res = deflated_sharpe_ratio_from_statistics(
                observed_sharpe=p_sharpe,
                n_samples=len(port_daily),
                skewness=float(pl.Series(port_daily).skew() or 0.0),
                excess_kurtosis=float(pl.Series(port_daily).kurtosis() or 0.0),
                n_trials=8,
                variance_trials=0.25,
            )
            dsr_val = float(dsr_res.deflated_sharpe_ratio)
        except Exception:
            dsr_val = 0.0

        results[tp] = {
            "combined": {
                "tp_mode": tp,
                "trades": len(p_trades),
                "wins": len(p_wins),
                "losses": len(p_losses),
                "win_rate": round(len(p_wins) / len(p_trades) * 100.0, 1),
                "net_profit_dollar": round(p_gp - p_gl, 2),
                "net_profit_pct": round(p_ret, 2),
                "profit_factor": round(p_pf, 2),
                "max_drawdown_pct": round(p_max_dd * 100.0, 2),
                "sharpe": round(p_sharpe, 2),
                "dsr": round(float(dsr_val), 4),
            },
            "de": res_de,
            "jp": res_jp,
            "all_trades": p_trades,
            "daily_returns": port_daily,
            "dates": [str(d) for d in all_dates],
        }

    # Print Main Results
    print("\n" + "="*80)
    print("HISTORICAL PERFORMANCE MATRIX (2017 - 2026: 9.3 YEARS) - FIXED 1% RISK")
    print("="*80)
    print(f"{'TP Mode':<18} | {'Trades':<7} | {'Win%':<6} | {'Net Profit $':<13} | {'Net Ret%':<9} | {'PF':<5} | {'MaxDD%':<7} | {'Sharpe':<6} | {'DSR':<6}")
    print("-" * 85)
    for tp, d in results.items():
        c = d["combined"]
        print(f"{tp:<18} | {c['trades']:<7} | {c['win_rate']:<6}% | ${c['net_profit_dollar']:<12,.0f} | +{c['net_profit_pct']:<7.1f}% | {c['profit_factor']:<5} | {c['max_drawdown_pct']:<6}% | {c['sharpe']:<6} | {c['dsr']:<6}")

    # Detailed Year-by-Year breakdown for Fixed 2.0x (Default Architecture)
    f2_trades = results["fixed_2.0x"]["all_trades"]
    years = sorted(list(set(t["year"] for t in f2_trades)))

    print("\n" + "="*80)
    print("YEAR-BY-YEAR STABILITY REPORT (Fixed 2.0x TP Architecture: 2017 - 2026)")
    print("="*80)
    print(f"{'Year':<6} | {'Trades':<7} | {'Wins':<5} | {'Losses':<6} | {'Win%':<6} | {'Net Profit $':<13} | {'Gross Win $':<12} | {'Gross Loss $':<12} | {'PF':<5}")
    print("-" * 85)

    yearly_stats = {}
    for y in years:
        y_tr = [t for t in f2_trades if t["year"] == y]
        y_w = [t for t in y_tr if t["pnl_dollar"] > 0]
        y_l = [t for t in y_tr if t["pnl_dollar"] <= 0]
        y_gp = sum(t["pnl_dollar"] for t in y_w)
        y_gl = abs(sum(t["pnl_dollar"] for t in y_l))
        y_np = y_gp - y_gl
        y_wr = len(y_w) / len(y_tr) * 100.0 if y_tr else 0.0
        y_pf = (y_gp / y_gl) if y_gl > 0 else 99.0
        yearly_stats[y] = {
            "year": y, "trades": len(y_tr), "wins": len(y_w), "losses": len(y_l),
            "win_rate": round(y_wr, 1), "net_profit": round(y_np, 2), "pf": round(y_pf, 2)
        }
        print(f"{y:<6} | {len(y_tr):<7} | {len(y_w):<5} | {len(y_l):<6} | {y_wr:<5.1f}% | ${y_np:<12,.0f} | ${y_gp:<11,.0f} | ${y_gl:<11,.0f} | {y_pf:<5.2f}")

    # Asset Attribution breakdown
    print("\n" + "="*80)
    print("ASSET ATTRIBUTION (2017 - 2026)")
    print("="*80)
    for k, res in [("Germany 40 (DAX)", results["fixed_2.0x"]["de"]), ("Nikkei 225", results["fixed_2.0x"]["jp"])]:
        print(f"{k:<20}: {res['total_trades']} trades | Win%: {res['win_rate']}% | Net: ${res['net_profit_dollar']:,.0f} (+{res['net_profit_pct']}%) | PF: {res['profit_factor']} | MaxDD: {res['max_drawdown_pct']}% | Sharpe: {res['sharpe']}")

    # Save to run_log
    Path("run_log").mkdir(exist_ok=True)
    out_payload = {
        "summary": {tp: d["combined"] for tp, d in results.items()},
        "yearly": yearly_stats,
        "asset_attribution": {
            "germany_40": {k: v for k, v in results["fixed_2.0x"]["de"].items() if k not in ["daily_pnl", "trades"]},
            "nikkei_225": {k: v for k, v in results["fixed_2.0x"]["jp"].items() if k not in ["daily_pnl", "trades"]},
        }
    }
    with open("run_log/orb_2017_2026_backtest.json", "w") as f:
        json.dump(out_payload, f, indent=2)
    print("\n-> Saved full empirical run log to run_log/orb_2017_2026_backtest.json")


if __name__ == "__main__":
    main()
