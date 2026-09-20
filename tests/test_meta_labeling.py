"""Unit and contract tests for the Institutional ML Meta-Labeling Pipeline.

Governed by ML4T Skills:
- ml4t-triple-barrier
- ml4t-meta-labels
- ml4t-cpcv
- ml4t-purging-embargo
"""

import numpy as np
import polars as pl
import pytest

from src.features import (
    compute_garman_klass_volatility,
    compute_nr7,
    extract_breakout_feature_vector,
)
from src.labeling import (
    MetaLabelingORBDatasetBuilder,
    ORBTradeEvent,
    compute_sample_uniqueness_weights,
)
from src.models import MetaModelResult, train_meta_classifier_cpcv


def test_garman_klass_and_nr7_features():
    """Verify that Garman-Klass volatility and NR7 compression are correctly computed."""
    n = 50
    rng = np.random.default_rng(42)
    closes = 100.0 + np.cumsum(rng.normal(0, 1, n))
    highs = closes + rng.uniform(0.5, 2.0, n)
    lows = closes - rng.uniform(0.5, 2.0, n)
    opens = closes + rng.normal(0, 0.5, n)

    df = pl.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
    })

    df = compute_garman_klass_volatility(df, lookback=10, alias="gk_vol")
    assert "gk_vol" in df.columns
    valid_gk = df["gk_vol"].drop_nulls().to_numpy()
    assert len(valid_gk) > 0
    assert np.all(valid_gk >= 0.0)

    df = compute_nr7(df, alias="nr7")
    assert "nr7" in df.columns
    assert df["nr7"].dtype == pl.Boolean


def test_extract_breakout_feature_vector():
    """Verify that the high-information feature vector is correctly extracted without lookahead."""
    rng = np.random.default_rng(42)
    or_df = pl.DataFrame({
        "open": [100.0] * 12,
        "high": [102.0] * 12,
        "low": [99.0] * 12,
        "close": [101.0] * 12,
        "volume": [1000.0] * 12,
    })
    current_bar = pl.DataFrame({
        "open": [101.0],
        "high": [103.0],
        "low": [100.5],
        "close": [102.8],
        "volume": [2500.0],
    })

    features = extract_breakout_feature_vector(
        or_df=or_df,
        current_bar=current_bar,
        or_high=102.0,
        or_low=99.0,
        or_range=3.0,
        atr20=2.0,
        direction=1,
    )

    assert "rvol_1h" in features
    assert "vwap_loc_1h" in features
    assert "vwap_alignment" in features
    assert "wick_exhaustion" in features
    assert "range_to_atr20" in features
    assert "spx_alignment" in features
    assert 0.0 <= features["vwap_loc_1h"] <= 1.0
    assert 0.0 <= features["wick_exhaustion"] <= 1.0


def test_meta_labeling_dataset_builder_synthetic():
    """Verify that MetaLabelingORBDatasetBuilder correctly extracts events and labels."""
    n_days = 10
    bars_per_day = 48  # 4 hours of 5m bars
    all_rows = []

    for d in range(n_days):
        date_str = f"2024-01-{d+1:02d}"
        base_p = 100.0 + d * 5.0
        for b in range(bars_per_day):
            h_val = b // 12
            m_val = (b % 12) * 5
            t_str = f"{date_str} {h_val:02d}:{m_val:02d}:00"
            price = base_p + (b * 0.1)  # Uptrend breakout
            all_rows.append({
                "timestamp": t_str,
                "date": date_str,
                "hour": h_val,
                "open": price - 0.05,
                "high": price + 0.15,
                "low": price - 0.10,
                "close": price,
                "volume": 1000.0 + b * 20.0,
                "atr20_bar": 0.5,
                "ema_200": base_p - 1.0,
            })

    df = pl.DataFrame(all_rows)
    builder = MetaLabelingORBDatasetBuilder(stretch_k=0.05)
    events = builder.extract_events_and_labels(df, symbol="TEST", session_hours=[0])

    assert len(events) > 0
    assert all(isinstance(e, ORBTradeEvent) for e in events)
    assert all(e.label in [0, 1] for e in events)

    # Test sample uniqueness weights
    all_ts = df["timestamp"].to_list()
    weights = compute_sample_uniqueness_weights(events, all_ts)
    assert len(weights) == len(events)
    assert np.all(weights > 0.0)


