"""Audit BTCUSDT perpetual funding inputs for the 2024-bounded allocation study.

This module reconciles observed funding events to the signed position held
strictly before each UTC settlement boundary. It does not run a strategy or
estimate performance. The canonical funding store has null mark prices, so
cash settlement remains blocked until exact settlement marks are available.
"""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
import hashlib
import json
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import polars as pl


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "run_log/independent_five_full_history_20261014/donchian-btc"
FUNDING_STORE = Path(
    "/home/quant/dev/quant/ml4t-data/.data/store/crypto_futures_funding_BTCUSDT_PERP"
)
DEVELOPMENT_END = datetime(2025, 1, 1, tzinfo=timezone.utc)
STRATEGY_START = datetime(2019, 11, 9, tzinfo=timezone.utc)
OUTPUT_DIR = ROOT / "run_log/allocation_prerequisites_20261014/btc"
RAW_BINANCE_DIR = OUTPUT_DIR / "binance_raw"
BINANCE_ENDPOINT = "https://fapi.binance.com/fapi/v1/fundingRate"
BINANCE_DOCS = "https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History"
BINANCE_START_MS = 1567296000000  # 2019-09-01T00:00:00.000Z
BINANCE_END_MS = 1735689599999  # 2024-12-31T23:59:59.999Z, inclusive
BINANCE_LIMIT = 1000
USER_AGENT = "OpenAI File Downloader, XaiImageApiFetch/1.0"


