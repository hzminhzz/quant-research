"""Integration and Contract Tests for the ML4T 7-Stage Case Study Pipeline.

Governed by ML4T Skills:
- ml4t-case-study-pipeline
- ml4t-triple-barrier
- ml4t-compute-features
- ml4t-evaluate-factor
- ml4t-cpcv
- ml4t-run-backtest
- ml4t-deflated-sharpe
"""

import numpy as np
import polars as pl
import pytest

from src.features import compute_atr, compute_bollinger_bands, compute_ema, compute_rsi
from src.labeling import compute_forward_returns, create_meta_labels, triple_barrier_labels
from src.diagnostics import evaluate_factor
from src.models import train_meta_model_cpcv
from src.backtest import CostModel, run_intraday_backtest
from src.synthesis import compute_dsr_audit, generate_tearsheet_metrics
from src.pipeline import ML4TCaseStudyPipeline, StageContract


def make_synthetic_ohlcv(n_bars: int = 400) -> pl.DataFrame:
    """Generate realistic synthetic OHLCV data for pipeline testing."""
    rng = np.random.default_rng(42)
    dt_range = [f"2024-01-01 {i//4:02d}:{(i%4)*15:02d}" for i in range(n_bars)]

    returns = rng.normal(loc=0.0002, scale=0.005, size=n_bars)
    prices = 100.0 * np.exp(np.cumsum(returns))

    highs = prices * (1.0 + rng.uniform(0.001, 0.004, size=n_bars))
    lows = prices * (1.0 - rng.uniform(0.001, 0.004, size=n_bars))
    opens = prices * (1.0 + rng.normal(0.0, 0.001, size=n_bars))
    volumes = rng.integers(500, 5000, size=n_bars)

    return pl.DataFrame({
        "timestamp": dt_range,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": prices,
        "volume": volumes,
    })


def test_stage2_labeling_contract():
    """Test that triple-barrier and forward returns adhere to the label contract."""
    df = make_synthetic_ohlcv(300)
    df = compute_atr(df, period=14, alias="atr")
    df_labels = triple_barrier_labels(df, upper_mult=2.0, lower_mult=1.0, max_holding=16, atr_col="atr")
    assert "tb_label" in df_labels.columns
    assert "tb_holding_bars" in df_labels.columns
    assert "tb_return" in df_labels.columns

    raw_labels = df_labels["tb_label"].to_list()
    valid_labels = [l for l in raw_labels if l is not None and not np.isnan(l)]
    assert len(valid_labels) > 0
    assert all(l in [-1.0, 0.0, 1.0] for l in valid_labels)

    # Forward returns
    df_fwd = compute_forward_returns(df, horizons=[1, 4, 8, 16])
    for h in [1, 4, 8, 16]:
        assert f"fwd_ret_{h}" in df_fwd.columns


def test_stage3_features_contract():
    """Test feature engineering transforms with strictly non-leaking indicators."""
    df = make_synthetic_ohlcv(300)
    df = compute_rsi(df, period=14, alias="rsi_14")
    df = compute_ema(df, span=50, alias="ema_50")
    df = compute_atr(df, period=14, alias="atr_14")

    assert "rsi_14" in df.columns
    assert "ema_50" in df.columns
    assert "atr_14" in df.columns

    # Check bounds
    valid_rsi = df["rsi_14"].drop_nulls()
    assert (valid_rsi >= 0.0).all() and (valid_rsi <= 100.0).all()


def test_stage4_diagnostics_contract():
    """Test signal diagnostic reporting with IC, HAC stats, and decay."""
    df = make_synthetic_ohlcv(300)
    df = compute_forward_returns(df, horizons=[1, 4, 8, 16])
    df = df.with_columns((pl.col("close") > pl.col("open")).cast(pl.Int32).alias("signal"))

    rep = evaluate_factor(df, signal_col="signal", return_col="fwd_ret_8")
    assert -1.0 <= rep.mean_ic <= 1.0
    assert "hac_t_stat" in dir(rep)
    assert "decay_profile" in dir(rep)


def test_stage5_cpcv_models_contract():
    """Test combinatorial purged cross validation meta-model training."""
    rng = np.random.default_rng(42)
    X = rng.normal(size=(120, 4))
    y_meta = (X[:, 0] + rng.normal(scale=0.5, size=120) > 0).astype(int)
    active_mask = np.ones(120, dtype=bool)

    cpcv_res = train_meta_model_cpcv(
        X,
        y_meta,
        active_mask,
        n_groups=4,
        n_test_groups=1,
        label_horizon=4,
        embargo_size=1,
    )
    assert cpcv_res.n_splits >= 1
    assert 0.0 <= cpcv_res.mean_auc <= 1.0
    assert len(cpcv_res.oof_probabilities) == 120


def test_stage6_and_7_backtest_and_synthesis_contract():
    """Test backtest simulation and Deflated Sharpe Ratio calculation."""
    # Generate sufficient days so daily equity has > 10 daily return observations
    n_bars = 1000
    rng = np.random.default_rng(42)
    dt_range = [f"2024-01-{(i//24)+1:02d} {i%24:02d}:00" for i in range(n_bars)]
    returns = rng.normal(loc=0.0002, scale=0.005, size=n_bars)
    prices = 100.0 * np.exp(np.cumsum(returns))
    highs = prices * (1.0 + rng.uniform(0.001, 0.004, size=n_bars))
    lows = prices * (1.0 - rng.uniform(0.001, 0.004, size=n_bars))
    opens = prices * (1.0 + rng.normal(0.0, 0.001, size=n_bars))
    volumes = rng.integers(500, 5000, size=n_bars)

    df = pl.DataFrame({
        "timestamp": dt_range,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": prices,
        "volume": volumes,
    })
    df = df.with_columns((pl.col("close") > pl.col("open")).cast(pl.Int32).alias("signal"))

    bt = run_intraday_backtest(
        df,
        entry_signal_col="signal",
        holding_bars=4,
        commission_bps=2.0,
        slippage_bps=1.0,
    )

    assert bt["total_trades"] >= 0
    assert bt["daily_equity"] is not None

    # Synthesis
    tearsheet = generate_tearsheet_metrics(
        daily_equity_df=bt["daily_equity"],
        total_trades=bt["total_trades"],
        win_rate_pct=bt["win_rate_pct"],
        profit_factor=bt["profit_factor"],
        rank_ic=0.04,
        p_value=0.01,
        n_trials=50,
    )
    assert "annualized_sharpe" in tearsheet
    assert "total_return_pct" in tearsheet
    assert "max_drawdown_pct" in tearsheet
    assert "dsr_probability" in tearsheet
    assert 0.0 <= tearsheet["dsr_probability"] <= 1.0


def test_pipeline_contract_dataclass():
    """Verify StageContract integrity."""
    contract = StageContract(
        stage_id=1,
        stage_name="Setup",
        reads_from=["config/setup.yaml"],
        writes_to=["data/processed/prices.parquet"],
        passed_gate=True,
    )
    assert contract.stage_id == 1
    assert contract.passed_gate is True
