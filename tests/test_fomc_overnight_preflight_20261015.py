"""Independent source/clock regression tests for the FOMC preflight.

No signal labels, returns, PnL, strategy simulation or 2025+ source access.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pytest
import yaml

from scripts import fomc_overnight_preflight_20261015 as audit

ROOT = Path(__file__).resolve().parents[1]


def test_original_calendar_publication_and_cancellation() -> None:
    events, cancelled = audit.event_dates()
    assert len(events) == 63
    assert len(cancelled) == 1
    assert cancelled[0]["statement_date"] == "2020-03-18"
    assert events[0]["date"] == date(2017, 2, 1)
    assert events[-1]["date"] == date(2024, 12, 18)

    for event in events:
        statement_date = event["date"]
        original_at = datetime.fromisoformat(event["original_publication_utc"])
        decision = audit.ny_utc(
            statement_date - timedelta(days=1), audit.ENTRY_DECISION
        )
        assert original_at < decision
        assert statement_date.year <= 2024
        assert statement_date != date(2020, 3, 18)


def test_future_announced_calendar_is_rejected_before_data_access(
    tmp_path: Path,
) -> None:
    document = yaml.safe_load(audit.CALENDAR_PATH.read_text(encoding="utf-8"))
    document["years"][2017]["published_at"] = "2018-01-01T14:00:00-05:00"
    future_schedule = tmp_path / "bad_release.yaml"
    future_schedule.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(ValueError, match="not known as of entry"):
        audit.event_dates(future_schedule)


def test_ny_dst_and_matched_calendar_day_offsets_are_exact() -> None:
    assert audit.ny_utc(date(2024, 3, 8), time(16, 6)) == datetime(
        2024, 3, 8, 21, 6, tzinfo=UTC
    )
    assert audit.ny_utc(date(2024, 3, 11), time(16, 6)) == datetime(
        2024, 3, 11, 20, 6, tzinfo=UTC
    )
    assert audit.ny_utc(date(2024, 11, 1), time(9, 36)) == datetime(
        2024, 11, 1, 13, 36, tzinfo=UTC
    )
    assert audit.ny_utc(date(2024, 11, 4), time(9, 36)) == datetime(
        2024, 11, 4, 14, 36, tzinfo=UTC
    )
    events, _ = audit.event_dates()
    for event in events:
        d = event["date"]
        c = d - timedelta(days=7)
        assert c.weekday() == d.weekday()
        assert audit.ny_utc(d - timedelta(days=1), audit.ENTRY_FILL) == (
            audit.ny_utc(d - timedelta(days=1), audit.ENTRY_DECISION)
            + timedelta(minutes=1)
        )
        assert audit.ny_utc(c, audit.EXIT_FILL) == (
            audit.ny_utc(c, audit.EXIT_DECISION) + timedelta(minutes=1)
        )


def test_market_calendar_excludes_early_closes() -> None:
    sessions = audit.full_cash_sessions()
    assert date(2024, 11, 27) in sessions
    assert date(2024, 11, 29) not in sessions  # Day after Thanksgiving
    assert date(2024, 12, 25) not in sessions  # Market holiday


def test_quote_reader_fails_closed_at_protected_holdout_boundary() -> None:
    with pytest.raises(ValueError, match="holdout"):
        audit.quote_check(datetime(2025, 1, 1, tzinfo=UTC))
    with pytest.raises(ValueError, match="Holdout"):
        audit.bars_for_utc_day(date(2025, 1, 1))
    with pytest.raises(ValueError, match="Holdout"):
        audit.bars_for_utc_day(date(2016, 12, 30))


def test_clock_checks_do_not_depend_on_filling_bars(monkeypatch) -> None:
    observed = []

    def check(ts: datetime) -> dict:
        observed.append(ts)
        return {"available": True, "timestamp_utc": ts.isoformat()}

    monkeypatch.setattr(audit, "quote_check", check)
    before = audit.inspect_leg(date(2024, 10, 29), entry=True)
    after = audit.inspect_leg(date(2024, 10, 30), entry=False)
    assert before["bar_clock_correct"] and after["bar_clock_correct"]
    assert observed == [
        audit.ny_utc(date(2024, 10, 29), time(16, 4)),
        audit.ny_utc(date(2024, 10, 29), time(16, 6)),
        audit.ny_utc(date(2024, 10, 30), time(9, 34)),
        audit.ny_utc(date(2024, 10, 30), time(9, 36)),
    ]


def test_saved_preflight_matches_source_only_evidence() -> None:
    path = ROOT / "docs/audit" / (audit.ID + "_source_preflight_v2.json")
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["terminal_preflight_status"] == "BLOCKED_DATA"
    assert record["frozen_session"] is False
    assert record["trial_started"] is False
    assert record["signal_returns_inspected"] is False
    assert record["phase3_performance_evaluation_executed"] is False
    assert record["native_backtest_executed"] is False
    assert record["protected_holdout_scored"] is False
    assert record["candidate_statement_count"] == 63
    assert record["source_complete_pair_count"] == 53
    assert record["source_complete_years"] == list(range(2018, 2025))
    assert record["calendar_and_source_counts"]["fill_bars_missing"] == 10
    assert (
        record["calendar_and_source_counts"]["all_eight_endpoint_clock_checks_passed"]
        == 53
    )
    assert any("dividend" in issue for issue in record["blockers"])

    bad = [
        event for event in record["events"] if not event.get("source_coverage_complete")
    ]
    assert len(bad) == 10
    assert [event["statement_date"] for event in bad] == [
        "2017-02-01",
        "2017-03-15",
        "2017-05-03",
        "2017-06-14",
        "2017-07-26",
        "2017-09-20",
        "2017-11-01",
        "2017-12-13",
        "2018-01-31",
        "2018-03-21",
    ]

    for event in record["events"]:
        d = date.fromisoformat(event["statement_date"])
        c = date.fromisoformat(event["control_statement_date"])
        assert d - c == timedelta(days=7)
        assert c.weekday() == d.weekday()
        for check in event["quote_checks"].values():
            assert check["bar_clock_correct"]
            assert check["last_complete_bar"]["timestamp_utc"] < check["decision_utc"]
            assert check["decision_utc"] < check["required_fill_bar"]["timestamp_utc"]
            assert datetime.fromisoformat(
                check["required_fill_bar"]["timestamp_utc"]
            ) < (audit.HOLDOUT_START)
