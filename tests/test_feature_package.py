"""Synthetic parity, semantics, and causal-prefix checks for feature package."""

from datetime import datetime, timedelta, timezone
import inspect

import numpy as np
import polars as pl
import pytest

from ml4t.engineer.features.fdiff import ffdiff
from ml4t.engineer.features.microstructure import bid_ask_imbalance, effective_tick_rule
import src.features as features


def ordered(frame: pl.DataFrame, *, start: datetime | None = None) -> pl.DataFrame:
    start = start or datetime(2020, 1, 1, tzinfo=timezone.utc)
    return frame.with_columns(
        pl.Series("timestamp", [start + timedelta(minutes=i) for i in range(len(frame))]),
        pl.lit("X").alias("instrument"),
    )


def test_legacy_public_api_and_numerical_reference():
    names = (
        "add_feature_availability", "join_features_at_decision", "compute_ema",
        "compute_rsi", "compute_atr", "compute_realized_volatility",
        "compute_bollinger_bands", "compute_momentum_panel",
        "compute_garman_klass_volatility", "compute_nr7",
        "extract_breakout_feature_vector",
    )
    for name in names:
        assert callable(getattr(features, name))
        assert inspect.signature(getattr(features, name)) == inspect.signature(
            getattr(features.legacy, name)
        )
    frame = pl.DataFrame({
        "open": [10., 11., 12., 13.], "high": [11., 12., 13., 14.],
        "low": [9., 10., 11., 12.], "close": [10., 11., 12., 13.],
    })
    result = features.compute_momentum_panel(features.compute_ema(frame, span=2), [1])
    np.testing.assert_allclose(result["ema_2"].to_numpy(),
                               [10., 10 + 2 / 3, 11 + 5 / 9, 12 + 14 / 27])
    np.testing.assert_allclose(result["mom_1"][1:].to_numpy(), [0.1, 1 / 11, 1 / 12])
    assert result["mom_1"][0] is None


def test_book_imbalance_requires_real_book_sizes():
    frame = ordered(pl.DataFrame({"bid_size": [3., 1.], "ask_size": [1., 3.], "volume": [5, 10]}))
    with pytest.raises(ValueError, match="not LOB OFI"):
        features.add_book_imbalance(frame, source_kind="cfd_tick_volume")
    with pytest.raises(ValueError, match="not LOB OFI"):
        features.add_book_imbalance(frame, source_kind="cfd_quotes")
    result = features.add_book_imbalance(frame, source_kind="exchange_lob_snapshot")
    assert result["book_size_imbalance"].to_list() == [0.5, -0.5]
    assert result["book_size_imbalance"].to_list() == frame.with_columns(
        bid_ask_imbalance("bid_size", "ask_size").alias("native")
    )["native"].to_list()
    with pytest.raises(ValueError, match="finite nonnegative"):
        features.add_book_imbalance(frame.with_columns(pl.lit(-1).alias("bid_size")),
                                    source_kind="exchange_lob_snapshot")
    for bad_bid, bad_ask in ((float("nan"), 1.), (float("inf"), 1.), (0., 0.),
                             (1e308, 1e308)):
        with pytest.raises(ValueError, match="positive total"):
            features.add_book_imbalance(ordered(pl.DataFrame({"bid_size": [bad_bid],
                                                                "ask_size": [bad_ask]})),
                                        source_kind="exchange_lob_snapshot")


def test_tick_rule_is_labeled_proxy_not_vpin_or_ofi():
    frame = ordered(pl.DataFrame({"close": [100., 101., 99., 102.], "volume": [100, 200, 300, 400]}))
    result = features.add_trade_sign_proxy(frame, source_kind="cfd_quotes")
    assert result["price_change_sign_proxy"].to_list() == frame.with_columns(
        effective_tick_rule("close").alias("native")
    )["native"].to_list()
    assert not {"vpin", "ofi", "trade_volume"} & set(result.columns)
    with pytest.raises(ValueError):
        features.add_trade_sign_proxy(frame, source_kind="cfd_tick_volume")


def test_ffdiff_native_parity_and_prefix_invariance():
    frame = ordered(pl.DataFrame({"close": np.arange(1., 161.) + np.sin(np.arange(160))}))
    result = features.add_fractional_difference(frame, d=0.6, threshold=0.01)
    expected = ffdiff(frame["close"], d=0.6, threshold=0.01)
    np.testing.assert_allclose(result["close_ffdiff"].to_numpy(), expected.to_numpy(), equal_nan=True)
    changed = frame.with_columns(pl.when(pl.int_range(pl.len()) >= 120)
                                 .then(pl.col("close") * 10).otherwise(pl.col("close")).alias("close"))
    other = features.add_fractional_difference(changed, d=0.6, threshold=0.01)
    np.testing.assert_allclose(result["close_ffdiff"][:120].to_numpy(),
                               other["close_ffdiff"][:120].to_numpy(), equal_nan=True)
    for d in (-0.1, float("nan"), 1.1):
        with pytest.raises(ValueError):
            features.add_fractional_difference(frame, d=d)


