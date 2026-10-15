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

from src.features import compute_atr
from src.labeling import compute_forward_returns, triple_barrier_labels
from src.diagnostics import evaluate_factor
from src.backtest import run_intraday_backtest
from src.synthesis import generate_tearsheet_metrics


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


def test_stage4_diagnostics_contract():
    """Test signal diagnostic reporting with IC, HAC stats, and decay."""
    df = make_synthetic_ohlcv(300)
    df = compute_forward_returns(df, horizons=[1, 4, 8, 16])
    df = df.with_columns((pl.col("close") > pl.col("open")).cast(pl.Int32).alias("signal"))

    rep = evaluate_factor(df, signal_col="signal", return_col="fwd_ret_8")
    assert -1.0 <= rep.mean_ic <= 1.0
    assert "hac_t_stat" in dir(rep)
    assert "decay_profile" in dir(rep)


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

    # Stage 6 inputs: the run must actually trade. A zero-trade backtest makes
    # every downstream metric vacuous (win rate 0, profit factor 1, Sharpe 0)
    # and would still satisfy a >= 0 assertion.
    assert bt["total_trades"] > 0
    assert bt["total_trades"] <= int(df["signal"].sum())
    assert bt["ending_equity"] > 0.0
    assert 0.0 <= bt["max_drawdown_pct"] <= 100.0

    # Stage 6 artifact: a settled, ordered daily equity series. Stage 7 refuses
    # to synthesise fewer than 10 daily observations.
    daily = bt["daily_equity"]
    assert daily is not None and daily.height >= 10
    dates = daily["date"].to_list()
    assert dates == sorted(dates)
    assert len(dates) == len(set(dates))
    assert daily["equity"].min() > 0.0

    # Synthesis
    tearsheet = generate_tearsheet_metrics(
        daily_equity_df=daily,
        total_trades=bt["total_trades"],
        win_rate_pct=bt["win_rate_pct"],
        profit_factor=bt["profit_factor"],
        rank_ic=0.04,
        p_value=0.01,
        n_trials=50,
    )
    assert "error" not in tearsheet

    # Pass-through contract: synthesis echoes the backtest values and the
    # diagnostics it was handed instead of recomputing or dropping them.
    assert tearsheet["total_trades"] == bt["total_trades"]
    assert tearsheet["win_rate_pct"] == bt["win_rate_pct"]
    assert tearsheet["profit_factor"] == bt["profit_factor"]
    assert tearsheet["rank_ic"] == 0.04
    assert tearsheet["p_value"] == 0.01

    # Reconciliation: tearsheet returns must follow the daily equity supplied.
    # generate_tearsheet_metrics drops the leading null pct_change row, so the
    # first usable mark is daily row 1.
    settled = daily["equity"].to_numpy()[1:]
    assert tearsheet["total_return_pct"] == pytest.approx(
        (settled[-1] / settled[0] - 1.0) * 100.0, rel=1e-12
    )
    assert tearsheet["n_daily_obs"] == daily.height - 1

    peak = np.maximum.accumulate(settled)
    expected_drawdown = float(np.abs(((settled - peak) / peak).min()) * 100.0)
    assert tearsheet["max_drawdown_pct"] == pytest.approx(expected_drawdown, rel=1e-12)

    # Every headline metric must be a finite number, never NaN or inf.
    for key in (
        "annualized_sharpe",
        "sortino_ratio",
        "calmar_ratio",
        "total_return_pct",
        "max_drawdown_pct",
        "dsr_probability",
        "dsr_haircut_sharpe",
    ):
        assert np.isfinite(tearsheet[key]), f"{key} is not finite: {tearsheet[key]}"

    # Deflation must move the Sharpe down, and the confidence interval must
    # bracket the point estimate it belongs to.
    assert 0.0 <= tearsheet["dsr_probability"] <= 1.0
    assert tearsheet["dsr_haircut_sharpe"] < tearsheet["annualized_sharpe"]
    lower_ci, upper_ci = tearsheet["sharpe_95_ci"]
    assert lower_ci <= tearsheet["annualized_sharpe"] <= upper_ci