def test_meta_classifier_training_and_cpcv():
    """Verify that train_meta_classifier_cpcv trains LightGBM with monotonic constraints."""
    rng = np.random.default_rng(42)
    events = []
    for i in range(120):
        # Generate correlated synthetic features
        vol_score = rng.uniform(0.5, 3.0)
        wick = rng.uniform(0.0, 0.8)
        # Probability of win positively correlated with vol, negatively with wick
        prob_win = 1.0 / (1.0 + np.exp(-(vol_score - 2.0 * wick)))
        lbl = int(rng.uniform(0, 1) < prob_win)

        ev = ORBTradeEvent(
            entry_time=f"2024-01-01 {i//6:02d}:{(i%6)*10:02d}",
            exit_time=f"2024-01-01 {(i//6)+1:02d}:{(i%6)*10:02d}",
            date=f"2024-01-{(i//12)+1:02d}",
            symbol="TEST",
            direction=1,
            entry_price=100.0,
            exit_price=102.0 if lbl == 1 else 99.0,
            or_high=101.0,
            or_low=99.0,
            or_range=2.0,
            atr20=1.0,
            delta=2.0,
            upper_barrier=104.0,
            lower_barrier=98.0,
            holding_bars=12,
            exit_reason="profit_target" if lbl == 1 else "stop_loss",
            label=lbl,
            realized_return=0.02 if lbl == 1 else -0.01,
            r_multiple=1.0 if lbl == 1 else -0.5,
            features={
                "rvol_1h": vol_score,
                "vwap_loc_1h": 0.6,
                "vwap_alignment": 0.6,
                "wick_upper_ratio": wick,
                "wick_lower_ratio": 0.2,
                "wick_exhaustion": wick,
                "range_to_atr20": 2.0,
                "garman_klass_norm": 1.5,
                "spx_vwap_dist": 0.5,
                "spx_alignment": 0.5,
                "nr7_flag": 0.0,
                "breakout_bar_range_ratio": 1.2,
            },
        )
        events.append(ev)

    res = train_meta_classifier_cpcv(
        events=events,
        n_groups=4,
        n_test_groups=1,
        embargo_size=2,
        conviction_threshold=0.50,
        random_state=42,
    )

    assert isinstance(res, MetaModelResult)
    assert 0.0 <= res.mean_auc <= 1.0
    assert 0.0 <= res.brier_score <= 1.0
    assert len(res.oof_probabilities) == len(events)
    assert "rvol_1h" in res.feature_importances


def test_multi_day_eow_holding_and_breakeven():
    """Verify that Multi-Day EOW holding correctly activates breakeven and exits at EOW."""
    all_rows = []
    for day_idx in range(5):
        day_date = f"2024-01-{8+day_idx:02d}"
        for h in range(24):
            for m in range(0, 60, 5):
                t_str = f"{day_date} {h:02d}:{m:02d}:00"
                if day_idx == 0 and h == 0:
                    price = 101.0
                    high = 102.0
                    low = 100.0
                elif day_idx == 0 and h == 1:
                    price = 103.0
                    high = 103.2
                    low = 102.8
                elif day_idx == 1 and h == 10:
                    price = 105.5
                    high = 105.8
                    low = 105.2
                elif day_idx == 4 and h >= 20:
                    price = 106.0
                    high = 106.2
                    low = 105.8
                else:
                    price = 104.0
                    high = 104.2
                    low = 103.8
                all_rows.append({
                    "timestamp": t_str,
                    "date": day_date,
                    "hour": h,
                    "open": price - 0.1,
                    "high": high,
                    "low": low,
                    "close": price,
                    "volume": 1000.0,
                    "atr20_bar": 0.5,
                    "ema_200": 95.0,
                })

    df = pl.DataFrame(all_rows)

    # 1. Test Multi-Day EOW with pure time exit at Friday close
    builder_eow = MetaLabelingORBDatasetBuilder(
        target_multiple=5.0,
        holding_mode="multi_day_eow",
        enable_breakeven=True,
        enable_trailing_stop=False,
        stretch_k=0.05,
    )
    events_eow = builder_eow.extract_events_and_labels(df, symbol="TEST_EOW", session_hours=[0])

    assert len(events_eow) == 1
    ev = events_eow[0]
    assert ev.exit_reason == "time_expiry"
    assert "2024-01-12 20:00:00" in ev.exit_time
    assert ev.r_multiple > 1.0
    assert ev.label == 1

    # 2. Test Multi-Day with Trailing Stop locking profits
    builder_trail = MetaLabelingORBDatasetBuilder(
        target_multiple=5.0,
        holding_mode="multi_day_eow",
        enable_breakeven=True,
        enable_trailing_stop=True,
        trailing_distance_r=1.0,
        stretch_k=0.05,
    )
    events_trail = builder_trail.extract_events_and_labels(df, symbol="TEST_TRAIL", session_hours=[0])
    assert len(events_trail) == 1
    assert events_trail[0].r_multiple > 0.0
    assert events_trail[0].label == 1


