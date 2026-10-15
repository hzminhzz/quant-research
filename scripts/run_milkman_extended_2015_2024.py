"""Pre-registered 2015-2024 annual native ML4T CFD development trials.

Annual trials are independent $100k equity books. Never chain as continuous
2015-2024 NAV or claim original CME/stock/options author parity.
One case-year per invocation for bounded VPS memory and append-only evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import traceback
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
from ml4t.backtest import DataFeed, Engine
from ml4t.backtest.analytics import max_drawdown, sharpe_ratio, sortino_ratio
from ml4t.engineer import compute_features

from scripts.run_milkman_native_cfd_20261014 import (
    aggregate,
    clean,
    config,
    globex_sessions,
    rth_daily,
)
from src.strategies.independent_seven_data import load_daily
from src.strategies.milkman_native_broker import (
    BuyDayOvernight,
    EmaNextDayReversion,
    HourlyBilboUnderlying,
    SwingGateShort,
)
from src.strategies.milkman_native_features import (
    attach_prior_daily_ema_gate,
    box_episode_signals,
    hourly_bilbo_features,
    legends_buy_day_features,
    legends_ema_daily_setups,
    swing_golden_gate_features,
)

ROOT = Path("/home/quant/dev/quant/ml4t-data/.data/store")
OUT = Path("run_log/milkman_cfd_2015_2024_dev_extension_v1")
CASES = ("legends_buy_day", "legends_ema", "bilbo_box_v2", "swing_golden_gate")
EARLIEST = 2013
LAST = 2024


def _time(year: int) -> tuple[datetime, datetime]:
    if not (2015 <= year <= 2024):
        raise ValueError("Only pre-2025 development years are authorized")
    return datetime(year, 1, 1, tzinfo=UTC), datetime(year + 1, 1, 1, tzinfo=UTC)


def _minute(alias: str, year: int, *, minimum_annual_rows: int = 220_000) -> tuple[pl.DataFrame, dict]:
    """Read only years [year-2..year], for prior-only indicator warmup."""
    root = ROOT / f"index_minute_{alias}"
    files = sorted(p for y in range(year - 2, year + 1)
                   for p in (root / f"year={y}").rglob("data.parquet"))
    if not files:
        raise FileNotFoundError(f"Missing source for {alias} {year}")
    start, end = _time(year)
    scan = pl.scan_parquet(
        [str(p) for p in files], hive_partitioning=False,
        cast_options=pl.ScanCastOptions(
            datetime_cast="millisecond-upcast", integer_cast="allow-float")
    ).select("timestamp", "open", "high", "low", "close", "volume")
    df = scan.filter(pl.col("timestamp") < pl.lit(end)).collect().sort("timestamp")
    if df.is_empty() or df["timestamp"].dtype.time_zone != "UTC":
        raise ValueError("Invalid UTC source")
    if df["timestamp"].n_unique() != df.height:
        raise ValueError("Duplicate market timestamps")
    if df.filter((pl.col("high") < pl.max_horizontal("open","close","low")) |
                 (pl.col("low") > pl.min_horizontal("open","close","high")) |
                 (pl.col("low") <= 0)).height:
        raise ValueError("Invalid OHLC ranges")
    active = df.filter((pl.col("timestamp") >= start) & (pl.col("timestamp") < end))
    if active.height < minimum_annual_rows:
        raise ValueError(f"Coverage deficit {alias} {year}: {active.height} minutes; gate={minimum_annual_rows}")
    days = active.select(pl.col("timestamp").dt.date().n_unique()).item()
    return df, {"store":str(root), "raw_partitions":len(files),
                "raw_rows_with_warmup":df.height, "execution_raw_rows":active.height,
                "active_dates":days, "first":str(active["timestamp"].min()),
                "last":str(active["timestamp"].max()),
                "timestamp_semantics":"minute bar OPEN UTC; +1min at decision availability",
                "volume_semantics":"Dukascopy broker activity, not CME exchange volume"}


def _rth_15m(raw: pl.DataFrame) -> pl.DataFrame:
    f = aggregate(raw, 15, et_start=9, et_end=16)
    t = pl.col("timestamp").dt.convert_time_zone("America/New_York")
    minute = t.dt.hour().cast(pl.Int32) * 60 + t.dt.minute().cast(pl.Int32)
    # Only 09:30-16:00 Eastern *completed* RTH bars, 26/day.
    return f.filter((minute >= 9 * 60 + 45) & (minute <= 16 * 60))


def _feed(prices: pl.DataFrame, sig: pl.DataFrame, start: datetime, end: datetime, asset: str):
    px = prices.filter(
        (pl.col("timestamp") >= start) & (pl.col("timestamp") < end)
    ).select("timestamp","open","high","low","close","volume").with_columns(asset=pl.lit(asset))
    if px.is_empty() or px["timestamp"].max() >= end:
        raise ValueError("Empty or out-of-window execution feed")
    sg = sig.filter((pl.col("timestamp") >= px["timestamp"].min()) &
                    (pl.col("timestamp") <= px["timestamp"].max()))
    sg = sg.with_columns(asset=pl.lit(asset))
    if px["timestamp"].n_unique() != px.height or sg["timestamp"].n_unique() != sg.height:
        raise ValueError("Duplicate price/signal timestamps")
    if sg.height and sg["timestamp"].max() >= end:
        raise ValueError("Protected/foreign signal timestamp")
    return px, sg


def inputs(case: str, year: int):
    start, end = _time(year)
    alias = "NQ" if case in ("legends_ema","bilbo_box_v2") else "ES"
    if case == "swing_golden_gate":
        # 2013 start protects 14-month ATR seed at January 2015.
        daily, manifest = load_daily("ES", max(2012,year - 2), year, end_exclusive=end)
        d = daily.with_columns(
            pl.col("timestamp").dt.date().cast(pl.Datetime("us"))
            .dt.replace_time_zone("America/New_York").dt.offset_by("17h")
            .dt.convert_time_zone("UTC").alias("timestamp")
        ).with_columns(
            pl.col("timestamp").dt.convert_time_zone("America/New_York")
            .dt.strftime("%Y-%m").alias("month")
        )
        m = d.group_by("month").agg(
            pl.col("timestamp").max().alias("timestamp"),
            pl.col("open").sort_by("timestamp").first().alias("open"),
            pl.col("high").max().alias("high"), pl.col("low").min().alias("low"),
            pl.col("close").sort_by("timestamp").last().alias("close"),
            pl.col("volume").sum().alias("volume"), pl.len().alias("sessions")
        ).filter(pl.col("sessions") >= 12).sort("timestamp").drop("sessions")
        f = swing_golden_gate_features(d, m).sort("timestamp").with_columns(
            (pl.col("month") != pl.col("month").shift(-1))
            .fill_null(True).alias("last_month_session")
        )
        fields = ["down_gate_open","down_gate_complete","short_stop","short_target",
                  "prev_close_above_ema21","last_month_session"]
        px, sg = _feed(d, f.select("timestamp",*fields), start, end, alias)
        return px, sg, SwingGateShort(alias), {"data":manifest,
                   "adjustment":"17:00 America/New_York CFD availability, monthly prior-only ATR"}

    # Amendment 1: per-strategy clock eligibility, not universal Globex rows.
    raw, manifest = _minute(alias, year, minimum_annual_rows=(
        220_000 if case == "legends_buy_day" else 180_000))
    # Source minute bars are OPEN labeled, decision becomes available at +1m.
    px = raw.with_columns((pl.col("timestamp") + pl.duration(minutes=1)).alias("timestamp"))
    if case == "legends_buy_day":
        ss = globex_sessions(raw)
        feature = legends_buy_day_features(ss.select(
            "timestamp","open","high","low","close","volume"))
        setup = ss.select("timestamp").with_columns(
            feature["setup_complete"].alias("entry_at_reopen")
        ).filter(pl.col("entry_at_reopen"))
        tm = pl.col("timestamp").dt.convert_time_zone("America/New_York")
        exit_clock = (tm.dt.hour() == 9) & (tm.dt.minute() == 29)
        exit_signal = raw.filter(exit_clock).select(
            (pl.col("timestamp") + pl.duration(minutes=1)).alias("timestamp")
        ).with_columns(exit_at_0930=pl.lit(True))
        sig = px.select("timestamp").join(setup, on="timestamp", how="left").join(
            exit_signal, on="timestamp", how="left")
        strat = BuyDayOvernight(alias)
    elif case == "legends_ema":
        bars15 = _rth_15m(raw)
        if bars15.is_empty():
            raise ValueError("No complete 15m RTH bars")
        full_rth_days = bars15.group_by("session_date").len().filter(pl.col("len") == 26)
        valid_this_year = full_rth_days.filter(pl.col("session_date").dt.year() == year).height
        if valid_this_year < 200:
            raise ValueError(f"Insufficient full RTH sessions {year}: {valid_this_year}")
        features = legends_ema_daily_setups(bars15, lookback_sessions=252)
        # Exclude short/half sessions from threshold and trial eligibility.
        # Current implementation's percentile is from prior calendar sessions,
        # including partial days; this limitation is logged in reports.
        daily = features.select("session_date","setup_complete").sort("session_date").with_columns(
            pl.col("setup_complete").shift(1).fill_null(False).alias("prior_setup")
        ).select("session_date","prior_setup")
        permin = px.select("timestamp").with_columns(
            pl.col("timestamp").dt.convert_time_zone("America/New_York")
            .dt.date().alias("session_date")
        ).join(daily,on="session_date",how="left")
        ema = compute_features(
            bars15.select("timestamp","open","high","low","close","volume"),
            [{"name":"ema","params":{"period":20},"output":"ema20"}],
            timestamp_col="timestamp"
        )
        sig = permin.join_asof(
            ema.select("timestamp",pl.col("ema20").alias("prior_completed_ema")),
            on="timestamp", strategy="backward"
        ).select("timestamp","prior_setup","prior_completed_ema")
        strat = EmaNextDayReversion(alias)
    else:
        bars15 = _rth_15m(raw)
        rth = rth_daily(bars15)
        h = aggregate(raw,60,et_start=4,et_end=20)
        valid_hours = h.filter(pl.col("timestamp").dt.year() == year).height
        if valid_hours < 2500:
            raise ValueError(f"Insufficient complete ETH hours {year}: {valid_hours}")
        feat = attach_prior_daily_ema_gate(hourly_bilbo_features(h),rth)
        atr = compute_features(rth.select("timestamp","open","high","low","close","volume"),
                               [{"name":"atr","params":{"period":14},"output":"datr14"}],
                               timestamp_col="timestamp")
        atr = atr.with_columns(
            pl.col("timestamp").dt.convert_time_zone("America/New_York")
            .dt.date().alias("et_day"),
            pl.col("datr14").shift(1).alias("prior_datr14")
        )
        feat=feat.join(atr.select("et_day","prior_datr14"),on="et_day",how="left")
        sig = box_episode_signals(feat,mode="hourly").filter(
            pl.col("box_close_break") & pl.col("prior_datr14").is_finite()
        ).select("timestamp","box_low","prior_datr14").with_columns(
            entry_signal=pl.lit(True))
        # Align to native 5-minute bar-close event clock.
        five = aggregate(raw,5,et_start=4,et_end=20)
        px = five
        strat = HourlyBilboUnderlying(alias)
    px,sg = _feed(px, sig, start, end, alias)
    if case == "legends_buy_day":
        manifest["globex_sessions_sample"] = int(ss.height)
        manifest["armed_events_in_year"] = int(sg["entry_at_reopen"].fill_null(False).sum())
    elif case == "legends_ema":
        manifest["complete_rth_15min_bars"] = bars15.height
        manifest["qualifying_full_rth_sessions"] = int((features["n_15m_bars"]==26).sum())
        manifest["prior_strong_day_flags_in_year"] = int(
            sg.filter(pl.col("timestamp").dt.convert_time_zone("America/New_York").dt.hour()==9)
            ["prior_setup"].fill_null(False).sum())
    else:
        manifest["eth_60min_bars"] = h.height
        manifest["box_signals_in_year"] = int(sg["entry_signal"].fill_null(False).sum())
    return px,sg,strat,{"data":manifest, "source_index_cfd":alias}


def filehash(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(case: str, year: int, root: Path):
    _time(year)
    if case not in CASES:
        raise ValueError(case)
    folder = root / case / str(year)
    if folder.exists():
        raise FileExistsError(f"Trial attempt already exists {folder}")
    folder.mkdir(parents=True)
    manifest={"program":"milkman_2015_2024_cfd_dev_extension_v1",
              "case":case,"year":year,"attempt_started":datetime.now(UTC).isoformat(),
              "status":"STARTED","holdout":"2025-2026 LOCKED",
              "unit":"independent annual $100k book; do not chain as continuous NAV",
              "costs":"2 bps commission + 2 bps slippage each side"}
    (folder/"attempt.json").write_text(json.dumps(manifest,indent=2)+"\n")
    try:
        px,signals,strategy,src=inputs(case,year)
        px.write_parquet(folder/"prices.parquet")
        signals.write_parquet(folder/"signals.parquet")
        print("INPUT",case,year,px.height,signals.height,flush=True)
        engine=Engine(DataFeed(prices_df=px,signals_df=signals),strategy,config())
        result=engine.run()
        df_eq=result.to_equity_dataframe()
        trades=result.to_trades_dataframe()
        fills=result.to_fills_dataframe()
        if fills.height and fills["timestamp"].dtype.time_zone is None:
            fills=fills.with_columns(pl.col("timestamp").dt.replace_time_zone("UTC"))
        for n,df in (("equity.csv",df_eq),("trades.csv",trades),
                     ("fills.csv",fills),("rejected_orders.csv",
                      result.to_rejected_orders_dataframe())):
            df.write_csv(folder/n)
        if not df_eq.height:
            raise ValueError("Empty native equity")
        pnl = float(trades["pnl"].sum()) if trades.height else 0.
        delta = float(df_eq["equity"][-1]-100000.)
        if abs(delta-pnl)>0.02:
            raise ValueError(f"Ledger reconciliation failed {delta} vs {pnl}")
        if fills.height and not ((fills["timestamp"].min()>=px["timestamp"].min()) and
                                 (fills["timestamp"].max()<=px["timestamp"].max())):
            raise ValueError("Fill outside data")
        daily = df_eq.with_columns(
            pl.col("timestamp").dt.convert_time_zone("America/New_York")
            .dt.date().alias("session")
        ).group_by("session").agg(
            pl.col("equity").sort_by("timestamp").last().alias("equity")
        ).sort("session")
        returns=daily["equity"].pct_change().fill_null(0).to_numpy()
        completed=(trades.filter(pl.col("status")=="closed").height if trades.height else 0)
        pending=(trades.filter(pl.col("status")!="closed").height if trades.height else 0)
        summary={**manifest,"status":"NATIVE_RECONCILED" if pending==0 else "INCONCLUSIVE_OPEN_AT_YEAR_BOUNDARY",
                 "attempt_finished":datetime.now(UTC).isoformat(),
                 "input":src,"signals_rows":signals.height,
                 "prices_rows":px.height,"hashes":{n:filehash(folder/n) for n in
                                                  ("prices.parquet","signals.parquet")},
                 "fills":fills.height,"closed_trades":completed,"open_trades":pending,
                 "rejections":len(result.rejected_orders),
                 "broker_submissions":strategy.decisions,
                 "net_return_pct":100*delta/100000,
                 "native_daily_sharpe":float(sharpe_ratio(returns)) if completed else None,
                 "native_daily_sortino":float(sortino_ratio(returns)) if completed else None,
                 "native_daily_maxdd":float(max_drawdown(daily["equity"].to_list())[0]),
                 "native_bar_sharpe_not_comparable":result.metrics.get("sharpe"),
                 "total_costs":result.metrics.get("total_costs"),
                 "pnl_reconcile_abs":abs(delta-pnl),
                 "limitations":["CFD index aliases, not author's CME futures/stocks/options",
                                "Annual capital reset: not continuous decade equity",
                                "Not a historical broker bid-ask/slippage/financing qualification",
                                "Overnight hours and DST follow CFD source availability"],
                }
        (folder/"report.json").write_text(json.dumps(clean(summary),indent=2,allow_nan=False)+"\n")
        print("RESULT",json.dumps({k:summary[k] for k in
              ("case","year","status","closed_trades","net_return_pct","native_daily_sharpe")}),flush=True)
        return summary
    except Exception:
        manifest.update(status="FAILED",error=traceback.format_exc(),
                        attempt_finished=datetime.now(UTC).isoformat())
        (folder/"failed.json").write_text(json.dumps(manifest,indent=2)+"\n")
        raise


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--case",choices=CASES,required=True)
    p.add_argument("--year",type=int,required=True)
    p.add_argument("--out",type=Path,default=OUT)
    a=p.parse_args()
    execute(a.case,a.year,a.out)


if __name__=="__main__":
    main()
