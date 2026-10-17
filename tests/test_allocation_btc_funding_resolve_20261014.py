from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from scripts import allocation_btc_funding_20261014 as old
from scripts import allocation_btc_funding_resolve_20261014 as mod


def ms(y, m, d, hour):
    return int(datetime(y, m, d, hour, tzinfo=UTC).timestamp() * 1000)


def local(t, rate="0.0001", jitter=6):
    return {"timestamp_ms": t + jitter, "funding_rate": rate}


def funding(t, rate="0.0001", mark=""):
    return {"symbol": "BTCUSDT", "fundingTime": t, "fundingRate": rate, "markPrice": mark}


def kline(t, close="100000"):
    return [t - mod.EIGHT_HOURS_MS, "0", "0", "0", close, "0", t - 1, "0", 0]


def test_valid_slot_preserves_ingestion_jitter():
    t = ms(2024, 1, 2, 8)
    assert mod.valid_slot(t+47) == t
    with pytest.raises(ValueError, match=">1 second"):
        mod.valid_slot(t+3000)


def test_exact_exchange_mark_precedes_kline_proxy_and_fallback():
    t = ms(2024, 1, 2, 8)
    got = mod.resolve_funding_marks([local(t)], [funding(t, mark="99999")],
                                   [kline(t, "99500")])
    assert got[0]["mark_price"] == Decimal(99999)
    assert got[0]["price_quality"] == "OFFICIAL_FUNDING_SETTLEMENT_MARK"
    assert got[0]["candle_proxy"] == Decimal(99500)


def test_official_8h_mark_proxy_precise_interval():
    t = ms(2024, 1, 2, 8)
    got = mod.resolve_funding_marks([local(t)], [funding(t)], [kline(t, "99200")])
    assert got[0]["mark_price"] == Decimal(99200)
    assert got[0]["price_quality"] == "OFFICIAL_MARK_8H_CLOSE_PROXY"


def test_early_fallback_only_when_missing_official_mark():
    t = ms(2019, 11, 9, 8)
    got = mod.resolve_funding_marks([local(t)], [funding(t)], [], {t: Decimal(9000)})
    assert got[0]["price_quality"] == "LOCAL_PERP_1M_CLOSE_PROXY"


def test_never_guess_if_mark_missing():
    t = ms(2024, 1, 2, 8)
    with pytest.raises(ValueError, match="No mark"):
        mod.resolve_funding_marks([local(t)], [funding(t)], [], {})


def test_rate_or_timestamp_mismatch_fails_closed():
    t = ms(2024, 1, 2, 8)
    with pytest.raises(ValueError, match="rate mismatch"):
        mod.resolve_funding_marks([local(t)], [funding(t, rate="0.0002")], [kline(t)])
    with pytest.raises(ValueError, match="slot mismatch"):
        mod.resolve_funding_marks([local(t)], [funding(t + mod.EIGHT_HOURS_MS)], [kline(t)])


def test_holdout_slot_is_rejected():
    with pytest.raises(ValueError, match="out-of-development"):
        mod.valid_slot(ms(2025, 1, 1, 0))


def test_same_clock_fill_has_two_timing_conventions():
    slot = ms(2024, 1, 2, 8)
    fills = old._prepare_fills([
        (datetime.fromtimestamp(slot / 1000, UTC), Decimal(1)),
        (datetime.fromtimestamp((slot + 8 * 3600 * 1000) / 1000, UTC), Decimal(-1))
    ])
    events = [{"event_ms": slot + 6, "scheduled_ms": slot, "mark_price": Decimal(100000),
               "funding_rate": Decimal("0.001"),
               "price_quality": "OFFICIAL_MARK_8H_CLOSE_PROXY",
               "official_mark": None, "candle_proxy": Decimal(100000)}]
    equity = [{"_timestamp": datetime.fromtimestamp((slot + mod.EIGHT_HOURS_MS) / 1000, UTC),
               "_equity": Decimal(100000), "_return": Decimal(0)}]
    ev, _, audit = mod.compute_accounting(events, equity, fills)
    assert ev[0]["position_btc_conservative"] == "0"
    assert ev[0]["position_btc_original_timestamp"] == "1"
    assert Decimal(ev[0]["funding_cashflow_usdt"]) == 0
    assert Decimal(ev[0]["funding_cashflow_event_clock_usdt"]) == -100
    assert audit["same_slot_fill_ambiguous_count"] == 1


def test_daily_overlay_does_not_book_same_time_event():
    slot = ms(2024, 1, 2, 8)
    fills = old._prepare_fills([(datetime.fromtimestamp((slot - 3600000) / 1000, UTC), Decimal(1))])
    events = [{"event_ms": slot, "scheduled_ms": slot, "mark_price": Decimal(100000),
               "funding_rate": Decimal("0.001"), "price_quality": "OFFICIAL_FUNDING_SETTLEMENT_MARK",
               "official_mark": Decimal(100000), "candle_proxy": None}]
    at = datetime.fromtimestamp(slot / 1000, UTC)
    equity = [{"_timestamp": at, "_equity": Decimal(100000), "_return": Decimal(0)},
              {"_timestamp": at + timedelta(days=1), "_equity": Decimal(100000), "_return": Decimal(0)}]
    _, daily, audit = mod.compute_accounting(events, equity, fills)
    assert daily[0]["cumulative_settled_funding_usdt"] == "0"
    assert Decimal(daily[1]["cumulative_settled_funding_usdt"]) == -100
    assert Decimal(audit["last_adjusted_equity_usdt"]) == 99900
