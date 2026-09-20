"""Test microstructure variants across all 5 assets (2022-2026)."""

from typing import Dict, List, Tuple
import numpy as np
import polars as pl
from scripts.run_orb_multi_asset_evaluation import prepare_spx_vwap, prepare_asset_dataframe

def run_portfolio_variant(k_stretch: float = 0.0, sl_ratio: float = 1.0, use_be: bool = False):
    df_spx = prepare_spx_vwap()

    configs = [
        ("Nikkei 225", "data/processed/JP225_USD_5m_2017_2026.parquet", [0], True, True, "Tokyo Open"),
        ("Hang Seng", "data/processed/HK33_5m_2022_2026.parquet", [1], True, True, "HK Open"),
        ("Germany 40", "data/processed/DE30_EUR_5m_2017_2026.parquet", [13], True, False, "US Overlap"),
        ("Nasdaq 100", "data/processed/NAS100_5m_2022_2026.parquet", [14], True, False, "US Open"),
        ("BTC/USD", "data/processed/BTCUSD_5m_2022_2026.parquet", [13], False, True, "US Crypto"),
    ]

    initial_cap = 100_000.0
    risk_frac = 0.01  # 1% static risk
    friction = 4.0 / 10_000.0

    all_trades = []

    for name, fpath, hours, allow_l, allow_s, label in configs:
        is_crypto = "BTC" in name
        df = prepare_asset_dataframe(fpath, df_spx, is_crypto=is_crypto)
        df = df.filter((pl.col("timestamp") >= pl.lit("2022-01-01").str.to_datetime()) & (pl.col("timestamp") <= pl.lit("2026-07-31").str.to_datetime()))

        dates = df["date"].unique().sort().to_list()

        for d in dates:
            day_df = df.filter(pl.col("date") == d)

            for s_idx, open_h in enumerate(hours):
                session_df = day_df.filter((pl.col("hour") >= open_h) & (pl.col("hour") < open_h + 6))
                if len(session_df) < 16:
                    continue

                or_df = session_df.slice(0, 12)
                or_h = or_df["high"].max()
                or_l = or_df["low"].min()
                or_rng = or_h - or_l
                atr20 = or_df["atr20_bar"].first()
                ema200 = or_df["ema_200"].last()

                if not or_rng or or_rng <= 0 or not atr20 or or_rng < 1.2 * atr20:
                    continue

                rest_df = session_df.slice(12)
                in_trade = False
                trade_dir = 0
                entry_p, sl_p, tp_p, pos_w, risk_dist = 0.0, 0.0, 0.0, 0.0, 0.0
                be_activated = False

                max_bars = min(len(rest_df), 36)
                stretch = k_stretch * atr20

                for i in range(max_bars):
                    bar = rest_df[i]
                    c, h, l = bar["close"][0], bar["high"][0], bar["low"][0]
                    spx_c = bar["spx_close"][0] if "spx_close" in bar.columns else None
                    spx_v = bar["spx_vwap"][0] if "spx_vwap" in bar.columns else None

                    if not in_trade:
                        if i < 12:
                            long_sig = allow_l and (c > or_h + stretch) and (ema200 is None or c > ema200)
                            if not is_crypto and spx_c is not None and spx_v is not None and spx_c <= spx_v:
                                long_sig = False

                            short_sig = allow_s and (c < or_l - stretch) and (ema200 is None or c < ema200)
                            if not is_crypto and spx_c is not None and spx_v is not None and spx_c >= spx_v:
                                short_sig = False

                            if long_sig:
                                in_trade = True
                                trade_dir = 1
                                entry_p = c
                                initial_stop_dist = sl_ratio * or_rng
                                sl_p = entry_p - initial_stop_dist
                                risk_dist = initial_stop_dist
                                tp_p = entry_p + 2.0 * or_rng
                                sl_dist_pct = (risk_dist / entry_p) + friction
                                pos_w = risk_frac / sl_dist_pct if sl_dist_pct > 0 else 1.0

                            elif short_sig:
                                in_trade = True
                                trade_dir = -1
                                entry_p = c
                                initial_stop_dist = sl_ratio * or_rng
                                sl_p = entry_p + initial_stop_dist
                                risk_dist = initial_stop_dist
                                tp_p = entry_p - 2.0 * or_rng
                                sl_dist_pct = (risk_dist / entry_p) + friction
                                pos_w = risk_frac / sl_dist_pct if sl_dist_pct > 0 else 1.0
                    else:
                        if trade_dir == 1:
                            if use_be and not be_activated and (h - entry_p) >= or_rng:
                                sl_p = max(sl_p, entry_p)
                                be_activated = True

                            hit_tp = h >= tp_p
                            hit_sl = l <= sl_p

                            if hit_tp and hit_sl:
                                raw_ret = (sl_p - entry_p) / entry_p - friction
                                all_trades.append({"date": str(d), "asset": name, "pnl_pct": pos_w * raw_ret, "pnl_d": pos_w * raw_ret * initial_cap, "r": (pos_w * raw_ret) / risk_frac})
                                break
                            elif hit_tp:
                                raw_ret = (tp_p - entry_p) / entry_p - friction
                                all_trades.append({"date": str(d), "asset": name, "pnl_pct": pos_w * raw_ret, "pnl_d": pos_w * raw_ret * initial_cap, "r": (pos_w * raw_ret) / risk_frac})
                                break
                            elif hit_sl:
                                raw_ret = (sl_p - entry_p) / entry_p - friction
                                all_trades.append({"date": str(d), "asset": name, "pnl_pct": pos_w * raw_ret, "pnl_d": pos_w * raw_ret * initial_cap, "r": (pos_w * raw_ret) / risk_frac})
                                break
                            elif i == max_bars - 1:
                                raw_ret = (c - entry_p) / entry_p - friction
                                all_trades.append({"date": str(d), "asset": name, "pnl_pct": pos_w * raw_ret, "pnl_d": pos_w * raw_ret * initial_cap, "r": (pos_w * raw_ret) / risk_frac})
                                break

                        elif trade_dir == -1:
                            if use_be and not be_activated and (entry_p - l) >= or_rng:
                                sl_p = min(sl_p, entry_p)
                                be_activated = True

                            hit_tp = l <= tp_p
                            hit_sl = h >= sl_p

                            if hit_tp and hit_sl:
                                raw_ret = (entry_p - sl_p) / entry_p - friction
                                all_trades.append({"date": str(d), "asset": name, "pnl_pct": pos_w * raw_ret, "pnl_d": pos_w * raw_ret * initial_cap, "r": (pos_w * raw_ret) / risk_frac})
                                break
                            elif hit_tp:
                                raw_ret = (entry_p - tp_p) / entry_p - friction
                                all_trades.append({"date": str(d), "asset": name, "pnl_pct": pos_w * raw_ret, "pnl_d": pos_w * raw_ret * initial_cap, "r": (pos_w * raw_ret) / risk_frac})
                                break
                            elif hit_sl:
                                raw_ret = (entry_p - sl_p) / entry_p - friction
                                all_trades.append({"date": str(d), "asset": name, "pnl_pct": pos_w * raw_ret, "pnl_d": pos_w * raw_ret * initial_cap, "r": (pos_w * raw_ret) / risk_frac})
                                break
                            elif i == max_bars - 1:
                                raw_ret = (entry_p - c) / entry_p - friction
                                all_trades.append({"date": str(d), "asset": name, "pnl_pct": pos_w * raw_ret, "pnl_d": pos_w * raw_ret * initial_cap, "r": (pos_w * raw_ret) / risk_frac})
                                break

    # Evaluate daily PnL with -2% daily circuit breaker
    trades_by_date = {}
    for t in all_trades:
        trades_by_date.setdefault(t["date"], []).append(t)

    dates = sorted(trades_by_date.keys())
    daily_rets = []
    worst_day = 0.0

    for d in dates:
        d_pnl = 0.0
        for t in trades_by_date[d]:
            if d_pnl <= -0.02:
                break
            d_pnl += t["pnl_pct"]
        if d_pnl < worst_day:
            worst_day = d_pnl
        daily_rets.append(d_pnl)

    cum = np.cumprod(1.0 + np.array(daily_rets))
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    max_dd = np.abs(dd.min()) * 100.0
    tot_prof = (cum[-1] - 1.0) * 100.0
    cagr = ((cum[-1]) ** (1.0 / 4.58) - 1.0) * 100.0

    wins = [t for t in all_trades if t["pnl_d"] > 0]
    losses = [t for t in all_trades if t["pnl_d"] <= 0]
    gp = sum(t["pnl_d"] for t in wins)
    gl = abs(sum(t["pnl_d"] for t in losses))
    pf = (gp / gl) if gl > 0 else 99.0
    sr = (np.mean(daily_rets) / np.std(daily_rets) * np.sqrt(252)) if np.std(daily_rets) > 0 else 0

    return len(all_trades), (len(wins)/len(all_trades)*100 if all_trades else 0), gp - gl, pf, worst_day * 100, max_dd, sr, all_trades

