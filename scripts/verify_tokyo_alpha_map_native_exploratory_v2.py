"""Independent replay audit of native USDJPY Engine fills, with no order simulation."""
from __future__ import annotations
import json
import math
from pathlib import Path
import polars as pl
ROOT=Path(__file__).resolve().parents[1]
SID="tokyo_alpha_map_program1_native_exploratory_v2"
OUT=ROOT/"run_log"/SID
SRC=OUT/"execution_bars.parquet"
PANEL=pl.read_parquet(OUT/"event_panel.parquet")
DEST=OUT/"T4_independent_oracle/result.json"
SCENARIOS=[
 ("T1_gotobi_short","B1_short","short","09:56","10:10"),
 ("T2_ordinary_short","B0_short","short","09:56","10:10"),
 ("T3_gotobi_long_reference","H1_long","long","08:30","09:54"),
]
def main():
    if DEST.exists():raise RuntimeError("Independent oracle output already exists")
    source=(pl.scan_parquet(SRC)
       .with_columns(pl.col("timestamp").dt.convert_time_zone("Asia/Tokyo").alias("jst"))
       .with_columns(
          pl.col("jst").dt.date().alias("session"),
          pl.col("jst").dt.strftime("%H:%M").alias("clock"))
       .filter(pl.col("clock").is_in(["08:30","09:54","09:56","10:10"]))
       .group_by("session").agg([
          pl.col("open").filter(pl.col("clock")==name).first().alias("o"+name.replace(":",""))
          for name in ["08:30","09:54","09:56","10:10"]])
       .collect())
    audit=[]
    for path,arm,side,eclock,xclock in SCENARIOS:
        base=OUT/path
        result=json.loads((base/"result.json").read_text())
        trades=pl.read_parquet(base/"trades.parquet")
        ref=source.select("session","o"+eclock.replace(":",""),"o"+xclock.replace(":",""))
        joined=trades.join(ref,on="session",how="inner",validate="1:1")
        if joined.height!=trades.height:raise AssertionError("Missing oracle quotes")
        expected_entry=(pl.col("o"+eclock.replace(":",""))+(.005 if side=="long" else -.005))
        expected_exit=(pl.col("o"+xclock.replace(":",""))+(-.005 if side=="long" else .005))
        a=(joined.with_columns(expected_entry.alias("verify_entry"),expected_exit.alias("verify_exit"))
          .with_columns(
            ((pl.col("verify_exit")-pl.col("verify_entry"))*(1 if side=="long" else -1)*10000).alias("verify_pnl_jpy"),
            ((pl.col("verify_exit")-pl.col("verify_entry"))*(1 if side=="long" else -1)*100).alias("verify_pips")))
        a=a.with_columns((pl.col("verify_pnl_jpy")/pl.col("verify_exit")).alias("verify_pnl_usd"))
        bad=a.filter(
          ((pl.col("entry")-pl.col("verify_entry")).abs()>1e-8)|
          ((pl.col("exit")-pl.col("verify_exit")).abs()>1e-8)|
          ((pl.col("pnl_jpy")-pl.col("verify_pnl_jpy")).abs()>1e-7)|
          ((pl.col("pnl_usd")-pl.col("verify_pnl_usd")).abs()>1e-7)|
          ((pl.col("net_pips")-pl.col("verify_pips")).abs()>1e-8)|
          (pl.col("entry_time").dt.convert_time_zone("Asia/Tokyo").dt.strftime("%H:%M")!=eclock)|
          (pl.col("exit_time").dt.convert_time_zone("Asia/Tokyo").dt.strftime("%H:%M")!=xclock))
        if bad.height:raise AssertionError(f"Bad native orders {arm}: {bad.height}")
        pnl=float(a["verify_pnl_usd"].sum())
        if not math.isclose(pnl,result["net_pnl_usd"],abs_tol=1e-6):
            raise AssertionError("USD PnL mismatch")
        if not math.isclose(float(a["verify_pnl_jpy"].sum()),result["native_quote_total_pnl_jpy"],abs_tol=1e-4):
            raise AssertionError("JPY PnL mismatch")
        # Correct peak baseline includes starting USD 10000, unlike first-fill-only cummax.
        path_curve=a.sort("session").with_columns(
            (10000+pl.col("verify_pnl_usd").cum_sum()).alias("eq"))
        eq=[10000.]+[float(x) for x in path_curve["eq"]]
        peak=10000.; maxdd=0.
        for p in eq:
            peak=max(peak,p);maxdd=min(maxdd,p-peak)
        audit.append({"arm":arm,"status":"PASS","trades_checked":a.height,
           "fills_checked":2*a.height,"expected_USD_pnl":pnl,
           "max_closed_trade_drawdown_including_initial_USD":maxdd,
           "reported_closed_trade_dd_USD":result["max_closed_trade_drawdown_usd"],
           "all_executions_next_bar_open":True})
    if sum(x["trades_checked"] for x in audit)!=2059:
        raise AssertionError("Unexpected total trials")
    DEST.parent.mkdir(parents=True,exist_ok=True)
    DEST.write_text(json.dumps({
       "status":"PASS","method":"Independent original snapshot minute opens vs native filled trade ledger and per-trade JPY/USD conversion",
       "trades_checked":sum(x["trades_checked"] for x in audit),
       "fills_checked":sum(x["fills_checked"] for x in audit),
       "results":audit},indent=2)+"\n")
    print(DEST.read_text())
if __name__=="__main__":main()
