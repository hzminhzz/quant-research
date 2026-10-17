"""Development-only BTC funding repair with explicit exact/proxy mark provenance.

Separate post-hoc funding accounting over the frozen native Donchian fills.
This is NOT a re-run of its execution or risk-based position-sizing engine.
No event from 2025 or later is requested or processed.
"""
from __future__ import annotations

import csv
import hashlib
import json
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import polars as pl

from scripts import allocation_btc_funding_20261014 as original

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "run_log/allocation_prerequisites_20261014/btc"
RAW = OUT / "mark_repair_raw"
EIGHT_HOURS_MS = 8 * 3600 * 1000
DEV_END_MS = 1735689600000   # 2025-01-01 00:00 UTC EXCLUSIVE
START_MS = 1567296000000     # 2019-09-01
UA = "OpenAI File Downloader, XaiImageApiFetch/1.0"
MINUTE_STORE = Path("/home/quant/dev/quant/ml4t-data/.data/store/crypto_futures_minute_BTCUSDT_PERP")
DATE = lambda ms: (datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=ms)).isoformat(timespec="milliseconds")


def valid_slot(time_ms: int) -> int:
    """Funding timestamps have up to 47 ms ingestion jitter; preserve actual event too."""
    if not START_MS <= time_ms < DEV_END_MS:
        raise ValueError("out-of-development funding timestamp")
    slot = (time_ms // EIGHT_HOURS_MS) * EIGHT_HOURS_MS
    if not 0 <= time_ms - slot < 1000:
        raise ValueError("funding timestamp >1 second from scheduled 8h boundary")
    return slot


def _paged(endpoint: str, params: dict[str, str | int], family: str) -> tuple[list, list[dict]]:
    """Read bounded public pages, preserving responses and request identities."""
    RAW.mkdir(parents=True, exist_ok=True)
    cursor = START_MS
    results = []
    manifest = []
    page_num = 0
    prior = -1
    while cursor < DEV_END_MS:
        query = {**params, "startTime": cursor, "endTime": DEV_END_MS - 1, "limit": 1000}
        url = endpoint + "?" + urlencode(query)
        data = None
        error = None
        for retry in range(3):
            try:
                req = Request(url, headers={"User-Agent": UA})
                with urlopen(req, timeout=25) as response:
                    data = response.read()
                break
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                error = str(exc)
                if retry < 2:
                    time.sleep(1 + retry)
        if data is None:
            raise RuntimeError(f"{family} fetch page {page_num}: {error}")
        parsed = json.loads(data)
        if not isinstance(parsed, list):
            raise TypeError(f"Unexpected {family} HTTP response: {str(parsed)[:200]}")
        if len(parsed) > 1000:
            raise ValueError(f"API returned too many {family} entries")
        timestamps = [int(row[0]) if family == "mark_kline" else int(row["fundingTime"]) for row in parsed]
        if timestamps and (timestamps[0] < cursor or timestamps[-1] >= DEV_END_MS):
            raise ValueError(f"Unexpected {family} timestamp outside requested range")
        if timestamps and (timestamps[0] <= prior or any(b <= a for a, b in pairwise(timestamps))):
            raise ValueError(f"Duplicate/out-of-order {family} events")
        path = RAW / f"{family}_{page_num:03}.json"
        path.write_bytes(data)
        manifest.append({"url": url, "path": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(data).hexdigest(),
                         "rows": len(parsed), "first_ms": timestamps[0] if timestamps else None,
                         "last_ms": timestamps[-1] if timestamps else None})
        results.extend(parsed)
        if not timestamps or len(parsed) < 1000:
            break
        prior = timestamps[-1]
        cursor = prior + 1
        page_num += 1
        time.sleep(0.12)
    return results, manifest


def fetch_official() -> tuple[list, list, list[dict]]:
    funding, funding_manifest = _paged("https://fapi.binance.com/fapi/v1/fundingRate",
                                      {"symbol": "BTCUSDT"}, "funding")
    klines, klines_manifest = _paged("https://fapi.binance.com/fapi/v1/markPriceKlines",
                                    {"symbol": "BTCUSDT", "interval": "8h"}, "mark_kline")
    return funding, klines, funding_manifest + klines_manifest


def _original_funding_rates(funding: list[dict]) -> dict[int, dict]:
    indexed: dict[int, dict] = {}
    for row in funding:
        if row.get("symbol") != "BTCUSDT":
            raise ValueError("Wrong funding symbol")
        ts = int(row["fundingTime"])
        slot = valid_slot(ts)
        if slot in indexed:
            raise ValueError("duplicate official funding slot")
        indexed[slot] = row
    return indexed


def _klines_at_prior_boundary(klines: list[list]) -> dict[int, Decimal]:
    marks: dict[int, Decimal] = {}
    for row in klines:
        bar_open_ms = int(row[0])
        bar_close_ms = int(row[6])
        if bar_open_ms % EIGHT_HOURS_MS or bar_close_ms != bar_open_ms + EIGHT_HOURS_MS - 1:
            raise ValueError("Invalid 8h mark candle boundary")
        slot = bar_close_ms + 1
        if slot in marks:
            raise ValueError("Duplicate 8h mark close")
        val = Decimal(str(row[4]))
        if val <= 0 or not val.is_finite():
            raise ValueError("Invalid 8h mark close")
        marks[slot] = val
    return marks


def _early_minute_closes(missing_slots: set[int]) -> dict[int, Decimal]:
    """Fallback only if no official 8h mark candle exists: last fully closed perp minute."""
    if not missing_slots:
        return {}
    if any(datetime.fromtimestamp(ms / 1000, UTC).year != 2019 for ms in missing_slots):
        raise ValueError("Missing post-2019 mark candle: fail closed, no fallback")
    paths = sorted(MINUTE_STORE.glob("year=2019/month=*/data.parquet"))
    if not paths:
        raise FileNotFoundError("2019 BTC perpetual minute source unavailable")
    needed = sorted(slot - 60000 for slot in missing_slots)
    prices = (pl.scan_parquet([str(p) for p in paths])
              .filter(pl.col("timestamp").dt.epoch("ms").is_in(needed))
              .select(pl.col("timestamp").dt.epoch("ms").alias("minute_ms"), "close")
              .collect())
    index = {int(t): Decimal(str(c)) for t, c in prices.iter_rows()}
    if len(index) != len(missing_slots):
        raise ValueError(f"Missing {len(missing_slots) - len(index)} fully closed BTC 1m source bars")
    if any(v <= 0 or not v.is_finite() for v in index.values()):
        raise ValueError("Invalid minute fallback price")
    return {slot: index[slot - 60000] for slot in missing_slots}


def resolve_funding_marks(
    local_rows: list[dict], exchange_funding: list[dict], exchange_klines: list[list],
    minute_fallback: dict[int, Decimal] | None = None
) -> list[dict]:
    """One event per local slot. Use official charge mark, then mark kline, then explicit 2019 proxy."""
    official = _original_funding_rates(exchange_funding)
    candles = _klines_at_prior_boundary(exchange_klines)
    source_slots: set[int] = set()
    for row in local_rows:
        slot = valid_slot(int(row["timestamp_ms"]))
        if slot in source_slots:
            raise ValueError("Duplicate local funding schedule slot")
        source_slots.add(slot)
    if source_slots != set(official):
        raise ValueError(f"Funding slot mismatch local={len(source_slots)} official={len(official)}, missing={len(source_slots - set(official))}, extra={len(set(official)-source_slots)}")
    if minute_fallback is None:
        minute_fallback = _early_minute_closes({s for s in source_slots if s not in candles and not official[s].get("markPrice")})
    results = []
    for row in local_rows:
        local_time = int(row["timestamp_ms"])
        slot = valid_slot(local_time)
        remote = official[slot]
        rate = Decimal(str(remote["fundingRate"]))
        local_rate = Decimal(str(row["funding_rate"]))
        if rate != local_rate:
            raise ValueError(f"Funding rate mismatch at {DATE(slot)}: local={local_rate} Binance={rate}")
        exact = remote.get("markPrice")
        if exact not in (None, ""):
            mark, quality = Decimal(str(exact)), "OFFICIAL_FUNDING_SETTLEMENT_MARK"
        elif slot in candles:
            mark, quality = candles[slot], "OFFICIAL_MARK_8H_CLOSE_PROXY"
        elif slot in minute_fallback:
            mark, quality = minute_fallback[slot], "LOCAL_PERP_1M_CLOSE_PROXY"
        else:
            raise ValueError(f"No mark or proxy for {DATE(slot)}")
        if mark <= 0 or not mark.is_finite():
            raise ValueError("Bad settlement/proxy price")
        results.append({"event_ms": local_time, "scheduled_ms": slot, "funding_rate": rate,
                        "mark_price": mark, "price_quality": quality,
                        "official_mark": Decimal(str(exact)) if exact not in (None, "") else None,
                        "candle_proxy": candles.get(slot)})
    return results


def compute_accounting(events: list[dict], native_equity_rows: list[dict], fills: original.PreparedFills) -> tuple[list[dict], list[dict], dict]:
    """Calculate funding cashflows and an additive overlay on UNCHANGED native equity."""
    funding_events = []
    cumulative = Decimal()
    count_ambiguous = 0
    for e in events:
        ts = datetime.fromtimestamp(e["event_ms"] / 1000, UTC)
        slot_dt = datetime.fromtimestamp(e["scheduled_ms"] / 1000, UTC)
        pos_nominal = original._position_before_event(fills, slot_dt)  # no same-slot fill is included
        pos_raw = original._position_before_event(fills, ts)
        if pos_nominal != pos_raw:
            count_ambiguous += 1
        cf = original.signed_funding_cashflow_usdt(pos_nominal, e["mark_price"], e["funding_rate"])
        cf_raw = original.signed_funding_cashflow_usdt(pos_raw, e["mark_price"], e["funding_rate"])
        funding_events.append({"event_ms": e["event_ms"], "funding_timestamp_utc": DATE(e["event_ms"]),
                               "slot_utc": DATE(e["scheduled_ms"]), "mark_price_usdt": str(e["mark_price"]),
                               "price_quality": e["price_quality"], "funding_rate": str(e["funding_rate"]),
                               "position_btc_conservative": str(pos_nominal),
                               "position_btc_original_timestamp": str(pos_raw),
                               "funding_cashflow_usdt": str(cf),
                               "funding_cashflow_event_clock_usdt": str(cf_raw),
                               "same_slot_fill_timing_differs": pos_nominal != pos_raw,
                               "candle_price_usdt": str(e["candle_proxy"]) if e["candle_proxy"] else "",
                               "official_exact_mark_usdt": str(e["official_mark"]) if e["official_mark"] else ""})
    daily_rows = []
    index = 0
    for row in native_equity_rows:
        snapshot_dt = row["_timestamp"]
        snapshot_ms = original._epoch_milliseconds(snapshot_dt)
        # Native equity has UTC daily LABELS, not funding marks.
        # Same-time funding does not enter the as-of snapshot.
        while index < len(funding_events) and funding_events[index]["event_ms"] < snapshot_ms:
            cumulative += Decimal(funding_events[index]["funding_cashflow_usdt"])
            index += 1
        native_nav = row["_equity"]
        native_ret = row["_return"]
        adjusted = native_nav + cumulative
        daily_rows.append({"timestamp_utc": snapshot_dt.isoformat(),
                           "native_equity_usdt": str(native_nav), "native_return": str(native_ret),
                           "cumulative_settled_funding_usdt": str(cumulative),
                           "funding_adjusted_equity_usdt": str(adjusted)})
    for i, row in enumerate(daily_rows):
        if i == 0:
            row["funding_adjusted_return"] = ""
        else:
            prev = Decimal(daily_rows[i - 1]["funding_adjusted_equity_usdt"])
            row["funding_adjusted_return"] = str(Decimal(row["funding_adjusted_equity_usdt"]) / prev - 1)
    total_cf = sum((Decimal(e["funding_cashflow_usdt"]) for e in funding_events), Decimal())
    return funding_events, daily_rows, {
        "event_count": len(funding_events),
        "total_funding_cashflow_usdt_all_events": str(total_cf),
        "total_funding_embedded_at_last_native_snapshot_usdt": daily_rows[-1]["cumulative_settled_funding_usdt"],
        "unbooked_after_last_native_snapshot_usdt": str(total_cf - Decimal(daily_rows[-1]["cumulative_settled_funding_usdt"])),
        "last_native_equity_usdt": daily_rows[-1]["native_equity_usdt"],
        "last_adjusted_equity_usdt": daily_rows[-1]["funding_adjusted_equity_usdt"],
        "native_rows": len(daily_rows),
        "same_slot_fill_ambiguous_count": count_ambiguous,
        "method": "POST-HOC FIXED-FILL funding cashflow overlay; no size/path feedback; native equity dated UTC day labels",
    }


def _save_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError("Cannot write empty ledger")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    local = original._local_funding_rows()  # 2019-2024 partitions only
    historical, klines, pages = fetch_official()
    repaired = resolve_funding_marks(local, historical, klines)
    filled = original._prepare_fills(original._read_development_fills(original.LEDGER / "fills.csv"))
    equity = original._read_development_equity(original.LEDGER / "equity.csv")
    funding_rows, daily_rows, audit = compute_accounting(repaired, equity, filled)
    _save_csv(OUT / "funding_cashflows_repaired_development.csv", funding_rows)
    _save_csv(OUT / "funding_adjusted_equity_development.csv", daily_rows)
    counts: dict[str, int] = {}
    comparison = []
    for e in repaired:
        counts[e["price_quality"]] = counts.get(e["price_quality"], 0) + 1
        if e["official_mark"] is not None and e["candle_proxy"] is not None:
            comparison.append(abs((e["candle_proxy"] / e["official_mark"] - 1) * 10000))
    result = {
        "status": "EXPLORATORY_REPAIRED_WITH_EXPLICIT_MARK_PROXIES" if counts.get("OFFICIAL_MARK_8H_CLOSE_PROXY", 0) + counts.get("LOCAL_PERP_1M_CLOSE_PROXY", 0) else "EXACT",
        "scope": {"development_end_exclusive": "2025-01-01T00:00:00Z",
                  "strategy": "Donchian BTCUSDT_PERP", "2025_2026_evaluation_opened": False,
                  "native_strategy_fills_unchanged": True},
        "price_sources": counts,
        "proxy_vs_exact_overlap_count": len(comparison),
        "proxy_vs_exact_median_abs_bps": float(sorted(comparison)[len(comparison)//2]) if comparison else None,
        "proxy_vs_exact_max_abs_bps": float(max(comparison)) if comparison else None,
        "funding_accounting": audit,
        "network_source": "Official Binance fapi fundingRate and markPriceKlines, strictly pre-2025; local Binance BTC perpetual 1m fallback for 2019 only",
        "api_pages": pages,
        "limitations": [
            "Mark 8h bar close is immediately before settlement but is not certified as exchange settlement mark.",
            "2019 minute close fallback is contract-specific, not the index/mark price.",
            "Fill ledger has daily timestamps; same-settlement-clock execution order is unresolved. Conservative slot-time positions used; alternative timestamp positions logged.",
            "Post-hoc funding overlay does not recalculate volatility-targeted sizing or execution behavior.",
            "Native account marked daily at UTC date labels. Events strictly earlier than each native equity timestamp are included.",
            "No 2025+ data was fetched or evaluated.",
        ],
    }
    (OUT / "funding_repair_summary.json").write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str)[:12000])
