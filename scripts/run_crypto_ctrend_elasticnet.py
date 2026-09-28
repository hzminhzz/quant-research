#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import json
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
from scipy import stats
from sklearn.linear_model import ElasticNetCV

from ml4t.engineer import compute_features
from src.experiment import compute_deflated_sharpe

FEATURES = (
    "boll_mid_dist",
    "cci20_rank",
    "macd_norm_rank",
    "macd_signal_diff_rank",
    "sma5_dist",
    "boll_upper_dist",
    "sma3_dist",
    "stochk_rank",
)
COST = 10.0
TOPN = 50
TRAIN_WEEKS = 52
EMBARGO_WEEKS = 1
MIN_TRAIN_WEEKS = 40
MIN_XS = 10
DEV0 = date(2022, 1, 1)
DEV1 = date(2024, 1, 1)
OOS0 = date(2024, 1, 1)
OOS1 = date(2026, 1, 1)


def load_daily(root: Path) -> pl.DataFrame:
    manifest = json.load(open(root / "dataset_manifest.json"))
    frames = []
    for symbol, meta in manifest["symbol_summaries"].items():
        if not symbol.endswith("USDT") or symbol == "BTCDOMUSDT":
            continue
        paths = glob.glob(str(root / f"symbol={symbol}" / "year=*" / "month=*" / "data.parquet"))
        if not paths:
            continue
        x = (
            pl.scan_parquet(paths, hive_partitioning=False)
            .filter(pl.col("timestamp") < pl.datetime(2026, 1, 8, time_zone="UTC"))
            .select("timestamp", "open", "high", "low", "close", "volume", "quote_volume")
            .collect()
            .sort("timestamp")
        )
        if x.height < 24 * 120:
            continue
        d = (
            x.with_columns(pl.col("timestamp").dt.date().alias("date"))
            .group_by("date")
            .agg(
                pl.col("open").first().alias("open"),
                pl.col("high").max().alias("high"),
                pl.col("low").min().alias("low"),
                pl.col("close").last().alias("close"),
                pl.col("volume").sum().alias("volume"),
                pl.col("quote_volume").sum().alias("qv"),
                pl.len().alias("hours"),
            )
            .filter(pl.col("hours") == 24)
            .drop("hours")
            .sort("date")
            .with_columns(pl.lit(symbol).alias("symbol"))
        )
        if d.height >= 120:
            frames.append(d)
    if not frames:
        raise RuntimeError("no daily data loaded")
    return pl.concat(frames, how="vertical").sort(["symbol", "date"])


