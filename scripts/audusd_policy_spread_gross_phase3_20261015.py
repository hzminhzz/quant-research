"""Predeclared AUDUSD macro-rate gross-price Phase 3 signal screen.

prepare -> freeze via research_session.py init -> evaluate -> record trial.
No perpetual fills, swaps, funding, homegrown backtest or holdout price access.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import polars as pl
import requests

ROOT = Path(__file__).resolve().parents[1]
NAME = "audusd_policy_spread_gross_phase3_20261015_v1"
SOURCE = Path("/home/quant/dev/quant/ml4t-data/.data/store/forex_minute_AUDUSD")
METADATA = SOURCE.parent / ".metadata/forex_minute_AUDUSD.json"
DATA = ROOT / "data/processed" / NAME / "monthly_endpoints.parquet"
SOURCES = DATA.parent / "official_rate_provenance.json"
CONTROL = ROOT / "run_log/research_sessions" / NAME / "frozen_spec.json"
OUT = ROOT / "run_log/diagnostics" / NAME
METRICS = OUT / "phase3_metrics.json"
REPORT = OUT / "phase3_signal_evaluation.md"
ROWS = OUT / "phase3_monthly_price_proxy.csv"
NY = ZoneInfo("America/New_York")
HOLDO = datetime(2025, 1, 1, tzinfo=UTC)
RBA_URL = "https://www.rba.gov.au/statistics/cash-rate/"
FED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTARU"
MONTHS = 120
BLOCK = 6
RESAMPLES = 5000
SEED = 7


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_hash(path: Path) -> str:
    return sha256(path.read_bytes())


@lru_cache(maxsize=700)
def _day(day: date) -> pl.DataFrame:
    if not (2014 <= day.year <= 2024):
        raise ValueError("Protected/unsupported quote date")
    p = SOURCE / f"year={day.year}/month={day.month}/day={day.day}/data.parquet"
    if not p.exists():
        return pl.DataFrame(
            schema={"timestamp": pl.Datetime("us", "UTC"), "symbol": pl.String,
                    "open": pl.Float64, "high": pl.Float64, "low": pl.Float64,
                    "close": pl.Float64}
        )
    df = pl.read_parquet(
        p, columns=["timestamp", "symbol", "open", "high", "low", "close"]
    )
    if df["timestamp"].dtype.time_zone != "UTC":
        raise AssertionError(f"Bad timestamp timezone: {p}")
    if df.height and df["symbol"].unique().to_list() != ["AUDUSD"]:
        raise AssertionError(f"Unexpected symbol: {p}")
    if df["timestamp"].n_unique() != df.height:
        raise AssertionError(f"Duplicate timestamps: {p}")
    return df


def _quote(local_day: date, hour: int, minute: int) -> dict | None:
    local = datetime.combine(local_day, time(hour, minute), NY)
    stamp = local.astimezone(UTC)
    if stamp >= HOLDO:
        raise ValueError("Holdout crossing")
    hit = _day(stamp.date()).filter(pl.col("timestamp") == stamp)
    if hit.height == 0:
        return None
    if hit.height != 1:
        raise AssertionError(f"Duplicate source endpoint: {stamp}")
    row = hit.row(0, named=True)
    if not (0 < row["low"] <= row["open"] <= row["high"] and
            row["low"] <= row["close"] <= row["high"]):
        raise AssertionError(f"Bad OHLC: {stamp}")
    return row


def _prev_completed_fx_session(local_day: date) -> date | None:
    for back in range(1, 11):
        prev = local_day - timedelta(days=back)
        if prev.weekday() < 5 and _quote(prev, 15, 59) and _quote(prev, 16, 0):
            return prev
    return None


def _monthly_anchor(year: int, month: int) -> tuple[date, date, dict] | None:
    # Qualify the first observed weekday market session, not a naive Monday.
    for dd in range(1, 15):
        day = date(year, month, dd)
        if day.weekday() >= 5:
            continue
        if not (_quote(day, 9, 59) and _quote(day, 10, 0)):
            continue
        next_min = _quote(day, 10, 1)
        if next_min is None:
            continue
        cutoff_day = _prev_completed_fx_session(day)
        if cutoff_day is None:
            continue
        return day, cutoff_day, next_min
    return None


def _policy_sources() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    session = requests.Session()
    rb = session.get(RBA_URL, timeout=30)
    rb.raise_for_status()
    rf = pd.read_html(io.StringIO(rb.text))[0]
    if not {"Effective Date", "Cash rate target %"}.issubset(rf.columns):
        raise ValueError("RBA table changed")
    rba = pd.DataFrame({
        "date": pd.to_datetime(rf["Effective Date"], format="%d %b %Y", errors="coerce"),
        "value": pd.to_numeric(rf["Cash rate target %"], errors="coerce"),
    }).dropna().sort_values("date")
    rba = rba[(rba.date >= "2014-01-01") & (rba.date < "2025-01-01")]
    if len(rba) < 100:
        raise AssertionError("RBA insufficient official policy events")
    fe = session.get(FED_URL, timeout=30)
    fe.raise_for_status()
    fed = pd.read_csv(io.StringIO(fe.text), parse_dates=["observation_date"])
    fed.columns = ["date", "value"]
    fed["value"] = pd.to_numeric(fed["value"], errors="coerce")
    fed = fed.dropna().sort_values("date")
    fed = fed[(fed.date >= "2014-01-01") & (fed.date < "2025-01-01")]
    if len(fed) < 3900:
        raise AssertionError("Fed daily effective level history insufficient")
    metadata = json.loads(METADATA.read_text())
    if metadata.get("provider_id") != "lse" or metadata.get("source_symbol") != "AUD/USD":
        raise AssertionError("Canonical source provider changed: fail closed")
    provenance = {
        "rba_url": RBA_URL, "rba_http_sha256": sha256(rb.content),
        "fed_url": FED_URL, "fed_http_sha256": sha256(fe.content),
        "rba_effective_events_2014_2024": len(rba),
        "fed_daily_effective_records_2014_2024": len(fed),
        "source_store_id": metadata["store_identity"],
        "source_provider": metadata["provider"],
        "price_provenance_note": "LSE 1m historical OHLC, not perp tradable bid/ask",
        "release_timestamp_limit": (
            "RBA policy decision releases at 14:30 Sydney preceding effective "
            "day according to official RBA guidance. Fed daily target levels "
            "effective-as-of from Board via FRED; original announcement "
            "timestamps not independently audited for each FOMC event."
        ),
        "holdout": "No 2025+ FX price rows accessed",
    }
    return rba, fed, provenance


def prepare() -> None:
    if DATA.exists() or SOURCES.exists():
        raise FileExistsError("A frozen input exists; never overwrite")
    if not (ROOT / "config/research_sessions" / f"{NAME}.yaml").is_file():
        raise FileNotFoundError("Preregister session before preparation")
    rba, fed, prov = _policy_sources()
    rows = []
    misses = []
    for year in range(2015, 2025):
        for month in range(1, 13):
            found = _monthly_anchor(year, month)
            if found is None:
                misses.append(f"{year:04d}-{month:02d}")
                continue
            day, cutoff, quote = found
            r = rba.loc[rba["date"].dt.date <= cutoff]
            f = fed.loc[fed["date"].dt.date <= cutoff]
            if r.empty or f.empty:
                misses.append(f"{year:04d}-{month:02d}:policy_missing")
                continue
            r_last, f_last = r.iloc[-1], f.iloc[-1]
            spread = float(r_last["value"] - f_last["value"])
            direction = int(np.sign(spread))
            fill_ts = datetime.combine(day, time(10, 1), NY).astimezone(UTC)
            rows.append({
                "timestamp": fill_ts, "symbol": "AUDUSD", "open": float(quote["open"]),
                "high": float(quote["high"]), "low": float(quote["low"]),
                "close": float(quote["close"]), "month": f"{year:04d}-{month:02d}",
                "decision_day": day.isoformat(),
                "cutoff_day": cutoff.isoformat(),
                "rba_effective_date": r_last["date"].date().isoformat(),
                "fed_effective_date": f_last["date"].date().isoformat(),
                "rba_target_pct": float(r_last["value"]),
                "fed_upper_pct": float(f_last["value"]),
                "spread_pp": spread, "direction": direction,
                "quote_side": "LSE_OHLC_UNVERIFIED_EXECUTION_SIDE"
            })
    prov["missing_anchor_months"] = misses
    prov["anchors_found"] = len(rows)
    prov["input_identity"] = "RBA target minus Fed upper target dated no later than previous observed FX session NY 16:00"
    if len(rows) != MONTHS or misses:
        raise AssertionError(
            f"No valid contiguous 120-anchor screen, found {len(rows)}; missing {misses}"
        )
    frame = pl.DataFrame(rows).sort("timestamp")
    if frame["timestamp"].n_unique() != MONTHS:
        raise AssertionError("Duplicate anchors")
    if frame["timestamp"].max() >= HOLDO:
        raise AssertionError("Protected market data used")
    assert frame["timestamp"].min().year == 2015
    DATA.parent.mkdir(parents=True, exist_ok=False)
    frame.write_parquet(DATA)
    prov["endpoint_sha256"] = file_hash(DATA)
    SOURCES.write_text(json.dumps(prov, indent=2) + "\n")
    print(json.dumps({
        "status": "PREPARED_NO_OUTCOME_COMPUTED", "anchors": len(rows),
        "long": sum(x["direction"] > 0 for x in rows),
        "short": sum(x["direction"] < 0 for x in rows),
        "flat": sum(x["direction"] == 0 for x in rows),
        "prices_sha256": prov["endpoint_sha256"], "path": str(DATA.relative_to(ROOT))
    }, indent=2))


def mbb_ci(values: np.ndarray) -> tuple[float, float]:
    n = len(values)
    starts = np.random.default_rng(SEED).integers(
        0, n - BLOCK + 1, size=(RESAMPLES, math.ceil(n / BLOCK))
    )
    indices = (starts[..., None] + np.arange(BLOCK)).reshape(RESAMPLES, -1)[:, :n]
    return tuple(np.percentile(values[indices].mean(axis=1), [2.5, 97.5]).tolist())


def evaluate() -> None:
    if not CONTROL.exists():
        raise RuntimeError("Freeze spec using research_session.py init BEFORE outcomes")
    if any(p.exists() for p in (METRICS, REPORT, ROWS)):
        raise FileExistsError("Existing immutable trial output")
    if not DATA.exists() or not SOURCES.exists():
        raise FileNotFoundError("Missing qualified preregistered input")
    provenance = json.loads(SOURCES.read_text())
    if file_hash(DATA) != provenance["endpoint_sha256"]:
        raise AssertionError("Source identity changed after preflight")
    data = pl.read_parquet(DATA).sort("timestamp")
    assert data.height == MONTHS
    assert data["timestamp"].max() < HOLDO
    for column in ("open", "high", "low", "close"):
        if data[column].null_count():
            raise AssertionError(f"Null price {column}")
    monthly = data.with_columns([
        pl.col("open").shift(-1).alias("next_open"),
        pl.col("timestamp").shift(-1).alias("next_ts")
    ]).head(MONTHS - 1).with_columns([
        (pl.col("direction") * 10000 * (pl.col("next_open") - pl.col("open"))).alias("gross_usd"),
        (10000 * (pl.col("next_open") - pl.col("open"))).alias("long_usd"),
        (pl.col("direction") * (pl.col("next_open") / pl.col("open") - 1) * 10000).alias("signed_price_bps")
    ])
    s = monthly.to_pandas()
    usd = s["gross_usd"].to_numpy(dtype=float)
    baseline = s["long_usd"].to_numpy(dtype=float)
    effective = s["direction"].to_numpy(dtype=int)
    episodes = int(np.sum((effective != 0) & (effective != np.r_[0, effective[:-1]])))
    ci = mbb_ci(usd)
    npos = int((effective > 0).sum())
    nneg = int((effective < 0).sum())
    nflat = int((effective == 0).sum())
    years = int(pd.to_datetime(s["month"]).dt.year.nunique())
    eligible = (len(usd) >= 96 and years >= 8 and npos >= 12 and nneg >= 12 and episodes >= 4)
    if not eligible:
        verdict = "INCONCLUSIVE"
    elif np.mean(usd) > 0 and ci[0] > 0:
        verdict = "PASS"
    elif ci[1] < 0:
        verdict = "FAIL"
    else:
        verdict = "INCONCLUSIVE"
    subgroups = {}
    for name, a, b in [("2015_2019", 2015, 2019), ("2020_2024", 2020, 2024)]:
        p = s[(s["timestamp"].dt.year >= a) & (s["timestamp"].dt.year <= b)]
        subgroups[name] = {"months": len(p), "mean_gross_usd": float(p.gross_usd.mean()),
                           "gross_sum_usd": float(p.gross_usd.sum())}
    metrics = {
        "candidate_id": NAME, "research_stage": "Phase3_price_only",
        "status": verdict, "mvp_economic_decision": "INCONCLUSIVE_UNTRADABLE_PERP_PROXY",
        "anchors": MONTHS, "month_intervals": len(usd), "represented_calendar_years": years,
        "long_months": npos, "short_months": nneg, "flat_months": nflat,
        "signed_exposure_episodes": episodes, "coverage_gate_pass": bool(eligible),
        "gross_mean_usd_per_month": float(np.mean(usd)),
        "gross_sum_usd": float(np.sum(usd)),
        "gross_mean_bps_of_100k_monthly": float(np.mean(usd) / 100000 * 10000),
        "gross_mean_signed_price_bps": float(s.signed_price_bps.mean()),
        "gross_positive_month_fraction": float(np.mean(usd > 0)),
        "always_long_mean_usd_per_month": float(np.mean(baseline)),
        "incremental_mean_vs_always_long_usd": float(np.mean(usd - baseline)),
        "six_month_moving_block_ci95_usd_per_month": list(ci),
        "cost_mode": "gross_price_only_zero_funding_for_screen_not_realistic_net",
        "bootstrap": {"seed": SEED, "block_months": BLOCK, "resamples": RESAMPLES},
        "subperiods": subgroups, "source_endpoint_sha256": file_hash(DATA),
        "holdout_access": False, "native_backtest_executed": False,
        "actual_perpetual_tradability": False
    }
    OUT.mkdir(parents=True, exist_ok=False)
    s.to_csv(ROWS, index=False)
    METRICS.write_text(json.dumps(metrics, indent=2, allow_nan=False) + "\n")
    report = f"""# AUDUSD policy-spread gross-price proxy — ResearchPhase 3

