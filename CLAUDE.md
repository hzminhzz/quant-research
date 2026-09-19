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

1. **The 80/20 Implementation Rule**:
   Implement conceptual patterns using standard scientific tools (`polars`, `numpy`, `scipy`). Reserve `ml4t-*` packages for production pipeline integration.
2. **Zero Lookahead Bias & Data Leakage**:
   All features must be backward-looking. Forward returns are target labels ($y$) only. Preprocessors and normalizers must be fit solely on in-sample training splits.
3. **Mandatory Multiple-Testing Haircuts**:
   Every tuned parameter, indicator variation, or universe filter counts as an empirical trial. Report the **Deflated Sharpe Ratio (DSR)** and **Bailey & López de Prado Haircut** whenever evaluating multiple iterations. Record every trial in `run_log/trials.jsonl`.
4. **Institutional Friction Modeling**:
   Always include transaction costs. Backtests must default to at least **2 bps commission** and **1 bps slippage** per execution leg.

---

## 3. Marimo Reactive DAG Invariants

Marimo compiles pure-Python files into a reactive Directed Acyclic Graph (DAG):
1. **Global Variable Uniqueness**: A variable name can only be defined in a single cell. Duplicate global definitions break DAG execution.
2. **Cell-Private Scoping**: Variables local to a cell's intermediate computation must start with an underscore (`_var`).
3. **Payload Budget (< 10 MB)**: Marimo serializes cell outputs to browser DOM. Never pass raw high-frequency DataFrames (>1,000 bars) directly to `mo.ui.table()` or Altair charts. Downsample to daily intervals or window lookbacks.
4. **Pure Python Files**: All notebooks must be `.py` modules decorated with `@app.cell`. Traditional `.ipynb` files are strictly banned.

---

## 4. Operational Runbook

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
* ❌ Do not hardcode parameters in notebooks or scripts; read from `config/setup.yaml`.
* ❌ Do not commit raw market data files or parquet caches to Git.
* ❌ Do not hide failed parameter iterations; append them to `run_log/trials.jsonl` to ensure statistically honest DSR reporting.
