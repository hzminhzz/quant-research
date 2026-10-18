"""G5 — purged walk-forward with the source's model class.

The source deliberately uses expanding annual windows with **no purge** because it
argues the 21-day target makes the leak minor. This gate re-runs the identical
model with a 21-day purge at the train/test boundary and reports how much of the
edge was boundary leakage.

Also reports the `lag1` execution convention (signal at close(t), entry at
close(t+1)) so the G2 decision/entry coincidence is priced.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "upstream"))

from mlcs.features import add_forward_target, build_feature_panel
from mlcs.model import EqualWeightBaseline, XGBRankerModel
from qtools.backtest.costs import CRYPTO
from qtools.backtest.engine import BacktestEngine
from qtools.backtest.portfolio import signal_to_weights
from qtools.metrics.performance import (
    annualized_return,
    max_drawdown,
    sharpe,
)

FEATURES = [
    "mom_12_1", "reversal_1w", "size_adv_60",
    "ret_21d", "ret_63d", "ret_126d", "ret_252d",
    "vol_20d", "vol_60d",
    "rsi_14", "macd_hist", "volume_z_60",
]
TARGET = "fwd_rank_21d"
HORIZON = 21
OOS_YEARS = (2022, 2023, 2024)
PURGE_DAYS = HORIZON          # 21 trading days of label overlap removed from train


def _n_eff(ic: pd.Series, max_lag: int = HORIZON) -> float:
    x = ic.to_numpy(dtype=float)
    n = len(x)
    if n < max_lag + 2:
        return float(n)
    xc = x - x.mean()
    denom = float(np.dot(xc, xc))
    if denom == 0:
        return float(n)
    rho = sum(float(np.dot(xc[:-k], xc[k:]) / denom) for k in range(1, max_lag + 1))
    factor = 1.0 + 2.0 * rho
    return float(n / factor) if factor > 0 else float(n)


def _hac_t(ic: pd.Series, max_lag: int = HORIZON) -> float:
    x = ic.to_numpy(dtype=float)
    n = len(x)
    if n < max_lag + 2:
        return float("nan")
    xc = x - x.mean()
    var = float(np.dot(xc, xc) / n)
    for k in range(1, max_lag + 1):
        gk = float(np.dot(xc[:-k], xc[k:]) / n)
        var += 2.0 * (1.0 - k / (max_lag + 1.0)) * gk
    if var <= 0:
        return float("nan")
    return float(x.mean() / np.sqrt(var / n))


def _per_date_ic(sub: pd.DataFrame, col: str) -> float:
    sub = sub[[col, TARGET]].dropna()
    if len(sub) < 5:
        return float("nan")
    return float(sub[col].rank().corr(sub[TARGET]))


def _ic_stats(preds: pd.DataFrame, col: str = "score") -> dict:
    ics = []
    for _, g in preds.groupby("date", sort=True):
        v = _per_date_ic(g, col)
        if not np.isnan(v):
            ics.append(v)
    s = pd.Series(ics, dtype="float64")
    return {
        "mean_ic": float(s.mean()),
        "ic_ir": float(s.mean() / s.std()) if s.std() > 0 else float("nan"),
        "t_hac": _hac_t(s),
        "t_naive": float(s.mean() / s.std() * np.sqrt(len(s))) if s.std() > 0 else float("nan"),
        "n_dates": len(s),
        "n_eff": _n_eff(s),
        "hit_rate": float((s > 0).mean()),
    }


def _backtest(preds: pd.DataFrame, prices: pd.DataFrame, model: str, shift_days: int = 0) -> dict:
    g = preds[preds["model"] == model]
    sig = g.pivot(index="date", columns="symbol", values="score").sort_index()
    if shift_days:
        # entry one bar later than the source convention
        sig = sig.shift(shift_days).dropna(how="all")
    w = signal_to_weights(sig, n_quantiles=5, long_short=True, rebalance="ME")
    res = BacktestEngine(prices[["date", "symbol", "close"]], cost_model=CRYPTO).run(w)
    t = res.turnover[res.turnover > 0]
    return {
        "ann_net": float(annualized_return(res.returns)),
        "sharpe_net": float(sharpe(res.returns)),
        "sharpe_gross": float(sharpe(res.gross_returns)),
        "mdd_net": float(max_drawdown(res.returns)),
        "mean_turnover": float(t.mean()) if len(t) else float("nan"),
        "cost_drag_ann": float(res.costs.mean() * 252),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "purged_output"))
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    prices = pd.read_parquet(HERE / "repro_output" / "btc_uni_prices.parquet")
    prices["date"] = pd.to_datetime(prices["date"])
    close = prices.pivot(index="date", columns="symbol", values="close").sort_index()
    volume = prices.pivot(index="date", columns="symbol", values="volume").sort_index()

    feats = build_feature_panel(close, volume)
    feats = add_forward_target(feats, close, horizon=HORIZON).dropna(subset=[TARGET])
    feats["date"] = pd.to_datetime(feats["date"])
    feats["year"] = feats["date"].dt.year

    rows = []
    preds_all = []
    for purge in (0, PURGE_DAYS):
        tag = "unpurged_source" if purge == 0 else f"purged_{purge}d"
        for oos_year in OOS_YEARS:
            boundary = pd.Timestamp(f"{oos_year}-01-01")
            train_cut = boundary - pd.Timedelta(days=0)
            tr = feats[feats["date"] < train_cut]
            if purge:
                # remove the last `purge` distinct trading dates so no training row's
                # 21-day label window overlaps the test period
                trail = np.sort(tr["date"].unique())[-purge:]
                tr = tr[~tr["date"].isin(trail)]
            te = feats[feats["year"] == oos_year]
            if tr.empty or te.empty:
                continue
            for mdl in [
                XGBRankerModel(n_estimators=200, max_depth=4, learning_rate=0.05, random_state=42),
                EqualWeightBaseline(),
            ]:
                mdl.fit(tr[FEATURES], tr[TARGET], tr["date"])
                te_local = te.copy()
                te_local["score"] = mdl.predict(te_local[FEATURES], te_local["date"])
                te_local["model"] = mdl.name
                te_local["variant"] = tag
                preds_all.append(te_local[["date", "symbol", TARGET, "score", "model", "variant"]])
                stats = _ic_stats(te_local, "score")
                rows.append({"variant": tag, "purge_days": purge, "oos_year": oos_year,
                             "model": mdl.name, **stats})

    per_year = pd.DataFrame(rows)
    per_year.to_csv(out / "purged_ic_by_year.csv", index=False)

    preds = pd.concat(preds_all, ignore_index=True)
    preds.to_parquet(out / "purged_oos_predictions.parquet", index=False)

    pooled = []
    for (tag, model), g in preds.groupby(["variant", "model"]):
        stats = _ic_stats(g, "score")
        bt = _backtest(preds[preds["variant"] == tag], prices, model, shift_days=0)
        bt_lag = _backtest(preds[preds["variant"] == tag], prices, model, shift_days=1)
        pooled.append({
            "variant": tag, "model": model, **stats,
            "ann_net": bt["ann_net"], "sharpe_net": bt["sharpe_net"],
            "mdd_net": bt["mdd_net"], "mean_turnover": bt["mean_turnover"],
            "cost_drag_ann": bt["cost_drag_ann"],
            "sharpe_net_lag1": bt_lag["sharpe_net"], "ann_net_lag1": bt_lag["ann_net"],
            "delta_sharpe_from_lag1": bt_lag["sharpe_net"] - bt["sharpe_net"],
        })
    pooled_tbl = pd.DataFrame(pooled).sort_values(["model", "variant"]).reset_index(drop=True)
    pooled_tbl.to_csv(out / "purged_pooled.csv", index=False)

    print("=== G5 per-year OOS IC (XGB) ===")
    print(per_year[per_year.model == "xgb_ranker"].to_string(index=False))
    print("\n=== G5 pooled OOS, purged vs source convention, and lag1 execution ===")
    print(pooled_tbl.to_string(index=False))

    xgb = pooled_tbl[pooled_tbl.model == "xgb_ranker"].set_index("variant")
    verdict = {
        "gate": "G5",
        "purge_days": PURGE_DAYS,
        "xgb_unpurged_ic_ir": float(xgb.loc["unpurged_source", "ic_ir"]),
        "xgb_purged_ic_ir": float(xgb.loc[f"purged_{PURGE_DAYS}d", "ic_ir"]),
        "xgb_unpurged_sharpe": float(xgb.loc["unpurged_source", "sharpe_net"]),
        "xgb_purged_sharpe": float(xgb.loc[f"purged_{PURGE_DAYS}d", "sharpe_net"]),
        "xgb_purged_hac_t": float(xgb.loc[f"purged_{PURGE_DAYS}d", "t_hac"]),
        "xgb_purged_n_eff": float(xgb.loc[f"purged_{PURGE_DAYS}d", "n_eff"]),
        "xgb_purged_sharpe_lag1": float(xgb.loc[f"purged_{PURGE_DAYS}d", "sharpe_net_lag1"]),
    }
    (out / "verdict.json").write_text(json.dumps(verdict, indent=2), encoding="utf-8")
    print("\n=== G5 verdict ===")
    print(json.dumps(verdict, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