**Decision: {verdict} (price-only signal screen).**
**MVP economic decision: INCONCLUSIVE — UNTRADABLE_PERP_PROXY.**

This is a separate proxy screen. Live Hyperliquid metadata found **no AUDUSD
perpetual**, so 2015–2024 LSE AUDUSD quotes are **not historical perpetual
prices, fills, spread, or funding**. No live or paper orders were placed.

## Frozen identity and method

- Session: `{NAME}`; trial: `phase3_signal_screen`.
- Frozen before looking at outcome prices: `{CONTROL.relative_to(ROOT)}`.
- Source quote endpoints SHA256: `{file_hash(DATA)}`.
- Source: LSE `forex_minute_AUDUSD`, 1-minute UTC OHLC.
- Rates: RBA cash target official effective decisions; Fed `DFEDTARU`
  official effective target-upper series through FRED.
- Rates as-of: no later than NY 16:00 of the previous observed completed FX
  weekday session. Original announcement-level exact Fed timestamp validation
  remains incomplete. No future-shift or final holdout data was used.
- Signal: RBA rate minus Fed upper bound, sign only.
- Decision: first observed eligible FX business session monthly at 10:00 NY.
  Outcome prices: next minute's 10:01 NY quote opens, until next month
  10:01 NY quote open. Gross USD monthly price label at 10,000 AUD.
