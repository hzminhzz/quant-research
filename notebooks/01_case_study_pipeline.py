# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "altair>=5.0.0",
#     "marimo>=0.24.0",
#     "ml4t-backtest",
#     "ml4t-diagnostic",
#     "ml4t-engineer",
#     "numpy>=1.26.0",
#     "polars>=1.20.0",
#     "scikit-learn>=1.4.0",
#     "scipy>=1.14.0",
# ]
# ///

import marimo

__generated_with = "0.24.2"
app = marimo.App(width="medium", auto_download=["html"])

with app.setup(hide_code=True):
    from pathlib import Path
    import json
    import altair as alt
    import marimo as mo
    import numpy as np
    import polars as pl
    import yaml

    from src.pipeline import ML4TCaseStudyPipeline
    from src.synthesis import compute_dsr_audit, load_strategy_trials

    alt.data_transformers.enable("default")


@app.cell
def header_markdown(mo):
    _header = mo.md(
        r"""
# 🏛️ ML4T 7-Stage Case Study Pipeline
### Institutional Systematic Strategy Research Architecture
**Standard**: Stefan Jansen's *Machine Learning for Algorithmic Trading* (ML4T) & Marcos López de Prado

```
[1. Setup]     setup.yaml: hypothesis, universe, label horizon, CV folds
     │
[2. Labels]    prices ──> forward returns & triple-barrier labels (data/labels/)
     │
[3. Features]  prices ──> momentum, volatility, microstructure (data/features/)
     │
[4. Evaluate]  features + labels ──> Rank IC, HAC t-stat, decay (run_log/diagnostics/)
     │
[5. Models]    features + labels + CPCV ──> predictions per fold (run_log/models/{hash}/)
     │
[6. Backtest]  predictions ──> event-driven simulation (run_log/strategy/{hash}/)
     │
[7. Synthesis] all results ──> DSR, tearsheets, final production signoff
```
"""
    )
    return (_header,)


@app.cell
def ui_controls():
    asset_select = mo.ui.dropdown(
        options=["DE30/EUR", "JP225/USD"],
        value="DE30/EUR",
        label="Target Universe Asset",
    )
    stage_select = mo.ui.dropdown(
        options=[
            "All 7 Stages (End-to-End)",
            "Stage 1: Setup & Canonical Prices",
            "Stage 2: Triple-Barrier Labels",
            "Stage 3: Feature Engineering",
            "Stage 4: Factor Diagnostics (Rank IC)",
            "Stage 5: CPCV Meta-Model",
            "Stage 6: Institutional Backtest",
            "Stage 7: DSR Multiple-Testing Synthesis",
        ],
        value="All 7 Stages (End-to-End)",
        label="Inspection Pipeline Stage",
    )

    controls_panel = mo.vstack([
        mo.md("### ⚙️ Pipeline Execution & Artifact Inspector"),
        mo.hstack([asset_select, stage_select], justify="start", gap=2),
    ])
    return asset_select, controls_panel, stage_select


@app.cell
def display_controls(controls_panel):
    controls_panel
    return


@app.cell
def run_pipeline_stages(asset_select):
    pipeline = ML4TCaseStudyPipeline(config_path="config/setup.yaml")
    sym = asset_select.value

    # Execute all 7 stages deterministically
    s1 = pipeline.run_stage1_setup(sym)
    s2 = pipeline.run_stage2_labels(sym)
    s3 = pipeline.run_stage3_features(sym)
    s4, diag_rep = pipeline.run_stage4_evaluate(sym)
    s5, cpcv_res = pipeline.run_stage5_models(sym)
    s6, bt_res = pipeline.run_stage6_backtest(sym, s5)
    s7, synth_metrics = pipeline.run_stage7_synthesis(sym, bt_res, diag_rep)

    return (
        bt_res,
        cpcv_res,
        diag_rep,
        pipeline,
        s1,
        s2,
        s3,
        s4,
        s5,
        s6,
        s7,
        sym,
        synth_metrics,
    )


@app.cell
def artifact_contracts_table(s1, s2, s3, s4, s5, s6, s7):
    _stages = [s1, s2, s3, s4, s5, s6, s7]
    _rows = []
    for s in _stages:
        _rows.append({
            "Stage": f"{s.stage_id}. {s.stage_name}",
            "Input Artifact": s.reads_from[0] if s.reads_from else "setup.yaml",
            "Output Artifact": s.writes_to[0],
            "Gate Check": "✅ PASS" if s.passed_gate else "⚠️ REVIEW",
        })

    contracts_table = mo.ui.table(_rows)
    return (contracts_table,)


@app.cell
def display_contracts(contracts_table):
    mo.vstack([
        mo.md("### 📦 7-Stage Artifact Contracts & Storage Hierarchy"),
        contracts_table,
    ])
    return


