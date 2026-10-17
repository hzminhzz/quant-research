"""Regression tests for the single fixed taker-flow exhaustion MVP."""
from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from scripts import run_taker_flow_exhaustion_mvp_20261011_v1 as m


def test_prior_only_threshold_and_direction():
    start = datetime(2025, 11, 1, tzinfo=UTC)
    base = [
        {
            "timestamp": start + timedelta(hours=i),
            "symbol": "BTCUSDT",
            "open": 100.0,
            "close": 100.5,
            "quote_volume": 100.0,
            "taker_buy_quote_volume": 55.0,
        }
        for i in range(720)
    ]
    # The extreme event must not affect its own prior threshold.
    base.append({
        "timestamp": start + timedelta(hours=720), "symbol": "BTCUSDT",
        "open": 100.0, "close": 105.0, "quote_volume": 200.0,
        "taker_buy_quote_volume": 195.0,
    })
    f = m.compute_flow_panel(pl.DataFrame(base))
    event = f.row(720, named=True)
    assert event["prior_abs_flow_p95"] == pytest.approx(0.1)
    assert event["signal"] == -1
    assert event["flow_imbalance"] == pytest.approx(0.95)
    assert f["prior_abs_flow_p95"][719] is None


def test_grouping_no_cross_asset_bleed():
    start = datetime(2025, 11, 1, tzinfo=UTC)
    rows = [
        {"timestamp": start + timedelta(hours=i), "symbol": symbol,
         "open": 100.0, "close": 101.0, "quote_volume": 100.0,
         "taker_buy_quote_volume": buy}
        for symbol, buy in (("BTCUSDT", 55.0), ("ETHUSDT", 70.0))
        for i in range(721)
    ]
    f = m.compute_flow_panel(pl.DataFrame(rows)).filter(
        pl.col("timestamp") == start + timedelta(hours=720))
    x = {r["symbol"]: r for r in f.iter_rows(named=True)}
    assert x["BTCUSDT"]["prior_abs_flow_p95"] == pytest.approx(0.1)
    assert x["ETHUSDT"]["prior_abs_flow_p95"] == pytest.approx(0.4)


def test_schedule_and_observed_funding_boundaries():
    start = datetime(2026, 1, 1, 4, tzinfo=UTC)
    assert not m.overlaps_scheduled_funding(start, start + timedelta(hours=4))
    assert m.overlaps_scheduled_funding(start + timedelta(hours=1),
                                         start + timedelta(hours=5))
    assert m.overlaps_scheduled_funding(datetime(2026, 1, 1, 8, tzinfo=UTC),
                                         datetime(2026, 1, 1, 12, tzinfo=UTC))
    event = datetime(2026, 1, 1, 8, 0, 0, 2000, tzinfo=UTC)
    assert m.crosses_observed_settlement(datetime(2026, 1, 1, 8, tzinfo=UTC),
                                          datetime(2026, 1, 1, 12, tzinfo=UTC), [event])
    assert not m.crosses_observed_settlement(start.replace(tzinfo=None),
                                              (start + timedelta(hours=4)).replace(tzinfo=None),
                                              [event])


def test_existing_trial_never_overwritten(tmp_path, monkeypatch):
    dst = tmp_path / "out"
    dst.mkdir()
    (dst / "trial_result.json").write_text("original")
    monkeypatch.setattr(m, "OUT", dst)
    with pytest.raises(FileExistsError):
        m.run()
    assert (dst / "trial_result.json").read_text() == "original"
