from datetime import datetime, timedelta, timezone

import polars as pl

from src.features import add_feature_availability, join_features_at_decision
from src.market_time import BarTimestampSpec

UTC = timezone.utc


def test_open_stamped_feature_is_unavailable_until_bar_close():
    source = pl.DataFrame(
        {
            "timestamp": [datetime(2026, 1, 1, 9, 0, tzinfo=UTC), datetime(2026, 1, 1, 9, 5, tzinfo=UTC)],
            "feature": [1.0, 2.0],
        }
    )
    result = add_feature_availability(source, BarTimestampSpec("open", timedelta(minutes=5)))
    assert result["available_at"].to_list()[0] == datetime(2026, 1, 1, 9, 5, tzinfo=UTC)


def test_asof_join_does_not_use_current_unavailable_bar():
    features = pl.DataFrame(
        {
            "available_at": [datetime(2026, 1, 1, 9, 5, tzinfo=UTC), datetime(2026, 1, 1, 9, 10, tzinfo=UTC)],
            "feature": [1.0, 2.0],
        }
    )
    decisions = pl.DataFrame(
        {
            "decision_time": [datetime(2026, 1, 1, 9, 7, tzinfo=UTC), datetime(2026, 1, 1, 9, 10, tzinfo=UTC)],
        }
    )
    joined = join_features_at_decision(decisions, features)
    assert joined["feature"].to_list() == [1.0, 2.0]


def test_future_rows_do_not_change_prior_join():
    base = pl.DataFrame(
        {"available_at": [datetime(2026, 1, 1, 9, 5, tzinfo=UTC)], "feature": [1.0]}
    )
    extended = base.vstack(
        pl.DataFrame(
            {"available_at": [datetime(2026, 1, 1, 9, 10, tzinfo=UTC)], "feature": [99.0]}
        )
    )
    decisions = pl.DataFrame(
        {"decision_time": [datetime(2026, 1, 1, 9, 7, tzinfo=UTC)]}
    )
    assert join_features_at_decision(decisions, base)["feature"].to_list() == [1.0]
    assert join_features_at_decision(decisions, extended)["feature"].to_list() == [1.0]
