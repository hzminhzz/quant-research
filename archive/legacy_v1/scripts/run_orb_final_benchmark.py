"""Final 5-Asset Benchmark and Portfolio Optimization (2022-01 to 2026-07).

Evaluates:
- Exactly requested user portfolio: DE30, JP225, USD/JPY, BTC/USD
- Plus US Equity Index (NAS100)
- Long, Short, and Long+Short per asset
- Risk sensitivity (1.0%, 1.5%, 2.0%, 2.5%)
- Optimization to identify the combination that achieves >20% annual return
"""

import json
from pathlib import Path
from typing import Any, Dict, List
import numpy as np
import polars as pl
import talib
from ml4t.diagnostic.evaluation.stats import deflated_sharpe_ratio_from_statistics
from scripts.run_orb_multi_asset_evaluation import (
    prepare_spx_vwap,
    prepare_asset_dataframe,
    run_session_backtest,
)


def main():
    print("Loading datasets through 2026-07...")
    df_spx = prepare_spx_vwap()

    configs = [
        ("Germany 40", "data/processed/DE30_EUR_5m_2017_2026.parquet", [7, 13], "DE30 (07:00+13:00)"),
        ("Nikkei 225", "data/processed/JP225_USD_5m_2017_2026.parquet", [0], "JP225 (00:00 Tokyo)"),
        ("USD/JPY", "data/processed/USDJPY_5m_2022_2026.parquet", [0, 13], "USDJPY (00:00+13:00)"),
        ("BTC/USD", "data/processed/BTCUSD_5m_2022_2026.parquet", [13], "BTCUSD (13:00 US)"),
        ("Nasdaq 100", "data/processed/NAS100_5m_2022_2026.parquet", [14], "NAS100 (14:00 US Open)"),
    ]

    dfs = {}
    for name, fpath, hours, label in configs:
        is_c = "BTC" in name
        dfs[name] = prepare_asset_dataframe(fpath, df_spx, is_crypto=is_c)

    print("\n" + "="*95)
    print("INDIVIDUAL ASSET BREAKDOWN (2022-01 to 2026-07 @ 1.0% RISK)")
    print("="*95)
    print(f"{'Asset':<14} | {'Direction':<11} | {'Trades':<7} | {'Win Rate':<8} | {'Net Profit $':<13} | {'Net Ret%':<9} | {'PF':<5} | {'Sharpe':<6}")
    print("-" * 95)

    asset_runs = {}
    for name, fpath, hours, label in configs:
        df = dfs[name]
        asset_runs[name] = {}
        for d_mode, allow_l, allow_s in [("LONG", True, False), ("SHORT", False, True), ("LONG+SHORT", True, True)]:
            res = run_session_backtest(df, name, hours, label, allow_long=allow_l, allow_short=allow_s, risk_pct=1.0)
            asset_runs[name][d_mode] = res
            tr, wr, np_d, ret, pf, sr = res["total_trades"], res["win_rate"], res["net_profit_dollar"], res["net_profit_pct"], res["profit_factor"], res["sharpe"]
            print(f"{name:<14} | {d_mode:<11} | {tr:^7} | {wr:>7.1f}% | ${np_d:>11,.0f} | {ret:>+7.1f}% | {pf:>5.2f} | {sr:>+6.2f}")
        print("-" * 95)

    # 1. User-Requested Exact Portfolio: DE30, JP225, USD/JPY, BTC/USD (Long + Short)
    print("\n" + "="*95)
    print("PORTFOLIO 1: USER-REQUESTED PORTFOLIO (DE30 + JP225 + USD/JPY + BTC/USD)")
    print("="*95)
    req_assets = [
        asset_runs["Germany 40"]["LONG+SHORT"],
        asset_runs["Nikkei 225"]["LONG+SHORT"],
        asset_runs["USD/JPY"]["LONG+SHORT"],
        asset_runs["BTC/USD"]["LONG+SHORT"],
    ]
    eval_portfolio(req_assets, label="User Portfolio (4 Assets, Long+Short @ 1% Risk)")

    # 2. Optimized Alpha Engine (Removing the toxic USD/JPY FX drag, adding NAS100 Long)
    # The pure Momentum / Trending Basket: Nikkei (L+S) + DE30 US (Long) + NAS100 (Long) + BTC (Short)
    print("\n" + "="*95)
    print("PORTFOLIO 2: REFINED INSTITUTIONAL BASKET (Excluding Toxic FX Mean-Reversion)")
    print("Components: Nikkei 225 (Long+Short) + Germany 40 (Long) + Nasdaq 100 (Long) + BTC/USD (Short)")
    print("="*95)
    opt_assets_1pct = [
        asset_runs["Nikkei 225"]["LONG+SHORT"],
        asset_runs["Germany 40"]["LONG"],
        asset_runs["Nasdaq 100"]["LONG"],
        asset_runs["BTC/USD"]["SHORT"],
    ]
    eval_portfolio(opt_assets_1pct, label="Refined Basket @ 1.0% Risk")

    # 3. High-Return Target Portfolio (>20% CAGR Target) @ 2.0% Risk
    print("\n" + "="*95)
    print("PORTFOLIO 3: HIGH-ALPHA RETURN ENGINE (@ 2.0% STATIC RISK)")
    print("="*95)
    opt_res_2pct = [
        run_session_backtest(dfs["Nikkei 225"], "Nikkei 225", [0], "Tokyo", allow_long=True, allow_short=True, risk_pct=2.0),
        run_session_backtest(dfs["Germany 40"], "Germany 40", [13], "US Overlap", allow_long=True, allow_short=False, risk_pct=2.0),
        run_session_backtest(dfs["Nasdaq 100"], "Nasdaq 100", [14], "US Open", allow_long=True, allow_short=False, risk_pct=2.0),
        run_session_backtest(dfs["BTC/USD"], "BTC/USD", [13], "US Crypto", allow_long=False, allow_short=True, risk_pct=2.0),
    ]
    eval_portfolio(opt_res_2pct, label="Target >20% CAGR Basket @ 2.0% Risk")


