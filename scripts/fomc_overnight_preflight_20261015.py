"""Read-only price/clock feasibility audit for the frozen-*candidate* FOMC thesis.

No PnL, forward returns, model fitting, parameter search or protected data access.
This script does not initialize/freeze a session. It checks metadata/source
eligibility before research registration, using the actual Dukascopy bid-only
one-minute store and Fed's original calendar announcements.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import polars as pl
import yaml

ROOT = Path(__file__).resolve().parents[1]
ID = "fomc_overnight_uncertainty_premium_us500_cfd_20261015_v1"
CALENDAR_PATH = (
    ROOT / "docs/research_inputs" / ID / "fed_original_calendar_2017_2024.yaml"
)
STORE = Path("/home/quant/dev/quant/ml4t-data/.data/store/index_minute_ES")
REPORT = ROOT / "docs/audit" / (ID + "_source_preflight.json")
NY = ZoneInfo("America/New_York")
HOLDOUT_START = datetime(2025, 1, 1, tzinfo=UTC)
ENTRY_DECISION = time(16, 5)
ENTRY_FILL = time(16, 6)
EXIT_DECISION = time(9, 35)
EXIT_FILL = time(9, 36)
AVAILABLE_ENTRY_BAR = time(16, 4)
AVAILABLE_EXIT_BAR = time(9, 34)


def parse_date(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def ny_utc(day: date, clock: time) -> datetime:
    return datetime.combine(day, clock, tzinfo=NY).astimezone(UTC)


def event_dates(path: Path = CALENDAR_PATH) -> tuple[list[dict], list[dict]]:
    """Reconstruct calendar eligibility without touching price outcomes."""
    source = yaml.safe_load(path.read_text(encoding="utf-8"))
    events: list[dict] = []
    cancelled: list[dict] = []
    for year, record in source["years"].items():
        original_at = datetime.fromisoformat(record["published_at"]).astimezone(UTC)
        cancelled_map = {
            parse_date(row["date"]): row
            for row in record.get("cancelled_statement_dates", [])
        }
        for d_raw in record["statement_dates"]:
            d = parse_date(d_raw)
            if d.year != int(year) or not 2017 <= d.year <= 2024:
                raise ValueError(f"unexpected statement date: {d}")
            if d in cancelled_map:
                cancelled.append(
                    {
                        "statement_date": d.isoformat(),
                        "original_url": record["url"],
                        "cancelled_source": cancelled_map[d]["url"],
                        "reason": "cancelled regular meeting; no trade",
                    }
                )
                continue
            decision = ny_utc(d - timedelta(days=1), ENTRY_DECISION)
            if original_at >= decision:
                raise ValueError(f"event not known as of entry: {d}")
            events.append(
                {
                    "date": d,
                    "original_url": record["url"],
                    "original_publication_utc": original_at.isoformat(),
                }
            )
    if len(events) + len(cancelled) != 64:
        raise ValueError(
            "Expected exactly eight original meetings in each of eight years"
        )
    return sorted(events, key=lambda row: row["date"]), cancelled


def full_cash_sessions(start: str = "2016-12-20", end: str = "2024-12-31") -> set[date]:
    cal = xcals.get_calendar("XNYS")
    sessions = {d.date() for d in cal.sessions_in_range(start, end)}
    early = {d.date() for d in cal.early_closes}
    return sessions - early


@lru_cache(maxsize=700)
def bars_for_utc_day(day: date) -> tuple[frozenset[datetime], str]:
    """Read only historical timestamps, symbol and OHLC validity flags.

    No raw OHLC or economic outcomes are exposed or persisted.
    """
    if day.year >= 2025 or day.year < 2017:
        raise ValueError(f"Holdout/invalid source access forbidden: {day}")
    path = STORE / f"year={day.year}/month={day.month}/day={day.day}/data.parquet"
    if not path.is_file():
        return frozenset(), "partition_missing"
    df = pl.read_parquet(
        path, columns=["timestamp", "symbol", "open", "high", "low", "close"]
    )
    if df.schema["timestamp"].time_zone != "UTC":
        return frozenset(), "timezone_invalid"
    if df.filter(pl.col("symbol") != "ES").height:
        return frozenset(), "unexpected_instrument"
    # Integrity, not performance: reject an impossible OHLC bar.
    invalid = df.filter(
        (pl.col("high") < pl.col("low"))
        | (pl.col("open") <= 0)
        | (pl.col("close") <= 0)
        | (pl.col("open") < pl.col("low"))
        | (pl.col("open") > pl.col("high"))
        | (pl.col("close") < pl.col("low"))
        | (pl.col("close") > pl.col("high"))
        | (~pl.col("open").is_finite())
        | (~pl.col("high").is_finite())
        | (~pl.col("low").is_finite())
        | (~pl.col("close").is_finite())
    )
    if invalid.height:
        return frozenset(), "invalid_ohlc_source_day"
    timestamps = df["timestamp"].to_list()
    if len(timestamps) != len(set(timestamps)):
        return frozenset(), "duplicate_source_minute"
    return frozenset(timestamps), "ok"


def quote_check(timestamp: datetime) -> dict:
    if not timestamp < HOLDOUT_START:
        raise ValueError("Attempted holdout quote inspection")
    rows, quality = bars_for_utc_day(timestamp.date())
    return {
        "timestamp_utc": timestamp.isoformat(),
        "available": quality == "ok" and timestamp in rows,
        "partition_quality": quality,
    }


def inspect_leg(day: date, *, entry: bool) -> dict:
    """Bar-clock proof: decision uses last fully completed minute; fill next."""
    clock_d = ENTRY_DECISION if entry else EXIT_DECISION
    clock_ref = AVAILABLE_ENTRY_BAR if entry else AVAILABLE_EXIT_BAR
    clock_fill = ENTRY_FILL if entry else EXIT_FILL
    decision = ny_utc(day, clock_d)
    completed = ny_utc(day, clock_ref)
    fill = ny_utc(day, clock_fill)
    if not completed + timedelta(minutes=1) == decision:
        raise AssertionError("Prior completed bar availability violation")
    if not fill == decision + timedelta(minutes=1):
        raise AssertionError("Next-open timing violation")
    return {
        "decision_utc": decision.isoformat(),
        "last_complete_bar": quote_check(completed),
        "required_fill_bar": quote_check(fill),
        "bar_clock_correct": True,
    }


def audit(source_calendar: Path = CALENDAR_PATH) -> dict:
    events, cancelled = event_dates(source_calendar)
    cash_full = full_cash_sessions()
    all_scheduled = {d for d in (ev["date"] for ev in events)}
    control_count = Counter()
    entries = []
    for event in events:
        d = event["date"]
        c = d - timedelta(days=7)
        entry_day = d - timedelta(days=1)
        control_entry_day = c - timedelta(days=1)
        reasons = []
        if entry_day not in cash_full or d not in cash_full:
            reasons.append("fomc_or_prior_cash_day_not_full")
        if c not in cash_full or control_entry_day not in cash_full:
            reasons.append("control_or_prior_cash_day_not_full")
        if c in all_scheduled or control_entry_day in all_scheduled:
            reasons.append("control_overlaps_scheduled_fomc")
        row = {
            "statement_date": d.isoformat(),
            "original_calendar_url": event["original_url"],
            "published_before_signal": True,
            "calendar_eligibility": not reasons,
            "calendar_exclusion_reasons": reasons,
            "control_statement_date": c.isoformat(),
        }
        if reasons:
            control_count["calendar_ineligible"] += 1
            row["quote_checks"] = {}
            entries.append(row)
            continue
        control_count["calendar_eligible"] += 1
        checks = {
            "fomc_entry": inspect_leg(entry_day, entry=True),
            "fomc_exit": inspect_leg(d, entry=False),
            "control_entry": inspect_leg(control_entry_day, entry=True),
            "control_exit": inspect_leg(c, entry=False),
        }
        row["quote_checks"] = checks
        all_fill_bars = all(
            v["required_fill_bar"]["available"] for v in checks.values()
        )
        all_decision_refs = all(
            v["last_complete_bar"]["available"] for v in checks.values()
        )
        row["all_four_exact_fill_bars"] = all_fill_bars
        row["all_decision_reference_bars"] = all_decision_refs
        row["source_coverage_complete"] = all_fill_bars and all_decision_refs
        control_count[
            "fill_bars_complete" if all_fill_bars else "fill_bars_missing"
        ] += 1
        control_count[
            "all_eight_endpoint_clock_checks_passed"
            if row["source_coverage_complete"]
            else "some_clock_bar_missing"
        ] += 1
        entries.append(row)

    eligible_rows = [x for x in entries if x.get("source_coverage_complete")]
    eligible_years = sorted({int(row["statement_date"][:4]) for row in eligible_rows})
    complete_days = sorted({row["statement_date"] for row in eligible_rows})
    blockers = [
        "Historical broker ask/spread at 16:06 ET entry absent from canonical bid-only minute store.",
        "Historical account-specific Dukascopy CFD rollover/swap at relevant dates and settlement times unavailable.",
        "Historical index-CFD dividend adjustment cash flows and ex-dividend settlement terms unavailable.",
        "Historical market-order slippage/commission and executable USA500 CFD contract identity/multiplier/lot not qualified.",
        "Official currently published broker trading hours are not an effective-dated proof of 2017-2024 session execution.",
        "Per-event final decision release clock and schedule amendments still need independent time-as-of confirmation.",
    ]
    if len(eligible_rows) < 50 or len(eligible_years) < 6:
        blockers.append("Fewer than 50 source-complete paired nights across six years.")
    counts = dict(control_count)
    for k in (
        "calendar_eligible",
        "calendar_ineligible",
        "fill_bars_complete",
        "fill_bars_missing",
        "all_eight_endpoint_clock_checks_passed",
        "some_clock_bar_missing",
    ):
        counts.setdefault(k, 0)
    return {
        "research_candidate": ID,
        "classification": "SOURCE_QUALIFICATION_ONLY",
        "terminal_preflight_status": "BLOCKED_DATA",
        "frozen_session": False,
        "native_backtest_executed": False,
        "signal_returns_inspected": False,
        "phase3_performance_evaluation_executed": False,
        "trial_started": False,
        "protected_holdout_scored": False,
        "source": {
            "canonical_key": "index_minute_ES",
            "vendor": "Dukascopy",
            "underlying_symbol": "usa500idxusd",
            "product": "US500 bid-only CFD historical price proxy",
            "execution_bid_ask": "NOT_AVAILABLE",
            "source_path": str(STORE),
            "calendar_source": str(source_calendar.relative_to(ROOT)),
            "inspection_range": "2017-01-01 to 2024-12-31 inclusive",
        },
        "candidate_statement_count": len(events),
        "cancelled_regular_meetings": cancelled,
        "calendar_and_source_counts": counts,
        "source_complete_pair_count": len(eligible_rows),
        "source_complete_years": eligible_years,
        "source_complete_dates": complete_days,
        "events": entries,
        "blockers": blockers,
        "next_eligible_step": "OBTAIN_EFFECTIVE_DATED_BROKER_COST_AND_ASK_EVIDENCE",
        "method": "read-only XNYS full-cash-session validation, originally published Federal Reserve schedules, per-event local-to-UTC DST and exact 1m bar START coverage; no price returns, no statistical trials.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=REPORT)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Append-only source audit exists: {args.output}")
    data = audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    summary = {
        k: data[k]
        for k in (
            "terminal_preflight_status",
            "candidate_statement_count",
            "source_complete_pair_count",
            "source_complete_years",
        )
    }
    summary["counts"] = data["calendar_and_source_counts"]
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