def engineer_features(daily: pl.DataFrame) -> pl.DataFrame:
    base = daily.with_columns(pl.col("date").cast(pl.Datetime).alias("timestamp"))
    specs = [
        {"name": "sma", "params": {"period": 3}, "output": "sma3"},
        {"name": "sma", "params": {"period": 5}, "output": "sma5"},
        {"name": "cci", "params": {"period": 20}, "output": "cci20"},
        {"name": "macd", "params": {"fast_period": 12, "slow_period": 26}, "output": "macd"},
        {
            "name": "stochastic",
            "params": {"fastk_period": 14, "slowk_period": 1, "slowd_period": 3, "return_pair": False},
            "output": "stochk",
        },
        {
            "name": "bollinger_bands",
            "params": {"period": 20, "nbdevup": 2.0, "nbdevdn": 2.0},
            "output": "boll",
        },
    ]
    x = compute_features(
        base,
        specs,
        group_col="symbol",
        timestamp_col="timestamp",
    ).sort(["symbol", "date"])
    x = x.with_columns(
        pl.col("macd").fill_nan(None).ewm_mean(span=9, adjust=False).over("symbol").alias("_macd_signal"),
        pl.col("qv").shift(1).rolling_sum(30).over("symbol").alias("_liq"),
        pl.col("date").shift(90).over("symbol").alias("_anchor90"),
    )
    x = x.with_columns(
        (pl.col("close") / pl.col("boll").struct.field("middle") - 1.0).alias("_boll_mid"),
        pl.col("cci20").alias("_cci"),
        (pl.col("macd") / pl.col("close")).alias("_macd_norm"),
        ((pl.col("macd") - pl.col("_macd_signal")) / pl.col("close")).alias("_macd_sig_diff"),
        (pl.col("close") / pl.col("sma5") - 1.0).alias("_sma5"),
        (pl.col("close") / pl.col("boll").struct.field("upper") - 1.0).alias("_boll_upper"),
        (pl.col("close") / pl.col("sma3") - 1.0).alias("_sma3"),
        (pl.col("stochk") / 100.0).alias("_stoch"),
    )
    # Monday decision uses only values through Sunday close.
    x = x.with_columns(
        pl.col("_boll_mid").shift(1).over("symbol").alias("_f0"),
        pl.col("_cci").shift(1).over("symbol").alias("_f1"),
        pl.col("_macd_norm").shift(1).over("symbol").alias("_f2"),
        pl.col("_macd_sig_diff").shift(1).over("symbol").alias("_f3"),
        pl.col("_sma5").shift(1).over("symbol").alias("_f4"),
        pl.col("_boll_upper").shift(1).over("symbol").alias("_f5"),
        pl.col("_sma3").shift(1).over("symbol").alias("_f6"),
        pl.col("_stoch").shift(1).over("symbol").alias("_f7"),
    )
    mondays = x.filter(
        (pl.col("date").dt.weekday() == 1)
        & pl.col("_liq").is_finite()
        & (pl.col("_anchor90") == pl.col("date") - pl.duration(days=90))
        & pl.all_horizontal([pl.col(f"_f{i}").is_finite() for i in range(8)])
    )
    out = []
    for part in mondays.partition_by("date", maintain_order=True):
        part = part.sort("_liq", descending=True).head(TOPN)
        n = part.height
        if n < MIN_XS:
            continue
        exprs = []
        for i, name in enumerate(FEATURES):
            exprs.append(
                ((pl.col(f"_f{i}").rank(method="average") - 0.5) / n - 0.5).alias(name)
            )
        out.append(part.with_columns(exprs).select("date", "symbol", "_liq", *FEATURES))
    if not out:
        raise RuntimeError("no Monday feature rows")
    return pl.concat(out, how="vertical").sort(["date", "symbol"])


def weekly_return_map(daily: pl.DataFrame) -> dict[tuple[date, str], float]:
    out: dict[tuple[date, str], float] = {}
    for part in daily.partition_by("symbol", maintain_order=True):
        symbol = str(part["symbol"][0])
        rows = part.select("date", "open", "close").sort("date").to_dicts()
        index = {r["date"]: i for i, r in enumerate(rows)}
        for d, i in index.items():
            if d.weekday() != 0:
                continue
            end = d + timedelta(days=7)
            entry = float(rows[i]["open"])
            if end in index:
                exit_px = float(rows[index[end]]["open"])
            else:
                candidates = [r for r in rows[i:] if r["date"] < end]
                if not candidates:
                    continue
                exit_px = float(candidates[-1]["close"])
            if entry > 0 and exit_px > 0:
                out[(d, symbol)] = exit_px / entry - 1.0
    return out


def make_model_rows(frame: pl.DataFrame, returns: dict[tuple[date, str], float]) -> pl.DataFrame:
    rows = []
    for r in frame.iter_rows(named=True):
        key = (r["date"], str(r["symbol"]))
        y = returns.get(key)
        if y is None or not np.isfinite(y):
            continue
        rows.append({**r, "target": float(y)})
    if not rows:
        raise RuntimeError("no labeled rows")
    return pl.DataFrame(rows).sort(["date", "symbol"])