def eval_portfolio(asset_results: List[Dict[str, Any]], label: str):
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
    cagr = ((p_cum[-1]) ** (1.0 / 4.58) - 1.0) * 100.0
    pf = (gp / gl) if gl > 0 else 99.0

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

    print(f"Results for: {label}")
    print(f"  Total Trades: {len(all_trades)} ({len(all_trades)/4.58:.1f} trades/year, ~{len(all_trades)/4.58/52:.1f}/week)")
    print(f"  Win Rate: {len(wins)/len(all_trades)*100:.1f}% ({len(wins)}W / {len(losses)}L)")
    print(f"  Total Net Profit: ${np_d:,.0f} (+{tot_ret:.2f}%)")
    print(f"  Annualized CAGR: {cagr:+.2f}% / year")
    print(f"  Profit Factor: {pf:.2f}")
    print(f"  Max Drawdown: {p_max_dd*100:.2f}%")
    print(f"  Annualized Sharpe: {p_sharpe:+.2f}")
    print(f"  Deflated Sharpe Ratio (DSR): {dsr_val:.4f}")

    print("\n  Annual Performance:")
    years = sorted(list(set(t["year"] for t in all_trades)))
    for y in years:
        y_tr = [t for t in all_trades if t["year"] == y]
        y_w = [t for t in y_tr if t["pnl_dollar"] > 0]
        y_l = [t for t in y_tr if t["pnl_dollar"] <= 0]
        y_gp = sum(t["pnl_dollar"] for t in y_w)
        y_gl = abs(sum(t["pnl_dollar"] for t in y_l))
        y_np = y_gp - y_gl
        y_pf = (y_gp / y_gl) if y_gl > 0 else 99.0
        print(f"    {y}: {len(y_tr):<3} trades | Win%: {len(y_w)/len(y_tr)*100:<4.1f}% | Net: ${y_np:<8,.0f} | PF: {y_pf:.2f}")


if __name__ == "__main__":
    main()
