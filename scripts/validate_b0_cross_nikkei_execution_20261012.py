"""Nikkei B0 execution validation against available minute and five-minute data.

The five-minute file cannot resolve same-minute stop ordering.
All PnL sensitivities here consume native ML4T ledgers, not a custom simulator.
"""
from pathlib import Path
from datetime import datetime, timezone
import json
import polars as pl
import sys

HERE=Path("run_log/one_bar_b0_cross_indices_20261012")
OUT=HERE/"followup_dax_nikkei_20261012"
OUT.mkdir(parents=True,exist_ok=True)
STORE=Path("/home/quant/dev/quant/ml4t-data/.data/store/index_minute_NIKKEI225")
FIVE=Path("data/processed/JP225_USD_5m_2017_2026.parquet")
YEAR=2026
CUTOFF=datetime(2026,7,15,tzinfo=timezone.utc)
def main():
    f=[str(x) for x in STORE.glob("year=2026/month=*/data.parquet") if int(x.parent.name.split("=")[1])<=7]
    one=(pl.scan_parquet(f,extra_columns="ignore",hive_partitioning=False)
         .select("timestamp","open","high","low","close","volume")
         .filter(pl.col("timestamp")<CUTOFF).sort("timestamp").collect(engine="streaming"))
    five=(pl.scan_parquet(FIVE).select("timestamp","open","high","low","close","volume")
          .filter((pl.col("timestamp").dt.year()==YEAR)&(pl.col("timestamp")<CUTOFF))
          .collect(engine="streaming"))
    agg=(one.with_columns(pl.col("timestamp").dt.truncate("5m").alias("slot"))
         .group_by("slot").agg(pl.len().alias("count"),
           pl.col("timestamp").min().alias("first"),
           pl.col("timestamp").max().alias("last"),
           pl.col("open").first().alias("one_open"),
           pl.col("high").max().alias("one_high"),
           pl.col("low").min().alias("one_low"),
           pl.col("close").last().alias("one_close"))
         .filter((pl.col("count")==5)&(pl.col("first")==pl.col("slot"))&
                 (pl.col("last")==pl.col("slot")+pl.duration(minutes=4)))
        ).sort("slot")
    joined=(agg.join(five.rename({"timestamp":"slot"}),on="slot",how="inner"))
    equality=joined.select(
      pl.len().alias("overlap"),
      ((pl.col("one_open")-pl.col("open")).abs()<1e-7).sum().alias("matching_open"),
      ((pl.col("one_high")-pl.col("high")).abs()<1e-7).sum().alias("matching_high"),
      ((pl.col("one_low")-pl.col("low")).abs()<1e-7).sum().alias("matching_low"),
      ((pl.col("one_close")-pl.col("close")).abs()<1e-7).sum().alias("matching_close"),
    ).to_dicts()[0]
    native_dir=HERE/"phase34/NIKKEI225/2026/native_costed_synthetic"
    metrics=json.loads((native_dir/"metrics.json").read_text())
    rows=(pl.read_csv(native_dir/"evaluation_trades.csv",try_parse_dates=True)
          .filter(pl.col("status")=="closed"))
    examples=metrics["ambiguous_examples"]
    ambiguous_times=[datetime.fromisoformat(x["timestamp"]) for x in examples]
    matched=rows.filter(pl.col("entry_time").is_in(ambiguous_times))
    a=one.join(pl.DataFrame({"timestamp":ambiguous_times}),on="timestamp",how="inner") if ambiguous_times else one.head(0)
    stop_fraction=rows.select((50/pl.col("entry_price")*100).alias("stop_pct"))["stop_pct"]
    controls={
      "native_closed_evaluation_trades":rows.height,
      "source_1m_rows_2026":one.height,
      "preexisting_native_ambiguous_raw_events_including_warmup":len(examples),
      "matched_evaluation_trade_ambiguous":matched.height,
      "matched_evaluation_trade_ambiguous_fraction":matched.height/rows.height,
      "matched_ambiguous_pnl_R":float(matched["pnl"].sum()/1000),
      "unambiguous_realized_native_R":float((rows["pnl"].sum()-matched["pnl"].sum())/1000),
      "observed_native_total_R":float(rows["pnl"].sum()/1000),
      "stop_distance_pct_of_entry":{"min":float(stop_fraction.min()),"median":float(stop_fraction.median()),"max":float(stop_fraction.max())},
      "matched_ambiguous_source_minute_count":a.height,
      "source_1m_duplicate_timestamps":one.height-one["timestamp"].n_unique(),
      "source_1m_null_ohlc":sum(one[c].null_count() for c in ("open","high","low","close")),
      "native_gap_trigger_events_including_warmup":metrics.get("entry_gap_triggers"),
      "native_protective_stop_gap_through_fills_including_warmup":metrics.get("protective_stop_gap_through_fills"),
    }
    sens=json.loads((HERE/"phase34/intraminute_ambiguity_sensitivity.json").read_text())
    gate=sens["results"]["NIKKEI225"]["groups"]["2026"]
    assert gate["trades"]==rows.height and gate["ambiguous_trades"]==matched.height
    assert gate["pessimistic_sensitivity_total_R"]<0
    result={
      "status":"EXECUTION_VALIDATION_INCONCLUSIVE",
      "primary_source":"LSE JP225/USD 1-minute index-price proxy; not OSE futures trades, not tick BID/ASK",
      "available_5m_reference":"Processed JP225/USD 5-minute index-price proxy; no intra-minute sequence.",
      "five_minute_crosscheck":equality,
      "five_minute_raw_rows":five.height,
      "source_independence_not_established":True,
      "native_engine_year":2026,
      "native_ordering":"1-minute OHLC cannot determine whether entry or protection level was touched first.",
      "metrics":controls,
      "pessimistic_R":gate["pessimistic_sensitivity_total_R"],
      "pessimistic_is_native_replay":False,
      "effective_stop":"fixed 50 index points, unchanged frozen B0",
      "required_before_promotion":[
        "Tick or timestamped BID/ASK updates from same tradable Nikkei venue covering the exact entry/stop events",
        "Verify contract, currency and tick, session and trading calendar; calibrate spread, slippage and gaps",
        "Native order-entry OCO/stop sequence with replayable fill event ordering; independent B0 parity tests",
        "Chronologically independent unseen test not already mined",
      ]
    }
    (OUT/"nikkei_execution_validation.json").write_text(json.dumps(result,indent=2,default=str)+"\n")
    print("NIKKEI_1M",one.height,"5M",five.height)
    print("5M_COMPARISON",equality)
    print("AMBIGUOUS",matched.height,"/",rows.height)
    print("NATIVE_R",round(controls["observed_native_total_R"],3),"CONSERVATIVE_NON_NATIVE_R",round(gate["pessimistic_sensitivity_total_R"],3))
    print("STOP_PERCENT_MEDIAN",round(controls["stop_distance_pct_of_entry"]["median"],4))
if __name__=="__main__":main()
