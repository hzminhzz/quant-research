from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import polars as pl
import pytest

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE / "scripts"))
import analyze_regime_2026 as audit  # noqa: E402


def test_native_exit_order_type_uses_alternating_fill_index_and_reconciles_trades() -> None:
    times = [datetime(2026, 1, 2, hour, tzinfo=timezone.utc) for hour in range(4)]
    fills = pl.DataFrame({
        "timestamp": times,
        "side": ["buy", "sell", "sell", "buy"],
        "order_type": ["stop", "stop", "stop", "market"],
    })
    native = pl.DataFrame({
        "entry_time": [times[0], times[2]], "exit_time": [times[1], times[3]],
        "direction": ["long", "short"],
    }).with_row_index("native_trade_index")

    paired = audit.pair_native_exit_fills(fills, native)

    assert paired["exit_fill_order_type"].to_list() == ["stop", "market"]
    assert paired.select("entry_time", "exit_time", "direction").equals(
        native.select("entry_time", "exit_time", "direction"))


def test_fill_pairing_fails_if_native_exit_timestamp_does_not_match() -> None:
    times = [datetime(2026, 1, 2, hour, tzinfo=timezone.utc) for hour in range(3)]
    fills = pl.DataFrame({"timestamp": [times[0], times[1]], "side": ["buy", "sell"], "order_type": ["stop"] * 2})
    native = pl.DataFrame({"entry_time": [times[0]], "exit_time": [times[2]], "direction": ["long"]}).with_row_index("native_trade_index")

    with pytest.raises(ValueError, match="timestamps differ"):
        audit.pair_native_exit_fills(fills, native)


def test_complete_bar_release_and_asof_join_exclude_unreleased_future_bar() -> None:
    start = datetime(2026, 1, 2, tzinfo=timezone.utc)
    rows = []
    for bar_no in range(25):
        for minute in range(30):
            price = 100 + bar_no * 0.8 + minute * 0.02
            rows.append({"timestamp": start + timedelta(minutes=bar_no * 30 + minute),
                         "session_date": date(2026, 1, 2), "bar_no": bar_no,
                         "open": price, "high": price + 1, "low": price - 1,
                         "close": price + 0.01, "volume": 1.0})
    source = pl.DataFrame(rows)
    entry_29 = start + timedelta(minutes=21 * 30 + 29)
    entry_before_future_minute = start + timedelta(minutes=22 * 30 + 1)
    entries = pl.DataFrame({"entry_time": [entry_29, entry_before_future_minute]})
    baseline_bars = audit.build_complete_bar_features(source)
    baseline = audit.join_available_features(entries, baseline_bars,
                                             ["atr20", "efficiency_20"])

    future_minute = start + timedelta(minutes=22 * 30 + 2)
    changed_source = source.with_columns(
        pl.when(pl.col("timestamp") == future_minute).then(pl.col("high") + 100).otherwise(pl.col("high")).alias("high"),
        pl.when(pl.col("timestamp") == future_minute).then(pl.col("low") - 50).otherwise(pl.col("low")).alias("low"),
        pl.when(pl.col("timestamp") == future_minute).then(pl.col("close") + 80).otherwise(pl.col("close")).alias("close"))
    mutated_bars = audit.build_complete_bar_features(changed_source)
    future_bar_start = start + timedelta(minutes=22 * 30)
    before_future_features = baseline_bars.filter(pl.col("bar_start") == future_bar_start).select("atr20", "efficiency_20")
    after_future_features = mutated_bars.filter(pl.col("bar_start") == future_bar_start).select("atr20", "efficiency_20")
    assert not before_future_features.equals(after_future_features)
    mutated = audit.join_available_features(entries, mutated_bars,
                                            ["atr20", "efficiency_20"])

    assert baseline["feature_available_at"].to_list()[0] == start + timedelta(minutes=21 * 30)
    assert baseline["feature_available_at"].to_list()[0] < start + timedelta(minutes=22 * 30)
    assert baseline.select("atr20", "efficiency_20").equals(mutated.select("atr20", "efficiency_20"))
    assert baseline["feature_available_at"].to_list()[1] <= entry_before_future_minute


def test_chicago_regular_session_boundaries() -> None:
    local = pl.Series("entry_local", [
        datetime(2026, 1, 5, 8, 29), datetime(2026, 1, 5, 8, 30),
        datetime(2026, 1, 5, 14, 59), datetime(2026, 1, 5, 15, 0),
    ]).dt.replace_time_zone("America/Chicago")
    result = pl.DataFrame({"entry_local": local}).select(audit.chicago_rth_expression().alias("session"))

    assert result["session"].to_list() == ["overnight", "RTH", "RTH", "overnight"]


def test_corrected_2026_exit_and_session_totals() -> None:
    metrics = __import__("json").loads((PACKAGE / "reports/regime_2026/metrics.json").read_text())
    exits = {row["exit_class"]: row for row in metrics["accounting"]["stop_vs_market_breakdown"]}
    sessions = {row["session"]: row for row in metrics["accounting"]["session_breakdown"]}

    assert (exits["STOP"]["trades"], round(exits["STOP"]["net_pnl_usd"], 2)) == (44, -48058.76)
    assert (exits["MARKET"]["trades"], round(exits["MARKET"]["net_pnl_usd"], 2)) == (194, 33891.80)
    assert sessions["RTH"]["trades"] > 0
    assert sum(row["trades"] for row in sessions.values()) == 238
    assert round(sum(row["net_pnl_usd"] for row in sessions.values()), 2) == -14166.96
    stop = metrics["features"]["fixed_50_point_stop_analysis"]
    assert stop["reference_2018_full_year_median_entry_price"] == 6966.5
    assert round(stop["reference_2018_full_year_stop_bps_of_median_price"], 1) == 71.8
    assert round(stop["current_stop_bps_of_median_price"], 1) == 19.4


def test_regenerated_trade_features_are_available_by_entry() -> None:
    trades = audit.read_csv(PACKAGE / "reports/regime_2026/trade_event_attribution.csv")

    assert trades.filter(pl.col("feature_available_at") > pl.col("entry_time")).is_empty()
