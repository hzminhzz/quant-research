"""Correlations and portfolio overlays for five independent native ML4T strategies.

Reads native-backtest equity artifacts. Performs no hand-written trade simulation.
Combines realized after-cost sleeve returns as in the uploaded Shannon-20
portfolio.py, but keeps this system separate from Shannon.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from ml4t.diagnostic.api import PortfolioAnalysis

ROOT = Path("run_log/independent_five_full_history_20261014")
OUT = Path("run_log/independent_five_correlation_portfolio_20261014")
CASES = (
    "pivot-breakout-btc", "donchian-btc", "three-red-spy",
    "slope-hook", "rsi-30-50",
)
ASSETS = {
    "pivot-breakout-btc": "BTC", "donchian-btc": "BTC",
    "three-red-spy": "ES", "slope-hook": "ES", "rsi-30-50": "ES",
}
START = pd.Timestamp("2020-01-01", tz="UTC")
CUTOFF = pd.Timestamp("2026-10-12", tz="UTC")
TRAIN_END = pd.Timestamp("2023-01-01", tz="UTC")
MAX_WEIGHT = 0.35


def load_native_sleeves() -> dict[str, pd.Series]:
    manifest = json.loads((ROOT / "manifest.json").read_text())
    assert manifest["status"] == "COMPLETE"
    assert set(manifest["completed"]) >= set(CASES)
    sleeves = {}
    for name in CASES:
        path = ROOT / name
        meta = json.loads((path / "summary.json").read_text())
        assert meta["native_rejections"] == 0
        assert meta["status"].startswith("EXPLORATORY")
        csv = path / "equity.csv"
        assert hashlib.sha256(csv.read_bytes()).hexdigest() == meta["artifact_sha256"]["equity.csv"]
        df = pd.read_csv(csv)
        times = pd.to_datetime(df["timestamp"], utc=True)
        equity = pd.Series(df["equity"].to_numpy(dtype=float), index=pd.DatetimeIndex(times))
        assert not equity.index.has_duplicates and equity.index.is_monotonic_increasing
        assert float(equity.min()) > 0 and equity.index.max() < CUTOFF
        assert abs(equity.iloc[-1] - meta["metrics"]["final_value"]) < .001
        rets = equity.pct_change().fillna(0.0)
        native_export = df["return"].to_numpy(dtype=float)
        assert np.allclose(rets.to_numpy(), native_export, atol=1e-7, rtol=1e-7)
        sleeves[name] = rets.rename(name)
    return sleeves


def align_business_days(
    sleeves: dict[str, pd.Series], *,
    start: pd.Timestamp = START, end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Compounds BTC weekends onto next business day like Shannon-20.

    Does not discard weekends, and does not add simple returns across days.
    Other missing source sessions are treated as zero-return closed sessions.
    """
    if end is None:
        es_end = [s.index[-1] for n, s in sleeves.items() if ASSETS[n] == "ES"]
        end = min(es_end)
    if end >= CUTOFF:
        end = CUTOFF - pd.Timedelta(days=1)
    calendar = pd.bdate_range(start, end, tz="UTC")
    if calendar.empty:
        raise ValueError("Empty shared calendar")
    frame = pd.DataFrame(index=calendar)
    for name, native_returns in sleeves.items():
        sample = native_returns.loc[(native_returns.index >= start) &
                                    (native_returns.index <= end)]
        positions = calendar.searchsorted(sample.index)
        valid = positions < len(calendar)
        # By design: Sat/Sun -> following Monday, if Monday is still in sample.
        slots = calendar.take(positions[valid])
        items = pd.DataFrame({"business_day": slots, "return": sample.iloc[np.flatnonzero(valid)].to_numpy()})
        if (items["return"] <= -1).any():
            raise ValueError(f"{name}: invalid native return <= -100%")
        # Exact geometric compounding of BTC weekend returns.
        acc = items.assign(log_growth=np.log1p(items["return"])).groupby("business_day")["log_growth"].sum()
        collapsed = np.expm1(acc)
        frame[name] = collapsed.reindex(calendar, fill_value=0.0).to_numpy()
    assert not frame.isnull().any().any()
    assert frame.index.max() < CUTOFF
    return frame