if __name__ == "__main__":
    print("=" * 100)
    print("5-ASSET FTMO BASKET: BASELINE VS MICROSTRUCTURE OPTIMIZATIONS (2022-2026)")
    print("=" * 100)
    print(f"{'Strategy Configuration':<42} | {'Trades':<6} | {'Win%':<6} | {'Net Profit':<11} | {'PF':<5} | {'WorstDay':<8} | {'MaxDD':<6} | {'Sharpe'}")
    print("-" * 100)

    tests = [
        ("1. Baseline (Raw High/Low, Opp SL)", 0.0, 1.0, False),
        ("2. Crabel Stretch Buffer k=0.05", 0.05, 1.0, False),
        ("3. Crabel Stretch Buffer k=0.10", 0.10, 1.0, False),
        ("4. Crabel Stretch Buffer k=0.15", 0.15, 1.0, False),
        ("5. Crabel k=0.10 + Breakeven @ +1.0R", 0.10, 1.0, True),
        ("6. Crabel k=0.15 + Breakeven @ +1.0R", 0.15, 1.0, True),
    ]

    for label, k, sl, be in tests:
        n, wr, net, pf, wd, dd, sr, tr = run_portfolio_variant(k_stretch=k, sl_ratio=sl, use_be=be)
        print(f"{label:<42} | {n:^6} | {wr:>5.1f}% | ${net:>9,.0f} | {pf:>5.2f} | {wd:>6.2f}% | {dd:>5.2f}% | {sr:>+6.2f}")
    print("=" * 100)
