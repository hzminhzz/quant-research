"""Phase 2-3 cross-asset time-series momentum replication.

This runner is read-only with respect to project artifacts. It prints one JSON
result document to stdout. The caller persists the captured result separately.

Methodology:
- ml4t.engineer.compute_features for registered features.
- ml4t.diagnostic.analyze_signal for supplemental panel diagnostics.
- ml4t.backtest.Engine for all strategy simulations.
- NEXT_BAR / OPEN execution. Signals use only completed bars.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from scipy import stats
from statsmodels.regression.linear_model import OLS

from ml4t.engineer import compute_features
from ml4t.diagnostic import analyze_signal
from ml4t.backtest import BacktestConfig, DataFeed, Engine, Strategy
from ml4t.backtest.config import CommissionType, ShareType, SlippageType

ROOT = Path(__file__).resolve().parents[1]
DEV_END = pl.datetime(2026, 8, 1, 0, 0, 0, time_zone="UTC")
INITIAL_CASH = 100_000.0

FEATURE_SPECS = [
    {"name": "roc", "output": "mom_20", "params": {"period": 20}},
    {"name": "roc", "output": "mom_60", "params": {"period": 60}},
    {"name": "roc", "output": "mom_120", "params": {"period": 120}},
    {"name": "ema", "output": "ema_20", "params": {"period": 20}},
    {"name": "ema", "output": "ema_60", "params": {"period": 60}},
    {"name": "donchian_channels", "output": "don_60", "params": {"period": 60}},
    {"name": "adx", "output": "adx_14", "params": {"period": 14}},
    {"name": "atr", "output": "atr_20", "params": {"period": 20}},
    {"name": "ewma_volatility", "output": "ewma_vol_20", "params": {"span": 20, "normalize": False}},
]

TRIALS = {
    "t0_momentum_60": "sig_t0",
    "t1_multi_horizon_momentum": "sig_t1",
    "t2_ema_20_60": "sig_t2",
    "t3_donchian_60": "sig_t3",
    "t4_equal_composite": "sig_t4",
    "t5_composite_vol_scaled": "sig_t5",
}

HORIZONS = (5, 20, 60)


@dataclass(frozen=True)
class Instrument:
    symbol: str
    path: str
    asset_class: str
    periods_per_year: int
    commission_rate: float
    slippage_rate: float


INSTRUMENTS = (
    Instrument("BTCUSDT", "data/processed/btc_1h.parquet", "crypto", 365, 0.00045, 0.00015),
    Instrument("ETHUSDT", "data/processed/eth_1h.parquet", "crypto", 365, 0.00045, 0.00015),
    Instrument("HYPEUSDT", "data/processed/hypeusdt_1h.parquet", "crypto", 365, 0.00045, 0.00015),
    Instrument("DE30_EUR_PROXY", "data/processed/dax_1m.parquet", "index_proxy", 252, 0.00020, 0.00010),
    Instrument("JP225_USD_PROXY", "data/processed/JP225_USD_5m_2017_2026.parquet", "index_proxy", 252, 0.00020, 0.00010),
)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (np.floating, np.integer)):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _sign_expr(column: str) -> pl.Expr:
    return (
        pl.when(pl.col(column) > 0)
        .then(pl.lit(1.0))
        .when(pl.col(column) < 0)
        .then(pl.lit(-1.0))
        .otherwise(pl.lit(0.0))
    )


def load_daily(inst: Instrument) -> pl.DataFrame:
    path = ROOT / inst.path
    if not path.is_file():
        raise FileNotFoundError(path)

    raw = (
        pl.scan_parquet(path)
        .select(["timestamp", "open", "high", "low", "close", "volume"])
        .filter(pl.col("timestamp") < DEV_END)
        .sort("timestamp")
        .collect()
    )

    raw = raw.with_columns(pl.col("timestamp").dt.cast_time_unit("us"))

    daily = (
        raw.group_by_dynamic("timestamp", every="1d", closed="left", label="left")
        .agg(
            pl.col("open").first().alias("open"),
            pl.col("high").max().alias("high"),
            pl.col("low").min().alias("low"),
            pl.col("close").last().alias("close"),
            pl.col("volume").sum().alias("volume"),
        )
        .drop_nulls(["open", "high", "low", "close"])
        .sort("timestamp")
        .with_columns(pl.lit(inst.symbol).alias("symbol"))
    )
    return daily


def audit_daily(df: pl.DataFrame) -> dict[str, Any]:
    return {
        "rows": df.height,
        "start": str(df["timestamp"].min()),
        "end": str(df["timestamp"].max()),
        "duplicates": int(df.select(pl.col("timestamp").is_duplicated().sum()).item()),
        "null_close": int(df["close"].null_count()),
        "high_lt_low": int(df.filter(pl.col("high") < pl.col("low")).height),
        "close_outside_range": int(
            df.filter((pl.col("close") > pl.col("high")) | (pl.col("close") < pl.col("low"))).height
        ),
    }


def engineer(inst: Instrument, daily: pl.DataFrame) -> pl.DataFrame:
    feat = compute_features(daily.drop("symbol"), FEATURE_SPECS).rename(
        {
            "don_60_0": "don_60_upper",
            "don_60_1": "don_60_lower",
            "don_60_2": "don_60_mid",
        }
    )

    feat = feat.with_columns(
        pl.lit(inst.symbol).alias("symbol"),
        pl.col("don_60_upper").shift(1).alias("don_60_upper_prev"),
        pl.col("don_60_lower").shift(1).alias("don_60_lower_prev"),
    )

    feat = feat.with_columns(
        _sign_expr("mom_60").alias("sig_t0"),
        ((_sign_expr("mom_20") + _sign_expr("mom_60") + _sign_expr("mom_120")) / 3.0).alias("sig_t1"),
        _sign_expr("ema_20").alias("_ema20_sign_placeholder"),
    ).with_columns(
        pl.when(pl.col("ema_20") > pl.col("ema_60"))
        .then(pl.lit(1.0))
        .when(pl.col("ema_20") < pl.col("ema_60"))
        .then(pl.lit(-1.0))
        .otherwise(pl.lit(0.0))
        .alias("sig_t2"),
        pl.when(pl.col("close") > pl.col("don_60_upper_prev"))
        .then(pl.lit(1.0))
        .when(pl.col("close") < pl.col("don_60_lower_prev"))
        .then(pl.lit(-1.0))
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .alias("_don_event"),
    ).drop("_ema20_sign_placeholder")

    feat = feat.with_columns(pl.col("_don_event").forward_fill().alias("sig_t3")).with_columns(
        ((pl.col("sig_t1") + pl.col("sig_t2") + pl.col("sig_t3")) / 3.0).alias("sig_t4"),
        (pl.col("ewma_vol_20") * math.sqrt(inst.periods_per_year)).alias("ewma_vol_ann"),
    ).with_columns(
        pl.when(pl.col("ewma_vol_ann") > 0)
        .then((0.20 / pl.col("ewma_vol_ann")).clip(0.0, 1.0))
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .alias("vol_scalar")
    ).with_columns(
        (pl.col("sig_t4") * pl.col("vol_scalar")).alias("sig_t5"),
        ((pl.col("ema_20") - pl.col("ema_60")) / pl.col("atr_20")).alias("ema_gap_atr"),
        (
            (pl.col("close") - pl.col("don_60_lower_prev"))
            / (pl.col("don_60_upper_prev") - pl.col("don_60_lower_prev"))
        ).alias("donchian_pos_60"),
    )

    fwd_exprs = [
        (pl.col("close").shift(-h) / pl.col("close") - 1.0).alias(f"fwd_{h}")
        for h in HORIZONS
    ]
    return feat.with_columns(fwd_exprs).sort("timestamp")


def hac_mean_tstat(values: np.ndarray, maxlags: int) -> tuple[float, float]:
    finite = values[np.isfinite(values)]
    if finite.size < 20:
        return float("nan"), float("nan")
    model = OLS(finite, np.ones((finite.size, 1))).fit(
        cov_type="HAC", cov_kwds={"maxlags": maxlags}
    )
    return float(model.tvalues[0]), float(model.pvalues[0])


def phase2_diagnostics(inst: Instrument, df: pl.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for trial_id, signal_col in TRIALS.items():
        trial_result: dict[str, Any] = {}
        for horizon in HORIZONS:
            sub = df.select([signal_col, f"fwd_{horizon}"]).drop_nulls()
            if sub.height == 0:
                trial_result[str(horizon)] = {"n": 0}
                continue
            signal = sub[signal_col].to_numpy()
            fwd = sub[f"fwd_{horizon}"].to_numpy()
            active = np.abs(signal) > 1e-12
            signal = signal[active]
            fwd = fwd[active]
            if signal.size == 0:
                trial_result[str(horizon)] = {"n": 0}
                continue
            signed = signal * fwd
            rho, p_naive = stats.spearmanr(signal, fwd)
            t_hac, p_hac = hac_mean_tstat(signed, maxlags=min(max(horizon - 1, 1), 60))
            trial_result[str(horizon)] = {
                "n": int(signal.size),
                "rank_ic": float(rho),
                "rank_ic_naive_p": float(p_naive),
                "mean_signed_forward_return": float(np.mean(signed)),
                "median_signed_forward_return": float(np.median(signed)),
                "directional_hit_rate": float(np.mean(signed > 0)),
                "hac_t_stat_mean_signed_return": t_hac,
                "hac_p_value_mean_signed_return": p_hac,
            }
        out[trial_id] = trial_result

    adx_frame = (
        df.select(["adx_14", "sig_t4", "fwd_20"])
        .drop_nulls()
        .filter(pl.col("sig_t4").abs() > 1e-12)
    )
    adx_diag: list[dict[str, Any]] = []
    if adx_frame.height >= 40:
        ranks = stats.rankdata(adx_frame["adx_14"].to_numpy(), method="average")
        quartile = np.minimum(4, np.ceil(ranks / len(ranks) * 4).astype(int))
        signed = adx_frame["sig_t4"].to_numpy() * adx_frame["fwd_20"].to_numpy()
        for q in range(1, 5):
            mask = quartile == q
            adx_diag.append(
                {
                    "quartile": q,
                    "n": int(mask.sum()),
                    "mean_adx": float(adx_frame["adx_14"].to_numpy()[mask].mean()),
                    "mean_signed_fwd20": float(signed[mask].mean()),
                }
            )

    signal_cols = ["sig_t0", "sig_t1", "sig_t2", "sig_t3", "sig_t4"]
    corr_df = df.select(signal_cols).drop_nulls()
    correlations: dict[str, dict[str, float | None]] = {}
    for left in signal_cols:
        correlations[left] = {}
        for right in signal_cols:
            if corr_df.height < 2:
                correlations[left][right] = None
            else:
                correlations[left][right] = float(
                    np.corrcoef(corr_df[left].to_numpy(), corr_df[right].to_numpy())[0, 1]
                )

    return {
        "instrument": inst.symbol,
        "time_series": out,
        "adx_quartiles_t4_fwd20": adx_diag,
        "signal_correlations": correlations,
    }


class TargetSignalStrategy(Strategy):
    def __init__(self, signal_col: str):
        super().__init__()
        self.signal_col = signal_col

    def on_data(self, timestamp, data, context, broker) -> None:
        for symbol, bar in data.items():
            value = bar["signals"].get(self.signal_col)
            if value is None:
                continue
            target = float(value)
            if not math.isfinite(target):
                continue
            target = max(-1.0, min(1.0, target))
            broker.order_target_percent(symbol, target)


def run_backtest(
    inst: Instrument,
    df: pl.DataFrame,
    signal_col: str,
    *,
    cost_multiplier: float = 1.0,
) -> dict[str, Any]:
    valid = df.select(
        ["timestamp", "symbol", "open", "high", "low", "close", "volume", signal_col]
    ).drop_nulls([signal_col])

    prices = valid.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
    signals = valid.select(["timestamp", "symbol", signal_col])
    if prices.height < 3:
        raise RuntimeError(f"{inst.symbol} has insufficient backtest rows for {signal_col}")

    config = BacktestConfig(
        initial_cash=INITIAL_CASH,
        allow_short_selling=True,
        allow_leverage=True,
        share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=inst.commission_rate * cost_multiplier,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=inst.slippage_rate * cost_multiplier,
    )
    feed = DataFeed(
        prices_df=prices,
        signals_df=signals,
        entity_col="symbol",
        timestamp_col="timestamp",
    )
    result = Engine(feed, TargetSignalStrategy(signal_col), config).run()
    metrics = result.metrics

    def metric(*names: str, default: float = 0.0) -> float:
        for name in names:
            if name in metrics and metrics[name] is not None:
                return float(metrics[name])
        return default

    return {
        "bars": int(prices.height),
        "start": str(prices["timestamp"].min()),
        "end": str(prices["timestamp"].max()),
        "initial_cash": INITIAL_CASH,
        "final_value": metric("final_value", default=INITIAL_CASH),
        "total_return": metric("total_return", "total_return_pct"),
        "sharpe": metric("sharpe"),
        "max_drawdown": metric("max_drawdown", "max_drawdown_pct"),
        "num_trades": int(metric("num_trades")),
        "win_rate": metric("win_rate"),
        "profit_factor": metric("profit_factor"),
        "total_commission": metric("total_commission"),
        "total_slippage": metric("total_slippage"),
        "total_costs": metric("total_costs"),
        "execution": {
            "mode": str(config.execution_mode),
            "price": str(config.execution_price),
            "commission_rate_per_side": inst.commission_rate * cost_multiplier,
            "slippage_rate_per_side": inst.slippage_rate * cost_multiplier,
            "cost_multiplier": cost_multiplier,
        },
    }


def panel_diagnostic(frames: list[pl.DataFrame]) -> dict[str, Any]:
    factor = (
        pl.concat(
            [
                frame.select(["timestamp", "symbol", "mom_60"])
                .rename({"timestamp": "date", "symbol": "asset", "mom_60": "factor"})
                for frame in frames
            ],
            how="vertical",
        )
        .drop_nulls()
        .sort(["date", "asset"])
    )
    prices = (
        pl.concat(
            [
                frame.select(["timestamp", "symbol", "close"])
                .rename({"timestamp": "date", "symbol": "asset", "close": "price"})
                for frame in frames
            ],
            how="vertical",
        )
        .drop_nulls()
        .sort(["date", "asset"])
    )
    try:
        result = analyze_signal(
            factor=factor,
            prices=prices,
            periods=HORIZONS,
            quantiles=2,
            min_assets=3,
            compute_turnover_flag=False,
        )
        return {"status": "completed", "result": _jsonable(result.to_dict())}
    except Exception as exc:
        return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}


def main() -> None:
    audits: dict[str, Any] = {}
    features: dict[str, pl.DataFrame] = {}
    phase2: dict[str, Any] = {}
    phase3: dict[str, Any] = {}

    for inst in INSTRUMENTS:
        daily = load_daily(inst)
        audits[inst.symbol] = audit_daily(daily)
        feat = engineer(inst, daily)
        features[inst.symbol] = feat
        phase2[inst.symbol] = phase2_diagnostics(inst, feat)

    for inst in INSTRUMENTS:
        inst_results: dict[str, Any] = {}
        for trial_id, signal_col in TRIALS.items():
            inst_results[trial_id] = run_backtest(inst, features[inst.symbol], signal_col)
        inst_results["cost_stress_2x"] = {
            "t4_equal_composite": run_backtest(
                inst, features[inst.symbol], "sig_t4", cost_multiplier=2.0
            ),
            "t5_composite_vol_scaled": run_backtest(
                inst, features[inst.symbol], "sig_t5", cost_multiplier=2.0
            ),
        }
        phase3[inst.symbol] = inst_results

    t4_returns = {
        sym: float(res["t4_equal_composite"]["total_return"])
        for sym, res in phase3.items()
    }
    t4_sharpes = [
        float(res["t4_equal_composite"]["sharpe"]) for res in phase3.values()
    ]
    stress_positive = {
        sym: float(res["cost_stress_2x"]["t4_equal_composite"]["total_return"]) > 0
        for sym, res in phase3.items()
    }

    summary = {
        "positive_t4_instruments": int(sum(ret > 0 for ret in t4_returns.values())),
        "t4_total_returns": t4_returns,
        "median_t4_sharpe": float(np.median(t4_sharpes)),
        "positive_t4_under_2x_cost": int(sum(stress_positive.values())),
        "stress_positive_by_instrument": stress_positive,
        "falsifier_checks": {
            "t4_positive_at_least_4_of_5": sum(ret > 0 for ret in t4_returns.values()) >= 4,
            "median_t4_sharpe_positive": float(np.median(t4_sharpes)) > 0,
            "t4_2x_cost_positive_at_least_3_of_5": sum(stress_positive.values()) >= 3,
            "parameter_plateau": "not_evaluated_in_phase_2_3",
        },
    }

    result = {
        "schema": "cross_asset_tsmom_phase2_3/v1",
        "session_id": "cross_asset_tsmom_replication_20261007",
        "classification": "EXPLORATORY",
        "approval_status": "NOT_APPROVED",
        "development_end_exclusive": "2026-08-01T00:00:00Z",
        "funding_included": False,
        "limitations": [
            "BTC and ETH TSMOM history was previously observed; this is development/historical evidence, not a fresh holdout.",
            "HYPEUSDT local price history starts in 2025 and no local HYPE funding dataset was found.",
            "Crypto funding is excluded from all Phase 3 simulations for comparability; crypto economics are cost-incomplete.",
            "DE30_EUR_PROXY and JP225_USD_PROXY are provider-defined research price proxies, not executable contract-level futures.",
            "DAX/Nikkei execution costs are exploratory placeholders, not contract-level fee, roll, basis, or financing models.",
            "No final holdout was opened.",
        ],
        "data_audit": audits,
        "phase2": {
            "per_instrument": phase2,
            "supplemental_ml4t_panel_mom60": panel_diagnostic(list(features.values())),
        },
        "phase3": phase3,
        "summary": summary,
    }
    print("RESULT_JSON_BEGIN")
    print(json.dumps(_jsonable(result), sort_keys=True))
    print("RESULT_JSON_END")


if __name__ == "__main__":
    main()
