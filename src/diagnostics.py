"""Alpha Factor Evaluation & Signal Diagnostics Engine.

Governed by ML4T Skills:
- ml4t-evaluate-factor
- ml4t-information-coefficient
- ml4t-horizon-design

Provides rigorous statistical evaluation of predictive signals before running
event-driven backtests:
1. Cross-sectional and time-series Spearman Rank Information Coefficient (Rank IC)
2. HAC (Newey-West) autocorrelation-adjusted standard errors and t-statistics
3. Quantile monotonicity (Q1 -> Q5) and turnover analysis
4. IC Decay profiling across multiple forecast horizons (1, 4, 8, 16, 20, 32 bars)
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import polars as pl
from scipy import stats

import ml4t.diagnostic as mld
from ml4t.diagnostic.api import compute_ic_hac_stats


@dataclass(frozen=True)
class FactorDiagnosticReport:
    """Statistical summary of factor predictive quality."""
    factor_name: str
    mean_ic: float
    ic_std: float
    ic_ir: float
    hac_t_stat: float
    hac_p_value: float
    is_statistically_significant: bool
    quantile_returns: Dict[str, float]
    is_monotonic: bool
    decay_profile: Dict[int, float]
    passed_quality_gate: bool


def compute_spearman_rank_ic(
    signal: np.ndarray,
    returns: np.ndarray,
) -> Tuple[float, float]:
    """Compute Spearman Rank IC and standard p-value between signal and forward return."""
    mask = ~np.isnan(signal) & ~np.isnan(returns)
    s_clean, r_clean = signal[mask], returns[mask]
    if len(s_clean) < 15 or np.all(s_clean == s_clean[0]) or np.all(r_clean == r_clean[0]):
        return 0.0, 1.0
    corr, p = stats.spearmanr(s_clean, r_clean)
    return float(corr), float(p)


def compute_ic_decay(
    df: pl.DataFrame,
    signal_col: str,
    price_col: str = "close",
    horizons: List[int] = [1, 4, 8, 16, 20, 32],
    group_col: Optional[str] = None,
) -> Dict[int, float]:
    """Measure signal decay across multiple forecast horizons.
    
    Identifies the natural alpha horizon and rebalance frequency.
    """
    decay_results = {}
    sig_arr = df[signal_col].to_numpy()
    
    for h in horizons:
        fwd_expr = pl.col(price_col).pct_change(h).shift(-h)
        if group_col and group_col in df.columns:
            fwd_expr = fwd_expr.over(group_col)
        fwd_arr = df.select(fwd_expr).to_series().to_numpy()
        
        ic, _ = compute_spearman_rank_ic(sig_arr, fwd_arr)
        decay_results[h] = round(ic, 4)
        
    return decay_results


def compute_quantile_spreads(
    signal: np.ndarray,
    returns: np.ndarray,
    n_quantiles: int = 5,
) -> Tuple[Dict[str, float], bool]:
    """Calculate mean forward return by signal quintile and check monotonicity."""
    mask = ~np.isnan(signal) & ~np.isnan(returns)
    s_clean, r_clean = signal[mask], returns[mask]
    if len(s_clean) < n_quantiles * 10:
        return {f"Q{q}": 0.0 for q in range(1, n_quantiles + 1)}, False

    # Rank signal into quantiles 1..n_quantiles
    ranks = stats.rankdata(s_clean, method="average")
    quantiles = np.ceil(ranks / len(ranks) * n_quantiles).astype(int)

    q_returns = {}
    vals = []
    for q in range(1, n_quantiles + 1):
        q_mask = quantiles == q
        mean_ret = float(np.mean(r_clean[q_mask])) if q_mask.sum() > 0 else 0.0
        q_returns[f"Q{q}"] = mean_ret
        vals.append(mean_ret)

    # Monotonicity check: strictly non-decreasing or strictly non-increasing
    is_ascending = all(x <= y for x, y in zip(vals, vals[1:]))
    is_descending = all(x >= y for x, y in zip(vals, vals[1:]))
    is_monotonic = is_ascending or is_descending

    return q_returns, is_monotonic


def evaluate_factor(
    df: pl.DataFrame,
    signal_col: str,
    return_col: str,
    timestamp_col: str = "timestamp",
    min_ic: float = 0.015,
    max_p_value: float = 0.05,
    horizons: List[int] = [1, 4, 8, 16, 20, 32],
) -> FactorDiagnosticReport:
    """Full ML4T Factor Evaluation Pipeline.
    
    Combines First-Principles stats with ml4t-diagnostic HAC corrections.
    """
    signal_arr = df[signal_col].to_numpy().astype(float)
    return_arr = df[return_col].to_numpy().astype(float)
    
    # 1. Overall & Pooled Rank IC via ml4t.diagnostic
    mask = ~np.isnan(signal_arr) & ~np.isnan(return_arr)
    s_clean = signal_arr[mask]
    r_clean = return_arr[mask]

    if len(s_clean) > 50 and not (np.all(s_clean == s_clean[0]) or np.all(r_clean == r_clean[0])):
        pooled_res = mld.metrics.pooled_ic(s_clean, r_clean, method="spearman", confidence_intervals=True)
        mean_ic = float(pooled_res["ic"])
        p_val = float(pooled_res["p_value"])
    else:
        mean_ic, p_val = 0.0, 1.0

    # 2. Block IC series for HAC t-stat (blocks of 20 bars to match label horizon)
    block_size = 20
    n_blocks = len(s_clean) // block_size
    ic_series = []
    for b in range(n_blocks):
        sb = s_clean[b * block_size : (b + 1) * block_size]
        rb = r_clean[b * block_size : (b + 1) * block_size]
        if not (np.all(sb == sb[0]) or np.all(rb == rb[0])):
            c, _ = stats.spearmanr(sb, rb)
            if not np.isnan(c):
                ic_series.append(c)

    if len(ic_series) >= 10 and np.std(ic_series) > 1e-6:
        ic_arr = np.array(ic_series)
        ic_std = float(np.std(ic_arr))
        ic_ir = mean_ic / (ic_std + 1e-8)
        hac_stats = compute_ic_hac_stats(ic_arr, label_horizon=4)
        t_stat = float(hac_stats["t_stat"])
        hac_p = float(hac_stats["p_value"])
    else:
        ic_std = 0.05
        ic_ir = mean_ic / ic_std
        t_stat = mean_ic * np.sqrt(max(len(s_clean), 1))
        hac_p = p_val

    # 3. Quantile spreads
    q_returns, is_monotonic = compute_quantile_spreads(signal_arr, return_arr)

    # 4. IC Decay across forecast horizons
    decay_profile = compute_ic_decay(df, signal_col=signal_col, horizons=horizons)

    # Quality Gate Assessment
    passed_gate = bool(
        abs(mean_ic) >= min_ic
        and hac_p <= max_p_value
    )

    return FactorDiagnosticReport(
        factor_name=signal_col,
        mean_ic=mean_ic,
        ic_std=ic_std,
        ic_ir=ic_ir,
        hac_t_stat=t_stat,
        hac_p_value=hac_p,
        is_statistically_significant=(hac_p < 0.05),
        quantile_returns=q_returns,
        is_monotonic=is_monotonic,
        decay_profile=decay_profile,
        passed_quality_gate=passed_gate,
    )
