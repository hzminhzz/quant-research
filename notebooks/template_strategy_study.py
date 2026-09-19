# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "marimo>=0.24.0",
#     "polars>=1.20.0",
#     "altair>=5.0.0",
#     "scipy>=1.14.0",
#     "numpy>=1.26.0",
# ]
# ///

import marimo

__generated_with = "0.24.0"
app = marimo.App(width="medium", auto_download=["html"])


@app.cell(hide_code=True)
def setup():
    from pathlib import Path
    import altair as alt
    import marimo as mo
    import numpy as np
    import polars as pl
    import yaml

    from src.patterns import detect_engulfing
    from src.features import compute_ema, compute_rsi, compute_atr, compute_bollinger_bands
    from src.labeling import compute_forward_returns, triple_barrier_labels
    from src.backtest import run_intraday_backtest
    from src.pipeline import run_full_pipeline
    from src.experiment import TrialRecord, log_trial, load_trials, compute_deflated_sharpe

    alt.data_transformers.enable("default")

    return (
        Path,
        alt,
        mo,
        np,
        pl,
        yaml,
        detect_engulfing,
        compute_ema,
        compute_rsi,
        compute_atr,
        compute_bollinger_bands,
        compute_forward_returns,
        triple_barrier_labels,
        run_intraday_backtest,
        run_full_pipeline,
        TrialRecord,
        log_trial,
        load_trials,
        compute_deflated_sharpe,
    )


@app.cell
def header_markdown(mo):
    mo.md(r"""
    # 🔬 ML4T Quantitative Research Strategy Study Template
    *A standardized, reactive research notebook implementing the ML4T 4-Stage Strategy Protocol:*
    1. **Stage 1**: Feature Engineering & Volatility-Adaptive Labeling
    2. **Stage 2**: Factor Predictive Diagnostics (Rank IC & Decay)
    3. **Stage 3**: Event-Driven Backtesting with Institutional Friction
    4. **Stage 4**: Multiple-Testing Audit & Deflated Sharpe Ratio (DSR)
    """)


@app.cell
def config_ui(mo):
    symbol_select = mo.ui.dropdown(
        options=["SPX500/USD", "JP225/USD", "DE30/EUR"],
        value="JP225/USD",
        label="Target Symbol",
    )
    timeframe_select = mo.ui.dropdown(
        options=["15m", "1h", "4h", "1d"],
        value="15m",
        label="Timeframe",
    )
    holding_bars_slider = mo.ui.slider(
        start=4, stop=48, step=4, value=16, label="Holding Horizon (Bars)"
    )
    mo.hstack([symbol_select, timeframe_select, holding_bars_slider])
    return config_ui, holding_bars_slider, symbol_select, timeframe_select


@app.cell
def load_data(Path, np, pl, symbol_select):
    # Check for cached data or generate synthetic test sample
    _cache_file = Path(f"/tmp/lse_15m_cache/{symbol_select.value.replace('/', '_')}_15m_2019_2026.parquet")
    if _cache_file.exists():
        market_data = pl.read_parquet(_cache_file)
    else:
        # Generate synthetic benchmark series
        _rng = np.random.default_rng(100)
        _n = 2000
        _rets = _rng.normal(loc=0.0001, scale=0.004, size=_n)
        _prices = 100.0 * np.exp(np.cumsum(_rets))
        _highs = _prices * (1.0 + _rng.uniform(0.001, 0.003, size=_n))
        _lows = _prices * (1.0 - _rng.uniform(0.001, 0.003, size=_n))
        _opens = _prices * (1.0 + _rng.normal(0.0, 0.001, size=_n))
        _dts = [f"2024-01-01 {i//4:02d}:{(i%4)*15:02d}" for i in range(_n)]
        market_data = pl.DataFrame({
            "timestamp": _dts,
            "open": _opens,
            "high": _highs,
            "low": _lows,
            "close": _prices,
            "volume": _rng.integers(1000, 5000, size=_n),
        })

    return market_data,


@app.cell
def stage1_features(
    compute_atr,
    compute_bollinger_bands,
    compute_ema,
    compute_forward_returns,
    compute_rsi,
    detect_engulfing,
    market_data,
    triple_barrier_labels,
):
    # 1. Patterns
    _df = detect_engulfing(market_data)

    # 2. Reusable Features from src/features
    _df = compute_atr(_df, period=14, alias="atr")
    _df = compute_rsi(_df, period=14, alias="rsi")
    _df = compute_ema(_df, span=200, alias="ema_200")
    _df = compute_bollinger_bands(_df, period=20, num_std=2.0)

    # 3. Target Labels from src/labeling
    _df = compute_forward_returns(_df, horizons=[1, 4, 8, 16, 32])
    feature_data = triple_barrier_labels(_df, upper_mult=2.0, lower_mult=1.0, max_holding=16)

    return feature_data,


