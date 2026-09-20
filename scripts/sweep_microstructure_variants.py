"""Test microstructure variants on Nikkei 225."""

import numpy as np
import polars as pl
from scripts.run_orb_multi_asset_evaluation import prepare_spx_vwap, prepare_asset_dataframe

df_spx = prepare_spx_vwap()
df = prepare_asset_dataframe("data/processed/JP225_USD_5m_2017_2026.parquet", df_spx, is_crypto=False)
df = df.filter((pl.col("timestamp") >= pl.lit("2022-01-01").str.to_datetime()) & (pl.col("timestamp") <= pl.lit("2026-07-31").str.to_datetime()))

def test_variant(df, k_stretch=0.0, sl_ratio=1.0, use_be=False):
    dates = df["date"].unique().sort().to_list()
    trades = []
    initial_cap = 100_000.0
    risk_frac = 0.01
    friction = 4.0 / 10_000.0

    for d in dates:
        day_df = df.filter(pl.col("date") == d)
        session_df = day_df.filter((pl.col("hour") >= 0) & (pl.col("hour") < 6))
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
            spx_c, spx_v = bar["spx_close"][0], bar["spx_vwap"][0]

            if not in_trade:
                if i < 12:
                    long_sig = (c > or_h + stretch) and (ema200 is None or c > ema200)
                    if spx_c is not None and spx_v is not None and spx_c <= spx_v:
                        long_sig = False
                    
                    short_sig = (c < or_l - stretch) and (ema200 is None or c < ema200)
                    if spx_c is not None and spx_v is not None and spx_c >= spx_v:
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
                        trades.append({"pnl_pct": pos_w * raw_ret, "pnl_d": pos_w * raw_ret * initial_cap})
                        break
                    elif hit_tp:
                        raw_ret = (tp_p - entry_p) / entry_p - friction
                        trades.append({"pnl_pct": pos_w * raw_ret, "pnl_d": pos_w * raw_ret * initial_cap})
                        break
                    elif hit_sl:
                        raw_ret = (sl_p - entry_p) / entry_p - friction
                        trades.append({"pnl_pct": pos_w * raw_ret, "pnl_d": pos_w * raw_ret * initial_cap})
                        break
                    elif i == max_bars - 1:
                        raw_ret = (c - entry_p) / entry_p - friction
                        trades.append({"pnl_pct": pos_w * raw_ret, "pnl_d": pos_w * raw_ret * initial_cap})
                        break

                elif trade_dir == -1:
                    if use_be and not be_activated and (entry_p - l) >= or_rng:
                        sl_p = min(sl_p, entry_p)
                        be_activated = True

                    hit_tp = l <= tp_p
                    hit_sl = h >= sl_p

                    if hit_tp and hit_sl:
                        raw_ret = (entry_p - sl_p) / entry_p - friction
                        trades.append({"pnl_pct": pos_w * raw_ret, "pnl_d": pos_w * raw_ret * initial_cap})
                        break
                    elif hit_tp:
                        raw_ret = (entry_p - tp_p) / entry_p - friction
                        trades.append({"pnl_pct": pos_w * raw_ret, "pnl_d": pos_w * raw_ret * initial_cap})
                        break
                    elif hit_sl:
                        raw_ret = (entry_p - sl_p) / entry_p - friction
                        trades.append({"pnl_pct": pos_w * raw_ret, "pnl_d": pos_w * raw_ret * initial_cap})
                        break
                    elif i == max_bars - 1:
                        raw_ret = (entry_p - c) / entry_p - friction
                        trades.append({"pnl_pct": pos_w * raw_ret, "pnl_d": pos_w * raw_ret * initial_cap})
                        break

    wins = [t for t in trades if t["pnl_d"] > 0]
    losses = [t for t in trades if t["pnl_d"] <= 0]
    gp = sum(t["pnl_d"] for t in wins)
    gl = abs(sum(t["pnl_d"] for t in losses))
    pf = (gp / gl) if gl > 0 else 99.0
    rets = [t["pnl_pct"] for t in trades]
    cum = np.cumprod(1.0 + np.array(rets)) if rets else np.array([1.0])
    dd = (cum - np.maximum.accumulate(cum)) / np.maximum.accumulate(cum)
    sr = (np.mean(rets) / np.std(rets) * np.sqrt(252)) if len(rets) > 10 and np.std(rets) > 0 else 0
    return len(trades), (len(wins)/len(trades)*100 if trades else 0), gp - gl, pf, np.abs(dd.min())*100, sr

if __name__ == "__main__":
    print("=== NIKKEI 225 MICROSTRUCTURE VARIANT SWEEP ===")
    print(f"{'Variant':<42} | {'Trades':<6} | {'Win%':<6} | {'Net Profit':<11} | {'PF':<5} | {'MaxDD':<6} | {'Sharpe'}")
    print("-" * 90)

    variants = [
        ("1. Baseline (Raw High, Opp Stop, No BE)", 0.0, 1.0, False),
        ("2. Stretch Buffer k=0.05", 0.05, 1.0, False),
        ("3. Stretch Buffer k=0.10", 0.10, 1.0, False),
        ("4. Stretch Buffer k=0.15", 0.15, 1.0, False),
        ("5. Baseline + Breakeven at +1.0R", 0.0, 1.0, True),
        ("6. Stretch k=0.05 + Breakeven at +1.0R", 0.05, 1.0, True),
        ("7. Stretch k=0.10 + Breakeven at +1.0R", 0.10, 1.0, True),
        ("8. Tight Stop 0.75x + Breakeven", 0.0, 0.75, True),
        ("9. Tight Stop 0.50x + Breakeven", 0.0, 0.50, True),
    ]

    for name, k, sl, be in variants:
        n, wr, net, pf, dd, sr = test_variant(df, k_stretch=k, sl_ratio=sl, use_be=be)
        print(f"{name:<42} | {n:^6} | {wr:>5.1f}% | ${net:>9,.0f} | {pf:>5.2f} | {dd:>5.2f}% | {sr:>+6.2f}")
