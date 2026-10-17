"""Prepare tick trades plus best bid/offer events from the source top10 feed.

This output is not full top10 L2 depth. Funding events are not prepared here.
"""

import time
from pathlib import Path
import numpy as np
import polars as pl

from hftbacktest import (
    BUY_EVENT,
    SELL_EVENT,
    DEPTH_EVENT,
    TRADE_EVENT,
    EXCH_EVENT,
    LOCAL_EVENT,
)
from hftbacktest.data.utils.binancefutures import event_dtype

ROOT = Path(__file__).resolve().parents[1]
STORE_BASE = Path("/home/quant/dev/quant/ml4t-data/.data/store")
OUT_DIR = ROOT / "data/hftbacktest"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def convert_and_save_day(year: int, month: int, day: int):
    date_str = f"{year}{month:02d}{day:02d}"
    out_btc = OUT_DIR / f"btcusdt_{date_str}.npz"
    out_eth = OUT_DIR / f"ethusdt_{date_str}.npz"

    if out_btc.exists() and out_eth.exists():
        print(f"Data for {date_str} already converted at {out_btc.name} and {out_eth.name}!")
        return

    f_btc_tick = STORE_BASE / f"crypto_futures_tick_BTCUSDT_PERP/year={year}/month={month}/day={day}/data.parquet"
    f_eth_tick = STORE_BASE / f"crypto_futures_tick_ETHUSDT_PERP/year={year}/month={month}/day={day}/data.parquet"
    f_btc_l2 = STORE_BASE / f"crypto_futures_l2_BTCUSDT_PERP_top10/year={year}/month={month:02d}/day={day:02d}/data.parquet"
    f_eth_l2 = STORE_BASE / f"crypto_futures_l2_ETHUSDT_PERP_top10/year={year}/month={month:02d}/day={day:02d}/data.parquet"
    print(f"Converting Day {day} (BTC & ETH)...")
    t0 = time.time()

    for sym, f_l2, f_tick, out_path in [("BTC", f_btc_l2, f_btc_tick, out_btc), ("ETH", f_eth_l2, f_eth_tick, out_eth)]:
        df_l = pl.read_parquet(f_l2).select(["timestamp", "bid_p1", "bid_q1", "ask_p1", "ask_q1"]).drop_nulls()
        df_t = pl.read_parquet(f_tick).select(["timestamp", "price", "qty", "side"]).drop_nulls()

        n_l = len(df_l)
        n_t = len(df_t)
        total_events = n_l * 2 + n_t

        events = np.empty(total_events, dtype=event_dtype)
        ts_l_ns = (df_l["timestamp"].to_numpy() * 1_000_000).astype(np.int64)

        # Bids
        events["ev"][:n_l] = DEPTH_EVENT | BUY_EVENT | EXCH_EVENT | LOCAL_EVENT
        events["exch_ts"][:n_l] = ts_l_ns
        events["local_ts"][:n_l] = ts_l_ns
        events["px"][:n_l] = df_l["bid_p1"].to_numpy()
        events["qty"][:n_l] = df_l["bid_q1"].to_numpy()
        events["order_id"][:n_l] = 0
        events["ival"][:n_l] = 0
        events["fval"][:n_l] = 0.0

        # Asks
        idx = n_l
        events["ev"][idx:idx + n_l] = DEPTH_EVENT | SELL_EVENT | EXCH_EVENT | LOCAL_EVENT
        events["exch_ts"][idx:idx + n_l] = ts_l_ns
        events["local_ts"][idx:idx + n_l] = ts_l_ns
        events["px"][idx:idx + n_l] = df_l["ask_p1"].to_numpy()
        events["qty"][idx:idx + n_l] = df_l["ask_q1"].to_numpy()
        events["order_id"][idx:idx + n_l] = 0
        events["ival"][idx:idx + n_l] = 0
        events["fval"][idx:idx + n_l] = 0.0

        # Trades
        idx += n_l
        ts_t_ns = (df_t["timestamp"].to_numpy() * 1_000_000).astype(np.int64)
        sides = df_t["side"].to_numpy()
        side_flags = np.where(sides == "B", BUY_EVENT, SELL_EVENT)

        events["ev"][idx:] = TRADE_EVENT | side_flags | EXCH_EVENT | LOCAL_EVENT
        events["exch_ts"][idx:] = ts_t_ns
        events["local_ts"][idx:] = ts_t_ns
        events["px"][idx:] = df_t["price"].to_numpy()
        events["qty"][idx:] = df_t["qty"].to_numpy()
        events["order_id"][idx:] = 0
        events["ival"][idx:] = 0
        events["fval"][idx:] = 0.0
        events.sort(order="exch_ts")
        np.savez(out_path, data=events)
        print(f"  Saved {sym} Day {day}: {len(events):,} events to {out_path.name}")

    print(f"Day {day} complete in {time.time()-t0:.2f}s!")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--month", type=int, default=2)
    parser.add_argument("--days", type=int, default=28)
    args = parser.parse_args()

    for d in range(1, args.days + 1):
        convert_and_save_day(args.year, args.month, d)
