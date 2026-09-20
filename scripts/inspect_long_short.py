from scripts.run_orb_multi_asset_evaluation import prepare_spx_vwap, prepare_asset_dataframe, run_session_backtest

df_spx = prepare_spx_vwap()
assets = [
    ("Germany 40", "data/processed/DE30_EUR_5m_2017_2026.parquet", [7, 13]),
    ("Nikkei 225", "data/processed/JP225_USD_5m_2017_2026.parquet", [0]),
    ("USD/JPY", "data/processed/USDJPY_5m_2022_2026.parquet", [0, 13]),
    ("BTC/USD", "data/processed/BTCUSD_5m_2022_2026.parquet", [13]),
]

print("="*85)
print(f"{'Asset':<14} | {'Dir':<6} | {'Trades':<7} | {'Win Rate':<8} | {'Net Profit $':<13} | {'PF':<5} | {'Sharpe':<6}")
print("="*85)

for name, fpath, hours in assets:
    df = prepare_asset_dataframe(fpath, df_spx, is_crypto=("BTC" in name))
    for d_label, allow_l, allow_s in [("LONG", True, False), ("SHORT", False, True), ("BOTH", True, True)]:
        res = run_session_backtest(df, name, hours, "Session", allow_long=allow_l, allow_short=allow_s, risk_pct=1.0)
        tr = res["total_trades"]
        wr = res["win_rate"]
        np_d = res["net_profit_dollar"]
        pf = res["profit_factor"]
        sr = res["sharpe"]
        print(f"{name:<14} | {d_label:<6} | {tr:^7} | {wr:>7.1f}% | ${np_d:>11,.0f} | {pf:>5.2f} | {sr:>+6.2f}")
    print("-" * 85)
