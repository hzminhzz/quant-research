# CLAUDE.md: Autonomous Agent Operational Guide

This document defines the essential operational directives, code invariants, and verification commands for Claude Code, Antigravity, and autonomous pair-programming agents contributing to this repository.

---

## 1. Project Overview & Target Modern Stack

This repository implements systematic quantitative alpha research, factor diagnostics, and event-driven backtesting following Stefan Jansen's *Machine Learning for Algorithmic Trading* (ML4T).
* **Data Processing**: Vectorized Polars (pure columnar transformations, zero Pandas/Numpy loops where possible).
* **Indicator Parity**: TA-Lib mathematical validation.
* **Interactive Research**: Marimo reactive notebooks (`.py` files structured as Directed Acyclic Graphs).
* **Quant Methodology**: `ml4t-engineer` (Stage 1), `ml4t-diagnostic` (Stage 2), `ml4t-backtest` (Stage 3).
* **Deprecated**: Zipline, Pyfolio, and Alphalens are deprecated. Do not introduce them.

---

## 2. Core Quantitative Invariants

Before starting crypto or index research, changing a strategy, or reviewing historical results, read [`docs/research_sessions.md`](docs/research_sessions.md). Define the economic hypothesis, mechanism, falsifier, and exact tradable instruments first. Choose labels and diagnostics for that thesis; neither triple-barrier labeling nor cross-sectional IC is universal. All new sessions are `EXPLORATORY`; retain the legacy `NOT_APPROVED` status and historical evidence.

1. **The 80/20 Implementation Rule**:
   Implement conceptual patterns using standard scientific tools (`polars`, `numpy`, `scipy`). Reserve `ml4t-*` packages for production pipeline integration.
2. **Zero Lookahead Bias & Data Leakage**:
   Use point-in-time data available at the decision timestamp and chronological walk-forward evaluation. Forward returns are target labels ($y$) only. Fit preprocessors on training splits; purge overlapping label/holding intervals and embargo where needed. Freeze the final test and selection rule before observing it; never tune on final-test results.
3. **Mandatory Multiple-Testing Haircuts**:
   Every evaluated parameter, feature, universe, label, cost, or execution variation counts as a trial, including failed attempts. Follow the session guide for preregistration and hashed evidence; preserve legacy ledgers such as `run_log/trials.jsonl`. Report DSR and Sharpe haircuts for multiple iterations, disclosing incomplete trial history and unreproducible adjustments. Historical review does not retroactively preregister trials.
4. **Market-Specific Friction Modeling**:
   Use actual venue/product fees, spreads, slippage, and impact, with crypto funding/borrow and index financing/rolls as applicable. Generic **2 bps commission** plus **1 bps slippage** is an exploratory placeholder. Neither generic fees nor metric thresholds approve deployment.

---

## 3. Marimo Reactive DAG Invariants

Marimo compiles pure-Python files into a reactive Directed Acyclic Graph (DAG):
1. **Global Variable Uniqueness**: A variable name can only be defined in a single cell. Duplicate global definitions break DAG execution.
2. **Cell-Private Scoping**: Variables local to a cell's intermediate computation must start with an underscore (`_var`).
3. **Payload Budget (< 10 MB)**: Marimo serializes cell outputs to browser DOM. Never pass raw high-frequency DataFrames (>1,000 bars) directly to `mo.ui.table()` or Altair charts. Downsample to daily intervals or window lookbacks.
4. **Pure Python Files**: All notebooks must be `.py` modules decorated with `@app.cell`. Traditional `.ipynb` files are strictly banned.

---

## 4. Operational Runbook

For documentation-only changes, review prose and links and run `git diff --check`. Apply the code and notebook checks below when those surfaces change; preserve unrelated edits and historical artifacts.

### Run Automated Tests
```bash
uv run --with polars,scipy,pytest python -m pytest tests/
```
*Requirement*: All unit and integration tests must pass with 0 errors and 0 warnings.

### Validate Marimo Reactive Notebooks
```bash
marimo check notebooks/quantified_strategies_engulfing.py
marimo check notebooks/template_strategy_study.py
```
*Requirement*: Must output 0 errors and 0 warnings.

### Format & Lint Code
```bash
ruff check src/ tests/
```

### Sync Remote Molab Container
```bash
bash /Users/minhvu/.opencode/skill/marimo-pair/scripts/execute-code.sh \
  --url https://sb-2c222524b512adcb.sb.molab.run/ \
  --token b3773ae143d6468af1ee4b2cedd08198a3b6634fb3d1d97bb25fc4dc5bb9c0ea \
  -c "python3 -m pytest tests && marimo check notebook.py"
```

---

## 5. Prohibited Anti-Patterns

* ❌ Do not calculate Sharpe ratios on trade-level returns multiplied by $\sqrt{252 \times N_{\text{trades}}}$. Always use continuous daily portfolio equity returns.
* ❌ Do not hardcode parameters in notebooks or scripts; use the applicable versioned configuration and session specification (`config/setup.yaml` is the existing default).
* ❌ Do not commit raw market data files or parquet caches to Git.
* ❌ Do not hide failed iterations; retain them in session evidence and preserve legacy ledgers so trial-count limitations remain visible.
