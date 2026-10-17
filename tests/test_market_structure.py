import polars as pl

from scripts.run_near_market_structure import simulate
from src.market_structure import Pivot, build_signals, detect_pivots


def frame(high, low, close):
    high = [float(x) for x in high]
    low = [float(x) for x in low]
    close = [float(x) for x in close]
    return pl.DataFrame({"timestamp": pl.datetime_range(pl.datetime(2024, 1, 1), pl.datetime(2024, 1, 1) + pl.duration(hours=len(close)-1), interval="1h", eager=True, time_zone="UTC"),
                         "open": close, "high": high, "low": low, "close": close, "volume": [1.0] * len(close)})


def test_pivot_is_available_only_after_atr_reversal_confirmation():
    bars = frame([10, 11, 12, 13, 14], [9, 9.5, 10, 11, 12], [9.5, 10, 11, 12, 13])
    _, pivots = detect_pivots(bars)
    assert pivots
    assert pivots[0].kind == "L"
    assert pivots[0].extremum_index == 0
    assert pivots[0].confirmation_index > pivots[0].extremum_index


def test_swing_classification_compares_previous_confirmed_same_type():
    # Oscillations produce LL/LH followed by a confirmed HL/HH reversal.
    closes = [10, 11, 12, 11, 10, 9, 10, 11, 10, 9, 8, 9, 10, 11, 10, 9, 9.5, 10.5, 12, 13, 12, 11]
    highs = [x + 0.4 for x in closes]
    lows = [x - 0.4 for x in closes]
    _, pivots = detect_pivots(frame(highs, lows, closes))
    lows_only = [p.classification for p in pivots if p.kind == "L"]
    highs_only = [p.classification for p in pivots if p.kind == "H"]
    assert "LL" in lows_only
    assert "HL" in lows_only
    assert "HH" in highs_only
    assert "LH" in highs_only


def test_future_append_does_not_change_prior_confirmed_pivots_or_signals():
    prefix = frame([10, 11, 12, 13, 14, 13, 12, 11], [9, 9.5, 10, 11, 12, 11, 10, 9], [9.5, 10, 11, 12, 13, 12, 11, 10])
    suffix = pl.concat([prefix, frame([11, 12, 13], [10, 11, 12], [10.5, 11.5, 12.5]).with_columns(
        (pl.col("timestamp") + pl.duration(hours=prefix.height)).alias("timestamp")
    )])
    _, before = detect_pivots(prefix)
    _, after = detect_pivots(suffix)
    old = [(p.kind, p.extremum_index, p.confirmation_index, p.price, p.classification) for p in before]
    extended = [(p.kind, p.extremum_index, p.confirmation_index, p.price, p.classification) for p in after if p.confirmation_index < prefix.height]
    assert old == extended
    sig_before, _ = build_signals(prefix)
    sig_after, _ = build_signals(suffix)
    assert sig_before["entry_signal"].to_list() == sig_after["entry_signal"].head(prefix.height).to_list()


def test_sequence_signal_is_never_available_before_confirming_second_higher_high():
    bars = frame([10, 11, 12, 13, 14, 13, 12], [9, 9.5, 10, 11, 12, 11, 10], [9.5, 10, 11, 12, 13, 12, 11])
    result, pivots = build_signals(bars)
    signal_indices = [i for i, flag in enumerate(result["entry_signal"].to_list()) if flag]
    hh_confirms = [p["confirmation_index"] for p in pivots if p["classification"] == "HH"]
    assert all(i in hh_confirms for i in signal_indices)


def test_simulation_fills_entry_on_next_bar_open():
    bars = frame([10, 11, 12, 13], [9, 10, 11, 12], [9.5, 10.5, 11.5, 12.5]).with_columns(
        pl.Series("entry_signal", [True, False, False, False]),
        pl.Series("entry_invalidation_level", [8.0, float("nan"), float("nan"), float("nan")]),
        pl.Series("confirmed_swing_low", [float("nan")] * 4),
    )
    _, trades = simulate(bars, 10)
    assert len(trades) == 1
    assert trades[0]["entry_index"] == 1
    assert trades[0]["entry_price"] == bars["open"][1]
    assert trades[0]["exit_reason"] == "end_of_sample_liquidation"
