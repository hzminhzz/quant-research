# Quantitative Research Suite & 4-Index Meta-Labeling Engine

> **Validation status: `NOT_APPROVED`.** Historical backtest, whitepaper, notebook, and dashboard results are preserved research artifacts, not independently validated evidence of live readiness. See [`run_log/validation_status.json`](run_log/validation_status.json) and [`docs/audit/validation-remediation-status.md`](docs/audit/validation-remediation-status.md).

[![Tests](https://img.shields.io/badge/pytest-33%20passed-brightgreen)]()
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)]()
[![Backtest](https://img.shields.io/badge/backtest-10%20Years%20(2017--2026)-blue)]()
[![Framework](https://img.shields.io/badge/framework-Marimo%20Reactive%20DAG-orange)]()
[![Methodology](https://img.shields.io/badge/standards-ML4T%204--Stage%20Pipeline-purple)]()
[![Prop Firm](https://img.shields.io/badge/FTMO-79.1%25%20Funded%20Pass%20Rate-success)]()
[![License](https://img.shields.io/badge/license-MIT-green)]()

A systematic quantitative research, factor diagnostics, and event-driven backtesting platform. Built on pure-Python **Marimo reactive notebooks**, **Polars** vectorization, and the **Machine Learning for Algorithmic Trading (ML4T)** methodology inspired by Stefan Jansen and Marcos López de Prado.

For new crypto or index studies and historical reviews, follow the [**thesis-driven research session guide**](docs/research_sessions.md): define an economic hypothesis, mechanism, falsifier, and exact tradable instruments, then use point-in-time data, chronological evaluation, market-specific costs, and complete trial accounting. New sessions are `EXPLORATORY`; the session CLI records hashed evidence and does not execute models or backtests. The guide includes YAML declaration examples and concrete commands.

The BTC/ETH relative-value runner reads canonical hourly Binance perpetual OHLCV and funding from `ml4t-data/.data/store/`; it does not acquire or repair data. Missing hourly bars, missing funding cadence evidence, or settlement timestamps inconsistent with the stored per-event `funding_interval_hours` stop the run. Funding checks include one 8-hour context window on each side of the evaluation range; each result records the price manifest, consumed partition hashes, and frame fingerprints.

> 📄 **Core Research Publication**: Read the exhaustive mathematical whitepaper in [**`docs/research_whitepaper.md`**](docs/research_whitepaper.md) for full LaTeX derivations, failure post-mortems, 10-year calendar breakdown, and 2,000-trial Monte Carlo bootstrap distributions.

### Dataset Catalog & Authority Enforcement

Research datasets from `ml4t-data/.data/store/` are resolved authoritatively via `src.catalog` (`resolve_dataset` and `resolve_data_store`). The catalog enforces canonical dataset resolution by default, maps historical aliases (`DE30` -> `index_minute_DAX`, `JP225` -> `index_minute_NIKKEI225`, `NAS100` -> `index_minute_NAS100`, etc.), binds cryptographic identities (`catalog_identity`, `consumer_identity`), rejects unqualified or retired datasets, and fails closed when contract-level futures are requested against continuous products or index CFDs (`contract_level_futures=false`).

---

## 1. Flagship Research: The 4-Index Meta-Gated ORB Strategy

This repository preserves historical Opening Range Breakout and meta-labeling research across four global equity index price series. The vendor aliases below do not identify exact executable contracts; new studies must specify the venue and tradable product. The historical results do not establish robustness or live readiness:

- **Nikkei 225 (`JP225`)** — Tokyo Open (00:00 UTC)
- **Hang Seng Index (`HK33`)** — Hong Kong Open (01:00 UTC); the current LSE `HK33/HKD` series is an index feed, not a futures contract. The existing 5-minute file includes bars outside Hong Kong cash-session hours, and vendor session semantics remain unresolved.
- **DAX 40 (`DE30`)** — Frankfurt/London Open (07:00 UTC)
- **Nasdaq 100 (`NAS100`)** — New York Open (14:30 UTC)

```mermaid
flowchart TD
    subgraph S1["Phase 1: Microstructure Alpha (Toby Crabel & Macro Alignment)"]
        A["Prior Day Volatility State"] --> B["Toby Crabel NR7 Compression Gate"]
        C["Current Session Open (First 60m)"] --> D["Opening Range Expansion Gate (>= 1.2 * ATR20)"]
        E["Global Equity Risk Proxy"] --> F["US S&P 500 VWAP Filter (SPX Close > SPX VWAP)"]
        B & D & F --> G["Crabel Stretch Buffer: Price > OR_High + 0.15 * ATR20"]
    end

    subgraph S2["Phase 2: Institutional ML Meta-Labeling (Marcos López de Prado)"]
        G --> H["Snapshot 7D Stationary Feature Vector at Breakout Timestamp"]
        H --> I["LightGBM Meta-Classifier with Monotonic Domain Constraints"]
        I --> J["Combinatorial Purged Cross-Validation (CPCV: 6 groups, 15 folds, 5-bar embargo)"]
        J --> K["Sample Uniqueness Weighting to Neutralize Concurrency Correlation"]
        K --> L["Predicted Win Probability p_hat >= 0.50 Gate"]
    end

    subgraph S3["Phase 3: Multi-Day Execution & Risk Management"]
        L --> M["Forward Continuous Multi-Day Path Tracking"]
        M --> N{"Unrealized Profit >= +1.0R?"}
        N -->|Yes| O["Ratchet Stop to Breakeven (+0.1R)<br/>Convert Winner to Free Option"]
        O --> P["Activate 1.0R Trailing Stop"]
        P --> Q["Mandatory Friday 20:45 UTC Market Liquidation (Zero Weekend Risk)"]
    end
```

---

## 2. Empirical Performance & Validation Summary

The tables below retain historical reported figures and wording, including pass and compliance claims, without revalidation. They are not current approval evidence; consult the `NOT_APPROVED` record linked above for corrected findings and unresolved limitations.

### A. The Evolution from Naive Intraday to Multi-Day Meta-Gating

$$\delta = \max\left(\text{Opening Range Width}, \, 0.5 \times \text{ATR}_{20}\right)$$

| Strategy Milestone | Testing Horizon | Trades | Win Rate | Net PnL ($R$) | Ann. Sharpe | Multiple-Testing Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **1. Naive Intraday ORB (120m exit, 2.0R target)** | 2022–2026 | 951 | 41.2% | $-25.4R$ | $-0.34$ | Bleeds under friction |
| **2. Crabel Stretch + S&P 500 VWAP Gate** | 2022–2026 | 951 | 51.5% | $+26.8R$ | $+0.65$ | Haircut Sharpe: $-0.12$ (Noise) |
| **3. Multi-Day EOW + BE@1R (4.5-Yr Baseline)** | 2022–2026 | 839 | 52.2% | $+99.1R$ | $+1.11$ | Haircut Sharpe: $+0.48$ (Passed) |
| **4. 10-Year Multi-Day EOW (Unfiltered)** | **2017–2026** | **1,492** | **53.8%** | **$+186.5R$** | **$+1.16$** | Haircut Sharpe: $+0.39$ (DSR: 89.8%) |
| **5. 10-Year Multi-Day EOW + Meta-Gated ($p \ge 0.50$)** | **2017–2026** | **997** | **56.3%** | **$+193.4R$** | **$+1.47$** | **DSR: 99.0% (10/10 Profitable Years)** |

---

### B. Prop Firm Capital Stress Test (FTMO 2-Step Challenge)

Evaluated via **2,000-trial stationary block-bootstrap Monte Carlo simulation** across the 10-year trade distribution against FTMO's official evaluation barriers (+10% Step 1, +5% Step 2, -5% Daily Limit, -10% Max Drawdown):

| Evaluation Metric | Option A: 10-Year Multi-Day EOW<br>*(Unfiltered Heuristic)* | Option B: 10-Year Multi-Day EOW + Meta-Gated<br>*(p ≥ 0.50, Flat 1.0% Risk)* | Edge Delivered by Machine Learning |
| :--- | :---: | :---: | :--- |
| **Step 1 Pass Rate (+10%)** | 60.4% | **82.7%** | **+22.3% higher pass rate** |
| **Step 2 Conditional Rate (+5%)** | 97.6% | **95.7%** | High verification consistency |
| **Complete 2-Step Funded Pass Rate** | 59.0% | **79.1%** | **Nearly 8 in 10 accounts get funded** |
| **Max Drawdown Breach Risk (-10%)** | **38.7%** | **15.9%** | **Breach risk cut in half (-59% relative)** |
| **Daily Loss Limit Breach (-5%)** | **0.0% (Zero)** | **0.0% (Zero)** | Guaranteed circuit-breaker compliance |
| **Median Days to Complete** | 56 trading days | **50 trading days** | Faster path to active allocation |
| **Expected Funded Payout** | $6,900 | **$9,332** | **+$2,432 (+35.2%) higher expected cash flow** |
| **Expected ROI on $540 Fee** | +1,177.8% | **+1,628.2%** | Superior capital efficiency |

---

## 3. Repository Architecture & Directory Contracts

```text
.
├── config/
│   └── setup.yaml              # Single Source of Truth: universe, dates, costs, quality gates
├── data/                       # Tiered data storage (read/write access controlled)
│   ├── raw/                    # Read-only vendor tick/bar feeds (.gitkeep)
│   ├── processed/              # Canonical Parquet datasets (JP225, HK33, DE30, NAS100, SPX500)
│   ├── features/               # Versioned factor matrices (.gitkeep)
│   └── labels/                 # Path-dependent target labels (.gitkeep)
├── docs/                       # Formal research publications
│   └── research_whitepaper.md  # Comprehensive Quantitative Research Whitepaper
├── notebooks/                  # Pure-Python Marimo reactive notebooks (.py)
│   ├── 04_opening_candle_breakout.py  # Interactive ML Meta-Labeling & FTMO Dashboard
│   ├── 02_breakout_factory.py         # Breakout Strategy Factory
│   └── quantified_strategies_engulfing.py # Multi-asset candlestick benchmark
├── src/                        # Modular, reusable quantitative domain logic
│   ├── __init__.py             # Unified package exports
│   ├── features.py             # Vectorized Polars indicators (Garman-Klass, NR7, RVOL)
│   ├── labeling.py             # Multi-Day EOW Triple Barrier & Sample Uniqueness Weighting
│   ├── models.py               # Calibrated LightGBM with Monotonic Constraints & CPCV
│   ├── ftmo_simulator.py       # 2-Step Challenge Monte Carlo Simulator & Kelly Sizing
│   ├── patterns.py             # Candlestick pattern recognition with TA-Lib parity
│   └── backtest.py             # Event-driven backtesting engine with realistic friction
├── tests/                      # Automated unit, contract, and parity test suites
│   ├── test_meta_labeling.py   # CPCV, sample uniqueness, and multi-day EOW tests
│   ├── test_ftmo_simulator.py  # FTMO challenge rules & Monte Carlo bootstrap tests
│   ├── test_features_parity.py # Zero-lookahead guarantees and TA-Lib numerical parity
│   └── test_factory.py         # Strategy Factory verification tests
├── pyproject.toml              # Dependencies, Marimo runtime config, and pytest settings
└── README.md                   # Repository landing portal & research guide
```

---

## 4. Historical Quantitative Quality Gates

The following table preserves historical thresholds and reported results, not universal requirements for new research. Thesis-specific criteria replace blanket cross-sectional IC or labeling requirements. Generic fee assumptions and passing metric thresholds do not approve deployment or override `NOT_APPROVED`.

| Quality Gate | Metric | Acceptance Threshold | Result |
| :--- | :--- | :--- | :---: |
| **Predictive Power** | Spearman Rank IC | $\ge 0.02$ with $p < 0.05$ | **$+0.228$ ($p < 10^{-15}$)** |
| **Multiple Testing Bias** | Deflated Sharpe Ratio (DSR) | $\ge 0.80$ across all 42 trials | **$99.0\%$ ($0.9903$)** |
| **Sharpe Haircut** | Bailey & López de Prado Haircut | $> 0.0$ post selection bound penalty | **$+0.69$ ($1.47 - 0.77$)** |
| **Temporal Integrity** | Combinatorial CV Embargo | Zero overlap leakage across folds | **5-bar embargo enforced** |
| **Capital Survivability** | FTMO Max Drawdown Breach | $< 30\%$ on 2,000 Monte Carlo paths | **$15.9\%$ (Passed)** |


---

## 5. Quickstart & Reproduction Guide

### 1. Environment Installation
```bash
# Clone the repository
git clone https://github.com/hzminhzz/quant-research.git
cd quant-research

# Install dependencies via uv
uv sync
```

### 2. Execute Automated Verification Suites
```bash
# Run all 33 unit and contract tests
uv run pytest
```

### 3. Launch Interactive Marimo Dashboard
```bash
# Launch the reactive Marimo research application
uv run marimo edit notebooks/04_opening_candle_breakout.py
```

---

## 6. Citation & Reference Standards

If you build upon this architecture or reference our findings in your own research, please cite:

```bibtex
@article{quant_research_orb_2026,
  title={Institutional Opening Range Breakout Strategy: From Naive Retail Heuristic to Two-Stage Machine Learning Meta-Labeling and Multi-Day Execution},
  author={Quantitative Research and Engineering Team},
  journal={Quantitative Research Suite Working Paper Series},
  year={2026},
  url={https://github.com/hzminhzz/quant-research/blob/main/docs/research_whitepaper.md}
}
```
