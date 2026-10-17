"""Temporal robustness and regime attribution for the frozen TSMOM candidate.

Candidate is fixed:
  mean(sign(ROC40), sign(ROC60), sign(ROC80)) * 20% annual vol target,
  capped at 1x gross.

This script does not fit or select parameters. It evaluates chronological
slices of the already-observed development sample. DAX remains supplemental.
"""

from __future__ import annotations

import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.run_tsmom_40_60_80_lse_2020_2026 as base
from ml4t.backtest import BacktestConfig, DataFeed, Engine
from ml4t.backtest.config import CommissionType, ShareType, SlippageType

PRIMARY = ("BTCUSDT", "ETHUSDT", "HYPEUSDT", "NIKKEI225_LSE")
SUPPLEMENTAL = ("DAX_LSE",)
SIGNAL_COL = "sig_ensemble_vt"


def jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, (np.integer, np.floating)):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def run_candidate(
    inst: base.Instrument,
    feat: pl.DataFrame,
    *,
    cost_multiplier: float,
):
    frame = feat.select(
        ["timestamp", "symbol", "open", "high", "low", "close", "volume", SIGNAL_COL]
    ).drop_nulls([SIGNAL_COL])
    prices = frame.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
    signals = frame.select(["timestamp", "symbol", SIGNAL_COL])
    config = BacktestConfig(
        initial_cash=base.INITIAL_CASH,
        allow_short_selling=True,
        allow_leverage=True,
        share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=inst.commission_rate * cost_multiplier,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=inst.slippage_rate * cost_multiplier,
        calendar=inst.calendar,
    )
    result = Engine(
        DataFeed(
            prices_df=prices,
            signals_df=signals,
            entity_col="symbol",
            timestamp_col="timestamp",
        ),
        base.SignalTargetStrategy(SIGNAL_COL),
        config,
    ).run()
    daily = result.to_daily_pnl(session_aligned=False).select(
        ["date", pl.col("return_pct").alias("return")]
    )
    return result, daily


def slice_metrics(returns: np.ndarray, periods_per_year: int) -> dict[str, Any]:
    r = returns[np.isfinite(returns)]
    if r.size == 0:
        return {
            "n": 0,
            "total_return": None,
            "sharpe": None,
            "max_drawdown": None,
            "hit_rate": None,
            "mean_daily_bps": None,
        }
    wealth = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(wealth)
    dd = wealth / peak - 1.0
    std = float(np.std(r, ddof=1)) if r.size > 1 else 0.0
    sharpe = float(np.mean(r) / std * math.sqrt(periods_per_year)) if std > 0 else 0.0
    return {
        "n": int(r.size),
        "total_return": float(wealth[-1] - 1.0),
        "sharpe": sharpe,
        "max_drawdown": float(-np.min(dd)),
        "hit_rate": float(np.mean(r > 0)),
        "mean_daily_bps": float(np.mean(r) * 10000.0),
    }


