"""Build observed monthly capital-return inputs, never synthesize daily returns.

This is an ACCOUNTING panel, not a backtest or allocation optimizer.
Each month uses the last common trading-session date with a verifiable
23:59 UTC B0 and C3 native mark. BTC and RSI timestamps are *session labels*
whose completed-bar information is available before the following UTC midnight.
Only 2019-09 through 2024-12 native source observations are read.
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NamedTuple

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "run_log/allocation_prerequisites_20261014"
OUT = DATA / "allocation_development"
SRC_B0 = DATA / "b0/continuous_2013_2024/native_full_tick_cost/daily_equity.csv"
SRC_C3 = DATA / "c3/continuous_equity.parquet"
SRC_BTC = DATA / "btc/funding_adjusted_equity_session_aligned_development.csv"
SRC_RSI = ROOT / "run_log/independent_five_full_history_20261014/rsi-30-50/equity.csv"
START = "2019-09-09"
END = "2025-01-01"
IDS = ("b0_nq_cfd", "c3_us500_us100_cfd", "donchian_btc_binance_perp", "rsi_es_cfd")


class ObservedMark(NamedTuple):
    session: str
    timestamp: datetime
    value: float


def _native_csv(path: Path, date_field: str, timestamp_field: str, equity_field: str) -> dict[str, ObservedMark]:
    values: dict[str, ObservedMark] = {}
    with path.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            session = str(row[date_field])[:10]
            if session >= END:
                break     # Do not read 2025+ outcome fields
            if session < START:
                continue
            ts = datetime.fromisoformat(row[timestamp_field]).astimezone(UTC)
            if session in values:
                raise ValueError(f"Duplicate {path.name} session label {session}")
            equity = float(row[equity_field])
            if not (0 < equity < float("inf")):
                raise ValueError(f"Invalid marked equity for {session}")
            values[session] = ObservedMark(session, ts, equity)
    return values


def _load_c3() -> dict[str, ObservedMark]:
    # Use Polars lazy source and filter timestamp before the materialized outcome.
    query = (pl.scan_parquet(SRC_C3)
             .filter((pl.col("timestamp") >= pl.lit(datetime(2019, 9, 9, tzinfo=UTC)))
                     & (pl.col("timestamp") < pl.lit(datetime(2025, 1, 1, tzinfo=UTC))))
             .with_columns(pl.col("timestamp").dt.strftime("%Y-%m-%d").alias("session"))
             .group_by("session")
             .agg(pl.col("timestamp").max().alias("mark_at"),
                  pl.col("equity").sort_by("timestamp").last().alias("equity"))
             .sort("session"))
    obs = query.collect()
    values = {}
    for row in obs.iter_rows(named=True):
        values[row["session"]] = ObservedMark(row["session"], row["mark_at"].astimezone(UTC), float(row["equity"]))
    return values


def _require_day_clock(name: str, mark: ObservedMark) -> bool:
    d = datetime.fromisoformat(mark.session).date()
    if name in ("b0_nq_cfd", "c3_us500_us100_cfd"):
        return mark.timestamp.date() == d and mark.timestamp.hour == 23 and mark.timestamp.minute == 59
    # RSI and BTC 00:00 UTC timestamps label an entire completed session.
    return mark.timestamp.date() == d and mark.timestamp.hour == 0 and mark.timestamp.minute == 0


def _eligible_calendar(sources: dict[str, dict[str, ObservedMark]]):
    if set(sources) != set(IDS):
        raise ValueError("Wrong four-source universe")
    date_sets = [set(sources[name]) for name in IDS]
    intersection = sorted(set.intersection(*date_sets))
    eligible = [d for d in intersection if all(_require_day_clock(name, sources[name][d]) for name in IDS)]
    per_month: dict[str, str] = {}
    for d in eligible:
        per_month[d[:7]] = d    # Select last eligible session of each UTC month
    return intersection, eligible, sorted(per_month.items())


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict:
    sources = {
        "b0_nq_cfd": _native_csv(SRC_B0, "utc_day", "timestamp", "equity"),
        "c3_us500_us100_cfd": _load_c3(),
        "donchian_btc_binance_perp": _native_csv(SRC_BTC, "session_date", "native_session_label_utc", "funding_adjusted_equity_usdt"),
        "rsi_es_cfd": _native_csv(SRC_RSI, "timestamp", "timestamp", "equity"),
    }
    intersection, eligible, months = _eligible_calendar(sources)
    if len(months) < 50:
        raise ValueError(f"Fewer than 50 observed development monthly marks: {len(months)}")
    values: list[dict] = []
    prev = None
    for month, day in months:
        stamps = {name: sources[name][day] for name in IDS}
        # Time 00 UTC following each complete session = common availability cutoff.
        cutoff = datetime.fromisoformat(day).replace(tzinfo=UTC) + timedelta(days=1)
        mark = {
            "month": month, "session_date": day, "valuation_available_at_utc": cutoff.isoformat(),
        }
        for name in IDS:
            mark[f"{name}__native_mark_timestamp"] = stamps[name].timestamp.isoformat()
            mark[f"{name}__native_nav"] = stamps[name].value
            if prev is None:
                mark[f"{name}__monthly_return"] = ""
            else:
                if stamps[name].value <= 0 or prev[name].value <= 0:
                    raise ValueError("Nonpositive native marked equity")
                mark[f"{name}__monthly_return"] = stamps[name].value / prev[name].value - 1
        values.append(mark)
        prev = stamps
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "monthly_observed_panel.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(values[0]))
        writer.writeheader()
        writer.writerows(values)
    results = {
        "classification": "EXPLORATORY monthly observed endpoints; no allocator fit or performance scored",
        "source_scope": "2019-09-09 through 2024-12-31 development ONLY",
        "reserved_holdout_observed": False,
        "sources": {name: {
            "observed_session_days": len(source),
            "earliest": min(source), "latest": max(source),
            "missing_from_four_way_intersection": len(set(source) - set(intersection)),
        } for name, source in sources.items()},
        "four_way_date_intersection": len(intersection),
        "four_way_clock_eligible_days": len(eligible),
        "clock_ineligible_common_days": len(intersection) - len(eligible),
        "monthly_mark_count": len(months),
        "monthly_return_intervals": len(months) - 1,
        "start_month": months[0][0],
        "last_month": months[-1][0],
        "months_missing_between_2019_09_and_2024_12": sorted({f"{y}-{m:02}" for y in range(2019, 2025)
                                                                 for m in range(1, 13) if (y > 2019 or m >= 9)} - {m for m, _ in months}),
        "monthly_mark_dates": [{"month": m, "session_date": d} for m, d in months],
        "identities": {
            "b0_native": _sha(SRC_B0), "c3_native": _sha(SRC_C3),
            "btc_funding_session_corrected": _sha(SRC_BTC), "rsi_native": _sha(SRC_RSI),
        },
        "accounting_scope": {
            "returns": "ratio of observed continuous marked NAVs at successive monthly common session endpoints",
            "no_forward_fill": True, "no_missing_zero_imputation": True,
            "strategy_cashflows": "native net costs, BTC posthoc funding, C3/B0 continuous development ledgers",
            "base_currency": "USD synthetic for CFDs, USDT for BTC; 1:1 USDT/USD capital-unit approximation for exploratory learning only",
            "valuation_clock": "next UTC midnight after common completed daily session date",
            "rsi_btc_timestamp": "label date 00:00 does not imply bar available at 00:00 of label date",
            "missing_exact_23_59_cfd_day": "exclude that entire date, never create an observed mark",
        },
    }
    (OUT / "calendar_and_provenance.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    return results


if __name__ == "__main__":
    print(json.dumps(build(), indent=2)[:16000])