def align_calendar_days(
    sleeves: dict[str, pd.Series], *,
    start: pd.Timestamp = START, end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    if end is None:
        end = min(s.index[-1] for n, s in sleeves.items() if ASSETS[n] == "ES")
    calendar = pd.date_range(start, end, tz="UTC", freq="D")
    out = pd.DataFrame(index=calendar)
    for name, series in sleeves.items():
        out[name] = series.reindex(calendar, fill_value=0.0)
    return out


def inverse_vol_group_weights(train: pd.DataFrame) -> pd.Series:
    """Half capital budget to BTC / ES; per-sleeve cap 35%.

    Only trained on 2020-2022 volatility, never future returns.
    """
    s = train.std(ddof=1)
    if (s <= 0).any():
        raise ValueError(f"Invalid training vol: {s.to_dict()}")
    weights = pd.Series(0.0, index=list(CASES), dtype=float)
    for group in ("BTC", "ES"):
        names = [n for n in CASES if ASSETS[n] == group]
        remaining = 0.5
        available = set(names)
        while available:
            a = [x for x in names if x in available]
            inv = (1.0 / s.loc[a])
            proposed = inv / inv.sum() * remaining
            over = proposed[proposed > MAX_WEIGHT + 1e-12]
            if not len(over):
                weights.loc[a] = proposed
                break
            for n in over.index:
                weights.loc[n] = MAX_WEIGHT
                remaining -= MAX_WEIGHT
                available.remove(n)
            if remaining < -1e-10:
                raise ValueError("Infeasible weights")
    assert abs(weights.sum() - 1.0) < 1e-10
    assert weights.max() <= MAX_WEIGHT + 1e-10
    assert abs(weights.loc[[n for n in CASES if ASSETS[n]=="BTC"]].sum() - 0.5) < 1e-10
    return weights


def inverse_vol_between_market_groups(train: pd.DataFrame) -> pd.Series:
    """Post-observation risk budget diagnostic; training 2020-22 only.

    Within each market group split equally. Two group baskets are inversely
    proportional to their development volatility; no Sharpe optimization.
    """
    btc = ["pivot-breakout-btc", "donchian-btc"]
    es = ["three-red-spy", "slope-hook", "rsi-30-50"]
    vol_btc = float(train[btc].mean(axis=1).std(ddof=1))
    vol_es = float(train[es].mean(axis=1).std(ddof=1))
    if not (vol_btc > 0 and vol_es > 0):
        raise ValueError("Invalid group risk scale")
    inverse = np.array([1.0 / vol_btc, 1.0 / vol_es])
    budgets = inverse / inverse.sum()
    weights = pd.Series(
        [budgets[0] / len(btc)] * len(btc) +
        [budgets[1] / len(es)] * len(es),
        index=CASES,
    )
    if weights.max() > MAX_WEIGHT + 1e-12:
        raise ValueError("Group-risk weights breach fixed 35% sleeve cap")
    assert abs(weights.sum() - 1.0) < 1e-10
    return weights


def portfolio_daily_rebalanced(returns: pd.DataFrame, weights: pd.Series) -> pd.Series:
    """Daily sleeve return overlay; NO extra portfolio-layer trading costs."""
    return returns.dot(weights).rename("return")


def portfolio_static_initial_capital(returns: pd.DataFrame, weights: pd.Series) -> pd.Series:
    """Own fixed capital fraction of each already executed native sleeve.

    No periodic cross-sleeve rebalancing; this is an accounting aggregation
    of separately native-executed equity curves, not another execution engine.
    """
    sleeve_nav = (1.0 + returns).cumprod(axis=0)
    total_nav = sleeve_nav.dot(weights)
    return total_nav.pct_change().fillna(total_nav.iloc[0] - 1.0).rename("return")


def ml4t_metrics(returns: pd.Series) -> dict:
    # The official ML4T diagnostic implementation supplies all risk statistics.
    score = PortfolioAnalysis(
        returns=returns.to_numpy(dtype=float),
        dates=returns.index.to_numpy(), periods_per_year=252,
    ).compute_summary_stats()
    fields = ["total_return", "annual_return", "annual_volatility",
              "sharpe_ratio", "sortino_ratio", "calmar_ratio", "max_drawdown",
              "var_95", "cvar_95", "profit_factor", "win_rate"]
    return {k: (float(v) if v is not None and np.isfinite(v) else None)
            for k in fields for v in [getattr(score, k)]}


def window_metrics(r: pd.Series) -> dict:
    windows = [
        ("full_common", START, None),
        ("screening_2020_2022", START, TRAIN_END),
        ("reviewed_2023_2025", TRAIN_END, pd.Timestamp("2026-01-01", tz="UTC")),
        ("reviewed_2026_ytd", pd.Timestamp("2026-01-01", tz="UTC"), None),
    ]
    out = {}
    for name, start, end in windows:
        sample = r.loc[(r.index >= start) & ((r.index < end) if end is not None else True)]
        if sample.shape[0] >= 15:
            out[name] = {"days":len(sample), **ml4t_metrics(sample)}
    return out


def daily_rebalance_turnover_diagnostic(returns: pd.DataFrame, weights: pd.Series) -> dict:
    """Theoretical transfer of capital needed to restore fixed weights.

    This is descriptive accounting, not a fill-cost model or native broker
    simulation; it assumes unrestricted same-day transfer capacity.
    """
    daily_pnl = portfolio_daily_rebalanced(returns, weights)
    post_return_weights = (1.0 + returns).mul(weights, axis=1).div(
        1.0 + daily_pnl, axis=0
    )
    notional_one_way = (post_return_weights - weights).abs().sum(axis=1) * .5
    return {
        "mean_daily_one_way_pct": float(notional_one_way.mean()*100),
        "annualized_one_way_turnover_pct": float(notional_one_way.mean()*252*100),
        "max_day_one_way_pct": float(notional_one_way.max()*100),
        "sum_one_way_turnover_pct_of_daily_nav": float(notional_one_way.sum()*100),
        "execution_simulated":False,
    }


def risk_contribution(returns: pd.DataFrame, weights: pd.Series) -> dict:
    cov = returns.cov()
    x = weights.to_numpy()
    contribution = x * (cov.to_numpy() @ x)
    total = x @ cov.to_numpy() @ x
    return {n:float(v / total) if total>0 else None
            for n,v in zip(CASES, contribution)}


def corr_diagnostics(returns: pd.DataFrame) -> dict:
    corr = returns.corr()
    x = returns
    rows = []
    for a_i, a in enumerate(CASES):
        for b in CASES[a_i+1:]:
            act_a = x[a].abs() > 1e-12
            act_b = x[b].abs() > 1e-12
            both = act_a & act_b
            either = act_a | act_b
            neg_a, neg_b = x[a] < 0, x[b] < 0
            loss_both = neg_a & neg_b
            active_n = int(both.sum())
            both_corr = float(x.loc[both,a].corr(x.loc[both,b])) if active_n>=30 else None
            rows.append({
                "a":a,"b":b,
                "daily_corr": float(corr.loc[a,b]),
                "both_active_corr":both_corr,
                "both_active_days":active_n,
                "either_active_days":int(either.sum()),
                "jaccard_active":float(both.sum()/either.sum()) if either.any() else None,
                "same_loss_days":int(loss_both.sum()),
                "joint_loss_given_a_loss_pct":float(loss_both.sum()/neg_a.sum()*100) if neg_a.any() else None,
                "same_underlying": ASSETS[a]==ASSETS[b],
            })
    weekly = ((1.0 + returns).resample("W-FRI").prod() - 1.0)
    rolling = x.rolling(252, min_periods=252).corr()  # diagnostic only, no fitting
    # Rolling pair series from rolling correlation matrix.
    ranges = []
    for a_i,a in enumerate(CASES):
        for b in CASES[a_i+1:]:
            s = rolling.loc[(slice(None), a), b].dropna()
            if len(s):
                ranges.append({"a":a,"b":b,"rolling_252_median":float(s.median()),
                               "rolling_252_p10":float(s.quantile(.1)),
                               "rolling_252_p90":float(s.quantile(.9)),
                               "valid_windows":len(s)})
    return {"pairs":rows,"weekly_correlation": weekly.corr().to_dict(),
            "rolling_252":ranges}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sleeves = load_native_sleeves()
    aligned = align_business_days(sleeves)
    utc = align_calendar_days(sleeves, end=aligned.index[-1])
    if not aligned.index.is_unique or (aligned.index >= CUTOFF).any():
        raise AssertionError("Bad calendar")
    # Freeze metadata and training-only weights before reading performance.
    train = aligned.loc[aligned.index < TRAIN_END]
    weights = {
        "equal_five":pd.Series(0.2, index=CASES),
        "market_bucket_equal":pd.Series([0.25,0.25,1/6,1/6,1/6], index=CASES),
        "market_bucket_inverse_vol_train2020_2022":inverse_vol_group_weights(train),
        "market_group_equal_risk_train2020_2022":inverse_vol_between_market_groups(train),
        "rsi_only_reference":pd.Series([0.,0.,0.,0.,1.], index=CASES),
    }
    corr = aligned.corr()
    corr_train = train.corr()
    corr_after = aligned.loc[aligned.index >= TRAIN_END].corr()
    utc_corr = utc.corr()
    trace = corr_diagnostics(aligned)
    overlay = pd.DataFrame(index=aligned.index)
    metrics = {}
    for name,w in weights.items():
        overlay[name] = portfolio_daily_rebalanced(aligned,w)
        metrics[name] = {
            "weights":{s:float(v) for s,v in w.items()},
            "daily_rebalanced":window_metrics(overlay[name]),
            "static_capital":window_metrics(portfolio_static_initial_capital(aligned,w)),
            "risk_contribution_full":risk_contribution(aligned,w),
            "rebalance_turnover_diagnostic":daily_rebalance_turnover_diagnostic(aligned,w),
            "capital_pct":{ASSETS[n]: float(w.loc[[k for k in CASES if ASSETS[k] == ASSETS[n]]].sum()) for n in ("pivot-breakout-btc","rsi-30-50")},
            "risk_contribution_reviewed_2023_2025":risk_contribution(
                aligned.loc[(aligned.index>=TRAIN_END)&(aligned.index<pd.Timestamp("2026-01-01",tz="UTC"))],w),
        }
    aligned.to_csv(OUT/"aligned_net_returns_business_days.csv",index_label="date")
    utc.to_csv(OUT/"aligned_net_returns_calendar_days.csv",index_label="date")
    corr.to_csv(OUT/"correlation_business_days.csv")
    corr_train.to_csv(OUT/"correlation_2020_2022.csv")
    corr_after.to_csv(OUT/"correlation_after_2022.csv")
    utc_corr.to_csv(OUT/"correlation_calendar_days.csv")
    overlay.to_csv(OUT/"portfolio_daily_returns.csv",index_label="date")
    weights_frame = pd.DataFrame({n:w for n,w in weights.items()})
    weights_frame.to_csv(OUT/"allocations.csv",index_label="strategy")

    # Familiar CSV artifact names, intentionally isolated from Shannon-20.
    aligned.to_csv(OUT/"strategie_renditen.csv",index_label="date")
    overlay.to_csv(OUT/"portfolio_renditen.csv",index_label="date")
    corr.to_csv(OUT/"korrelation.csv")
    weights_frame.to_csv(OUT/"gewichte.csv",index_label="strategy")
    equity_marks = (1.0 + overlay).cumprod() * 100000.0
    equity_marks.to_csv(OUT/"portfolio_equity_analytical_overlay.csv",index_label="date")
    pd.DataFrame({
        name:risk_contribution(aligned,w) for name,w in weights.items()
    }).to_csv(OUT/"risikobeitrag.csv",index_label="strategy")

    stats_rows = []
    for portfolio, record in metrics.items():
        for kind in ("daily_rebalanced","static_capital"):
            for window, score in record[kind].items():
                stats_rows.append({
                    "portfolio": portfolio,"mode":kind,"window":window,**score
                })
    pd.DataFrame(stats_rows).to_csv(OUT/"kennzahlen_portfolios.csv",index=False)
    stats_rows = []
    for sleeve in CASES:
        for window, score in window_metrics(aligned[sleeve]).items():
            stats_rows.append({"strategy":sleeve,"window":window,**score})
    pd.DataFrame(stats_rows).to_csv(OUT/"kennzahlen_strategien.csv",index=False)
    summary = {
        "status":"EXPLORATORY_COMPLETE",
        "source_native_engine":"run_log/independent_five_full_history_20261014",
        "days":len(aligned), "start":str(aligned.index[0]),"end":str(aligned.index[-1]),
        "alignment":"BTC geometric weekend-to-next-business-day; ES closed-day zero return",
        "correlation_business_days":corr.to_dict(),
        "correlation_2020_2022":corr_train.to_dict(),
        "correlation_after_2022":corr_after.to_dict(),
        "correlation_calendar_days":utc_corr.to_dict(),
        "pair_diagnostics":trace,
        "single_sleeve_metrics":{n:window_metrics(aligned[n]) for n in CASES},
        "portfolios":metrics,
        "caveats":[
            "Strategy returns already include native per-sleeve transaction assumptions",
            "Daily portfolio rebalancing and margin NETTING not simulated by native broker",
            "No additional portfolio-level rebalance cost; optimistic for daily-rebalanced overlays",
            "UTC crypto versus 17:00 NY ES daily session labels are not synchronized",
            "Selected using 2020-22 Sharpe; 2023+ previously reviewed; no untouched holdout",
            "BTC perpetual funding, ES CFD financing and ETF dividend adjustment missing",
        ],
    }
    (OUT/"summary.json").write_text(json.dumps(summary,indent=2,allow_nan=False)+"\n")
    print("DAYS",len(aligned), "FIRST",aligned.index[0],"LAST",aligned.index[-1])
    print("DAILY_CORR")
    print(corr.round(3).to_string())
    print("CORR_2023PLUS")
    print(corr_after.round(3).to_string())
    print("WEIGHTS")
    print(pd.DataFrame(weights).round(3).to_string())
    print("FULL_METRICS")
    for k,v in metrics.items():
        print(k,{a:round(v["daily_rebalanced"]["full_common"][a],4)
                 for a in ("total_return","sharpe_ratio","max_drawdown","calmar_ratio","cvar_95")})
        print("  POST2022",{a:round(v["daily_rebalanced"]["reviewed_2023_2025"][a],4)
                 for a in ("total_return","sharpe_ratio","max_drawdown")})


if __name__=="__main__":
    main()
