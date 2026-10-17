#!/usr/bin/env python3
"""Execute the frozen 20-cell NEAR EMA/ATR exit sweep."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.market_structure import _wilder_atr, build_signals

INPUT = Path("/home/quant/dev/quant/ml4t-data/data/crypto/market/ohlcv_1h/symbol=NEARUSDT/data.parquet")
OUT = ROOT / "run_log/near_market_structure_exit_sweep_20261006"
START = datetime(2020, 10, 15, 8, tzinfo=timezone.utc)
END = datetime(2026, 1, 1, tzinfo=timezone.utc)
TRAIN_END = datetime(2024, 1, 1, tzinfo=timezone.utc)
VALID_END = datetime(2025, 1, 1, tzinfo=timezone.utc)
EMA_PERIODS = (5, 8, 13, 21, 34)
ATR_MULTIPLIERS = (1.0, 1.5, 2.0, 2.5)


def _ema(values: np.ndarray, period: int) -> np.ndarray:
    """Causal EMA seeded with the first observation."""
    result = np.empty(len(values), dtype=float)
    if not len(values):
        return result
    alpha = 2.0 / (period + 1.0)
    result[0] = values[0]
    for i in range(1, len(values)):
        result[i] = alpha * values[i] + (1.0 - alpha) * result[i - 1]
    return result


def add_exit_features(bars: pl.DataFrame) -> pl.DataFrame:
    """Add current-close EMA and Wilder ATR features for frozen exit rule."""
    close = bars["close"].to_numpy()
    atr = _wilder_atr(bars, 14)
    return bars.with_columns(
        pl.Series("atr14_exit", atr),
        *[pl.Series(f"ema_{period}", _ema(close, period)) for period in EMA_PERIODS],
    )


def simulate(bars: pl.DataFrame, ema_period: int, atr_multiplier: float,
             per_side_bps: float = 10.0) -> tuple[pl.DataFrame, list[dict]]:
    """Simulate close decisions and next-open fills with compounding equity."""
    cost = per_side_bps / 10_000.0
    n = bars.height
    if not n:
        return pl.DataFrame(schema={"timestamp": pl.Datetime(time_zone="UTC"), "equity": pl.Float64, "exposure": pl.Float64}), []
    ts = bars["timestamp"].to_list()
    opens, closes = bars["open"].to_numpy(), bars["close"].to_numpy()
    atr, ema = bars["atr14_exit"].to_numpy(), bars[f"ema_{ema_period}"].to_numpy()
    signals = bars["entry_signal"].to_numpy()
    equity, qty, entry_i, entry_px, held = 1.0, 0.0, -1, 0.0, 0
    in_pos = queued_entry = queued_exit = False
    highest_close = 0.0
    exit_reason = None
    trades, rows = [], []

    for i in range(n):
        if i and queued_exit and in_pos:
            px = float(opens[i])
            equity = qty * px * (1.0 - cost)
            trades.append({
                "entry_time": ts[entry_i].isoformat(), "exit_time": ts[i].isoformat(),
                "entry_index": entry_i, "exit_index": i, "entry_price": entry_px,
                "exit_price": px, "holding_bars": held, "exit_reason": exit_reason,
                "net_return": (px / entry_px) * (1.0 - cost) ** 2 - 1.0,
            })
            qty, in_pos, queued_exit = 0.0, False, False
        if i and queued_entry and not in_pos:
            px = float(opens[i])
            qty = equity * (1.0 - cost) / px
            entry_i, entry_px, held, highest_close = i, px, 0, float(closes[i])
            in_pos, queued_entry = True, False
        if in_pos:
            held += 1
            equity = qty * float(closes[i])
            highest_close = max(highest_close, float(closes[i]))
            # Indicators and close are available at this completed bar close.
            level = max(float(ema[i]), highest_close - atr_multiplier * float(atr[i]))
            if float(closes[i]) < level and i < n - 1:
                queued_exit, exit_reason = True, "ema_atr_trail_next_open"
        elif not queued_entry and bool(signals[i]) and i < n - 1:
            queued_entry = True
        rows.append({"timestamp": ts[i], "equity": equity, "exposure": float(in_pos)})

    if in_pos:
        px = float(closes[-1])
        equity = qty * px * (1.0 - cost)
        trades.append({
            "entry_time": ts[entry_i].isoformat(), "exit_time": ts[-1].isoformat(),
            "entry_index": entry_i, "exit_index": n - 1, "entry_price": entry_px,
            "exit_price": px, "holding_bars": held,
            "exit_reason": "end_of_sample_liquidation",
            "net_return": (px / entry_px) * (1.0 - cost) ** 2 - 1.0,
        })
        rows[-1]["equity"], rows[-1]["exposure"] = equity, 0.0
    hourly = pl.DataFrame(rows)
    daily = hourly.group_by_dynamic("timestamp", every="1d", closed="left").agg(
        pl.col("equity").last(), pl.col("exposure").mean()
    ).sort("timestamp")
    return daily, trades


def metrics(daily: pl.DataFrame, trades: list[dict], period: str,
            bps: float, base_equity: float = 1.0) -> dict:
    if daily.is_empty():
        return {"period": period, "n_days": 0, "trade_count": 0}
    values = daily["equity"].to_numpy()
    path = np.r_[base_equity, values]
    returns = np.diff(path) / path[:-1]
    std = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
    sharpe = float(np.mean(returns) / std * math.sqrt(365)) if std > 0 else 0.0
    dd = path / np.maximum.accumulate(path) - 1.0
    pnls = np.asarray([t["net_return"] for t in trades], dtype=float)
    wins, losses = pnls[pnls > 0].sum(), -pnls[pnls < 0].sum()
    hold = [t["holding_bars"] for t in trades]
    return {
        "period": period, "n_days": int(len(values)), "net_return": float(values[-1] / base_equity - 1),
        "annualized_daily_sharpe": sharpe, "max_drawdown": float(dd.min()),
        "win_rate": float(np.mean(pnls > 0)) if len(pnls) else 0.0,
        "profit_factor": float(wins / losses) if losses else ("inf" if wins else None),
        "mean_trade_return": float(pnls.mean()) if len(pnls) else None,
        "median_trade_return": float(np.median(pnls)) if len(pnls) else None,
        "trade_count": len(trades), "exposure_fraction": float(daily["exposure"].mean()),
        "average_holding_bars": float(np.mean(hold)) if hold else None,
        "average_holding_hours": float(np.mean(hold)) if hold else None,
        "cost_bps_per_side": bps,
    }


def select_top5(train_rows: list[dict]) -> list[dict]:
    """Apply frozen train plateau ordering and stable tie breakers."""
    return sorted(train_rows, key=lambda r: (
        -r["train_plateau_score"], -r["train_profitable_fraction"],
        abs(r["max_drawdown"]), r["ema_period"], r["atr_multiplier"],
    ))[:5]


def select_final(validation_rows: list[dict]) -> dict:
    """Select by min(train plateau, validation Sharpe), then frozen ties."""
    return sorted(validation_rows, key=lambda r: (
        -min(r["train_plateau_score"], r["validation_sharpe"]),
        -r["validation_net_return"], abs(r["validation_max_drawdown"]),
        r["ema_period"], r["atr_multiplier"],
    ))[0]


def _write(rows: list[dict], stem: str) -> None:
    pl.DataFrame(rows).write_csv(OUT / f"{stem}.csv")
    (OUT / f"{stem}.json").write_text(json.dumps(rows, indent=2, allow_nan=False) + "\n")


def run() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    spec = json.loads((OUT / "frozen_spec.json").read_text())
    raw = pl.read_parquet(INPUT).sort("timestamp")
    target = raw.filter((pl.col("timestamp") >= START) & (pl.col("timestamp") < END))
    expected = int((END - START).total_seconds() // 3600)
    deltas = target.select((pl.col("timestamp") - pl.col("timestamp").shift(1)).alias("d")).filter(pl.col("d") != pl.duration(hours=1)).height
    if target.height != expected or target["timestamp"].n_unique() != target.height or deltas or target["timestamp"].min() != START or target["timestamp"].max() != END.replace(hour=0) - __import__("datetime").timedelta(hours=1):
        raise ValueError(f"Canonical data failed exact coverage/sort/unique/hourly-gap checks: rows={target.height}, expected={expected}, gaps={deltas}")
    # Causal features use data through each close. Prefix warmup preserves entry state.
    warm = raw.filter(pl.col("timestamp") < END)
    signaled, pivots = build_signals(warm)
    features = add_exit_features(signaled).filter(pl.col("timestamp") >= START)
    train = features.filter(pl.col("timestamp") < TRAIN_END)
    validation = features.filter((pl.col("timestamp") >= TRAIN_END) & (pl.col("timestamp") < VALID_END))
    test = features.filter((pl.col("timestamp") >= VALID_END) & (pl.col("timestamp") < END))
    outcomes, daily_by_key = {}, {}
    for ema, mult in itertools.product(EMA_PERIODS, ATR_MULTIPLIERS):
        key = (ema, mult)
        daily, trades = simulate(train, ema, mult, 10)
        m = metrics(daily, trades, "train", 10)
        outcomes[key] = {"train": m, "train_daily": daily, "train_trades": trades}
        daily_by_key[key] = daily
    train_rows = []
    for ema_i, ema in enumerate(EMA_PERIODS):
        for atr_i, mult in enumerate(ATR_MULTIPLIERS):
            neighbors = [outcomes[(e, a)]["train"] for ei, e in enumerate(EMA_PERIODS) for ai, a in enumerate(ATR_MULTIPLIERS) if abs(ei - ema_i) <= 1 and abs(ai - atr_i) <= 1]
            train_rows.append({"ema_period": ema, "atr_multiplier": mult,
                "train_net_return": outcomes[(ema, mult)]["train"]["net_return"],
                "train_sharpe": outcomes[(ema, mult)]["train"]["annualized_daily_sharpe"],
                "max_drawdown": outcomes[(ema, mult)]["train"]["max_drawdown"],
                "train_plateau_score": float(np.median([x["annualized_daily_sharpe"] for x in neighbors])),
                "train_profitable_fraction": float(np.mean([x["net_return"] > 0 for x in neighbors]))})
    _write(train_rows, "train_surface")
    top5 = select_top5(train_rows)
    val_rows = []
    for candidate in top5:
        ema, mult = candidate["ema_period"], candidate["atr_multiplier"]
        daily, trades = simulate(validation, ema, mult, 10)
        m = metrics(daily, trades, "validation", 10)
        val_rows.append({**candidate, "validation_net_return": m["net_return"],
                         "validation_sharpe": m["annualized_daily_sharpe"],
                         "validation_max_drawdown": m["max_drawdown"], **{"validation_" + k: v for k, v in m.items() if k not in {"period", "net_return", "annualized_daily_sharpe", "max_drawdown"}}})
    _write(val_rows, "validation_top5")
    selected = select_final(val_rows)
    selected_config = {"ema_period": selected["ema_period"], "atr_multiplier": selected["atr_multiplier"],
        "train_plateau_score": selected["train_plateau_score"], "train_profitable_fraction": selected["train_profitable_fraction"],
        "validation_net_return": selected["validation_net_return"], "validation_sharpe": selected["validation_sharpe"],
        "validation_gate": "PASS" if selected["validation_net_return"] > 0 and selected["validation_sharpe"] > 0 else "FAIL",
        "selection_rule": "max min(train_plateau_score, validation_sharpe); frozen tie breaks"}
    (OUT / "selected_config.json").write_text(json.dumps(selected_config, indent=2) + "\n")
    ema, mult = selected["ema_period"], selected["atr_multiplier"]
    selected_daily, selected_trades = simulate(test, ema, mult, 10)
    test_result = metrics(selected_daily, selected_trades, "2025_retrospective_test", 10)
    (OUT / "test_result.json").write_text(json.dumps(test_result, indent=2, allow_nan=False) + "\n")
    selected_daily.write_csv(OUT / "test_daily_equity.csv")
    pl.DataFrame(selected_trades).write_csv(OUT / "test_trades.csv")
    stress = []
    for bps in (10, 20, 30):
        daily, trades = simulate(test, ema, mult, bps)
        stress.append(metrics(daily, trades, "2025_retrospective_test", bps))
    _write(stress, "selected_cost_stress")
    # One continuous path gives calendar-year results and trades spanning boundaries.
    full_daily, full_trades = simulate(features, ema, mult, 10)
    year_rows = []
    for year in range(2020, 2026):
        lo = datetime(year, 1, 1, tzinfo=timezone.utc) if year > 2020 else START
        hi = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        yd = full_daily.filter((pl.col("timestamp") >= lo) & (pl.col("timestamp") < hi))
        prior = full_daily.filter(pl.col("timestamp") < lo)
        base = float(prior["equity"][-1]) if prior.height else 1.0
        yt = [t for t in full_trades if lo.isoformat() <= t["entry_time"] < hi.isoformat()]
        year_rows.append(metrics(yd, yt, f"{year}_partial" if year == 2020 else str(year), 10, base))
    _write(year_rows, "selected_yearly_metrics")
    # Verify per-trade factors exactly reproduce full-path terminal equity.
    compounded = float(np.prod([1.0 + t["net_return"] for t in full_trades]))
    equity_return = float(full_daily["equity"][-1])
    accounting_delta = abs(compounded - equity_return)
    # DSR receives all 20 aligned daily TRAIN returns, preserving the registered cohort.
    from ml4t.diagnostic.evaluation.stats import deflated_sharpe_ratio
    train_arrays = []
    train_dates = outcomes[(EMA_PERIODS[0], ATR_MULTIPLIERS[0])]["train_daily"]["timestamp"].to_list()
    for key in itertools.product(EMA_PERIODS, ATR_MULTIPLIERS):
        d = outcomes[key]["train_daily"]
        arr = d["equity"].to_numpy()
        train_arrays.append(np.diff(np.r_[1.0, arr]) / np.r_[1.0, arr][:-1])
    dsr = deflated_sharpe_ratio(train_arrays, frequency="daily", periods_per_year=365)
    dsr_record = {k: getattr(dsr, k) for k in ("probability", "is_significant", "n_samples", "n_trials", "expected_max_sharpe", "deflated_sharpe", "variance_trials", "frequency", "periods_per_year")}
    (OUT / "trial_accounting.json").write_text(json.dumps({"registered_exit_parameter_trials": 20, "prior_baseline_trial": 1, "dsr_cohort": "20 frozen exit configurations on aligned TRAIN daily returns", "dsr": dsr_record}, indent=2, default=str) + "\n")
    # Previous baseline is only a high-level descriptive comparator, not pooled.
    baseline_path = ROOT / "run_log/near_market_structure_20261005/result.json"
    baseline = json.loads(baseline_path.read_text())
    summary = {
        "session_id": spec["session_id"], "status": "EXPLORATORY", "approval_status": "NOT_APPROVED",
        "instrument": spec["instrument"], "input_sha256": hashlib.sha256(INPUT.read_bytes()).hexdigest(),
        "coverage": {"rows": target.height, "expected_rows": expected, "gaps": deltas, "duplicates": target.height-target["timestamp"].n_unique(), "sorted": target["timestamp"].is_sorted(), "start": target["timestamp"].min().isoformat(), "end": target["timestamp"].max().isoformat()},
        "entry_signals": int(features["entry_signal"].sum()), "confirmed_pivots": len(pivots),
        "trial_count": 20, "trials": [{"ema_period": r["ema_period"], "atr_multiplier": r["atr_multiplier"], "train_net_return": r["train_net_return"], "train_sharpe": r["train_sharpe"]} for r in train_rows],
        "selected_config": selected_config, "retrospective_test": test_result,
        "selected_cost_stress": stress, "yearly_metrics": year_rows,
        "dsr": dsr_record,
        "baseline_comparison": {"source": "run_log/near_market_structure_20261005/result.json", "status": "descriptive_only_different_exit_and_2024-2025_period", "prior_2024_net_return": baseline["metrics_by_cost_bps_per_side"]["10"][1]["total_net_return"], "prior_2025_net_return": baseline["metrics_by_cost_bps_per_side"]["10"][2]["total_net_return"]},
        "funding_included": False, "funding_note": spec["costs"]["funding_note"],
        "accounting_check": {"compounded_trade_return": compounded, "portfolio_equity_return": equity_return, "absolute_difference": accounting_delta, "passed": accounting_delta < 1e-12},
        "overfitting_note": "20 exit parameter trials were preregistered. DSR uses the aligned TRAIN daily returns from these 20 cells. Earlier baseline is a separate prior trial and is not pooled because its exit rule and period differ. 2025 is retrospective, not untouched.",
        "selected_skills": [
          {"name":"ml4t-sensitivity-analysis","path":".agents/skills/ml4t-sensitivity-analysis/SKILL.md","invariant":"retain full 2D surface and neighborhood stability","verification":"train_surface.csv/json and frozen plateau selection"},
          {"name":"ml4t-backtest-overfitting","path":".agents/skills/ml4t-backtest-overfitting/SKILL.md","invariant":"count all 20 preregistered cells","verification":"trial_accounting.json and aligned-return DSR"},
          {"name":"ml4t-walk-forward-cv","path":".agents/skills/ml4t-walk-forward-cv/SKILL.md","invariant":"chronological splits with no shuffling","verification":"frozen TRAIN/VALIDATION/retrospective TEST ranges"},
          {"name":"ml4t-run-backtest","path":".agents/skills/ml4t-run-backtest/SKILL.md","invariant":"close decisions fill at next open; costs per side","verification":"simulation and tests"},
          {"name":"ml4t-lookahead-bias","path":".agents/skills/ml4t-lookahead-bias/SKILL.md","invariant":"no future bars affect features, entries, or exits","verification":"causal indicators and append-future tests"}],
        "next_decisive_question": "Can a selected exit remain positive after validated venue execution costs and realized funding, using genuinely new post-2025 data?"
    }
    if accounting_delta >= 1e-12:
        raise AssertionError(f"Trade compounding does not reconcile with portfolio: {accounting_delta}")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False, default=str) + "\n")
    return summary


if __name__ == "__main__":
    result = run()
    print(json.dumps({"selected_config": result["selected_config"], "test": result["retrospective_test"], "accounting_check": result["accounting_check"]}, indent=2))
