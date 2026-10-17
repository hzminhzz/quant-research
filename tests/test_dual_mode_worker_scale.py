"""Bounded scale regression: real Linux bwrap + Polars on 500 symbols."""
from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from src.engine.isolation import isolated_features


def five_hundred_symbol_panel() -> pl.DataFrame:
    hours = pl.DataFrame({"timestamp": [datetime(2025, 1, 1, tzinfo=UTC) + timedelta(hours=i)
                                         for i in range(720)]})
    symbols = pl.DataFrame({"symbol": [f"S{i:04d}" for i in range(500)]})
    return hours.join(symbols, how="cross").sort("symbol", "timestamp").with_columns(
        ((pl.col("timestamp").dt.epoch("s") // 3600) % 97).cast(pl.Float64).alias("value"))


@pytest.mark.slow
def test_500_symbol_polars_bwrap_wall_time_budget():
    # Nested function is serialized by value: the sandbox cannot import tests/.
    def causal_scale_feature(frame: pl.DataFrame) -> pl.DataFrame:
        import resource

        return frame.with_columns(
            pl.col("value").rolling_mean(window_size=48, min_samples=48).over("symbol").alias("mean48"),
            pl.col("value").rank().over("timestamp").alias("rank_at_hour"),
            pl.lit(resource.getrlimit(resource.RLIMIT_CPU)[0] == resource.RLIM_INFINITY).alias("cpu_wall_only"),
            pl.lit(resource.getrlimit(resource.RLIMIT_AS)[0] >= 64 * 1024**3).alias("virtual_limit_64g"),
        )

    panel = five_hundred_symbol_panel()
    result = isolated_features(panel, causal_scale_feature, timeout=600)
    assert panel.height == result.height == 360_000
    assert result["symbol"].n_unique() == 500
    assert result["mean48"].null_count() == 500 * 47
    assert result["mean48"].is_not_null().sum() > 300_000
    assert result["cpu_wall_only"].all()
    assert result["virtual_limit_64g"].all()
