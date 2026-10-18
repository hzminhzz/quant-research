"""G3/G4 — signal before model, then cost ceiling.

Measures the twelve source features directly against forward returns, with no
model in the loop: per-feature IC and IC-IR, IC decay across horizons, monthly
quintile spread, turnover, effective sample size, and the cost ceiling implied
by the source's own CRYPTO cost model.

Two execution conventions are reported side by side:
  source   — signal at close(t), entry at close(t)      (the source's convention)
  lag1     — signal at close(t), entry at close(t+1)    (tradeable convention)
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

from mlcs.features import build_feature_panel
from qtools.utils.dates import resample_to_last

FEATURES = [
    "mom_12_1", "reversal_1w", "size_adv_60",
    "ret_21d", "ret_63d", "ret_126d", "ret_252d",
    "vol_20d", "vol_60d",
    "rsi_14", "macd_hist", "volume_z_60",
]
HORIZONS = [1, 5, 21, 63]
OOS_START, OOS_END = "2022-01-01", "2024-12-31"
COST_BPS_ONE_WAY = 10.0        # qtools CRYPTO = 5 commission + 5 slippage
N_QUANTILES = 5


def _ic_series(df: pd.DataFrame, feat: str, fwd: str) -> pd.Series:
    """Per-date Spearman IC, min 5 names (same rule as the source)."""
    out = {}
    for d, g in df.groupby("date", sort=True):
        sub = g[[feat, fwd]].dropna()
        if len(sub) < 5:
            continue
        out[d] = sub[feat].rank().corr(sub[fwd].rank())
    s = pd.Series(out, dtype="float64").dropna()
    return s.sort_index()


def _n_eff(ic: pd.Series, max_lag: int = 21) -> float:
    """n / (1 + 2*sum(rho_k)) over lags 1..max_lag (overlapping-label correction)."""
    x = ic.to_numpy(dtype=float)
    n = len(x)
    if n < max_lag + 2:
        return float(n)
    x = x - x.mean()
    denom = float(np.dot(x, x))
    if denom == 0:
        return float(n)
    rho = 0.0
    for k in range(1, max_lag + 1):
        rho += float(np.dot(x[:-k], x[k:]) / denom)
    factor = 1.0 + 2.0 * rho
    return float(n / factor) if factor > 0 else float(n)


def _hac_t(ic: pd.Series, max_lag: int = 21) -> float:
    """Newey-West t-stat on the IC mean; fallback to naive if degenerate."""
    x = ic.to_numpy(dtype=float)
    n = len(x)
    if n < max_lag + 2:
        return float("nan")
    xc = x - x.mean()
    gamma0 = float(np.dot(xc, xc) / n)
    var = gamma0
    for k in range(1, max_lag + 1):
        gk = float(np.dot(xc[:-k], xc[k:]) / n)
        var += 2.0 * (1.0 - k / (max_lag + 1.0)) * gk
    if var <= 0:
        return float("nan")
    return float(x.mean() / np.sqrt(var / n))


def _quintile_spread(df: pd.DataFrame, feat: str, fwd: str, dates: pd.DatetimeIndex) -> dict:
    """Month-end quintile long-short spread in forward-return units, plus turnover.

    Turnover follows qtools exactly: sum(|dW|)/2 over SYMBOLS, with the long leg
    carrying +1/n_top and the short leg -1/n_bot (gross = 2, dollar-neutral).
    """
    spreads = []
    prev_w: dict[str, float] = {}
    turnovers = []
    for d in dates:
        g = df.loc[df["date"] == d, ["symbol", feat, fwd]].dropna()
        if len(g) < N_QUANTILES * 2:
            continue
        r = g[feat].rank(pct=True, method="first")
        top = g[r > 1 - 1 / N_QUANTILES]
        bot = g[r <= 1 / N_QUANTILES]
        if top.empty or bot.empty:
            continue
        spreads.append(top[fwd].mean() - bot[fwd].mean())
        w: dict[str, float] = {}
        for sym in top["symbol"]:
            w[sym] = w.get(sym, 0.0) + 1.0 / len(top)
        for sym in bot["symbol"]:
            w[sym] = w.get(sym, 0.0) - 1.0 / len(bot)
        if prev_w:
            keys = set(w) | set(prev_w)
            turnovers.append(sum(abs(w.get(k, 0.0) - prev_w.get(k, 0.0)) for k in keys) / 2.0)
        prev_w = w
    if not spreads:
        return {}
    s = pd.Series(spreads, dtype="float64")
    return {
        "n_rebalances": len(s),
        "mean_spread_21d": float(s.mean()),
        "std_spread_21d": float(s.std()),
        "t_spread": float(s.mean() / s.std() * np.sqrt(len(s))) if s.std() > 0 else float("nan"),
        "ann_spread_gross": float(s.mean() * 12),
        "mean_turnover_oneway": float(np.mean(turnovers)) if turnovers else float("nan"),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "signal_output"))
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    prices = pd.read_parquet(HERE / "repro_output" / "btc_uni_prices.parquet")
    prices["date"] = pd.to_datetime(prices["date"])
    close = prices.pivot(index="date", columns="symbol", values="close").sort_index()
    volume = prices.pivot(index="date", columns="symbol", values="volume").sort_index()

    feats = build_feature_panel(close, volume)
    feats["date"] = pd.to_datetime(feats["date"])

    # forward returns under both conventions, for each horizon
    for h in HORIZONS:
        src = (close.shift(-h) / close - 1).stack().rename(f"fwd_{h}_src")
        lag = (close.shift(-h - 1) / close.shift(-1) - 1).stack().rename(f"fwd_{h}_lag1")
        src.index.names = lag.index.names = ["date", "symbol"]
        feats = feats.merge(src.reset_index(), on=["date", "symbol"], how="left")
        feats = feats.merge(lag.reset_index(), on=["date", "symbol"], how="left")

    oos = feats[(feats["date"] >= OOS_START) & (feats["date"] <= OOS_END)].copy()
    print(f"OOS feature rows: {len(oos):,}, dates: {oos['date'].nunique()}, symbols: {oos['symbol'].nunique()}")

    # ---- G3a: per-feature IC on the source horizon, both conventions --------
    rows = []
    for f in FEATURES:
        rec = {"feature": f}
        for tag in ("src", "lag1"):
            ic = _ic_series(oos, f, f"fwd_21_{tag}")
            n_eff = _n_eff(ic)
            rec[f"mean_ic_{tag}"] = float(ic.mean())
            rec[f"ic_ir_{tag}"] = float(ic.mean() / ic.std()) if ic.std() > 0 else float("nan")
            rec[f"t_hac_{tag}"] = _hac_t(ic)
            rec[f"t_naive_{tag}"] = float(ic.mean() / ic.std() * np.sqrt(len(ic))) if ic.std() > 0 else float("nan")
            rec[f"n_dates_{tag}"] = len(ic)
            rec[f"n_eff_{tag}"] = n_eff
            rec[f"hit_{tag}"] = float((ic > 0).mean())
        rows.append(rec)
    ic_tbl = pd.DataFrame(rows).sort_values("ic_ir_src", ascending=False)
    ic_tbl.to_csv(out / "feature_ic.csv", index=False)
    print("\n=== G3 per-feature IC, OOS 2022-2024, horizon 21 ===")
    print(ic_tbl[["feature", "mean_ic_src", "ic_ir_src", "t_hac_src", "t_naive_src",
                  "n_dates_src", "n_eff_src", "ic_ir_lag1", "t_hac_lag1"]].to_string(index=False))

    # ---- G3b: IC decay ------------------------------------------------------
    decay = []
    for f in FEATURES:
        rec = {"feature": f}
        for h in HORIZONS:
            ic = _ic_series(oos, f, f"fwd_{h}_src")
            rec[f"ic_h{h}"] = float(ic.mean())
            rec[f"ir_h{h}"] = float(ic.mean() / ic.std()) if ic.std() > 0 else float("nan")
        decay.append(rec)
    decay_tbl = pd.DataFrame(decay)
    decay_tbl.to_csv(out / "ic_decay.csv", index=False)
    print("\n=== G3 IC decay (mean IC by horizon) ===")
    print(decay_tbl.to_string(index=False))

    # ---- G3c/G4: quintile spread, turnover, cost ceiling -------------------
    all_dates = pd.DatetimeIndex(sorted(pd.to_datetime(oos["date"].unique())))
    me_dates = resample_to_last(all_dates, "ME")
    spread_rows = []
    for f in FEATURES:
        rec = {"feature": f}
        for tag in ("src", "lag1"):
            q = _quintile_spread(oos, f, f"fwd_21_{tag}", me_dates)
            for k, v in q.items():
                rec[f"{k}_{tag}"] = v
        # G4 cost ceiling: annual cost = 12 rebalances * turnover(gross=2) * 2 legs * 10bps
        t = rec.get("mean_turnover_oneway_src", float("nan"))
        rec["ann_cost_bps"] = 12 * t * 2 * COST_BPS_ONE_WAY
        rec["ann_spread_bps_gross"] = rec.get("ann_spread_gross_src", float("nan")) * 1e4
        rec["ann_net_bps"] = rec["ann_spread_bps_gross"] - rec["ann_cost_bps"]
        spread_rows.append(rec)
    spread_tbl = pd.DataFrame(spread_rows).sort_values("ann_net_bps", ascending=False)
    spread_tbl.to_csv(out / "quintile_spread.csv", index=False)
    spread_tbl["ann_spread_bps_gross_lag1"] = spread_tbl["ann_spread_gross_lag1"] * 1e4
    spread_tbl["ann_cost_bps_lag1"] = 12 * spread_tbl["mean_turnover_oneway_lag1"] * 2 * COST_BPS_ONE_WAY
    spread_tbl["ann_net_bps_lag1"] = (
        spread_tbl["ann_spread_bps_gross_lag1"] - spread_tbl["ann_cost_bps_lag1"]
    )
    spread_tbl = spread_tbl.sort_values("ann_net_bps", ascending=False).reset_index(drop=True)
    spread_tbl.to_csv(out / "quintile_spread.csv", index=False)
    print("\n=== G3c/G4 month-end quintile spread and cost ceiling ===")
    cols = ["feature", "mean_spread_21d_src", "t_spread_src", "mean_turnover_oneway_src",
            "ann_spread_bps_gross", "ann_cost_bps", "ann_net_bps",
            "ann_spread_bps_gross_lag1", "ann_cost_bps_lag1", "ann_net_bps_lag1"]
    print(spread_tbl[cols].to_string(index=False))

    # ---- verdict records ---------------------------------------------------
    best = spread_tbl.iloc[0]
    verdict = {
        "gate": "G3/G4",
        "oos_window": [OOS_START, OOS_END],
        "n_dates": int(oos["date"].nunique()),
        "n_symbols": int(oos["symbol"].nunique()),
        "horizon_bars": 21,
        "cost_bps_one_way": COST_BPS_ONE_WAY,
        "max_n_eff": float(ic_tbl["n_eff_src"].max()),
        "features_with_positive_ic": int((ic_tbl["mean_ic_src"] > 0).sum()),
        "features_with_hac_t_gt_2": int((ic_tbl["t_hac_src"] > 2).sum()),
        "best_feature_by_net_bps": str(best["feature"]),
        "best_ann_net_bps_src": float(best["ann_net_bps"]),
        "best_ann_net_bps_lag1": float(best["ann_net_bps_lag1"]),
    }
    (out / "verdict.json").write_text(json.dumps(verdict, indent=2), encoding="utf-8")
    print("\n=== G3/G4 verdict ===")
    print(json.dumps(verdict, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