- Baseline: cash zero; descriptive always-long same 10,000 AUD.
- Uncertainty: 6-month moving-block, 5000 replicates, fixed seed 7.
- Scope: 2015-01 through 2024-11 complete start-month intervals; protected
  2025+ holdout was not accessed. No optimizations.

## Results

| Metric | Gross price-only |
| --- | ---: |
| Monthly intervals | {len(usd)} |
| Years | {years} |
| Long / short / flat months | {npos} / {nneg} / {nflat} |
| Signed exposure episodes | {episodes} |
| Gross price mean USD / month | {metrics["gross_mean_usd_per_month"]:.3f} |
| Gross price sum USD | {metrics["gross_sum_usd"]:.3f} |
| Gross mean bps per USD100k / month | {metrics["gross_mean_bps_of_100k_monthly"]:.3f} |
| Positive signed months | {metrics["gross_positive_month_fraction"]:.1%} |
| Always-long gross USD / month | {metrics["always_long_mean_usd_per_month"]:.3f} |
| Increment over always-long USD / month | {metrics["incremental_mean_vs_always_long_usd"]:.3f} |
| 95% moving-block CI mean USD / month | [{ci[0]:.3f}, {ci[1]:.3f}] |
| Source-coverage and episode gate | {"PASS" if eligible else "FAIL"} |

