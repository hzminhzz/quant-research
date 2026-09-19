"""Financial Target Labeling Engine.

Implements path-dependent labeling techniques following Stefan Jansen's ML4T and
Marcos López de Prado's methodology:
1. Triple-Barrier Method with Volatility Scaling (ATR / Realized Vol)
2. Meta-Labeling (secondary binary classification for primary trading signals)
3. Multi-Horizon Forward Returns for IC Profiling
"""

from typing import List, Optional
import polars as pl
import numpy as np


def compute_forward_returns(
    df: pl.DataFrame,
    horizons: List[int] = [1, 4, 8, 16, 32],
    price_col: str = "close",
    group_col: Optional[str] = None,
) -> pl.DataFrame:
    """Compute forward returns across multiple prediction horizons.

    NOTE: Forward returns look ahead by construction and MUST ONLY be used as
    target variables (y) in Stage 2 diagnostics or Stage 4 model training.
    """
    exprs = []
    for h in horizons:
        expr = pl.col(price_col).pct_change(h).shift(-h)
        if group_col and group_col in df.columns:
            expr = expr.over(group_col)
        exprs.append(expr.alias(f"fwd_ret_{h}"))
    return df.with_columns(exprs)


def triple_barrier_labels(
    df: pl.DataFrame,
    upper_mult: float = 2.0,
    lower_mult: float = 1.0,
    max_holding: int = 16,
    atr_col: str = "atr",
    price_col: str = "close",
) -> pl.DataFrame:
    """Compute Triple Barrier Labels: +1 (Profit Target), -1 (Stop Loss), 0 (Time Expiry).

    Barriers adapt dynamically to current volatility via the specified ATR column.
    """
    prices = df[price_col].to_numpy()
    atrs = df[atr_col].to_numpy()
    n = len(prices)

    labels = np.full(n, np.nan)
    holding_bars = np.full(n, np.nan)
    trade_returns = np.full(n, np.nan)

    for i in range(n - max_holding):
        entry_price = prices[i]
        vol = atrs[i]
        if np.isnan(vol) or vol <= 0:
            continue

        upper_barrier = entry_price + (vol * upper_mult)
        lower_barrier = entry_price - (vol * lower_mult)

        # Default to time expiry (0.0)
        hit_label = 0.0
        hit_bar = max_holding
        exit_price = prices[i + max_holding]

        for j in range(1, max_holding + 1):
            curr = prices[i + j]
            if curr >= upper_barrier:
                hit_label = 1.0
                hit_bar = j
                exit_price = curr
                break
            elif curr <= lower_barrier:
                hit_label = -1.0
                hit_bar = j
                exit_price = curr
                break

        labels[i] = hit_label
        holding_bars[i] = hit_bar
        trade_returns[i] = (exit_price - entry_price) / entry_price

    return df.with_columns([
        pl.Series("tb_label", labels),
        pl.Series("tb_holding_bars", holding_bars),
        pl.Series("tb_return", trade_returns),
    ])


def create_meta_labels(
    primary_signal_col: str,
    outcome_return_col: str,
    df: pl.DataFrame,
    profit_threshold: float = 0.0,
) -> pl.DataFrame:
    """Create binary meta-labels (1 = take trade, 0 = pass).

    Meta-labeling models whether a primary trade signal will be profitable after
    costs, allowing a secondary ML model to size or filter trades without learning
    direction from scratch.
    """
    is_signal = pl.col(primary_signal_col) != 0
    is_profitable = pl.col(outcome_return_col) > profit_threshold

    meta_label_expr = (
        pl.when(is_signal & is_profitable)
        .then(1)
        .when(is_signal & ~is_profitable)
        .then(0)
        .otherwise(None)
    )

    return df.with_columns(meta_label_expr.alias("meta_label"))