def test_training_only_d_selection(monkeypatch):
    seen = []

    def fake_find(series, *, d_range, step):
        seen.append(series.to_list())
        return {"optimal_d": 0.4, "adf_pvalue": 0.01, "correlation": 0.8}

    monkeypatch.setattr("src.features.stationarity.find_optimal_d", fake_find)
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    full = ordered(pl.DataFrame({"close": np.arange(1., 101.)}), start=start)
    full = full.with_columns((pl.col("timestamp") + timedelta(minutes=2)).alias("available_at"))
    training = full.head(70)
    assert features.fit_fractional_difference_d(full, training_end=start + timedelta(minutes=70))["optimal_d"] == 0.4
    assert features.fit_fractional_difference_d(training)["optimal_d"] == 0.4
    assert seen == [full.head(68)["close"].to_list(), training["close"].to_list()]
    with pytest.raises(ValueError, match="at least 50"):
        features.fit_fractional_difference_d(full, training_end=start + timedelta(minutes=40))


def test_order_contract_blocks_mixed_unsorted_and_naive():
    base = ordered(pl.DataFrame({"close": [100., 101., 102.]}))
    invalid = (
        base.with_columns(pl.when(pl.int_range(pl.len()) == 2).then(pl.lit("Y"))
                          .otherwise(pl.col("instrument")).alias("instrument")),
        base.reverse(),
        base.with_columns(pl.col("timestamp").dt.replace_time_zone(None)),
        base.with_columns(pl.col("timestamp").shift(1).fill_null(pl.col("timestamp").first())),
    )
    for frame in invalid:
        with pytest.raises(ValueError):
            features.add_trade_sign_proxy(frame, source_kind="cfd_quotes")
        with pytest.raises(ValueError):
            features.add_fractional_difference(frame, d=0.5)


def test_semivariance_and_jump_proxy_no_future_dependence():
    frame = ordered(pl.DataFrame({"close": [100., 110., 99., 99., 108.9, 98.01, 98.01]}))
    result = features.add_signed_semivariance_jump_proxy(frame, window=2)
    up = np.log(110 / 100) ** 2
    down = np.log(99 / 110) ** 2
    assert result["realized_up_semivariance"][2] == pytest.approx(up)
    assert result["realized_down_semivariance"][2] == pytest.approx(down)
    assert result["rv_bpv_jump_proxy"][2] == pytest.approx(max(0., up + down - np.pi / 2 * np.sqrt(up * down)))
    changed = frame.with_columns(pl.when(pl.int_range(pl.len()) >= 5)
                                 .then(pl.col("close") * 10).otherwise(pl.col("close")).alias("close"))
    other = features.add_signed_semivariance_jump_proxy(changed, window=2)
    for column in ("realized_up_semivariance", "realized_down_semivariance", "rv_bpv_jump_proxy"):
        np.testing.assert_allclose(result[column][:5].to_numpy(), other[column][:5].to_numpy(), equal_nan=True)


def test_cross_session_asof_uses_availability_and_instrument():
    t = datetime(2020, 1, 1, tzinfo=timezone.utc)
    source = pl.DataFrame({"instrument": ["X", "X", "Y"],
                           "event_time": [t, t + timedelta(hours=1), t],
                           "available_at": [t + timedelta(minutes=30), t + timedelta(hours=3),
                                            t + timedelta(minutes=30)],
                           "spill": [1., 2., 99.]})
    decisions = pl.DataFrame({"instrument": ["X", "X", "X", "Y"],
                              "decision_time": [t + timedelta(minutes=10), t + timedelta(hours=2),
                                                t + timedelta(hours=3), t + timedelta(hours=2)]})
    result = features.join_cross_session_asof(decisions, source, source_session="Asia",
                                              decision_session="Europe", feature_cols=("spill",))
    assert result.select("instrument", "spill").rows() == [
        ("X", None), ("X", 1.), ("Y", 99.), ("X", 2.)
    ]
    with pytest.raises(ValueError, match="availability"):
        features.join_cross_session_asof(decisions, source.with_columns(
            (pl.col("event_time") - timedelta(minutes=1)).alias("available_at")),
            source_session="Asia", decision_session="Europe", feature_cols=("spill",))
    with pytest.raises(ValueError, match="distinct"):
        features.join_cross_session_asof(decisions, source, source_session="Asia",
                                          decision_session="Asia", feature_cols=("spill",))


@pytest.mark.parametrize("name", ["auction", "VPIN", "volume-profile", "OFI"])
def test_unsupported_market_structure_claims_rejected(name):
    with pytest.raises(NotImplementedError):
        features.require_market_structure_capability(name)
    with pytest.raises(ValueError, match="proxy cannot"):
        features.add_trade_sign_proxy(ordered(pl.DataFrame({"close": [100., 101.]})),
                                      source_kind="cfd_quotes", alias=name)