def annual_slices(daily: pl.DataFrame, periods_per_year: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    years = sorted(set(daily["date"].dt.year().to_list()))
    for year in years:
        sub = daily.filter(pl.col("date").dt.year() == year)
        out[str(year)] = slice_metrics(sub["return"].to_numpy(), periods_per_year)
    valid = [v for v in out.values() if v["n"] >= max(60, int(periods_per_year * 0.20))]
    return {
        "by_year": out,
        "summary": {
            "valid_slices": len(valid),
            "positive_return_slices": int(sum(v["total_return"] > 0 for v in valid)),
            "positive_return_fraction": float(np.mean([v["total_return"] > 0 for v in valid])) if valid else None,
            "positive_sharpe_slices": int(sum(v["sharpe"] > 0 for v in valid)),
            "median_sharpe": float(np.median([v["sharpe"] for v in valid])) if valid else None,
            "worst_return": float(min(v["total_return"] for v in valid)) if valid else None,
            "worst_max_drawdown": float(max(v["max_drawdown"] for v in valid)) if valid else None,
        },
    }


def rolling_one_year(
    daily: pl.DataFrame,
    periods_per_year: int,
    *,
    step_days: int = 90,
) -> dict[str, Any]:
    start = daily["date"].min()
    end = daily["date"].max()
    if start is None or end is None:
        return {"windows": [], "summary": {}}
    min_obs = max(60, int(periods_per_year * 0.70))
    windows: list[dict[str, Any]] = []
    cursor = start
    while cursor + timedelta(days=365) <= end + timedelta(days=1):
        stop = cursor + timedelta(days=365)
        sub = daily.filter((pl.col("date") >= cursor) & (pl.col("date") < stop))
        metrics = slice_metrics(sub["return"].to_numpy(), periods_per_year)
        if metrics["n"] >= min_obs:
            windows.append(
                {
                    "start": str(cursor),
                    "end_exclusive": str(stop),
                    **metrics,
                }
            )
        cursor = cursor + timedelta(days=step_days)
    return {
        "windows": windows,
        "summary": {
            "windows": len(windows),
            "positive_return_windows": int(sum(w["total_return"] > 0 for w in windows)),
            "positive_return_fraction": float(np.mean([w["total_return"] > 0 for w in windows])) if windows else None,
            "positive_sharpe_windows": int(sum(w["sharpe"] > 0 for w in windows)),
            "median_sharpe": float(np.median([w["sharpe"] for w in windows])) if windows else None,
            "worst_return": float(min(w["total_return"] for w in windows)) if windows else None,
            "best_return": float(max(w["total_return"] for w in windows)) if windows else None,
        },
    }


def causal_vol_regimes(feat: pl.DataFrame) -> pl.DataFrame:
    dates = feat["timestamp"].dt.date().to_list()
    rv = feat["rv20"].to_numpy()
    labels: list[str | None] = []
    values: list[float | None] = []
    q33s: list[float | None] = []
    q67s: list[float | None] = []

    for i in range(len(rv)):
        hist = rv[max(0, i - 252):i]
        hist = hist[np.isfinite(hist)]
        value = rv[i - 1] if i > 0 and np.isfinite(rv[i - 1]) else np.nan
        if hist.size < 60 or not np.isfinite(value):
            labels.append(None)
            values.append(None)
            q33s.append(None)
            q67s.append(None)
            continue
        q33 = float(np.quantile(hist, 1.0 / 3.0))
        q67 = float(np.quantile(hist, 2.0 / 3.0))
        if value <= q33:
            label = "low_vol"
        elif value >= q67:
            label = "high_vol"
        else:
            label = "mid_vol"
        labels.append(label)
        values.append(float(value))
        q33s.append(q33)
        q67s.append(q67)

    return pl.DataFrame(
        {
            "date": dates,
            "regime": labels,
            "lagged_rv20": values,
            "q33": q33s,
            "q67": q67s,
        }
    )


def regime_attribution(
    daily: pl.DataFrame,
    feat: pl.DataFrame,
    periods_per_year: int,
) -> dict[str, Any]:
    regimes = causal_vol_regimes(feat)
    joined = daily.join(regimes, on="date", how="left").drop_nulls(["regime"])
    out: dict[str, Any] = {}
    for label in ("low_vol", "mid_vol", "high_vol"):
        sub = joined.filter(pl.col("regime") == label)
        out[label] = slice_metrics(sub["return"].to_numpy(), periods_per_year)
        if sub.height:
            out[label]["mean_lagged_rv20"] = float(sub["lagged_rv20"].mean())
        else:
            out[label]["mean_lagged_rv20"] = None
    return {
        "definition": "lagged rv20 versus rolling prior-252-observation 33rd/67th percentiles; min 60 observations",
        "classified_days": joined.height,
        "regimes": out,
    }


def load_all_data():
    data: dict[str, pl.DataFrame] = {}
    audits: dict[str, Any] = {}
    for symbol in ("BTCUSDT", "ETHUSDT", "HYPEUSDT"):
        data[symbol], audits[symbol] = base.load_crypto_daily(symbol)
    data["NIKKEI225_LSE"], audits["NIKKEI225_LSE"] = base.load_nikkei_daily()
    data["DAX_LSE"], audits["DAX_LSE"] = base.load_dax_repaired_daily()
    return data, audits


def market_validation(
    symbol: str,
    daily_prices: pl.DataFrame,
    audit: dict[str, Any],
) -> dict[str, Any]:
    inst = base.INSTRUMENTS[symbol]
    feat = base.engineer_features(inst, daily_prices)
    base_result, base_daily = run_candidate(inst, feat, cost_multiplier=1.0)
    stress_result, stress_daily = run_candidate(inst, feat, cost_multiplier=2.0)

    return {
        "data_status": audit["status"],
        "base_full_sample": {
            "total_return": float(base_result.metrics["total_return"]),
            "sharpe": float(base_result.metrics["sharpe"]),
            "max_drawdown": float(base_result.metrics["max_drawdown"]),
            "num_trades": int(base_result.metrics["num_trades"]),
        },
        "stress_2x_full_sample": {
            "total_return": float(stress_result.metrics["total_return"]),
            "sharpe": float(stress_result.metrics["sharpe"]),
            "max_drawdown": float(stress_result.metrics["max_drawdown"]),
            "num_trades": int(stress_result.metrics["num_trades"]),
        },
        "annual_base": annual_slices(base_daily, inst.periods_per_year),
        "annual_stress_2x": annual_slices(stress_daily, inst.periods_per_year),
        "rolling_one_year_base": rolling_one_year(base_daily, inst.periods_per_year),
        "rolling_one_year_stress_2x": rolling_one_year(stress_daily, inst.periods_per_year),
        "regime_base": regime_attribution(base_daily, feat, inst.periods_per_year),
    }


def primary_summary(markets: dict[str, Any]) -> dict[str, Any]:
    rows = [markets[s] for s in PRIMARY]
    return {
        "markets": list(PRIMARY),
        "full_sample_positive_base": int(sum(x["base_full_sample"]["total_return"] > 0 for x in rows)),
        "full_sample_positive_2x_cost": int(sum(x["stress_2x_full_sample"]["total_return"] > 0 for x in rows)),
        "annual_positive_fraction_by_market": {
            s: markets[s]["annual_base"]["summary"]["positive_return_fraction"] for s in PRIMARY
        },
        "rolling_1y_positive_fraction_by_market": {
            s: markets[s]["rolling_one_year_base"]["summary"]["positive_return_fraction"] for s in PRIMARY
        },
        "rolling_1y_positive_fraction_2x_cost_by_market": {
            s: markets[s]["rolling_one_year_stress_2x"]["summary"]["positive_return_fraction"] for s in PRIMARY
        },
        "positive_sharpe_all_vol_regimes": {
            s: all(
                markets[s]["regime_base"]["regimes"][reg]["sharpe"] is not None
                and markets[s]["regime_base"]["regimes"][reg]["sharpe"] > 0
                for reg in ("low_vol", "mid_vol", "high_vol")
            )
            for s in PRIMARY
        },
    }


def main() -> None:
    data, audits = load_all_data()
    markets: dict[str, Any] = {}
    for symbol in (*PRIMARY, *SUPPLEMENTAL):
        markets[symbol] = market_validation(symbol, data[symbol], audits[symbol])

    output = {
        "schema": "tsmom_temporal_validation/v1",
        "session_id": "tsmom_40_60_80_lse_2020_2026",
        "classification": "EXPLORATORY",
        "approval_status": "NOT_APPROVED",
        "candidate_frozen": True,
        "candidate": "equal 40/60/80 sign ensemble times 20% annual volatility target, capped at 1x",
        "window": "2020-01-01 through 2026-09-30; HYPE from listing",
        "walk_forward_note": (
            "The strategy has no fitted model or trainable parameters. Expanding versus rolling "
            "training is therefore not applicable. Sequential annual slices and quarterly-stepped "
            "one-year forward windows test temporal stability of the frozen rule."
        ),
        "markets": markets,
        "primary_summary": primary_summary(markets),
        "selection_bias": {
            "dsr_status": "BLOCKED",
            "pbo_status": "BLOCKED",
            "reason": "The complete historical trial ledger across earlier TSMOM exploration is not reconstructable. Do not compute a misleading trial-count correction.",
        },
        "limitations": [
            "All dates in this validation were already available during development; this is not a final unseen holdout.",
            "HYPE has a short sample that starts after its 2025 listing.",
            "Crypto funding remains excluded because no canonical HYPE funding series is available locally.",
            "Nikkei is an LSE research-price proxy, not a contract-level futures series.",
            "DAX remains supplemental because fresh LSE DE30/EUR fails the primary data-quality gate.",
            "Regime attribution is descriptive. It does not alter the strategy or time the market.",
        ],
    }
    print("RESULT_JSON_BEGIN")
    print(json.dumps(jsonable(output), sort_keys=True))
    print("RESULT_JSON_END")


if __name__ == "__main__":
    main()
