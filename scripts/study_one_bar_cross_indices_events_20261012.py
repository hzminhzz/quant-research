"""Vectorized causal event diagnostics. Not a trading simulator or native fill proxy."""
from __future__ import annotations
import json
from datetime import timedelta
from pathlib import Path
import polars as pl
from run_one_bar_cross_indices_native_20261012 import (
    OUT, NAMES, build_feed
)

YEARS = (2018, 2022, 2024, 2025, 2026)


def event_labels(feed: pl.DataFrame) -> pl.DataFrame:
    """Compare prior completed 50-bar levels with FUTURE complete 30m outcomes.

    The future frame exists for research labels only, never joined into engine
    strategy inputs. If the next 30m window is incomplete, omit from labels.
    """
    decision = (
        feed.filter(
            (pl.col("timestamp").dt.minute().is_in([29, 59]))
            & pl.col("next_long_stop").is_not_null()
        ).select("timestamp", "next_long_stop", "next_short_stop")
        .with_columns(
            (pl.col("timestamp") + pl.duration(minutes=1)).alias("next_window_start")))
    future = (
        feed.with_columns(
            pl.col("timestamp").dt.truncate("30m").alias("next_window_start"))
        .group_by("next_window_start")
        .agg(
            pl.len().alias("minutes"),
            pl.col("timestamp").n_unique().alias("unique_minutes"),
            pl.col("timestamp").min().alias("actual_start"),
            pl.col("timestamp").max().alias("actual_end"),
            pl.col("open").first().alias("future_open"),
            pl.col("high").max().alias("future_high"),
            pl.col("low").min().alias("future_low"),
            pl.col("close").last().alias("future_close"))
        .filter(
            (pl.col("minutes") == 30)
            & (pl.col("unique_minutes") == 30)
            & (pl.col("actual_start") == pl.col("next_window_start"))
            & (pl.col("actual_end") == pl.col("next_window_start") + pl.duration(minutes=29))))
    return (
        decision.join(future, on="next_window_start", how="left")
        .with_columns(
            (pl.col("future_high") >= pl.col("next_long_stop")).alias("long_cross"),
            (pl.col("future_low") <= pl.col("next_short_stop")).alias("short_cross"))
        .with_columns(
            (pl.col("long_cross").fill_null(False)
             & pl.col("short_cross").fill_null(False)).alias("both_cross"))
    )


def main() -> None:
    rows = []
    for sym in NAMES:
        for year in YEARS:
            print("EVENT_STUDY", sym, year, flush=True)
            feed, quality = build_feed(sym, year)
            labels = event_labels(feed)
            total = labels.height
            with_next = labels.filter(pl.col("future_open").is_not_null())
            yes = labels.select(
                pl.col("long_cross").fill_null(False).sum().alias("long_count"),
                pl.col("short_cross").fill_null(False).sum().alias("short_count"),
                pl.col("both_cross").sum().alias("both_count"),
            ).to_dicts()[0]
            rows.append({
                "instrument": sym, "year": year,
                "eligible_decisions": total, "fully_observed_next_30m_bars": with_next.height,
                "incomplete_or_missing_next_bars": total - with_next.height,
                **yes,
                "coverage_fraction": with_next.height / total if total else None,
                "method": "Polars future 30m labels from 1m OHLC; NOT a fill model",
            })
    path = OUT / "phase34"
    path.mkdir(parents=True, exist_ok=True)
    (path / "phase3_event_diagnostics.json").write_text(
        json.dumps({"status": "COMPLETE_DIAGNOSTIC_ONLY",
                    "sample_years": list(YEARS), "rows": rows,
                    "causality": "The prior 50-bar level uses only fully completed bars and native-next-minute order timing. Future 30m OHLC is research LABEL ONLY; absent windows are not filled.",
                    "note": "Event touch rates are NOT strategy win rates or PnL."},
                   indent=2) + "\n")
    pl.DataFrame(rows).write_csv(path / "phase3_event_diagnostics.csv")
    print("EVENT_DIAGNOSTICS_COMPLETE", flush=True)


if __name__ == "__main__":
    main()