def cv_splits(train: pl.DataFrame) -> list[tuple[np.ndarray, np.ndarray]]:
    weeks = sorted(train["date"].unique().to_list())
    if len(weeks) < 24:
        return []
    # Four expanding chronological folds preserving whole weeks.
    starts = [int(len(weeks) * q) for q in (0.45, 0.58, 0.71, 0.84)]
    splits = []
    dates = train["date"].to_numpy()
    for start in starts:
        stop = min(len(weeks), start + max(4, len(weeks) // 10))
        if start < 16 or stop <= start:
            continue
        tr_weeks = set(weeks[:start])
        va_weeks = set(weeks[start:stop])
        tr = np.flatnonzero(np.isin(dates, list(tr_weeks)))
        va = np.flatnonzero(np.isin(dates, list(va_weeks)))
        if len(tr) and len(va):
            splits.append((tr, va))
    return splits


def rolling_predictions(
    feature_rows: pl.DataFrame,
    labeled_rows: pl.DataFrame,
    start: date,
    end: date,
) -> pl.DataFrame:
    outputs = []
    decision_weeks = sorted(
        feature_rows.filter((pl.col("date") >= start) & (pl.col("date") < end))["date"].unique().to_list()
    )
    for d in decision_weeks:
        train_end = d - timedelta(days=7 * EMBARGO_WEEKS)
        eligible = labeled_rows.filter(pl.col("date") <= train_end)
        weeks = sorted(eligible["date"].unique().to_list())
        if len(weeks) < MIN_TRAIN_WEEKS:
            continue
        keep_weeks = weeks[-TRAIN_WEEKS:]
        train = eligible.filter(pl.col("date").is_in(keep_weeks)).sort(["date", "symbol"])
        current = feature_rows.filter(pl.col("date") == d).sort("symbol")
        if train.height < 200 or current.height < MIN_XS:
            continue
        splits = cv_splits(train)
        if len(splits) < 3:
            continue
        X = train.select(FEATURES).to_numpy().astype(float)
        y = train["target"].to_numpy().astype(float)
        model = ElasticNetCV(
            l1_ratio=[0.1, 0.5, 0.9],
            alphas=np.logspace(-5, -2, 7),
            cv=splits,
            fit_intercept=True,
            max_iter=5000,
            tol=1e-5,
        )
        model.fit(X, y)
        pred = model.predict(current.select(FEATURES).to_numpy().astype(float))
        outputs.append(
            current.select("date", "symbol").with_columns(
                pl.Series("prediction", pred),
                pl.lit(float(model.alpha_)).alias("selected_alpha"),
                pl.lit(float(model.l1_ratio_)).alias("selected_l1_ratio"),
                pl.lit(int(len(keep_weeks))).alias("train_weeks"),
            )
        )
    if not outputs:
        return pl.DataFrame()
    return pl.concat(outputs, how="vertical").sort(["date", "symbol"])


def hac_mean_test(values: np.ndarray, max_lag: int = 4) -> tuple[float, float]:
    if len(values) < 8:
        return 0.0, 1.0
    centered = values - values.mean()
    n = len(values)
    lrv = float(np.dot(centered, centered) / n)
    for lag in range(1, min(max_lag, n - 1) + 1):
        gamma = float(np.dot(centered[lag:], centered[:-lag]) / n)
        lrv += 2.0 * (1.0 - lag / (max_lag + 1.0)) * gamma
    if lrv <= 0:
        return 0.0, 1.0
    t = float(values.mean() / math.sqrt(lrv / n))
    return t, float(2.0 * stats.norm.sf(abs(t)))


def diagnostics(pred: pl.DataFrame, returns: dict[tuple[date, str], float]) -> dict:
    ics, spreads = [], []
    for part in pred.partition_by("date", maintain_order=True):
        d = part["date"][0]
        rows = [(float(r["prediction"]), returns.get((d, str(r["symbol"])))) for r in part.iter_rows(named=True)]
        rows = [(p, float(y)) for p, y in rows if y is not None and np.isfinite(y)]
        if len(rows) < MIN_XS:
            continue
        p = np.array([x[0] for x in rows])
        y = np.array([x[1] for x in rows])
        ic = float(stats.spearmanr(p, y).statistic)
        if np.isfinite(ic):
            ics.append(ic)
        order = np.argsort(p)
        k = max(2, len(order) // 5)
        spreads.append(float(y[order[-k:]].mean() - y[order[:k]].mean()))
    arr = np.asarray(ics, dtype=float)
    t, pval = hac_mean_test(arr)
    return {
        "n_weeks": int(len(arr)),
        "mean_ic": float(arr.mean()) if len(arr) else 0.0,
        "ic_ir": float(arr.mean() / arr.std(ddof=1)) if len(arr) > 1 and arr.std(ddof=1) > 0 else 0.0,
        "hac_t": t,
        "hac_p": pval,
        "winner_minus_loser": float(np.mean(spreads)) if spreads else 0.0,
    }


def build_targets(pred: pl.DataFrame, exclude: set[str] | None = None) -> dict[date, dict[str, float]]:
    exclude = exclude or set()
    out = {}
    for part in pred.partition_by("date", maintain_order=True):
        rows = sorted(
            [(str(r["symbol"]), float(r["prediction"])) for r in part.iter_rows(named=True) if str(r["symbol"]) not in exclude],
            key=lambda z: z[1],
        )
        if len(rows) < MIN_XS:
            continue
        k = max(2, len(rows) // 5)
        w = {}
        for s, _ in rows[:k]:
            w[s] = -0.5 / k
        for s, _ in rows[-k:]:
            w[s] = 0.5 / k
        out[part["date"][0]] = w
    return out


def simulate(
    targets: dict[date, dict[str, float]],
    returns: dict[tuple[date, str], float],
    start: date,
    end: date,
    cost_bps: float,
) -> dict:
    prev: dict[str, float] = {}
    rr: list[tuple[date, float]] = []
    contribution: dict[str, float] = {}
    turns = []
    for d in sorted(k for k in targets if start <= k < end):
        w = targets[d]
        turn = sum(abs(w.get(s, 0.0) - prev.get(s, 0.0)) for s in set(w) | set(prev))
        gross = 0.0
        for s, weight in w.items():
            ret = returns.get((d, s))
            if ret is not None:
                gross += weight * ret
                contribution[s] = contribution.get(s, 0.0) + weight * ret
        rr.append((d, gross - turn * cost_bps / 10000.0))
        turns.append(turn)
        prev = w
    if not rr:
        return {"metrics": {"annualized_sharpe": 0.0, "total_return": 0.0, "max_drawdown": 0.0, "n_weeks": 0}}
    a = np.array([r for _, r in rr], dtype=float)
    eq = np.cumprod(1.0 + a)
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1.0
    sd = float(np.std(a, ddof=1))
    by_year = {}
    for year in sorted({d.year for d, _ in rr}):
        q = np.array([r for d, r in rr if d.year == year], dtype=float)
        qs = float(np.std(q, ddof=1)) if len(q) > 1 else 0.0
        by_year[str(year)] = {
            "total_return": float(np.prod(1.0 + q) - 1.0),
            "sharpe": float(np.mean(q) / qs * math.sqrt(52.0)) if qs > 0 else 0.0,
        }
    return {
        "metrics": {
            "annualized_sharpe": float(np.mean(a) / sd * math.sqrt(52.0)) if sd > 0 else 0.0,
            "total_return": float(eq[-1] - 1.0),
            "max_drawdown": float(dd.min()),
            "n_weeks": int(len(a)),
            "turnover": float(sum(turns)),
        },
        "by_year": by_year,
        "asset_contribution": contribution,
    }


def hyperparameter_summary(pred: pl.DataFrame) -> dict:
    if pred.height == 0:
        return {}
    return {
        "alpha_counts": pred.group_by("selected_alpha").len().sort("selected_alpha").to_dicts(),
        "l1_ratio_counts": pred.group_by("selected_l1_ratio").len().sort("selected_l1_ratio").to_dicts(),
    }


def emit_result(out: dict, output: Path | None) -> None:
    payload = json.dumps(out, indent=2, default=str)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n")
    print(payload)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()

    daily = load_daily(args.root)
    feat = engineer_features(daily)
    retmap = weekly_return_map(daily)
    labeled = make_model_rows(feat, retmap)

    dev_pred = rolling_predictions(feat, labeled, DEV0, DEV1)
    dev_diag = diagnostics(dev_pred, retmap)
    dev = simulate(build_targets(dev_pred), retmap, DEV0, DEV1, COST)
    dm = dev["metrics"]
    dev_gate = (
        dev_diag["n_weeks"] >= 40
        and dev_diag["mean_ic"] >= 0.02
        and dev_diag["hac_p"] < 0.05
        and dev_diag["winner_minus_loser"] > 0
        and dm["annualized_sharpe"] > 0.70
        and dm["total_return"] > 0
    )
    out = {
        "schema_version": 1,
        "run_id": "20260928-ctrend-rolling-elasticnet",
        "universe_symbols": int(daily["symbol"].n_unique()),
        "feature_rows": int(feat.height),
        "development_diagnostics": dev_diag,
        "development": dev,
        "development_hyperparameters": hyperparameter_summary(dev_pred),
        "development_gate_passed": dev_gate,
        "oos_consumed": False,
        "trial_accounting": {
            "previous_parameter_trials": 86,
            "new_external_parameter_trials": 1,
            "cumulative_parameter_trials": 87,
            "internal_cv_grid": "3 l1 ratios x 7 alphas selected entirely inside each rolling training window",
        },
    }
    if not dev_gate:
        out.update(
            classification="REJECT",
            success_gate_candidate=False,
            conclusion="Rolling development gate failed; OOS not consumed.",
        )
        emit_result(out, args.output)
        return 0

    oos_pred = rolling_predictions(feat, labeled, OOS0, OOS1)
    oos_diag = diagnostics(oos_pred, retmap)
    targets = build_targets(oos_pred)
    costs = {str(m): simulate(targets, retmap, OOS0, OOS1, COST * m) for m in (1, 2, 3)}
    base = costs["1"]
    bm = base["metrics"]
    exclude_btc_eth = simulate(build_targets(oos_pred, {"BTCUSDT", "ETHUSDT"}), retmap, OOS0, OOS1, COST)
    strongest = (
        max(base["asset_contribution"], key=lambda s: abs(base["asset_contribution"][s]))
        if base.get("asset_contribution")
        else None
    )
    exclude_strongest = (
        simulate(build_targets(oos_pred, {strongest}), retmap, OOS0, OOS1, COST)
        if strongest
        else None
    )
    years_ok = all(base["by_year"].get(str(y), {}).get("total_return", -1.0) >= 0 for y in (2024, 2025))
    global_dsr = compute_deflated_sharpe(
        float(bm["annualized_sharpe"]),
        [float(bm["annualized_sharpe"])] + [0.0] * 86,
        n_obs_days=max(int(bm["n_weeks"]) * 7, 1),
    )
    dsr_prob = float(global_dsr.get("dsr_probability", 0.0))
    qualifies = (
        bm["annualized_sharpe"] > 1.0
        and oos_diag["mean_ic"] >= 0.02
        and oos_diag["hac_p"] < 0.05
        and costs["2"]["metrics"]["total_return"] > 0
        and years_ok
        and bm["max_drawdown"] > -0.35
        and exclude_btc_eth["metrics"]["total_return"] > 0
        and (exclude_strongest is None or exclude_strongest["metrics"]["total_return"] > 0)
        and dsr_prob >= 0.95
    )
    out.update(
        oos_consumed=True,
        oos_diagnostics=oos_diag,
        oos_results=costs,
        oos_hyperparameters=hyperparameter_summary(oos_pred),
        exclude_btc_eth=exclude_btc_eth,
        strongest_asset=strongest,
        exclude_strongest=exclude_strongest,
        multiple_testing={
            "global_87_trial_proxy": global_dsr,
            "pbo": "N/A: one externally preregistered ML specification; hyperparameters nested inside rolling training only",
        },
        success_gate_candidate=qualifies,
        classification="EXPLORATORY_PASS" if qualifies else "REJECT",
    )
    emit_result(out, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
