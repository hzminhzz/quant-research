#!/usr/bin/env python3
"""Historical B0/B2 risk comparison; does not run a backtest."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl
from ml4t.backtest.analytics import calmar_ratio, max_drawdown, sharpe_ratio, sortino_ratio

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SEED = 20261012
REPS = 5000
BLOCKS = (5, 20)
START = "2013-01-01"
END = "2026-07-14"
LAUNCH = "2019-05-06"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_ledgers(base: str, leaf: str) -> tuple[pl.DataFrame, list[str]]:
    paths = sorted((ROOT / base).glob(f"*/{leaf}/evaluation_trades.csv"))
    if len(paths) != 14:
        raise AssertionError(f"expected 14 annual files, found {len(paths)} under {base}")
    frames = [pl.read_csv(path, try_parse_dates=False) for path in paths]
    df = pl.concat(frames, how="diagonal_relaxed").with_columns(
        pl.col("entry_time").str.slice(0, 10).alias("utc_entry_date"),
        pl.col("pnl").cast(pl.Float64),
    )
    if df.filter(pl.col("status") != "closed").height:
        raise AssertionError(f"non-closed ledger rows in {base}")
    if df.get_column("utc_entry_date").max() > END:
        raise AssertionError(f"entry dates exceed protected cutoff {END} in {base}")
    return df, [str(p.relative_to(ROOT)) for p in paths]


def safe_sharpe(x: np.ndarray) -> float | None:
    if len(x) < 2 or not np.isfinite(x).all() or np.std(x, ddof=1) == 0:
        return None
    return float(sharpe_ratio(x, risk_free_rate=0.0, annualize=False) * np.sqrt(365.25))


def trade_stats(df: pl.DataFrame, label: str) -> dict:
    p = df.get_column("pnl").to_numpy()
    wins, losses = p[p > 0], p[p < 0]
    loss_streak = best_loss_streak = 0
    for value in p:
        loss_streak = loss_streak + 1 if value < 0 else 0
        best_loss_streak = max(best_loss_streak, loss_streak)
    ans = {
        "ledger": label, "trades": int(len(p)), "net_pnl_usd": float(p.sum()),
        "win_rate": float((p > 0).mean()) if len(p) else None,
        "ties": int((p == 0).sum()), "profit_factor": float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() else None,
        "average_win_usd": float(wins.mean()) if len(wins) else None,
        "average_loss_usd": float(losses.mean()) if len(losses) else None,
        "expectancy_usd_per_trade": float(p.mean()) if len(p) else None,
        "worst_trade_usd": float(p.min()) if len(p) else None,
        "max_consecutive_losses": best_loss_streak,
    }
    if "direction" in df.columns:
        ans["by_direction"] = {
            side: {"trades": int((df.get_column("direction") == side).sum()), "net_pnl_usd": float(p[df.get_column("direction").to_numpy() == side].sum())}
            for side in sorted(df.get_column("direction").unique().to_list())
        }
    if "fees" in df.columns and "total_slippage_cost" in df.columns:
        ans["fees_usd"] = float(df.get_column("fees").cast(pl.Float64).sum())
        ans["slippage_usd"] = float(df.get_column("total_slippage_cost").cast(pl.Float64).sum())
        ans["cost_drag_usd_per_trade"] = float((ans["fees_usd"] + ans["slippage_usd"]) / len(p)) if len(p) else None
    if "nominal_risk_usd" in df.columns:
        risk = df.get_column("nominal_risk_usd").cast(pl.Float64).to_numpy()
        r = p / risk
        qty = df.get_column("quantity").cast(pl.Float64).abs().to_numpy()
        ans.update({
            "risk_unit_expectancy_r": float(r.mean()),
            "risk_unit_win_rate": float((r > 0).mean()),
            "risk_unit_worst_trade_r": float(r.min()),
            "risk_budget_utilization_median": float(np.median(risk / 1000.0)),
            "risk_budget_utilization_mean": float(np.mean(risk / 1000.0)),
            "quantity_median_mnq": float(np.median(qty)),
            "quantity_median_nq_equivalent": float(np.median(qty) / 10),
            "share_trades_over_10_mnq": float(np.mean(qty > 10)),
            "nominal_risk_over_1000_count": int(np.sum(risk > 1000)),
        })
        if "r_multiple" in df.columns:
            ans["stored_r_multiple_max_abs_error"] = float(np.max(np.abs(r - df.get_column("r_multiple").cast(pl.Float64).to_numpy())))
    return ans


def equity_stats(daily_pnl: np.ndarray, risk_daily: np.ndarray, days: int) -> dict:
    # Trade-entry-date closed P&L proxy, with a fixed illustrative $1m account.
    equity = 1_000_000.0 + np.cumsum(daily_pnl)
    dd_pct, peak_idx, trough_idx = max_drawdown(np.r_[1_000_000.0, equity])
    peak_idx, trough_idx = max(0, peak_idx - 1), max(0, trough_idx - 1)
    dd_usd = float(np.min(equity - np.maximum.accumulate(np.r_[1_000_000.0, equity])[:-1]))
    cagr = float((equity[-1] / 1_000_000.0) ** (365.25 / days) - 1) if equity[-1] > 0 else None
    ret = daily_pnl / 1_000_000.0
    return {
        "calendar_days": days, "net_pnl_usd": float(daily_pnl.sum()),
        "daily_sharpe_usd": safe_sharpe(ret), "daily_sortino_usd": float(sortino_ratio(ret, 0.0, False) * np.sqrt(365.25)) if np.any(ret < 0) else None,
        "daily_sharpe_r_units": safe_sharpe(risk_daily),
        "max_drawdown_usd": dd_usd, "max_drawdown_pct": float(dd_pct),
        "drawdown_peak_index": int(peak_idx), "drawdown_trough_index": int(trough_idx),
        "cagr_1m_initial_capital": cagr,
        "calmar_1m_initial_capital": float(calmar_ratio(cagr, float(dd_pct))) if cagr is not None and dd_pct != 0 else None,
        "annualized_net_usd_over_max_drawdown_usd": float(daily_pnl.sum() * 365.25 / days / abs(dd_usd)) if dd_usd < 0 else None,
    }


def daily_panel(b0: pl.DataFrame, b2: pl.DataFrame, start: str, end: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[str]]:
    dates = pl.date_range(date.fromisoformat(start), date.fromisoformat(end), interval="1d", eager=True).dt.strftime("%Y-%m-%d").to_list()
    grid = pl.DataFrame({"utc_entry_date": dates})
    def daily(df: pl.DataFrame, val: str, alias: str) -> pl.DataFrame:
        return df.filter((pl.col("utc_entry_date") >= start) & (pl.col("utc_entry_date") <= end)).group_by("utc_entry_date").agg(pl.col(val).sum().alias(alias))
    b0d = grid.join(daily(b0, "pnl", "b0"), on="utc_entry_date", how="left").with_columns(pl.col("b0").fill_null(0.0))
    b2d = grid.join(daily(b2, "pnl", "b2"), on="utc_entry_date", how="left").with_columns(pl.col("b2").fill_null(0.0))
    b0r = grid.join(daily(b0.with_columns((pl.col("pnl") / 1000).alias("risk_r")), "risk_r", "b0r"), on="utc_entry_date", how="left").with_columns(pl.col("b0r").fill_null(0.0))
    b2r = grid.join(daily(b2.with_columns((pl.col("pnl") / pl.col("nominal_risk_usd")).alias("risk_r")), "risk_r", "b2r"), on="utc_entry_date", how="left").with_columns(pl.col("b2r").fill_null(0.0))
    return tuple(x.get_column(c).to_numpy() for x, c in [(b0d,"b0"),(b2d,"b2"),(b0r,"b0r"),(b2r,"b2r")]) + (dates,)


def block_bootstrap(a: np.ndarray, b: np.ndarray, block: int, seed: int, thresholds: tuple[float, ...]) -> dict:
    n = len(a)
    nblocks = int(np.ceil(n / block))
    rng = np.random.default_rng(seed + block)
    starts = rng.integers(0, n, size=(REPS, nblocks))
    idx = (starts[:, :, None] + np.arange(block)) % n
    idx = idx.reshape(REPS, -1)[:, :n]
    xa, xb = a[idx], b[idx]
    def mdd(mat: np.ndarray) -> np.ndarray:
        cum = np.cumsum(mat, axis=1)
        peaks = np.maximum.accumulate(np.concatenate([np.zeros((REPS, 1)), cum], axis=1), axis=1)[:, 1:]
        return np.min(cum - peaks, axis=1)
    def sharpe(mat: np.ndarray) -> np.ndarray:
        s = mat.std(axis=1, ddof=1)
        return np.divide(mat.mean(axis=1), s, out=np.full(REPS, np.nan), where=s > 0) * np.sqrt(365.25)
    da, db = mdd(xa), mdd(xb)
    sa, sb = sharpe(xa), sharpe(xb)
    delta = sb - sa
    term_a, term_b = xa.sum(axis=1), xb.sum(axis=1)
    def q(x: np.ndarray) -> list[float]:
        return [float(v) for v in np.nanquantile(x, [0.05, 0.5, 0.95])]
    return {
        "block_days": block, "replicates": REPS, "terminal_net_5_50_95": {"B0": q(term_a), "B2": q(term_b)},
        "prob_terminal_positive": {"B0": float(np.mean(term_a > 0)), "B2": float(np.mean(term_b > 0))},
        "max_drawdown_50_95": {"B0": q(-da)[1:], "B2": q(-db)[1:]},
        "prob_max_drawdown_exceeds_thresholds": {str(t): {"B0": float(np.mean(-da > t)), "B2": float(np.mean(-db > t))} for t in thresholds},
        "annualized_sharpe_5_50_95": {"B0": q(sa), "B2": q(sb)},
        "paired_sharpe_delta_B2_minus_B0_5_50_95": q(delta), "prob_B2_sharpe_gt_B0": float(np.mean(delta > 0)),
    }



def scale_b2_to_one_nq_equivalent(df: pl.DataFrame) -> pl.DataFrame:
    """Algebraic positive-quantity exposure scaling; NOT a new native Engine run."""
    if df.filter(pl.col("quantity") == 0).height:
        raise ValueError("cannot scale a zero-quantity trade")
    factor = 10.0 / pl.col("quantity").abs()
    return df.with_columns(
        (pl.col("pnl") * factor).alias("pnl"),
        (pl.col("nominal_risk_usd") * factor).alias("nominal_risk_usd"),
        (pl.col("fees") * factor).alias("fees"),
        (pl.col("total_slippage_cost") * factor).alias("total_slippage_cost"),
    )


def run() -> dict:
    b0, b0paths = load_ledgers("run_log/one_bar_practical_1m_20261012/by_year", "native_full_tick_cost")
    b2, b2paths = load_ledgers("run_log/one_bar_nq_stop_scaling_20261012/phase234/by_year", "B2_costed")
    if b0.height != 5462 or not np.isclose(b0.get_column("pnl").sum(), 166107.92, atol=0.02):
        raise AssertionError("B0 current annual ledgers do not match expected count/PnL")
    if b2.height != 5459 or not np.isclose(b2.get_column("pnl").sum(), -142674.93, atol=0.02):
        raise AssertionError("B2 current annual ledgers do not match independent review count/PnL")
    b2_r_error = b2.select((pl.col("pnl") / pl.col("nominal_risk_usd") - pl.col("r_multiple")).abs().max()).item()
    if b2_r_error > 1e-8:
        raise AssertionError("B2 stored risk multiple does not reconcile to net P&L / nominal risk")
    periods = {"full_historical": (START, END), "post_mnq_launch": (LAUNCH, END), "2020_2025": ("2020-01-01", "2025-12-31"), "2026_stress": ("2026-01-01", END), "pre_mnq_counterfactual": (START, "2019-05-05")}
    results, mc = {}, {}
    for name, (lo, hi) in periods.items():
        x0 = b0.filter((pl.col("utc_entry_date") >= lo) & (pl.col("utc_entry_date") <= hi)).with_columns(pl.lit(1000.0).alias("nominal_risk_usd"))
        # Apply the same UTC entry-date period boundary to B0 and B2.
        x2 = b2.filter((pl.col("utc_entry_date") >= lo) & (pl.col("utc_entry_date") <= hi))
        d0, d2, r0, r2, dates = daily_panel(x0, x2, lo, hi)
        results[name] = {
            "date_start": lo, "date_end": hi, "B0": trade_stats(x0, "B0"), "B2": trade_stats(x2, "B2"),
            "B0_daily": equity_stats(d0, r0, len(dates)), "B2_daily": equity_stats(d2, r2, len(dates)),
            "counterfactual_B2_scaled_to_1_NQ_equivalent": trade_stats(scale_b2_to_one_nq_equivalent(x2), "B2_linear_10_MNQ"),
        }
        if name in ("post_mnq_launch", "2026_stress"):
            mc[name] = {}
            for block in BLOCKS:
                mc[name][f"usd_block_{block}"] = block_bootstrap(d0, d2, block, SEED, (5000.0,))
                mc[name][f"risk_unit_block_{block}"] = block_bootstrap(r0, r2, block, SEED + 100, (5.0, 10.0))
    return {
        "status": "historical_review_only; NOT_APPROVED_FOR_LIVE", "seed": SEED, "replicates": REPS,
        "source_cutoff_inclusive_utc": END, "pnl_attribution": "closed-trade net P&L assigned to UTC entry date; zeros on all other calendar days; B2 reporting-period membership uses frozen Chicago session_day",
        "annualization": "365.25 calendar days; rf=0; sample standard deviation", "periods": results, "monte_carlo": mc,
        "source_files": {"B0": b0paths, "B2_costed": b2paths},
        "source_sha256": {"B0": {p: sha256(ROOT / p) for p in b0paths}, "B2_costed": {p: sha256(ROOT / p) for p in b2paths}},
        "limitations": ["BID-only CFD proxy; not dated CME futures", "pre-2019-05-06 MNQ is counterfactual", "annual B2 shards have documented GTC boundary leakage and duplicated entry fill", "trade-entry-day closed P&L is not native mark-to-market", "linear 1-NQ-equivalent B2 scaling is algebraic and ignores margin/impact", "moving-block bootstrap resamples this historical path and does not forecast future regimes", "2026 is observed stress evidence, not holdout"],
    }


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    result = run()
    (OUT / "metrics.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    flat = []
    for period, data in result["periods"].items():
        for strategy in ("B0", "B2", "counterfactual_B2_scaled_to_1_NQ_equivalent"):
            row = {"period": period, "strategy": strategy}
            row.update(data[strategy])
            row = {k: json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v for k, v in row.items()}
            flat.append(row)
    pl.DataFrame(flat, infer_schema_length=None).write_csv(OUT / "metrics.csv")
    (OUT / "monte_carlo.json").write_text(json.dumps(result["monte_carlo"], indent=2, allow_nan=False) + "\n")
