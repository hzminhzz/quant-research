import math

import polars as pl

from scripts.run_near_market_structure_exit_sweep import (
    add_exit_features,
    select_final,
    select_top5,
    simulate,
)


def _bars(closes, opens=None, highs=None, lows=None, signals=None):
    n = len(closes)
    opens = [float(x) for x in (opens if opens is not None else closes)]
    closes = [float(x) for x in closes]
    highs = [float(x) for x in (highs if highs is not None else [x + 0.2 for x in closes])]
    lows = [float(x) for x in (lows if lows is not None else [x - 0.2 for x in closes])]
    signals = signals if signals is not None else [False] * n
    return pl.DataFrame(
        {
            "timestamp": pl.datetime_range(
                pl.datetime(2024, 1, 1),
                pl.datetime(2024, 1, 1) + pl.duration(hours=n - 1),
                interval="1h",
                eager=True,
                time_zone="UTC",
            ),
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [1.0] * n,
            "entry_signal": signals,
        }
    )


def test_exit_features_are_prefix_invariant_when_future_is_appended():
    prefix = _bars([10, 10.5, 11, 10.8, 11.2, 11.5])
    extended = _bars([10, 10.5, 11, 10.8, 11.2, 11.5, 9, 15, 8])
    before = add_exit_features(prefix)
    after = add_exit_features(extended).head(prefix.height)
    for name in ["atr14_exit", "ema_5", "ema_8", "ema_13", "ema_21", "ema_34"]:
        assert before[name].to_list() == after[name].to_list()


def test_atr_trail_uses_highest_close_since_entry_and_exits_next_open():
    bars = _bars(
        closes=[10.0, 10.0, 12.0, 11.4, 11.0],
        opens=[10.0, 10.5, 12.1, 11.5, 10.8],
        signals=[True, False, False, False, False],
    ).with_columns(
        pl.Series("atr14_exit", [1.0] * 5),
        pl.Series("ema_5", [0.0] * 5),
    )
    daily, trades = simulate(bars, ema_period=5, atr_multiplier=0.5, per_side_bps=0)
    assert len(trades) == 1
    # Entry signal at bar 0 fills bar 1 open.
    assert trades[0]["entry_index"] == 1
    assert trades[0]["entry_price"] == 10.5
    # Highest close reaches 12.0, so ATR trail is 11.5. Close 11.4 breaches it
    # on bar 3; exit therefore fills bar 4 open.
    assert trades[0]["exit_index"] == 4
    assert trades[0]["exit_price"] == 10.8
    assert trades[0]["exit_reason"] == "ema_atr_trail_next_open"
    assert daily.height > 0


def test_ema_current_completed_bar_can_trigger_exit_but_fill_is_future_open():
    bars = _bars(
        closes=[10.0, 10.0, 9.0, 8.0],
        opens=[10.0, 10.2, 9.1, 7.8],
        signals=[True, False, False, False],
    ).with_columns(
        pl.Series("atr14_exit", [100.0] * 4),
        # Current completed bar 2 has EMA 9.5 and close 9.0, so exit is queued there.
        pl.Series("ema_5", [0.0, 0.0, 9.5, 9.0]),
    )
    _, trades = simulate(bars, ema_period=5, atr_multiplier=2.5, per_side_bps=0)
    assert len(trades) == 1
    assert trades[0]["entry_index"] == 1
    assert trades[0]["exit_index"] == 3
    assert trades[0]["exit_price"] == 7.8


def test_frozen_selection_protocol_top5_and_final_choice():
    rows = []
    for i in range(20):
        rows.append(
            {
                "ema_period": [5, 8, 13, 21, 34][i // 4],
                "atr_multiplier": [1.0, 1.5, 2.0, 2.5][i % 4],
                "train_plateau_score": float(i),
                "train_profitable_fraction": 1.0,
                "max_drawdown": -0.1,
            }
        )
    top5 = select_top5(rows)
    assert [x["train_plateau_score"] for x in top5] == [19.0, 18.0, 17.0, 16.0, 15.0]

    validation = []
    for score, val_sharpe, val_ret in [
        (19.0, 0.2, 0.01),
        (18.0, 0.5, 0.02),
        (17.0, 0.4, 0.03),
        (16.0, 0.3, 0.04),
        (15.0, 0.1, 0.05),
    ]:
        validation.append(
            {
                "ema_period": 13,
                "atr_multiplier": 1.0,
                "train_plateau_score": score,
                "validation_sharpe": val_sharpe,
                "validation_net_return": val_ret,
                "validation_max_drawdown": -0.1,
            }
        )
    selected = select_final(validation)
    # max(min(train plateau, validation Sharpe)) => second row (0.5).
    assert math.isclose(selected["validation_sharpe"], 0.5)
