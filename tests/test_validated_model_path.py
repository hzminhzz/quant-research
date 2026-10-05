from datetime import datetime, timedelta, timezone

import numpy as np

from src.labeling import ORBTradeEvent
from src.models import train_meta_classifier_cpcv


def make_events(n: int = 60) -> list[ORBTradeEvent]:
    events = []
    for i in range(n):
        decision = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=5 * i)
        entry = decision + timedelta(minutes=5)
        exit_time = entry + timedelta(minutes=10)
        label = i % 2
        events.append(
            ORBTradeEvent(
                entry_time=entry.isoformat(),
                exit_time=exit_time.isoformat(),
                decision_time=decision.isoformat(),
                session_name="cash",
                date=decision.date().isoformat(),
                symbol="TEST" if i % 2 else "ALT",
                direction=1,
                entry_price=100.0,
                exit_price=101.0 if label else 99.0,
                or_high=101.0,
                or_low=99.0,
                or_range=2.0,
                atr20=1.0,
                delta=2.0,
                upper_barrier=104.0,
                lower_barrier=98.0,
                holding_bars=3,
                exit_reason="profit_target" if label else "stop_loss",
                label=label,
                realized_return=0.01 if label else -0.01,
                r_multiple=1.0 if label else -1.0,
                features={
                    "rvol_1h": 1.0 + label,
                    "vwap_alignment": 0.6,
                    "wick_exhaustion": 0.2,
                    "range_to_atr20": 2.0,
                    "garman_klass_norm": 1.0,
                    "spx_alignment": 0.5,
                    "nr7_flag": 0.0,
                    "breakout_bar_range_ratio": 1.0,
                },
            )
        )
    return events


def test_temporal_model_path_uses_interval_validation_and_complete_scores():
    result = train_meta_classifier_cpcv(
        make_events(),
        n_groups=4,
        n_test_groups=1,
        embargo_duration=timedelta(minutes=10),
        conviction_threshold=0.5,
        require_temporal_contract=True,
    )
    assert result.score_semantics == "raw_model_score"
    assert result.oof_coverage is not None
    assert np.all(result.oof_coverage > 0)
    assert np.all(np.isfinite(result.oof_probabilities))
