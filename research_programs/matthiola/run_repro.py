"""G1 reproduction runner: Matthiola ml-cross-sectional BTC robustness (notebook 05).

Runs the UPSTREAM source code verbatim (vendored under upstream/) against raw
Binance spot daily OHLCV fetched through the upstream qtools/ccxt loader.
Nothing here re-implements the source feature, target, model, validation, IC or
backtest logic — it only sequences the upstream calls exactly as notebook 05 does.

Reported targets (README.md, notebook 05):
    BTC-uni, 20 names, 2018-01-01..2025-07-31, OOS 2022-2024
    xgb_ranker  IC-IR +0.18   net Sharpe +0.74
    naive_ew    IC-IR -0.39   net Sharpe -0.22
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "upstream"))

from mlcs.features import add_forward_target, build_feature_panel
from mlcs.model import EqualWeightBaseline, XGBRankerModel
from mlcs.validation import walk_forward_years
from qtools.backtest.costs import CRYPTO
from qtools.backtest.engine import BacktestEngine
from qtools.backtest.portfolio import signal_to_weights
from qtools.data.loaders.crypto import get_crypto_prices
from qtools.metrics.performance import (
    annualized_return,
    max_drawdown,
    sharpe,
)

# notebook 05, cell 1 — verbatim
FEATURES = [
    "mom_12_1", "reversal_1w", "size_adv_60",
    "ret_21d", "ret_63d", "ret_126d", "ret_252d",
    "vol_20d", "vol_60d",
    "rsi_14", "macd_hist", "volume_z_60",
]
TARGET = "fwd_rank_21d"

# notebook 05, cell 10 — verbatim
BTC_UNIVERSE = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT",
    "DOGE/USDT", "SOL/USDT", "DOT/USDT", "LTC/USDT", "BCH/USDT",
    "LINK/USDT", "AVAX/USDT", "ATOM/USDT", "TRX/USDT", "XLM/USDT",
    "ETC/USDT", "FIL/USDT", "NEAR/USDT", "UNI/USDT", "ALGO/USDT",
]

START, END = "2018-01-01", "2025-07-31"
FIRST_OOS, LAST_OOS = 2022, 2024


def _sha(path: Path) -> str:
    return hashlib.file_digest(path.open("rb"), "sha256").hexdigest()


def prepare_feature_matrix(prices: pd.DataFrame, label: str):
    """notebook 05, cell 3 — verbatim logic."""
    prices = prices.copy()
    prices["date"] = pd.to_datetime(prices["date"])
    close = prices.pivot(index="date", columns="symbol", values="close").sort_index()
    volume = prices.pivot(index="date", columns="symbol", values="volume").sort_index()
    feats = build_feature_panel(close, volume)
    feats = add_forward_target(feats, close, horizon=21)
    feats = feats.dropna(subset=[TARGET])
    print(f"[{label}] feature rows: {len(feats):,}, symbols: {feats['symbol'].nunique()}")
    return feats, close


def run_walkforward(work: pd.DataFrame, first_oos: int, last_oos: int, label: str) -> pd.DataFrame:
    """notebook 05, cell 3 — verbatim logic including the 200/4/0.05 override."""
    all_preds = []
    for oos_year, tr_mask, te_mask in walk_forward_years(work["date"], first_oos, last_oos):
        tr = work.loc[tr_mask]
        te = work.loc[te_mask]
        if len(tr) == 0 or len(te) == 0:
            continue
        for mdl in [
            XGBRankerModel(n_estimators=200, max_depth=4, learning_rate=0.05, random_state=42),
            EqualWeightBaseline(),
        ]:
            mdl.fit(tr[FEATURES], tr[TARGET], tr["date"])
            scores = mdl.predict(te[FEATURES], te["date"])
            out = te[["date", "symbol", TARGET]].copy()
            out["model"] = mdl.name
            out["score"] = scores
            out["universe"] = label
            all_preds.append(out)
    return pd.concat(all_preds, ignore_index=True)


def _per_date_ic(sub: pd.DataFrame) -> float:
    sub = sub[["score", TARGET]].dropna()
    if len(sub) < 5:          # min names per date, as in the notebook
        return np.nan
    return sub["score"].rank().corr(sub[TARGET])


def ic_summary(preds: pd.DataFrame) -> pd.DataFrame:
    """notebook 05, cell 3 — reimplemented as an explicit loop for pandas-version
    safety; the statistic is identical (per-date Spearman rank correlation)."""
    rows = []
    for (uni, model), group in preds.groupby(["universe", "model"]):
        ics = [_per_date_ic(g) for _, g in group.groupby("date", sort=True)]
        ic = pd.Series(ics, dtype="float64").dropna()
        if len(ic) == 0:
            continue
        ir = ic.mean() / ic.std() if ic.std() > 0 else np.nan
        rows.append({
            "universe": uni, "model": model,
            "mean_ic": round(float(ic.mean()), 4),
            "ic_ir": round(float(ir), 3) if pd.notna(ir) else np.nan,
            "t_stat": round(float(ir) * np.sqrt(len(ic)), 2) if pd.notna(ir) else np.nan,
            "hit_rate": round(float((ic > 0).mean()), 3),
            "n_dates": len(ic),
        })
    return pd.DataFrame(rows).sort_values(["universe", "ic_ir"], ascending=[True, False]).reset_index(drop=True)


def run_backtest(preds: pd.DataFrame, prices: pd.DataFrame, cost, n_quantiles: int, rebalance: str) -> pd.DataFrame:
    """notebook 05, cell 3 — verbatim logic."""
    rows = []
    for model, group in preds.groupby("model"):
        signal = group.pivot(index="date", columns="symbol", values="score").sort_index()
        weights = signal_to_weights(signal, n_quantiles=n_quantiles, long_short=True, rebalance=rebalance)
        engine = BacktestEngine(prices[["date", "symbol", "close"]], cost_model=cost)
        res = engine.run(weights)
        rows.append({
            "model": model,
            "ann_gross": round(float(annualized_return(res.gross_returns)), 4),
            "ann_net": round(float(annualized_return(res.returns)), 4),
            "sharpe_gross": round(float(sharpe(res.gross_returns)), 3),
            "sharpe_net": round(float(sharpe(res.returns)), 3),
            "mdd_net": round(float(max_drawdown(res.returns)), 4),
            "cost_drag": round(float((res.gross_returns.mean() - res.returns.mean()) * 252), 4),
        })
    return pd.DataFrame(rows).sort_values("sharpe_net", ascending=False).reset_index(drop=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "repro_output"))
    args = ap.parse_args(argv)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- G0: raw tape acquisition through the upstream loader -------------
    btc_prices = get_crypto_prices(BTC_UNIVERSE, START, END, interval="1d")
    print("BTC-uni price rows:", len(btc_prices), "  symbols:", btc_prices["symbol"].nunique())

    cache = Path.home() / ".qtools_cache" / "crypto_prices"
    cache_files = sorted(cache.glob("*.parquet"))
    tape = {
        "loader": "qtools.data.loaders.crypto.get_crypto_prices",
        "exchange": "binance (spot, ccxt)",
        "interval": "1d",
        "requested_universe": BTC_UNIVERSE,
        "present_symbols": sorted(btc_prices["symbol"].unique().tolist()),
        "dropped_symbols": sorted(set(BTC_UNIVERSE) - set(btc_prices["symbol"].unique())),
        "rows": len(btc_prices),
        "date_min": str(btc_prices["date"].min().date()),
        "date_max": str(btc_prices["date"].max().date()),
    }
    btc_prices.to_parquet(out_dir / "btc_uni_prices.parquet", index=False)
    tape["parquet_sha256"] = _sha(out_dir / "btc_uni_prices.parquet")
    tape["cache_files"] = [{"name": p.name, "sha256": _sha(p)} for p in cache_files]
    (out_dir / "tape_manifest.json").write_text(json.dumps(tape, indent=2), encoding="utf-8")
    print("tape manifest:", json.dumps({k: tape[k] for k in ("rows", "date_min", "date_max", "dropped_symbols")}))

    # ---- G1: features, walk-forward, IC, backtest -------------------------
    btc_work, _btc_close = prepare_feature_matrix(btc_prices, "BTC")
    btc_preds = run_walkforward(btc_work, first_oos=FIRST_OOS, last_oos=LAST_OOS, label="BTC")
    print("BTC OOS predictions:", btc_preds.shape)

    btc_ic = ic_summary(btc_preds)
    btc_bt = run_backtest(btc_preds, btc_prices, CRYPTO, n_quantiles=5, rebalance="ME")

    btc_ic.to_csv(out_dir / "btc_ic.csv", index=False)
    btc_bt.to_csv(out_dir / "btc_backtest.csv", index=False)
    btc_preds.to_parquet(out_dir / "btc_oos_predictions.parquet", index=False)

    reported = {
        "xgb_ranker": {"ic_ir": 0.18, "sharpe_net": 0.74},
        "naive_ew": {"ic_ir": -0.39, "sharpe_net": -0.22},
    }
    comparison = []
    for model, exp in reported.items():
        ic_row = btc_ic[btc_ic["model"] == model]
        bt_row = btc_bt[btc_bt["model"] == model]
        comparison.append({
            "model": model,
            "reported_ic_ir": exp["ic_ir"],
            "reproduced_ic_ir": float(ic_row["ic_ir"].iloc[0]) if len(ic_row) else None,
            "reported_sharpe_net": exp["sharpe_net"],
            "reproduced_sharpe_net": float(bt_row["sharpe_net"].iloc[0]) if len(bt_row) else None,
        })
    comp = pd.DataFrame(comparison)
    comp.to_csv(out_dir / "reported_vs_reproduced.csv", index=False)

    print("\n=== IC (OOS 2022-2024, BTC-uni) ===")
    print(btc_ic.to_string(index=False))
    print("\n=== Backtest (CRYPTO 5+5 bps, ME rebalance, 5 quintiles) ===")
    print(btc_bt.to_string(index=False))
    print("\n=== Reported vs reproduced ===")
    print(comp.to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
