"""Post-validation mechanism forensic: funding persistence and carry decay.

This analysis does not alter or select strategy parameters. It compares the
already-frozen 2022-2023 mature reference with the opened 2024-2025 validation
period using the exact same 48h basket schedule and canonical funding rates.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import polars as pl
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_crypto_xs_plain_funding_mvp_20261015 import build_baskets

OUT = (
    ROOT
    / "run_log"
    / "research_sessions"
    / "crypto_xs_plain_funding_decay_validation_20261015_v1"
    / "decay_forensics"
)

DEV_SIGNAL = (
    ROOT
    / "run_log"
    / "research_sessions"
    / "crypto_xs_plain_funding_mvp_20261015_v1"
    / "mvp"
    / "factor_panel.parquet"
)
DEV_EVENTS = (
    ROOT
    / "data"
    / "processed"
    / "crypto_xs_plain_funding_phase4_20261015_v1"
    / "required_funding_events.parquet"
)
VAL_SIGNAL = (
    ROOT
    / "data"
    / "processed"
    / "crypto_xs_plain_funding_decay_validation_20261015_v1"
    / "signal_panel_preoutcome.parquet"
)
VAL_EVENTS = (
    ROOT
    / "data"
    / "processed"
    / "crypto_xs_plain_funding_decay_validation_20261015_v1"
    / "required_funding_events.parquet"
)


def analyze(
    signal_path: Path,
    events_path: Path,
    *,
    years: set[int],
    label: str,
) -> tuple[dict, pl.DataFrame, pl.DataFrame]:
    signal = pl.read_parquet(signal_path).filter(
        pl.col("decision_ts").dt.year().is_in(sorted(years))
    )
    baskets = build_baskets(signal)
    events = pl.read_parquet(events_path).sort("symbol", "timestamp")
    by_symbol = {
        (symbol[0] if isinstance(symbol, tuple) else symbol): group.sort("timestamp")
        for symbol, group in events.group_by("symbol", maintain_order=True)
    }
    signal_lookup = {
        (row["decision_ts"], row["symbol"]): float(row["cum_funding_24h"])
        for row in signal.select(
            "decision_ts", "symbol", "cum_funding_24h"
        ).iter_rows(named=True)
    }

    legs: list[dict] = []
    cycles: list[dict] = []
    for decision_ts, targets in sorted(baskets.items()):
        if decision_ts.year not in years:
            continue
        entry = decision_ts + timedelta(hours=1)
        exit_ = entry + timedelta(hours=48)
        cycle_rows = []
        for symbol, weight in targets.items():
            side = "LONG" if weight > 0 else "SHORT"
            sign = 1.0 if weight > 0 else -1.0
            trail = signal_lookup[(decision_ts, symbol)]
            frame = by_symbol.get(symbol)
            if frame is None:
                forward_sum = 0.0
                n_events = 0
            else:
                held = frame.filter(
                    (pl.col("timestamp") > entry)
                    & (pl.col("timestamp") <= exit_)
                )
                forward_sum = (
                    float(held["funding_rate"].sum()) if held.height else 0.0
                )
                n_events = held.height
            signed_exante = -sign * trail
            signed_realized = -sign * forward_sum
            row = {
                "period": label,
                "year": decision_ts.year,
                "decision_ts": decision_ts,
                "symbol": symbol,
                "side": side,
                "target_weight": weight,
                "trailing_funding_24h": trail,
                "forward_funding_48h": forward_sum,
                "signed_exante_carry_24h": signed_exante,
                "signed_realized_carry_48h": signed_realized,
                "funding_events_48h": n_events,
            }
            legs.append(row)
            cycle_rows.append(row)

        trailing = np.asarray(
            [r["trailing_funding_24h"] for r in cycle_rows], dtype=float
        )
        forward = np.asarray(
            [r["forward_funding_48h"] for r in cycle_rows], dtype=float
        )
        persistence = (
            float(spearmanr(trailing, forward).statistic)
            if len(np.unique(trailing)) > 1 and len(np.unique(forward)) > 1
            else None
        )
        exante_portfolio = sum(
            abs(r["target_weight"]) * r["signed_exante_carry_24h"]
            for r in cycle_rows
        )
        realized_portfolio = sum(
            abs(r["target_weight"]) * r["signed_realized_carry_48h"]
            for r in cycle_rows
        )
        cycles.append(
            {
                "period": label,
                "year": decision_ts.year,
                "decision_ts": decision_ts,
                "funding_persistence_rank_ic": persistence,
                "exante_portfolio_carry_24h": exante_portfolio,
                "realized_portfolio_carry_48h": realized_portfolio,
                "realized_carry_positive": realized_portfolio > 0,
            }
        )

    leg_df = pl.DataFrame(legs).sort("decision_ts", "symbol")
    cycle_df = pl.DataFrame(cycles).sort("decision_ts")
    if leg_df.is_empty() or cycle_df.is_empty():
        raise RuntimeError(f"{label}: empty forensic panel")

    def aggregate_leg(frame: pl.DataFrame) -> dict:
        return {
            "legs": frame.height,
            "mean_trailing_funding_24h": float(
                frame["trailing_funding_24h"].mean()
            ),
            "mean_forward_funding_48h": float(
                frame["forward_funding_48h"].mean()
            ),
            "mean_signed_exante_carry_24h": float(
                frame["signed_exante_carry_24h"].mean()
            ),
            "mean_signed_realized_carry_48h": float(
                frame["signed_realized_carry_48h"].mean()
            ),
            "positive_realized_carry_share": float(
                (frame["signed_realized_carry_48h"] > 0).mean()
            ),
        }

    side = {
        side_name: aggregate_leg(
            leg_df.filter(pl.col("side") == side_name)
        )
        for side_name in ("LONG", "SHORT")
    }
    annual_rows = []
    for year in sorted(years):
        year_cycles = cycle_df.filter(pl.col("year") == year)
        year_legs = leg_df.filter(pl.col("year") == year)
        annual_rows.append(
            {
                "year": year,
                "cycles": year_cycles.height,
                "mean_funding_persistence_rank_ic": float(
                    year_cycles["funding_persistence_rank_ic"].drop_nulls().mean()
                ),
                "mean_exante_portfolio_carry_24h": float(
                    year_cycles["exante_portfolio_carry_24h"].mean()
                ),
                "mean_realized_portfolio_carry_48h": float(
                    year_cycles["realized_portfolio_carry_48h"].mean()
                ),
                "positive_realized_carry_cycle_share": float(
                    year_cycles["realized_carry_positive"].mean()
                ),
                "long_mean_realized_carry_48h": float(
                    year_legs.filter(pl.col("side") == "LONG")[
                        "signed_realized_carry_48h"
                    ].mean()
                ),
                "short_mean_realized_carry_48h": float(
                    year_legs.filter(pl.col("side") == "SHORT")[
                        "signed_realized_carry_48h"
                    ].mean()
                ),
            }
        )

    result = {
        "label": label,
        "years": sorted(years),
        "cycles": cycle_df.height,
        "legs": leg_df.height,
        "mean_funding_persistence_rank_ic": float(
            cycle_df["funding_persistence_rank_ic"].drop_nulls().mean()
        ),
        "mean_exante_portfolio_carry_24h": float(
            cycle_df["exante_portfolio_carry_24h"].mean()
        ),
        "mean_realized_portfolio_carry_48h": float(
            cycle_df["realized_portfolio_carry_48h"].mean()
        ),
        "positive_realized_carry_cycle_share": float(
            cycle_df["realized_carry_positive"].mean()
        ),
        "side": side,
        "annual": annual_rows,
    }
    return result, leg_df, cycle_df


def main() -> None:
    dev, dev_legs, dev_cycles = analyze(
        DEV_SIGNAL, DEV_EVENTS, years={2022, 2023}, label="2022_2023_reference"
    )
    val, val_legs, val_cycles = analyze(
        VAL_SIGNAL, VAL_EVENTS, years={2024, 2025}, label="2024_2025_validation"
    )
    ratios = {
        "funding_persistence_ratio": (
            val["mean_funding_persistence_rank_ic"]
            / dev["mean_funding_persistence_rank_ic"]
            if dev["mean_funding_persistence_rank_ic"] != 0
            else None
        ),
        "exante_carry_ratio": (
            val["mean_exante_portfolio_carry_24h"]
            / dev["mean_exante_portfolio_carry_24h"]
            if dev["mean_exante_portfolio_carry_24h"] != 0
            else None
        ),
        "realized_carry_ratio": (
            val["mean_realized_portfolio_carry_48h"]
            / dev["mean_realized_portfolio_carry_48h"]
            if dev["mean_realized_portfolio_carry_48h"] != 0
            else None
        ),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    pl.concat([dev_legs, val_legs]).write_parquet(OUT / "funding_leg_forensics.parquet")
    pl.concat([dev_cycles, val_cycles]).write_csv(OUT / "funding_cycle_forensics.csv")
    payload = {
        "reference_2022_2023": dev,
        "validation_2024_2025": val,
        "ratios": ratios,
        "interpretation_guardrail": (
            "Rate-space carry is a unit-notional mechanism diagnostic. Native "
            "cash PnL additionally depends on mark prices, changing equity and "
            "target-weight rescaling."
        ),
    }
    (OUT / "funding_persistence_summary.json").write_text(
        json.dumps(payload, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
