"""Correct BTC native-session-label funding allocation, development only.

BTC equity timestamps label the COMPLETE UTC day, not equity observed at
the beginning of that day. Recognize funding at actual event time before
the next day's midnight. Do not alter the frozen fills or return history.
"""
from __future__ import annotations

import csv
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from pathlib import Path

from scripts import allocation_btc_funding_20261014 as native

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "run_log/allocation_prerequisites_20261014/btc"
END = datetime(2025, 1, 1, tzinfo=UTC)


def _load_funding() -> list[tuple[datetime, Decimal]]:
    result = []
    with (BASE / "funding_cashflows_repaired_development.csv").open(newline="") as f:
        for row in csv.DictReader(f):
            t = datetime.fromisoformat(row["funding_timestamp_utc"]).astimezone(UTC)
            if t >= END:
                raise ValueError("funding event enters reserved period")
            result.append((t, Decimal(row["funding_cashflow_usdt"])))
    if any(right[0] <= left[0] for left, right in pairwise(result)):
        raise ValueError("funding events not strictly increasing")
    return result


def compute_session_equity() -> dict:
    source = native._read_development_equity(
        ROOT / "run_log/independent_five_full_history_20261014/donchian-btc/equity.csv"
    )
    events = _load_funding()
    records = []
    index = 0
    cumulative = Decimal()
    previous_adjusted: Decimal | None = None
    for row in source:
        label = row["_timestamp"]
        if label >= END:
            raise ValueError("source equity row at or after holdout")
        if label.hour or label.minute or label.second:
            raise ValueError("BTC daily timestamp must be UTC midnight SESSION LABEL")
        valuation_available_at = label + timedelta(days=1)
        # Funding exactly at 00:00 on the following date occurs AFTER the
        # completed session and is not charged against this session's NAV.
        while index < len(events) and events[index][0] < valuation_available_at:
            cumulative += events[index][1]
            index += 1
        nav = row["_equity"]
        adjusted = nav + cumulative
        ret = "" if previous_adjusted is None else str(adjusted / previous_adjusted - 1)
        records.append({
            "session_date": label.date().isoformat(),
            "native_session_label_utc": label.isoformat(),
            "valuation_available_at_utc": valuation_available_at.isoformat(),
            "native_equity_usdt": str(nav),
            "cumulative_funding_usdt": str(cumulative),
            "funding_adjusted_equity_usdt": str(adjusted),
            "funding_adjusted_return": ret,
        })
        previous_adjusted = adjusted
    OUT = BASE / "funding_adjusted_equity_session_aligned_development.csv"
    with OUT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    result = {
        "status": "VERIFIED_SESSION_LABEL_ALIGNMENT",
        "session_rows": len(records),
        "first_session": records[0]["session_date"],
        "last_session": records[-1]["session_date"],
        "native_timestamp_semantics": "UTC daily session label; mark available after 23:59 UTC of that session",
        "first_mark_available_at": records[0]["valuation_available_at_utc"],
        "last_mark_available_at": records[-1]["valuation_available_at_utc"],
        "applied_funding_events": index,
        "excluded_events_at_or_after_last_valuation": len(events) - index,
        "last_session_cumulative_funding_usdt": records[-1]["cumulative_funding_usdt"],
        "last_adjusted_equity_usdt": records[-1]["funding_adjusted_equity_usdt"],
        "holdout_source_read": False,
        "returns_are_posthoc_fixed_fill": True,
    }
    (BASE / "funding_session_alignment_audit.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    print(json.dumps(compute_session_equity(), indent=2))
