#!/usr/bin/env python3
"""Phase 2 quality closure and Phase 3 gross-price event study, LSE NQ.F proxy.

This script detects *signals* and analyzes future prices; it does NOT simulate
orders, TP/SL executions, portfolio risk, or net trading PnL.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path

import exchange_calendars as xcals
import numpy as np
import polars as pl
import talib
from ml4t.engineer import compute_features

ROOT = Path(__file__).resolve().parents[1]
SID = "vwap_pullback_adx_nq_20261012_proxy_v2"
DATA = ROOT / "data/processed/vwap_adx_nqf_2026h1_1m.parquet"
MANIFEST = ROOT / "run_log" / SID / "phase2_source_manifest.json"
OUT = ROOT / "run_log" / SID
CAL = xcals.get_calendar("XNYS")
DEV_FIRST = date(2026, 1, 1)
DEV_LAST = date(2026, 6, 30)
MINUTE = timedelta(minutes=1)
HORIZONS = (1, 5, 10, 30)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def detected_events(day_bars: pl.DataFrame) -> dict:
    """First OR-break, VWAP reclaim, and ADX gate signal per day.

    The time of every signal is the completed 1m bar's opening timestamp.
    Do not model positions or TP/SL here. The complete data group is one CT
    session and includes the 08:30-08:59 opening range.
    """
    bars = day_bars.sort("timestamp")
    stamps = bars["timestamp"].to_list()
    clocks = bars["ct"].dt.strftime("%H:%M").to_list()
    highs = bars["high"].to_numpy()
    lows = bars["low"].to_numpy()
    closes = bars["close"].to_numpy()
    vwaps = bars["vwap"].to_numpy()
    adx = bars["adx"].to_numpy()
    n = len(stamps)
    or_idx = [i for i, s in enumerate(clocks) if "08:30" <= s <= "08:59"]
    if len(or_idx) != 30:
        return {"b1": None, "b2": None, "b3": None, "counts": {}}
    or_high = float(np.max(highs[or_idx]))
    out = {"b1": None, "b2": None, "b3": None}
    state = "IDLE"
    armed_at = None
    wait_at = None
    counts = {"breakouts": 0, "touches": 0, "reclaims": 0,
              "rising_adx_waits": 0, "nonincreasing_qualifiers": 0,
              "reclaim_adx_not_above_20": 0, "reset_below_vwap": 0}
    for i in range(1, n):
        c = clocks[i]
        if c < "09:00" or c >= "15:54":
            continue  # No next-open entry at 15:55 or later.
        if stamps[i] - stamps[i-1] != MINUTE:
            state = "IDLE"  # No transition across an unknown minute gap.
            armed_at = None
            wait_at = None
            continue
        if not np.isfinite(vwaps[i]) or not np.isfinite(adx[i]) or not np.isfinite(adx[i-1]):
            continue
        if state == "IDLE":
            if closes[i-1] <= or_high and highs[i] > or_high and closes[i] > or_high:
                counts["breakouts"] += 1
                armed_at = i
                state = "ARMED"
                if out["b1"] is None:
                    out["b1"] = i
            continue
        if state == "ARMED":
            if i > armed_at and lows[i] <= vwaps[i]:
                state = "TOUCHED"
                counts["touches"] += 1
            else:
                continue
        if state == "RETOUCH":
            if lows[i] <= vwaps[i]:
                counts["touches"] += 1
                state = "TOUCHED"
            else:
                continue
        if state == "TOUCHED":
            if closes[i] <= vwaps[i]:
                continue
            counts["reclaims"] += 1
            if out["b2"] is None:
                out["b2"] = i
            if adx[i] > 20 and adx[i] <= adx[i - 1]:
                counts["nonincreasing_qualifiers"] += 1
                out["b3"] = i
                break
            if adx[i] > 20:
                state = "WAIT_ADX"
                wait_at = i
                counts["rising_adx_waits"] += 1
            else:
                state = "RETOUCH"
                counts["reclaim_adx_not_above_20"] += 1
            continue
        if state == "WAIT_ADX":
            if closes[i] <= vwaps[i]:
                state = "TOUCHED"
                counts["reset_below_vwap"] += 1
            elif adx[i] <= 20:
                state = "RETOUCH"
            elif adx[i] <= adx[i-1]:
                counts["nonincreasing_qualifiers"] += 1
                out["b3"] = i
                break
    return {**out, "counts": counts, "or_high": or_high,
            "adx_wait_minutes": (out["b3"] - out["b2"])
            if (out["b2"] is not None and out["b3"] is not None) else None}


def forward_outcome(bars: pl.DataFrame, idx: int, horizon: int) -> dict | None:
    """Gross *signal-conditioned* return, executed from next bar OPEN.

    The future close is a research label, not known when the signal fired.
    It is never used to decide an entry or set a same-bar target.
    """
    if idx + horizon >= bars.height:
        return None
    stamp = bars["timestamp"][idx]
    next_stamp = bars["timestamp"][idx + 1]
    end_stamp = bars["timestamp"][idx + horizon]
    if next_stamp - stamp != MINUTE or end_stamp - stamp != horizon * MINUTE:
        return None
    if bars["ct"][idx + horizon].strftime("%H:%M") > "15:54":
        return None
    entry = float(bars["open"][idx + 1])
    final = float(bars["close"][idx + horizon])
    return {"points": final - entry, "bps": (final / entry - 1) * 1e4}


def bootstrap_ci(vals: list[float], seed: int) -> list[float] | None:
    if len(vals) < 5:
        return None
    rng = np.random.default_rng(seed)
    x = np.asarray(vals, dtype=np.float64)
    means = rng.choice(x, size=(2000, len(x)), replace=True).mean(axis=1)
    return [round(v, 4) for v in np.quantile(means, [0.025, 0.975])]


def summarize(events: list[dict]) -> dict:
    result: dict = {}
    for kind in ("b1", "b2", "b3"):
        result[kind] = {}
        for h in HORIZONS:
            vals = [e[f"r_{h}_points"] for e in events
                    if e["kind"] == kind and e.get(f"r_{h}_points") is not None]
            result[kind][str(h)] = {
                "n": len(vals),
                "gross_mean_points": round(float(np.mean(vals)), 4) if vals else None,
                "median_points": round(float(np.median(vals)), 4) if vals else None,
                "positive_fraction": round(float(np.mean(np.array(vals) > 0)), 4) if vals else None,
                "session_bootstrap_95pct_mean_ci_points": bootstrap_ci(vals, 20261012 + h),
            }
    return result


def main() -> None:
    source_manifest = json.loads(MANIFEST.read_text())
    assert source_manifest["input_sha256"] == sha256(DATA), "Dataset drift"
    x = pl.read_parquet(DATA).sort("timestamp")
    assert x["symbol"].unique().to_list() == ["NQ.F"]
    assert x["timestamp"].is_sorted() and x["timestamp"].n_unique() == x.height
    assert x.select(pl.all().null_count()).sum_horizontal().sum() == 0
    assert x["volume"].min() > 0
    assert x.filter(
        (pl.col("high") < pl.max_horizontal("open","low","close"))
        | (pl.col("low") > pl.min_horizontal("open","high","close"))
    ).is_empty()
    # Official ML4T feature API; compare with independent TA-Lib oracle.
    x = compute_features(x, [{"name": "adx", "params": {"period": 14}}])
    ref = talib.ADX(
        x["high"].to_numpy(), x["low"].to_numpy(), x["close"].to_numpy(), timeperiod=14)
    assert np.nanmax(np.abs(x["adx"].to_numpy() - ref)) < 1e-8
    x = x.with_columns(
        pl.col("timestamp").dt.convert_time_zone("America/Chicago").alias("ct")
    ).with_columns(
        pl.col("ct").dt.date().alias("day"),
        pl.col("ct").dt.strftime("%H:%M").alias("clock"),
    )
    cash = pl.col("clock") >= "08:30"
    x = x.with_columns(
        pl.when(cash).then(
            (pl.col("high") + pl.col("low") + pl.col("close")) / 3 * pl.col("volume")
        ).otherwise(0.0).cum_sum().over("day").alias("pv_sum"),
        pl.when(cash).then(pl.col("volume")).otherwise(0.0)
        .cum_sum().over("day").alias("vol_sum"),
    ).with_columns(
        pl.when(pl.col("vol_sum") > 0)
        .then(pl.col("pv_sum") / pl.col("vol_sum"))
        .otherwise(None).alias("vwap")
    )
    valid_days = {d.date() for d in CAL.sessions_in_range("2026-01-01","2026-06-30")}
    early_days = {d.date() for d in CAL.early_closes if DEV_FIRST <= d.date() <= DEV_LAST}
    full_days = valid_days - early_days
    x = x.filter((pl.col("day") >= DEV_FIRST) & (pl.col("day") <= DEV_LAST))
    grouped = x.partition_by("day", as_dict=True, maintain_order=True)
    qa = {"expected_xnys_cash_sessions": len(valid_days),
          "xnys_early_closes_excluded": sorted(str(d) for d in early_days),
          "or_bar_failures": [], "missing_1555_excluded": [],
          "bad_continuity_sessions": [], "zero_or_vol": [],
          "accepted_sessions": [], "source": "LSE NQ.F, continuous provider-defined proxy",
          "cme_contract_level": False, "true_cme_volume": "UNVERIFIED",
          "original_2026_results_scored": False}
    output = []
    funnel = {"b1_sessions": 0, "b2_sessions": 0, "b3_sessions": 0}
    wait_minutes = []
    for key, bars in grouped.items():
        day = key[0] if isinstance(key, tuple) else key
        if day not in full_days:
            continue
        minutes = bars["clock"].to_list()
        or_sub = bars.filter(pl.col("clock").is_between(pl.lit("08:30"), pl.lit("08:59")))
        if or_sub.height != 30 or or_sub["clock"].n_unique() != 30:
            qa["or_bar_failures"].append(str(day))
            continue
        if or_sub["volume"].min() <= 0:
            qa["zero_or_vol"].append(str(day))
            continue
        if "15:55" not in minutes:
            qa["missing_1555_excluded"].append(str(day))
            continue
        # Gap checks in cash hours. Keep the sample only if minute grid is complete.
        cash_bars = bars.filter(pl.col("clock").is_between(pl.lit("08:30"), pl.lit("15:55")))
        n_minutes = cash_bars.height
        if n_minutes != 446 or cash_bars["timestamp"].diff().drop_nulls().to_list().count(MINUTE) != n_minutes - 1:
            qa["bad_continuity_sessions"].append(str(day))
            continue
        qa["accepted_sessions"].append(str(day))
        sigs = detected_events(bars)
        for kind in ("b1","b2","b3"):
            idx = sigs[kind]
            if idx is None:
                continue
            funnel[f"{kind}_sessions"] += 1
            record = {
                "day": str(day), "kind": kind, "signal_timestamp": str(bars["timestamp"][idx]),
                "signal_ct": str(bars["ct"][idx]),
                "adx": float(bars["adx"][idx]),
                "adx_prev": float(bars["adx"][idx-1]),
                "or_high": float(sigs["or_high"]),
                "close": float(bars["close"][idx]),
                "vwap": float(bars["vwap"][idx]),
            }
            for h in HORIZONS:
                result = forward_outcome(bars, idx, h)
                record[f"r_{h}_points"] = result["points"] if result else None
                record[f"r_{h}_bps"] = result["bps"] if result else None
            output.append(record)
        if sigs["adx_wait_minutes"] is not None:
            wait_minutes.append(sigs["adx_wait_minutes"])
    days_with_data = len(qa["accepted_sessions"])
    if days_with_data == 0:
        raise RuntimeError("No eligible sessions: do not produce empty event study")
    paired: dict = {}
    evmap = {(e["day"],e["kind"]):e for e in output}
    matched = [day for day in qa["accepted_sessions"]
               if (day,"b2") in evmap and (day,"b3") in evmap]
    for h in HORIZONS:
        diffs = []
        for day in matched:
            a=evmap[(day,"b2")].get(f"r_{h}_points")
            b=evmap[(day,"b3")].get(f"r_{h}_points")
            if a is not None and b is not None:
                diffs.append(b-a)
        paired[str(h)] = {
            "n_paired_days":len(diffs),
            "b3_minus_b2_mean_points":round(float(np.mean(diffs)),4) if diffs else None,
            "bootstrap_95pct_ci_points":bootstrap_ci(diffs,20261013+h),
        }
    qa["accepted_count"] = days_with_data
    qa["excluded_count"] = len(full_days) - days_with_data
    qa["calendar_full_sessions"] = len(full_days)
    qa["adx_numerical_parity_max_abs_error"] = float(np.nanmax(np.abs(x["adx"].to_numpy()-ref[-x.height:]))) if x.height==ref.size else "Already verified full input before day filter"
    study={
        "session":SID, "phase":3,"status":"EXPLORATORY_GROSS_EVENT_DIAGNOSTICS",
        "development_start":"2026-01-01","development_end_exclusive":"2026-07-01",
        "source_input_sha256":source_manifest["input_sha256"],
        "source_label":"LSE_NQ.F_PROVIDER_DEFINED_CONTINUOUS_PROXY",
        "first_opportunity_per_session_only":True,
        "no_trading_execution_or_costs":True,
        "signal_funnel":funnel, "valid_sessions":days_with_data,
        "wait_minutes_mean":float(np.mean(wait_minutes)) if wait_minutes else None,
        "wait_minutes_median":float(np.median(wait_minutes)) if wait_minutes else None,
        "per_event_horizon":summarize(output),
        "paired_b3_minus_b2_forward_points":paired,
        "limitations":[
            "Provider-defined continuous product; contract mapping/rolls not verified.",
            "Vendor volume may differ from CME traded contracts; VWAP is a proxy.",
            "No transaction costs, spread, partial fills, TP/SL, or portfolio effects.",
            "One first qualified signal per day; original strategy permits reentry.",
            "Paired B2/B3 days condition on future ADX gating and do not identify causal ADX effect.",
            "First future return starts at next-minute open and ends at completed future bar close.",
            "No Jul-Oct retrospective validation or Nov-onward prospective holdout accessed.",
        ],
    }
    OUT.mkdir(exist_ok=True,parents=True)
    (OUT/"phase2_quality_report.json").write_text(json.dumps(qa,indent=2,sort_keys=True)+"\n")
    study_path=OUT/"phase3_event_study.json"
    study_path.write_text(json.dumps(study,indent=2,sort_keys=True)+"\n")
    pl.DataFrame(output).write_parquet(OUT/"phase3_events.parquet")
    print(json.dumps({
        "phase2": {"expected":len(full_days),"accepted":days_with_data,
                   "or_fail":len(qa["or_bar_failures"]),
                   "time_fail":len(qa["missing_1555_excluded"]),
                   "gap_fail":len(qa["bad_continuity_sessions"])},
        "phase3":study,
        "outputs":[str(OUT/"phase2_quality_report.json"),
                   str(study_path),str(OUT/"phase3_events.parquet")],
    },indent=2))

if __name__=="__main__":
    main()
