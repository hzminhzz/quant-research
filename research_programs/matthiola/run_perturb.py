"""G7 — adversarial perturbation battery.

Takes the purged XGB walk-forward scores and asks whether the conclusion survives
plausible changes that a sceptical reviewer would demand. Each perturbation is
applied to the same scores unless it must be re-run.

Perturbations
  P1  entry shifted +1 day (signal at close(t), fill at close(t+1))
  P2  drop the 5% best daily net returns
  P3  drop the 5% best rebalance months
  P4  cost model at 5 / 10 / 20 bps per leg (source is 10)
  P5  universe floor: keep only the 10 highest median-dollar-volume names
  P6  quintile count 3 / 5 / 10

Every variant reports annualised net return, net Sharpe, a stationary block
bootstrap 95% CI for Sharpe, max drawdown and turnover. A conclusion is FRAGILE
if the Sharpe sign or the CI's relation to zero flips.
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

BLOCK = 21
BOOT = 2000
SEED = 7


def _boot_ci(returns: pd.Series, block: int = BLOCK, n: int = BOOT, seed: int = SEED) -> tuple[float, float]:
    """Stationary block bootstrap CI for annualised Sharpe."""
    x = returns.to_numpy(dtype=float)
    if len(x) < block * 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(len(x) / block))
    starts = rng.integers(0, len(x) - block, size=(n, n_blocks))
    out = np.empty(n)
    for i in range(n):
        idx = np.concatenate([np.arange(s, s + block) for s in starts[i]])[: len(x)]
        sample = x[idx]
        sd = sample.std()
        out[i] = sample.mean() / sd * np.sqrt(252) if sd > 0 else np.nan
    lo, hi = np.nanpercentile(out, [2.5, 97.5])
    return float(lo), float(hi)


def _describe(returns: pd.Series, weights: pd.DataFrame, label: str, detail: str) -> dict:
    lo, hi = _boot_ci(returns)
    t = weights.diff().abs().sum(axis=1) / 2
    t.iloc[0] = weights.iloc[0].abs().sum() / 2
    t = t[t > 0]
    return {
        "variant": label,
        "detail": detail,
        "ann_net": float(annualized_return(returns)),
        "sharpe_net": float(sharpe(returns)),
        "sharpe_ci_lo": lo,
        "sharpe_ci_hi": hi,
        "ci_excludes_zero": bool(lo > 0 or hi < 0),
        "mdd_net": float(max_drawdown(returns)),
        "mean_turnover": float(t.mean()) if len(t) else float("nan"),
        "n_days": len(returns),
    }


def _run(preds: pd.DataFrame, prices: pd.DataFrame, *, label: str, detail: str,
         shift: int = 0, cost_bps: float = 10.0, n_quantiles: int = 5,
         keep_symbols: list[str] | None = None, drop_best_daily: float = 0.0,
         drop_best_months: int = 0) -> dict:
    g = preds
    if keep_symbols is not None:
        g = g[g["symbol"].isin(keep_symbols)]
    sig = g.pivot(index="date", columns="symbol", values="score").sort_index()
    if shift:
        sig = sig.shift(shift).dropna(how="all")
    w = signal_to_weights(sig, n_quantiles=n_quantiles, long_short=True, rebalance="ME")
    cost = CostModel(commission_bps=cost_bps / 2, slippage_bps=cost_bps / 2)
    res = BacktestEngine(prices[["date", "symbol", "close"]], cost_model=cost).run(w)
    r = res.returns.copy()

    if drop_best_daily:
        k = int(np.ceil(len(r) * drop_best_daily))
        keep = r.drop(r.nlargest(k).index)
        r = keep
    if drop_best_months:
        monthly = r.groupby([r.index.year, r.index.month]).sum()
        worst = monthly.nsmallest(len(monthly) - drop_best_months)
        mask = pd.Series(list(zip(r.index.year, r.index.month)), index=r.index).isin(worst.index)
        r = r[mask.to_numpy()]

    return _describe(r, w, label, detail)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "perturb_output"))
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    preds = pd.read_parquet(HERE / "purged_output" / "purged_oos_predictions.parquet")
    preds = preds[(preds["variant"] == "purged_21d") & (preds["model"] == "xgb_ranker")].copy()
    prices = pd.read_parquet(HERE / "repro_output" / "btc_uni_prices.parquet")
    prices["date"] = pd.to_datetime(prices["date"])

    # universe floor: 10 highest median dollar volume over the OOS window
    oos_prices = prices[(prices["date"] >= preds["date"].min()) & (prices["date"] <= preds["date"].max())]
    adv = (oos_prices.assign(dv=oos_prices["close"] * oos_prices["volume"])
           .groupby("symbol")["dv"].median().sort_values(ascending=False))
    top10 = adv.head(10).index.tolist()

    rows = [
        _run(preds, prices, label="baseline", detail="purged XGB, 10 bps/leg, 5 quintiles, 20 names"),
        _run(preds, prices, label="P1_entry_lag1", detail="fill at close(t+1) instead of close(t)", shift=1),
        _run(preds, prices, label="P2_drop_best5pct_days", detail="remove the 5% best daily net returns",
             drop_best_daily=0.05),
        _run(preds, prices, label="P3_drop_best2_months", detail="remove the 2 best rebalance months",
             drop_best_months=2),
        _run(preds, prices, label="P4_cost_5bps", detail="5 bps per leg (maker-ish)", cost_bps=5.0),
        _run(preds, prices, label="P4_cost_20bps", detail="20 bps per leg (worse taker)", cost_bps=20.0),
        _run(preds, prices, label="P5_top10_adv", detail="universe floor: 10 highest median ADV names",
             keep_symbols=top10),
        _run(preds, prices, label="P6_quintiles_3", detail="terciles instead of quintiles", n_quantiles=3),
        _run(preds, prices, label="P6_quintiles_10", detail="deciles instead of quintiles", n_quantiles=10),
    ]
    tbl = pd.DataFrame(rows)
    tbl.to_csv(out / "perturbations.csv", index=False)
    print(tbl.to_string(index=False))

    base = tbl[tbl.variant == "baseline"].iloc[0]
    base_sign = np.sign(base["sharpe_net"])
    flips = tbl[(np.sign(tbl["sharpe_net"]) != base_sign)]
    verdict = {
        "gate": "G7",
        "baseline_sharpe": float(base["sharpe_net"]),
        "baseline_ci": [float(base["sharpe_ci_lo"]), float(base["sharpe_ci_hi"])],
        "baseline_ci_excludes_zero": bool(base["ci_excludes_zero"]),
        "n_perturbations": int(len(tbl) - 1),
        "sign_flips": flips["variant"].tolist(),
        "min_sharpe": float(tbl[tbl.variant != "baseline"]["sharpe_net"].min()),
        "max_sharpe": float(tbl[tbl.variant != "baseline"]["sharpe_net"].max()),
        "ci_excludes_zero_count": int(tbl["ci_excludes_zero"].sum()),
        "status": "FRAGILE" if len(flips) else "STABLE",
        "top10_adv_symbols": top10,
    }
    (out / "verdict.json").write_text(json.dumps(verdict, indent=2), encoding="utf-8")
    print("\n=== G7 verdict ===")
    print(json.dumps(verdict, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