def _decimal(value: object, *, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{label} is not a valid decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{label} must be finite")
    return result


def signed_funding_cashflow_usdt(
    signed_btc_quantity: Decimal | float, funding_mark_price: Decimal | float, funding_rate: Decimal | float
) -> Decimal:
    """Return settlement cashflow: positive is a credit, negative is a debit."""
    signed_quantity = _decimal(signed_btc_quantity, label="signed_btc_quantity")
    mark_price = _decimal(funding_mark_price, label="funding_mark_price")
    rate = _decimal(funding_rate, label="funding_rate")
    if mark_price <= 0:
        raise ValueError("funding_mark_price must be positive")
    return -signed_quantity * mark_price * rate


def _as_utc(value: datetime, *, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _schedule_slot_utc(value: datetime) -> datetime:
    """Return an hour slot for cadence checks only, not position matching."""
    value = _as_utc(value, label="funding timestamp")
    return value.replace(minute=0, second=0, microsecond=0)


@dataclass(frozen=True)
class PreparedFills:
    times: tuple[datetime, ...]
    cumulative_signed_btc: tuple[Decimal, ...]


def _prepare_fills(rows: list[tuple[datetime, Decimal | float]]) -> PreparedFills:
    """Validate strict timestamp order and uniqueness before binary search."""
    times: list[datetime] = []
    cumulative: list[Decimal] = []
    position = Decimal(0)
    previous: datetime | None = None
    for timestamp, signed_quantity in rows:
        timestamp = _as_utc(timestamp, label="fill timestamp")
        signed_quantity = _decimal(signed_quantity, label="signed fill quantity")
        if not signed_quantity.is_finite():
            raise ValueError("fill quantity must be finite")
        if previous is not None and timestamp <= previous:
            reason = "duplicate fill timestamp collision" if timestamp == previous else "fill timestamps are out of order"
            raise ValueError(reason)
        position += signed_quantity
        if not position.is_finite():
            raise ValueError("cumulative signed position must be finite")
        times.append(timestamp)
        cumulative.append(position)
        previous = timestamp
    return PreparedFills(tuple(times), tuple(cumulative))


def _position_before_event(
    fills: PreparedFills, event_timestamp: datetime
) -> Decimal:
    """Use original event precision and include fills only when timestamp < event."""
    event_timestamp = _as_utc(event_timestamp, label="funding timestamp")
    prior_fill_count = bisect_left(fills.times, event_timestamp)
    return fills.cumulative_signed_btc[prior_fill_count - 1] if prior_fill_count else Decimal(0)


def _read_development_fills(path: Path) -> list[tuple[datetime, Decimal]]:
    """Read only fill rows through 2024; stop before parsing later outcomes."""
    rows: list[tuple[datetime, float]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            raw_time = row["timestamp"]
            if raw_time[:10] >= "2025-01-01":
                break
            timestamp = datetime.fromisoformat(raw_time)
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            else:
                timestamp = timestamp.astimezone(timezone.utc)
            quantity = _decimal(row["quantity"], label="fill quantity")
            if quantity <= 0:
                raise ValueError("fill quantity must be finite and positive")
            side = row["side"].strip().lower()
            if side not in {"buy", "sell"}:
                raise ValueError(f"unsupported fill side: {row['side']!r}")
            signed_quantity = quantity if side == "buy" else -quantity
            rows.append((timestamp, signed_quantity))
    _prepare_fills(rows)  # Fail closed before any funding position lookup.
    return rows


def _development_funding() -> pl.DataFrame:
    files = sorted(
        path
        for path in FUNDING_STORE.glob("year=*/month=*/data.parquet")
        if path.parent.parent.name.removeprefix("year=").isdigit()
        and int(path.parent.parent.name.removeprefix("year=")) <= 2024
    )
    if not files:
        raise FileNotFoundError(f"No development funding files in {FUNDING_STORE}")
    return (
        pl.scan_parquet([str(path) for path in files])
        .filter(pl.col("timestamp") < pl.lit(DEVELOPMENT_END))
        .select("timestamp", "symbol", "funding_interval_hours", "funding_rate", "mark_price")
        .collect()
        .sort("timestamp")
    )


def _next_start_time_ms(rows: list[dict[str, object]]) -> int | None:
    """Advance past the last inclusive fundingTime without repeating it."""
    if not rows:
        return None
    last_time = int(rows[-1]["fundingTime"])
    if any(int(row["fundingTime"]) >= last_time for row in rows[:-1]):
        raise ValueError("API page fundingTime values must be strictly ascending")
    return last_time + 1


def _request_binance_history() -> tuple[list[dict[str, object]], dict[str, object]]:
    """Fetch only Sep 2019 through Dec 2024 and preserve each raw page."""
    RAW_BINANCE_DIR.mkdir(parents=True, exist_ok=True)
    cursor = BINANCE_START_MS
    pages: list[dict[str, object]] = []
    records: list[dict[str, object]] = []
    previous_time: int | None = None
    page_number = 0
    while cursor <= BINANCE_END_MS:
        params = urlencode(
            {
                "symbol": "BTCUSDT",
                "startTime": cursor,
                "endTime": BINANCE_END_MS,
                "limit": BINANCE_LIMIT,
            }
        )
        url = f"{BINANCE_ENDPOINT}?{params}"
        requested_at = datetime.now(timezone.utc).isoformat()
        request = Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read()
                status_code = response.status
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            error_body = exc.read() if isinstance(exc, HTTPError) else b""
            raw_path = RAW_BINANCE_DIR / f"page_{page_number:04d}_error.bin"
            raw_path.write_bytes(error_body)
            pages.append(
                {
                    "request_url": url,
                    "request_started_utc": requested_at,
                    "response_received_utc": datetime.now(timezone.utc).isoformat(),
                    "http_status": getattr(exc, "code", None),
                    "raw_response_path": str(raw_path.relative_to(ROOT)),
                    "response_sha256": hashlib.sha256(error_body).hexdigest(),
                    "response_bytes": len(error_body),
                    "error": str(exc),
                }
            )
            provenance = _binance_provenance(pages, "BLOCKED_API_ERROR")
            (OUTPUT_DIR / "binance_provenance.json").write_text(
                json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            raise RuntimeError(f"Binance request failed; see binance_provenance.json: {exc}") from exc

        received_at = datetime.now(timezone.utc).isoformat()
        raw_path = RAW_BINANCE_DIR / f"page_{page_number:04d}.json"
        raw_path.write_bytes(raw)
        page_info: dict[str, object] = {
            "request_url": url,
            "request_started_utc": requested_at,
            "response_received_utc": received_at,
            "http_status": status_code,
            "raw_response_path": str(raw_path.relative_to(ROOT)),
            "response_sha256": hashlib.sha256(raw).hexdigest(),
            "response_bytes": len(raw),
        }
        pages.append(page_info)
        try:
            page_records = json.loads(raw)
            if not isinstance(page_records, list):
                raise ValueError("response JSON is not a list")
            if len(page_records) > BINANCE_LIMIT:
                raise ValueError("response exceeds requested page limit")
            page_times = [int(row["fundingTime"]) for row in page_records]
            if any(right <= left for left, right in zip(page_times, page_times[1:])):
                raise ValueError("response event times are duplicated or out of order")
            if page_times and (page_times[0] < cursor or page_times[-1] > BINANCE_END_MS):
                raise ValueError("response contains an event outside the requested development window")
            if page_times and previous_time is not None and page_times[0] <= previous_time:
                raise ValueError("pagination repeated or reordered an event")
            for row in page_records:
                if row.get("symbol") != "BTCUSDT":
                    raise ValueError("API response contains a non-BTCUSDT row")
            page_info["rows"] = len(page_records)
            records.extend(page_records)
            if page_times:
                previous_time = page_times[-1]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            page_info["validation_error"] = str(exc)
            provenance = _binance_provenance(pages, "BLOCKED_RESPONSE_VALIDATION")
            (OUTPUT_DIR / "binance_provenance.json").write_text(
                json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            raise RuntimeError(f"Binance response failed validation: {exc}") from exc

        provenance = _binance_provenance(pages, "RETRIEVING")
        (OUTPUT_DIR / "binance_provenance.json").write_text(
            json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        page_number += 1
        if len(page_records) < BINANCE_LIMIT:
            break
        next_cursor = _next_start_time_ms(page_records)
        if next_cursor is None or next_cursor <= cursor:
            raise RuntimeError("Binance pagination cursor did not advance")
        cursor = next_cursor
        time.sleep(0.25)

    return records, _binance_provenance(pages, "RETRIEVED")


def _binance_provenance(pages: list[dict[str, object]], status: str) -> dict[str, object]:
    return {
        "source": BINANCE_ENDPOINT,
        "official_documentation": BINANCE_DOCS,
        "documentation_observation": "GET /fapi/v1/fundingRate; startTime/endTime inclusive; limit max 1000; ascending; response markPrice is the mark associated with funding fee charge.",
        "status": status,
        "retrieval_started_utc": pages[0]["request_started_utc"] if pages else None,
        "retrieval_updated_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "symbol": "BTCUSDT",
            "start_time_ms_inclusive": BINANCE_START_MS,
            "start_time_utc": "2019-09-01T00:00:00.000Z",
            "end_time_ms_inclusive": BINANCE_END_MS,
            "end_time_utc": "2024-12-31T23:59:59.999Z",
            "limit_per_request": BINANCE_LIMIT,
            "user_agent": USER_AGENT,
            "credentials_used": False,
            "future_data_requested": False,
        },
        "page_count": len(pages),
        "row_count": sum(int(page.get("rows", 0)) for page in pages),
        "pages": pages,
    }


def _epoch_milliseconds(timestamp: datetime) -> int:
    timestamp = _as_utc(timestamp, label="funding timestamp")
    if timestamp.microsecond % 1000:
        raise ValueError("local funding timestamp is not aligned to UTC milliseconds")
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = timestamp - epoch
    return delta.days * 86_400_000 + delta.seconds * 1000 + delta.microseconds // 1000


def _join_exchange_rows(
    local_rows: list[dict[str, object]], exchange_rows: list[dict[str, object]]
) -> list[dict[str, object]]:
    """Require a one-to-one exact timestamp and rate match; return mark prices."""
    local_by_time: dict[int, dict[str, object]] = {}
    for row in local_rows:
        timestamp_ms = int(row["timestamp_ms"])
        if timestamp_ms in local_by_time:
            raise ValueError(f"duplicate local funding timestamp: {timestamp_ms}")
        local_by_time[timestamp_ms] = row
    exchange_by_time: dict[int, dict[str, object]] = {}
    previous: int | None = None
    for row in exchange_rows:
        timestamp_ms = int(row["fundingTime"])
        if timestamp_ms in exchange_by_time:
            raise ValueError(f"duplicate Binance funding timestamp: {timestamp_ms}")
        if previous is not None and timestamp_ms <= previous:
            raise ValueError("Binance funding timestamps are not strictly ascending")
        exchange_by_time[timestamp_ms] = row
        previous = timestamp_ms
    if local_by_time.keys() != exchange_by_time.keys():
        missing = sorted(local_by_time.keys() - exchange_by_time.keys())
        extra = sorted(exchange_by_time.keys() - local_by_time.keys())
        raise ValueError(f"timestamp set mismatch: missing_exchange={len(missing)} extra_exchange={len(extra)}")

    matched: list[dict[str, object]] = []
    for timestamp_ms in sorted(local_by_time):
        local = local_by_time[timestamp_ms]
        exchange = exchange_by_time[timestamp_ms]
        local_rate = _decimal(local["funding_rate"], label="local funding_rate")
        exchange_rate = _decimal(exchange["fundingRate"], label="Binance fundingRate")
        if local_rate != exchange_rate:
            raise ValueError(
                f"funding rate mismatch at {timestamp_ms}: local={local_rate} Binance={exchange_rate}"
            )
        if exchange.get("markPrice") in (None, ""):
            raise ValueError(f"missing Binance markPrice at {timestamp_ms}")
        mark_price = _decimal(exchange["markPrice"], label="Binance markPrice")
        if mark_price <= 0:
            raise ValueError(f"nonpositive Binance markPrice at {timestamp_ms}")
        matched.append({**local, "markPrice": str(mark_price), "fundingRate": str(exchange_rate)})
    return matched


def _local_funding_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in _development_funding().iter_rows(named=True):
        timestamp = _as_utc(row["timestamp"], label="local funding timestamp")
        rows.append(
            {
                "timestamp_ms": _epoch_milliseconds(timestamp),
                "timestamp_utc": timestamp,
                "symbol": row["symbol"],
                "funding_rate": str(row["funding_rate"]),
                "local_mark_price": row["mark_price"],
            }
        )
    return rows


def _read_development_equity(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        previous: datetime | None = None
        for row in reader:
            raw_time = row["timestamp"]
            if raw_time[:10] >= "2025-01-01":
                break
            timestamp = datetime.fromisoformat(raw_time)
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            else:
                timestamp = timestamp.astimezone(timezone.utc)
            if previous is not None and timestamp <= previous:
                raise ValueError("native equity timestamps must be sorted and unique")
            row["_timestamp"] = timestamp
            row["_equity"] = _decimal(row["equity"], label="native equity")
            row["_return"] = _decimal(row["return"], label="native daily return")
            rows.append(row)
            previous = timestamp
    return rows


def _write_exact_ledger_and_daily_effect(
    matched: list[dict[str, object]], fills: PreparedFills
) -> dict[str, object]:
    exact_rows: list[dict[str, object]] = []
    daily_cashflows: dict[object, Decimal] = {}
    for row in matched:
        event_timestamp = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(
            milliseconds=int(row["timestamp_ms"])
        )
        position = _position_before_event(fills, event_timestamp)
        rate = _decimal(row["fundingRate"], label="fundingRate")
        mark_price = _decimal(row["markPrice"], label="markPrice")
        cashflow = signed_funding_cashflow_usdt(position, mark_price, rate)
        daily_cashflows[event_timestamp.date()] = daily_cashflows.get(
            event_timestamp.date(), Decimal(0)
        ) + cashflow
        exact_rows.append(
            {
                "funding_timestamp_utc": event_timestamp.isoformat(timespec="milliseconds"),
                "position_btc_before_event": str(position),
                "funding_rate": str(rate),
                "mark_price_usdt": str(mark_price),
                "cashflow_usdt": str(cashflow),
                "cashflow_sign": "credit" if cashflow > 0 else "debit" if cashflow < 0 else "zero",
            }
        )

    exact_path = OUTPUT_DIR / "funding_events_exact.csv"
    with exact_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(exact_rows[0]))
        writer.writeheader()
        writer.writerows(exact_rows)

    equity_rows = _read_development_equity(LEDGER / "equity.csv")
    equity_dates = {row["_timestamp"].date() for row in equity_rows}
    missing_equity_dates = sorted(set(daily_cashflows) - equity_dates)
    if missing_equity_dates:
        raise ValueError(f"native equity missing UTC dates with funding: {missing_equity_dates[:5]}")

    cumulative_funding = Decimal(0)
    prior_adjusted_equity: Decimal | None = None
    daily_rows: list[dict[str, object]] = []
    for row in equity_rows:
        date = row["_timestamp"].date()
        cashflow = daily_cashflows.get(date, Decimal(0))
        cumulative_funding += cashflow
        native_equity = row["_equity"]
        adjusted_equity = native_equity + cumulative_funding
        adjusted_return = (
            Decimal(0)
            if prior_adjusted_equity is None
            else adjusted_equity / prior_adjusted_equity - Decimal(1)
        )
        native_return = row["_return"]
        daily_rows.append(
            {
                "date_utc": date.isoformat(),
                "native_equity_usdt": str(native_equity),
                "daily_funding_cashflow_usdt": str(cashflow),
                "cumulative_funding_cashflow_usdt": str(cumulative_funding),
                "funding_adjusted_equity_usdt": str(adjusted_equity),
                "native_daily_return": str(native_return),
                "funding_adjusted_daily_return": str(adjusted_return),
                "daily_return_delta": str(adjusted_return - native_return),
            }
        )
        prior_adjusted_equity = adjusted_equity

    daily_path = OUTPUT_DIR / "funding_daily_equity_effect.csv"
    with daily_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(daily_rows[0]))
        writer.writeheader()
        writer.writerows(daily_rows)

    total_cashflow = sum((Decimal(str(row["cashflow_usdt"])) for row in exact_rows), Decimal(0))
    return {
        "exact_funding_events": len(exact_rows),
        "exact_event_ledger": str(exact_path.relative_to(ROOT)),
        "daily_equity_effect_ledger": str(daily_path.relative_to(ROOT)),
        "daily_equity_rows": len(daily_rows),
        "total_funding_cashflow_usdt": str(total_cashflow),
        "final_native_equity_usdt": str(equity_rows[-1]["_equity"]),
        "final_funding_adjusted_equity_usdt": daily_rows[-1]["funding_adjusted_equity_usdt"],
        "equity_method": "additive funding cashflow overlay on frozen native daily equity, grouped by UTC date; positions and strategy sizing are unchanged",
        "daily_timestamp_limit": "native equity timestamp is a daily session label, not an intraday mark clock",
    }


def retrieve_and_reconcile_binance() -> dict[str, object]:
    """Retrieve official public funding data and fail closed on any join defect."""
    result = reconcile()
    try:
        exchange_rows, provenance = _request_binance_history()
        local_rows = _local_funding_rows()
        matched = _join_exchange_rows(local_rows, exchange_rows)
        fills = _prepare_fills(_read_development_fills(LEDGER / "fills.csv"))
        exact_effect = _write_exact_ledger_and_daily_effect(matched, fills)
        provenance.update(
            {
                "status": "VERIFIED_EXACT_MATCH",
                "local_event_count": len(local_rows),
                "exchange_event_count": len(exchange_rows),
                "matched_event_count": len(matched),
                "exact_match": True,
            }
        )
        (OUTPUT_DIR / "binance_provenance.json").write_text(
            json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        result["binance_retrieval"] = provenance
        result["exact_accounting"] = exact_effect
        result["status"] = "VERIFIED_INPUTS"
    except Exception as exc:
        provenance_path = OUTPUT_DIR / "binance_provenance.json"
        if provenance_path.exists():
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        else:
            provenance = _binance_provenance([], "BLOCKED_BEFORE_REQUEST")
        provenance["status"] = "BLOCKED"
        provenance["blocking_error"] = f"{type(exc).__name__}: {exc}"
        (OUTPUT_DIR / "binance_provenance.json").write_text(
            json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        result["binance_retrieval"] = provenance
        result["status"] = "BLOCKED"
        result["accounting"]["blocker"] = str(provenance["blocking_error"])
    (OUTPUT_DIR / "reconciliation.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def reconcile() -> dict[str, object]:
    """Write a bounded event ledger and machine-readable prerequisite result."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fills = _read_development_fills(LEDGER / "fills.csv")
    funding = _development_funding()

    if funding.get_column("symbol").unique().to_list() != ["BTCUSDT"]:
        raise ValueError("Funding symbol identity is not exactly BTCUSDT")
    interval_values = set(funding.get_column("funding_interval_hours").unique().to_list())
    if not interval_values.issubset({8, None}):
        raise ValueError("Funding interval contains values other than eight hours or null")

    prepared_fills = _prepare_fills(fills)
    funding_timestamps = [
        _as_utc(event["timestamp"], label="funding timestamp")
        for event in funding.iter_rows(named=True)
    ]
    if any(right <= left for left, right in zip(funding_timestamps, funding_timestamps[1:])):
        raise ValueError("funding timestamps must be sorted and unique")
    schedule_slots = [_schedule_slot_utc(timestamp) for timestamp in funding_timestamps]
    if len(schedule_slots) != len(set(schedule_slots)):
        raise ValueError("funding schedule slot collision")

    events: list[dict[str, object]] = []
    for event, event_timestamp, schedule_slot in zip(
        funding.iter_rows(named=True), funding_timestamps, schedule_slots, strict=True
    ):
        # Compare the original timezone-aware source timestamp. Do not round
        # subsecond settlement times before applying strict-before.
        held_btc = _position_before_event(prepared_fills, event_timestamp)
        rate = float(event["funding_rate"])
        mark = event["mark_price"]
        settlement = (
            signed_funding_cashflow_usdt(held_btc, float(mark), rate)
            if mark is not None
            else None
        )
        events.append(
            {
                "funding_timestamp_utc": event_timestamp.isoformat(),
                "funding_schedule_slot_utc": schedule_slot.isoformat(),
                "source_timestamp_utc": event_timestamp.isoformat(),
                "position_btc_before_event": held_btc,
                "funding_rate": rate,
                "funding_mark_price_usdt": mark,
                "settlement_cashflow_usdt": settlement,
                "settlement_status": "exact" if settlement is not None else "blocked_null_mark_price",
            }
        )

    hours = [datetime.fromisoformat(str(row["funding_schedule_slot_utc"])) for row in events]
    active_start = next((timestamp for timestamp in hours if timestamp >= STRATEGY_START), None)
    if active_start is None:
        raise ValueError("No funding events overlap the strategy's active ledger")
    expected: list[datetime] = []
    current = active_start
    last_event = max(hours)
    while current <= last_event:
        expected.append(current)
        current += timedelta(hours=8)
    observed = {timestamp for timestamp in hours if timestamp >= active_start}
    expected_set = set(expected)
    missing = [timestamp.isoformat() for timestamp in expected if timestamp not in observed]
    unexpected = [timestamp.isoformat() for timestamp in observed if timestamp not in expected_set]

    with (OUTPUT_DIR / "funding_events.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(events[0]))
        writer.writeheader()
        writer.writerows(events)

    fill_times = list(prepared_fills.times)
    result = {
        "status": "BLOCKED" if any(row["settlement_status"] != "exact" for row in events) or missing else "VERIFIED_INPUTS",
        "scope": {
            "instrument": "Binance BTCUSDT USDT-margined perpetual",
            "development_end_exclusive_utc": DEVELOPMENT_END.isoformat(),
            "strategy_active_ledger_start_utc": STRATEGY_START.isoformat(),
            "future_rows_read": False,
        },
        "funding": {
            "rows": len(events),
            "first_event_utc": min(hours).isoformat(),
            "last_event_utc": max(hours).isoformat(),
            "interval_hours": 8,
            "null_interval_metadata_rows": funding.filter(
                pl.col("funding_interval_hours").is_null()
            ).height,
            "missing_expected_events_during_active_period": len(missing),
            "unexpected_event_boundaries": len(unexpected),
            "null_mark_price_rows": sum(row["funding_mark_price_usdt"] is None for row in events),
        },
        "fills": {
            "development_rows": len(fills),
            "first_fill_utc": min(fill_times).isoformat() if fill_times else None,
            "last_development_fill_utc": max(fill_times).isoformat() if fill_times else None,
            "position_rule": "sum signed fills with fill timestamp strictly before original timezone-aware UTC funding timestamp",
            "fill_timestamps_sorted_unique": True,
            "same_timestamp_fill_collisions": 0,
            "same_timestamp_fills_excluded": True,
        },
        "accounting": {
            "cashflow_formula_usdt": "-signed_position_btc * funding_mark_price_usdt * funding_rate",
            "positive_cashflow_means_credit": True,
            "exact_cash_settlement_available": False,
            "blocker": "Canonical funding mark_price is null for all development events; daily/one-minute close proxies are not exact settlement marks.",
        },
        "diagnostics": {
            "checks_passed_before_diagnostics": [
                "fill timestamps sorted and unique",
                "fill sides limited to buy/sell",
                "fill quantities finite and positive",
                "funding timestamps timezone-aware, sorted, and unique",
                "funding schedule slots collision-free",
                "positions use strict-before comparison at original event precision",
            ],
            "fill_order_validation": "PASS",
            "funding_timestamp_validation": "PASS",
            "position_match_precision": "original timezone-aware source timestamp; no flooring",
        },
        "missing_events": missing,
        "unexpected_events": unexpected,
    }
    (OUTPUT_DIR / "reconciliation.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


if __name__ == "__main__":
    print(json.dumps(retrieve_and_reconcile_binance(), indent=2, sort_keys=True))
