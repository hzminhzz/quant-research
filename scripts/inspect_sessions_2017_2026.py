from scripts.run_orb_2017_2026 import prepare_spx_vwap, run_session_backtest
import polars as pl
import talib

df_spx = prepare_spx_vwap()

# DAX
df_de = pl.read_parquet("data/processed/DE30_EUR_5m_2017_2026.parquet").sort("timestamp")
df_de = df_de.join_asof(df_spx, on="timestamp", strategy="backward")
df_de_1h = df_de.group_by_dynamic("timestamp", every="1h").agg([
    pl.col("open").first(), pl.col("high").max(), pl.col("low").min(), pl.col("close").last()
]).drop_nulls()
atr_de = talib.ATR(df_de_1h["high"].to_numpy(), df_de_1h["low"].to_numpy(), df_de_1h["close"].to_numpy(), timeperiod=20)
df_de_1h = df_de_1h.with_columns(pl.Series("atr20_bar", atr_de).shift(1))
df_de = df_de.join_asof(df_de_1h.select(["timestamp", "atr20_bar"]), on="timestamp", strategy="backward")
df_de = df_de.with_columns([
    pl.col("timestamp").dt.date().alias("date"),
    pl.col("timestamp").dt.hour().alias("hour"),
    pl.col("close").ewm_mean(span=200).alias("ema_200"),
])

# Nikkei
df_jp = pl.read_parquet("data/processed/JP225_USD_5m_2017_2026.parquet").sort("timestamp")
df_jp = df_jp.join_asof(df_spx, on="timestamp", strategy="backward")
df_jp_1h = df_jp.group_by_dynamic("timestamp", every="1h").agg([
    pl.col("open").first(), pl.col("high").max(), pl.col("low").min(), pl.col("close").last()
]).drop_nulls()
atr_jp = talib.ATR(df_jp_1h["high"].to_numpy(), df_jp_1h["low"].to_numpy(), df_jp_1h["close"].to_numpy(), timeperiod=20)
df_jp_1h = df_jp_1h.with_columns(pl.Series("atr20_bar", atr_jp).shift(1))
df_jp = df_jp.join_asof(df_jp_1h.select(["timestamp", "atr20_bar"]), on="timestamp", strategy="backward")
df_jp = df_jp.with_columns([
    pl.col("timestamp").dt.date().alias("date"),
    pl.col("timestamp").dt.hour().alias("hour"),
    pl.col("close").ewm_mean(span=200).alias("ema_200"),
])

print("=== DAX SESSIONS 2017-2026 ===")
for h_name, h_list in [("07:00 Cash Open", [7]), ("13:00 US Overlap", [13]), ("Dual 07+13", [7, 13])]:
    r = run_session_backtest(df_de, "DAX", h_list, h_name, tp_mode="fixed_2.0x")
    tr = r["total_trades"]
    wr = r["win_rate"]
    np_d = r["net_profit_dollar"]
    pf = r["profit_factor"]
    sr = r["sharpe"]
    print(f"{h_name:<18} | Trades: {tr:<4} | Win%: {wr:<5}% | Net: ${np_d:<10,.0f} | PF: {pf:<5.2f} | Sharpe: {sr:+.2f}")

print("\n=== NIKKEI SESSIONS 2017-2026 ===")
for h_name, h_list in [("00:00 Tokyo Open", [0]), ("03:00 Afternoon", [3]), ("Dual 00+03", [0, 3])]:
    r = run_session_backtest(df_jp, "Nikkei", h_list, h_name, tp_mode="fixed_2.0x")
    tr = r["total_trades"]
    wr = r["win_rate"]
    np_d = r["net_profit_dollar"]
    pf = r["profit_factor"]
    sr = r["sharpe"]
    print(f"{h_name:<18} | Trades: {tr:<4} | Win%: {wr:<5}% | Net: ${np_d:<10,.0f} | PF: {pf:<5.2f} | Sharpe: {sr:+.2f}")
