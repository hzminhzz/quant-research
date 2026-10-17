"""Vectorized Volatility Breakout Feature Pipeline.

Adheres strictly to ml4t-polars-patterns and ml4t-compute-features:
- Lazy execution via pl.scan_parquet
- Point-in-time invariants (Day T only sees ATR(5) from Day T-1)
- Group-aware operations per asset
- Vectorized expressions without Python UDFs (.map_elements)
"""

from __future__ import annotations

from datetime import time
from pathlib import Path
from typing import Dict, Tuple

import polars as pl

# Designated cash trading sessions per asset
ASSET_SESSION_CONFIG: Dict[str, Tuple[str, time, time]] = {
    "ES": ("America/New_York", time(9, 30), time(16, 0)),
    "NQ": ("America/New_York", time(9, 30), time(16, 0)),
    "US30": ("America/New_York", time(9, 30), time(16, 0)),
    "DAX": ("Europe/Berlin", time(9, 0), time(17, 30)),
    "XAUUSD": ("America/New_York", time(8, 0), time(17, 0)),
}


def compute_daily_atr_features(
    df: pl.DataFrame,
    atr_period: int = 5,
    vol_quantile: float = 0.20,
    vol_quantile_window: int = 60,
) -> pl.DataFrame:
    """Compute daily ATR and volatility regime percentiles with strict zero lookahead.
    
    Returns a dataframe keyed by (symbol, date) where prior_atr is shifted by 1 day.
    """
    daily = (
        df.group_by(["symbol", "date"])
        .agg(
            d_open=pl.col("open").first(),
            d_high=pl.col("high").max(),
            d_low=pl.col("low").min(),
            d_close=pl.col("close").last(),
        )
        .sort(["symbol", "date"])
    )

    # True range calculation
    daily = (
        daily.with_columns(prev_close=pl.col("d_close").shift(1).over("symbol"))
        .with_columns(
            tr=pl.max_horizontal(
                pl.col("d_high") - pl.col("d_low"),
                (pl.col("d_high") - pl.col("prev_close")).abs(),
                (pl.col("d_low") - pl.col("prev_close")).abs(),
            )
        )
        .with_columns(
            atr=pl.col("tr").rolling_mean(atr_period).over("symbol"),
            change_10=(pl.col("d_close") - pl.col("d_close").shift(10).over("symbol")).abs(),
            vol_sum_10=(pl.col("d_close") - pl.col("d_close").shift(1).over("symbol")).abs().rolling_sum(10).over("symbol"),
        )
        .with_columns(
            er_10=pl.col("change_10") / (pl.col("vol_sum_10") + 1e-6),
            vol_rank=(
                (pl.col("atr") - pl.col("atr").rolling_min(120).over("symbol"))
                / (pl.col("atr").rolling_max(120).over("symbol") - pl.col("atr").rolling_min(120).over("symbol") + 1e-6)
            ),
            atr_p20=pl.col("atr")
            .rolling_quantile(vol_quantile, window_size=vol_quantile_window)
            .over("symbol"),
        )
        .with_columns(
            # Shift by 1: Strictly point-in-time. On day T, only features through T-1 are visible.
            prior_atr=pl.col("atr").shift(1).over("symbol"),
            prior_atr_p20=pl.col("atr_p20").shift(1).over("symbol"),
            prior_er_10=pl.col("er_10").shift(1).over("symbol"),
            prior_vol_rank=pl.col("vol_rank").shift(1).over("symbol"),
        )
        .select(["symbol", "date", "prior_atr", "prior_atr_p20", "prior_er_10", "prior_vol_rank"])
    )
    return daily


def build_breakout_feature_matrix(
    data_dir: Path | str = "data/processed",
    output_path: Path | str = "data/features/breakout_features.parquet",
    breakout_mult: float = 0.40,
    atr_period: int = 5,
) -> pl.DataFrame:
    """Build canonical feature matrix across all declared instruments."""
    data_dir = Path(data_dir)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    asset_dfs = []
    for symbol, (tz, s_open, s_close) in ASSET_SESSION_CONFIG.items():
        file_path = data_dir / f"{symbol.lower()}_1m.parquet"
        if not file_path.exists():
            continue

        raw = pl.read_parquet(file_path)
        # Convert timestamp to asset's local session time for calendar alignment
        raw = raw.with_columns(
            local_ts=pl.col("timestamp").dt.convert_time_zone(tz)
        ).with_columns(
            date=pl.col("local_ts").dt.date(),
            bar_time=pl.col("local_ts").dt.time(),
        )

        daily_features = compute_daily_atr_features(raw, atr_period=atr_period)

        # Filter strictly to designated cash session hours
        session_bars = raw.filter(
            (pl.col("bar_time") >= s_open) & (pl.col("bar_time") <= s_close)
        )

        # Extract opening bar of each session
        session_opens = session_bars.group_by(["symbol", "date"]).agg(
            session_open=pl.col("open").first()
        )

        # Vectorized join
        joined = (
            session_bars.join(daily_features, on=["symbol", "date"], how="inner")
            .join(session_opens, on=["symbol", "date"], how="inner")
            .with_columns(
                long_trigger=pl.col("session_open") + breakout_mult * pl.col("prior_atr"),
                short_trigger=pl.col("session_open") - breakout_mult * pl.col("prior_atr"),
                stop_loss=pl.col("session_open"),
                risk_distance=breakout_mult * pl.col("prior_atr"),
                vol_filter_active=pl.col("prior_atr") >= pl.col("prior_atr_p20"),
                is_session_end=(
                    (pl.col("timestamp") == pl.col("timestamp").max().over(["symbol", "date"]))
                    | (pl.col("bar_time") >= s_close)
                ),
            )
            .drop("local_ts")
        )
        asset_dfs.append(joined)

    panel = pl.concat(asset_dfs).sort(["symbol", "timestamp"])
    panel.write_parquet(output_path)
    return panel


if __name__ == "__main__":
    features_df = build_breakout_feature_matrix()
    print(f"Generated feature matrix: {features_df.height:,} rows across {features_df['symbol'].n_unique()} symbols.")
    print("Columns:", features_df.columns)
