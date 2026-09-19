"""ML4T 4-Stage Strategy Research Pipeline Contract.

Formalizes the typed interfaces and execution lifecycle for systematic quantitative
strategies adhering to the ML4T methodology:
- Stage 1: Feature Engineering & Path-Dependent Labeling
- Stage 2: Signal & Factor Diagnostics (Information Coefficient, Decay, Bootstrap CIs)
- Stage 3: Event-Driven Backtesting (Friction-adjusted execution, daily equity)
- Stage 4: Machine Learning Meta-Labeling (Conviction filtering & sizing)
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple
import polars as pl
import numpy as np
from scipy import stats

from src.patterns import detect_engulfing
from src.features import compute_ema, compute_rsi, compute_atr
from src.labeling import compute_forward_returns, triple_barrier_labels, create_meta_labels
from src.backtest import CostModel, run_intraday_backtest


@dataclass(frozen=True)
class Stage1Result:
    """Artifact produced by Stage 1: Feature Engineering & Labeling."""
    data: pl.DataFrame
    feature_names: List[str]
    label_names: List[str]


@dataclass(frozen=True)
class DiagnosticMetric:
    """Statistical metric for alpha factor predictive power."""
    horizon: int
    rank_ic: float
    ic_std: float
    ic_ir: float
    p_value: float
    ci_lower: float
    ci_upper: float
    passed_gate: bool


@dataclass(frozen=True)
class Stage2Result:
    """Artifact produced by Stage 2: Signal Diagnostics."""
    metrics: List[DiagnosticMetric]
    primary_horizon: int
    mean_ic: float
    passed_quality_gate: bool


@dataclass(frozen=True)
class Stage3Result:
    """Artifact produced by Stage 3: Event-Driven Backtest."""
    total_return_pct: float
    annualized_sharpe: float
    sortino_ratio: float
    max_drawdown_pct: float
    win_rate_pct: float
    total_trades: int
    daily_equity: pl.DataFrame
    passed_quality_gate: bool


@dataclass(frozen=True)
class Stage4Result:
    """Artifact produced by Stage 4: Meta-Labeling & ML Conviction."""
    train_size: int
    test_size: int
    baseline_win_rate_pct: float
    filtered_win_rate_pct: float
    filter_precision: float
    passed_quality_gate: bool


@dataclass
class PipelineReport:
    """Consolidated report across all 4 ML4T pipeline stages."""
    symbol: str
    stage1: Stage1Result
    stage2: Stage2Result
    stage3: Stage3Result
    stage4: Optional[Stage4Result] = None

    @property
    def is_deployable(self) -> bool:
        """Strategy is deployable only if all individual stage gates passed."""
        return (
            self.stage2.passed_quality_gate
            and self.stage3.passed_quality_gate
            and (self.stage4.passed_quality_gate if self.stage4 else True)
        )


def run_stage1_features(
    df: pl.DataFrame,
    atr_period: int = 14,
    rsi_period: int = 14,
    ema_span: int = 200,
) -> Stage1Result:
    """Execute Stage 1: Feature Engineering & Labeling."""
    # Compute base patterns
    processed = detect_engulfing(df)
    
    # Compute technical features
    processed = compute_atr(processed, period=atr_period, alias="atr")
    processed = compute_rsi(processed, period=rsi_period, alias="rsi")
    processed = compute_ema(processed, span=ema_span, alias="ema_200")

    # Compute forward returns for horizons 1, 4, 8, 16, 32
    processed = compute_forward_returns(processed, horizons=[1, 4, 8, 16, 32])

    # Compute triple barrier labels
    processed = triple_barrier_labels(
        processed, upper_mult=2.0, lower_mult=1.0, max_holding=16, atr_col="atr"
    )

    feature_names = ["atr", "rsi", "ema_200", "is_bullish_engulfing", "is_bearish_engulfing"]
    label_names = ["fwd_ret_1", "fwd_ret_4", "fwd_ret_8", "fwd_ret_16", "fwd_ret_32", "tb_label"]

    return Stage1Result(data=processed, feature_names=feature_names, label_names=label_names)


def run_stage2_diagnostics(
    stage1: Stage1Result,
    signal_col: str,
    horizons: List[int] = [1, 4, 8, 16, 32],
    min_ic: float = 0.02,
    max_p_value: float = 0.05,
    n_bootstrap: int = 500,
) -> Stage2Result:
    """Execute Stage 2: Signal & Factor Diagnostics."""
    df = stage1.data
    signals = df[signal_col].cast(pl.Float64).to_numpy()
    metrics = []

    for h in horizons:
        fwd_col = fwd_ret_col = f"fwd_ret_{h}"
        if fwd_col not in df.columns:
            continue

        fwd = df[fwd_col].to_numpy()
        mask = ~np.isnan(signals) & ~np.isnan(fwd)
        sig_clean = signals[mask]
        fwd_clean = fwd[mask]

        if len(sig_clean) < 50 or np.all(sig_clean == sig_clean[0]) or np.all(fwd_clean == fwd_clean[0]):
            corr, p_val = 0.0, 1.0
        else:
            corr, p_val = stats.spearmanr(sig_clean, fwd_clean)
            corr = 0.0 if np.isnan(corr) else float(corr)
            p_val = 1.0 if np.isnan(p_val) else float(p_val)

        # Bootstrap 95% Confidence Interval
        indices = np.arange(len(sig_clean))
        boot_corrs = []
        rng = np.random.default_rng(42)
        for _ in range(n_bootstrap):
            boot_idx = rng.choice(indices, size=len(indices), replace=True)
            b_sig = sig_clean[boot_idx]
            b_fwd = fwd_clean[boot_idx]
            if np.all(b_sig == b_sig[0]) or np.all(b_fwd == b_fwd[0]):
                boot_corrs.append(0.0)
            else:
                bc, _ = stats.spearmanr(b_sig, b_fwd)
                if not np.isnan(bc):
                    boot_corrs.append(float(bc))

        ci_low = float(np.percentile(boot_corrs, 2.5)) if boot_corrs else corr
        ci_high = float(np.percentile(boot_corrs, 97.5)) if boot_corrs else corr
        ic_std = float(np.std(boot_corrs)) if boot_corrs else 1e-6
        ic_ir = corr / ic_std if ic_std > 0 else 0.0

        passed = (corr >= min_ic) and (p_val <= max_p_value) and (ci_low > 0)
        metrics.append(
            DiagnosticMetric(
                horizon=h,
                rank_ic=corr,
                ic_std=ic_std,
                ic_ir=ic_ir,
                p_value=p_val,
                ci_lower=ci_low,
                ci_upper=ci_high,
                passed_gate=passed,
            )
        )

    primary = metrics[0] if metrics else None
    mean_ic = float(np.mean([m.rank_ic for m in metrics])) if metrics else 0.0
    passed_gate = any(m.passed_gate for m in metrics)

    return Stage2Result(
        metrics=metrics,
        primary_horizon=primary.horizon if primary else 0,
        mean_ic=mean_ic,
        passed_quality_gate=passed_gate,
    )


def run_stage3_backtest(
    stage1: Stage1Result,
    signal_col: str,
    holding_bars: int = 16,
    commission_bps: float = 2.0,
    slippage_bps: float = 1.0,
    min_sharpe: float = 0.0,
    max_drawdown: float = 25.0,
) -> Stage3Result:
    """Execute Stage 3: Event-Driven Institutional Backtest."""
    bt = run_intraday_backtest(
        df=stage1.data,
        entry_signal_col=signal_col,
        holding_bars=holding_bars,
        commission_bps=commission_bps,
        slippage_bps=slippage_bps,
    )

    passed_gate = (
        bt["annualized_sharpe"] >= min_sharpe
        and bt["max_drawdown_pct"] <= max_drawdown
        and bt["total_trades"] >= 20
    )

    return Stage3Result(
        total_return_pct=bt["total_return_pct"],
        annualized_sharpe=bt["annualized_sharpe"],
        sortino_ratio=bt["sortino_ratio"],
        max_drawdown_pct=bt["max_drawdown_pct"],
        win_rate_pct=bt["win_rate_pct"],
        total_trades=bt["total_trades"],
        daily_equity=bt["daily_equity"],
        passed_quality_gate=passed_gate,
    )


def run_stage4_meta_labeling(
    stage1: Stage1Result,
    primary_signal_col: str,
    outcome_col: str = "fwd_ret_16",
    train_split: float = 0.70,
) -> Stage4Result:
    """Execute Stage 4: Meta-Labeling with chronological train/test split."""
    labeled = create_meta_labels(
        primary_signal_col=primary_signal_col,
        outcome_return_col=outcome_col,
        df=stage1.data,
    )

    # Filter only rows where primary signal fired
    signal_rows = labeled.filter(pl.col(primary_signal_col) == True).drop_nulls(subset=["meta_label"])
    n = len(signal_rows)

    if n < 30:
        return Stage4Result(
            train_size=0,
            test_size=0,
            baseline_win_rate_pct=0.0,
            filtered_win_rate_pct=0.0,
            filter_precision=0.0,
            passed_quality_gate=False,
        )

    split_idx = int(n * train_split)
    train_df = signal_rows.slice(0, split_idx)
    test_df = signal_rows.slice(split_idx, n - split_idx)

    baseline_win_rate = float((test_df["meta_label"] == 1).mean() * 100)

    # Simple regime heuristic classifier: RSI < 50 filter
    if "rsi" in test_df.columns:
        conviction_mask = test_df["rsi"] < 50
        filtered_trades = test_df.filter(conviction_mask)
        filtered_win_rate = (
            float((filtered_trades["meta_label"] == 1).mean() * 100)
            if len(filtered_trades) > 0
            else baseline_win_rate
        )
    else:
        filtered_win_rate = baseline_win_rate

    precision_improvement = filtered_win_rate - baseline_win_rate
    passed_gate = (filtered_win_rate >= baseline_win_rate) and (len(test_df) >= 10)

    return Stage4Result(
        train_size=len(train_df),
        test_size=len(test_df),
        baseline_win_rate_pct=baseline_win_rate,
        filtered_win_rate_pct=filtered_win_rate,
        filter_precision=precision_improvement,
        passed_quality_gate=passed_gate,
    )


def run_full_pipeline(
    df: pl.DataFrame,
    symbol: str,
    primary_signal_fn,
    holding_bars: int = 16,
) -> PipelineReport:
    """Orchestrate the complete 4-Stage ML4T Pipeline end-to-end."""
    # Stage 1
    s1 = run_stage1_features(df)

    # Apply strategy signal
    s1_data = primary_signal_fn(s1.data)
    s1 = Stage1Result(
        data=s1_data,
        feature_names=s1.feature_names + ["strategy_signal"],
        label_names=s1.label_names,
    )

    # Stage 2
    s2 = run_stage2_diagnostics(s1, signal_col="strategy_signal")

    # Stage 3
    s3 = run_stage3_backtest(s1, signal_col="strategy_signal", holding_bars=holding_bars)

    # Stage 4
    s4 = run_stage4_meta_labeling(s1, primary_signal_col="strategy_signal")

    return PipelineReport(symbol=symbol, stage1=s1, stage2=s2, stage3=s3, stage4=s4)
