"""Follow-up: does the reproduced Matthiola edge survive beta neutralisation, and
where does it actually come from?

Two questions the mission verdict left open:

  Q1 Concentration — is the 2023-24 result a broad cross-sectional effect or a
     handful of months/names?
  Q2 Beta — the largest raw |HAC t| sit on vol_60d / vol_20d / size_adv_60, all
     pointing long high-vol, long illiquid. Is the ranker's IC just market beta?
     The source runs sector+beta neutralisation for equities (notebook 06) and no
     crypto analogue; this is that analogue.

All inputs already exist from the G5 run; nothing is refitted except the
neutralised score, which is a per-date cross-sectional OLS residual.
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

from qtools.backtest.costs import CostModel
from qtools.backtest.engine import BacktestEngine
from qtools.backtest.portfolio import signal_to_weights
from qtools.metrics.performance import (
    annualized_return,
    max_drawdown,
    sharpe,
)

TARGET = "fwd_rank_21d"
BETA_WINDOW = 60
BLOCK, BOOT, SEED = 21, 2000, 7
COST_PER_LEG_BPS = 10.0


def _boot(returns: pd.Series) -> tuple[float, float]:
    x = returns.to_numpy(dtype=float)
    if len(x) < BLOCK * 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(SEED)
    nb = int(np.ceil(len(x) / BLOCK))
    starts = rng.integers(0, len(x) - BLOCK, size=(BOOT, nb))
    out = np.empty(BOOT)
    for i in range(BOOT):
        idx = np.concatenate([np.arange(s, s + BLOCK) for s in starts[i]])[: len(x)]
        s = x[idx]
        out[i] = s.mean() / s.std() * np.sqrt(252) if s.std() > 0 else np.nan
    lo, hi = np.nanpercentile(out, [2.5, 97.5])
    return float(lo), float(hi)


def _ic(preds: pd.DataFrame, col: str) -> pd.Series:
    vals = []
    dates = []
    for d, g in preds.groupby("date", sort=True):
        sub = g[[col, TARGET]].dropna()
        if len(sub) < 5:
            continue
        dates.append(d)
        vals.append(float(sub[col].rank().corr(sub[TARGET])))
    return pd.Series(vals, index=pd.DatetimeIndex(dates), dtype="float64").dropna()


def _hac_t(s: pd.Series, lag: int = 21) -> float:
    x = s.to_numpy(dtype=float)
    n = len(x)
    if n < lag + 2:
        return float("nan")
    xc = x - x.mean()
    var = float(np.dot(xc, xc) / n)
    for k in range(1, lag + 1):
        var += 2.0 * (1.0 - k / (lag + 1.0)) * float(np.dot(xc[:-k], xc[k:]) / n)
    return float(x.mean() / np.sqrt(var / n)) if var > 0 else float("nan")


def _n_eff(s: pd.Series, lag: int = 21) -> float:
    x = s.to_numpy(dtype=float)
    n = len(x)
    if n < lag + 2:
        return float(n)
    xc = x - x.mean()
    den = float(np.dot(xc, xc))
    if den == 0:
        return float(n)
    rho = sum(float(np.dot(xc[:-k], xc[k:]) / den) for k in range(1, lag + 1))
    f = 1.0 + 2.0 * rho
    return float(n / f) if f > 0 else float(n)


def _book(preds: pd.DataFrame, prices: pd.DataFrame, col: str = "score",
          drop_best_months: int = 0, keep: list[str] | None = None) -> dict:
    g = preds if keep is None else preds[preds["symbol"].isin(keep)]
    sig = g.pivot(index="date", columns="symbol", values=col).sort_index()
    w = signal_to_weights(sig, n_quantiles=5, long_short=True, rebalance="ME")
    res = BacktestEngine(prices[["date", "symbol", "close"]],
                         cost_model=CostModel(commission_bps=COST_PER_LEG_BPS / 2,
                                              slippage_bps=COST_PER_LEG_BPS / 2)).run(w)
    r = res.returns.copy()
    if drop_best_months:
        monthly = r.groupby([r.index.year, r.index.month]).sum()
        keep_m = monthly.nsmallest(len(monthly) - drop_best_months).index
        mask = pd.Series(list(zip(r.index.year, r.index.month)), index=r.index).isin(keep_m)
        r = r[mask.to_numpy()]
    lo, hi = _boot(r)
    return {"ann_net": float(annualized_return(r)), "sharpe": float(sharpe(r)),
            "ci_lo": lo, "ci_hi": hi, "mdd": float(max_drawdown(r))}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "followup_output"))
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    preds = pd.read_parquet(HERE / "purged_output" / "purged_oos_predictions.parquet")
    preds = preds[preds["variant"] == "purged_21d"].copy()
    prices = pd.read_parquet(HERE / "repro_output" / "btc_uni_prices.parquet")
    prices["date"] = pd.to_datetime(prices["date"])

    # ---------- Q1: concentration -----------------------------------------
    xgb = preds[preds["model"] == "xgb_ranker"]
    sig = xgb.pivot(index="date", columns="symbol", values="score").sort_index()
    w = signal_to_weights(sig, n_quantiles=5, long_short=True, rebalance="ME")
    res = BacktestEngine(prices[["date", "symbol", "close"]],
                         cost_model=CostModel(commission_bps=5, slippage_bps=5)).run(w)
    r = res.returns
    monthly = r.groupby([r.index.year, r.index.month]).sum().sort_values(ascending=False)
    total = float(monthly.sum())
    top3 = float(monthly.head(3).sum())
    # per-symbol contribution: position * instrument return, summed
    rets = prices.pivot(index="date", columns="symbol", values="close").sort_index().pct_change()
    pos = res.weights.shift(1).fillna(0.0)
    per_sym = (pos * rets.reindex(index=pos.index, columns=pos.columns)).sum().sort_values(ascending=False)
    gross_total = float(per_sym.sum())
    concentration = {
        "total_net_pnl_units": total,
        "top3_months": [[int(y), int(m), float(v)] for (y, m), v in monthly.head(3).items()],
        "top3_month_share_of_total": top3 / total if total else None,
        "positive_months": int((monthly > 0).sum()),
        "negative_months": int((monthly < 0).sum()),
        "per_symbol_gross_contribution": {k: float(v) for k, v in per_sym.items()},
        "top3_symbol_share_of_gross": float(per_sym.head(3).sum() / gross_total) if gross_total else None,
    }
    (out / "concentration.json").write_text(json.dumps(concentration, indent=2), encoding="utf-8")

    # ---------- Q2: beta neutralisation -----------------------------------
    close = prices.pivot(index="date", columns="symbol", values="close").sort_index()
    rets_all = close.pct_change()
    mkt = rets_all.mean(axis=1)                      # equal-weight basket
    var_m = mkt.rolling(BETA_WINDOW).var()
    beta = rets_all.rolling(BETA_WINDOW).cov(mkt).div(var_m, axis=0)
    beta = beta.shift(1)                             # causal: yesterday's beta
    beta_long = beta.stack().rename("beta").reset_index()
    beta_long.columns = ["date", "symbol", "beta"]

    work = xgb.merge(beta_long, on=["date", "symbol"], how="left")
    work = work.dropna(subset=["beta"])

    # explicit per-date loop: pandas groupby.apply drops the grouping column in 3.x
    pieces = []
    for _, g in work.groupby("date", sort=True):
        g = g.copy()
        if len(g) < 6 or g["beta"].nunique() < 2:
            g["score_neutral"] = np.nan
            g["beta_loading"] = np.nan
        else:
            X = np.column_stack([np.ones(len(g)), g["beta"].to_numpy()])
            y = g["score"].to_numpy()
            coef, *_ = np.linalg.lstsq(X, y, rcond=None)
            g["score_neutral"] = y - X @ coef
            g["beta_loading"] = float(coef[1])
        pieces.append(g)
    neutral = pd.concat(pieces, ignore_index=True)
    neutral.to_parquet(out / "neutralised_predictions.parquet", index=False)

    corr_rows = []
    for d, g in work.groupby("date"):
        if len(g) >= 6 and g["beta"].nunique() >= 2:
            corr_rows.append(float(g["score"].rank().corr(g["beta"].rank())))
    score_beta_corr = float(pd.Series(corr_rows).mean())

    rows = []
    for label, col in (("raw", "score"), ("beta_neutral", "score_neutral")):
        sub = neutral.dropna(subset=[col])
        ic = _ic(sub, col)
        b = _book(sub, prices, col=col)
        b_drop = _book(sub, prices, col=col, drop_best_months=2)
        adv = (prices.assign(dv=prices["close"] * prices["volume"])
               .groupby("symbol")["dv"].median().sort_values(ascending=False))
        b_top10 = _book(sub, prices, col=col, keep=adv.head(10).index.tolist())
        rows.append({
            "variant": label, "mean_ic": float(ic.mean()),
            "ic_ir": float(ic.mean() / ic.std()) if ic.std() > 0 else float("nan"),
            "hac_t": _hac_t(ic), "n_eff": _n_eff(ic), "n_dates": len(ic),
            "ann_net": b["ann_net"], "sharpe": b["sharpe"],
            "ci_lo": b["ci_lo"], "ci_hi": b["ci_hi"], "mdd": b["mdd"],
            "sharpe_drop_best2m": b_drop["sharpe"],
            "sharpe_top10_adv": b_top10["sharpe"],
        })
    tbl = pd.DataFrame(rows)
    tbl.to_csv(out / "neutralisation.csv", index=False)

    raw, neu = tbl.iloc[0], tbl.iloc[1]
    verdict = {
        "gate": "followup",
        "mean_cross_sectional_score_beta_corr": score_beta_corr,
        "raw": {"ic_ir": raw["ic_ir"], "hac_t": raw["hac_t"], "sharpe": raw["sharpe"]},
        "beta_neutral": {"ic_ir": neu["ic_ir"], "hac_t": neu["hac_t"], "sharpe": neu["sharpe"],
                         "sharpe_drop_best2m": neu["sharpe_drop_best2m"],
                         "sharpe_top10_adv": neu["sharpe_top10_adv"]},
        "ic_ir_survival_pct": float(neu["ic_ir"] / raw["ic_ir"] * 100) if raw["ic_ir"] else None,
        "sharpe_survival_pct": float(neu["sharpe"] / raw["sharpe"] * 100) if raw["sharpe"] else None,
    }
    (out / "verdict.json").write_text(json.dumps(verdict, indent=2), encoding="utf-8")

    print("=== Q1 concentration ===")
    print(json.dumps(concentration, indent=2))
    print("\n=== Q2 raw vs beta-neutral ===")
    print(tbl.to_string(index=False))
    print("\n=== verdict ===")
    print(json.dumps(verdict, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
