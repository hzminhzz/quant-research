from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


MODULE_PATH = Path(__file__).parents[1] / "scripts/allocation_btc_funding_20261014.py"
SPEC = importlib.util.spec_from_file_location("allocation_btc_funding_20261014", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize(
    ("signed_position", "rate", "expected_cashflow"),
    [
        (1.0, 0.001, -100.0),
        (-1.0, 0.001, 100.0),
        (1.0, -0.001, 100.0),
        (-1.0, -0.001, -100.0),
    ],
)
def test_funding_cashflow_sign_for_long_short_and_rate_direction(
    signed_position: float, rate: float, expected_cashflow: float
) -> None:
    assert MODULE.signed_funding_cashflow_usdt(signed_position, 100_000.0, rate) == expected_cashflow


def test_funding_cashflow_rejects_nonpositive_mark_price() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        MODULE.signed_funding_cashflow_usdt(1.0, 0.0, 0.001)


def test_funding_schedule_slot_normalizes_utc_for_cadence_only() -> None:
    from datetime import datetime, timezone, timedelta

    timestamp = datetime(2024, 1, 2, 8, 0, 0, 9000, tzinfo=timezone(timedelta(hours=2)))
    assert MODULE._schedule_slot_utc(timestamp).isoformat() == "2024-01-02T06:00:00+00:00"


def test_position_at_boundary_excludes_same_time_fill_then_includes_it_later() -> None:
    from datetime import datetime, timezone

    day_open = datetime(2024, 1, 2, 0, tzinfo=timezone.utc)
    next_funding = datetime(2024, 1, 2, 8, tzinfo=timezone.utc)
    following_open = datetime(2024, 1, 3, 0, tzinfo=timezone.utc)
    fills = MODULE._prepare_fills([(day_open, 1.25), (following_open, -0.75)])

    assert MODULE._position_before_event(fills, day_open) == 0.0
    assert MODULE._position_before_event(fills, next_funding) == 1.25
    assert MODULE._position_before_event(fills, following_open) == 1.25


def test_out_of_order_fill_timestamps_are_rejected() -> None:
    from datetime import datetime, timezone

    first = datetime(2024, 1, 2, 0, tzinfo=timezone.utc)
    second = datetime(2024, 1, 2, 8, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="out of order"):
        MODULE._prepare_fills([(second, 1.0), (first, -1.0)])


def test_duplicate_fill_timestamps_are_rejected_as_collisions() -> None:
    from datetime import datetime, timezone

    same_time = datetime(2024, 1, 2, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="timestamp collision"):
        MODULE._prepare_fills([(same_time, 1.0), (same_time, -1.0)])


def test_subsecond_settlement_uses_original_timestamp_and_excludes_equal_or_future_fills() -> None:
    from datetime import datetime, timezone

    event_time = datetime(2024, 1, 2, 8, 0, 0, 1000, tzinfo=timezone.utc)
    fills = MODULE._prepare_fills(
        [
            (datetime(2024, 1, 2, 8, 0, 0, 0, tzinfo=timezone.utc), 1.0),
            (event_time, 2.0),
            (datetime(2024, 1, 2, 8, 0, 0, 2000, tzinfo=timezone.utc), 4.0),
        ]
    )

    # The 08:00:00.000 fill is strictly before this 08:00:00.001 settlement.
    # The equal-time fill and the later fill are both excluded.
    assert MODULE._position_before_event(fills, event_time) == 1.0


def test_funding_match_rejects_naive_event_timestamp() -> None:
    from datetime import datetime, timezone

    fills = MODULE._prepare_fills([(datetime(2024, 1, 2, tzinfo=timezone.utc), 1.0)])
    with pytest.raises(ValueError, match="timezone-aware"):
        MODULE._position_before_event(fills, datetime(2024, 1, 2, 8))


def test_fill_reader_rejects_unknown_side(tmp_path: Path) -> None:
    source = tmp_path / "fills.csv"
    source.write_text(
        "timestamp,side,quantity\n2024-01-02T00:00:00,buy,1\n"
        "2024-01-02T08:00:00,hold,1\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unsupported fill side"):
        MODULE._read_development_fills(source)


def test_pagination_advances_one_millisecond_after_inclusive_last_event() -> None:
    page = [{"fundingTime": 1_000}, {"fundingTime": 9_000}]
    next_start = MODULE._next_start_time_ms(page)

    assert next_start == 9_001
    # The next inclusive request starts immediately after the last event.
    next_page = [{"fundingTime": 9_001}]
    assert next_page[0]["fundingTime"] >= next_start


def test_pagination_rejects_duplicate_or_unordered_page_events() -> None:
    with pytest.raises(ValueError, match="strictly ascending"):
        MODULE._next_start_time_ms([{"fundingTime": 2}, {"fundingTime": 2}])


def test_exact_join_uses_timestamp_and_rate_and_returns_official_mark() -> None:
    local = [{"timestamp_ms": 1_700_000_000_000, "funding_rate": "0.0001"}]
    exchange = [
        {
            "symbol": "BTCUSDT",
            "fundingTime": 1_700_000_000_000,
            "fundingRate": "0.00010000",
            "markPrice": "42000.12500000",
        }
    ]

    assert MODULE._join_exchange_rows(local, exchange)[0]["markPrice"] == "42000.12500000"


def test_exact_join_fails_closed_on_unmatched_rate() -> None:
    local = [{"timestamp_ms": 1_700_000_000_000, "funding_rate": "0.0001"}]
    exchange = [
        {
            "symbol": "BTCUSDT",
            "fundingTime": 1_700_000_000_000,
            "fundingRate": "0.00010001",
            "markPrice": "42000.12500000",
        }
    ]

    with pytest.raises(ValueError, match="rate mismatch"):
        MODULE._join_exchange_rows(local, exchange)


def test_exact_join_fails_closed_on_duplicate_exchange_event() -> None:
    local = [{"timestamp_ms": 1_700_000_000_000, "funding_rate": "0.0001"}]
    event = {
        "symbol": "BTCUSDT",
        "fundingTime": 1_700_000_000_000,
        "fundingRate": "0.0001",
        "markPrice": "42000.12500000",
    }
    with pytest.raises(ValueError, match="duplicate Binance"):
        MODULE._join_exchange_rows(local, [event, event])
