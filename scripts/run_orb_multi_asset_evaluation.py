"""Comprehensive 4-Asset Long + Short Evaluation (2022-01 to 2026-07).

Universe:
1. Germany 40 (DE30/EUR): 07:00 & 13:00 UTC
2. Nikkei 225 (JP225/USD): 00:00 UTC
3. USD/JPY (USD/JPY): Japan Open (00:00 UTC) & US Session (13:00 UTC)
4. BTC/USD (BTC/USD): US Session (13:00 UTC)

Evaluates:
- Long + Short breakouts
- 1.2x 1-Hour ATR Volatility Filter
- SPX 15m VWAP Alignment
- Static Risk (1.0%, 1.5%, 2.0%)
- Year-by-year stability (2022 - 2026)
- Deflated Sharpe Ratio (DSR) & CAGR
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


def prepare_asset_dataframe(fpath: str, df_spx: pl.DataFrame, is_crypto: bool = False) -> pl.DataFrame:
    df = pl.read_parquet(fpath).sort("timestamp")
    df = df.join_asof(df_spx, on="timestamp", strategy="backward")

    df_1h = df.group_by_dynamic("timestamp", every="1h").agg([
        pl.col("open").first(),
        pl.col("high").max(),
        pl.col("low").min(),
        pl.col("close").last(),
    ]).drop_nulls()

    atr = talib.ATR(
        df_1h["high"].to_numpy(),
        df_1h["low"].to_numpy(),
        df_1h["close"].to_numpy(),
        timeperiod=20
    )
    df_1h = df_1h.with_columns(pl.Series("atr20_bar", atr).shift(1))
    df = df.join_asof(df_1h.select(["timestamp", "atr20_bar"]), on="timestamp", strategy="backward")

    df = df.with_columns([
        pl.col("timestamp").dt.date().alias("date"),
        pl.col("timestamp").dt.hour().alias("hour"),
        pl.col("close").ewm_mean(span=200).alias("ema_200"),
    ])
    return df


def run_session_backtest(
    df: pl.DataFrame,
    asset_name: str,
    session_hours: List[int],
    session_label: str,
    allow_long: bool = True,
    allow_short: bool = True,
    tp_multiple: float = 2.0,
    max_hold_bars: int = 36,
    slippage_bps: float = 2.0,
    commission_bps: float = 0.0,
    risk_pct: float = 1.0,
    initial_capital: float = 100_000.0,
    start_date: str = "2022-01-01",
    end_date: str = "2026-07-31",
) -> Dict[str, Any]:
    friction = 2.0 * (commission_bps + slippage_bps) / 10_000.0
    risk_fraction = risk_pct / 100.0

    filtered_df = df.filter(
        (pl.col("timestamp") >= pl.lit(start_date).str.to_datetime())
        & (pl.col("timestamp") <= pl.lit(end_date).str.to_datetime())
    )

    dates = filtered_df["date"].unique().sort().to_list()
    daily_pnl = {d: 0.0 for d in dates}
    all_trades = []

    for d in dates:
        day_df = filtered_df.filter(pl.col("date") == d)

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
            trade_dir = 0
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
                    if i < 12:  # 1-hour entry window
                        # Long condition
                        sig_long = allow_long and (c > or_h) and (ema200 is None or c > ema200)
                        if spx_c is not None and spx_v is not None and spx_c <= spx_v:
                            sig_long = False

                        # Short condition
                        sig_short = allow_short and (c < or_l) and (ema200 is None or c < ema200)
                        if spx_c is not None and spx_v is not None and spx_c >= spx_v:
                            sig_short = False

                        if sig_long:
                            in_trade = True
                            trade_dir = 1
                            entry_p = c
                            sl_p = or_l
                            tp_p = entry_p + tp_multiple * or_rng
                            d_sl = (entry_p - sl_p) / entry_p + friction
                            pos_weight = (risk_fraction / d_sl) if d_sl > 0 else 1.0
                        elif sig_short:
                            in_trade = True
                            trade_dir = -1
                            entry_p = c
                            sl_p = or_h
                            tp_p = entry_p - tp_multiple * or_rng
                            d_sl = (sl_p - entry_p) / entry_p + friction
                            pos_weight = (risk_fraction / d_sl) if d_sl > 0 else 1.0

                else:
                    if trade_dir == 1:
                        # LONG
                        hit_tp = h >= tp_p
                        hit_sl = l <= sl_p

                        if hit_tp and hit_sl:
                            raw_ret = (sl_p - entry_p) / entry_p - friction
                            pnl_pct = pos_weight * raw_ret
                            pnl_dollar = pnl_pct * initial_capital
                            r_mult = pnl_pct / risk_fraction if risk_fraction > 0 else -1.0
                            all_trades.append({
                                "date": str(d), "year": d.year, "asset": asset_name, "dir": "LONG",
                                "entry": entry_p, "exit": sl_p, "reason": "Stop Loss",
                                "pnl_pct": pnl_pct, "pnl_dollar": pnl_dollar, "r_mult": r_mult
                            })
                            daily_pnl[d] += pnl_pct
                            break
                        elif hit_tp:
                            raw_ret = (tp_p - entry_p) / entry_p - friction
                            pnl_pct = pos_weight * raw_ret
                            pnl_dollar = pnl_pct * initial_capital
                            r_mult = pnl_pct / risk_fraction if risk_fraction > 0 else tp_multiple
                            all_trades.append({
                                "date": str(d), "year": d.year, "asset": asset_name, "dir": "LONG",
                                "entry": entry_p, "exit": tp_p, "reason": "Take Profit",
                                "pnl_pct": pnl_pct, "pnl_dollar": pnl_dollar, "r_mult": r_mult
                            })
                            daily_pnl[d] += pnl_pct
                            break
                        elif hit_sl:
                            raw_ret = (sl_p - entry_p) / entry_p - friction
                            pnl_pct = pos_weight * raw_ret
                            pnl_dollar = pnl_pct * initial_capital
                            r_mult = pnl_pct / risk_fraction if risk_fraction > 0 else -1.0
                            all_trades.append({
                                "date": str(d), "year": d.year, "asset": asset_name, "dir": "LONG",
                                "entry": entry_p, "exit": sl_p, "reason": "Stop Loss",
                                "pnl_pct": pnl_pct, "pnl_dollar": pnl_dollar, "r_mult": r_mult
                            })
                            daily_pnl[d] += pnl_pct
                            break
                        elif i == max_bars - 1:
                            raw_ret = (c - entry_p) / entry_p - friction
                            pnl_pct = pos_weight * raw_ret
                            pnl_dollar = pnl_pct * initial_capital
                            r_mult = pnl_pct / risk_fraction if risk_fraction > 0 else 0.0
                            all_trades.append({
                                "date": str(d), "year": d.year, "asset": asset_name, "dir": "LONG",
                                "entry": entry_p, "exit": c, "reason": "Session Close",
                                "pnl_pct": pnl_pct, "pnl_dollar": pnl_dollar, "r_mult": r_mult
                            })
                            daily_pnl[d] += pnl_pct
                            break

                    elif trade_dir == -1:
                        # SHORT
                        hit_tp = l <= tp_p
                        hit_sl = h >= sl_p

                        if hit_tp and hit_sl:
                            raw_ret = (entry_p - sl_p) / entry_p - friction
                            pnl_pct = pos_weight * raw_ret
                            pnl_dollar = pnl_pct * initial_capital
                            r_mult = pnl_pct / risk_fraction if risk_fraction > 0 else -1.0
                            all_trades.append({
                                "date": str(d), "year": d.year, "asset": asset_name, "dir": "SHORT",
                                "entry": entry_p, "exit": sl_p, "reason": "Stop Loss",
                                "pnl_pct": pnl_pct, "pnl_dollar": pnl_dollar, "r_mult": r_mult
                            })
                            daily_pnl[d] += pnl_pct
                            break
                        elif hit_tp:
                            raw_ret = (entry_p - tp_p) / entry_p - friction
                            pnl_pct = pos_weight * raw_ret
                            pnl_dollar = pnl_pct * initial_capital
                            r_mult = pnl_pct / risk_fraction if risk_fraction > 0 else tp_multiple
                            all_trades.append({
                                "date": str(d), "year": d.year, "asset": asset_name, "dir": "SHORT",
                                "entry": entry_p, "exit": tp_p, "reason": "Take Profit",
                                "pnl_pct": pnl_pct, "pnl_dollar": pnl_dollar, "r_mult": r_mult
                            })
                            daily_pnl[d] += pnl_pct
                            break
                        elif hit_sl:
                            raw_ret = (entry_p - sl_p) / entry_p - friction
                            pnl_pct = pos_weight * raw_ret
                            pnl_dollar = pnl_pct * initial_capital
                            r_mult = pnl_pct / risk_fraction if risk_fraction > 0 else -1.0
                            all_trades.append({
                                "date": str(d), "year": d.year, "asset": asset_name, "dir": "SHORT",
                                "entry": entry_p, "exit": sl_p, "reason": "Stop Loss",
                                "pnl_pct": pnl_pct, "pnl_dollar": pnl_dollar, "r_mult": r_mult
                            })
                            daily_pnl[d] += pnl_pct
                            break
                        elif i == max_bars - 1:
                            raw_ret = (entry_p - c) / entry_p - friction
                            pnl_pct = pos_weight * raw_ret
                            pnl_dollar = pnl_pct * initial_capital
                            r_mult = pnl_pct / risk_fraction if risk_fraction > 0 else 0.0
                            all_trades.append({
                                "date": str(d), "year": d.year, "asset": asset_name, "dir": "SHORT",
                                "entry": entry_p, "exit": c, "reason": "Session Close",
                                "pnl_pct": pnl_pct, "pnl_dollar": pnl_dollar, "r_mult": r_mult
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
        "total_trades": len(all_trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate * 100.0, 1),
        "net_profit_dollar": round(net_profit_dollar, 2),
        "net_profit_pct": round(net_profit_pct, 2),
        "profit_factor": round(profit_factor, 2),
        "max_drawdown_pct": round(max_dd * 100.0, 2),
        "sharpe": round(sharpe, 2),
        "daily_pnl": daily_pnl,
        "trades": all_trades,
    }


def main():
    print("Loading synchronized datasets through 2026-07...")
    df_spx = prepare_spx_vwap()

    df_de = prepare_asset_dataframe("data/processed/DE30_EUR_5m_2017_2026.parquet", df_spx)
    df_jp = prepare_asset_dataframe("data/processed/JP225_USD_5m_2017_2026.parquet", df_spx)
    df_uj = prepare_asset_dataframe("data/processed/USDJPY_5m_2022_2026.parquet", df_spx)
    df_btc = prepare_asset_dataframe("data/processed/BTCUSD_5m_2022_2026.parquet", df_spx, is_crypto=True)

    print(f"DE30: {len(df_de):,} rows | JP225: {len(df_jp):,} rows")
    print(f"USDJPY: {len(df_uj):,} rows | BTCUSD: {len(df_btc):,} rows")

    # Evaluate at multiple risk levels: 1.0%, 1.5%, 2.0%
    risk_levels = [1.0, 1.5, 2.0]
    out_results = {}

    for r_pct in risk_levels:
        print(f"\n" + "="*80)
        print(f"EVALUATING 4-ASSET LONG + SHORT PORTFOLIO @ {r_pct:.1f}% RISK (2022-01 to 2026-07)")
        print("="*80)

        res_de = run_session_backtest(df_de, "Germany 40", [7, 13], "Dual (07:00+13:00 UTC)", risk_pct=r_pct)
        res_jp = run_session_backtest(df_jp, "Nikkei 225", [0], "Tokyo Open (00:00 UTC)", risk_pct=r_pct)
        res_uj = run_session_backtest(df_uj, "USD/JPY", [0, 13], "Japan+US (00:00+13:00 UTC)", risk_pct=r_pct)
        res_btc = run_session_backtest(df_btc, "BTC/USD", [13], "US Session (13:00 UTC)", risk_pct=r_pct)

        asset_results = [res_de, res_jp, res_uj, res_btc]

        print(f"{'Asset':<15} | {'Trades':<7} | {'Win%':<6} | {'Net Profit $':<13} | {'Net Ret%':<9} | {'PF':<5} | {'MaxDD%':<7} | {'Sharpe':<6}")
        print("-" * 80)
        for r in asset_results:
            print(f"{r['asset']:<15} | {r['total_trades']:<7} | {r['win_rate']:<6}% | ${r['net_profit_dollar']:<12,.0f} | {r['net_profit_pct']:<+8.1f}% | {r['profit_factor']:<5.2f} | {r['max_drawdown_pct']:<6.2f}% | {r['sharpe']:<+6.2f}")

        # Combined Portfolio
        all_dates = sorted(set().union(*[r["daily_pnl"].keys() for r in asset_results]))
        port_daily = [sum(r["daily_pnl"].get(d, 0.0) for r in asset_results) for d in all_dates]
        p_arr = np.array(port_daily)
        p_cum = np.cumprod(1.0 + p_arr)
        p_max = np.maximum.accumulate(p_cum)
        p_dd = (p_cum - p_max) / p_max
        p_max_dd = float(np.abs(p_dd.min())) if len(p_dd) > 0 else 0.0
        p_mean = float(np.mean(p_arr))
        p_std = float(np.std(p_arr))
        p_sharpe = (p_mean / p_std * np.sqrt(252)) if p_std > 0 else 0.0

        all_trades = sum([r["trades"] for r in asset_results], [])
        wins = [t for t in all_trades if t["pnl_dollar"] > 0]
        losses = [t for t in all_trades if t["pnl_dollar"] <= 0]
        gp = sum(t["pnl_dollar"] for t in wins)
        gl = abs(sum(t["pnl_dollar"] for t in losses))
        np_d = gp - gl
        tot_ret = (p_cum[-1] - 1.0) * 100.0
        cagr = ((p_cum[-1]) ** (1.0 / 4.58) - 1.0) * 100.0  # 4.58 years from 2022-01 to 2026-07
        pf = (gp / gl) if gl > 0 else 99.0

        # DSR calculation
        try:
            dsr_res = deflated_sharpe_ratio_from_statistics(
                observed_sharpe=p_sharpe,
                n_samples=len(port_daily),
                skewness=float(pl.Series(port_daily).skew() or 0.0),
                excess_kurtosis=float(pl.Series(port_daily).kurtosis() or 0.0),
                n_trials=16,
                variance_trials=0.25,
            )
            dsr_val = float(dsr_res.deflated_sharpe_ratio)
        except Exception:
            dsr_val = 0.0

        print("-" * 80)
        print(f"COMBINED PORTFOLIO (@ {r_pct:.1f}% Risk):")
        print(f"  Total Trades: {len(all_trades)} ({len(all_trades)/4.58:.1f} trades/year, ~{len(all_trades)/4.58/52:.1f} trades/week)")
        print(f"  Win Rate: {len(wins)/len(all_trades)*100:.1f}% ({len(wins)}W / {len(losses)}L)")
        print(f"  Total Net Profit: ${np_d:,.0f} (+{tot_ret:.2f}%)")
        print(f"  Annualized Return (CAGR): +{cagr:.2f}% / year")
        print(f"  Profit Factor: {pf:.2f}")
        print(f"  Max Drawdown: {p_max_dd*100:.2f}%")
        print(f"  Annualized Sharpe: {p_sharpe:+.2f}")
        print(f"  Deflated Sharpe Ratio (DSR): {dsr_val:.4f}")

        # Year-by-year
        print("\n  Year-by-Year Breakdown:")
        years = sorted(list(set(t["year"] for t in all_trades)))
        for y in years:
            y_tr = [t for t in all_trades if t["year"] == y]
            y_w = [t for t in y_tr if t["pnl_dollar"] > 0]
            y_l = [t for t in y_tr if t["pnl_dollar"] <= 0]
            y_gp = sum(t["pnl_dollar"] for t in y_w)
            y_gl = abs(sum(t["pnl_dollar"] for t in y_l))
            y_np = y_gp - y_gl
            y_pf = (y_gp / y_gl) if y_gl > 0 else 99.0
            print(f"    {y}: {len(y_tr):<3} trades | Win: {len(y_w)/len(y_tr)*100:<4.1f}% | Net: ${y_np:<8,.0f} | PF: {y_pf:.2f}")

        out_results[f"risk_{r_pct}"] = {
            "risk_pct": r_pct,
            "total_trades": len(all_trades),
            "trades_per_year": round(len(all_trades) / 4.58, 1),
            "win_rate": round(len(wins) / len(all_trades) * 100.0, 1),
            "net_profit_dollar": round(np_d, 2),
            "net_profit_pct": round(tot_ret, 2),
            "cagr": round(cagr, 2),
            "profit_factor": round(pf, 2),
            "max_drawdown_pct": round(p_max_dd * 100.0, 2),
            "sharpe": round(p_sharpe, 2),
            "dsr": round(dsr_val, 4),
        }

    with open("run_log/orb_multi_asset_2022_2026.json", "w") as f:
        json.dump(out_results, f, indent=2)
    print("\n-> Saved empirical run log to run_log/orb_multi_asset_2022_2026.json")


if __name__ == "__main__":
    main()
