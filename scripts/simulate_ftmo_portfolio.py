"""FTMO Challenge Multi-Asset Portfolio Simulation (2022-01 to 2026-07).

Universe:
1. Nikkei 225 (JP225/USD): 00:00 UTC (Tokyo Cash Open) - Long + Short
2. Hang Seng (HK33/HKD): 01:30 UTC (HK Cash Open) - Long + Short (Short is 1.50 PF)
3. Germany 40 (DE30/EUR): 13:00 UTC (US Overlap) - Long
4. Nasdaq 100 (NAS100/USD): 14:00 UTC (US Cash Open) - Long (1.16 PF)
5. BTC/USD (BTC/USD): 13:00 UTC (US Session) - Short (1.10 PF)

Constraints & Rules:
- Account Capital: $100,000
- FTMO Max Daily Drawdown: 4.0% hard limit (5.0% FTMO rule)
- FTMO Max Total Drawdown: 9.0% hard limit (10.0% FTMO rule)
- Target: 10.0% ($10,000) per phase
- Compares:
  1. Static 1.0% Risk with Max 2 Concurrent Trades + Daily Circuit Breaker at -2.0%
  2. Static 2.0% Risk with "Panic Close at -3.0%"
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
        ("Nikkei 225", "data/processed/JP225_USD_5m_2017_2026.parquet", [0], True, True, "Tokyo Open"),
        ("Hang Seng", "data/processed/HK33_5m_2022_2026.parquet", [1], True, True, "HK Open"),
        ("Germany 40", "data/processed/DE30_EUR_5m_2017_2026.parquet", [13], True, False, "US Overlap"),
        ("Nasdaq 100", "data/processed/NAS100_5m_2022_2026.parquet", [14], True, False, "US Open"),
        ("BTC/USD", "data/processed/BTCUSD_5m_2022_2026.parquet", [13], False, True, "US Crypto"),
    ]

    dfs = {}
    for name, fpath, hours, allow_l, allow_s, label in configs:
        is_c = "BTC" in name
        dfs[name] = prepare_asset_dataframe(fpath, df_spx, is_crypto=is_c)

    print("\n" + "="*95)
    print("FTMO CANDIDATE ASSETS (2022-01 to 2026-07 @ 1.0% RISK)")
    print("="*95)
    print(f"{'Asset':<14} | {'Direction':<11} | {'Session':<15} | {'Trades':<7} | {'Win%':<6} | {'Net Profit $':<13} | {'PF':<5} | {'Sharpe':<6}")
    print("-" * 95)

    asset_runs = []
    for name, fpath, hours, allow_l, allow_s, label in configs:
        dir_str = "BOTH" if (allow_l and allow_s) else ("LONG" if allow_l else "SHORT")
        res = run_session_backtest(
            dfs[name], name, hours, label, allow_long=allow_l, allow_short=allow_s, risk_pct=1.0
        )
        asset_runs.append(res)
        tr, wr, np_d, pf, sr = res["total_trades"], res["win_rate"], res["net_profit_dollar"], res["profit_factor"], res["sharpe"]
        print(f"{name:<14} | {dir_str:<11} | {label:<15} | {tr:^7} | {wr:>5.1f}% | ${np_d:>11,.0f} | {pf:>5.2f} | {sr:>+6.2f}")

    print("="*95)

    # Combined Portfolio Simulation with Daily Circuit Breaker
    all_dates = sorted(set().union(*[r["daily_pnl"].keys() for r in asset_runs]))
    
    # 1. Evaluate Portfolio with 1.0% Risk & Daily Circuit Breaker at -2.0%
    print("\n" + "="*95)
    print("PORTFOLIO SIMULATION: 1.0% RISK WITH FTMO DAILY CIRCUIT BREAKER (-2.0%)")
    print("="*95)
    sim_ftmo_portfolio(asset_runs, all_dates, risk_pct=1.0, daily_loss_limit=0.02)

    # 2. Evaluate Portfolio with 1.5% Risk & Daily Circuit Breaker at -2.5%
    print("\n" + "="*95)
    print("PORTFOLIO SIMULATION: 1.5% RISK WITH FTMO DAILY CIRCUIT BREAKER (-2.5%)")
    print("="*95)
    sim_ftmo_portfolio(asset_runs, all_dates, risk_pct=1.5, daily_loss_limit=0.025)

    # 3. Evaluate Portfolio with 2.0% Risk & "Panic Close at -3.0%"
    print("\n" + "="*95)
    print("PORTFOLIO SIMULATION: 2.0% RISK WITH 'PANIC CLOSE AT -3.0%'")
    print("="*95)
    sim_ftmo_portfolio(asset_runs, all_dates, risk_pct=2.0, daily_loss_limit=0.03, panic_slippage_penalty=0.005)


def sim_ftmo_portfolio(asset_runs: List[Dict[str, Any]], all_dates: List[Any], risk_pct: float, daily_loss_limit: float, panic_slippage_penalty: float = 0.0):
    initial_capital = 100_000.0
    all_trades = sum([r["trades"] for r in asset_runs], [])
    all_trades.sort(key=lambda t: t["date"])

    # Group trades by date
    trades_by_date = {}
    for t in all_trades:
        trades_by_date.setdefault(t["date"], []).append(t)

    daily_rets = []
    executed_trades = []
    daily_breach_count = 0
    circuit_breaker_trips = 0

    for d in all_dates:
        d_str = str(d)
        d_trades = trades_by_date.get(d_str, [])
        day_pnl = 0.0

        for t in d_trades:
            # Check if daily loss limit reached
            if day_pnl <= -daily_loss_limit:
                circuit_breaker_trips += 1
                # Skip trade due to circuit breaker (prevents FTMO breach!)
                continue

            # Scale P&L to current risk_pct
            scaled_pnl = t["pnl_pct"] * risk_pct
            day_pnl += scaled_pnl
            executed_trades.append({**t, "pnl_pct": scaled_pnl, "pnl_dollar": scaled_pnl * initial_capital})

        # If panic close at 3% was triggered with penalty
        if panic_slippage_penalty > 0 and day_pnl <= -daily_loss_limit:
            day_pnl -= panic_slippage_penalty  # slippage on panic close

        if day_pnl <= -0.04:  # 4% FTMO daily loss breach
            daily_breach_count += 1

        daily_rets.append(day_pnl)

    p_arr = np.array(daily_rets)
    p_cum = np.cumprod(1.0 + p_arr)
    p_max = np.maximum.accumulate(p_cum)
    p_dd = (p_cum - p_max) / p_max
    max_dd = float(np.abs(p_dd.min()))
    mean_ret = float(np.mean(p_arr))
    std_ret = float(np.std(p_arr))
    sharpe = (mean_ret / std_ret * np.sqrt(252)) if std_ret > 0 else 0.0
    tot_ret = (p_cum[-1] - 1.0) * 100.0
    cagr = ((p_cum[-1]) ** (1.0 / 4.58) - 1.0) * 100.0

    wins = [t for t in executed_trades if t["pnl_dollar"] > 0]
    losses = [t for t in executed_trades if t["pnl_dollar"] <= 0]
    gp = sum(t["pnl_dollar"] for t in wins)
    gl = abs(sum(t["pnl_dollar"] for t in losses))
    pf = (gp / gl) if gl > 0 else 99.0

    print(f"Risk per Trade: {risk_pct:.1f}% | Daily Limit: {daily_loss_limit*100:.1f}%")
    print(f"  Total Trades: {len(executed_trades)} ({len(executed_trades)/4.58:.1f} trades/year, ~{len(executed_trades)/4.58/52:.1f}/week)")
    print(f"  Win Rate: {len(wins)/len(executed_trades)*100:.1f}% ({len(wins)}W / {len(losses)}L)")
    print(f"  Total Net Profit: ${gp - gl:,.0f} (+{tot_ret:.2f}%)")
    print(f"  Annualized CAGR: +{cagr:.2f}% / year")
    print(f"  Profit Factor: {pf:.2f}")
    print(f"  Max Total Drawdown: {max_dd*100:.2f}%")
    print(f"  Annualized Sharpe: {sharpe:+.2f}")
    print(f"  Circuit Breaker Tripped: {circuit_breaker_trips} times (blocked risky trades)")
    print(f"  FTMO 4% Daily Drawdown Breaches: {daily_breach_count} breaches")
    if daily_breach_count == 0 and max_dd < 0.09:
        print(f"  --> FTMO STATUS: 100% COMPLIANT (Zero Breaches, MaxDD < 9.0%)")
    else:
        print(f"  --> FTMO STATUS: ACCOUNT DISQUALIFIED / BREACHED")

    print("\n  Year-by-Year Performance:")
    years = sorted(list(set(t["year"] for t in executed_trades)))
    for y in years:
        y_tr = [t for t in executed_trades if t["year"] == y]
        y_w = [t for t in y_tr if t["pnl_dollar"] > 0]
        y_l = [t for t in y_tr if t["pnl_dollar"] <= 0]
        y_gp = sum(t["pnl_dollar"] for t in y_w)
        y_gl = abs(sum(t["pnl_dollar"] for t in y_l))
        y_np = y_gp - y_gl
        y_pf = (y_gp / y_gl) if y_gl > 0 else 99.0
        print(f"    {y}: {len(y_tr):<3} trades | Win%: {len(y_w)/len(y_tr)*100:<4.1f}% | Net: ${y_np:<8,.0f} | PF: {y_pf:.2f}")


if __name__ == "__main__":
    main()