- 2015–2019: {subgroups["2015_2019"]["months"]} months,
  mean gross USD/month {subgroups["2015_2019"]["mean_gross_usd"]:.3f}.
- 2020–2024: {subgroups["2020_2024"]["months"]} months,
  mean gross USD/month {subgroups["2020_2024"]["mean_gross_usd"]:.3f}.

## Interpretation

- This stage labels price-direction predictability only. The spread of
  overnight policy targets is **not** the cashflow for a perpetual.
- Missing execution book, funding, broker trade fees and quotes prevent
  a net-PnL validation regardless of price-only stage outcome.
- LSE OHLC bar-start quote-side semantics and original publication time
  for every Fed/RBA decision have not been certified for executable trading.
- Count each month as an interval, not an independent signed strategy trade.
  Signed-policy exposure episodes: {episodes}.
- This is **not** a native `ml4t-backtest.Engine` simulation. The repository's
  ResearchPhase 3 single-symbol macro directional screen does not require a
  pretend exchange backtest.
- A {verdict} on gross-price signal is **not** a final economic validation
  of the original CFD carry thesis or of any Hyperliquid perpetual.

**ResearchPhase 3 next action:** STOP. Research lead must select a genuinely
listed perpetual and its own historical price/funding data for a new trial.
Do not relabel AUDUSD LSE spot quotes as an executable perp.
"""
    REPORT.write_text(report)
    print(json.dumps(metrics, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["prepare", "evaluate"])
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare()
    else:
        evaluate()


if __name__ == "__main__":
    main()