@app.cell
def stage2_diagnostics(feature_data, mo, np, pl):
    from scipy import stats

    _signal = (
        pl.col("is_bearish_engulfing") & (pl.col("rsi") < 40)
    ).alias("signal_contrarian")

    _df = feature_data.with_columns(_signal)

    # Compute Rank IC across forecast horizons
    _rows = []
    _sig_arr = _df["signal_contrarian"].cast(pl.Float64).to_numpy()

    for _h in [1, 4, 8, 16, 32]:
        _fwd = _df[f"fwd_ret_{_h}"].to_numpy()
        _mask = ~np.isnan(_sig_arr) & ~np.isnan(_fwd)
        _s_clean, _f_clean = _sig_arr[_mask], _fwd[_mask]
        if len(_s_clean) > 50 and not np.all(_s_clean == _s_clean[0]) and not np.all(_f_clean == _f_clean[0]):
            _corr, _p = stats.spearmanr(_s_clean, _f_clean)
        else:
            _corr, _p = 0.0, 1.0
        _rows.append({
            "Horizon (Bars)": _h,
            "Rank IC": round(float(_corr), 4),
            "p-value": round(float(_p), 4),
            "Quality Gate": "PASS" if _corr > 0.02 and _p < 0.05 else "FAIL",
        })

    diag_table = mo.ui.table(pl.DataFrame(_rows).to_dicts())
    return diag_table,


@app.cell
def stage3_backtest(feature_data, holding_bars_slider, mo, run_intraday_backtest):
    # Run institutional backtest
    _df = feature_data.with_columns(
        (feature_data["is_bearish_engulfing"] & (feature_data["rsi"] < 40)).alias("entry_signal")
    )

    bt_result = run_intraday_backtest(
        df=_df,
        entry_signal_col="entry_signal",
        holding_bars=holding_bars_slider.value,
        commission_bps=2.0,
        slippage_bps=1.0,
    )

    _kpis = mo.hstack([
        mo.stat(label="Total Return", value=f"{bt_result['total_return_pct']:.2f}%"),
        mo.stat(label="Annualized Sharpe", value=f"{bt_result['annualized_sharpe']:.2f}"),
        mo.stat(label="Max Drawdown", value=f"{bt_result['max_drawdown_pct']:.2f}%"),
        mo.stat(label="Total Trades", value=f"{bt_result['total_trades']}"),
        mo.stat(label="Win Rate", value=f"{bt_result['win_rate_pct']:.1f}%"),
    ])

    return bt_result, _kpis


@app.cell
def stage4_audit(
    TrialRecord,
    bt_result,
    compute_deflated_sharpe,
    holding_bars_slider,
    load_trials,
    log_trial,
    mo,
    symbol_select,
    timeframe_select,
):
    # Log trial
    _record = TrialRecord(
        trial_id=f"study-{symbol_select.value}-{timeframe_select.value}-h{holding_bars_slider.value}",
        strategy_name="Dip Buy Bearish Engulfing",
        symbol=symbol_select.value,
        timeframe=timeframe_select.value,
        parameters={"holding_bars": holding_bars_slider.value, "rsi_thresh": 40},
        total_return_pct=bt_result["total_return_pct"],
        annualized_sharpe=bt_result["annualized_sharpe"],
        max_drawdown_pct=bt_result["max_drawdown_pct"],
        win_rate_pct=bt_result["win_rate_pct"],
        total_trades=bt_result["total_trades"],
    )

    # Compute DSR against historical ledger
    _past = load_trials()
    _all_sr = [t["annualized_sharpe"] for t in _past] + [bt_result["annualized_sharpe"]]
    dsr_audit = compute_deflated_sharpe(
        observed_annualized_sharpe=bt_result["annualized_sharpe"],
        all_sharpes=_all_sr,
    )

    _audit_callout = mo.callout(
        mo.md(f"""
        ### 🛡️ Deflated Sharpe Ratio (DSR) & Multiple Testing Audit
        - **Total Historical Trials Documented**: `{dsr_audit['n_trials']}`
        - **Observed Sharpe**: `{dsr_audit['observed_sharpe']:.2f}`
        - **Haircut Sharpe (Bailey & López de Prado)**: `{dsr_audit['haircut_sharpe']:.2f}`
        - **DSR Statistical Probability**: `{dsr_audit['dsr_probability']:.3f}` *(Requires > 0.95 to reject noise)*
        """),
        kind="info" if dsr_audit["dsr_probability"] > 0.95 else "warn",
    )

    return dsr_audit, _record, _audit_callout


@app.cell
def render_ui(_audit_callout, _kpis, diag_table, mo):
    mo.vstack([
        mo.md("### 📊 Factor Diagnostic Quality Gates"),
        diag_table,
        mo.md("### 📈 Institutional Backtest Execution (2 bps fee + 1 bps slip)"),
        _kpis,
        _audit_callout,
    ])


if __name__ == "__main__":
    app.run()
