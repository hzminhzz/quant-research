#!/usr/bin/env python3
from __future__ import annotations

import bisect
import json
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[4]
RUN = ROOT / "run_log/eow_rebuild/eow-ny-overlap-authoritative-20260924-final2"
OUT = RUN / "forensics"
CACHE = OUT / "cache"
SYMBOLS = ("HK33", "JP225")
COST_BPS = 6.0
RISK_UNIT_PCT = 1.0


def parse_dt(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def load_events() -> pl.DataFrame:
    dev = pl.read_parquet(CACHE / "can6_wf_dev.parquet")
    hold = pl.read_parquet(CACHE / "hold.parquet")
    return (
        pl.concat([dev, hold], how="vertical")
        .filter(pl.col("symbol").is_in(SYMBOLS))
        .sort(["strategy_date", "symbol"])
    )


def load_markets() -> dict[str, tuple[list[datetime], np.ndarray]]:
    files = {
        "HK33": ROOT / "data/processed/HK33_5m_2017_2026.parquet",
        "JP225": ROOT / "data/processed/JP225_USD_5m_2017_2026.parquet",
    }
    markets: dict[str, tuple[list[datetime], np.ndarray]] = {}
    for symbol, path in files.items():
        frame = pl.read_parquet(path).select(["timestamp", "close"]).sort("timestamp")
        available_at = (frame["timestamp"] + timedelta(minutes=5)).to_list()
        markets[symbol] = (available_at, frame["close"].to_numpy())
    return markets


def summarize(
    frame: pl.DataFrame,
    markets: dict[str, tuple[list[datetime], np.ndarray]],
    *,
    gated: bool,
) -> dict[str, object]:
    selected = frame.filter(pl.col("score") >= 0.5) if gated else frame
    returns_r = selected["r_multiple"].to_numpy()
    yearly = (
        selected.with_columns(pl.col("strategy_date").str.slice(0, 4).alias("year"))
        .group_by("year")
        .agg(
            pl.len().alias("trades"),
            (pl.col("r_multiple") > 0).sum().alias("wins"),
            pl.col("r_multiple").sum().alias("net_r"),
        )
        .sort("year")
        .with_columns((pl.col("wins") / pl.col("trades") * 100).alias("win_rate_pct"))
    )

    daily_r: dict[object, float] = {}
    cost_fraction = COST_BPS / 10_000.0

    for row in selected.iter_rows(named=True):
        symbol = row["symbol"]
        available_at, closes = markets[symbol]
        entry_time = parse_dt(row["entry_time"])
        exit_time = parse_dt(row["exit_time"])
        entry_price = float(row["entry_price"])
        direction = int(row["direction"])
        delta = float(row["delta"])
        event_r = float(row["r_multiple"])

        risk_fraction = delta / entry_price
        half_cost_r = (cost_fraction / 2.0) / risk_fraction
        gross_r = event_r + 2.0 * half_cost_r
        exit_price = entry_price + direction * delta * gross_r

        current = entry_time.date()
        end_date = exit_time.date()
        previous_mark_r = -half_cost_r
        daily_r[current] = daily_r.get(current, 0.0) + previous_mark_r

        while current <= end_date:
            day_end = datetime.combine(
                current, time(23, 59, 59, 999999), tzinfo=timezone.utc
            )
            if day_end < entry_time:
                current += timedelta(days=1)
                continue
            cap = min(day_end, exit_time)
            right = bisect.bisect_right(available_at, cap)
            left = bisect.bisect_left(available_at, entry_time)
            if right <= left:
                current += timedelta(days=1)
                continue

            mark_idx = right - 1
            mark_price = (
                exit_price
                if available_at[mark_idx] >= exit_time
                else float(closes[mark_idx])
            )
            mark_r = direction * (mark_price - entry_price) / delta - half_cost_r
            if day_end >= exit_time:
                mark_r -= half_cost_r
            increment = mark_r - previous_mark_r
            daily_r[current] = daily_r.get(current, 0.0) + increment
            previous_mark_r = mark_r
            current += timedelta(days=1)

    first = min(daily_r)
    last = max(daily_r)
    daily_returns: list[float] = []
    current = first
    while current <= last:
        if current.weekday() < 5:
            daily_returns.append(
                daily_r.get(current, 0.0) * (RISK_UNIT_PCT / 100.0)
            )
        current += timedelta(days=1)

    values = np.asarray(daily_returns, dtype=float)
    std = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
    sharpe = float(np.mean(values) / std * np.sqrt(252)) if std > 0 else 0.0
    equity = np.cumprod(1.0 + values)
    path = np.concatenate(([1.0], equity))
    drawdown = path / np.maximum.accumulate(path) - 1.0

    return {
        "trades": len(selected),
        "win_rate_pct": float(np.mean(returns_r > 0) * 100.0),
        "net_r": float(np.sum(returns_r)),
        "daily_sharpe": sharpe,
        "max_drawdown": float(np.min(drawdown)),
        "yearly": yearly.to_dicts(),
        "reconciliation_r": float(sum(daily_r.values())),
    }


def main() -> None:
    events = load_events()
    markets = load_markets()
    result: dict[str, object] = {
        "contract": {
            "symbols": list(SYMBOLS),
            "roundtrip_cost_bps": COST_BPS,
            "risk_unit_pct": RISK_UNIT_PCT,
            "score_policy": "existing frozen/shared corrected 6bps scores; no retraining",
            "end": "2026-07-31",
        }
    }

    for start, label in (
        ("2017-01-01", "2017-2026-07-31"),
        ("2024-01-01", "2024-2026-07-31"),
    ):
        period = events.filter(pl.col("strategy_date") >= start)
        period_result: dict[str, object] = {
            "combined": {
                "gated": summarize(period, markets, gated=True),
                "raw": summarize(period, markets, gated=False),
            }
        }
        for symbol in SYMBOLS:
            sleeve = period.filter(pl.col("symbol") == symbol)
            period_result[symbol] = {
                "gated": summarize(sleeve, markets, gated=True),
                "raw": summarize(sleeve, markets, gated=False),
            }
        result[label] = period_result

    output = OUT / "hkjp_performance.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(output)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