@app.cell
def diagnostics_view(diag_rep):
    _ic = diag_rep.mean_ic
    _p = diag_rep.hac_p_value
    _t = diag_rep.hac_t_stat
    _ir = diag_rep.ic_ir

    # IC Decay bar chart across horizons
    _decay_data = [{"Horizon (Bars)": f"{h}h", "Rank IC": ic} for h, ic in diag_rep.decay_profile.items()]
    _df_decay = pl.DataFrame(_decay_data).to_pandas()

    _chart = (
        alt.Chart(_df_decay)
        .mark_bar(color="#3498db")
        .encode(
            x=alt.X("Horizon (Bars):N", title="Forecast Horizon"),
            y=alt.Y("Rank IC:Q", title="Spearman Rank IC"),
            tooltip=["Horizon (Bars):N", "Rank IC:Q"],
        )
        .properties(width="container", height=240, title="Factor IC Decay Profile (Decay across Holding Horizons)")
    )

    diag_section = mo.vstack([
        mo.md("### 🔬 Stage 4: Factor Predictive Diagnostics"),
        mo.hstack([
            mo.stat(label="Mean Rank IC", value=f"{_ic:.4f}"),
            mo.stat(label="HAC p-value", value=f"{_p:.4e}"),
            mo.stat(label="HAC t-statistic", value=f"{_t:.2f}"),
            mo.stat(label="Information Ratio (IC_IR)", value=f"{_ir:.2f}"),
        ]),
        mo.ui.altair_chart(_chart),
    ])
    return (diag_section,)


@app.cell
def display_diagnostics(diag_section):
    diag_section
    return


@app.cell
def cpcv_view(cpcv_res):
    _auc = cpcv_res.mean_auc
    _base_wr = cpcv_res.baseline_win_rate * 100.0
    _filt_wr = cpcv_res.filtered_win_rate * 100.0
    _prec = cpcv_res.precision * 100.0

    cpcv_section = mo.vstack([
        mo.md("### 🤖 Stage 5: Machine Learning Meta-Model (Combinatorial Purged CV)"),
        mo.hstack([
            mo.stat(label="CPCV Mean AUC", value=f"{_auc:.3f}", caption=f"+/- {cpcv_res.std_auc:.3f}"),
            mo.stat(label="Baseline Win Rate", value=f"{_base_wr:.1f}%", caption="Raw primary signal"),
            mo.stat(label="Meta-Filtered Win Rate", value=f"{_filt_wr:.1f}%", caption="P(win) >= 0.52"),
            mo.stat(label="Precision", value=f"{_prec:.1f}%", caption="Quality filtered"),
            mo.stat(label="Combinations", value=f"{cpcv_res.n_splits} splits", caption=f"{cpcv_res.n_paths} backtest paths"),
        ]),
    ])
    return (cpcv_section,)


@app.cell
def display_cpcv(cpcv_section):
    cpcv_section
    return


@app.cell
def backtest_view(bt_res, sym):
    _sr = bt_res["annualized_sharpe"]
    _ret = bt_res["total_return_pct"]
    _dd = bt_res["max_drawdown_pct"]
    _trades = bt_res["total_trades"]
    _pf = bt_res["profit_factor"]

    _eq = bt_res["daily_equity"].to_pandas()
    _chart = (
        alt.Chart(_eq)
        .mark_line(color="#27ae60", strokeWidth=2)
        .encode(
            x=alt.X("date:T", title="Date"),
            y=alt.Y("equity:Q", title="Portfolio Equity ($)", scale=alt.Scale(zero=False)),
            tooltip=["date:T", "equity:Q"],
        )
        .properties(
            width="container",
            height=300,
            title=f"Stage 6 Event-Driven Equity: {sym} (Post 2 bps Fee + 1 bps Slip)",
        )
    )

    bt_section = mo.vstack([
        mo.md("### 📈 Stage 6: Event-Driven Backtest Simulation"),
        mo.hstack([
            mo.stat(label="Annualized Sharpe", value=f"{_sr:.2f}"),
            mo.stat(label="Cumulative Return", value=f"{_ret:+.1f}%"),
            mo.stat(label="Max Drawdown", value=f"{_dd:.1f}%"),
            mo.stat(label="Profit Factor", value=f"{_pf:.2f}"),
            mo.stat(label="Executions", value=f"{_trades} trades"),
        ]),
        mo.ui.altair_chart(_chart),
    ])
    return (bt_section,)


@app.cell
def display_backtest(bt_section):
    bt_section
    return


@app.cell
def synthesis_view(synth_metrics):
    _dsr_p = synth_metrics["dsr_probability"] * 100.0
    _haircut = synth_metrics["dsr_haircut_sharpe"]
    _obs_sr = synth_metrics["annualized_sharpe"]
    _n_trials = synth_metrics.get("n_trials", 50)

    synthesis_section = mo.vstack([
        mo.md("### 🛡️ Stage 7: Multiple-Testing Synthesis & Deflated Sharpe Ratio"),
        mo.callout(
            mo.md(f"""
            - **Observed Annualized Sharpe**: `{_obs_sr:.2f}`
            - **Historical Trials Documented**: `{_n_trials}`
            - **Bailey & López de Prado Haircut Sharpe**: `{_haircut:.2f}`
            - **Deflated Sharpe Ratio (DSR) Statistical Probability**: `{_dsr_p:.1f}%`
            - **Verdict**: {'✅ **Statistically Significant Edge**' if _dsr_p >= 95.0 else '⚠️ **Borderline / Requires Further Out-of-Sample Evaluation**'}
            """),
            kind="success" if _dsr_p >= 95.0 else "warn",
        ),
    ])
    return (synthesis_section,)


@app.cell
def display_synthesis(synthesis_section):
    synthesis_section
    return


if __name__ == "__main__":
    app.run()
