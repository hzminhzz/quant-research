"""Independent verification of saved development BTC funding overlay. No network or model fit."""
from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from scripts import allocation_btc_funding_resolve_20261014 as repair

ROOT = Path(__file__).resolve().parents[1]
OUT = repair.OUT
END = datetime(2025, 1, 1, tzinfo=UTC)

def _rows(path: Path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))

def verify() -> dict:
    summary = json.loads((OUT / "funding_repair_summary.json").read_text())
    if summary["scope"]["2025_2026_evaluation_opened"]:
        raise ValueError("reserved holdout opened")
    for page in summary["api_pages"]:
        path = ROOT / page["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != page["sha256"]:
            raise ValueError(f"raw Binance source hash mismatch: {path}")
        data = json.loads(path.read_text())
        if len(data) != page["rows"]:
            raise ValueError(f"raw Binance row count mismatch: {path}")
        actual_times = [int(a["fundingTime"]) for a in data] if "/funding_" in page["path"] else [int(a[0]) for a in data]
        if actual_times and (max(actual_times) >= repair.DEV_END_MS or min(actual_times) < repair.START_MS):
            raise ValueError("raw source contains holdout or unexpected earlier data")
    events = _rows(OUT / "funding_cashflows_repaired_development.csv")
    equity = _rows(OUT / "funding_adjusted_equity_development.csv")
    if len(events) != 5819:
        raise ValueError("wrong event count")
    if not equity:
        raise ValueError("no native-equity rows")
    prev_ms = -1
    by_year = defaultdict(lambda: {"funding_cashflow_usdt": Decimal(), "event_clock_funding_usdt": Decimal(), "events": 0})
    by_source = defaultdict(lambda: {"total": 0, "nonflat": 0, "funding_cashflow_usdt": Decimal()})
    event_sum = Decimal()
    conservative_events_different = 0
    overlap_errors = []
    overlap_cashflow_errors = []
    for row in events:
        t = int(row["event_ms"])
        if t >= repair.DEV_END_MS or t <= prev_ms:
            raise ValueError("event timestamps not monotonic or out of bounds")
        if repair.valid_slot(t) != repair.valid_slot(int(datetime.fromisoformat(row["slot_utc"]).timestamp()*1000)):
            raise ValueError("slot mismatch")
        prev_ms = t
        rate = Decimal(row["funding_rate"])
        mark = Decimal(row["mark_price_usdt"])
        position = Decimal(row["position_btc_conservative"])
        pos_raw = Decimal(row["position_btc_original_timestamp"])
        cashflow = Decimal(row["funding_cashflow_usdt"])
        cashflow_raw = Decimal(row["funding_cashflow_event_clock_usdt"])
        if cashflow != -position * mark * rate:
            raise ValueError("event funding arithmetic mismatch")
        if cashflow_raw != -pos_raw * mark * rate:
            raise ValueError("raw-clock funding arithmetic mismatch")
        year = datetime.fromtimestamp(t / 1000, UTC).year
        by_year[year]["funding_cashflow_usdt"] += cashflow
        by_year[year]["event_clock_funding_usdt"] += cashflow_raw
        by_year[year]["events"] += 1
        quality = row["price_quality"]
        by_source[quality]["total"] += 1
        by_source[quality]["nonflat"] += int(position != 0)
        by_source[quality]["funding_cashflow_usdt"] += cashflow
        event_sum += cashflow
        if position != pos_raw:
            conservative_events_different += 1
        if row["official_exact_mark_usdt"] and row["candle_price_usdt"]:
            official = Decimal(row["official_exact_mark_usdt"])
            candle = Decimal(row["candle_price_usdt"])
            overlap_errors.append(abs(candle / official - 1) * Decimal(10_000))
            overlap_cashflow_errors.append(abs(position * (candle - official) * rate))
    if event_sum != Decimal(summary["funding_accounting"]["total_funding_cashflow_usdt_all_events"]):
        raise ValueError("summary funding cashflow total mismatch")
    if conservative_events_different != summary["funding_accounting"]["same_slot_fill_ambiguous_count"]:
        raise ValueError("summary ambiguous count mismatch")
    prev_nav = None
    for row in equity:
        ts = datetime.fromisoformat(row["timestamp_utc"])
        if ts >= END:
            raise ValueError("equity contains holdout row")
        nav = Decimal(row["native_equity_usdt"])
        cost = Decimal(row["cumulative_settled_funding_usdt"])
        adjusted = Decimal(row["funding_adjusted_equity_usdt"])
        if adjusted != nav + cost:
            raise ValueError("daily equity not equal native plus cumulative funding")
        ret = row["funding_adjusted_return"]
        if prev_nav is None:
            if ret:
                raise ValueError("initial adjusted return must be blank")
        else:
            if abs(Decimal(ret) - (adjusted / prev_nav - 1)) > Decimal("1e-17"):
                raise ValueError("funding adjusted daily return mismatch")
        prev_nav = adjusted
    result = {
        "status": "VERIFIED_POSTHOC_FUNDING_OVERLAY_WITH_PROXIES",
        "event_count": len(events),
        "daily_rows": len(equity),
        "source_categories": {k: {field: str(value) if isinstance(value, Decimal) else value
                                 for field, value in v.items()} for k, v in by_source.items()},
        "yearly_funding": {str(y): {field: str(value) if isinstance(value, Decimal) else value
                                  for field, value in vals.items()} for y, vals in sorted(by_year.items())},
        "conservative_position_total_funding_usdt": str(event_sum),
        "event_timestamp_position_total_funding_usdt": str(sum(Decimal(e["funding_cashflow_event_clock_usdt"]) for e in events)),
        "position_timing_sensitivity_usdt": str(sum(Decimal(e["funding_cashflow_event_clock_usdt"]) - Decimal(e["funding_cashflow_usdt"]) for e in events)),
        "position_timing_ambiguous_events": conservative_events_different,
        "exact_mark_overlap_count": len(overlap_errors),
        "candle_proxy_error_median_abs_bps": str(sorted(overlap_errors)[len(overlap_errors)//2]),
        "candle_proxy_error_max_abs_bps": str(max(overlap_errors)),
        "official_proxy_cashflow_absolute_error_overlap_usdt": str(sum(overlap_cashflow_errors, Decimal())),
        "source_page_count": len(summary["api_pages"]),
        "hashes_verified": True,
        "native_equity_plus_funding_identity_verified": True,
        "holdout_unopened": True,
        "scientific_boundary": "The overlay holds original native fills fixed; it is not a funding-aware re-execution."
    }
    (OUT / "funding_repair_independent_verification.json").write_text(json.dumps(result, indent=2) + "\n")
    return result

if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
