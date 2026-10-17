"""Build Tokyo bank calendar from audited official dates; read no prices."""
from __future__ import annotations

import calendar
import csv
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent
    source = json.loads((root / "holidays.json").read_text())
    start, end = map(date.fromisoformat, (source["start"], source["end_inclusive"]))
    national = set(map(date.fromisoformat, source["public_holidays"]))
    bank = set(map(date.fromisoformat, source["additional_bank_holidays"]))

    def is_business(day: date) -> bool:
        # Apply the statutory bank closure rule beyond the in-scope date list.
        # Backward roll of January 5, 2020 reaches December 2019.
        year_end_bank_closure = (day.month == 12 and day.day == 31) or (
            day.month == 1 and day.day <= 3
        )
        return day.weekday() < 5 and day not in national and not year_end_bank_closure

    def previous_business(day: date) -> date:
        while not is_business(day):
            day -= timedelta(days=1)
        return day

    nominal_map: dict[date, list[date]] = {}
    nominal_events = []
    month_ends = set()
    quarter_ends = set()
    for year in range(start.year, end.year + 1):
        for month in range(1, 13):
            first = date(year, month, 1)
            if first > end:
                continue
            last = date(year, month, calendar.monthrange(year, month)[1])
            final_business = previous_business(last)
            month_ends.add(final_business)
            if month in (3, 6, 9, 12):
                quarter_ends.add(final_business)
            for dom in (5, 10, 15, 20, 25, 30):
                if dom > last.day:
                    continue
                nominal = date(year, month, dom)
                if nominal > end:
                    continue
                observed = previous_business(nominal)
                nominal_map.setdefault(observed, []).append(nominal)
                nominal_events.append({"nominal_date": nominal.isoformat(),
                    "nominal_day": dom, "event_date": observed.isoformat(),
                    "is_rolled": observed != nominal,
                    "roll_days": (nominal - observed).days,
                    "rule_status": "RESEARCH_ASSUMPTION_PREVIOUS_BANK_BUSINESS_DAY"})
    days = []
    day = start
    while day <= end:
        nominals = nominal_map.get(day, [])
        rolled = [n for n in nominals if n != day]
        business = is_business(day)
        days.append({"date": day.isoformat(), "weekday": day.weekday(),
            "tokyo_bank_business_day": business, "national_holiday": day in national,
            "additional_bank_holiday": day in bank, "gotobi": bool(nominals),
            "nominal_gotobi_on_date": day in nominals,
            "rolled_gotobi": bool(rolled),
            "nominal_dates": ";".join(n.isoformat() for n in nominals),
            "nominal_days": ";".join(str(n.day) for n in nominals),
            "month_end_bank_business_day": day in month_ends,
            "quarter_end_bank_business_day": day in quarter_ends,
            "calendar_month_end": day.day == calendar.monthrange(day.year, day.month)[1],
            "friday": day.weekday() == 4,
            "ordinary_bank_business_day": business and not nominals,
            "negative_control_dom_2_7_12_17_22_27": business and not nominals and day.day in (2, 7, 12, 17, 22, 27)})
        day += timedelta(days=1)
    assert len(national) == 120
    assert len(days) == (end - start).days + 1
    assert all(is_business(date.fromisoformat(e["event_date"])) for e in nominal_events)
    assert all(date.fromisoformat(e["event_date"]) <= date.fromisoformat(e["nominal_date"]) for e in nominal_events)
    assert all(e["nominal_day"] != 30 or date.fromisoformat(e["nominal_date"]).month != 2 for e in nominal_events)
    assert date(2020, 7, 23) in national and date(2020, 7, 24) in national
    assert date(2020, 8, 10) in national and date(2020, 8, 11) not in national
    assert date(2021, 7, 22) in national and date(2021, 7, 23) in national
    assert date(2021, 8, 8) in national and date(2021, 8, 9) in national
    assert date(2021, 8, 11) not in national
    assert previous_business(date(2020, 5, 5)) == date(2020, 5, 1)
    assert previous_business(date(2020, 1, 5)) == date(2019, 12, 30)
    assert not is_business(date(2019, 12, 31))
    assert previous_business(date(2021, 1, 5)) == date(2021, 1, 5)
    assert previous_business(date(2022, 12, 31)) == date(2022, 12, 30)
    with (root / "calendar_dates.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(days[0]))
        writer.writeheader()
        writer.writerows(days)
    (root / "nominal_gotobi_events.json").write_text(json.dumps(nominal_events, indent=2) + "\n")
    audit = {"calendar_days": len(days), "bank_business_days": sum(d["tokyo_bank_business_day"] for d in days),
        "gotobi_event_days": sum(d["gotobi"] for d in days),
        "nominal_events": len(nominal_events), "rolled_events": sum(e["is_rolled"] for e in nominal_events),
        "month_ends": sum(d["month_end_bank_business_day"] for d in days),
        "quarter_ends": sum(d["quarter_end_bank_business_day"] for d in days),
        "assertions": "PASSED", "price_data_read": False,
        "holdout_price_outcomes_read": False,
        "by_year": {str(y): {"business_days": sum(d["tokyo_bank_business_day"] for d in days if d["date"].startswith(str(y))),
            "gotobi_days": sum(d["gotobi"] for d in days if d["date"].startswith(str(y)))} for y in range(2020, 2027)},
        "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.is_file() and p.name != "verification.json"}}
    (root / "verification.json").write_text(json.dumps(audit, indent=2) + "\n")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
